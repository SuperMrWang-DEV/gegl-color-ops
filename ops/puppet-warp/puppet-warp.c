/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:puppet-warp
 * menu       Puppet Warp (live)
 * where      GIMP 里在 SuperMrWang → Distort 下（同一个子菜单里还有 Python 版
 *            那个破坏性的「木偶变形」，两个入口并排）
 * purpose    木偶变形的**非破坏**版本：把钉子串挂在滤镜栈上，改参数只是让
 *            这条滤镜重算，原像素不动。对话框（Python 插件）拖完钉子点应用
 *            时写的也是这里的 pins 串，重跑对话框会从滤镜里把钉子读回来。
 *            The non-destructive puppet warp: the pin string lives on the
 *            filter, re-running the plug-in reloads it. Pixels untouched.
 * type       GeglOperationFilter（逐像素；双线性取样只多要 1 px 邻域）
 * why C     GIMP 3 的非破坏编辑只认 GEGL 算子（见 lb:layer-style 头注释）。
 *            MLS 是逐像素的闭式解，天生 tile 安全；ARAP 在这里用带状
 *            Cholesky 解网格（n≤~2400、带宽 nx+1，一次分解 6e6 flops），
 *            12 轮迭代复用同一个分解。
 * algorithm  与 plugin/_shared/warp_math.py + arap.py 同一套公式：
 *            - similarity / affine：MLS 逐点解（权重 1/(d²+1)），
 *              外面乘「到最近钉子的 smoothstep」收口，圈外严格恒等；
 *            - arap：48 节点网格、2D 旋转闭式解（atan2，无 SVD）、
 *              钉子硬约束（Dirichlet）、弱锚定 0.06、只分解一次复用；
 *              反向场 = 把钉子的原位/现位交换再解一遍（与 Python 版一致）。
 *            重采样是双线性，源坐标按 w-1.001 / h-1.001 夹紧。
 * reference  plugin/_shared/warp_math.py、plugin/_shared/arap.py
 *            （同一套公式的 Python/numpy 版，回归对拍用）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>
#include <stdlib.h>

#ifdef GEGL_PROPERTIES

enum_start (pw_modes)
  enum_value (PW_MODE_SIMILARITY, "similarity", "Rigid (keeps shapes)")
  enum_value (PW_MODE_AFFINE,     "affine",     "Free (allows stretching)")
  enum_value (PW_MODE_ARAP,      "arap",       "ARAP (best at bending)")
enum_end (PwModes)

property_string (pins, _("Pins"), "")
  description (_("sx,sy,dx,dy; sx,sy,dx,dy — where each pin was placed and "
                 "where it was dragged to, in layer pixels. The interactive "
                 "dialog writes this string, and re-running the dialog reads "
                 "it back from the filter, so the warp stays editable."))
property_enum (mode, _("Deformation"), PwModes, pw_modes, PW_MODE_SIMILARITY)
  description (_("How the pixels between pins are solved. Rigid keeps shapes "
                 "(MLS similarity); Free allows shear and stretch (affine); "
                 "ARAP bends best on big rotations."))
property_double (radius, _("Falloff"), 30.0)
  description (_("How far a pin reaches, as a percentage of the long edge. "
                 "Outside that circle the picture is left untouched. Not used "
                 "in ARAP mode (it anchors globally)."))
  value_range (5.0, 100.0)
  ui_meta ("unit", "percent")

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_puppet_warp
#define GEGL_OP_C_SOURCE puppet-warp.c

#include "gegl-op.h"

/* ---- 与 Python 版一致的常数 -------------------------------------------- */

#define PW_ARAP_NODES   48       /* ARAP 网格沿长边的格数（同 arap.py）   */
#define PW_ARAP_ITERS   12
#define PW_ARAP_TOL     0.02     /* px */
#define PW_ARAP_ANCHOR  0.06
#define PW_ARAP_DAMPING 1.0e-6
#define PW_MAX_PINS     512

typedef struct {
  gdouble sx, sy, dx, dy;
} PwPin;

typedef struct {
  gint    n;                     /* 钉子数 */
  PwPin   pins[PW_MAX_PINS];
  gboolean moved;                /* 至少一个钉子被拖过 */
} PwPinSet;

/* ---- pins 串解析 -------------------------------------------------------- */

static gboolean
pw_parse_pins (const gchar *text, PwPinSet *set)
{
  const gchar *p;
  gint n = 0;

  set->n = 0;
  set->moved = FALSE;
  if (!text || !*text)
    return FALSE;

  p = text;
  while (*p && n < PW_MAX_PINS)
    {
      gdouble v[4] = { 0, 0, 0, 0 };
      gint got = 0;

      while (*p == ' ' || *p == '\t' || *p == ',' || *p == ';')
        p++;
      if (!*p)
        break;

      while (got < 4)
        {
          gchar *end = NULL;
          gdouble val = g_ascii_strtod (p, &end);

          if (end == p)
            break;
          v[got++] = val;
          p = end;
          while (*p == ' ' || *p == '\t' || *p == ',')
            p++;
          if (*p == ';' || *p == '\0')
            break;
        }

      if (got < 4)
        break;

      if (isfinite (v[0]) && isfinite (v[1]) &&
          isfinite (v[2]) && isfinite (v[3]))
        {
          PwPin *pin = &set->pins[n];

          pin->sx = v[0];
          pin->sy = v[1];
          pin->dx = v[2];
          pin->dy = v[3];
          if (fabs (v[2] - v[0]) > 1e-9 || fabs (v[3] - v[1]) > 1e-9)
            set->moved = TRUE;
          n++;
        }

      while (*p && *p != ';')
        p++;
      if (*p == ';')
        p++;
    }

  set->n = n;
  return n > 0;
}

/* ---- MLS 逐点解（对照 warp_math._mls_solve / mls_point） ---------------- */

static inline gdouble
pw_smoothstep (gdouble t)
{
  if (t <= 0.0)
    return 0.0;
  if (t >= 1.0)
    return 1.0;
  return t * t * (3.0 - 2.0 * t);
}

/* 反向场：目标像素 p 应从源图的哪里取样。
 * a = 钉子现位（d），t = 原位（s），映射 f(p) = M·(p-m) + q。
 * 单点成本 O(K)，K 个钉子 —— 逐像素直解，不需要栅格场。 */
