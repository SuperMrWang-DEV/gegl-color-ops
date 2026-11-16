/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:color-lookup
 * menu       Color Lookup
 * purpose    按 .cube 3D LUT（可带 1D shaper）做颜色查找，等价于经典图像编辑器「颜色查找」
 *            调整图层；强度按 0..1 与原图线性混合
 *            Colour lookup through a .cube 3D LUT (optionally with 1D shaper
 *            tables), the equivalent of the classic editor Color Lookup adjustment
 *            layer. Strength blends the result back towards the source.
 * algorithm  解析 Cube LUT（LUT_1D_SIZE / LUT_3D_SIZE / DOMAIN_MIN /
 *            DOMAIN_MAX），节点值按声明的 domain 归一化到 0..1：1D 表逐通道
 *            先查，再进 3D 表（红变化最快，索引 r + g*n + b*n*n）。3D 采样可选
 *            三线性或四面体——四面体在灰轴附近不会出现三线性的楔形误差。
 *            强度 s 在输出端做 lerp(源, 查表结果, s)。
 *            Parse a Cube LUT, normalise node values to 0..1 with the
 *            declared domain, run the optional 1D shaper tables per channel,
 *            then sample the 3D table (red varies fastest, index
 *            r + g*n + b*n*n) either trilinearly or tetrahedrally. Strength
 *            lerps between the source and the mapped colour.
 * type       GeglOperationFilter（按行扫描 / row-wise）
 * reference  经典图像编辑器「颜色查找」调整层 + Cube LUT 规范
 *            the classic editor Color Lookup adjustment layer + Cube LUT spec
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <glib/gstdio.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_file_path (file, _("LUT File"), "")
    description (_("Cube LUT (.cube), 1D and/or 3D"))

property_double (strength, _("Strength"), 1.0)
    value_range (0.0, 1.0)
    ui_range (0.0, 1.0)
    description (_("Blend the mapped colour back towards the source"))

property_enum (interpolation, _("Interpolation"),
               ClInterp, cl_interp_enum, CL_TRILINEAR)
    description (_("How the 3D table is sampled between grid nodes"))

enum_start (cl_interp_enum)
  enum_value (CL_TRILINEAR, "trilinear", N_("Trilinear"))
  enum_value (CL_TETRAHEDRAL, "tetrahedral", N_("Tetrahedral"))
enum_end (ClInterp)

#else

#define GEGL_OP_FILTER
#define GEGL_OP_NAME     lb_color_lookup
#define GEGL_OP_C_SOURCE color-lookup.c
#include "gegl-op.h"

#define CL_MAX_3D 256

typedef struct {
  gchar   *path;          /* 缓存键：路径 + 修改时间 + 大小 */
  gint64   mtime;         /* cache key: path, mtime and size */
  goffset  size;
  gboolean loaded;        /* 已经尝试加载过（失败也算，避免每帧重试） */
  gboolean valid;

  gint     n1;            /* 1D 表长度，0 = 没有 */
  gfloat  *lut1;          /* n1 * 3，逐通道 */
  gint     n3;            /* 3D 表边长，0 = 没有 */
  gfloat  *lut3;          /* n3^3 * 3，红变化最快 */
} ClLut;

/* ---------------------------------------------------------------- 工具 ---- */

static gfloat
cl_clamp01 (gfloat v)
{
  if (!isfinite (v))
    return 0.0f;
  return CLAMP (v, 0.0f, 1.0f);
}

static void
cl_lut_free (ClLut *lut)
{
  if (!lut)
    return;
  g_free (lut->path);
  g_free (lut->lut1);
  g_free (lut->lut3);
  g_free (lut);
}

/* 解析一个以空白分隔的浮点数
 * parse one whitespace separated float */
static const gchar *
cl_next_float (const gchar *p, gfloat *out)
{
  while (*p == ' ' || *p == '\t' || *p == '\r')
    p++;
  if (!*p)
    return NULL;
  gchar *end = NULL;
  gdouble v = g_ascii_strtod (p, &end);
  if (end == p)
    return NULL;
  *out = (gfloat) v;
  return end;
}

/* 逐行读 .cube。任何结构问题都只让 valid=FALSE，算子退化为恒等，
 * 绝不因为一个坏文件让整张图渲染失败。
 * Read a .cube line by line. Any structural problem only clears `valid`, the
 * op then behaves as identity - a broken file must never fail a render. */
