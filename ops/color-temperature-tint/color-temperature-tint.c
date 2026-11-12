/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:color-temperature-tint
 * menu       Color Temperature & Tint
 * purpose    PS 2026「色彩与自然饱和度」里的色温 / 色调：中性灰跟着偏蓝-黄、
 *            绿-洋红，黑白两端不动
 *            The Temperature and Tint sliders of Photoshop 2026's Color and
 *            vibrance layer: neutrals drift blue-yellow or green-magenta
 *            while the black and white endpoints stay put.
 * algorithm  编码值解码到线性 → 3 次多项式（20 项）→ clamp → 编码。系数在 17×
 *            17 的(色温,色调) 网格上实测，运行时双线性插值后烘成 33³ LUT，逐
 *            像素只查表；截断样本用带删失的迭代回归拟合，硬裁切交给 clamp
 *            Encoded values are decoded to linear, run through a 3rd-order
 *            polynomial (20 terms), clamped and encoded. Coefficients are
 *            measured on a 17x17 (temperature, tint) grid, interpolated at
 *            run time and baked into a 33^3 LUT, so the per-pixel work is a
 *            lookup. Censored samples are fitted with an iterated hinge
 *            regression and the hard clip is left to the clamp.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  Photoshop 2026（27.0）「色彩与自然饱和度」调整图层（实测逆向）
 *            Photoshop 2026 (27.0) Color and vibrance adjustment layer
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_double (temperature, _("Temperature"), 0.0)
    description (_("Warm / cool shift, -100 to +100. Negative is cooler (blue), "
                   "positive warmer (yellow); 0 leaves the image untouched"))
    value_range (-100.0, 100.0)
    ui_range    (-100.0, 100.0)
    ui_steps    (1.0, 5.0)

property_double (tint, _("Tint"), 0.0)
    description (_("Green / magenta shift, -100 to +100. Negative is greener, "
                   "positive more magenta; 0 leaves the image untouched"))
    value_range (-100.0, 100.0)
    ui_range    (-100.0, 100.0)
    ui_steps    (1.0, 5.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_color_temperature_tint
#define GEGL_OP_C_SOURCE color-temperature-tint.c

#include "gegl-op.h"
#include "ps-temp-tint.h"

/* 33³ LUT 挂在 user_data 上：色温色调对整张图是常量，每张图只需要烘一次。
 * The 33³ LUT hangs off user_data: temperature/tint are constant for the whole
 * image, so it only has to be baked once per render. */
typedef struct
{
  gboolean identity;
  gfloat   lut[PT_LUT * PT_LUT * PT_LUT * 3];
} TtParams;

static void
prepare (GeglOperation *operation)
{
  GeglProperties *o = GEGL_PROPERTIES (operation);
  const Babl     *space = gegl_operation_get_source_space (operation, "input");
  TtParams       *p = (TtParams *) o->user_data;

  /* 感知（非线性）RGB：这套标定是在 sRGB 编码值上做的，放进线性光会整体跑偏
   * Perceptual (non-linear) RGB: the calibration was done on sRGB-encoded
   * values and would drift in linear light. */
  if (! space)
    space = babl_space ("sRGB");

  if (! p)
    {
      p = g_new0 (TtParams, 1);
      o->user_data = p;
    }

  p->identity = (fabs (o->temperature) < 1e-3 && fabs (o->tint) < 1e-3);

  if (! p->identity)
    pt_build_lut ((gfloat) o->temperature, (gfloat) o->tint, p->lut);

  gegl_operation_set_format (operation, "input",
                             babl_format_with_space ("R~G~B~A float", space));
  gegl_operation_set_format (operation, "output",
                             babl_format_with_space ("R~G~B~A float", space));
}

static void
finalize (GObject *object)
{
  GeglProperties *o = GEGL_PROPERTIES (object);

  if (o->user_data)
    {
      g_free (o->user_data);
      o->user_data = NULL;
    }

  G_OBJECT_CLASS (gegl_op_parent_class)->finalize (object);
}

static gboolean
process (GeglOperation       *operation,
         void                *in_buf,
         void                *out_buf,
         glong                n_pixels,
         const GeglRectangle *roi,
         gint                 level)
{
  GeglProperties    *o = GEGL_PROPERTIES (operation);
  const TtParams    *p = (const TtParams *) o->user_data;
  const gfloat * GEGL_ALIGNED in  = in_buf;
  gfloat       * GEGL_ALIGNED out = out_buf;

  g_assert (p != NULL);

  /* prepare() 把格式钉死为 R~G~B~A float，步长恒为 4
   * prepare() pins R~G~B~A float, so the stride is always 4. */
  if (p->identity)
    {
      memcpy (out, in, sizeof (gfloat) * 4 * (gsize) n_pixels);
      return TRUE;
    }

  while (n_pixels--)
    {
      gfloat v[3];

      pt_sample (p->lut, in, v);
      out[0] = v[0];
      out[1] = v[1];
      out[2] = v[2];
      out[3] = in[3];

      in  += 4;
      out += 4;
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass            *oc = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointFilterClass *cc = GEGL_OPERATION_POINT_FILTER_CLASS (klass);
  GObjectClass                  *gc = G_OBJECT_CLASS (klass);

  oc->prepare = prepare;
  cc->process = process;
  gc->finalize = finalize;

  gegl_operation_class_set_keys (oc,
    "name",            "lb:color-temperature-tint",
    "title",           _("Color Temperature & Tint (Photoshop)"),
    "categories",      "color:enhance",
    "description",     _("Photoshop 2026's Temperature and Tint sliders, matched "
                         "by measurement: a 3rd-order polynomial in linear light "
                         "over a 17x17 parameter grid, clamped and baked into a "
                         "33^3 lookup table"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Color",
    "gimp:menu-label", _("Color Temperature & Tint"),
    NULL);
}

#endif
