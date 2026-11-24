#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#ifdef GEGL_PROPERTIES

property_string (mesh, _("Mesh"), "")
  description (_("cols,rows; x,y,ux,uy,vx,vy[,a]; ... — the Bezier control "
                 "mesh, row-major, plus optional u:/v: split lines. The "
                 "interactive dialog writes this string, and re-running it "
                 "reads the mesh back from the filter, so the warp stays "
                 "editable."))

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_mesh_warp
#define GEGL_OP_C_SOURCE mesh-warp.c

#include "gegl-op.h"

/* ---- 常量（同 mesh_warp.py） --------------------------------------------- */

#define MW_MAX_CELLS   12       /* 网格最大格数                            */
#define MW_GRID_NODES  140      /* 反向场栅格（长边）                      */
#define MW_NEWTON_ITERS 24
#define MW_NEWTON_TOL  1e-4
#define MW_NEWTON_STEP 0.75     /* 单步最多走 0.75 格（不限步会跨格震）    */
#define MW_ZERO_EPS    1e-6     /* 小于这个值当成 0（恒等网格判不出来） */

/* ---- 网格数据 ------------------------------------------------------------ */

typedef struct {
  gdouble x, y;                 /* 交点位置（像素） */
  gdouble ux, uy;               /* ∂P/∂u：每参数单位的位移 */
  gdouble vx, vy;               /* ∂P/∂v */
  gint    a;                    /* 1 = 把手自动（auto_refresh 会重算） */
} MwNode;

typedef struct {
  gint    cols, rows;
  gint    w, h;                 /* 源图尺寸（把手限幅用） */
  gdouble us[MW_MAX_CELLS + 2]; /* 格界（参数位置 0..cols，可不等距） */
  gdouble vs[MW_MAX_CELLS + 2];
  MwNode  nodes[(MW_MAX_CELLS + 1) * (MW_MAX_CELLS + 1)];
} MwMesh;

/* ---- 小工具 -------------------------------------------------------------- */

static void
mw_breaks (const gdouble *arr, gint count, gdouble *out)
{
  gint i;
  gboolean ok = FALSE;

  if (arr)
    {
      ok = TRUE;
      for (i = 0; i < count; i++)
        if (!(arr[i] < arr[i + 1]))
          {
            ok = FALSE;
            break;
          }
    }
  if (!ok)
    {
      for (i = 0; i <= count; i++)
        out[i] = i;
      return;
    }
  {
    gdouble span = arr[count] - arr[0];

    if (span <= 0.0)
      {
        for (i = 0; i <= count; i++)
          out[i] = i;
        return;
      }
    for (i = 0; i <= count; i++)
      out[i] = (arr[i] - arr[0]) * count / span;
  }
}

static void
mw_mesh_identity (MwMesh *m, gint w, gint h, gint cols, gint rows,
                  const gdouble *us, const gdouble *vs)
{
  gint i, j;
  gdouble cw, ch;

  cols = CLAMP (cols, 1, MW_MAX_CELLS);
  rows = CLAMP (rows, 1, MW_MAX_CELLS);
  m->cols = cols;
  m->rows = rows;
  m->w = w;
  m->h = h;
  mw_breaks (us, cols, m->us);
  mw_breaks (vs, rows, m->vs);
  cw = (w > 1) ? (w - 1.0) / cols : 1.0;
  ch = (h > 1) ? (h - 1.0) / rows : 1.0;
  for (j = 0; j <= rows; j++)
    for (i = 0; i <= cols; i++)
      {
        MwNode *n = &m->nodes[j * (cols + 1) + i];

        n->x = m->us[i] * cw;
        n->y = m->vs[j] * ch;
        n->ux = cw;
        n->uy = 0.0;
        n->vx = 0.0;
        n->vy = ch;
        n->a = 1;
      }
}

static MwNode *
mw_node (MwMesh *m, gint i, gint j)
{
  return &m->nodes[j * (m->cols + 1) + i];
}

/* 参数 val 落在断点数组第几段 + 段内归一化位置（同 _seg） */
static void
mw_seg (const gdouble *arr, gint count, gdouble val, gint *seg, gdouble *frac)
{
  gint lo = 0, hi = count;
  gdouble span;

  if (val <= arr[0])
    {
      *seg = 0;
      *frac = 0.0;
      return;
    }
  if (val >= arr[count])
    {
      *seg = count - 1;
      *frac = 1.0;
      return;
    }
  while (hi - lo > 1)
    {
      gint mid = (lo + hi) / 2;

      if (arr[mid] <= val)
        lo = mid;
      else
        hi = mid;
    }
  span = arr[lo + 1] - arr[lo];
  *seg = lo;
  *frac = (span > 0.0) ? (val - arr[lo]) / span : 0.0;
}

/* ---- 把手自动重算 + 限幅（同 auto_refresh） ------------------------------- */

