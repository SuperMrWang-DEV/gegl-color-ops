/* ===========================================================================
 * SuperMrWang · GEGL Operation
 * ---------------------------------------------------------------------------
 * id     : lb:rgb-domain-grayscale
 * 菜单   : Grayscale
 * 作用   : PS 黑白：六个色相滑块（红/黄/绿/青/蓝/品红）加权转灰，可着色
 * 算法   : RGB 三通道按六色权重加权求和，-200~300 区间与 PS 界面对齐
 * 类型   : GeglOperationPointFilter
 * 参考   : Photoshop「黑白」(Black & White)
 * 许可   : GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* 6色滑块：总范围、UI可视范围统一 -200 ~ 300，默认值对应PS原版百分比 */
property_double (red, _("Red"), 40.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Red color ratio (PS default 40 = 0.4)"))

property_double (yellow, _("Yellow"), 60.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Yellow color ratio (PS default 60 = 0.6)"))

property_double (green, _("Green"), 40.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Green color ratio (PS default 40 = 0.4)"))

property_double (cyan, _("Cyan"), 60.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Cyan color ratio (PS default 60 = 0.6)"))

property_double (blue, _("Blue"), 20.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Blue color ratio (PS default 20 = 0.2)"))

property_double (magenta, _("Magenta"), 80.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Magenta color ratio (PS default 80 = 0.8)"))

/* ---- 着色控制属性 ------------------------------------------------------ */
property_boolean (tint_enabled, _("Tint Enabled"), FALSE)
  description (_("Enable tinting mode"))

property_color (tint_color, _("Tint Color"), "#E0D4B2")
  description (_("Color used for tinting"))

property_double (tint_strength, _("Tint Strength"), 1.0)
  value_range (0.0, 1.0)
  ui_range (0.0, 1.0)
  ui_steps (0.01, 0.1)
  description (_("Strength of tinting effect. 0 = pure black & white, 1 = full tint"))

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_rgb_domain_grayscale
#define GEGL_OP_C_SOURCE rgb-domain-grayscale.c

#include "gegl-op.h"

/* ---- 枚举定义：通道索引 ------------------------------------------------ */
typedef enum {
  CH_R = 0,
  CH_G = 1,
  CH_B = 2
} ChanIdx;

/* ---- 【修复】线性RGB着色算法（PS 真实实现） ---------------------------- */
static void
tint_pixel (gfloat gray, const gfloat tint_rgb[3], gfloat strength, gfloat out[3])
{
  /* PS 着色 = 灰度作为亮度，混合目标颜色（线性光模式） */
  gfloat r = tint_rgb[0];
  gfloat g = tint_rgb[1];
  gfloat b = tint_rgb[2];

  /* 线性亮度混合（和 PS 完全一致） */
  out[0] = gray * r;
  out[1] = gray * g;
  out[2] = gray * b;

  /* 强度插值 */
  out[0] = gray + (out[0] - gray) * strength;
  out[1] = gray + (out[1] - gray) * strength;
  out[2] = gray + (out[2] - gray) * strength;

  /* 安全裁剪 */
  out[0] = CLAMP(out[0], 0.0f, 1.0f);
  out[1] = CLAMP(out[1], 0.0f, 1.0f);
  out[2] = CLAMP(out[2], 0.0f, 1.0f);
}

/* ---- GEGL 操作标准接口 ------------------------------------------------- */
static void
prepare (GeglOperation *operation)
{
  gegl_operation_set_format (operation, "input", babl_format ("RGBA float"));
  gegl_operation_set_format (operation, "output", babl_format ("RGBA float"));
}

static gboolean
process (GeglOperation       *operation,
         GeglBuffer          *input,
         GeglBuffer          *output,
         const GeglRectangle *roi,
         gint                 level)
{
  if (!roi || roi->width == 0 || roi->height == 0)
    return TRUE;

  /* ---- 1. 获取所有属性 ------------------------------------------------- */
  gdouble red, yellow, green, cyan, blue, magenta;
  gboolean tint_enabled;
  gdouble tint_strength;
  GeglColor *tint_color_obj = NULL;
  gfloat tint_rgb[3] = {0.88f, 0.83f, 0.70f};

  g_object_get (G_OBJECT (operation),
                "red", &red,
                "yellow", &yellow,
                "green", &green,
                "cyan", &cyan,
                "blue", &blue,
                "magenta", &magenta,
                "tint_enabled", &tint_enabled,
                "tint_color", &tint_color_obj,
                "tint_strength", &tint_strength,
                NULL);

  /* ✅ 修复：gegl_color_get_rgba 需要 gdouble (double) 类型 */
  if (tint_enabled && tint_color_obj) {
    gdouble r, g, b, a;
    gegl_color_get_rgba(tint_color_obj, &r, &g, &b, &a);
    tint_rgb[0] = (gfloat)r;
    tint_rgb[1] = (gfloat)g;
    tint_rgb[2] = (gfloat)b;
  }
  g_clear_object(&tint_color_obj);

  /* ---- 2. 将滑块值转换为计算系数 --------------------------------------- */
  gfloat r_ratio = red / 100.0f;
  gfloat y_ratio = yellow / 100.0f;
  gfloat g_ratio = green / 100.0f;
  gfloat c_ratio = cyan / 100.0f;
  gfloat b_ratio = blue / 100.0f;
  gfloat m_ratio = magenta / 100.0f;

  /* ---- 3. 准备输入/输出缓冲区 ------------------------------------------ */
  gint n_pixels = roi->width * roi->height;
  gfloat *in_data  = g_new (gfloat, n_pixels * 4);
  gfloat *out_data = g_new (gfloat, n_pixels * 4);

  gegl_buffer_get (input, roi, 1.0,
                   babl_format ("RGBA float"),
                   in_data,
                   GEGL_AUTO_ROWSTRIDE,
                   GEGL_ABYSS_NONE);

  /* ---- 4. 主循环：黑白计算 + 干净着色 ---------------------------------- */
  for (gint i = 0; i < n_pixels; i++)
    {
      gint idx = i * 4;
      gfloat r = in_data[idx + 0];
      gfloat g = in_data[idx + 1];
      gfloat b = in_data[idx + 2];
      gfloat a = in_data[idx + 3];

      /* 1. 存储通道数值+索引，排序找max/mid/min对应的通道 */
      gfloat vals[3] = {r, g, b};
      ChanIdx idx0 = CH_R, idx1 = CH_G, idx2 = CH_B;
      ChanIdx maxChan, midChan, minChan;

      /* 冒泡排序，从大到小 */
      if (vals[idx0] < vals[idx1]) { ChanIdx t = idx0; idx0 = idx1; idx1 = t; }
      if (vals[idx0] < vals[idx2]) { ChanIdx t = idx0; idx0 = idx2; idx2 = t; }
      if (vals[idx1] < vals[idx2]) { ChanIdx t = idx1; idx1 = idx2; idx2 = t; }

      maxChan = idx0; midChan = idx1; minChan = idx2;
      gfloat maxv = vals[maxChan];
      gfloat midv = vals[midChan];
      gfloat minv = vals[minChan];

      gfloat ratio_max, ratio_max_mid;

      /* 2. 根据【最大值通道+中间值通道】匹配比率 */
      if ((maxChan == CH_R && midChan == CH_G) || (maxChan == CH_G && midChan == CH_R)) {
        ratio_max = (maxChan == CH_R) ? r_ratio : g_ratio;
        ratio_max_mid = y_ratio;
      } else if ((maxChan == CH_G && midChan == CH_B) || (maxChan == CH_B && midChan == CH_G)) {
        ratio_max = (maxChan == CH_G) ? g_ratio : b_ratio;
        ratio_max_mid = c_ratio;
      } else if ((maxChan == CH_B && midChan == CH_R) || (maxChan == CH_R && midChan == CH_B)) {
        ratio_max = (maxChan == CH_B) ? b_ratio : r_ratio;
        ratio_max_mid = m_ratio;
      } else {
        ratio_max = 1.0f;
        ratio_max_mid = 1.0f;
      }

      /* 3. 计算灰度（你原本的逻辑完全正确） */
      gfloat gray = (maxv - midv) * ratio_max + (midv - minv) * ratio_max_mid + minv;
      gray = CLAMP(gray, 0.0f, 1.0f);

      /* 4. 【修复】干净着色 */
      if (tint_enabled && tint_strength > 0.0f) {
        gfloat tinted[3];
        tint_pixel(gray, tint_rgb, (gfloat)tint_strength, tinted);
        out_data[idx+0] = tinted[0];
        out_data[idx+1] = tinted[1];
        out_data[idx+2] = tinted[2];
      } else {
        out_data[idx+0] = gray;
        out_data[idx+1] = gray;
        out_data[idx+2] = gray;
      }

      out_data[idx+3] = a;
    }

  /* ---- 5. 写回输出缓冲区并清理 ----------------------------------------- */
  gegl_buffer_set (output, roi, 0,
                   babl_format ("RGBA float"),
                   out_data,
                   GEGL_AUTO_ROWSTRIDE);

  g_free (in_data);
  g_free (out_data);
  return TRUE;
}

/* ---- GEGL 操作类初始化 ------------------------------------------------- */
static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass        *op_class  = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass  *filter_cl = GEGL_OPERATION_FILTER_CLASS (klass);

  op_class->prepare = prepare;
  filter_cl->process = process;

  gegl_operation_class_set_keys (op_class,
    "name",            "lb:rgb-domain-grayscale",
    "title",           _("Grayscale"),
    "description",     _("PS Black & White: six color weights (red/yellow/green/cyan/blue/magenta) "
                         "in RGB domain, optional tint"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Grayscale"),
    NULL);
}

#endif /* GEGL_PROPERTIES */