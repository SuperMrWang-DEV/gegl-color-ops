/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:calculations
 * menu       Calculations
 * purpose    PS 计算：两路通道按混合模式合成，输出灰度图或 alpha 蒙版
 *            PS Calculations: blend two channels with a blend mode and output
 *            a grey image or an alpha mask.
 * algorithm  主输入取 source1 通道、aux 取 source2 通道，按混合模式算出标量，
 *            再按 mask × opacity 混回 source1
 *            Take a channel from the input and one from aux, blend the two
 *            scalars, then mix the result back into source1 by mask x opacity.
 * type       GeglOperationPointComposer（input + aux 双输入 / two inputs）
 * reference  Photoshop「图像 → 计算」/ Image > Calculations
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include "blend.h"

#ifdef GEGL_PROPERTIES

/* ---- 混合模式 / blend modes -------------------------------------------- */
enum_start (lb_calc_blend)
  enum_value (CALC_BLEND_NORMAL, "normal", "Normal")
  enum_value (CALC_BLEND_DARKEN, "darken", "Darken")
  enum_value (CALC_BLEND_MULTIPLY, "multiply", "Multiply")
  enum_value (CALC_BLEND_COLOR_BURN, "color-burn", "Color Burn")
  enum_value (CALC_BLEND_LINEAR_BURN, "linear-burn", "Linear Burn")
  enum_value (CALC_BLEND_LIGHTEN, "lighten", "Lighten")
  enum_value (CALC_BLEND_SCREEN, "screen", "Screen")
  enum_value (CALC_BLEND_COLOR_DODGE, "color-dodge", "Color Dodge")
  enum_value (CALC_BLEND_LINEAR_DODGE, "linear-dodge", "Linear Dodge (Add)")
  enum_value (CALC_BLEND_OVERLAY, "overlay", "Overlay")
  enum_value (CALC_BLEND_SOFT_LIGHT, "soft-light", "Soft Light")
  enum_value (CALC_BLEND_HARD_LIGHT, "hard-light", "Hard Light")
  enum_value (CALC_BLEND_VIVID_LIGHT, "vivid-light", "Vivid Light")
  enum_value (CALC_BLEND_LINEAR_LIGHT, "linear-light", "Linear Light")
  enum_value (CALC_BLEND_PIN_LIGHT, "pin-light", "Pin Light")
  enum_value (CALC_BLEND_HARD_MIX, "hard-mix", "Hard Mix")
  enum_value (CALC_BLEND_DIFFERENCE, "difference", "Difference")
  enum_value (CALC_BLEND_EXCLUSION, "exclusion", "Exclusion")
  enum_value (CALC_BLEND_SUBTRACT, "subtract", "Subtract")
  enum_value (CALC_BLEND_DIVIDE, "divide", "Divide")
  enum_value (CALC_BLEND_DARKER_COLOR, "darker-color", "Darker Color")
  enum_value (CALC_BLEND_LIGHTER_COLOR, "lighter-color", "Lighter Color")
  enum_value (CALC_BLEND_HUE, "hue", "Hue")
  enum_value (CALC_BLEND_SATURATION, "saturation", "Saturation")
  enum_value (CALC_BLEND_COLOR, "color", "Color")
  enum_value (CALC_BLEND_LUMINOSITY, "luminosity", "Luminosity")
enum_end (LbCalcBlend)

/* ---- 通道选择 / channel selection -------------------------------------- */
enum_start (lb_calc_channel)
  enum_value (CALC_CH_RED,    "red",    "Red")
  enum_value (CALC_CH_GREEN,  "green",  "Green")
  enum_value (CALC_CH_BLUE,   "blue",   "Blue")
  enum_value (CALC_CH_LUMA,   "luma",   "Luminance")
  enum_value (CALC_CH_ALPHA,  "alpha",  "Alpha")
enum_end (LbCalcChannel)

/* ---- 输出形式 / output mode -------------------------------------------- */
enum_start (lb_calc_output)
  enum_value (CALC_OUT_MASK_GRAY,  "mask-gray",  "Grey mask")
  enum_value (CALC_OUT_MASK_ALPHA, "mask-alpha", "Alpha mask")
enum_end (LbCalcOutput)

/* ---- 参数 / parameters ------------------------------------------------- */

property_enum (source1_channel, _("Source 1 channel"), LbCalcChannel, lb_calc_channel,
               CALC_CH_LUMA)
    description (_("Channel of the main input, used as the backdrop"))

property_boolean (invert_source1, _("Invert source 1"), FALSE)
    description (_("Use the inverted value of source 1"))

property_enum (source2_channel, _("Source 2 channel"), LbCalcChannel, lb_calc_channel,
               CALC_CH_LUMA)
    description (_("Channel of the aux input, used as the blend source"))

property_boolean (invert_source2, _("Invert source 2"), FALSE)
    description (_("Use the inverted value of source 2"))

property_enum (blend_mode, _("Blend mode"), LbCalcBlend, lb_calc_blend, CALC_BLEND_MULTIPLY)
    description (_("Blend mode between source 1 and source 2"))

property_double (opacity, _("Opacity"), 100.0)
    description (_("Blend strength, 0 = source 1 only, 100 = full blend"))
    value_range (0.0, 100.0)

property_boolean (mask_enabled, _("Use mask"), FALSE)
    description (_("Limit the effect with a channel of the aux input"))

