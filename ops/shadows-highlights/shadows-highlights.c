/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:shadows-highlights
 * menu       Shadows/Highlights
 * purpose    等价于经典图像编辑器「图像 → 调整 → 阴影/高光」：按**邻域**亮度分别提亮阴影、
 *            压暗高光，而不是只看像素值本身。
 *            The the classic editor Image > Adjustments > Shadows/Highlights command:
 *            shadows are lifted and highlights pulled back according to the
 *            local neighbourhood, not the pixel value alone.
 * algorithm  参数与 经典图像编辑器 一一对应（阴影、高光各三项，加颜色、中间调对比度、
 *            修剪黑/白）。结构照 经典图像编辑器 25.4 的黑盒实测结果：
 *
 *            1. 亮度 lum = (max(R,G,B) + Rec.601 luma) / 2，直接作用于 sRGB 编码值。
 *            2. 邻域亮度 nb：先把 lum 按 σ=1.3559 轻模糊成 guide，再按 guide 的
 *               17 级量化把像素分成 17 组，每组用「权重 = 1 − |lum − g|/1.0152」
 *               做加权平均（Durand–Dorsey 分段线性双边）：权重和与加权和在 1/d
 *               的格子上先平均，再用 σ=1.1424·半径 的高斯模糊，最后按 guide 的
 *               小数级在相邻两级之间插值、双线性上采样回全分辨率。
 *               于是「同样的像素值，周围亮就少提、周围暗就多提」。
 *            3. 色调遮罩：把 nb 当自变量查 256 项表，表 = 1 − BetaCDF(level)。
 *               形状随「色调宽度」在 Beta(a,b) 之间插值（宽度 0 → Beta(1.95,23)
 *               的补，宽度 ≥95 → 1 − L）。高光用 255 − nb 的镜像。
 *            4. 曲线：自屏幕 1 − (1 − v)^q，q 在 1/2/4/8 之间按「数量」混合
 *               （数量 15 ≈ 1、50 ≈ 2、100 ≈ 3）。阴影把每个通道按
 *               mask × (curve − v) 抬起；高光用镜像压回。
 *            5. 颜色：只保留结果的新亮度，原色差按「颜色」缩放后加回
 *               （正值 exp(k·ΔY/maxY)，负值 1 + k·ΔY/maxY），并收进色域。
 *            6. 中间调对比度是亮度上的全局 S 曲线；修剪黑/白是直方图两端的
 *               拉伸（默认的 0.01% 也真的会拉伸，所以它需要一次全图预扫）。
 *
 *            Numbers come from a black-box fit of classic image editor 25.4; the same
 *            structure is used by PhotoCraft (MIT) — tables reproduced here.
 * type       GeglOperationFilter（空间域，按条带处理 / spatial, row strips）
 * reference  经典图像编辑器 Shadows/Highlights（黑盒实测 / black-box measurement）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_double (shadows_amount, _("Shadows Amount"), 35.0)
    value_range (0.0, 100.0)
    ui_range    (0.0, 100.0)
    ui_gamma    (2.0)
    description (_("How much to lift the shadows (the classic default 35)"))

property_double (shadows_width, _("Shadows Tonal Width"), 50.0)
    value_range (0.0, 100.0)
    ui_range    (0.0, 100.0)
    description (_("Range of shadow tones affected; small values stay in the darkest areas"))

property_double (shadows_radius, _("Shadows Radius"), 30.0)
    value_range (0.0, 2500.0)
    ui_range    (0.0, 300.0)
    ui_meta     ("unit", "pixel-distance")
    description (_("Size of the local neighbourhood that decides what counts as shadow"))

property_double (highlights_amount, _("Highlights Amount"), 0.0)
    value_range (0.0, 100.0)
    ui_range    (0.0, 100.0)
    ui_gamma    (2.0)
    description (_("How much to pull the highlights back (the classic default 0)"))

property_double (highlights_width, _("Highlights Tonal Width"), 50.0)
    value_range (0.0, 100.0)
    ui_range    (0.0, 100.0)
    description (_("Range of highlight tones affected"))

property_double (highlights_radius, _("Highlights Radius"), 30.0)
    value_range (0.0, 2500.0)
    ui_range    (0.0, 300.0)
    ui_meta     ("unit", "pixel-distance")
    description (_("Size of the local neighbourhood that decides what counts as highlight"))

property_double (color_correction, _("Color Correction"), 20.0)
    value_range (-100.0, 100.0)
    ui_range    (-100.0, 100.0)
    description (_("How much of the colour difference survives the brightness change; "
                   "positive keeps more saturation (the classic default +20)"))

property_double (midtone_contrast, _("Midtone Contrast"), 0.0)
    value_range (-100.0, 100.0)
    ui_range    (-100.0, 100.0)
    description (_("Global S-curve on the resulting brightness"))

property_double (black_clip, _("Black Clip"), 0.01)
    value_range (0.0, 50.0)
    ui_range    (0.0, 50.0)
    ui_digits   (2)
    description (_("Percent of the darkest pixels stretched to black (0.01 in the classic editor)"))

property_double (white_clip, _("White Clip"), 0.01)
    value_range (0.0, 50.0)
    ui_range    (0.0, 50.0)
    ui_digits   (2)
    description (_("Percent of the brightest pixels stretched to white (0.01 in the classic editor)"))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_shadows_highlights
#define GEGL_OP_C_SOURCE shadows-highlights.c
#include "gegl-op.h"

/* ---- 实测常数 / constants measured on 经典图像编辑器 ------------------------ */
#define SH_LEVELS  17       /* guide 的量化级数 / levels the guide is quantised to */
#define SH_RANGE   1.0152   /* 权重归零的亮度差 / difference at which a weight hits 0 */
#define SH_SPATIAL 1.1424   /* 邻域 σ 每像素半径 / neighbourhood sigma per radius pixel */
#define SH_GUIDE   1.3559   /* guide 预模糊 σ（像素）/ guide pre-blur sigma, pixels */
#define SH_HIST    4096     /* 修剪直方图格数 / bins of the clip histogram */
#define SH_STRIP   192      /* 最小条带高度 / minimum rows per internal strip */
#define SH_STRIP_MAX 1024   /* 条带高度上限 / maximum strip rows */
#define SH_MAXPX   60000000.0 /* 预扫的像素上限 / cap for the full-image pre-pass */
#define SH_CHUNK_FLT 8000000.0 /* 亮度取数块的 float 预算 ≈32MB / float budget per fetch chunk */
#define SH_PLANES_MAX 48000000.0 /* lum+guide+tmp 的 float 预算 ≈192MB / float budget for the three planes */

/* Beta(a,b) 形状，按色调宽度每 5 一步 / beta shape per 5 units of tonal width */
static const gdouble SH_MASK_BETA[20][2] = {
  { 1.9468, 22.9366 }, { 1.7770, 18.3471 }, { 1.6403, 14.7559 },
  { 1.5270, 11.9346 }, { 1.4269,  9.6467 }, { 1.3470,  7.8430 },
  { 1.2807,  6.4038 }, { 1.2240,  5.2384 }, { 1.1772,  4.2967 },
  { 1.1373,  3.5350 }, { 1.1021,  2.9109 }, { 1.0755,  2.4186 },
  { 1.0508,  2.0189 }, { 1.0307,  1.7034 }, { 1.0140,  1.4583 },
  { 1.0015,  1.2758 }, { 1.0000,  1.1403 }, { 1.0000,  1.0510 },
  { 1.0000,  1.0002 }, { 1.0000,  1.0000 }
};

