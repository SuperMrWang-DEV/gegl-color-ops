/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:exposure
 * menu       Exposure EV
 * purpose    PS 曝光：EV、偏移、伽马三段式调整（按 EV 计曝光档位）
 *            PS Exposure: EV, offset and gamma in three stages, measured in
 *            exposure stops.
 * algorithm  在 8bit sRGB 伽马域反推 PS 曝光层公式；输入须为伽马编码 sRGB，勿
 *            在前置节点用 linear-rgb
 *            Reverse-engineered from the PS Exposure layer in 8-bit sRGB
 *            gamma space. Feed gamma-encoded sRGB; do not insert linear-rgb
 *            before this op.
 * type       GeglOperationFilter（需整块区域 / whole-region）
 * reference  Photoshop「曝光」调整层
 *            Photoshop Exposure adjustment layer
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (exposure, _("Exposure"), 0.0)
    description (_("Exposure (EV), same slider range as Photoshop"))
    value_range (-20.0, 20.0)
    ui_range (-6.0, 6.0)

property_double (offset, _("Offset"), 0.0)
    description (_("Offset, adjusts shadow and midtone"))
    value_range (-0.5, 0.5)
    ui_range (-0.2, 0.2)

property_double (gamma, _("Gamma Correction"), 1.0)
    description (_("Gray coefficient correction / Gamma"))
    value_range (0.01, 9.99)
    ui_range (0.10, 3.0)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_exposure
#define GEGL_OP_C_SOURCE exposure.c
#include "gegl-op.h"

#define GAMMA_SRGB      2.2f
#define SAFE_GAMMA_MIN  0.001f
#define FLOAT_EPS       1e-12f

static inline gfloat sanitize_f(gfloat v)
{
  if (!isfinite(v))
    return 0.0f;
  return v;
}

static inline gfloat exposure_8bit_kernel(gfloat in,
                                          gdouble exposure,
                                          gdouble offset,
                                          gdouble gamma)
{
  gfloat v1, v2, out;
  in = MAX(sanitize_f(in), 0.0f);

  /* 第 1 步：曝光
   * Step 1: exposure */
  v1 = in * powf(2.0f, (gfloat)exposure / GAMMA_SRGB);

  /* 第 2 步：偏移，并转到线性空间
   * Step 2: offset, then convert to linear space */
  gfloat lin = powf(MAX(v1, FLOAT_EPS), GAMMA_SRGB);
  lin += (gfloat)offset;
  lin = CLAMP(lin, 0.0f, 1.0f);
  v2 = powf(lin, 1.0f / GAMMA_SRGB);

  /* 第 3 步：伽马校正
   * Step 3: gamma correction */
  gfloat safe_g = MAX((gfloat)gamma, SAFE_GAMMA_MIN);
  out = powf(MAX(v2, FLOAT_EPS), 1.0f / safe_g);

  return CLAMP(out, 0.0f, 1.0f);
}

static void
prepare(GeglOperation *op)
{
  /* 固定格式，与 hsl-seven 一致
   * Fixed format, same as hsl-seven */
  gegl_operation_set_format(op, "input",  babl_format("RGBA float"));
  gegl_operation_set_format(op, "output", babl_format("RGBA float"));
}

static gboolean
process(GeglOperation       *op,
        GeglBuffer          *in_buf,
        GeglBuffer          *out_buf,
        const GeglRectangle *roi,
        gint                 level)
{
  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  /* 参数在 process 内部读取，与 hsl-seven 的做法一致
   * Read parameters inside process(), exactly like hsl-seven */
  gdouble exposure;
  gdouble offset;
  gdouble gamma;

  g_object_get(G_OBJECT(op),
    "exposure", &exposure,
    "offset", &offset,
    "gamma", &gamma,
    NULL);

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };

    /* 读入一行扫描线
     * Read one scanline */
    gegl_buffer_get(in_buf, &row_rect, 1.0f, babl_format("RGBA float"),
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint px = x * 4;
      gfloat r = in_line[px + 0];
      gfloat g = in_line[px + 1];
      gfloat b = in_line[px + 2];
      gfloat a = in_line[px + 3];

      /* 执行 PS 8bit 曝光算法
       * Run the PS 8-bit exposure algorithm */
      out_line[px + 0] = exposure_8bit_kernel(r, exposure, offset, gamma);
      out_line[px + 1] = exposure_8bit_kernel(g, exposure, offset, gamma);
      out_line[px + 2] = exposure_8bit_kernel(b, exposure, offset, gamma);
      out_line[px + 3] = sanitize_f(a);
    }

    /* 写出一行扫描线
     * Write the scanline back */
    gegl_buffer_set(out_buf, &row_rect, 0, babl_format("RGBA float"),
                     out_line, GEGL_AUTO_ROWSTRIDE);
  }

  g_free(in_line);
  g_free(out_line);
  return TRUE;
}

static void
gegl_op_class_init(GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS(klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS(klass);

  oclass->prepare = prepare;
  fclass->process = process;

  gegl_operation_class_set_keys(oclass,
    "name",            "lb:exposure",
    "title",           _("Exposure EV"),
    "description",     _("Replicate Photoshop Exposure Adjustment Layer (8-bit sRGB algorithm). Directly works on standard sRGB layers. Do NOT add linear-rgb conversion node before operation."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Exposure EV"),
    NULL);
}

#endif