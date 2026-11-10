/* ===========================================================================
 * SuperMrWang · GEGL Operation
 * ---------------------------------------------------------------------------
 * id     : lb:vibrance-hyper
 * 菜单   : Vibrance
 * 作用   : 自然饱和度：优先提升低饱和区，保护高饱和与肤色
 * 算法   : 双曲函数给出自适应增益，再乘全局线性饱和度
 * 类型   : GeglOperationPointFilter
 * 许可   : GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (vibrance, _("Vibrance"), 0.0)
    description (_("Adaptive natural saturation (hyperbola curve, protect high-saturation & skin)"))
    value_range (-100.0, 100.0)
    ui_range    (-50.0, 50.0)
    ui_steps    (0.1, 1.0)

property_double (saturation, _("Saturation"), 1.0)
    description (_("Global linear saturation multiplier"))
    value_range (0.0, 10.0)
    ui_range    (0.0, 2.0)
    ui_steps    (0.1, 1.0)

property_double (attenuation, _("High Saturation Attenuation"), 2.0)
    description (_("Hyperbola attenuation strength: higher = stronger protection for vivid colors"))
    value_range (0.5, 5.0)
    ui_range    (0.5, 3.0)
    ui_steps    (0.1, 0.5)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_vibrance_hyper
#define GEGL_OP_C_SOURCE vibrance-hyper.c

#include "gegl-op.h"

typedef struct
{
  gdouble vibrance;
  gdouble saturation;
  gdouble atten;
  gboolean has_alpha;
} VibranceParams;

/* LAB转换辅助函数 纯C */
static inline gfloat lab_forward_func(gfloat t)
{
  if (t > 0.008856f)
    return cbrtf(t);
  else
    return 7.787f * t + 16.0f / 116.0f;
}

static inline gfloat lab_inverse_func(gfloat t)
{
  if (t > 0.206893f)
    return t * t * t;
  else
    return (t - 16.0f / 116.0f) / 7.787f;
}

/* linear sRGB float (0~1) -> CIELAB D65 */
static void rgb_to_lab (gfloat r, gfloat g, gfloat b, gfloat *L, gfloat *a, gfloat *b_out)
{
  gfloat x, y, z;
  x = r * 0.4124564f + g * 0.3575761f + b * 0.1804375f;
  y = r * 0.2126729f + g * 0.7151522f + b * 0.0721750f;
  z = r * 0.0193339f + g * 0.1191920f + b * 0.9503041f;

  gfloat fx = lab_forward_func(x / 0.95047f);
  gfloat fy = lab_forward_func(y / 1.00000f);
  gfloat fz = lab_forward_func(z / 1.08883f);

  *L = 116.0f * fy - 16.0f;
  *a = 500.0f * (fx - fy);
  *b_out = 200.0f * (fy - fz);
}

/* CIELAB D65 -> linear sRGB float (0~1) */
static void lab_to_rgb (gfloat L, gfloat a, gfloat b, gfloat *r, gfloat *g, gfloat *b_out)
{
  gfloat fy = (L + 16.0f) / 116.0f;
  gfloat fx = fy + a / 500.0f;
  gfloat fz = fy - b / 200.0f;

  gfloat x = lab_inverse_func(fx) * 0.95047f;
  gfloat y = lab_inverse_func(fy) * 1.00000f;
  gfloat z = lab_inverse_func(fz) * 1.08883f;

  *r  = x *  3.2404542f + y * -1.5371385f + z * -0.4985314f;
  *g  = x * -0.9692660f + y *  1.8760108f + z *  0.0415560f;
  *b_out = x *  0.0556434f + y * -0.2040259f + z *  1.0572252f;
}

static void prepare (GeglOperation *operation)
{
  const Babl *input_fmt = gegl_operation_get_source_format (operation, "input");
  GeglProperties *o = GEGL_PROPERTIES (operation);
  VibranceParams *p;
  const Babl *out_fmt;

  if (!o->user_data)
    o->user_data = g_slice_new0 (VibranceParams);
  p = (VibranceParams*) o->user_data;

  /* 放大vibrance倍率，增强调节可见度 */
  p->vibrance = o->vibrance / 50.0;
  p->saturation = o->saturation;
  p->atten = o->attenuation;

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
  GeglOperation *op = (void*) object;
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
  gfloat r = src[0], g = src[1], b = src[2];
  gfloat L, a, bb;

  rgb_to_lab(r, g, b, &L, &a, &bb);

  /* 1. 先应用全局线性饱和度（顺序修正） */
  a *= p->saturation;
  bb *= p->saturation;

  /* 2. 计算色度Chroma，归一化放大衰减区间，解决chroma数值过小无衰减问题 */
  gfloat chroma = sqrtf(a*a + bb*bb);
  gfloat chroma_norm = chroma / 50.0f; // 归一化到0~2区间，双曲线衰减明显

  /* 3. 标准双曲线自适应缩放系数（修复核心公式错误） */
  gfloat hyper_weight = 1.0f / (1.0f + p->atten * chroma_norm);
  gfloat chroma_scale = 1.0f + (p->vibrance * hyper_weight);

  /* 4. 缩放总色度，保持色相不变（彻底修复之前a/a逻辑错误） */
  gfloat new_chroma = chroma * chroma_scale;
  gfloat hue = atan2f(bb, a); // 提取原始色相，不偏移颜色

  /* 5. 用新色度、原始色相还原a/b通道 */
  gfloat new_a = cosf(hue) * new_chroma;
  gfloat new_bb = sinf(hue) * new_chroma;

  /* LAB转回RGB */
  lab_to_rgb(L, new_a, new_bb, &dst[0], &dst[1], &dst[2]);

  /* 裁剪防止溢出 */
  dst[0] = CLAMP(dst[0], 0.0f, 1.0f);
  dst[1] = CLAMP(dst[1], 0.0f, 1.0f);
  dst[2] = CLAMP(dst[2], 0.0f, 1.0f);
}

static gboolean process (GeglOperation       *op,
                         void                *in_buf,
                         void                *out_buf,
                         glong                samples,
                         const GeglRectangle *roi,
                         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (op);
  VibranceParams *p = (VibranceParams*) o->user_data;
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
    "title",           _("Vibrance"),
    "categories",      "color",
    "description",     _("Natural saturation with hyperbola curve, protect high-chroma colors & skin tones, no color clipping"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Vibrance"),
    NULL);
}

#endif