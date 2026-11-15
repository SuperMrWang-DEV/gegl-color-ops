/* ===========================================================================
 * SuperMrWang · 分量色阶共用内核 / shared component-levels kernel
 * ---------------------------------------------------------------------------
 * 给 lb:hsl-levels / lb:hsb-levels / lb:lch-levels / lb:cmyk-levels /
 * lb:hsi-levels 共用：色阶数学、环形色相映射、LUT，以及「按模型格式逐分量
 * 查表」的整块处理循环。算子文件里只剩属性声明与参数收集。
 *
 * Two kinds of channel:
 *   线性分量（S/V/L/C/K/I）—— clamp 到 [in_lo, in_hi]，归一化，gamma，再映射
 *     到 [out_lo, out_hi]。与 ops/lab-levels 的 L 通道同一套语义。
 *   环形分量（H）—— 色相是环，不能简单 clamp。把圆在 in_lo 处剪开，弧
 *     [in_lo → in_hi] 映到 [out_lo → out_hi]，剩下的弧线性映到剩余弧长，
 *     两段共用 gamma。映射在整圈上连续，identity 时逐位还原。
 *
 * 所有色阶都是 1D 单调映射，逐像素 powf 换成 4096 项 LUT + 插值；色相的
 * LUT 按环形采样（跨 360/0 处按最短弧插值），否则边界会绕远路。
 * ======================================================================== */

#ifndef LB_COLOR_LEVELS_H
#define LB_COLOR_LEVELS_H

#include <math.h>
#include <glib.h>
#include <gegl.h>

#define LB_CL_LUT_N  4096
#define LB_CL_EPS    1e-9f

/* 每个分量的 5 个参数在数组里的下标 */
#define LB_CL_IB  0   /* 输入黑场 */
#define LB_CL_IW  1   /* 输入白场 */
#define LB_CL_G   2   /* gamma */
#define LB_CL_OB  3   /* 输出黑场 */
#define LB_CL_OW  4   /* 输出白场 */

/* 参数按 n 个分量 × 5 个参数平铺存放：p[c * 5 + k]。
 * 用一维数组而不是 gdouble[c][5]，是因为 C 不允许 double(*)[5] 隐式转
 * const double(*)[5]，二维写法会编译告警 */
#define LB_CL_PARAM(p, c, k)  ((p)[(c) * 5 + (k)])

typedef struct
{
  const char *fmt;          /* babl 格式（含 alpha），如 "HSLA float" */
  gint        n;            /* 分量数（不含 alpha，2…4） */
  gfloat      scale[4];     /* 属性单位 / 内部单位（百分比与 babl 0-1 之间） */
  gfloat      lo[4];        /* 属性单位下的量程下限 */
  gfloat      hi[4];        /* 属性单位下的量程上限 */
  gboolean    circular[4];  /* TRUE = 环形分量（色相） */
} LbClModel;

/* ---------------------------------------------------------------- 线性分量 */

static inline gfloat
lb_cl_levels_linear (gfloat v,
                     gfloat ib, gfloat iw, gfloat gamma,
                     gfloat ob, gfloat ow)
{
  /* 黑白场交叉时自动交换（滑杆允许拉出交叉） */
  if (ib > iw)
    {
      gfloat t = ib;
      ib = iw;
      iw = t;
    }

  if (fabsf (iw - ib) < LB_CL_EPS)
    return v;

  v = CLAMP (v, ib, iw);

  gfloat n = powf (MAX ((v - ib) / (iw - ib), LB_CL_EPS), 1.0f / gamma);

  v = ob + n * (ow - ob);

  /* 输出反向（负片式）时 clamp 到真实上下界，而不是压成单值 */
  return CLAMP (v, MIN (ob, ow), MAX (ob, ow));
}

/* ---------------------------------------------------------------- 环形色相 */

static inline gfloat
lb_cl_wrap360 (gfloat a)
{
  a = fmodf (a, 360.0f);
  if (a < 0.0f)
    a += 360.0f;
  return a;
}

