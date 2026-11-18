/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:color-grading
 * menu       Color Grading
 * purpose    等价 经典 RAW 编辑器的「颜色分级」：阴影 / 中间调 / 高光 / 全局四个
 *            轮盘（色相 + 饱和度）加各自的明度滑杆，按亮度分带给画面上色。
 *            The classic RAW editors' Color Grading panel: Shadows / Midtones /
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
 *               - 明度滑杆：V += Lw·0.005·w（与 hsl-bands 同系数，±100 → ±0.5）；
 *               - 染色强度 t = Sat/100·w：往「同明度的轮盘纯色」混合，
 *                 rgb = rgb·(1−t) + tint·t，tint = HSV(轮盘色相, 1, V)。
 *                 灰像素于是自然吃到染色，与轮盘色接近互补的色相则去饱和，
 *                 色相上不做插值 → 没有「旋转方向翻转」的接缝（见 apply_wheel）。
 *            4. 全局轮盘权重恒为 1，先做；三个带再做。
 *
 *            该 RAW 编辑器无法在本机标定（未装其插件），分界 0.3/0.7、
 *            过渡 ±0.25、Rec.709 亮度等均为按公开行为设定的合理模型，
 *            不是黑盒实测值。
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  经典 RAW 编辑器的 Color Grading 面板
 *            classic RAW editors Color Grading panel
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

/* 一个轮盘（带权重 w）的一次染色。r/g/b 就地修改。
 * One wheel application with range weight w; r/g/b are modified in place.
 *
 * 染色 = 往像素里混入「同明度的轮盘纯色」：
 *   t    = Sat/100 × w              （混合比例）
 *   tint = HSV(轮盘色相, 1, 当前 V)  （保持明度结构，不改变黑白关系）
 *   rgb  = rgb·(1−t) + tint·t
 * 不在色相上做插值，因此不存在「互补色相处旋转方向翻转」的接缝——
 * 轮盘色与像素色接近互补时，混合自然会去饱和（掺灰），而不是绕半圈。
 * 这与轮盘「给画面加一层颜色」的物理语义一致。
 *
 * The tint is a plain mix towards the wheel colour at the pixel's own value:
 *   t    = Sat/100 * w,  tint = HSV(wheel hue, 1, current V)
 *   rgb  = rgb*(1-t) + tint*t
 * No hue interpolation, so no seam where the rotation direction flips for
 * complementary hues: mixing towards the complement desaturates, which is
 * what a wheel physically does to a picture. */
static inline void
apply_wheel(gfloat *r, gfloat *g, gfloat *b,
            gfloat hue_deg, gfloat sat_ui, gfloat lum_ui, gfloat w)
{
  if (w < 0.001f)
    return;

  gfloat rr = *r, gg = *g, bb = *b;
  gfloat cmax = MAX(MAX(rr, gg), bb);
  gfloat cmin = MIN(MIN(rr, gg), bb);
  gfloat delta = cmax - cmin;
  gfloat v = cmax;
  gfloat s = (cmax > 0.0f) ? delta / cmax : 0.0f;
  gfloat h = 0.0f;
  if (delta > 0.0f) {
    if (cmax == rr)
      h = (gg - bb) / delta;
    else if (cmax == gg)
      h = 2.0f + (bb - rr) / delta;
    else
      h = 4.0f + (rr - gg) / delta;
    h /= 6.0f;
    if (h < 0.0f) h += 1.0f;
  }

  /* 明度滑杆：±100 → V ±0.5（与 hsl-bands 的 lightness 系数一致）
   * Luminance slider: +-100 -> V +-0.5 (same coefficient as hsl-bands) */
  v = CLAMP(v + lum_ui * 0.005f * w, 0.0f, 1.0f);

  gfloat t = sat_ui * 0.01f * w;
  if (t < 0.001f)
  {
    hsv_to_rgb(h, s, v, &rr, &gg, &bb);
    *r = rr; *g = gg; *b = bb;
    return;
  }
  t = MIN(t, 1.0f);

  gfloat tr, tg, tb;
  hsv_to_rgb(hue_deg / 360.0f, 1.0f, v, &tr, &tg, &tb);

  /* 先把明度变化落回 RGB，再与轮盘色混合
   * apply the luminance change to RGB first, then mix the wheel colour in */
  hsv_to_rgb(h, s, v, &rr, &gg, &bb);
  *r = rr * (1.0f - t) + tr * t;
  *g = gg * (1.0f - t) + tg * t;
  *b = bb * (1.0f - t) + tb * t;
}

/* 感知（非线性）格式：公式按 8bit sRGB 伽马域推导，必须拿伽马值，否则 babl
 * 会喂线性光，数值对不上（同 hsl-bands / shadows-highlights）
 * Perceptual (non-linear) format, same as hsl-bands / shadows-highlights */
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

      /* 全局轮盘（权重 1）→ 三个亮度带
       * global wheel (weight 1), then the three tonal ranges */
      apply_wheel(&r, &g, &b, g_hue, g_sat, g_lum, 1.0f);
      apply_wheel(&r, &g, &b, s_hue, s_sat, s_lum, w_sh);
      apply_wheel(&r, &g, &b, m_hue, m_sat, m_lum, w_md);
      apply_wheel(&r, &g, &b, h_hue, h_sat, h_lum, w_hi);

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
    "gimp:menu-path",  "<Image>/SuperMrWang/Color",
    "gimp:menu-label", _("Color Grading"),
    NULL);
}

#endif
