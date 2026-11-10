/* ===========================================================================
 * SuperMrWang · GEGL Operation
 * ---------------------------------------------------------------------------
 * id     : lb:color-balance
 * 菜单   : Color Balance
 * 作用   : PS 色彩平衡：阴影 / 中间调 / 高光各自调 C-R、M-G、Y-B 三对色轴
 * 算法   : 在 8bit sRGB 伽马域反推 PS 曲线，两种模式：
 *          原版 = 三区间独立通道曲线；MATLAB 版 = 零和矩阵（保明度）
 *          输入须为伽马编码 sRGB，勿在前置节点用 linear-rgb
 * 类型   : GeglOperationFilter
 * 参考   : zhuanlan.zhihu.com/p/679776283 、/p/59450298（PS 色彩平衡原理）
 * 许可   : GPL-3.0-or-later，见工程根目录 LICENSE
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
    description (_("MATLAB-style zero-sum logic. Unchecked: original PS color balance."))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_color_balance
#define GEGL_OP_C_SOURCE color-balance.c
#include "gegl-op.h"

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

static inline gfloat trimResult(gfloat value)
{
    if (value < 0.0f) return 0.0f;
    if (value > 255.0f) return 255.0f;
    return value;
}

static inline gfloat gammaCorrection255(gfloat input8, gdouble gamma)
{
    input8 = CLAMP(input8, 0.0f, 255.0f);
    gfloat normalized = input8 / 255.0f;
    gfloat corrected = powf(normalized, (gfloat)gamma);
    gint outi = (gint)(corrected * 255.0f + 0.5f);
    if (outi > 255) outi = 255;
    return (gfloat)outi;
}

/* ---- Highlight curve functions (unchanged) ----------------------------- */
static inline gfloat highlightRight(gdouble value, gfloat input8)
{
    gfloat result = (1.0f / (1.0f - 0.004f * (gfloat)value)) * input8;
    return trimResult(result);
}
static inline gfloat highlightLeft(gdouble value, gfloat input8)
{
    return gammaCorrection255(input8, 1.0 - (0.004 * value));
}
static inline gfloat highlight(gdouble value, gfloat input8)
{
    if (value >= 0)
        return highlightRight(value, input8);
    else
        return highlightLeft(value, input8);
}

/* ---- Midtone curve functions (unchanged) ------------------------------- */
static inline gfloat midtoneRight(gdouble value, gfloat input8)
{
    return gammaCorrection255(input8, 1.0 - (0.005 * value));
}
static inline gfloat midtoneLeft(gdouble value, gfloat input8)
{
    return gammaCorrection255(input8, 1.0 - (0.01 * value));
}
static inline gfloat midtone(gdouble value, gfloat input8)
{
    if (value >=0)
        return midtoneRight(value, input8);
    else
        return midtoneLeft(value, input8);
}

/* ---- Shadow curve functions (unchanged) -------------------------------- */
static inline gfloat shadowRight(gdouble value, gfloat input8)
{
    return gammaCorrection255(input8, 1.0 - (0.003 * value));
}
static inline gfloat shadowLeft(gdouble value, gdouble value_param, gfloat input8)
{
    gfloat temp = 0.004f * fabs((gfloat)value_param);
    gfloat temp1 = (input8 / 255.0f) - temp;
    gfloat temp2 = 1.0f - temp;
    gfloat result = (temp1 / temp2) * 255.0f;
    return trimResult(result);
}
static inline gfloat shadow(gdouble value, gfloat input8)
{
    if (value >=0)
        return shadowRight(value, input8);
    else
        return shadowLeft(value, value, input8);
}

/**
 * colorbalance_8bit_kernel
 * CHANGED: No brightness region split, NO weighting/interpolation.
 * Shadow, Midtone, Highlight curves apply sequentially in full to every pixel.
 * Every pixel goes through all three curves one after another.
 */
static inline gfloat colorbalance_8bit_kernel(gfloat inFloat,
                                              gdouble shd,
                                              gdouble mid,
                                              gdouble hlt)
{
    gfloat val = inFloat * 255.0f;

    /* 全部像素依次应用三条曲线，全程生效，不分明暗 */
    val = shadow(shd, val);
    val = midtone(mid, val);
    val = highlight(hlt, val);

    gfloat out8 = trimResult(val);
    return out8 / 255.0f;
}

