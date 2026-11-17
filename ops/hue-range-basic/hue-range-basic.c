/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:hue-range-basic
 * menu       Hue/Saturation Range
 * purpose    色系范围调整：选一个色相族，在其软范围内应用色相/饱和度/明度，
 *            与 lb:hue-saturation-basic（全图）串联即接近某图像编辑器
 *            「色相/饱和度」对话框的「编辑」下拉 + 底部色条模型。
 *            Per-family hue/saturation/lightness inside a soft hue range;
 *            chained after lb:hue-saturation-basic (master) this mirrors the
 *            "edit dropdown + colour bar" model of the classic
 *            Hue/Saturation dialog.
 * algorithm  ① 范围：四个柄定义一条色条——内二柄之间全选（权重 1），
 *               外二柄之间线性过渡（经典图像编辑器 的羽化是线性的），其余为 0。
 *               六个色系默认（度）：红 315/345/15/45、黄 15/45/75/105、
 *               绿 75/105/135/165、青 135/165/195/225、蓝 195/225/255/285、
 *               品红 255/285/315/345，即中心 ±15 全选、±45 过渡。
 *               柄值 -1 = 跟随色系默认，拖动后为绝对角度（0–360，可环绕）。
 *               Range: two inner handles select fully (weight 1), the bands
 *               out to the two outer handles ramp linearly (the classic
 *               feathering is linear). Defaults per family are centre ±15
 *               selected, ±45 falloff. A handle of -1 follows the family
 *               default; dragged values are absolute degrees 0-360.
 *            ② 权重作用在【原始】色相上（先算 w，再调整），与内部蒙版的
 *               语义一致；无彩像素（RGB 相等）不参与任何色系。
 *               The weight is computed on the ORIGINAL hue, like an internal
 *               mask; achromatic pixels join no family.
 *            ③ 调整量按 w 缩放后走 lb:hue-saturation-basic 的同一套公式：
 *               明度 screen/multiply（t·w）→ HSL → 色相 +hue·w →
 *               饱和度 s/(1-x·w) / s(1+x·w) → RGB。w=1 时与全图算子
 *               逐位一致，w=0 时逐位等于原图。
 *               Adjustments scale by w and reuse the master op's formula
 *               exactly: at w = 1 identical to lb:hue-saturation-basic, at
 *               w = 0 identical to the input.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  经典「色相/饱和度」对话框的通道范围模型（色条四柄、线性羽化）
 *            The classic Hue/Saturation dialog's channel-range model.
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_enum (channel, _("Channel Range"),
               LbHueRangeChannel, hue_range_basic_channel_enum, RANGE_REDS)
    description (_("Which hue family to adjust"))

enum_start (hue_range_basic_channel_enum)
  enum_value (RANGE_REDS,     "reds",     N_("Reds"))
  enum_value (RANGE_YELLOWS,  "yellows",  N_("Yellows"))
  enum_value (RANGE_GREENS,   "greens",   N_("Greens"))
  enum_value (RANGE_CYANS,    "cyans",    N_("Cyans"))
  enum_value (RANGE_BLUES,    "blues",    N_("Blues"))
  enum_value (RANGE_MAGENTAS, "magentas", N_("Magentas"))
enum_end (LbHueRangeChannel)

/* 四个柄：内二柄之间全选，向外二柄线性过渡。-1 = 跟随色系默认。
 * Four handles: full selection between the inner two, linear falloff out
 * to the outer two. -1 follows the family default. */
property_double (range_low, _("Falloff Left"), -1.0)
    description (_("Outer left handle of the colour bar, in degrees. -1 uses "
                   "the family default (centre - 45)"))
    value_range (-1.0, 360.0)
    ui_range    (0.0, 360.0)

property_double (range_inner_low, _("Range Left"), -1.0)
    description (_("Inner left handle, in degrees. -1 uses the family default "
                   "(centre - 15)"))
    value_range (-1.0, 360.0)
    ui_range    (0.0, 360.0)

