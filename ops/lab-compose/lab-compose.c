/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lab-compose
 * menu       Lab Compose
 * purpose    Lab 分量曲线工作流的合成器：把「R = a、G = b、B = L」的数据图
 *            还原成真实颜色
 *            Composer for the Lab component-curve workflow: turns the data
 *            image (R = a, G = b, B = L) back into real colour.
 * input      R'G'B'A float，数值是数据（lb:lab-dual 的输出，或用户自己拼的
 *            三通道数据图）。alpha 被忽略，输出恒不透明
 * output     R'G'B'A float，sRGB 编码值
 * algorithm  先把 0…1 还原成 babl 的 Lab 量程（a = R·255 − 128、L = B·100），
 *            再交给 babl（"CIE Lab float"）转回 RGB。超出 sRGB 色域的结果
 *            按 [0,1] 裁掉。
 *            Undo the normalisation, then let babl convert Lab back to RGB.
 * type       GeglOperationFilter（逐像素，无 aux）
 * note       「R 是 a、G 是 b、B 是 L」是硬约定：本算子无法分辨输入是一张
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
#define GEGL_OP_NAME     lb_lab_compose
#define GEGL_OP_C_SOURCE lab-compose.c
#include "gegl-op.h"

#define LB_LAB_A_MIN   (-128.0f)
#define LB_LAB_AB_SPAN  255.0f
#define LB_LAB_AB_MAX   127.0f
#define LB_LAB_L_SPAN   100.0f

static const Babl *lab_to_rgb_fish (void);

static inline gfloat
clampf (gfloat v, gfloat lo, gfloat hi)
{
  if (!isfinite (v))
    return lo;
  return v < lo ? lo : (v > hi ? hi : v);
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
  const Babl *fish  = lab_to_rgb_fish ();
  const gint  width = roi->width;
  gfloat     *data_line, *lab_line;
  gint        y;

  if (width <= 0 || roi->height <= 0)
    return TRUE;

  data_line = g_new (gfloat, (gsize) width * 4);
  lab_line  = g_new (gfloat, (gsize) width * 3);

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, width, 1 };
      gint          x;

      gegl_buffer_get (in_buf, &row, 1.0, fin, data_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (x = 0; x < width; x++)
        {
          /* 曲线可以把数据推到 0…1 之外（比如把 a 拉高到 1.4），先夹回
           * Lab 的合法量程再转换，避免 babl 收到 NaN/无穷。
           * Curves may push data outside 0..1; clamp into Lab's range first. */
          lab_line[x * 3 + 0] = clampf (data_line[x * 4 + 2], 0.0f, 1.0f)
                                * LB_LAB_L_SPAN;
          lab_line[x * 3 + 1] = clampf (data_line[x * 4 + 0] * LB_LAB_AB_SPAN
                                        + LB_LAB_A_MIN,
                                        LB_LAB_A_MIN, LB_LAB_AB_MAX);
          lab_line[x * 3 + 2] = clampf (data_line[x * 4 + 1] * LB_LAB_AB_SPAN
                                        + LB_LAB_A_MIN,
                                        LB_LAB_A_MIN, LB_LAB_AB_MAX);
        }

      babl_process (fish, lab_line, data_line, width);

      for (x = 0; x < width; x++)
        {
          data_line[x * 4 + 0] = clampf (data_line[x * 4 + 0], 0.0f, 1.0f);
          data_line[x * 4 + 1] = clampf (data_line[x * 4 + 1], 0.0f, 1.0f);
          data_line[x * 4 + 2] = clampf (data_line[x * 4 + 2], 0.0f, 1.0f);
          data_line[x * 4 + 3] = 1.0f;
        }

      gegl_buffer_set (out_buf, &row, 0, fin, data_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (data_line);
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
    "name",            "lb:lab-compose",
    "title",           _("Lab Compose"),
    "categories",      "color",
    "description",     _("Turn the data image (R=a, G=b, B=L) back into "
                         "real Lab colour"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Component",
    "gimp:menu-label", _("Lab Compose"),
    NULL);
}

static gsize       fish_once = 0;
static const Babl *fish_lab2rgb = NULL;

static void
make_fish (void)
{
  fish_lab2rgb = babl_fish ("CIE Lab float", "R'G'B'A float");
}

static const Babl *
lab_to_rgb_fish (void)
{
  if (g_once_init_enter (&fish_once))
    {
      make_fish ();
      g_once_init_leave (&fish_once, 1);
    }
  return fish_lab2rgb;
}

#endif