static gboolean
cl_parse_cube (ClLut *lut, const gchar *text, gsize len)
{
  gint   n1 = 0, n3 = 0;
  gfloat dmin[3] = { 0.0f, 0.0f, 0.0f };
  gfloat dmax[3] = { 1.0f, 1.0f, 1.0f };
  gfloat *vals = NULL;
  gsize   nvals = 0, cap = 0;

  const gchar *p = text;
  const gchar *end = text + len;

  while (p < end)
  {
    const gchar *eol = memchr (p, '\n', (gsize) (end - p));
    if (!eol)
      eol = end;

    /* 跳过行首空白与 UTF-8 BOM */
    const gchar *s = p;
    while (s < eol && (*s == ' ' || *s == '\t' || *s == '\r'
                       || (guchar) *s == 0xEF || (guchar) *s == 0xBB
                       || (guchar) *s == 0xBF))
      s++;

    if (s < eol && *s != '#')
    {
      if (g_ascii_strncasecmp (s, "LUT_1D_SIZE", 11) == 0)
      {
        n1 = (gint) g_ascii_strtoll (s + 11, NULL, 10);
      }
      else if (g_ascii_strncasecmp (s, "LUT_3D_SIZE", 11) == 0)
      {
        n3 = (gint) g_ascii_strtoll (s + 11, NULL, 10);
      }
      else if (g_ascii_strncasecmp (s, "DOMAIN_MIN", 10) == 0)
      {
        const gchar *q = s + 10;
        for (gint i = 0; i < 3; i++)
        {
          gfloat v;
          const gchar *nx = cl_next_float (q, &v);
          if (!nx)
            break;
          dmin[i] = v;
          q = nx;
        }
      }
      else if (g_ascii_strncasecmp (s, "DOMAIN_MAX", 10) == 0)
      {
        const gchar *q = s + 10;
        for (gint i = 0; i < 3; i++)
        {
          gfloat v;
          const gchar *nx = cl_next_float (q, &v);
          if (!nx)
            break;
          dmax[i] = v;
          q = nx;
        }
      }
      else if (g_ascii_strncasecmp (s, "LUT_1D_INPUT_RANGE", 18) == 0
            || g_ascii_strncasecmp (s, "LUT_3D_INPUT_RANGE", 18) == 0)
      {
        gfloat a = 0.0f, b = 1.0f;
        const gchar *q = cl_next_float (s + 18, &a);
        if (q)
        {
          const gchar *q2 = cl_next_float (q, &b);
          if (!q2)
            b = a;
        }
        for (gint i = 0; i < 3; i++)
        {
          dmin[i] = a;
          dmax[i] = b;
        }
      }
      else if (g_ascii_strncasecmp (s, "TITLE", 5) != 0)
      {
        /* 数据行：三个浮点
         * data row: three floats */
        const gchar *q = s;
        gfloat rgb[3];
        gint   got = 0;

        for (gint i = 0; i < 3; i++)
        {
          const gchar *nx = cl_next_float (q, &rgb[i]);
          if (!nx)
            break;
          q = nx;
          got++;
        }

        if (got == 3)
        {
          if (nvals + 3 > cap)
          {
            cap = cap ? cap * 2 : 4096;
            vals = g_renew (gfloat, vals, cap);
          }
          vals[nvals++] = rgb[0];
          vals[nvals++] = rgb[1];
          vals[nvals++] = rgb[2];
        }
      }
    }

    p = eol + 1;
  }

  /* 纯 1D 的 .cube 也合法（很多相机/厂商 LUT 只有 shaper 表）
   * A 1D-only .cube is legal too - plenty of vendor LUTs are shaper tables. */
  const gboolean has1 = (n1 >= 2);
  const gboolean has3 = (n3 >= 2 && n3 <= CL_MAX_3D);

  const gsize n1v = has1 ? (gsize) n1 * 3 : 0;
  const gsize n3v = has3 ? (gsize) n3 * (gsize) n3 * (gsize) n3 * 3 : 0;
  const gsize need = n1v + n3v;

  if ((!has1 && !has3) || nvals < need)
  {
    g_free (vals);
    return FALSE;
  }

  /* 归一化到 0..1（按文件声明的 domain）
   * normalise to 0..1 using the declared domain */
  gfloat scale[3];
  for (gint i = 0; i < 3; i++)
    scale[i] = (dmax[i] != dmin[i]) ? 1.0f / (dmax[i] - dmin[i]) : 1.0f;

  for (gsize i = 0; i < need; i += 3)
    for (gint c = 0; c < 3; c++)
      vals[i + c] = (vals[i + c] - dmin[c]) * scale[c];

  if (n1 > 0)
  {
    /* 文件里是样本主序（每行 r,g,b），内部改成通道主序，
     * 查表时一个通道就是一张连续的表
     * The file is sample-major (r,g,b per line); store channel-major so each
     * channel becomes one contiguous table. */
    lut->n1   = n1;
    lut->lut1 = g_new (gfloat, n1v);

    for (gint i = 0; i < n1; i++)
      for (gint c = 0; c < 3; c++)
        lut->lut1[(gsize) c * (gsize) n1 + (gsize) i] = vals[(gsize) i * 3 + (gsize) c];
  }

  if (has3)
  {
    lut->n3   = n3;
    lut->lut3 = g_new (gfloat, n3v);
    memcpy (lut->lut3, vals + n1v, sizeof (gfloat) * n3v);
  }

  g_free (vals);
  return TRUE;
}

