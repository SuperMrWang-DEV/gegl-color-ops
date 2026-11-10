/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:apply-image
 * menu       Apply Image
 * purpose    PS 应用图像：把 aux 输入当成源，按混合模式、不透明度与遮罩压到
 *            主输入上，可选只作用于某一个通道
 *            PS Apply Image: blend the aux input over the main input with a
 *            blend mode, opacity and mask, optionally per channel.
 * algorithm  两路 RGBA 逐像素混合：先取目标/源通道（RGB、亮度、alpha 或合成），
 *            按混合模式算出结果，再用 mask × opacity 混回原值
 *            Two RGBA streams are blended per pixel: pick the target and
 *            source channels (RGB, luma, alpha or composite), run the blend
 *            mode, then mix the result back by mask x opacity.
 * type       GeglOperationPointComposer（input + aux 双输入 / two inputs）
 * reference  Photoshop「图像 → 应用图像」/ Image > Apply Image
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include "blend.h"

#ifdef GEGL_PROPERTIES

/* ---- 混合模式 / blend modes -------------------------------------------- */
enum_start (lb_ai_blend)
  enum_value (AI_BLEND_NORMAL, "normal", "Normal")
  enum_value (AI_BLEND_DARKEN, "darken", "Darken")
  enum_value (AI_BLEND_MULTIPLY, "multiply", "Multiply")
  enum_value (AI_BLEND_COLOR_BURN, "color-burn", "Color Burn")
  enum_value (AI_BLEND_LINEAR_BURN, "linear-burn", "Linear Burn")
  enum_value (AI_BLEND_LIGHTEN, "lighten", "Lighten")
  enum_value (AI_BLEND_SCREEN, "screen", "Screen")
  enum_value (AI_BLEND_COLOR_DODGE, "color-dodge", "Color Dodge")
  enum_value (AI_BLEND_LINEAR_DODGE, "linear-dodge", "Linear Dodge (Add)")
  enum_value (AI_BLEND_OVERLAY, "overlay", "Overlay")
  enum_value (AI_BLEND_SOFT_LIGHT, "soft-light", "Soft Light")
  enum_value (AI_BLEND_HARD_LIGHT, "hard-light", "Hard Light")
  enum_value (AI_BLEND_VIVID_LIGHT, "vivid-light", "Vivid Light")
  enum_value (AI_BLEND_LINEAR_LIGHT, "linear-light", "Linear Light")
  enum_value (AI_BLEND_PIN_LIGHT, "pin-light", "Pin Light")
  enum_value (AI_BLEND_HARD_MIX, "hard-mix", "Hard Mix")
  enum_value (AI_BLEND_DIFFERENCE, "difference", "Difference")
  enum_value (AI_BLEND_EXCLUSION, "exclusion", "Exclusion")
  enum_value (AI_BLEND_SUBTRACT, "subtract", "Subtract")
  enum_value (AI_BLEND_DIVIDE, "divide", "Divide")
  enum_value (AI_BLEND_DARKER_COLOR, "darker-color", "Darker Color")
  enum_value (AI_BLEND_LIGHTER_COLOR, "lighter-color", "Lighter Color")
  enum_value (AI_BLEND_HUE, "hue", "Hue")
  enum_value (AI_BLEND_SATURATION, "saturation", "Saturation")
  enum_value (AI_BLEND_COLOR, "color", "Color")
  enum_value (AI_BLEND_LUMINOSITY, "luminosity", "Luminosity")
enum_end (LbAiBlend)

/* ---- 通道选择 / channel selection -------------------------------------- */
enum_start (lb_ai_channel)
  enum_value (AI_CH_COMPOSITE, "composite", "Composite")
  enum_value (AI_CH_RED,       "red",       "Red")
  enum_value (AI_CH_GREEN,     "green",     "Green")
  enum_value (AI_CH_BLUE,      "blue",      "Blue")
  enum_value (AI_CH_LUMA,      "luma",      "Luminance")
  enum_value (AI_CH_ALPHA,     "alpha",     "Alpha")
enum_end (LbAiChannel)

/* ---- 输出形式 / output mode -------------------------------------------- */
enum_start (lb_ai_output)
  enum_value (AI_OUT_COMPOSITE,  "composite",  "Composite")
  enum_value (AI_OUT_MASK_GRAY,  "mask-gray",  "Mask (grey)")
  enum_value (AI_OUT_MASK_ALPHA, "mask-alpha", "Mask (alpha)")
enum_end (LbAiOutput)

