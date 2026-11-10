/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:channel-range-to-alpha
 * menu       Range → Alpha
 * purpose    按通道数值区间（0–255）生成 alpha，实现「混合颜色带」式透明控制
 *            Build alpha from a numeric range (0-255) of one channel, i.e.
 *            Blend-If style transparency.
 * algorithm  选定 RGB / 亮度 / LAB L·A·B 通道，区间内不透明，区间外按
 *            fuzziness 与 feather 平滑衰减
 *            Pick an RGB, luminance or LAB L/a/b channel. Values inside the
 *            range stay opaque, values outside fade out by 'fuzziness' and
 *            'feather'.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  Photoshop「混合颜色带」(Blend If)
 *            Photoshop Blend If
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_enum (channel, _("Channel"),
               ChannelEnum, channel_enum, CHANNEL_RED)
    description (_("Select color channel, luminance or LAB L/A/B"))

enum_start (channel_enum)
  enum_value (CHANNEL_RED,    "red",     N_("Red"))
  enum_value (CHANNEL_GREEN,  "green",   N_("Green"))
  enum_value (CHANNEL_BLUE,   "blue",    N_("Blue"))
  enum_value (CHANNEL_GRAY,   "gray",    N_("Gray (Luminance)"))
  enum_value (CHANNEL_LAB_L,  "lab-l",   N_("LAB L (Lightness)"))
  enum_value (CHANNEL_LAB_A,  "lab-a",   N_("LAB A (Red-Green)"))
  enum_value (CHANNEL_LAB_B,  "lab-b",   N_("LAB B (Yellow-Blue)"))
enum_end (ChannelEnum)

/* 滑块范围统一 0~255，内部自动映射 LAB 值域
 * Slider range is 0~255 everywhere; the LAB value range is mapped
 * internally. */
/* 滑块显示名沿用 Photoshop 风格：阴影/高光的最小值与最大值
 * Slider labels follow Photoshop: Shadow Min/Max and Highlight Min/Max. */
/* 内部属性名保持 l1、l2、r1、r2，方便代码复用
 * Internal property names stay l1, l2, r1, r2 to keep the code simple. */

property_double (l1, _("Shadow Min"), 0.0)
    value_range (0.0, 255.0)
    ui_range (0.0, 255.0)

property_double (l2, _("Shadow Max"), 0.0)
    value_range (0.0, 255.0)
    ui_range (0.0, 255.0)

property_double (r1, _("Highlight Min"), 255.0)
    value_range (0.0, 255.0)
    ui_range (0.0, 255.0)

