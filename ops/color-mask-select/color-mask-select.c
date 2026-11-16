/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:color-mask-select
 * menu       Mask by Color
 * purpose    PS 色彩范围：按指定色 + 容差 + 羽化生成蒙版，可红色叠加预览
 *            PS Color Range: build a mask from a picked colour, a fuzziness
 *            radius and feathering, with an optional red overlay preview.
 * algorithm  两条通路 / two paths:
 *
 *            1) 高光 / 阴影 / 中间调 —— 复刻 PS 实测行为（见下）。
 *               PS 在这三个模式里有两个独立滑杆：「范围」是阈值，
 *               「容差」把过渡带按比例推向亮度极端（纯黑 / 纯白）。
 *               阈值本身是硬边界，容差才是柔边的来源。
 *               Highlights / shadows / midtones follow the measured
 *               Photoshop model: "range" is a hard threshold, "fuzziness"
 *               widens the falloff band towards black or white.
 *
 *               亮度 = Rec.601 伽马域加权（0.299/0.587/0.114）。实测校准：
 *               阈值 100 时 50% 交界落在 luma 100.9，阈值 150 时落在 149.0，
 *               说明 PS 用的就是这套系数，不是 Lab L*。
 *               Luminance is Rec.601 in the gamma domain (matches PS to ~1
 *               code: limit 100 -> 50% at luma 100.9, limit 150 -> 149.0).
 *
 *               阴影   alpha = 1 - ramp((L - lim) / band), band = fz*(1-lim)
 *               高光   alpha = 1 - ramp((lim - L) / band), band = fz*lim
 *               中间调 alpha = (1 - ramp((low - L)/fz*low))
 *                            * (1 - ramp((L - high)/fz*(1-high)))
 *               其中 fz = fuzziness/200 ∈ [0,1]，band 走上限的「剩余量」，
 *               所以 fz=1 时过渡带正好铺到纯黑/纯白。ramp(t) = smoothstep(t^1.2)：
 *               实测 PS 的 50% 点落在带宽的 0.555 处，纯 smoothstep 是 0.5，
 *               这个 1.2 次幂把中段误差从 10 码压到 1.7 码。
 *               ramp(t) = smoothstep(t^1.2) because the measured 50% point
 *               sits at 0.555 of the band, not 0.5.
 *
 *            2) 色系预设 / 自定颜色 —— 统一模型：先把像素换算成「与目标的不
 *               匹配度」d ∈ [0,1]（0 = 精确匹配），色系按色环距离；自定色按
 *               CIELAB ΔE 感知距离归一化（d = ΔE/100 钳到 1，黑白≈100 为
 *               满刻度），并加 ΔE94 的明度权重 kL=2（明度差折半）——选色蒙版
 *               要的是「同一族颜色」，暗红和亮红不该被明度差拆开；babl 整行
 *               转换，目标色与像素走同一套源空间→Lab 通路；
 *               fuzziness 定容差窗 w = fz（fz=1 时窗宽到最大不匹配度），
 *               alpha = 1 - smoothstep(d, w*(1-feather), w)；
 *               色系预设再乘彩度门限：门控用彩度 s×v 而不是单看饱和度——
 *               近黑像素 v≈0 时 s 可以是 1，但色相纯属数值噪声，不该被选中。
 *               Colour presets and the picked colour keep the unified
 *               mismatch-window model. The picked colour is matched by
 *               perceptual CIELAB ΔE (d = ΔE/100, clamped) with ΔE94's
 *               lightness weight kL = 2 (ΔL halved) - a mask picks colour
 *               families, so dark red must not be split from bright red by
 *               lightness alone. babl converts a row at a time through the
 *               same source-space path as the pixels. Presets are gated by
 *               chroma (s×v), not saturation alone - near-black pixels can
 *               report s = 1 while their hue is pure numeric noise.
 *
 *            公共：可反相，可红色叠加预览 / invertible, optional red overlay.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  Photoshop「色彩范围」(Color Range)
 *            Photoshop Color Range
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_enum (mask_mode, _("Selection Mode"),
               MaskSelectType, mask_select_type_enum, MASK_RED)
    description (_("Color selection mode"))

