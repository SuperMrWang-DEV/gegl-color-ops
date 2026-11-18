/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:match-color
 * menu       Match Color
 * purpose    经典图像编辑器 匹配颜色：把另一张图（或另一层）的 L*a*b* 统计量迁移到本层
 *            the classic editor Match Color: transfer the L*a*b* statistics of another image
 *            (or layer) onto this layer.
 * algorithm  与 经典图像编辑器 一致地工作在 CIELAB（D50）里，三种映射方法（下拉框）：
 *            ① 统计（默认，= 经典图像编辑器 的行为）：逐通道均值/标准差仿射映射
 *                 out = (v − μ_t) · (σ_s / σ_t) + μ_s        （Reinhard 2001）
 *            ② Monge-Kantorovich：用完整 3×3 协方差的线性最优传输映射
 *                 out = T · (v − μ_t) + μ_s,  T Σ_t Tᵀ = Σ_s
 *               多利用了 L/a/b 之间的协方差——颜色是相关的，不是三个独立通道，
 *               所以不会把同一种颜色沿某条通道撕开，色斑/空洞伪影明显更少。
 *            ③ MKL + 直方图：先做 ②，再逐通道把残差的分布拉到来源的直方图上
 *               （相当于 HM-MKL-HM），线性方法够不到的色调尾部由直方图补齐。
 *            亮度滑杆只缩放 L 的映射量，颜色强度只缩放 a/b 的映射量（向原值
 *            lerp：滑杆=100 是精确匹配，200 是双倍，1 几乎不动），渐隐等价于
 *            整体映射量乘 (1 − fade)。中和把输出的 a/b 均值强制为 0（去色偏），
 *            L 照常。
 *            全局统计量与逐块渲染是天然冲突的：process 每次只拿到一小块，而
 *            均值/协方差/直方图必须对整层算。做法是首次 process 时整层读一遍
 *            input/aux 攒出统计量，缓存在 operation 实例上（互斥锁保护，键为
 *            源节点 + extent + 金字塔层级），后续块直接复用——预览时拖滑杆
 *            不会反复重算。来源图层内容变了（预览场景）勾一次「重算统计」即可。
 *            Works in CIELAB (D50) like the classic editor, with three methods:
 *            per-channel mean/std (the classic editor's behaviour), the full
 *            3x3 linear Monge-Kantorovich map (Pitie & Kokaram 2007), and MKL
 *            followed by per-channel histogram matching of the residual.
 *            Global statistics conflict with tiled rendering, so the first
 *            process() call reads both layers once and caches the numbers on
 *            the operation instance (mutex-guarded, keyed by source node +
 *            extent + level); later tiles reuse them, so preview slider drags
 *            don't recompute.
 * type       GeglOperationComposer（input + aux 双输入 / two inputs）
 * reference  经典图像编辑器「图像 → 调整 → 匹配颜色」
 *            Image > Adjustments > Match Color; Reinhard et al.,
 *            "Color Transfer between Images" (2001); F. Pitie, A. Kokaram,
 *            "The Linear Monge-Kantorovich Linear Colour Mapping for
 *            Example-Based Colour Transfer" (CVMP 2007)
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* enum_value 的第三个参数必须是字符串字面量：GEGL 在注册后自己走
 * dgettext（gegl-op.h 里的 values 循环），这里不能再套 _()，否则初始化器
 * 不是常量。
 * The third enum_value argument must be a literal: GEGL runs dgettext over
 * the table itself after registration, so wrapping it in _() here would make
 * the initialiser non-constant. */
enum_start (mc_method)
  enum_value (MC_METHOD_STATS,    "stats",   "Statistics (mean/std)")
  enum_value (MC_METHOD_MKL,      "mkl",     "Monge-Kantorovich (covariance)")
  enum_value (MC_METHOD_MKL_HIST, "mklhist", "Monge-Kantorovich + histogram")
enum_end (McMethod)

property_enum (method, _("Method"), McMethod, mc_method, MC_METHOD_STATS)
    description (_("Statistics matches each channel's mean and standard deviation, "
                   "exactly like the classic editor. Monge-Kantorovich adds the 3x3 "
                   "covariance so L, a and b stay correlated (no colour blotches). "
                   "The +histogram variant then pulls the residuals onto the "
                   "source's histogram, which catches tonal tails a linear map "
                   "cannot reach"))

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

/* ---- 常量 / constants -------------------------------------------------- */

/* σ 小于这个数时视为常数通道：除零保护。常数通道的 (v−μ) 本来就是 0，
 * 比值多少都不影响结果，取 1 最稳。
 * Channels flatter than this are treated as constant: the ratio would blow
 * up, but (v − μ) is 0 anyway, so 1 is the safe replacement. */
#define MC_STD_EPS 1e-3

/* 特征值下限：协方差奇异（整层纯色、或颜色只落在一条线上）时求逆平方根
 * 会炸。归一化后方差典型在 1e-2 量级，1e-6 足够小又足够安全。
 * Eigenvalue floor: a singular covariance (flat layer, or colours that only
 * live on a line) would blow up the inverse square root. */
#define MC_EIG_EPS 1e-6

/* 直方图桶数。经典图像编辑器 在 8bit L*a*b* 里工作，256 桶正好对着它的精度。
 * Histogram bins. The classic editor works in 8-bit L*a*b*, so 256 bins match
 * its precision exactly. */
#define MC_HIST_BINS 256

/* 各通道归一化尺度 + 定义域：L 是 0..100，a/b 是 −128..127。直接拿原始单位
 * 算协方差会让 L 的方差压过 a/b，最优传输的度量就歪了，所以先除尺度再解。
 * Per-channel scale and domain: L runs 0..100, a/b run −128..127. Solving in
 * raw units would let L's variance swamp chroma and skew the transport metric,
 * so the scale is divided out first. */
static const gdouble MC_SCALE[3] = { 100.0, 128.0, 128.0 };
static const gdouble MC_LO[3]    = { 0.0, -128.0, -128.0 };
static const gdouble MC_HI[3]    = { 100.0, 127.0, 127.0 };

/* ---- 全局统计量 / global statistics ------------------------------------ */

typedef struct
{
  gdouble mean[3];
  gdouble std[3];
  gdouble cov[3][3];    /* Lab 原始单位 / raw Lab units */
  gsize   n;            /* 参与统计的不透明像素数 / opaque pixels counted */
} McStats;

/* 一次算好的「模型」：统计量 + MKL 矩阵 + 直方图 LUT。
 * 全部跟着缓存走，process 里只读。
 * The precomputed model: statistics + MKL matrix + histogram LUT. It lives in
 * the cache; process() only reads it. */
typedef struct
{
  McStats tgt;                     /* 本层 / the target (input) */
  McStats src;                     /* 来源层 / the donor (aux) */
  gboolean mkl_ok;
  gdouble  T[3][3];
  gboolean lut_ok;
  gboolean lut_neutralize;         /* LUT 是按哪种中和状态建的 / build state */
  gfloat   lut[3][MC_HIST_BINS];   /* 桶 → 通道值 / bin → channel value */
} McModel;

/* 缓存挂在 operation 实例上（g_object_set_data），多线程 process 共享，
 * 互斥锁保护首次计算。键用「源节点 + extent + 层级」，**不用缓冲指针**：
 * GEGL 每次重新求值都会给 pad 换一块缓存缓冲，指针必然变，拿它做键等于
 * 永远不命中——拖一下滑杆就整层重扫两遍（4 MP 的图约 1 秒）。
 * 源节点在拖滑杆时不变，所以键稳定。上游内容真的变了（换图层、改上游）
 * 仍需勾一次「重算统计」，这也正是 refresh 那个复选框存在的理由。
 * The cache hangs off the operation instance and is shared by concurrent
 * process calls behind a mutex. Keyed by source node + extent + level, NOT
 * by buffer pointers: GEGL hands a fresh cache buffer to the pad on every
 * evaluation, so pointer keys never hit and each slider step rescans both
 * layers. The source node is stable across slider drags, so this key hits. */
typedef struct
{
  GMutex        lock;
  gboolean      valid;
  gpointer      in_node;
  gpointer      aux_node;
  GeglRectangle in_ext;
  GeglRectangle aux_ext;
  gint          level;
  McModel       model;
} McCache;

/* 缓存创建期间必须串行。多线程首次进入 process 时 g_object_get_data 都会
 * 看到 NULL，各自 g_new0 再 g_object_set_data_full；而 set_data_full 的
 * destroy 通知会把先创建的那一份 g_free 掉，先创建者随后就在已释放的内存
 * 上加锁、读模型——轻则该块拿到 n=0 的垃圾模型走「原样输出」（画面上若干
 * 块没被转换），重则直接崩溃。
 * Creation must be serialised: on the first pass every render thread sees
 * NULL, and whichever one calls g_object_set_data_full last frees the cache
 * another thread is already using. */
static GMutex cache_create_lock;

static void
cache_free (gpointer p)
{
  McCache *c = p;

  g_mutex_clear (&c->lock);
  g_free (c);
}

static McCache *
cache_get (GeglOperation *op)
{
  McCache *c = g_object_get_data (G_OBJECT (op), "lb-mc-cache");

  if (c != NULL)
    return c;

  g_mutex_lock (&cache_create_lock);

  c = g_object_get_data (G_OBJECT (op), "lb-mc-cache");
  if (c == NULL)
    {
      c = g_new0 (McCache, 1);
      g_mutex_init (&c->lock);
      g_object_set_data_full (G_OBJECT (op), "lb-mc-cache", c, cache_free);
    }

  g_mutex_unlock (&cache_create_lock);

  return c;
}

/* 单层统计：整层按行块读一遍，攒 sum / sum² / 交叉积。透明像素（alpha ≤ 0）
 * 不计入——抠图层的洞不该给统计量掺 0。
 * One layer's stats: a single full-extent pass accumulating sum, sum² and the
 * cross products. Transparent pixels (alpha ≤ 0) are excluded so holes in a
 * matte don't drag the statistics toward 0. */
static void
stats_compute (GeglBuffer *buf, const Babl *fmt, McStats *st)
{
  const GeglRectangle ext  = *gegl_buffer_get_extent (buf);
  const gint          band_h = 64;
  gdouble             s1[3]  = { 0.0, 0.0, 0.0 };
  gdouble             s2[3]  = { 0.0, 0.0, 0.0 };
  gdouble             sxy[3] = { 0.0, 0.0, 0.0 };   /* 01, 02, 12 */
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
          sxy[0] += (gdouble) p[0] * p[1];
          sxy[1] += (gdouble) p[0] * p[2];
          sxy[2] += (gdouble) p[1] * p[2];
          n++;
        }
    }

  g_free (px);

  for (gint c = 0; c < 3; c++)
    {
      st->mean[c] = (n == 0) ? 0.0 : s1[c] / (gdouble) n;
      st->std[c]  = 0.0;
      for (gint d = 0; d < 3; d++)
        st->cov[c][d] = 0.0;
    }
  st->n = n;

  if (n == 0)
    return;

  for (gint c = 0; c < 3; c++)
    {
      const gdouble var = s2[c] / (gdouble) n - st->mean[c] * st->mean[c];
      st->std[c] = sqrt (MAX (var, 0.0));
      st->cov[c][c] = var;
    }
  st->cov[0][1] = st->cov[1][0] = sxy[0] / (gdouble) n - st->mean[0] * st->mean[1];
  st->cov[0][2] = st->cov[2][0] = sxy[1] / (gdouble) n - st->mean[0] * st->mean[2];
  st->cov[1][2] = st->cov[2][1] = sxy[2] / (gdouble) n - st->mean[1] * st->mean[2];
}

