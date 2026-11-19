/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:max-min
 * menu       Maximum / Minimum
 * purpose    形态学的两个基本算子，也是 Photoshop「最大值 / 最小值」滤镜的
 *           等价物：每个像素取邻域内最大（膨胀）或最小值（腐蚀）。
 *           最大值把亮区向外推、吞掉暗处的小点；最小值反过来收亮区、
 *           啃掉残留的白边。蒙版精修、去灰尘点、发光底图都用它。
 *           Morphological dilate / erode — the two halves of Photoshop's
 *           Maximum / Minimum filter.
 * input      任意格式的 drawable 缓冲。三个色/灰度分量各自独立取极值，
 *           alpha 默认不参与（PS 同样不动图层透明度；抠图边缘被一起
 *           膨胀会得到意料外的结果）。
 * algorithm  矩形结构元可分离：先横向一遍滑动极值、再纵向一遍，均摊 O(n)，
 *           与半径无关（van Herk / Gil-Werman，见 maxmin-kernel.h）。
 *           圆盘结构元每行半宽 sqrt(r²−dy²) 不同，不能分离，退化为
 *           O(n·r)：逐 dy 做横向极值再纵向累积。
 *           半径 r 表示检查 (±r, ±r) 的方形邻域（r=1 即 3×3，边界向外
 *           长一圈），与 Photoshop 的半径语义一致。
 *           边界按复制边缘像素处理。对取极值而言这与「截断窗口」逐位
 *           等价，不像模糊那样会在边缘暗一圈。
 * precision 在缓冲自身的精度域里比较：u8 比 u8、u16 比 u16、float32 比
 *           float32，中途不做任何格式转换。极值只需要大小关系，但如果把
 *           u16 读成 float 再写回，个别像素会差 1 码——这里不给它机会。
 *           不做色彩管理、不做 gamma 换算：PS 的这两个滤镜同样是直接对
 *           通道值取极值。
 * type       GeglOperationAreaFilter（邻域滤波，需要向外扩 r 像素的输入）
 * used-by    plugin/max-min —— 参数（模式 / 半径 / 形状 / alpha）都由它弹窗收集
 * reference  Adobe Photoshop「滤镜 → 其它 → 最大值 / 最小值」
 *            （半径 1–100、保留：方形度 / 圆度）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

enum_start (lb_mm_mode)
  enum_value (MM_MODE_MAXIMUM, "maximum", "Maximum (dilate)")
  enum_value (MM_MODE_MINIMUM, "minimum", "Minimum (erode)")
enum_end (LbMmMode)

property_enum (mode, _("Mode"), LbMmMode, lb_mm_mode, MM_MODE_MAXIMUM)
    description (_("最大值＝每个像素取邻域内的最大（膨胀，亮区外扩）；"
                   "最小值＝取最小（腐蚀，亮区收缩）"))

enum_start (lb_mm_shape)
  enum_value (MM_SHAPE_SQUARE, "square", "Square")
  enum_value (MM_SHAPE_ROUND,  "round",  "Round")
enum_end (LbMmShape)

property_enum (shape, _("Shape"), LbMmShape, lb_mm_shape, MM_SHAPE_SQUARE)
    description (_("方形＝(±r, ±r) 的方窗；圆形＝半径 r 的圆盘。"
                   "对应 Photoshop 的「保留：方形度 / 圆度」"))

property_int (radius, _("Radius"), 3)
    description (_("半径（像素）。r=1 即 3×3 邻域，边缘向外长一圈。"
                   "与 Photoshop 一样限制在 1–100"))
    value_range (1, 100)
    ui_range (1, 30)

property_boolean (affect_alpha, _("Affect Alpha"), FALSE)
    description (_("是否连 alpha 一起取极值。默认不动 alpha：PS 同样不改"
                   "图层透明度，抠图边缘跟着膨胀往往不是想要的结果"))

#else

#define GEGL_OP_AREA_FILTER
#define GEGL_OP_NAME     lb_max_min
#define GEGL_OP_C_SOURCE max-min.c
#include "gegl-op.h"

/* 取值：want_max 为真取大，否则取小。内核模板按这个宏展开三次 */
#define PICK(a, b, want_max) \
  ((want_max) ? ((a) > (b) ? (a) : (b)) : ((a) < (b) ? (a) : (b)))

