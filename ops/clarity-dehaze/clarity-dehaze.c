/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:clarity-dehaze
 * menu       Clarity & Dehaze（SuperMrWang → Color）
 * purpose    Camera Raw「基本」面板上最常拖的两个滑块，一个算子装下：
 *            - 清晰度 Clarity：中频局部对比度，不是锐化（锐化是小半径高频）
 *            - 去朦胧 Dehaze：暗通道先验反解大气散射，把远山从灰雾里拉回来
 *            Clarity and Dehaze — the two most-dragged sliders in Camera
 *            Raw's Basic panel. Clarity boosts mid-frequency local contrast
 *            (not sharpening, which is high frequency); Dehaze inverts
 *            atmospheric scattering with the dark-channel prior.
 * algorithm  清晰度 / clarity
 *              Y      = 0.2126 R + 0.7152 G + 0.0722 B（编码值，感知空间）
 *              low    = 三次盒式模糊近似高斯，半径 clarity-radius
 *              d      = Y − low
 *              d'     = h · tanh(d / h)        h = halo 宽度，压住边缘过冲
 *              w      = 1 − |2Y − 1|²          中间调权重，护住黑白两端
 *              gain   = 1 + 强度 · w · d' / max(low, 0.08)
 *              RGB   *= gain
 *            用 d/low 的**相对**量而不是绝对差值：暗部不会因为 low 很小而被
 *            放大成噪点，亮部也不会一推就溢出。
 *            Relative (d/low) rather than absolute difference: shadows cannot
 *            blow up into noise and highlights cannot clip.
 *            tanh 压缩是 halo 抑制的核心：|d| 远大于 h 的地方（硬边缘两侧）
 *            被压到 ±h，边缘不会出现亮边/黑边；而幅度在 h 以内的中频细节
 *            几乎原样通过。这就是清晰度与 USM 的区别。
 *
 *            去朦胧 / dehaze（He, Sun & Tang 2009 暗通道先验）
 *              暗通道  dark = min over window( min(R,G,B) )  窗口 = dehaze-radius
 *              大气光  A    = 暗通道最亮 0.1% 像素的原图均值（直方图找阈值）
 *              透射率  t    = 1 − ω · dark / max(lum(A), ε)，夹在 [t_min, 1]
 *              恢复    J_c  = (I_c − A_c) / t + A_c
 *              输出    O_c  = I_c + s · (J_c − I_c)
 *            ω 默认 0.95（留一点雾更像照片），t_min 取 0.12：再低会把
 *            噪声乘上十几倍变成色斑。
 *            ω defaults to 0.95 — leaving a little haze looks like a photo —
 *            and t is floored at 0.12: below that the noise gets multiplied by
 *            a factor of ten and turns into coloured blotches.
 * type       GeglOperationFilter（单输入、整幅处理 / single input, whole image）
 * reference  He, Sun & Tang (2009)「Single Image Haze Removal Using Dark
 *            Channel Prior」CVPR；PS Camera Raw 的 Clarity / Dehaze 语义；
 *            RawTherapee 的 local contrast 用相对量而非绝对差值。
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_double (clarity, _("Clarity"), 0.0)
  description (_("Mid-frequency local contrast. Positive opens up the texture "
                 "in clouds, foliage and skin; negative softens it. Unlike "
                 "unsharp mask this does not touch fine detail"))
  value_range (-100.0, 100.0)

property_int (clarity_radius, _("Clarity radius"), 40)
  description (_("Radius of the local average that defines \"mid frequency\". "
                 "Too small turns into sharpening, too large turns into a "
                 "global contrast change"))
  value_range (4, 400)

property_double (clarity_protect, _("Edge protection"), 0.35)
  description (_("Compresses the overshoot at hard edges so they do not grow "
                 "a bright or dark halo. 0 lets edges through unchecked, 1 "
                 "flattens them almost completely"))
  value_range (0.0, 1.0)

