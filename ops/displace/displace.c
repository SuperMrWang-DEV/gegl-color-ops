/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:displace
 * menu       Displace
 * purpose    按位移图重采样图像。相对 GEGL 自带的 gegl:displace，这里修掉四件事：
 *            单张图同时给水平/垂直、位移图不强制乘 alpha、位移图覆盖不到的
 *            区域原样输出而不是硬移、默认用无振铃的采样器。
 *            Resamples the image through a displacement map. Compared with
 *            GEGL's own gegl:displace this fixes four things: one map drives
 *            both axes, the map is not silently multiplied by its alpha,
 *            areas the map does not cover pass through instead of jumping,
 *            and the default sampler does not ring.
 * algorithm  逐像素求出源坐标再采样：
 *              t = remap(v; black, mid, white)，mid 两侧各自归一到 -1..+1
 *              dx = t_x * amount-x * unit，dy = t_y * amount-y * unit
 *              src = (x + 0.5 + dx, y + 0.5 + dy)
 *            矢量场模式取位移图的 R 作 X、G 作 Y（0 = 不动）；标量模式取同一
 *            个通道分别乘 amount-x / amount-y，对应「一张灰度图 + 两个比例」
 *            的传统置换。单位可选像素或长边百分比，后者换分辨率不用重调。
 *            Per pixel: remap the map value so the midpoint lands on zero,
 *            multiply by the amount, then pull the source pixel with a
 *            sampler. Vector mode reads R as X and G as Y (0 = no shift);
 *            scalar mode reads one channel and applies it to both axes with
 *            separate amounts, the classic "one grey map, two ratios" setup.
 * type       GeglOperationComposer（input + aux 双输入 / two inputs）
 * reference  GEGL operations/common-gpl3+/displace.c
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* ---- 单位 / amount unit ------------------------------------------------ */
enum_start (lb_disp_units)
  enum_value (LB_DISP_UNIT_PIXEL,   "pixel",   "Pixels")
  enum_value (LB_DISP_UNIT_PERCENT, "percent", "Percent of long edge")
enum_end (LbDispUnits)

/* ---- 位移图的读法 / how the map is read -------------------------------- */
enum_start (lb_disp_map)
  enum_value (LB_DISP_MAP_VECTOR, "vector", "Vector (R = X, G = Y)")
  enum_value (LB_DISP_MAP_SCALAR, "scalar", "Single channel")
enum_end (LbDispMap)

/* ---- 标量模式取哪个通道 / channel used by scalar mode ------------------- */
enum_start (lb_disp_channel)
  enum_value (LB_DISP_CH_LUMA,  "luma",  "Luminance")
  enum_value (LB_DISP_CH_RED,   "red",   "Red")
  enum_value (LB_DISP_CH_GREEN, "green", "Green")
  enum_value (LB_DISP_CH_BLUE,  "blue",  "Blue")
  enum_value (LB_DISP_CH_ALPHA, "alpha", "Alpha")
enum_end (LbDispChannel)

/* ---- 越界处理 / out-of-bounds policy ----------------------------------- */
enum_start (lb_disp_abyss)
  enum_value (LB_DISP_ABYSS_LOOP,        "loop",        "Wrap around")
  enum_value (LB_DISP_ABYSS_CLAMP,       "clamp",       "Repeat edge pixels")
  enum_value (LB_DISP_ABYSS_TRANSPARENT, "transparent", "Transparent")
  enum_value (LB_DISP_ABYSS_BLACK,       "black",       "Black")
  enum_value (LB_DISP_ABYSS_WHITE,       "white",       "White")
enum_end (LbDispAbyss)

/* ---- 重采样 / resampling ----------------------------------------------- */
enum_start (lb_disp_resample)
  enum_value (LB_DISP_RES_NEAREST,  "nearest",  "Nearest")
  enum_value (LB_DISP_RES_BILINEAR, "bilinear", "Bilinear")
  enum_value (LB_DISP_RES_CUBIC,    "cubic",    "Bicubic")
  enum_value (LB_DISP_RES_NOHALO,   "nohalo",   "Nohalo (no ringing)")
  enum_value (LB_DISP_RES_LOHALO,   "lohalo",   "Lohalo (no ringing, slow)")
enum_end (LbDispResample)

property_double (amount_x, _("Horizontal amount"), 0.0)
  description (_("Displacement along X for a map value at the white point"))
  value_range (-5000.0, 5000.0)

property_double (amount_y, _("Vertical amount"), 0.0)
  description (_("Displacement along Y for a map value at the white point"))
  value_range (-5000.0, 5000.0)

property_enum (units, _("Amount unit"), LbDispUnits, lb_disp_units,
               LB_DISP_UNIT_PIXEL)
  description (_("Pixels stay fixed when the image is resized; a percentage "
                 "of the long edge scales with it"))

