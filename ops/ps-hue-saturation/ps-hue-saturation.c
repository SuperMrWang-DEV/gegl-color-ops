/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:ps-hue-saturation
 * menu       Hue/Saturation (Basic)
 * purpose    三滑杆公式：全局色相旋转、饱和度相对缩放、明度向白/黑混合。
 *            Three-slider formula: global hue rotation, relative saturation
 *            scaling, lightness as a blend toward white/black.
 * algorithm  规范来源是 tools/ref_ps_hue_sat.py（用户给定 Python 代码的逐字
 *            转写 + 浮点版对照），处理链四步：
 *            Normative reference: tools/ref_ps_hue_sat.py, four steps:
 *            ① 明度：逐通道与中性灰做 screen(t>0) / multiply(t<0)，
 *               代数上等于 c' = c + t(1-c) 与 c' = c(1+t)，t = lightness/100。
 *               Lightness: screen / multiply against a neutral grey, i.e.
 *               c + t(1-c) for t>0, c(1+t) for t<0.
 *            ② 转 HSL（标准 HSL，与 colorsys.rgb_to_hls 同式）。
 *            ③ 色相：h' = (h + hue) mod 360。
 *            ④ 饱和度：x = saturation/100，x>0 时 s' = s/(1-x)，x<0 时
 *               s' = s(1+x)，再钳到 [0,1]。
 *               Saturation: s/(1-x) for x>0, s(1+x) for x<0, clamped.
 *
 *            与原代码的两处**有意**差别（都不是算法语义，是实现缺陷）：
 *            Two deliberate deviations, both implementation defects rather
 *            than algorithm semantics:
 *            (a) 原代码把 h 取整到 1°、s/l 取整到 1% 再算，输出又 int() 截断；
 *                实测这层量化平均偏暗 1.7 码、最大 9 码（tools/ref_ps_hue_sat.py
 *                的 breakdown 函数）。
 *                本算子全程浮点，量化误差交给 GEGL 的输出格式处理。
 *                The original rounds h to 1 deg and s/l to 1 %, then truncates
 *                the 8-bit output: measured mean -1.7 codes, max 9. This op
 *                stays in float throughout.
 *            (b) x = +1 时原式 s/(1-1) 除零（原代码直接抛 ZeroDivisionError）。
 *                数学极限是 +inf 后被 clamp 到 1，故本算子取「s>0 即满饱和」。
 *                At x = +1 the original divides by zero; the limit is full
 *                saturation, which is what this op returns.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  tools/ref_ps_hue_sat.py
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_double (hue, _("Hue"), 0.0)
   description (_("Rotate the hue of every pixel, in degrees; wraps around the "
                  "hue circle"))
   value_range (-180.0, 180.0)
   ui_range    (-180.0, 180.0)

property_double (saturation, _("Saturation"), 0.0)
   description (_("Relative saturation, in percent: +100 drives any coloured "
                  "pixel to full saturation, -100 to grey"))
   value_range (-100.0, 100.0)
   ui_range    (-100.0, 100.0)

