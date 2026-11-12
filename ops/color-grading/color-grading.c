/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:color-grading
 * menu       Color Grading
 * purpose    等价 ACR/Lightroom「颜色分级」：阴影 / 中间调 / 高光 / 全局四个
 *            轮盘（色相 + 饱和度）加各自的明度滑杆，按亮度分带给画面上色。
 *            The ACR/Lightroom Color Grading panel: Shadows / Midtones /
 *            Highlights / Global wheels (hue + saturation) with per-range
 *            Luminance sliders, tinting the picture by luminance band.
 * algorithm  逐像素（感知 / 伽马域）：
 *
 *            1. 亮度 L = Rec.709 luma（伽马域），决定像素落在哪个亮度带。
 *            2. 带权重：阴影/中间调分界默认 0.3，中间调/高光分界默认 0.7；
 *               Blending 把两条硬边界铺成 smoothstep 过渡（0 = 硬分界，
 *               100 = 各 ±0.25 的宽过渡，相邻带自动交叉淡化）；
 *               Balance 把两条分界一起平移（正 = 高光范围扩大）。
 *               mid 权重 = 1 − shadow − highlight（钳到 ≥0）。
 *            3. 染色（每个带 / 全局各做一次，权重 w 相乘）：
 *               - 明度滑杆：V += Lw·0.005·w（与 hsl-seven 同系数，±100 → ±0.5）；
 *               - 轮盘强度 t = Sat/100·w：色相向轮盘色相收敛（t=1 完全落位），
 *                 饱和度 s += (1−s)·t —— 只加不减，对应 Sat 滑杆没有负半区；
 *                 低饱和像素的色相额外向轮盘色相靠拢（f = t + (1−t)·max(0, 1−s/t)），
 *                 纯灰像素直接落到轮盘色相上，避免灰像素染出错色相。
 *            4. 全局轮盘权重恒为 1，先做；三个带再做。
 *
 *            ACR 无法在本机标定（未装 Camera Raw 插件），分界 0.3/0.7、
 *            过渡 ±0.25、Rec.709 亮度等均为按公开行为设定的合理模型，
 *            不是黑盒实测值。
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  Adobe Camera Raw / Lightroom Classic 的 Color Grading 面板
 *            Adobe Camera Raw / Lightroom Classic Color Grading panel
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* ---- 全局轮盘 / global wheel ------------------------------------------- */
property_double (global_hue, _("Global Hue"), 0.0)
    value_range (0.0, 360.0)
    description (_("Hue of the global wheel, degrees"))

property_double (global_sat, _("Global Saturation"), 0.0)
    value_range (0.0, 100.0)
    description (_("Strength of the global tint"))

property_double (global_lum, _("Global Luminance"), 0.0)
    value_range (-100.0, 100.0)
    description (_("Brightness shift applied everywhere"))

/* ---- 阴影 / shadows ----------------------------------------------------- */
property_double (shadow_hue, _("Shadows Hue"), 0.0)
    value_range (0.0, 360.0)
    description (_("Hue of the shadows wheel, degrees"))

property_double (shadow_sat, _("Shadows Saturation"), 0.0)
    value_range (0.0, 100.0)
    description (_("Strength of the shadows tint"))

property_double (shadow_lum, _("Shadows Luminance"), 0.0)
    value_range (-100.0, 100.0)
    description (_("Brightness shift in the shadows"))

/* ---- 中间调 / midtones -------------------------------------------------- */
property_double (mid_hue, _("Midtones Hue"), 0.0)
    value_range (0.0, 360.0)
    description (_("Hue of the midtones wheel, degrees"))

property_double (mid_sat, _("Midtones Saturation"), 0.0)
    value_range (0.0, 100.0)
    description (_("Strength of the midtones tint"))

property_double (mid_lum, _("Midtones Luminance"), 0.0)
    value_range (-100.0, 100.0)
    description (_("Brightness shift in the midtones"))

/* ---- 高光 / highlights -------------------------------------------------- */
property_double (high_hue, _("Highlights Hue"), 0.0)
    value_range (0.0, 360.0)
    description (_("Hue of the highlights wheel, degrees"))

property_double (high_sat, _("Highlights Saturation"), 0.0)
    value_range (0.0, 100.0)
    description (_("Strength of the highlights tint"))

property_double (high_lum, _("Highlights Luminance"), 0.0)
    value_range (-100.0, 100.0)
    description (_("Brightness shift in the highlights"))

