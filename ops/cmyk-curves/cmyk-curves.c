/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:cmyk-curves
 * menu       CMYK Curves
 * purpose    CMYK 四版各自一条曲线
 *            One curve per ink plate.
 * algorithm  在 babl "CMYKA float" 上逐通道查曲线，每个分量 0…100（墨量）。
 *            与 lb:cmyk-levels / lb:cmyk-primary-correction 同一套 babl 分色
 *            口径（不是 ICC 特性文件，因此结果只在这个工作空间内自洽）。
 *            Per-plate curve lookup on babl CMYKA, each component 0…100 of
 *            ink. Same babl separation basis as lb:cmyk-levels — not an ICC
 *            profile, so the result is only self-consistent inside this
 *            working space.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_string (curves, _("Curves"), "")
  description (_("Control points for the C, M, Y and K plates, as "
                 "\"C 0,0 0.5,0.42 1,1|M 0,0 1,1|Y 0,0 1,1|K 0,0 1,1\". "
                 "Coordinates are normalised to 0…1 along each axis over the "
                 "0…100 ink range. A plate that is omitted stays unchanged. "
                 "The interactive dialog writes this string and reads it "
                 "back, so the adjustment stays editable."))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_cmyk_curves
#define GEGL_OP_C_SOURCE cmyk-curves.c
#include "gegl-op.h"

#include "curve.h"

#define CMYK_LO    0.0f
#define CMYK_HI    1.0f   /* babl CMYKA 内部是 0…1，不是 0…100 */

static const gchar *const cmyk_names[4] = { "C", "M", "Y", "K" };

static inline gfloat
cmyk_norm (gfloat v)
{
  return CLAMP ((v - CMYK_LO) / (CMYK_HI - CMYK_LO), 0.0f, 1.0f);
}

static inline gfloat
cmyk_denorm (gfloat t)
{
  return CMYK_LO + t * (CMYK_HI - CMYK_LO);
}

static void
prepare (GeglOperation *op)
{
  gegl_operation_set_format (op, "input",  babl_format ("CMYKA float"));
  gegl_operation_set_format (op, "output", babl_format ("CMYKA float"));
}

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *in_buf,
         GeglBuffer          *out_buf,
         const GeglRectangle *roi,
         gint                 level)
{
  LbCurve curves[4];
  gchar  *text = NULL;
  gboolean identity = TRUE;

  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  for (gint i = 0; i < 4; i++)
    lb_curve_identity (&curves[i]);

  g_object_get (G_OBJECT (op), "curves", &text, NULL);
  lb_curve_parse_set (curves, 4, cmyk_names, text ? text : "");
  g_free (text);

  for (gint i = 0; i < 4; i++)
    if (!curves[i].identity)
      identity = FALSE;

  const Babl *fmt    = babl_format ("CMYKA float");
  gint        stride = roi->width * 5;          /* CMYK + A */
  gfloat     *in_line  = g_new (gfloat, stride);
  gfloat     *out_line = g_new (gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };

    gegl_buffer_get (in_buf, &row_rect, 1.0f, fmt,
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    if (identity)
    {
      memcpy (out_line, in_line, sizeof (gfloat) * stride);
    }
    else
    {
      for (gint x = 0; x < roi->width; x++)
      {
        gint   px = x * 5;
        gfloat a  = in_line[px + 4];

        if (a <= 0.0f)
        {
          memcpy (&out_line[px], &in_line[px], sizeof (gfloat) * 5);
          out_line[px + 4] = 0.0f;
          continue;
        }

        for (gint k = 0; k < 4; k++)
          out_line[px + k] = cmyk_denorm (
              lb_curve_at (&curves[k], cmyk_norm (in_line[px + k])));
        out_line[px + 4] = a;
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
    "name",            "lb:cmyk-curves",
    "title",           _("CMYK Curves"),
    "categories",      "color",
    "description",     _("Free-form curves for the C, M, Y and K plates"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Curves",
    "gimp:menu-label", _("CMYK Curves"),
    NULL);
}

#endif