/* ---- 3×3 对称矩阵 / symmetric 3x3 helpers ------------------------------ */

/* 对称矩阵特征分解（循环 Jacobi）。3×3 用不着 LAPACK，十几行就够，也不用
 * 给工程拉新依赖。
 * Symmetric eigen-decomposition by cyclic Jacobi: ten lines beat a LAPACK
 * dependency for a 3x3. */
static void
mc_eig3 (const gdouble a[3][3], gdouble w[3], gdouble v[3][3])
{
  gdouble m[3][3];
  gint    i, j, k, sweep;

  for (i = 0; i < 3; i++)
    for (j = 0; j < 3; j++)
      {
        m[i][j] = a[i][j];
        v[i][j] = (i == j) ? 1.0 : 0.0;
      }

  for (sweep = 0; sweep < 24; sweep++)
    {
      gdouble off = fabs (m[0][1]) + fabs (m[0][2]) + fabs (m[1][2]);

      if (off < 1e-15)
        break;

      for (i = 0; i < 2; i++)
        for (j = i + 1; j < 3; j++)
          {
            gdouble theta, t, cs, sn;

            if (fabs (m[i][j]) < 1e-18)
              continue;

            theta = (m[j][j] - m[i][i]) / (2.0 * m[i][j]);
            t = (theta >= 0.0 ? 1.0 : -1.0) /
                (fabs (theta) + sqrt (theta * theta + 1.0));
            cs = 1.0 / sqrt (t * t + 1.0);
            sn = t * cs;

            for (k = 0; k < 3; k++)
              {
                const gdouble mk_i = m[k][i];
                const gdouble mk_j = m[k][j];
                m[k][i] = cs * mk_i - sn * mk_j;
                m[k][j] = sn * mk_i + cs * mk_j;
              }
            for (k = 0; k < 3; k++)
              {
                const gdouble mi_k = m[i][k];
                const gdouble mj_k = m[j][k];
                m[i][k] = cs * mi_k - sn * mj_k;
                m[j][k] = sn * mi_k + cs * mj_k;
              }
            for (k = 0; k < 3; k++)
              {
                const gdouble vk_i = v[k][i];
                const gdouble vk_j = v[k][j];
                v[k][i] = cs * vk_i - sn * vk_j;
                v[k][j] = sn * vk_i + cs * vk_j;
              }
          }
    }

  w[0] = m[0][0];
  w[1] = m[1][1];
  w[2] = m[2][2];
}

