/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:unsharp-mask
 * menu       Unsharp Mask / Smart Sharpen
 * purpose    Photoshop「锐化 → USM 锐化 / 智能锐化」的等价物：用模糊版做参考，
 *           把原图与模糊版的差值按百分比加回去。
 *           Unsharp masking with the halo suppression Photoshop's Smart Sharpen
 *           is really after.
 * input      任意格式，内部一律转 R'G'B'A float 计算；alpha 原样透传。
 * algorithm  1) 高斯模糊：半径小（σ ≤ 4）时用真高斯核（可分离卷积），半径大时
 *              退化为三次盒式模糊串联 —— 三次盒式在 σ ≥ 4 时与真高斯的分歧
 *              已经小于 1/255，而代价与半径无关（O(n) 而不是 O(n·σ)）。
 *            2) 差值 = 原值 − 模糊值；|差值| ≤ 阈值 的像素判为平坦区，原样保留，
 *              这是 PS 的「阈值」参数（避免放大胶片颗粒与噪点）。
 *            3) 锐化 = 原值 + 数量 × 差值。
 *            4) 光晕抑制：把锐化结果夹到原图 3×3 邻域的 [min, max] 之内。
 *              这是关键的一步 —— 普通 USM 在硬边两侧各留一条白边/黑边，
 *              夹到邻域极值之后白边就没了，代价是高光的微弱溢出会被压掉，
 *              所以做成 0–100% 可调（PS 的「智能锐化 → 移去 → 镜头模糊」近亲）。
 * precision 统一在 float32 里算，写回时由 GEGL 转回缓冲本身的格式。
 *           8/16 位缓冲结果再夹到 [0,1]；浮点缓冲不夹上界，保留 HDR 高光。
 * type       GeglOperationAreaFilter（邻域滤波，向外扩 ceil(3σ)+1 像素）
 * used-by    GIMP 里作为普通 GEGL 滤镜（滤镜 → 增强 → 锐化）调用
 * reference  Adobe Photoshop「滤镜 → 锐化 → USM 锐化 / 智能锐化」
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_double (radius, _("Radius"), 2.0)
    description (_("Blur radius the sharpening is measured against. Small values "
                   "sharpen fine texture, large values build local contrast "
                   "(the so-called clarity look)."))
    value_range (0.1, 100.0)
    ui_range (0.1, 20.0)
    ui_gamma (2.0)

property_double (amount, _("Amount"), 100.0)
    description (_("How much of the difference is added back, in percent. "
                   "Photoshop's Amount slider, 1–500%."))
    value_range (0.0, 500.0)
    ui_range (0.0, 300.0)

property_int (threshold, _("Threshold"), 0)
    description (_("Differences below this many levels (0–255) count as flat "
                   "area and are left alone, so grain and sensor noise are not "
                   "amplified. Photoshop's Threshold slider."))
    value_range (0, 255)
    ui_range (0, 100)

