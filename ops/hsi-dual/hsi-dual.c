/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsi-dual
 * menu       HSI Dual Extract
 * purpose    HSI 分量曲线工作流的提取器：把一张图拆成「R = 饱和度、
 *            G = 强度、B = 色相/360」的数据图，一张图同时携带三个分量
 *            Extractor for the HSI component-curve workflow: turns an image
 *            into a data image with R = S, G = I, B = H/360.
 * input      R'G'B'A float（滤镜栈的编码域缓冲）
 * output     R'G'B'A float，数值是数据不是颜色；alpha 恒为 1
 * algorithm  babl 没有 HSI 模型，转换用的是本仓库 common/color-levels.h 里
 *            那一套（与 lb:hsi-levels 同一份代码）：I = (R+G+B)/3、
 *            S = 1 − min/I、色相取余弦定义
 *              cos H = [(R−G)+(R−B)] / (2·√((R−G)² + (R−B)(G−B)))
 *            这正是 HSI 的「真实角度」，不是 HSV 的六边形参数角。
 *            HSI lives in common/color-levels.h because babl has no HSI
 *            model; the hue is the true (cosine) angle, not HSV's.
 * type       GeglOperationFilter（逐像素，无 aux）
 * note       为什么三个分量必须挤进同一张图：HSI 的 I 是 (R+G+B)/3，S 是
 *            1 − min/I——GIMP 的六条分量混合模式（HSV / LCh）里一条也对不上。
 *            更要紧的是色相：HSI 的色相角是余弦定义，与 HSV 的参数角最多差
 *            1.117°，而且借「HSV 色相」模式换角会把 I 带走（实测 0.08，约
 *            20 码）。所以色相也只能在这张数据图里改，由 lb:hsi-compose 连同
 *            S、I 一起重算。
 *            No GIMP component mode carries HSI's I, and rotating hue through
 *            the HSV hue mode drags I along, so all three stay in one buffer.
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
#define GEGL_OP_NAME     lb_hsi_dual
#define GEGL_OP_C_SOURCE hsi-dual.c
#include "gegl-op.h"
#include "color-levels.h"      /* lb_cl_rgb_to_hsi，与 lb:hsi-levels 同源 */

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
  const gint  width = roi->width;
  gfloat     *in_line;
  gint        y;

  if (width <= 0 || roi->height <= 0)
    return TRUE;

  in_line = g_new (gfloat, (gsize) width * 4);

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, width, 1 };
      gint          x;

      gegl_buffer_get (in_buf, &row, 1.0, fin, in_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (x = 0; x < width; x++)
        {
          gfloat h, s, i;

          lb_cl_rgb_to_hsi (in_line[x * 4 + 0], in_line[x * 4 + 1],
                            in_line[x * 4 + 2], &h, &s, &i);

          in_line[x * 4 + 0] = s;                 /* 饱和度 */
          in_line[x * 4 + 1] = i;                 /* 强度   */
          in_line[x * 4 + 2] = h / 360.0f;        /* 色相   */
          in_line[x * 4 + 3] = 1.0f;              /* 分量层一律不透明 */
        }

      gegl_buffer_set (out_buf, &row, 0, fin, in_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (in_line);
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
    "name",            "lb:hsi-dual",
    "title",           _("HSI Dual Extract"),
    "categories",      "color",
    "description",     _("Pack HSI saturation, intensity and hue into one "
                         "data image (R=S, G=I, B=H/360) for curve editing"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Component",
    "gimp:menu-label", _("HSI Dual Extract"),
    NULL);
}

#endif