/* 箭头从 a 顺时针到 b 的弧长；重合时返回 0（由调用方当作整圈处理）。 */
static inline gfloat
lb_cl_arc (gfloat a, gfloat b)
{
  return lb_cl_wrap360 (b - a);
}

/* 环形色相 levels：把圆在 ia 处剪开，主弧 [ia→ib] 映到 [oa→ob]，余弧映到
 * 余下的弧长；两段都套 gamma。整圈上连续，identity（0/360 → 0/360，γ=1）
 * 精确还原。
 * Circular hue levels: cut the circle at ia, map the main arc [ia→ib] onto
 * [oa→ob] and the remaining arc onto what is left of the circle. Continuous
 * everywhere on the circle, exact identity for 0/360 → 0/360 with γ = 1. */
static inline gfloat
lb_cl_levels_hue (gfloat h,
                  gfloat ia, gfloat ib, gfloat gamma,
                  gfloat oa, gfloat ob)
{
  gfloat in_span  = lb_cl_arc (ia, ib);
  gfloat out_span = lb_cl_arc (oa, ob);
  gfloat z        = lb_cl_arc (ia, h);   /* 0 … 360，从黑场顺时针量 */

  /* 黑白场重合 = 整圈：既保证默认 0/360 恒等，也让「黑白场拉到一起」变成
   * 纯色相旋转 + gamma 环绕，而不是塌成一个颜色 */
  if (in_span < 1e-3f)
    in_span = 360.0f;
  if (out_span < 1e-3f)
    out_span = 360.0f;

  gfloat base, span, t;

  if (z <= in_span)
    {
      t    = z / in_span;
      base = oa;
      span = out_span;
    }
  else
    {
      gfloat rest = 360.0f - in_span;
      t    = (rest < 1e-3f) ? 0.0f : (z - in_span) / rest;
      base = oa + out_span;
      span = 360.0f - out_span;
    }

  t = powf (MAX (t, 0.0f), 1.0f / gamma);

  return lb_cl_wrap360 (base + span * t);
}

/* --------------------------------------------------------------------- LUT */

static inline void
lb_cl_lut_build_linear (gfloat       *lut,
                        gfloat        lo, gfloat hi,
                        gfloat        ib, gfloat iw, gfloat gamma,
                        gfloat        ob, gfloat ow)
{
  for (gint i = 0; i < LB_CL_LUT_N; i++)
    lut[i] = lb_cl_levels_linear (lo + (hi - lo) * (gfloat) i /
                                      (gfloat) (LB_CL_LUT_N - 1),
                                  ib, iw, gamma, ob, ow);
}

static inline gfloat
lb_cl_lut_sample_linear (const gfloat *lut,
                         gfloat        v,
                         gfloat        lo, gfloat hi)
{
  if (hi - lo < LB_CL_EPS)
    return v;

  gfloat t  = (CLAMP (v, lo, hi) - lo) * (gfloat) (LB_CL_LUT_N - 1) / (hi - lo);
  gint   i0 = (gint) t;
  if (i0 >= LB_CL_LUT_N - 1)
    return lut[LB_CL_LUT_N - 1];

  gfloat f = t - (gfloat) i0;

  return lut[i0] * (1.0f - f) + lut[i0 + 1] * f;
}

/* 色相 LUT 只在 [0,360) 上采样：360 与 0 是同一个点，多采一格会让环形插值
 * 在边界处互相打架 */
static inline void
lb_cl_lut_build_hue (gfloat *lut,
                     gfloat  ia, gfloat ib, gfloat gamma,
                     gfloat  oa, gfloat ob)
{
  for (gint i = 0; i < LB_CL_LUT_N; i++)
    lut[i] = lb_cl_levels_hue (360.0f * (gfloat) i / (gfloat) LB_CL_LUT_N,
                               ia, ib, gamma, oa, ob);
}

