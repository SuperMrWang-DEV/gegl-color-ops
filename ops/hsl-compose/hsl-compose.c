/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hsl-compose
 * menu       HSL Compose
 * purpose    HSL 分量曲线工作流的合成器：把「R = 饱和度、G = 明度、
 *            B = 色相/360」的数据图还原成真实颜色
 *            Composer for the HSL component-curve workflow: turns the data
 *            image (R = S, G = L, B = H/360) back into real colour.
 * input      R'G'B'A float，数值是数据（lb:hsl-dual 的输出，或用户自己
 *            拼的三通道数据图）。alpha 被忽略，输出恒不透明
 * output     R'G'B'A float，sRGB 编码值
 * algorithm  HSL→RGB 由 babl 完成（"HSLA float"），与 GIMP 的 HSL 同一口径；
 *            本算子只把 0…1 还原成 0…360 / 0…100 / 0…100
 *            babl does the conversion; this op only rescales back.
 * type       GeglOperationFilter（逐像素，无 aux）
 * note       「R 是饱和度、G 是明度」是硬约定：本算子无法分辨输入是一张
 *            数据图还是一张普通照片。挂错地方会把照片当数据解释。
 *            The channel layout is a hard contract; feed it data, not photos.
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* 无可调参数：调整在输入的那两条曲线上完成。
 * No parameters: the adjustment happens in the curves upstream. */

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_hsl_compose
#define GEGL_OP_C_SOURCE hsl-compose.c
#include "gegl-op.h"

static const Babl *hsl_to_rgb_fish (void);

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
  const Babl *fish  = hsl_to_rgb_fish ();
  const gint  width = roi->width;
  gfloat     *data_line, *hsl_line;
  gint        y;

  if (width <= 0 || roi->height <= 0)
    return TRUE;

  data_line = g_new (gfloat, (gsize) width * 4);
  hsl_line  = g_new (gfloat, (gsize) width * 4);

  for (y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, width, 1 };
      gint          x;

      gegl_buffer_get (in_buf, &row, 1.0, fin, data_line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

      for (x = 0; x < width; x++)
        {
          /* babl 的 "HSLA float" 是 0…1 归一化，数据图也是 0…1，直接对位。
           * babl's HSLA float is normalised to 0..1; the data image is too. */
          hsl_line[x * 4 + 0] = clamp01 (data_line[x * 4 + 2]);  /* H/360 */
          hsl_line[x * 4 + 1] = clamp01 (data_line[x * 4 + 0]);  /* S */
          hsl_line[x * 4 + 2] = clamp01 (data_line[x * 4 + 1]);  /* L */
          hsl_line[x * 4 + 3] = 1.0f;
        }

      babl_process (fish, hsl_line, data_line, width);
      gegl_buffer_set (out_buf, &row, 0, fin, data_line, GEGL_AUTO_ROWSTRIDE);
    }

  g_free (data_line);
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
    "name",            "lb:hsl-compose",
    "title",           _("HSL Compose"),
    "categories",      "color",
    "description",     _("Turn the data image (R=S, G=L, B=H/360) back into "
                         "real HSL colour"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Component",
    "gimp:menu-label", _("HSL Compose"),
    NULL);
}

static gsize       fish_once = 0;
static const Babl *fish_hsl2rgb = NULL;

static void
make_fish (void)
{
  fish_hsl2rgb = babl_fish ("HSLA float", "R'G'B'A float");
}

static const Babl *
hsl_to_rgb_fish (void)
{
  if (g_once_init_enter (&fish_once))
    {
      make_fish ();
      g_once_init_leave (&fish_once, 1);
    }
  return fish_hsl2rgb;
}

#endif
