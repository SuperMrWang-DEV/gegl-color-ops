/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lab-curves
 * menu       LAB Curves
 * purpose    LAB 三通道各自一条任意曲线
 *            One free-form curve per LAB channel.
 * algorithm  在 babl "CIE Lab alpha float"（D50 白点）上逐通道查曲线：
 *            L 走 0…100，a/b 走 −128…127（中性 0 落在曲线横向 50.2% 处）。
 *            曲线用 Fritsch–Carlson 单调三次插值（common/curve.h），
 *            保单调不过冲——过冲会在中性附近打出一圈本不存在的色光。
 *            Per-channel curve lookup on babl CIE Lab (D50): L spans 0…100,
 *            a/b span −128…127 so neutral 0 sits at 50.2% of the horizontal
 *            axis. Curves use Fritsch–Carlson monotone cubic interpolation,
 *            which cannot overshoot into a phantom colour bloom.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_string (curves, _("Curves"), "")
  description (_("Control points for the L, a and b channels, as "
                 "\"L 0,0 0.3,0.2 1,1|a 0,0 0.5,0.52 1,1|b 0,0 1,1\". "
                 "Coordinates are normalised to 0…1 along each axis. "
                 "A channel that is omitted stays unchanged. The interactive "
                 "dialog writes this string, and re-running it reads the "
                 "curves back, so the adjustment stays editable."))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_lab_curves
#define GEGL_OP_C_SOURCE lab-curves.c
#include "gegl-op.h"

#include "curve.h"

/* 三个分量的物理量程 / physical range of each component */
#define LAB_L_LO    0.0f
#define LAB_L_HI  100.0f
#define LAB_AB_LO (-128.0f)
#define LAB_AB_HI  127.0f

static const gchar *const lab_names[3] = { "L", "a", "b" };

/* 物理值 → 曲线横轴 0..1 / physical value to the 0..1 curve axis */
static inline gfloat
lab_norm (gfloat v, gfloat lo, gfloat hi)
{
  return CLAMP ((v - lo) / (hi - lo), 0.0f, 1.0f);
}

/* 曲线纵轴 0..1 → 物理值 / curve output back to a physical value */
static inline gfloat
lab_denorm (gfloat t, gfloat lo, gfloat hi)
{
  return lo + t * (hi - lo);
}

static void
prepare (GeglOperation *op)
{
  /* 直接声明 Lab 格式：babl 负责输入到 Lab、输出回 RGB 的转换，算子只
   * 逐通道查表。与 lb:lab-levels / lb:match-color 同一套数值口径。
   * Declaring Lab lets babl do RGB↔Lab on both sides, so the op only does
   * three table lookups per pixel. */
  gegl_operation_set_format (op, "input",  babl_format ("CIE Lab alpha float"));
  gegl_operation_set_format (op, "output", babl_format ("CIE Lab alpha float"));
}

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *in_buf,
         GeglBuffer          *out_buf,
         const GeglRectangle *roi,
         gint                 level)
{
  LbCurve curves[3];
  gchar  *text = NULL;

  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  /* 先铺恒等，再由曲线串覆盖出现过的分量（parse_set 不碰初值）
   * Lay down identity first, then let the string override what it mentions. */
  for (gint i = 0; i < 3; i++)
    lb_curve_identity (&curves[i]);

  /* 参数在 process 内部读取，避免 user_data 的并发竞争
   * Parameters are read inside process(), so the user_data race is gone. */
  g_object_get (G_OBJECT (op), "curves", &text, NULL);
  lb_curve_parse_set (curves, 3, lab_names, text ? text : "");
  g_free (text);

  const Babl *fmt   = babl_format ("CIE Lab alpha float");
  gint        stride = roi->width * 4;
  gfloat     *in_line  = g_new (gfloat, stride);
  gfloat     *out_line = g_new (gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };

    gegl_buffer_get (in_buf, &row_rect, 1.0f, fmt,
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    /* 三条曲线都没动：整行原样抄过去，省掉三次 clamp 与查表
     * All three curves are identity: copy the row untouched. */
    if (curves[0].identity && curves[1].identity && curves[2].identity)
    {
      memcpy (out_line, in_line, sizeof (gfloat) * stride);
    }
    else
    {
      for (gint x = 0; x < roi->width; x++)
      {
        gint   px = x * 4;
        gfloat L  = in_line[px + 0];
        gfloat ach = in_line[px + 1];
        gfloat bb  = in_line[px + 2];
        gfloat a   = in_line[px + 3];

        /* 透明像素原样透传（透明处色彩无意义）
         * Fully transparent pixels pass through untouched. */
        if (a <= 0.0f)
        {
          out_line[px + 0] = L;
          out_line[px + 1] = ach;
          out_line[px + 2] = bb;
          out_line[px + 3] = 0.0f;
          continue;
        }

        out_line[px + 0] = lab_denorm (
            lb_curve_at (&curves[0], lab_norm (L,   LAB_L_LO,  LAB_L_HI)),
            LAB_L_LO,  LAB_L_HI);
        out_line[px + 1] = lab_denorm (
            lb_curve_at (&curves[1], lab_norm (ach, LAB_AB_LO, LAB_AB_HI)),
            LAB_AB_LO, LAB_AB_HI);
        out_line[px + 2] = lab_denorm (
            lb_curve_at (&curves[2], lab_norm (bb,  LAB_AB_LO, LAB_AB_HI)),
            LAB_AB_LO, LAB_AB_HI);
        out_line[px + 3] = a;
      }
    }

    gegl_buffer_set (out_buf, &row_rect, 0, fmt,
                     out_line, GEGL_AUTO_ROWSTRIDE);
  }

  g_free (in_line);
  g_free (out_line);
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
    "name",            "lb:lab-curves",
    "title",           _("LAB Curves"),
    "categories",      "color",
    "description",     _("Free-form curves for the L, a and b channels; "
                         "adjust tone and colour separately"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Curves",
    "gimp:menu-label", _("LAB Curves"),
    NULL);
}

#endif