property_double (r2, _("Highlight Max"), 255.0)
    value_range (0.0, 255.0)
    ui_range (0.0, 255.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_channel_range_to_alpha
#define GEGL_OP_C_SOURCE channel-range-to-alpha.c

#include "gegl-op.h"

/* 最小间隔 1.0（0~255 量程）
 * Minimum step 1.0 on the 0~255 scale */
#define MIN_STEP 1.0f
/* LAB 值域常量
 * LAB value-range constants */
#define LAB_L_MIN 0.0f
#define LAB_L_MAX 100.0f
#define LAB_AB_MIN -128.0f
#define LAB_AB_MAX 127.0f


/* sRGB → XYZ 的伽马校正辅助函数
 * sRGB to XYZ helper: gamma correction */
static inline gfloat srgb_to_linear(gfloat val)
{
  if (val <= 0.04045f)
    return val / 12.92f;
  else
    return powf((val + 0.055f) / 1.055f, 2.4f);
}

/* 线性 RGB（sRGB D65）→ CIE XYZ
 * Linear RGB (sRGB D65) -> CIE XYZ */
static void rgb_to_xyz(gfloat r, gfloat g, gfloat b,
                       gfloat *x, gfloat *y, gfloat *z)
{
  gfloat lr = srgb_to_linear(r);
  gfloat lg = srgb_to_linear(g);
  gfloat lb = srgb_to_linear(b);

  /* D65 转换矩阵
   * D65 conversion matrix */
  *x = 0.4124564f * lr + 0.3575761f * lg + 0.1804375f * lb;
  *y = 0.2126729f * lr + 0.7151522f * lg + 0.0721750f * lb;
  *z = 0.0193339f * lr + 0.1191920f * lg + 0.9503041f * lb;
}

/* XYZ → LAB（D65 白点）
 * XYZ -> LAB with the D65 white point */
static inline gfloat lab_f(gfloat t)
{
  const gfloat t0 = powf(6.0f / 29.0f, 3.0f);
  if (t > t0)
    return powf(t, 1.0f / 3.0f);
  else
    return (t * 3.0f * powf(29.0f / 6.0f, 2.0f)) + 4.0f / 29.0f;
}

static void xyz_to_lab(gfloat x, gfloat y, gfloat z,
                       gfloat *L, gfloat *a, gfloat *b)
{
  /* D65 白点
   * D65 white point */
  const gfloat xn = 0.95047f;
  const gfloat yn = 1.00000f;
  const gfloat zn = 1.08883f;

  gfloat fx = lab_f(x / xn);
  gfloat fy = lab_f(y / yn);
  gfloat fz = lab_f(z / zn);

  *L = 116.0f * fy - 16.0f;
  *a = 500.0f * (fx - fy);
  *b = 200.0f * (fy - fz);
}

/* 入口：输入 RGBA float（0~1），直接给出 LAB 的 L/A/B
 * entry point: RGBA float (0~1) in, LAB L/A/B out */
static void rgb_to_lab(gfloat r, gfloat g, gfloat b,
                       gfloat *lab_L, gfloat *lab_A, gfloat *lab_B)
{
  gfloat x, y, z;
  rgb_to_xyz(r, g, b, &x, &y, &z);
  xyz_to_lab(x, y, z, lab_L, lab_A, lab_B);
}

/* 标准灰度亮度
 * standard grey luminance */
static inline gfloat luminance(gfloat r, gfloat g, gfloat b)
{
    return 0.299f * r + 0.587f * g + 0.114f * b;
}

/* 透明度计算（Blend If 算法）
 * alpha computation (Blend If algorithm) */
static inline gfloat blend_if_alpha(gfloat x, gfloat l1, gfloat l2, gfloat r1, gfloat r2)
{
    if (x < l1 || x > r2)
        return 0.0f;
    if (x >= l2 && x <= r1)
        return 1.0f;

    gfloat alpha = 0.0f;
    if (x >= l1 && x < l2)
    {
        gfloat span = l2 - l1;
        alpha = (span < 1e-3f) ? 1.0f : (x - l1) / span;
    }
    else if (x > r1 && x <= r2)
    {
        gfloat span = r2 - r1;
        alpha = (span < 1e-3f) ? 1.0f : 1.0f - (x - r1) / span;
    }
    return CLAMP(alpha, 0.0f, 1.0f);
}

static void prepare(GeglOperation *operation)
{
    gegl_operation_set_format(operation, "input", babl_format("RGBA float"));
    gegl_operation_set_format(operation, "output", babl_format("RGBA float"));
}

/* 统一矫正滑块顺序，防止区间反转
 * clamp the slider order so the ranges cannot invert */
/* l1=阴影下限 l2=阴影上限 r1=高光下限 r2=高光上限
 * l1=Shadow Min, l2=Shadow Max, r1=Highlight Min, r2=Highlight Max */
static void clamp_slider_order(gdouble *l1, gdouble *l2, gdouble *r1, gdouble *r2)
{
    *l1 = CLAMP(*l1, 0.0, 255.0);
    *l2 = CLAMP(*l2, 0.0, 255.0);
    *r1 = CLAMP(*r1, 0.0, 255.0);
    *r2 = CLAMP(*r2, 0.0, 255.0);

    if (*l2 <= *l1 + MIN_STEP)
        *l2 = *l1 + MIN_STEP;
    if (*r1 <= *l2 + MIN_STEP)
        *r1 = *l2 + MIN_STEP;
    if (*r2 <= *r1 + MIN_STEP)
        *r2 = *r1 + MIN_STEP;
}

/* 把 LAB 值域映射到 0~255 的滑块区间
 * map the LAB range onto the 0~255 slider range */
static inline gfloat labL_to_0_255(gfloat L)
{
    gfloat norm = (L - LAB_L_MIN) / (LAB_L_MAX - LAB_L_MIN);
    return CLAMP(norm, 0.0f, 1.0f) * 255.0f;
}
static inline gfloat labAB_to_0_255(gfloat ab)
{
    gfloat norm = (ab - LAB_AB_MIN) / (LAB_AB_MAX - LAB_AB_MIN);
    return CLAMP(norm, 0.0f, 1.0f) * 255.0f;
}

static gboolean process(
    GeglOperation *op,
    GeglBuffer    *input,
    GeglBuffer    *output,
    const GeglRectangle *roi,
    gint           level)
{
    if (!roi || roi->width <= 0 || roi->height <= 0)
        return TRUE;

    ChannelEnum channel;
    gdouble l1, l2, r1, r2;

    g_object_get(G_OBJECT(op),
        "channel", &channel,
        "l1", &l1,
        "l2", &l2,
        "r1", &r1,
        "r2", &r2,
        NULL);

    clamp_slider_order(&l1, &l2, &r1, &r2);

    gint n_pixels = roi->width * roi->height;
    gsize buf_size = n_pixels * 4 * sizeof(gfloat);

    gfloat *in_buffer = g_malloc0(buf_size);
    gfloat *out_buffer = g_malloc0(buf_size);

    gegl_buffer_get(input, roi, 1.0, babl_format("RGBA float"),
                    in_buffer, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint i = 0; i < n_pixels; i++)
    {
        gfloat r = in_buffer[i*4 + 0];
        gfloat g = in_buffer[i*4 + 1];
        gfloat b = in_buffer[i*4 + 2];
        gfloat a = in_buffer[i*4 + 3];

        gfloat x = 0.0f;
        switch (channel)
        {
            case CHANNEL_RED:
                x = r * 255.0f;
                break;
            case CHANNEL_GREEN:
                x = g * 255.0f;
                break;
            case CHANNEL_BLUE:
                x = b * 255.0f;
                break;
            case CHANNEL_GRAY:
                x = luminance(r,g,b) * 255.0f;
                break;
            case CHANNEL_LAB_L:
            {
                gfloat L, A, B;
                rgb_to_lab(r,g,b,&L,&A,&B);
                x = labL_to_0_255(L);
                break;
            }
            case CHANNEL_LAB_A:
            {
                gfloat L, A, B;
                rgb_to_lab(r,g,b,&L,&A,&B);
                x = labAB_to_0_255(A);
                break;
            }
            case CHANNEL_LAB_B:
            {
                gfloat L, A, B;
                rgb_to_lab(r,g,b,&L,&A,&B);
                x = labAB_to_0_255(B);
                break;
            }
            default:
                x = 0.0f;
        }

        gfloat mask_alpha = blend_if_alpha(x, l1, l2, r1, r2);

        out_buffer[i*4 + 0] = r;
        out_buffer[i*4 + 1] = g;
        out_buffer[i*4 + 2] = b;
        out_buffer[i*4 + 3] = a * mask_alpha;
    }

    gegl_buffer_set(output, roi, 0, babl_format("RGBA float"),
                    out_buffer, GEGL_AUTO_ROWSTRIDE);

    g_free(in_buffer);
    g_free(out_buffer);
    return TRUE;
}

static void gegl_op_class_init(GeglOpClass *klass)
{
    GeglOperationClass *op_class = GEGL_OPERATION_CLASS(klass);
    GeglOperationFilterClass *filter_class = GEGL_OPERATION_FILTER_CLASS(klass);

    op_class->prepare = prepare;
    filter_class->process = process;

    gegl_operation_class_set_keys(op_class,
        "name",            "lb:channel-range-to-alpha",
        "title",           _("Channel Range to Alpha"),
        "description",     "Adjust opacity based on channel values, supports RGB, Gray and LAB L/A/B, slider 0~255",
        "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
        "gimp:menu-label", _("Range → Alpha"),
        NULL);
}

#endif