static inline gfloat
lb_cl_lut_sample_hue (const gfloat *lut, gfloat h)
{
  gfloat t  = lb_cl_wrap360 (h) * (gfloat) LB_CL_LUT_N / 360.0f;
  gint   i0 = (gint) t;
  gfloat f  = t - (gfloat) i0;

  gfloat a = lut[i0 % LB_CL_LUT_N];
  gfloat b = lut[(i0 + 1) % LB_CL_LUT_N];

  /* 跨 360/0 时按最短弧插值，直接线性插值会绕整圈 */
  gfloat d = b - a;
  if (d >  180.0f) d -= 360.0f;
  if (d < -180.0f) d += 360.0f;

  return lb_cl_wrap360 (a + d * f);
}

/* --------------------------------------------------- 按模型格式逐分量处理 */

/* 一次处理整块 roi。p[c][0..4] 是第 c 个分量的五个参数，属性单位。
 * Process one whole region; p[c][0..4] holds the five levels parameters of
 * channel c, in property units. */
static inline gboolean
lb_cl_process (GeglBuffer          *in_buf,
               GeglBuffer          *out_buf,
               const GeglRectangle *roi,
               const LbClModel     *m,
               const gdouble       *p)
{
  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  const Babl *fmt  = babl_format (m->fmt);
  gint        npx  = m->n + 1;              /* 含 alpha */
  gint        stride = roi->width * npx;

  gfloat *lut = g_new (gfloat, LB_CL_LUT_N * m->n);

  for (gint c = 0; c < m->n; c++)
    {
      gfloat *l = lut + (gsize) c * LB_CL_LUT_N;
      gfloat  ib = (gfloat) LB_CL_PARAM (p, c, LB_CL_IB);
      gfloat  iw = (gfloat) LB_CL_PARAM (p, c, LB_CL_IW);
      gfloat  ga = (gfloat) MAX (LB_CL_PARAM (p, c, LB_CL_G), 0.01);
      gfloat  ob = (gfloat) LB_CL_PARAM (p, c, LB_CL_OB);
      gfloat  ow = (gfloat) LB_CL_PARAM (p, c, LB_CL_OW);

      if (m->circular[c])
        lb_cl_lut_build_hue (l, ib, iw, ga, ob, ow);
      else
        lb_cl_lut_build_linear (l, m->lo[c], m->hi[c], ib, iw, ga, ob, ow);
    }

  gfloat *in_line  = g_new (gfloat, stride);
  gfloat *out_line = g_new (gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, roi->width, 1 };

      gegl_buffer_get (in_buf, &row, 1.0f, fmt, in_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (gint x = 0; x < roi->width; x++)
        {
          gint   px = x * npx;
          gfloat a  = in_line[px + m->n];

          /* 透明像素原样透传：色彩无意义，也不该被色阶移动 */
          if (a <= 0.0f)
            {
              for (gint c = 0; c <= m->n; c++)
                out_line[px + c] = in_line[px + c];
              out_line[px + m->n] = 0.0f;
              continue;
            }

          for (gint c = 0; c < m->n; c++)
            {
              gfloat sc  = m->scale[c];
              gfloat val = in_line[px + c] * sc;      /* 属性单位 */
              gfloat out;

              if (m->circular[c])
                out = lb_cl_lut_sample_hue (lut + (gsize) c * LB_CL_LUT_N, val);
              else
                out = lb_cl_lut_sample_linear (lut + (gsize) c * LB_CL_LUT_N,
                                               val, m->lo[c], m->hi[c]);

              out_line[px + c] = (sc > LB_CL_EPS) ? out / sc : out;
            }

          out_line[px + m->n] = a;
        }

      gegl_buffer_set (out_buf, &row, 0, fmt, out_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (in_line);
  g_free (out_line);
  g_free (lut);

  return TRUE;
}

/* ------------------------------------------------------------------ HSI ---
 * babl 只有 HSL / HSV / HCY / Lab / LCh / CMYK，没有 HSI，所以这一套自备。
 * HSI: I = (R+G+B)/3，S = 1 − min/I，H 用与 HSV 同一个色相角（0° 红）。
 * babl has no HSI model, so the conversion lives here. HSI with I as the mean
 * of the three channels and S as 1 - min/I. */

static inline void
lb_cl_rgb_to_hsi (gfloat  r, gfloat g, gfloat b,
                  gfloat *h, gfloat *s, gfloat *i)
{
  const gfloat R2D = 57.29577951308232f;
  gfloat sum = r + g + b;
  gfloat mn  = MIN (r, MIN (g, b));
  gfloat c   = MAX (r, MAX (g, b)) - mn;

  *i = sum / 3.0f;

  if (*i <= LB_CL_EPS || c <= LB_CL_EPS)
    {
      *s = 0.0f;
      *h = 0.0f;
      return;
    }

  *s = 1.0f - mn / *i;

  /* HSI 的色相角是余弦定义，不是 HSV 那种六边形分量比：
   *   cos H = [(R−G) + (R−B)] / (2·sqrt((R−G)² + (R−B)(G−B)))
   * 两者在等亮度平面上不是同一个角，混用会让往返偏 4 码以上（实测
   * 纯色附近最差），逆变换也就对不上。
   * HSI's hue is the cosine form, not HSV's channel-ratio form; mixing them
   * breaks the round trip by several codes near saturated colours. */
  gfloat num = 0.5f * ((r - g) + (r - b));
  gfloat den = sqrtf ((r - g) * (r - g) + (r - b) * (g - b));

  if (den <= LB_CL_EPS)
    *h = 0.0f;
  else
    {
      gfloat theta = acosf (CLAMP (num / den, -1.0f, 1.0f)) * R2D;
      *h = (b <= g) ? theta : 360.0f - theta;
    }

  *h = lb_cl_wrap360 (*h);
}

static inline void
lb_cl_hsi_to_rgb (gfloat h, gfloat s, gfloat i,
                  gfloat *r, gfloat *g, gfloat *b)
{
  const gfloat D2R = 0.017453292519943295f;
  gfloat hh, lo, mid, hi;

  s = CLAMP (s, 0.0f, 1.0f);
  i = CLAMP (i, 0.0f, 1.0f);
  hh = lb_cl_wrap360 (h);

  /* HSI 的逆变换不是 HSV 那种扇区互换：每个 120° 段里，两个通道是
   * I(1−S) 与 I[1 + S·cos h / cos(60−h)]，第三通道由 3I 减出来。用 HSV 的
   * 线性扇区公式会在 S 高、I 低时偏差几十码。
   * HSI inverts via the cosine form, not HSV's linear sectors. */
  if (hh < 120.0f)
    {
      lo  = i * (1.0f - s);
      hi  = i * (1.0f + s * cosf (hh * D2R) / cosf ((60.0f - hh) * D2R));
      mid = 3.0f * i - lo - hi;
      *b = lo; *r = hi; *g = mid;
    }
  else if (hh < 240.0f)
    {
      gfloat a = hh - 120.0f;
      lo  = i * (1.0f - s);
      hi  = i * (1.0f + s * cosf (a * D2R) / cosf ((60.0f - a) * D2R));
      mid = 3.0f * i - lo - hi;
      *r = lo; *g = hi; *b = mid;
    }
  else
    {
      gfloat a = hh - 240.0f;
      lo  = i * (1.0f - s);
      hi  = i * (1.0f + s * cosf (a * D2R) / cosf ((60.0f - a) * D2R));
      mid = 3.0f * i - lo - hi;
      *g = lo; *b = hi; *r = mid;
    }

  *r = CLAMP (*r, 0.0f, 1.0f);
  *g = CLAMP (*g, 0.0f, 1.0f);
  *b = CLAMP (*b, 0.0f, 1.0f);
}

/* HSI 版整块处理：输入输出都是 RGB(A)，逐像素来回转换。
 * HSI pass: RGB(A) in and out, converting per pixel. */
static inline gboolean
lb_cl_process_hsi (GeglBuffer          *in_buf,
                   GeglBuffer          *out_buf,
                   const GeglRectangle *roi,
                   const gdouble       *p)
{
  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  const Babl *fmt    = babl_format ("R'G'B'A float");
  gint        stride = roi->width * 4;

  gfloat *lut_h = g_new (gfloat, LB_CL_LUT_N);
  gfloat *lut_s = g_new (gfloat, LB_CL_LUT_N);
  gfloat *lut_i = g_new (gfloat, LB_CL_LUT_N);

  lb_cl_lut_build_hue (lut_h,
                       (gfloat) LB_CL_PARAM (p, 0, LB_CL_IB),
                       (gfloat) LB_CL_PARAM (p, 0, LB_CL_IW),
                       (gfloat) MAX (LB_CL_PARAM (p, 0, LB_CL_G), 0.01),
                       (gfloat) LB_CL_PARAM (p, 0, LB_CL_OB),
                       (gfloat) LB_CL_PARAM (p, 0, LB_CL_OW));
  lb_cl_lut_build_linear (lut_s, 0.0f, 100.0f,
                          (gfloat) LB_CL_PARAM (p, 1, LB_CL_IB),
                          (gfloat) LB_CL_PARAM (p, 1, LB_CL_IW),
                          (gfloat) MAX (LB_CL_PARAM (p, 1, LB_CL_G), 0.01),
                          (gfloat) LB_CL_PARAM (p, 1, LB_CL_OB),
                          (gfloat) LB_CL_PARAM (p, 1, LB_CL_OW));
  lb_cl_lut_build_linear (lut_i, 0.0f, 100.0f,
                          (gfloat) LB_CL_PARAM (p, 2, LB_CL_IB),
                          (gfloat) LB_CL_PARAM (p, 2, LB_CL_IW),
                          (gfloat) MAX (LB_CL_PARAM (p, 2, LB_CL_G), 0.01),
                          (gfloat) LB_CL_PARAM (p, 2, LB_CL_OB),
                          (gfloat) LB_CL_PARAM (p, 2, LB_CL_OW));

  gfloat *in_line  = g_new (gfloat, stride);
  gfloat *out_line = g_new (gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, roi->width, 1 };

      gegl_buffer_get (in_buf, &row, 1.0f, fmt, in_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (gint x = 0; x < roi->width; x++)
        {
          gint   px = x * 4;
          gfloat a  = in_line[px + 3];

          if (a <= 0.0f)
            {
              out_line[px + 0] = in_line[px + 0];
              out_line[px + 1] = in_line[px + 1];
              out_line[px + 2] = in_line[px + 2];
              out_line[px + 3] = 0.0f;
              continue;
            }

          gfloat h, s, i, r, g, b;

          lb_cl_rgb_to_hsi (in_line[px + 0], in_line[px + 1], in_line[px + 2],
                            &h, &s, &i);

          h = lb_cl_lut_sample_hue (lut_h, h);
          s = lb_cl_lut_sample_linear (lut_s, s * 100.0f, 0.0f, 100.0f) / 100.0f;
          i = lb_cl_lut_sample_linear (lut_i, i * 100.0f, 0.0f, 100.0f) / 100.0f;

          lb_cl_hsi_to_rgb (h, s, i, &r, &g, &b);

          out_line[px + 0] = r;
          out_line[px + 1] = g;
          out_line[px + 2] = b;
          out_line[px + 3] = a;
        }

      gegl_buffer_set (out_buf, &row, 0, fmt, out_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (in_line);
  g_free (out_line);
  g_free (lut_h);
  g_free (lut_s);
  g_free (lut_i);

  return TRUE;
}

#endif /* LB_COLOR_LEVELS_H */