property_double (dehaze, _("Dehaze"), 0.0)
  description (_("Removes atmospheric haze using the dark channel prior. "
                 "Negative values add haze, which is occasionally what you "
                 "want for depth"))
  value_range (-100.0, 100.0)

property_int (dehaze_radius, _("Dehaze radius"), 15)
  description (_("Window used to find the dark channel. Should be larger than "
                 "the brightest thing in the hazy area, otherwise the "
                 "transmission map picks up objects instead of depth"))
  value_range (4, 200)

property_double (dehaze_keep, _("Haze kept"), 0.95)
  description (_("How much of the estimated haze to remove, as a fraction. "
                 "1.0 is a full solve and looks artificial; 0.95 keeps a "
                 "little atmosphere"))
  value_range (0.5, 1.0)

property_double (dehaze_saturation, _("Dehaze saturation"), 0.0)
  description (_("Saturation applied after dehazing, in percent. Removing "
                 "haze darkens the sky and flattens colour, so a little extra "
                 "saturation usually looks right"))
  value_range (-100.0, 100.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_clarity_dehaze
#define GEGL_OP_C_SOURCE clarity-dehaze.c

#include "gegl-op.h"

/* 透射率下限。低于它噪声会被放大到可见：1/0.12 ≈ 8 倍。
 * Transmission floor: below this the noise gets multiplied by 1/0.12 ≈ 8. */
#define LB_CD_TMIN 0.12

/* 暗通道估计大气光时取的像素比例（最亮的千分之一）。
 * Fraction of pixels used to estimate the atmospheric light. */
#define LB_CD_AIRLIGHT 0.001

/* 相对增益的夹紧范围，防极端参数把画面推成纯黑或纯白。
 * Clamp for the relative gain so extreme settings cannot flatten the image. */
#define LB_CD_GAIN_MIN 0.15
#define LB_CD_GAIN_MAX 6.0

static inline gint
lb_cd_clampi (gint v, gint lo, gint hi)
{
  return v < lo ? lo : (v > hi ? hi : v);
}

static inline gfloat
lb_cd_clampf (gfloat v, gfloat lo, gfloat hi)
{
  return v < lo ? lo : (v > hi ? hi : v);
}

/* 亮度用编码值上的 Rec.709 系数。在 sRGB 编码空间里算，是因为清晰度描述的
 * 是**感知**上的中频对比；换到线性空间会让暗部的同一组参数看起来强得多。
 * Luma from the encoded values with Rec.709 weights: clarity is about
 * perceived mid-frequency contrast, and in linear light the same setting
 * looks far stronger in the shadows. */
static inline gfloat
lb_cd_luma (const gfloat *p)
{
  return 0.2126f * p[0] + 0.7152f * p[1] + 0.0722f * p[2];
}

/* ---- 水平/垂直盒式模糊（滑动和，O(N)） --------------------------------- */
/* 边界用 clamp（重复边缘像素）。三次盒式模糊在半径 ≥ 2 时与真高斯差不到
 * 一个色阶，而代价只有三次滑动和。
 * Box blur with a running sum and clamped edges. Three passes approximate a
 * Gaussian to within a colour code for radii of 2 and up, at O(N) per pass. */

static void
lb_cd_box_h (const gfloat *src, gfloat *dst, gint w, gint h, gint r)
{
  const gfloat inv = 1.0f / (gfloat) (2 * r + 1);
  gint y;

  for (y = 0; y < h; y++)
    {
      const gfloat *s = src + (gsize) y * w;
      gfloat       *d = dst + (gsize) y * w;
      gfloat sum = 0.0f;
      gint   x;

      for (x = -r; x <= r; x++)
        sum += s[lb_cd_clampi (x, 0, w - 1)];

      d[0] = sum * inv;

      for (x = 1; x < w; x++)
        {
          sum += s[lb_cd_clampi (x + r, 0, w - 1)];
          sum -= s[lb_cd_clampi (x - r - 1, 0, w - 1)];
          d[x] = sum * inv;
        }
    }
}

static void
lb_cd_box_v (const gfloat *src, gfloat *dst, gint w, gint h, gint r)
{
  const gfloat inv = 1.0f / (gfloat) (2 * r + 1);
  gint x;

  for (x = 0; x < w; x++)
    {
      gfloat sum = 0.0f;
      gint   y;

      for (y = -r; y <= r; y++)
        sum += src[(gsize) lb_cd_clampi (y, 0, h - 1) * w + x];

      dst[x] = sum * inv;

      for (y = 1; y < h; y++)
        {
          sum += src[(gsize) lb_cd_clampi (y + r, 0, h - 1) * w + x];
          sum -= src[(gsize) lb_cd_clampi (y - r - 1, 0, h - 1) * w + x];
          dst[(gsize) y * w + x] = sum * inv;
        }
    }
}

/* 三次盒式模糊 ≈ 高斯。tmp 由调用方提供，省一次分配。
 * Three box passes approximate a Gaussian; tmp is caller-provided. */
static void
lb_cd_gauss (const gfloat *src, gfloat *dst, gfloat *tmp,
             gint w, gint h, gint radius)
{
  const gint r = MAX (1, radius / 3);

  lb_cd_box_h (src, dst, w, h, r);
  lb_cd_box_v (dst, tmp, w, h, r);
  lb_cd_box_h (tmp, dst, w, h, r);
  lb_cd_box_v (dst, tmp, w, h, r);
  lb_cd_box_h (tmp, dst, w, h, r);
  lb_cd_box_v (dst, tmp, w, h, r);
}

/* ---- 暗通道：滑动窗口最小值（单调队列，O(N)） -------------------------- */
/* 每行/每列维护一个递增队列，队首就是窗口最小值。窗口半径再大也不变慢，
 * 而朴素写法是 O(W·r)，半径 15 就要多跑 30 倍的像素。
 * Sliding-window minimum with a monotone deque: O(N) regardless of radius.
 * The naive version is O(W·r), i.e. 30x the work at radius 15. */

static void
lb_cd_min_h (const gfloat *src, gfloat *dst, gint w, gint h, gint r,
             gint *dq, gfloat *qv)
{
  gint y;

  for (y = 0; y < h; y++)
    {
      const gfloat *s = src + (gsize) y * w;
      gfloat       *d = dst + (gsize) y * w;
      gint head = 0, tail = 0;
      gint x;

      for (x = 0; x < w + r; x++)
        {
          if (x < w)
            {
              while (tail > head && qv[tail - 1] >= s[x])
                tail--;
              dq[tail] = x;
              qv[tail] = s[x];
              tail++;
            }
          while (tail > head && dq[head] < x - r)
            head++;
          if (x >= r)
            d[x - r] = qv[head];
        }
    }
}

static void
lb_cd_min_v (const gfloat *src, gfloat *dst, gint w, gint h, gint r,
             gint *dq, gfloat *qv)
{
  gint x;

  for (x = 0; x < w; x++)
    {
      gint head = 0, tail = 0;
      gint y;

      for (y = 0; y < h + r; y++)
        {
          if (y < h)
            {
              const gfloat v = src[(gsize) y * w + x];

              while (tail > head && qv[tail - 1] >= v)
                tail--;
              dq[tail] = y;
              qv[tail] = v;
              tail++;
            }
          while (tail > head && dq[head] < y - r)
            head++;
          if (y >= r)
            dst[(gsize) (y - r) * w + x] = qv[head];
        }
    }
}

/* ---- 清晰度 ------------------------------------------------------------ */

/* 对整幅做中频增强。in/out 是交错的 RGB(A) float，Y 是预存的亮度。
 * Mid-frequency boost over the whole image; in/out is interleaved RGBA. */
static void
lb_cd_clarity (gfloat *buf, const gfloat *Y, gfloat *low, gfloat *tmp,
               gint w, gint h, gdouble amount, gint radius,
               gdouble protect)
{
  /* 相对增益的参考下限：low 落在这里以下就当作纯黑，不再放大。
   * Reference floor for the relative gain: below this the local average is
   * treated as black and no longer amplified. */
  const gfloat floor_l = 0.08f;
  const gfloat amt     = (gfloat) (amount / 100.0);
  /* halo 宽度：保护 0 时极大（tanh 近似线性，等于不压），1 时很小（边缘被
   * 压成一段平顶）。这两个端点都对应实测结果，不是随手取的。
   * Halo width: at protection 0 it is huge (tanh becomes linear, i.e. no
   * compression); at 1 it is tiny and hard edges flatten out. */
  const gfloat hw = (gfloat) (0.03 + 0.25 * (1.0 - protect) * (1.0 - protect)
                              * 4.0);
  gsize i, n = (gsize) w * h;

  lb_cd_gauss (Y, low, tmp, w, h, radius);

  for (i = 0; i < n; i++)
    {
      const gfloat y  = Y[i];
      const gfloat lo = low[i];
      const gfloat d  = y - lo;
      const gfloat m  = (2.0f * y - 1.0f);
      const gfloat wgt = MAX (0.0f, 1.0f - m * m);
      const gfloat dc = hw * tanh (d / hw);
      const gfloat gain = lb_cd_clampf (1.0f + amt * wgt * dc /
                                        MAX (lo, floor_l),
                                        LB_CD_GAIN_MIN, LB_CD_GAIN_MAX);
      gfloat *p = buf + i * 4;

      p[0] *= gain;
      p[1] *= gain;
      p[2] *= gain;
    }
}

/* ---- 去朦胧 ------------------------------------------------------------ */

static void
lb_cd_dehaze (gfloat *buf, gfloat *minc, gfloat *dark, gfloat *tmp,
              gint w, gint h, gdouble amount, gint radius,
              gdouble keep, gdouble sat)
{
  const gfloat s = (gfloat) (amount / 100.0);
  const gsize  n = (gsize) w * h;
  gint   hist[1024];
  gfloat A[3] = { 1.0f, 1.0f, 1.0f };
  gfloat A_lum = 1.0f;
  gfloat thr   = 0.0f;
  gsize  i;
  gint   b;
  /* 队列是每次调用自己的：GEGL 会多线程跑 process，静态缓冲会串数据。
   * Per-call deque — GEGL may run process on several threads at once. */
  gint  *dq = g_new (gint, (gsize) MAX (w, h) + 2 * (gsize) radius + 4);
  gfloat *qv = g_new (gfloat, (gsize) MAX (w, h) + 2 * (gsize) radius + 4);

  for (i = 0; i < n; i++)
    {
      const gfloat *p = buf + i * 4;

      minc[i] = MIN (p[0], MIN (p[1], p[2]));
    }

  lb_cd_min_h (minc, tmp, w, h, radius, dq, qv);
  lb_cd_min_v (tmp, dark, w, h, radius, dq, qv);

  /* 大气光：暗通道最亮的那 0.1% 像素。用直方图找阈值，避免对 400 万个数
   * 排序（排序是这里唯一会明显拖慢的地方）。
   * Atmospheric light from the brightest 0.1% of the dark channel: a
   * histogram instead of sorting four million values. */
  memset (hist, 0, sizeof (hist));
  for (i = 0; i < n; i++)
    hist[lb_cd_clampi ((gint) (dark[i] * 1023.0f), 0, 1023)]++;

  {
    const gsize want = MAX ((gsize) 1, (gsize) (n * LB_CD_AIRLIGHT));
    gsize acc = 0;

    for (b = 1023; b >= 0; b--)
      {
        acc += (gsize) hist[b];
        if (acc >= want)
          {
            thr = (gfloat) b / 1023.0f;
            break;
          }
      }
  }

  {
    gdouble sr = 0.0, sg = 0.0, sb = 0.0;
    gsize cnt = 0;

    for (i = 0; i < n; i++)
      {
        if (dark[i] >= thr)
          {
            const gfloat *p = buf + i * 4;

            sr += p[0];
            sg += p[1];
            sb += p[2];
            cnt++;
          }
      }

    if (cnt > 0)
      {
        A[0] = (gfloat) (sr / cnt);
        A[1] = (gfloat) (sg / cnt);
        A[2] = (gfloat) (sb / cnt);
      }

    /* 大气光几乎全黑只可能是夜拍——这时候 t ≈ 1，整段等于不动。
     * An almost-black airlight means a night shot, where t stays at 1. */
    A_lum = MAX ((A[0] + A[1] + A[2]) / 3.0f, 1.0e-3f);
  }

  for (i = 0; i < n; i++)
    {
      gfloat *p = buf + i * 4;
      gfloat t = 1.0f - (gfloat) keep * dark[i] / A_lum;
      gint   c;

      t = lb_cd_clampf (t, LB_CD_TMIN, 1.0f);

      for (c = 0; c < 3; c++)
        {
          const gfloat j = (p[c] - A[c]) / t + A[c];
          gfloat o = p[c] + s * (j - p[c]);

          p[c] = o;
        }

      if (sat != 0.0)
        {
          /* 去雾按 t 提亮，颜色会被拉向大气光的灰白，补一点饱和拉回来。
           * 围绕亮度缩放到亮度，色相不动。
           * Dehazing pulls colour toward the grey airlight, so saturation is
           * restored by scaling chroma around luma — hue stays put. */
          const gfloat y = lb_cd_luma (p);
          const gfloat k = (gfloat) (1.0 + sat / 100.0);

          p[0] = y + (p[0] - y) * k;
          p[1] = y + (p[1] - y) * k;
          p[2] = y + (p[2] - y) * k;
        }
    }

  g_free (dq);
  g_free (qv);
}

/* ---- GEGL 接线 --------------------------------------------------------- */

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");
  const Babl *fmt   = babl_format_with_space ("R'G'B'A float", space);

  gegl_operation_set_format (operation, "input",  fmt);
  gegl_operation_set_format (operation, "output", fmt);
}

