/* ===========================================================================
 * SuperMrWang · 共用混合内核 / shared blend kernel
 * ---------------------------------------------------------------------------
 * purpose    应用图像与计算两个算子共用的通道取值 + 混合模式实现
 *            Channel extraction and blend-mode maths shared by
 *            lb:apply-image and lb:calculations.
 * note       所有函数 static inline，随每个算子各自编译一份，不做成独立库
 *            Everything is static inline and compiled into each op, so no
 *            separate shared library is needed.
 * reference  Photoshop 混合模式 / W3C compositing spec（可分离部分）
 *            Photoshop blend modes / W3C compositing spec (separable part)
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#ifndef LB_BLEND_H
#define LB_BLEND_H

#include <math.h>
#include <glib.h>

/* ---- 混合模式编号 / blend mode ids -------------------------------------- */
/* 顺序即菜单顺序：可分离模式在前，色相类不可分离模式在后
 * The order is the menu order: separable modes first, hue-based ones last. */

#define LB_BLEND_NORMAL        0
#define LB_BLEND_DARKEN        1
#define LB_BLEND_MULTIPLY      2
#define LB_BLEND_COLOR_BURN    3
#define LB_BLEND_LINEAR_BURN   4
#define LB_BLEND_LIGHTEN       5
#define LB_BLEND_SCREEN        6
#define LB_BLEND_COLOR_DODGE   7
#define LB_BLEND_LINEAR_DODGE  8
#define LB_BLEND_OVERLAY       9
#define LB_BLEND_SOFT_LIGHT   10
#define LB_BLEND_HARD_LIGHT   11
#define LB_BLEND_VIVID_LIGHT  12
#define LB_BLEND_LINEAR_LIGHT 13
#define LB_BLEND_PIN_LIGHT    14
#define LB_BLEND_HARD_MIX     15
#define LB_BLEND_DIFFERENCE   16
#define LB_BLEND_EXCLUSION    17
#define LB_BLEND_SUBTRACT     18
#define LB_BLEND_DIVIDE       19
#define LB_BLEND_DARKER_COLOR 20
#define LB_BLEND_LIGHTER_COLOR 21
#define LB_BLEND_HUE          22
#define LB_BLEND_SATURATION   23
#define LB_BLEND_COLOR        24
#define LB_BLEND_LUMINOSITY   25

/* ---- 通道选择 / channel selection -------------------------------------- */

#define LB_CH_COMPOSITE 0
#define LB_CH_RED       1
#define LB_CH_GREEN     2
#define LB_CH_BLUE      3
#define LB_CH_LUMA      4
#define LB_CH_ALPHA     5

/* ---- 输出形式 / output mode -------------------------------------------- */

#define LB_OUT_COMPOSITE 0
#define LB_OUT_MASK_GRAY 1
#define LB_OUT_MASK_ALPHA 2

static inline gfloat
lb_clamp01 (gfloat v)
{
  return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v);
}

/* 亮度系数与 GIMP 的亮度口径一致
 * Luma weights, same as GIMP's luminance */
static inline gfloat
lb_luma (gfloat r, gfloat g, gfloat b)
{
  return 0.2126f * r + 0.7152f * g + 0.0722f * b;
}

/* 取某个通道的值；composite 返回亮度，便于和标量混合模式统一处理
 * Value of one channel; 'composite' returns luma so that scalar blend modes
 * always get a single number. */
static inline gfloat
lb_channel (gfloat r, gfloat g, gfloat b, gfloat a, gint ch)
{
  switch (ch)
    {
      case LB_CH_RED:   return r;
      case LB_CH_GREEN: return g;
      case LB_CH_BLUE:  return b;
      case LB_CH_ALPHA: return a;
      case LB_CH_LUMA:  return lb_luma (r, g, b);
      default:          return lb_luma (r, g, b);
    }
}

/* ---- 可分离混合模式 / separable blend modes ----------------------------- */

static inline gfloat
lb_blend_color_burn (gfloat a, gfloat b)
{
  if (b <= 0.0f) return 0.0f;
  return lb_clamp01 (1.0f - (1.0f - a) / b);
}

static inline gfloat
lb_blend_color_dodge (gfloat a, gfloat b)
{
  if (b >= 1.0f) return 1.0f;
  return lb_clamp01 (a / (1.0f - b));
}