static void
pw_mls_reverse (gdouble px, gdouble py, const PwPinSet *set,
                gboolean similarity, gdouble radius,
                gdouble *out_x, gdouble *out_y)
{
  const PwPin *pins = set->pins;
  gint n = set->n;
  gdouble sw = 0, mx = 0, my = 0, qx = 0, qy = 0;
  gdouble gate = 0.0;
  gdouble fx, fy;
  gint k;

  if (n <= 0)
    {
      *out_x = px;
      *out_y = py;
      return;
    }

  /* 收口：到最近钉子（现位）的 smoothstep。圈外严格恒等 —— 逐像素直解
   * 的好处就是没有栅格插值，圈外一个字节都不会动。 */
  if (radius > 0.0)
    {
      gdouble best = radius * radius;

      for (k = 0; k < n; k++)
        {
          gdouble vx = pins[k].dx - px;
          gdouble vy = pins[k].dy - py;
          gdouble d2 = vx * vx + vy * vy;

          if (d2 < best)
            best = d2;
        }
      if (best >= radius * radius)
        {
          *out_x = px;
          *out_y = py;
          return;
        }
      gate = pw_smoothstep (1.0 - sqrt (best) / radius);
      if (gate <= 0.0)
        {
          *out_x = px;
          *out_y = py;
          return;
        }
    }

  for (k = 0; k < n; k++)
    {
      gdouble vx = pins[k].dx - px;
      gdouble vy = pins[k].dy - py;
      gdouble w = 1.0 / (vx * vx + vy * vy + 1.0);

      sw += w;
      mx += w * pins[k].dx;
      my += w * pins[k].dy;
      qx += w * pins[k].sx;
      qy += w * pins[k].sy;
    }
  mx /= sw;
  my /= sw;
  qx /= sw;
  qy /= sw;

  if (n == 1)                            /* 一个钉子：纯平移 f = (p-m)+q */
    {
      fx = px - mx + qx;
      fy = py - my + qy;
    }
  else if (similarity)
    {
      gdouble mu = 0, sa = 0, sb = 0;

      for (k = 0; k < n; k++)
        {
          gdouble vx = pins[k].dx - px;
          gdouble vy = pins[k].dy - py;
          gdouble w = 1.0 / (vx * vx + vy * vy + 1.0);
          gdouble ex = pins[k].dx - mx;
          gdouble ey = pins[k].dy - my;
          gdouble ux = pins[k].sx - qx;
          gdouble uy = pins[k].sy - qy;

          mu += w * (ex * ex + ey * ey);
          sa += w * (ux * ex + uy * ey);
          sb += w * (uy * ex - ux * ey);
        }
      if (mu > 1e-12)
        {
          gdouble a = sa / mu;
          gdouble b = sb / mu;
          gdouble vx = px - mx, vy = py - my;

          fx = a * vx - b * vy + qx;
          fy = b * vx + a * vy + qy;
        }
      else
        {
          fx = px - mx + qx;
          fy = py - my + qy;
        }
    }
  else                                   /* 完整仿射 */
    {
      gdouble a11 = 0, a12 = 0, a22 = 0;
      gdouble b11 = 0, b12 = 0, b21 = 0, b22 = 0;
      gdouble det, inv;
      gdouble vx = px - mx, vy = py - my;

      for (k = 0; k < n; k++)
        {
          gdouble vx0 = pins[k].dx - px;
          gdouble vy0 = pins[k].dy - py;
          gdouble w = 1.0 / (vx0 * vx0 + vy0 * vy0 + 1.0);
          gdouble ex = pins[k].dx - mx;
          gdouble ey = pins[k].dy - my;
          gdouble ux = pins[k].sx - qx;
          gdouble uy = pins[k].sy - qy;

          a11 += w * ex * ex;
          a12 += w * ex * ey;
          a22 += w * ey * ey;
          b11 += w * ux * ex;
          b12 += w * ux * ey;
          b21 += w * uy * ex;
          b22 += w * uy * ey;
        }
      det = a11 * a22 - a12 * a12;
      if (fabs (det) < 1e-12)            /* 钉子共线：退化成平移 (p-m)+q */
        {
          fx = px - mx + qx;
          fy = py - my + qy;
        }
      else
        {
          gdouble m00, m01, m10, m11;

          inv = 1.0 / det;
          m00 = (b11 * a22 - b12 * a12) * inv;
          m01 = (b12 * a11 - b11 * a12) * inv;
          m10 = (b21 * a22 - b22 * a12) * inv;
          m11 = (b22 * a11 - b21 * a12) * inv;
          fx = m00 * vx + m01 * vy + qx;
          fy = m10 * vx + m11 * vy + qy;
        }
    }

  if (gate > 0.0 && gate < 1.0)
    {
      fx = px + (fx - px) * gate;
      fy = py + (fy - py) * gate;
    }
  *out_x = fx;
  *out_y = fy;
}

/* ---- ARAP（对照 arap.py，带状 Cholesky 版） ----------------------------- */

#define PW_ARAP_MAX_BAND 64

typedef struct {
  /* 网格 */
  gint nx, ny, n;                       /* n = nx*ny 顶点 */
  gdouble step_x, step_y;              /* 顶点间距（像素） */
  /* 边 */
  gint ne;
  gint *ei, *ej;
  gdouble *ew;
  gdouble *erx, *ery;                  /* 原位边向量（不随迭代变） */
  /* 约束 */
  gint ncons;
  gint *cons;                          /* 约束顶点列表（升序） */
  gint *cons_rank;                     /* 顶点 → 约束序号（-1 = 自由），长 n */
  gdouble *xc;                          /* 约束顶点目标位置（2*ncons） */
  /* 耦合修正：自由顶点 i 与约束顶点 c 之间的边 (w>0) → rhs_i -= w*Xc_c */
  gint ncouple;
  gint *cp_i, *cp_c;
  gdouble *cp_w;
  /* 带状 LDL（只存下带，带宽 band；L 存 1 的下三角，D 单独） */
  gint band;
  gdouble *Lb;                          /* n*(band+1)：Lb[i*(band+1)+d] = L[i][i-d] */
  gdouble *Dv;                          /* n：对角 D */
  gdouble *anchor;                      /* n*2：弱锚定的右端项 = ANCHOR*v0 */
} PwArap;

static GMutex pw_arap_mutex;
static PwArap *pw_arap_cache = NULL;
static gchar  *pw_arap_key = NULL;

static void
pw_grid_extent (gint w, gint h, gint nodes, gint *nx, gint *ny)
{
  gint long_edge = MAX (w, h);
  gdouble step;
  gint gx, gy;

  if (long_edge <= 2)
    {
      *nx = *ny = 2;
      return;
    }
  step = long_edge / (gdouble) (MAX (2, nodes) - 1);
  gx = (gint) ceil ((w - 1) / step) + 1;
  gy = (gint) ceil ((h - 1) / step) + 1;
  *nx = MAX (2, gx);
  *ny = MAX (2, gy);
}

static void
pw_arap_free (PwArap *a)
{
  if (!a)
    return;
  g_free (a->ei);
  g_free (a->ej);
  g_free (a->ew);
  g_free (a->erx);
  g_free (a->ery);
  g_free (a->cons);
  g_free (a->cons_rank);
  g_free (a->xc);
  g_free (a->cp_i);
  g_free (a->cp_c);
  g_free (a->cp_w);
  g_free (a->Lb);
  g_free (a->Dv);
  g_free (a->anchor);
  g_slice_free (PwArap, a);
}

static inline gdouble
pw_lb (const PwArap *a, gint i, gint j)
{
  /* L[i][j]（j≤i），带外为 0 */
  gint d = i - j;

  if (d < 0 || d > a->band)
    return 0.0;
  return a->Lb[i * (a->band + 1) + d];
}