property_double (lightness, _("Lightness"), 0.0)
   description (_("Lightness in percent: positive blends toward white, negative "
                  "toward black, channel by channel"))
   value_range (-100.0, 100.0)
   ui_range    (-100.0, 100.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_ps_hue_saturation
#define GEGL_OP_C_SOURCE ps-hue-saturation.c

#include "gegl-op.h"

/* ---- 辅助函数 / helpers ------------------------------------------------ */

static inline gfloat
wrap_degrees (gfloat d)
{
  d = fmodf (d, 360.0f);
  if (d < 0.0f)
    d += 360.0f;
  return d;
}

/* HSL 的色相分段插值，与 colorsys.hls_to_rgb 同式
 * Hue sector interpolation, same as colorsys.hls_to_rgb. */
static inline gfloat
hue_channel (gfloat m1, gfloat m2, gfloat h)
{
  if (h < 0.0f)
    h += 360.0f;
  else if (h >= 360.0f)
    h -= 360.0f;

  if (h < 60.0f)
    return m1 + (m2 - m1) * h / 60.0f;
  if (h < 180.0f)
    return m2;
  if (h < 240.0f)
    return m1 + (m2 - m1) * (240.0f - h) / 60.0f;
  return m1;
}

static inline void
rgb_to_hsl (gfloat r, gfloat g, gfloat b,
            gfloat *hue, gfloat *sat, gfloat *lig)
{
  gfloat max   = MAX (r, MAX (g, b));
  gfloat min   = MIN (r, MIN (g, b));
  gfloat delta = max - min;
  gfloat sum   = max + min;
  gfloat h = 0.0f, s = 0.0f, l = sum * 0.5f;

  if (delta > 1.0e-6f && sum > 1.0e-6f)
    {
      if (l <= 0.5f)
        s = delta / sum;
      else
        s = delta / (2.0f - sum);

      if (max == r)
        h = (g - b) / delta + (g < b ? 6.0f : 0.0f);
      else if (max == g)
        h = (b - r) / delta + 2.0f;
      else
        h = (r - g) / delta + 4.0f;

      h *= 60.0f;
    }

  *hue = wrap_degrees (h);
  *sat = CLAMP (s, 0.0f, 1.0f);
  *lig = CLAMP (l, 0.0f, 1.0f);
}

static inline void
hsl_to_rgb (gfloat h, gfloat s, gfloat l,
            gfloat *r, gfloat *g, gfloat *b)
{
  if (s <= 1.0e-6f)
    {
      *r = *g = *b = l;
      return;
    }

  {
    gfloat m2 = (l <= 0.5f) ? l * (1.0f + s) : l + s - l * s;
    gfloat m1 = 2.0f * l - m2;

    *r = hue_channel (m1, m2, h + 120.0f);
    *g = hue_channel (m1, m2, h);
    *b = hue_channel (m1, m2, h - 120.0f);
  }
}

/* 明度：与中性灰做 screen / multiply。展开后就是向白/黑插值。
 *  t = +1 → 全白，t = -1 → 全黑，两端都落在合法色域内。
 * Lightness: screen / multiply with a neutral grey, i.e. a lerp toward
 * white / black. t = +1 gives white, t = -1 gives black. */
static inline gfloat
apply_lightness (gfloat c, gfloat t)
{
  if (t > 0.0f)
    return c + t * (1.0f - c);
  if (t < 0.0f)
    return c * (1.0f + t);
  return c;
}

/* 饱和度：x>0 走 s/(1-x)（双曲放大），x<0 走 s(1+x)（线性收缩）。
 *  x=+1 在原式里是除零；极限为 +inf 再钳到 1，故取「s>0 即满饱和」。
 * Saturation: s/(1-x) for x>0 (hyperbolic), s(1+x) for x<0 (linear).
 * x=+1 divides by zero in the original; its limit is full saturation. */
static inline gfloat
scale_saturation (gfloat s, gfloat x)
{
  if (x >= 1.0f)
    return (s > 0.0f) ? 1.0f : 0.0f;
  if (x > 0.0f)
    return MIN (1.0f, s / (1.0f - x));
  if (x < 0.0f)
    return MAX (0.0f, s * (1.0f + x));
  return s;
}

/* ---- 算子定义 / operation ---------------------------------------------- */

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");

  /* 感知（非线性）RGB：公式里的 screen / multiply 是在 0…255 的编码值上做的，
   * 换到线性光下会得到完全不同的明度曲线。
   * Perceptual (non-linear) RGB: the formula's screen / multiply works on
   * 0..255 encoded values; linear light would give a different curve. */
  gegl_operation_set_format (operation, "input",
                             babl_format_with_space ("R~G~B~A float", space));
  gegl_operation_set_format (operation, "output",
                             babl_format_with_space ("R~G~B~A float", space));
}

static gboolean
process (GeglOperation       *operation,
         void                *in_buf,
         void                *out_buf,
         glong                n_pixels,
         const GeglRectangle *roi,
         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (operation);
  gfloat * GEGL_ALIGNED in_pixel  = in_buf;
  gfloat * GEGL_ALIGNED out_pixel = out_buf;

  const gfloat t_light = (gfloat) o->lightness / 100.0f;
  const gfloat hue_add = (gfloat) o->hue;
  const gfloat sat_x   = (gfloat) o->saturation / 100.0f;

  glong i;

  if (t_light == 0.0f && hue_add == 0.0f && sat_x == 0.0f)
    {
      memcpy (out_buf, in_buf, (size_t) n_pixels * 4 * sizeof (gfloat));
      return TRUE;
    }

  for (i = 0; i < n_pixels; i++)
    {
      gfloat r = CLAMP (in_pixel[0], 0.0f, 1.0f);
      gfloat g = CLAMP (in_pixel[1], 0.0f, 1.0f);
      gfloat b = CLAMP (in_pixel[2], 0.0f, 1.0f);
      gfloat h, s, l;

      /* ① 明度先进 RGB —— 这一步会连带改掉 S，后续饱和度作用在新 S 上
       * (1) lightness goes into RGB first, which also changes S; the
       *     saturation below therefore acts on the shifted S. */
      if (t_light != 0.0f)
        {
          r = apply_lightness (r, t_light);
          g = apply_lightness (g, t_light);
          b = apply_lightness (b, t_light);
        }

      /* ② 转 HSL */
      rgb_to_hsl (r, g, b, &h, &s, &l);

      /* ③ 色相旋转 */
      if (hue_add != 0.0f)
        h = wrap_degrees (h + hue_add);

      /* ④ 饱和度相对缩放 */
      if (sat_x != 0.0f)
        s = scale_saturation (s, sat_x);

      hsl_to_rgb (h, s, l, &out_pixel[0], &out_pixel[1], &out_pixel[2]);
      out_pixel[3] = in_pixel[3];

      in_pixel  += 4;
      out_pixel += 4;
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass            *operation_class    = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointFilterClass *point_filter_class = GEGL_OPERATION_POINT_FILTER_CLASS (klass);

  operation_class->prepare    = prepare;
  point_filter_class->process = process;

  gegl_operation_class_set_keys (operation_class,
                                 "name",            "lb:ps-hue-saturation",
                                 "title",           _("Hue/Saturation (Basic)"),
                                 "categories",      "color:enhance",
                                 "description",     _("Hue rotation, relative saturation scaling "
                                                      "and lightness blended toward white/black."),
                                 "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Color",
                                 "gimp:menu-label", _("Hue/Saturation (Basic)"),
                                 NULL);
}

#endif
