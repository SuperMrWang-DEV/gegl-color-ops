/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:apply-image
 * menu       Apply Image
 * purpose    经典图像编辑器 应用图像：把 aux 输入当成源，按混合模式、不透明度与遮罩压到
 *            主输入上，可选只作用于某一个通道
 *            Apply Image: blend the aux input over the main input with a
 *            blend mode, opacity and mask, optionally per channel.
 * algorithm  两路 RGBA 逐像素混合：先取目标/源通道（RGB、亮度、alpha 或合成），
 *            按混合模式算出结果，再用 mask × opacity 混回原值。源层可能比
 *            主图层小或带偏移，用 aux 缓冲区的 extent 判断哪些像素真的有源，
 *            没盖到的像素原样输出；源层范围内的透明像素也不参与（alpha 当
 *            覆盖率），这样只有「源层真有像素」的地方才被改动。
 *            Two RGBA streams are blended per pixel: pick the target and
 *            source channels (RGB, luma, alpha or composite), run the blend
 *            mode, then mix the result back by mask x opacity. The source may
 *            be smaller than the target or offset; the aux buffer's extent is
 *            used to tell which area belongs to the source, while the source
 *            alpha (as coverage) tells which pixels actually have pixels.
 *            Only where the source is present and not transparent does the
 *            target change.
 * type       GeglOperationComposer（input + aux 双输入 / two inputs）
 * reference  经典图像编辑器「图像 → 应用图像」/ Image > Apply Image
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

/* 缩放/补偿值只对 加法（Linear Dodge）和 减法 生效，其余模式忽略，
 * 对位经典图像编辑器 应用图像/计算对话框：结果 = (A ± B) / 缩放 + 补偿值。
 * 补偿值用 8bit 口径 ±255，内部归一化。/ Scale and offset only affect
 * Linear Dodge (Add) and Subtract (the classic editor shows them only for
 * these two): result = (A ± B) / scale + offset; offset in 8-bit units. */
property_double (scale, _("Scale"), 1.0)
    description (_("Add/Subtract only: result = (A ± B) / scale + offset"))
    value_range (1.0, 2.0)

property_double (offset, _("Offset"), 0.0)
    description (_("Add/Subtract only: value added after scaling, -255..255"))
    value_range (-255.0, 255.0)

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

#define GEGL_OP_COMPOSER
#define GEGL_OP_NAME     lb_apply_image
#define GEGL_OP_C_SOURCE apply-image.c
#include "gegl-op.h"

/* ---- 格式 / formats ---------------------------------------------------- */

/* 感知（非线性）格式：混合模式按 8bit sRGB 伽马域定义，线性光下中间调会偏
 * Perceptual (non-linear) format: the classic editor blend modes are defined in the
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

/* ---- 参数快照 / parameter snapshot -------------------------------------- */

typedef struct
{
  gint     blend, tch, sch, mch, mfrom, omode;
  gfloat   opacity, scale, offset;
  gboolean use_mask, inv_mask, keep_transp;
} AiParams;

/* ---- 单像素混合 / one pixel --------------------------------------------- */