static void
mw_auto_refresh (MwMesh *m)
{
  gint cols = m->cols, rows = m->rows;
  gint i, j;

  for (j = 0; j <= rows; j++)
    for (i = 0; i <= cols; i++)
      {
        MwNode *n = mw_node (m, i, j);
        gdouble ax, ay, bx, by, lim_u, lim_v, norm, k;

        if (!n->a)
          continue;

        /* u 方向切向 */
        if (cols == 1)
          {
            ax = ay = 0.0;
            lim_u = 0.0;
          }
        else
          {
            MwNode *p, *q;
            gdouble span;
            gdouble chords[2];
            gint nch = 0;

            if (i == 0)
              {
                p = mw_node (m, 0, j);
                q = mw_node (m, 1, j);
                span = m->us[1] - m->us[0];
              }
            else if (i == cols)
              {
                p = mw_node (m, cols - 1, j);
                q = mw_node (m, cols, j);
                span = m->us[cols] - m->us[cols - 1];
              }
            else
              {
                p = mw_node (m, i - 1, j);
                q = mw_node (m, i + 1, j);
                span = m->us[i + 1] - m->us[i - 1];
              }
            ax = (q->x - p->x) / span;
            ay = (q->y - p->y) / span;
            if (i > 0)
              chords[nch++] = hypot (mw_node (m, i - 1, j)->x - n->x,
                                     mw_node (m, i - 1, j)->y - n->y);
            if (i < cols)
              chords[nch++] = hypot (mw_node (m, i + 1, j)->x - n->x,
                                     mw_node (m, i + 1, j)->y - n->y);
            if (nch)
              {
                gdouble c = MIN (chords[0], nch > 1 ? chords[1] : chords[0]);
                /* 节点两侧较窄的那列宽（换算限幅用） */
                gdouble nw;

                if (i <= 0)
                  nw = m->us[1] - m->us[0];
                else if (i >= cols)
                  nw = m->us[cols] - m->us[cols - 1];
                else
                  nw = MIN (m->us[i] - m->us[i - 1],
                            m->us[i + 1] - m->us[i]);
                lim_u = MAX (1e-3, c) / MAX (nw, 1e-9);
              }
            else
              lim_u = 0.0;
          }
        norm = hypot (ax, ay);
        if (lim_u > 0.0 && norm > lim_u)
          {
            k = lim_u / norm;
            ax *= k;
            ay *= k;
          }
        n->ux = ax;
        n->uy = ay;

        /* v 方向切向 */
        if (rows == 1)
          {
            bx = by = 0.0;
            lim_v = 0.0;
          }
        else
          {
            MwNode *p, *q;
            gdouble span;
            gdouble chords[2];
            gint nch = 0;

            if (j == 0)
              {
                p = mw_node (m, i, 0);
                q = mw_node (m, i, 1);
                span = m->vs[1] - m->vs[0];
              }
            else if (j == rows)
              {
                p = mw_node (m, i, rows - 1);
                q = mw_node (m, i, rows);
                span = m->vs[rows] - m->vs[rows - 1];
              }
            else
              {
                p = mw_node (m, i, j - 1);
                q = mw_node (m, i, j + 1);
                span = m->vs[j + 1] - m->vs[j - 1];
              }
            bx = (q->x - p->x) / span;
            by = (q->y - p->y) / span;
            if (j > 0)
              chords[nch++] = hypot (mw_node (m, i, j - 1)->x - n->x,
                                     mw_node (m, i, j - 1)->y - n->y);
            if (j < rows)
              chords[nch++] = hypot (mw_node (m, i, j + 1)->x - n->x,
                                     mw_node (m, i, j + 1)->y - n->y);
            if (nch)
              {
                gdouble c = MIN (chords[0], nch > 1 ? chords[1] : chords[0]);
                gdouble nh;

                if (j <= 0)
                  nh = m->vs[1] - m->vs[0];
                else if (j >= rows)
                  nh = m->vs[rows] - m->vs[rows - 1];
                else
                  nh = MIN (m->vs[j] - m->vs[j - 1],
                            m->vs[j + 1] - m->vs[j]);
                lim_v = MAX (1e-3, c) / MAX (nh, 1e-9);
              }
            else
              lim_v = 0.0;
          }
        norm = hypot (bx, by);
        if (lim_v > 0.0 && norm > lim_v)
          {
            k = lim_v / norm;
            bx *= k;
            by *= k;
          }
        n->vx = bx;
        n->vy = by;
      }
}

/* ---- 序列化解析（同 parse_mesh_string 的容错口径） ---------------------- */