static inline void
pw_lb_set (PwArap *a, gint i, gint j, gdouble v)
{
  gint d = i - j;

  if (d < 0 || d > a->band)
    return;
  a->Lb[i * (a->band + 1) + d] = v;
}

static inline void
pw_lb_add (PwArap *a, gint i, gint j, gdouble v)
{
  gint d = i - j;

  if (d < 0 || d > a->band)
    return;
  a->Lb[i * (a->band + 1) + d] += v;
}

/* 带外一条边也要进耦合修正（i 与 j 的距离 ≤ band，见边构造：≤ nx+1 ≤ band）。 */

static gboolean
pw_arap_prepare (PwArap *a, gint w, gint h, const PwPinSet *set)
{
  gint nx, ny, n, i, j, k, ne;
  gdouble sx_scale, sy_scale;
  gboolean *cmask;
  gdouble *diag;

  pw_grid_extent (w, h, PW_ARAP_NODES, &nx, &ny);
  n = nx * ny;
  if (n > 4000 || nx > PW_ARAP_MAX_BAND - 2)
    return FALSE;

  a->nx = nx;
  a->ny = ny;
  a->n = n;
  sx_scale = (w > 1) ? (nx - 1.0) / (w - 1.0) : 0.0;
  sy_scale = (h > 1) ? (ny - 1.0) / (h - 1.0) : 0.0;
  a->step_x = (nx > 1) ? (w - 1.0) / (nx - 1.0) : 0.0;
  a->step_y = (ny > 1) ? (h - 1.0) / (ny - 1.0) : 0.0;

  /* 边：水平 + 垂直 + 两条对角线（对角线按 1/√2 加权，同 arap.py） */
  ne = 2 * nx * ny - nx - ny            /* 轴向 */
       + 2 * (nx - 1) * (ny - 1);       /* 对角 */
  a->ne = ne;
  a->ei = g_new (gint, ne);
  a->ej = g_new (gint, ne);
  a->ew = g_new (gdouble, ne);
  a->erx = g_new (gdouble, ne);
  a->ery = g_new (gdouble, ne);

  k = 0;
  for (j = 0; j < ny; j++)
    for (i = 0; i < nx; i++)
      {
        if (i + 1 < nx)
          {
            a->ei[k] = j * nx + i;
            a->ej[k] = j * nx + i + 1;
            a->ew[k] = 1.0;
            k++;
          }
        if (j + 1 < ny)
          {
            a->ei[k] = j * nx + i;
            a->ej[k] = (j + 1) * nx + i;
            a->ew[k] = 1.0;
            k++;
          }
      }
  for (j = 0; j < ny - 1; j++)
    for (i = 0; i < nx - 1; i++)
      {
        a->ei[k] = j * nx + i;
        a->ej[k] = (j + 1) * nx + i + 1;
        a->ew[k] = 1.0 / G_SQRT2;
        k++;
        a->ei[k] = j * nx + i + 1;
        a->ej[k] = (j + 1) * nx + i;
        a->ew[k] = 1.0 / G_SQRT2;
        k++;
      }
  g_assert (k == ne);

  for (k = 0; k < ne; k++)
    {
      gint vi = a->ei[k], vj = a->ej[k];

      a->erx[k] = (vi % nx) * a->step_x - (vj % nx) * a->step_x;
      a->ery[k] = (vi / nx) * a->step_y - (vj / nx) * a->step_y;
    }

  /* 钉子 → 所在单元的 4 个顶点（Dirichlet）。约束集只跟**原位**有关。 */
  cmask = g_new0 (gboolean, n);
  for (k = 0; k < set->n; k++)
    {
      gdouble fx = set->pins[k].sx * sx_scale;
      gdouble fy = set->pins[k].sy * sy_scale;
      gint ii, jj;

      fx = CLAMP (fx, 0.0, nx - 1.0);
      fy = CLAMP (fy, 0.0, ny - 1.0);
      ii = MIN ((gint) fx, nx - 2);
      jj = MIN ((gint) fy, ny - 2);
      cmask[jj * nx + ii] = TRUE;
      cmask[jj * nx + ii + 1] = TRUE;
      cmask[(jj + 1) * nx + ii] = TRUE;
      cmask[(jj + 1) * nx + ii + 1] = TRUE;
    }

  a->cons_rank = g_new (gint, n);
  a->ncons = 0;
  for (i = 0; i < n; i++)
    {
      if (cmask[i])
        a->ncons++;
      a->cons_rank[i] = -1;
    }
  a->cons = g_new (gint, MAX (1, a->ncons));
  j = 0;
  for (i = 0; i < n; i++)
    if (cmask[i])
      {
        a->cons[j] = i;
        a->cons_rank[i] = j;
        j++;
      }
  g_free (cmask);

  if (n - a->ncons < 2)                 /* 钉子占满整个网格，无解可解 */
    return FALSE;

  a->xc = g_new0 (gdouble, 2 * MAX (1, a->ncons));
  a->band = nx + 1;

  /* 耦合边：一端自由、一端约束。它们的值要从矩阵里挪到右端项。 */
  a->ncouple = 0;
  for (k = 0; k < ne; k++)
    {
      gint ci = a->cons_rank[a->ei[k]];
      gint cj = a->cons_rank[a->ej[k]];

      if ((ci >= 0) != (cj >= 0))
        a->ncouple++;
    }
  a->cp_i = g_new (gint, MAX (1, a->ncouple));
  a->cp_c = g_new (gint, MAX (1, a->ncouple));
  a->cp_w = g_new (gdouble, MAX (1, a->ncouple));
  j = 0;
  for (k = 0; k < ne; k++)
    {
      gint vi = a->ei[k], vj = a->ej[k];
      gint ci = a->cons_rank[vi], cj = a->cons_rank[vj];

      if (ci >= 0 && cj < 0)
        {
          a->cp_i[j] = vj;
          a->cp_c[j] = vi;
          a->cp_w[j] = a->ew[k];
          j++;
        }
      else if (cj >= 0 && ci < 0)
        {
          a->cp_i[j] = vi;
          a->cp_c[j] = vj;
          a->cp_w[j] = a->ew[k];
          j++;
        }
    }

  /* 组装带状矩阵：先把边权加进对角和带内下三角，然后：
   *   约束顶点：行列清零、对角置 1（Dirichlet，保持对称）
   *   自由顶点：对角加 (DAMPING + ANCHOR)（同 Lff + …*I） */
  a->Lb = g_new0 (gdouble, (gsize) n * (a->band + 1));
  diag = g_new0 (gdouble, n);
  for (k = 0; k < ne; k++)
    {
      gint vi = a->ei[k], vj = a->ej[k];

      diag[vi] += a->ew[k];
      diag[vj] += a->ew[k];
      if (vi > vj)
        pw_lb_add (a, vi, vj, -a->ew[k]);
      else
        pw_lb_add (a, vj, vi, -a->ew[k]);
    }
  for (i = 0; i < n; i++)
    if (a->cons_rank[i] < 0)
      diag[i] += PW_ARAP_DAMPING + PW_ARAP_ANCHOR;

  /* 约束顶点行列都清零、对角置 1（Dirichlet，保持对称）。
   * 带内下三角存的是 L[i][j]（j≤i）：「行 c」= L[c][j≤c]，「列 c」= L[i≥c][c]。
   * 只清列不清行的话约束行还带着 −w，矩阵不是「单位行」，LDL 直接爆
   * （实测解出 1e84）。 */
  for (i = 0; i < n; i++)
    {
      gint d;

      if (a->cons_rank[i] >= 0)
        {
          /* 行 */
          for (d = 1; d <= a->band && i - d >= 0; d++)
            pw_lb_set (a, i, i - d, 0.0);
        }
      else
        {
          /* 列（只在自由行里出现） */
          for (d = 1; d <= a->band && i - d >= 0; d++)
            if (a->cons_rank[i - d] >= 0)
              pw_lb_set (a, i, i - d, 0.0);
        }
    }

  for (i = 0; i < n; i++)
    {
      pw_lb_set (a, i, i, (a->cons_rank[i] >= 0) ? 1.0 : diag[i]);
    }
  g_free (diag);

  /* 带状 LDL^T 分解（对称，带宽 band）。L 单位下三角、D 对角。 */
  a->Dv = g_new0 (gdouble, n);
  {
    gdouble *row = g_new (gdouble, a->band + 1);

    for (i = 0; i < n; i++)
      {
        gint lo = MAX (0, i - a->band);
        gint jj;

        for (jj = lo; jj <= i; jj++)
          {
            gdouble s;

            if (jj == i)
              continue;
            s = pw_lb (a, i, jj);
            /* 注意：这里**不能**因为 s==0 就跳过 —— 消去公式的
             * L[i][j] = (A[i][j] − Σ L[i][k]·D[k]·L[j][k]) / D[j]
             * 里 A[i][j]=0 时分子仍可能是非零的**填充项**（带内分解的
             * fill-in）。实测第 48 行丢掉 2..5 列的填充，解整体偏成
             * 刚体旋转、远端顶点动 100+ px，就是这个捷径造成的。 */
            {
              gint klo = MAX (lo, MAX (0, jj - a->band));
              gint kk;
              gdouble acc = s;

              /* 注意：当前行的 L[i][kk] 还没写回带内存储（写回在整行算完之后），
               * 必须从 row[] 里读；直接 pw_lb 会拿到还没分解的 A 值 ——
               * 那是 NaN 的来源（实测 D 变负 → 1e-12 兜底 → L 爆炸）。 */
              for (kk = klo; kk < jj; kk++)
                {
                  gdouble lik = row[i - kk];
                  gdouble ljk = pw_lb (a, jj, kk);

                  if (ljk != 0.0)
                    acc -= lik * a->Dv[kk] * ljk;
                }
              row[i - jj] = acc / a->Dv[jj];   /* L[i][jj] */
            }
          }

        /* 对角 */
        {
          gdouble s = pw_lb (a, i, i);
          gint klo = MAX (0, i - a->band);
          gint kk;

          for (kk = klo; kk < i; kk++)
            {
              gdouble lik = row[i - kk];

              if (lik != 0.0)
                s -= lik * lik * a->Dv[kk];
            }
          a->Dv[i] = s;
          if (s <= 0.0)
            {
              /* 数值上不该发生（有阻尼）；兜底避免除零 */
              a->Dv[i] = 1e-12;
            }
        }

        /* 把 row 写回带内存储 */
        for (jj = MAX (0, i - a->band); jj < i; jj++)
          pw_lb_set (a, i, jj, row[i - jj]);
      }
    g_free (row);
  }

  /* 锚定右端项 = ANCHOR * v0（自由顶点） */
  a->anchor = g_new0 (gdouble, 2 * n);
  for (j = 0; j < ny; j++)
    for (i = 0; i < nx; i++)
      {
        gint v = j * nx + i;

        if (a->cons_rank[v] < 0)
          {
            a->anchor[2 * v] = PW_ARAP_ANCHOR * i * a->step_x;
            a->anchor[2 * v + 1] = PW_ARAP_ANCHOR * j * a->step_y;
          }
      }

  return TRUE;
}