/* 「颜色」正值 k(f) / positive colour correction */
static const gdouble SH_COLOR_UP[12][2] = {
  {   0.0, 0.0000 }, {   1.0, 0.1566 }, {   2.0, 0.2271 }, {   5.0, 0.3776 },
  {  10.0, 0.5653 }, {  20.0, 0.8669 }, {  30.0, 1.1299 }, {  40.0, 1.3748 },
  {  50.0, 1.6093 }, {  60.0, 1.8375 }, {  75.0, 2.1721 }, { 100.0, 2.7193 }
};

/* 「颜色」负值 k(f)（本身为负）/ negative colour correction */
static const gdouble SH_COLOR_DOWN[9][2] = {
  {   0.0,  0.0000 }, {   1.0, -0.0145 }, {   5.0, -0.0709 },
  {  10.0, -0.1373 }, {  20.0, -0.2570 }, {  30.0, -0.3612 },
  {  50.0, -0.5312 }, {  75.0, -0.6866 }, { 100.0, -0.7968 }
};

/* 中间调对比度 {值, k, p} / midtone contrast */
static const gdouble SH_MIDTONE[11][3] = {
  {-100.0,  -0.6955, 2.267 }, { -75.0,  -0.5873, 2.362 },
  { -50.0,  -0.4429, 2.492 }, { -25.0,  -0.2514, 2.667 },
  { -10.0,  -0.1088, 2.803 }, {   0.0,   0.0000, 2.900 },
  {  10.0,   0.1206, 3.016 }, {  25.0,   0.3262, 3.216 },
  {  50.0,   0.7423, 3.625 }, {  75.0,   1.2635, 4.160 },
  { 100.0,   1.9032, 4.850 }
};

/* ========================================================= 小工具 ----- */

static inline gfloat
sh_clampf (gfloat v, gfloat lo, gfloat hi)
{
  return v < lo ? lo : (v > hi ? hi : v);
}

static inline gint
sh_floor_div (gint a, gint b)
{
  gint q = a / b;

  if ((a % b) != 0 && ((a < 0) != (b < 0)))
    q--;
  return q;
}

static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}

/* 前置声明（sh_strip 用到缓存路径的辅助函数）
 * forward declarations (sh_strip shares helpers with the cached path) */
static void sh_lum_guide (GeglBuffer *in_buf, const Babl *fmt,
                          gint ex, gint ey, gint ew, gint eh,
                          gfloat **out_lum, gfloat **out_guide);

/* 两列表格线性插值 / piecewise-linear lookup in a two-column table */
static gdouble
sh_interp2 (const gdouble (*tab)[2], gint n, gdouble x)
{
  gint i;

  if (x <= tab[0][0])
    return tab[0][1];
  if (x >= tab[n - 1][0])
    return tab[n - 1][1];

  for (i = 1; i < n; i++)
    if (x <= tab[i][0])
      {
        gdouble t = (x - tab[i - 1][0]) / (tab[i][0] - tab[i - 1][0]);
        return tab[i - 1][1] + (tab[i][1] - tab[i - 1][1]) * t;
      }
  return tab[n - 1][1];
}

/* 可分高斯模糊（单通道 float，边界钳制）
 * separable Gaussian blur of a single-channel float plane, clamped edges */
static void
sh_blur (gfloat *buf, gfloat *tmp, gint w, gint h, gdouble sigma)
{
  gint    r, i, x, y;
  gfloat *ker;
  gdouble sum = 0.0;

  if (sigma <= 0.0 || w <= 0 || h <= 0)
    return;

  r = (gint) ceil (3.0 * sigma);
  if (r < 1)
    r = 1;

  ker = g_new (gfloat, 2 * r + 1);
  for (i = -r; i <= r; i++)
    {
      ker[i + r] = (gfloat) exp (-(gdouble) i * i / (2.0 * sigma * sigma));
      sum += ker[i + r];
    }
  for (i = 0; i <= 2 * r; i++)
    ker[i] = (gfloat) (ker[i] / sum);

  for (y = 0; y < h; y++)                       /* 横向 / horizontal */
    {
      const gfloat *src = buf + (gsize) y * w;
      gfloat       *dst = tmp + (gsize) y * w;

      /* 内部区域不需要钳制，只有左右 r 列走 CLAMP 分支——
       * 大半径时这个分支差异占整次模糊的两成上下
       * the interior needs no clamping; only the r edge columns branch */
      for (x = 0; x < MIN (r, w); x++)
        {
          gfloat acc = 0.0f;

          for (i = -r; i <= r; i++)
            acc += ker[i + r] * src[CLAMP (x + i, 0, w - 1)];
          dst[x] = acc;
        }
      for (; x < w - r; x++)
        {
          const gfloat *s = src + x - r;
          gfloat       *k = ker;
          gfloat       *e = ker + 2 * r + 1;
          gfloat        acc = 0.0f;

          while (k < e)
            acc += *k++ * *s++;
          dst[x] = acc;
        }
      for (; x < w; x++)
        {
          gfloat acc = 0.0f;

          for (i = -r; i <= r; i++)
            acc += ker[i + r] * src[CLAMP (x + i, 0, w - 1)];
          dst[x] = acc;
        }
    }

  for (y = 0; y < h; y++)                       /* 纵向 / vertical */
    {
      gfloat *dst = buf + (gsize) y * w;

      /* 与横向同理：内部行直接连续读 r 行窗口，上下边缘才钳制 */
      if (y < MIN (r, h))
        {
          for (x = 0; x < w; x++)
            {
              gfloat acc = 0.0f;

              for (i = -r; i <= r; i++)
                acc += ker[i + r] * tmp[(gsize) CLAMP (y + i, 0, h - 1) * w + x];
              dst[x] = acc;
            }
        }
      else if (y < h - r)
        {
          for (x = 0; x < w; x++)
            {
              const gfloat *s  = tmp + (gsize) (y - r) * w + x;
              const gfloat *k  = ker;
              const gfloat *ke = ker + 2 * r + 1;
              gfloat        acc = 0.0f;

              /* 行距 = w，窗口内不需要钳制 */
              while (k < ke)
                {
                  acc += *k++ * *s;
                  s   += w;
                }
              dst[x] = acc;
            }
        }
      else
        {
          for (x = 0; x < w; x++)
            {
              gfloat acc = 0.0f;

              for (i = -r; i <= r; i++)
                acc += ker[i + r] * tmp[(gsize) CLAMP (y + i, 0, h - 1) * w + x];
              dst[x] = acc;
            }
        }
    }

  g_free (ker);
}

/* =================================================== 色调遮罩 / mask ---- */

/* 1 − BetaCDF 在 256 级上的取值，形状由色调宽度插值得到
 * 1 - BetaCDF sampled at the 256 levels; shape interpolated over tonal width */