/* f(A) = V·diag(f(λ))·Vᵀ；inv = TRUE 时 f(λ) = λ^(−1/2)，否则 λ^(1/2)。
 * 特征值夹到 MC_EIG_EPS 以上：奇异协方差得到的是「退化方向不放大」的合理
 * 映射，而不是 inf。
 * f(A) = V·diag(f(λ))·Vᵀ, f(λ) = λ^(−1/2) when inv, λ^(1/2) otherwise, with
 * the eigenvalues floored so a singular covariance maps sanely instead of to
 * infs. */
static void
mc_sym_pow (const gdouble a[3][3], gboolean inv, gdouble out[3][3])
{
  gdouble w[3], v[3][3], f[3];

  mc_eig3 (a, w, v);

  for (gint i = 0; i < 3; i++)
    {
      const gdouble lam = MAX (w[i], MC_EIG_EPS);
      f[i] = inv ? 1.0 / sqrt (lam) : sqrt (lam);
    }

  for (gint i = 0; i < 3; i++)
    for (gint j = 0; j < 3; j++)
      out[i][j] = v[i][0] * f[0] * v[j][0] +
                  v[i][1] * f[1] * v[j][1] +
                  v[i][2] * f[2] * v[j][2];
}

static void
mc_mul3 (const gdouble a[3][3], const gdouble b[3][3], gdouble out[3][3])
{
  gdouble t[3][3];

  /* 先算到局部再拷：调用处有 out 与 a 同一块的情况（矩阵连乘就地累乘），
   * 直接写 out 会在中途读到自己刚写坏的值。
   * Work in a local first: some call sites pass out == a (in-place chaining),
   * and writing out directly would read back half-updated entries. */
  for (gint i = 0; i < 3; i++)
    for (gint j = 0; j < 3; j++)
      t[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j];

  for (gint i = 0; i < 3; i++)
    for (gint j = 0; j < 3; j++)
      out[i][j] = t[i][j];
}