property_double (fringe, _("Halo suppression"), 100.0)
    description (_("Clamp the sharpened value to the 3×3 neighbourhood of the "
                   "original, in percent. At 100 the white and dark fringes "
                   "along hard edges disappear; at 0 this is a plain unsharp "
                   "mask."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

#else

#define GEGL_OP_AREA_FILTER
#define GEGL_OP_NAME     lb_unsharp_mask
#define GEGL_OP_C_SOURCE unsharp-mask.c
#include "gegl-op.h"

#define BAND_ROWS 128

/* ---- 盒式模糊：滑动窗口，代价与半径无关 -------------------------------- */

static void
box_h (const gfloat *src, gfloat *dst, gint pw, gint ph, gint r)
{
  gint y, x;
  gfloat inv = 1.0f / (gfloat) (2 * r + 1);

  for (y = 0; y < ph; y++)
    {
      const gfloat *s = src + (gsize) y * pw;
      gfloat       *d = dst + (gsize) y * pw;
      gdouble       sum = 0.0;

      /* 前 r 个用第 0 列补齐（复制边缘） */
      for (x = -r; x <= r; x++)
        sum += s[CLAMP (x, 0, pw - 1)];

      for (x = 0; x < pw; x++)
        {
          d[x] = (gfloat) (sum * inv);
          sum += s[MIN (x + r + 1, pw - 1)] - s[MAX (x - r, 0)];
        }
    }
}

static void
box_v (const gfloat *src, gfloat *dst, gint pw, gint ph, gint r)
{
  gint x, y;
  gfloat inv = 1.0f / (gfloat) (2 * r + 1);

  for (x = 0; x < pw; x++)
    {
      gdouble sum = 0.0;
      for (y = -r; y <= r; y++)
        sum += src[(gsize) CLAMP (y, 0, ph - 1) * pw + x];

      for (y = 0; y < ph; y++)
        {
          dst[(gsize) y * pw + x] = (gfloat) (sum * inv);
          sum += src[(gsize) MIN (y + r + 1, ph - 1) * pw + x]
               - src[(gsize) MAX (y - r, 0) * pw + x];
        }
    }
}

/* ---- 真高斯核：σ 小时用它，边缘更准 ------------------------------------ */

static gfloat *
gauss_kernel (gfloat sigma, gint *radius)
{
  gint    r = MAX (1, (gint) ceil (3.0 * sigma));
  gfloat *k = g_new (gfloat, 2 * r + 1);
  gdouble sum = 0.0;
  gint    i;

  for (i = -r; i <= r; i++)
    {
      gdouble v = exp (-(gdouble) i * i / (2.0 * sigma * sigma));
      k[i + r] = (gfloat) v;
      sum += v;
    }
  for (i = 0; i < 2 * r + 1; i++)
    k[i] = (gfloat) (k[i] / sum);

  *radius = r;
  return k;
}

static void
conv_h (const gfloat *src, gfloat *dst, gint pw, gint ph,
        const gfloat *k, gint kr)
{
  gint y, x, i;

  for (y = 0; y < ph; y++)
    {
      const gfloat *s = src + (gsize) y * pw;
      gfloat       *d = dst + (gsize) y * pw;
      for (x = 0; x < pw; x++)
        {
          gdouble acc = 0.0;
          for (i = -kr; i <= kr; i++)
            acc += s[CLAMP (x + i, 0, pw - 1)] * k[i + kr];
          d[x] = (gfloat) acc;
        }
    }
}

static void
conv_v (const gfloat *src, gfloat *dst, gint pw, gint ph,
        const gfloat *k, gint kr)
{
  gint x, y, i;

  for (y = 0; y < ph; y++)
    {
      gfloat *d = dst + (gsize) y * pw;
      for (x = 0; x < pw; x++)
        {
          gdouble acc = 0.0;
          for (i = -kr; i <= kr; i++)
            acc += src[(gsize) CLAMP (y + i, 0, ph - 1) * pw + x] * k[i + kr];
          d[x] = (gfloat) acc;
        }
    }
}

/* 模糊一整张平面。scratch 至少两块，用于盒式串联的乒乓。 */
static void
blur_plane (const gfloat *src, gfloat *dst, gfloat *s1, gfloat *s2,
            gint pw, gint ph, gfloat sigma)
{
  if (sigma <= 0.05f)
    {
      memcpy (dst, src, sizeof (gfloat) * (gsize) pw * ph);
      return;
    }

  if (sigma <= 4.0f)
    {
      gint    kr;
      gfloat *k = gauss_kernel (sigma, &kr);
      conv_h (src, s1, pw, ph, k, kr);
      conv_v (s1, dst, pw, ph, k, kr);
      g_free (k);
      return;
    }

  /* 三次盒式 ≈ 高斯：(2r+1)² = 4σ²+1 */
  {
    gint r = MAX (1, (gint) lround ((sqrt (4.0 * sigma * sigma + 1.0) - 1.0) / 2.0));

    box_h (src, s1, pw, ph, r);
    box_h (s1, s2, pw, ph, r);
    box_h (s2, s1, pw, ph, r);
    box_v (s1, s2, pw, ph, r);
    box_v (s2, s1, pw, ph, r);
    box_v (s1, dst, pw, ph, r);
  }
}

static void
prepare (GeglOperation *operation)
{
  GeglProperties          *o  = GEGL_PROPERTIES (operation);
  GeglOperationAreaFilter *af = GEGL_OPERATION_AREA_FILTER (operation);
  gdouble                  sigma = MAX (o->radius, 0.1);
  gint                     pad;

  /* 往外要多少：模糊核半宽（σ≤4 时 3σ，否则盒式半径）+ 1 圈给 3×3 夹取 */
  pad = (sigma <= 4.0)
          ? (gint) ceil (3.0 * sigma) + 1
          : (gint) lround ((sqrt (4.0 * sigma * sigma + 1.0) - 1.0) / 2.0) + 1;

  af->left = af->right = af->top = af->bottom = pad;

  gegl_operation_set_format (operation, "input", babl_format ("R'G'B'A float"));
  gegl_operation_set_format (operation, "output", babl_format ("R'G'B'A float"));
}

/* 邻域算子的输出尺寸必须与输入一致：area filter 的默认 bbox 会按 pad 外扩，
 * 滤镜不该把画布撑大（GEGL 命令行下能直接看到 8×8 变成 22×22）。
 * The output must stay the size of the input; the default area-filter bbox
 * grows by the padding, which no filter should do. */
static GeglRectangle
get_bounding_box (GeglOperation *operation)
{
  GeglRectangle *in = gegl_operation_source_get_bounding_box (operation, "input");
  if (in)
    return *in;
  return *GEGL_RECTANGLE (0, 0, 0, 0);
}

static gboolean
process (GeglOperation       *operation,
         GeglBuffer          *input,
         GeglBuffer          *output,
         const GeglRectangle *result,
         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (operation);
  const Babl     *fmt = babl_format ("R'G'B'A float");
  const Babl     *src_fmt = gegl_operation_get_source_format (operation, "input");
  const gchar    *src_name = src_fmt ? babl_get_name (src_fmt) : "";
  gboolean        clamp_hi = (g_strrstr (src_name, "u8") != NULL ||
                              g_strrstr (src_name, "u16") != NULL);
  gfloat          sigma = (gfloat) MAX (o->radius, 0.1);
  gfloat          amount = (gfloat) (o->amount / 100.0);
  gfloat          thr = (gfloat) (o->threshold / 255.0);
  gfloat          fringe = (gfloat) (o->fringe / 100.0);
  gint            pad = MAX (1, (gint) ceil (3.0 * sigma));
  const GeglRectangle *src_bb;
  GeglRectangle   bb;
  gint            yb;

  src_bb = gegl_operation_source_get_bounding_box (operation, "input");
  bb = src_bb ? *src_bb : *gegl_buffer_get_extent (input);

  for (yb = result->y; yb < result->y + result->height; yb += BAND_ROWS)
    {
      gint          bh = MIN (BAND_ROWS, result->y + result->height - yb);
      gint          w = result->width;
      gint          py0 = MAX (bb.y, yb - pad);
      gint          py1 = MIN (bb.y + bb.height, yb + bh + pad);
      gint          px0 = MAX (bb.x, result->x - pad);
      gint          px1 = MIN (bb.x + bb.width, result->x + result->width + pad);
      gint          ph = py1 - py0, pw = px1 - px0;
      gint          ox = result->x - px0, oy = yb - py0;
      GeglRectangle prect = { px0, py0, pw, ph };
      GeglRectangle outr  = { result->x, yb, w, bh };
      gfloat       *in, *res, *plane, *blur, *s1, *s2;
      gint          c, y, x;

      if (pw <= 0 || ph <= 0)
        continue;

      in    = g_new (gfloat, (gsize) pw * ph * 4);
      res   = g_new (gfloat, (gsize) w * bh * 4);
      plane = g_new (gfloat, (gsize) pw * ph);
      blur  = g_new (gfloat, (gsize) pw * ph);
      s1    = g_new (gfloat, (gsize) pw * ph);
      s2    = g_new (gfloat, (gsize) pw * ph);

      gegl_buffer_get (input, &prect, 1.0, fmt, in,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      /* alpha 与未参与运算的通道先原样透传 */
      for (y = 0; y < bh; y++)
        memcpy (res + (gsize) y * w * 4,
                in + (gsize) ((oy + y) * pw + ox) * 4,
                (gsize) w * 4 * sizeof (gfloat));

      for (c = 0; c < 3; c++)
        {
          for (y = 0; y < ph; y++)
            for (x = 0; x < pw; x++)
              plane[(gsize) y * pw + x] = in[(gsize) ((gsize) y * pw + x) * 4 + c];

          blur_plane (plane, blur, s1, s2, pw, ph, sigma);

          for (y = 0; y < bh; y++)
            {
              for (x = 0; x < w; x++)
                {
                  gint    i = (oy + y) * pw + (ox + x);
                  gfloat  v = plane[i];
                  gfloat  d = v - blur[i];
                  gfloat  out;

                  if (fabsf (d) <= thr)
                    {
                      res[(gsize) ((gsize) y * w + x) * 4 + c] = v;
                      continue;
                    }

                  out = v + amount * d;

                  if (fringe > 0.0f)
                    {
                      /* 3×3 原图极值，边界复制 */
                      gfloat lo = v, hi = v;
                      gint   dy, dx;
                      for (dy = -1; dy <= 1; dy++)
                        for (dx = -1; dx <= 1; dx++)
                          {
                            gfloat q = plane[(gsize) CLAMP (oy + y + dy, 0, ph - 1) * pw
                                             + CLAMP (ox + x + dx, 0, pw - 1)];
                            lo = MIN (lo, q);
                            hi = MAX (hi, q);
                          }
                      if (out > hi) out = hi;
                      if (out < lo) out = lo;
                      /* fringe 是混合系数：0 时不夹，100 时完全夹住 */
                      if (fringe < 1.0f)
                        out = v + amount * d
                              + fringe * (out - (v + amount * d));
                    }

                  if (out < 0.0f) out = 0.0f;
                  if (clamp_hi && out > 1.0f) out = 1.0f;

                  res[(gsize) ((gsize) y * w + x) * 4 + c] = out;
                }
            }
        }

      gegl_buffer_set (output, &outr, 0, fmt, res, GEGL_AUTO_ROWSTRIDE);

      g_free (in);
      g_free (res);
      g_free (plane);
      g_free (blur);
      g_free (s1);
      g_free (s2);
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  oclass->prepare          = prepare;
  oclass->get_bounding_box = get_bounding_box;
  fclass->process          = process;

  gegl_operation_class_set_keys (oclass,
    "name",        "lb:unsharp-mask",
    "title",       _("Unsharp Mask"),
    "description", _("Sharpens against a blurred copy with the amount, radius "
                     "and threshold of Photoshop's Unsharp Mask, plus a halo "
                     "suppression stage that clamps the result to the 3×3 "
                     "neighbourhood so hard edges do not grow white fringes."),
    "categories",  "generic",
    "gimp:menu-path",  "<Image>/SuperMrWang/Sharpen",
    "gimp:menu-label", _("Unsharp Mask"),
    NULL);
}

#endif
