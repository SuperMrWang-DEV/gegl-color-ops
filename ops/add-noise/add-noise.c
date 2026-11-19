/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:add-noise
 * menu       Add Noise
 * purpose    Photoshop「滤镜 → 杂色 → 添加杂色」的等价物：给每个像素叠一层
 *           随机扰动。加颗粒、做旧、掩盖色带、给渐变加「胶片感」都是它。
 *           Adds random noise per pixel — Photoshop's Add Noise.
 * input      任意格式，内部转 R'G'B'A float；alpha 不参与（叠噪点不该改动
 *           图层透明度，PS 同样不碰）。
 * algorithm  按「行」播种：第 y 行的随机数种子由 seed 与 y 混合得到，所以
 *           分带处理不影响结果 —— 同一张图不管一次算完还是切 8 带算，
 *           逐位相同。这一点对可复现很重要：PS 每次应用都换随机数，
 *           想复现只能存图层再画。
 *             · gaussian：Box–Muller，σ = 25% × amount/100
 *             · uniform ：±50% × amount/100 的均匀分布
 *           单调色时三个通道共用同一个扰动，得到灰度噪点（PS 的「单色」）。
 * precision 统一在 float32 里算。8/16 位缓冲的源会把结果夹回 [0,1]，
 *           浮点缓冲不夹上界，高光叠噪点不会平掉。
 * type       GeglOperationFilter（逐像素，不需要邻域）
 * used-by    GIMP 里作为普通 GEGL 滤镜调用
 * reference  Adobe Photoshop「滤镜 → 杂色 → 添加杂色」
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

enum_start (lb_noise_dist)
  enum_value (LB_NOISE_GAUSSIAN, "gaussian", "Gaussian")
  enum_value (LB_NOISE_UNIFORM,  "uniform",  "Uniform")
enum_end (LbNoiseDist)

property_double (amount, _("Amount"), 10.0)
    description (_("Noise strength in percent. 100% means a standard deviation "
                   "of a quarter of the full range for Gaussian noise, or "
                   "±half the range for uniform noise."))
    value_range (0.0, 100.0)
    ui_range (0.0, 50.0)

property_enum (distribution, _("Distribution"), LbNoiseDist, lb_noise_dist,
               LB_NOISE_GAUSSIAN)
    description (_("Gaussian looks like film grain and sensor noise; uniform "
                   "looks like digital dithering."))

property_boolean (monochrome, _("Monochromatic"), FALSE)
    description (_("Use one value for all three channels, giving grey grain "
                   "instead of coloured speckle. Photoshop's Monochromatic "
                   "checkbox."))

property_int (seed, _("Seed"), 1)
    description (_("Same seed and same image always give the same noise, so a "
                   "look can be reproduced exactly."))
    value_range (0, 999999)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_add_noise
#define GEGL_OP_C_SOURCE add-noise.c
#include "gegl-op.h"

#define BAND_ROWS 256

/* Box–Muller，均值 0、方差 1 */
static gfloat
gauss_rand (GRand *r)
{
  gdouble u1 = g_rand_double_range (r, 1e-12, 1.0);
  gdouble u2 = g_rand_double (r);
  return (gfloat) (sqrt (-2.0 * log (u1)) * cos (2.0 * G_PI * u2));
}

/* 每行独立播种：分带不改变结果 */
static GRand *
row_rand (gint seed, gint y)
{
  guint32 h = (guint32) seed * 2654435761u ^ (guint32) (y + 1) * 40503u;
  return g_rand_new_with_seed (h ? h : 1u);
}

static void
prepare (GeglOperation *operation)
{
  gegl_operation_set_format (operation, "input", babl_format ("R'G'B'A float"));
  gegl_operation_set_format (operation, "output", babl_format ("R'G'B'A float"));
}

static gboolean
process (GeglOperation       *operation,
         GeglBuffer          *input,
         GeglBuffer          *output,
         const GeglRectangle *result,
         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (operation);
  const Babl     *fmt = babl_format ("R'G'B'A float");
  const Babl     *src_fmt = gegl_operation_get_source_format (operation, "input");
  const gchar    *src_name = src_fmt ? babl_get_name (src_fmt) : "";
  gboolean        clamp_hi = (g_strrstr (src_name, "u8") != NULL ||
                              g_strrstr (src_name, "u16") != NULL);
  gboolean        gaussian = (o->distribution == LB_NOISE_GAUSSIAN);
  gfloat          scale = (gfloat) (o->amount / 100.0);
  gint            yb;

  for (yb = result->y; yb < result->y + result->height; yb += BAND_ROWS)
    {
      gint          bh = MIN (BAND_ROWS, result->y + result->height - yb);
      gint          w = result->width;
      GeglRectangle outr = { result->x, yb, w, bh };
      gfloat       *buf = g_new (gfloat, (gsize) w * bh * 4);
      gint          y, x, c;

      gegl_buffer_get (input, &outr, 1.0, fmt, buf,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (y = 0; y < bh; y++)
        {
          GRand   *r = row_rand (o->seed, yb + y);
          gfloat  *row = buf + (gsize) y * w * 4;

          for (x = 0; x < w; x++)
            {
              gfloat n[3];
              gint   k;

              if (o->monochrome)
                {
                  gfloat v = gaussian ? gauss_rand (r) * 0.25f * scale
                                      : (g_rand_double_range (r, -1.0, 1.0) * 0.5f
                                         * scale);
                  n[0] = n[1] = n[2] = v;
                }
              else
                {
                  for (k = 0; k < 3; k++)
                    n[k] = gaussian ? gauss_rand (r) * 0.25f * scale
                                    : (g_rand_double_range (r, -1.0, 1.0) * 0.5f
                                       * scale);
                }

              for (c = 0; c < 3; c++)
                {
                  gfloat v = row[x * 4 + c] + n[c];
                  if (v < 0.0f) v = 0.0f;
                  if (clamp_hi && v > 1.0f) v = 1.0f;
                  row[x * 4 + c] = v;
                }
            }

          g_rand_free (r);
        }

      gegl_buffer_set (output, &outr, 0, fmt, buf, GEGL_AUTO_ROWSTRIDE);
      g_free (buf);
    }

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
    "name",        "lb:add-noise",
    "title",       _("Add Noise"),
    "description", _("Adds Gaussian or uniform noise, monochromatic or per "
                     "channel. The seed makes the grain reproducible."),
    "categories",  "generic",
    "gimp:menu-path",  "<Image>/SuperMrWang/Noise",
    "gimp:menu-label", _("Add Noise"),
    NULL);
}

#endif