static GeglRectangle
get_bounding_box (GeglOperation *operation)
{
  const GeglRectangle *in = gegl_operation_source_get_bounding_box (operation,
                                                                    "input");

  if (in)
    return *in;

  {
    const GeglRectangle empty = { 0, 0, 0, 0 };
    return empty;
  }
}

/* 大气光要看整幅才准，所以输入全部算作必需。只给 roi 的话，同一张图在
 * 预览和导出时会得到不同的 A，观感就跳一下。
 * The airlight needs the whole frame, so the whole input is required;
 * otherwise the preview and the export disagree on A and the look jumps. */
static GeglRectangle
get_required_for_output (GeglOperation       *operation,
                         const gchar         *input_pad,
                         const GeglRectangle *roi)
{
  const GeglRectangle *full = gegl_operation_source_get_bounding_box (operation,
                                                                      "input");

  return full ? *full : *roi;
}

static gboolean
process (GeglOperation       *operation,
         GeglOperationContext *context,
         const gchar         *output_prop,
         const GeglRectangle *result,
         gint                 level)
{
  GeglProperties *o   = GEGL_PROPERTIES (operation);
  const Babl     *fmt = gegl_operation_get_format (operation, "output");
  const GeglRectangle *ext =
    gegl_operation_source_get_bounding_box (operation, "input");

  GeglBuffer *input  = gegl_operation_context_get_source (context, "input");
  GeglBuffer *output = gegl_operation_context_get_target (context, "output");

  gfloat *buf = NULL;
  gfloat *Y = NULL, *low = NULL, *tmp = NULL, *minc = NULL, *dark = NULL;
  gint lw, lh, lx0, ly0;
  GeglRectangle full0, area;
  gdouble amount_c, amount_d;

  (void) output_prop;

  if (ext == NULL)
    return TRUE;

  if (input == NULL || output == NULL)
    {
      g_clear_object (&input);
      return TRUE;
    }

  amount_c = o->clarity;
  amount_d = o->dehaze;

  /* 两个都是 0 就别碰像素：这是一条真正等于恒等的快路径，浮点往返都不做。
   * Both at zero means byte-identical copy, no float round trip at all. */
  if (amount_c == 0.0 && amount_d == 0.0 && level == 0)
    {
      gegl_buffer_copy (input, NULL, GEGL_ABYSS_NONE, output, NULL);
      g_object_unref (input);
      return TRUE;
    }

  const gint sub = 1 << level;

  lw  = MAX (1, ext->width  >> level);
  lh  = MAX (1, ext->height >> level);
  lx0 = ext->x / sub;
  ly0 = ext->y / sub;

  full0.x      = ext->x;
  full0.y      = ext->y;
  full0.width  = ext->width;
  full0.height = ext->height;

  area = result ? *result : (GeglRectangle) { lx0, ly0, lw, lh };

  buf = g_try_malloc_n ((gsize) lw * lh * 4, sizeof (gfloat));

  if (buf == NULL)
    {
      /* 内存不够就直通，别让 GIMP 在一个 8 亿像素的图上崩掉。
       * Out of memory: pass through rather than crash the host. */
      g_warning ("lb:clarity-dehaze: not enough memory for %dx%d", lw, lh);
      gegl_buffer_copy (input, NULL, GEGL_ABYSS_NONE, output, NULL);
      g_object_unref (input);
      return TRUE;
    }

  gegl_buffer_get (input, &full0, 1.0 / (gdouble) sub, fmt, buf,
                   (gint) (sizeof (gfloat) * 4 * (gsize) lw),
                   GEGL_ABYSS_CLAMP);

  if (amount_d != 0.0)
    {
      const gsize n = (gsize) lw * lh;

      minc = g_new (gfloat, n);
      dark = g_new (gfloat, n);
      tmp  = g_new (gfloat, n);

      lb_cd_dehaze (buf, minc, dark, tmp, lw, lh, amount_d,
                    MAX (2, (gint) o->dehaze_radius >> level),
                    o->dehaze_keep, o->dehaze_saturation);

      g_free (minc); g_free (dark); g_free (tmp);
      minc = dark = tmp = NULL;

      /* 去雾改过 RGB，清晰度那段会自己重算亮度（见下面 Y[] 的填充），
       * 不会拿旧的低频去比。
       * Dehaze changed RGB; the clarity pass recomputes luma from the new
       * pixels, so the low-pass never compares against stale values. */
    }

  if (amount_c != 0.0)
    {
      gsize i, n = (gsize) lw * lh;

      Y   = g_new (gfloat, n);
      low = g_new (gfloat, n);
      tmp = g_new (gfloat, n);

      for (i = 0; i < n; i++)
        Y[i] = lb_cd_luma (buf + i * 4);

      lb_cd_clarity (buf, Y, low, tmp, lw, lh, amount_c,
                     MAX (2, (gint) o->clarity_radius >> level),
                     o->clarity_protect);
    }

  {
    const gint xoff = area.x - lx0;
    const gint yoff = area.y - ly0;
    const gfloat *p = buf + ((gsize) yoff * lw + xoff) * 4;

    gegl_buffer_set (output, &area, level, fmt, p,
                     (gint) (sizeof (gfloat) * 4 * (gsize) lw));
  }

  g_free (Y);
  g_free (low);
  g_free (tmp);
  g_free (buf);
  g_object_unref (input);

  return TRUE;
}

/* ---- 类初始化 / class init --------------------------------------------- */

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass *oclass = GEGL_OPERATION_CLASS (klass);

  oclass->prepare                 = prepare;
  oclass->process                 = process;
  oclass->get_bounding_box        = get_bounding_box;
  oclass->get_required_for_output = get_required_for_output;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:clarity-dehaze",
    "title",           _("Clarity & Dehaze"),
    "description",     _("Mid-frequency local contrast plus dark-channel "
                         "dehazing: the two Camera Raw sliders that fix flat, "
                         "hazy pictures."),
    "gimp:menu-path",  "<Image>/SuperMrWang/Color",
    "gimp:menu-label", _("Clarity & Dehaze"),
    NULL);
}

#endif
