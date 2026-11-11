/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:shadows-highlights
 * menu       Shadows/Highlights
 * purpose    等价 PS「图像 → 调整 → 阴影/高光」：按**邻域**亮度分别提亮阴影、
 *            压暗高光，而不是只看像素值本身。
 *            The Photoshop Image > Adjustments > Shadows/Highlights command:
 *            shadows are lifted and highlights pulled back according to the
 *            local neighbourhood, not the pixel value alone.
 * algorithm  参数与 PS 一一对应（阴影、高光各三项，加颜色、中间调对比度、
 *            修剪黑/白）。结构照 PS 25.4 的黑盒实测结果：
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
 *            Numbers come from a black-box fit of Photoshop 25.4; the same
 *            structure is used by PhotoCraft (MIT) — tables reproduced here.
 * type       GeglOperationFilter（空间域，按条带处理 / spatial, row strips）
 * reference  Photoshop Shadows/Highlights（黑盒实测 / black-box measurement）
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
    description (_("How much to lift the shadows (Photoshop default 35)"))

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
    description (_("How much to pull the highlights back (Photoshop default 0)"))

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
                   "positive keeps more saturation (Photoshop default +20)"))

property_double (midtone_contrast, _("Midtone Contrast"), 0.0)
    value_range (-100.0, 100.0)
    ui_range    (-100.0, 100.0)
    description (_("Global S-curve on the resulting brightness"))

property_double (black_clip, _("Black Clip"), 0.01)
    value_range (0.0, 50.0)
    ui_range    (0.0, 50.0)
    ui_digits   (2)
    description (_("Percent of the darkest pixels stretched to black (0.01 in Photoshop)"))

property_double (white_clip, _("White Clip"), 0.01)
    value_range (0.0, 50.0)
    ui_range    (0.0, 50.0)
    ui_digits   (2)
    description (_("Percent of the brightest pixels stretched to white (0.01 in Photoshop)"))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_shadows_highlights
#define GEGL_OP_C_SOURCE shadows-highlights.c
#include "gegl-op.h"

