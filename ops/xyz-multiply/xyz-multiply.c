/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:xyz-multiply
 * menu       Photo Filter
 * purpose    PS「照片滤镜」的复刻：滤镜色在 XYZ 域做正片叠底，密度当不透明度，
 *            另有保留明度开关。
 *            Photoshop's Photo Filter: multiply the filter colour in XYZ space,
 *            density as opacity, with an optional preserve-luminosity switch.
 * algorithm  与 PS 实测对齐（标定记录见 photo-filter-cal/）：
 *              1. 线性化 sRGB，用标准 Bradford 转到 D50 的 XYZ
 *              2. 逐通道乘 k = (1-d) + d·(filt_XYZ / W50)，d = 密度
 *              3. 转回编码值；若开了保留明度，再做 W3C 的 SetLum + ClipColor
 *            前两步在线性 sRGB 里等价于一个常数 3×3 矩阵
 *            M = XYZ2sRGB · A⁻¹ · diag(k) · A · sRGB2XYZ，每 process 只算一次；
 *            逐像素只剩 3 次查表 + 9 乘 6 加 + 3 次查表（+ 保留明度的几条）。
 *            Matches Photoshop, measured end to end: linearise, adapt to D50
 *            XYZ with standard Bradford, multiply per channel by
 *            k = (1-d)+d·(filt/W50), re-encode, then optionally restore the
 *            encoded Rec.601 luma. Steps 1-2 collapse into one constant 3x3
 *            matrix built once per process call.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  PS 照片滤镜标定：photo-filter-cal/（灰阶 + 彩色探针，12 + 6 档）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_color (overlay_color, _("Filter Color"), "rgba(1.0,1.0,1.0,1.0)")
    description (_("Filter colour, i.e. the Photo Filter preset colour"))

property_enum (white_mode, _("White Point"),
               WPSelectType, wp_select_enum, WHITE_D50)
    description (_("CIE standard illuminant white point (Photoshop uses D50)"))

enum_start (wp_select_enum)
  enum_value (WHITE_D50, "d50", N_("D50 (Photoshop / print ICC)"))
  enum_value (WHITE_D55, "d55", N_("D55 (Old daylight)"))
  enum_value (WHITE_D65, "d65", N_("D65 (sRGB screen)"))
  enum_value (WHITE_D75, "d75", N_("D75 Cool proof light"))
enum_end (WPSelectType)

property_double (opacity, _("Density"), 1.0)
    value_range (0.0, 1.0)
    ui_range (0.0, 1.0)
    description (_("Filter density (Photoshop's 0-100% divided by 100)"))

property_boolean (preserve_luminosity, _("Preserve Luminosity"), TRUE)
    description (_("Keep the original luminance, like Photoshop's default checkbox"))

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

/* Bradford 锥响应矩阵及其逆。
 *
 * 老代码里有一组 CAT_BRADFORD（1.0478112, 0.0228866, …）被当成"锥响应"用，其实
 * 那组数正是 **D65→D50 的适配矩阵本身**（拿下面这套矩阵按 D50 白点算一遍就能
 * 复现到 7e-8）。把它当锥响应喂进去，推出的 A 完全是另一个矩阵，D50 档的偏色
 * 就是这么来的。现在按标准锥响应现算，4 个白点都成立。
 *
 * Bradford cone response. The old CAT_BRADFORD table (1.0478112, 0.0228866, …)
 * is the D65->D50 adaptation matrix itself, not the cone response -- using it as
 * the cone response produced a completely different A, which is where the D50
 * colour shift came from. */
static const gfloat BRADFORD_CONE[3][3] = {
  { 0.8951000f,  0.2664000f, -0.1614000f},
  {-0.7502000f,  1.7135000f,  0.0367000f},
  { 0.0389000f, -0.0685000f,  1.0296000f}
};
static const gfloat BRADFORD_CONE_INV[3][3] = {
  { 0.9869929f, -0.1470543f,  0.1599627f},
  { 0.4323053f,  0.5183603f,  0.0492912f},
  {-0.0085287f,  0.0400428f,  0.9684867f}
};

static const gfloat MAT_SRGB_TO_XYZ[3][3] = {
  {0.4124564f, 0.3575761f, 0.1804375f},
  {0.2126729f, 0.7151522f, 0.0721750f},
  {0.0193339f, 0.1191920f, 0.9503041f}
};
static const gfloat MAT_XYZ_TO_SRGB[3][3] = {
  { 3.2404542f, -1.5371385f, -0.4985314f},
  {-0.9692660f, 1.8760108f,  0.0415560f},
  { 0.0556434f, -0.2040259f,  1.0572252f}
};