/* 两遍式解析（mw_parse_mesh 的正式实现）：先头部 + 分割线，再节点 */
static void
mw_parse (const gchar *text, gint w, gint h, MwMesh *m)
{
  gchar **chunks;
  gint i;
  gdouble us_buf[MW_MAX_CELLS + 2], vs_buf[MW_MAX_CELLS + 2];
  gboolean have_us = FALSE, have_vs = FALSE;
  gint cols = 3, rows = 3, have_head = FALSE;
  gint want, node_idx = 0;

  mw_mesh_identity (m, w, h, 3, 3, NULL, NULL);
  if (!text || !*text)
    return;

  /* 第一遍：头部 + u:/v:（拿到 cols/rows 才能建恒等骨架） */
  chunks = g_strsplit (text, ";", 0);
  for (i = 0; chunks[i]; i++)
    {
      gchar *s = g_strdup (chunks[i]);
      gchar *t = g_strstrip (s);

      if (!*t)
        {
          g_free (s);
          continue;
        }
      if (g_ascii_tolower (t[0]) == 'u' && t[1] == ':')
        {
          g_strfreev (g_strsplit_set (t + 2, ",", 0));
          {
            gchar **parts = g_strsplit_set (t + 2, ", \t", 0);
            gint nv = 0, p;

            for (p = 0; parts[p]; p++)
              {
                if (*parts[p] && nv < MW_MAX_CELLS + 2)
                  us_buf[nv++] = g_ascii_strtod (parts[p], NULL);
              }
            g_strfreev (parts);
            if (nv == cols + 1)
              have_us = TRUE;
          }
          g_free (s);
          continue;
        }
      if (g_ascii_tolower (t[0]) == 'v' && t[1] == ':')
        {
          gchar **parts = g_strsplit_set (t + 2, ", \t", 0);
          gint nv = 0, p;

          for (p = 0; parts[p]; p++)
            {
              if (*parts[p] && nv < MW_MAX_CELLS + 2)
                vs_buf[nv++] = g_ascii_strtod (parts[p], NULL);
            }
            g_strfreev (parts);
            if (nv == rows + 1)
              have_vs = TRUE;
          g_free (s);
          continue;
        }
      if (!have_head)
        {
          gchar **parts = g_strsplit_set (t, ", \t", 0);
          gint nv = 0, p;
          gdouble vals[4];

          for (p = 0; parts[p]; p++)
            {
              if (*parts[p] && nv < 4)
                vals[nv++] = g_ascii_strtod (parts[p], NULL);
            }
          g_strfreev (parts);
          if (nv >= 2)
            {
              cols = CLAMP ((gint) vals[0], 1, MW_MAX_CELLS);
              rows = CLAMP ((gint) vals[1], 1, MW_MAX_CELLS);
            }
          have_head = TRUE;
          g_free (s);
          continue;
        }
      g_free (s);
    }

  /* u:/v: 的长度按 3x3 判过一遍可能错过（头部是 5x5）——第二遍重判 */
  mw_mesh_identity (m, w, h, cols, rows,
                    have_us ? us_buf : NULL, have_vs ? vs_buf : NULL);

  /* 第二遍：节点 */
  node_idx = 0;
  want = (m->cols + 1) * (m->rows + 1);
  have_head = FALSE;
  for (i = 0; chunks[i]; i++)
    {
      gchar *s = g_strdup (chunks[i]);
      gchar *t = g_strstrip (s);

      if (!*t || (g_ascii_tolower (t[0]) == 'u' && t[1] == ':') ||
          (g_ascii_tolower (t[0]) == 'v' && t[1] == ':'))
        {
          g_free (s);
          continue;
        }
      if (!have_head)
        {
          have_head = TRUE;
          g_free (s);
          continue;
        }
      if (node_idx < want)
        {
          gchar **parts = g_strsplit_set (t, ", \t", 0);
          gdouble vals[8];
          gint nv = 0, p;

          for (p = 0; parts[p]; p++)
            {
              if (*parts[p] && nv < 8)
                vals[nv++] = g_ascii_strtod (parts[p], NULL);
            }
          g_strfreev (parts);
          if (nv >= 2)
            {
              MwNode *n = &m->nodes[node_idx];

              n->x = CLAMP (vals[0], 0.0, (w > 1) ? w - 1.0 : 0.0);
              n->y = CLAMP (vals[1], 0.0, (h > 1) ? h - 1.0 : 0.0);
              if (nv >= 6)
                {
                  n->ux = vals[2];
                  n->uy = vals[3];
                  n->vx = vals[4];
                  n->vy = vals[5];
                  n->a = (nv >= 7 && vals[6] >= 0.5) ? 1 : 0;
                }
              else
                n->a = 1;
              node_idx++;
            }
        }
      g_free (s);
    }
  g_strfreev (chunks);
  mw_auto_refresh (m);
}

/* ---- 恒等判定 ------------------------------------------------------------ */

static gboolean
mw_is_identity (const MwMesh *m)
{
  gint i, j;
  gdouble cw = (m->w > 1) ? (m->w - 1.0) / m->cols : 0.0;
  gdouble ch = (m->h > 1) ? (m->h - 1.0) / m->rows : 0.0;

  for (j = 0; j <= m->rows; j++)
    for (i = 0; i <= m->cols; i++)
      {
        const MwNode *n = &m->nodes[j * (m->cols + 1) + i];

        if (fabs (n->x - m->us[i] * cw) > 1e-6 ||
            fabs (n->y - m->vs[j] * ch) > 1e-6)
          return FALSE;
        if (fabs (n->ux - cw) > 1e-6 || fabs (n->uy) > 1e-6)
          return FALSE;
        if (fabs (n->vx) > 1e-6 || fabs (n->vy - ch) > 1e-6)
          return FALSE;
      }
  return TRUE;
}

/* ---- 曲面片求值（同 _cell_ctrl / _patch） -------------------------------- */