property_enum (map_mode, _("Map mode"), LbDispMap, lb_disp_map,
               LB_DISP_MAP_VECTOR)
  description (_("Vector reads R as X and G as Y, so one RGBA map drives both "
                 "axes. Single channel reads one channel and feeds it to both "
                 "amounts, the classic grey-map setup"))

property_enum (map_channel, _("Map channel"), LbDispChannel, lb_disp_channel,
               LB_DISP_CH_LUMA)
  description (_("Channel read in single channel mode"))
  ui_meta ("sensitive", "map-mode {scalar}")

property_double (black_point, _("Black point"), 0.0)
  description (_("Map value that means the full negative displacement"))
  value_range (-2.0, 2.0)

property_double (midpoint, _("Midpoint"), 0.5)
  description (_("Map value that means no displacement. Grey maps use 0.5; "
                 "vector fields that are zero at rest use 0"))
  value_range (-1.0, 2.0)

property_double (white_point, _("White point"), 1.0)
  description (_("Map value that means the full positive displacement"))
  value_range (-1.0, 3.0)

property_boolean (alpha_weight, _("Weight by map alpha"), FALSE)
  description (_("Multiply the displacement by the map's alpha. GEGL's own "
                 "displace always does this, which silently cancels the "
                 "displacement on transparent parts of the map"))

property_enum (abyss, _("Out of bounds"), LbDispAbyss, lb_disp_abyss,
               LB_DISP_ABYSS_LOOP)
  description (_("How pixels pulled from outside the image are resolved. "
                 "Wrap around keeps tiles seamless, repeat edge pixels avoids "
                 "both seams and smears behind a small elongation"))

property_enum (resampling, _("Resampling"), LbDispResample, lb_disp_resample,
               LB_DISP_RES_NOHALO)
  description (_("Bilinear never overshoots; bicubic is sharper on smooth maps "
                 "but rings on hard edges; nohalo and lohalo stay sharp "
                 "without ringing"))

#else

#define GEGL_OP_COMPOSER
/* GType 名不能叫 gegl_op_displace —— GEGL 自带的 gegl:displace 已经占了这个名字，
 * 同时载入时 GType 系统会拒绝注册第二个，模块直接加载失败。
 * The GType must not be gegl_op_displace: GEGL's own gegl:displace already
 * owns that name, and a second registration makes the module fail to load. */
#define GEGL_OP_NAME     lb_displace
#define GEGL_OP_C_SOURCE displace.c

#include "gegl-op.h"

/* 一次处理的行数。位移是随机访问，band 太大没有缓存收益，太小则调用开销
 * 变显著。
 * Rows per pass. Random access gains nothing from tall bands, but very short
 * ones make the sampler setup cost visible. */
#define LB_DISP_BAND 64

/* 把位移图的原始值换算成 -1..+1：midpoint 两侧各自按 black/white 归一化，
 * 这样灰色图（0.5 中性）和零中性矢量场（0 中性）用同一套参数就能表达。
 * Remaps a raw map value to -1..+1, normalising each side of the midpoint
 * against black/white, so a grey map (0.5 = rest) and a zero-centred vector
 * field (0 = rest) share one parameter set.
 * 超出量程的值不硬夹到 1，允许用 2 之类的白场做超量位移；只防住失控值。
 * Values beyond the white point are allowed past 1 on purpose; the clamp is
 * only there to keep a broken map from asking for absurd coordinates. */
static inline gdouble
lb_disp_remap (gdouble v,
               gdouble black,
               gdouble mid,
               gdouble white)
{
  gdouble t;

  if (v >= mid)
    t = (white > mid) ? (v - mid) / (white - mid) : 0.0;
  else
    t = (mid > black) ? (v - mid) / (mid - black) : 0.0;

  return CLAMP (t, -8.0, 8.0);
}

/* 标量模式下取一个通道。R'G'B' 已经是显示编码，亮度就用 Rec.709 权重直接
 * 加权，和 babl 的 Y' 一致。
 * Reads one channel for scalar mode. R'G'B' is display encoded already, so
 * luma is the plain Rec.709 weighted sum, matching babl's Y'. */
static inline gfloat
lb_disp_channel (const gfloat *p, LbDispChannel ch)
{
  switch (ch)
    {
      case LB_DISP_CH_RED:   return p[0];
      case LB_DISP_CH_GREEN: return p[1];
      case LB_DISP_CH_BLUE:  return p[2];
      case LB_DISP_CH_ALPHA: return p[3];
      default:               return 0.2126f * p[0] + 0.7152f * p[1] +
                                    0.0722f * p[2];
    }
}

