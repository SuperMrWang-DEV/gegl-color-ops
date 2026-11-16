/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:color-balance
 * menu       Color Balance
 * purpose    经典图像编辑器 色彩平衡：阴影 / 中间调 / 高光各自调 C-R、M-G、Y-B 三对色轴
 *            the classic editor Color Balance: shadow, midtone and highlight each carry three
 *            axis pairs (C-R, M-G, Y-B).
 * algorithm  两种模式。原版（默认）= 逐通道「电平」曲线：三个区间的参数合并成一条
 *            幂律，指数相乘（G = g_shd·g_mid·g_hlt），黑场取阴影负值、白场
 *            取高光正值，近黑端再补一段趾部；保明度 = 零和矩阵（MATLAB
 *            版，未改动）。算子自行钉成感知（伽马）格式，无需前置
 *            linear-rgb。
 *            Two modes. Original (default) = per-channel levels-style curve:
 *            the three ranges merge into one power law whose exponents
 *            multiply (G = g_shd·g_mid·g_hlt), black point from a negative
 *            shadow slider, white point from a positive highlight slider, plus
 *            one near-black toe correction. Preserve-luminosity = zero-sum
 *            matrix (MATLAB version, untouched). The op pins itself to the
 *            perceptual (gamma) format; no linear-rgb node needed.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * reference  色彩平衡调整图层的本质-背后的数学原理（王先生的副业）
 *            https://zhuanlan.zhihu.com/p/679776283
 *            经典图像编辑器 中的色彩平衡调整图层的原理分析（章佳杰）
 *            https://zhuanlan.zhihu.com/p/59450298
 *            The math behind the Color Balance layer / Wang's side project
 *            https://zhuanlan.zhihu.com/p/679776283
 *            How the classic editor Color Balance layer really works / Zhang
 *            Jiajie
 *            https://zhuanlan.zhihu.com/p/59450298
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (shadow_cr, _("Shadow Cyan-Red"), 0.0)
    description (_("Shadow Cyan/Red slider (-100 Cyan ~ +100 Red)"))
    value_range (-100.0, 100.0)
    ui_range (-100.0, 100.0)

property_double (shadow_mg, _("Shadow Magenta-Green"), 0.0)
    description (_("Shadow Magenta/Green slider (-100 Magenta ~ +100 Green)"))
    value_range (-100.0, 100.0)
    ui_range (-100.0, 100.0)

property_double (shadow_yb, _("Shadow Yellow-Blue"), 0.0)
    description (_("Shadow Yellow/Blue slider (-100 Yellow ~ +100 Blue)"))
    value_range (-100.0, 100.0)
    ui_range (-100.0, 100.0)

property_double (midtone_cr, _("Midtone Cyan-Red"), 0.0)
    description (_("Midtone Cyan/Red slider (-100 Cyan ~ +100 Red)"))
    value_range (-100.0, 100.0)
    ui_range (-100.0, 100.0)

property_double (midtone_mg, _("Midtone Magenta-Green"), 0.0)
    description (_("Midtone Magenta/Green slider (-100 Magenta ~ +100 Green)"))
    value_range (-100.0, 100.0)
    ui_range (-100.0, 100.0)

property_double (midtone_yb, _("Midtone Yellow-Blue"), 0.0)
    description (_("Midtone Yellow/Blue slider (-100 Yellow ~ +100 Blue)"))
    value_range (-100.0, 100.0)
    ui_range (-100.0, 100.0)

property_double (highlight_cr, _("Highlight Cyan-Red"), 0.0)
    description (_("Highlight Cyan/Red slider (-100 Cyan ~ +100 Red)"))
    value_range (-100.0, 100.0)
    ui_range (-100.0, 100.0)

property_double (highlight_mg, _("Highlight Magenta-Green"), 0.0)
    description (_("Highlight Magenta/Green slider (-100 Magenta ~ +100 Green)"))
    value_range (-100.0, 100.0)
    ui_range (-100.0, 100.0)

