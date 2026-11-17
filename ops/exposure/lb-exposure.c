/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:exposure
 * menu       Exposure EV
 * purpose    经典图像编辑器 曝光：EV、偏移、伽马三段式调整（按 EV 计曝光档位）
 *            the classic editor Exposure: EV, offset and gamma in three stages, measured in
 *            exposure stops.
 * algorithm  两条公式，按输入精度自动选择 / Two formulas chosen automatically
 *            from the input precision:
 *
 *            ① 8 位（整数格式，sRGB 伽马编码值）—— 分支一
 *               v1 = min(c · 2^(EV/2.2), 1)
 *               v2 = clamp(v1^2.2 + offset, 0, 1)^(1/2.2)
 *               v3 = v2^(1/gamma)
 *               在伽马域乘 2^(EV/2.2) 等价于线性光乘 2^EV，省掉两次幂运算；
 *               偏移 offset 加在**线性**光上，所以中间要解一次 2.2。
 *               Multiplying in gamma space by 2^(EV/2.2) equals multiplying
 *               linear light by 2^EV. The offset is added in linear light,
 *               hence the 2.2 decode/encode pair in the middle.
 *
 *            ② 32 位（浮点格式，线性光）—— 分支二
 *               v1 = c · 2^EV + offset
 *               v2 = v1^(1/gamma)
 *               输入已经是线性光，没有 2.2 的往返。
 *               Linear input, so the 2.2 round trip disappears.
 *
 *            分支一先按 min(…,1) 切掉高光再叠 offset —— 负 offset 因此还能把
 *            过曝区拉回来；漏掉这一步，EV>0 配负 offset 会直接顶成白。
 *            Branch one clips highlights *before* adding the offset, so a
 *            negative offset can still pull blown areas back.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * reference  用户给定的 Java 实现（BlendColor.exposure / exposure2）
 *            The Java implementation supplied by the user
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

enum_start (lb_exposure_precision)
  enum_value (LB_EXPOSURE_AUTO,    "auto",    "Auto (from input precision)")
  enum_value (LB_EXPOSURE_ENCODED, "encoded", "8-bit (sRGB gamma)")
  enum_value (LB_EXPOSURE_LINEAR,  "linear",  "32-bit (linear)")
enum_end (LbExposurePrecision)

property_double (exposure, _("Exposure"), 0.0)
    description (_("Exposure (EV), same slider range as the classic editor"))
    value_range (-20.0, 20.0)
    ui_range (-6.0, 6.0)

property_double (offset, _("Offset"), 0.0)
    description (_("Offset, adjusts shadow and midtone; added in linear light"))
    value_range (-0.5, 0.5)
    ui_range (-0.2, 0.2)

property_double (gamma, _("Gamma Correction"), 1.0)
    description (_("Gray coefficient correction / Gamma"))
    value_range (0.01, 9.99)
    ui_range (0.10, 3.0)

property_enum (precision, _("Precision"), LbExposurePrecision, lb_exposure_precision,
               LB_EXPOSURE_AUTO)
    description (_("Which formula to run. Auto picks the 8-bit (gamma) branch for "
                   "integer input and the 32-bit (linear) branch for float input"))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_exposure
#define GEGL_OP_C_SOURCE lb-exposure.c
#include "gegl-op.h"

#define GAMMA_SRGB      2.2f
#define SAFE_GAMMA_MIN  0.001f

static inline gfloat sanitize_f(gfloat v)
{
  if (!isfinite(v))
    return 0.0f;
  return v;
}

static inline gfloat safe_gamma(gdouble gamma)
{
  return MAX((gfloat)gamma, SAFE_GAMMA_MIN);
}

/* 8 位分支：伽马编码域（u8/u16 图像）
 * Encoded branch: works on gamma-encoded values (u8 / u16 images) */
static inline gfloat
exposure_encoded(gfloat in, gdouble exposure, gdouble offset, gdouble gamma)
{
  gfloat v1, v2;

  in = MAX(sanitize_f(in), 0.0f);

  /* ① 曝光：伽马域乘 2^(EV/2.2) ≡ 线性光乘 2^EV，并在此切掉高光
   * (1) exposure: gamma-space ×2^(EV/2.2) = linear ×2^EV, clip here */
  v1 = MIN(in * powf(2.0f, (gfloat)exposure / GAMMA_SRGB), 1.0f);

  /* ② 偏移：解到线性光、加 offset、钳位、再编码回去
   * (2) offset: decode to linear, add, clamp, encode back */
  v2 = CLAMP(powf(v1, GAMMA_SRGB) + (gfloat)offset, 0.0f, 1.0f);

  /* ③ 伽马校正
   * (3) gamma correction */
  return powf(powf(v2, 1.0f / GAMMA_SRGB), 1.0f / safe_gamma(gamma));
}