enum_start (mask_select_type_enum)
  enum_value (MASK_RED,      "red",      N_("Red"))
  enum_value (MASK_GREEN,    "green",    N_("Green"))
  enum_value (MASK_BLUE,     "blue",     N_("Blue"))
  enum_value (MASK_CYAN,     "cyan",     N_("Cyan"))
  enum_value (MASK_MAGENTA,  "magenta",  N_("Magenta"))
  enum_value (MASK_YELLOW,   "yellow",   N_("Yellow"))
  enum_value (MASK_WHITE,    "white",    N_("Highlights"))
  enum_value (MASK_BLACK,    "black",    N_("Shadows"))
  enum_value (MASK_GRAY,     "gray",     N_("Midtones"))
  enum_value (MASK_CUSTOM,   "custom",   N_("Custom Picked Color"))
enum_end (MaskSelectType)

property_color (custom_color, _("Custom Color"), "rgba(1.0, 0.0, 0.0, 1.0)")
    description (_("Color picked from image"))

property_boolean (preview_red_mask, _("Red Overlay Preview"), FALSE)
    description (_("Blend the mask in as a red overlay. Turn on while adjusting "
                   "to preview, off to write the mask into the layer alpha. "
                   "Applying with this on bakes the red blend into the layer"))

property_double (fuzziness, _("Fuzziness"), 50.0)
    value_range (0.0, 200.0)
    ui_range (0.0, 200.0)
    description (_("Width of the soft falloff. In the tonal modes this is "
                   "Photoshop's Fuzziness: 0 gives a hard edge at the limit, "
                   "200 (100 in Photoshop) reaches pure black / pure white"))

/* 色调模式的「范围」滑杆，等价 PS 色彩范围里同名的两个框。
 * 「阴影上限」同时是中间调的下限，语义按 PS 分开给，避免互相牵连。
 * Tone-mode range sliders, one per Photoshop field. Kept separate so moving
 * one does not silently move another mode's threshold. */
property_int (shadows_limit, _("Shadows Upper Limit"), 64)
    value_range (0, 255)
    description (_("Luminance up to this value is fully selected in Shadows "
                   "mode (Photoshop's Shadows range)"))

property_int (highlights_limit, _("Highlights Lower Limit"), 192)
    value_range (0, 255)
    description (_("Luminance from this value up is fully selected in "
                   "Highlights mode (Photoshop's Highlights range)"))

property_int (midtone_low, _("Midtones Lower Limit"), 64)
    value_range (0, 255)
    description (_("Lower edge of the Midtones band"))

property_int (midtone_high, _("Midtones Upper Limit"), 192)
    value_range (0, 255)
    description (_("Upper edge of the Midtones band"))

property_double (feather, _("Feather"), 10.0)
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)

property_double (saturation_min, _("Min Saturation"), 0.0)
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)
    description (_("Pixels whose chroma (saturation times value) is below "
                   "this never match a colour preset (grays and near-blacks "
                   "have no usable hue). 0 uses a small fixed floor"))

property_boolean (invert, _("Invert"), FALSE)
    description (_("Invert the mask like Photoshop's Invert checkbox"))

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_color_mask_select
#define GEGL_OP_C_SOURCE color-mask-select.c

#include "gegl-op.h"

static inline void
rgb_to_hsv(gfloat r, gfloat g, gfloat b, gfloat *h, gfloat *s, gfloat *v)
{
  gfloat cmax = MAX(MAX(r, g), b);
  gfloat cmin = MIN(MIN(r, g), b);
  gfloat delta = cmax - cmin;

  *v = cmax;
  *s = (cmax > 0) ? delta / cmax : 0.0f;
  *h = 0.0f;

  if (delta > 0) {
    if (cmax == r)
      *h = (g - b) / delta;
    else if (cmax == g)
      *h = 2.0f + (b - r) / delta;
    else
      *h = 4.0f + (r - g) / delta;

    *h /= 6.0f;
    if (*h < 0) *h += 1.0f;
  }
}

/* 标准灰度亮度（伽马域加权，与 8bit 直觉一致）
 * Standard grey luminance, gamma-domain weighted */
static inline gfloat
luminance(gfloat r, gfloat g, gfloat b)
{
  return 0.299f * r + 0.587f * g + 0.114f * b;
}

