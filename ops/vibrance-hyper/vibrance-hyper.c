/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:vibrance-hyper
 * menu       Natural Saturation
 * purpose    自然饱和度：提升低饱和区，抑制高饱和与肤色，不破坏色相
 *            Natural saturation: lift muted colours while holding back highly
 *            saturated ones and skin tones, without moving hue.
 * algorithm  LAB 下按源图色度 C* 取双曲增益，叠加肤色色相窗；色度沿固定色相放
 *            大后按色域二分收敛，避免裁剪扭色
 *            In LAB a hyperbolic gain is driven by the source chroma C*,
 *            gated by a skin-hue window. Chroma grows along a fixed hue and
 *            is bisected back into gamut instead of being clipped.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  Adobe Camera Raw / Photoshop 的 Vibrance
 *            Adobe Camera Raw / Photoshop Vibrance
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (vibrance, _("Vibrance"), 0.0)
    description (_("Adaptive natural saturation: fuller boost on low-chroma colors, "
                   "fading out on already vivid ones"))
    value_range (-100.0, 100.0)
    ui_range    (-50.0, 50.0)
    ui_steps    (0.1, 1.0)

property_double (saturation, _("Saturation"), 1.0)
    description (_("Global linear chroma multiplier, applied independently of Vibrance"))
    value_range (0.0, 10.0)
    ui_range    (0.0, 2.0)
    ui_steps    (0.1, 1.0)

property_double (attenuation, _("High Chroma Attenuation"), 2.0)
    description (_("How fast Vibrance fades on saturated colors: higher = stronger protection"))
    value_range (0.5, 8.0)
    ui_range    (0.5, 5.0)
    ui_steps    (0.1, 0.5)

property_double (skin_protect, _("Skin Protection"), 0.7)
    description (_("How strongly skin-tone hues (orange band around 55°) are held back: "
                   "0 = treat skin like any other color, 1 = almost no boost on skin"))
    value_range (0.0, 1.0)
    ui_range    (0.0, 1.0)
    ui_steps    (0.05, 0.1)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_vibrance_hyper
#define GEGL_OP_C_SOURCE vibrance-hyper.c

#include "gegl-op.h"

typedef struct
{
  gdouble vibrance;      /* 已归一到 -2..2（滑杆/50） / normalised to -2..2 (slider / 50) */
  gdouble saturation;
  gdouble atten;
  gdouble skin;          /* 肤色保护强度 0..1 / skin protection 0..1 */
  gboolean has_alpha;
} VibranceParams;

/* ---- 色域边界容差（小于它视为在色域内，避免末位抖动）/ gamut tolerance - */
#define GAMUT_EPS 1e-4f

/* ---- LAB 转换（D65，线性输入）/ LAB conversion (D65) ------------------ */

static inline gfloat lab_forward_func (gfloat t)
{
  return (t > 0.008856f) ? cbrtf (t) : (7.787f * t + 16.0f / 116.0f);
}

static inline gfloat lab_inverse_func (gfloat t)
{
  return (t > 0.206893f) ? (t * t * t) : ((t - 16.0f / 116.0f) / 7.787f);
}

static void rgb_to_lab (gfloat r, gfloat g, gfloat b,
                        gfloat *L, gfloat *a, gfloat *b_out)
{
  gfloat x = r * 0.4124564f + g * 0.3575761f + b * 0.1804375f;
  gfloat y = r * 0.2126729f + g * 0.7151522f + b * 0.0721750f;
  gfloat z = r * 0.0193339f + g * 0.1191920f + b * 0.9503041f;

  gfloat fx = lab_forward_func (x / 0.95047f);
  gfloat fy = lab_forward_func (y / 1.00000f);
  gfloat fz = lab_forward_func (z / 1.08883f);

  *L     = 116.0f * fy - 16.0f;
  *a     = 500.0f * (fx - fy);
  *b_out = 200.0f * (fy - fz);
}