property_double (highlight_yb, _("Highlight Yellow-Blue"), 0.0)
    description (_("Highlight Yellow/Blue slider (-100 Yellow ~ +100 Blue)"))
    value_range (-100.0, 100.0)
    ui_range (-100.0, 100.0)

property_boolean (preserve_luminosity, _("Preserve Luminosity"), FALSE)
    description (_("MATLAB-style zero-sum logic. Unchecked: original the classic editor color balance."))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_color_balance
#define GEGL_OP_C_SOURCE color-balance.c
#include "gegl-op.h"
#include "cb-tables.h"

#ifndef MAX
#define MAX(a,b) ((a) > (b) ? (a) : (b))
#endif
#ifndef MIN
#define MIN(a,b) ((a) < (b) ? (a) : (b))
#endif

#define FLOAT_EPS       1e-12f

static inline gfloat sanitize_f(gfloat v)
{
  if (!isfinite(v))
    return 0.0f;
  return v;
}

/* ===========================================================================
 * 非保明度路径：经典图像编辑器 色彩平衡的逐通道曲线
 * The non-preserve-luminosity path: the classic editor's per-channel curves
 * ---------------------------------------------------------------------------
 * 实测结论（经典图像编辑器 26.10；16 位、每个整数滑杆档、三个区间 201 档 + 9 个组合档；
 * 1024 px 连续斜坡探针，见 cb-cal/）：
 *
 * 1. 逐通道独立。一个通道只有一条曲线，只由该通道在三个区间上的滑杆决定，
 *    与另外两个通道无关（单通道斜坡带与灰阶带的输出逐位相同）。
 * 2. 曲线是「电平」形式的幂律：
 *
 *        base(v) = 255 · clamp( ((v − b) / (W − b))^G )
 *
 *    只有两处会挪动端点，其余情况 b = 0、W = 255：
 *        b = |s_shd|       仅阴影为负值时抬起黑场
 *        W = 255 − s_hlt   仅高光为正值时压低白场
 * 3. 三个区间不是依次串联，而是把指数乘起来：
 *
 *        G = g_shd · g_mid · g_hlt
 *
 *    整幅图只有一条复合曲线，黑场取阴影负值、白场取高光正值。
 *    中间调最强（±100 → 2^∓1），阴影与高光只有它一半量级（±100 → 2^∓0.5）。
 *    （旧版按「高光 → 中间调 → 阴影 依次作用」实现，组合档最多差 112 码；
 *      改成指数相乘后 9 个组合档全部 ≤ 0.6 码。）
 * 4. 近黑端还有一段「趾部」：G < 1 时幂律在 0 处的斜率是无穷，经典图像编辑器 实际是有限
 *    斜率起步。它等价于 [b, h0] 上的一段三次 Hermite：
 *
 *        h0  = b + H · (W − b)
 *        y1  = 255 · H^G         区间右端值
 *        m0s = Su · H            起点斜率（已乘区间长度）
 *        m1s = G · y1            右端斜率（已乘区间长度，等于 base′(h0)·(h0−b)）
 *
 *    Su、H 都只随复合指数 G 变化（表 CB_TOE 的第 1、2 列），与「这个 G 是哪个
 *    区间给的」无关：单区间与组合档落在同一条 Su(G) 上。G ≥ 0.85 时 H 已经衰减
 *    到 0，趾部自然消失；G > 1 时幂律本来就是零斜率起步，也不需要。
 *    忽略这一段时最坏误差 16 码（中间调 +100，v≈4），补上后 ≤ 0.3 码。
 *
 * 1. Each channel has its own curve, independent of the other two channels
 *    (a single-channel ramp and a grey ramp give bit-identical output).
 * 2. Every curve is a levels-style power law, see base() above; b/W only move
 *    for shadow-negative and highlight-positive.
 * 3. The three ranges are not chained: their exponents multiply into one
 *    composite curve, G = g_shd · g_mid · g_hlt (the old "highlight ->
 *    midtone -> shadow" chaining was off by up to 112 codes on combos).
 * 4. Near black the power law is replaced by one cubic Hermite on [b, h0],
 *    where h0 = b + H(G)·(W − b) and the initial slope is Su(G). Both H and Su
 *    depend on the composite exponent only; skipping this correction costs up
 *    to 16 codes around v = 4, with it the worst case is 0.3.
 * ======================================================================== */

