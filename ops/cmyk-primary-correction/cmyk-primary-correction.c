/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:cmyk-primary-correction
 * menu       CMYK Primary
 * purpose    PS 可选颜色：红/黄/绿/青/蓝/品红/白/中性/黑九组各自独立记忆
 *            C/M/Y/K
 *            PS Selective Color: nine ranges (red, yellow, green, cyan, blue,
 *            magenta, white, neutral, black), each keeping its own C/M/Y/K
 *            values.
 * algorithm  RGB → CMYK；九组色域分别算权重，逐像素把九组偏移同时叠加，支持绝
 *            对 / 相对两种模式，灰阶不受影响
 *            RGB -> CMYK. All nine ranges are weighted per pixel and their
 *            offsets are summed simultaneously; absolute and relative modes
 *            are supported and greys are left untouched.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  Photoshop「可选颜色」(Selective Color)
 *            Photoshop Selective Color
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* ---- 全局选项 / global options ----------------------------------------- */

property_boolean (absolute, _("Absolute Mode"), FALSE)
    description (_("PS 'Absolute' checkbox: 100 means a hard +100% ink step "
                   "instead of a relative one"))

/* ---- 九组色域各自一份 C/M/Y/K / nine ranges, one set each --------------
 * PS 的「可选颜色」有 9 个页签，各存一套 C/M/Y/K；切换页签不会丢掉别组的
 * 数值，而且九组同时作用。这里用 36 个独立属性如实还原该行为。
 * PS Selective Color keeps one C/M/Y/K set per tab: switching tabs never
 * drops another tab's values and all nine act at once. 36 separate
 * properties reproduce that faithfully.
 * 顺序与 PS 一致：红 / 黄 / 绿 / 青 / 蓝 / 品红 / 白 / 中性 / 黑
 * Order matches PS: red, yellow, green, cyan, blue, magenta, white,
 * neutral, black.
 */

property_double (reds_cyan,    _("Reds – Cyan"),    0.0)
    value_range (-100.0, 100.0)
property_double (reds_magenta, _("Reds – Magenta"), 0.0)
    value_range (-100.0, 100.0)
property_double (reds_yellow,  _("Reds – Yellow"),  0.0)
    value_range (-100.0, 100.0)
property_double (reds_black,   _("Reds – Black"),   0.0)
    value_range (-100.0, 100.0)

property_double (yellows_cyan,    _("Yellows – Cyan"),    0.0)
    value_range (-100.0, 100.0)
property_double (yellows_magenta, _("Yellows – Magenta"), 0.0)
    value_range (-100.0, 100.0)
property_double (yellows_yellow,  _("Yellows – Yellow"),  0.0)
    value_range (-100.0, 100.0)
property_double (yellows_black,   _("Yellows – Black"),   0.0)
    value_range (-100.0, 100.0)

property_double (greens_cyan,    _("Greens – Cyan"),    0.0)
    value_range (-100.0, 100.0)
property_double (greens_magenta, _("Greens – Magenta"), 0.0)
    value_range (-100.0, 100.0)
property_double (greens_yellow,  _("Greens – Yellow"),  0.0)
    value_range (-100.0, 100.0)
property_double (greens_black,   _("Greens – Black"),   0.0)
    value_range (-100.0, 100.0)

property_double (cyans_cyan,    _("Cyans – Cyan"),    0.0)
    value_range (-100.0, 100.0)
property_double (cyans_magenta, _("Cyans – Magenta"), 0.0)
    value_range (-100.0, 100.0)
property_double (cyans_yellow,  _("Cyans – Yellow"),  0.0)
    value_range (-100.0, 100.0)
property_double (cyans_black,   _("Cyans – Black"),   0.0)
    value_range (-100.0, 100.0)

property_double (blues_cyan,    _("Blues – Cyan"),    0.0)
    value_range (-100.0, 100.0)
property_double (blues_magenta, _("Blues – Magenta"), 0.0)
    value_range (-100.0, 100.0)
property_double (blues_yellow,  _("Blues – Yellow"),  0.0)
    value_range (-100.0, 100.0)
property_double (blues_black,   _("Blues – Black"),   0.0)
    value_range (-100.0, 100.0)

property_double (magentas_cyan,    _("Magentas – Cyan"),    0.0)
    value_range (-100.0, 100.0)
property_double (magentas_magenta, _("Magentas – Magenta"), 0.0)
    value_range (-100.0, 100.0)
property_double (magentas_yellow,  _("Magentas – Yellow"),  0.0)
    value_range (-100.0, 100.0)
property_double (magentas_black,   _("Magentas – Black"),   0.0)
    value_range (-100.0, 100.0)

property_double (whites_cyan,    _("Whites – Cyan"),    0.0)
    value_range (-100.0, 100.0)
property_double (whites_magenta, _("Whites – Magenta"), 0.0)
    value_range (-100.0, 100.0)
property_double (whites_yellow,  _("Whites – Yellow"),  0.0)
    value_range (-100.0, 100.0)
