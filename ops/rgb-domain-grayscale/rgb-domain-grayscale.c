/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:rgb-domain-grayscale
 * menu       Black & White
 * purpose    PS 黑白：六个色相滑块（红/黄/绿/青/蓝/品红）加权转灰，可着色
 *            PS Black & White: six hue sliders (red, yellow, green, cyan,
 *            blue, magenta) weight the grey conversion, with optional
 *            tinting.
 * algorithm  RGB 三通道按六色权重加权求和，-200~300 区间与 PS 界面对齐
 *            The three RGB channels are summed with six hue weights; the
 *            -200..300 slider range matches the PS dialog.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  Photoshop「黑白」(Black & White)
 *            Photoshop Black & White
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* 6 个色相滑块：取值范围与 UI 可视范围统一为 -200 ~ 300，默认值对应 PS 原
 * 版的百分比
 * Six hue sliders: value range and UI range are both -200..300; the
 * defaults match the PS percentages. */
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

/* ---- 着色控制属性 / tint controls -------------------------------------- */
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

/* ---- 枚举定义：通道索引 / enum: channel indices ------------------------ */
typedef enum {
  CH_R = 0,
  CH_G = 1,
  CH_B = 2
} ChanIdx;

/* ---- 线性 RGB 着色算法（PS 的真实实现）/ linear-RGB tint (what PS does) */
static void
tint_pixel (gfloat gray, const gfloat tint_rgb[3], gfloat strength, gfloat out[3])
{
  /* PS 的着色 = 把灰度当亮度，用线性光模式混合目标色
   * PS tint = treat the grey as luminance and blend the target colour in
   * linear light */
  gfloat r = tint_rgb[0];
  gfloat g = tint_rgb[1];
  gfloat b = tint_rgb[2];

  /* 线性亮度混合（与 PS 完全一致）
   * linear luminance blend, identical to PS */
  out[0] = gray * r;
  out[1] = gray * g;
  out[2] = gray * b;

  /* 按强度插值
   * interpolate by strength */
  out[0] = gray + (out[0] - gray) * strength;
  out[1] = gray + (out[1] - gray) * strength;
  out[2] = gray + (out[2] - gray) * strength;

  /* 安全裁剪
   * safe clamp */
  out[0] = CLAMP(out[0], 0.0f, 1.0f);
  out[1] = CLAMP(out[1], 0.0f, 1.0f);
  out[2] = CLAMP(out[2], 0.0f, 1.0f);
}

/* ---- GEGL 算子标准接口 / GEGL operation interface ---------------------- */
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

  /* ---- 1. 取出全部属性 / 1. fetch every property ----------------------- */
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

  /* 修复：gegl_color_get_rgba 需要 gdouble（double）类型的存储
   * fix: gegl_color_get_rgba needs gdouble (double) storage */
  if (tint_enabled && tint_color_obj) {
    gdouble r, g, b, a;
    gegl_color_get_rgba(tint_color_obj, &r, &g, &b, &a);
    tint_rgb[0] = (gfloat)r;
    tint_rgb[1] = (gfloat)g;
    tint_rgb[2] = (gfloat)b;
  }
  g_clear_object(&tint_color_obj);

  /* ---- 2. 滑块值换算成系数 / 2. slider values -> coefficients ---------- */
  gfloat r_ratio = red / 100.0f;
  gfloat y_ratio = yellow / 100.0f;
  gfloat g_ratio = green / 100.0f;
  gfloat c_ratio = cyan / 100.0f;
  gfloat b_ratio = blue / 100.0f;
  gfloat m_ratio = magenta / 100.0f;

  /* ---- 3. 准备输入/输出缓冲区 / 3. prepare the buffers ----------------- */
  gint n_pixels = roi->width * roi->height;
  gfloat *in_data  = g_new (gfloat, n_pixels * 4);
  gfloat *out_data = g_new (gfloat, n_pixels * 4);

  gegl_buffer_get (input, roi, 1.0,
                   babl_format ("RGBA float"),
                   in_data,
                   GEGL_AUTO_ROWSTRIDE,
                   GEGL_ABYSS_NONE);

  /* ---- 4. 主循环：黑白计算 + 干净着色 / 4. loop: grey + tint ----------- */
  for (gint i = 0; i < n_pixels; i++)
    {
      gint idx = i * 4;
      gfloat r = in_data[idx + 0];
      gfloat g = in_data[idx + 1];
      gfloat b = in_data[idx + 2];
      gfloat a = in_data[idx + 3];

      /* 1. 记下三个通道的数值与索引，排序后得到 max/mid/min 各自对应的通道
       * 1. keep each channel value with its index, sort to find which is
       * max/mid/min */
      gfloat vals[3] = {r, g, b};
      ChanIdx idx0 = CH_R, idx1 = CH_G, idx2 = CH_B;
      ChanIdx maxChan, midChan, minChan;

      /* 冒泡排序，从大到小
       * bubble sort, largest first */
      if (vals[idx0] < vals[idx1]) { ChanIdx t = idx0; idx0 = idx1; idx1 = t; }
      if (vals[idx0] < vals[idx2]) { ChanIdx t = idx0; idx0 = idx2; idx2 = t; }
      if (vals[idx1] < vals[idx2]) { ChanIdx t = idx1; idx1 = idx2; idx2 = t; }

      maxChan = idx0; midChan = idx1; minChan = idx2;
      gfloat maxv = vals[maxChan];
      gfloat midv = vals[midChan];
      gfloat minv = vals[minChan];

      gfloat ratio_max, ratio_max_mid;

      /* 2. 用「最大值通道 + 中间值通道」的组合去匹配权重
       * 2. match the weights against the max/mid channel pair */
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

      /* 3. 计算灰度（原有逻辑，保持不动）
       * 3. compute the grey value (original logic, left untouched) */
      gfloat gray = (maxv - midv) * ratio_max + (midv - minv) * ratio_max_mid + minv;
      gray = CLAMP(gray, 0.0f, 1.0f);

      /* 4. 干净着色，不再二次污染
       * 4. tint without polluting the result */
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

  /* ---- 5. 写回输出并清理 / 5. write back and clean up ------------------ */
  gegl_buffer_set (output, roi, 0,
                   babl_format ("RGBA float"),
                   out_data,
                   GEGL_AUTO_ROWSTRIDE);

  g_free (in_data);
  g_free (out_data);
  return TRUE;
}

/* ---- GEGL 算子类初始化 / operation class init -------------------------- */
static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass        *op_class  = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass  *filter_cl = GEGL_OPERATION_FILTER_CLASS (klass);

  op_class->prepare = prepare;
  filter_cl->process = process;

  gegl_operation_class_set_keys (op_class,
    "name",            "lb:rgb-domain-grayscale",
    "title",           _("Black & White"),
    "description",     _("PS Black & White: six color weights (red/yellow/green/cyan/blue/magenta) "
                         "in RGB domain, optional tint"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Black & White"),
    NULL);
}

#endif /* GEGL_PROPERTIES */