static void lab_to_rgb (gfloat L, gfloat a, gfloat b,
                        gfloat *r, gfloat *g, gfloat *b_out)
{
  gfloat fy = (L + 16.0f) / 116.0f;
  gfloat fx = fy + a / 500.0f;
  gfloat fz = fy - b / 200.0f;

  gfloat x = lab_inverse_func (fx) * 0.95047f;
  gfloat y = lab_inverse_func (fy) * 1.00000f;
  gfloat z = lab_inverse_func (fz) * 1.08883f;

  *r     = x *  3.2404542f + y * -1.5371385f + z * -0.4985314f;
  *g     = x * -0.9692660f + y *  1.8760108f + z *  0.0415560f;
  *b_out = x *  0.0556434f + y * -0.2040259f + z *  1.0572252f;
}

/* ---- 蒙版 / masks ------------------------------------------------------ */

static inline gfloat smoothstep01 (gfloat e0, gfloat e1, gfloat x)
{
  gfloat t = (x - e0) / (e1 - e0);

  if (t <= 0.0f) return 0.0f;
  if (t >= 1.0f) return 1.0f;

  return t * t * (3.0f - 2.0f * t);
}

/* 色度蒙版：C* 越大权重越低，读的是「源图」色度，与 Saturation 互不影响。
 * 指数 1.3 让 60 以上的色度掉得比纯双曲线更快，避免高饱和区还在被推
 * Chroma mask: the larger C*, the lower the weight. It reads the SOURCE
 * chroma, so Saturation cannot bias it. The 1.3 exponent makes chroma
 * above 60 fall off faster than a plain hyperbola, so vivid colours stop
 * being pushed. */
static inline gfloat chroma_mask (gfloat chroma, gfloat atten)
{
  return 1.0f / (1.0f + atten * powf (chroma / 50.0f, 1.3f));
}

/* 肤色蒙版：LAB 色相落在 55° 附近（橙/肤色带）且色度处于肤色区间时降权。用
 * smoothstep 做软窗，不会出现一刀切的硬边
 * Skin mask: lower the weight when the LAB hue sits near 55 deg (the
 * orange/skin band) and the chroma falls inside the skin range. smoothstep
 * makes it a soft window without a hard edge. */
static inline gfloat skin_mask (gfloat a, gfloat b, gfloat chroma, gfloat strength)
{
  gfloat hue, dist, w_hue, w_chroma;

  if (strength <= 0.0f || chroma < 8.0f)
    return 1.0f;

  hue = atan2f (b, a) * (180.0f / G_PI);
  if (hue < 0.0f)
    hue += 360.0f;

  dist = fabsf (hue - 55.0f);
  if (dist > 180.0f)
    dist = 360.0f - dist;

  w_hue    = 1.0f - smoothstep01 (18.0f, 36.0f, dist);
  w_chroma = smoothstep01 (8.0f, 18.0f, chroma) *
             (1.0f - smoothstep01 (55.0f, 80.0f, chroma));

  return 1.0f - strength * w_hue * w_chroma;
}

/* ---- 色域收敛：沿固定色相与 L 把色度收进 sRGB / gamut convergence ------ */

static inline gboolean in_gamut (gfloat L, gfloat a, gfloat b)
{
  gfloat r, g, bb;

  lab_to_rgb (L, a, b, &r, &g, &bb);

  return r >= -GAMUT_EPS && r <= 1.0f + GAMUT_EPS &&
         g >= -GAMUT_EPS && g <= 1.0f + GAMUT_EPS &&
         bb >= -GAMUT_EPS && bb <= 1.0f + GAMUT_EPS;
}

/* 返回能让 (L, a*k, b*k) 留在色域内的最大 k ∈ [0,1]。这一步替代硬裁剪：色
 * 相与明度完全不动，只是少加一点饱和度
 * Return the largest k in [0,1] that keeps (L, a*k, b*k) inside the gamut.
 * This replaces hard clipping: hue and lightness stay put, only a little
 * saturation is given up. */
static inline gfloat gamut_limit (gfloat L, gfloat a, gfloat b)
{
  gfloat lo, hi;
  gint   i;

  if (in_gamut (L, a, b))
    return 1.0f;

  lo = 0.0f;
  hi = 1.0f;

  for (i = 0; i < 5; i++)
    {
      gfloat mid = (lo + hi) * 0.5f;

      if (in_gamut (L, a * mid, b * mid))
        lo = mid;
      else
        hi = mid;
    }

  return lo;
}

/* ---- 主处理 / main processing ------------------------------------------ */