static void
sh_mask_table (gdouble tone, gdouble out[256])
{
  const gint sub = 16;
  gdouble t  = CLAMP (tone, 0.0, 95.0) / 5.0;
  gint    i0 = MIN ((gint) floor (t), 18);
  gdouble f  = t - i0;
  gdouble a, b, total = 0.0, cum = 0.0;
  gdouble *dens;
  gint    i, lv, k;

  a = SH_MASK_BETA[i0][0] + (SH_MASK_BETA[i0 + 1][0] - SH_MASK_BETA[i0][0]) * f;
  b = SH_MASK_BETA[i0][1] + (SH_MASK_BETA[i0 + 1][1] - SH_MASK_BETA[i0][1]) * f;

  dens = g_new (gdouble, 255 * sub);

  for (i = 0; i < 255 * sub; i++)
    {
      gdouble xs = (i + 0.5) / (255.0 * sub);

      dens[i] = exp ((a - 1.0) * log (xs) + (b - 1.0) * log1p (-xs));
      total  += dens[i];
    }

  out[0] = 1.0;
  for (lv = 1; lv < 256; lv++)
    {
      for (k = 0; k < sub; k++)
        cum += dens[(lv - 1) * sub + k];
      out[lv] = 1.0 - cum / total;
    }

  g_free (dens);
}

/* 数量 → 曲线强度：15 附近 1、50 得 2、100 得 3
 * amount to curve strength: ~1 near 15, 2 at 50, 3 at 100 */
static gdouble
sh_strength (gdouble amount)
{
  gdouble u = pow (CLAMP (amount, 0.0, 100.0) / 100.0, 0.6216);

  return u <= 0.3 ? u / 0.3 : (1.0 + 20.0 * u) / 7.0;
}

/* 自屏幕 1 − (1 − v)^q，q ∈ {1,2,4,8}，按 s 的小数部分混合
 * screen with itself: 1 - (1 - v)^q blended between q = 1, 2, 4, 8 */
static inline gfloat
sh_lift (gfloat s, gfloat v)
{
  gint   n = CLAMP ((gint) floor (s), 0, 2);
  gfloat t = sh_clampf (s - n, 0.0f, 1.0f);
  gfloat lo = powf (sh_clampf (1.0f - v, 0.0f, 1.0f), (gfloat) (1 << n));

  return 1.0f - ((1.0f - t) * lo + t * lo * lo);
}

/* ================================================ 上下文 / context ----- */

typedef struct
{
  guint8  *lv;                   /* 层级平面（extent 大小）/ level plane over the extent */
  gint     x, y, w, h;           /* 平面几何 / plane geometry */
  gdouble  sigma;                /* 0 = 未分配 / 0 = unassigned */
} ShPlane;

typedef struct
{
  gdouble sa, sw, sr;            /* 阴影 / shadows */
  gdouble ha, hw, hr;            /* 高光 / highlights */
  gdouble cc, mc, bc, wc;        /* 颜色、中间调、修剪 / colour, midtone, clips */
  gdouble s_str, h_str;          /* 曲线强度 / curve strengths */
  gdouble mid_k, mid_p;
  gdouble up_k, down_k;

  gdouble mask_s[256], mask_h[256];

  gboolean clip_ready;
  gdouble  clip_lo, clip_hi;

  ShPlane  ps, ph;               /* 缓存的邻域层级平面 / cached level planes */
  guint32  fp;                   /* 输入指纹 / input fingerprint */
  gboolean fp_valid;
  gdouble  params[10];           /* 上次 prepare 的参数 / params at last prepare */
  gboolean params_valid;

  GMutex lock;
} ShCtx;

static ShCtx *
sh_ctx (GeglOperation *op)
{
  ShCtx *c = GEGL_PROPERTIES (op)->user_data;

  if (!c)
    {
      c = g_new0 (ShCtx, 1);
      g_mutex_init (&c->lock);
      GEGL_PROPERTIES (op)->user_data = c;
    }
  return c;
}

/* ================================ 邻域亮度 / neighbourhood brightness --- */

/* 格子取值（绝对格索引 → 数组索引）/ cell access by absolute cell index */
static inline gfloat
sh_cell (const gfloat *a, gint bx0, gint by0, gint ncx, gint cx, gint cy)
{
  return a[(gsize) (cy - by0) * ncx + (cx - bx0)];
}

static inline gfloat
sh_cell_bilerp (const gfloat *a, gint bx0, gint by0, gint ncx,
                gint ix, gint iy, gfloat tx, gfloat ty)
{
  gfloat v00 = sh_cell (a, bx0, by0, ncx, ix,     iy);
  gfloat v10 = sh_cell (a, bx0, by0, ncx, ix + 1, iy);
  gfloat v01 = sh_cell (a, bx0, by0, ncx, ix,     iy + 1);
  gfloat v11 = sh_cell (a, bx0, by0, ncx, ix + 1, iy + 1);
  gfloat top = v00 + (v10 - v00) * tx;
  gfloat bot = v01 + (v11 - v01) * tx;

  return top + (bot - top) * ty;
}

/* 给定半径需要的输入边距 / input margin needed for a radius */
static gint
sh_margin (gdouble sigma)
{
  gint d  = MAX (1, (gint) floor (sigma / 4.0));
  gint mc = (gint) ceil (3.0 * sigma / (gdouble) d) + 1;
  gint m1 = (gint) ceil (3.0 * sigma) + 2;
  gint m2 = (mc + 1) * d + 2;

  return MAX (m1, m2);
}

/* 计算 ROI 的邻域亮度；lum/guide 覆盖扩展区 [ex,ey,ew,eh]，结果写 nb（rw×rh）
 * neighbourhood brightness of the ROI; lum/guide span the expanded region */
