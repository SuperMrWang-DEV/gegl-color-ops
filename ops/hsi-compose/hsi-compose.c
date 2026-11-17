/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsi-compose
 * menu       HSI Compose
 * purpose    HSI 分量曲线工作流的合成器：把「R = 饱和度、G = 强度、
 *            B = 色相/360」的数据图还原成真实颜色
 *            Composer for the HSI component-curve workflow: turns the data
 *            image (R=S, G=I, B=H/360) back into real colour.
 * input      R'G'B'A float，数值是数据（lb:hsi-dual 的输出）。alpha 被忽略，
 *            输出恒不透明
 * output     R'G'B'A float，sRGB 编码值
 * algorithm  逆变换用 HSI 的余弦式（不是 HSV 的线性扇区）：
 *              H<120°: B = I(1−S)、R = I[1 + S·cosH/cos(60−H)]、G = 3I−R−B
 *            另两段各轮转 120°。转换函数来自 common/color-levels.h，与
 *            lb:hsi-levels 同一份。S、I 拉高时逆变换可能出界，按 [0,1] 裁掉。
 *            The inverse uses HSI's cosine form; out-of-gamut results clip.
 * type       GeglOperationFilter（逐像素，无 aux）
 * note       「R 是饱和度、G 是强度」是硬约定：本算子无法分辨输入是一张
 *            数据图还是一张普通照片。挂错地方会把照片当数据解释。
 *            The channel layout is a hard contract; feed it data, not photos.
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* 无可调参数：调整在输入的那几条曲线上完成。
 * No parameters: the adjustment happens in the curves upstream. */

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_hsi_compose
#define GEGL_OP_C_SOURCE hsi-compose.c
#include "gegl-op.h"
#include "color-levels.h"      /* lb_cl_hsi_to_rgb，与 lb:hsi-levels 同源 */

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
  gfloat     *data_line;
  gint        y;

  if (width <= 0 || roi->height <= 0)
    return TRUE;

  data_line = g_new (gfloat, (gsize) width * 4);

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, width, 1 };
      gint          x;

      gegl_buffer_get (in_buf, &row, 1.0, fin, data_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (x = 0; x < width; x++)
        {
          gfloat r, g, b;

          /* 曲线可以把数据推到 0…1 之外；lb_cl_hsi_to_rgb 自己会夹 S 与 I，
           * 色相走 wrap360，所以这里不用重复夹紧。逆变换的输出它也会裁到
           * [0,1]（sRGB 色域外只能裁）。
           * Curves may push data past 0..1; the converter clamps internally. */
          lb_cl_hsi_to_rgb (data_line[x * 4 + 2] * 360.0f,   /* H */
                            data_line[x * 4 + 0],            /* S */
                            data_line[x * 4 + 1],            /* I */
                            &r, &g, &b);

          data_line[x * 4 + 0] = r;
          data_line[x * 4 + 1] = g;
          data_line[x * 4 + 2] = b;
          data_line[x * 4 + 3] = 1.0f;
        }

      gegl_buffer_set (out_buf, &row, 0, fin, data_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (data_line);
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
    "name",            "lb:hsi-compose",
    "title",           _("HSI Compose"),
    "categories",      "color",
    "description",     _("Turn the data image (R=S, G=I, B=H/360) back into "
                         "real HSI colour"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Component",
    "gimp:menu-label", _("HSI Compose"),
    NULL);
}

#endif