static void
mw_cell_ctrl (const MwMesh *m, gint ci, gint cj, gdouble *bx, gdouble *by)
{
  const MwNode *n00 = &m->nodes[cj * (m->cols + 1) + ci];
  const MwNode *n01 = &m->nodes[(cj + 1) * (m->cols + 1) + ci];
  const MwNode *n10 = &m->nodes[cj * (m->cols + 1) + ci + 1];
  const MwNode *n11 = &m->nodes[(cj + 1) * (m->cols + 1) + ci + 1];
  gdouble dw = m->us[ci + 1] - m->us[ci];
  gdouble dv = m->vs[cj + 1] - m->vs[cj];
  gdouble tx = (n11->x - n10->x - n01->x + n00->x) / 9.0;
  gdouble ty = (n11->y - n10->y - n01->y + n00->y) / 9.0;

#define MW_PUT(a, b, X, Y)  bx[(a) * 4 + (b)] = (X); by[(a) * 4 + (b)] = (Y)

  MW_PUT (0, 0, n00->x, n00->y);
  MW_PUT (0, 3, n01->x, n01->y);
  MW_PUT (3, 0, n10->x, n10->y);
  MW_PUT (3, 3, n11->x, n11->y);

  MW_PUT (0, 1, n00->x + n00->vx * dv / 3.0, n00->y + n00->vy * dv / 3.0);
  MW_PUT (0, 2, n01->x - n01->vx * dv / 3.0, n01->y - n01->vy * dv / 3.0);
  MW_PUT (3, 1, n10->x + n10->vx * dv / 3.0, n10->y + n10->vy * dv / 3.0);
  MW_PUT (3, 2, n11->x - n11->vx * dv / 3.0, n11->y - n11->vy * dv / 3.0);

  MW_PUT (1, 0, n00->x + n00->ux * dw / 3.0, n00->y + n00->uy * dw / 3.0);
  MW_PUT (2, 0, n10->x - n10->ux * dw / 3.0, n10->y - n10->uy * dw / 3.0);
  MW_PUT (1, 3, n01->x + n01->ux * dw / 3.0, n01->y + n01->uy * dw / 3.0);
  MW_PUT (2, 3, n11->x - n11->ux * dw / 3.0, n11->y - n11->uy * dw / 3.0);

  MW_PUT (1, 1, n00->x + (n00->ux * dw + n00->vx * dv) / 3.0 + tx,
               n00->y + (n00->uy * dw + n00->vy * dv) / 3.0 + ty);
  MW_PUT (1, 2, n01->x + (n01->ux * dw - n01->vx * dv) / 3.0 + tx,
               n01->y + (n01->uy * dw - n01->vy * dv) / 3.0 + ty);
  MW_PUT (2, 1, n10->x + (-n10->ux * dw + n10->vx * dv) / 3.0 + tx,
               n10->y + (-n10->uy * dw + n10->vy * dv) / 3.0 + ty);
  MW_PUT (2, 2, n11->x + (-n11->ux * dw - n11->vx * dv) / 3.0 + tx,
               n11->y + (-n11->uy * dw - n11->vy * dv) / 3.0 + ty);
#undef MW_PUT
}

/* P、∂P/∂s、∂P/∂t */
static void
mw_patch (const gdouble *bx, const gdouble *by, gdouble s, gdouble t,
          gdouble *px, gdouble *py, gdouble *psx, gdouble *psy,
          gdouble *ptx, gdouble *pty)
{
  gdouble s1 = 1.0 - s, t1 = 1.0 - t;
  gdouble bs[4], bt[4], qs[3], qt[3];
  gdouble X = 0.0, Y = 0.0, SX = 0.0, SY = 0.0, TX = 0.0, TY = 0.0;
  gint a, b;

  bs[0] = s1 * s1 * s1;
  bs[1] = 3.0 * s * s1 * s1;
  bs[2] = 3.0 * s * s * s1;
  bs[3] = s * s * s;
  bt[0] = t1 * t1 * t1;
  bt[1] = 3.0 * t * t1 * t1;
  bt[2] = 3.0 * t * t * t1;
  bt[3] = t * t * t;
  qs[0] = s1 * s1;
  qs[1] = 2.0 * s * s1;
  qs[2] = s * s;
  qt[0] = t1 * t1;
  qt[1] = 2.0 * t * t1;
  qt[2] = t * t;

  for (a = 0; a < 4; a++)
    {
      gdouble ka = bs[a];
      const gdouble *rx = bx + a * 4, *ry = by + a * 4;

      for (b = 0; b < 4; b++)
        {
          gdouble k = ka * bt[b];

          X += rx[b] * k;
          Y += ry[b] * k;
        }
    }
  for (a = 0; a < 3; a++)
    {
      gdouble ka = 3.0 * qs[a];
      const gdouble *rx = bx + a * 4, *ry = by + a * 4;

      for (b = 0; b < 4; b++)
        {
          gdouble k = ka * bt[b];

          SX += (rx[b + 4] - rx[b]) * k;
          SY += (ry[b + 4] - ry[b]) * k;
        }
    }
  for (a = 0; a < 4; a++)
    {
      gdouble ka = bs[a];
      const gdouble *rx = bx + a * 4, *ry = by + a * 4;

      for (b = 0; b < 3; b++)
        {
          gdouble k = ka * 3.0 * qt[b];

          TX += (rx[b + 1] - rx[b]) * k;
          TY += (ry[b + 1] - ry[b]) * k;
        }
    }
  *px = X;
  *py = Y;
  *psx = SX;
  *psy = SY;
  *ptx = TX;
  *pty = TY;
}

/* ---- Newton 反解（同 invert_point） -------------------------------------- */

/* det_out：收敛点处的雅可比（∂P/∂s × ∂P/∂t）。
 *   > 0 —— 正常，这一支是「正着」的；
 *   <= 0 —— 落在翻转的那一支（网格自交），这个输出像素根本没有对应的源。
 * 交互层现在会拦着不让网格翻过去，但 PDB / 旧脚本、手写的 mesh 串照样能
 * 传进一个自交的网格，所以采样端还需要这道判据。 */
