/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsl-levels
 * menu       HSL Levels
 * purpose    HSL 三个分量各自设输入 / 输出黑白场与伽马
 *            Independent input/output black-white points and gamma for the H, S and L channels of HSL.
 * algorithm  在 babl "HSLA float" 上逐分量色阶：S/L 线性映射；H 是环形的，按弧重映射（主弧 [黑场→白场] 映到输出弧，余弧按比例跟进），整圈连续、默认参数逐位还原；alpha≤0 透传；映射走 4096 项 LUT
 *            Per-component levels on babl HSLA: S/L linear; H is circular and remapped by arcs (main arc [black→white] onto the output arc, the rest scaled to follow), continuous around the circle and bit-exact at defaults; transparent pixels pass through; 4096-entry LUT.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * reference  Common HSL Levels 工作流：色相环上做色阶，饱和度/明度当普通灰度色阶
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

property_double (l_in_black, _("L input black (%)"), 0.0)
    description (_("Lightness input black: values below it are clamped to the output black point."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (l_in_white, _("L input white (%)"), 100.0)
    description (_("Lightness input white: values above it are lifted to the output white point."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (l_gamma, _("L Gamma"), 1.0)
    description (_("Lightness midtones: >1 lightens the midtones, <1 darkens them."))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (l_out_black, _("L output black (%)"), 0.0)
    description (_("Lightness output black; swap it with the output white to invert."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (l_out_white, _("L output white (%)"), 100.0)
    description (_("Lightness output white."))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_hsl_levels
#define GEGL_OP_C_SOURCE hsl-levels.c
#include "gegl-op.h"
#include "color-levels.h"

/* 格式钉在 babl 的模型格式上：RGB↔HSL 的转换由 babl 完成，与 GIMP 的
 * 「分解 / 提取分量」走同一套口径，算子内部不再自带色彩转换。
 * babl does the RGB↔HSL conversion, the same one GIMP's decompose and
 * component-extract use, so no colour code lives in this file. */
static void
prepare (GeglOperation *op)
{
  gegl_operation_set_format (op, "input",  babl_format ("HSLA float"));
  gegl_operation_set_format (op, "output", babl_format ("HSLA float"));
}

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *in_buf,
         GeglBuffer          *out_buf,
         const GeglRectangle *roi,
         gint                 level)
{
  static const LbClModel model = { "HSLA float", 3,
      { 360.0f, 100.0f, 100.0f, 0.0f },
      { 0.0f, 0.0f, 0.0f, 0.0f },
      { 360.0f, 100.0f, 100.0f, 0.0f },
      { TRUE, FALSE, FALSE, FALSE } };
  gdouble p[3 * 5];

  g_object_get (G_OBJECT (op),
                "h-in-black", &p[0 * 5 + LB_CL_IB],
                "h-in-white", &p[0 * 5 + LB_CL_IW],
                "h-gamma", &p[0 * 5 + LB_CL_G],
                "h-out-black", &p[0 * 5 + LB_CL_OB],
                "h-out-white", &p[0 * 5 + LB_CL_OW],
                "s-in-black", &p[1 * 5 + LB_CL_IB],
                "s-in-white", &p[1 * 5 + LB_CL_IW],
                "s-gamma", &p[1 * 5 + LB_CL_G],
                "s-out-black", &p[1 * 5 + LB_CL_OB],
                "s-out-white", &p[1 * 5 + LB_CL_OW],
                "l-in-black", &p[2 * 5 + LB_CL_IB],
                "l-in-white", &p[2 * 5 + LB_CL_IW],
                "l-gamma", &p[2 * 5 + LB_CL_G],
                "l-out-black", &p[2 * 5 + LB_CL_OB],
                "l-out-white", &p[2 * 5 + LB_CL_OW],
                 NULL);

  return lb_cl_process (in_buf, out_buf, roi, &model, p);
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  oclass->prepare = prepare;
  fclass->process = process;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:hsl-levels",
    "title",           _("HSL Levels"),
    "categories",      "color",
    "description",     _("Independent levels adjustment for H, S and L channels, hue remapped around the circle"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Levels",
    "gimp:menu-label", _("HSL Levels"),
    NULL);
}

#endif
