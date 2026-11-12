/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:match-color
 * menu       Match Color
 * purpose    PS 匹配颜色：把另一张图（或另一层）的 L*a*b* 统计量迁移到本层
 *            PS Match Color: transfer the L*a*b* statistics of another image
 *            (or layer) onto this layer.
 * algorithm  与 PS 一致地工作在 CIELAB（D50）里：对 L、a、b 各通道算出目标
 *            （本层）和来源（aux）的均值/标准差，逐像素做仿射映射
 *              out = (v − μ_t) · (σ_s / σ_t) + μ_s        （Reinhard 2001）
 *            亮度滑杆只缩放 L 的映射量，颜色强度只缩放 a/b 的映射量（按
 *            lerp(1, ratio, k) 插值：滑杆=100 是精确匹配，200 是双倍，1 几乎
 *            不动），渐隐等价于整体映射量乘 (1 − fade)。中和把输出的 a/b 均
 *            值强制为 0（去色偏），L 照常。
 *            全局统计量与逐块渲染是天然冲突的：process 每次只拿到一小块，
 *            而均值/方差必须对整层算。做法是首次 process 时整层读一遍
 *            input/aux 攒出统计量，缓存在 operation 实例上（互斥锁保护，
 *            键为缓冲指针 + extent + 金字塔层级），后续块直接复用——预览时
 *            拖滑杆不会反复重算。来源图层内容变了（预览场景）勾一次
 *            「重算统计」即可。
 *            Works in CIELAB (D50) like PS: mean/std of L,a,b are taken over
 *            the whole input and the whole aux, and each pixel is mapped by
 *            an affine transform. Global statistics conflict with tiled
 *            rendering, so the first process() call reads both layers once
 *            and caches the numbers on the operation instance (mutex-guarded,
 *            keyed by buffer pointer + extent + level); later tiles reuse
 *            them, so preview slider drags don't recompute.
 * type       GeglOperationComposer（input + aux 双输入 / two inputs）
 * reference  Photoshop「图像 → 调整 → 匹配颜色」
 *            Image > Adjustments > Match Color; Reinhard et al.,
 *            "Color Transfer between Images" (2001)
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

property_double (luminance, _("Luminance"), 100.0)
    description (_("How strongly the L channel is matched: 100 = exact, "
                   "200 = twice the correction, 1 = almost none"))
    value_range (1.0, 200.0)

property_double (color_intensity, _("Color intensity"), 100.0)
    description (_("How strongly the a/b channels are matched"))
    value_range (1.0, 200.0)

property_double (fade, _("Fade"), 0.0)
    description (_("Blend the result back toward the original"))
    value_range (0.0, 100.0)

property_boolean (neutralize, _("Neutralize"), FALSE)
    description (_("Force the output chroma mean to neutral (remove color cast); "
                   "the source still donates contrast"))

property_boolean (refresh, _("Refresh stats"), FALSE)
    description (_("Recompute the statistics on the next tile (use after the "
                   "source layer changed in a preview session)"))

#else

#define GEGL_OP_COMPOSER
#define GEGL_OP_NAME     lb_match_color
#define GEGL_OP_C_SOURCE match-color.c
#include "gegl-op.h"

/* ---- 格式 / formats ---------------------------------------------------- */

/* 整个算子直接泡在 CIELAB 里：格式声明好了，GEGL/babl 负责进出转换，不需要
 * 手写 RGB↔Lab。带 alpha 是因为统计要排除透明像素、输出要保留目标 alpha。
 * The whole op lives in CIELAB: declare the format once and babl does the
 * conversions in and out. Alpha comes along because statistics must skip
 * transparent pixels and the output keeps the target's alpha. */
static const Babl *
lab_format (void)
{
  return babl_format ("CIE Lab alpha float");
}

static void
prepare (GeglOperation *op)
{
  const Babl *fmt = lab_format ();

  gegl_operation_set_format (op, "input",  fmt);
  gegl_operation_set_format (op, "aux",    fmt);
  gegl_operation_set_format (op, "output", fmt);
}

