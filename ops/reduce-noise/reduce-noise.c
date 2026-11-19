/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:reduce-noise
 * menu       Reduce Noise
 * purpose    Photoshop「滤镜 → 杂色 → 减少杂色」的等价物：只平均那些「和中心
 *           像素差不多」的邻居，差得多的（边缘、细节）不参与。结果是平坦区
 *           被磨平、边缘原样保留。
 *           Edge-preserving smoothing — Photoshop's Reduce Noise.
 * input      任意格式，内部转 R'G'B'A float；alpha 不参与。
 * algorithm  sigma 滤波（Lee 1983）：对每个像素取 (2r+1)² 的邻域，用通道差
 *           最大值 d 做权重
 *               w = max(0, 1 − (d/t)²)
 *           然后加权平均。d 超过阈值 t 的邻居权重为 0，所以边缘一侧的像素
 *           不会把另一侧拉过来 —— 这正是它不糊边的原因。
 *             · strength 决定 t（越大抹得越狠）
 *             · detail 把 t 调小，保留更多纹理（PS 的「保留细节」）
 *             · per-channel 关闭时三个通道共用一份权重（由通道差的最大值决定），
 *               色噪点会被一起抹掉而颜色关系不变；打开时每个通道各算各的，
 *               适合处理单色噪点（PS 的「每通道」）
 * precision 统一在 float32 里算，写回时由 GEGL 转回缓冲格式。
 * type       GeglOperationAreaFilter（向外扩 radius）
 * used-by    GIMP 里作为普通 GEGL 滤镜调用
 * reference  Adobe Photoshop「滤镜 → 杂色 → 减少杂色」
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_double (strength, _("Strength"), 50.0)
    description (_("How aggressively neighbours are averaged. Higher values "
                   "smooth more and start to eat texture."))
    value_range (0.0, 100.0)

property_double (detail, _("Preserve detail"), 20.0)
    description (_("Shrinks the averaging threshold so fine texture survives. "
                   "Photoshop's Preserve Details slider."))
    value_range (0.0, 100.0)

property_int (radius, _("Radius"), 2)
    description (_("Neighbourhood radius in pixels. 1 is a 3×3 window; larger "
                   "radii handle coarser grain but cost quadratically more."))
    value_range (1, 10)
    ui_range (1, 5)

property_boolean (per_channel, _("Per channel"), FALSE)
    description (_("Off: the three channels share one weight set, so colour "
                   "speckle disappears without shifting hues. On: each channel "
                   "is filtered on its own, which suits luminance noise only."))

#else

#define GEGL_OP_AREA_FILTER
#define GEGL_OP_NAME     lb_reduce_noise
#define GEGL_OP_C_SOURCE reduce-noise.c
#include "gegl-op.h"

#define BAND_ROWS 96

/* 邻域算子的输出尺寸必须与输入一致：area filter 默认 bbox 会按 pad 外扩，
 * 滤镜不该把画布撑大。The output must stay the size of the input. */
static GeglRectangle
get_bounding_box (GeglOperation *operation)
{
  GeglRectangle *in = gegl_operation_source_get_bounding_box (operation, "input");
  if (in)
    return *in;
  return *GEGL_RECTANGLE (0, 0, 0, 0);
}