static inline void mat3_mul_vec(const gfloat m[3][3], gfloat x, gfloat y, gfloat z, gfloat *ox, gfloat *oy, gfloat *oz)
{
  *ox = m[0][0] * x + m[0][1] * y + m[0][2] * z;
  *oy = m[1][0] * x + m[1][1] * y + m[1][2] * z;
  *oz = m[2][0] * x + m[2][1] * y + m[2][2] * z;
}

static inline void mat3_mul_mat(const gfloat a[3][3], const gfloat b[3][3], gfloat out[3][3])
{
  for (gint i = 0; i < 3; i++)
    for (gint j = 0; j < 3; j++)
      out[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j];
}

/* ---------------------------------------------------------------------------
 * sRGB 传递函数查表
 * sRGB transfer-function lookup tables
 *
 * powf 在 MSVC 上要走 double 版的 pow，一次 50 ns 上下；逐像素 6 次就吃掉
 * 大部分时间。两条曲线都是光滑的（sRGB 在拐点处 C¹ 连续），4097 项线性插值
 * 的误差在 1e-7 量级，远低于 1 个 16 位 LSB。
 *
 * powf on MSVC ends up in the double-precision pow and costs ~50 ns; six of
 * them per pixel dominated the runtime. Both curves are smooth (sRGB is C1 at
 * the knee), so a 4097-entry lerped table is accurate to ~1e-7 -- far below one
 * 16-bit LSB.
 * ------------------------------------------------------------------------- */
#define XYZ_LUTN 4097

static gfloat xyz_ungamma_lut[XYZ_LUTN];
static gfloat xyz_gamma_lut[XYZ_LUTN];

static void
ensure_srgb_luts (void)
{
  static gsize once = 0;

  if (g_once_init_enter (&once))
    {
      for (gint i = 0; i < XYZ_LUTN; i++)
        {
          gfloat v = (gfloat) i / (gfloat) (XYZ_LUTN - 1);

          xyz_ungamma_lut[i] = (v <= 0.04045f)
            ? v / 12.92f
            : powf ((v + 0.055f) / 1.055f, 2.4f);
          xyz_gamma_lut[i] = (v <= 0.0031308f)
            ? 12.92f * v
            : 1.055f * powf (v, 1.0f / 2.4f) - 0.055f;
        }
      g_once_init_leave (&once, 1);
    }
}

/* 查表 + 线性插值；调用方保证 0 <= v <= 1
 * lookup with linear interpolation; callers guarantee 0 <= v <= 1 */
static inline gfloat
lut_lerp (const gfloat *lut, gfloat v)
{
  gfloat f = v * (gfloat) (XYZ_LUTN - 1);
  gint   i = (gint) f;

  if (i >= XYZ_LUTN - 1)
    return lut[XYZ_LUTN - 1];
  f -= (gfloat) i;
  return lut[i] + (lut[i + 1] - lut[i]) * f;
}

/* sRGB 伽马域 → 线性 / sRGB gamma -> linear */
static inline gfloat
srgb_ungamma (gfloat v)
{
  /* 越界值（HDR、上一个算子的负数结果）走精确式，正常图不会进来
   * out-of-range values (HDR, negative output of an earlier op) take the
   * exact path; normal images never get here */
  if (v < 0.0f || v > 1.0f)
    return (v <= 0.04045f) ? v / 12.92f
                           : powf ((v + 0.055f) / 1.055f, 2.4f);
  return lut_lerp (xyz_ungamma_lut, v);
}

/* 线性 → sRGB 伽马域（含 [0,1] 夹紧，与原实现一致）
 * linear -> sRGB gamma, clamping to [0,1] like the original */
static inline gfloat
srgb_gamma (gfloat v)
{
  if (v <= 0.0f)
    return 0.0f;
  if (v >= 1.0f)
    return 1.0f;
  if (v <= 0.0031308f)
    return 12.92f * v;
  return lut_lerp (xyz_gamma_lut, v);
}

/* sRGB 伽马域 → D65 XYZ（进程内只用于叠加色一次）
 * sRGB gamma -> D65 XYZ; only used once per process for the overlay colour */