/* ---- 全局统计量 / global statistics ------------------------------------ */

/* σ 小于这个数时视为常数通道：除零保护。常数通道的 (v−μ) 本来就是 0，
 * 比值多少都不影响结果，取 1 最稳。
 * Channels flatter than this are treated as constant: the ratio would blow
 * up, but (v − μ) is 0 anyway, so 1 is the safe replacement. */
#define MC_STD_EPS 1e-3f

typedef struct
{
  gdouble mean[3];
  gdouble std[3];
  gsize   n;            /* 参与统计的不透明像素数 / opaque pixels counted */
} McStats;

/* 缓存挂在 operation 实例上（g_object_set_data），多线程 process 共享，
 * 互斥锁保护首次计算。键：两块缓冲的指针 + extent + 层级，任何一个变了
 * 就整体重算。预览拖滑杆不换缓冲，不会重算。
 * The cache hangs off the operation instance and is shared by concurrent
 * process calls behind a mutex. Keyed by buffer pointers + extents + level:
 * any change recomputes everything, slider drags recompute nothing. */
typedef struct
{
  GMutex        lock;
  gboolean      valid;
  gpointer      in_key;
  gpointer      aux_key;
  GeglRectangle in_ext;
  GeglRectangle aux_ext;
  gint          level;
  McStats       tgt;    /* 本层 / the target (input) */
  McStats       src;    /* 来源层 / the donor (aux) */
} McCache;

static McCache *
cache_get (GeglOperation *op)
{
  McCache *c = g_object_get_data (G_OBJECT (op), "lb-mc-cache");

  if (c == NULL)
    {
      c = g_new0 (McCache, 1);
      g_mutex_init (&c->lock);
      g_object_set_data_full (G_OBJECT (op), "lb-mc-cache", c,
                              (GDestroyNotify) g_free);
    }
  return c;
}

/* 单层统计：整层按行块读一遍，攒 sum 与 sum²。透明像素（alpha ≤ 0）不计入
 * ——抠图层的洞不该给统计量掺 0。
 * One layer's stats: a single full-extent pass accumulating sum and sum².
 * Transparent pixels (alpha ≤ 0) are excluded so holes in a matte don't
 * drag the statistics toward 0. */
static void
stats_compute (GeglBuffer *buf, const Babl *fmt, McStats *st)
{
  const GeglRectangle ext  = *gegl_buffer_get_extent (buf);
  const gint          band_h = 64;
  gdouble             s1[3] = { 0.0, 0.0, 0.0 };
  gdouble             s2[3] = { 0.0, 0.0, 0.0 };
  gsize               n = 0;

  gfloat *px = g_new (gfloat, (gsize) ext.width * band_h * 4);

  for (gint y0 = ext.y; y0 < ext.y + ext.height; y0 += band_h)
    {
      const gint nh = MIN (band_h, ext.y + ext.height - y0);
      const GeglRectangle band = { ext.x, y0, ext.width, nh };
      const gint stride = (gint) (sizeof (gfloat) * 4 * (gsize) ext.width);

      gegl_buffer_get (buf, &band, 1.0, fmt, px, stride, GEGL_ABYSS_NONE);

      const gsize np = (gsize) ext.width * nh;
      for (gsize i = 0; i < np; i++)
        {
          const gfloat *p = px + i * 4;

          if (p[3] <= 0.0f)
            continue;

          for (gint c = 0; c < 3; c++)
            {
              s1[c] += p[c];
              s2[c] += (gdouble) p[c] * p[c];
            }
          n++;
        }
    }

  g_free (px);

  for (gint c = 0; c < 3; c++)
    {
      if (n == 0)
        {
          st->mean[c] = 0.0;
          st->std[c]  = 0.0;
          continue;
        }
      st->mean[c] = s1[c] / (gdouble) n;
      const gdouble var = s2[c] / (gdouble) n - st->mean[c] * st->mean[c];
      st->std[c] = sqrt (MAX (var, 0.0));
    }
  st->n = n;
}

