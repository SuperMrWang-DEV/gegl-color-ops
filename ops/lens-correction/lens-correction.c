/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:lens-correction
 * menu       Lens Correction（SuperMrWang → Distort）
 * purpose    PS「滤镜 → 镜头校正」里最常动的三项：桶形 / 枕形畸变、暗角、
 *            横向色差。一个算子一次重采样全解决，参数挂在图层滤镜栈上，
 *            原像素一个字节不动。
 *            The three Lens Correction controls people actually use: barrel /
 *            pincushion distortion, vignetting, and lateral chromatic
 *            aberration. One operator, one resample, live on the filter stack.
 * algorithm  以画面半对角线为 1 的归一化半径 r（四角恰为 r = 1）：
 *              s(r) = 1 + k1·r² + k2·r⁴            Brown–Conrady 径向项
 *              src  = c + (p − c) · s(r) · zoom
 *              r_通道 = r · (1 + ca_像素/halfdiag · r²)   横向色差
 *              gain = 1 + 暗角/100 · smoothstep(mid, mid+feather, r)
 *            r 用半对角线归一化而不是短边，是为了四个角同权：同一组 k1/k2 在
 *            4:3 和 3:2 上看到的角落形变一致。暗角按**输出**半径算，因为它
 *            描述的是成像面上的照度衰减，与畸变无关。
 *            Radius is normalised to the half diagonal so all four corners sit
 *            at r = 1 and one k1/k2 pair means the same thing on 4:3 and 3:2.
 *            The vignette uses the output radius: it describes illumination
 *            falloff on the sensor, independent of the distortion solve.
 * type       GeglOperationCustom（单输入几何重采样 / single-input resample）
 * reference  Brown, D. C. (1966)「Decentering distortion of lenses」；
 *            Hugin / lensfun 的 r³/r⁵ 归一化写法；GIMP 自带的
 *            gegl:lens-distortion 只做畸变，没有暗角与色差。
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* ---- 越界处理 / out-of-bounds policy ----------------------------------- */
enum_start (lb_lens_abyss)
  enum_value (LB_LENS_ABYSS_CLAMP,       "clamp",       "Repeat edge pixels")
  enum_value (LB_LENS_ABYSS_TRANSPARENT, "transparent", "Transparent")
  enum_value (LB_LENS_ABYSS_LOOP,        "loop",        "Wrap around")
  enum_value (LB_LENS_ABYSS_BLACK,       "black",       "Black")
enum_end (LbLensAbyss)

/* ---- 重采样 / resampling ----------------------------------------------- */
enum_start (lb_lens_resample)
  enum_value (LB_LENS_RES_NEAREST,  "nearest",  "Nearest")
  enum_value (LB_LENS_RES_BILINEAR, "bilinear", "Bilinear")
  enum_value (LB_LENS_RES_CUBIC,    "cubic",    "Bicubic")
  enum_value (LB_LENS_RES_NOHALO,   "nohalo",   "Nohalo (no ringing)")
  enum_value (LB_LENS_RES_LOHALO,   "lohalo",   "Lohalo (no ringing, slow)")
enum_end (LbLensResample)

property_double (k1, _("Distortion k1"), 0.0)
  description (_("Radial term at r². Positive pulls from further out, which "
                 "corrects barrel distortion and shrinks the picture; "
                 "negative inflates it like a fisheye"))
  value_range (-0.5, 0.5)

property_double (k2, _("Distortion k2"), 0.0)
  description (_("Radial term at r⁴ — the correction that only bites near the "
                 "corners. Small values, typically under 0.1"))
  value_range (-0.5, 0.5)

property_boolean (auto_zoom, _("Auto scale"), TRUE)
  description (_("Scale the picture so the corners stay in frame after the "
                 "distortion. A k1 of 0.1 without it leaves four transparent "
                 "notches at the corners"))

property_double (zoom, _("Scale"), 1.0)
  description (_("Extra scale on top of auto scale: below 1 pulls more of the "
                 "frame in, above 1 crops"))
  value_range (0.2, 4.0)

