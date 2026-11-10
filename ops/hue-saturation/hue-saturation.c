/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hue-saturation
 * menu       Hue/Saturation
 * purpose    全局或按红/黄/绿/青/蓝/品红六个色相区间调整色相、饱和度、明度
 *            Adjust hue, saturation and lightness globally, or inside six hue
 *            ranges (red, yellow, green, cyan, blue, magenta).
 * algorithm  RGB → HSL → 偏移 H/S/L → RGB；六区间按三角色相权重混合，overlap
 *            控制区间互相渗透的宽度；无彩像素跳过，避免灰阶染色
 *            RGB -> HSL, add the H/S/L offsets, back to RGB. The six ranges
 *            are blended with triangular hue weights, and 'overlap' sets how
 *            far each range bleeds into its neighbours. Achromatic pixels are
 *            skipped so greys are never tinted.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  GIMP 内置「色相-饱和度」（HSL 空间重写）
 *            GIMP Hue-Saturation dialog, reimplemented in HSL space
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_double (hue, _("Hue"), 0.0)
   description (_("Rotate the hue of every pixel, in degrees"))
   value_range (-180.0, 180.0)
   ui_range    (-180.0, 180.0)

property_double (saturation, _("Saturation"), 0.0)
   description (_("Add to the HSL saturation of every pixel"))
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (lightness, _("Lightness"), 0.0)
   description (_("Add to the HSL lightness of every pixel"))
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (overlap, _("Range overlap"), 0.0)
   description (_("How far each of the six hue ranges reaches into its neighbours: "
                  "0 = the ranges tile the hue circle exactly and each centre gets its "
                  "full setting, 1 = wide soft blending that also dilutes the peak strength"))
   value_range (0.0, 1.0)
   ui_range    (0.0, 1.0)

property_double (red_hue, _("Red hue"), 0.0)
   description (_("Hue shift applied to the red range, in degrees"))
   value_range (-180.0, 180.0)
   ui_range    (-180.0, 180.0)