/* ---- 三份同构内核 / three typed kernels ---------------------------------- */

#define PLANE_T     guint8
#define PLANE_SLIDE slide_u8
#define PLANE_BAND  band_u8
#include "maxmin-kernel.h"
#undef PLANE_T
#undef PLANE_SLIDE
#undef PLANE_BAND

#define PLANE_T     guint16
#define PLANE_SLIDE slide_u16
#define PLANE_BAND  band_u16
#include "maxmin-kernel.h"
#undef PLANE_T
#undef PLANE_SLIDE
#undef PLANE_BAND

#define PLANE_T     gfloat
#define PLANE_SLIDE slide_f32
#define PLANE_BAND  band_f32
#include "maxmin-kernel.h"
#undef PLANE_T
#undef PLANE_SLIDE
#undef PLANE_BAND

/* ---- 逐通道搬进搬出 / per-channel interleave ---------------------------- */

/* 把交错缓冲里的第 c 个分量摊成平面、算完再摊回去。
 * 这样缓冲只需按「一带」分配，24MP 的 32 位图也不会一次性吃掉几百 MB。 */
#define RUN_CHANNEL(T, BAND)                                                  \
  do {                                                                        \
    T    *plane = g_new (T, (gsize) pw * ph);                                 \
    T    *outp  = g_new (T, (gsize) w * h);                                   \
    gint  rr, xx;                                                             \
    for (rr = 0; rr < ph; rr++)                                               \
      for (xx = 0; xx < pw; xx++)                                             \
        memcpy (plane + (gsize) rr * pw + xx,                                 \
                in + ((gsize) rr * pw + xx) * bpp + (gsize) c * bpc,          \
                sizeof (T));                                                  \
    BAND (plane, pw, ph, ox, oy, w, h, r, want_max, round, outp);             \
    for (rr = 0; rr < h; rr++)                                                \
      for (xx = 0; xx < w; xx++)                                              \
        memcpy (res + ((gsize) rr * w + xx) * bpp + (gsize) c * bpc,          \
                outp + (gsize) rr * w + xx, sizeof (T));                      \
    g_free (plane);                                                           \
    g_free (outp);                                                            \
  } while (0)

/* ---- 准备：告诉 GEGL 需要向外扩多少 ------------------------- */ 

static void
prepare (GeglOperation *operation)
{
  GeglProperties          *o  = GEGL_PROPERTIES (operation);
  GeglOperationAreaFilter *af = GEGL_OPERATION_AREA_FILTER (operation);
  const Babl              *fmt;

  af->left = af->right = af->top = af->bottom = CLAMP (o->radius, 1, 100);

  /* 输入输出钉成同一个格式：这个算子只比较、不换算 */
  fmt = gegl_operation_get_source_format (operation, "input");
  if (fmt == NULL)
    fmt = babl_format ("R'G'B'A float");
  gegl_operation_set_format (operation, "input", fmt);
  gegl_operation_set_format (operation, "output", fmt);
}

/* ---- 主过程 -------------------------------------------------------------- */

#define BAND_ROWS 128