/* 统计量就绪（缓存命中或现算）。aux 未接时来源退化为本层自身：比值 1、
 * 均值相同，恒等映射。
 * Ready-to-use stats, cached or computed. Without an aux the source falls
 * back to the input itself: ratio 1, same means, an identity mapping. */
static void
stats_ensure (McCache        *c,
              GeglOperation  *op,
              GeglBuffer     *input,
              GeglBuffer     *aux,
              const GeglRectangle *result,
              gint            level,
              McStats        *tgt,
              McStats        *src)
{
  const Babl *fmt = lab_format ();
  const GeglRectangle iext = *gegl_buffer_get_extent (input);
  const GeglRectangle aext = aux ? *gegl_buffer_get_extent (aux) : iext;
  const gboolean want_refresh = GEGL_PROPERTIES (op)->refresh;

  g_mutex_lock (&c->lock);

  if (want_refresh)
    {
      /* 用完即复位：不然 TRUE 一直挂着，每个渲染块都会整层重扫
       * Clear the flag after one use, or every tile would rescan the
       * whole layers while the checkbox stays ticked. */
      GEGL_PROPERTIES (op)->refresh = FALSE;
    }
  else if (c->valid &&
           c->in_key  == (gpointer) input  &&
           c->aux_key == (gpointer) aux    &&
           c->level   == level             &&
           memcmp (&c->in_ext, &iext, sizeof (GeglRectangle)) == 0 &&
           memcmp (&c->aux_ext, &aext, sizeof (GeglRectangle)) == 0)
    {
      *tgt = c->tgt;
      *src = c->src;
      g_mutex_unlock (&c->lock);
      return;
    }

  stats_compute (input, fmt, &c->tgt);
  if (aux != NULL)
    stats_compute (aux, fmt, &c->src);
  else
    c->src = c->tgt;

  c->in_key  = (gpointer) input;
  c->aux_key = (gpointer) aux;
  c->in_ext  = iext;
  c->aux_ext = aext;
  c->level   = level;
  c->valid   = TRUE;

  *tgt = c->tgt;
  *src = c->src;
  g_mutex_unlock (&c->lock);

  (void) result;
}

/* ---- 单像素映射 / one pixel -------------------------------------------- */

static inline void
match_pixel (const gfloat *in,
             gfloat       *out,
             const gdouble amount_l,   /* 亮度映射量 / L mapping amount   */
             const gdouble amount_c,   /* 颜色映射量 / chroma mapping amount */
             const gdouble ratio[3],   /* σ_s / σ_t（保护后） / guarded    */
             const gdouble t_mean[3],
             const gdouble s_mean[3],
             const gboolean neutralize)
{
  /* 完整映射 M(v) = (v − μt)·r + μs，按 amount 收敛：
   * out = v·(1 + k(r−1)) + k·(μs − μt·r)
   * 中和把输出的色度均值压成 0：μs 换成 0。
   * Full mapping M(v) = (v − μt)·r + μs, approached by amount k:
   * out = v·(1 + k(r−1)) + k·(μs − μt·r). Neutralize pushes the output
   * chroma mean to 0, i.e. μs → 0 for a and b. */
  const gdouble kL = amount_l;
  const gdouble kC = amount_c;

  for (gint c = 0; c < 3; c++)
    {
      const gdouble k     = (c == 0) ? kL : kC;
      const gdouble r     = ratio[c];
      const gdouble mu_s  = (neutralize && c > 0) ? 0.0 : s_mean[c];
      const gdouble slope = 1.0 + k * (r - 1.0);
      gdouble v = in[c] * slope + k * (mu_s - t_mean[c] * r);

      /* PS 在 8bit L*a*b* 里工作，越界直接削到边界
       * PS works in 8-bit L*a*b* and clips to the domain edges. */
      if (c == 0)
        v = CLAMP (v, 0.0, 100.0);
      else
        v = CLAMP (v, -128.0, 127.0);

      out[c] = (gfloat) v;
    }
  out[3] = in[3];
}

