/* ===========================================================================
 * SuperMrWang · GEGL Operation
 * ---------------------------------------------------------------------------
 * id     : lb:colorize-hsl
 * 菜单   : Colorize
 * 作用   : 单色罩染：替换色相与饱和度，保留画面原有明暗结构
 * 算法   : 三通道 Overlay 叠灰层调明度 → 取 HSL 的 L → 换 H/S → 回 RGB；
 *          输出的像素间差异只来自 L
 * 类型   : GeglOperationFilter
 * 参考   : Photoshop「颜色」调整层 + Overlay 着色
 * 许可   : GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (hue, _("Hue"), 0.0) \
    description (_("Target Hue (0~360)")) \
    value_range (0.0, 360.0) \
    ui_range (0.0, 360.0)

property_double (saturation, _("Saturation"), 50.0) \
    description (_("Target Saturation (0~100)")) \
    value_range (0.0, 100.0) \
    ui_range (0.0, 100.0)

property_double (lightness, _("Lightness"), 0.0) \
    description (_("Lightness adjustment, Overlay blend solid gray layer (-100 ~ +100)")) \
    value_range (-100.0, 100.0) \
    ui_range (-100.0, 100.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_colorize_hsl
#define GEGL_OP_C_SOURCE colorize-hsl.c
#include "gegl-op.h"

static inline gfloat sanitize_f(gfloat v)
{
  if (!isfinite(v))
    return 0.0f;
  return v;
}

static inline gdouble clamp01(gdouble v)
{
  if (v < 0.0) return 0.0;
  if (v > 1.0) return 1.0;
  return v;
}

/* ---- RGB 0..1 -> HSL (H:0..360, S:0..1, L:0..1) ------------------------ */
static void rgb_to_hsl(gdouble r, gdouble g, gdouble b,
                       gdouble *h_out, gdouble *s_out, gdouble *l_out)
{
  gdouble mx = MAX(MAX(r, g), b);
  gdouble mn = MIN(MIN(r, g), b);
  gdouble delta = mx - mn;
  gdouble h = 0.0, s = 0.0;
  gdouble l = (mx + mn) * 0.5;

  if (delta > 0.0)
  {
    s = (l > 0.5) ? delta / (2.0 - mx - mn) : delta / (mx + mn);

    if (mx == r)
      h = (g - b) / delta + (g < b ? 6.0 : 0.0);
    else if (mx == g)
      h = (b - r) / delta + 2.0;
    else
      h = (r - g) / delta + 4.0;

    h *= 60.0;
  }

  *h_out = h;
  *s_out = s;
  *l_out = l;
}

/* ---- HSL -> RGB 0..1 --------------------------------------------------- */
static void hsl_to_rgb(gdouble h, gdouble s, gdouble l,
                       gdouble *r_out, gdouble *g_out, gdouble *b_out)
{
  h = fmod(h, 360.0);
  if (h < 0.0) h += 360.0;

  gdouble c  = (1.0 - fabs(2.0 * l - 1.0)) * s;
  gdouble hp = h / 60.0;
  gdouble x  = c * (1.0 - fabs(fmod(hp, 2.0) - 1.0));
  gdouble m  = l - c * 0.5;
  gdouble r, g, b;

  if      (hp < 1.0) { r = c;   g = x;   b = 0.0; }
  else if (hp < 2.0) { r = x;   g = c;   b = 0.0; }
  else if (hp < 3.0) { r = 0.0; g = c;   b = x;   }
  else if (hp < 4.0) { r = 0.0; g = x;   b = c;   }
  else if (hp < 5.0) { r = x;   g = 0.0; b = c;   }
  else               { r = c;   g = 0.0; b = x;   }

  *r_out = r + m;
  *g_out = g + m;
  *b_out = b + m;
}

/* ---- Overlay 明度调整 ---------------------------------------------------
 *   v   : 底层通道值 0..1
 *   a   : 上层纯灰 0..1，由 light_slider [-100,100] 映射
 *   Overlay 公式：v<=0.5 时 out = 2*v*a；否则 out = 1 - 2*(1-v)*(1-a)
 *   返回 0..1
 */
static inline gdouble adjust_channel(gdouble v, gdouble light_slider)
{
  /* 滑块映射到Overlay上层灰度 a: [-100,100] → [0,1] */
  gdouble a = (light_slider + 100.0) / 200.0;

  gdouble out;
  if (v <= 0.5)
  {
    out = 2.0 * v * a;
  }
  else
  {
    out = 1.0 - 2.0 * (1.0 - v) * (1.0 - a);
  }
  return clamp01(out);
}

static void colorize_kernel(gfloat inR, gfloat inG, gfloat inB,
                            gdouble target_h, gdouble target_s, gdouble light_slider,
                            gfloat *outR, gfloat *outG, gfloat *outB)
{
  /* ---- Step 1: 先对 RGB 通道做Overlay明度调整 -------------------------- */
  gdouble r_adj = adjust_channel(inR, light_slider);
  gdouble g_adj = adjust_channel(inG, light_slider);
  gdouble b_adj = adjust_channel(inB, light_slider);

  /* ---- Step 2: 将调整后的 RGB 转为 HSL，取 L --------------------------- */
  gdouble h_orig, s_orig, L_adj;
  rgb_to_hsl(r_adj, g_adj, b_adj, &h_orig, &s_orig, &L_adj);

  /* ---- Step 3: 只替换 H 和 S，L 用调整后的值 --------------------------- */
  gdouble final_h = target_h;             /* 0..360 */
  gdouble final_s = target_s / 100.0;     /* 0..1  */
  gdouble final_l = L_adj;                /* 来自调整后的 RGB 的 L */

  /* ---- Step 4: HSL -> RGB ---------------------------------------------- */
  gdouble r2, g2, b2;
  hsl_to_rgb(final_h, final_s, final_l, &r2, &g2, &b2);

  *outR = (gfloat)clamp01(r2);
  *outG = (gfloat)clamp01(g2);
  *outB = (gfloat)clamp01(b2);
}

static void prepare(GeglOperation *op)
{
  gegl_operation_set_format(op, "input",  babl_format("RGBA float"));
  gegl_operation_set_format(op, "output", babl_format("RGBA float"));
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

  gdouble slider_h, slider_s, slider_l;
  g_object_get(G_OBJECT(op),
               "hue",        &slider_h,
               "saturation", &slider_s,
               "lightness",  &slider_l,
               NULL);

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };

    gegl_buffer_get(in_buf, &row_rect, 1.0f, babl_format("RGBA float"),
                    in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint px = x * 4;
      gfloat r = in_line[px + 0];
      gfloat g = in_line[px + 1];
      gfloat b = in_line[px + 2];
      gfloat a = in_line[px + 3];

      gfloat ro, go, bo;
      colorize_kernel(r, g, b, slider_h, slider_s, slider_l, &ro, &go, &bo);

      out_line[px + 0] = sanitize_f(ro);
      out_line[px + 1] = sanitize_f(go);
      out_line[px + 2] = sanitize_f(bo);
      out_line[px + 3] = sanitize_f(a);
    }

    gegl_buffer_set(out_buf, &row_rect, 0, babl_format("RGBA float"),
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
    "name",            "lb:colorize-hsl",
    "title",           _("Colorize"),
    "description",     _("Colorize with Overlay-based lightness adjustment: keep HSL lightness, replace hue/saturation."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Colorize"),
    NULL);
}

#endif