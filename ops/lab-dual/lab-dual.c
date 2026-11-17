/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lab-dual
 * menu       Lab Dual Extract
 * purpose    Lab 分量曲线工作流的提取器：把一张图拆成「R = a、G = b、
 *            B = L」的数据图，一张图同时携带三个分量
 *            Extractor for the Lab component-curve workflow: turns an image
 *            into a data image with R = a, G = b, B = L.
 * input      R'G'B'A float（滤镜栈的编码域缓冲，与 component-extract 同域）
 * output     R'G'B'A float，数值是数据不是颜色；alpha 恒为 1（分量层必须
 *            不透明，透明度由插件挂在组上的蒙版负责）
 * algorithm  RGB→Lab 由 babl 完成（"CIE Lab float"，与 GIMP 的 Lab 空间同一
 *            口径：D50 白点）。babl 的 Lab 是 a/b ∈ [−128,127]、L ∈ [0,100]，
 *            这里线性搬到 0…1：a' = (a+128)/255，b' = (b+128)/255，L' = L/100。
 *            babl does the conversion (D50, same as GIMP's Lab space); this op
 *            only rescales the three channels into 0..1 for curve editing.
 * type       GeglOperationFilter（逐像素，无 aux）
 * note       为什么 a 和 b 要挤进同一张图：Lab 的 a/b 是直角坐标，GIMP 没有
 *            「a」「b」分量混合模式可用——LCh 的 Chroma/Hue 是 a/b 的极坐标
 *            形式，改色相是绕圈平移色度矢量，改不了单独一个 a。要把 a、b
 *            各自独立地映射，编码器必须同时读到两者，再一起换算回颜色。
 *            a and b are cartesian; LCh's chroma/hue are their polar form, so
 *            no single-component mode can move a or b alone.
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* 无可调参数：本算子只做重排与归一化，所有调整都在后续的曲线里。
 * No parameters: the adjustment happens in the curves that follow. */

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_lab_dual
#define GEGL_OP_C_SOURCE lab-dual.c
#include "gegl-op.h"

/* babl 的 Lab 量程：a/b ∈ [−128,127]（跨度 255），L ∈ [0,100]。
 * babl's Lab ranges: a/b span 255 starting at -128, L spans 0..100. */
#define LB_LAB_A_MIN   (-128.0f)
#define LB_LAB_AB_SPAN  255.0f
#define LB_LAB_L_SPAN   100.0f

static const Babl *rgb_to_lab_fish (void);

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
  const Babl *flab  = babl_format ("CIE Lab float");
  const Babl *fish  = rgb_to_lab_fish ();
  const gint  width = roi->width;
  gfloat     *in_line, *lab_line;
  gint        y;

  if (width <= 0 || roi->height <= 0)
    return TRUE;

  in_line  = g_new (gfloat, (gsize) width * 4);
  lab_line = g_new (gfloat, (gsize) width * 3);   /* Lab 无 alpha */

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, width, 1 };
      gint          x;

      gegl_buffer_get (in_buf, &row, 1.0, fin, in_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);
      babl_process (fish, in_line, lab_line, width);

      for (x = 0; x < width; x++)
        {
          const gfloat L = lab_line[x * 3 + 0];
          const gfloat a = lab_line[x * 3 + 1];
          const gfloat b = lab_line[x * 3 + 2];

          /* a/b 从 [−128,127] 搬到 0…1（中性灰 a=b=0 落在 0.502），
           * L 从 [0,100] 搬到 0…1。浮点图可以超出 sRGB 色域，这里不做
           * 二次夹紧，超界值原样带过去交给曲线判断。
           * a/b map from -128..127 to 0..1; neutral grey sits at 0.502. */
          in_line[x * 4 + 0] = (a - LB_LAB_A_MIN) / LB_LAB_AB_SPAN;
          in_line[x * 4 + 1] = (b - LB_LAB_A_MIN) / LB_LAB_AB_SPAN;
          in_line[x * 4 + 2] = L / LB_LAB_L_SPAN;
          in_line[x * 4 + 3] = 1.0f;              /* 分量层一律不透明 */
        }

      gegl_buffer_set (out_buf, &row, 0, fin, in_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (in_line);
  g_free (lab_line);
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
    "name",            "lb:lab-dual",
    "title",           _("Lab Dual Extract"),
    "categories",      "color",
    "description",     _("Pack Lab a, b and lightness into one data image "
                         "(R=a, G=b, B=L) for curve editing"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Component",
    "gimp:menu-label", _("Lab Dual Extract"),
    NULL);
}

/* babl fish 只建一次；GEGL 的 process 是多线程的，用 GOnce 保护。
 * Built once: GEGL calls process from worker threads. */
static gsize        fish_once = 0;
static const Babl  *fish_rgb2lab = NULL;

static void
make_fish (void)
{
  fish_rgb2lab = babl_fish ("R'G'B'A float", "CIE Lab float");
}

static const Babl *
rgb_to_lab_fish (void)
{
  if (g_once_init_enter (&fish_once))
    {
      make_fish ();
      g_once_init_leave (&fish_once, 1);
    }
  return fish_rgb2lab;
}

#endif
