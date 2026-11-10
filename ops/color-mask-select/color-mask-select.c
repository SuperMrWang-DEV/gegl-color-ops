/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:color-mask-select
 * menu       Mask by Color
 * purpose    PS 色彩范围：按指定色 + 容差 + 羽化生成蒙版，可红色叠加预览
 *            PS Color Range: build a mask from a picked colour, a fuzziness
 *            radius and feathering, with an optional red overlay preview.
 * algorithm  九组预设色或图像取色 → 色距判定 → fuzziness / feather 生成 alpha
 *            Nine preset colours or a colour sampled from the image ->
 *            distance test -> alpha from 'fuzziness' and 'feather'.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  Photoshop「色彩范围」(Color Range)
 *            Photoshop Color Range
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_enum (mask_mode, _("Selection Mode"),
               MaskSelectType, mask_select_type_enum, MASK_RED)
    description (_("Color selection mode"))

enum_start (mask_select_type_enum)
  enum_value (MASK_RED,      "red",      N_("Red"))
  enum_value (MASK_GREEN,    "green",    N_("Green"))
  enum_value (MASK_BLUE,     "blue",     N_("Blue"))
  enum_value (MASK_CYAN,     "cyan",     N_("Cyan"))
  enum_value (MASK_MAGENTA,  "magenta",  N_("Magenta"))
  enum_value (MASK_YELLOW,   "yellow",   N_("Yellow"))
  enum_value (MASK_WHITE,    "white",    N_("Highlights"))
  enum_value (MASK_BLACK,    "black",    N_("Shadows"))
  enum_value (MASK_GRAY,     "gray",     N_("Midtones"))
  enum_value (MASK_CUSTOM,   "custom",   N_("Custom Picked Color"))
enum_end (MaskSelectType)

property_color (custom_color, _("Custom Color"), "rgba(1.0, 0.0, 0.0, 1.0)")
    description (_("Color picked from image"))

property_boolean (preview_red_mask, _("Red Overlay Preview"), TRUE)
    description (_("Show red overlay like Photoshop"))

property_double (fuzziness, _("Fuzziness"), 50.0)
    value_range (0.0, 200.0)
    ui_range (0.0, 200.0)

property_double (feather, _("Feather"), 10.0)
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (saturation_min, _("Min Saturation"), 0.0)
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_color_mask_select
#define GEGL_OP_C_SOURCE color-mask-select.c

#include "gegl-op.h"

static inline void
rgb_to_hsv(gfloat r, gfloat g, gfloat b, gfloat *h, gfloat *s, gfloat *v)
{
  gfloat cmax = MAX(MAX(r, g), b);
  gfloat cmin = MIN(MIN(r, g), b);
  gfloat delta = cmax - cmin;

  *v = cmax;
  *s = (cmax > 0) ? delta / cmax : 0.0f;
  *h = 0.0f;

  if (delta > 0) {
    if (cmax == r)
      *h = (g - b) / delta;
    else if (cmax == g)
      *h = 2.0f + (b - r) / delta;
    else
      *h = 4.0f + (r - g) / delta;

    *h /= 6.0f;
    if (*h < 0) *h += 1.0f;
  }
}

static inline gfloat
color_dist(gfloat r1, gfloat g1, gfloat b1, gfloat r2, gfloat g2, gfloat b2)
{
  gfloat dr = r1 - r2;
  gfloat dg = g1 - g2;
  gfloat db = b1 - b2;
  return sqrtf(dr*dr + dg*dg + db*db);
}

static inline gfloat
smooth_step(gfloat val, gfloat a, gfloat b)
{
  if (val < a) return 0.0f;
  if (val > b) return 1.0f;
  gfloat t = (val - a) / (b - a);
  return t * t * (3.0f - 2.0f * t);
}

/* 感知（非线性）格式：公式按 8bit sRGB 伽马域推导，必须拿伽马值，否则 babl
 * 会喂线性光，数值与 PS 对不上
 * Perceptual (non-linear) format: the maths was derived in the 8-bit sRGB
 * gamma domain. Linear light from babl would drift away from Photoshop. */
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

  MaskSelectType mode;
  GeglColor *custom_color;
  gboolean preview_red;
  gdouble fuzz, feather, sat_min;

  g_object_get(G_OBJECT(op),
    "mask-mode", &mode,
    "custom-color", &custom_color,
    "preview-red-mask", &preview_red,
    "fuzziness", &fuzz,
    "feather", &feather,
    "saturation-min", &sat_min,
    NULL);

  gdouble cr, cg, cb;
  gegl_color_get_rgba(custom_color, &cr, &cg, &cb, NULL);
  g_object_unref(custom_color);

  gfloat fz = fuzz * 0.01f;
  gfloat ft = feather * 0.01f;
  gfloat st = sat_min * 0.01f;

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
      gfloat h, s, v;

      rgb_to_hsv(r, g, b, &h, &s, &v);

      gfloat score = 0.0f;

      switch (mode)
      {
        case MASK_RED:
          score = r - MAX(g, b);
          break;
        case MASK_GREEN:
          score = g - MAX(r, b);
          break;
        case MASK_BLUE:
          score = b - MAX(r, g);
          break;
        case MASK_CYAN:
          score = MIN(g, b) - r;
          break;
        case MASK_MAGENTA:
          score = MIN(r, b) - g;
          break;
        case MASK_YELLOW:
          score = MIN(r, g) - b;
          break;
        case MASK_WHITE:
          score = v - 0.5f;
          break;
        case MASK_BLACK:
          score = 0.5f - v;
          break;
        case MASK_GRAY:
          score = 1.0f - (fabsf(r-g) + fabsf(g-b) + fabsf(r-b)) * 0.5f;
          break;
        case MASK_CUSTOM:
          score = 1.0f - color_dist(r, g, b, cr, cg, cb);
          break;
        default:
          score = 0.0f;
      }

      gfloat sat_ok  = smooth_step(s, st * 0.5f, st);
      gfloat alpha   = smooth_step(score, -fz * ft, fz);
      alpha = CLAMP(alpha * sat_ok, 0.0f, 1.0f);

      if (preview_red) {
        out_line[p+0] = r * (1.0f - alpha) + 1.0f * alpha;
        out_line[p+1] = g * (1.0f - alpha) + 0.0f * alpha;
        out_line[p+2] = b * (1.0f - alpha) + 0.0f * alpha;
        out_line[p+3] = 1.0f;
      } else {
        out_line[p+0] = r;
        out_line[p+1] = g;
        out_line[p+2] = b;
        out_line[p+3] = alpha;
      }
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
    "name",            "lb:color-mask-select",
    "title",           _("Color Mask Select"),
    "description",     _("Photoshop Color Range with color picker & red overlay"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Mask by Color"),
    NULL);
}

#endif