/* 归一化协方差：Σ̂ = S⁻¹ Σ S⁻¹，S = diag(MC_SCALE)。
 * Normalised covariance: Σ̂ = S⁻¹ Σ S⁻¹ with S = diag(MC_SCALE). */
static void
mc_cov_norm (const McStats *st, gdouble out[3][3])
{
  for (gint i = 0; i < 3; i++)
    for (gint j = 0; j < 3; j++)
      out[i][j] = st->cov[i][j] / (MC_SCALE[i] * MC_SCALE[j]);
}

/* 线性 Monge-Kantorovich 映射矩阵（Pitié & Kokaram 2007）：
 *   T = Σt^(−1/2) · (Σt^(1/2) Σs Σt^(1/2))^(1/2) · Σt^(−1/2)
 * 满足 T Σt Tᵀ = Σs，即映射后协方差与来源一致；在所有满足该条件的线性
 * 映射里它是传输代价（Wasserstein-2）最小的那个——这正是它比逐通道缩放
 * 更自然、色斑更少的原因。
 * The linear Monge-Kantorovich map, which satisfies T Σt Tᵀ = Σs and is the
 * cheapest (Wasserstein-2) linear map with that property. */
static gboolean
mc_mkl_matrix (const McStats *tgt, const McStats *src, gdouble T[3][3])
{
  gdouble st[3][3], ss[3][3], mt[3][3], mti[3][3], mid[3][3], half[3][3];

  if (tgt->n < 2 || src->n < 2)
    return FALSE;

  /* 目标层是纯色：协方差全 0，解出来的 T 没有意义（1e6 量级的放大），
   * 直接用逐通道那条路。
   * A flat target layer has a zero covariance, so the solved T is meaningless
   * (1e6-scale amplification); take the per-channel path instead. */
  if (tgt->std[0] < MC_STD_EPS &&
      tgt->std[1] < MC_STD_EPS &&
      tgt->std[2] < MC_STD_EPS)
    return FALSE;

  mc_cov_norm (tgt, st);
  mc_cov_norm (src, ss);

  mc_sym_pow (st, FALSE, mt);      /* Σt^(1/2)  */
  mc_sym_pow (st, TRUE,  mti);     /* Σt^(−1/2) */

  mc_mul3 (mt, ss, mid);
  mc_mul3 (mid, mt, mid);
  mc_sym_pow (mid, FALSE, half);   /* (Σt^½ Σs Σt^½)^(½) */

  mc_mul3 (mti, half, T);
  mc_mul3 (T, mti, T);
  return TRUE;
}