static void
sh_neighbourhood (const gfloat *lum, const gfloat *guide,
                  gint ex, gint ey, gint ew, gint eh,
                  gint rx, gint ry, gint rw, gint rh,
                  gdouble sigma, gfloat *nb)
{
  gint    d = (gint) floor (sigma / 4.0);
  gint    cbx, cby, cex, cey, mc, bx0, by0, ncx, ncy;
  gint    k, cx, cy, x, y;
  gsize   cells;
  gfloat *num, *den, *avg;

  if (d < 1)
    d = 1;

  if (sigma < 0.3)
    {
      /* 半径极小：不平均，直接用 guide / tiny radius: the guide is the value */
      for (y = 0; y < rh; y++)
        {
          gint gy = CLAMP (ry + y - ey, 0, eh - 1);

          for (x = 0; x < rw; x++)
            {
              gint gx = CLAMP (rx + x - ex, 0, ew - 1);

              nb[(gsize) y * rw + x] = guide[(gsize) gy * ew + gx];
            }
        }
      return;
    }

  cbx = sh_floor_div (ex, d);
  cby = sh_floor_div (ey, d);
  cex = sh_floor_div (ex + ew - 1, d);
  cey = sh_floor_div (ey + eh - 1, d);

  mc  = (gint) ceil (3.0 * sigma / d) + 1;
  bx0 = cbx - mc;
  by0 = cby - mc;
  ncx = (cex + mc) - bx0 + 1;
  ncy = (cey + mc) - by0 + 1;
  cells = (gsize) ncx * ncy;

  num = g_new0 (gfloat, cells * SH_LEVELS);
  den = g_new0 (gfloat, cells * SH_LEVELS);

  /* 1) 17 级加权分块累加，再在格子上做高斯。
   *    旧实现每个级各扫一遍像素（内存带宽 17 倍）；改为每像素单遍更新
   *    17 组累加器（sw/swl 各 17 项常驻缓存），累加顺序仍是格内行主序、
   *    每级之间顺序不变，结果逐位一致。
   *    One pass over the pixels updating all 17 range bins at once; per-bin
   *    accumulation order matches the old level-by-level loops exactly,
   *    so the result is bitwise identical. */
  {
    gfloat  gk_tab[SH_LEVELS];
    gfloat  inv = (gfloat) (1.0 / SH_RANGE);
    gfloat *tn  = g_new (gfloat, cells);
    gfloat *td  = g_new (gfloat, cells);

    for (k = 0; k < SH_LEVELS; k++)
      gk_tab[k] = (gfloat) k / (gfloat) (SH_LEVELS - 1);

    for (cy = cby; cy <= cey; cy++)
      {
        gint y0 = MAX (cy * d, ey);
        gint y1 = MIN (cy * d + d, ey + eh);

        for (cx = cbx; cx <= cex; cx++)
          {
            gint   x0 = MAX (cx * d, ex);
            gint   x1 = MIN (cx * d + d, ex + ew);
            gfloat sw[SH_LEVELS], swl[SH_LEVELS];

            for (k = 0; k < SH_LEVELS; k++)
              sw[k] = swl[k] = 0.0f;

            for (y = y0; y < y1; y++)
              {
                const gfloat *lp = lum + (gsize) (y - ey) * ew + (x0 - ex);
                gint          n  = x1 - x0;

                while (n--)
                  {
                    gfloat l = *lp++;

                    for (k = 0; k < SH_LEVELS; k++)
                      {
                        gfloat w = 1.0f - fabsf (l - gk_tab[k]) * inv;

                        if (w > 0.0f)
                          {
                            sw[k]  += w;
                            swl[k] += w * l;
                          }
                      }
                  }
              }

            for (k = 0; k < SH_LEVELS; k++)
              {
                num[(gsize) cells * k + (gsize) (cy - by0) * ncx + (cx - bx0)] += swl[k];
                den[(gsize) cells * k + (gsize) (cy - by0) * ncx + (cx - bx0)] += sw[k];
              }
          }
      }

    for (k = 0; k < SH_LEVELS; k++)
      {
        sh_blur (num + cells * k, tn, ncx, ncy, sigma / d);
        sh_blur (den + cells * k, td, ncx, ncy, sigma / d);
      }

    g_free (tn);
    g_free (td);
  }

  /* 2) 归一化 / normalise */
  avg = g_new (gfloat, cells * SH_LEVELS);
  for (k = 0; k < SH_LEVELS; k++)
    {
      const gfloat *nk = num + cells * k;
      const gfloat *dk = den + cells * k;
      gfloat       *ak = avg + cells * k;
      gfloat        gk = (gfloat) k / (gfloat) (SH_LEVELS - 1);
      gsize         i;

      for (i = 0; i < cells; i++)
        ak[i] = dk[i] > 1e-6f ? nk[i] / dk[i] : gk;
    }

  /* 3) 按 guide 的小数级在相邻两级间插值 + 双线性上采样
   *    interpolate the two neighbouring levels, bilinear upsample */
  for (y = 0; y < rh; y++)
    {
      gint gy = CLAMP (ry + y - ey, 0, eh - 1);

      for (x = 0; x < rw; x++)
        {
          gint   gx = CLAMP (rx + x - ex, 0, ew - 1);
          gfloat t  = sh_clampf (guide[(gsize) gy * ew + gx] * (SH_LEVELS - 1),
                                 0.0f, (gfloat) (SH_LEVELS - 1) - 1e-4f);
          gint   k0 = (gint) floorf (t);
          gfloat fr = t - k0;
          gfloat fx = (rx + x + 0.5f) / (gfloat) d - 0.5f;
          gfloat fy = (ry + y + 0.5f) / (gfloat) d - 0.5f;
          gint   ix = (gint) floorf (fx);
          gint   iy = (gint) floorf (fy);
          gfloat tx = fx - ix, ty = fy - iy;
          gfloat v0, v1;

          if (k0 > SH_LEVELS - 2)
            k0 = SH_LEVELS - 2;

          ix = CLAMP (ix, bx0, bx0 + ncx - 2);
          iy = CLAMP (iy, by0, by0 + ncy - 2);

          v0 = sh_cell_bilerp (avg + cells * k0,       bx0, by0, ncx, ix, iy, tx, ty);
          v1 = sh_cell_bilerp (avg + cells * (k0 + 1), bx0, by0, ncx, ix, iy, tx, ty);

          nb[(gsize) y * rw + x] = (1.0f - fr) * v0 + fr * v1;
        }
    }

  g_free (avg);
  g_free (num);
  g_free (den);
}

/* ============================================ 一条带 / one row strip ---- */

/* 处理 [rx,ry,rw,rh)；out 非空时写 RGB（A 原样），hist 非空时累计 y2 直方图。
 * Renders one strip; out may be NULL (histogram pre-pass). */
