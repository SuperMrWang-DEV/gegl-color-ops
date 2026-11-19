/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsi-levels
 * menu       HSI Levels
 * purpose    HSI 三个分量各自设输入 / 输出黑白场与伽马
 *            Independent input/output black-white points and gamma for H, S and I (intensity).
 * algorithm  babl 没有 HSI，自己转：I = (R+G+B)/3，S = 1 − min/I，H 用余弦式（等亮度平面里的真实夹角，与 HSV 的参数角最多差 1.117°）；逆变换同样走余弦式，不用 HSV 的线性扇区。H 环形映射，S/I 线性。I 高时逆变换可能出界，按 sRGB 裁到 [0,1]
 *            No HSI model in babl, so it converts here: I = mean(RGB), S = 1 - min/I, hue at HSV's angle; the inverse uses HSI's cosine form, not HSV's linear sectors. Out-of-gamut results clamp to sRGB.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * reference  Common HSI Levels 工作流：HSI 常见于图像分析（亮度取均值，比 HSV 的 max 更接近感知亮度）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (h_in_black, _("H input black (deg)"), 0.0)
    description (_("Start of the hue ring: measured clockwise from here to the white point."))
    value_range (0.0, 360.0)
    ui_range (0.0, 360.0)

property_double (h_in_white, _("H input white (deg)"), 360.0)
    description (_("End of the hue ring: hues outside the main arc wrap around by the remaining arc length."))
    value_range (0.0, 360.0)
    ui_range (0.0, 360.0)

property_double (h_gamma, _("H Gamma"), 1.0)
    description (_("Hue distribution inside the main arc: >1 pushes toward black, <1 toward white."))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (h_out_black, _("H output black (deg)"), 0.0)
    description (_("Start of the output hue ring; the arc length follows the output black/white difference."))
    value_range (0.0, 360.0)
    ui_range (0.0, 360.0)

property_double (h_out_white, _("H output white (deg)"), 360.0)
    description (_("End of the output hue ring; coinciding with the black point is treated as a full turn (pure hue rotation)."))
    value_range (0.0, 360.0)
    ui_range (0.0, 360.0)

property_double (s_in_black, _("S input black (%)"), 0.0)
    description (_("Saturation input black: values below it are clamped to the output black point."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (s_in_white, _("S input white (%)"), 100.0)
    description (_("Saturation input white: values above it are lifted to the output white point."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (s_gamma, _("S Gamma"), 1.0)
    description (_("Saturation midtones: >1 lightens the midtones, <1 darkens them."))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (s_out_black, _("S output black (%)"), 0.0)
    description (_("Saturation output black; swap it with the output white to invert."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (s_out_white, _("S output white (%)"), 100.0)
    description (_("Saturation output white."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (i_in_black, _("I input black (%)"), 0.0)
    description (_("Intensity input black: values below it are clamped to the output black point."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (i_in_white, _("I input white (%)"), 100.0)
    description (_("Intensity input white: values above it are lifted to the output white point."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (i_gamma, _("I Gamma"), 1.0)
    description (_("Intensity midtones: >1 lightens the midtones, <1 darkens them."))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (i_out_black, _("I output black (%)"), 0.0)
    description (_("Intensity output black; swap it with the output white to invert."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (i_out_white, _("I output white (%)"), 100.0)
    description (_("Intensity output white."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_hsi_levels
#define GEGL_OP_C_SOURCE hsi-levels.c
#include "gegl-op.h"
#include "color-levels.h"

/* babl 没有 HSI 模型，所以在 RGB 域自己转：I 取三通道均值，S = 1 − min/I。
 * 输入输出都钉 R'G'B'A float，转换与 LUT 都在 common/color-levels.h 里。 */
static void
prepare (GeglOperation *op)
{
  gegl_operation_set_format (op, "input",  babl_format ("R'G'B'A float"));
  gegl_operation_set_format (op, "output", babl_format ("R'G'B'A float"));
}

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *in_buf,
         GeglBuffer          *out_buf,
         const GeglRectangle *roi,
         gint                 level)
{
  gdouble p[3 * 5];

  g_object_get (G_OBJECT (op),
                "h-in-black",  &p[0 * 5 + LB_CL_IB],
                "h-in-white",  &p[0 * 5 + LB_CL_IW],
                "h-gamma",     &p[0 * 5 + LB_CL_G],
                "h-out-black", &p[0 * 5 + LB_CL_OB],
                "h-out-white", &p[0 * 5 + LB_CL_OW],
                "s-in-black",  &p[1 * 5 + LB_CL_IB],
                "s-in-white",  &p[1 * 5 + LB_CL_IW],
                "s-gamma",     &p[1 * 5 + LB_CL_G],
                "s-out-black", &p[1 * 5 + LB_CL_OB],
                "s-out-white", &p[1 * 5 + LB_CL_OW],
                "i-in-black",  &p[2 * 5 + LB_CL_IB],
                "i-in-white",  &p[2 * 5 + LB_CL_IW],
                "i-gamma",     &p[2 * 5 + LB_CL_G],
                "i-out-black", &p[2 * 5 + LB_CL_OB],
                "i-out-white", &p[2 * 5 + LB_CL_OW],
                 NULL);

  return lb_cl_process_hsi (in_buf, out_buf, roi, p);
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  oclass->prepare = prepare;
  fclass->process = process;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:hsi-levels",
    "title",           _("HSI Levels"),
    "categories",      "color",
    "description",     _("Independent levels for H, S and I (intensity) channels"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Levels",
    "gimp:menu-label", _("HSI Levels"),
    NULL);
}

#endif
