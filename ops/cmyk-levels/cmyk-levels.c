/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:cmyk-levels
 * menu       CMYK Levels
 * purpose    CMYK 四个分量各自设输入 / 输出黑白场与伽马
 *            Independent input/output black-white points and gamma for the four CMYK inks.
 * algorithm  在 babl "CMYKA float" 上逐分量色阶。RGB↔CMYK 用 babl 的分色（带黑版生成，与 GIMP「分解 → CMYK」同源），不是 ICC 特性文件；色阶只映射已算出的 C/M/Y/K，拉 K 不会回算 CMY 的 GCR 补偿
 *            Per-component levels on babl CMYKA. RGB↔CMYK uses babl's separation (with black generation, same as GIMP's decompose), not an ICC profile; levels map the inks as given and do not re-run GCR.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * reference  Common CMYK Levels 工作流：印刷四分色版的墨量色阶，K 单独一条曲线
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (c_in_black, _("C 输入黑场（%）"), 0.0)
    description (_("青输入黑场：低于它的值压到输出黑场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (c_in_white, _("C 输入白场（%）"), 100.0)
    description (_("青输入白场：高于它的值提到输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (c_gamma, _("C Gamma"), 1.0)
    description (_("青中间调：>1 提亮中间调，<1 压暗"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (c_out_black, _("C 输出下限（%）"), 0.0)
    description (_("青输出黑场，可与输出上限对调做反相"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (c_out_white, _("C 输出上限（%）"), 100.0)
    description (_("青输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (m_in_black, _("M 输入黑场（%）"), 0.0)
    description (_("洋红输入黑场：低于它的值压到输出黑场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (m_in_white, _("M 输入白场（%）"), 100.0)
    description (_("洋红输入白场：高于它的值提到输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (m_gamma, _("M Gamma"), 1.0)
    description (_("洋红中间调：>1 提亮中间调，<1 压暗"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (m_out_black, _("M 输出下限（%）"), 0.0)
    description (_("洋红输出黑场，可与输出上限对调做反相"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (m_out_white, _("M 输出上限（%）"), 100.0)
    description (_("洋红输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (y_in_black, _("Y 输入黑场（%）"), 0.0)
    description (_("黄输入黑场：低于它的值压到输出黑场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (y_in_white, _("Y 输入白场（%）"), 100.0)
    description (_("黄输入白场：高于它的值提到输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (y_gamma, _("Y Gamma"), 1.0)
    description (_("黄中间调：>1 提亮中间调，<1 压暗"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (y_out_black, _("Y 输出下限（%）"), 0.0)
    description (_("黄输出黑场，可与输出上限对调做反相"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (y_out_white, _("Y 输出上限（%）"), 100.0)
    description (_("黄输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (k_in_black, _("K 输入黑场（%）"), 0.0)
    description (_("黑输入黑场：低于它的值压到输出黑场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (k_in_white, _("K 输入白场（%）"), 100.0)
    description (_("黑输入白场：高于它的值提到输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (k_gamma, _("K Gamma"), 1.0)
    description (_("黑中间调：>1 提亮中间调，<1 压暗"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (k_out_black, _("K 输出下限（%）"), 0.0)
    description (_("黑输出黑场，可与输出上限对调做反相"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (k_out_white, _("K 输出上限（%）"), 100.0)
    description (_("黑输出白场"))
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_cmyk_levels
#define GEGL_OP_C_SOURCE cmyk-levels.c
#include "gegl-op.h"
#include "color-levels.h"

/* 格式钉在 babl 的模型格式上：RGB↔CMYK 的转换由 babl 完成，与 GIMP 的
 * 「分解 / 提取分量」走同一套口径，算子内部不再自带色彩转换。
 * babl does the RGB↔CMYK conversion, the same one GIMP's decompose and
 * component-extract use, so no colour code lives in this file. */
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
  static const LbClModel model = { "CMYKA float", 4,
      { 100.0f, 100.0f, 100.0f, 100.0f },
      { 0.0f, 0.0f, 0.0f, 0.0f },
      { 100.0f, 100.0f, 100.0f, 100.0f },
      { FALSE, FALSE, FALSE, FALSE } };
  gdouble p[4 * 5];

  g_object_get (G_OBJECT (op),
                "c-in-black", &p[0 * 5 + LB_CL_IB],
                "c-in-white", &p[0 * 5 + LB_CL_IW],
                "c-gamma", &p[0 * 5 + LB_CL_G],
                "c-out-black", &p[0 * 5 + LB_CL_OB],
                "c-out-white", &p[0 * 5 + LB_CL_OW],
                "m-in-black", &p[1 * 5 + LB_CL_IB],
                "m-in-white", &p[1 * 5 + LB_CL_IW],
                "m-gamma", &p[1 * 5 + LB_CL_G],
                "m-out-black", &p[1 * 5 + LB_CL_OB],
                "m-out-white", &p[1 * 5 + LB_CL_OW],
                "y-in-black", &p[2 * 5 + LB_CL_IB],
                "y-in-white", &p[2 * 5 + LB_CL_IW],
                "y-gamma", &p[2 * 5 + LB_CL_G],
                "y-out-black", &p[2 * 5 + LB_CL_OB],
                "y-out-white", &p[2 * 5 + LB_CL_OW],
                "k-in-black", &p[3 * 5 + LB_CL_IB],
                "k-in-white", &p[3 * 5 + LB_CL_IW],
                "k-gamma", &p[3 * 5 + LB_CL_G],
                "k-out-black", &p[3 * 5 + LB_CL_OB],
                "k-out-white", &p[3 * 5 + LB_CL_OW],
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
    "name",            "lb:cmyk-levels",
    "title",           _("CMYK Levels"),
    "categories",      "color",
    "description",     _("Independent levels adjustment for C, M, Y and K inks (babl separation, not ICC)"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Tone",
    "gimp:menu-label", _("CMYK Levels"),
    NULL);
}

#endif
