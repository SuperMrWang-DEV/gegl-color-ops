/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:brightness-contrast-ps
 * menu       Brightness/Contrast (Photoshop)
 * purpose    复刻 Photoshop「亮度/对比度」，新版与旧版（「使用旧版」复选框）
 *            两套行为都在里面
 *            Reproduce Photoshop's Brightness/Contrast, both the modern
 *            behaviour and the legacy one behind the "Use Legacy" checkbox.
 * algorithm  实测结论（Photoshop 26.10，16 位/通道标定）：
 *            ① 这是一条逐通道相同的 LUT —— 与邻居、位置、通道都无关
 *              （通道耦合实测 0.000，正/反向 ramp 逐位镜像）
 *            ② 新版 = 先亮度、后对比度：f(x) = F_c(F_b(x))，可分离误差 0.02 码
 *            ③ 旧版 = 亮度是 clamp(x+b) 且 b 被夹到 ±100；对比度是围绕
 *              89.0（不是 128）的线性缩放，K = 1/(1-c/100) 或 1+c/100；
 *              且 c>0 时先加亮度再缩放，c<0 时先缩放再加亮度
 *            ④ 新版把 x=255 原样保留（纯白保护），旧版没有这条规则
 *            Measured facts (Photoshop 26.10, 16 bit/ch calibration):
 *            (1) it is one LUT applied identically to all three channels;
 *            (2) modern = brightness then contrast, separable to 0.02 codes;
 *            (3) legacy = clamp(x+b) with b clamped to ±100, and contrast is
 *                a linear scaling about 89.0 (not 128), with the order
 *                depending on the sign of c;
 *            (4) modern pins x=255 to 255 (pure-white protection).
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * source     bc-cal/：标定图 + JSX 批量 + 16 位数据；参数表由
 *            tools/gen_bc_tables.py 从 bc_model.json 导出，算子不手抄常数
 * reference  Adobe Photoshop 26.10 亮度/对比度（实测逆向）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

property_double (brightness, _("Brightness"), 0.0)
    description (_("Photoshop's Brightness, -150 to +150. In the legacy mode "
                   "the value is clamped to ±100, exactly like Photoshop"))
    value_range (-150.0, 150.0)
    ui_range    (-150.0, 150.0)
    ui_steps    (1.0, 5.0)

property_double (contrast, _("Contrast"), 0.0)
    description (_("Photoshop's Contrast, -50 to +100. The pivot is 89/255, "
                   "not middle grey — that is what the measurement shows"))
    value_range (-50.0, 100.0)
    ui_range    (-50.0, 100.0)
    ui_steps    (1.0, 5.0)

property_boolean (legacy, _("Use Legacy"), FALSE)
    description (_("The pre-CS3 behaviour (Photoshop's \"Use Legacy\" checkbox): "
                   "brightness is a plain offset with hard clipping and the "
                   "contrast pivot sits at 89. Leave off for the modern curve"))

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_brightness_contrast_ps
#define GEGL_OP_C_SOURCE lb-brightness-contrast.c

#include "gegl-op.h"
#include "bc-tables.h"

/* 亮度与对比度对整个图像是常量，所以整条复合曲线在 prepare() 里折成一张
 * 256 项的 LUT；process() 每个通道只剩一次查表 + 一次线性插值。
 * Both parameters are image-wide constants, so the composite curve is folded
 * into a 256-entry LUT in prepare(); the process loop is left with one lookup
 * and one lerp per channel. */
typedef struct
{
  gboolean identity;
  gfloat   lut[256];        /* 输入 0…255（sRGB 编码刻度）→ 输出 0…255 */
} BcParams;

static inline gfloat
clamp255 (gfloat v)
{
  return v < 0.0f ? 0.0f : (v > 255.0f ? 255.0f : v);
}

/* 一条 255 点曲线在任意 x 处取值（x 可以是小数：中间步骤的输出要再进下一张表）
 * One 255-point curve sampled at an arbitrary x; x can be fractional because
 * the output of the brightness stage feeds the contrast stage. */
static inline gfloat
row_at (const unsigned char *row,
        gfloat               x)
{
  gint   i;
  gfloat f;

  if (x <= 0.0f)
    return (gfloat) row[0];
  if (x >= (gfloat) (BC_NX - 1))
    return (gfloat) row[BC_NX - 1];

  i = (gint) x;
  f = x - (gfloat) i;

  return (gfloat) row[i] + ((gfloat) row[i + 1] - (gfloat) row[i]) * f;
}

/* 在整族曲线里按参数 v 线性插值，再在 x 方向线性插值
 * Bilinear: interpolate between the two neighbouring parameter rows, then
 * along x inside each row. */
static gfloat
family_at (const unsigned char (*tab)[BC_NX],
           gint                     n_levels,
           gint                     first,
           gint                     step,
           gfloat                   v,
           gfloat                   x)
{
  gfloat t, a;
  gint   i0, i1;

  t = (v - (gfloat) first) / (gfloat) step;

  if (t <= 0.0f)
    return row_at (tab[0], x);
  if (t >= (gfloat) (n_levels - 1))
    return row_at (tab[n_levels - 1], x);

  i0 = (gint) t;
  i1 = i0 + 1;
  t -= (gfloat) i0;

  a = row_at (tab[i0], x);

  if (t == 0.0f)
    return a;

  return a + (row_at (tab[i1], x) - a) * t;
}