/* ---- 主处理 / main processing ------------------------------------------ */

#define MC_BAND 32

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *input,
         GeglBuffer          *aux,
         GeglBuffer          *output,
         const GeglRectangle *result,
         gint                 level)
{
  GeglProperties *o   = GEGL_PROPERTIES (op);
  const Babl     *fmt = lab_format ();

  McStats tgt, src;
  McCache *c = cache_get (op);
  stats_ensure (c, op, input, aux, result, level, &tgt, &src);

  /* 两个统计都算不出来（全透明）就原样通过
   * Nothing to match with (fully transparent layers): pass through. */
  if (tgt.n == 0 || src.n == 0)
    {
      const gint stride = (gint) (sizeof (gfloat) * 4 * (gsize) result->width);
      gfloat *row = g_new (gfloat, (gsize) result->width * 4);

      for (gint y = 0; y < result->height; y++)
        {
          const GeglRectangle line = { result->x, result->y + y,
                                       result->width, 1 };
          gegl_buffer_get (input, &line, 1.0, fmt, row, stride,
                           GEGL_ABYSS_NONE);
          gegl_buffer_set (output, &line, level, fmt, row, stride);
        }
      g_free (row);
      return TRUE;
    }

  /* 三个通道的比值：σ_s / σ_t，常数通道保护成 1
   * Per-channel ratios σ_s / σ_t; constant channels are guarded to 1. */
  gdouble ratio[3];
  for (gint ch = 0; ch < 3; ch++)
    ratio[ch] = (src.std[ch] < MC_STD_EPS || tgt.std[ch] < MC_STD_EPS)
                  ? 1.0
                  : src.std[ch] / tgt.std[ch];

  /* 映射量：滑杆 100% → k = 1 精确匹配；渐隐整体打折
   * Amounts: slider 100% → k = 1 (exact match); fade scales everything. */
  const gdouble fade_k = 1.0 - o->fade / 100.0;
  const gdouble kL = (o->luminance / 100.0) * fade_k;
  const gdouble kC = (o->color_intensity / 100.0) * fade_k;

  const gint  w  = result->width;
  const gint  stride = (gint) (sizeof (gfloat) * 4 * (gsize) w);
  gfloat *in_band  = g_new (gfloat, (gsize) w * MC_BAND * 4);
  gfloat *out_band = g_new (gfloat, (gsize) w * MC_BAND * 4);

  for (gint y0 = 0; y0 < result->height; y0 += MC_BAND)
    {
      const gint nh = MIN (MC_BAND, result->height - y0);
      const GeglRectangle band = { result->x, result->y + y0, w, nh };

      gegl_buffer_get (input, &band, 1.0, fmt, in_band, stride,
                       GEGL_ABYSS_NONE);

      const gsize np = (gsize) w * nh;
      for (gsize i = 0; i < np; i++)
        match_pixel (in_band + i * 4, out_band + i * 4,
                     kL, kC, ratio, tgt.mean, src.mean, o->neutralize);

      gegl_buffer_set (output, &band, level, fmt, out_band, stride);
    }

  g_free (in_band);
  g_free (out_band);

  return TRUE;
}

/* ---- 类初始化 / class init --------------------------------------------- */

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass         *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationComposerClass *cclass =
    GEGL_OPERATION_COMPOSER_CLASS (klass);

  oclass->prepare = prepare;
  cclass->process = process;

  cclass->aux_label = _("Source");
  cclass->aux_description =
    _("Image whose colors are matched onto the input (statistics donor)");

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:match-color",
    "title",           _("Match Color"),
    "description",     _("PS Match Color: transfer the L*a*b* statistics "
                         "(mean and standard deviation) of another image or "
                         "layer onto this one, with luminance, color "
                         "intensity, fade and neutralize."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Color",
    "gimp:menu-label", _("Match Color"),
    NULL);
}

#endif
