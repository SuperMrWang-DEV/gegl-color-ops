/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:levels
 * menu       Levels
 * purpose    经典图像编辑器 色阶：复合 + R/G/B 四组「输入黑场 / 灰点 / 白场 + 输出黑场 /
 *            白场」，数值刻度 0–255，与 经典图像编辑器 对话框的数字框一一对应
 *            the classic editor Levels: composite plus per-channel input black / gamma /
 *            white and output black / white, in 0-255 units so the numbers
 *            match the classic dialog field for field.
 * algorithm  t   = clamp((v - inLow) / (inHigh - inLow), 0, 1)
 *            t'  = t ^ (1 / gamma)
 *            out = outLow + t' * (outHigh - outLow)
 *            逐通道在 8bit sRGB 伽马域直接算，不经线性光；复合组先做，再做
 *            各通道组（各通道默认恒等，所以「只动复合」与 经典图像编辑器的 RGB 通道
 *            模式逐位一致）。
 *            Evaluated per channel in the 8-bit sRGB gamma domain, never in
 *            linear light. The composite group runs first, then the per-
 *            channel groups; those default to identity, so "composite only"
 *            matches the classic editor's RGB channel mode exactly.
 * type       GeglOperationPointFilter（无邻域、可并行）
 * reference  经典图像编辑器「色阶」对话框
 *            the classic editor Levels dialog
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

/* 归一化到 0–1 的输入区间，便于内部计算
 * Values are stored in 0-255 (the classic editor units) and normalised to 0..1 internally */
#define LEVELS_UNIT 255.0

#ifdef GEGL_PROPERTIES

property_double (in_low, _("Input black"), 0.0)
    description (_("Composite channel input black: pixels at or below it become black."))
    value_range (0.0, 255.0)

property_double (in_gamma, _("Input grey"), 1.0)
    description (_("Composite midtones: >1 lightens, <1 darkens."))
    value_range (0.01, 9.99)

property_double (in_high, _("Input white"), 255.0)
    description (_("Composite channel input white: pixels at or above it become white."))
    value_range (0.0, 255.0)

property_double (out_low, _("Output black"), 0.0)
    description (_("Composite channel output black."))
    value_range (0.0, 255.0)

property_double (out_high, _("Output white"), 255.0)
    description (_("Composite channel output white."))
    value_range (0.0, 255.0)

property_double (red_in_low, _("Red input black"), 0.0)
    description (_("Red channel input black."))
    value_range (0.0, 255.0)

property_double (red_in_gamma, _("Red input grey"), 1.0)
    description (_("Red channel midtones: >1 lightens, <1 darkens."))
    value_range (0.01, 9.99)

property_double (red_in_high, _("Red input white"), 255.0)
    description (_("Red channel input white."))
    value_range (0.0, 255.0)

property_double (red_out_low, _("Red output black"), 0.0)
    description (_("Red channel output black."))
    value_range (0.0, 255.0)

property_double (red_out_high, _("Red output white"), 255.0)
    description (_("Red channel output white."))
    value_range (0.0, 255.0)

property_double (green_in_low, _("Green input black"), 0.0)
    description (_("Green channel input black."))
    value_range (0.0, 255.0)

property_double (green_in_gamma, _("Green input grey"), 1.0)
    description (_("Green channel midtones: >1 lightens, <1 darkens."))
    value_range (0.01, 9.99)

property_double (green_in_high, _("Green input white"), 255.0)
    description (_("Green channel input white."))
    value_range (0.0, 255.0)

property_double (green_out_low, _("Green output black"), 0.0)
    description (_("Green channel output black."))
    value_range (0.0, 255.0)

property_double (green_out_high, _("Green output white"), 255.0)
    description (_("Green channel output white."))
    value_range (0.0, 255.0)

property_double (blue_in_low, _("Blue input black"), 0.0)
    description (_("Blue channel input black."))
    value_range (0.0, 255.0)

property_double (blue_in_gamma, _("Blue input grey"), 1.0)
    description (_("Blue channel midtones: >1 lightens, <1 darkens."))
    value_range (0.01, 9.99)

property_double (blue_in_high, _("Blue input white"), 255.0)
    description (_("Blue channel input white."))
    value_range (0.0, 255.0)

property_double (blue_out_low, _("Blue output black"), 0.0)
    description (_("Blue channel output black."))
    value_range (0.0, 255.0)

