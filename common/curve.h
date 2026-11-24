/* ===========================================================================
 * SuperMrWang · 共用曲线内核 / shared curve kernel
 * ---------------------------------------------------------------------------
 * purpose    四个曲线算子（lb:lab-curves / lch-curves / hsv-curves /
 *            cmyk-curves）共用的控制点解析与单调三次插值
 *            Point-list parsing and monotone cubic interpolation shared by
 *            the four lb:*-curves operations.
 * note       所有函数 static inline，随每个算子各自编译一份，不做成独立库
 *            Everything is static inline and compiled into each op, so no
 *            separate shared library is needed.
 * algorithm  Fritsch–Carlson 单调三次 Hermite：切线在每段内做三点限制，
 *            保证插值不越过相邻控制点的上下界。为什么不用自然样条：
 *            自然样条在两点之间会过冲（打出比控制点还亮的包），落在色彩
 *            分量上就是一圈本不该有的色光；Catmull-Rom 同样不保单调。
 *            Fritsch–Carlson monotone cubic Hermite: tangents are limited per
 *            segment so the interpolant never overshoots the neighbouring
 *            control points. Natural splines and Catmull-Rom both overshoot,
 *            which on a colour component shows up as an unwanted colour bloom.
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#ifndef LB_CURVE_H
#define LB_CURVE_H

#include <math.h>
#include <string.h>
#include <glib.h>

/* 控制点上限：再多也不会有可见差别，却会让曲线串长到写不进滤镜参数
 * Point cap: more never shows a visible difference while making the string
 * grow past what is comfortable inside a filter parameter. */
#define LB_CURVE_MAX_POINTS  32

/* LUT 长度：1024 点在 16 位深上仍有 1/64 码的余量，比逐像素求 Hermite 便宜
 * 1024 entries leaves 1/64 code of headroom at 16 bit and is far cheaper
 * than evaluating Hermite per pixel. */
#define LB_CURVE_LUT         1024

typedef struct
{
  gint    n;                              /* 控制点数 / control point count */
  gdouble x[LB_CURVE_MAX_POINTS];
  gdouble y[LB_CURVE_MAX_POINTS];
  gfloat  lut[LB_CURVE_LUT];
  gboolean identity;                      /* y == x 全程，采样直接返回输入 */
} LbCurve;

/* ---------------------------------------------------------------------------
 * 恒等曲线：两点 (0,0)-(1,1)，identity 置位
 * The identity curve: two points (0,0)-(1,1) with the identity flag set.
 * ------------------------------------------------------------------------ */
static inline void
lb_curve_identity (LbCurve *c)
{
  memset (c, 0, sizeof *c);
  c->n = 2;
  c->x[0] = 0.0; c->y[0] = 0.0;
  c->x[1] = 1.0; c->y[1] = 1.0;
  for (gint i = 0; i < LB_CURVE_LUT; i++)
    c->lut[i] = (gfloat) i / (gfloat) (LB_CURVE_LUT - 1);
  c->identity = TRUE;
}

/* ---------------------------------------------------------------------------
 * 单点 Hermite 求值（区间 i 内）
 * Evaluate the cubic Hermite on segment i.
 * ------------------------------------------------------------------------ */
static inline gdouble
lb_curve_hermite (gdouble x,
                  gdouble x0, gdouble x1, gdouble y0, gdouble y1,
                  gdouble m0, gdouble m1)
{
  gdouble h = x1 - x0;
  if (h <= 0.0)
    return y1;
  gdouble t  = (x - x0) / h;
  gdouble t2 = t * t;
  gdouble t3 = t2 * t;

  /* 三次 Hermite 基函数 / cubic Hermite basis */
  gdouble h00 =  2.0 * t3 - 3.0 * t2 + 1.0;
  gdouble h10 =        t3 - 2.0 * t2 + t;
  gdouble h01 = -2.0 * t3 + 3.0 * t2;
  gdouble h11 =        t3 -       t2;

  return h00 * y0 + h10 * h * m0 + h01 * y1 + h11 * h * m1;
}

/* ---------------------------------------------------------------------------
 * 由控制点建 LUT
 * Build the LUT from the control points.
 *
 * 调用前 x[]/y[] 必须已按 x 升序、首尾覆盖 0 和 1。
 * x[]/y[] must already be sorted and must span 0..1 at the ends.
 * 失败（点数不足）时退回恒等，调用方不必再判。
 * Falls back to identity when there are too few points.
 * ------------------------------------------------------------------------ */