static GeglSamplerType
lb_disp_sampler_type (LbDispResample r)
{
  switch (r)
    {
      case LB_DISP_RES_NEAREST:  return GEGL_SAMPLER_NEAREST;
      case LB_DISP_RES_BILINEAR: return GEGL_SAMPLER_LINEAR;
      case LB_DISP_RES_CUBIC:    return GEGL_SAMPLER_CUBIC;
      case LB_DISP_RES_LOHALO:   return GEGL_SAMPLER_LOHALO;
      default:                   return GEGL_SAMPLER_NOHALO;
    }
}

static GeglAbyssPolicy
lb_disp_abyss_policy (LbDispAbyss a)
{
  switch (a)
    {
      case LB_DISP_ABYSS_CLAMP:       return GEGL_ABYSS_CLAMP;
      case LB_DISP_ABYSS_TRANSPARENT: return GEGL_ABYSS_NONE;
      case LB_DISP_ABYSS_BLACK:       return GEGL_ABYSS_BLACK;
      case LB_DISP_ABYSS_WHITE:       return GEGL_ABYSS_WHITE;
      default:                        return GEGL_ABYSS_LOOP;
    }
}

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");
  const Babl *fmt   = babl_format_with_space ("R'G'B'A float", space);

  gegl_operation_set_format (operation, "input",  fmt);
  gegl_operation_set_format (operation, "output", fmt);
  /* aux 要 R/G（矢量）也要 alpha（可选权重），所以同样按 RGBA 取，比
   * gegl:displace 的 Y'A 宽一档。
   * The map is read as RGBA: R/G for the vector, A for the optional weight.
   * That is one channel wider than gegl:displace's Y'A. */
  gegl_operation_set_format (operation, "aux", fmt);
}

/* 输出尺寸永远跟随主图。composer 的默认 bbox 是 input 与 aux 的并集，位移图
 * 比主图小、还带偏移时画布会被悄悄撑大；置换只该改像素，不该改画布。
 * The output always follows the input. A composer's default bounding box is
 * the union of input and aux, so a smaller or offset map silently enlarges
 * the canvas; a displacement should move pixels, not resize the image. */
static GeglRectangle
get_bounding_box (GeglOperation *operation)
{
  GeglRectangle *in = gegl_operation_source_get_bounding_box (operation, "input");

  if (in)
    return *in;

  {
    const GeglRectangle empty = { 0, 0, 0, 0 };
    return empty;
  }
}

/* 位移可以把任意像素拉到任意位置，输入必须整张都可用；返回 roi 会让边缘
 * 出现「够不到」的黑块。
 * Any output pixel can pull from anywhere, so the whole input must be
 * available. Returning the roi alone would make edges pull black. */
static GeglRectangle
get_required_for_output (GeglOperation       *operation,
                         const gchar         *input_pad,
                         const GeglRectangle *roi)
{
  GeglRectangle *full = gegl_operation_source_get_bounding_box (operation, "input");

  if (!strcmp (input_pad, "aux"))
    return *roi;

  return full ? *full : *roi;
}