static inline void
apply_pixel (const AiParams *p,
             const gfloat   *in,
             const gfloat   *src,
             gfloat         *out)
{
  const gfloat ir = in[0];
  const gfloat ig = in[1];
  const gfloat ib = in[2];
  const gfloat ia = in[3];

  const gfloat sr = src[0];
  const gfloat sg = src[1];
  const gfloat sb = src[2];
  const gfloat sa = src[3];

  gfloat rr = ir, rg = ig, rb = ib, ra = ia;

  /* 全透明像素：按 经典图像编辑器的「保留透明区域」直接跳过
   * Fully transparent pixels are skipped when preservation is on */
  if (p->keep_transp && ia <= 0.0f)
    {
      out[0] = ir;
      out[1] = ig;
      out[2] = ib;
      out[3] = ia;
      return;
    }

  /* 源层的透明像素不参与作用：源层的缓冲区范围（extent）只说明「这块地方
   * 属于源层」，不说明「这块地方有像素」。源层是抠图、文字层或带透明背景
   * 的图层时，透明区的 RGB 是 0，照常走 multiply 会把目标乘成黑色——用户
   * 看到的「相交区域也变了」就是这个。alpha 兼作覆盖率，抠图边缘还能平滑
   * 过渡，不会出现硬边。
   * Transparent source pixels must not take part. The aux extent only says
   * the area belongs to the source layer, not that it holds pixels: on a
   * cut-out or text layer the transparent areas are RGB 0, and letting them
   * run through multiply blackens the target. The alpha doubles as coverage,
   * so soft matte edges fade instead of showing a hard seam. */
  if (sa <= 0.0f)
    {
      out[0] = ir;
      out[1] = ig;
      out[2] = ib;
      out[3] = ia;
      return;
    }

  /* 源通道本身就是 alpha 时，这个 alpha 是数据而不是覆盖率，不能再乘一次，
   * 否则等于 alpha 平方
   * When the source channel is alpha itself, that value is the data, not the
   * coverage; multiplying again would square it. */
  const gfloat cov = (p->sch == LB_CH_ALPHA) ? 1.0f : sa;

  /* 遮罩可取自源层或本层，两者都已在手边，不必再开第三个 pad
   * The mask is read from either connected layer, so no third pad is
   * needed to cover both halves of the classic editor's mask options. */
  gfloat mask = cov;
  if (p->use_mask)
    {
      mask = (p->mfrom == AI_MASK_INPUT)
               ? lb_channel (ir, ig, ib, ia, p->mch)
               : lb_channel (sr, sg, sb, sa, p->mch);
      if (p->inv_mask)
        mask = 1.0f - mask;
      mask *= cov;
    }

  if (p->tch == LB_CH_COMPOSITE && p->sch == LB_CH_COMPOSITE)
    {
      /* 合成 × 合成：三通道各自混合，色相类模式走整体算法
       * Composite x composite: blend all three channels, hue-family
       * modes go through the whole-pixel path. */
      gfloat br, bg, bb;
      lb_blend_rgb (p->blend, ir, ig, ib, sr, sg, sb, &br, &bg, &bb,
                    p->scale, p->offset);
      rr = lb_mix (ir, br, mask, p->opacity);
      rg = lb_mix (ig, bg, mask, p->opacity);
      rb = lb_mix (ib, bb, mask, p->opacity);
    }
  else if (p->tch != LB_CH_COMPOSITE)
    {
      /* 目标是单通道：源取标量（单通道取值，合成都取亮度）
       * Single target channel: source becomes a scalar (its own channel,
       * or luma when the source is the composite). */
      const gfloat tv = lb_channel (ir, ig, ib, ia, p->tch);
      const gfloat sv = (p->sch == LB_CH_COMPOSITE)
                          ? lb_luma (sr, sg, sb)
                          : lb_channel (sr, sg, sb, sa, p->sch);
      const gfloat nv = lb_mix (tv, lb_blend_separable (p->blend, tv, sv,
                                                        p->scale, p->offset),
                                mask, p->opacity);

      switch (p->tch)
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
      /* 目标合成、源单通道：用同一个标量去混每个通道（等同 经典图像编辑器 把某个通道
       * 压进合成）
       * Composite target with a single-channel source: the same scalar is
       * blended into every channel, like the classic editor pressing one channel onto the
       * composite. */
      const gfloat sv = lb_channel (sr, sg, sb, sa, p->sch);
      gfloat bv[3];
      bv[0] = lb_blend_separable (p->blend, ir, sv, p->scale, p->offset);
      bv[1] = lb_blend_separable (p->blend, ig, sv, p->scale, p->offset);
      bv[2] = lb_blend_separable (p->blend, ib, sv, p->scale, p->offset);

      rr = lb_mix (ir, lb_clamp01 (bv[0]), mask, p->opacity);
      rg = lb_mix (ig, lb_clamp01 (bv[1]), mask, p->opacity);
      rb = lb_mix (ib, lb_clamp01 (bv[2]), mask, p->opacity);
    }

  if (p->omode == LB_OUT_COMPOSITE)
    {
      out[0] = lb_clamp01 (rr);
      out[1] = lb_clamp01 (rg);
      out[2] = lb_clamp01 (rb);
      out[3] = lb_clamp01 (ra);
    }
  else
    {
      /* 蒙版输出：结果取混合后的亮度，灰版给图层蒙版用，alpha 版直接当
       * 不透明度
       * Mask output: the blended luma, either as grey (for a layer mask)
       * or as alpha (for direct transparency). */
      gfloat grey = lb_luma (rr, rg, rb);
      out[0] = grey;
      out[1] = grey;
      out[2] = grey;
      out[3] = (p->omode == LB_OUT_MASK_ALPHA) ? grey : 1.0f;
    }
}