static inline void
lb_curve_build (LbCurve *c)
{
  if (c->n < 2)
  {
    lb_curve_identity (c);
    return;
  }

  /* 端点落在 (0,0)/(1,1) 上且所有点都在对角线上 → 恒等，不必建表
   * Ends on (0,0)/(1,1) with every point on the diagonal → identity. */
  {
    gboolean diag = TRUE;
    for (gint i = 0; i < c->n; i++)
      if (fabs (c->y[i] - c->x[i]) > 1e-9)
      {
        diag = FALSE;
        break;
      }
    if (diag)
    {
      lb_curve_identity (c);
      return;
    }
  }

  const gint n = c->n;
  gdouble d[LB_CURVE_MAX_POINTS - 1];   /* 割线斜率 / secant slopes */
  gdouble m[LB_CURVE_MAX_POINTS];       /* 节点切线 / node tangents   */

  for (gint i = 0; i < n - 1; i++)
  {
    gdouble h = c->x[i + 1] - c->x[i];
    d[i] = (h > 1e-12) ? (c->y[i + 1] - c->y[i]) / h : 0.0;
  }

  /* 端点用单侧割线，内部用相邻割线均值——这是 Fritsch–Carlson 的起点
   * One-sided secant at the ends, mean of both secants inside. */
  m[0]     = d[0];
  m[n - 1] = d[n - 2];
  for (gint i = 1; i < n - 1; i++)
    m[i] = 0.5 * (d[i - 1] + d[i]);

  /* 限制：把切线圆夹进 3·|割线| 的圆里，插值就不会冲出相邻控制点
   * Limit each tangent pair to a circle of radius 3·|secant|; this is what
   * keeps the interpolant monotone between control points. */
  for (gint i = 0; i < n - 1; i++)
  {
    if (fabs (d[i]) < 1e-12)
    {
      m[i] = 0.0;
      m[i + 1] = 0.0;
      continue;
    }
    gdouble a = m[i]     / d[i];
    gdouble b = m[i + 1] / d[i];
    gdouble s = a * a + b * b;
    if (s > 9.0)
    {
      gdouble t = 3.0 / sqrt (s);
      m[i]     = t * a * d[i];
      m[i + 1] = t * b * d[i];
    }
  }

  /* 采样建表：段内按 x 前进，避免每点都从第 0 段开始线性搜索
   * Fill the table walking forward through the segments. */
  gint seg = 0;
  for (gint i = 0; i < LB_CURVE_LUT; i++)
  {
    gdouble v = (gdouble) i / (gdouble) (LB_CURVE_LUT - 1);
    while (seg < n - 2 && v > c->x[seg + 1])
      seg++;

    gdouble r = lb_curve_hermite (v,
                                  c->x[seg], c->x[seg + 1],
                                  c->y[seg], c->y[seg + 1],
                                  m[seg],    m[seg + 1]);
    c->lut[i] = (gfloat) CLAMP (r, 0.0, 1.0);
  }

  /* 两端钉死：中点采样永远不落在 v=0 与 v=1 之外，但浮点误差可能让表首尾
   * 与端点差一两个码，钉一下省得逐像素再判
   * Pin both ends so the table matches the endpoints exactly. */
  c->lut[0]              = (gfloat) CLAMP (c->y[0],     0.0, 1.0);
  c->lut[LB_CURVE_LUT - 1] = (gfloat) CLAMP (c->y[n - 1], 0.0, 1.0);

  c->identity = FALSE;
}

/* ---------------------------------------------------------------------------
 * 解析一段控制点串："0,0 0.25,0.22 1,1"
 * Parse one point list: "0,0 0.25,0.22 1,1"
 *
 * 容错策略：坏 token 直接跳过而不是整体失败——曲线串可能存在滤镜参数里，
 * 用户手改过之后语法出错不该让整个调整失效，退化成一条更简单的曲线总比
 * 「滤镜报错、画面全黑」好。
 * Bad tokens are skipped rather than rejecting the whole string: it lives in
 * a filter property that users can edit by hand, and degrading to a simpler
 * curve beats a filter that refuses to render.
 *
 * 返回解析成功并采纳的点数 / returns the number of points accepted.
 * ------------------------------------------------------------------------ */
