/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsl-seven
 * menu       HSL 7 Bands
 * purpose    红/橙/黄/绿/青/蓝/紫七段色相各自调 H/S/L，ACR 风格
 *            Seven hue bands (red, orange, yellow, green, cyan, blue,
 *            purple), each with its own H/S/L shift, Camera Raw style.
 * algorithm  21 个滑块按色相段加权叠加，段间由 feather 平滑过渡；低于
 *            min-saturation 的灰像素可选择跳过
 *            The 21 sliders are weighted by hue band and summed, with
 *            'feather' cross-fading adjacent bands. Pixels below
 *            'min-saturation' can be skipped.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  Camera Raw 的 HSL 面板
 *            Adobe Camera Raw HSL panel
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* 全局通用参数
 * Global shared parameters */
property_double (hue_feather, _("Hue Transition Feather"), 12.0)
    value_range (0.0, 50.0)
    ui_range (0.0, 50.0)
    description (_("Smooth transition between color ranges"))

property_double (saturation_min, _("Min Saturation Filter"), 0.0)
    value_range (0.0, 100.0)
    ui_range (0.0, 100.0)
    description (_("Grayscale pixels below this saturation will not be modified"))

/* ---- 红 / red ---------------------------------------------------------- */
property_double (red_hue, _("Red Hue"), 0.0)
    value_range (-100.0, 100.0)
property_double (red_sat, _("Red Saturation"), 0.0)
    value_range (-100.0, 100.0)
property_double (red_lum, _("Red Luminance"), 0.0)
    value_range (-100.0, 100.0)

/* ---- 橙 / orange ------------------------------------------------------- */
property_double (orange_hue, _("Orange Hue"), 0.0)
    value_range (-100.0, 100.0)
property_double (orange_sat, _("Orange Saturation"), 0.0)
    value_range (-100.0, 100.0)
property_double (orange_lum, _("Orange Luminance"), 0.0)
    value_range (-100.0, 100.0)

/* ---- 黄 / yellow ------------------------------------------------------- */
property_double (yellow_hue, _("Yellow Hue"), 0.0)
    value_range (-100.0, 100.0)
property_double (yellow_sat, _("Yellow Saturation"), 0.0)
    value_range (-100.0, 100.0)
property_double (yellow_lum, _("Yellow Luminance"), 0.0)
    value_range (-100.0, 100.0)

/* ---- 绿 / green -------------------------------------------------------- */
property_double (green_hue, _("Green Hue"), 0.0)
    value_range (-100.0, 100.0)
property_double (green_sat, _("Green Saturation"), 0.0)
    value_range (-100.0, 100.0)
property_double (green_lum, _("Green Luminance"), 0.0)
    value_range (-100.0, 100.0)

/* ---- 青 / cyan --------------------------------------------------------- */
property_double (cyan_hue, _("Cyan Hue"), 0.0)
    value_range (-100.0, 100.0)
property_double (cyan_sat, _("Cyan Saturation"), 0.0)
    value_range (-100.0, 100.0)
property_double (cyan_lum, _("Cyan Luminance"), 0.0)
    value_range (-100.0, 100.0)

/* ---- 蓝 / blue --------------------------------------------------------- */
property_double (blue_hue, _("Blue Hue"), 0.0)
    value_range (-100.0, 100.0)
property_double (blue_sat, _("Blue Saturation"), 0.0)
    value_range (-100.0, 100.0)
property_double (blue_lum, _("Blue Luminance"), 0.0)
    value_range (-100.0, 100.0)

/* ---- 紫 / purple ------------------------------------------------------- */
property_double (purple_hue, _("Purple Hue"), 0.0)
    value_range (-100.0, 100.0)
property_double (purple_sat, _("Purple Saturation"), 0.0)
    value_range (-100.0, 100.0)