property_double (red_saturation, _("Red saturation"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (red_lightness, _("Red lightness"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (yellow_hue, _("Yellow hue"), 0.0)
   description (_("Hue shift applied to the yellow range, in degrees"))
   value_range (-180.0, 180.0)
   ui_range    (-180.0, 180.0)

property_double (yellow_saturation, _("Yellow saturation"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (yellow_lightness, _("Yellow lightness"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (green_hue, _("Green hue"), 0.0)
   description (_("Hue shift applied to the green range, in degrees"))
   value_range (-180.0, 180.0)
   ui_range    (-180.0, 180.0)

property_double (green_saturation, _("Green saturation"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (green_lightness, _("Green lightness"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (cyan_hue, _("Cyan hue"), 0.0)
   description (_("Hue shift applied to the cyan range, in degrees"))
   value_range (-180.0, 180.0)
   ui_range    (-180.0, 180.0)

property_double (cyan_saturation, _("Cyan saturation"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (cyan_lightness, _("Cyan lightness"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (blue_hue, _("Blue hue"), 0.0)
   description (_("Hue shift applied to the blue range, in degrees"))
   value_range (-180.0, 180.0)
   ui_range    (-180.0, 180.0)

property_double (blue_saturation, _("Blue saturation"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (blue_lightness, _("Blue lightness"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (magenta_hue, _("Magenta hue"), 0.0)
   description (_("Hue shift applied to the magenta range, in degrees"))
   value_range (-180.0, 180.0)
   ui_range    (-180.0, 180.0)

property_double (magenta_saturation, _("Magenta saturation"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

property_double (magenta_lightness, _("Magenta lightness"), 0.0)
   value_range (-1.0, 1.0)
   ui_range    (-1.0, 1.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_hue_saturation
#define GEGL_OP_C_SOURCE hue-saturation.c

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

/* 感知 RGB（假定输入在 [0,1]）→ H∈[0,360)，S/L∈[0,1]
 * perceptual RGB (input assumed in [0,1]) -> H in [0,360), S/L in [0,1] */
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

/* 六个色相区间的三角权重，归一化后之和为 1。half_width 以度为单位，取 60
 * 以上即可完整覆盖整个色环
 * Triangular weights for the six hue ranges, normalised to sum to 1.
 * half_width is in degrees; 60 or more guarantees full coverage of the hue
 * circle. */
static inline void
hue_weights (gfloat hue, gfloat half_width, gfloat w[6])
{
  gfloat sum = 0.0f;
  gint   i;

  for (i = 0; i < 6; i++)
    {
      gfloat d = fabsf (hue - (gfloat) i * 60.0f);

      if (d > 180.0f)
        d = 360.0f - d;

      w[i] = MAX (0.0f, 1.0f - d / half_width);
      sum += w[i];
    }

  if (sum > 1.0e-6f)
    {
      gfloat inv = 1.0f / sum;
      for (i = 0; i < 6; i++)
        w[i] *= inv;
    }
  else
    {
      /* 退化兜底：归到最近的区间
       * degenerate fallback: snap to the nearest range */
      gint nearest = (gint) (wrap_degrees (hue + 30.0f) / 60.0f) % 6;
      for (i = 0; i < 6; i++)
        w[i] = (i == nearest) ? 1.0f : 0.0f;
    }
}

/* ---- 算子定义 / operation ---------------------------------------------- */

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");

  /* 感知（非线性）RGB：色相/饱和度的运算不能放在线性光下做，否则中间调会相
   * 对 GIMP 滤镜反向偏移
   * Perceptual (non-linear) RGB: hue/saturation maths must not run in
   * linear light, otherwise mid-tones shift the wrong way compared with
   * GIMP's filter. */
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

  const gfloat master_hue = (gfloat) o->hue;
  const gfloat master_sat = (gfloat) o->saturation;
  const gfloat master_lig = (gfloat) o->lightness;

  const gfloat range_hue[6] = { (gfloat) o->red_hue,  (gfloat) o->yellow_hue,
                                (gfloat) o->green_hue, (gfloat) o->cyan_hue,
                                (gfloat) o->blue_hue, (gfloat) o->magenta_hue };
  const gfloat range_sat[6] = { (gfloat) o->red_saturation,  (gfloat) o->yellow_saturation,
                                (gfloat) o->green_saturation, (gfloat) o->cyan_saturation,
                                (gfloat) o->blue_saturation, (gfloat) o->magenta_saturation };
  const gfloat range_lig[6] = { (gfloat) o->red_lightness,  (gfloat) o->yellow_lightness,
                                (gfloat) o->green_lightness, (gfloat) o->cyan_lightness,
                                (gfloat) o->blue_lightness, (gfloat) o->magenta_lightness };

  /* half_width 取 60° 时六个区间刚好无缝铺满色环；overlap 让它们变宽，相邻
   * 区间互相渗透
   * half_width 60deg makes the six ranges tile the hue circle exactly;
   * overlap widens them so neighbours blend into each other. */
  const gfloat half_width = 60.0f * (1.0f + (gfloat) o->overlap);

  gboolean per_range = FALSE;
  gboolean identity  = (master_hue == 0.0f && master_sat == 0.0f && master_lig == 0.0f);
  gint     k;
  glong    i;

  for (k = 0; k < 6; k++)
    if (range_hue[k] != 0.0f || range_sat[k] != 0.0f || range_lig[k] != 0.0f)
      per_range = TRUE;

  if (! per_range && identity)
    {
      /* 无需处理：直接拷贝，alpha 保持不变
       * nothing to do: a plain copy keeps alpha untouched */
      memcpy (out_buf, in_buf, (size_t) n_pixels * 4 * sizeof (gfloat));
      return TRUE;
    }

  for (i = 0; i < n_pixels; i++)
    {
      gfloat r = CLAMP (in_pixel[0], 0.0f, 1.0f);
      gfloat g = CLAMP (in_pixel[1], 0.0f, 1.0f);
      gfloat b = CLAMP (in_pixel[2], 0.0f, 1.0f);
      gfloat h, s, l;
      gfloat dh = master_hue;
      gfloat ds = master_sat;
      gfloat dl = master_lig;

      rgb_to_hsl (r, g, b, &h, &s, &l);

      if (per_range)
        {
          gfloat w[6];

          hue_weights (h, half_width, w);

          for (k = 0; k < 6; k++)
            {
              dh += w[k] * range_hue[k];
              ds += w[k] * range_sat[k];
              dl += w[k] * range_lig[k];
            }
        }

      if (s < 1.0e-5f)
        {
          /* 无彩像素：色相没有意义，保持原来的灰
           * achromatic pixel: hue is meaningless, keep it grey */
          dh = 0.0f;
          ds = 0.0f;
        }

      h = wrap_degrees (h + dh);
      s = CLAMP (s + ds, 0.0f, 1.0f);
      l = CLAMP (l + dl, 0.0f, 1.0f);

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
                                 "name",            "lb:hue-saturation",
                                 "title",           _("Hue/Saturation"),
                                 "categories",      "color:enhance",
                                 "description",     _("Adjust hue, saturation and lightness in HSL, "
                                                      "globally or per hue range (red/yellow/green/cyan/blue/magenta)."),
                                 "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
                                 "gimp:menu-label", _("Hue/Saturation"),
                                 NULL);
}

#endif
