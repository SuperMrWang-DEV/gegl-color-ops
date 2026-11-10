/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:xyz-multiply
 * menu       XYZ Multiply
 * purpose    以参考色在 XYZ 域做正片叠底，白点可选 D50/D55/D65/D75
 *            Multiply blend against a reference colour in XYZ space; the
 *            white point can be D50/D55/D65/D75.
 * algorithm  sRGB → XYZ 乘叠 → 回 sRGB，opacity 控制混合比例
 *            sRGB -> XYZ, multiply, back to sRGB; 'opacity' sets the blend
 *            amount.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  正片叠底 (Multiply) 的 XYZ 域实现
 *            Multiply blend, implemented in XYZ space
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_color (overlay_color, _("Overlay Color"), "rgba(1.0,1.0,1.0,1.0)")
    description (_("Reference color for XYZ multiply blend"))

property_enum (white_mode, _("White Point"),
               WPSelectType, wp_select_enum, WHITE_D65)
    description (_("CIE standard illuminant white point"))

enum_start (wp_select_enum)
  enum_value (WHITE_D50, "d50", N_("D50 (Print ICC)"))
  enum_value (WHITE_D55, "d55", N_("D55 (Old daylight)"))
  enum_value (WHITE_D65, "d65", N_("D65 (sRGB Screen)"))
  enum_value (WHITE_D75, "d75", N_("D75 Cool proof light"))
enum_end (WPSelectType)

property_double (opacity, _("Opacity"), 1.0)
    value_range (0.0, 1.0)
    ui_range (0.0, 1.0)
    description (_("Blend opacity of multiply layer"))

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_xyz_multiply
#define GEGL_OP_C_SOURCE xyz-multiply.c

#include "gegl-op.h"

typedef struct {
  gfloat X, Y, Z;
} WhitePoint;

/* 四种白点常量
 * the four white-point constants */
static const WhitePoint WP_D50  = {0.96422f, 1.00000f, 0.82521f};
static const WhitePoint WP_D55  = {0.95682f, 1.00000f, 0.92149f};
static const WhitePoint WP_D65  = {0.95047f, 1.00000f, 1.08883f};
static const WhitePoint WP_D75  = {0.94972f, 1.00000f, 1.22638f};

/* Bradford 基础矩阵：D65 ↔ D50
 * Bradford base matrix, D65 <-> D50 */
static const gfloat CAT_BRADFORD[3][3] = {
  { 1.0478112f,  0.0228866f, -0.0501270f},
  { 0.0295424f,  0.9904844f, -0.0170491f},
  {-0.0092345f,  0.0150436f,  0.7521316f}
};
static const gfloat CAT_INV_BRADFORD[3][3] = {
  { 0.9555766f, -0.0230393f,  0.0631636f},
  {-0.0282895f,  1.0099416f,  0.0210077f},
  { 0.0122982f, -0.0204830f,  1.3299098f}
};

static const gfloat MAT_SRGB_TO_XYZ[3][3] = {
  {0.4124564f, 0.3575761f, 0.1804375f},
  {0.2126729f, 0.7151522f, 0.0721750f},
  {0.0193339f, 0.1191920f, 0.9503041f}
};
static const gfloat MAT_XYZ_TO_SRGB[3][3] = {
  { 3.2404542f, -1.5371385f, -0.4985314f},
  {-0.9692660f,  1.8760108f,  0.0415560f},
  { 0.0556434f, -0.2040259f,  1.0572252f}
};

static inline void mat3_mul_vec(const gfloat m[3][3], gfloat x, gfloat y, gfloat z, gfloat *ox, gfloat *oy, gfloat *oz)
{
  *ox = m[0][0] * x + m[0][1] * y + m[0][2] * z;
  *oy = m[1][0] * x + m[1][1] * y + m[1][2] * z;
  *oz = m[2][0] * x + m[2][1] * y + m[2][2] * z;
}

static inline gfloat srgb_ungamma(gfloat val)
{
  if (val <= 0.04045f)
    return val / 12.92f;
  return powf((val + 0.055f) / 1.055f, 2.4f);
}

static inline gfloat srgb_gamma(gfloat val)
{
  if (val <= 0.0031308f)
    return 12.92f * val;
  return 1.055f * powf(val, 1.0f/2.4f) - 0.055f;
}