/* 32 位分支：线性光（float 图像），没有 2.2 往返
 * Linear branch: linear-light values (float images), no 2.2 round trip.
 * 只做下限钳位（powf 的定义域），上限不动 —— 32 位图允许 HDR，
 * 按 0…1 截断会把高光压平。Java 版末尾的 clamp 是它 0…1 数据模型的产物。
 * Only the lower bound is clamped (powf's domain); HDR highlights above 1.0
 * pass through, since clipping them would flatten a 32-bit image. */
static inline gfloat
exposure_linear(gfloat in, gdouble exposure, gdouble offset, gdouble gamma)
{
  gfloat v = sanitize_f(in) * powf(2.0f, (gfloat)exposure) + (gfloat)offset;

  if (v < 0.0f)
    v = 0.0f;

  if (v == 0.0f)
    return 0.0f;

  return powf(v, 1.0f / safe_gamma(gamma));
}

/* 感知（非线性）格式：8 位路径要求拿伽马编码值，不能喂线性光。
 * 32 位路径拿到的仍是缓冲里的原值（线性），两条分支共用这个格式。
 * Perceptual format: the 8-bit branch needs gamma-encoded values. For float
 * images the same format carries the original (linear) numbers. */
static const Babl *
perceptual_format(GeglOperation *op)
{
  return babl_format_with_space("R~G~B~A float",
                                gegl_operation_get_source_space(op, "input"));
}

/* 自动判精度：整数格式（u8/u16）是伽马编码，浮点格式是线性光。
 * Auto-detect: integer formats (u8/u16) are gamma-encoded, float formats
 * (float/half/double) are linear light. */
static gboolean
input_is_linear(GeglOperation *op, LbExposurePrecision precision)
{
  const Babl *fmt;
  const gchar *name;

  if (precision == LB_EXPOSURE_LINEAR)
    return TRUE;
  if (precision == LB_EXPOSURE_ENCODED)
    return FALSE;

  fmt = gegl_operation_get_source_format(op, "input");
  if (fmt == NULL)
    return FALSE;                       /* 判不出来时按历史行为走 8 位 */

  name = babl_get_name(fmt);
  if (name == NULL)
    return FALSE;

  return (strstr(name, "float") != NULL ||
          strstr(name, "double") != NULL ||
          strstr(name, "half") != NULL);
}

static void
prepare(GeglOperation *op)
{
  /* 输入输出都钉成感知格式
   * Pin both pads to the perceptual format */
  gegl_operation_set_format(op, "input",  perceptual_format(op));
  gegl_operation_set_format(op, "output", perceptual_format(op));
}

static gboolean
process(GeglOperation       *op,
        GeglBuffer          *in_buf,
        GeglBuffer          *out_buf,
        const GeglRectangle *roi,
        gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES(op);
  const gdouble exposure = o->exposure;
  const gdouble offset   = o->offset;
  const gdouble gamma    = o->gamma;
  gboolean linear;
  gint stride;
  gfloat *in_line, *out_line;
  gint y;

  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  linear = input_is_linear(op, o->precision);

  stride   = roi->width * 4;
  in_line  = g_new(gfloat, stride);
  out_line = g_new(gfloat, stride);

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };
      gint x;

      gegl_buffer_get(in_buf, &row_rect, 1.0f, perceptual_format(op),
                      in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (x = 0; x < roi->width; x++)
        {
          gint px = x * 4;

          if (linear)
            {
              out_line[px + 0] = exposure_linear(in_line[px + 0], exposure, offset, gamma);
              out_line[px + 1] = exposure_linear(in_line[px + 1], exposure, offset, gamma);
              out_line[px + 2] = exposure_linear(in_line[px + 2], exposure, offset, gamma);
            }
          else
            {
              out_line[px + 0] = exposure_encoded(in_line[px + 0], exposure, offset, gamma);
              out_line[px + 1] = exposure_encoded(in_line[px + 1], exposure, offset, gamma);
              out_line[px + 2] = exposure_encoded(in_line[px + 2], exposure, offset, gamma);
            }

          out_line[px + 3] = sanitize_f(in_line[px + 3]);
        }

      gegl_buffer_set(out_buf, &row_rect, 0, perceptual_format(op),
                      out_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free(in_line);
  g_free(out_line);
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
    "name",            "lb:exposure",
    "title",           _("Exposure EV"),
    "description",     _("the classic editor Exposure: EV, offset and gamma. Picks the 8-bit (gamma) formula for integer images and the 32-bit (linear) formula for float images; override with the precision property."),
    "gimp:menu-path",  "<Image>/SuperMrWang/Tone",
    "gimp:menu-label", _("Exposure EV"),
    NULL);
}

#endif