/* ---- 直方图 / histograms ----------------------------------------------- */

static inline gint
mc_bin_of (gint c, gdouble v)
{
  gdouble f = (v - MC_LO[c]) / (MC_HI[c] - MC_LO[c]) * MC_HIST_BINS;

  if (f <= 0.0)
    return 0;
  if (f >= MC_HIST_BINS)
    return MC_HIST_BINS - 1;
  return (gint) f;
}

static inline gdouble
mc_bin_value (gint c, gint i)
{
  return MC_LO[c] + ((gdouble) i + 0.5) *
                    (MC_HI[c] - MC_LO[c]) / MC_HIST_BINS;
}

/* 整层直方图（原始值）。只给「+直方图」那条路用，所以单独一趟，不拖累
 * 其他两种方法。
 * Whole-layer histogram of raw values. Only the +histogram method needs it,
 * hence its own pass instead of taxing the other two. */
static void
mc_hist_raw (GeglBuffer *buf, const Babl *fmt, guint32 hist[3][MC_HIST_BINS])
{
  const GeglRectangle ext  = *gegl_buffer_get_extent (buf);
  const gint          band_h = 64;
  gfloat             *px = g_new (gfloat, (gsize) ext.width * band_h * 4);

  memset (hist, 0, sizeof (guint32) * 3 * MC_HIST_BINS);

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
            hist[c][mc_bin_of (c, p[c])]++;
        }
    }

  g_free (px);
}

/* LUT：把「MKL 之后」的分布拉到来源分布上（逐通道 CDF 匹配）。
 * 两个累计分布做单调归并，桶 i 的目标值 = 来源在该累计比例处的分位数。
 * The LUT pulls the post-MKL distribution onto the donor's (per-channel CDF
 * matching): bin i maps to the donor quantile at the same cumulative fraction. */
