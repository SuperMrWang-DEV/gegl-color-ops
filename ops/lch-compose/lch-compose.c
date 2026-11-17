/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lch-compose
 * menu       LCh Compose
 * purpose    LCh 分量曲线工作流的合成器：把「R = L/100、G = C/140、
 *            B = 色相/360」的数据图还原成真实颜色
 *            Composer for the LCh component-curve workflow: turns the data
 *            image (R=L/100, G=C/140, B=h/360) back into real colour.
 * input      R'G'B'A float，数值是数据（lb:lch-dual 的输出，或用户自己拼的
 *            三通道数据图）。alpha 被忽略，输出恒不透明
 * output     R'G'B'A float，sRGB 编码值
 * algorithm  先把 0…1 还原成物理量（L* = R·100、C* = G·140、h = B·360°），
 *            再由 babl 转成 RGB（"CIE LCH(ab) alpha float"，D50）。与
 *            lb:lch-levels 同一套 Lab 口径。
 *            Rescale back to L*, C*, h and let babl do LCh→RGB (D50).
 * type       GeglOperationFilter（逐像素，无 aux）
 * note       「R 是明度、G 是彩度」是硬约定：本算子无法分辨输入是一张数据图
 *            还是一张普通照片。挂错地方会把照片当数据解释。
 *            The channel layout is a hard contract; feed it data, not photos.
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

/* 与 lb:lch-dual 必须一致；改了一边就要改另一边。
 * Must match lb:lch-dual. */
#define LB_LCH_C_SPAN   140.0f

#ifdef GEGL_PROPERTIES

/* 无可调参数：调整在输入的那三条曲线上完成。
 * No parameters: the adjustment happens in the curves upstream. */

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_lch_compose
#define GEGL_OP_C_SOURCE lch-compose.c
#include "gegl-op.h"

static const Babl *lch_to_rgb_fish (void);

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
  const Babl *fish  = lch_to_rgb_fish ();
  const gint  width = roi->width;
  gfloat     *data_line, *lch_line;
  gint        y;

  if (width <= 0 || roi->height <= 0)
    return TRUE;

  data_line = g_new (gfloat, (gsize) width * 4);
  lch_line  = g_new (gfloat, (gsize) width * 4);

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, width, 1 };
      gint          x;

      gegl_buffer_get (in_buf, &row, 1.0, fin, data_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (x = 0; x < width; x++)
        {
          lch_line[x * 4 + 0] = clamp01 (data_line[x * 4 + 0]) * 100.0f; /* L */
          lch_line[x * 4 + 1] = clamp01 (data_line[x * 4 + 1]) * LB_LCH_C_SPAN;
          lch_line[x * 4 + 2] = clamp01 (data_line[x * 4 + 2]) * 360.0f; /* h */
          lch_line[x * 4 + 3] = 1.0f;
        }

      babl_process (fish, lch_line, data_line, width);
      gegl_buffer_set (out_buf, &row, 0, fin, data_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (data_line);
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
    "name",            "lb:lch-compose",
    "title",           _("LCh Compose"),
    "categories",      "color",
    "description",     _("Turn the data image (R=L/100, G=C/140, B=h/360) "
                         "back into real LCh colour"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Component",
    "gimp:menu-label", _("LCh Compose"),
    NULL);
}

static gsize       fish_once = 0;
static const Babl *fish_lch2rgb = NULL;

static void
make_fish (void)
{
  fish_lch2rgb = babl_fish ("CIE LCH(ab) alpha float", "R'G'B'A float");
}

static const Babl *
lch_to_rgb_fish (void)
{
  if (g_once_init_enter (&fish_once))
    {
      make_fish ();
      g_once_init_leave (&fish_once, 1);
    }
  return fish_lch2rgb;
}

#endif