/* ---- 主处理 / main processing ------------------------------------------ */

/* 按行块处理：整幅一次性取进内存在大图上会吃掉几百 MB，GEGL 也是按块
 * 调 process 的。块高 32 行足够摊平 gegl_buffer_get 的调用开销。
 * Process in bands of rows: pulling a whole image into memory costs hundreds
 * of MB on large files, and GEGL calls process on tiles anyway. */
#define AI_BAND 32

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *input,
         GeglBuffer          *aux,
         GeglBuffer          *output,
         const GeglRectangle *result,
         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (op);
  const Babl     *fmt = perceptual_format (op);

  AiParams p;
  p.blend      = (gint) o->blend_mode;
  p.tch        = (gint) o->target_channel;
  p.sch        = (gint) o->source_channel;
  p.mch        = (gint) o->mask_channel;
  p.mfrom      = (gint) o->mask_from;
  p.omode      = (gint) o->output_mode;
  p.opacity    = (gfloat) (o->opacity / 100.0);
  p.scale      = (gfloat) o->scale;
  p.offset     = (gfloat) (o->offset / 255.0);
  p.use_mask   = o->mask_enabled;
  p.inv_mask   = o->invert_mask;
  p.keep_transp = o->preserve_transparency;

  /* aux 没接时退化成「源 = 本图」，至少能当通道内的混合用
   * With no aux connected the source falls back to the input itself, so the
   * op still works as a within-image channel blend. */
  const gboolean has_aux = (aux != NULL);
  const GeglRectangle aext = has_aux ? *gegl_buffer_get_extent (aux)
                                     : *gegl_buffer_get_extent (input);

  const gint w  = result->width;
  const gint bh = MIN (AI_BAND, result->height);

  gfloat *in_band  = g_new (gfloat, (gsize) w * bh * 4);
  gfloat *aux_band = g_new (gfloat, (gsize) w * bh * 4);
  gfloat *out_band = g_new (gfloat, (gsize) w * bh * 4);

  /* 行距按整行宽算，不能用 GEGL_AUTO_ROWSTRIDE：它取的是 rect 的宽度，
   * 而 aux 只覆盖块里的一小段时，取回来的行宽比 w 窄，后续按 w 索引会串行。
   * The row stride has to follow the full band width. GEGL_AUTO_ROWSTRIDE
   * uses the rect's own width instead, so a partial aux rect would come back
   * packed narrower than w and every row after the first would be misread. */
  const gint band_stride = (gint) (sizeof (gfloat) * 4 * (gsize) w);

  for (gint y0 = 0; y0 < result->height; y0 += AI_BAND)
    {
      const gint nh = MIN (AI_BAND, result->height - y0);
      const GeglRectangle band = { result->x, result->y + y0, w, nh };

      memset (in_band, 0, sizeof (gfloat) * (gsize) w * nh * 4);
      gegl_buffer_get (input, &band, 1.0, fmt, in_band,
                       band_stride, GEGL_ABYSS_NONE);

      /* 源覆盖区之外显式清零：aux_band 只在源矩形里被写入，剩下的是上一块
       * 的残留，万一覆盖判断有漏，垃圾数据会直接混进结果。清成 0 等于全透明，
       * 正好被 apply_pixel 的 alpha 判断挡住。
       * Zero the part the source does not cover: aux_band is only filled
       * inside the source rect, and stale bytes from the previous band would
       * otherwise slip into the blend if the coverage test ever missed.
       * Zero means transparent, which the alpha test rejects. */
      memset (aux_band, 0, sizeof (gfloat) * (gsize) w * nh * 4);

      /* 本块内「属于源层」的列/行区间（相对块左上角）。aux 的 extent 就是
       * 源图层自己的大小和位置：图层比主图小、或者带偏移时，没盖到的地方
       * 不能被当成「透明黑」参与混合——multiply 会把那里涂黑，normal 会
       * 把它擦成透明。这只做粗筛，源层内部透明的地方由 apply_pixel 里的
       * alpha 判断兜住。
       * Rows and columns of this band that belong to the source, relative to
       * the band's top-left. The aux extent is the source layer's own size
       * and position: where a smaller or offset layer does not reach, the
       * pixels must not join the blend as transparent black (multiply would
       * blacken them, normal would erase them). This is only the coarse
       * filter; transparent pixels inside the layer are handled by the alpha
       * test in apply_pixel. */
      gint cx0 = 0, cx1 = 0, cy0 = 0, cy1 = 0;

      if (!has_aux)
        {
          memcpy (aux_band, in_band, sizeof (gfloat) * (gsize) w * nh * 4);
          cx1 = w;
          cy1 = nh;
        }
      else
        {
          cx0 = MAX (band.x, aext.x) - band.x;
          cx1 = MIN (band.x + w, aext.x + aext.width) - band.x;
          cy0 = MAX (band.y, aext.y) - band.y;
          cy1 = MIN (band.y + nh, aext.y + aext.height) - band.y;

          if (cx1 <= cx0 || cy1 <= cy0)
            {
              cx1 = cx0 = 0;
              cy1 = cy0 = 0;
            }
          else
            {
              GeglRectangle ar = { band.x + cx0, band.y + cy0,
                                   cx1 - cx0, cy1 - cy0 };
              gegl_buffer_get (aux, &ar, 1.0, fmt,
                               aux_band + ((gsize) cy0 * w + cx0) * 4,
                               band_stride, GEGL_ABYSS_NONE);
            }
        }

      for (gint row = 0; row < nh; row++)
        {
          for (gint col = 0; col < w; col++)
            {
              const gsize n = ((gsize) row * w + col) * 4;

              if (row < cy0 || row >= cy1 || col < cx0 || col >= cx1)
                {
                  /* 源层没覆盖到这里：原样输出
                   * Not covered by the source: pass through */
                  out_band[n + 0] = in_band[n + 0];
                  out_band[n + 1] = in_band[n + 1];
                  out_band[n + 2] = in_band[n + 2];
                  out_band[n + 3] = in_band[n + 3];
                  continue;
                }

              apply_pixel (&p, in_band + n, aux_band + n, out_band + n);
            }
        }

      gegl_buffer_set (output, &band, level, fmt, out_band, band_stride);
    }

  g_free (in_band);
  g_free (aux_band);
  g_free (out_band);

  return TRUE;
}

/* ---- 类初始化 / class init --------------------------------------------- */

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass        *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationComposerClass *cclass =
    GEGL_OPERATION_COMPOSER_CLASS (klass);

  oclass->prepare = prepare;
  cclass->process = process;

  cclass->aux_label = _("Source");
  cclass->aux_description = _("Image blended onto the input (defaults to the input itself)");

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:apply-image",
    "title",           _("Apply Image"),
    "description",     _("Apply Image: blend a second image over this one with "
                         "26 blend modes, per-channel targets, mask and opacity. "
                         "Areas the source layer does not cover stay untouched."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Blend",
    "gimp:menu-label", _("Apply Image"),
    NULL);
}

#endif