/* sRGB → D65 XYZ
 * sRGB -> D65 XYZ */
static void srgb_float_to_xyz_d65(gfloat r, gfloat g, gfloat b, gfloat *X, gfloat *Y, gfloat *Z)
{
  gfloat lr = srgb_ungamma(r);
  gfloat lg = srgb_ungamma(g);
  gfloat lb = srgb_ungamma(b);
  mat3_mul_vec(MAT_SRGB_TO_XYZ, lr, lg, lb, X, Y, Z);
}

/* D65 XYZ → sRGB
 * D65 XYZ -> sRGB */
static void xyz_d65_to_srgb_float(gfloat X, gfloat Y, gfloat Z, gfloat *r, gfloat *g, gfloat *b)
{
  gfloat lr, lg, lb;
  mat3_mul_vec(MAT_XYZ_TO_SRGB, X, Y, Z, &lr, &lg, &lb);
  lr = CLAMP(lr, 0.0f, 1.0f);
  lg = CLAMP(lg, 0.0f, 1.0f);
  lb = CLAMP(lb, 0.0f, 1.0f);
  *r = srgb_gamma(lr);
  *g = srgb_gamma(lg);
  *b = srgb_gamma(lb);
}

/* 取选中枚举对应的白点结构体
 * white-point struct for the selected enum */
static WhitePoint get_wp_from_enum(WPSelectType mode)
{
  switch(mode)
  {
    case WHITE_D50: return WP_D50;
    case WHITE_D55: return WP_D55;
    case WHITE_D75: return WP_D75;
    default: return WP_D65;
  }
}

/* 通用：D65 XYZ → 目标白点 XYZ（Bradford）
 * generic: D65 XYZ -> target white-point XYZ (Bradford) */
static void xyz_d65_to_target_wp(gfloat x65, gfloat y65, gfloat z65,
                                 const WhitePoint target_wp,
                                 gfloat *tX, gfloat *tY, gfloat *tZ)
{
  /* 简化的通用 Bradford 适配（业界常用简化实现）
   * simplified generic Bradford adaptation, as commonly implemented */
  gfloat sr = x65 / WP_D65.X;
  gfloat sg = y65 / WP_D65.Y;
  gfloat sb = z65 / WP_D65.Z;

  gfloat tr = target_wp.X / WP_D65.X;
  gfloat tg = target_wp.Y / WP_D65.Y;
  gfloat tb = target_wp.Z / WP_D65.Z;

  mat3_mul_vec(CAT_BRADFORD, sr, sg, sb, &sr, &sg, &sb);
  sr *= tr; sg *= tg; sb *= tb;
  mat3_mul_vec(CAT_INV_BRADFORD, sr, sg, sb, tX, tY, tZ);
}

/* 通用：目标白点 XYZ → D65 XYZ
 * generic: target white-point XYZ -> D65 XYZ */
static void target_wp_to_xyz_d65(gfloat tX, gfloat tY, gfloat tZ,
                                 const WhitePoint target_wp,
                                 gfloat *x65, gfloat *y65, gfloat *z65)
{
  gfloat sr = tX / target_wp.X;
  gfloat sg = tY / target_wp.Y;
  gfloat sb = tZ / target_wp.Z;

  gfloat tr = WP_D65.X / target_wp.X;
  gfloat tg = WP_D65.Y / target_wp.Y;
  gfloat tb = WP_D65.Z / target_wp.Z;

  mat3_mul_vec(CAT_BRADFORD, sr, sg, sb, &sr, &sg, &sb);
  sr *= tr; sg *= tg; sb *= tb;
  mat3_mul_vec(CAT_INV_BRADFORD, sr, sg, sb, x65, y65, z65);
}

/* 混合函数不变
 * blend function unchanged */
static void xyz_multiply_blend(gfloat bX, gfloat bY, gfloat bZ,
                               gfloat oX, gfloat oY, gfloat oZ,
                               const WhitePoint wp,
                               gfloat opacity,
                               gfloat *outX, gfloat *outY, gfloat *outZ)
{
  gfloat alpha = CLAMP(opacity, 0.0f, 1.0f);
  gfloat Xm = (bX * oX) / wp.X;
  gfloat Ym = (bY * oY) / wp.Y;
  gfloat Zm = (bZ * oZ) / wp.Z;
  *outX = bX * (1.0f - alpha) + Xm * alpha;
  *outY = bY * (1.0f - alpha) + Ym * alpha;
  *outZ = bZ * (1.0f - alpha) + Zm * alpha;
}