/* ---- 实测常数 / constants measured on Photoshop ------------------------ */
#define SH_LEVELS  17       /* guide 的量化级数 / levels the guide is quantised to */
#define SH_RANGE   1.0152   /* 权重归零的亮度差 / difference at which a weight hits 0 */
#define SH_SPATIAL 1.1424   /* 邻域 σ 每像素半径 / neighbourhood sigma per radius pixel */
#define SH_GUIDE   1.3559   /* guide 预模糊 σ（像素）/ guide pre-blur sigma, pixels */
#define SH_HIST    4096     /* 修剪直方图格数 / bins of the clip histogram */
#define SH_STRIP   192      /* 内部分条高度 / rows per internal strip */
#define SH_MAXPX   60000000.0 /* 预扫的像素上限 / cap for the full-image pre-pass */

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

      for (x = 0; x < w; x++)
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

      for (x = 0; x < w; x++)
        {
          gfloat acc = 0.0f;

          for (i = -r; i <= r; i++)
            acc += ker[i + r] * tmp[(gsize) CLAMP (y + i, 0, h - 1) * w + x];
          dst[x] = acc;
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
  gdouble sa, sw, sr;            /* 阴影 / shadows */
  gdouble ha, hw, hr;            /* 高光 / highlights */
  gdouble cc, mc, bc, wc;        /* 颜色、中间调、修剪 / colour, midtone, clips */
  gdouble s_str, h_str;          /* 曲线强度 / curve strengths */
  gdouble mid_k, mid_p;
  gdouble up_k, down_k;

  gdouble mask_s[256], mask_h[256];

  gboolean clip_ready;
  gdouble  clip_lo, clip_hi;

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

  /* 1) 17 级加权分块累加，再在格子上做高斯
   *    17 weighted range bins per cell, then blur the cell grid */
  for (k = 0; k < SH_LEVELS; k++)
    {
      gfloat  gk  = (gfloat) k / (gfloat) (SH_LEVELS - 1);
      gfloat  inv = (gfloat) (1.0 / SH_RANGE); 
      gfloat *nk  = num + cells * k;
      gfloat *dk  = den + cells * k;
      gfloat *tn  = g_new (gfloat, cells);
      gfloat *td  = g_new (gfloat, cells);

      for (cy = cby; cy <= cey; cy++)
        {
          gint y0  = MAX (cy * d, ey);
          gint y1  = MIN (cy * d + d, ey + eh);
          gint row = (cy - by0) * ncx - bx0;

          for (cx = cbx; cx <= cex; cx++)
            {
              gint   x0 = MAX (cx * d, ex);
              gint   x1 = MIN (cx * d + d, ex + ew);
              gfloat sw = 0.0f, swl = 0.0f;

              for (y = y0; y < y1; y++)
                {
                  const gfloat *lp = lum + (gsize) (y - ey) * ew + (x0 - ex);
                  gint          n  = x1 - x0;

                  while (n--)
                    {
                      gfloat l = *lp++;
                      gfloat w = 1.0f - fabsf (l - gk) * inv;

                      if (w > 0.0f)
                        {
                          sw  += w;
                          swl += w * l;
                        }
                    }
                }
              nk[row + cx] += swl;
              dk[row + cx] += sw;
            }
        }

      sh_blur (nk, tn, ncx, ncy, sigma / d);
      sh_blur (dk, td, ncx, ncy, sigma / d);

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
  gfloat  *ebuf, *lum, *guide, *nb_s = NULL, *nb_h = NULL;
  gboolean share;

  if (do_s) M = MAX (M, sh_margin (sig_s));
  if (do_h) M = MAX (M, sh_margin (sig_h));

  ex = rx - M;
  ey = ry - M;
  ew = rw + 2 * M;
  eh = rh + 2 * M;

  ebuf = g_new (gfloat, (gsize) ew * eh * 4);
  lum  = g_new (gfloat, (gsize) ew * eh);

  {
    GeglRectangle rect = { ex, ey, ew, eh };

    gegl_buffer_get (in_buf, &rect, 1.0, fmt, ebuf, GEGL_AUTO_ROWSTRIDE,
                     GEGL_ABYSS_CLAMP);
  }

  for (y = 0; y < eh; y++)
    for (x = 0; x < ew; x++)
      {
        const gfloat *p = ebuf + ((gsize) y * ew + x) * 4;
        gfloat r = p[0], g = p[1], b = p[2];
        gfloat luma = 0.299f * r + 0.587f * g + 0.114f * b;
        gfloat mx   = MAX (r, MAX (g, b));

        lum[(gsize) y * ew + x] = (mx + luma) * 0.5f;
      }

  guide = g_new (gfloat, (gsize) ew * eh);
  memcpy (guide, lum, sizeof (gfloat) * (gsize) ew * eh);
  {
    gfloat *tmp = g_new (gfloat, (gsize) ew * eh);

    sh_blur (guide, tmp, ew, eh, SH_GUIDE); 
    g_free (tmp);
  }

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

  for (y = 0; y < rh; y++)
    {
      for (x = 0; x < rw; x++)
        {
          const gfloat *p = ebuf + ((gsize) (y + M) * ew + (x + M)) * 4;
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
  g_free (ebuf);
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

/* ===================================================== GEGL 钩子 ----- */

static void
prepare (GeglOperation *op)
{
  ShCtx *c = sh_ctx (op);

  g_object_get (G_OBJECT (op),
    "shadows-amount",     &c->sa,
    "shadows-width",      &c->sw,
    "shadows-radius",     &c->sr,
    "highlights-amount",  &c->ha,
    "highlights-width",   &c->hw,
    "highlights-radius",  &c->hr,
    "color-correction",   &c->cc,
    "midtone-contrast",   &c->mc,
    "black-clip",         &c->bc,
    "white-clip",         &c->wc,
    NULL);

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

  /* 参数或输入变了，修剪端点要重新统计
   * the clip endpoints must be measured again for new settings / inputs */
  c->clip_ready = FALSE;
  c->clip_lo    = 0.0;      /* 两个修剪都为 0（或图太大不预扫）时走这里，
                             * 否则下面的除法会 0/0 把整图推成纯白 */
  c->clip_hi    = 1.0;

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
      gfloat *line = g_new (gfloat, roi->width * 4);

      for (y = 0; y < roi->height; y++)
        {
          GeglRectangle row = { roi->x, roi->y + y, roi->width, 1 };

          gegl_buffer_get (in_buf, &row, 1.0, fmt, line,
                           GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);
          gegl_buffer_set (out_buf, &row, 0, fmt, line, GEGL_AUTO_ROWSTRIDE);
        }
      g_free (line);
      return TRUE;
    }

  /* 修剪黑/白要先知道全图的新亮度直方图 —— 一次全图预扫
   * Black/White Clip needs the histogram of the new luma over the whole image */
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

              for (sy = ext->y; sy < ext->y + ext->height; sy += SH_STRIP)
                {
                  gint hh = MIN (SH_STRIP, ext->y + ext->height - sy);

                  sh_strip (c, in_buf, fmt, ext->x, sy, ext->width, hh, NULL, hist);
                }
              sh_clip_levels (c, hist);
              g_free (hist);
            }
          c->clip_ready = TRUE;
        }
      g_mutex_unlock (&c->lock);
    }

  for (y = 0; y < roi->height; y += SH_STRIP)
    {
      gint     hh = MIN (SH_STRIP, roi->height - y);
      gfloat  *buf = g_new (gfloat, (gsize) roi->width * hh * 4);
      gint     r;

      sh_strip (c, in_buf, fmt, roi->x, roi->y + y, roi->width, hh, buf, NULL);

      for (r = 0; r < hh; r++)
        {
          GeglRectangle row = { roi->x, roi->y + y + r, roi->width, 1 };

          gegl_buffer_set (out_buf, &row, 0, fmt,
                           buf + (gsize) r * roi->width * 4, GEGL_AUTO_ROWSTRIDE);
        }
      g_free (buf);
    }

  return TRUE;
}

static void
finalize (GObject *object)
{
  ShCtx *c = GEGL_PROPERTIES (object)->user_data;

  if (c)
    {
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
    "description",     _("Photoshop's Shadows/Highlights: lifts shadows and pulls "
                         "highlights back according to an edge-aware local "
                         "neighbourhood, with colour correction, midtone contrast "
                         "and black/white clipping."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Shadows/Highlights"),
    NULL);
}

#endif