property_double (range_inner_high, _("Range Right"), -1.0)
    description (_("Inner right handle, in degrees. -1 uses the family default "
                   "(centre + 15)"))
    value_range (-1.0, 360.0)
    ui_range    (0.0, 360.0)

property_double (range_high, _("Falloff Right"), -1.0)
    description (_("Outer right handle, in degrees. -1 uses the family default "
                   "(centre + 45)"))
    value_range (-1.0, 360.0)
    ui_range    (0.0, 360.0)

property_double (hue, _("Hue"), 0.0)
   description (_("Rotate the family's hue, in degrees; scaled by the range "
                  "weight per pixel"))
   value_range (-180.0, 180.0)
   ui_range    (-180.0, 180.0)

property_double (saturation, _("Saturation"), 0.0)
   description (_("Relative saturation for the family, in percent: +100 drives "
                  "coloured pixels to full saturation, -100 to grey"))
   value_range (-100.0, 100.0)
   ui_range    (-100.0, 100.0)

property_double (lightness, _("Lightness"), 0.0)
   description (_("Lightness for the family, in percent: positive blends toward "
                  "white, negative toward black, channel by channel"))
   value_range (-100.0, 100.0)
   ui_range    (-100.0, 100.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_hue_range_basic
#define GEGL_OP_C_SOURCE hue-range-basic.c

#include "gegl-op.h"

/* ---- 色系默认范围（度）：中心 ±15 全选，±45 过渡 / family defaults ---- */

typedef struct
{
  gfloat outer_low, inner_low, inner_high, outer_high;
} HueRangeDefaults;

static const HueRangeDefaults *
channel_defaults (LbHueRangeChannel ch)
{
  static const HueRangeDefaults defaults[] =
  {
    { 315.0f, 345.0f,  15.0f,  45.0f },   /* reds     */
    {  15.0f,  45.0f,  75.0f, 105.0f },   /* yellows  */
    {  75.0f, 105.0f, 135.0f, 165.0f },   /* greens   */
    { 135.0f, 165.0f, 195.0f, 225.0f },   /* cyans    */
    { 195.0f, 225.0f, 255.0f, 285.0f },   /* blues    */
    { 255.0f, 285.0f, 315.0f, 345.0f },   /* magentas */
  };
  gint i = (gint) ch;
  return &defaults[CLAMP (i, 0, (gint) G_N_ELEMENTS (defaults) - 1)];
}

/* ---- 公式与 lb:hue-saturation-basic 逐字共用 / shared formula -------------- */

static inline gfloat
wrap_degrees (gfloat d)
{
  d = fmodf (d, 360.0f);
  if (d < 0.0f)
    d += 360.0f;
  return d;
}

static inline gfloat
hue_channel (gfloat m1, gfloat m2, gfloat h)
{
  if (h < 0.0f)
    h += 360.0f;
  else if (h >= 360.0f)
    h -= 360.0f;

  if (h < 60.0f)
    return m1 + (m2 - m1) * h / 60.0f;
  if (h < 180.0f)
    return m2;
  if (h < 240.0f)
    return m1 + (m2 - m1) * (240.0f - h) / 60.0f;
  return m1;
}

static inline void
rgb_to_hsl (gfloat r, gfloat g, gfloat b,
            gfloat *hue, gfloat *sat, gfloat *lig, gfloat *chroma)
{
  gfloat max   = MAX (r, MAX (g, b));
  gfloat min   = MIN (r, MIN (g, b));
  gfloat delta = max - min;
  gfloat sum   = max + min;
  gfloat h = 0.0f, s = 0.0f, l = sum * 0.5f;

  if (delta > 1.0e-6f && sum > 1.0e-6f)
    {
      if (l <= 0.5f)
        s = delta / sum;
      else
        s = delta / (2.0f - sum);

      if (max == r)
        h = (g - b) / delta + (g < b ? 6.0f : 0.0f);
      else if (max == g)
        h = (b - r) / delta + 2.0f;
      else
        h = (r - g) / delta + 4.0f;

      h *= 60.0f;
    }

  *hue    = wrap_degrees (h);
  *sat    = CLAMP (s, 0.0f, 1.0f);
  *lig    = CLAMP (l, 0.0f, 1.0f);
  *chroma = delta;
}

static inline void
hsl_to_rgb (gfloat h, gfloat s, gfloat l,
            gfloat *r, gfloat *g, gfloat *b)
{
  if (s <= 1.0e-6f)
    {
      *r = *g = *b = l;
      return;
    }

  {
    gfloat m2 = (l <= 0.5f) ? l * (1.0f + s) : l + s - l * s;
    gfloat m1 = 2.0f * l - m2;

    *r = hue_channel (m1, m2, h + 120.0f);
    *g = hue_channel (m1, m2, h);
    *b = hue_channel (m1, m2, h - 120.0f);
  }
}

static inline gfloat
apply_lightness (gfloat c, gfloat t)
{
  if (t > 0.0f)
    return c + t * (1.0f - c);
  if (t < 0.0f)
    return c * (1.0f + t);
  return c;
}

static inline gfloat
scale_saturation (gfloat s, gfloat x)
{
  if (x >= 1.0f)
    return (s > 0.0f) ? 1.0f : 0.0f;
  if (x > 0.0f)
    return MIN (1.0f, s / (1.0f - x));
  if (x < 0.0f)
    return MAX (0.0f, s * (1.0f + x));
  return s;
}

/* ---- 范围权重 / range weight ------------------------------------------- */

/* 四柄色条：内二柄之间 w=1，向外二柄线性过渡，其余 w=0。
 * 柄值都在 0–360 圆上，先解开环绕再分段线性，支持用户把范围拖过 0/360。
 * Four-handle colour bar: w = 1 between the inner handles, linear ramps out
 * to the outer handles, 0 elsewhere. Handles live on the 0-360 circle; unwrap
 * around the inner range first so ranges dragged across 0/360 still work. */
static gfloat
range_weight (gfloat h,
              gfloat outer_low, gfloat inner_low,
              gfloat inner_high, gfloat outer_high)
{
  /* 解环绕：把 inner_low 放到原点，内区跨度 ≤360 */
  gfloat span = inner_high - inner_low;
  if (span < 0.0f)
    span += 360.0f;

  gfloat i_l = inner_low;
  gfloat i_r = i_l + span;
  gfloat o_l = i_l - wrap_degrees (i_l - outer_low);
  gfloat o_r = i_r + wrap_degrees (outer_high - inner_high);
  gfloat hu  = i_l + wrap_degrees (h - i_l);

  if (hu < o_l || hu > o_r)
    return 0.0f;
  if (hu >= i_l && hu <= i_r)
    return 1.0f;
  if (hu < i_l)
    {
      gfloat band = i_l - o_l;
      return (band <= 1.0e-6f) ? 0.0f : (hu - o_l) / band;
    }
  {
    gfloat band = o_r - i_r;
    return (band <= 1.0e-6f) ? 0.0f : (o_r - hu) / band;
  }
}

/* ---- 算子定义 / operation ---------------------------------------------- */

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");

  /* 与 lb:hue-saturation-basic 同款感知（非线性）RGB：串联时两边口径一致。
   * Same perceptual RGB as lb:hue-saturation-basic so the chained pair works
   * in one domain. */
  gegl_operation_set_format (operation, "input",
                             babl_format_with_space ("R~G~B~A float", space));
  gegl_operation_set_format (operation, "output",
                             babl_format_with_space ("R~G~B~A float", space));
}