#define CB_LUTN 4097            /* 复合曲线采样点数 / samples per curve */

typedef struct
{
  gboolean identity;
  gfloat   lut[3][CB_LUTN];     /* [通道][索引]，输入 0…255 → 输出 0…255 */
} CbParams;

/* 滑杆 → 指数：表里存的是整数档，浮点滑杆在相邻两档之间线性插值
 * Slider -> exponent. The table is per integer step; fractional sliders are
 * interpolated linearly between neighbours. */
static inline gdouble
cb_exponent (gint range, gdouble s)
{
  gint    neg = (s < 0.0) ? 1 : 0;
  gdouble a   = fabs (s);
  gint    i;
  gdouble f, g0, g1;

  if (a > 100.0)
    a = 100.0;
  i = (gint) a;
  f = a - (gdouble) i;
  if (i >= 100)
    return (gdouble) CB_G[range][neg][100];

  g0 = (gdouble) CB_G[range][neg][i];
  g1 = (gdouble) CB_G[range][neg][i + 1];
  return g0 + (g1 - g0) * f;
}

/* 在 CB_TOE 上按 G 线性插值取一列（col 1 = Su，col 2 = H），两端 clamp
 * Linear interpolation over CB_TOE in G; col 1 is Su, col 2 is H. */
static inline gdouble
cb_toe_lookup (gdouble g, gint col)
{
  gint i;

  if (g <= (gdouble) CB_TOE[0][0])
    return (gdouble) CB_TOE[0][col];
  if (g >= (gdouble) CB_TOE[CB_NTOE - 1][0])
    return (gdouble) CB_TOE[CB_NTOE - 1][col];

  for (i = 0; i + 1 < CB_NTOE; i++)
    {
      gdouble g0 = (gdouble) CB_TOE[i][0], g1 = (gdouble) CB_TOE[i + 1][0];

      if (g >= g0 && g <= g1)
        {
          gdouble v0 = (gdouble) CB_TOE[i][col];
          gdouble v1 = (gdouble) CB_TOE[i + 1][col];

          return v0 + (v1 - v0) * (g - g0) / (g1 - g0);
        }
    }
  return (gdouble) CB_TOE[CB_NTOE - 1][col];
}

/* 电平式幂律 / the levels-style power law */
static inline gdouble
cb_base (gdouble v, gdouble G, gdouble b, gdouble W)
{
  gdouble x;

  if (v <= b)
    return 0.0;
  x = (v - b) / (W - b);
  if (x <= 0.0)
    return 0.0;
  if (x >= 1.0)
    return 255.0;
  return 255.0 * pow (x, G);
}

/* [b, h0] 上的三次 Hermite（t 已归一化，两个斜率都乘过区间长度）
 * Cubic Hermite on [b, h0]; t is normalised, both slopes are pre-scaled. */
static inline gdouble
cb_hermite (gdouble t, gdouble m0s, gdouble y1, gdouble m1s)
{
  return (t * t * t - 2.0 * t * t + t) * m0s
       + (-2.0 * t * t * t + 3.0 * t * t) * y1
       + (t * t * t - t * t) * m1s;
}