static gboolean
process (GeglOperation       *operation,
         GeglBuffer          *input,
         GeglBuffer          *output,
         const GeglRectangle *result,
         gint                 level)
{
  GeglProperties    *o = GEGL_PROPERTIES (operation);
  const Babl        *fmt = gegl_buffer_get_format (input);
  const gchar       *name = babl_get_name (fmt);
  gint               ncomp = babl_format_get_n_components (fmt);
  gint               bpp = babl_format_get_bytes_per_pixel (fmt);
  gint               bpc = (ncomp > 0) ? bpp / ncomp : 0;
  gint               r = CLAMP (o->radius, 1, 100);
  gboolean           want_max = (o->mode == MM_MODE_MAXIMUM);
  gboolean           round = (o->shape == MM_SHAPE_ROUND);
  gboolean           is_u8 = FALSE, is_u16 = FALSE, is_f32 = FALSE;
  gboolean           has_alpha;
  gint               c, yb;
  const GeglRectangle *src_bb;
  GeglRectangle       bb;

  if (!is_u8 && bpc == 1)
    is_u8 = TRUE;
  if (bpc == 2 && g_strrstr (name, "u16") != NULL)
    is_u16 = TRUE;
  if (bpc == 4 && g_strrstr (name, "float") != NULL)
    is_f32 = TRUE;

  if (!is_u8 && !is_u16 && !is_f32)
  {
    g_warning ("lb:max-min 不支持缓冲格式 %s（只支持 u8 / u16 / float32）",
               name ? name : "?");
    return FALSE;
  }

  /* alpha 判定：通道数为 2 或 4 且格式名里带 alpha 标记。
   * "R'G'B'A u8" 末尾是 "A u8"，"RGBA float" 是 "A float"，
   * "Y u8" 没有 alpha。 */
  has_alpha = (ncomp == 2 || ncomp == 4) &&
              (g_strrstr (name, "A ") != NULL ||
               g_strrstr (name, "alpha") != NULL);

  src_bb = gegl_operation_source_get_bounding_box (operation, "input");
  if (src_bb != NULL)
    bb = *src_bb;
  else
    bb = *gegl_buffer_get_extent (input);

  /* 分带在外、通道在内：每一带只读一次、写一次，几个通道各自覆盖自己那一列。
   * 反过来（通道在外）会让后一个通道用输入重建整带，把前一个通道的结果
   * 覆盖回去——这个坑已经踩过一次，注释留在这里。
   * Bands outer, channels inner: each band is read once and written once. */
  for (yb = result->y; yb < result->y + result->height; yb += BAND_ROWS)
  {
    gint          bh = MIN (BAND_ROWS, result->y + result->height - yb);
    gint          w = result->width;
    gint          h = bh;
    gint          py0 = MAX (bb.y, yb - r);
    gint          py1 = MIN (bb.y + bb.height, yb + bh + r);
    gint          px0 = MAX (bb.x, result->x - r);
    gint          px1 = MIN (bb.x + bb.width, result->x + result->width + r);
    gint          ph = py1 - py0;
    gint          pw = px1 - px0;
    gint          ox = result->x - px0;
    gint          oy = yb - py0;
    gint          rr;
    GeglRectangle prect = { px0, py0, pw, ph };
    GeglRectangle outr  = { result->x, yb, result->width, bh };
    gpointer      in, res;

    if (pw <= 0 || ph <= 0)
      continue;

    in  = g_malloc ((gsize) pw * ph * bpp);
    res = g_malloc ((gsize) result->width * bh * bpp);

    gegl_buffer_get (input, &prect, 1.0, fmt, in,
                     GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);

    /* 先原样铺一遍：不参与运算的通道（默认是 alpha）就此透传，
     * 后面只覆盖真正要算的那几个 */
    for (rr = 0; rr < bh; rr++)
      memcpy (res + (gsize) rr * result->width * bpp,
              in + ((gsize) (oy + rr) * pw + ox) * bpp,
              (gsize) result->width * bpp);

    for (c = 0; c < ncomp; c++)
    {
      if (has_alpha && c == ncomp - 1 && !o->affect_alpha)
        continue;

      if (is_u8)
        RUN_CHANNEL (guint8, band_u8);
      else if (is_u16)
        RUN_CHANNEL (guint16, band_u16);
      else
        RUN_CHANNEL (gfloat, band_f32);
    }

    gegl_buffer_set (output, &outr, 0, fmt, res, GEGL_AUTO_ROWSTRIDE);

    g_free (in);
    g_free (res);
  }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass       *oclass = GEGL_OPERATION_CLASS (klass);
  GeglOperationFilterClass *fclass = GEGL_OPERATION_FILTER_CLASS (klass);

  oclass->prepare = prepare;
  fclass->process = process;

  gegl_operation_class_set_keys (oclass,
    "name",        "lb:max-min",
    "title",       _("Maximum / Minimum"),
    "description", _("Morphological dilate (maximum) and erode (minimum) over "
                     "a square or round neighbourhood: expands or shrinks "
                     "bright areas. The equivalent of Photoshop's Maximum / "
                     "Minimum filter, computed in the buffer's own precision."),
    "categories",  "generic",
    NULL);
}

#endif