static inline gfloat
lb_blend_soft_light (gfloat a, gfloat b)
{
  if (b <= 0.5f)
    return a - (1.0f - 2.0f * b) * a * (1.0f - a);

  /* b > 0.5：用 W3C 的分段函数，接近 PS 但不会在暗部压死
   * b > 0.5: W3C's piecewise curve, close to PS without crushing shadows */
  gfloat d = (a <= 0.25f) ? ((16.0f * a - 12.0f) * a + 4.0f) * a : sqrtf (a);
  return a + (2.0f * b - 1.0f) * (d - a);
}

static inline gfloat
lb_blend_separable (gint mode, gfloat a, gfloat b)
{
  switch (mode)
    {
      case LB_BLEND_NORMAL:       return b;
      case LB_BLEND_DARKEN:       return MIN (a, b);
      case LB_BLEND_MULTIPLY:     return a * b;
      case LB_BLEND_COLOR_BURN:   return lb_blend_color_burn (a, b);
      case LB_BLEND_LINEAR_BURN:  return lb_clamp01 (a + b - 1.0f);
      case LB_BLEND_LIGHTEN:      return MAX (a, b);
      case LB_BLEND_SCREEN:       return 1.0f - (1.0f - a) * (1.0f - b);
      case LB_BLEND_COLOR_DODGE:  return lb_blend_color_dodge (a, b);
      case LB_BLEND_LINEAR_DODGE: return lb_clamp01 (a + b);
      case LB_BLEND_OVERLAY:      return (a <= 0.5f) ? 2.0f * a * b
                                                     : 1.0f - 2.0f * (1.0f - a) * (1.0f - b);
      case LB_BLEND_SOFT_LIGHT:   return lb_blend_soft_light (a, b);
      case LB_BLEND_HARD_LIGHT:   return (b <= 0.5f) ? 2.0f * a * b
                                                     : 1.0f - 2.0f * (1.0f - a) * (1.0f - b);
      case LB_BLEND_VIVID_LIGHT:  return (b <= 0.5f)
                                        ? lb_blend_color_burn (a, 2.0f * b)
                                        : lb_blend_color_dodge (a, 2.0f * b - 1.0f);
      case LB_BLEND_LINEAR_LIGHT: return lb_clamp01 (a + 2.0f * b - 1.0f);
      case LB_BLEND_PIN_LIGHT:    return (b <= 0.5f) ? MIN (a, 2.0f * b)
                                                     : MAX (a, 2.0f * b - 1.0f);
      case LB_BLEND_HARD_MIX:     return (a + b >= 1.0f) ? 1.0f : 0.0f;
      case LB_BLEND_DIFFERENCE:   return fabsf (a - b);
      case LB_BLEND_EXCLUSION:    return a + b - 2.0f * a * b;
      case LB_BLEND_SUBTRACT:     return lb_clamp01 (a - b);
      case LB_BLEND_DIVIDE:       return (b <= 0.0f) ? 1.0f : lb_clamp01 (a / b);

      /* 单通道上下文里「深色/浅色」退化为深/浅
       * In a single-channel context Darker/Lighter Color degrade to Darken
       * and Lighten. */
      case LB_BLEND_DARKER_COLOR:  return MIN (a, b);
      case LB_BLEND_LIGHTER_COLOR: return MAX (a, b);
      default:                    return b;
    }
}

/* ---- 色相类模式 / non-separable (HSB based) ---------------------------- */

typedef struct { gfloat h, s, v; } LbHsv;

static inline LbHsv
lb_rgb_to_hsv (gfloat r, gfloat g, gfloat b)
{
  LbHsv out = { 0.0f, 0.0f, 0.0f };
  gfloat max = MAX (r, MAX (g, b));
  gfloat min = MIN (r, MIN (g, b));
  gfloat d   = max - min;

  out.v = max;
  out.s = (max <= 0.0f) ? 0.0f : d / max;

  if (d <= 0.0f)
    return out;

  if (max == r)
    out.h = fmodf ((g - b) / d, 6.0f);
  else if (max == g)
    out.h = (b - r) / d + 2.0f;
  else
    out.h = (r - g) / d + 4.0f;

  out.h *= 60.0f;
  if (out.h < 0.0f) out.h += 360.0f;
  return out;
}