/* ---- 遮罩来源 / mask source -------------------------------------------- */
enum_start (lb_ai_mask_from)
  enum_value (AI_MASK_AUX,   "aux",   "Source layer")
  enum_value (AI_MASK_INPUT, "input", "This layer")
enum_end (LbAiMaskFrom)

/* ---- 参数 / parameters ------------------------------------------------- */

property_enum (blend_mode, _("Blend mode"), LbAiBlend, lb_ai_blend, AI_BLEND_MULTIPLY)
    description (_("How the source (aux) is combined with the target"))

property_double (opacity, _("Opacity"), 100.0)
    description (_("Blend strength, 0 = untouched target, 100 = full blend"))
    value_range (0.0, 100.0)

property_enum (target_channel, _("Target channel"), LbAiChannel, lb_ai_channel,
               AI_CH_COMPOSITE)
    description (_("Which channel of the main input receives the blend"))

property_enum (source_channel, _("Source channel"), LbAiChannel, lb_ai_channel,
               AI_CH_COMPOSITE)
    description (_("Which channel of the aux input is used as the source"))

property_boolean (mask_enabled, _("Use mask"), FALSE)
    description (_("Limit the effect with a channel of the chosen layer"))

property_enum (mask_from, _("Mask from"), LbAiMaskFrom, lb_ai_mask_from, AI_MASK_AUX)
    description (_("Which of the two connected layers the mask channel is read from"))

property_enum (mask_channel, _("Mask channel"), LbAiChannel, lb_ai_channel,
               AI_CH_COMPOSITE)
    description (_("Channel used as the mask; Composite reads luminance"))

property_boolean (invert_mask, _("Invert mask"), FALSE)
    description (_("Use the inverted mask value"))

property_boolean (preserve_transparency, _("Preserve transparency"), FALSE)
    description (_("Leave fully transparent pixels untouched"))

property_enum (output_mode, _("Output"), LbAiOutput, lb_ai_output, AI_OUT_COMPOSITE)
    description (_("Composite result, or the blended channel as a grey / alpha mask"))

#else

#define GEGL_OP_POINT_COMPOSER
#define GEGL_OP_NAME     lb_apply_image
#define GEGL_OP_C_SOURCE apply-image.c
#include "gegl-op.h"

/* ---- 格式 / formats ---------------------------------------------------- */

