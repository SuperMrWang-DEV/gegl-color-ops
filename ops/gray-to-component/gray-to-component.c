/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:gray-to-component
 * menu       Gray To Component
 * purpose    通道灰度调色工作流的编码器：把分解出的分量灰度重新编码成
 *            「携带该分量」的彩色图层，供 GIMP 分量混合模式（Hue /
 *            Saturation / Lightness / LCh 系）读取还原，全程非破坏
 *            Encoder for the grayscale-component color-grading workflow:
 *            re-encodes a decomposed component gray layer into a color
 *            layer that GIMP's component blend modes can read back.
 * algorithm  灰度 g∈[0,1] 按模式映射（编码公式经 hsl-cal 恒等往返校准，
 *            见 ops/gray-to-component/README.md）：
 *            hue        hsl_to_rgb(g*360, 1, 0.5)——饱和度/亮度拉满的
 *                       色相轮，喂 Hue 模式恒等
 *            saturation hsv_to_rgb(sat_hue, g, 1)——红相 V=1 的饱和度
 *                       编码（HSV 语义！HSL 的 S 喂 Saturation 模式会
 *                       误差 214/255），喂 Saturation 模式恒等
 *            lightness  Lab(g*100, 0, 0) 直写——喂 LCh Lightness 恒等
 *            red/green/blue  (g,0,0) 等单通道编码，用 Lighten 模式叠合还原
 *            lch-hue    Lab(lch_l, lch_c·cos(g·360°), lch_c·sin(g·360°))
 *                       ——喂 LCh Hue 恒等（HSL 色相与 CIE 色相不可线性
 *                       互转，HSL 轮直接喂 LCh Hue 误差 139/255）
 *            lch-chroma Lab(lch_l, g·chroma_scale, lch_h 方向)——喂
 *                       LCh Chroma 恒等（chroma_scale 默认 100，与 GIMP
 *                       分解量程一致；sRGB 色域 C 可达 ~130，可调大）
 *            输出钉成 CIE Lab alpha float（Lab/LCh 模式零转换直写；HSL/
 *            RGB 模式经 babl fish 转 Lab，与 GIMP 内部转换同源）。
 *            Lab/LCh 编码允许超出 sRGB 色域的值原样保留（float32）。
 * type       GeglOperationFilter（纯逐像素，无 aux，可挂非破坏滤镜）
 * reference  GIMP 3 分量混合模式（HSV 组 + LCh 组）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

enum_start (lb_gtc_mode)
  enum_value (GTC_MODE_HUE,        "hue",        "Hue (HSL wheel)")
  enum_value (GTC_MODE_SATURATION, "saturation", "Saturation (HSV)")
  enum_value (GTC_MODE_LIGHTNESS,  "lightness",  "Lightness (CIE L)")
  enum_value (GTC_MODE_RED,        "red",        "Red channel")
  enum_value (GTC_MODE_GREEN,      "green",      "Green channel")
  enum_value (GTC_MODE_BLUE,       "blue",       "Blue channel")
  enum_value (GTC_MODE_LCH_HUE,    "lch-hue",    "LCh Hue (CIE wheel)")
  enum_value (GTC_MODE_LCH_CHROMA, "lch-chroma", "LCh Chroma")
enum_end (LbGtcMode)

property_enum (mode, _("Mode"), LbGtcMode, lb_gtc_mode, GTC_MODE_HUE)
    description (_("编码模式：灰度映射为哪个分量。Hue/Saturation 配 HSV 组"
                   "混合模式，Lightness/LCh 配 LCh 组，RGB 三通道用 Lighten "
                   "叠合还原"))

property_double (sat_hue, _("Saturation Hue"), 0.0)
    description (_("Saturation 模式使用的色相（度）；0=红，按需可改。该层只"
                   "提供饱和度信息，色相在混合还原时不进入结果"))
    value_range (0.0, 360.0)