/* 带状解算：L·D·Lᵀ·x = rhs（rhs 长 2n，两列同时解） */
static void
pw_arap_solve (const PwArap *a, const gdouble *rhs, gdouble *x)
{
  gint i, j;
  gint band = a->band;

  /* 前代：L y = rhs（两列一起） */
  for (i = 0; i < a->n; i++)
    {
      gdouble sx = rhs[2 * i], sy = rhs[2 * i + 1];
      gint lo = MAX (0, i - band);

      for (j = lo; j < i; j++)
        {
          gdouble lik = pw_lb (a, i, j);

          if (lik != 0.0)
            {
              sx -= lik * x[2 * j];
              sy -= lik * x[2 * j + 1];
            }
        }
      x[2 * i] = sx;
      x[2 * i + 1] = sy;
    }
  /* 对角 */
  for (i = 0; i < a->n; i++)
    {
      gdouble d = a->Dv[i];

      if (d != 1.0 && d != 0.0)
        {
          x[2 * i] /= d;
          x[2 * i + 1] /= d;
        }
    }
  /* 回代：Lᵀ x = y */
  for (i = a->n - 1; i >= 0; i--)
    {
      gdouble sx = x[2 * i], sy = x[2 * i + 1];
      gint hi = MIN (a->n - 1, i + band);

      for (j = i + 1; j <= hi; j++)
        {
          gdouble lji = pw_lb (a, j, i);

          if (lji != 0.0)
            {
              sx -= lji * x[2 * j];
              sy -= lji * x[2 * j + 1];
            }
        }
      x[2 * i] = sx;
      x[2 * i + 1] = sy;
    }
}

/* 解出每个网格顶点的位移（正向场），写入 dx/dy（长 n）。
 * 反向场 = 用「原位/现位交换过的钉子」再解一遍（同 warp_math._build_field_arap）。
 * 返回 FALSE = 没法解（钉子占满网格等）。 */