/* 把一条复合曲线折成 LUT / fold one composite curve into a LUT */
static void
cb_build_curve (gfloat *lut, gdouble s_shd, gdouble s_mid, gdouble s_hlt)
{
  gdouble  G  = cb_exponent (0, s_shd) * cb_exponent (1, s_mid)
              * cb_exponent (2, s_hlt);
  gdouble  b  = (s_shd < 0.0) ? -s_shd : 0.0;
  gdouble  W  = (s_hlt > 0.0) ? 255.0 - s_hlt : 255.0;
  gdouble  h0 = 0.0, y1 = 0.0, m0s = 0.0, m1s = 0.0;
  gboolean toe = FALSE;
  gint     i;

  if (G < 0.995 && W - b > 1.0)
    {
      gdouble hf = cb_toe_lookup (G, 2);       /* 趾部宽度占 (W−b) 的比例 */

      if (hf > 1e-3)
        {
          h0  = b + hf * (W - b);
          y1  = 255.0 * pow (hf, G);
          m0s = cb_toe_lookup (G, 1) * hf;
          m1s = G * y1;
          toe = TRUE;
        }
    }

  for (i = 0; i < CB_LUTN; i++)
    {
      gdouble v = (gdouble) i * (255.0 / (gdouble) (CB_LUTN - 1));
      gdouble o;

      if (toe && v < h0)
        o = (v <= b) ? 0.0
                     : cb_hermite ((v - b) / (h0 - b), m0s, y1, m1s);
      else
        o = cb_base (v, G, b, W);

      lut[i] = (gfloat) CLAMP (o, 0.0, 255.0);
    }
}

/* 查表 + 线性插值 / lookup with linear interpolation */
static inline gfloat
cb_lookup (const gfloat *lut, gfloat v)
{
  gfloat x, f;
  gint   i;

  if (v <= 0.0f)
    return lut[0];
  if (v >= 255.0f)
    return lut[CB_LUTN - 1];

  x = v * (gfloat) (CB_LUTN - 1) / 255.0f;
  i = (gint) x;
  f = x - (gfloat) i;
  return lut[i] + (lut[i + 1] - lut[i]) * f;
}

/**
 * normalize_three_median
 * 三个值先排序，再各自减去中位数；三值相等时全部变成 0。
 * Sort the three values and subtract the median; equal inputs collapse to 0.
 */
static inline void normalize_three_median(gdouble *v)
{
    gdouble a = v[0], b = v[1], c = v[2];
    gdouble median;
    if ((a <= b && b <= c) || (c <= b && b <= a))
        median = b;
    else if ((b <= a && a <= c) || (c <= a && a <= b))
        median = a;
    else
        median = c;
    v[0] -= median;
    v[1] -= median;
    v[2] -= median;
}

/*
 * ===== MATLAB 风格保明度函数 / MATLAB preserve luminosity =====
 * 依据 MATLAB 算法：
 *   1. 系数减去中位数做归一化 / normalize coefficients by the median
 *   2. 高光：矩阵 -> 每通道 alpha -> in / (1 - alpha)
 *      highlights: matrix -> alpha per channel -> in / (1 - alpha)
 *   3. 阴影：矩阵 -> 每通道 alpha -> (in - alpha) / (1 - alpha)
 *      shadows: matrix -> alpha per channel -> (in - alpha) / (1 - alpha)
 *   4. 中间调：矩阵 -> 每通道 gamma -> in ^ gamma
 *      midtones: matrix -> gamma per channel -> in ^ gamma
 */

/**
 * compute_highlights_alpha
 * 高光的 MATLAB 算法：先把系数拆成正、负两部分，再按矩阵列求和得到
 * 每通道一个 alpha。
 * MATLAB algorithm for highlights: split the coefficients into pos/neg parts,
 * then sum the matrix columns to get one alpha per channel.
 *   alpha = k * coef  (k = 0.0039230)
 *   pos = max(alpha, 0), neg = max(-alpha, 0)
 *   Matrix = diag(pos)*I + diag(neg)*M_offdiag
 *     where M_offdiag = [0,1,1; 1,0,1; 1,1,0]
 *   alpha_result = sum(Matrix)  (column sums)
 *   => alpha_result[j] = alpha[j] + sum(neg)
 */
