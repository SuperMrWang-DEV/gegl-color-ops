/* ===========================================================================
 * SuperMrWang · PS 应用图像/计算的 ctypes 像素内核
 * ---------------------------------------------------------------------------
 * purpose    plugin/ps-blend/ 的 Python 插件调用本内核做逐像素混合。公式与
 *            common/blend.h 完全同源（include 同一个文件），GEGL 算子和
 *            Python 插件不会各算各的。
 *            Pixel kernel for the ps-blend Python plug-in, driven through
 *            ctypes. The maths includes common/blend.h directly, so the GEGL
 *            ops and the plug-in share one implementation.
 * channel    本内核使用插件侧的通道编号：0 Gray(亮度)、1 R、2 G、3 B、4 A；
 *            混合模式编号是 plugin/ps-blend/psblend.py BLENDS 列表的顺序
 *            （Photoshop 对话框顺序），这里映射回 blend.h 的 LB_BLEND_*。
 * build      由 build.sh 编到 plugin/ps-blend/psblend_core.dll（找不到编译器
 *            或失败时插件自动退化为纯 Python，结果一致只是慢）。
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#ifdef _WIN32
#define PSEXPORT __declspec(dllexport)
#else
#define PSEXPORT __attribute__((visibility("default")))
#endif

#include <glib.h>
#include "blend.h"

/* psblend.py 的模式顺序 -> blend.h 的编号（两个枚举顺序刻意不同：
 * Python 侧照 Photoshop 对话框排，blend.h 照可分离/不可分离排） */
static const gint ps_blend_map[26] = {
  LB_BLEND_NORMAL, LB_BLEND_DARKEN, LB_BLEND_MULTIPLY,
  LB_BLEND_COLOR_BURN, LB_BLEND_LINEAR_BURN, LB_BLEND_DARKER_COLOR,
  LB_BLEND_LIGHTEN, LB_BLEND_SCREEN, LB_BLEND_COLOR_DODGE,
  LB_BLEND_LINEAR_DODGE, LB_BLEND_LIGHTER_COLOR, LB_BLEND_OVERLAY,
  LB_BLEND_SOFT_LIGHT, LB_BLEND_HARD_LIGHT, LB_BLEND_VIVID_LIGHT,
  LB_BLEND_LINEAR_LIGHT, LB_BLEND_PIN_LIGHT, LB_BLEND_HARD_MIX,
  LB_BLEND_DIFFERENCE, LB_BLEND_EXCLUSION, LB_BLEND_SUBTRACT,
  LB_BLEND_DIVIDE, LB_BLEND_HUE, LB_BLEND_SATURATION,
  LB_BLEND_COLOR, LB_BLEND_LUMINOSITY
};

/* 插件通道编号 -> 数值。0 = Gray 取亮度，与 PS 的 Gray 通道一致 */
static inline gfloat
ps_ch (gint ch, gfloat r, gfloat g, gfloat b, gfloat a)
{
  switch (ch)
    {
      case 1: return r;
      case 2: return g;
      case 3: return b;
      case 4: return a;
      default: return lb_luma (r, g, b);
    }
}

/* 单通道混合：深/浅色退化为深/浅，色相类对单通道取不到语义，按 normal 处理
 * Single-channel blend: Darker/Lighter degrade to Darken/Lighten and the
 * hue-family modes fall back to Normal. */
static inline gfloat
ps_scalar (gint mode, gfloat a, gfloat b)
{
  if (mode == LB_BLEND_HUE || mode == LB_BLEND_SATURATION ||
      mode == LB_BLEND_COLOR || mode == LB_BLEND_LUMINOSITY)
    return b;
  return lb_blend_separable (mode, a, b);
}