static void prepare (GeglOperation *operation)
{
  const Babl *input_fmt = gegl_operation_get_source_format (operation, "input");
  GeglProperties *o = GEGL_PROPERTIES (operation);
  VibranceParams *p;
  const Babl *out_fmt;

  if (!o->user_data)
    o->user_data = g_slice_new0 (VibranceParams);
  p = (VibranceParams *) o->user_data;

  p->vibrance   = o->vibrance / 50.0;
  p->saturation = o->saturation;
  p->atten      = o->attenuation;
  p->skin       = o->skin_protect;

  if (input_fmt && babl_format_has_alpha (input_fmt))
    {
      p->has_alpha = TRUE;
      out_fmt = babl_format_with_space ("RGBA float", input_fmt);
    }
  else
    {
      p->has_alpha = FALSE;
      out_fmt = babl_format_with_space ("RGB float", input_fmt);
    }

  gegl_operation_set_format (operation, "input", out_fmt);
  gegl_operation_set_format (operation, "output", out_fmt);
}

static void finalize (GObject *object)
{
  GeglOperation *op = (void *) object;
  GeglProperties *o = GEGL_PROPERTIES (op);

  if (o->user_data)
    {
      g_slice_free (VibranceParams, o->user_data);
      o->user_data = NULL;
    }

  G_OBJECT_CLASS (gegl_op_parent_class)->finalize (object);
}

static inline void process_pixel (VibranceParams *p, const gfloat *src, gfloat *dst)
{
  gfloat L, a, b, chroma, mask, scale, k;

  rgb_to_lab (src[0], src[1], src[2], &L, &a, &b);

  chroma = sqrtf (a * a + b * b);

  /* 蒙版全部基于源图：色度取 C*，色相取 h_ab
   * all masks come from the source image: chroma from C*, hue from h_ab */
  mask = chroma_mask (chroma, p->atten) * skin_mask (a, b, chroma, p->skin);

  /* 全局饱和度与自然饱和度相乘，两者互不污染
   * global saturation multiplies the natural gain; neither pollutes the
   * other */
  scale = p->saturation * (1.0f + p->vibrance * mask);

  if (scale == 1.0f)
    {
      dst[0] = src[0];
      dst[1] = src[1];
      dst[2] = src[2];
      return;
    }

  /* 沿原色相放大色度，等价于 a *= scale、b *= scale，不需要三角运算
   * grow chroma along the original hue; that equals a *= scale and b *=
   * scale, no trigonometry needed */
  a *= scale;
  b *= scale;

  /* 出界就沿同一条色相射线收回来，不做逐通道裁剪
   * if it leaves the gamut, pull it back along the same hue ray instead of
   * clipping per channel */
  k = gamut_limit (L, a, b);
  if (k < 1.0f)
    {
      a *= k;
      b *= k;
    }

  lab_to_rgb (L, a, b, &dst[0], &dst[1], &dst[2]);

  dst[0] = CLAMP (dst[0], 0.0f, 1.0f);
  dst[1] = CLAMP (dst[1], 0.0f, 1.0f);
  dst[2] = CLAMP (dst[2], 0.0f, 1.0f);
}

static gboolean process (GeglOperation       *op,
                         void                *in_buf,
                         void                *out_buf,
                         glong                samples,
                         const GeglRectangle *roi,
                         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (op);
  VibranceParams *p = (VibranceParams *) o->user_data;
  gfloat *in = in_buf, *out = out_buf;

  g_assert (p != NULL);

  if (p->has_alpha)
    {
      while (samples--)
        {
          process_pixel (p, in, out);
          out[3] = in[3];
          in += 4;
          out += 4;
        }
    }
  else
    {
      while (samples--)
        {
          process_pixel (p, in, out);
          in += 3;
          out += 3;
        }
    }

  return TRUE;
}

static void gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass            *oc = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointFilterClass *cc = GEGL_OPERATION_POINT_FILTER_CLASS (klass);

  oc->prepare = prepare;
  cc->process = process;
  G_OBJECT_CLASS (klass)->finalize = finalize;

  gegl_operation_class_set_keys (oc,
    "name",            "lb:vibrance-hyper",
    "title",           _("Natural Saturation"),
    "categories",      "color",
    "description",     _("Natural saturation in LAB: chroma-driven hyperbola mask plus "
                         "skin-hue protection, gamut-limited so hue and lightness never shift"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Natural Saturation"),
    NULL);
}

#endif