static void
mw_invert (const MwMesh *m, gdouble x, gdouble y, gdouble *u_out,
           gdouble *v_out, gdouble *det_out)
{
  gint cols = m->cols, rows = m->rows;
  gdouble w1 = (m->w > 1) ? m->w - 1.0 : 0.0;
  gdouble h1 = (m->h > 1) ? m->h - 1.0 : 0.0;
  gdouble u = (w1 > 0) ? x / w1 * cols : 0.0;
  gdouble v = (h1 > 0) ? y / h1 * rows : 0.0;
  gint it;

  u = CLAMP (u, 0.0, (gdouble) cols);
  v = CLAMP (v, 0.0, (gdouble) rows);

  for (it = 0; it < MW_NEWTON_ITERS; it++)
    {
      gdouble bx[16], by[16];
      gdouble px, py, psx, psy, ptx, pty, ex, ey, det, du, dv, step, k;
      gint ci, cj;
      gdouble s, t;

      mw_seg (m->us, cols, u, &ci, &s);
      mw_seg (m->vs, rows, v, &cj, &t);
      mw_cell_ctrl (m, ci, cj, bx, by);
      mw_patch (bx, by, s, t, &px, &py, &psx, &psy, &ptx, &pty);
      ex = x - px;
      ey = y - py;
      if (ex * ex + ey * ey <= MW_NEWTON_TOL * MW_NEWTON_TOL)
        break;
      det = psx * pty - psy * ptx;
      if (fabs (det) < 1e-9)
        break;
      du = (pty * ex - ptx * ey) / det;
      dv = (-psy * ex + psx * ey) / det;
      step = MAX (fabs (du), fabs (dv));
      if (step > MW_NEWTON_STEP)
        {
          k = MW_NEWTON_STEP / step;
          du *= k;
          dv *= k;
        }
      u += du * (m->us[ci + 1] - m->us[ci]);
      v += dv * (m->vs[cj + 1] - m->vs[cj]);
      if (u != u || v != v)
        break;
      u = CLAMP (u, 0.0, (gdouble) cols);
      v = CLAMP (v, 0.0, (gdouble) rows);
    }

  /* 迭代中途的 det 可能是「上一格」的，收敛后按最终的 (u,v) 再量一次 */
  {
    gdouble bx[16], by[16];
    gdouble px, py, psx, psy, ptx, pty;
    gint ci, cj;
    gdouble s, t;

    mw_seg (m->us, cols, u, &ci, &s);
    mw_seg (m->vs, rows, v, &cj, &t);
    mw_cell_ctrl (m, ci, cj, bx, by);
    mw_patch (bx, by, s, t, &px, &py, &psx, &psy, &ptx, &pty);
    if (det_out)
      *det_out = psx * pty - psy * ptx;
  }

  *u_out = u;
  *v_out = v;
}

/* ---- 反向场（栅格 + 缓存，同 mesh_warp.build_field） --------------------- */

static void
mw_grid_extent (gint w, gint h, gint nodes, gint *nx, gint *ny)
{
  gdouble step = MAX (w, h) / (gdouble) (nodes - 1);

  *nx = (gint) CLAMP (ceil ((w - 1) / step) + 1, 2, nodes);
  *ny = (gint) CLAMP (ceil ((h - 1) / step) + 1, 2, nodes);
}

/* 解算本体：parse → 栅格场（恒等 → 全 0） */
static gboolean
mw_field_compute (const gchar *mesh_text, gint w, gint h,
                  gint *nx_out, gint *ny_out,
                  gdouble **dx_out, gdouble **dy_out)
{
  gint nx, ny, i, j;
  gdouble *dx, *dy, kx, ky;
  MwMesh m;

  mw_parse (mesh_text, w, h, &m);
  mw_grid_extent (w, h, MW_GRID_NODES, &nx, &ny);
  dx = g_new (gdouble, (gsize) nx * ny);
  dy = g_new (gdouble, (gsize) nx * ny);
  kx = (w > 1) ? (w - 1.0) / m.cols : 0.0;
  ky = (h > 1) ? (h - 1.0) / m.rows : 0.0;

  if (!mw_is_identity (&m))
    {
      guchar *state = g_new0 (guchar, (gsize) nx * ny);   /* 0=坏 1=填的 2=原 */
      gint bad = 0, pass;

      for (j = 0; j < ny; j++)
        {
          gdouble y = (ny > 1) ? (h - 1.0) * j / (ny - 1) : 0.0;

          for (i = 0; i < nx; i++)
            {
              gdouble x = (nx > 1) ? (w - 1.0) * i / (nx - 1) : 0.0;
              gdouble u, v, ox, oy, det = 1.0;

              mw_invert (&m, x, y, &u, &v, &det);
              ox = u * kx - x;
              oy = v * ky - y;
              if (fabs (ox) < MW_ZERO_EPS)
                ox = 0.0;
              if (fabs (oy) < MW_ZERO_EPS)
                oy = 0.0;
              dx[(gsize) j * nx + i] = ox;
              dy[(gsize) j * nx + i] = oy;
              /* det <= 0：这个栅格点落在了翻转支上（网格自交）。照它算，
               * 像素会被采到「另一个分支」去——画面就是一块捏起来的褶子
               * 外加大片断线。先标坏，下面用邻居的偏移填掉。 */
              if (det <= 0.0 || det != det)
                {
                  state[(gsize) j * nx + i] = 0;
                  bad++;
                }
              else
                {
                  state[(gsize) j * nx + i] = 2;
                }
            }
        }

      /* 坏点用 8 邻域里「已知值」的平均填。折叠区通常只有几格宽，4 遍
       * 就够覆盖；全坏（网格彻底废了）就整场归零——宁可不变形，也不花屏。 */
      for (pass = 0; pass < 4 && bad > 0; pass++)
        {
          gint filled = 0;

          for (j = 0; j < ny; j++)
            for (i = 0; i < nx; i++)
              {
                gsize idx = (gsize) j * nx + i;
                gdouble sx = 0.0, sy = 0.0;
                gint n = 0, a, b;

                if (state[idx] != 0)
                  continue;
                for (a = -1; a <= 1; a++)
                  for (b = -1; b <= 1; b++)
                    {
                      gint ii = i + a, jj = j + b;
                      gsize nidx;

                      if ((!a && !b) || ii < 0 || jj < 0 || ii >= nx || jj >= ny)
                        continue;
                      nidx = (gsize) jj * nx + ii;
                      if (state[nidx] == 0)
                        continue;
                      sx += dx[nidx];
                      sy += dy[nidx];
                      n++;
                    }
                if (n)
                  {
                    dx[idx] = sx / n;
                    dy[idx] = sy / n;
                    state[idx] = 1;          /* 1 = 本遍刚填（也当邻居用，
                                              * 扫掠方向会带一点点偏，折叠区里
                                              * 无所谓，反正马上被下一次拖动覆盖） */
                    bad--;
                    filled++;
                  }
              }
          if (!filled)
            break;
          /* 1 → 2：下一遍它们就是「确定值」了 */
          for (i = 0; i < nx * ny; i++)
            if (state[i] == 1)
              state[i] = 2;
        }

      if (bad > 0)                        /* 还有填不到的：整场归零（不变形） */
        {
          memset (dx, 0, sizeof (gdouble) * (gsize) nx * ny);
          memset (dy, 0, sizeof (gdouble) * (gsize) nx * ny);
        }
      g_free (state);
    }
  else
    {
      memset (dx, 0, sizeof (gdouble) * (gsize) nx * ny);
      memset (dy, 0, sizeof (gdouble) * (gsize) nx * ny);
    }
  *nx_out = nx;
  *ny_out = ny;
  *dx_out = dx;
  *dy_out = dy;
  return TRUE;
}