/* 感知（非线性）格式：公式按 8bit sRGB 伽马域推导，必须拿伽马值，否则 babl
 * 会喂线性光，数值与 PS 对不上
 * Perceptual (non-linear) format: the maths was derived in the 8-bit sRGB
 * gamma domain. Linear light from babl would drift away from Photoshop. */
static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}

static void prepare(GeglOperation *op)
{
  gegl_operation_set_format(op, "input",  perceptual_format(op));
  gegl_operation_set_format(op, "output", perceptual_format(op));
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

  WPSelectType wmode;
  GeglColor *overlay_color;
  gdouble opacity;

  g_object_get(G_OBJECT(op),
    "white-mode", &wmode,
    "overlay-color", &overlay_color,
    "opacity", &opacity,
    NULL);

  gdouble ovr_d, ovg_d, ovb_d, ova_d;
  gegl_color_get_rgba(overlay_color, &ovr_d, &ovg_d, &ovb_d, &ova_d);
  g_object_unref(overlay_color);
  gfloat ovr = (gfloat)ovr_d;
  gfloat ovg = (gfloat)ovg_d;
  gfloat ovb = (gfloat)ovb_d;
  gfloat opac_f = (gfloat)opacity;

  /* 取当前选中的白点
   * fetch the selected white point */
  WhitePoint wp = get_wp_from_enum(wmode);

  /* 预计算叠加色的 XYZ（已转到目标白点空间）
   * precompute the overlay colour in target white-point XYZ */
  gfloat oX65, oY65, oZ65;
  srgb_float_to_xyz_d65(ovr, ovg, ovb, &oX65, &oY65, &oZ65);
  gfloat oX, oY, oZ;
  xyz_d65_to_target_wp(oX65, oY65, oZ65, wp, &oX, &oY, &oZ);

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row = { roi->x, roi->y + y, roi->width, 1 };
    gegl_buffer_get(in_buf, &row, 1.0f, perceptual_format(op),
                     in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint p = x * 4;
      gfloat r = in_line[p+0];
      gfloat g = in_line[p+1];
      gfloat b = in_line[p+2];
      gfloat a = in_line[p+3];

      /* 原图 sRGB → D65 XYZ → 目标白点空间
       * source sRGB -> D65 XYZ -> target white-point space */
      gfloat bX65, bY65, bZ65;
      srgb_float_to_xyz_d65(r, g, b, &bX65, &bY65, &bZ65);
      gfloat bX, bY, bZ;
      xyz_d65_to_target_wp(bX65, bY65, bZ65, wp, &bX, &bY, &bZ);

      /* 在目标白点空间做正片叠底
       * multiply inside the target white-point space */
      gfloat mX, mY, mZ;
      xyz_multiply_blend(bX, bY, bZ, oX, oY, oZ, wp, opac_f, &mX, &mY, &mZ);

      /* 结果转回 D65 → sRGB 输出
       * convert back to D65 -> sRGB output */
      gfloat mX65, mY65, mZ65;
      target_wp_to_xyz_d65(mX, mY, mZ, wp, &mX65, &mY65, &mZ65);
      gfloat or_, og, ob;
      xyz_d65_to_srgb_float(mX65, mY65, mZ65, &or_, &og, &ob);

      out_line[p+0] = CLAMP(or_, 0.0f, 1.0f);
      out_line[p+1] = CLAMP(og, 0.0f, 1.0f);
      out_line[p+2] = CLAMP(ob, 0.0f, 1.0f);
      out_line[p+3] = a;
    }

    gegl_buffer_set(out_buf, &row, 0, perceptual_format(op),
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
    "name",            "lb:xyz-multiply",
    "title",           _("XYZ Multiply"),
    "description",     _("XYZ multiply blend with D50 D55 D65 D75 illuminant white points"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("XYZ Multiply"),
    NULL);
}

#endif