/* 重新读文件（只在 prepare 里、且缓存键变了才做）
 * (re)load the file; only from prepare(), only when the cache key changed */
static void
cl_stat (const gchar *path, gint64 *mtime, goffset *size)
{
  GStatBuf st;

  *mtime = 0;
  *size  = 0;

  if (path && *path && g_stat (path, &st) == 0)
  {
    *mtime = (gint64) st.st_mtime;
    *size  = (goffset) st.st_size;
  }
}

static void
cl_lut_reload (ClLut *lut, const gchar *path)
{
  g_free (lut->lut1);
  g_free (lut->lut3);
  lut->lut1 = NULL;
  lut->lut3 = NULL;
  lut->n1 = lut->n3 = 0;
  lut->valid  = FALSE;
  lut->loaded = TRUE;

  cl_stat (path, &lut->mtime, &lut->size);

  if (!path || !*path)
    return;

  gchar *text = NULL;
  gsize  len  = 0;

  if (g_file_get_contents (path, &text, &len, NULL))
  {
    lut->valid = cl_parse_cube (lut, text, len);
    g_free (text);
  }

  if (!lut->valid)
  {
    g_free (lut->lut1);
    g_free (lut->lut3);
    lut->lut1 = NULL;
    lut->lut3 = NULL;
    lut->n1 = lut->n3 = 0;
    g_warning ("lb:color-lookup: 无法解析 LUT 文件 / cannot parse LUT: %s",
               (path && *path) ? path : "(empty)");
  }
}

/* 路径变了才重新加载；同一路径改了文件内容靠 mtime/size 兜住
 * reload only when the path changed; an edited file is caught by mtime/size.
 * （这里只在 prepare 里调用，一次渲染最多一次磁盘 IO） */
static void
cl_lut_refresh (ClLut *lut, const gchar *path)
{
  if (lut->loaded && g_strcmp0 (lut->path, path) == 0)
  {
    gint64  mtime;
    goffset size;

    cl_stat (path, &mtime, &size);

    if (mtime == lut->mtime && size == lut->size)
      return;

    cl_lut_reload (lut, path);
    return;
  }

  g_free (lut->path);
  lut->path = g_strdup (path);
  cl_lut_reload (lut, path);
}

/* -------------------------------------------------------------- 采样 ---- */

static inline const gfloat *
cl_node (const ClLut *lut, gint r, gint g, gint b)
{
  gsize idx = ((gsize) b * (gsize) lut->n3 + (gsize) g) * (gsize) lut->n3
              + (gsize) r;
  return lut->lut3 + idx * 3;
}

/* 把 0..1 的输入映射到网格坐标：格点序号 + 格内小数
 * map 0..1 onto grid coordinates: cell index plus in-cell fraction */
static inline void
cl_grid (const ClLut *lut, const gfloat v[3], gint i0[3], gfloat f[3])
{
  const gfloat n1f = (gfloat) (lut->n3 - 1);

  for (gint c = 0; c < 3; c++)
  {
    gfloat p = cl_clamp01 (v[c]) * n1f;
    i0[c] = (gint) p;
    if (i0[c] >= lut->n3 - 1)
      i0[c] = lut->n3 - 2;
    f[c] = p - (gfloat) i0[c];
  }
}