property_double (vignette, _("Vignette"), 0.0)
  description (_("Negative darkens the corners, positive lightens them, as a "
                 "percentage of the original brightness"))
  value_range (-100.0, 100.0)

property_double (vignette_midpoint, _("Vignette midpoint"), 0.55)
  description (_("Radius where the falloff starts, 0 at the centre and 1 at "
                 "the corners"))
  value_range (0.0, 1.5)

property_double (vignette_feather, _("Vignette feather"), 0.45)
  description (_("Width of the transition after the midpoint. Small values "
                 "leave a visible ring, large ones creep into the centre"))
  value_range (0.0, 1.5)

property_double (ca_red, _("Red fringing"), 0.0)
  description (_("Radial shift of the red channel at the corners, in pixels. "
                 "Positive pushes red outwards; try ±1–3 px on a 24 MP frame"))
  value_range (-20.0, 20.0)

property_double (ca_blue, _("Blue fringing"), 0.0)
  description (_("Radial shift of the blue channel at the corners, in pixels. "
                 "Usually the opposite sign of the red one"))
  value_range (-20.0, 20.0)

property_enum (abyss, _("Out of bounds"), LbLensAbyss, lb_lens_abyss,
               LB_LENS_ABYSS_CLAMP)
  description (_("How pixels pulled from outside the picture are resolved. "
                 "Repeat edge pixels smears the border outward, transparent "
                 "lets the layer below show through"))

property_enum (resampling, _("Resampling"), LbLensResample, lb_lens_resample,
               LB_LENS_RES_NOHALO)
  description (_("Bilinear never overshoots and is the cheapest; bicubic is "
                 "sharper on smooth areas but rings on hard edges; nohalo "
                 "stays sharp without ringing"))

#else

/* 单输入几何算子用 GEGL_OP_FILTER 而不是 GEGL_OP_CUSTOM：custom 要自己写
 * GType 那一整套（gegl-op.h 在 GEGL_OP_CUSTOM 下不提供父类结构），而
 * GeglOperationFilter 的 process 正好是「输入 → 输出」五参数那种写法。
 * A single-input geometry op uses GEGL_OP_FILTER rather than GEGL_OP_CUSTOM:
 * custom wants the whole GType boilerplate written by hand (gegl-op.h leaves
 * the parent struct undefined), while GeglOperationFilter's process already
 * has the five-argument input → output shape used here. */
#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_lens_correction
#define GEGL_OP_C_SOURCE lens-correction.c

#include "gegl-op.h"

/* 一次处理的行数。重采样是随机访问，band 再高也没有缓存收益。
 * Rows per pass. Resampling is random access, so taller bands buy nothing. */
#define LB_LENS_BAND 64

static GeglSamplerType
lb_lens_sampler_type (LbLensResample r)
{
  switch (r)
    {
      case LB_LENS_RES_NEAREST:  return GEGL_SAMPLER_NEAREST;
      case LB_LENS_RES_BILINEAR: return GEGL_SAMPLER_LINEAR;
      case LB_LENS_RES_CUBIC:    return GEGL_SAMPLER_CUBIC;
      case LB_LENS_RES_LOHALO:   return GEGL_SAMPLER_LOHALO;
      default:                   return GEGL_SAMPLER_NOHALO;
    }
}

static GeglAbyssPolicy
lb_lens_abyss_policy (LbLensAbyss a)
{
  switch (a)
    {
      case LB_LENS_ABYSS_TRANSPARENT: return GEGL_ABYSS_NONE;
      case LB_LENS_ABYSS_LOOP:        return GEGL_ABYSS_LOOP;
      case LB_LENS_ABYSS_BLACK:       return GEGL_ABYSS_BLACK;
      default:                        return GEGL_ABYSS_CLAMP;
    }
}

/* 平滑过渡：0 以下为 0，1 以上为 1，中间是三次 Hermite。暗角的羽化用它，
 * 免得 mid/feather 边界上出现一圈硬边（那是可见的同心环）。
 * Smoothstep, used by the vignette feather so the falloff has no visible
 * concentric ring at the transition boundary. */