static inline void compute_highlights_alpha(const gdouble *coef, gdouble *alpha_out)
{
    const gdouble k = 0.0039230;
    gdouble a[3], neg[3];
    gdouble sum_neg;
    int i;

    for (i = 0; i < 3; i++) {
        a[i] = k * coef[i];
        neg[i] = a[i] < 0.0 ? -a[i] : 0.0;
    }
    sum_neg = neg[0] + neg[1] + neg[2];
    for (i = 0; i < 3; i++) {
        alpha_out[i] = a[i] + sum_neg;
    }
}

/**
 * compute_shadows_alpha
 * 阴影的 MATLAB 算法：与高光方向相反，负系数进对角、正系数进非对角。
 * MATLAB algorithm for shadows: the opposite of highlights, negative
 * coefficients go to the diagonal and positive ones off it.
 *   alpha = k * coef  (k = 0.0039230)
 *   pos = max(alpha, 0), neg = max(-alpha, 0)
 *   Matrix = diag(neg)*I + diag(pos)*M_offdiag
 *     where M_offdiag = [0,1,1; 1,0,1; 1,1,0]
 *   alpha_result = sum(Matrix)  (column sums)
 *   => alpha_result[j] = sum(pos) - alpha[j]
 */
static inline void compute_shadows_alpha(const gdouble *coef, gdouble *alpha_out)
{
    const gdouble k = 0.0039230;
    gdouble a[3], pos[3];
    gdouble sum_pos;
    int i;

    for (i = 0; i < 3; i++) {
        a[i] = k * coef[i];
        pos[i] = a[i] > 0.0 ? a[i] : 0.0;
    }
    sum_pos = pos[0] + pos[1] + pos[2];
    for (i = 0; i < 3; i++) {
        alpha_out[i] = sum_pos - a[i];
    }
}

/**
 * compute_midtones_gamma
 * 中间调的 MATLAB 算法：由三通道 alpha 通过反对角矩阵换成每通道 gamma。
 * MATLAB algorithm for midtones: turn the three alphas into one gamma per
 * channel through the anti-diagonal matrix.
 *   alpha = k * coef  (k = 0.0033944)
 *   gamma = exp(sum(diag(-alpha) * M))
 *     where M = [1,-1,-1; -1,1,-1; -1,-1,1]
 *   => gamma[j] = exp(sum(diag(-alpha)*M)[j])
 *   => gamma[0] = exp(-a[0] + a[1] + a[2])
 *   => gamma[1] = exp(a[0] - a[1] + a[2])
 *   => gamma[2] = exp(a[0] + a[1] - a[2])
 */
static inline void compute_midtones_gamma(const gdouble *coef, gdouble *gamma_out)
{
    const gdouble k = 0.0033944;
    gdouble a[3];
    int i;

    for (i = 0; i < 3; i++) {
        a[i] = k * coef[i];
    }
    gamma_out[0] = exp(-a[0] + a[1] + a[2]);
    gamma_out[1] = exp(a[0] - a[1] + a[2]);
    gamma_out[2] = exp(a[0] + a[1] - a[2]);
}

/* 感知（非线性）格式：公式按 8bit sRGB 伽马域推导，必须拿伽马值，否则 babl
 * 会喂线性光，数值与 经典图像编辑器 对不上
 * Perceptual (non-linear) format: the maths was derived in the 8-bit sRGB
 * gamma domain. Linear light from babl would drift away from the classic editor. */
static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}

