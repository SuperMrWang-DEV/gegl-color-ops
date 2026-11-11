/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:vibrance-ps
 * menu       Vibrance (Photoshop)
 * purpose    按 Photoshop「自然饱和度」的实测响应改饱和度：低饱和吃得饱、高饱
 *            和主动收手、红带（肤色）额外保护、浅色少给一点，色相与明度不动
 *            Reproduce Photoshop's Vibrance: muted colours gain the most, vivid
 *            ones are held back, the red band (skin) is protected further and
 *            light colours receive a little less. Hue and lightness stay put.
 * algorithm  HSV 下按 S 取增量：ΔS = A(v)·S^p(v)·(1-S)^q(v)，再乘红带系数
 *            r(H,S,v) 与亮度系数 c(L)；三个系数都随 v 查表。负方向是另一套
 *            实测机制（S' 与 V'/V 直接查表），不是正向的镜像。RGB 重建保持
 *            max 不变、其余通道按 S'/S 缩放 —— 数学上不会越界，无需裁剪
 *            In HSV, ΔS = A(v)·S^p(v)·(1-S)^q(v), scaled by a red-band
 *            factor r(H,S,v) and a lightness factor c(L); all three are
 *            tabulated against v. The negative range uses a separate measured
 *            mechanism (S' and V'/V tabulated), it is not a mirror of the
 *            positive one. RGB is rebuilt by keeping max and scaling the other
 *            channels by S'/S, which provably stays inside gamut — no clipping.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * source     参数表由 tools/gen_vibrance_tables.py 从 vibrance-cal 的 16 位 /
 *            步长 5 标定数据导出，拟合残差 0.41 pp（v=+100）、0.02 pp（v=+5）
 *            The tables come from the 16-bit / step-5 calibration in
 *            vibrance-cal; fit residual 0.41 pp at v=+100, 0.02 pp at v=+5.
 * reference  Adobe Photoshop 26.10 自然饱和度（实测逆向，非经验近似）
 *            Adobe Photoshop 26.10 Vibrance, reverse-engineered by measurement
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_double (vibrance, _("Vibrance"), 0.0)
    description (_("Photoshop's Vibrance, -100 to +100. Low-saturation colours gain "
                   "the most, already-vivid ones are held back, and the red band "
                   "carries extra protection"))
    value_range (-100.0, 100.0)
    ui_range    (-100.0, 100.0)
    ui_steps    (1.0, 5.0)

property_boolean (protect_reds, _("Red-band protection"), TRUE)
    description (_("The measured hold-back on reds/skin (hue within 40° of red). "
                   "Turn off to boost every hue identically"))

property_boolean (compensate_lightness, _("Lightness compensation"), TRUE)
    description (_("The measured rule that light colours receive a smaller boost "
                   "(0.72x at HSL lightness 80, 1.39x at 20)"))

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_vibrance_ps
#define GEGL_OP_C_SOURCE vibrance-ps.c

#include "gegl-op.h"
#include "vibrance-tables.h"

/* 逐像素参数：v 对整张图是常量，所以每条「随 v 变化」的曲线都在 prepare()
 * 里先按当前 v 折叠成一条（11 个点），process() 只剩一维插值。
 * Per-pixel parameters. v is constant for the whole image, so every curve that
 * varies with v is collapsed to a single row (11 points) in prepare(); the
 * process loop is left with one-dimensional lookups only. */
typedef struct
{
  gboolean identity;      /* v≈0，直接拷贝 / nothing to do */
  gboolean positive;
  gboolean use_red;
  gboolean use_lum;
  gfloat   A;             /* ΔS 的幅度 / amplitude */
  gfloat   pexp;
  gfloat   qexp;
  gfloat   red[VIB_COLS]; /* 红带系数（已折叠）/ red factor, collapsed */
  gfloat   neg_s1[VIB_COLS];
  gfloat   neg_v[VIB_COLS];
} VibParams;

static inline gfloat
lerp (gfloat a, gfloat b, gfloat t)
{
  return a + (b - a) * t;
}

/* 在公共 S 网格上取一条曲线（s 用百分数，0-100）。
 * Sample one curve on the shared S grid; s is in percent. */
static inline gfloat
curve_at (const gfloat *row,
          gfloat        s)
{
  gint i;

  if (s <= vib_S[0])
    return row[0];

  for (i = 1; i < VIB_COLS; i++)
    {
      if (s <= vib_S[i])
        return lerp (row[i - 1], row[i],
                     (s - vib_S[i - 1]) / (vib_S[i] - vib_S[i - 1]));
    }

  return row[VIB_COLS - 1];
}

/* 亮度系数 c(L)，L 为 HSL 明度百分数。
 * Lightness factor c(L) with L as HSL lightness in percent. */
static inline gfloat
lum_at (gfloat L)
{
  gint i;

  if (L <= vib_lumL[0])
    return vib_lumC[0];

  for (i = 1; i < VIB_LUM; i++)
    {
      if (L <= vib_lumL[i])
        return lerp (vib_lumC[i - 1], vib_lumC[i],
                     (L - vib_lumL[i - 1]) / (vib_lumL[i] - vib_lumL[i - 1]));
    }

  return vib_lumC[VIB_LUM - 1];
}