static void
sh_strip (ShCtx *c, GeglBuffer *in_buf, const Babl *fmt,
          gint rx, gint ry, gint rw, gint rh,
          gfloat *out, guint32 *hist)
{
  const gboolean do_s = c->sa > 0.0;
  const gboolean do_h = c->ha > 0.0;
  const gdouble  sig_s = SH_SPATIAL * c->sr;
  const gdouble  sig_h = SH_SPATIAL * c->hr;
  gint     M = 0;
  gint     ex, ey, ew, eh, x, y;
  gfloat  *roi_buf, *lum, *guide, *nb_s = NULL, *nb_h = NULL;
  gboolean share;

  if (do_s) M = MAX (M, sh_margin (sig_s));
  if (do_h) M = MAX (M, sh_margin (sig_h));

  ex = rx - M;
  ey = ry - M;
  ew = rw + 2 * M;
  eh = rh + 2 * M;

  /* 亮度 + guide 预模糊（分块取数，与缓存路径共用实现）
   * luma + guide blur via the shared chunked helper */
  sh_lum_guide (in_buf, fmt, ex, ey, ew, eh, &lum, &guide);

  share = do_s && do_h && fabs (c->sr - c->hr) < 1e-9;

  if (do_s)
    {
      nb_s = g_new (gfloat, (gsize) rw * rh);
      sh_neighbourhood (lum, guide, ex, ey, ew, eh, rx, ry, rw, rh, sig_s, nb_s);
    }
  if (do_h)
    {
      if (share)
        nb_h = nb_s;
      else
        {
          nb_h = g_new (gfloat, (gsize) rw * rh);
          sh_neighbourhood (lum, guide, ex, ey, ew, eh, rx, ry, rw, rh, sig_h, nb_h);
        }
    }

  /* 逐像素阶段只需要 ROI 本身的原图（此前是从扩展区大缓冲里偏移取）
   * the per-pixel stage only needs the ROI itself, not the whole
   * expanded RGBA block */
  roi_buf = g_new (gfloat, (gsize) rw * rh * 4);

  {
    GeglRectangle rect = { rx, ry, rw, rh };

    gegl_buffer_get (in_buf, &rect, 1.0, fmt, roi_buf, GEGL_AUTO_ROWSTRIDE,
                     GEGL_ABYSS_NONE);
  }

  for (y = 0; y < rh; y++)
    {
      for (x = 0; x < rw; x++)
        {
          const gfloat *p = roi_buf + ((gsize) y * rw + x) * 4;
          gfloat r = p[0], g = p[1], b = p[2];
          gfloat adj[3] = { r, g, b };
          gfloat y1, ym, y2, den, f, gain, k, span, diff[3];
          gint   i;

          if (do_s)
            {
              gint lv = CLAMP ((gint) lroundf (sh_clampf (nb_s[(gsize) y * rw + x], 0.0f, 1.0f) * 255.0f), 0, 255);
              gfloat m = (gfloat) c->mask_s[lv];

              if (m > 0.0f)
                for (i = 0; i < 3; i++)
                  adj[i] = adj[i] + m * (sh_lift ((gfloat) c->s_str, adj[i]) - adj[i]);
            }

          if (do_h)
            {
              gint lv, idx;
              gfloat m;

              lv  = CLAMP ((gint) lroundf (sh_clampf (nb_h[(gsize) y * rw + x], 0.0f, 1.0f) * 255.0f), 0, 255);
              idx = CLAMP (255 - lv, 0, 255);
              m   = (gfloat) c->mask_h[idx];

              if (m > 0.0f)
                for (i = 0; i < 3; i++)
                  {
                    gfloat inv = 1.0f - adj[i];

                    adj[i] = adj[i] - m * (sh_lift ((gfloat) c->h_str, inv) - inv);
                  }
            }

          y1 = 0.299f * r + 0.587f * g + 0.114f * b;
          ym = 0.299f * adj[0] + 0.587f * adj[1] + 0.114f * adj[2];
          ym = sh_clampf (ym, 0.0f, 1.0f);

          if (c->mc != 0.0)
            {
              gfloat t = MAX (0.0f, 4.0f * ym * (1.0f - ym));

              ym = sh_clampf (ym + (gfloat) c->mid_k * (ym - 0.5f)
                              * powf (t, (gfloat) c->mid_p), 0.0f, 1.0f);
            }

          if (hist)
            {
              gint bin = CLAMP ((gint) lroundf (ym * (SH_HIST - 1)), 0, SH_HIST - 1);

              hist[bin]++;
            }

          if (!out)
            continue;

          span = (gfloat) (c->clip_hi - c->clip_lo);
          y2   = span > 1e-6f ? sh_clampf ((ym - (gfloat) c->clip_lo) / span, 0.0f, 1.0f)
                              : ym;

          den  = MAX (MAX (y2, y1), 1e-6f);
          f    = fabsf (y2 - y1) / den;
          gain = c->cc >= 0.0 ? expf ((gfloat) c->up_k * f)
                              : 1.0f + (gfloat) c->down_k * f;

          /* 色差取**原像素**与它自己的亮度之差；只用 y2 当新亮度
           * the colour difference is the source pixel minus its own luma;
           * the adjusted pixel only supplies the new brightness y2 */
          k = 1.0f;
          for (i = 0; i < 3; i++)
            {
              gfloat q = (i == 0) ? r : (i == 1) ? g : b;

              diff[i] = (q - y1) * gain;
              if (diff[i] > 1e-9f)
                k = MIN (k, (1.0f - y2) / diff[i]);
              else if (diff[i] < -1e-9f)
                k = MIN (k, y2 / (-diff[i]));
            }
          k = sh_clampf (k, 0.0f, 1.0f);

          {
            gfloat *o = out + ((gsize) y * rw + x) * 4;

            o[0] = sh_clampf (y2 + k * diff[0], 0.0f, 1.0f);
            o[1] = sh_clampf (y2 + k * diff[1], 0.0f, 1.0f);
            o[2] = sh_clampf (y2 + k * diff[2], 0.0f, 1.0f);
            o[3] = p[3];
          }
        }
    }

  if (nb_h && nb_h != nb_s)
    g_free (nb_h);
  if (nb_s)
    g_free (nb_s);
  g_free (guide);
  g_free (lum);
  g_free (roi_buf);
}

/* 条带高度按 margin 自适应：条带越高，上下 margin 重复引入的上下文越少
 * （r300 时 margin 每侧 1277 行，192 行的条带等于把邻域算了 14 遍）。
 * lum+guide+tmp 三个平面用 SH_PLANES_MAX 兜底。
 * Strip height adapts to the margin: taller strips amortise the vertical
 * context rows; SH_PLANES_MAX caps the three luma/guide/tmp planes. */
static gint
sh_strip_height (gint rw, gint M)
{
  gint ew    = rw + 2 * M;
  gint strip = CLAMP (4 * M, SH_STRIP, SH_STRIP_MAX);

  while (strip > SH_STRIP &&
         3.0 * ew * (strip + 2.0 * M) > SH_PLANES_MAX)
    strip /= 2;
  return strip;
}

/* 由直方图求修剪端点 / clip endpoints from the histogram */
static void
sh_clip_levels (ShCtx *c, const guint32 *hist)
{
  gdouble total = 0.0;
  gint    i;
  gint    lo_idx = 0, hi_idx = SH_HIST - 1;
  gdouble acc;

  for (i = 0; i < SH_HIST; i++)
    total += hist[i];

  c->clip_lo = 0.0;
  c->clip_hi = 1.0;

  if (total <= 0.0)
    return;

  if (c->bc > 0.0)
    {
      gdouble target = c->bc / 100.0 * total;

      acc = 0.0;
      for (i = 0; i < SH_HIST; i++)
        {
          acc += hist[i];
          if (acc > target)
            break;
        }
      lo_idx = MIN (i, SH_HIST - 1);
      c->clip_lo = (gdouble) lo_idx / (SH_HIST - 1.0);
    }

  if (c->wc > 0.0)
    {
      gdouble target = c->wc / 100.0 * total;

      acc = 0.0;
      for (i = SH_HIST - 1; i >= 0; i--)
        {
          acc += hist[i];
          if (acc > target)
            break;
        }
      hi_idx = MAX (i, 0);
      c->clip_hi = (gdouble) hi_idx / (SH_HIST - 1.0);
    }

  if (c->clip_hi - c->clip_lo < 1e-3)
    {
      c->clip_lo = 0.0;
      c->clip_hi = 1.0;
    }
}

/* =================================== 全图缓存 / whole-image cache ------- */

/* GEGL 按列（或瓦片）并行调用 process()，每次调用都自带 margin 重复——
 * 12 列并行时邻域被整算 12 遍，r300 时每列的 margin 达 2554 像素、重复
 * 17 倍；黑/白修剪的预扫还要再翻一倍。因此把整个 extent 的邻域亮度
 * **只算一次**缓存成 8 位层级平面：遮罩查表本来就用
 * lv = lround(clamp(nb)*255)，8 位量化是无损的，20MP 也只占 40MB。
 * GEGL calls process() per column/tile, each dragging its own margin —
 * with 12 parallel columns the neighbourhood ran 12x, and 17x at r300.
 * The whole extent is computed once and cached as an 8-bit level plane:
 * the mask lookup already uses lv = lround(clamp(nb)*255), so 8-bit is
 * lossless here. */
#define SH_CACHE_MAXPX   20000000.0  /* 缓存路径的像素上限 / px cap for the cached path */
#define SH_CACHE_BUDGET  128000000.0 /* 过渡平面 float 预算 ≈512MB / float budget for transient planes */
#define SH_OUT_STRIP     256         /* 缓存路径的输出条带 / output strip rows in the cached path */

static void
sh_plane_reset (ShPlane *p)
{
  g_free (p->lv);
  p->lv = NULL;
  p->x = p->y = p->w = p->h = 0;
  p->sigma = 0.0;
}