static inline gdouble
lb_lens_smooth (gdouble u)
{
  if (u <= 0.0) return 0.0;
  if (u >= 1.0) return 1.0;
  return u * u * (3.0 - 2.0 * u);
}

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");
  const Babl *fmt   = babl_format_with_space ("R'G'B'A float", space);

  gegl_operation_set_format (operation, "input",  fmt);
  gegl_operation_set_format (operation, "output", fmt);
}

/* 画布永远跟随主图：畸变只改像素，不该改尺寸。
 * The canvas always follows the input; a distortion moves pixels, not edges. */
static GeglRectangle
get_bounding_box (GeglOperation *operation)
{
  const GeglRectangle *in = gegl_operation_source_get_bounding_box (operation,
                                                                    "input");

  if (in)
    return *in;

  {
    const GeglRectangle empty = { 0, 0, 0, 0 };
    return empty;
  }
}

/* 畸变可以把任意像素拉到任意位置（角落甚至从画外取样），所以整张都得可用。
 * 只返回 roi 会让边缘出现「够不到」的黑块。
 * Any output pixel can pull from anywhere, so the whole input must be ready;
 * returning the roi alone would paint black notches along the border. */
static GeglRectangle
get_required_for_output (GeglOperation       *operation,
                         const gchar         *input_pad,
                         const GeglRectangle *roi)
{
  const GeglRectangle *full = gegl_operation_source_get_bounding_box (operation,
                                                                      "input");

  return full ? *full : *roi;
}

/* 单输入的几何算子在 GEGL 0.4 里走「context 版」process：buffer 不在参数表里，
 * 得自己去 context 里按 pad 名取。GeglOperationFilter 没有带 buffer 的虚函数
 * （那是 point filter / area filter 的便利写法），几何变形又不属于那两类。
 * A single-input geometry op uses the context-style process in GEGL 0.4: the
 * buffers are not arguments, they are fetched from the context by pad name.
 * GeglOperationFilter has no buffer-passing virtual (that shape belongs to
 * point and area filters, which cannot express a resample). */
