/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsb-levels
 * menu       HSB Levels
 * purpose    HSB（=HSV）三个分量各自设输入 / 输出黑白场与伽马
 *            Independent input/output black-white points and gamma for the H, S and B (value) channels of HSB/HSV.
 * algorithm  在 babl "HSVA float" 上逐分量色阶；H 环形重映射，S/B 线性。注意 S 是 HSV 语义（S = 1 − min/V），与 HSL 的 S 不是同一个量
 *            Per-component levels on babl HSVA: hue circular, S/B linear. S here is HSV's (1 - min/value), which is not the same quantity as HSL's S.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * reference  Common HSB Levels 工作流：取色器的 HSB 数值面板，B 就是最大通道值
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (h_in_black, _("H 输入黑场（度）"), 0.0)
    description (_("色相环上的起点：从这里顺时针量到白场"))
    value_range (0.0, 360.0)
    ui_range (0.0, 360.0)

property_double (h_in_white, _("H 输入白场（度）"), 360.0)
    description (_("色相环上的终点：主弧之外的色相按剩余弧长绕回来"))
    value_range (0.0, 360.0)
    ui_range (0.0, 360.0)

property_double (h_gamma, _("H Gamma"), 1.0)
    description (_("主弧内的色相分布：>1 往黑场挤，<1 往白场挤"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (h_out_black, _("H 输出下限（度）"), 0.0)
    description (_("输出色相环的起点，弧长沿用输出上下限之差"))
    value_range (0.0, 360.0)
    ui_range (0.0, 360.0)

property_double (h_out_white, _("H 输出上限（度）"), 360.0)
    description (_("输出色相环的终点；与下限重合按整圈处理（纯色相旋转）"))
    value_range (0.0, 360.0)
    ui_range (0.0, 360.0)

property_double (s_in_black, _("S 输入黑场（%）"), 0.0)
    description (_("饱和度输入黑场：低于它的值压到输出黑场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (s_in_white, _("S 输入白场（%）"), 100.0)
    description (_("饱和度输入白场：高于它的值提到输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (s_gamma, _("S Gamma"), 1.0)
    description (_("饱和度中间调：>1 提亮中间调，<1 压暗"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (s_out_black, _("S 输出下限（%）"), 0.0)
    description (_("饱和度输出黑场，可与输出上限对调做反相"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (s_out_white, _("S 输出上限（%）"), 100.0)
    description (_("饱和度输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (b_in_black, _("B 输入黑场（%）"), 0.0)
    description (_("明度 V输入黑场：低于它的值压到输出黑场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (b_in_white, _("B 输入白场（%）"), 100.0)
    description (_("明度 V输入白场：高于它的值提到输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (b_gamma, _("B Gamma"), 1.0)
    description (_("明度 V中间调：>1 提亮中间调，<1 压暗"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (b_out_black, _("B 输出下限（%）"), 0.0)
    description (_("明度 V输出黑场，可与输出上限对调做反相"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (b_out_white, _("B 输出上限（%）"), 100.0)
    description (_("明度 V输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_hsb_levels
#define GEGL_OP_C_SOURCE hsb-levels.c
#include "gegl-op.h"
#include "color-levels.h"

/* 格式钉在 babl 的模型格式上：RGB↔HSV 的转换由 babl 完成，与 GIMP 的
 * 「分解 / 提取分量」走同一套口径，算子内部不再自带色彩转换。
 * babl does the RGB↔HSV conversion, the same one GIMP's decompose and
 * component-extract use, so no colour code lives in this file. */
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
  static const LbClModel model = { "HSVA float", 3,
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
                "b-in-black", &p[2 * 5 + LB_CL_IB],
                "b-in-white", &p[2 * 5 + LB_CL_IW],
                "b-gamma", &p[2 * 5 + LB_CL_G],
                "b-out-black", &p[2 * 5 + LB_CL_OB],
                "b-out-white", &p[2 * 5 + LB_CL_OW],
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
    "name",            "lb:hsb-levels",
    "title",           _("HSB Levels"),
    "categories",      "color",
    "description",     _("Independent levels adjustment for H, S and B (value) channels"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Levels",
    "gimp:menu-label", _("HSB Levels"),
    NULL);
}

#endif
