/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsl-dual
 * menu       HSL Dual Extract
 * purpose    HSL 分量曲线工作流的提取器：把一张图拆成「R = HSL 饱和度、
 *            G = HSL 明度、B = 色相/360」的数据图，一张图同时携带三个分量
 *            Extractor for the HSL component-curve workflow: turns an image
 *            into a data image with R = HSL saturation, G = HSL lightness,
 *            B = hue/360, so one image carries all three components.
 * input      R'G'B'A float（滤镜栈的编码域缓冲，与 component-extract 同域）
 * output     R'G'B'A float，数值是数据不是颜色；alpha 恒为 1（分量层必须
 *            不透明，透明度由插件挂在组上的蒙版负责）
 * algorithm  RGB→HSL 由 babl 完成（"HSLA float"），与 GIMP 的分解 /
 *            component-extract 同一口径；babl 的输出本来就是 0…1 归一化
 *            （h/360、s、l）。本算子只把通道重排成 R=S、G=L、B=H，好让曲线
 *            分别挂在红、绿两个通道上。
 *            babl does the conversion and its output is already 0..1; this op
 *            only repacks the channels so each component gets its own curve.
 * type       GeglOperationFilter（逐像素，无 aux）
 * note       为什么 S 和 L 要挤进同一张图：HSL 的 S 与 L 彼此耦合
 *            （C = (1-|2L-1|)·S、V = L + C/2），要把它们精确换回 HSV 的
 *            S/V，编码器必须同时读到两者。分成两张图就做不到。
 *            S and L are coupled, so the encoder needs both at once.
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* 无可调参数：本算子只做重排，所有调整都在后续的曲线里。
 * No parameters: the adjustment happens in the curves that follow. */

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_hsl_dual
#define GEGL_OP_C_SOURCE hsl-dual.c
#include "gegl-op.h"

static const Babl *rgb_to_hsl_fish (void);

/* 0…1 夹紧；NaN 归 0（无色像素的色相在 babl 侧可能无定义）。
 * Clamp to 0..1 and fold NaN to 0 (hue is undefined for greys). */
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
  const Babl *fish  = rgb_to_hsl_fish ();
  const gint  width = roi->width;
  gfloat     *in_line, *hsl_line;
  gint        y;

  if (width <= 0 || roi->height <= 0)
    return TRUE;

  in_line  = g_new (gfloat, (gsize) width * 4);
  hsl_line = g_new (gfloat, (gsize) width * 4);

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, width, 1 };
      gint          x;

      gegl_buffer_get (in_buf, &row, 1.0, fin, in_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);
      babl_process (fish, in_line, hsl_line, width);

      for (x = 0; x < width; x++)
        {
          /* babl 的 "HSLA float" 已经是 0…1 归一化（h/360、s、l 各除以
           * 自己的满量程），所以这里不需要再缩放，直接搬。
           * babl's HSLA float is already normalised to 0..1. */
          in_line[x * 4 + 0] = clamp01 (hsl_line[x * 4 + 1]);  /* S */
          in_line[x * 4 + 1] = clamp01 (hsl_line[x * 4 + 2]);  /* L */
          in_line[x * 4 + 2] = clamp01 (hsl_line[x * 4 + 0]);  /* H/360 */
          in_line[x * 4 + 3] = 1.0f;              /* 分量层一律不透明 */
        }

      gegl_buffer_set (out_buf, &row, 0, fin, in_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (in_line);
  g_free (hsl_line);
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
    "name",            "lb:hsl-dual",
    "title",           _("HSL Dual Extract"),
    "categories",      "color",
    "description",     _("Pack HSL saturation, lightness and hue into one "
                         "data image (R=S, G=L, B=H/360) for curve editing"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Component",
    "gimp:menu-label", _("HSL Dual Extract"),
    NULL);
}

/* babl fish 只建一次；GEGL 的 process 是多线程的，用 GOnce 保护。
 * Built once: GEGL calls process from worker threads. */
static gsize        fish_once = 0;
static const Babl  *fish_rgb2hsl = NULL;

static void
make_fish (void)
{
  fish_rgb2hsl = babl_fish ("R'G'B'A float", "HSLA float");
}

static const Babl *
rgb_to_hsl_fish (void)
{
  if (g_once_init_enter (&fish_once))
    {
      make_fish ();
      g_once_init_leave (&fish_once, 1);
    }
  return fish_rgb2hsl;
}

#endif