static gboolean
pw_arap_solve_field (gint w, gint h, const PwPinSet *set,
                     gdouble *dx, gdouble *dy)
{
  PwArap *a;
  gchar *key;
  GString *gs = g_string_new ("");
  gdouble *rhs, *X;
  gdouble *S, *b;
  gdouble *v0x, *v0y;
  gdouble delta;
  gint iter, k, i, j, n;

  /* 把钉子原位拼进 key：约束集只认原位（同 arap._cache_key），
   * 拖动时原位不变、只有目标变，分解结果直接复用。 */
  g_string_append_printf (gs, "%d|%d|", w, h);
  for (k = 0; k < set->n; k++)
    g_string_append_printf (gs, "%.4f,%.4f;", set->pins[k].sx,
                            set->pins[k].sy);
  key = g_string_free (gs, FALSE);

  g_mutex_lock (&pw_arap_mutex);
  if (!pw_arap_cache || !pw_arap_key || strcmp (pw_arap_key, key) != 0)
    {
      pw_arap_free (pw_arap_cache);
      pw_arap_cache = g_slice_new0 (PwArap);
      if (!pw_arap_prepare (pw_arap_cache, w, h, set))
        {
          pw_arap_free (pw_arap_cache);
          pw_arap_cache = NULL;
          g_free (pw_arap_key);
          pw_arap_key = NULL;
          g_free (key);
          g_mutex_unlock (&pw_arap_mutex);
          return FALSE;
        }
      g_free (pw_arap_key);
      pw_arap_key = key;
    }
  else
    {
      g_free (key);
    }
  a = pw_arap_cache;
  n = a->n;
  g_mutex_unlock (&pw_arap_mutex);

  rhs = g_new (gdouble, 2 * n);
  X = g_new (gdouble, 2 * n);
  S = g_new0 (gdouble, 4 * n);           /* n 个 2×2 */
  b = g_new0 (gdouble, 2 * n);
  v0x = g_new (gdouble, n);
  v0y = g_new (gdouble, n);

  for (j = 0; j < a->ny; j++)
    for (i = 0; i < a->nx; i++)
      {
        v0x[j * a->nx + i] = i * a->step_x;
        v0y[j * a->nx + i] = j * a->step_y;
      }

  /* 约束顶点目标：钉子所在单元的 4 个顶点各自平移 (d - s)，按覆盖次数平均 */
  {
    gdouble *acc = g_new0 (gdouble, 2 * n);
    gdouble *cnt = g_new0 (gdouble, n);

    for (k = 0; k < set->n; k++)
      {
        gdouble ddx = set->pins[k].dx - set->pins[k].sx;
        gdouble ddy = set->pins[k].dy - set->pins[k].sy;
        gdouble fx = set->pins[k].sx * ((w > 1) ? (a->nx - 1.0) / (w - 1.0)
                                                : 0.0);
        gdouble fy = set->pins[k].sy * ((h > 1) ? (a->ny - 1.0) / (h - 1.0)
                                                : 0.0);
        gint ii = MIN ((gint) CLAMP (fx, 0.0, a->nx - 1.0), a->nx - 2);
        gint jj = MIN ((gint) CLAMP (fy, 0.0, a->ny - 1.0), a->ny - 2);
        gint q;

        gint quad[4];

        quad[0] = jj * a->nx + ii;
        quad[1] = jj * a->nx + ii + 1;
        quad[2] = (jj + 1) * a->nx + ii;
        quad[3] = (jj + 1) * a->nx + ii + 1;
        for (q = 0; q < 4; q++)
          {
            gint v = quad[q];

            acc[2 * v] += v0x[v] + ddx;
            acc[2 * v + 1] += v0y[v] + ddy;
            cnt[v] += 1.0;
          }
      }
    for (i = 0; i < a->ncons; i++)
      {
        gint v = a->cons[i];

        a->xc[2 * i] = acc[2 * v] / cnt[v];
        a->xc[2 * i + 1] = acc[2 * v + 1] / cnt[v];
      }
    g_free (acc);
    g_free (cnt);
  }

  /* 初值：约束顶点到位、自由顶点在原位 */
  for (i = 0; i < n; i++)
    {
      if (a->cons_rank[i] >= 0)
        {
          X[2 * i] = a->xc[2 * a->cons_rank[i]];
          X[2 * i + 1] = a->xc[2 * a->cons_rank[i] + 1];
        }
      else
        {
          X[2 * i] = v0x[i];
          X[2 * i + 1] = v0y[i];
        }
    }

  for (iter = 0; iter < PW_ARAP_ITERS; iter++)
    {
      /* 局部：S_i = Σ_j w (v_i-v_j)(x_i-x_j)^T */
      memset (S, 0, sizeof (gdouble) * 4 * n);
      for (k = 0; k < a->ne; k++)
        {
          gint vi = a->ei[k], vj = a->ej[k];
          gdouble ex = v0x[vi] - v0x[vj];
          gdouble ey = v0y[vi] - v0y[vj];
          gdouble nx_ = X[2 * vi] - X[2 * vj];
          gdouble ny_ = X[2 * vi + 1] - X[2 * vj + 1];
          gdouble w = a->ew[k];

          S[4 * vi + 0] += w * ex * nx_;
          S[4 * vi + 1] += w * ex * ny_;
          S[4 * vi + 2] += w * ey * nx_;
          S[4 * vi + 3] += w * ey * ny_;
          S[4 * vj + 0] += w * ex * nx_;
          S[4 * vj + 1] += w * ex * ny_;
          S[4 * vj + 2] += w * ey * nx_;
          S[4 * vj + 3] += w * ey * ny_;
        }

      /* 全局右端：b_i = Σ_j (w/2)(R_i+R_j)(v_i-v_j) */
      memset (b, 0, sizeof (gdouble) * 2 * n);
      for (k = 0; k < a->ne; k++)
        {
          gint vi = a->ei[k], vj = a->ej[k];
          gdouble *Si = S + 4 * vi, *Sj = S + 4 * vj;
          gdouble a_i = Si[0] + Si[3], b_i = Si[1] - Si[2];
          gdouble a_j = Sj[0] + Sj[3], b_j = Sj[1] - Sj[2];
          gdouble ri = sqrt (a_i * a_i + b_i * b_i);
          gdouble rj = sqrt (a_j * a_j + b_j * b_j);
          gdouble csi, sni, csj, snj;
          gdouble r00, r01, r10, r11;
          gdouble rx, ry;
          gdouble w;

          if (ri < 1e-12)
            ri = 1.0;
          if (rj < 1e-12)
            rj = 1.0;
          csi = a_i / ri;
          sni = b_i / ri;
          csj = a_j / rj;
          snj = b_j / rj;
          /* 平均旋转 (R_i+R_j)/2 */
          r00 = 0.5 * (csi + csj);
          r01 = -0.5 * (sni + snj);
          r10 = 0.5 * (sni + snj);
          r11 = 0.5 * (csi + csj);
          rx = r00 * a->erx[k] + r01 * a->ery[k];
          ry = r10 * a->erx[k] + r11 * a->ery[k];
          w = a->ew[k];
          b[2 * vi] += w * rx;
          b[2 * vi + 1] += w * ry;
          b[2 * vj] -= w * rx;
          b[2 * vj + 1] -= w * ry;
        }

      /* rhs：自由顶点 = b - 耦合边·Xc + anchor；约束顶点 = Xc */
      for (i = 0; i < n; i++)
        {
          if (a->cons_rank[i] >= 0)
            {
              rhs[2 * i] = a->xc[2 * a->cons_rank[i]];
              rhs[2 * i + 1] = a->xc[2 * a->cons_rank[i] + 1];
            }
          else
            {
              rhs[2 * i] = b[2 * i] + a->anchor[2 * i];
              rhs[2 * i + 1] = b[2 * i + 1] + a->anchor[2 * i + 1];
            }
        }
      for (k = 0; k < a->ncouple; k++)
        {
          gint fi = a->cp_i[k], ci = a->cp_c[k];

          /* 符号：自由顶点方程 Σ_free w(Xi−Xj) + Σ_cons w(Xi−Xc) + anchor(Xi−v0) = b
           * → Lff·Xi = b + anchor·v0 + Σ_cons w·Xc。耦合项是 **加**，
           * 写成减会把整张网格推去反向补偿钉子（远端顶点多动几十 px）。 */
          rhs[2 * fi] += a->cp_w[k] * a->xc[2 * a->cons_rank[ci]];
          rhs[2 * fi + 1] += a->cp_w[k] * a->xc[2 * a->cons_rank[ci] + 1];
        }

      pw_arap_solve (a, rhs, X);

      /* 收敛检查只在自由顶点上做 */
      delta = 0.0;
      for (i = 0; i < n; i++)
        {
          if (a->cons_rank[i] < 0)
            {
              gdouble d0 = fabs (X[2 * i] - v0x[i]);
              gdouble d1 = fabs (X[2 * i + 1] - v0y[i]);

              /* 这里没有上一轮的直接差值：用「离原位多远」做代理不严谨，
               * 直接每轮都跑满（12 轮 × 6e6 flops 的解算，便宜）。 */
              delta = MAX (delta, MAX (d0, d1));
            }
        }
      if (iter > 0 && delta < PW_ARAP_TOL * 3.0)
        break;
    }

  for (i = 0; i < n; i++)
    {
      dx[i] = X[2 * i] - v0x[i];
      dy[i] = X[2 * i + 1] - v0y[i];
    }

  g_free (rhs);
  g_free (X);
  g_free (S);
  g_free (b);
  g_free (v0x);
  g_free (v0y);
  return TRUE;
}