property_double (lch_l, _("LCh Lightness"), 54.0)
    description (_("LCh 模式使用的固定明度 L（0-100）。混合模式只读色相/"
                   "色度时此值不影响结果，取中庸值以留在常见色域内"))
    value_range (0.0, 100.0)

property_double (lch_c, _("LCh Chroma"), 30.0)
    description (_("LCh Hue 模式使用的固定色度 C。色度越大颜色越鲜艳，"
                   "过大可能超出 sRGB 色域（float32 下仍可往返）"))
    value_range (0.0, 132.0)
    ui_range (0.0, 100.0)

property_double (lch_h, _("LCh Hue Angle"), 30.0)
    description (_("LCh Chroma 模式使用的固定色相（度）；0=红。该层只提供"
                   "色度信息，色相在混合还原时不进入结果"))
    value_range (0.0, 360.0)

property_double (chroma_scale, _("Chroma Scale"), 100.0)
    description (_("LCh Chroma 模式的满量程：灰度 1.0 对应的色度上限。GIMP "
                   "的 LCh 分解把 C 0..100 映射到满量程；要覆盖更宽色域"
                   "（sRGB 可达 ~130）可调大，但必须与分解侧的缩放一致"))
    value_range (50.0, 160.0)
    ui_range (50.0, 150.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_gray_to_component
#define GEGL_OP_C_SOURCE gray-to-component.c
#include "gegl-op.h"

#define DEG2RAD (G_PI / 180.0f)

static const Babl *gtc_input_format(void)
{
  /* 灰度输入：YA float（亮度+alpha）。分解出的灰度层是 RGBA 时 babl
   * 自动转 Y（CIE 亮度）；需要保 alpha 供混合模式正常工作 */
  return babl_format("YA float");
}

static const Babl *gtc_output_format(void)
{
  return babl_format("CIE Lab alpha float");
}

/* HSL → RGB（色相轮编码：S=1, L=0.5）
 * HSL to RGB conversion, standard colorsys formula */
static inline void hsl_to_rgb(gfloat h_deg, gfloat s, gfloat l,
                              gfloat *r, gfloat *g, gfloat *b)
{
  h_deg = fmodf(fmodf(h_deg, 360.0f) + 360.0f, 360.0f);
  gfloat h = h_deg / 360.0f;

  if (s <= 0.0f)
  {
    *r = *g = *b = l;
    return;
  }

  gfloat q = (l < 0.5f) ? (l * (1.0f + s)) : (l + s - l * s);
  gfloat p = 2.0f * l - q;

  gfloat t[3];
  t[0] = h + 1.0f / 3.0f;   /* R */
  t[1] = h;                 /* G */
  t[2] = h - 1.0f / 3.0f;   /* B */

  for (gint i = 0; i < 3; i++)
  {
    gfloat tt = t[i];
    if (tt < 0.0f) tt += 1.0f;
    if (tt > 1.0f) tt -= 1.0f;
    gfloat v;
    if (tt < 1.0f / 6.0f)
      v = p + (q - p) * 6.0f * tt;
    else if (tt < 0.5f)
      v = q;
    else if (tt < 2.0f / 3.0f)
      v = p + (q - p) * (2.0f / 3.0f - tt) * 6.0f;
    else
      v = p;
    if (i == 0) *r = v; else if (i == 1) *g = v; else *b = v;
  }
}

/* HSV → RGB（饱和度编码：V=1，色相固定）
 * HSV to RGB conversion, standard formula */
static inline void hsv_to_rgb(gfloat h_deg, gfloat s, gfloat v,
                              gfloat *r, gfloat *g, gfloat *b)
{
  h_deg = fmodf(fmodf(h_deg, 360.0f) + 360.0f, 360.0f);
  gfloat h = h_deg / 60.0f;
  gint   i = (gint) h;
  gfloat f = h - (gfloat) i;

  gfloat p = v * (1.0f - s);
  gfloat q = v * (1.0f - f * s);
  gfloat t = v * (1.0f - (1.0f - f) * s);

  switch (i % 6)
  {
    case 0: *r = v; *g = t; *b = p; break;
    case 1: *r = q; *g = v; *b = p; break;
    case 2: *r = p; *g = v; *b = t; break;
    case 3: *r = p; *g = q; *b = v; break;
    case 4: *r = t; *g = p; *b = v; break;
    default:*r = v; *g = p; *b = q; break;
  }
}

/* 每像素：灰度 → 该模式下的 RGB（感知域）
 * Per-pixel: gray → RGB (perceptual domain) for RGB-domain modes */
static inline void gtc_rgb_for_mode(gint          mode,
                                    gfloat        gray,
                                    gdouble       sat_hue,
                                    gfloat       *r,
                                    gfloat       *g,
                                    gfloat       *b,
                                    gboolean     *needs_fish)
{
  *needs_fish = FALSE;

  switch (mode)
  {
    case GTC_MODE_HUE:
      hsl_to_rgb((gfloat)(gray * 360.0f), 1.0f, 0.5f, r, g, b);
      *needs_fish = TRUE;
      break;

    case GTC_MODE_SATURATION:
      /* 红相、V=1 的 HSV 饱和度编码：RGB=(1, 1-s, 1-s)
       * Red hue, V=1: the encoding GIMP's Saturation mode reads exactly */
      hsv_to_rgb((gfloat)sat_hue, gray, 1.0f, r, g, b);
      *needs_fish = TRUE;
      break;

    case GTC_MODE_RED:
      *r = gray; *g = 0.0f; *b = 0.0f;
      *needs_fish = TRUE;
      break;

    case GTC_MODE_GREEN:
      *r = 0.0f; *g = gray; *b = 0.0f;
      *needs_fish = TRUE;
      break;

    case GTC_MODE_BLUE:
      *r = 0.0f; *g = 0.0f; *b = gray;
      *needs_fish = TRUE;
      break;

    default:
      *r = *g = *b = 0.0f;
      break;
  }
}

static void
prepare (GeglOperation *op)
{
  gegl_operation_set_format (op, "input",  gtc_input_format ());
  gegl_operation_set_format (op, "output", gtc_output_format ());
}

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *in_buf,
         GeglBuffer          *out_buf,
         const GeglRectangle *roi,
         gint                 level)
{
  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  gdouble sat_hue, lch_l, lch_c, lch_h, chroma_scale;
  gint    mode;
  g_object_get (G_OBJECT (op),
                "mode",         &mode,
                "sat-hue",      &sat_hue,
                "lch-l",        &lch_l,
                "lch-c",        &lch_c,
                "lch-h",        &lch_h,
                "chroma-scale", &chroma_scale,
                NULL);

  const Babl *fmt_in  = gtc_input_format ();
  const Babl *fmt_out = gtc_output_format ();

  const gint w      = roi->width;
  const gint n_in   = w * 2;    /* YA float */
  const gint n_out  = w * 4;    /* CIE Lab alpha float */

  gfloat *in_line   = g_new (gfloat, n_in);
  gfloat *out_line  = g_new (gfloat, n_out);
  gfloat *rgb_line  = g_new (gfloat, n_out);   /* 供 fish 转换的 RGB 中间行 */

  /* Lab 域模式在循环外算一次三角量
   * Precompute trig constants for Lab-domain modes */
  gfloat hue_cos = 0.0f, hue_sin = 0.0f;
  gboolean lab_domain = (mode == GTC_MODE_LIGHTNESS ||
                         mode == GTC_MODE_LCH_HUE ||
                         mode == GTC_MODE_LCH_CHROMA);
  if (mode == GTC_MODE_LCH_CHROMA)
  {
    hue_cos = cosf ((gfloat) lch_h * DEG2RAD);
    hue_sin = sinf ((gfloat) lch_h * DEG2RAD);
  }

  const Babl *fish = NULL;
  gboolean needs_fish = FALSE;

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, w, 1 };

    gegl_buffer_get (in_buf, &row_rect, 1.0f, fmt_in,
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < w; x++)
    {
      gint px_in  = x * 2;
      gint px_out = x * 4;

      gfloat gray = in_line[px_in + 0];
      gfloat a    = in_line[px_in + 1];

      /* 透明像素：Lab(0,0,0) + 原 alpha，与全仓透明像素规则一致
       * Fully transparent pixels stay transparent */
      if (a <= 0.0f)
      {
        out_line[px_out + 0] = 0.0f;
        out_line[px_out + 1] = 0.0f;
        out_line[px_out + 2] = 0.0f;
        out_line[px_out + 3] = 0.0f;
        continue;
      }

      gfloat gc = CLAMP (gray, 0.0f, 1.0f);

      if (lab_domain)
      {
        gfloat L, ca, cb;
        if (mode == GTC_MODE_LIGHTNESS)
        {
          L  = gc * 100.0f;
          ca = 0.0f;
          cb = 0.0f;
        }
        else if (mode == GTC_MODE_LCH_HUE)
        {
          /* h = g*360，L/C 固定。a=C·cos(h°), b=C·sin(h°) 是 CIE LCh 的
           * 定义式，直写 Lab 与 babl 直写 LCH 等价
           * h = g*360 with fixed L/C: exact LCh definition in Lab coords */
          gfloat h_rad = gc * 360.0f * DEG2RAD;
          L  = (gfloat) lch_l;
          ca = (gfloat) lch_c * cosf (h_rad);
          cb = (gfloat) lch_c * sinf (h_rad);
        }
        else /* GTC_MODE_LCH_CHROMA */
        {
          L  = (gfloat) lch_l;
          ca = gc * (gfloat) chroma_scale * hue_cos;
          cb = gc * (gfloat) chroma_scale * hue_sin;
        }

        out_line[px_out + 0] = L;
        out_line[px_out + 1] = ca;
        out_line[px_out + 2] = cb;
        out_line[px_out + 3] = a;
      }
      else
      {
        gfloat r, g, b;
        gtc_rgb_for_mode (mode, gc, sat_hue, &r, &g, &b, &needs_fish);
        if (needs_fish && fish == NULL)
          fish = babl_fish (babl_format ("R'G'B'A float"), fmt_out);

        rgb_line[px_out + 0] = r;
        rgb_line[px_out + 1] = g;
        rgb_line[px_out + 2] = b;
        rgb_line[px_out + 3] = a;   /* fish 保留 alpha */
      }
    }

    if (!lab_domain)
    {
      /* RGB 域模式：整行交给 babl 转 Lab，与 GIMP 内部转换同源、零漂移
       * RGB-domain modes: convert the whole row via babl fish */
      babl_process (fish, rgb_line, out_line, w);
    }

    gegl_buffer_set (out_buf, &row_rect, 0, fmt_out,
                     out_line, GEGL_AUTO_ROWSTRIDE);
  }

  g_free (in_line);
  g_free (out_line);
  g_free (rgb_line);
  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  oclass->prepare = prepare;
  fclass->process = process;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:gray-to-component",
    "title",           _("Gray To Component"),
    "description",     _("Re-encode a decomposed component gray layer into a color layer that GIMP's component blend modes (Hue / Saturation / Value / LCh group) read back exactly. Feed the result as a blend layer: Hue mode for 'hue', Saturation for 'saturation', LCh Lightness for 'lightness', LCh Hue / LCh Chroma for the lch modes, and Lighten to recombine the red/green/blue channel layers. Encoding formulas are calibrated by identity round-trip against GIMP 3 blend modes."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Blend",
    "gimp:menu-label", _("Gray To Component"),
    NULL);
}

#endif