/* 输入指纹：抽 24 条整行做哈希。点采样覆盖不到局部修改（GIMP 里在下层
 * 涂改时几何不变、改动又未必命中采样点），整行扫描能可靠察觉。
 * Input fingerprint: hash 24 evenly spaced full rows; point samples can
 * miss local upstream edits (geometry unchanged), full rows cannot. */
static guint32
sh_fingerprint (GeglBuffer *buf, const Babl *fmt, const GeglRectangle *ext)
{
  guint32 h = 2166136261u;
  const gint rows = 24;
  gfloat *row = g_new (gfloat, (gsize) ext->width * 4);
  gint    i, k;

  for (i = 0; i < rows; i++)
    {
      GeglRectangle r = { ext->x,
                          ext->y + (gint) ((gint64) ext->height * i / rows),
                          ext->width, 1 };

      gegl_buffer_get (buf, &r, 1.0, fmt, row, GEGL_AUTO_ROWSTRIDE,
                       GEGL_ABYSS_NONE);

      for (k = 0; k < ext->width * 4; k++)
        {
          guint32 v;

          memcpy (&v, &row[k], sizeof (v));
          h = (h ^ v) * 16777619u;
        }
    }

  g_free (row);
  return h;
}

/* 分块取扩展区、算亮度平面并做 guide 预模糊（sh_strip 与缓存路径共用）
 * Chunked fetch of the expanded region; luma + guide blur, shared by the
 * per-strip path and the cached path. */
static void
sh_lum_guide (GeglBuffer *in_buf, const Babl *fmt,
              gint ex, gint ey, gint ew, gint eh,
              gfloat **out_lum, gfloat **out_guide)
{
  gfloat *lum   = g_new (gfloat, (gsize) ew * eh);
  gint    chunk = MAX (1, (gint) (SH_CHUNK_FLT / (ew * 4.0)));
  gfloat *cbuf  = g_new (gfloat, (gsize) ew * chunk * 4);
  gint    cy, yy, xx;

  for (cy = 0; cy < eh; cy += chunk)
    {
      GeglRectangle rect = { ex, ey + cy, ew, MIN (chunk, eh - cy) };
      gint          ch   = rect.height;

      gegl_buffer_get (in_buf, &rect, 1.0, fmt, cbuf, GEGL_AUTO_ROWSTRIDE,
                       GEGL_ABYSS_CLAMP);

      for (yy = 0; yy < ch; yy++)
        for (xx = 0; xx < ew; xx++)
          {
            const gfloat *p = cbuf + ((gsize) yy * ew + xx) * 4;
            gfloat r = p[0], g = p[1], b = p[2];
            gfloat luma = 0.299f * r + 0.587f * g + 0.114f * b;
            gfloat mx   = MAX (r, MAX (g, b));

            lum[(gsize) (cy + yy) * ew + xx] = (mx + luma) * 0.5f;
          }
    }

  g_free (cbuf);

  {
    gfloat *guide = g_new (gfloat, (gsize) ew * eh);
    gfloat *tmp   = g_new (gfloat, (gsize) ew * eh);

    memcpy (guide, lum, sizeof (gfloat) * (gsize) ew * eh);
    sh_blur (guide, tmp, ew, eh, SH_GUIDE);
    g_free (tmp);

    *out_lum   = lum;
    *out_guide = guide;
  }
}

/* 把一个半径的邻域亮度算满整个 extent 并量化成 8 位层级平面
 * Compute the neighbourhood over the whole extent and quantise to a plane */
static void
sh_fill_plane (const gfloat *lum, const gfloat *guide,
               gint ex, gint ey, gint ew, gint eh,
               const GeglRectangle *ext, gdouble sigma, ShPlane *pl)
{
  gfloat *nb = g_new (gfloat, (gsize) ext->width * ext->height);
  gint    i, n = ext->width * ext->height;

  sh_neighbourhood (lum, guide, ex, ey, ew, eh,
                    ext->x, ext->y, ext->width, ext->height, sigma, nb);

  g_free (pl->lv);
  pl->lv = g_new (guint8, (gsize) n);

  for (i = 0; i < n; i++)
    pl->lv[i] = (guint8) CLAMP ((gint) lroundf (sh_clampf (nb[i], 0.0f, 1.0f) * 255.0f),
                                0, 255);

  g_free (nb);

  pl->x = ext->x;
  pl->y = ext->y;
  pl->w = ext->width;
  pl->h = ext->height;
  pl->sigma = sigma;
}

/* 轻量逐像素阶段：邻域平面已就绪，只做遮罩/曲线/颜色。
 * 与 sh_strip 的逐像素部分逐句相同，只是 nb 换成查缓存平面。
 * The per-pixel stage of sh_strip, byte-for-byte, sampling cached planes. */
static void
sh_pixels (ShCtx *c, GeglBuffer *in_buf, const Babl *fmt,
           gint rx, gint ry, gint rw, gint rh,
           const ShPlane *ps, const ShPlane *ph,
           gfloat *out, guint32 *hist)
{
  gfloat *roi_buf = g_new (gfloat, (gsize) rw * rh * 4);
  gint    x, y;

  {
    GeglRectangle rect = { rx, ry, rw, rh };

    gegl_buffer_get (in_buf, &rect, 1.0, fmt, roi_buf, GEGL_AUTO_ROWSTRIDE,
                     GEGL_ABYSS_NONE);
  }

  for (y = 0; y < rh; y++)
    {
      for (x = 0; x < rw; x++)
        {
          const gfloat *p = roi_buf + ((gsize) y * rw + x) * 4;
          gfloat r = p[0], g = p[1], b = p[2];
          gfloat adj[3] = { r, g, b };
          gfloat y1, ym, y2, den, f, gain, k, span, diff[3];
          gint   i;

          if (ps && ps->lv)
            {
              gint lv = ps->lv[(gsize) (ry + y - ps->y) * ps->w + (rx + x - ps->x)];
              gfloat m = (gfloat) c->mask_s[lv];

              if (m > 0.0f)
                for (i = 0; i < 3; i++)
                  adj[i] = adj[i] + m * (sh_lift ((gfloat) c->s_str, adj[i]) - adj[i]);
            }

          if (ph && ph->lv)
            {
              gint lv  = ph->lv[(gsize) (ry + y - ph->y) * ph->w + (rx + x - ph->x)];
              gint idx = CLAMP (255 - lv, 0, 255);
              gfloat m = (gfloat) c->mask_h[idx];

              if (m > 0.0f)
                for (i = 0; i < 3; i++)
                  {
                    gfloat inv = 1.0f - adj[i];

                    adj[i] = adj[i] - m * (sh_lift ((gfloat) c->h_str, inv) - inv);
                  }
            }

          y1 = 0.299f * r + 0.587f * g + 0.114f * b;
          ym = 0.299f * adj[0] + 0.587f * adj[1] + 0.114f * adj[2];
          ym = sh_clampf (ym, 0.0f, 1.0f);

          if (c->mc != 0.0)
            {
              gfloat t = MAX (0.0f, 4.0f * ym * (1.0f - ym));

              ym = sh_clampf (ym + (gfloat) c->mid_k * (ym - 0.5f)
                              * powf (t, (gfloat) c->mid_p), 0.0f, 1.0f);
            }

          if (hist)
            {
              gint bin = CLAMP ((gint) lroundf (ym * (SH_HIST - 1)), 0, SH_HIST - 1);

              hist[bin]++;
            }

          if (!out)
            continue;

          span = (gfloat) (c->clip_hi - c->clip_lo);
          y2   = span > 1e-6f ? sh_clampf ((ym - (gfloat) c->clip_lo) / span, 0.0f, 1.0f)
                              : ym;

          den  = MAX (MAX (y2, y1), 1e-6f);
          f    = fabsf (y2 - y1) / den;
          gain = c->cc >= 0.0 ? expf ((gfloat) c->up_k * f)
                              : 1.0f + (gfloat) c->down_k * f;

          {
            gfloat kk = 1.0f;
            gfloat *o = out + ((gsize) y * rw + x) * 4;

            for (i = 0; i < 3; i++)
              {
                gfloat q = (i == 0) ? r : (i == 1) ? g : b;

                diff[i] = (q - y1) * gain;
                if (diff[i] > 1e-9f)
                  kk = MIN (kk, (1.0f - y2) / diff[i]);
                else if (diff[i] < -1e-9f)
                  kk = MIN (kk, y2 / (-diff[i]));
              }
            kk = sh_clampf (kk, 0.0f, 1.0f);

            o[0] = sh_clampf (y2 + kk * diff[0], 0.0f, 1.0f);
            o[1] = sh_clampf (y2 + kk * diff[1], 0.0f, 1.0f);
            o[2] = sh_clampf (y2 + kk * diff[2], 0.0f, 1.0f);
            o[3] = p[3];
          }
        }
    }

  g_free (roi_buf);
}

