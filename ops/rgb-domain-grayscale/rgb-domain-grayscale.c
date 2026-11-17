/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:rgb-domain-grayscale
 * menu       Black & White
 * purpose    经典图像编辑器 黑白：六个色相滑块（红/黄/绿/青/蓝/品红）加权转灰，可着色
 *            the classic editor Black & White: six hue sliders (red, yellow, green, cyan,
 *            blue, magenta) weight the grey conversion, with optional
 *            tinting.
 * algorithm  RGB 三通道按六色权重加权求和，-200~300 区间与 经典图像编辑器 界面对齐；
 *            着色走编码域 SetLum + 边界收缩（黑盒标定，见 bw-cal/RESULTS.md）
 *            The three RGB channels are summed with six hue weights; the
 *            -200..300 slider range matches the classic editor dialog. Tinting
 *            is an encoding-domain SetLum plus a gamut collapse at the cube
 *            faces (black-box calibration, see bw-cal/RESULTS.md).
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  经典图像编辑器「黑白」(Black & White)
 *            the classic editor Black & White
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* 6 个色相滑块：取值范围与 UI 可视范围统一为 -200 ~ 300，默认值对应 经典图像编辑器 原
 * 版的百分比
 * Six hue sliders: value range and UI range are both -200..300; the
 * defaults match the classic editor percentages. */
property_double (red, _("Red"), 40.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Red color ratio (the classic editor default 40 = 0.4)"))

property_double (yellow, _("Yellow"), 60.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Yellow color ratio (the classic editor default 60 = 0.6)"))

property_double (green, _("Green"), 40.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Green color ratio (the classic editor default 40 = 0.4)"))

property_double (cyan, _("Cyan"), 60.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Cyan color ratio (the classic editor default 60 = 0.6)"))

property_double (blue, _("Blue"), 20.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Blue color ratio (the classic editor default 20 = 0.2)"))

property_double (magenta, _("Magenta"), 80.0)
  value_range (-200.0, 300.0)
  ui_range (-200.0, 300.0)
  ui_steps (1.0, 10.0)
  description (_("Magenta color ratio (the classic editor default 80 = 0.8)"))

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

/* ---- 着色算法（黑盒标定自 经典图像编辑器，见 bw-cal/RESULTS.md）
 *      the tint algorithm, black-box calibrated against the classic editor ------
 *
 * 着色不是「灰度×颜色」的乘法，而是编码域的 SetLum 平移再按边界收缩：
 * The tint is not a plain grey×colour multiply: it is an encoding-domain SetLum
 * shift followed by a gamut collapse at the cube faces.
 *
 *   记 tint=(tR,tG,tB)，L = 0.3·tR + 0.59·tG + 0.11·tB（NTSC 亮度，编码域），
 *   tmax=max(tint)，tmin=min(tint)：
 *   with L the NTSC luma in the encoding domain, tmax/tmin the tint extremes:
 *
 *   中段   out_ch = gray + tint_ch − L          （斜率 1 平移，白仍白、黑仍黑）
 *   顶部   g ≥ 1−(tmax−L) 时（tint 比灰亮，先撞到 1）
 *          out_ch = 1 − (tmax − tint_ch)·(1 − gray)/(tmax − L)
 *          最亮通道被钉在 1，其余通道沿「tint → (tmax,tmax,tmax) 灰点」方向收敛
 *   底部   g ≤ L−tmin 时（tint 比灰暗，先撞到 0）
 *          out_ch = (tint_ch − tmin)·gray/(L − tmin)
 *
 *   三段在断点处连续，顶/底两段精确过 (1,1,1)/(0,0,0)。实测 18 组色相 × 饱和度
 *   逐码吻合（最大 0.10/255，平均 0.01/255）；旧的乘法实现平均偏 58 码。
 *   The three pieces join continuously and the top/bottom pieces pass exactly
 *   through white/black. Measured over 18 tint cases: max 0.10 code, average
 *   0.01 code; the previous multiplicative version was off by 58 codes on average. */
static void
tint_pixel (gfloat gray, const gfloat tint_rgb[3], gfloat strength, gfloat out[3])
{
  const gfloat lum = 0.3f * tint_rgb[0] + 0.59f * tint_rgb[1] + 0.11f * tint_rgb[2];

  gfloat tmax = tint_rgb[0], tmin = tint_rgb[0];
  for (gint c = 1; c < 3; c++)
    {
      if (tint_rgb[c] > tmax) tmax = tint_rgb[c];
      if (tint_rgb[c] < tmin) tmin = tint_rgb[c];
    }

  const gfloat top = tmax - lum;   /* 顶部裁剪带宽 / width of the top collapse  */
  const gfloat bot = lum - tmin;   /* 底部裁剪带宽 / width of the bottom one    */

  for (gint c = 0; c < 3; c++)
    {
      gfloat y;

      if (top > 1e-6f && gray >= 1.0f - top)
        /* 撞到白端：最亮通道钉在 1，其余按 tint 的通道差收缩
         * hit the white end: the brightest channel pins at 1, the others
         * collapse proportionally to their distance from it */
        y = 1.0f - (tmax - tint_rgb[c]) * (1.0f - gray) / top;
      else if (bot > 1e-6f && gray <= bot)
        /* 撞到黑端 / hit the black end */
        y = (tint_rgb[c] - tmin) * gray / bot;
      else
        /* 中段：编码域斜率 1 的 SetLum / middle: unit-slope SetLum */
        y = gray + tint_rgb[c] - lum;

      y = CLAMP (y, 0.0f, 1.0f);

      /* 按强度回插灰度 / blend back toward the neutral grey by strength */
      out[c] = CLAMP (gray + (y - gray) * strength, 0.0f, 1.0f);
    }
}

/* ---- GEGL 算子标准接口 / GEGL operation interface ---------------------- */
/* 感知（非线性）格式：公式按 8bit sRGB 伽马域推导，必须拿伽马值，否则 babl
 * 会喂线性光，数值与 经典图像编辑器 对不上
 * Perceptual (non-linear) format: the maths was derived in the 8-bit sRGB
 * gamma domain. Linear light from babl would drift away from the classic editor. */
static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}

static void
prepare (GeglOperation *operation)
{
  gegl_operation_set_format (operation, "input", perceptual_format(operation));
  gegl_operation_set_format (operation, "output", perceptual_format(operation));
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

  /* 着色公式在编码域（8bit 伽马）推导，tint 也必须换算到编码域。
   * gegl_color_get_rgba 返回的是**线性光**，直接用会让着色整体偏暗（#80FF00 的
   * 0.5 会变成 0.216），所以这里取 sRGB 空间下的存储值。
   * The tint maths is derived in the encoding (8-bit gamma) domain, so the tint
   * has to be encoded too. gegl_color_get_rgba gives **linear light** — using it
   * directly darkens the tint (0.5 of #80FF00 would read 0.216) — hence the
   * sRGB-space getter. */
  if (tint_enabled && tint_color_obj) {
    gdouble r, g, b, a;
    gegl_color_get_rgba_with_space(tint_color_obj, &r, &g, &b, &a, NULL);
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
                   perceptual_format(operation),
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
                   perceptual_format(operation),
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
    "description",     _("the classic editor Black & White: six color weights (red/yellow/green/cyan/blue/magenta) "
                         "in RGB domain, optional tint"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Tone",
    "gimp:menu-label", _("Black & White"),
    NULL);
}

#endif /* GEGL_PROPERTIES */