static void
prepare(GeglOperation *op)
{
  GeglProperties *o = GEGL_PROPERTIES (op);
  CbParams       *p = (CbParams *) o->user_data;
  gdouble         shd[3], mid[3], hlt[3];
  gint            c;

  /* 非保明度路径的三条复合曲线只取决于滑杆，整幅图像共用，
   * 所以在 prepare() 里折成三张 LUT；process() 只剩查表 + 插值。
   * The three composite curves depend on the sliders only, so they are folded
   * into three LUTs here; the process loop is left with one lookup per
   * channel. */
  if (! p)
    {
      p = g_slice_new0 (CbParams);
      o->user_data = p;
    }

  shd[0] = o->shadow_cr;    shd[1] = o->shadow_mg;    shd[2] = o->shadow_yb;
  mid[0] = o->midtone_cr;   mid[1] = o->midtone_mg;   mid[2] = o->midtone_yb;
  hlt[0] = o->highlight_cr; hlt[1] = o->highlight_mg; hlt[2] = o->highlight_yb;

  p->identity = TRUE;
  for (c = 0; c < 3; c++)
    if (shd[c] != 0.0 || mid[c] != 0.0 || hlt[c] != 0.0)
      p->identity = FALSE;

  if (! p->identity)
    for (c = 0; c < 3; c++)
      cb_build_curve (p->lut[c], shd[c], mid[c], hlt[c]);

  gegl_operation_set_format(op, "input",  perceptual_format(op));
  gegl_operation_set_format(op, "output", perceptual_format(op));
}

static void
finalize (GObject *object)
{
  GeglProperties *o = GEGL_PROPERTIES (object);

  if (o->user_data)
    {
      g_slice_free (CbParams, o->user_data);
      o->user_data = NULL;
    }

  G_OBJECT_CLASS (gegl_op_parent_class)->finalize (object);
}