static void
prepare (GeglOperation *operation)
{
  GeglProperties          *o  = GEGL_PROPERTIES (operation);
  GeglOperationAreaFilter *af = GEGL_OPERATION_AREA_FILTER (operation);
  gint                     r  = CLAMP (o->radius, 1, 10);

  af->left = af->right = af->top = af->bottom = r;

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
  GeglProperties      *o = GEGL_PROPERTIES (operation);
  const Babl          *fmt = babl_format ("R'G'B'A float");
  gint                 r = CLAMP (o->radius, 1, 10);
  gfloat               t = (gfloat) (0.22 * o->strength / 100.0);
  gboolean             per_channel = o->per_channel;
  const GeglRectangle *src_bb;
  GeglRectangle        bb;
  gint                 yb;

  /* 保留细节 = 收窄阈值 */
  t *= (gfloat) (1.0 - 0.8 * o->detail / 100.0);
  /* strength=0 时 t=0：只有完全相同的邻居参与平均，结果就是原值 */
  if (t < 1e-6f)
    t = 1e-6f;

  src_bb = gegl_operation_source_get_bounding_box (operation, "input");
  bb = src_bb ? *src_bb : *gegl_buffer_get_extent (input);

  for (yb = result->y; yb < result->y + result->height; yb += BAND_ROWS)
    {
      gint          bh = MIN (BAND_ROWS, result->y + result->height - yb);
      gint          w = result->width;
      gint          py0 = MAX (bb.y, yb - r);
      gint          py1 = MIN (bb.y + bb.height, yb + bh + r);
      gint          px0 = MAX (bb.x, result->x - r);
      gint          px1 = MIN (bb.x + bb.width, result->x + result->width + r);
      gint          ph = py1 - py0, pw = px1 - px0;
      gint          ox = result->x - px0, oy = yb - py0;
      GeglRectangle prect = { px0, py0, pw, ph };
      GeglRectangle outr  = { result->x, yb, w, bh };
      gfloat       *in, *res;
      gint          y, x;

      if (pw <= 0 || ph <= 0)
        continue;

      in  = g_new (gfloat, (gsize) pw * ph * 4);
      res = g_new (gfloat, (gsize) w * bh * 4);

      gegl_buffer_get (input, &prect, 1.0, fmt, in,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (y = 0; y < bh; y++)
        {
          for (x = 0; x < w; x++)
            {
              gint    cx = ox + x, cy = oy + y;
              gfloat *ctr = in + (gsize) (cy * pw + cx) * 4;
              gfloat  acc[3] = { 0, 0, 0 };
              gfloat  wsum[3] = { 0, 0, 0 };
              gint    dy, dx, c;

              for (dy = -r; dy <= r; dy++)
                {
                  gint qy = CLAMP (cy + dy, 0, ph - 1);
                  for (dx = -r; dx <= r; dx++)
                    {
                      gint    qx = CLAMP (cx + dx, 0, pw - 1);
                      gfloat *q = in + (gsize) (qy * pw + qx) * 4;

                      if (per_channel)
                        {
                          for (c = 0; c < 3; c++)
                            {
                              gfloat d = fabsf (q[c] - ctr[c]) / t;
                              gfloat ww = 1.0f - d * d;
                              if (ww <= 0.0f)
                                continue;
                              acc[c] += ww * q[c];
                              wsum[c] += ww;
                            }
                        }
                      else
                        {
                          gfloat d = 0.0f, wt;
                          for (c = 0; c < 3; c++)
                            d = MAX (d, fabsf (q[c] - ctr[c]));
                          d /= t;
                          wt = 1.0f - d * d;
                          if (wt <= 0.0f)
                            continue;
                          for (c = 0; c < 3; c++)
                            {
                              acc[c] += wt * q[c];
                              wsum[c] += wt;
                            }
                        }
                    }
                }

              for (c = 0; c < 3; c++)
                res[(gsize) ((gsize) y * w + x) * 4 + c] =
                    (wsum[c] > 0.0f) ? acc[c] / wsum[c] : ctr[c];
              res[(gsize) ((gsize) y * w + x) * 4 + 3] = ctr[3];
            }
        }

      gegl_buffer_set (output, &outr, 0, fmt, res, GEGL_AUTO_ROWSTRIDE);

      g_free (in);
      g_free (res);
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  oclass->prepare          = prepare;
  oclass->get_bounding_box = get_bounding_box;
  fclass->process          = process;

  gegl_operation_class_set_keys (oclass,
    "name",        "lb:reduce-noise",
    "title",       _("Reduce Noise"),
    "description", _("Sigma filter: averages only neighbours close to the "
                     "centre pixel, so flat areas are smoothed and edges are "
                     "left alone. Colour speckle can be removed without "
                     "shifting hues."),
    "categories",  "generic",
    NULL);
}

#endif