static void
mc_build_lut (const guint32 post[3][MC_HIST_BINS],
              const guint32 ref[3][MC_HIST_BINS],
              gfloat       lut[3][MC_HIST_BINS])
{
  for (gint c = 0; c < 3; c++)
    {
      gdouble cum_p[MC_HIST_BINS], cum_r[MC_HIST_BINS];
      gdouble tot_p = 0.0, tot_r = 0.0, acc_p = 0.0, acc_r = 0.0;
      gint    j = 0;

      for (gint i = 0; i < MC_HIST_BINS; i++)
        {
          tot_p += post[c][i];
          tot_r += ref[c][i];
        }

      if (tot_p <= 0.0 || tot_r <= 0.0)
        {
          /* 一侧空：恒等（桶 → 桶中心值），不看来源
           * one side empty: identity, ignore the donor */
          for (gint i = 0; i < MC_HIST_BINS; i++)
            lut[c][i] = (gfloat) mc_bin_value (c, i);
          continue;
        }

      for (gint i = 0; i < MC_HIST_BINS; i++)
        {
          acc_p += post[c][i];
          acc_r += ref[c][i];
          cum_p[i] = acc_p / tot_p;
          cum_r[i] = acc_r / tot_r;
        }

      for (gint i = 0; i < MC_HIST_BINS; i++)
        {
          const gdouble target = cum_p[i];

          while (j < MC_HIST_BINS - 1 && cum_r[j] < target)
            j++;

          if (j == 0)
            {
              lut[c][i] = (gfloat) mc_bin_value (c, 0);
            }
          else
            {
              const gdouble span = cum_r[j] - cum_r[j - 1];
              const gdouble t    = (span > 0.0)
                                     ? CLAMP ((target - cum_r[j - 1]) / span, 0.0, 1.0)
                                     : 1.0;
              lut[c][i] = (gfloat) (mc_bin_value (c, j - 1) * (1.0 - t) +
                                    mc_bin_value (c, j) * t);
            }
        }
    }
}

static inline gdouble
mc_lut_lookup (const gfloat *lut, gint c, gdouble v)
{
  const gdouble pos = (v - MC_LO[c]) / (MC_HI[c] - MC_LO[c]) *
                      (MC_HIST_BINS - 1);

  if (pos <= 0.0)
    return lut[0];
  if (pos >= (gdouble) (MC_HIST_BINS - 1))
    return lut[MC_HIST_BINS - 1];

  {
    const gint    i = (gint) pos;
    const gdouble f = pos - (gdouble) i;

    return lut[i] * (1.0 - f) + lut[i + 1] * f;
  }
}

/* ---- MKL 映射（供 LUT 那一趟复用） ------------------------------------- */

static inline void
mc_mkl_apply (const gdouble v[3],
              const gdouble T[3][3],
              const gdouble t_mean[3],
              const gdouble s_mean[3],
              gboolean      neutralize,
              gdouble       out[3])
{
  gdouble d[3], w[3];

  for (gint c = 0; c < 3; c++)
    d[c] = (v[c] - t_mean[c]) / MC_SCALE[c];

  for (gint i = 0; i < 3; i++)
    w[i] = T[i][0] * d[0] + T[i][1] * d[1] + T[i][2] * d[2];

  for (gint c = 0; c < 3; c++)
    out[c] = w[c] * MC_SCALE[c] +
             ((neutralize && c > 0) ? 0.0 : s_mean[c]);
}

/* MKL 之后整层的直方图：LUT 需要知道「映射后落在哪」，所以再扫一遍。
 * 只有 method = mklhist 时才会走到这里。
 * Histogram of the MKL-mapped layer, which the LUT needs; one more pass, only
 * ever reached with method = mklhist. */