static gboolean
process(GeglOperation       *op,
        GeglBuffer          *in_buf,
        GeglBuffer          *out_buf,
        const GeglRectangle *roi,
        gint                 level)
{
  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  gdouble shd_cr, shd_mg, shd_yb;
  gdouble mid_cr, mid_mg, mid_yb;
  gdouble hlt_cr, hlt_mg, hlt_yb;
  gboolean preserve_lum;
  CbParams *p = (CbParams *) GEGL_PROPERTIES (op)->user_data;

  g_object_get(G_OBJECT(op),
    "shadow-cr", &shd_cr,
    "shadow-mg", &shd_mg,
    "shadow-yb", &shd_yb,
    "midtone-cr", &mid_cr,
    "midtone-mg", &mid_mg,
    "midtone-yb", &mid_yb,
    "highlight-cr", &hlt_cr,
    "highlight-mg", &hlt_mg,
    "highlight-yb", &hlt_yb,
    "preserve-luminosity", &preserve_lum,
    NULL);

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };

    gegl_buffer_get(in_buf, &row_rect, 1.0f, perceptual_format(op),
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint px = x * 4;
      gfloat r_in = in_line[px + 0];
      gfloat g_in = in_line[px + 1];
      gfloat b_in = in_line[px + 2];
      gfloat a    = in_line[px + 3];

      gfloat r_out, g_out, b_out;

      if (preserve_lum)
      {
          /* ---- MATLAB 保明度 / preserve luminosity --------------------- */
          /* 第 1 步：系数减中位数归一化
           * Step 1: normalize the coefficients by the median */
          gdouble shd_in[3] = { shd_cr, shd_mg, shd_yb };
          gdouble mid_in[3] = { mid_cr, mid_mg, mid_yb };
          gdouble hlt_in[3] = { hlt_cr, hlt_mg, hlt_yb };

          normalize_three_median(shd_in);
          normalize_three_median(mid_in);
          normalize_three_median(hlt_in);

          /* 第 2 步：算每通道系数
           * Step 2: compute per-channel coefficients */
          gdouble hlt_alpha[3], shd_alpha[3], mid_gamma[3];
          compute_highlights_alpha(hlt_in, hlt_alpha);
          compute_shadows_alpha(shd_in, shd_alpha);
          compute_midtones_gamma(mid_in, mid_gamma);

          /* 第 3 步：应用高光，out = in / (1 - alpha)
           * Step 3: apply highlights -> out = in / (1 - alpha) */
          r_out = r_in / (1.0f - (gfloat)hlt_alpha[0]);
          g_out = g_in / (1.0f - (gfloat)hlt_alpha[1]);
          b_out = b_in / (1.0f - (gfloat)hlt_alpha[2]);
          r_out = CLAMP(r_out, 0.0f, 1.0f);
          g_out = CLAMP(g_out, 0.0f, 1.0f);
          b_out = CLAMP(b_out, 0.0f, 1.0f);

          /* 第 4 步：应用阴影，out = (in - alpha) / (1 - alpha)
           * Step 4: apply shadows -> out = (in - alpha) / (1 - alpha) */
          r_out = (r_out - (gfloat)shd_alpha[0]) / (1.0f - (gfloat)shd_alpha[0]);
          g_out = (g_out - (gfloat)shd_alpha[1]) / (1.0f - (gfloat)shd_alpha[1]);
          b_out = (b_out - (gfloat)shd_alpha[2]) / (1.0f - (gfloat)shd_alpha[2]);
          r_out = CLAMP(r_out, 0.0f, 1.0f);
          g_out = CLAMP(g_out, 0.0f, 1.0f);
          b_out = CLAMP(b_out, 0.0f, 1.0f);

          /* 第 5 步：应用中间调，out = in ^ gamma
           * Step 5: apply midtones -> out = in ^ gamma */
          r_out = powf(r_out, (gfloat)mid_gamma[0]);
          g_out = powf(g_out, (gfloat)mid_gamma[1]);
          b_out = powf(b_out, (gfloat)mid_gamma[2]);
          r_out = CLAMP(r_out, 0.0f, 1.0f);
          g_out = CLAMP(g_out, 0.0f, 1.0f);
          b_out = CLAMP(b_out, 0.0f, 1.0f);
      }
      else
      {
          /* 原版 经典图像编辑器 行为：逐通道复合曲线，prepare() 里已折成 LUT
           * Original the classic editor behaviour: per-channel composite curve, already folded
           * into a LUT in prepare(). */
          if (p && ! p->identity)
            {
              r_out = cb_lookup (p->lut[0], r_in * 255.0f) * (1.0f / 255.0f);
              g_out = cb_lookup (p->lut[1], g_in * 255.0f) * (1.0f / 255.0f);
              b_out = cb_lookup (p->lut[2], b_in * 255.0f) * (1.0f / 255.0f);
            }
          else
            {
              r_out = r_in;
              g_out = g_in;
              b_out = b_in;
            }
      }

      r_out = CLAMP(r_out, 0.0f, 1.0f);
      g_out = CLAMP(g_out, 0.0f, 1.0f);
      b_out = CLAMP(b_out, 0.0f, 1.0f);

      out_line[px + 0] = r_out;
      out_line[px + 1] = g_out;
      out_line[px + 2] = b_out;
      out_line[px + 3] = sanitize_f(a);
    }

    gegl_buffer_set(out_buf, &row_rect, 0, perceptual_format(op),
                     out_line, GEGL_AUTO_ROWSTRIDE);
  }

  g_free(in_line);
  g_free(out_line);
  return TRUE;
}

static void
gegl_op_class_init(GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS(klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS(klass);

  oclass->prepare = prepare;
  fclass->process = process;
  G_OBJECT_CLASS (klass)->finalize = finalize;

  gegl_operation_class_set_keys(oclass,
    "name",            "lb:color-balance",
    "title",           _("Color Balance"),
    "description",     _("the classic editor Color Balance: shadow/midtone/highlight C-R, M-G, Y-B. "
                         "Per-channel levels-style curve: the three range exponents "
                         "multiply into one power law (black point from a negative "
                         "shadow slider, white point from a positive highlight "
                         "slider) plus a near-black toe, measured against "
                         "the classic editor. Pins itself to the perceptual format."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Color",
    "gimp:menu-label", _("Color Balance"),
    NULL);
}

#endif