static inline gint
lb_curve_parse_points (LbCurve *c, const gchar *text)
{
  gchar **tokens;
  gint    used = 0;

  c->n = 0;

  if (!text || !*text)
    return 0;

  tokens = g_strsplit_set (text, " \t\r\n", -1);
  for (gint i = 0; tokens[i]; i++)
  {
    const gchar *tok = tokens[i];
    gchar       *end = NULL;
    gdouble      x, y;
    gint         j;

    if (!*tok || c->n >= LB_CURVE_MAX_POINTS)
      continue;

    x = g_ascii_strtod (tok, &end);
    if (!end || *end != ',')
      continue;                         /* 不是 "x,y" / not a point pair */
    y = g_ascii_strtod (end + 1, &end);

    x = CLAMP (x, 0.0, 1.0);
    y = CLAMP (y, 0.0, 1.0);

    /* 插入排序：控制点很少，十几项的插入排序比 qsort 更快也更好读
     * Insertion sort: with a handful of points this beats qsort. */
    for (j = c->n; j > 0 && c->x[j - 1] > x; j--)
    {
      c->x[j] = c->x[j - 1];
      c->y[j] = c->y[j - 1];
    }
    c->x[j] = x;
    c->y[j] = y;
    c->n++;
    used++;
  }
  g_strfreev (tokens);

  /* 同 x 只留最后一个；x 重复会让 Hermite 的段长为 0，切线和 LUT 都没定义
   * Keep the last point for duplicate x: a zero-width segment leaves both
   * the tangent and the LUT undefined. */
  {
    gint w = 0;
    for (gint i = 0; i < c->n; i++)
    {
      if (w > 0 && fabs (c->x[i] - c->x[w - 1]) < 1e-9)
      {
        c->y[w - 1] = c->y[i];
        continue;
      }
      c->x[w] = c->x[i];
      c->y[w] = c->y[i];
      w++;
    }
    c->n = w;
  }

  return used;
}

/* ---------------------------------------------------------------------------
 * 解析一条完整曲线（补端点 + 建表）
 * Parse one complete curve: fill in the ends, then build the LUT.
 *
 * 端点缺失时补 (0,0) / (1,1)，而不是把首点的 y 平延过去。理由：用户只写了
 * 一个中间点时，本意几乎总是「让中间弯一下，两头别动」，平延会把整幅图压成
 * 一个常数。曲线编辑器也永远给出覆盖全域的曲线，这里只是对残缺输入兜底。
 * Missing ends get (0,0)/(1,1) rather than extending the nearest y: a user
 * who typed a single mid point almost always means "bend the middle, leave
 * the ends alone", and extending would flatten the whole image to a constant.
 * ------------------------------------------------------------------------ */
static inline void
lb_curve_parse (LbCurve *c, const gchar *text)
{
  lb_curve_parse_points (c, text);

  if (c->n < 2)
  {
    lb_curve_identity (c);
    return;
  }

  if (c->x[0] > 1e-9 && c->n < LB_CURVE_MAX_POINTS)
  {
    memmove (&c->x[1], &c->x[0], sizeof (c->x[0]) * c->n);
    memmove (&c->y[1], &c->y[0], sizeof (c->y[0]) * c->n);
    c->x[0] = 0.0;
    c->y[0] = 0.0;
    c->n++;
  }
  if (c->x[c->n - 1] < 1.0 - 1e-9 && c->n < LB_CURVE_MAX_POINTS)
  {
    c->x[c->n] = 1.0;
    c->y[c->n] = 1.0;
    c->n++;
  }

  lb_curve_build (c);
}

/* ---------------------------------------------------------------------------
 * 环形分量的默认曲线：一条 y = 0.5 的水平线
 * The default curve for a circular component: a flat line at y = 0.5.
 *
 * 前置声明：偏移采样要调用通用采样器，而它定义在后面。
 * Forward declaration: the offset sampler below calls the generic one.
 * 色相不能当普通分量画对角线。色相是环形的，曲线首尾映射到不同的 y 时，
 * 0° 与 360° 会撞出一条硬接缝；而首尾强行对齐又做不了整体旋转（那恰恰是
 * 「色相偏移」最常用的形态）。所以色相分量改用**偏移曲线**：横轴是输入
 * 色相，纵轴 0.5 表示不偏，整体旋转 = 一条水平线，分带调整 = 曲线在中间弯，
 * 两种用法都天然连续，不存在接缝。
 * Hue cannot use the usual diagonal. It is circular, so a curve whose ends
 * map to different values leaves a hard seam where 0° meets 360°; forcing
 * the ends together kills the whole-circle rotation, which is the most common
 * use. Hue components therefore use an offset curve: the x axis is the input
 * hue, y = 0.5 means no shift, a flat line at another height rotates the whole
 * ring, and a bent line redistributes bands — both stay continuous.
 * ------------------------------------------------------------------------ */
static inline gfloat lb_curve_at (const LbCurve *c, gfloat v01);

static inline void
lb_curve_offset_default (LbCurve *c)
{
  memset (c, 0, sizeof *c);
  c->n = 2;
  c->x[0] = 0.0; c->y[0] = 0.5;
  c->x[1] = 1.0; c->y[1] = 0.5;
  /* identity 在这里的含义是「零偏移」，不是「对角线」：采样器见 identity
   * 直接返回输入，正好等于不偏，于是没被曲线串覆盖过的色相分量能走快路径
   * identity here means "zero shift" rather than "diagonal": the sampler
   * returns its input, which is exactly no shift, so an untouched hue
   * component keeps the fast path. */
  c->identity = TRUE;
  for (gint i = 0; i < LB_CURVE_LUT; i++)
    c->lut[i] = 0.5f;
}