/* ARAP 偏移场缓存：process 会被 GEGL 的多个 worker 线程并发调用，
 * 而所有线程在同一轮渲染里看到的是**同一组**属性，所以命中是常态。
 * 关键坑：不能「新 key 进来就 free 旧数组」——另一个线程可能正拿着
 * 旧指针在用（实测在 gegl 的 worker 线程里 SIGSEGV）。改成 4 槽环形：
 *  - 线程先找 ready 且 key 匹配的槽；找到直接用（指针保持有效，因为
 *    槽只会在 4 个更新的 key 之后才被回收，同轮渲染不可能发生）；
 *  - 没找到就独占一个空槽（reserved 标记防止两个冷启动线程写同一槽），
 *    算完标记 ready。两个线程各算各的，多花一次 <100 ms 的解算，不崩。 */
#define PW_FIELD_SLOTS 4

#define PW_SLOT_FREE     0
#define PW_SLOT_RESERVED 1          /* 某线程已预留、正在算 */
#define PW_SLOT_READY    2

typedef struct {
  gchar    *key;                        /* pins|mode|w|h */
  gint      nx, ny;
  gdouble  *dx, *dy;                    /* nx*ny */
  volatile gint state;
} PwFieldCache;

static GMutex pw_field_mutex;
static PwFieldCache pw_fields[PW_FIELD_SLOTS];
static gint pw_field_lru = 0;         /* 轮转游标：驱逐时用 */

static gboolean
pw_arap_field_for (const gchar *pins_text, gint w, gint h,
                   const PwPinSet *set, PwFieldCache *out)
{
  gchar *key;
  gint slot;
  gint nx, ny;
  gdouble *dx = NULL, *dy = NULL;

  key = g_strdup_printf ("%s|%d|%d", pins_text, w, h);

  /* ① 先找现成的 */
  g_mutex_lock (&pw_field_mutex);
  for (slot = 0; slot < PW_FIELD_SLOTS; slot++)
    {
      if (pw_fields[slot].state == PW_SLOT_READY && pw_fields[slot].key &&
          strcmp (pw_fields[slot].key, key) == 0)
        {
          *out = pw_fields[slot];
          g_mutex_unlock (&pw_field_mutex);
          g_free (key);
          return TRUE;
        }
    }
  /* ② 预留一个槽。只挑 FREE 或 READY（RESERVED 是别的线程正在算的，
   * 绝不能碰——两个线程写同一个槽会把对方的交付竞争掉，进而 free
   * 掉对方还在用的数组）。全满就轮转驱逐一个 READY 槽。 */
  {
    int victim = -1;

    for (slot = 0; slot < PW_FIELD_SLOTS; slot++)
      if (pw_fields[slot].state == PW_SLOT_FREE)
        {
          victim = slot;
          break;
        }
    if (victim < 0)
      {
        int tries;

        for (tries = 0; tries < PW_FIELD_SLOTS; tries++)
          {
            pw_field_lru = (pw_field_lru + 1) % PW_FIELD_SLOTS;
            if (pw_fields[pw_field_lru].state == PW_SLOT_READY)
              {
                victim = pw_field_lru;
                break;
              }
          }
      }
    if (victim < 0)                       /* 全被 RESERVED：罕见，直接算完丢弃 */
      {
        g_mutex_unlock (&pw_field_mutex);
        pw_grid_extent (w, h, PW_ARAP_NODES, &nx, &ny);
        dx = g_new (gdouble, (gsize) nx * ny);
        dy = g_new (gdouble, (gsize) nx * ny);
        if (!pw_arap_solve_field (w, h, set, dx, dy))
          {
            g_free (dx);
            g_free (dy);
            g_free (key);
            return FALSE;
          }
        out->key = NULL;
        out->nx = nx;
        out->ny = ny;
        out->dx = dx;
        out->dy = dy;
        out->state = PW_SLOT_READY;
        g_free (key);
        return TRUE;                     /* 调用方用完自己 free */
      }
    pw_fields[victim].state = PW_SLOT_RESERVED;
    g_free (pw_fields[victim].key);
    pw_fields[victim].key = NULL;
    slot = victim;
  }
  g_mutex_unlock (&pw_field_mutex);

  /* ③ 无锁解算（<100 ms） */
  pw_grid_extent (w, h, PW_ARAP_NODES, &nx, &ny);
  dx = g_new (gdouble, (gsize) nx * ny);
  dy = g_new (gdouble, (gsize) nx * ny);
  if (!pw_arap_solve_field (w, h, set, dx, dy))
    {
      g_free (dx);
      g_free (dy);
      g_free (key);
      g_mutex_lock (&pw_field_mutex);
      pw_fields[slot].state = PW_SLOT_FREE;
      g_mutex_unlock (&pw_field_mutex);
      return FALSE;
    }

  /* ④ 交付 */
  g_mutex_lock (&pw_field_mutex);
  {
    gint s;

    for (s = 0; s < PW_FIELD_SLOTS; s++)
      {
        if (s != slot && pw_fields[s].state == PW_SLOT_READY &&
            pw_fields[s].key && strcmp (pw_fields[s].key, key) == 0)
          {
            /* 别的线程已经算好了同一份：用它，丢掉自己的 */
            *out = pw_fields[s];
            g_mutex_unlock (&pw_field_mutex);
            g_free (dx);
            g_free (dy);
            g_free (key);
            pw_fields[slot].state = PW_SLOT_FREE;
            g_free (pw_fields[slot].key);
            pw_fields[slot].key = NULL;
            return TRUE;
          }
      }
    g_free (pw_fields[slot].dx);
    g_free (pw_fields[slot].dy);
    pw_fields[slot].key = key;
    pw_fields[slot].nx = nx;
    pw_fields[slot].ny = ny;
    pw_fields[slot].dx = dx;
    pw_fields[slot].dy = dy;
    pw_fields[slot].state = PW_SLOT_READY;
    *out = pw_fields[slot];
  }
  g_mutex_unlock (&pw_field_mutex);
  return TRUE;
}