typedef struct {
  gchar    *key;
  gint      nx, ny;
  gdouble  *dx, *dy;
  volatile gint state;   /* 0=FREE 1=RESERVED 2=READY */
} MwField;

#define MW_SLOTS 4

static GMutex mw_field_mutex;
static MwField mw_fields[MW_SLOTS];
static gint   mw_field_lru = 0;

static void
mw_field_slot_clear (MwField *f)
{
  g_free (f->key);
  g_free (f->dx);
  g_free (f->dy);
  f->key = NULL;
  f->dx = NULL;
  f->dy = NULL;
  f->state = 0;
}

/* 解栅格场。key = 尺寸 + mesh 串。多线程 tile：三态槽（puppet-warp 同款），
 * RESERVED 是别的线程正在算的槽，绝不能碰。 */
static gboolean
mw_field_for (const gchar *mesh_text, gint w, gint h, MwField *out)
{
  gchar *key = g_strdup_printf ("%d|%d|%s", w, h, mesh_text);
  gint slot, nx, ny;
  gdouble *dx, *dy;

  /* ① 找现成的 */
  g_mutex_lock (&mw_field_mutex);
  for (slot = 0; slot < MW_SLOTS; slot++)
    {
      if (mw_fields[slot].state == 2 && mw_fields[slot].key &&
          strcmp (mw_fields[slot].key, key) == 0)
        {
          *out = mw_fields[slot];
          g_mutex_unlock (&mw_field_mutex);
          g_free (key);
          return TRUE;
        }
    }
  /* ② 预留一个槽（FREE 或 READY；全 RESERVED 时退化为私有解） */
  {
    gint victim = -1, tries;

    for (slot = 0; slot < MW_SLOTS; slot++)
      if (mw_fields[slot].state == 0)
        {
          victim = slot;
          break;
        }
    if (victim < 0)
      for (tries = 0; tries < MW_SLOTS; tries++)
        {
          mw_field_lru = (mw_field_lru + 1) % MW_SLOTS;
          if (mw_fields[mw_field_lru].state == 2)
            {
              victim = mw_field_lru;
              break;
            }
        }
    if (victim < 0)
      {
        g_mutex_unlock (&mw_field_mutex);
        {
          gboolean ok = mw_field_compute (mesh_text, w, h, &nx, &ny, &dx, &dy);
          if (!ok)
            {
              g_free (key);
              return FALSE;
            }
          out->key = NULL;
          out->nx = nx;
          out->ny = ny;
          out->dx = dx;
          out->dy = dy;
          return TRUE;               /* 私有：process 用完自己 free */
        }
      }
    mw_field_slot_clear (&mw_fields[victim]);
    mw_fields[victim].state = 1;
    slot = victim;
  }
  g_mutex_unlock (&mw_field_mutex);

  /* ③ 无锁解算 */
  if (!mw_field_compute (mesh_text, w, h, &nx, &ny, &dx, &dy))
    {
      g_mutex_lock (&mw_field_mutex);
      mw_fields[slot].state = 0;
      g_mutex_unlock (&mw_field_mutex);
      g_free (key);
      return FALSE;
    }

  /* ④ 交付（撞重：别的线程已算好同一份 → 用它的） */
  g_mutex_lock (&mw_field_mutex);
  {
    gint t;

    for (t = 0; t < MW_SLOTS; t++)
      {
        if (t != slot && mw_fields[t].state == 2 && mw_fields[t].key &&
            strcmp (mw_fields[t].key, key) == 0)
          {
            *out = mw_fields[t];
            g_mutex_unlock (&mw_field_mutex);
            g_free (dx);
            g_free (dy);
            g_free (key);
            mw_field_slot_clear (&mw_fields[slot]);
            return TRUE;
          }
      }
    mw_field_slot_clear (&mw_fields[slot]);
    mw_fields[slot].key = key;
    mw_fields[slot].nx = nx;
    mw_fields[slot].ny = ny;
    mw_fields[slot].dx = dx;
    mw_fields[slot].dy = dy;
    mw_fields[slot].state = 2;
    *out = mw_fields[slot];
  }
  g_mutex_unlock (&mw_field_mutex);
  return TRUE;
}