static inline void
lb_hsv_to_rgb (gfloat h, gfloat s, gfloat v, gfloat *r, gfloat *g, gfloat *b)
{
  gfloat c = v * s;
  gfloat x = c * (1.0f - fabsf (fmodf (h / 60.0f, 2.0f) - 1.0f));
  gfloat m = v - c;
  gfloat rr, gg, bb;

  if      (h <  60.0f) { rr = c; gg = x; bb = 0; }
  else if (h < 120.0f) { rr = x; gg = c; bb = 0; }
  else if (h < 180.0f) { rr = 0; gg = c; bb = x; }
  else if (h < 240.0f) { rr = 0; gg = x; bb = c; }
  else if (h < 300.0f) { rr = x; gg = 0; bb = c; }
  else                 { rr = c; gg = 0; bb = x; }

  *r = lb_clamp01 (rr + m);
  *g = lb_clamp01 (gg + m);
  *b = lb_clamp01 (bb + m);
}

/* 不可分离模式：a = 底（目标），b = 源
 * Non-separable modes: a = backdrop (target), b = source */
static inline void
lb_blend_hue_family (gint mode,
                     gfloat ar, gfloat ag, gfloat ab,
                     gfloat br, gfloat bg, gfloat bb,
                     gfloat *or_, gfloat *og, gfloat *ob)
{
  LbHsv A = lb_rgb_to_hsv (ar, ag, ab);
  LbHsv B = lb_rgb_to_hsv (br, bg, bb);

  switch (mode)
    {
      case LB_BLEND_HUE:
        lb_hsv_to_rgb (B.h, A.s, A.v, or_, og, ob);
        break;
      case LB_BLEND_SATURATION:
        lb_hsv_to_rgb (A.h, B.s, A.v, or_, og, ob);
        break;
      case LB_BLEND_COLOR:
        lb_hsv_to_rgb (B.h, B.s, A.v, or_, og, ob);
        break;
      case LB_BLEND_LUMINOSITY:
        lb_hsv_to_rgb (A.h, A.s, B.v, or_, og, ob);
        break;
      default:
        *or_ = br; *og = bg; *ob = bb;
        break;
    }
}

/* ---- 统一入口 / single entry point ------------------------------------ */
/* 一次算完一个像素的三个通道，省得调用方判断可分离与否
 * Blend one pixel in one call, so the caller need not care whether the mode
 * is separable. */
static inline void
lb_blend_rgb (gint mode,
              gfloat ar, gfloat ag, gfloat ab,
              gfloat br, gfloat bg, gfloat bb,
              gfloat *or_, gfloat *og, gfloat *ob)
{
  /* 深色/浅色比较的是整像素亮度，取其中一方全部通道，不能逐通道取
   * Darker/Lighter Color compare whole-pixel luminance and keep one side
   * entirely, so they must not be applied per channel. */
  if (mode == LB_BLEND_DARKER_COLOR || mode == LB_BLEND_LIGHTER_COLOR)
    {
      const gboolean take_b =
        (mode == LB_BLEND_DARKER_COLOR)
          ? (lb_luma (br, bg, bb) < lb_luma (ar, ag, ab))
          : (lb_luma (br, bg, bb) > lb_luma (ar, ag, ab));

      *or_ = take_b ? br : ar;
      *og  = take_b ? bg : ag;
      *ob  = take_b ? bb : ab;
      return;
    }

  if (mode >= LB_BLEND_HUE)
    {
      lb_blend_hue_family (mode, ar, ag, ab, br, bg, bb, or_, og, ob);
      return;
    }

  *or_ = lb_clamp01 (lb_blend_separable (mode, ar, br));
  *og  = lb_clamp01 (lb_blend_separable (mode, ag, bg));
  *ob  = lb_clamp01 (lb_blend_separable (mode, ab, bb));
}

/* 遮罩 + 不透明度：先把合成结果按 mask*opacity 混回目标
 * Mask and opacity: mix the blended result back into the target. */
static inline gfloat
lb_mix (gfloat target, gfloat blended, gfloat mask, gfloat opacity)
{
  gfloat k = lb_clamp01 (mask * opacity);
  return target + (blended - target) * k;
}

#endif /* LB_BLEND_H */
