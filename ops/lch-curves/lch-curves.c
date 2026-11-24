/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lch-curves
 * menu       LCh Curves
 * purpose    LCh 三通道各自一条曲线（色相用偏移曲线）
 *            One curve per LCh component; hue uses an offset curve.
 * algorithm  在 babl "CIE LCH(ab) alpha float"（D50）上逐通道查曲线：
 *            L 0…100、C 0…132（sRGB 最饱和的纯蓝也装得下）、h 环形。
 *            色相不能用对角线曲线——首尾映射到不同值就在 0°/360° 撞出接缝，
 *            强行对齐又做不了整体旋转。改用偏移曲线：纵轴 0.5 = 不偏，
 *            水平线 = 整体旋转，弯线 = 分带调整。
 *            Per-channel lookup on babl CIE LCH(ab) (D50): L spans 0…100,
 *            C spans 0…132 (enough for the most saturated sRGB blue), h is
 *            circular. Hue uses an offset curve — see common/curve.h.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_string (curves, _("Curves"), "")
  description (_("Control points for the L, C and h components, as "
                 "\"L 0,0 0.5,0.55 1,1|C 0,0 0.5,0.62 1,1|h 0,0.5 1,0.5\". "
                 "The hue curve is an offset curve: 0.5 on the vertical axis "
                 "means no shift, a flat line at another height rotates the "
                 "whole ring, a bent line redistributes hue bands. An omitted "
                 "component stays unchanged. The interactive dialog writes "
                 "this string and reads it back, so the adjustment stays "
                 "editable."))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_lch_curves
#define GEGL_OP_C_SOURCE lch-curves.c
#include "gegl-op.h"

#include "curve.h"

#define LCH_L_LO    0.0f
#define LCH_L_HI  100.0f
#define LCH_C_LO    0.0f
#define LCH_C_HI  132.0f
#define LCH_H_LO    0.0f
#define LCH_H_HI  360.0f

static const gchar *const lch_names[3] = { "L", "C", "h" };

static inline gfloat
lch_norm (gfloat v, gfloat lo, gfloat hi)
{
  return CLAMP ((v - lo) / (hi - lo), 0.0f, 1.0f);
}

static inline gfloat
lch_denorm (gfloat t, gfloat lo, gfloat hi)
{
  return lo + t * (hi - lo);
}

static void
prepare (GeglOperation *op)
{
  gegl_operation_set_format (op, "input",  babl_format ("CIE LCH(ab) alpha float"));
  gegl_operation_set_format (op, "output", babl_format ("CIE LCH(ab) alpha float"));
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

  /* L 与 C 是普通曲线（对角线恒等），h 是偏移曲线（水平中线恒等）
   * L and C are ordinary curves; h is an offset curve flat at 0.5. */
  lb_curve_identity (&curves[0]);
  lb_curve_identity (&curves[1]);
  lb_curve_offset_default (&curves[2]);

  g_object_get (G_OBJECT (op), "curves", &text, NULL);
  lb_curve_parse_set (curves, 3, lch_names, text ? text : "");
  g_free (text);

  const Babl *fmt    = babl_format ("CIE LCH(ab) alpha float");
  gint        stride = roi->width * 4;
  gfloat     *in_line  = g_new (gfloat, stride);
  gfloat     *out_line = g_new (gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };

    gegl_buffer_get (in_buf, &row_rect, 1.0f, fmt,
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

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
        gfloat C  = in_line[px + 1];
        gfloat h  = in_line[px + 2];
        gfloat a  = in_line[px + 3];

        if (a <= 0.0f)
        {
          out_line[px + 0] = L;
          out_line[px + 1] = C;
          out_line[px + 2] = h;
          out_line[px + 3] = 0.0f;
          continue;
        }

        out_line[px + 0] = lch_denorm (
            lb_curve_at (&curves[0], lch_norm (L, LCH_L_LO, LCH_L_HI)),
            LCH_L_LO, LCH_L_HI);
        out_line[px + 1] = lch_denorm (
            lb_curve_at (&curves[1], lch_norm (C, LCH_C_LO, LCH_C_HI)),
            LCH_C_LO, LCH_C_HI);
        /* 无彩色像素的色相没有意义，偏移只会让它去撞一个随机的角度
         * Hue is meaningless at zero chroma; shifting it would just pick a
         * random angle. */
        out_line[px + 2] = (C > 1e-4f)
            ? lch_denorm (
                lb_curve_offset_at (&curves[2], lch_norm (h, LCH_H_LO, LCH_H_HI)),
                LCH_H_LO, LCH_H_HI)
            : h;
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
    "name",            "lb:lch-curves",
    "title",           _("LCh Curves"),
    "categories",      "color",
    "description",     _("Free-form curves for lightness, chroma and hue; "
                         "the hue curve shifts the ring without a seam"),
    "gimp:menu-path",  "<Image>/SuperMrWang/Curves",
    "gimp:menu-label", _("LCh Curves"),
    NULL);
}

#endif