/* ARAP 反向场：钉子原位/现位交换再解（同 warp_math._build_field_arap） */
static gboolean
pw_arap_reverse_field (const gchar *pins_text, gint w, gint h,
                       const PwPinSet *set, PwFieldCache *out)
{
  PwPinSet swapped = *set;
  gint k;

  for (k = 0; k < set->n; k++)
    {
      swapped.pins[k].sx = set->pins[k].dx;
      swapped.pins[k].sy = set->pins[k].dy;
      swapped.pins[k].dx = set->pins[k].sx;
      swapped.pins[k].dy = set->pins[k].sy;
    }
  {
    gchar *sw = g_strconcat (pins_text, "#r", NULL);
    gboolean ok = pw_arap_field_for (sw, w, h, &swapped, out);

    g_free (sw);
    return ok;
  }
}

/* ---- 采样 / sampling ---------------------------------------------------- */

static inline void
pw_sample (const gfloat *src, gint w, gint h,
           gdouble sx, gdouble sy, gfloat *dst)
{
  gdouble w1 = w - 1.001, h1 = h - 1.001;
  gint x0, y0;
  gdouble fx, fy, ifx, ify;
  gsize o0, o1, o2, o3;
  gint c;

  sx = CLAMP (sx, 0.0, w1);
  sy = CLAMP (sy, 0.0, h1);
  x0 = (gint) sx;
  y0 = (gint) sy;
  if (x0 > w - 2)
    x0 = w - 2;
  if (y0 > h - 2)
    y0 = h - 2;
  fx = sx - x0;
  fy = sy - y0;
  ifx = 1.0 - fx;
  ify = 1.0 - fy;

  o0 = ((gsize) y0 * w + x0) * 4;
  o2 = o0 + 4;
  o1 = o0 + (gsize) w * 4;
  o3 = o1 + 4;
  for (c = 0; c < 4; c++)
    {
      dst[c] = (gfloat) (src[o0 + c] * (ifx * ify) +
                         src[o2 + c] * (fx * ify) +
                         src[o1 + c] * (ifx * fy) +
                         src[o3 + c] * (fx * fy));
    }
}

/* ARAP 场的双线性取值（网格坐标 → 偏移） */
static inline void
pw_field_offset (const PwFieldCache *f, gint w, gint h,
                 gdouble x, gdouble y, gdouble *ox, gdouble *oy)
{
  gdouble gx = (w > 1) ? x * (f->nx - 1.0) / (w - 1.0) : 0.0;
  gdouble gy = (h > 1) ? y * (f->ny - 1.0) / (h - 1.0) : 0.0;
  gint ix, iy;
  gdouble tx, ty, a, b_, c, d, t0, t1;

  ix = (gint) gx;
  iy = (gint) gy;
  if (ix > f->nx - 2)
    ix = f->nx - 2;
  if (iy > f->ny - 2)
    iy = f->ny - 2;
  if (ix < 0)
    ix = 0;
  if (iy < 0)
    iy = 0;
  tx = gx - ix;
  ty = gy - iy;

  a = f->dx[(gsize) iy * f->nx + ix];
  b_ = f->dx[(gsize) iy * f->nx + ix + 1];
  c = f->dx[(gsize) (iy + 1) * f->nx + ix];
  d = f->dx[(gsize) (iy + 1) * f->nx + ix + 1];
  t0 = a + (b_ - a) * tx;
  t1 = c + (d - c) * tx;
  *ox = t0 + (t1 - t0) * ty;

  a = f->dy[(gsize) iy * f->nx + ix];
  b_ = f->dy[(gsize) iy * f->nx + ix + 1];
  c = f->dy[(gsize) (iy + 1) * f->nx + ix];
  d = f->dy[(gsize) (iy + 1) * f->nx + ix + 1];
  t0 = a + (b_ - a) * tx;
  t1 = c + (d - c) * tx;
  *oy = t0 + (t1 - t0) * ty;
}

/* ---- 滤镜本体 ----------------------------------------------------------- */

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");
  const Babl *fmt = babl_format_with_space ("R'G'B'A float", space);

  gegl_operation_set_format (operation, "input", fmt);
  gegl_operation_set_format (operation, "output", fmt);
}

/* 双线性取样会读邻居，多要 1 px 就够 */
static GeglRectangle
get_required_for_output (GeglOperation       *operation,
                         const gchar         *input_pad,
                         const GeglRectangle *roi)
{
  GeglRectangle r = *roi;

  r.x -= 1;
  r.y -= 1;
  r.width += 2;
  r.height += 2;
  return r;
}