static gboolean
process (GeglOperation       *operation,
         void                *in_buf,
         void                *out_buf,
         glong                n_pixels,
         const GeglRectangle *roi,
         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (operation);
  gfloat * GEGL_ALIGNED in_pixel  = in_buf;
  gfloat * GEGL_ALIGNED out_pixel = out_buf;

  const gfloat hue_add = (gfloat) o->hue;
  const gfloat sat_x   = (gfloat) o->saturation / 100.0f;
  const gfloat t_light = (gfloat) o->lightness / 100.0f;

  const HueRangeDefaults *def = channel_defaults (o->channel);
  const gfloat o_l = (o->range_low        < 0.0f) ? def->outer_low  : (gfloat) o->range_low;
  const gfloat i_l = (o->range_inner_low  < 0.0f) ? def->inner_low  : (gfloat) o->range_inner_low;
  const gfloat i_r = (o->range_inner_high < 0.0f) ? def->inner_high : (gfloat) o->range_inner_high;
  const gfloat o_r = (o->range_high       < 0.0f) ? def->outer_high : (gfloat) o->range_high;

  glong i;

  if (t_light == 0.0f && hue_add == 0.0f && sat_x == 0.0f)
    {
      memcpy (out_buf, in_buf, (size_t) n_pixels * 4 * sizeof (gfloat));
      return TRUE;
    }

  for (i = 0; i < n_pixels; i++)
    {
      gfloat r = CLAMP (in_pixel[0], 0.0f, 1.0f);
      gfloat g = CLAMP (in_pixel[1], 0.0f, 1.0f);
      gfloat b = CLAMP (in_pixel[2], 0.0f, 1.0f);
      gfloat h, s, l, chroma;

      /* 权重作用在【原始】色相上：先算 w，再调整。
       * The weight comes from the ORIGINAL hue: compute w first. */
      rgb_to_hsl (r, g, b, &h, &s, &l, &chroma);
      gfloat w = (chroma > 1.0e-6f)
                 ? range_weight (h, o_l, i_l, i_r, o_r)
                 : 0.0f;

      if (w <= 0.0f)
        {
          out_pixel[0] = in_pixel[0];
          out_pixel[1] = in_pixel[1];
          out_pixel[2] = in_pixel[2];
          out_pixel[3] = in_pixel[3];
          in_pixel  += 4;
          out_pixel += 4;
          continue;
        }

      /* ① 明度（t·w）先进 RGB —— 与全图算子同序，饱和度作用在明度挪过
       *     之后的 S 上。
       * (1) lightness (t·w) into RGB first; saturation then acts on the
       *     shifted S, same order as the master op. */
      if (t_light != 0.0f)
        {
          gfloat tw = t_light * w;
          r = apply_lightness (r, tw);
          g = apply_lightness (g, tw);
          b = apply_lightness (b, tw);
        }

      /* ② 转 HSL（明度挪过之后的色） */
      rgb_to_hsl (r, g, b, &h, &s, &l, &chroma);

      /* ③ 色相 +hue·w */
      if (hue_add != 0.0f)
        h = wrap_degrees (h + hue_add * w);

      /* ④ 饱和度相对缩放（x·w） */
      if (sat_x != 0.0f)
        s = scale_saturation (s, sat_x * w);

      hsl_to_rgb (h, s, l, &out_pixel[0], &out_pixel[1], &out_pixel[2]);
      out_pixel[3] = in_pixel[3];

      in_pixel  += 4;
      out_pixel += 4;
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass            *operation_class    = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointFilterClass *point_filter_class = GEGL_OPERATION_POINT_FILTER_CLASS (klass);

  operation_class->prepare    = prepare;
  point_filter_class->process = process;

  gegl_operation_class_set_keys (operation_class,
                                 "name",            "lb:hue-range-basic",
                                 "title",           _("Hue/Saturation Range"),
                                 "categories",      "color:enhance",
                                 "description",     _("Hue, saturation and lightness inside one "
                                                      "hue family with a soft four-handle range; "
                                                      "chain after Hue/Saturation (Basic) for the "
                                                      "full master + per-family workflow."),
                                 "gimp:menu-path",  "<Image>/SuperMrWang/Color",
                                 "gimp:menu-label", _("Hue/Saturation Range"),
                                 NULL);
}

#endif