/* 把 20 行（v = 5…100，步长 5）的红带表按当前 v 折叠成一行。
 * Collapse the 20-row red table (v = 5…100 step 5) onto the current v. */
static void
collapse_red (gfloat  v,
              gfloat *out)
{
  gint   i, c;
  gfloat t;

  if (v <= 5.0f)
    {
      memcpy (out, vib_red[0], sizeof (gfloat) * VIB_COLS);
      return;
    }

  if (v >= 100.0f)
    {
      memcpy (out, vib_red[VIB_NEG_LEVELS - 1], sizeof (gfloat) * VIB_COLS);
      return;
    }

  i = (gint) (v / 5.0f);                 /* 5 ≤ v < 100 → i = 1…19 */
  t = (v - 5.0f * (gfloat) i) / 5.0f;

  for (c = 0; c < VIB_COLS; c++)
    out[c] = lerp (vib_red[i - 1][c], vib_red[i][c], t);
}

/* 同理折叠负向的两张表（行 = v = -100…-5）。
 * Same for the two negative-side tables (rows v = -100…-5). */
static void
collapse_neg (gfloat  v,
              gfloat *s1,
              gfloat *vv)
{
  gint   j, c;
  gfloat t;

  if (v <= -100.0f)
    {
      memcpy (s1, vib_neg_S1[0], sizeof (gfloat) * VIB_COLS);
      memcpy (vv, vib_neg_V[0], sizeof (gfloat) * VIB_COLS);
      return;
    }

  if (v >= -5.0f)
    {
      memcpy (s1, vib_neg_S1[VIB_NEG_LEVELS - 1], sizeof (gfloat) * VIB_COLS);
      memcpy (vv, vib_neg_V[VIB_NEG_LEVELS - 1], sizeof (gfloat) * VIB_COLS);
      return;
    }

  j = (gint) ((v + 100.0f) / 5.0f);      /* -100 ≤ v < -5 → j = 0…18 */
  t = (v + 100.0f - 5.0f * (gfloat) j) / 5.0f;

  for (c = 0; c < VIB_COLS; c++)
    {
      s1[c] = lerp (vib_neg_S1[j][c], vib_neg_S1[j + 1][c], t);
      vv[c] = lerp (vib_neg_V[j][c], vib_neg_V[j + 1][c], t);
    }
}

static void
prepare (GeglOperation *operation)
{
  GeglProperties *o = GEGL_PROPERTIES (operation);
  const Babl     *space = gegl_operation_get_source_space (operation, "input");
  VibParams      *p = (VibParams *) o->user_data;
  gfloat          v = (gfloat) o->vibrance;

  /* 感知（非线性）RGB，与 GIMP 其余色彩工具一致：这套标定是在 sRGB 编码值
   * 上做的，放进线性光会整体跑偏
   * Perceptual (non-linear) RGB, like GIMP's other colour tools: the
   * calibration was done on sRGB-encoded values and would drift in linear
   * light. */
  if (! space)
    space = babl_space ("sRGB");

  if (! p)
    {
      p = g_slice_new0 (VibParams);
      o->user_data = p;
    }

  p->identity = (fabsf (v) < 1e-3f);
  p->positive = (v > 0.0f);
  p->use_red  = o->protect_reds;
  p->use_lum  = o->compensate_lightness;

  if (! p->identity)
    {
      if (p->positive)
        {
          if (v >= 100.0f)
            {
              p->A    = vib_A[VIB_LEVELS - 1];
              p->pexp = vib_p[VIB_LEVELS - 1];
              p->qexp = vib_q[VIB_LEVELS - 1];
            }
          else
            {
              gint   i = (gint) (v / 5.0f);        /* 0 ≤ v < 100 → i = 0…19 */
              gfloat t = (v - 5.0f * (gfloat) i) / 5.0f;

              p->A    = lerp (vib_A[i], vib_A[i + 1], t);
              p->pexp = lerp (vib_p[i], vib_p[i + 1], t);
              p->qexp = lerp (vib_q[i], vib_q[i + 1], t);
            }

          if (p->use_red)
            collapse_red (v, p->red);
        }
      else
        {
          collapse_neg (v, p->neg_s1, p->neg_v);
          p->use_lum = FALSE;                /* 负向没有亮度项 / not measured */
        }
    }

  gegl_operation_set_format (operation, "input",
                             babl_format_with_space ("R~G~B~A float", space));
  gegl_operation_set_format (operation, "output",
                             babl_format_with_space ("R~G~B~A float", space));
}

static void
finalize (GObject *object)
{
  GeglProperties *o = GEGL_PROPERTIES (object);

  if (o->user_data)
    {
      g_slice_free (VibParams, o->user_data);
      o->user_data = NULL;
    }

  G_OBJECT_CLASS (gegl_op_parent_class)->finalize (object);
}