static void
mc_hist_post_mkl (GeglBuffer    *buf,
                  const Babl    *fmt,
                  const McModel *m,
                  gboolean       neutralize,
                  guint32        hist[3][MC_HIST_BINS])
{
  const GeglRectangle ext  = *gegl_buffer_get_extent (buf);
  const gint          band_h = 64;
  gfloat             *px = g_new (gfloat, (gsize) ext.width * band_h * 4);

  memset (hist, 0, sizeof (guint32) * 3 * MC_HIST_BINS);

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
          gdouble v[3], o[3];

          if (p[3] <= 0.0f)
            continue;

          for (gint c = 0; c < 3; c++)
            v[c] = p[c];

          mc_mkl_apply (v, m->T, m->tgt.mean, m->src.mean, neutralize, o);

          for (gint c = 0; c < 3; c++)
            hist[c][mc_bin_of (c, o[c])]++;
        }
    }

  g_free (px);
}

/* 模型就绪（缓存命中或现算），顺带把 MKL 矩阵解出来、需要时建 LUT。
 * Ready-to-use model, cached or computed; the MKL matrix is solved here and
 * the LUT is built on demand (it depends on the method and on Neutralize). */
static void
model_ensure (McCache        *c,
              GeglOperation  *op,
              GeglBuffer     *input,
              GeglBuffer     *aux,
              gint            level,
              McModel        *out)
{
  const Babl *fmt = lab_format ();
  GeglProperties *o = GEGL_PROPERTIES (op);
  const GeglRectangle iext = *gegl_buffer_get_extent (input);
  const GeglRectangle aext = aux ? *gegl_buffer_get_extent (aux) : iext;
  const gboolean want_refresh = o->refresh;
  /* 源节点指针：拖滑杆不变，换图层才变 */
  GeglNode *in_node  = gegl_operation_get_source_node (op, "input");
  GeglNode *aux_node = aux ? gegl_operation_get_source_node (op, "aux") : NULL;

  g_mutex_lock (&c->lock);

  if (want_refresh)
    {
      /* 用完即复位：不然 TRUE 一直挂着，每个渲染块都会整层重扫
       * Clear the flag after one use, or every tile would rescan the
       * whole layers while the checkbox stays ticked. */
      o->refresh = FALSE;
      c->valid = FALSE;
    }
  else if (!(c->valid &&
             c->in_node  == (gpointer) in_node  &&
             c->aux_node == (gpointer) aux_node &&
             c->level   == level            &&
             memcmp (&c->in_ext, &iext, sizeof (GeglRectangle)) == 0 &&
             memcmp (&c->aux_ext, &aext, sizeof (GeglRectangle)) == 0))
    {
      c->valid = FALSE;
    }

  if (!c->valid)
    {
      stats_compute (input, fmt, &c->model.tgt);
      if (aux != NULL)
        stats_compute (aux, fmt, &c->model.src);
      else
        c->model.src = c->model.tgt;

      c->model.mkl_ok = mc_mkl_matrix (&c->model.tgt, &c->model.src,
                                       c->model.T);
      c->model.lut_ok = FALSE;

      c->in_node  = (gpointer) in_node;
      c->aux_node = (gpointer) aux_node;
      c->in_ext  = iext;
      c->aux_ext = aext;
      c->level   = level;
      c->valid   = TRUE;
    }

  /* 「+直方图」的 LUT：方法或中和状态变了就重建。一趟整层扫描，
   * 只在这一条路上付。
   * The +histogram LUT is rebuilt when the method or the Neutralize state
   * changes; one full scan, paid only on this path. */
  if (o->method == MC_METHOD_MKL_HIST && c->model.mkl_ok &&
      (!c->model.lut_ok || c->model.lut_neutralize != o->neutralize))
    {
      guint32 hist_ref[3][MC_HIST_BINS];
      guint32 hist_post[3][MC_HIST_BINS];

      if (aux != NULL)
        mc_hist_raw (aux, fmt, hist_ref);
      else
        mc_hist_raw (input, fmt, hist_ref);

      mc_hist_post_mkl (input, fmt, &c->model, o->neutralize, hist_post);
      mc_build_lut (hist_post, hist_ref, c->model.lut);

      c->model.lut_ok = TRUE;
      c->model.lut_neutralize = o->neutralize;
    }

  *out = c->model;
  g_mutex_unlock (&c->lock);
}

/* ---- 单像素映射 / one pixel -------------------------------------------- */

static inline gdouble
mc_clamp_ch (gint c, gdouble v)
{
  return (c == 0) ? CLAMP (v, 0.0, 100.0) : CLAMP (v, -128.0, 127.0);
}