/* ---------------- 新版 ---------------- */
static gfloat
modern_at (gfloat x,
           gfloat b,
           gfloat c)
{
  /* 纯白保护：实测 254 会照曲线走，255 却原样保留
   * Pure-white protection: measured 254 follows the curve, 255 does not. */
  if (x >= 255.0f)
    return 255.0f;
  if (x <= 0.0f)
    return 0.0f;

  if (b != 0.0f)
    x = family_at (bc_b_table, BC_B_LEVELS, (gint) bc_b_first, BC_B_STEP, b, x);
  if (c != 0.0f)
    x = family_at (bc_c_table, BC_C_LEVELS, (gint) bc_c_first, BC_C_STEP, c, x);

  return clamp255 (x);
}

/* ---------------- 旧版 ---------------- */
static gfloat
legacy_at (gfloat x,
           gfloat b,
           gfloat c)
{
  gfloat bb;

  if (b > BC_B_CLAMP)  b = BC_B_CLAMP;
  if (b < -BC_B_CLAMP) b = -BC_B_CLAMP;
  bb = b;

  if (c >= 100.0f)          /* K 发散：PS 在 c=100 就是纯黑白两段 */
    return ((x + bb) > BC_PIVOT) ? 255.0f : 0.0f;

  if (c > 0.0f)
    /* 先加亮度再缩放：亮度被同一个 K 放大
     * Brightness first, then scale: the offset gets amplified by K too. */
    return clamp255 (BC_PIVOT + (x + bb - BC_PIVOT) / (1.0f - c / 100.0f));

  if (c < 0.0f)
    /* 先缩放再加亮度：亮度不被缩小
     * Scale first, then offset: the offset is not attenuated. */
    return clamp255 (BC_PIVOT + (x - BC_PIVOT) * (1.0f + c / 100.0f) + bb);

  return clamp255 (x + bb);
}

static void
prepare (GeglOperation *operation)
{
  GeglProperties *o = GEGL_PROPERTIES (operation);
  const Babl     *space = gegl_operation_get_source_space (operation, "input");
  BcParams       *p = (BcParams *) o->user_data;
  gfloat          b = (gfloat) o->brightness;
  gfloat          c = (gfloat) o->contrast;
  gint            i;

  /* 感知（非线性）RGB：标定是在 sRGB 编码值上做的，放进线性光会整体跑偏
   * Perceptual (non-linear) RGB: the calibration was done on sRGB-encoded
   * values and would drift in linear light. */
  if (! space)
    space = babl_space ("sRGB");

  if (! p)
    {
      p = g_slice_new0 (BcParams);
      o->user_data = p;
    }

  p->identity = (fabsf (b) < 1e-3f && fabsf (c) < 1e-3f);

  if (! p->identity)
    {
      for (i = 0; i < 256; i++)
        {
          gfloat x = (gfloat) i;

          p->lut[i] = o->legacy
                      ? legacy_at (x, b, c)
                      : modern_at (x, b, c);
        }
    }

  gegl_operation_set_format (operation, "input",
                             babl_format_with_space ("R~G~B~A float", space));
  gegl_operation_set_format (operation, "output",
                             babl_format_with_space ("R~G~B~A float", space));
}

static void
finalize (GObject *object)
{
  GeglProperties *o = GEGL_PROPERTIES (object);

  if (o->user_data)
    {
      g_slice_free (BcParams, o->user_data);
      o->user_data = NULL;
    }

  G_OBJECT_CLASS (gegl_op_parent_class)->finalize (object);
}

static gboolean
process (GeglOperation       *operation,
         void                *in_buf,
         void                *out_buf,
         glong                n_pixels,
         const GeglRectangle *roi,
         gint                 level)
{
  GeglProperties    *o = GEGL_PROPERTIES (operation);
  const BcParams    *p = (const BcParams *) o->user_data;
  const gfloat * GEGL_ALIGNED in  = in_buf;
  gfloat       * GEGL_ALIGNED out = out_buf;

  g_assert (p != NULL);

  /* 格式在 prepare() 里固定为 R~G~B~A float，步长恒为 4，不按源格式分支
   * prepare() pins R~G~B~A float, so the stride is always 4. */
  if (p->identity)
    {
      memcpy (out, in, sizeof (gfloat) * 4 * (gsize) n_pixels);
      return TRUE;
    }

  while (n_pixels--)
    {
      gint ch;

      for (ch = 0; ch < 3; ch++)
        {
          gfloat v = in[ch] * 255.0f;
          gfloat r;

          if (v <= 0.0f)
            r = p->lut[0];
          else if (v >= 255.0f)
            r = p->lut[255];
          else
            {
              gint   i = (gint) v;
              gfloat f = v - (gfloat) i;

              r = p->lut[i] + (p->lut[i + 1] - p->lut[i]) * f;
            }

          out[ch] = r * (1.0f / 255.0f);
        }

      out[3] = in[3];
      in  += 4;
      out += 4;
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass            *oc = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointFilterClass *cc = GEGL_OPERATION_POINT_FILTER_CLASS (klass);
  GObjectClass                  *gc = G_OBJECT_CLASS (klass);

  oc->prepare = prepare;
  cc->process = process;
  gc->finalize = finalize;

  gegl_operation_class_set_keys (oc,
    "name",            "lb:brightness-contrast-ps",
    "title",           _("Brightness/Contrast (Photoshop)"),
    "categories",      "color:tonemap",
    "description",     _("Photoshop's Brightness/Contrast, both the modern "
                         "curve and the legacy behaviour (offset + clip, "
                         "contrast about 89/255), matched by measurement"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Brightness/Contrast PS"),
    NULL);
}

#endif
