/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:dust-scratches
 * menu       Dust & Scratches
 * purpose    Photoshop「滤镜 → 杂色 → 蒙尘与划痕」的等价物：把与周围差得太远
 *           的孤立像素（灰尘、划痕、传感器坏点）用邻域中值替换，同时尽量
 *           不动真实的边缘与细节。
 *           Median-of-similar-neighbours — Photoshop's Dust & Scratches.
 * input      任意格式，内部转 R'G'B'A float；alpha 不参与。
 * algorithm  对每个像素逐通道收集半径 r 内、且与中心相差不超过阈值的邻居，
 *           取这些值的中值；一个都不合格时保留原值。
 *           中值而不是均值，是因为中值不会被少数极端值拉动 —— 这正是
 *           「去掉一个亮斑」所要求的；均值只能把它摊成一个更大的灰斑。
 *           阈值的作用是保护边缘：真实边缘的邻居差值大，会被排除在外，
 *           于是中值在原值附近，像素不变。
 *           「减去灰尘」时，阈值 0–255 就是「多大的差才算灰尘」。PS 的默认 0
 *           表示任何差异都算，即纯中值滤波（会糊掉细节，需要配合半径使用）。
 * precision 统一在 float32 里算。中值取自原值，不做任何量化，所以 16 位
 *           缓冲上的细划痕不会被 8 位取整漏掉。
 * type       GeglOperationAreaFilter（向外扩 radius）
 * used-by    GIMP 里作为普通 GEGL 滤镜调用
 * reference  Adobe Photoshop「滤镜 → 杂色 → 蒙尘与划痕」
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_int (radius, _("Radius"), 2)
    description (_("Neighbourhood radius in pixels. 1 is a 3×3 window. Bigger "
                   "values remove bigger specks and also soften more detail."))
    value_range (1, 10)
    ui_range (1, 5)

property_int (threshold, _("Threshold"), 0)
    description (_("Neighbours that differ from the centre pixel by more than "
                   "this many levels (0–255) are ignored, which is what keeps "
                   "real edges intact. Raise it to remove stronger dust, lower "
                   "it to protect fine texture."))
    value_range (0, 255)
    ui_range (0, 128)

#else

#define GEGL_OP_AREA_FILTER
#define GEGL_OP_NAME     lb_dust_scratches
#define GEGL_OP_C_SOURCE dust-scratches.c
#include "gegl-op.h"

#define BAND_ROWS 96

static GeglRectangle
get_bounding_box (GeglOperation *operation)
{
  GeglRectangle *in = gegl_operation_source_get_bounding_box (operation, "input");
  if (in)
    return *in;
  return *GEGL_RECTANGLE (0, 0, 0, 0);
}

/* 就地快速选择：返回 arr[0..n-1] 的中值。n 很小（≤ 441），插入排序更省。 */
static gfloat
median_of (gfloat *a, gint n)
{
  gint i, j;

  if (n <= 0)
    return 0.0f;
  if (n == 1)
    return a[0];

  for (i = 1; i < n; i++)
    {
      gfloat v = a[i];
      for (j = i - 1; j >= 0 && a[j] > v; j--)
        a[j + 1] = a[j];
      a[j + 1] = v;
    }

  return (n & 1) ? a[n / 2] : 0.5f * (a[n / 2 - 1] + a[n / 2]);
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
  gfloat               thr = (gfloat) (o->threshold / 255.0);
  gint                 win = (2 * r + 1) * (2 * r + 1);
  const GeglRectangle *src_bb;
  GeglRectangle        bb;
  gint                 yb;

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
      gfloat       *in, *res, *vals;
      gint          y, x, c;

      if (pw <= 0 || ph <= 0)
        continue;

      in   = g_new (gfloat, (gsize) pw * ph * 4);
      res  = g_new (gfloat, (gsize) w * bh * 4);
      vals = g_new (gfloat, win);

      gegl_buffer_get (input, &prect, 1.0, fmt, in,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (y = 0; y < bh; y++)
        {
          for (x = 0; x < w; x++)
            {
              gint    cx = ox + x, cy = oy + y;
              gfloat *ctr = in + (gsize) (cy * pw + cx) * 4;

              for (c = 0; c < 3; c++)
                {
                  gint   n = 0;
                  gint   dy, dx;
                  gfloat v0 = ctr[c];

                  /* 中心自己不入集合：灰尘之所以是灰尘，就因为它和周围都不一样，
                   * 把它算进去只会让它自己当选。The centre is excluded: a dust
                   * speck differs from every neighbour, so including it would
                   * simply elect itself. */
                  for (dy = -r; dy <= r; dy++)
                    {
                      gint qy = CLAMP (cy + dy, 0, ph - 1);
                      for (dx = -r; dx <= r; dx++)
                        {
                          gint   qx = CLAMP (cx + dx, 0, pw - 1);
                          gfloat v;

                          if (dy == 0 && dx == 0)
                            continue;
                          v = in[(gsize) (qy * pw + qx) * 4 + c];
                          if (fabsf (v - v0) <= thr)
                            vals[n++] = v;
                        }
                    }

                  /* 一个合格的都没有（整块都是异类，典型是硬边正中）：退回整窗中值，
                   * 宁可轻微平滑也不要留下那个孤点。 */
                  if (n == 0)
                    {
                      for (dy = -r; dy <= r; dy++)
                        {
                          gint qy = CLAMP (cy + dy, 0, ph - 1);
                          for (dx = -r; dx <= r; dx++)
                            {
                              gint qx = CLAMP (cx + dx, 0, pw - 1);
                              if (dy == 0 && dx == 0)
                                continue;
                              vals[n++] = in[(gsize) (qy * pw + qx) * 4 + c];
                            }
                        }
                    }

                  res[(gsize) ((gsize) y * w + x) * 4 + c] =
                      (n > 0) ? median_of (vals, n) : v0;
                }

              res[(gsize) ((gsize) y * w + x) * 4 + 3] = ctr[3];
            }
        }

      gegl_buffer_set (output, &outr, 0, fmt, res, GEGL_AUTO_ROWSTRIDE);

      g_free (in);
      g_free (res);
      g_free (vals);
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
    "name",        "lb:dust-scratches",
    "title",       _("Dust & Scratches"),
    "description", _("Replaces a pixel with the median of the neighbours that "
                     "are within the threshold, so isolated dust and scratches "
                     "vanish while real edges — whose neighbours differ too "
                     "much — stay untouched."),
    "categories",  "generic",
    "gimp:menu-path",  "<Image>/SuperMrWang/Noise",
    "gimp:menu-label", _("Dust & Scratches"),
    NULL);
}

#endif
