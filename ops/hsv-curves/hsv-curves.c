/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsv-curves
 * menu       HSV Curves
 * purpose    HSV 三通道各自一条曲线（色相用偏移曲线）
 *            One curve per HSV component; hue uses an offset curve.
 * algorithm  在 babl "HSVA float" 上逐通道查曲线：H 0…360（环形，走偏移
 *            曲线）、S / V 0…100。与 lb:hsv-dual 同一套 babl 口径。
 *            Per-channel lookup on babl HSVA: H spans 0…360 and is circular
 *            (offset curve), S and V span 0…100. Same babl basis as
 *            lb:hsv-dual.
 * note       饱和度为 0 的像素色相无意义，色相曲线不作用在它们身上。
 *            Hue is meaningless at zero saturation, so the hue curve skips
 *            those pixels.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_string (curves, _("Curves"), "")
  description (_("Control points for the H, S and V components, as "
                 "\"H 0,0.5 1,0.5|S 0,0 0.5,0.55 1,1|V 0,0 1,1\". "
                 "The hue curve is an offset curve: 0.5 on the vertical axis "
                 "means no shift. An omitted component stays unchanged. The "
                 "interactive dialog writes this string and reads it back, so "
                 "the adjustment stays editable."))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_hsv_curves
#define GEGL_OP_C_SOURCE hsv-curves.c
#include "gegl-op.h"

#include "curve.h"

/* babl 的 HSVA 内部是 0…1，不是 0…360/100（对照 color-levels.h 的 scale
 * 字段：360/100 是「属性单位 ÷ 内部单位」）。直接按 0…1 写，省一次乘除，
 * 也让色相的 mod 1 折回与偏移曲线天然同口径。
 * babl keeps HSVA in 0…1, not 0…360/100 — the 360/100 in color-levels.h is
 * the ratio between property units and these internal units. Working in 0…1
 * saves a multiply and matches the mod-1 wrap of the hue offset curve. */
#define HSV_LO    0.0f
#define HSV_HI    1.0f

static const gchar *const hsv_names[3] = { "H", "S", "V" };

static inline gfloat
hsv_norm (gfloat v)
{
  return CLAMP (v, HSV_LO, HSV_HI);
}

static inline gfloat
hsv_denorm (gfloat t)
{
  return CLAMP (t, HSV_LO, HSV_HI);
}

static void
prepare (GeglOperation *op)
{
  gegl_operation_set_format (op, "input",  babl_format ("HSVA float"));
  gegl_operation_set_format (op, "output", babl_format ("HSVA float"));
}

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *in_buf,
         GeglBuffer          *out_buf,
         const GeglRectangle *roi,
         gint                 level)
{
  LbCurve curves[3];
  gchar  *text = NULL;

  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  /* 数组顺序是 H / S / V：色相走偏移曲线，另外两条是普通曲线
   * The array is ordered H / S / V: hue uses an offset curve. */
  lb_curve_offset_default (&curves[0]);
  lb_curve_identity (&curves[1]);
  lb_curve_identity (&curves[2]);

  g_object_get (G_OBJECT (op), "curves", &text, NULL);
  lb_curve_parse_set (curves, 3, hsv_names, text ? text : "");
  g_free (text);

  const Babl *fmt    = babl_format ("HSVA float");
  gint        stride = roi->width * 4;
  gfloat     *in_line  = g_new (gfloat, stride);
  gfloat     *out_line = g_new (gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };

    gegl_buffer_get (in_buf, &row_rect, 1.0f, fmt,
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    if (curves[0].identity && curves[1].identity && curves[2].identity)
    {
      memcpy (out_line, in_line, sizeof (gfloat) * stride);
    }
    else
    {
      for (gint x = 0; x < roi->width; x++)
      {
        gint   px = x * 4;
        gfloat H  = in_line[px + 0];
        gfloat S  = in_line[px + 1];
        gfloat V  = in_line[px + 2];
        gfloat a  = in_line[px + 3];

        if (a <= 0.0f)
        {
          out_line[px + 0] = H;
          out_line[px + 1] = S;
          out_line[px + 2] = V;
          out_line[px + 3] = 0.0f;
          continue;
        }

        out_line[px + 1] = hsv_denorm (
            lb_curve_at (&curves[1], hsv_norm (S)));
        out_line[px + 2] = hsv_denorm (
            lb_curve_at (&curves[2], hsv_norm (V)));

        /* 灰阶（S=0）没有色相，别给它随机换一个角
         * Grey has no hue; do not hand it a random angle. */
        out_line[px + 0] = (S > 1e-4f)
            ? lb_curve_offset_at (&curves[0], hsv_norm (H))
            : H;
        out_line[px + 3] = a;
      }
    }

    gegl_buffer_set (out_buf, &row_rect, 0, fmt,
                     out_line, GEGL_AUTO_ROWSTRIDE);
  }

  g_free (in_line);
  g_free (out_line);
  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  oclass->prepare = prepare;
  fclass->process = process;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:hsv-curves",
    "title",           _("HSV Curves"),
    "categories",      "color",
    "description",     _("Free-form curves for hue, saturation and value; "
                         "the hue curve shifts the ring without a seam"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Curves",
    "gimp:menu-label", _("HSV Curves"),
    NULL);
}

#endif