static inline gfloat
smooth_step(gfloat val, gfloat a, gfloat b)
{
  /* 退化区间必须有守卫：以前 a==b 时 0/0 出 NaN，灰阶像素的 alpha 全变 0，
   * 白/黑/中间调三个模式整体报废。老 bug，2026-11-12 修复时加的守卫。
   * Degenerate ranges must be guarded: a==b used to produce NaN via 0/0,
   * which zeroed the alpha of every gray pixel. */
  if (b <= a)
    return (val <= a) ? 0.0f : 1.0f;
  if (val < a) return 0.0f;
  if (val > b) return 1.0f;
  gfloat t = (val - a) / (b - a);
  return t * t * (3.0f - 2.0f * t);
}

/* 色环距离：把 [0,1) 的色相差映射到 0（同色）…1（互补色）
 * Hue distance on the colour wheel: 0 for the same hue, 1 for complementary */
static inline gfloat
hue_dist(gfloat h, gfloat center)
{
  gfloat d = fabsf(h - center);
  if (d > 0.5f) d = 1.0f - d;
  return d * 2.0f;
}

/* PS 色调模式的响应曲线：先 t^1.2 再 smoothstep。
 * 实测（shadow 64/128/192 × 容差 25/50/75）50% 点落在带宽的 0.53–0.58，
 * 恒定在 ~0.555，纯 smoothstep 的 0.5 会让中段偏亮最多 10 码。
 * Photoshop's tonal response: smoothstep of t^1.2. The measured 50% point
 * sits at 0.555 of the band (smoothstep alone would put it at 0.5). */
static inline gfloat
ps_tone_ramp (gfloat t)
{
  if (t <= 0.0f) return 0.0f;
  if (t >= 1.0f) return 1.0f;
  t = powf (t, 1.2f);
  return t * t * (3.0f - 2.0f * t);
}

/* 亮度 → alpha 的查找表：色调模式只依赖亮度，参数在 process() 里是常量，
 * 逐像素调用 powf 没必要。1024 级线性插值，量化误差 < 0.13 码。
 * Luma -> alpha lookup table: the tonal modes depend on luminance only and
 * the parameters are constant per process() call, so powf per pixel is waste.
 * 1024 entries with linear interpolation, quantisation error < 0.13 code. */
#define TONE_LUT 1024

/* 亮度 → alpha 的唯一真源：查表和逐像素直算都走它。
 * Single source of truth for luma -> alpha; both the LUT and the direct
 * path call it. */
static gfloat
tone_alpha (gfloat         L,
            MaskSelectType mode,
            gfloat         low,
            gfloat         high,
            gfloat         fzv)
{
  switch (mode)
  {
    case MASK_BLACK:   /* 阴影：低于阈值全选，向上按剩余量铺开 */
    {
      gfloat band = fzv * (1.0f - low);
      return (band <= 1e-5f) ? ((L <= low + 1e-4f) ? 1.0f : 0.0f)
                             : 1.0f - ps_tone_ramp ((L - low) / band);
    }
    case MASK_WHITE:   /* 高光：高于阈值全选，向下按剩余量铺开 */
    {
      gfloat band = fzv * high;
      return (band <= 1e-5f) ? ((L >= high - 1e-4f) ? 1.0f : 0.0f)
                             : 1.0f - ps_tone_ramp ((high - L) / band);
    }
    default:           /* 中间调：两条边各自向外铺开，取交集 */
    {
      gfloat band_lo = fzv * low;
      gfloat band_hi = fzv * (1.0f - high);
      gfloat up = (band_lo <= 1e-5f) ? ((L >= low - 1e-4f) ? 1.0f : 0.0f)
                                     : 1.0f - ps_tone_ramp ((low - L) / band_lo);
      gfloat dn = (band_hi <= 1e-5f) ? ((L <= high + 1e-4f) ? 1.0f : 0.0f)
                                     : 1.0f - ps_tone_ramp ((L - high) / band_hi);
      return up * dn;
    }
  }
}

/* 有硬边界（容差 0，或阈值已经贴到极端）时不能走查表：1024 级线性插值会把
 * 一个码宽的台阶抹成 30 多，实测对拍时正好压在台阶上就报 225 码的假误差。
 * A hard edge must not go through the LUT: linear interpolation smears the
 * one-code step across a sample, which showed up as a bogus 225-code error. */