property_enum (mask_channel, _("Mask channel"), LbCalcChannel, lb_calc_channel,
               CALC_CH_LUMA)
    description (_("Channel of the aux input used as the mask"))

property_boolean (invert_mask, _("Invert mask"), FALSE)
    description (_("Use the inverted mask value"))

property_enum (output_mode, _("Output"), LbCalcOutput, lb_calc_output,
               CALC_OUT_MASK_GRAY)
    description (_("Grey mask for layer masks, or alpha for direct transparency"))

#else

#define GEGL_OP_POINT_COMPOSER
#define GEGL_OP_NAME     lb_calculations
#define GEGL_OP_C_SOURCE calculations.c
#include "gegl-op.h"

/* ---- 格式 / formats ---------------------------------------------------- */

/* 感知（非线性）格式：混合模式与 PS 的 8bit 伽马域口径一致
 * Perceptual (non-linear) format, matching Photoshop's 8-bit gamma domain. */
static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}

static void
prepare (GeglOperation *op)
{
  const Babl *fmt = perceptual_format (op);

  /* 枚举顺序必须和 common/blend.h 的编号一致，这里自检一次。输出枚举只有
   * 两项（灰 / alpha），不从 LB_OUT_* 取值，故不参与比较。
   * The enum order must match the ids in common/blend.h; checked once here.
   * The output enum has two entries of its own and is deliberately excluded. */
  if ((gint) CALC_BLEND_DARKER_COLOR != LB_BLEND_DARKER_COLOR ||
      (gint) CALC_BLEND_LUMINOSITY  != LB_BLEND_LUMINOSITY   ||
      (gint) CALC_CH_ALPHA          != LB_CH_ALPHA)
    g_warning ("lb:calculations: enum order out of sync with common/blend.h");

  gegl_operation_set_format (op, "input",  fmt);
  gegl_operation_set_format (op, "aux",    fmt);
  gegl_operation_set_format (op, "output", fmt);
}

/* ---- 主处理 / main processing ------------------------------------------ */

static gboolean
process (GeglOperation       *op,
         void                *in_buf,
         void                *aux_buf,
         void                *out_buf,
         glong                samples,
         const GeglRectangle *roi,
         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (op);

  /* 没接 aux 时第二路退化为本图（此时等同单通道自混合）
   * Without aux the second source falls back to the input itself. */
  gfloat *GEGL_ALIGNED in  = in_buf;
  gfloat *GEGL_ALIGNED aux = aux_buf ? aux_buf : in_buf;
  gfloat *GEGL_ALIGNED out = out_buf;

  const gint   blend   = (gint) o->blend_mode;
  const gint   ch1     = (gint) o->source1_channel;
  const gint   ch2     = (gint) o->source2_channel;
  const gint   mch     = (gint) o->mask_channel;
  const gint   omode   = (gint) o->output_mode;
  const gfloat opacity = (gfloat) (o->opacity / 100.0);
  const gboolean use_mask = o->mask_enabled;
  const gboolean inv_mask = o->invert_mask;
  const gboolean inv1     = o->invert_source1;
  const gboolean inv2     = o->invert_source2;

  for (glong n = 0; n < samples; n++)
    {
      const gfloat ir = in[n * 4 + 0];
      const gfloat ig = in[n * 4 + 1];
      const gfloat ib = in[n * 4 + 2];
      const gfloat ia = in[n * 4 + 3];

      const gfloat sr = aux[n * 4 + 0];
      const gfloat sg = aux[n * 4 + 1];
      const gfloat sb = aux[n * 4 + 2];
      const gfloat sa = aux[n * 4 + 3];

      /* 两路各取一个通道并各自可选反相，再按遮罩混回 source 1
       * One channel from each side, each optionally inverted, then mixed
       * back into source 1 */
      gfloat v1 = lb_channel (ir, ig, ib, ia, ch1);
      gfloat v2 = lb_channel (sr, sg, sb, sa, ch2);

      if (inv1) v1 = 1.0f - v1;
      if (inv2) v2 = 1.0f - v2;

      gfloat mask = 1.0f;
      if (use_mask)
        {
          mask = lb_channel (sr, sg, sb, sa, mch);
          if (inv_mask)
            mask = 1.0f - mask;
        }

      const gfloat blended = lb_clamp01 (lb_blend_separable (blend, v1, v2));
      const gfloat grey    = lb_mix (v1, blended, mask, opacity);

      out[n * 4 + 0] = grey;
      out[n * 4 + 1] = grey;
      out[n * 4 + 2] = grey;
      out[n * 4 + 3] = (omode == CALC_OUT_MASK_ALPHA) ? grey : 1.0f;
    }

  return TRUE;
}

/* ---- 类初始化 / class init --------------------------------------------- */

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass         *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointComposerClass *cclass =
    GEGL_OPERATION_POINT_COMPOSER_CLASS (klass);

  oclass->prepare = prepare;
  cclass->process = process;

  GEGL_OPERATION_COMPOSER_CLASS (klass)->aux_label = _("Source 2");
  GEGL_OPERATION_COMPOSER_CLASS (klass)->aux_description = _("Second channel source (defaults to the input itself)");

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:calculations",
    "title",           _("Calculations"),
    "description",     _("PS Calculations: blend two channels into a grey or alpha "
                         "mask, 26 blend modes, per-source invert, mask and opacity."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Calculations"),
    NULL);
}

#endif
