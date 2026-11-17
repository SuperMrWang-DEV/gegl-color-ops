/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lch-dual
 * menu       LCh Dual Extract
 * purpose    LCh 分量曲线工作流的提取器：把一张图拆成「R = 明度 L*、
 *            G = 彩度 C*、B = 色相/360」的数据图，一张图同时携带三个分量
 *            Extractor for the LCh component-curve workflow: turns an image
 *            into a data image (R = L/100, G = C/140, B = h/360) so one layer
 *            carries all three components.
 * input      R'G'B'A float（滤镜栈的编码域缓冲，与 component-extract 同域）
 * output     R'G'B'A float，数值是数据不是颜色；alpha 恒为 1（分量层必须
 *            不透明，透明度由插件挂在组上的蒙版负责）
 * algorithm  RGB→LCh 由 babl 完成（"CIE LCH(ab) alpha float"，D50，与
 *            lb:lch-levels 同一口径）；本算子只把量程缩到 0…1：
 *              L*  0…100  → /100
 *              C*  0…140  → /140（sRGB 全色域最大值约 133.8，留一点余量）
 *              h   0…360° → /360
 *            babl does the conversion (D50, same baseline as lb:lch-levels);
 *            this op only rescales to 0..1.
 * type       GeglOperationFilter（逐像素，无 aux）
 * note       为什么是极坐标而不是 Lab 的 a/b：a、b 是直角坐标，一条一维通道
 *            曲线改 a 会连带改彩度与色相。要「只动彩度」或「只动色相」，必须
 *            先换成极坐标 (C, h)，改完再转回去——这正是本算子存在的理由。
 *            a/b are Cartesian: one 1-D curve on a shifts both C and h.
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

/* 数据图里 1.0 代表的彩度。sRGB 全色域的最饱和点是纯蓝，C*≈133.8；
 * 取 140 让整圈都能装进来，8 位图上 1 码≈0.55 C*，往返量化误差仍在 0.5 码内。
 * 1.0 in the data image stands for this much chroma. */
#define LB_LCH_C_SPAN   140.0f

#ifdef GEGL_PROPERTIES

/* 无可调参数：本算子只做重排，所有调整都在后续的曲线里。
 * No parameters: the adjustment happens in the curves that follow. */

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_lch_dual
#define GEGL_OP_C_SOURCE lch-dual.c
#include "gegl-op.h"

static const Babl *rgb_to_lch_fish (void);

/* 0…1 夹紧；NaN 归 0（中性灰的色相在 babl 侧可能无定义）。
 * Clamp to 0..1 and fold NaN to 0 (hue is undefined for neutrals). */
static inline gfloat
clamp01 (gfloat v)
{
  if (!isfinite (v))
    return 0.0f;
  return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v);
}

static void
prepare (GeglOperation *op)
{
  gegl_operation_set_format (op, "input",  babl_format ("R'G'B'A float"));
  gegl_operation_set_format (op, "output", babl_format ("R'G'B'A float"));
}

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *in_buf,
         GeglBuffer          *out_buf,
         const GeglRectangle *roi,
         gint                 level)
{
  const Babl *fin   = babl_format ("R'G'B'A float");
  const Babl *fish  = rgb_to_lch_fish ();
  const gint  width = roi->width;
  gfloat     *in_line, *lch_line;
  gint        y;

  if (width <= 0 || roi->height <= 0)
    return TRUE;

  in_line  = g_new (gfloat, (gsize) width * 4);
  lch_line = g_new (gfloat, (gsize) width * 4);

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, width, 1 };
      gint          x;

      gegl_buffer_get (in_buf, &row, 1.0, fin, in_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);
      babl_process (fish, in_line, lch_line, width);

      for (x = 0; x < width; x++)
        {
          /* babl 的 CIE LCH(ab) 是物理量：L 0…100、C 0…~134、h 0…360°。
           * babl's LCH is in physical units, so rescale each to 0..1. */
          in_line[x * 4 + 0] = clamp01 (lch_line[x * 4 + 0] / 100.0f);   /* L */
          in_line[x * 4 + 1] = clamp01 (lch_line[x * 4 + 1] / LB_LCH_C_SPAN);
          in_line[x * 4 + 2] = clamp01 (lch_line[x * 4 + 2] / 360.0f);   /* h */
          in_line[x * 4 + 3] = 1.0f;              /* 分量层一律不透明 */
        }

      gegl_buffer_set (out_buf, &row, 0, fin, in_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (in_line);
  g_free (lch_line);
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
    "name",            "lb:lch-dual",
    "title",           _("LCh Dual Extract"),
    "categories",      "color",
    "description",     _("Pack LCh lightness, chroma and hue into one "
                         "data image (R=L/100, G=C/140, B=h/360)"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Component",
    "gimp:menu-label", _("LCh Dual Extract"),
    NULL);
}

/* babl fish 只建一次；GEGL 的 process 是多线程的，用 GOnce 保护。
 * Built once: GEGL calls process from worker threads. */
static gsize        fish_once = 0;
static const Babl  *fish_rgb2lch = NULL;

static void
make_fish (void)
{
  fish_rgb2lch = babl_fish ("R'G'B'A float", "CIE LCH(ab) alpha float");
}

static const Babl *
rgb_to_lch_fish (void)
{
  if (g_once_init_enter (&fish_once))
    {
      make_fish ();
      g_once_init_leave (&fish_once, 1);
    }
  return fish_rgb2lch;
}

#endif