static gboolean
tone_is_hard (MaskSelectType mode, gfloat low, gfloat high, gfloat fzv)
{
  if (mode == MASK_BLACK) return fzv * (1.0f - low) <= 1e-5f;
  if (mode == MASK_WHITE) return fzv * high <= 1e-5f;
  return fzv * low <= 1e-5f || fzv * (1.0f - high) <= 1e-5f;
}

static void
build_tone_lut (gfloat         lut[TONE_LUT],
                MaskSelectType mode,
                gfloat         low,
                gfloat         high,
                gfloat         fzv)
{
  for (gint i = 0; i < TONE_LUT; i++)
    lut[i] = CLAMP (tone_alpha ((gfloat) i / (TONE_LUT - 1),
                                mode, low, high, fzv), 0.0f, 1.0f);
}

static inline gfloat
tone_lookup (const gfloat lut[TONE_LUT], gfloat L)
{
  gfloat pos = CLAMP (L, 0.0f, 1.0f) * (TONE_LUT - 1);
  gint   i   = (gint) pos;
  gfloat fr  = pos - i;

  if (G_UNLIKELY (i >= TONE_LUT - 1))
    return lut[TONE_LUT - 1];
  return lut[i] * (1.0f - fr) + lut[i + 1] * fr;
}

/* 感知（非线性）格式：公式按 8bit sRGB 伽马域推导，必须拿伽马值，否则 babl
 * 会喂线性光，数值与 PS 对不上
 * Perceptual (non-linear) format: the maths was derived in the 8-bit sRGB
 * gamma domain. Linear light from babl would drift away from Photoshop. */
static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}