/* 感知（非线性）格式：混合模式按 8bit sRGB 伽马域定义，线性光下中间调会偏
 * Perceptual (non-linear) format: Photoshop blend modes are defined in the
 * 8-bit sRGB gamma domain; linear light shifts the mid-tones. */
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

  /* 枚举顺序必须和 common/blend.h 的编号一致，这里自检一次
   * The enum order must match the ids in common/blend.h; check it once. */
  if ((gint) AI_BLEND_DARKER_COLOR != LB_BLEND_DARKER_COLOR ||
      (gint) AI_BLEND_HUE          != LB_BLEND_HUE          ||
      (gint) AI_BLEND_LUMINOSITY   != LB_BLEND_LUMINOSITY   ||
      (gint) AI_CH_ALPHA           != LB_CH_ALPHA           ||
      (gint) AI_OUT_MASK_ALPHA     != LB_OUT_MASK_ALPHA)
    g_warning ("lb:apply-image: enum order out of sync with common/blend.h");

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

  /* aux 没接时退化成「源 = 本图」，至少能当通道内的混合用
   * With no aux connected the source falls back to the input itself, so the
   * op still works as a within-image channel blend. */
  gfloat *GEGL_ALIGNED in  = in_buf;
  gfloat *GEGL_ALIGNED aux = aux_buf ? aux_buf : in_buf;
  gfloat *GEGL_ALIGNED out = out_buf;

  const gint   blend   = (gint) o->blend_mode;
  const gint   tch     = (gint) o->target_channel;
  const gint   sch     = (gint) o->source_channel;
  const gint   mch     = (gint) o->mask_channel;
  const gint   mfrom   = (gint) o->mask_from;
  const gint   omode   = (gint) o->output_mode;
  const gfloat opacity = (gfloat) (o->opacity / 100.0);
  const gboolean use_mask = o->mask_enabled;
  const gboolean inv_mask = o->invert_mask;
  const gboolean keep_transp = o->preserve_transparency;

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

      gfloat rr = ir, rg = ig, rb = ib, ra = ia;

      /* 全透明像素：按 PS 的「保留透明区域」直接跳过
       * Fully transparent pixels are skipped when preservation is on */
      if (keep_transp && ia <= 0.0f)
        {
          out[n * 4 + 0] = ir;
          out[n * 4 + 1] = ig;
          out[n * 4 + 2] = ib;
          out[n * 4 + 3] = ia;
          continue;
        }

      /* 遮罩可取自源层或本层，两者都已在手边，不必再开第三个 pad
       * The mask is read from either connected layer, so no third pad is
       * needed to cover both halves of PS's mask options. */
      gfloat mask = 1.0f;
      if (use_mask)
        {
          mask = (mfrom == AI_MASK_INPUT)
                   ? lb_channel (ir, ig, ib, ia, mch)
                   : lb_channel (sr, sg, sb, sa, mch);
          if (inv_mask)
            mask = 1.0f - mask;
        }

      if (tch == LB_CH_COMPOSITE && sch == LB_CH_COMPOSITE)
        {
          /* 合成 × 合成：三通道各自混合，色相类模式走整体算法
           * Composite x composite: blend all three channels, hue-family
           * modes go through the whole-pixel path. */
          gfloat br, bg, bb;
          lb_blend_rgb (blend, ir, ig, ib, sr, sg, sb, &br, &bg, &bb);
          rr = lb_mix (ir, br, mask, opacity);
          rg = lb_mix (ig, bg, mask, opacity);
          rb = lb_mix (ib, bb, mask, opacity);
        }
      else if (tch != LB_CH_COMPOSITE)
        {
          /* 目标是单通道：源取标量（单通道取值，合成都取亮度）
           * Single target channel: source becomes a scalar (its own channel,
           * or luma when the source is the composite). */
          const gfloat tv = lb_channel (ir, ig, ib, ia, tch);
          const gfloat sv = (sch == LB_CH_COMPOSITE)
                              ? lb_luma (sr, sg, sb)
                              : lb_channel (sr, sg, sb, sa, sch);
          const gfloat nv = lb_mix (tv, lb_blend_separable (blend, tv, sv),
                                    mask, opacity);

          switch (tch)
            {
              case LB_CH_RED:   rr = nv; break;
              case LB_CH_GREEN: rg = nv; break;
              case LB_CH_BLUE:  rb = nv; break;
              case LB_CH_ALPHA: ra = nv; break;
              default:          break;
            }
        }
      else
        {
          /* 目标合成、源单通道：用同一个标量去混每个通道（等同 PS 把某个通道
           * 压进合成）
           * Composite target with a single-channel source: the same scalar is
           * blended into every channel, like PS pressing one channel onto the
           * composite. */
          const gfloat sv = lb_channel (sr, sg, sb, sa, sch);
          gfloat bv[3];
          bv[0] = lb_blend_separable (blend, ir, sv);
          bv[1] = lb_blend_separable (blend, ig, sv);
          bv[2] = lb_blend_separable (blend, ib, sv);

          rr = lb_mix (ir, lb_clamp01 (bv[0]), mask, opacity);
          rg = lb_mix (ig, lb_clamp01 (bv[1]), mask, opacity);
          rb = lb_mix (ib, lb_clamp01 (bv[2]), mask, opacity);
        }

      if (omode == LB_OUT_COMPOSITE)
        {
          out[n * 4 + 0] = lb_clamp01 (rr);
          out[n * 4 + 1] = lb_clamp01 (rg);
          out[n * 4 + 2] = lb_clamp01 (rb);
          out[n * 4 + 3] = lb_clamp01 (ra);
        }
      else
        {
          /* 蒙版输出：结果取混合后的亮度，灰版给图层蒙版用，alpha 版直接当
           * 不透明度
           * Mask output: the blended luma, either as grey (for a layer mask)
           * or as alpha (for direct transparency). */
          gfloat grey = lb_luma (rr, rg, rb);
          out[n * 4 + 0] = grey;
          out[n * 4 + 1] = grey;
          out[n * 4 + 2] = grey;
          out[n * 4 + 3] = (omode == LB_OUT_MASK_ALPHA) ? grey : 1.0f;
        }
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

  GEGL_OPERATION_COMPOSER_CLASS (klass)->aux_label = _("Source");
  GEGL_OPERATION_COMPOSER_CLASS (klass)->aux_description = _("Image blended onto the input (defaults to the input itself)");

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:apply-image",
    "title",           _("Apply Image"),
    "description",     _("PS Apply Image: blend a second image over this one with "
                         "26 blend modes, per-channel targets, mask and opacity."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Apply Image"),
    NULL);
}

#endif