/* ---------------------------------------------------------------------------
 * 偏移曲线采样：返回 0..1 的色相，已按模 1 折回
 * Sample an offset curve and return the hue wrapped back into 0..1.
 *
 * 偏移量夹在 ±0.5：再多就等价于往反方向转，画出来还会在环上自交。
 * The shift is clamped to ±0.5; beyond that it just equals turning the other
 * way, and the curve would fold over itself on the ring.
 * ------------------------------------------------------------------------ */
static inline gfloat
lb_curve_offset_at (const LbCurve *c, gfloat v01)
{
  gfloat d;

  if (c->identity)                  /* 防御：身份曲线当 0 偏移 */
    return v01;

  d = CLAMP (lb_curve_at (c, v01) - 0.5f, -0.5f, 0.5f);
  v01 += d;
  if (v01 < 0.0f)
    v01 += 1.0f;
  else if (v01 >= 1.0f)
    v01 -= 1.0f;
  return v01;
}

/* ---------------------------------------------------------------------------
 * 采样：v 归一到 0..1，返回同样归一的输出
 * Sample with both the input and the output normalised to 0..1.
 * ------------------------------------------------------------------------ */
static inline gfloat
lb_curve_at (const LbCurve *c, gfloat v01)
{
  gfloat t;
  gint   i;
  gfloat f;

  if (c->identity)
    return v01;

  v01 = CLAMP (v01, 0.0f, 1.0f);
  t = v01 * (gfloat) (LB_CURVE_LUT - 1);
  i = (gint) t;
  if (i >= LB_CURVE_LUT - 1)
    return c->lut[LB_CURVE_LUT - 1];

  f = t - (gfloat) i;
  return c->lut[i] * (1.0f - f) + c->lut[i + 1] * f;
}

/* ---------------------------------------------------------------------------
 * 解析带分量名的成组曲线："L 0,0 0.3,0.2 1,1|a 0,0 1,1|b 0,0 1,1"
 * Parse a named group: "L 0,0 0.3,0.2 1,1|a 0,0 1,1|b 0,0 1,1"
 *
 * 每段以分量名开头（名字不含逗号），后续是控制点。**没有出现的分量保持
 * 调用方预置的样子**——普通分量该预设 lb_curve_identity()，环形分量该预设
 * lb_curve_offset_default()，所以这个函数自己不碰 out[] 的初值。
 * Each segment starts with a component name (no comma in it) followed by
 * points. **Components that do not appear keep whatever the caller put
 * there** — lb_curve_identity() for an ordinary one, lb_curve_offset_default()
 * for a circular one — so this function never resets out[] itself.
 *
 * 名字不认识、或整段没有名字时按出现顺序回退，因为这个字符串是给人改的。
 * Unknown or missing names fall back to position, because this string is
 * meant to be hand-edited.
 * ------------------------------------------------------------------------ */
static inline void
lb_curve_parse_set (LbCurve        *out,
                    gint            count,
                    const gchar   **names,
                    const gchar    *text)
{
  gchar **segs;

  if (!text || !*text)
    return;

  segs = g_strsplit (text, "|", -1);
  for (gint i = 0; segs[i]; i++)
  {
    gchar *seg = g_strstrip (segs[i]);
    gchar *body;
    gint   slot = -1;

    if (!*seg)
      continue;

    body = seg;
    while (*body && *body != ' ' && *body != '\t')
      body++;

    if (*body)
    {
      gint    namelen = (gint) (body - seg);
      gchar  *name    = g_strndup (seg, namelen);
      gchar  *trimmed = g_strstrip (name);

      for (gint k = 0; k < count; k++)
        if (g_ascii_strcasecmp (trimmed, names[k]) == 0)
        {
          slot = k;
          break;
        }
      g_free (name);
      body = g_strstrip (body);
    }
    else
    {
      /* 整段只有一个 token：要么是名字（该分量保持恒等），要么是孤立点
       * A segment holding one token is either a bare name or a lone point. */
      if (strchr (seg, ','))
        body = seg;
      else
        continue;
    }

    if (slot < 0)
      slot = i;                        /* 没有名字时按出现顺序 / by position */

    if (slot >= 0 && slot < count)
      lb_curve_parse (&out[slot], body);
  }
  g_strfreev (segs);
}

#endif /* LB_CURVE_H */
