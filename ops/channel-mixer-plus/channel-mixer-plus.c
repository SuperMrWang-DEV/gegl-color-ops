/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:channel-mixer-plus
 * menu       Channel Mixer Plus
 * purpose    PS 通道混合器：每路输出通道由 RGB 三源加权相加，并带通道偏移
 *            PS Channel Mixer: every output channel is a weighted sum of
 *            R/G/B, plus a constant offset per channel.
 * algorithm  3×3 混合矩阵 + 每通道 offset；monochrome 打开时改用单组系数转灰
 *            A 3x3 mixing matrix plus one offset per channel; with
 *            'monochrome' a single set of coefficients produces grey.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  GEGL 官方 channel-mixer（补 RGB offset、去 preserve luminosity）
 *            GEGL core channel-mixer, with per-channel offsets added and
 *            keep-luminosity dropped
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>

#ifdef GEGL_PROPERTIES

/* 新增：PS 单色开关
 * New: PS Monochrome toggle */
property_boolean (monochrome, _("Monochrome"), FALSE)
  description(_("Produce grayscale monochrome image (PS style single channel mixer)"))

/* 单色共用的混合系数（仅 monochrome=TRUE 时生效）
 * Monochrome shared mixing coefficients (only used when monochrome=TRUE) */
property_double (mono_r, _("Red"), 0.33)
  description(_("Red channel contribution for monochrome output"))
  value_range (-2.0, 2.0)

property_double (mono_g, _("Green"), 0.33)
  description(_("Green channel contribution for monochrome output"))
  value_range (-2.0, 2.0)

property_double (mono_b, _("Blue"), 0.34)
  description(_("Blue channel contribution for monochrome output"))
  value_range (-2.0, 2.0)

property_double (mono_offset, _("Monochrome Offset"), 0.0)
  description(_("Constant offset added to monochrome gray value"))
  value_range (-1.0, 1.0)

/* 红色输出通道（仅普通彩色模式）
 * Red output channel (normal colour mode only) */
property_double (rr_gain, _("Red in Red channel"), 1.0)
  description(_("Set the red amount for the red channel"))
  value_range (-2.0, 2.0)

property_double (rg_gain, _("Green in Red channel"), 0.0)
  description(_("Set the green amount for the red channel"))
  value_range (-2.0, 2.0)

property_double (rb_gain, _("Blue in Red channel"), 0.0)
  description(_("Set the blue amount for the red channel"))
  value_range (-2.0, 2.0)

property_double (r_offset, _("Red Offset"), 0.0)
  description(_("Constant offset added to red output channel"))
  value_range (-1.0, 1.0)

/* 绿色输出通道（仅普通彩色模式）
 * Green output channel (normal colour mode only) */
property_double (gr_gain, _("Red in Green channel"), 0.0)
  description(_("Set the red amount for the green channel"))
  value_range (-2.0, 2.0)

property_double (gg_gain, _("Green for Green channel"), 1.0)
  description(_("Set the green amount for the green channel"))
  value_range (-2.0, 2.0)

property_double (gb_gain, _("Blue in Green channel"), 0.0)
  description(_("Set the blue amount for the green channel"))
  value_range (-2.0, 2.0)

property_double (g_offset, _("Green Offset"), 0.0)
  description(_("Constant offset added to green output channel"))
  value_range (-1.0, 1.0)

/* 蓝色输出通道（仅普通彩色模式）
 * Blue output channel (normal colour mode only) */
property_double (br_gain, _("Red in Blue channel"), 0.0)
  description(_("Set the red amount for the blue channel"))
  value_range (-2.0, 2.0)

property_double (bg_gain, _("Green in Blue channel"), 0.0)
  description(_("Set the green amount for the blue channel"))
  value_range (-2.0, 2.0)

property_double (bb_gain, _("Blue in Blue channel"), 1.0)
  description(_("Set the blue amount for the blue channel"))
  value_range (-2.0, 2.0)

property_double (b_offset, _("Blue Offset"), 0.0)
  description(_("Constant offset added to blue output channel"))
  value_range (-1.0, 1.0)

#else

#define GEGL_OP_POINT_FILTER
#define GEGL_OP_NAME     lb_channel_mixer_plus
#define GEGL_OP_C_SOURCE channel-mixer-plus.c

#include "gegl-op.h"

typedef struct
{
  gdouble       red_gain;
  gdouble       green_gain;
  gdouble       blue_gain;
  gdouble       offset;
} CmChannelType;

typedef struct
{
  CmChannelType  red;
  CmChannelType  green;
  CmChannelType  blue;

  /* 新增的单色参数
   * New monochrome params */
  gboolean monochrome;
  gdouble mono_r;
  gdouble mono_g;
  gdouble mono_b;
  gdouble mono_offset;

  gboolean       has_alpha;
} CmParamsType;