static inline void
process_pixel (const VibParams *p,
               const gfloat    *src,
               gfloat          *dst)
{
  gfloat r = src[0], g = src[1], b = src[2];
  gfloat mx, mn, chroma, s, s1, k, f, base, gain;

  mx = MAX (r, MAX (g, b));
  mn = MIN (r, MIN (g, b));

  /* 全黑与中性灰没有饱和度可调；也顺手挡掉除零
   * Pure black and neutral greys have no saturation to adjust, and this
   * also keeps the division below safe. */
  if (mx <= 0.0f || mx - mn < 1e-6f)
    {
      dst[0] = r;
      dst[1] = g;
      dst[2] = b;
      return;
    }

  chroma = mx - mn;
  s = chroma / mx;
  k = 1.0f;

  if (p->positive)
    {
      gfloat fac = 1.0f;

      if (p->use_red)
        {
          /* 只需要「离红色的角距」：实测 H 60°…300° 的响应与中性色逐位相同，
           * 保护只存在于红带 330°…40°，26°…40° 之间线性过渡出去
           * Only the angular distance to red matters: measured response at
           * H 60°…300° is bit-identical to neutral hues, the hold-back lives
           * in the red band 330°…40° and fades out over 28°…40°. */
          gfloat h, d;

          if (mx == r)
            h = 60.0f * (g - b) / chroma;                 /* -60…60 */
          else if (mx == g)
            h = 60.0f * (b - r) / chroma + 120.0f;        /*  60…180 */
          else
            h = 60.0f * (r - g) / chroma + 240.0f;        /* 180…300 */

          if (h < 0.0f)
            d = -h;
          else
            d = (h > 180.0f) ? 360.0f - h : h;

          if (d < 40.0f)
            {
              gfloat rr = curve_at (p->red, s * 100.0f);
              gfloat edge = (d <= 28.0f) ? 1.0f : (40.0f - d) / 12.0f;

              fac = 1.0f - (1.0f - rr) * edge;
            }
        }

      if (p->use_lum)
        fac *= lum_at ((mx + mn) * 50.0f);      /* (mx+mn)/2 换算成百分数 */

      s1 = s + p->A * powf (s, p->pexp) * powf (1.0f - s, p->qexp) * fac;
      if (s1 > 1.0f)
        s1 = 1.0f;
      else if (s1 < 0.0f)
        s1 = 0.0f;
    }
  else
    {
      s1 = curve_at (p->neg_s1, s * 100.0f);
      k  = curve_at (p->neg_v,  s * 100.0f);
    }

  f = s1 / s;

  /* 重建：max 变成 mx·k（负向才 <1），其余通道先随整体缩放，再以新 max 为
   * 轴按 S'/S 展开。等价于 out = mx' - (mx' - c·k)·f
   * Rebuild: max becomes mx·k (only below 1 when v < 0), the channels scale
   * with it, then spread away from the new max by S'/S. */
  mx *= k;
  base = mx * (1.0f - f);
  gain = k * f;

  dst[0] = base + r * gain;
  dst[1] = base + g * gain;
  dst[2] = base + b * gain;

  if (dst[0] < 0.0f) dst[0] = 0.0f;
  if (dst[1] < 0.0f) dst[1] = 0.0f;
  if (dst[2] < 0.0f) dst[2] = 0.0f;
}

static gboolean
process (GeglOperation       *operation,
         void                *in_buf,
         void                *out_buf,
         glong                n_pixels,
         const GeglRectangle *roi,
         gint                 level)
{
  GeglProperties    *o = GEGL_PROPERTIES (operation);
  const VibParams   *p = (const VibParams *) o->user_data;
  const gfloat * GEGL_ALIGNED in  = in_buf;
  gfloat       * GEGL_ALIGNED out = out_buf;

  g_assert (p != NULL);

  /* 格式在 prepare() 里固定为 R~G~B~A float，步长恒为 4 —— 不按源格式分支，
   * 免得再出现「按 3 通道走、实际 4 通道缓冲」那类错位
   * prepare() pins R~G~B~A float, so the stride is always 4. No branching on
   * the source format, which is what produced the earlier stride mismatch. */
  if (p->identity)
    {
      memcpy (out, in, sizeof (gfloat) * 4 * (gsize) n_pixels);
      return TRUE;
    }

  while (n_pixels--)
    {
      process_pixel (p, in, out);
      out[3] = in[3];
      in  += 4;
      out += 4;
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass            *oc = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointFilterClass *cc = GEGL_OPERATION_POINT_FILTER_CLASS (klass);
  GObjectClass                  *gc = G_OBJECT_CLASS (klass);

  oc->prepare = prepare;
  cc->process = process;
  gc->finalize = finalize;

  gegl_operation_class_set_keys (oc,
    "name",            "lb:vibrance-ps",
    "title",           _("Vibrance (Photoshop)"),
    "categories",      "color:enhance",
    "description",     _("Photoshop's Vibrance, matched by measurement: "
                         "dS = A(v)·S^p·(1-S)^q with tabulated red-band and "
                         "lightness terms, gamut-safe by construction"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Vibrance PS"),
    NULL);
}

#endif
