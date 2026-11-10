/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lab-levels
 * menu       LAB Levels
 * purpose    LAB 三通道各自设输入 / 输出黑白场与伽马
 *            Independent input/output black-white points and gamma for each
 *            LAB channel.
 * algorithm  L/a/b 分别做 levels 映射后合并，a/b 以 0.5 为中性轴
 *            Levels are applied per L/a/b channel and then merged; a and b
 *            use 0.5 as the neutral axis.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (L_in_black, _("L 输入黑场"), 0.0)
    description (_("明度通道 输入黑场"))
    value_range (0.0, 95.0)
    ui_range (0.0, 95.0)

property_double (L_in_white, _("L 输入白场"), 100.0)
    description (_("明度通道 输入白场"))
    value_range (5.0, 100.0)
    ui_range (5.0, 100.0)

property_double (L_gamma, _("L Gamma"), 1.0)
    description (_("明度通道 伽马 / 中间调"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (L_out_black, _("L 输出下限"), 0.0)
    description (_("明度通道输出黑场"))
    value_range (0.0, 100.0)

property_double (L_out_white, _("L 输出上限"), 100.0)
    description (_("明度通道输出白场"))
    value_range (0.0, 100.0)

property_double (a_in_black, _("a 输入黑场"), -128.0)
    description (_("a通道(红‑绿轴)输入黑场"))
    value_range (-128.0, 120.0)

property_double (a_in_white, _("a 输入白场"), 127.0)
    description (_("a通道(红‑绿轴)输入白场"))
    value_range (-120.0, 127.0)

property_double (a_gamma, _("a Gamma"), 1.0)
    description (_("a通道伽马，控制色彩中间调倾向"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (a_out_black, _("a 输出下限"), -128.0)
    description (_("a通道输出下限，限制最大绿色"))
    value_range (-128.0, 127.0)

property_double (a_out_white, _("a 输出上限"), 127.0)
    description (_("a通道输出上限，限制最大洋红"))
    value_range (-128.0, 127.0)

property_double (b_in_black, _("b 输入黑场"), -128.0)
    description (_("b通道(黄‑蓝轴)输入黑场"))
    value_range (-128.0, 120.0)

property_double (b_in_white, _("b 输入白场"), 127.0)
    description (_("b通道(黄‑蓝轴)输入白场"))
    value_range (-120.0, 127.0)

property_double (b_gamma, _("b Gamma"), 1.0)
    description (_("b通道伽马，控制色彩中间调倾向"))
    value_range (0.10, 4.0)
    ui_range (0.20, 2.5)

property_double (b_out_black, _("b 输出下限"), -128.0)
    description (_("b通道输出下限，限制最大蓝色"))
    value_range (-128.0, 127.0)

property_double (b_out_white, _("b 输出上限"), 127.0)
    description (_("b通道输出上限，限制最大黄色"))
    value_range (-128.0, 127.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_lab_levels
#define GEGL_OP_C_SOURCE lab-levels.c
#include "gegl-op.h"

#define FLOAT_EPS    1e-12f

static inline gfloat sanitize_f(gfloat v)
{
  if (!isfinite(v))
    return 0.0f;
  return v;
}

static inline gfloat lab_forward_func(gfloat t)
{
  t = MAX(t, FLOAT_EPS);
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

static void rgb_to_lab (gfloat r, gfloat g, gfloat b, gfloat *L, gfloat *a, gfloat *b_out)
{
  r = sanitize_f(r);
  g = sanitize_f(g);
  b = sanitize_f(b);

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

static inline gfloat levels_channel(gfloat val,
                                    gfloat in_black,
                                    gfloat in_white,
                                    gfloat gamma,
                                    gfloat out_black,
                                    gfloat out_white)
{
    val = CLAMP(val, in_black, in_white);

    if(fabsf(in_white - in_black) < FLOAT_EPS)
        return val;

    gfloat norm = (val - in_black) / (in_white - in_black);
    norm = powf(MAX(norm, FLOAT_EPS), 1.0f / gamma);
    val = out_black + norm * (out_white - out_black);

    val = CLAMP(val, out_black, out_white);
    return val;
}

static void
prepare(GeglOperation *op)
{
  /* 固定格式，与 hsl-seven 统一，不再动态继承输入色彩空间
   * Fixed format like hsl-seven: no dynamic colour-space inheritance. */
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

  /* 参数在 process 内部读取，彻底消除了 user_data 的并发竞争
   * Parameters are read inside process(), so the user_data race is gone. */
  gdouble L_in_black, L_in_white, L_gamma, L_out_black, L_out_white;
  gdouble a_in_black, a_in_white, a_gamma, a_out_black, a_out_white;
  gdouble b_in_black, b_in_white, b_gamma, b_out_black, b_out_white;

  g_object_get(G_OBJECT(op),
    "L-in-black", &L_in_black,
    "L-in-white", &L_in_white,
    "L-gamma",    &L_gamma,
    "L-out-black",&L_out_black,
    "L-out-white",&L_out_white,

    "a-in-black", &a_in_black,
    "a-in-white", &a_in_white,
    "a-gamma",    &a_gamma,
    "a-out-black",&a_out_black,
    "a-out-white",&a_out_white,

    "b-in-black", &b_in_black,
    "b-in-white", &b_in_white,
    "b-gamma",    &b_gamma,
    "b-out-black",&b_out_black,
    "b-out-white",&b_out_white,
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

      gfloat L, ach, bb;
      rgb_to_lab(r,g,b,&L,&ach,&bb);

      L  = levels_channel(L,
        (gfloat)L_in_black,(gfloat)L_in_white,(gfloat)L_gamma,(gfloat)L_out_black,(gfloat)L_out_white);

      ach  = levels_channel(ach,
        (gfloat)a_in_black,(gfloat)a_in_white,(gfloat)a_gamma,(gfloat)a_out_black,(gfloat)a_out_white);

      bb = levels_channel(bb,
        (gfloat)b_in_black,(gfloat)b_in_white,(gfloat)b_gamma,(gfloat)b_out_black,(gfloat)b_out_white);

      gfloat nr, ng, nb;
      lab_to_rgb(L,ach,bb,&nr,&ng,&nb);

      out_line[px + 0] = CLAMP(sanitize_f(nr), 0.0f, 1.0f);
      out_line[px + 1] = CLAMP(sanitize_f(ng), 0.0f, 1.0f);
      out_line[px + 2] = CLAMP(sanitize_f(nb), 0.0f, 1.0f);
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
    "name",            "lb:lab-levels",
    "title",           _("LAB Levels"),
    "categories",      "color",
    "description",     _("Independent levels adjustment for L,a,b channel, adjust tone and color separately"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("LAB Levels"),
    NULL);
}

#endif