/* ---- 过渡 / transition -------------------------------------------------- */
property_double (blending, _("Blending"), 50.0)
    value_range (0.0, 100.0)
    description (_("Cross-fade width between the tonal ranges (0 = hard split)"))

property_double (balance, _("Balance"), 0.0)
    value_range (-100.0, 100.0)
    description (_("Shift the split toward highlights (positive) or shadows (negative)"))

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_color_grading
#define GEGL_OP_C_SOURCE color-grading.c

#include "gegl-op.h"

/* HSV 边界钳位（沿用 hsl-seven 的写法）
 * clamp the HSV components (same as hsl-seven) */
static inline gfloat
hue_wrap(gfloat h)
{
  h = fmodf(h, 1.0f);
  if (h < 0.0f) h += 1.0f;
  return h;
}

static inline void
hsv_clamp(gfloat *h, gfloat *s, gfloat *v)
{
  *h = hue_wrap(*h);
  *s = CLAMP(*s, 0.0f, 1.0f);
  *v = CLAMP(*v, 0.0f, 1.0f);
}

static inline gfloat
smooth_step(gfloat val, gfloat a, gfloat b)
{
  /* a == b 时退化为阶跃函数（Blending = 0 的硬分界）。
   * When a == b it degenerates to a step function (Blending = 0 hard split). */
  if (b <= a)
    return (val <= a) ? 0.0f : 1.0f;

  if (val <= a) return 0.0f;
  if (val >= b) return 1.0f;

  gfloat t = (val - a) / (b - a);
  return t * t * (3.0f - 2.0f * t);
}

static inline void
hsv_to_rgb(gfloat h, gfloat s, gfloat v, gfloat *r, gfloat *g, gfloat *b)
{
  gfloat c = v * s;
  gfloat x = c * (1.0f - fabsf(fmodf(h*6.0f, 2.0f) - 1.0f));
  gfloat m = v - c;

  if (h < 1.0f/6.0f)
    *r=c, *g=x, *b=0;
  else if (h < 2.0f/6.0f)
    *r=x, *g=c, *b=0;
  else if (h < 3.0f/6.0f)
    *r=0, *g=c, *b=x;
  else if (h < 4.0f/6.0f)
    *r=0, *g=x, *b=c;
  else if (h < 5.0f/6.0f)
    *r=x, *g=0, *b=c;
  else
    *r=c, *g=0, *b=x;

  *r += m;
  *g += m;
  *b += m;
}

/* 一个轮盘（带权重 w）的一次染色。h/s/v 就地修改。
 * One wheel application with range weight w; h/s/v are modified in place. */
static inline void
apply_wheel(gfloat *h, gfloat *s, gfloat *v,
            gfloat hue_deg, gfloat sat_ui, gfloat lum_ui, gfloat w)
{
  if (w < 0.001f)
    return;

  /* 明度滑杆：±100 → V ±0.5（与 hsl-seven 的 lightness 系数一致）
   * Luminance slider: +-100 -> V +-0.5 (same coefficient as hsl-seven) */
  *v += lum_ui * 0.005f * w;

  gfloat t = sat_ui * 0.01f * w;
  if (t < 0.001f)
    return;

  /* 轮盘色相（度 → 0~1 圈）
   * wheel hue, degrees -> 0..1 circle */
  gfloat hw = hue_deg / 360.0f;

  /* 色相收敛比例：轮盘强度 t 为基础；原本低饱和的像素额外向轮盘色相
   * 靠拢（s=0 时比例到 1，纯灰直接落位），避免灰像素染出错色相。
   * Hue convergence fraction: t as the base; low-saturation pixels
   * converge further (fraction 1 at s=0, so greys land on the wheel
   * hue instead of an arbitrary one). */
  gfloat f = t + (1.0f - t) * MAX(0.0f, 1.0f - *s / t);

  gfloat d = hw - *h;
  d -= roundf(d);            /* 包到 [-0.5, 0.5] / wrap to [-0.5, 0.5] */
  *h += d * f;

  /* 饱和度只加不减，对应 ACR 的 Sat 滑杆没有负半区
   * saturation only grows, matching ACR's non-negative Sat slider */
  *s += (1.0f - *s) * t;
}

/* 感知（非线性）格式：公式按 8bit sRGB 伽马域推导，必须拿伽马值，否则 babl
 * 会喂线性光，数值对不上（同 hsl-seven / shadows-highlights）
 * Perceptual (non-linear) format, same as hsl-seven / shadows-highlights */
static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}