static gboolean
process (GeglOperation       *operation,
         GeglBuffer          *input,
         GeglBuffer          *aux,
         GeglBuffer          *output,
         const GeglRectangle *result,
         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (operation);
  const Babl     *fmt = gegl_operation_get_format (operation, "output");

  /* 没接位移图：原样输出，等于一个占位的恒等算子。
   * No map connected: pass through, so the op doubles as an identity. */
  if (aux == NULL)
    {
      gegl_buffer_copy (input, result, GEGL_ABYSS_NONE, output, result);
      return TRUE;
    }

  const GeglRectangle aext = *gegl_buffer_get_extent (aux);
  const gint w  = result->width;
  const gint bh = MIN (LB_DISP_BAND, result->height);
  /* 行距按整行宽算，不能用 GEGL_AUTO_ROWSTRIDE：aux 只覆盖 band 的一部分时，
   * 取回来的行宽比 w 窄，后续按 w 索引会错行。
   * The row stride follows the full band width. GEGL_AUTO_ROWSTRIDE would use
   * the fetched rect's width, and a partially covered aux rect comes back
   * packed narrower. */
  const gint stride = (gint) (sizeof (gfloat) * 4 * (gsize) w);

  gfloat *aux_band = g_new (gfloat, (gsize) w * bh * 4);
  gfloat *out_band = g_new (gfloat, (gsize) w * bh * 4);

  gdouble unit = 1.0;

  if (o->units == LB_DISP_UNIT_PERCENT)
    {
      const GeglRectangle *ext =
        gegl_operation_source_get_bounding_box (operation, "input");

      if (ext)
        unit = MAX (ext->width, ext->height) * 0.01;
    }

  const GeglAbyssPolicy policy = lb_disp_abyss_policy (o->abyss);
  GeglSampler *sampler = gegl_buffer_sampler_new_at_level (input, fmt,
                                                           lb_disp_sampler_type (o->resampling),
                                                           level);

  for (gint y0 = 0; y0 < result->height; y0 += LB_DISP_BAND)
    {
      const gint nh = MIN (LB_DISP_BAND, result->height - y0);
      const GeglRectangle band = { result->x, result->y + y0, w, nh };

      /* 先清零：aux_band 只在覆盖矩形内被写，剩下的是上一块的数据。
       * Zero first: only the covered rect is written, the rest still holds
       * the previous band. */
      memset (aux_band, 0, sizeof (gfloat) * (gsize) w * nh * 4);

      /* 本块内位移图真正覆盖到的列/行（相对块左上角）。图比主图小或带偏移
       * 时，外面那些像素保持原样 —— gegl:displace 在这里读到 0，于是整块
       * 被硬移 -amount，是它最隐蔽的一个坑。
       * Columns/rows actually covered by the map, relative to the band.
       * Outside them the image passes through untouched. gegl:displace reads
       * zero there and hard-shifts the whole area by -amount, which is its
       * most easily missed trap. */
      gint cx0 = 0, cx1 = 0, cy0 = 0, cy1 = 0;

      cx0 = MAX (band.x, aext.x) - band.x;
      cx1 = MIN (band.x + w, aext.x + aext.width) - band.x;
      cy0 = MAX (band.y, aext.y) - band.y;
      cy1 = MIN (band.y + nh, aext.y + aext.height) - band.y;

      if (cx1 <= cx0 || cy1 <= cy0)
        cx1 = cx0 = cy1 = cy0 = 0;
      else
        {
          const GeglRectangle ar = { band.x + cx0, band.y + cy0,
                                     cx1 - cx0, cy1 - cy0 };

          gegl_buffer_get (aux, &ar, 1.0, fmt,
                           aux_band + ((gsize) cy0 * w + cx0) * 4,
                           stride, GEGL_ABYSS_NONE);
        }

      for (gint row = 0; row < nh; row++)
        for (gint col = 0; col < w; col++)
          {
            const gsize n = ((gsize) row * w + col) * 4;
            const gdouble px = band.x + col + 0.5;
            const gdouble py = band.y + row + 0.5;
            gdouble dx = 0.0, dy = 0.0;

            if (row >= cy0 && row < cy1 && col >= cx0 && col < cx1)
              {
                const gfloat *m = aux_band + n;
                gdouble tx, ty;

                if (o->map_mode == LB_DISP_MAP_VECTOR)
                  {
                    tx = lb_disp_remap (m[0], o->black_point, o->midpoint,
                                        o->white_point);
                    ty = lb_disp_remap (m[1], o->black_point, o->midpoint,
                                        o->white_point);
                  }
                else
                  {
                    /* 单通道：同一个标量喂两个轴，靠 amount-x / amount-y
                     * 的比例决定拉伸方向。
                     * Single channel: one scalar feeds both axes, the ratio of
                     * amount-x to amount-y decides the stretch direction. */
                    tx = lb_disp_remap (lb_disp_channel (m, o->map_channel),
                                        o->black_point, o->midpoint,
                                        o->white_point);
                    ty = tx;
                  }

                if (o->alpha_weight)
                  {
                    tx *= m[3];
                    ty *= m[3];
                  }

                dx = tx * o->amount_x * unit;
                dy = ty * o->amount_y * unit;
              }

            gegl_sampler_get (sampler, px + dx, py + dy, NULL,
                              out_band + n, policy);
          }

      gegl_buffer_set (output, &band, level, fmt, out_band, stride);
    }

  g_object_unref (sampler);
  g_free (aux_band);
  g_free (out_band);

  return TRUE;
}

/* ---- 类初始化 / class init --------------------------------------------- */

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass         *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationComposerClass *cclass = GEGL_OPERATION_COMPOSER_CLASS (klass);

  oclass->prepare              = prepare;
  oclass->get_bounding_box     = get_bounding_box;
  oclass->get_required_for_output = get_required_for_output;
  cclass->process              = process;

  cclass->aux_label       = _("Displacement map");
  cclass->aux_description = _("Map that drives the displacement; without it "
                              "the image passes through");

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:displace",
    "title",           _("Displace"),
    "description",     _("Resamples the image through a displacement map: one "
                         "RGBA map drives both axes, amounts in pixels or "
                         "percent of the long edge, five edge policies and a "
                         "sampler that does not ring by default."),
    "gimp:menu-path",  "<Image>/SuperMrWang/Distort",
    "gimp:menu-label", _("Displace"),
    NULL);
}

#endif