/* 确保两个半径的层级平面与修剪端点就绪（锁内，先到者算，其余线程等待）
 * Ensure the level planes and clip endpoints are ready (first caller
 * computes under the lock, the rest wait and sample). */
static void
sh_ensure_planes (ShCtx *c, GeglBuffer *in_buf, const Babl *fmt,
                  const GeglRectangle *ext)
{
  const gboolean do_s   = c->sa > 0.0;
  const gboolean do_h   = c->ha > 0.0;
  const gboolean share  = do_s && do_h && fabs (c->sr - c->hr) < 1e-9;
  const gdouble  sig_s  = SH_SPATIAL * c->sr;
  const gdouble  sig_h  = SH_SPATIAL * c->hr;
  const gboolean need_clip = c->bc > 0.0 || c->wc > 0.0;
  gint           M = 0;

  if (do_s) M = MAX (M, sh_margin (sig_s));
  if (do_h && !share) M = MAX (M, sh_margin (sig_h));

  g_mutex_lock (&c->lock);

  {
    guint32 fp = sh_fingerprint (in_buf, fmt, ext);

    if (!c->fp_valid || c->fp != fp)
      {
        sh_plane_reset (&c->ps);
        sh_plane_reset (&c->ph);
        c->fp        = fp;
        c->fp_valid  = TRUE;
        c->clip_ready = FALSE;
        c->clip_lo    = 0.0;
        c->clip_hi    = 1.0;
      }
  }

  if (c->ps.lv && (c->ps.x != ext->x || c->ps.y != ext->y ||
                   c->ps.w != ext->width || c->ps.h != ext->height))
    sh_plane_reset (&c->ps);
  if (c->ph.lv && (c->ph.x != ext->x || c->ph.y != ext->y ||
                   c->ph.w != ext->width || c->ph.h != ext->height))
    sh_plane_reset (&c->ph);

  if ((do_s && c->ps.lv == NULL) || (do_h && !share && c->ph.lv == NULL))
    {
      gfloat *lum, *guide;
      gint    ex = ext->x - M, ey = ext->y - M;
      gint    ew = ext->width + 2 * M, eh = ext->height + 2 * M;

      sh_lum_guide (in_buf, fmt, ex, ey, ew, eh, &lum, &guide);

      if (do_s && c->ps.lv == NULL)
        sh_fill_plane (lum, guide, ex, ey, ew, eh, ext, sig_s, &c->ps);
      if (do_h && !share && c->ph.lv == NULL)
        sh_fill_plane (lum, guide, ex, ey, ew, eh, ext, sig_h, &c->ph);

      g_free (guide);
      g_free (lum);
    }

  if (need_clip && !c->clip_ready)
    {
      guint32 *hist = g_new0 (guint32, SH_HIST);
      const ShPlane *ps = do_s ? &c->ps : NULL;
      const ShPlane *ph = do_h ? (share ? &c->ps : &c->ph) : NULL;
      gint           sy;

      for (sy = ext->y; sy < ext->y + ext->height; sy += SH_OUT_STRIP)
        sh_pixels (c, in_buf, fmt, ext->x, sy, ext->width,
                   MIN (SH_OUT_STRIP, ext->y + ext->height - sy),
                   ps, ph, NULL, hist);

      sh_clip_levels (c, hist);
      g_free (hist);

      c->clip_ready = TRUE;
    }

  g_mutex_unlock (&c->lock);
}

/* ===================================================== GEGL 钩子 ----- */

static void
prepare (GeglOperation *op)
{
  ShCtx *c = sh_ctx (op);
  gdouble p[10];

  g_object_get (G_OBJECT (op),
    "shadows-amount",     &p[0],
    "shadows-width",      &p[1],
    "shadows-radius",     &p[2],
    "highlights-amount",  &p[3],
    "highlights-width",   &p[4],
    "highlights-radius",  &p[5],
    "color-correction",   &p[6],
    "midtone-contrast",   &p[7],
    "black-clip",         &p[8],
    "white-clip",         &p[9],
    NULL);

  /* 参数真的变了才弃缓存；缩放/滚动等不改参数的重渲染直接复用
   * drop the cache only when a parameter actually changed */
  if (!c->params_valid || memcmp (c->params, p, sizeof (p)) != 0)
    {
      sh_plane_reset (&c->ps);
      sh_plane_reset (&c->ph);
      c->fp_valid   = FALSE;
      c->clip_ready = FALSE;
      c->clip_lo    = 0.0;
      c->clip_hi    = 1.0;
      memcpy (c->params, p, sizeof (p));
      c->params_valid = TRUE;
    }

  c->sa = p[0];  c->sw = p[1];  c->sr = p[2];
  c->ha = p[3];  c->hw = p[4];  c->hr = p[5];
  c->cc = p[6];  c->mc = p[7];  c->bc = p[8];  c->wc = p[9];

  c->s_str = sh_strength (c->sa);
  c->h_str = sh_strength (c->ha);

  {
    gint i, n = G_N_ELEMENTS (SH_MIDTONE);
    gdouble k = 0.0, p = 2.9;

    for (i = 1; i < n; i++)
      if (c->mc <= SH_MIDTONE[i][0])
        {
          gdouble t = (c->mc - SH_MIDTONE[i - 1][0])
                    / (SH_MIDTONE[i][0] - SH_MIDTONE[i - 1][0]);

          k = SH_MIDTONE[i - 1][1] + (SH_MIDTONE[i][1] - SH_MIDTONE[i - 1][1]) * t;
          p = SH_MIDTONE[i - 1][2] + (SH_MIDTONE[i][2] - SH_MIDTONE[i - 1][2]) * t;
          break;
        }
    if (c->mc >= SH_MIDTONE[n - 1][0])
      {
        k = SH_MIDTONE[n - 1][1];
        p = SH_MIDTONE[n - 1][2];
      }
    c->mid_k = k;
    c->mid_p = p;
  }

  c->up_k   = sh_interp2 (SH_COLOR_UP,   G_N_ELEMENTS (SH_COLOR_UP),   c->cc);
  c->down_k = sh_interp2 (SH_COLOR_DOWN, G_N_ELEMENTS (SH_COLOR_DOWN), -c->cc);

  sh_mask_table (c->sw, c->mask_s);
  sh_mask_table (c->hw, c->mask_h);

  gegl_operation_set_format (op, "input",  perceptual_format (op));
  gegl_operation_set_format (op, "output", perceptual_format (op));
}