/* ---- 采样 ---------------------------------------------------------------- */

static inline void
mw_sample (const gfloat *src, gint w, gint h,
           gdouble sx, gdouble sy, gfloat *dst)
{
  gdouble w1 = w - 1.001, h1 = h - 1.001;
  gint x0, y0, c;
  gdouble fx, fy, ifx, ify;
  gsize o0, o1, o2, o3;

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
    dst[c] = (gfloat) (src[o0 + c] * (ifx * ify) +
                       src[o2 + c] * (fx * ify) +
                       src[o1 + c] * (ifx * fy) +
                       src[o3 + c] * (fx * fy));
}

static inline void
mw_field_offset (const MwField *f, gint w, gint h,
                 gdouble x, gdouble y, gdouble *ox, gdouble *oy)
{
  gdouble gx = (w > 1) ? x * (f->nx - 1.0) / (w - 1.0) : 0.0;
  gdouble gy = (h > 1) ? y * (f->ny - 1.0) / (h - 1.0) : 0.0;
  gint ix = (gint) CLAMP (gx, 0.0, f->nx - 1.0001);
  gint iy = (gint) CLAMP (gy, 0.0, f->ny - 1.0001);
  gdouble tx = gx - ix, ty = gy - iy;
  gsize r0 = (gsize) iy * f->nx + ix;
  gsize r1 = r0 + f->nx;
  gdouble a, b_, c, d, t0, t1;

  a = f->dx[r0];
  b_ = f->dx[r0 + 1];
  c = f->dx[r1];
  d = f->dx[r1 + 1];
  t0 = a + (b_ - a) * tx;
  t1 = c + (d - c) * tx;
  *ox = t0 + (t1 - t0) * ty;

  a = f->dy[r0];
  b_ = f->dy[r0 + 1];
  c = f->dy[r1];
  d = f->dy[r1 + 1];
  t0 = a + (b_ - a) * tx;
  t1 = c + (d - c) * tx;
  *oy = t0 + (t1 - t0) * ty;
}

/* ---- 滤镜本体 ------------------------------------------------------------ */

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");
  const Babl *fmt = babl_format_with_space ("R'G'B'A float", space);

  gegl_operation_set_format (operation, "input", fmt);
  gegl_operation_set_format (operation, "output", fmt);
}