property_double (whites_black,   _("Whites – Black"),   0.0)
    value_range (-100.0, 100.0)

property_double (neutrals_cyan,    _("Neutrals – Cyan"),    0.0)
    value_range (-100.0, 100.0)
property_double (neutrals_magenta, _("Neutrals – Magenta"), 0.0)
    value_range (-100.0, 100.0)
property_double (neutrals_yellow,  _("Neutrals – Yellow"),  0.0)
    value_range (-100.0, 100.0)
property_double (neutrals_black,   _("Neutrals – Black"),   0.0)
    value_range (-100.0, 100.0)

property_double (blacks_cyan,    _("Blacks – Cyan"),    0.0)
    value_range (-100.0, 100.0)
property_double (blacks_magenta, _("Blacks – Magenta"), 0.0)
    value_range (-100.0, 100.0)
property_double (blacks_yellow,  _("Blacks – Yellow"),  0.0)
    value_range (-100.0, 100.0)
property_double (blacks_black,   _("Blacks – Black"),   0.0)
    value_range (-100.0, 100.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_cmyk_primary_correction
#define GEGL_OP_C_SOURCE cmyk-primary-correction.c

#include "gegl-op.h"

/* ---- 九组色域数据 / the nine ranges ------------------------------------ */

typedef enum
{
  SEC_REDS = 0,
  SEC_YELLOWS,
  SEC_GREENS,
  SEC_CYANS,
  SEC_BLUES,
  SEC_MAGENTAS,
  SEC_WHITES,
  SEC_NEUTRALS,
  SEC_BLACKS,
  SEC_COUNT
} SectionId;

/* 每组一份 C/M/Y/K，下标 0=C 1=M 2=Y 3=K，取值 -1~1
 * one C/M/Y/K set per group, index 0=C 1=M 2=Y 3=K, range -1..1 */
typedef struct
{
  gfloat v[4];
} SectionAdjust;

/* 拼接属性名用的段名与通道名，顺序必须与上表一致
 * segment and channel names used to build property names; the order must
 * match the table above */
static const gchar *section_ids[SEC_COUNT] = {
  "reds", "yellows", "greens", "cyans", "blues",
  "magentas", "whites", "neutrals", "blacks"
};

static const gchar *channel_ids[4] = {
  "cyan", "magenta", "yellow", "black"
};

/* ---- 单像素 RGB 分量信息 / per-pixel RGB components -------------------- */

typedef struct {
  gfloat r, g, b;
  gfloat max_val, mid_val, min_val;
  gint max_idx, mid_idx, min_idx;   /* 0=红 1=绿 2=蓝 / 0=r 1=g 2=b */
} RgbInfo;

static inline gfloat clampf(gfloat v, gfloat low, gfloat high)
{
  if (v < low) return low;
  if (v > high) return high;
  return v;
}

/* 移植 Java 的 ColorUtils.round，并限幅到区间
 * ported from Java ColorUtils.round, clamped to the range */
static inline gfloat color_round_clamp(gfloat val, gfloat upper, gfloat lower)
{
  return clampf(val, lower, upper);
}

/* 单通道修正量，对应 Java 的 selectiveColorChannel
 * per-channel delta, mirrors Java selectiveColorChannel */
static gfloat
channel_delta(gfloat   ch_val,   /* 当前通道 0~1 / current channel 0..1 */
              gfloat   range,    /* 色域权重 0~1 / range weight 0..1 */
              gboolean is_abs,
              gfloat   arg,      /* C/M/Y 参数 -1~1 / C/M/Y argument -1..1 */
              gfloat   karg)     /* K 参数 -1~1 / K argument -1..1 */
{
  gfloat m = is_abs ? 1.0f : (1.0f - ch_val);

  gfloat base = ((-1.0f - arg) * karg - arg) * m;
  gfloat clamped = color_round_clamp(base, 1.0f - ch_val, -ch_val);
  return clamped * range;
}

/* 分解像素 RGB：按 min/mid/max 排序并记下各自索引
 * decompose the pixel RGB, sort into min/mid/max and keep the indices */
static void
split_rgb(gfloat r, gfloat g, gfloat b, RgbInfo *info)
{
  info->r = r;
  info->g = g;
  info->b = b;

  gfloat vals[3] = { r, g, b };
  gint   idxs[3] = { 0, 1, 2 };

  for (gint i = 0; i < 2; i++)
  {
    for (gint j = 0; j < 2 - i; j++)
    {
      if (vals[j] > vals[j + 1])
      {
        gfloat tv = vals[j]; vals[j] = vals[j + 1]; vals[j + 1] = tv;
        gint   ti = idxs[j]; idxs[j] = idxs[j + 1]; idxs[j + 1] = ti;
      }
    }
  }
  info->min_val = vals[0]; info->min_idx = idxs[0];
  info->mid_val = vals[1]; info->mid_idx = idxs[1];
  info->max_val = vals[2]; info->max_idx = idxs[2];
}

/* 当前像素落在某个色域的权重 0~1，移植 Java 逻辑
 * weight 0..1 of this pixel for one range, ported from the Java code */
static gfloat
calc_weight_range(const RgbInfo *rgb, gint section)
{
  gfloat range = 0.0f;
  gfloat r = rgb->r, g = rgb->g, b = rgb->b;
  gfloat maxv = rgb->max_val, midv = rgb->mid_val, minv = rgb->min_val;
  gint   maxi = rgb->max_idx, mini = rgb->min_idx;

  switch (section)
  {
    case SEC_REDS:      if (maxi == 0) range = maxv - midv; break;
    case SEC_GREENS:    if (maxi == 1) range = maxv - midv; break;
    case SEC_BLUES:     if (maxi == 2) range = maxv - midv; break;

    case SEC_CYANS:     if (mini == 0) range = midv - minv; break;
    case SEC_MAGENTAS:  if (mini == 1) range = midv - minv; break;
    case SEC_YELLOWS:   if (mini == 2) range = midv - minv; break;

    case SEC_WHITES:
      if (r > 0.5f && g > 0.5f && b > 0.5f)
        range = 2.0f * minv - 1.0f;
      break;

    case SEC_BLACKS:
      if (r < 0.5f && g < 0.5f && b < 0.5f)
        range = 1.0f - 2.0f * maxv;
      break;

    case SEC_NEUTRALS:
      if (!((r == 0.0f && g == 0.0f && b == 0.0f) ||
            (r == 1.0f && g == 1.0f && b == 1.0f)))
        range = 1.0f - (fabsf(maxv - 0.5f) + fabsf(minv - 0.5f));
      break;

    default:
      range = 0.0f;
  }
  return clampf(range, 0.0f, 1.0f);
}

/* ---- 读取九组参数 / read the nine parameter sets ----------------------- */

static void
read_adjustments(GeglOperation *op, SectionAdjust adj[SEC_COUNT],
                 gboolean active[SEC_COUNT])
{
  for (gint s = 0; s < SEC_COUNT; s++)
  {
    active[s] = FALSE;

    for (gint c = 0; c < 4; c++)
    {
      gchar *pname = g_strdup_printf("%s-%s", section_ids[s], channel_ids[c]);
      GValue val = G_VALUE_INIT;
      gdouble pct = 0.0;

      g_value_init(&val, G_TYPE_DOUBLE);
      g_object_get_property(G_OBJECT(op), pname, &val);
      pct = g_value_get_double(&val);
      g_value_unset(&val);
      g_free(pname);

      adj[s].v[c] = (gfloat) (pct / 100.0);

      if (adj[s].v[c] != 0.0f)
        active[s] = TRUE;
    }
  }
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

static void
prepare(GeglOperation *op)
{
  /* 感知（伽马域）浮点 RGBA 输入输出；CMYK 近似在伽马域才算得准
   * Perceptual (gamma) float RGBA in and out; the CMYK approximation is
   * only meaningful in gamma space */
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

  gboolean absolute = FALSE;
  g_object_get(G_OBJECT(op), "absolute", &absolute, NULL);

  SectionAdjust adj[SEC_COUNT];
  gboolean      active[SEC_COUNT];

  read_adjustments(op, adj, active);

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new(gfloat, stride);
  gfloat *out_line = g_new(gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };
    gegl_buffer_get(in_buf, &row_rect, 1.0f, perceptual_format(op),
                    in_line, GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint px = x * 4;
      gfloat r = in_line[px + 0];
      gfloat g = in_line[px + 1];
      gfloat b = in_line[px + 2];
      gfloat a = in_line[px + 3];

      RgbInfo rgb_info;
      split_rgb(r, g, b, &rgb_info);

      gfloat dr = 0.0f, dg = 0.0f, db = 0.0f;

      /* 九组同时叠加：像素同时属于「红」和「白」时两组都生效，与 PS 一致
       * all nine add up: a pixel that is both red and white gets both, as
       * in PS */
      for (gint s = 0; s < SEC_COUNT; s++)
      {
        gfloat w;

        if (!active[s])
          continue;

        w = calc_weight_range(&rgb_info, s);
        if (w <= 0.0f)
          continue;

        dr += channel_delta(r, w, absolute, adj[s].v[0], adj[s].v[3]);
        dg += channel_delta(g, w, absolute, adj[s].v[1], adj[s].v[3]);
        db += channel_delta(b, w, absolute, adj[s].v[2], adj[s].v[3]);
      }

      out_line[px + 0] = clampf(r + dr, 0.0f, 1.0f);
      out_line[px + 1] = clampf(g + dg, 0.0f, 1.0f);
      out_line[px + 2] = clampf(b + db, 0.0f, 1.0f);
      out_line[px + 3] = a;
    }

    gegl_buffer_set(out_buf, &row_rect, 0, perceptual_format(op),
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
    "name",            "lb:cmyk-primary-correction",
    "title",           _("CMYK Primary Correction"),
    "description",     _("PS Selective Color: 9 color ranges each keep their own C/M/Y/K "
                         "and all apply at once, absolute/relative mode"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("CMYK Primary"),
    NULL);
}

#endif