static gboolean
process (GeglOperation       *op,
         GeglBuffer          *in_buf,
         GeglBuffer          *out_buf,
         const GeglRectangle *roi,
         gint                 level)
{
  ShCtx        *c = sh_ctx (op);
  const Babl   *fmt = perceptual_format (op);
  const gboolean need_clip = c->bc > 0.0 || c->wc > 0.0;
  gint          y;

  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  /* 什么都不做：直接复制 / nothing to do, just copy */
  if (c->sa <= 0.0 && c->ha <= 0.0 && c->mc == 0.0 && c->cc == 0.0 && !need_clip)
    {
      /* 逐行 get/set 的开销在 3M 像素下能吃掉几百毫秒，整块一次搬
       * row-by-row buffer copies used to cost hundreds of ms; move in one go */
      gfloat *line = g_new (gfloat, (gsize) roi->width * roi->height * 4);
      GeglRectangle all = { roi->x, roi->y, roi->width, roi->height };

      gegl_buffer_get (in_buf, &all, 1.0, fmt, line,
                       GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);
      gegl_buffer_set (out_buf, &all, 0, fmt, line, GEGL_AUTO_ROWSTRIDE);
      g_free (line);
      return TRUE;
    }

  /* 全图缓存路径：邻域只算一次，各列/瓦片直接采样层级平面。
   * GEGL 并行调用本函数时（实测 3M 像素拆成 12 根 171 宽的竖条），
   * margin 会随调用次数线性重复；缓存后每根竖条只剩轻量逐像素。
   * Cached path: the neighbourhood is computed once, columns/tiles only
   * sample the plane. GEGL splits a 3MP image into 12 parallel columns;
   * without the cache each column redid the margins. */
  {
    const GeglRectangle *ext = gegl_buffer_get_extent (in_buf);
    gint                  M = 0;
    gboolean              can_cache;

    if (c->sa > 0.0) M = MAX (M, sh_margin (SH_SPATIAL * c->sr));
    if (c->ha > 0.0 && fabs (c->sr - c->hr) >= 1e-9)
      M = MAX (M, sh_margin (SH_SPATIAL * c->hr));

    can_cache = ext &&
                !g_getenv ("SH_NO_CACHE") &&
                (gdouble) ext->width * ext->height <= SH_CACHE_MAXPX &&
                4.0 * (ext->width + 2.0 * M) * (ext->height + 2.0 * M)
                    <= SH_CACHE_BUDGET;

    if (can_cache)
      {
        const ShPlane *ps, *ph;
        const gboolean share = c->sa > 0.0 && c->ha > 0.0 &&
                               fabs (c->sr - c->hr) < 1e-9;
        gint y;

        sh_ensure_planes (c, in_buf, fmt, ext);

        ps = (c->sa > 0.0) ? &c->ps : NULL;
        ph = (c->ha > 0.0) ? (share ? &c->ps : &c->ph) : NULL;

        for (y = 0; y < roi->height; y += SH_OUT_STRIP)
          {
            gint          hh  = MIN (SH_OUT_STRIP, roi->height - y);
            GeglRectangle rect = { roi->x, roi->y + y, roi->width, hh };
            gfloat       *buf  = g_new (gfloat, (gsize) roi->width * hh * 4);

            sh_pixels (c, in_buf, fmt, roi->x, roi->y + y, roi->width, hh,
                       ps, ph, buf, NULL);
            gegl_buffer_set (out_buf, &rect, 0, fmt, buf, GEGL_AUTO_ROWSTRIDE);
            g_free (buf);
          }

        return TRUE;
      }
  }

  /* 回退路径（图超大或 margin 超预算）：按条带就地计算。
   * Fallback (huge image or margin over budget): compute per strip. */
  if (need_clip)
    {
      g_mutex_lock (&c->lock);
      if (!c->clip_ready)
        {
          const GeglRectangle *ext = gegl_buffer_get_extent (in_buf);

          if (ext && (gdouble) ext->width * ext->height <= SH_MAXPX)
            {
              guint32 *hist = g_new0 (guint32, SH_HIST);
              gint     sy;
              gint     M = 0, strip;

              if (c->sa > 0.0) M = MAX (M, sh_margin (SH_SPATIAL * c->sr));
              if (c->ha > 0.0) M = MAX (M, sh_margin (SH_SPATIAL * c->hr));
              strip = sh_strip_height (ext->width, MAX (M, 1));

              for (sy = ext->y; sy < ext->y + ext->height; sy += strip)
                {
                  gint hh = MIN (strip, ext->y + ext->height - sy);

                  sh_strip (c, in_buf, fmt, ext->x, sy, ext->width, hh, NULL, hist);
                }
              sh_clip_levels (c, hist);
              g_free (hist);
            }
          c->clip_ready = TRUE;
        }
      g_mutex_unlock (&c->lock);
    }

  {
    gint     M = 0, strip;

    if (c->sa > 0.0) M = MAX (M, sh_margin (SH_SPATIAL * c->sr));
    if (c->ha > 0.0) M = MAX (M, sh_margin (SH_SPATIAL * c->hr));
    strip = sh_strip_height (roi->width, MAX (M, 1));

    for (y = 0; y < roi->height; y += strip)
      {
        gint     hh = MIN (strip, roi->height - y);
        gfloat  *buf = g_new (gfloat, (gsize) roi->width * hh * 4);
        GeglRectangle rect = { roi->x, roi->y + y, roi->width, hh };

        sh_strip (c, in_buf, fmt, roi->x, roi->y + y, roi->width, hh, buf, NULL);

        /* 整条一次写回 / one buffer_set per strip, not per row */
        gegl_buffer_set (out_buf, &rect, 0, fmt, buf, GEGL_AUTO_ROWSTRIDE);
        g_free (buf);
      }
  }

  return TRUE;
}

static void
finalize (GObject *object)
{
  ShCtx *c = GEGL_PROPERTIES (object)->user_data;

  if (c)
    {
      sh_plane_reset (&c->ps);
      sh_plane_reset (&c->ph);
      g_mutex_clear (&c->lock);
      g_free (c);
      GEGL_PROPERTIES (object)->user_data = NULL;
    }

  G_OBJECT_CLASS (gegl_op_parent_class)->finalize (object);
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GObjectClass             *object_class = G_OBJECT_CLASS (klass);
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  object_class->finalize = finalize;
  oclass->prepare  = prepare;
  fclass->process  = process;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:shadows-highlights",
    "title",           _("Shadows/Highlights"),
    "description",     _("the classic editor's Shadows/Highlights: lifts shadows and pulls "
                         "highlights back according to an edge-aware local "
                         "neighbourhood, with colour correction, midtone contrast "
                         "and black/white clipping."),
    "gimp:menu-path",  "<Image>/SuperMrWang/Tone",
    "gimp:menu-label", _("Shadows/Highlights"),
    NULL);
}

#endif
