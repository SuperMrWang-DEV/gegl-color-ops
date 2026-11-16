/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:colorize-hsl
 * menu       Colorize
 * purpose    复刻 经典图像编辑器「色相/饱和度」里的「着色」复选框
 *            Reproduce the Colorize checkbox of the classic editor's Hue/Saturation.
 * algorithm  RGB → HSL 只取 L → 按明度滑杆改 L → 用滑杆的 H/S 与原 L 回 RGB。
 *            像素原有的色相与饱和度被完全丢弃，只保留明暗结构。
 *            Take L from HSL, move it with the lightness slider, then convert
 *            back with the slider's H/S. The pixel's own hue and saturation are
 *            discarded entirely; only its lightness survives.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  classic image editor 26.10.0 Hue/Saturation + Colorize，实测标定见
 *            ../colorize-cal/RESULTS.md
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (hue, _("Hue"), 0.0) \
    description (_("Absolute hue of the tint, in degrees. The slider clamps at "
                   "0 and 360, it does not wrap: -20 gives red, not 340.")) \
    value_range (0.0, 360.0) \
    ui_range (0.0, 360.0)

property_double (saturation, _("Saturation"), 25.0) \
    description (_("Absolute HSL saturation of the tint, in percent")) \
    value_range (0.0, 100.0) \
    ui_range (0.0, 100.0)

property_double (lightness, _("Lightness"), 0.0) \
    description (_("Moves HSL lightness: positive pulls towards white, "
                   "negative towards black")) \
    value_range (-100.0, 100.0) \
    ui_range (-100.0, 100.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_colorize_hsl
#define GEGL_OP_C_SOURCE colorize-hsl.c
#include "gegl-op.h"

static inline gfloat
clamp01 (gfloat v)
{
  if (!isfinite (v))
    return 0.0f;
  if (v < 0.0f)
    return 0.0f;
  if (v > 1.0f)
    return 1.0f;
  return v;
}

/* ---- 只要 HSL 的 L / HSL lightness only --------------------------------
 * 着色把 H 与 S 整个换掉，所以输入唯一还用得上的就是 L = (max+min)/2。
 * Colorize replaces H and S outright, so the only thing carried over from
 * the input is L = (max + min) / 2.
 */
static inline gfloat
hsl_lightness (gfloat r, gfloat g, gfloat b)
{
  gfloat mx = MAX (MAX (r, g), b);
  gfloat mn = MIN (MIN (r, g), b);
  return (mx + mn) * 0.5f;
}

/* ---- HSL → RGB --------------------------------------------------------- */
static inline void
hsl_to_rgb (gfloat h, gfloat s, gfloat l,
            gfloat *r_out, gfloat *g_out, gfloat *b_out)
{
  gfloat c  = (1.0f - fabsf (2.0f * l - 1.0f)) * s;
  gfloat hp = h / 60.0f;
  gfloat x  = c * (1.0f - fabsf (fmodf (hp, 2.0f) - 1.0f));
  gfloat m  = l - c * 0.5f;
  gfloat r, g, b;

  if      (hp < 1.0f) { r = c;   g = x;   b = 0.0f; }
  else if (hp < 2.0f) { r = x;   g = c;   b = 0.0f; }
  else if (hp < 3.0f) { r = 0.0f; g = c;  b = x;    }
  else if (hp < 4.0f) { r = 0.0f; g = x;  b = c;    }
  else if (hp < 5.0f) { r = x;   g = 0.0f; b = c;   }
  else                { r = c;   g = 0.0f; b = x;   }

  *r_out = r + m;
  *g_out = g + m;
  *b_out = b + m;
}

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");

  /* 公式是在 sRGB 伽马刻度上标定的，必须拿感知（非线性）格式；线性光会跑偏
   * The model was calibrated on gamma-encoded sRGB, so ask for a perceptual
   * (non-linear) format; linear light would drift. */
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

  /* 色相滑杆在着色模式下是绝对值，且两端是钳位不是回绕：实测 -20 给出纯红
   * The hue slider is absolute in colorize mode and clamps instead of
   * wrapping: -20 measures as pure red, not 340. */
  gfloat h = (gfloat) CLAMP (o->hue, 0.0, 360.0);
  gfloat s = (gfloat) CLAMP (o->saturation, 0.0, 100.0) * 0.01f;
  gfloat t = (gfloat) CLAMP (o->lightness, -100.0, 100.0) * 0.01f;

  if (h >= 360.0f)
    h = 0.0f;

  for (glong i = 0; i < n_pixels; i++)
    {
      gfloat L  = hsl_lightness (in_pixel[0], in_pixel[1], in_pixel[2]);
      /* 明度滑杆：正向往白拉，负向往黑压。两条都是 L 的线性函数，中点
       * L=0.5 时位移正好是 t/2，终点不动 —— 与实测逐点一致。
       * Lightness: positive pulls toward white, negative toward black. Both
       * are linear in L; at L=0.5 the shift is exactly t/2 and the end point
       * stays put, which is what the measurements show. */
      gfloat Lp = (t > 0.0f) ? L + t * (1.0f - L) : L * (1.0f + t);
      gfloat r, g, b;

      hsl_to_rgb (h, s, Lp, &r, &g, &b);

      out_pixel[0] = clamp01 (r);
      out_pixel[1] = clamp01 (g);
      out_pixel[2] = clamp01 (b);
      out_pixel[3] = in_pixel[3];

      in_pixel  += 4;
      out_pixel += 4;
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointFilterClass *fclass = GEGL_OPERATION_POINT_FILTER_CLASS (klass);

  oclass->prepare = prepare;
  fclass->process = process;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:colorize-hsl",
    "title",           _("Colorize"),
    "description",     _("the classic editor's Colorize: keep the HSL lightness of each "
                         "pixel, replace hue and saturation with the slider "
                         "values."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Color",
    "gimp:menu-label", _("Colorize"),
    NULL);
}

#endif