static void
prepare(GeglOperation *op)
{
  gegl_operation_set_format(op, "input",  perceptual_format(op));
  gegl_operation_set_format(op, "output", perceptual_format(op));
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

  gdouble g_hue, g_sat, g_lum;
  gdouble s_hue, s_sat, s_lum;
  gdouble m_hue, m_sat, m_lum;
  gdouble h_hue, h_sat, h_lum;
  gdouble blend_ui, bal_ui;

  g_object_get(G_OBJECT(op),
    "global-hue", &g_hue, "global-sat", &g_sat, "global-lum", &g_lum,
    "shadow-hue", &s_hue, "shadow-sat", &s_sat, "shadow-lum", &s_lum,
    "mid-hue",    &m_hue, "mid-sat",    &m_sat, "mid-lum",    &m_lum,
    "high-hue",   &h_hue, "high-sat",   &h_sat, "high-lum",   &h_lum,
    "blending",   &blend_ui,
    "balance",    &bal_ui,
    NULL);

  /* 分界与过渡：默认 0.3 / 0.7；Blending 100 → 各 ±0.25；
   * Balance ±100 → 两条分界一起平移 ±0.25（正 = 高光范围扩大）。
   * Splits 0.3/0.7 by default; Blending 100 -> +-0.25 feather each;
   * Balance +-100 shifts both splits by +-0.25 (positive favours highlights). */
  gfloat feather = CLAMP(blend_ui, 0.0, 100.0) * 0.0025f;
  gfloat shift   = CLAMP(bal_ui, -100.0, 100.0) * 0.0025f;
  gfloat split1  = 0.30f - shift;   /* 阴影 / 中间调 */
  gfloat split2  = 0.70f - shift;   /* 中间调 / 高光 */

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row = { roi->x, roi->y + y, roi->width, 1 };
    gegl_buffer_get(in_buf, &row, 1.0f, perceptual_format(op),
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint p = x * 4;
      gfloat r = in_line[p+0];
      gfloat g = in_line[p+1];
      gfloat b = in_line[p+2];
      gfloat a = in_line[p+3];

      /* 亮度带判定：Rec.709 luma（伽马域）
       * band classification: Rec.709 luma in the gamma domain */
      gfloat L = 0.2126f * r + 0.7152f * g + 0.0722f * b;
      L = CLAMP(L, 0.0f, 1.0f);

      gfloat w_sh = 1.0f - smooth_step(L, split1 - feather, split1 + feather);
      gfloat w_hi = smooth_step(L, split2 - feather, split2 + feather);
      gfloat w_md = CLAMP(1.0f - w_sh - w_hi, 0.0f, 1.0f);

      /* RGB → HSV（hsl-seven 同款转换，cmax/cmin）
       * RGB -> HSV, same cmax/cmin conversion as hsl-seven */
      gfloat cmax = MAX(MAX(r, g), b);
      gfloat cmin = MIN(MIN(r, g), b);
      gfloat delta = cmax - cmin;
      gfloat v = cmax;
      gfloat s = (cmax > 0.0f) ? delta / cmax : 0.0f;
      gfloat h = 0.0f;
      if (delta > 0.0f) {
        if (cmax == r)
          h = (g - b) / delta;
        else if (cmax == g)
          h = 2.0f + (b - r) / delta;
        else
          h = 4.0f + (r - g) / delta;
        h /= 6.0f;
        if (h < 0.0f) h += 1.0f;
      }

      /* 全局轮盘（权重 1）→ 三个亮度带
       * global wheel (weight 1), then the three tonal ranges */
      apply_wheel(&h, &s, &v, g_hue, g_sat, g_lum, 1.0f);
      apply_wheel(&h, &s, &v, s_hue, s_sat, s_lum, w_sh);
      apply_wheel(&h, &s, &v, m_hue, m_sat, m_lum, w_md);
      apply_wheel(&h, &s, &v, h_hue, h_sat, h_lum, w_hi);

      hsv_clamp(&h, &s, &v);
      hsv_to_rgb(h, s, v, &r, &g, &b);

      out_line[p+0] = r;
      out_line[p+1] = g;
      out_line[p+2] = b;
      out_line[p+3] = a;
    }

    gegl_buffer_set(out_buf, &row, 0, perceptual_format(op),
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
    "name",            "lb:color-grading",
    "title",           _("Color Grading"),
    "description",     _("Shadows Midtones Highlights Global color wheels with Luminance, Blending and Balance"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Color Grading"),
    NULL);
}

#endif