/* 变形是全局的：任何输出像素都可能采自任何输入位置 → 要整张图 */
static GeglRectangle
get_required_for_output (GeglOperation       *operation,
                         const gchar         *input_pad,
                         const GeglRectangle *roi)
{
  GeglRectangle r = *roi;
  GeglRectangle full = gegl_operation_get_bounding_box (GEGL_OPERATION (operation));

  gegl_rectangle_bounding_box (&r, &r, &full);
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
  GeglRectangle   full;
  MwField         fc = { NULL, 0, 0, NULL, NULL };
  gfloat         *src, *dst;
  gint            stride, x, y;
  const gchar    *mesh_text = o->mesh ? o->mesh : "";

  full = *gegl_buffer_get_extent (input);
  if (full.width < 2 || full.height < 2)
    {
      gfloat *buf = g_new (gfloat, (gsize) 4 * result->width * result->height);

      gegl_buffer_get (input, result, 1.0, fmt, buf,
                       (gint) (sizeof (gfloat) * 4 * result->width),
                       GEGL_ABYSS_BLACK);
      gegl_buffer_set (output, result, level, fmt, buf,
                       (gint) (sizeof (gfloat) * 4 * result->width));
      g_free (buf);
      return TRUE;
    }

  if (!mw_field_for (mesh_text, full.width, full.height, &fc))
    return FALSE;

#ifdef MW_DEBUG
  {
    const gchar *dp = g_getenv ("MW_DEBUG_DUMP");
    if (dp)
      {
        FILE *f = fopen (dp, "wb");
        if (f)
          {
            gint32 hdr[2] = { fc.nx, fc.ny };
            fwrite (hdr, 4, 2, f);
            fwrite (fc.dx, 8, (gsize) fc.nx * fc.ny, f);
            fwrite (fc.dy, 8, (gsize) fc.nx * fc.ny, f);
            fclose (f);
          }
      }
  }
#endif

  /* 场全 0（恒等）：直通，保证逐字节不变 */
  {
    gsize n = (gsize) fc.nx * fc.ny, i;
    gboolean zero = TRUE;

    for (i = 0; i < n; i++)
      if (fc.dx[i] != 0.0 || fc.dy[i] != 0.0)
        {
          zero = FALSE;
          break;
        }
    if (zero)
      {
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

  stride = 4 * full.width;
  src = g_new (gfloat, (gsize) stride * full.height);
  dst = g_new (gfloat, (gsize) 4 * result->width * result->height);

  gegl_buffer_get (input, &full, 1.0, fmt, src,
                   (gint) (sizeof (gfloat) * stride), GEGL_ABYSS_BLACK);

  for (y = 0; y < result->height; y++)
    {
      gdouble py = result->y + y;
      gfloat *out_row = dst + (gsize) y * result->width * 4;

      for (x = 0; x < result->width; x++)
        {
          gdouble px = result->x + x;
          gdouble ox, oy, sx, sy;

          mw_field_offset (&fc, full.width, full.height, px, py, &ox, &oy);
          sx = px + ox;
          sy = py + oy;
          sx = CLAMP (sx, (gdouble) full.x,
                      (gdouble) (full.x + full.width) - 1.001) - full.x;
          sy = CLAMP (sy, (gdouble) full.y,
                      (gdouble) (full.y + full.height) - 1.001) - full.y;
          mw_sample (src, full.width, full.height, sx, sy,
                     out_row + (gsize) x * 4);
        }
    }

  gegl_buffer_set (output, result, level, fmt, dst,
                   (gint) (sizeof (gfloat) * 4 * result->width));

  g_free (src);
  g_free (dst);
  if (!fc.key)                       /* 私有解（全 RESERVED 时的退化路径） */
    {
      g_free (fc.dx);
      g_free (fc.dy);
    }
  return TRUE;
}



/* ---- 给 ctypes 的纯 C 接口（Puppet/Mesh Warp 的「实时预览」） -------------
 *
 * 为什么要这一层：交互时每一帧都要出一张预览，走 GEGL 那条路要建 buffer、
 * 走 babl 转格式、再整块取回，Python 侧还得 numpy 重采样一遍——480×360 实测
 * 84 ms（解场 47 + 重采样 37），拖动明显掉帧。
 *
 * 这里把**同一套** mw_field_for / mw_sample 直接暴露出来，Python 用 ctypes
 * 把源像素指针传进来，结果原地写回 dst。预览和最终烘焙走的是同一份数学，
 * 所以不存在「预览和结果不一致」的问题（这是这套设计最要紧的一点）。
 */
G_MODULE_EXPORT gint
mw_render_rgba (const gfloat *src, gint w, gint h,
                const gchar *mesh_text, gfloat *dst)
{
  MwField fc = { NULL, 0, 0, NULL, NULL };
  gint x, y;

  if (!src || !dst || w < 2 || h < 2)
    return 0;
  if (!mw_field_for (mesh_text ? mesh_text : "", w, h, &fc))
    return 0;

  for (y = 0; y < h; y++)
    {
      gfloat *row = dst + (gsize) y * w * 4;

      for (x = 0; x < w; x++)
        {
          gdouble ox, oy, sx, sy;

          mw_field_offset (&fc, w, h, (gdouble) x, (gdouble) y, &ox, &oy);
          sx = CLAMP ((gdouble) x + ox, 0.0, (gdouble) w - 1.001);
          sy = CLAMP ((gdouble) y + oy, 0.0, (gdouble) h - 1.001);
          mw_sample (src, w, h, sx, sy, row + (gsize) x * 4);
        }
    }

  if (!fc.key)                        /* 私有解（全 RESERVED 时的退化路径） */
    {
      g_free (fc.dx);
      g_free (fc.dy);
    }
  return 1;
}

/* u8 版本：插件里的预览像素本来就是 8 位 RGBA，让它自己在这边转 float。
 * 为什么不在 Python 里转——691200 个通道逐个 /255 是纯 Python 循环，实测比
 * 省下来的渲染时间还长（numpy 有的话很快，但 GIMP 自带的 Python 不一定装）。
 * 转 float 就走**同一个** mw_sample，所以预览和烘焙的像素一致到浮点误差。 */
G_MODULE_EXPORT gint
mw_render_rgba_u8 (const guint8 *src8, gint w, gint h,
                   const gchar *mesh_text, guint8 *dst8)
{
  gfloat *src, *dst;
  gsize n, i;
  gint ok;

  if (!src8 || !dst8 || w < 2 || h < 2)
    return 0;

  n = (gsize) w * h * 4;
  src = g_new (gfloat, n);
  dst = g_new (gfloat, n);
  for (i = 0; i < n; i++)
    src[i] = src8[i] * (1.0f / 255.0f);

  ok = mw_render_rgba (src, w, h, mesh_text, dst);
  if (ok)
    for (i = 0; i < n; i++)
      {
        gdouble v = dst[i] * 255.0 + 0.5;

        dst8[i] = (guint8) CLAMP (v, 0.0, 255.0);
      }

  g_free (src);
  g_free (dst);
  return ok;
}

/* 预览用：只解场、不重采样。返回 1 = 场全 0（恒等），0 = 需要重采样，
 * -1 = 失败。插件拿它来决定「要不要白算一遍像素」。 */
G_MODULE_EXPORT gint
mw_field_is_identity (const gchar *mesh_text, gint w, gint h)
{
  MwField fc = { NULL, 0, 0, NULL, NULL };
  gsize n, i;

  if (w < 2 || h < 2)
    return -1;
  if (!mw_field_for (mesh_text ? mesh_text : "", w, h, &fc))
    return -1;

  n = (gsize) fc.nx * fc.ny;
  for (i = 0; i < n; i++)
    if (fc.dx[i] != 0.0 || fc.dy[i] != 0.0)
      {
        if (!fc.key)
          {
            g_free (fc.dx);
            g_free (fc.dy);
          }
        return 0;
      }

  if (!fc.key)
    {
      g_free (fc.dx);
      g_free (fc.dy);
    }
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
    "name",            "lb:mesh-warp",
    "title",           _("Mesh Warp (live)"),
    "description",     _("Photoshop's Edit-Transform-Warp as a live filter: "
                         "drag the control mesh and the handles, the pixels "
                         "are never baked and the mesh can be re-edited at "
                         "any time."),
    "categories",      "distort",
    "gimp:menu-path",  "<Image>/SuperMrWang/Distort",
    "gimp:menu-label", _("Mesh Warp (live)…"),
    "position",        "gimp:middle",
    NULL);
}

#endif