static gboolean
process (GeglOperation       *operation,
         GeglOperationContext *context,
         const gchar         *output_prop,
         const GeglRectangle *result,
         gint                 level)
{
  GeglProperties *o   = GEGL_PROPERTIES (operation);
  const Babl     *fmt = gegl_operation_get_format (operation, "output");
  const GeglRectangle *ext =
    gegl_operation_source_get_bounding_box (operation, "input");

  GeglBuffer *input  = gegl_operation_context_get_source (context, "input");
  GeglBuffer *output = gegl_operation_context_get_target (context, "output");

  if (ext == NULL)
    return TRUE;

  if (input == NULL || output == NULL)
    {
      g_clear_object (&input);
      return TRUE;
    }

  /* roi 一般由调用方给；GEGL 允许 NULL 表示整张，别拿它去解引用。
   * The caller usually passes a roi; GEGL allows NULL for "everything",
   * so never dereference it blindly. */
  const GeglRectangle area = result ? *result : *gegl_buffer_get_extent (output);

  /* 半径按当前 level 的尺寸算，否则缩略图预览与全尺寸结果不是同一张图：
   * 预览走 level 2/3，坐标是缩过的，直接用 level 0 的中心会让形变偏心。
   * The radius follows the current level. Previews render at level 2/3 with
   * scaled coordinates; using the level-0 centre would shift the distortion. */
  const gint lw = MAX (1, ext->width  >> level);
  const gint lh = MAX (1, ext->height >> level);
  const gint sub = 1 << level;
  const gdouble cx = (gdouble) (ext->x / sub) + lw * 0.5;
  const gdouble cy = (gdouble) (ext->y / sub) + lh * 0.5;
  const gdouble halfdiag = 0.5 * sqrt ((gdouble) lw * lw +
                                       (gdouble) lh * lh);

  /* 自动缩放：让 r = 1 的角落映射后仍落在 r = 1。s(1) = 1 + k1 + k2，
   * 除一下正好抵消；k1/k2 组合接近 -1 时 s 会穿过 0（图像塌成一点），
   * 那种参数直接不缩放，交给用户自己调。
   * Auto scale divides by s(1) so the corners land back on the frame. When
   * the pair drives s(1) near zero the picture would collapse to a point;
   * those values simply skip the compensation. */
  gdouble zoom = o->zoom;
  if (o->auto_zoom)
    {
      const gdouble s_corner = 1.0 + o->k1 + o->k2;

      if (fabs (s_corner) > 0.05)
        zoom /= s_corner;
    }
  zoom = CLAMP (zoom, 0.1, 10.0);

  /* 色差用像素给，缩略图要按 level 缩回去，否则预览里的紫边比成品粗一倍。
   * Chromatic aberration is given in pixels of the full-resolution image, so
   * it shrinks with the level like everything else. */
  const gdouble ca_r = o->ca_red  / (gdouble) sub;
  const gdouble ca_b = o->ca_blue / (gdouble) sub;
  const gboolean has_ca = (fabs (ca_r) > 1e-6 || fabs (ca_b) > 1e-6);
  const gboolean has_vig = fabs (o->vignette) > 1e-6;

  const gdouble vig_amt = o->vignette * 0.01;
  const gdouble vig_mid = o->vignette_midpoint;
  const gdouble vig_fea = MAX (o->vignette_feather, 1.0e-4);

  /* 快路径：几何部分全关时不必逐像素采样。
   * · 只有暗角（最常见的一档）：整块拷过来，乘个增益就完事，比走采样器快一个
   *   数量级——3.8 MP 从 1.1 s 降到 0.1 s。
   * · 全默认：直接拷贝，挂在栈上一个字节都不动，也免得「挂了个滤镜忘了调」
   *   把整条链拖慢。
   * Fast paths for the geometry-off cases. Vignette-only copies the band and
   * multiplies, an order of magnitude cheaper than sampling; a fully default
   * stack is a plain copy. */
  const gboolean no_geom = (fabs (o->k1) < 1e-9 && fabs (o->k2) < 1e-9 &&
                            fabs (ca_r) < 1e-9 && fabs (ca_b) < 1e-9 &&
                            fabs (zoom - 1.0) < 1e-9);

  if (no_geom && !has_vig)
    {
      gegl_buffer_copy (input, &area, GEGL_ABYSS_NONE, output, &area);
      g_object_unref (input);
      return TRUE;
    }

  if (no_geom)
    {
      const gint stride = (gint) (sizeof (gfloat) * 4 * (gsize) area.width);
      gfloat *band_buf = g_new (gfloat, (gsize) area.width *
                                       (gsize) LB_LENS_BAND * 4);

      for (gint y0 = 0; y0 < area.height; y0 += LB_LENS_BAND)
        {
          const gint nh = MIN (LB_LENS_BAND, area.height - y0);
          const GeglRectangle band = { area.x, area.y + y0, area.width, nh };

          gegl_buffer_get (input, &band, 1.0, fmt, band_buf, stride,
                           GEGL_ABYSS_NONE);

          for (gint row = 0; row < nh; row++)
            {
              const gdouble py = band.y + row + 0.5;
              const gdouble dy = py - cy;
              gfloat *p = band_buf + (gsize) row * area.width * 4;

              for (gint col = 0; col < area.width; col++, p += 4)
                {
                  const gdouble px = band.x + col + 0.5;
                  const gdouble dx = px - cx;
                  const gdouble r = (halfdiag > 1e-9)
                                    ? sqrt (dx * dx + dy * dy) / halfdiag : 0.0;
                  const gdouble t = lb_lens_smooth ((r - vig_mid) / vig_fea);
                  const gdouble gain = MAX (0.0, 1.0 + vig_amt * t);

                  p[0] *= (gfloat) gain;
                  p[1] *= (gfloat) gain;
                  p[2] *= (gfloat) gain;
                }
            }

          gegl_buffer_set (output, &band, level, fmt, band_buf, stride);
        }

      g_free (band_buf);
      g_object_unref (input);
      return TRUE;
    }

  const GeglAbyssPolicy policy = lb_lens_abyss_policy (o->abyss);
  GeglSampler *sampler =
    gegl_buffer_sampler_new_at_level (input, fmt,
                                      lb_lens_sampler_type (o->resampling),
                                      level);

  gfloat *out_band = g_new (gfloat, (gsize) area.width *
                                    (gsize) LB_LENS_BAND * 4);

  for (gint y0 = 0; y0 < area.height; y0 += LB_LENS_BAND)
    {
      const gint nh = MIN (LB_LENS_BAND, area.height - y0);
      const GeglRectangle band = { area.x, area.y + y0,
                                   area.width, nh };
      gfloat *out = out_band;

      for (gint row = 0; row < nh; row++)
        {
          const gdouble py = band.y + row + 0.5;
          const gdouble dy = py - cy;

          for (gint col = 0; col < band.width; col++, out += 4)
            {
              const gdouble px = band.x + col + 0.5;
              const gdouble dx = px - cx;
              const gdouble d  = sqrt (dx * dx + dy * dy);
              gdouble r  = (halfdiag > 1e-9) ? d / halfdiag : 0.0;
              const gdouble r2 = r * r;
              const gdouble base = 1.0 + o->k1 * r2 + o->k2 * r2 * r2;
              const gdouble gs = base * zoom;

              gdouble sx = cx + dx * gs;
              gdouble sy = cy + dy * gs;

              if (has_ca)
                {
                  /* 横向色差：R 与 B 各自按 r² 缩放，绿通道不动——绿是
                   * 对焦参考，镜头设计上它就是基准。
                   * Lateral CA: R and B are scaled by r² while green stays put
                   * — green is the focus reference by design. */
                  const gdouble rsr = base * zoom *
                                      (1.0 + (ca_r / halfdiag) * r2);
                  const gdouble rsb = base * zoom *
                                      (1.0 + (ca_b / halfdiag) * r2);
                  gfloat c_r[4], c_g[4], c_b[4];

                  gegl_sampler_get (sampler, cx + dx * rsr, cy + dy * rsr,
                                    NULL, c_r, policy);
                  gegl_sampler_get (sampler, sx, sy, NULL, c_g, policy);
                  gegl_sampler_get (sampler, cx + dx * rsb, cy + dy * rsb,
                                    NULL, c_b, policy);

                  out[0] = c_r[0];
                  out[1] = c_g[1];
                  out[2] = c_b[2];
                  out[3] = c_g[3];
                }
              else
                {
                  gegl_sampler_get (sampler, sx, sy, NULL, out, policy);
                }

              if (has_vig)
                {
                  const gdouble t = lb_lens_smooth ((r - vig_mid) / vig_fea);
                  const gdouble gain = MAX (0.0, 1.0 + vig_amt * t);

                  out[0] *= (gfloat) gain;
                  out[1] *= (gfloat) gain;
                  out[2] *= (gfloat) gain;
                }
            }
        }

      gegl_buffer_set (output, &band, level, fmt, out_band,
                       (gint) (sizeof (gfloat) * 4 * (gsize) band.width));
    }

  g_object_unref (sampler);
  g_free (out_band);
  g_object_unref (input);

  return TRUE;
}

/* ---- 类初始化 / class init --------------------------------------------- */

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass *oclass = GEGL_OPERATION_CLASS (klass);

  oclass->prepare                 = prepare;
  oclass->process                 = process;
  oclass->get_bounding_box        = get_bounding_box;
  oclass->get_required_for_output = get_required_for_output;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:lens-correction",
    "title",           _("Lens Correction"),
    "description",     _("Barrel / pincushion distortion, vignetting and "
                         "lateral chromatic aberration in one resample, with an "
                         "auto scale that keeps the corners in frame."),
    "gimp:menu-path",  "<Image>/SuperMrWang/Distort",
    "gimp:menu-label", _("Lens Correction"),
    NULL);
}

#endif