static void srgb_float_to_xyz_d65(gfloat r, gfloat g, gfloat b, gfloat *X, gfloat *Y, gfloat *Z)
{
  mat3_mul_vec(MAT_SRGB_TO_XYZ,
               srgb_ungamma(r), srgb_ungamma(g), srgb_ungamma(b), X, Y, Z);
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

/* 标准 Bradford 白点适配（D65 ↔ 目标白点），预先乘成一个 3×3：
 *
 *   A   = B⁻¹ · diag(ρ_wp / ρ_65) · B      （D65 → 目标白点）
 *   A⁻¹ = B⁻¹ · diag(ρ_65 / ρ_wp) · B
 *
 * 其中 ρ = B·W 是两个白点在 Bradford 锥响应空间里的坐标。
 *
 * 旧写法是 `B⁻¹ · diag(wp/W65) · B · diag(1/W65)` —— 既没走锥响应（直接拿
 * 白点坐标当锥响应），又多除了一次 W65，于是 D65 时 A 退化成 diag(1/W65) 而
 * 不是单位阵，A·A⁻¹ 也偏离单位阵最多 0.16。α=0 时画面仍会偏色就是它造成的。
 * 改成标准形式后 A(D65) = I 严格成立。
 *
 * Standard Bradford adaptation folded into one 3x3. The old expression skipped
 * the cone response and divided by the white point twice, so A degenerated to
 * diag(1/W65) at D65 and A·A⁻¹ was off by up to 0.16 -- which is why alpha=0
 * still shifted colours. The standard form gives A(D65) = I exactly.
 * ------------------------------------------------------------------------- */
static void
wp_matrix (const WhitePoint wp, gboolean inverse, gfloat out[3][3])
{
  const gfloat w[3]  = { wp.X, wp.Y, wp.Z };
  const gfloat d[3]  = { WP_D65.X, WP_D65.Y, WP_D65.Z };
  gfloat cs[3], cd[3], D[3][3] = {{0.0f}}, t[3][3];

  mat3_mul_vec (BRADFORD_CONE, d[0], d[1], d[2], &cs[0], &cs[1], &cs[2]);
  mat3_mul_vec (BRADFORD_CONE, w[0], w[1], w[2], &cd[0], &cd[1], &cd[2]);

  for (gint i = 0; i < 3; i++)
    D[i][i] = inverse ? (cs[i] / cd[i]) : (cd[i] / cs[i]);

  mat3_mul_mat (D, BRADFORD_CONE, t);
  mat3_mul_mat (BRADFORD_CONE_INV, t, out);
}

/* 目标白点空间里「正片叠底 + 不透明度」合成出的逐通道系数
 * per-channel factor the multiply layer and the opacity produce in the
 * target white-point space: b·(1-a) + (b·o/wp)·a  =  b · ((1-a) + a·o/wp) */
static void
blend_factors (const WhitePoint wp, gfloat oX, gfloat oY, gfloat oZ,
               gfloat alpha, gfloat k[3])
{
  const gfloat o[3] = { oX, oY, oZ };
  const gfloat w[3] = { wp.X, wp.Y, wp.Z };

  for (gint i = 0; i < 3; i++)
    k[i] = (1.0f - alpha) + alpha * (o[i] / w[i]);
}

/* 整条链路的合成矩阵：线性 sRGB → 线性 sRGB
 * the whole chain as one linear-sRGB -> linear-sRGB matrix */
static void
build_chain_matrix (const WhitePoint wp, gfloat oX, gfloat oY, gfloat oZ,
                    gfloat alpha, gfloat M[3][3])
{
  gfloat A[3][3], Ai[3][3], K[3][3] = {{0.0f}};
  gfloat t1[3][3], t2[3][3];
  gfloat k[3];

  wp_matrix (wp, FALSE, A);
  wp_matrix (wp, TRUE,  Ai);
  blend_factors (wp, oX, oY, oZ, alpha, k);

  K[0][0] = k[0];
  K[1][1] = k[1];
  K[2][2] = k[2];

  mat3_mul_mat (A, MAT_SRGB_TO_XYZ, t1);   /* sRGB 线性 → 目标白点空间 */
  mat3_mul_mat (K, t1, t2);                /* 正片叠底 + 不透明度 */
  mat3_mul_mat (Ai, t2, t1);               /* 回到 D65 XYZ */
  mat3_mul_mat (MAT_XYZ_TO_SRGB, t1, M);   /* 回到线性 sRGB */
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
  gboolean preserve_lum;

  g_object_get(G_OBJECT(op),
    "white-mode", &wmode,
    "overlay-color", &overlay_color,
    "opacity", &opacity,
    "preserve-luminosity", &preserve_lum,
    NULL);

  gdouble ovr_d, ovg_d, ovb_d, ova_d;
  gegl_color_get_rgba(overlay_color, &ovr_d, &ovg_d, &ovb_d, &ova_d);
  g_object_unref(overlay_color);
  gfloat opac_f = CLAMP((gfloat)opacity, 0.0f, 1.0f);

  const Babl *fmt = perceptual_format(op);
  gint  stride    = roi->width * 4;

  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  /* 白点矩阵修好之后 A·A⁻¹ = I，α=0 时链路严格恒等，可以安全走直通
   * with the white-point matrix fixed, A·A⁻¹ = I, so alpha=0 is a true identity */
  if (opac_f <= 0.0f)
  {
    for (gint y = 0; y < roi->height; y++)
    {
      GeglRectangle row = { roi->x, roi->y + y, roi->width, 1 };
      gegl_buffer_get(in_buf, &row, 1.0f, fmt, in_line,
                      GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);
      gegl_buffer_set(out_buf, &row, 0, fmt, in_line, GEGL_AUTO_ROWSTRIDE);
    }
    g_free(in_line);
    g_free(out_line);
    return TRUE;
  }

  ensure_srgb_luts ();

  /* 白点 + 叠加色 + 不透明度 → 一个常数矩阵，每次 process 只算一次
   * white point + overlay + opacity -> one constant matrix, once per call */
  WhitePoint wp = get_wp_from_enum(wmode);

  gfloat oX65, oY65, oZ65;
  srgb_float_to_xyz_d65((gfloat)ovr_d, (gfloat)ovg_d, (gfloat)ovb_d,
                        &oX65, &oY65, &oZ65);
  gfloat A65[3][3], oX, oY, oZ;             /* 叠加色转到目标白点空间 */
  wp_matrix (wp, FALSE, A65);
  mat3_mul_vec (A65, oX65, oY65, oZ65, &oX, &oY, &oZ);

  gfloat M[3][3];
  build_chain_matrix (wp, oX, oY, oZ, opac_f, M);

  const gfloat m00 = M[0][0], m01 = M[0][1], m02 = M[0][2];
  const gfloat m10 = M[1][0], m11 = M[1][1], m12 = M[1][2];
  const gfloat m20 = M[2][0], m21 = M[2][1], m22 = M[2][2];

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row = { roi->x, roi->y + y, roi->width, 1 };
    gegl_buffer_get(in_buf, &row, 1.0f, fmt, in_line,
                    GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint p = x * 4;
      gfloat lr = srgb_ungamma(in_line[p+0]);
      gfloat lg = srgb_ungamma(in_line[p+1]);
      gfloat lb = srgb_ungamma(in_line[p+2]);

      gfloat X = m00 * lr + m01 * lg + m02 * lb;
      gfloat Y = m10 * lr + m11 * lg + m12 * lb;
      gfloat Z = m20 * lr + m21 * lg + m22 * lb;

      gfloat r8 = srgb_gamma(X);
      gfloat g8 = srgb_gamma(Y);
      gfloat b8 = srgb_gamma(Z);

      if (preserve_lum)
        {
          /* W3C / PDF 的 Luminosity 混合模式：SetLum + ClipColor，权重是
           * Rec.601 的 0.3/0.59/0.11，全部作用在**编码值**上。
           *
           * 这是实测出来的：128 灰 + 纯红密度 100% 时 PS 给 (218,90,90)，
           * SetLum 手算恰是 (217.6, 89.6, 89.6)；换成 Lab 保 L*、乘性还原、
           * Rec.709 权重都对不上（中位误差 5～45 码）。
           *
           * W3C Luminosity blending on encoded values with Rec.601 weights.
           * 128 grey through a 100% red filter gives (218,90,90) in Photoshop,
           * which is exactly what SetLum computes. */
          gfloat target = 0.3f * in_line[p+0] + 0.59f * in_line[p+1] + 0.11f * in_line[p+2];
          gfloat dsh    = target - (0.3f * r8 + 0.59f * g8 + 0.11f * b8);

          r8 += dsh;
          g8 += dsh;
          b8 += dsh;

          gfloat lo = MIN (r8, MIN (g8, b8));
          gfloat hi = MAX (r8, MAX (g8, b8));

          if (lo < 0.0f)
            {
              gfloat k = (target - lo > 1e-6f) ? target / (target - lo) : 0.0f;
              r8 = target + (r8 - target) * k;
              g8 = target + (g8 - target) * k;
              b8 = target + (b8 - target) * k;
            }

          if (hi > 1.0f)
            {
              gfloat k = (hi - target > 1e-6f) ? (1.0f - target) / (hi - target) : 0.0f;
              r8 = target + (r8 - target) * k;
              g8 = target + (g8 - target) * k;
              b8 = target + (b8 - target) * k;
            }
        }

      out_line[p+0] = r8;
      out_line[p+1] = g8;
      out_line[p+2] = b8;
      out_line[p+3] = in_line[p+3];
    }

    gegl_buffer_set(out_buf, &row, 0, fmt, out_line, GEGL_AUTO_ROWSTRIDE);
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
    "title",           _("Photo Filter"),
    "description",     _("Photoshop's Photo Filter: filter colour multiplied in XYZ space, "
                         "with density and preserve-luminosity"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Photo Filter"),
    NULL);
}

#endif