/* 「统计」映射：逐通道仿射，和经典图像编辑器一致。
 * 完整映射 M(v) = (v − μt)·r + μs，按 amount 收敛：
 * out = v·(1 + k(r−1)) + k·(μs − μt·r)
 * The classic per-channel affine map, approached by amount k. */
static void
match_pixel_stats (const gfloat *in,
                   gfloat       *out,
                   const gdouble amount_l,
                   const gdouble amount_c,
                   const gdouble ratio[3],
                   const gdouble t_mean[3],
                   const gdouble s_mean[3],
                   const gboolean neutralize)
{
  for (gint c = 0; c < 3; c++)
    {
      const gdouble k     = (c == 0) ? amount_l : amount_c;
      const gdouble r     = ratio[c];
      const gdouble mu_s  = (neutralize && c > 0) ? 0.0 : s_mean[c];
      const gdouble slope = 1.0 + k * (r - 1.0);
      gdouble v = in[c] * slope + k * (mu_s - t_mean[c] * r);

      out[c] = (gfloat) mc_clamp_ch (c, v);
    }
  out[3] = in[3];
}

/* 「MKL」映射：out = T·((v − μt)/S)·S + μs，按 amount 逐通道向原值收敛。
 * with_lut = TRUE 时先过一遍直方图 LUT（mklhist）。
 * The MKL map, approached per channel; with_lut also runs the histogram LUT. */
static void
match_pixel_mkl (const gfloat *in,
                 gfloat       *out,
                 const gdouble amount_l,
                 const gdouble amount_c,
                 const McModel *m,
                 gboolean       with_lut,
                 const gboolean neutralize)
{
  gdouble v[3], mapped[3];

  for (gint c = 0; c < 3; c++)
    v[c] = in[c];

  mc_mkl_apply (v, m->T, m->tgt.mean, m->src.mean, neutralize, mapped);

  for (gint c = 0; c < 3; c++)
    {
      const gdouble k = (c == 0) ? amount_l : amount_c;
      const gdouble target = (with_lut && m->lut_ok)
                               ? mc_lut_lookup (m->lut[c], c, mapped[c])
                               : mapped[c];
      const gdouble o = v[c] + k * (target - v[c]);

      out[c] = (gfloat) mc_clamp_ch (c, o);
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

  McModel  m;
  McCache *c = cache_get (op);
  model_ensure (c, op, input, aux, level, &m);

  /* 两个统计都算不出来（全透明）就原样通过
   * Nothing to match with (fully transparent layers): pass through. */
  if (m.tgt.n == 0 || m.src.n == 0)
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
    ratio[ch] = (m.src.std[ch] < MC_STD_EPS || m.tgt.std[ch] < MC_STD_EPS)
                  ? 1.0
                  : m.src.std[ch] / m.tgt.std[ch];

  /* 协方差奇异（纯色层等）时 MKL 退回逐通道，不报错也不出 NaN
   * A singular covariance (flat layers etc.) falls back to the per-channel
   * map rather than producing NaNs. */
  const gboolean use_mkl = (o->method != MC_METHOD_STATS) && m.mkl_ok;

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
        {
          if (use_mkl)
            match_pixel_mkl (in_band + i * 4, out_band + i * 4,
                             kL, kC, &m,
                             o->method == MC_METHOD_MKL_HIST, o->neutralize);
          else
            match_pixel_stats (in_band + i * 4, out_band + i * 4,
                               kL, kC, ratio, m.tgt.mean, m.src.mean,
                               o->neutralize);
        }

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
    "description",     _("the classic editor Match Color: transfer the L*a*b* statistics "
                         "of another image or layer onto this one. Method "
                         "chooses per-channel mean/std (the classic editor's "
                         "behaviour), the full 3x3 linear Monge-Kantorovich "
                         "map, or MKL plus histogram matching; plus "
                         "luminance, color intensity, fade and neutralize."),
    "gimp:menu-path",  "<Image>/SuperMrWang/Color",
    "gimp:menu-label", _("Match Color"),
    NULL);
}

#endif