static inline void
cl_sample_trilinear (const ClLut *lut, const gfloat v[3], gfloat out[3])
{
  gint   i0[3];
  gfloat f[3];

  cl_grid (lut, v, i0, f);

  const gfloat *c000 = cl_node (lut, i0[0],     i0[1],     i0[2]);
  const gfloat *c100 = cl_node (lut, i0[0] + 1, i0[1],     i0[2]);
  const gfloat *c010 = cl_node (lut, i0[0],     i0[1] + 1, i0[2]);
  const gfloat *c110 = cl_node (lut, i0[0] + 1, i0[1] + 1, i0[2]);
  const gfloat *c001 = cl_node (lut, i0[0],     i0[1],     i0[2] + 1);
  const gfloat *c101 = cl_node (lut, i0[0] + 1, i0[1],     i0[2] + 1);
  const gfloat *c011 = cl_node (lut, i0[0],     i0[1] + 1, i0[2] + 1);
  const gfloat *c111 = cl_node (lut, i0[0] + 1, i0[1] + 1, i0[2] + 1);

  const gfloat fr = f[0], fg = f[1], fb = f[2];

  for (gint c = 0; c < 3; c++)
  {
    gfloat x00 = c000[c] + (c100[c] - c000[c]) * fr;
    gfloat x10 = c010[c] + (c110[c] - c010[c]) * fr;
    gfloat x01 = c001[c] + (c101[c] - c001[c]) * fr;
    gfloat x11 = c011[c] + (c111[c] - c011[c]) * fr;
    gfloat y0  = x00 + (x10 - x00) * fg;
    gfloat y1  = x01 + (x11 - x01) * fg;

    out[c] = y0 + (y1 - y0) * fb;
  }
}

/* 六面体分解：立方体按 fr/fg/fb 的大小关系切成 6 个四面体，每个只走 3 条棱。
 * 灰轴附近不会像三线性那样出现楔形偏色。
 * Six-tetrahedron decomposition: the cell is split by the ordering of
 * fr/fg/fb into six tetrahedra, three edges each. Unlike trilinear it does not
 * show the wedge-shaped neutral-axis error. */
static inline void
cl_sample_tetra (const ClLut *lut, const gfloat v[3], gfloat out[3])
{
  gint   i0[3];
  gfloat f[3];

  cl_grid (lut, v, i0, f);

  const gfloat *c000 = cl_node (lut, i0[0],     i0[1],     i0[2]);
  const gfloat *c100 = cl_node (lut, i0[0] + 1, i0[1],     i0[2]);
  const gfloat *c010 = cl_node (lut, i0[0],     i0[1] + 1, i0[2]);
  const gfloat *c110 = cl_node (lut, i0[0] + 1, i0[1] + 1, i0[2]);
  const gfloat *c001 = cl_node (lut, i0[0],     i0[1],     i0[2] + 1);
  const gfloat *c101 = cl_node (lut, i0[0] + 1, i0[1],     i0[2] + 1);
  const gfloat *c011 = cl_node (lut, i0[0],     i0[1] + 1, i0[2] + 1);
  const gfloat *c111 = cl_node (lut, i0[0] + 1, i0[1] + 1, i0[2] + 1);

  const gfloat fr = f[0], fg = f[1], fb = f[2];

  for (gint c = 0; c < 3; c++)
  {
    gfloat o;

    if (fr > fg)
    {
      if (fg > fb)              /* fr >= fg >= fb */
        o = c000[c] + fr * (c100[c] - c000[c])
                    + fg * (c110[c] - c100[c])
                    + fb * (c111[c] - c110[c]);
      else if (fr > fb)         /* fr >= fb > fg */
        o = c000[c] + fr * (c100[c] - c000[c])
                    + fb * (c101[c] - c100[c])
                    + fg * (c111[c] - c101[c]);
      else                      /* fb >= fr > fg */
        o = c000[c] + fb * (c001[c] - c000[c])
                    + fr * (c101[c] - c001[c])
                    + fg * (c111[c] - c101[c]);
    }
    else
    {
      if (fb > fg)              /* fb > fg >= fr */
        o = c000[c] + fb * (c001[c] - c000[c])
                    + fg * (c011[c] - c001[c])
                    + fr * (c111[c] - c011[c]);
      else if (fb > fr)         /* fg >= fb > fr */
        o = c000[c] + fg * (c010[c] - c000[c])
                    + fb * (c011[c] - c010[c])
                    + fr * (c111[c] - c011[c]);
      else                      /* fg >= fr >= fb */
        o = c000[c] + fg * (c010[c] - c000[c])
                    + fr * (c110[c] - c010[c])
                    + fb * (c111[c] - c110[c]);
    }

    out[c] = o;
  }
}

/* ------------------------------------------------------------- GEGL ---- */

