/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lch-levels
 * menu       LCH Levels
 * purpose    CIE LCh 三个分量各自设输入 / 输出黑白场与伽马
 *            Independent input/output black-white points and gamma for CIE LCh's L, C and H.
 * algorithm  在 babl "CIE LCH(ab) alpha float"（D50）上逐分量色阶：L/C 线性，C 的量程到 132 覆盖 sRGB 全色域；H 环形重映射。与 lb:lab-levels 同一套 Lab 口径，区别是色度/色相用极坐标，调色度不会连带改色相
 *            Per-component levels on babl CIE LCH(ab) (D50): L/C linear (C range up to 132 covers sRGB), hue circular. Same Lab baseline as lb:lab-levels, but chroma/hue are polar, so touching C never shifts H.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * reference  Common LCH Levels 工作流：GIMP 分解 LCH 后逐层跑色阶的等效非破坏做法
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (l_in_black, _("L 输入黑场"), 0.0)
    description (_("明度输入黑场：低于它的值压到输出黑场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (l_in_white, _("L 输入白场"), 100.0)
    description (_("明度输入白场：高于它的值提到输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (l_gamma, _("L Gamma"), 1.0)
    description (_("明度中间调：>1 提亮中间调，<1 压暗"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (l_out_black, _("L 输出下限"), 0.0)
    description (_("明度输出黑场，可与输出上限对调做反相"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (l_out_white, _("L 输出上限"), 100.0)
    description (_("明度输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (c_in_black, _("C 输入黑场"), 0.0)
    description (_("色度输入黑场：低于它的值压到输出黑场"))
    value_range (0.0, 132.0)
    ui_range (0.0, 132.0)

property_double (c_in_white, _("C 输入白场"), 132.0)
    description (_("色度输入白场：高于它的值提到输出白场"))
    value_range (0.0, 132.0)
    ui_range (0.0, 132.0)

property_double (c_gamma, _("C Gamma"), 1.0)
    description (_("色度中间调：>1 提亮中间调，<1 压暗"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (c_out_black, _("C 输出下限"), 0.0)
    description (_("色度输出黑场，可与输出上限对调做反相"))
    value_range (0.0, 132.0)
    ui_range (0.0, 132.0)

property_double (c_out_white, _("C 输出上限"), 132.0)
    description (_("色度输出白场"))
    value_range (0.0, 132.0)
    ui_range (0.0, 132.0)

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

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_lch_levels
#define GEGL_OP_C_SOURCE lch-levels.c
#include "gegl-op.h"
#include "color-levels.h"

/* 格式钉在 babl 的模型格式上：RGB↔LCh 的转换由 babl 完成，与 GIMP 的
 * 「分解 / 提取分量」走同一套口径，算子内部不再自带色彩转换。
 * babl does the RGB↔LCh conversion, the same one GIMP's decompose and
 * component-extract use, so no colour code lives in this file. */
static void
prepare (GeglOperation *op)
{
  gegl_operation_set_format (op, "input",  babl_format ("CIE LCH(ab) alpha float"));
  gegl_operation_set_format (op, "output", babl_format ("CIE LCH(ab) alpha float"));
}

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *in_buf,
         GeglBuffer          *out_buf,
         const GeglRectangle *roi,
         gint                 level)
{
  static const LbClModel model = { "CIE LCH(ab) alpha float", 3,
      { 1.0f, 1.0f, 1.0f, 0.0f },
      { 0.0f, 0.0f, 0.0f, 0.0f },
      { 100.0f, 132.0f, 360.0f, 0.0f },
      { FALSE, FALSE, TRUE, FALSE } };
  gdouble p[3 * 5];

  g_object_get (G_OBJECT (op),
                "l-in-black", &p[0 * 5 + LB_CL_IB],
                "l-in-white", &p[0 * 5 + LB_CL_IW],
                "l-gamma", &p[0 * 5 + LB_CL_G],
                "l-out-black", &p[0 * 5 + LB_CL_OB],
                "l-out-white", &p[0 * 5 + LB_CL_OW],
                "c-in-black", &p[1 * 5 + LB_CL_IB],
                "c-in-white", &p[1 * 5 + LB_CL_IW],
                "c-gamma", &p[1 * 5 + LB_CL_G],
                "c-out-black", &p[1 * 5 + LB_CL_OB],
                "c-out-white", &p[1 * 5 + LB_CL_OW],
                "h-in-black", &p[2 * 5 + LB_CL_IB],
                "h-in-white", &p[2 * 5 + LB_CL_IW],
                "h-gamma", &p[2 * 5 + LB_CL_G],
                "h-out-black", &p[2 * 5 + LB_CL_OB],
                "h-out-white", &p[2 * 5 + LB_CL_OW],
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
    "name",            "lb:lch-levels",
    "title",           _("LCH Levels"),
    "categories",      "color",
    "description",     _("Independent levels adjustment for CIE LCh L, C and H channels"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Levels",
    "gimp:menu-label", _("LCH Levels"),
    NULL);
}

#endif