static void
prepare(GeglOperation *op)
{
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
  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  MaskSelectType mode;
  GeglColor *custom_color;
  gboolean preview_red;
  gboolean do_invert;
  gdouble fuzz, feather, sat_min;
  gint sh_lim, hi_lim, mt_lo, mt_hi;

  g_object_get(G_OBJECT(op),
    "mask-mode", &mode,
    "custom-color", &custom_color,
    "preview-red-mask", &preview_red,
    "fuzziness", &fuzz,
    "feather", &feather,
    "saturation-min", &sat_min,
    "shadows-limit", &sh_lim,
    "highlights-limit", &hi_lim,
    "midtone-low", &mt_lo,
    "midtone-high", &mt_hi,
    "invert", &do_invert,
    NULL);

  /* 自定颜色：目标值直接按源空间伽马格式取。不能用 gegl_color_get_rgba ——
   * 它返回线性光，而下面的像素是伽马域值，旧代码拿线性值对伽马值算距离，
   * 口径不一致，暗色目标会整体偏。
   * Custom colour: fetch the target straight in the source-space gamma
   * format. gegl_color_get_rgba returns linear light, which does not match
   * the gamma-domain pixels below - comparing across that mismatch shifted
   * every dark target. The mismatch is also computed in CIELAB: babl
   * converts a whole row at once, so per-pixel cost stays at one sqrt.
   * ΔE76 is normalised as d = ΔE/100 (black↔white ≈ 100) and clamped, so
   * the fuzziness window keeps the same semantics as the hue presets. */
  gfloat       tgt_lab[4] = { 0.0f, 0.0f, 0.0f, 1.0f };
  gfloat       tgt_rgb[4];
  const Babl  *lab_fmt    = NULL;
  const Babl  *fish_lab   = NULL;
  gfloat      *lab_line   = NULL;

  if (mode == MASK_CUSTOM)
  {
    lab_fmt  = babl_format ("CIE Lab alpha float");
    fish_lab = babl_fish (perceptual_format (op), lab_fmt);
    /* 目标色按源空间伽马格式取成像素，再进 Lab，保证和像素同一条通路。
     * Fetch the target as a source-space gamma pixel first, then to Lab,
     * so it travels the exact same conversion path as the image rows. */
    gegl_color_get_pixel (custom_color, perceptual_format (op), tgt_rgb);
    babl_process (fish_lab, tgt_rgb, tgt_lab, 1);
  }
  g_object_unref (custom_color);

  gfloat fz = fuzz * 0.01f;
  gfloat ft = feather * 0.01f;
  gfloat st = sat_min * 0.01f;

  /* 容差窗 w = fuzziness/200，即 fz=200 时窗宽到最大不匹配度（色相互补、
   * 纯黑↔纯白），fz=50 约为 ±45° 色相 / 亮度 0.75 端，语义在所有模式一致。
   * feather 控制窗内缘的过渡带宽。
   * Window w = fuzziness/200 so fz=200 reaches the farthest mismatch
   * (complementary hue, pure white↔pure black); feather controls the soft
   * band inside the window. Same meaning in every mode. */
  const gfloat w = CLAMP(fz * 0.5f, 0.0f, 1.0f);
  const gfloat w_lo = w * (1.0f - CLAMP(ft, 0.0f, 1.0f));
  /* 色系预设的彩度门限（门控量是彩度 s×v）：灰阶与近黑像素没有可用色相，
   * 不该被色相匹配选中。默认 0 时用固定底限 0.25：实测 (16,0,0) 这种近黑
   * 彩度约 0.06，底限 0.05 挡不住它；0.25 ≈ RGB 通道差 13%，
   * 再暗/再灰的色相就是噪声。
   * Chroma gate for hue presets (gate input is chroma s×v): grays and
   * near-blacks have no usable hue. With the default 0 the floor is 0.25:
   * a measured (16,0,0) near-black has chroma ~0.06, which a 0.05 floor
   * still lets through; 0.25 is ~13% RGB channel spread. */
  const gfloat sg_lo = st * 0.5f;
  const gfloat sg_hi = MAX(st, 0.25f);

  /* 色调模式：阈值 + 容差 → 亮度响应查表。PS 的容差上限是 100，本算子沿用
   * 统一的 0–200，所以这里除以 200 得到 0–1 的 fzv。
   * Tonal modes: threshold + fuzziness -> luma response LUT. Photoshop caps
   * its tonal fuzziness at 100; this op keeps the uniform 0-200 range, hence
   * the /200 to normalise. */
  const gboolean tone_mode = (mode == MASK_WHITE || mode == MASK_BLACK ||
                              mode == MASK_GRAY);
  gfloat   tone_lut[TONE_LUT];
  gfloat   tone_low  = 0.0f;
  gfloat   tone_high = 1.0f;
  gboolean tone_hard = FALSE;

  if (tone_mode)
  {
    if (mode == MASK_BLACK)
      tone_low = (gfloat) sh_lim / 255.0f;       /* 阴影上限 */
    else if (mode == MASK_WHITE)
      tone_high = (gfloat) hi_lim / 255.0f;      /* 高光下限 */
    else
    {
      tone_low  = (gfloat) mt_lo / 255.0f;
      tone_high = (gfloat) mt_hi / 255.0f;
      if (tone_low > tone_high)                  /* 拖反了也别出怪图 */
      {
        gfloat t = tone_low; tone_low = tone_high; tone_high = t;
      }
    }
    tone_hard = tone_is_hard (mode, tone_low, tone_high, w);
    if (!tone_hard)
      build_tone_lut (tone_lut, mode, tone_low, tone_high, w);
  }

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  if (lab_fmt)
    lab_line = g_new(gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row = { roi->x, roi->y + y, roi->width, 1 };
    gegl_buffer_get(in_buf, &row, 1.0f, perceptual_format(op),
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    if (lab_line)
      babl_process (fish_lab, in_line, lab_line, roi->width);

    for (gint x = 0; x < roi->width; x++)
    {
      gint p = x * 4;
      gfloat r = in_line[p+0];
      gfloat g = in_line[p+1];
      gfloat b = in_line[p+2];
      gfloat h, s, v;

      if (!tone_mode)
        rgb_to_hsv(r, g, b, &h, &s, &v);

      gfloat alpha;

      if (tone_mode)
      {
        /* 高光/阴影/中间调：纯亮度响应。羽化在这三个模式里没有对应概念
         * （柔边由容差决定），所以不参与。
         * Tonal modes: pure luma response. Feather has no counterpart here -
         * in Photoshop the softness comes from fuzziness alone. */
        gfloat lv = luminance (r, g, b);
        alpha = tone_hard ? tone_alpha (lv, mode, tone_low, tone_high, w)
                          : tone_lookup (tone_lut, lv);
      }
      else
      {
        /* d：与目标的不匹配度，0 = 精确匹配，1 = 完全不匹配
         * d: mismatch to the target colour, 0 = exact match */
        gfloat d = 1.0f;
        gboolean hue_mode = FALSE;

        switch (mode)
        {
          case MASK_RED:
            d = hue_dist(h, 0.0f);
            hue_mode = TRUE;
            break;
          case MASK_YELLOW:
            d = hue_dist(h, 1.0f / 6.0f);
            hue_mode = TRUE;
            break;
          case MASK_GREEN:
            d = hue_dist(h, 2.0f / 6.0f);
            hue_mode = TRUE;
            break;
          case MASK_CYAN:
            d = hue_dist(h, 3.0f / 6.0f);
            hue_mode = TRUE;
            break;
          case MASK_BLUE:
            d = hue_dist(h, 4.0f / 6.0f);
            hue_mode = TRUE;
            break;
          case MASK_MAGENTA:
            d = hue_dist(h, 5.0f / 6.0f);
            hue_mode = TRUE;
            break;
          case MASK_CUSTOM:
          {
            /* ΔE76 加 ΔE94 的明度权重 kL=2：明度差折半。选色蒙版要的是
             * 「同一族颜色」，暗红和亮红是一族的，明度差不该否决它；
             * 纯 ΔE76 会把 ΔL≈28 的暗红判到窗外（实测）。归一化仍是
             * d = ΔE/100 鉗到 1，fz=200 时窗仍能覆盖最大不匹配度。
             * ΔE76 with ΔE94's lightness weight kL=2 (ΔL halved): a mask
             * picks colour families, and dark red is the same family as
             * bright red - plain ΔE76 pushes ΔL≈28 out of the window.
             * Still normalised as d = ΔE/100, clamped to 1, so fz = 200
             * keeps covering everything. */
            gfloat dl = (lab_line[p+0] - tgt_lab[0]) * 0.5f;
            gfloat da = lab_line[p+1] - tgt_lab[1];
            gfloat db = lab_line[p+2] - tgt_lab[2];
            d = MIN (sqrtf (dl*dl + da*da + db*db) * 0.01f, 1.0f);
            break;
          }
          default:
            d = 1.0f;
        }

        if (w >= 1.0f)
          alpha = 1.0f;   /* fz=200：连极端差异也选上 / fz=200 picks everything */
        else
          alpha = 1.0f - smooth_step(d, w_lo, w);
        if (hue_mode)
          /* 彩度门：s×v 而不是单看 s。近黑像素 v≈0 时 s 可以是 1，
           * 但那个色相是数值噪声；彩度同时反映饱和度和明度。
           * Chroma gate (s×v), not s alone: a near-black pixel can report
           * s = 1 while its hue is numeric noise. Chroma folds value in. */
          alpha *= smooth_step(s * v, sg_lo, sg_hi);
      }
      alpha = CLAMP(alpha, 0.0f, 1.0f);
      if (do_invert)
        alpha = 1.0f - alpha;

      if (preview_red) {
        out_line[p+0] = r * (1.0f - alpha) + 1.0f * alpha;
        out_line[p+1] = g * (1.0f - alpha) + 0.0f * alpha;
        out_line[p+2] = b * (1.0f - alpha) + 0.0f * alpha;
        out_line[p+3] = 1.0f;
      } else {
        out_line[p+0] = r;
        out_line[p+1] = g;
        out_line[p+2] = b;
        out_line[p+3] = alpha;
      }
    }

    gegl_buffer_set(out_buf, &row, 0, perceptual_format(op),
                     out_line, GEGL_AUTO_ROWSTRIDE);
  }

  g_free(in_line);
  g_free(out_line);
  g_free(lab_line);
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
    "name",            "lb:color-mask-select",
    "title",           _("Color Mask Select"),
    "description",     _("Photoshop Color Range with color picker & red overlay"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Mask",
    "gimp:menu-label", _("Mask by Color"),
    NULL);
}

#endif