/* ---- 应用图像 / Apply Image ---------------------------------------------- */
PSEXPORT void
psblend_apply (const float *in, const float *aux, const float *mask,
               float *out, long n, int blend, int tch, int sch,
               float opacity, int use_mask, int inv_mask,
               int keep_transp, int grey_out)
{
  const gint mode = ps_blend_map[blend];

  for (long i = 0; i < n; i++)
    {
      const long j = i * 4;
      const gfloat ir = in[j], ig = in[j + 1], ib = in[j + 2], ia = in[j + 3];
      const gfloat sr = aux[j], sg = aux[j + 1], sb = aux[j + 2], sa = aux[j + 3];
      gfloat orr = ir, org = ig, ob = ib, oa = ia;
      gfloat k;

      if (keep_transp && ia <= 0.0f)
        {
          out[j] = ir; out[j + 1] = ig; out[j + 2] = ib; out[j + 3] = ia;
          continue;
        }

      /* 遮罩：mask 缓冲缺省时退回 aux 的 Gray（与插件侧约定一致）
       * Mask: fall back to the aux buffer's Gray when none is given */
      if (use_mask)
        {
          gfloat v = (mask != NULL)
            ? ps_ch (0, mask[j], mask[j + 1], mask[j + 2], mask[j + 3])
            : ps_ch (0, sr, sg, sb, sa);
          k = lb_clamp01 (opacity * ((inv_mask) ? 1.0f - v : v));
        }
      else
        k = opacity;

      if (tch == 0)
        {
          /* 目标合成：色相类与深/浅色整像素处理；可分离模式里 Gray 源取
           * 亮度作标量压进每个通道（PS 的行为）
           * Composite target: hue-family and Darker/Lighter Color are
           * whole-pixel; a separable Gray source presses luminance into
           * every channel, like Photoshop. */
          if (mode >= LB_BLEND_HUE || mode == LB_BLEND_DARKER_COLOR ||
              mode == LB_BLEND_LIGHTER_COLOR)
            {
              gfloat br, bg, bb;
              lb_blend_rgb (mode, ir, ig, ib, sr, sg, sb, &br, &bg, &bb);
              orr = ir + (br - ir) * k;
              org = ig + (bg - ig) * k;
              ob  = ib + (bb - ib) * k;
            }
          else
            {
              const gfloat s = (sch == 0) ? lb_luma (sr, sg, sb)
                                          : ps_ch (sch, sr, sg, sb, sa);
              orr = ir + (lb_clamp01 (ps_scalar (mode, ir, s)) - ir) * k;
              org = ig + (lb_clamp01 (ps_scalar (mode, ig, s)) - ig) * k;
              ob  = ib + (lb_clamp01 (ps_scalar (mode, ib, s)) - ib) * k;
            }
        }
      else
        {
          /* 目标单通道：只改那一个通道
           * Single-channel target: only that channel changes */
          const gfloat tv = ps_ch (tch, ir, ig, ib, ia);
          const gfloat sv = (sch == 0) ? lb_luma (sr, sg, sb)
                                       : ps_ch (sch, sr, sg, sb, sa);
          const gfloat nv = tv + (lb_clamp01 (ps_scalar (mode, tv, sv)) - tv) * k;

          switch (tch)
            {
              case 1: orr = nv; break;
              case 2: org = nv; break;
              case 3: ob  = nv; break;
              case 4: oa  = nv; break;
              default: break;
            }
        }

      if (grey_out)
        {
          const gfloat g = lb_luma (orr, org, ob);
          out[j] = g; out[j + 1] = g; out[j + 2] = g; out[j + 3] = 1.0f;
        }
      else
        {
          out[j]     = lb_clamp01 (orr);
          out[j + 1] = lb_clamp01 (org);
          out[j + 2] = lb_clamp01 (ob);
          out[j + 3] = lb_clamp01 (oa);
        }
    }
}

/* ---- 计算 / Calculations -------------------------------------------------- */
PSEXPORT void
psblend_calc (const float *in, const float *aux, const float *mask,
              float *out, long n, int ch1, int inv1, int ch2, int inv2,
              int blend, float opacity, int use_mask, int inv_mask)
{
  const gint mode = ps_blend_map[blend];

  for (long i = 0; i < n; i++)
    {
      const long j = i * 4;
      gfloat v1 = ps_ch (ch1, in[j], in[j + 1], in[j + 2], in[j + 3]);
      gfloat v2 = ps_ch (ch2, aux[j], aux[j + 1], aux[j + 2], aux[j + 3]);
      gfloat blended, grey, k;

      if (inv1) v1 = 1.0f - v1;
      if (inv2) v2 = 1.0f - v2;

      if (use_mask)
        {
          gfloat v = (mask != NULL)
            ? ps_ch (0, mask[j], mask[j + 1], mask[j + 2], mask[j + 3])
            : ps_ch (0, aux[j], aux[j + 1], aux[j + 2], aux[j + 3]);
          k = lb_clamp01 (opacity * ((inv_mask) ? 1.0f - v : v));
        }
      else
        k = opacity;

      /* 计算输出是标量。整像素语义（深/浅色、色相类）把两个标量当作灰度
       * RGB 走 lb_blend_rgb，再取三通道均值，与 Python 侧一致
       * The result is a scalar. Whole-pixel semantics (Darker/Lighter Color,
       * hue family) run the scalars through lb_blend_rgb as grey RGB and take
       * the channel average, matching the Python side. */
      if (mode >= LB_BLEND_HUE || mode == LB_BLEND_DARKER_COLOR ||
          mode == LB_BLEND_LIGHTER_COLOR)
        {
          gfloat br, bg, bb;
          lb_blend_rgb (mode, v1, v1, v1, v2, v2, v2, &br, &bg, &bb);
          blended = (br + bg + bb) / 3.0f;
        }
      else
        blended = lb_clamp01 (ps_scalar (mode, v1, v2));
      grey    = v1 + (blended - v1) * k;

      out[j] = grey; out[j + 1] = grey; out[j + 2] = grey; out[j + 3] = 1.0f;
    }
}