static gboolean
process (GeglOperation       *operation,
         GeglBuffer          *input,
         GeglBuffer          *output,
         const GeglRectangle *result,
         gint                 level)
{
  GeglProperties *o = GEGL_PROPERTIES (operation);
  const Babl     *fmt = gegl_operation_get_format (operation, "output");
  PwPinSet        set;
  GeglRectangle   full, work;
  gfloat         *src, *dst;
  gdouble         radius_px;
  gint            stride;
  gint            x, y;
  gboolean        similarity = (o->mode != PW_MODE_AFFINE);
  gboolean        arap = (o->mode == PW_MODE_ARAP);
  PwFieldCache    fc = { NULL, 0, 0, NULL, NULL };
  gboolean        have_field = FALSE;

  if (!pw_parse_pins (o->pins ? o->pins : "", &set) || !set.moved)
    {
      /* 没钉子 / 没拖过：直通（get+set 拷贝，不用 gegl_buffer_copy 以免签名差异） */
      gfloat *buf = g_new (gfloat, (gsize) 4 * result->width * result->height);

      gegl_buffer_get (input, result, 1.0, fmt, buf,
                       (gint) (sizeof (gfloat) * 4 * result->width),
                       GEGL_ABYSS_BLACK);
      gegl_buffer_set (output, result, level, fmt, buf,
                       (gint) (sizeof (gfloat) * 4 * result->width));
      g_free (buf);
      return TRUE;
    }

  full = *gegl_buffer_get_extent (input);
  if (full.width < 2 || full.height < 2)
    return TRUE;

  radius_px = o->radius / 100.0 * MAX (full.width, full.height);

  if (arap)
    {
      have_field = pw_arap_reverse_field (o->pins ? o->pins : "",
                                         full.width, full.height,
                                         &set, &fc);
      if (!have_field)
        {
          /* ARAP 解不出来：直通，别把画面弄丢 */
          gfloat *buf =
            g_new (gfloat, (gsize) 4 * result->width * result->height);

          gegl_buffer_get (input, result, 1.0, fmt, buf,
                           (gint) (sizeof (gfloat) * 4 * result->width),
                           GEGL_ABYSS_BLACK);
          gegl_buffer_set (output, result, level, fmt, buf,
                           (gint) (sizeof (gfloat) * 4 * result->width));
          g_free (buf);
          return TRUE;
        }
    }

  /* work = result + 1px；采样时坐标按 full 平移，圈外夹到 full */
  work.x = full.x - 1;
  work.y = full.y - 1;
  work.width = full.width + 2;
  work.height = full.height + 2;

  stride = 4 * work.width;
  src = g_new (gfloat, (gsize) stride * work.height);
  dst = g_new (gfloat, (gsize) 4 * result->width * result->height);

  gegl_buffer_get (input, &work, 1.0, fmt, src,
                   (gint) (sizeof (gfloat) * stride), GEGL_ABYSS_BLACK);

  for (y = 0; y < result->height; y++)
    {
      gdouble py = result->y + y;
      gfloat *out_row = dst + (gsize) y * result->width * 4;

      for (x = 0; x < result->width; x++)
        {
          gdouble px = result->x + x;
          gdouble sx, sy;

          if (arap)
            {
              gdouble ox, oy;

              pw_field_offset (&fc, full.width, full.height, px, py, &ox, &oy);
              sx = px + ox;
              sy = py + oy;
            }
          else
            {
              pw_mls_reverse (px, py, &set, similarity, radius_px, &sx, &sy);
            }

          /* full → work 坐标（work 从 full.x-1 起）。
           * 夹紧必须在 **full** 坐标上做：work 比图大 1 px（abyss 黑边），
           * 夹到 work 边上会把出界像素采成黑，而 Python 版是夹到图边。 */
          {
            gdouble wx = CLAMP (sx, (gdouble) full.x,
                                (gdouble) (full.x + full.width) - 1.001)
                         - work.x;
            gdouble wy = CLAMP (sy, (gdouble) full.y,
                                (gdouble) (full.y + full.height) - 1.001)
                         - work.y;

            pw_sample (src, work.width, work.height, wx, wy,
                       out_row + (gsize) x * 4);
          }
        }
    }

  gegl_buffer_set (output, result, level, fmt, dst,
                   (gint) (sizeof (gfloat) * 4 * result->width));

  /* 罕见路径（4 槽全被别的线程 RESERVED）返回的是调用方自有的数组：
   * key==NULL 标记，用完要自己 free。 */
  if (arap && fc.key == NULL && fc.dx)
    {
      g_free (fc.dx);
      g_free (fc.dy);
    }
  g_free (src);
  g_free (dst);
  return TRUE;
}

/* ---- 给 ctypes 的预览入口（同 mesh-warp 的 mw_render_rgba_u8） ----------
 *
 * 预览每帧都要出图，走 GEGL + numpy 一趟 480×360 要 80～100 ms，拖动掉帧。
 * 这里直接把 process 里那段「解场 → 采样」暴露成纯 C 函数，插件用 ctypes
 * 传像素指针调用。走的是**同一份** pw_arap_reverse_field / pw_mls_reverse /
 * pw_sample，所以预览和烘焙的像素一致（差别只有 16 位取整）。
 *
 * mode 用字符串传，不依赖 glib 枚举的数值顺序。
 */
G_MODULE_EXPORT gint
pw_render_rgba_u8 (const guint8 *src8, gint w, gint h,
                   const gchar *pins_text, const gchar *mode,
                   gdouble radius, guint8 *dst8)
{
  PwPinSet set;
  PwFieldCache fc = { NULL, 0, 0, NULL, NULL };
  gboolean similarity, arap, have_field = TRUE;
  gdouble radius_px;
  gfloat *src, *dst;
  gsize n, i;
  gint x, y;

  if (!src8 || !dst8 || w < 2 || h < 2)
    return 0;

  n = (gsize) w * h * 4;
  src = g_new (gfloat, n);
  dst = g_new (gfloat, n);
  for (i = 0; i < n; i++)
    src[i] = src8[i] * (1.0f / 255.0f);

  similarity = !(mode && g_strcmp0 (mode, "affine") == 0);
  arap = (mode && g_strcmp0 (mode, "arap") == 0);
  radius_px = radius / 100.0 * MAX (w, h);

  if (!pw_parse_pins (pins_text ? pins_text : "", &set) || !set.moved)
    {
      /* 没钉子：直通 */
      memcpy (dst8, src8, n);
      g_free (src);
      g_free (dst);
      return 1;
    }

  if (arap)
    {
      have_field = pw_arap_reverse_field (pins_text ? pins_text : "",
                                          w, h, &set, &fc);
      if (!have_field)
        {
          /* ARAP 解不出来：直通，别把画面弄丢 */
          memcpy (dst8, src8, n);
          g_free (src);
          g_free (dst);
          return 1;
        }
    }

  for (y = 0; y < h; y++)
    {
      gfloat *row = dst + (gsize) y * w * 4;

      for (x = 0; x < w; x++)
        {
          gdouble sx, sy;

          if (arap)
            {
              gdouble ox, oy;

              pw_field_offset (&fc, w, h, (gdouble) x, (gdouble) y, &ox, &oy);
              sx = x + ox;
              sy = y + oy;
            }
          else
            {
              pw_mls_reverse ((gdouble) x, (gdouble) y, &set, similarity,
                              radius_px, &sx, &sy);
            }
          pw_sample (src, w, h, sx, sy, row + (gsize) x * 4);
        }
    }

  for (i = 0; i < n; i++)
    {
      gdouble v = dst[i] * 255.0 + 0.5;

      dst8[i] = (guint8) CLAMP (v, 0.0, 255.0);
    }

  g_free (src);
  g_free (dst);
  return 1;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  oclass->prepare                 = prepare;
  oclass->get_required_for_output = get_required_for_output;
  fclass->process                 = process;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:puppet-warp",
    "title",           _("Puppet Warp (live)"),
    "description",     _("Warp a layer by dragging pins, as a live filter: "
                         "the pins live on the filter so the warp can be "
                         "re-edited at any time. Rigid keeps shapes, free "
                         "allows stretching, ARAP bends best."),
    "categories",      "distort",
    "gimp:menu-path",  "<Image>/SuperMrWang/Distort",
    "gimp:menu-label", _("Puppet Warp (live)…"),
    "position",        "gimp:middle",
    NULL);
}

#endif