/* 感知（非线性）格式：LUT 是给编码值（0..1 的 sRGB 码）定义的，
 * 喂线性光会把整张表用错位置
 * Perceptual (non-linear) format: a LUT is defined over encoded 0..1 values;
 * feeding linear light samples the table in the wrong place. */
static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}

static ClLut *
get_lut (GeglOperation *op)
{
  ClLut *lut = GEGL_PROPERTIES (op)->user_data;

  if (!lut)
  {
    lut = g_new0 (ClLut, 1);
    GEGL_PROPERTIES (op)->user_data = lut;
  }
  return lut;
}

static void
prepare (GeglOperation *op)
{
  gchar *path = NULL;

  g_object_get (G_OBJECT (op), "file", &path, NULL);
  cl_lut_refresh (get_lut (op), path);
  g_free (path);

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
  if (!roi || roi->width <= 0 || roi->height <= 0)
    return TRUE;

  gdouble  strength;
  ClInterp interp;

  g_object_get (G_OBJECT (op),
    "strength",      &strength,
    "interpolation", &interp,
    NULL);

  ClLut *lut = get_lut (op);
  const Babl *fmt = perceptual_format (op);
  const gboolean use_lut = lut->valid && (lut->n1 >= 2 || lut->n3 >= 2);
  const gfloat   s = CLAMP ((gfloat) strength, 0.0f, 1.0f);

  gint stride = roi->width * 4;
  gfloat *in_line  = g_new (gfloat, stride);
  gfloat *out_line = g_new (gfloat, stride);

  for (gint y = 0; y < roi->height; y++)
  {
    GeglRectangle row_rect = { roi->x, roi->y + y, roi->width, 1 };

    gegl_buffer_get (in_buf, &row_rect, 1.0f, fmt, in_line,
                     GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    for (gint x = 0; x < roi->width; x++)
    {
      gint  px = x * 4;
      gfloat src[3] = { in_line[px + 0], in_line[px + 1], in_line[px + 2] };
      gfloat rgb[3] = { cl_clamp01 (src[0]),
                        cl_clamp01 (src[1]),
                        cl_clamp01 (src[2]) };

      if (use_lut)
      {
        /* 1D shaper：逐通道先压一段曲线
         * 1D shaper: a per-channel curve applied before the 3D table */
        if (lut->n1 >= 2)
        {
          const gfloat n1f = (gfloat) (lut->n1 - 1);

          for (gint c = 0; c < 3; c++)
          {
            gfloat p = rgb[c] * n1f;
            gint   i = (gint) p;

            if (i >= lut->n1 - 1)
              i = lut->n1 - 2;

            gfloat t = p - (gfloat) i;
            const gfloat *tbl = lut->lut1 + (gsize) c * lut->n1;

            rgb[c] = tbl[i] + (tbl[i + 1] - tbl[i]) * t;
          }
        }

        if (lut->n3 >= 2)
        {
          if (interp == CL_TETRAHEDRAL)
            cl_sample_tetra (lut, rgb, rgb);
          else
            cl_sample_trilinear (lut, rgb, rgb);
        }
      }

      out_line[px + 0] = cl_clamp01 (src[0] + (rgb[0] - src[0]) * s);
      out_line[px + 1] = cl_clamp01 (src[1] + (rgb[1] - src[1]) * s);
      out_line[px + 2] = cl_clamp01 (src[2] + (rgb[2] - src[2]) * s);
      out_line[px + 3] = in_line[px + 3];
    }

    gegl_buffer_set (out_buf, &row_rect, 0, fmt, out_line, GEGL_AUTO_ROWSTRIDE);
  }

  g_free (in_line);
  g_free (out_line);
  return TRUE;
}

static void
finalize (GObject *object)
{
  cl_lut_free (GEGL_PROPERTIES (object)->user_data);
  GEGL_PROPERTIES (object)->user_data = NULL;

  G_OBJECT_CLASS (gegl_op_parent_class)->finalize (object);
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GObjectClass             *object_class = G_OBJECT_CLASS (klass);
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  object_class->finalize = finalize;
  oclass->prepare = prepare;
  fclass->process = process;

  gegl_operation_class_set_keys (oclass,
    "name",            "lb:color-lookup",
    "title",           _("Color Lookup"),
    "description",     _("Colour lookup through a Cube LUT (.cube), the equivalent of the classic editor Color Lookup adjustment layer. 1D shaper tables and trilinear / tetrahedral 3D sampling are supported."),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang/Blend",
    "gimp:menu-label", _("Color Lookup"),
    NULL);
}

#endif