static void prepare (GeglOperation *operation)
{
  const Babl *input_format = gegl_operation_get_source_format (operation, "input");
  /* 感知（非线性）格式：通道增益按 8bit 伽马域标定，线性光下灰阶会整体变亮
   * Perceptual (non-linear) format: the gains are calibrated in the 8-bit
   * gamma domain; in linear light the greys lift noticeably. */
  const Babl *space = gegl_operation_get_source_space (operation, "input");
  GeglProperties *o = GEGL_PROPERTIES (operation);
  CmParamsType *mix;
  const Babl *format;

  if (o->user_data == NULL)
    o->user_data = g_slice_new0 (CmParamsType);

  mix = (CmParamsType*) o->user_data;

  /* 读取单色配置
   * Read the monochrome configuration */
  mix->monochrome = o->monochrome;
  mix->mono_r     = o->mono_r;
  mix->mono_g     = o->mono_g;
  mix->mono_b     = o->mono_b;
  mix->mono_offset= o->mono_offset;

  /* 普通彩色模式的通道增益与偏移
   * Normal colour channel gains and offsets */
  mix->red.red_gain     = o->rr_gain;
  mix->red.green_gain   = o->rg_gain;
  mix->red.blue_gain    = o->rb_gain;
  mix->red.offset       = o->r_offset;

  mix->green.red_gain   = o->gr_gain;
  mix->green.green_gain = o->gg_gain;
  mix->green.blue_gain  = o->gb_gain;
  mix->green.offset     = o->g_offset;

  mix->blue.red_gain    = o->br_gain;
  mix->blue.green_gain  = o->bg_gain;
  mix->blue.blue_gain   = o->bb_gain;
  mix->blue.offset      = o->b_offset;

  if (input_format == NULL || babl_format_has_alpha (input_format))
    {
      mix->has_alpha = TRUE;
      format = babl_format_with_space ("R~G~B~A float", space);
    }
  else
    {
      mix->has_alpha = FALSE;
      /* babl 只有带 alpha 的感知格式 R~G~B~A，无 alpha 图也走它
       * babl only ships the perceptual format with alpha, so use it either way */
      format = babl_format_with_space ("R~G~B~A float", space);
    }

  gegl_operation_set_format (operation, "input", format);
  gegl_operation_set_format (operation, "output", format);
}

static void finalize (GObject *object)
{
  GeglOperation *op = (void*) object;
  GeglProperties *o = GEGL_PROPERTIES (op);

  if (o->user_data)
    {
      g_slice_free (CmParamsType, o->user_data);
      o->user_data = NULL;
    }

  G_OBJECT_CLASS (gegl_op_parent_class)->finalize (object);
}

static inline gfloat
cm_mix_pixel (CmChannelType *ch,
              gfloat         r,
              gfloat         g,
              gfloat         b)
{
  gdouble c = ch->red_gain * r + ch->green_gain * g + ch->blue_gain * b;
  c += ch->offset;
  return (gfloat) c;
}

/* 新增：计算单色灰度值
 * New: compute the monochrome grey value */
static inline gfloat
cm_mono_gray (CmParamsType *mix, gfloat r, gfloat g, gfloat b)
{
  gdouble gray = mix->mono_r * r + mix->mono_g * g + mix->mono_b * b;
  gray += mix->mono_offset;
  return (gfloat) gray;
}

static inline void
cm_process_pixel (CmParamsType  *mix,
                  const gfloat  *s,
                  gfloat        *d)
{
  if (mix->monochrome)
    {
      gfloat gray = cm_mono_gray (mix, s[0], s[1], s[2]);
      /* 令 R=G=B 得到单色灰度图
       * R=G=B produces the monochrome grey image */
      d[0] = gray;
      d[1] = gray;
      d[2] = gray;
    }
  else
    {
      /* 原有的彩色混合逻辑
       * Original colour mixing logic */
      d[0] = cm_mix_pixel (&mix->red,   s[0], s[1], s[2]);
      d[1] = cm_mix_pixel (&mix->green, s[0], s[1], s[2]);
      d[2] = cm_mix_pixel (&mix->blue,  s[0], s[1], s[2]);
    }
}

static gboolean
process (GeglOperation       *op,
         void                *in_buf,
         void                *out_buf,
         glong                samples,
         const GeglRectangle *roi,
         gint                 level)
{
  GeglProperties   *o = GEGL_PROPERTIES (op);
  CmParamsType *mix = (CmParamsType*) o->user_data;

  gfloat       *in, *out;

  g_assert (mix != NULL);

  in = in_buf;
  out = out_buf;

  if (mix->has_alpha)
    {
      while (samples--)
        {
          cm_process_pixel (mix, in, out);
          out[3] = in[3];

          in += 4;
          out += 4;
        }
    }
  else
    {
      while (samples--)
        {
          cm_process_pixel (mix, in, out);
          in += 3;
          out += 3;
        }
    }

  return TRUE;
}

static void
gegl_op_class_init (GeglOpClass *klass)
{
  GeglOperationClass            *oc = GEGL_OPERATION_CLASS (klass);
  GeglOperationPointFilterClass *cc = GEGL_OPERATION_POINT_FILTER_CLASS (klass);

  oc->prepare = prepare;
  cc->process = process;
  G_OBJECT_CLASS (klass)->finalize = finalize;

  gegl_operation_class_set_keys (oc,
    "name",            "lb:channel-mixer-plus",
    "title",           _("Channel Mixer Plus"),
    "description",     _("Mix RGB channels with independent offsets, PS-style monochrome grayscale mode, no luminosity preservation"),
    "gimp:menu-path",  "<Image>/Colors/SuperMrWang",
    "gimp:menu-label", _("Channel Mixer Plus"),
    NULL);
}

#endif