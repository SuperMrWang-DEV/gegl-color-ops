/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lab-levels
 * menu       LAB Levels
 * purpose    LAB 三通道各自设输入 / 输出黑白场与伽马
 *            Independent input/output black-white points and gamma for each
 *            LAB channel.
 * algorithm  在 babl "CIE Lab alpha float"（D50 白点）上逐通道 levels：
 *            L 做标准映射；a/b 以 0 为中性轴分负/正半轴各自映射，gamma
 *            绕中性轴转动（灰白像素不被动）；黑白场交叉自动交换，输出
 *            反向（负片）可用；alpha≤0 像素原样透传；levels 查 LUT
 *            Levels per L/a/b channel on babl CIE Lab (D50); a and b
 *            pivot gamma around the neutral axis 0 (neutral pixels stay
 *            untouched), crossed black/white points are swapped, inverted
 *            output works, fully transparent pixels pass through, and the
 *            levels maps are table-driven.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (L_in_black, _("L input black"), 0.0)
    description (_("Lightness channel input black."))
    value_range (0.0, 95.0)
    ui_range (0.0, 95.0)

property_double (L_in_white, _("L input white"), 100.0)
    description (_("Lightness channel input white."))
    value_range (5.0, 100.0)
    ui_range (5.0, 100.0)

property_double (L_gamma, _("L Gamma"), 1.0)
    description (_("Lightness channel gamma / midtones."))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (L_out_black, _("L output black"), 0.0)
    description (_("Lightness channel output black."))
    value_range (0.0, 100.0)

property_double (L_out_white, _("L output white"), 100.0)
    description (_("Lightness channel output white."))
    value_range (0.0, 100.0)

property_double (a_in_black, _("a input black"), -128.0)
    description (_("a channel (red-green axis) input black."))
    value_range (-128.0, 120.0)

property_double (a_in_white, _("a input white"), 127.0)
    description (_("a channel (red-green axis) input white."))
    value_range (-120.0, 127.0)

property_double (a_gamma, _("a Gamma"), 1.0)
    description (_("a channel gamma, pivoting about the neutral axis; controls the midtone colour cast."))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (a_out_black, _("a output black"), -128.0)
    description (_("a channel output black; caps how far green can go."))
    value_range (-128.0, 127.0)

property_double (a_out_white, _("a output white"), 127.0)
    description (_("a channel output white; caps how far magenta can go."))
    value_range (-128.0, 127.0)

property_double (b_in_black, _("b input black"), -128.0)
    description (_("b channel (yellow-blue axis) input black."))
    value_range (-128.0, 120.0)

property_double (b_in_white, _("b input white"), 127.0)
    description (_("b channel (yellow-blue axis) input white."))
    value_range (-120.0, 127.0)

property_double (b_gamma, _("b Gamma"), 1.0)
    description (_("b channel gamma, pivoting about the neutral axis; controls the midtone colour cast."))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (b_out_black, _("b output black"), -128.0)
    description (_("b channel output black; caps how far blue can go."))
    value_range (-128.0, 127.0)