/**
 * normalize_three_median
 * 三个值排序，减去中位数。
 * 三值相等时全部变成 0。
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
 * ===== MATLAB-style preserve luminosity functions =====
 * Based on the MATLAB algorithm:
 *   1. Normalize coefficients by subtracting median
 *   2. Highlights: matrix method -> per-channel alpha -> out = in / (1 - alpha)
 *   3. Shadows:   matrix method -> per-channel alpha -> out = (in - alpha) / (1 - alpha)
 *   4. Midtones:  matrix method -> per-channel gamma -> out = in ^ gamma
 */

/**
 * compute_highlights_alpha
 * MATLAB algorithm for highlights:
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
 * MATLAB algorithm for shadows:
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
 * MATLAB algorithm for midtones:
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

static void
prepare(GeglOperation *op)
{
  gegl_operation_set_format(op, "input",  babl_format("RGBA float"));
  gegl_operation_set_format(op, "output", babl_format("RGBA float"));
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

    gegl_buffer_get(in_buf, &row_rect, 1.0f, babl_format("RGBA float"),
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
          /* ---- MATLAB-style preserve luminosity ------------------------ */
          /* Step 1: Normalize coefficients by subtracting median */
          gdouble shd_in[3] = { shd_cr, shd_mg, shd_yb };
          gdouble mid_in[3] = { mid_cr, mid_mg, mid_yb };
          gdouble hlt_in[3] = { hlt_cr, hlt_mg, hlt_yb };

          normalize_three_median(shd_in);
          normalize_three_median(mid_in);
          normalize_three_median(hlt_in);

          /* Step 2: Compute per-channel coefficients */
          gdouble hlt_alpha[3], shd_alpha[3], mid_gamma[3];
          compute_highlights_alpha(hlt_in, hlt_alpha);
          compute_shadows_alpha(shd_in, shd_alpha);
          compute_midtones_gamma(mid_in, mid_gamma);

          /* Step 3: Apply highlights -> out = in / (1 - alpha) */
          r_out = r_in / (1.0f - (gfloat)hlt_alpha[0]);
          g_out = g_in / (1.0f - (gfloat)hlt_alpha[1]);
          b_out = b_in / (1.0f - (gfloat)hlt_alpha[2]);
          r_out = CLAMP(r_out, 0.0f, 1.0f);
          g_out = CLAMP(g_out, 0.0f, 1.0f);
          b_out = CLAMP(b_out, 0.0f, 1.0f);

          /* Step 4: Apply shadows -> out = (in - alpha) / (1 - alpha) */
          r_out = (r_out - (gfloat)shd_alpha[0]) / (1.0f - (gfloat)shd_alpha[0]);
          g_out = (g_out - (gfloat)shd_alpha[1]) / (1.0f - (gfloat)shd_alpha[1]);
          b_out = (b_out - (gfloat)shd_alpha[2]) / (1.0f - (gfloat)shd_alpha[2]);
          r_out = CLAMP(r_out, 0.0f, 1.0f);
          g_out = CLAMP(g_out, 0.0f, 1.0f);
          b_out = CLAMP(b_out, 0.0f, 1.0f);

          /* Step 5: Apply midtones -> out = in ^ gamma */
          r_out = powf(r_out, (gfloat)mid_gamma[0]);
          g_out = powf(g_out, (gfloat)mid_gamma[1]);
          b_out = powf(b_out, (gfloat)mid_gamma[2]);
          r_out = CLAMP(r_out, 0.0f, 1.0f);
          g_out = CLAMP(g_out, 0.0f, 1.0f);
          b_out = CLAMP(b_out, 0.0f, 1.0f);
      }
      else
      {
          /* Original PS behavior: independent channel kernel, use raw sliders */
          r_out = colorbalance_8bit_kernel(r_in, shd_cr, mid_cr, hlt_cr);
          g_out = colorbalance_8bit_kernel(g_in, shd_mg, mid_mg, hlt_mg);
          b_out = colorbalance_8bit_kernel(b_in, shd_yb, mid_yb, hlt_yb);
      }

      r_out = CLAMP(r_out, 0.0f, 1.0f);
      g_out = CLAMP(g_out, 0.0f, 1.0f);
      b_out = CLAMP(b_out, 0.0f, 1.0f);

      out_line[px + 0] = r_out;
      out_line[px + 1] = g_out;
      out_line[px + 2] = b_out;
      out_line[px + 3] = sanitize_f(a);
    }

    gegl_buffer_set(out_buf, &row_rect, 0, babl_format("RGBA float"),
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

  gegl_operation_class_set_keys(oclass,
    "name",            "lb:color-balance",
    "title",           _("Color Balance"),
    "description",     _("PS Color Balance: shadow/midtone/highlight C-R, M-G, Y-B "
                         "on 8-bit sRGB gamma data. Do NOT use linear-rgb before this op."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Color Balance"),
    NULL);
}

#endif