property_double (blue_out_high, _("Blue output white"), 255.0)
    description (_("Blue channel output white."))
    value_range (0.0, 255.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_levels_ps
#define GEGL_OP_C_SOURCE levels.c
#include "gegl-op.h"

/* 一组色阶参数（已归一化到 0–1）
 * One levels group, already normalised to 0..1 */
typedef struct
{
  gfloat in_low;
  gfloat in_gamma;
  gfloat in_high;
  gfloat out_low;
  gfloat out_high;
} LevelsGroup;

static inline gfloat
sanitize_f (gfloat v)
{
  if (!isfinite (v))
    return 0.0f;
  return v;
}

/* 单通道色阶传递函数
 * Single-channel levels transfer function.

 * in_high == in_low 时区间退化成一点：按「台阶」处理（>= 该值为白，否则黑），
 * 而不是除以 0。经典图像编辑器的 UI 不允许把黑场拖过白场，但脚本/属性可以，得挡住。
 * When in_high == in_low the span collapses to a point; treat it as a step
 * (>= that value is white, below is black) instead of dividing by zero. */
static inline gfloat
levels_one (gfloat v, const LevelsGroup *p)
{
  gfloat span = p->in_high - p->in_low;
  gfloat t;

  if (span > 1e-6f)
    t = (v - p->in_low) / span;
  else
    t = (v >= p->in_high) ? 1.0f : 0.0f;

  if (t <= 0.0f)
    return p->out_low;
  if (t >= 1.0f)
    return p->out_high;

  /* gamma 与 1 差得极小时跳过 powf：大图上这是纯收益
   * Skip powf when gamma is ~1: pure win on large images */
  if (fabsf (p->in_gamma - 1.0f) > 1e-4f)
    t = powf (t, 1.0f / p->in_gamma);

  return p->out_low + t * (p->out_high - p->out_low);
}

/* 从属性读一组参数；属性是 0–255，这里一次性除以 255
 * Read one group from properties; properties are 0-255, divide once here */
static void
read_group (GObject *op, LevelsGroup *g,
            const gchar *low, const gchar *gamma, const gchar *high,
            const gchar *olow, const gchar *ohigh)
{
  gdouble lo = 0.0, ga = 1.0, hi = 255.0, olo = 0.0, ohi = 255.0;

  g_object_get (op, low, &lo, gamma, &ga, high, &hi, olow, &olo, ohigh, &ohi, NULL);

  g->in_low    = (gfloat) (lo  / LEVELS_UNIT);
  g->in_gamma  = (gfloat) MAX (ga, 0.01);
  g->in_high   = (gfloat) (hi  / LEVELS_UNIT);
  g->out_low   = (gfloat) (olo / LEVELS_UNIT);
  g->out_high  = (gfloat) (ohi / LEVELS_UNIT);
}

/* 感知（非线性）格式：色阶的黑白场是 8bit sRGB 编码值语义，必须拿伽马值，
 * 否则 babl 会喂线性光，输入色阶的数字就和 经典图像编辑器 对不上
 * Perceptual (non-linear) format: the black/white points are 8-bit sRGB
 * encoded values. Feeding linear light would make the numbers disagree
 * with the classic editor. */
static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}

static void
prepare (GeglOperation *op)
{
  gegl_operation_set_format (op, "input",  perceptual_format (op));
  gegl_operation_set_format (op, "output", perceptual_format (op));
}

static gboolean
process (GeglOperation       *op,
         void                *in_buf,
         void                *out_buf,
         glong                samples,
         const GeglRectangle *roi,
         gint                 level)
{
  LevelsGroup comp, red, grn, blu;

  read_group (G_OBJECT (op), &comp, "in-low", "in-gamma", "in-high",
              "out-low", "out-high");
  read_group (G_OBJECT (op), &red, "red-in-low", "red-in-gamma", "red-in-high",
              "red-out-low", "red-out-high");
  read_group (G_OBJECT (op), &grn, "green-in-low", "green-in-gamma",
              "green-in-high", "green-out-low", "green-out-high");
  read_group (G_OBJECT (op), &blu, "blue-in-low", "blue-in-gamma",
              "blue-in-high", "blue-out-low", "blue-out-high");

  const gfloat *in  = (const gfloat *) in_buf;
  gfloat       *out = (gfloat *) out_buf;

  for (glong i = 0; i < samples; i++)
    {
      gfloat r = in[0], g = in[1], b = in[2];

      /* 1) 复合组：三通道同一条曲线
       * 1) composite group: one curve for all three channels */
      r = levels_one (r, &comp);
      g = levels_one (g, &comp);
      b = levels_one (b, &comp);

      /* 2) 各通道组（默认恒等）
       * 2) per-channel groups (identity by default) */
      r = levels_one (r, &red);
      g = levels_one (g, &grn);
      b = levels_one (b, &blu);

      out[0] = CLAMP (sanitize_f (r), 0.0f, 1.0f);
      out[1] = CLAMP (sanitize_f (g), 0.0f, 1.0f);
      out[2] = CLAMP (sanitize_f (b), 0.0f, 1.0f);
      out[3] = sanitize_f (in[3]);

      in  += 4;
      out += 4;
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass            *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointFilterClass *pclass = GEGL_OPERATION_POINT_FILTER_CLASS (klass);

  oclass->prepare = prepare;
  pclass->process = process;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:levels",
    "title",           _("Levels"),
    "description",     _("Replicate the classic editor Levels (composite + per-channel input black/gamma/white and output black/white, 0-255 units). Evaluated in the 8-bit sRGB gamma domain, so the numbers agree with the classic dialog."),
    "gimp:menu-path",  "<Image>/SuperMrWang/Levels",
    "gimp:menu-label", _("Levels"),
    NULL);
}

#endif