property_double (b_out_white, _("b output white"), 127.0)
    description (_("b channel output white; caps how far yellow can go."))
    value_range (-128.0, 127.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_lab_levels
#define GEGL_OP_C_SOURCE lab-levels.c
#include "gegl-op.h"

#include <math.h>

#define FLOAT_EPS    1e-12f
#define LUT_N        4096

/* ===========================================================================
 * 色彩空间：直接在 babl 的 "CIE Lab alpha float"（D50 白点）上工作，
 * RGB↔Lab 交给 babl——与 GIMP 原生 Lab 工具（指针/曲线）及 lb:match-color
 * 使用同一套 Lab 数值口径，算子内部不再自带转换。
 * 工作在 Lab 域等价于在感知域做 levels，不依赖“线性光”前提。
 * =========================================================================== */

static inline gfloat levels_channel(gfloat val,
                                    gfloat in_black,
                                    gfloat in_white,
                                    gfloat gamma,
                                    gfloat out_black,
                                    gfloat out_white)
{
    /* 输入黑白场交叉时自动交换（滑杆允许拉出交叉） */
    if (in_black > in_white)
    {
        gfloat t = in_black;
        in_black = in_white;
        in_white = t;
    }

    val = CLAMP(val, in_black, in_white);

    if(fabsf(in_white - in_black) < FLOAT_EPS)
        return val;

    gfloat norm = (val - in_black) / (in_white - in_black);
    norm = powf(MAX(norm, FLOAT_EPS), 1.0f / gamma);
    val = out_black + norm * (out_white - out_black);

    /* 输出反向（负片式）时 clamp 到真实上下界，而不是压成单值 */
    return CLAMP(val, MIN(out_black, out_white), MAX(out_black, out_white));
}

/* a/b 通道专用：gamma 绕中性轴 0 转动。负半轴 [in_black,0] 与正半轴
 * [0,in_white] 各自归一化后做 gamma，再映射到输出半轴。中性像素
 * （a=b=0 的灰白）在任意 gamma 下保持不动——这是 Lab 色阶与 RGB 色阶
 * 的本质差异：a/b 的“中间调”是中性轴，不是数值范围的中点。 */
static inline gfloat levels_channel_signed(gfloat val,
                                           gfloat in_black,
                                           gfloat in_white,
                                           gfloat gamma,
                                           gfloat out_black,
                                           gfloat out_white)
{
    if (in_black > in_white)
    {
        gfloat t = in_black;
        in_black = in_white;
        in_white = t;
    }

    val = CLAMP(val, in_black, in_white);

    gfloat in_lo = (val < 0.0f) ? in_black : 0.0f;
    gfloat in_hi = (val < 0.0f) ? 0.0f     : in_white;
    gfloat span  = in_hi - in_lo;
    if (fabsf(span) < FLOAT_EPS)
        return val;

    gfloat norm = (val - in_lo) / span;
    norm = powf(MAX(norm, FLOAT_EPS), 1.0f / gamma);

    gfloat out_lo = (val < 0.0f) ? out_black : 0.0f;
    gfloat out_hi = (val < 0.0f) ? 0.0f      : out_white;
    val = out_lo + norm * (out_hi - out_lo);

    return CLAMP(val, MIN(out_lo, out_hi), MAX(out_lo, out_hi));
}

/* ---- LUT：levels 是 1D 单调映射，逐像素 powf 换成查表 + 线性插值 ----
 * 每次 process 重建（几千次 powf，微秒级），确定性重建保证跨块一致。 */

static void
lut_build(gfloat        *lut_L,
          gfloat        *lut_a_neg, gfloat *lut_a_pos,
          gfloat        *lut_b_neg, gfloat *lut_b_pos,
          gdouble L_in_black,  gdouble L_in_white,  gdouble L_gamma,
          gdouble L_out_black, gdouble L_out_white,
          gdouble a_in_black,  gdouble a_in_white,  gdouble a_gamma,
          gdouble a_out_black, gdouble a_out_white,
          gdouble b_in_black,  gdouble b_in_white,  gdouble b_gamma,
          gdouble b_out_black, gdouble b_out_white)
{
  for (gint i = 0; i < LUT_N; i++)
  {
    gfloat vL = (gfloat) i * 100.0f / (gfloat) (LUT_N - 1);
    lut_L[i] = levels_channel(vL,
                (gfloat) L_in_black, (gfloat) L_in_white, (gfloat) L_gamma,
                (gfloat) L_out_black, (gfloat) L_out_white);

    /* a/b 的绕轴映射在 0 处导数不连续（拐点），必须负/正半轴各建一表，
     * 插值永不跨蝓 0——否则中性附近的微小输入会被插值过冲放大 */
    gfloat vN = -128.0f + (gfloat) i * 128.0f / (gfloat) (LUT_N - 1);
    gfloat vP = (gfloat) i * 127.0f / (gfloat) (LUT_N - 1);
    lut_a_neg[i] = levels_channel_signed(vN,
                (gfloat) a_in_black, (gfloat) a_in_white, (gfloat) a_gamma,
                (gfloat) a_out_black, (gfloat) a_out_white);
    lut_a_pos[i] = levels_channel_signed(vP,
                (gfloat) a_in_black, (gfloat) a_in_white, (gfloat) a_gamma,
                (gfloat) a_out_black, (gfloat) a_out_white);
    lut_b_neg[i] = levels_channel_signed(vN,
                (gfloat) b_in_black, (gfloat) b_in_white, (gfloat) b_gamma,
                (gfloat) b_out_black, (gfloat) b_out_white);
    lut_b_pos[i] = levels_channel_signed(vP,
                (gfloat) b_in_black, (gfloat) b_in_white, (gfloat) b_gamma,
                (gfloat) b_out_black, (gfloat) b_out_white);
  }
}

static inline gfloat
lut_sample(const gfloat *lut, gfloat v, gfloat lo, gfloat hi)
{
  gfloat t = (CLAMP(v, lo, hi) - lo) * (gfloat) (LUT_N - 1) / (hi - lo);
  gint i0 = (gint) t;
  if (i0 >= LUT_N - 1)
    return lut[LUT_N - 1];
  gfloat f = t - (gfloat) i0;
  return lut[i0] * (1.0f - f) + lut[i0 + 1] * f;
}

static void
prepare(GeglOperation *op)
{
  /* 直接声明 Lab 格式：babl 负责输入到 Lab、输出回 RGB 的转换，
   * 算子逐通道处理 L/a/b（D50 白点，与 GIMP 原生 Lab 工具一致）。 */
  gegl_operation_set_format(op, "input",  babl_format("CIE Lab alpha float"));
  gegl_operation_set_format(op, "output", babl_format("CIE Lab alpha float"));
}

static gboolean
process(GeglOperation       *op,
        GeglBuffer          *in_buf,
        GeglBuffer          *out_buf,
        const GeglRectangle *roi,
        gint                 level)
{
  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  /* 参数在 process 内部读取，彻底消除了 user_data 的并发竞争
   * Parameters are read inside process(), so the user_data race is gone. */
  gdouble L_in_black, L_in_white, L_gamma, L_out_black, L_out_white;
  gdouble a_in_black, a_in_white, a_gamma, a_out_black, a_out_white;
  gdouble b_in_black, b_in_white, b_gamma, b_out_black, b_out_white;

  g_object_get(G_OBJECT(op),
    "L-in-black", &L_in_black,
    "L-in-white", &L_in_white,
    "L-gamma",    &L_gamma,
    "L-out-black",&L_out_black,
    "L-out-white",&L_out_white,

    "a-in-black", &a_in_black,
    "a-in-white", &a_in_white,
    "a-gamma",    &a_gamma,
    "a-out-black",&a_out_black,
    "a-out-white",&a_out_white,

    "b-in-black", &b_in_black,
    "b-in-white", &b_in_white,
    "b-gamma",    &b_gamma,
    "b-out-black",&b_out_black,
    "b-out-white",&b_out_white,
    NULL);

  const Babl *fmt = babl_format("CIE Lab alpha float");

  gfloat *lut_L      = g_new(gfloat, LUT_N);
  gfloat *lut_a_neg  = g_new(gfloat, LUT_N);
  gfloat *lut_a_pos  = g_new(gfloat, LUT_N);
  gfloat *lut_b_neg  = g_new(gfloat, LUT_N);
  gfloat *lut_b_pos  = g_new(gfloat, LUT_N);
  lut_build(lut_L, lut_a_neg, lut_a_pos, lut_b_neg, lut_b_pos,
            L_in_black, L_in_white, L_gamma, L_out_black, L_out_white,
            a_in_black, a_in_white, a_gamma, a_out_black, a_out_white,
            b_in_black, b_in_white, b_gamma, b_out_black, b_out_white);

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };

    gegl_buffer_get(in_buf, &row_rect, 1.0f, fmt,
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint px = x * 4;
      gfloat L  = in_line[px + 0];
      gfloat ach = in_line[px + 1];
      gfloat bb  = in_line[px + 2];
      gfloat a   = in_line[px + 3];

      /* 透明像素原样透传（透明处色彩无意义，不做无谓的映射） */
      if (a <= 0.0f)
      {
        out_line[px + 0] = L;
        out_line[px + 1] = ach;
        out_line[px + 2] = bb;
        out_line[px + 3] = 0.0f;
        continue;
      }

      out_line[px + 0] = lut_sample(lut_L, L, 0.0f, 100.0f);
      out_line[px + 1] = (ach < 0.0f)
          ? lut_sample(lut_a_neg, ach, -128.0f, 0.0f)
          : lut_sample(lut_a_pos, ach, 0.0f, 127.0f);
      out_line[px + 2] = (bb < 0.0f)
          ? lut_sample(lut_b_neg, bb, -128.0f, 0.0f)
          : lut_sample(lut_b_pos, bb, 0.0f, 127.0f);
      out_line[px + 3] = a;
    }

    gegl_buffer_set(out_buf, &row_rect, 0, fmt,
                     out_line, GEGL_AUTO_ROWSTRIDE);
  }

  g_free(in_line);
  g_free(out_line);
  g_free(lut_L);
  g_free(lut_a_neg);
  g_free(lut_a_pos);
  g_free(lut_b_neg);
  g_free(lut_b_pos);
  return TRUE;
}

static void
gegl_op_class_init(GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS(klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS(klass);

  oclass->prepare = prepare;
  fclass->process = process;

  gegl_operation_class_set_keys(oclass,
    "name",            "lb:lab-levels",
    "title",           _("LAB Levels"),
    "categories",      "color",
    "description",     _("Independent levels adjustment for L,a,b channel, adjust tone and color separately"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Levels",
    "gimp:menu-label", _("LAB Levels"),
    NULL);
}

#endif