property_double (purple_lum, _("Purple Luminance"), 0.0)
    value_range (-100.0, 100.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_hsl_seven
#define GEGL_OP_C_SOURCE hsl-seven.c

#include "gegl-op.h"

/* 复用 RGB → HSV 转换
 * reuse the RGB -> HSV conversion */
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
static inline gfloat
smooth_step(gfloat val, gfloat a, gfloat b)
{
  /* a == b 时退化为阶跃函数，避免 (val - a) / (b - a) 出现除零。
   * 对 sat_mask 来说：sat_min = 0 时 a = b = 0，s = 0 返回 0（纯黑/灰跳
   * 过），s > 0 返回 1（正常参与）。
   * When a == b it degenerates to a step function, so (val - a) / (b - a)
   * never divides by zero. For sat_mask: sat_min = 0 gives a = b = 0, so s
   * = 0 returns 0 (black/grey skipped) and s > 0 returns 1 (takes part). */
  if (b <= a)
    return (val <= a) ? 0.0f : 1.0f;

  if (val <= a) return 0.0f;
  if (val >= b) return 1.0f;

  gfloat t = (val - a) / (b - a);
  return t * t * (3.0f - 2.0f * t);
}
/* 色相环形包裹到 0~1
 * wrap hue onto the 0..1 circle */
static inline gfloat
hue_wrap(gfloat h)
{
  h = fmodf(h, 1.0f);
  if (h < 0.0f) h += 1.0f;
  return h;
}

/* HSV 边界钳位
 * clamp the HSV components */
static inline void
hsv_clamp(gfloat *h, gfloat *s, gfloat *v)
{
  *h = hue_wrap(*h);
  *s = CLAMP(*s, 0.0f, 1.0f);
  *v = CLAMP(*v, 0.0f, 1.0f);
}

/* 通用环形色相区间权重（支持跨 0 的红色区间）
 * generic circular hue-range weight (handles the red range that crosses 0) */
static inline gfloat
get_hue_weight(gfloat h, gfloat h_start, gfloat h_end, gfloat feather)
{
  gfloat w = 0.0f;
  gfloat f = feather * 0.01f;

  if (h_start > h_end) {
    /* 按到区间两端的距离算平滑权重
     * smooth weight from the distance to either end of the range */
    gfloat w_right = smooth_step(h, h_start - f, h_start);      // 接近 1 侧
    gfloat w_left  = 1.0f - smooth_step(h, h_end, h_end + f);   // 接近 0 侧，注意反转
    w = CLAMP(w_right + w_left, 0.0f, 1.0f);
}
  else
  {
    gfloat in  = smooth_step(h, h_start - f, h_start);
    gfloat out = smooth_step(h, h_end, h_end + f);
    w = in * (1.0f - out);
  }
  return CLAMP(w, 0.0f, 1.0f);
}

/* HSV 转回 RGBA
 * HSV back to RGBA */
static inline void
hsv_to_rgb(gfloat h, gfloat s, gfloat v, gfloat *r, gfloat *g, gfloat *b)
{
  gfloat c = v * s;
  gfloat x = c * (1.0f - fabsf(fmodf(h*6.0f, 2.0f) - 1.0f));
  gfloat m = v - c;

  if (h < 1.0f/6.0f)
    *r=c, *g=x, *b=0;
  else if (h < 2.0f/6.0f)
    *r=x, *g=c, *b=0;
  else if (h < 3.0f/6.0f)
    *r=0, *g=c, *b=x;
  else if (h < 4.0f/6.0f)
    *r=0, *g=x, *b=c;
  else if (h < 5.0f/6.0f)
    *r=x, *g=0, *b=c;
  else
    *r=c, *g=0, *b=x;

  *r += m;
  *g += m;
  *b += m;
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

  /* 全局参数
   * global parameters */
  gdouble hue_ft, sat_min_ui;
  /* 红
   * red */
  gdouble red_h, red_s, red_l;
  /* 橙
   * orange */
  gdouble ora_h, ora_s, ora_l;
  /* 黄
   * yellow */
  gdouble yel_h, yel_s, yel_l;
  /* 绿
   * green */
  gdouble gre_h, gre_s, gre_l;
  /* 青
   * cyan */
  gdouble cya_h, cya_s, cya_l;
  /* 蓝
   * blue */
  gdouble blu_h, blu_s, blu_l;
  /* 紫
   * purple */
  gdouble pur_h, pur_s, pur_l;

  g_object_get(G_OBJECT(op),
    "hue-feather", &hue_ft,
    "saturation-min", &sat_min_ui,

    "red-hue", &red_h, "red-sat", &red_s, "red-lum", &red_l,
    "orange-hue", &ora_h, "orange-sat", &ora_s, "orange-lum", &ora_l,
    "yellow-hue", &yel_h, "yellow-sat", &yel_s, "yellow-lum", &yel_l,
    "green-hue", &gre_h, "green-sat", &gre_s, "green-lum", &gre_l,
    "cyan-hue", &cya_h, "cyan-sat", &cya_s, "cyan-lum", &cya_l,
    "blue-hue", &blu_h, "blue-sat", &blu_s, "blue-lum", &blu_l,
    "purple-hue", &pur_h, "purple-sat", &pur_s, "purple-lum", &pur_l,
    NULL);

  gfloat sat_min_thr = sat_min_ui * 0.01f;

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  /* ACR 标准七色色相区间，H 取 0~1
   * ACR's seven standard hue ranges, H in 0..1 */
  typedef struct {
    gfloat start;
    gfloat end;
    gdouble h_off;
    gdouble s_scale;
    gdouble l_off;
  } ColorRange;

  ColorRange ranges[7] = {
    /* 红（跨 0）
     * red, crossing 0 */
    {0.92f, 0.08f, red_h, red_s, red_l},
    /* 橙
     * orange */
    {0.08f, 0.18f, ora_h, ora_s, ora_l},
    /* 黄
     * yellow */
    {0.18f, 0.28f, yel_h, yel_s, yel_l},
    /* 绿
     * green */
    {0.28f, 0.48f, gre_h, gre_s, gre_l},
    /* 青
     * cyan */
    {0.48f, 0.62f, cya_h, cya_s, cya_l},
    /* 蓝
     * blue */
    {0.62f, 0.78f, blu_h, blu_s, blu_l},
    /* 紫
     * purple */
    {0.78f, 0.92f, pur_h, pur_s, pur_l},
  };

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row = { roi->x, roi->y + y, roi->width, 1 };
    gegl_buffer_get(in_buf, &row, 1.0f, perceptual_format(op),
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint p = x * 4;
      gfloat r = in_line[p+0];
      gfloat g = in_line[p+1];
      gfloat b = in_line[p+2];
      gfloat a = in_line[p+3];

      gfloat h, s, v;
      rgb_to_hsv(r, g, b, &h, &s, &v);

      /* 灰度过滤：饱和度低于阈值时完全不调整
       * grey filter: below the saturation threshold nothing is adjusted */
      gfloat sat_mask = smooth_step(s, sat_min_thr * 0.5f, sat_min_thr);
      if (sat_mask < 0.001f)
      {
        out_line[p+0] = r;
        out_line[p+1] = g;
        out_line[p+2] = b;
        out_line[p+3] = a;
        continue;
      }

      gfloat orig_h = h;
      gfloat orig_s = s;

      /* 遍历 7 个色系叠加调整
       * loop over the seven bands and accumulate */
      for (gint i = 0; i < 7; i++)
      {
        ColorRange cr = ranges[i];
        gfloat w = get_hue_weight(orig_h, cr.start, cr.end, hue_ft);
        w *= sat_mask;
        if (w < 0.001f) continue;

        /* 色相偏移 -100~100 → 色环上 ±0.15
         * hue shift -100..100 -> +-0.15 of the hue circle */
        gfloat h_delta = cr.h_off * 0.0015f * w;
        h += h_delta;

        /* 饱和度缩放：-100 = 0x，+100 = 2x
         * saturation scale: -100 = 0x, +100 = 2x */
        gfloat s_mult = (1.0f + cr.s_scale * 0.01f);
        s = orig_s * (1.0f - w) + s * s_mult * w;

        /* 明度偏移 ±100
         * lightness shift, +-100 */
        gfloat v_delta = cr.l_off * 0.005f * w;
        v += v_delta;
      }

      hsv_clamp(&h, &s, &v);
      gfloat nr, ng, nb;
      hsv_to_rgb(h, s, v, &nr, &ng, &nb);

      out_line[p+0] = nr;
      out_line[p+1] = ng;
      out_line[p+2] = nb;
      out_line[p+3] = a;
    }

    gegl_buffer_set(out_buf, &row, 0, perceptual_format(op),
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
    "name",            "lb:hsl-seven",
    "title",           _("HSL 7 Bands"),
    "description",     _("Red Orange Yellow Green Cyan Blue Purple independent Hue/Sat/Lum"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("HSL 7 Bands"),
    NULL);
}

#endif