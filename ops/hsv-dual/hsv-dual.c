/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsv-dual
 * menu       HSV Dual Extract
 * purpose    HSV 分量曲线工作流的提取器：把一张图拆成「R = HSV 饱和度、
 *            G = HSV 明度、B = 色相/360」的数据图，一张图同时携带三个分量
 *            Extractor for the HSV component-curve workflow: turns an image
 *            into a data image (R = S, G = V, B = H/360) so one layer carries
 *            all three components.
 * input      R'G'B'A float（滤镜栈的编码域缓冲，与 component-extract 同域）
 * output     R'G'B'A float，数值是数据不是颜色；alpha 恒为 1（分量层必须
 *            不透明，透明度由插件挂在组上的蒙版负责）
 * algorithm  RGB→HSV 由 babl 完成（"HSVA float"），与 GIMP 的 HSV 分量模式
 *            同一口径；babl 的输出本来就是 0…1 归一化（h/360、s、v）。
 *            本算子只把通道重排成 R=S、G=V、B=H，好让三条曲线分别挂在
 *           红、绿、蓝通道上。
 *            babl does the conversion and its output is already 0..1; this op
 *            only repacks the channels so each component gets its own curve.
 * type       GeglOperationFilter（逐像素，无 aux）
 * note       为什么三个分量都在一张图里：HSV 的 H、S、V 互相耦合（改 V 会让
 *            S 的绝对值变化，改 S 又改变 V 与 S 的比例），要用一条曲线精确
 *           改其中一个分量、其余不动，就必须让合成器同时读到三者。分开成
 *           三张图只能靠分量混合模式逐层叠，那正是旧版插件的做法——能工作，
 *           但需要三层和三次编码，且 8 位上逐层量化。
 *            H/S/V are coupled, so the composer needs all three at once.
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
#define GEGL_OP_NAME     lb_hsv_dual
#define GEGL_OP_C_SOURCE hsv-dual.c
#include "gegl-op.h"

static const Babl *rgb_to_hsv_fish (void);

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
  const Babl *fish  = rgb_to_hsv_fish ();
  const gint  width = roi->width;
  gfloat     *in_line, *hsv_line;
  gint        y;

  if (width <= 0 || roi->height <= 0)
    return TRUE;

  in_line  = g_new (gfloat, (gsize) width * 4);
  hsv_line = g_new (gfloat, (gsize) width * 4);

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, width, 1 };
      gint          x;

      gegl_buffer_get (in_buf, &row, 1.0, fin, in_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);
      babl_process (fish, in_line, hsv_line, width);

      for (x = 0; x < width; x++)
        {
          /* babl 的 "HSVA float" 已经是 0…1 归一化（h/360、s、v），直接搬。
           * babl's HSVA float is already normalised to 0..1. */
          in_line[x * 4 + 0] = clamp01 (hsv_line[x * 4 + 1]);  /* S */
          in_line[x * 4 + 1] = clamp01 (hsv_line[x * 4 + 2]);  /* V */
          in_line[x * 4 + 2] = clamp01 (hsv_line[x * 4 + 0]);  /* H/360 */
          in_line[x * 4 + 3] = 1.0f;              /* 分量层一律不透明 */
        }

      gegl_buffer_set (out_buf, &row, 0, fin, in_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (in_line);
  g_free (hsv_line);
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
    "name",            "lb:hsv-dual",
    "title",           _("HSV Dual Extract"),
    "categories",      "color",
    "description",     _("Pack HSV saturation, value and hue into one "
                         "data image (R=S, G=V, B=H/360) for curve editing"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Component",
    "gimp:menu-label", _("HSV Dual Extract"),
    NULL);
}

/* babl fish 只建一次；GEGL 的 process 是多线程的，用 GOnce 保护。
 * Built once: GEGL calls process from worker threads. */
static gsize        fish_once = 0;
static const Babl  *fish_rgb2hsv = NULL;

static void
make_fish (void)
{
  fish_rgb2hsv = babl_fish ("R'G'B'A float", "HSVA float");
}

static const Babl *
rgb_to_hsv_fish (void)
{
  if (g_once_init_enter (&fish_once))
    {
      make_fish ();
      g_once_init_leave (&fish_once, 1);
    }
  return fish_rgb2hsv;
}

#endif
