/* ===========================================================================
 * SuperMrWang · max-min 内核模板 / kernel template
 * ---------------------------------------------------------------------------
 * 这个头文件没有 include guard，是刻意的：max-min.c 会以不同的 PLANE_T /
 * PLANE_SLIDE / PLANE_BAND 宏把它展开三次，分别生成 u8、u16、float32 三份
 * 完全同构的代码。三个类型各自在自己的精度域里比较，中途不经过任何格式
 * 转换——极值只需要大小关系，但结果值必须原样搬出来，一次 u8→float→u8 的
 * 往返就足以让个别像素差 1 码。
 *
 * No include guard on purpose: max-min.c includes this three times with
 * different PLANE_* macros to emit byte-exact u8 / u16 / float32 variants.
 *
 * 调用前需定义：
 *   PLANE_T      元素类型
 *   PLANE_SLIDE  生成的「一行滑动极值」函数名
 *   PLANE_BAND   生成的「一带（band）两遍」函数名
 * 另外用到 max-min.c 中的 PICK(a, b, want_max) 宏。
 * ======================================================================== */

/* 一维滑动极值（窗口半宽 hw，即窗口宽 2hw+1），van Herk / Gil-Werman。
 *
 * 朴素做法每个像素扫 2hw+1 次；这里按窗口宽度把行切成块，块内先算前缀、
 * 后缀极值，任意一个窗口恰好被「起始处的后缀」和「末端处的前缀」拼满，
 * 于是每像素只要两次比较。开销与半径无关，O(n)。
 *
 * 边界一律复制边缘像素。对取极值而言这与「截断窗口」逐位等价：越界补进来
 * 的永远是本行已有像素的副本，不引入新值，也不像模糊那样会改变结果。
 * Clamp-to-edge is bit-identical to a truncated window for min/max.
 *
 * pad / pre / suf 是调用方复用的暂存，容量需 >= n + 2 * max_hw。
 */
static void
PLANE_SLIDE (const PLANE_T *src, PLANE_T *dst,
             gint           n,
             gint           hw,
             gboolean       want_max,
             PLANE_T       *pad,
             PLANE_T       *pre,
             PLANE_T       *suf)
{
  gint k = 2 * hw + 1;          /* 窗口宽度 */
  gint N = n + 2 * hw;          /* 补边后的长度 */
  gint i, j;

  if (hw <= 0)
  {
    memcpy (dst, src, (size_t) n * sizeof (PLANE_T));
    return;
  }

  for (i = 0; i < hw; i++)
    pad[i] = src[0];
  memcpy (pad + hw, src, (size_t) n * sizeof (PLANE_T));
  for (i = 0; i < hw; i++)
    pad[hw + n + i] = src[n - 1];

  for (j = 0; j < N; j += k)
  {
    gint end = MIN (j + k, N);

    pre[j] = pad[j];
    for (i = j + 1; i < end; i++)
      pre[i] = PICK (pre[i - 1], pad[i], want_max);

    suf[end - 1] = pad[end - 1];
    for (i = end - 2; i >= j; i--)
      suf[i] = PICK (suf[i + 1], pad[i], want_max);
  }

  /* dst[i] 对应 pad 中窗口 [i, i+k-1]：suf[i] 覆盖到本块末尾，
   * pre[i+k-1] 从上一块（或本块）开头补足，两者之并刚好是这个窗口 */
  for (i = 0; i < n; i++)
    dst[i] = PICK (suf[i], pre[i + k - 1], want_max);
}

/* 二维：在「一带」上跑完整个极值，结果为 h × w 连续排列。
 *
 * plane  带上下各 r 行先验余量的单通道平面（pw × ph）
 * ox, oy 结果左上角在平面内的坐标（正常情况就是 r, r；贴图边时更小）
 * round  true = 圆盘结构元（逐行半宽 sqrt(r²−dy²)），false = 方窗
 *
 * 方窗可分离：先横向一遍，再逐列纵向一遍，两遍都是 O(n)，与半径无关。
 * 圆盘每行半宽不同，无法分离；按 dy 逐行横向极值、再纵向累积，O(n·r)。
 * 半径 100 时这条路的比较次数约为方窗的 100 倍，但极值只有比较没有乘法，
 * 24MP 图仍在秒级。
 *
 * Square is separable (two O(n) passes); a disc is not, so it costs O(n·r).
 */
static void
PLANE_BAND (const PLANE_T *plane, gint pw, gint ph,
            gint ox, gint oy, gint w, gint h,
            gint r, gboolean want_max, gboolean round,
            PLANE_T *out)
{
  /* 行级暂存：纵向那一遍扫的是长度 ph 的列，所以容量按两者之大取，
   * 只按 pw 分配会在「高瘦」分带上越界（已经踩过）。 */
  gint    cap  = MAX (pw, ph) + 2 * r + 1;
  PLANE_T *pad = g_new (PLANE_T, cap);
  PLANE_T *pre = g_new (PLANE_T, cap);
  PLANE_T *suf = g_new (PLANE_T, cap);
  gint     i, j;

  if (!round)
  {
    PLANE_T *hor  = g_new (PLANE_T, (gsize) pw * ph);
    PLANE_T *col  = g_new (PLANE_T, ph);    /* 取列 */
    PLANE_T *cres = g_new (PLANE_T, ph);    /* 列结果 */

    /* 1) 横向 */
    for (i = 0; i < ph; i++)
      PLANE_SLIDE (plane + (gsize) i * pw, hor + (gsize) i * pw,
                   pw, r, want_max, pad, pre, suf);

    /* 2) 纵向（逐列，列在内存里不连续，因此先取出再扫描） */
    for (j = 0; j < w; j++)
    {
      gint x = ox + j;

      for (i = 0; i < ph; i++)
        col[i] = hor[(gsize) i * pw + x];

      PLANE_SLIDE (col, cres, ph, r, want_max, pad, pre, suf);

      for (i = 0; i < h; i++)
        out[(gsize) i * w + j] = cres[oy + i];
    }

    g_free (hor);
    g_free (col);
    g_free (cres);
  }
  else
  {
    PLANE_T *acc = g_new (PLANE_T, (gsize) w * h);
    PLANE_T *row = g_new (PLANE_T, pw);
    gboolean first = TRUE;
    gint     dy;

    for (dy = -r; dy <= r; dy++)
    {
      gint hw = (gint) floor (sqrt ((double) (r * r - dy * dy)) + 1e-9);

      for (i = 0; i < h; i++)
      {
        /* 平面行号贴边钳到边界：等价于把画布外的行按边缘行复制 */
        gint py = CLAMP (oy + i + dy, 0, ph - 1);
        gint x;

        PLANE_SLIDE (plane + (gsize) py * pw, row, pw, hw,
                     want_max, pad, pre, suf);

        if (first)
        {
          for (x = 0; x < w; x++)
            acc[(gsize) i * w + x] = row[ox + x];
        }
        else
        {
          for (x = 0; x < w; x++)
            acc[(gsize) i * w + x] =
              PICK (acc[(gsize) i * w + x], row[ox + x], want_max);
        }
      }
      first = FALSE;
    }

    memcpy (out, acc, (size_t) w * h * sizeof (PLANE_T));
    g_free (acc);
    g_free (row);
  }

  g_free (pad);
  g_free (pre);
  g_free (suf);
}
