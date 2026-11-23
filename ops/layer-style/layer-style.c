/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:layer-style
 * menu       Layer Style (live)
 * where      GIMP 里在 SuperMrWang → Layer 下（同一个子菜单里还有 Python 版那个
 *            破坏性的「图层样式…」，两个入口并排）
 * purpose    Photoshop 图层样式的**非破坏**版本。参数挂在滤镜栈上，改一个滑杆
 *            只是让这条滤镜重新算一遍；原像素一个字节都没动过，随时可以整体
 *            关掉或删掉。
 *            A non-destructive take on Photoshop layer styles: the parameters
 *            live on the filter, so nudging a slider only re-runs the filter.
 *            The pixels themselves are never written to; switch the filter off
 *            or throw it away at any time.
 * type       GeglOperationFilter（整块区域 + 按最大 size 向外扩的邻域）
 * why C     GIMP 3 的非破坏编辑只认 GEGL 算子：拖动条能把这条滤镜的参数存进
 *            XCF，重新打开还能拖回来。Python 插件只能读写像素、外加自己造图层，
 *            那是破坏性的（这也是为什么同一套样式要留两个版本）。
 *            GIMP 3's non-destructive editing only understands GEGL ops: the
 *            filter's properties are saved in the XCF and can be re-edited
 *            later. A Python plug-in can only read/write pixels and invent
 *            layers, which is destructive — hence two versions of the same
 *            style set are shipped.
 * algorithm  源的 alpha 决定一切：先按 alpha 生成「投影 / 外发光」两个下层，
 *            再把内容叠上去，最后在内侧按 alpha 刷「内阴影 / 内发光 / 三种
 *            叠加 / 光泽 / 斜面」两片，描边单独 over。
 *            Everything is driven by the source alpha: the two below-the-layer
 *            effects are generated first, the content goes on top, then the
 *            inner effects paint inside the alpha, and the stroke composites
 *            last. Blending is done in sRGB values like Photoshop does, not in
 *            linear light.
 * reference  plugin/_shared/layer_style.py（同一套公式的 numpy 版，逐条对齐）
 *            the numpy twin, formula by formula
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */

#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>

#ifdef GEGL_PROPERTIES

/* ---- 混合模式 / blend modes -------------------------------------------- */
/* 顺序与 numpy 版一致，方便两边对拍 / same order as the numpy twin */
enum_start (ls_blend_modes)
  enum_value (LS_BLEND_NORMAL,        "normal",        "Normal")
  enum_value (LS_BLEND_DARKEN,        "darken",        "Darken")
  enum_value (LS_BLEND_MULTIPLY,      "multiply",      "Multiply")
  enum_value (LS_BLEND_COLORBURN,     "colorburn",     "Color burn")
  enum_value (LS_BLEND_LINEARBURN,    "linearburn",    "Linear burn")
  enum_value (LS_BLEND_LIGHTEN,       "lighten",       "Lighten")
  enum_value (LS_BLEND_SCREEN,        "screen",        "Screen")
  enum_value (LS_BLEND_COLORDODGE,    "colordodge",    "Color dodge")
  enum_value (LS_BLEND_LINEARDODGE,   "lineardodge",   "Linear dodge (add)")
  enum_value (LS_BLEND_OVERLAY,       "overlay",       "Overlay")
  enum_value (LS_BLEND_SOFTLIGHT,     "softlight",     "Soft light")
  enum_value (LS_BLEND_HARDLIGHT,     "hardlight",     "Hard light")
  enum_value (LS_BLEND_VIVIDLIGHT,    "vividlight",    "Vivid light")
  enum_value (LS_BLEND_PINLIGHT,      "pinlight",      "Pin light")
  enum_value (LS_BLEND_LINEARLIGHT,   "linearlight",   "Linear light")
  enum_value (LS_BLEND_HARDMIX,       "hardmix",       "Hard mix")
  enum_value (LS_BLEND_DIFFERENCE,    "difference",    "Difference")
  enum_value (LS_BLEND_EXCLUSION,     "exclusion",     "Exclusion")
  enum_value (LS_BLEND_SUBTRACT,      "subtract",      "Subtract")
  enum_value (LS_BLEND_DIVIDE,        "divide",        "Divide")
  enum_value (LS_BLEND_HUE,           "hue",           "Hue")
  enum_value (LS_BLEND_SATURATION,    "saturation",    "Saturation")
  enum_value (LS_BLEND_COLOR,         "color",         "Color")
  enum_value (LS_BLEND_LUMINOSITY,    "luminosity",    "Luminosity")
  enum_value (LS_BLEND_DARKERCOLOR,   "darkercolor",   "Darker color")
  enum_value (LS_BLEND_LIGHTERCOLOR,  "lightercolor",  "Lighter color")
enum_end (LsBlendModes)

/* ---- 等高线 / contours -------------------------------------------------- */
enum_start (ls_contours)
  enum_value (LS_CONTOUR_LINEAR,          "linear",          "Linear")
  enum_value (LS_CONTOUR_CONE,            "cone",            "Cone")
  enum_value (LS_CONTOUR_CONE_INVERTED,   "cone-inverted",   "Cone inverted")
  enum_value (LS_CONTOUR_GAUSS,           "gauss",           "Gaussian")
  enum_value (LS_CONTOUR_RING,            "ring",            "Ring")
  enum_value (LS_CONTOUR_RING_DOUBLE,     "ring-double",     "Ring double")
  enum_value (LS_CONTOUR_HOLLOW,          "hollow",          "Hollow")
  enum_value (LS_CONTOUR_ROLLING,         "rolling-slope",   "Rolling slope")
  enum_value (LS_CONTOUR_SAWTOOTH,        "sawtooth",        "Sawtooth")
  enum_value (LS_CONTOUR_SAWTOOTH_DOUBLE, "sawtooth-double", "Sawtooth double")
  enum_value (LS_CONTOUR_NOTCHED,         "notched",         "Notched")
  enum_value (LS_CONTOUR_HALF_ROUND,      "half-round",      "Half round")
enum_end (LsContours)

/* ---- 斜面样式 / bevel styles ------------------------------------------- */
enum_start (ls_bevel_styles)
  enum_value (LS_BEVEL_INNER,  "inner",  "Inner bevel")
  enum_value (LS_BEVEL_OUTER,  "outer",  "Outer bevel")
  enum_value (LS_BEVEL_EMBOSS, "emboss", "Emboss")
  enum_value (LS_BEVEL_PILLOW, "pillow", "Pillow emboss")
  enum_value (LS_BEVEL_STROKE, "stroke", "Stroke emboss")
enum_end (LsBevelStyles)

enum_start (ls_bevel_methods)
  enum_value (LS_METHOD_SMOOTH,     "smooth",      "Smooth")
  enum_value (LS_METHOD_CHISEL_HARD, "chisel-hard", "Chisel hard")
  enum_value (LS_METHOD_CHISEL_SOFT, "chisel-soft", "Chisel soft")
enum_end (LsBevelMethods)

enum_start (ls_directions)
  enum_value (LS_DIR_UP,   "up",   "Up")
  enum_value (LS_DIR_DOWN, "down", "Down")
enum_end (LsDirections)

/* ---- 渐变样式 / gradient styles ---------------------------------------- */
enum_start (ls_grad_styles)
  enum_value (LS_GRAD_LINEAR,    "linear",    "Linear")
  enum_value (LS_GRAD_RADIAL,    "radial",    "Radial")
  enum_value (LS_GRAD_ANGLE,     "angle",     "Angle")
  enum_value (LS_GRAD_REFLECTED, "reflected", "Reflected")
  enum_value (LS_GRAD_DIAMOND,   "diamond",   "Diamond")
enum_end (LsGradStyles)

/* ---- 描边位置 / stroke positions --------------------------------------- */
enum_start (ls_stroke_pos)
  enum_value (LS_STROKE_OUTSIDE, "outside", "Outside")
  enum_value (LS_STROKE_INSIDE,  "inside",  "Inside")
  enum_value (LS_STROKE_CENTER,  "center",  "Center")
enum_end (LsStrokePos)

enum_start (ls_glow_sources)
  enum_value (LS_GLOW_EDGE,   "edge",   "Edge")
  enum_value (LS_GLOW_CENTER, "center", "Center")
enum_end (LsGlowSources)

/* ---- 图案类型 / procedural patterns ------------------------------------ */
/* GEGL 算子拿不到 GIMP 的图案库（那要 GimpContext），所以这里给几何图案：
 * 颜色、周期、旋转都是参数，能覆盖「网点 / 条纹 / 棋盘 / 网格」这类常见叠加。
 * A GEGL op cannot reach GIMP's pattern library (that needs a GimpContext),
 * so the patterns here are generated: colour, period and rotation are all
 * parameters, which covers the usual dots / stripes / checker / grid cases. */
enum_start (ls_patterns)
  enum_value (LS_PAT_DOTS,     "dots",     "Dots")
  enum_value (LS_PAT_STRIPES,  "stripes",  "Stripes")
  enum_value (LS_PAT_CHECKER,  "checker",  "Checker")
  enum_value (LS_PAT_GRID,     "grid",     "Grid")
  enum_value (LS_PAT_DIAGONAL, "diagonal", "Diagonal stripes")
  enum_value (LS_PAT_RINGS,    "rings",    "Rings")
enum_end (LsPatterns)

/* ---- 全局光 / global light --------------------------------------------- */
property_double (global_angle, _("Global light angle"), 120.0)
  description (_("Photoshop's global light. Effects with Use global light ticked "
                 "follow it; 120° means the light comes from the upper left, "
                 "so a drop shadow falls to the lower right"))
  value_range (0.0, 360.0)
  ui_meta ("unit", "degree")

property_double (global_altitude, _("Global light altitude"), 30.0)
  description (_("Height of the light above the surface, used by the bevel"))
  value_range (0.0, 89.0)
  ui_meta ("unit", "degree")

/* ---- 投影 / drop shadow ------------------------------------------------ */
property_boolean (shadow_on, _("Drop shadow"), TRUE)
property_color (shadow_color, _("  Shadow colour"), "#000000")
  ui_meta ("sensitive", "shadow-on")
property_double (shadow_opacity, _("  Opacity"), 75.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_double (shadow_angle, _("  Angle"), 120.0)
  value_range (0.0, 360.0)
  ui_meta ("unit", "degree")
property_boolean (shadow_global, _("  Use global light"), TRUE)
property_double (shadow_distance, _("  Distance"), 5.0)
  description (_("How far the shadow is offset, in pixels"))
  value_range (0.0, 300.0)
  ui_meta ("unit", "pixel-distance")
property_double (shadow_spread, _("  Spread"), 0.0)
  description (_("Tightens the shadow after the blur: 0 is a soft edge, 100 is "
                 "a hard one. Photoshop applies spread after the blur for the "
                 "same reason — before it, the blur just softens it again"))
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_double (shadow_size, _("  Size"), 5.0)
  value_range (0.0, 250.0)
  ui_meta ("unit", "pixel-distance")
property_enum (shadow_contour, _("  Contour"), LsContours, ls_contours,
               LS_CONTOUR_LINEAR)

/* ---- 外发光 / outer glow ----------------------------------------------- */
property_boolean (glow_on, _("Outer glow"), FALSE)
property_color (glow_color, _("  Glow colour"), "#fdfa87")
  ui_meta ("sensitive", "glow-on")
property_double (glow_opacity, _("  Opacity"), 75.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_double (glow_size, _("  Size"), 8.0)
  value_range (0.0, 250.0)
  ui_meta ("unit", "pixel-distance")
property_double (glow_spread, _("  Spread"), 0.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_double (glow_range, _("  Range"), 50.0)
  description (_("How much of the glow's alpha survives: a low range boosts "
                 "the glow, 100 keeps it as it is"))
  value_range (1.0, 100.0)
  ui_meta ("unit", "percent")
property_enum (glow_contour, _("  Contour"), LsContours, ls_contours,
               LS_CONTOUR_LINEAR)

/* ---- 内阴影 / inner shadow --------------------------------------------- */
property_boolean (ishadow_on, _("Inner shadow"), FALSE)
property_color (ishadow_color, _("  Inner shadow colour"), "#000000")
  ui_meta ("sensitive", "ishadow-on")
property_double (ishadow_opacity, _("  Opacity"), 75.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_double (ishadow_angle, _("  Angle"), 120.0)
  value_range (0.0, 360.0)
  ui_meta ("unit", "degree")
property_boolean (ishadow_global, _("  Use global light"), TRUE)
property_double (ishadow_distance, _("  Distance"), 5.0)
  value_range (0.0, 300.0)
  ui_meta ("unit", "pixel-distance")
property_double (ishadow_choke, _("  Choke"), 0.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_double (ishadow_size, _("  Size"), 5.0)
  value_range (0.0, 250.0)
  ui_meta ("unit", "pixel-distance")
property_enum (ishadow_contour, _("  Contour"), LsContours, ls_contours,
               LS_CONTOUR_LINEAR)

/* ---- 内发光 / inner glow ----------------------------------------------- */
property_boolean (iglow_on, _("Inner glow"), FALSE)
property_color (iglow_color, _("  Inner glow colour"), "#fdfa87")
  ui_meta ("sensitive", "iglow-on")
property_double (iglow_opacity, _("  Opacity"), 75.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_enum (iglow_source, _("  Source"), LsGlowSources, ls_glow_sources,
               LS_GLOW_EDGE)
property_double (iglow_choke, _("  Choke"), 0.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_double (iglow_size, _("  Size"), 8.0)
  value_range (0.0, 250.0)
  ui_meta ("unit", "pixel-distance")
property_double (iglow_range, _("  Range"), 50.0)
  value_range (1.0, 100.0)
  ui_meta ("unit", "percent")
property_enum (iglow_contour, _("  Contour"), LsContours, ls_contours,
               LS_CONTOUR_LINEAR)

/* ---- 斜面和浮雕 / bevel and emboss ------------------------------------- */
property_boolean (bevel_on, _("Bevel and emboss"), FALSE)
property_enum (bevel_style, _("  Style"), LsBevelStyles, ls_bevel_styles,
               LS_BEVEL_INNER)
  ui_meta ("sensitive", "bevel-on")
property_enum (bevel_method, _("  Technique"), LsBevelMethods, ls_bevel_methods,
               LS_METHOD_SMOOTH)
  ui_meta ("sensitive", "bevel-on")
property_double (bevel_depth, _("  Depth"), 100.0)
  value_range (1.0, 1000.0)
  ui_meta ("unit", "percent")
  ui_meta ("sensitive", "bevel-on")
property_enum (bevel_direction, _("  Direction"), LsDirections, ls_directions,
               LS_DIR_UP)
  ui_meta ("sensitive", "bevel-on")
property_double (bevel_size, _("  Size"), 5.0)
  value_range (1.0, 250.0)
  ui_meta ("unit", "pixel-distance")
  ui_meta ("sensitive", "bevel-on")
property_double (bevel_soften, _("  Soften"), 0.0)
  value_range (0.0, 16.0)
  ui_meta ("unit", "pixel-distance")
  ui_meta ("sensitive", "bevel-on")
property_double (bevel_angle, _("  Angle"), 120.0)
  value_range (0.0, 360.0)
  ui_meta ("unit", "degree")
  ui_meta ("sensitive", "bevel-on")
property_boolean (bevel_global, _("  Use global light"), TRUE)
  ui_meta ("sensitive", "bevel-on")
property_double (bevel_altitude, _("  Altitude"), 30.0)
  value_range (0.0, 89.0)
  ui_meta ("unit", "degree")
  ui_meta ("sensitive", "bevel-on")
property_enum (bevel_highlight_mode, _("  Highlight mode"), LsBlendModes,
               ls_blend_modes, LS_BLEND_SCREEN)
  ui_meta ("sensitive", "bevel-on")
property_color (bevel_highlight_color, _("  Highlight colour"), "#ffffff")
  ui_meta ("sensitive", "bevel-on")
property_double (bevel_highlight_opacity, _("  Highlight opacity"), 75.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
  ui_meta ("sensitive", "bevel-on")
property_enum (bevel_shadow_mode, _("  Shadow mode"), LsBlendModes,
               ls_blend_modes, LS_BLEND_MULTIPLY)
  ui_meta ("sensitive", "bevel-on")
property_color (bevel_shadow_color, _("  Shadow colour"), "#000000")
  ui_meta ("sensitive", "bevel-on")
property_double (bevel_shadow_opacity, _("  Shadow opacity"), 75.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
  ui_meta ("sensitive", "bevel-on")
property_double (bevel_stroke_size, _("  Stroke size (stroke emboss)"), 3.0)
  value_range (1.0, 50.0)
  ui_meta ("unit", "pixel-distance")
  ui_meta ("sensitive", "bevel-on")

/* ---- 光泽 / satin ------------------------------------------------------ */
property_boolean (satin_on, _("Satin"), FALSE)
property_color (satin_color, _("  Satin colour"), "#000000")
  ui_meta ("sensitive", "satin-on")
property_double (satin_opacity, _("  Opacity"), 50.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_double (satin_angle, _("  Angle"), 19.0)
  value_range (0.0, 360.0)
  ui_meta ("unit", "degree")
property_double (satin_distance, _("  Distance"), 11.0)
  value_range (0.0, 300.0)
  ui_meta ("unit", "pixel-distance")
property_double (satin_size, _("  Size"), 14.0)
  value_range (0.0, 250.0)
  ui_meta ("unit", "pixel-distance")
property_boolean (satin_invert, _("  Invert"), FALSE)
property_enum (satin_mode, _("  Blend mode"), LsBlendModes, ls_blend_modes,
               LS_BLEND_MULTIPLY)

/* ---- 颜色叠加 / colour overlay ----------------------------------------- */
property_boolean (color_on, _("Colour overlay"), FALSE)
property_color (color_color, _("  Colour"), "#ff0000")
  ui_meta ("sensitive", "color-on")
property_double (color_opacity, _("  Opacity"), 100.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_enum (color_mode, _("  Blend mode"), LsBlendModes, ls_blend_modes,
               LS_BLEND_NORMAL)

/* ---- 渐变叠加 / gradient overlay --------------------------------------- */
property_boolean (grad_on, _("Gradient overlay"), FALSE)
property_color (grad_color1, _("  From"), "#000000")
  ui_meta ("sensitive", "grad-on")
property_color (grad_color2, _("  To"), "#ffffff")
  ui_meta ("sensitive", "grad-on")
property_enum (grad_style, _("  Style"), LsGradStyles, ls_grad_styles,
               LS_GRAD_LINEAR)
  ui_meta ("sensitive", "grad-on")
property_double (grad_angle, _("  Angle"), 90.0)
  value_range (0.0, 360.0)
  ui_meta ("unit", "degree")
  ui_meta ("sensitive", "grad-on")
property_double (grad_scale, _("  Scale"), 100.0)
  value_range (10.0, 1000.0)
  ui_meta ("unit", "percent")
  ui_meta ("sensitive", "grad-on")
property_boolean (grad_reverse, _("  Reverse"), FALSE)
  ui_meta ("sensitive", "grad-on")
property_double (grad_opacity, _("  Opacity"), 100.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_enum (grad_mode, _("  Blend mode"), LsBlendModes, ls_blend_modes,
               LS_BLEND_NORMAL)

/* ---- 图案叠加 / pattern overlay ---------------------------------------- */
property_boolean (pattern_on, _("Pattern overlay"), FALSE)
property_enum (pattern_kind, _("  Pattern"), LsPatterns, ls_patterns,
               LS_PAT_DOTS)
  ui_meta ("sensitive", "pattern-on")
property_color (pattern_color1, _("  Colour 1"), "#000000")
  ui_meta ("sensitive", "pattern-on")
property_color (pattern_color2, _("  Colour 2"), "#ffffff")
  ui_meta ("sensitive", "pattern-on")
property_double (pattern_scale, _("  Scale"), 100.0)
  value_range (10.0, 1000.0)
  ui_meta ("unit", "percent")
  ui_meta ("sensitive", "pattern-on")
property_double (pattern_opacity, _("  Opacity"), 100.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_enum (pattern_mode, _("  Blend mode"), LsBlendModes, ls_blend_modes,
               LS_BLEND_NORMAL)

/* ---- 描边 / stroke ----------------------------------------------------- */
property_boolean (stroke_on, _("Stroke"), FALSE)
property_double (stroke_size, _("  Size"), 3.0)
  value_range (1.0, 250.0)
  ui_meta ("unit", "pixel-distance")
  ui_meta ("sensitive", "stroke-on")
property_enum (stroke_position, _("  Position"), LsStrokePos, ls_stroke_pos,
               LS_STROKE_OUTSIDE)
  ui_meta ("sensitive", "stroke-on")
property_color (stroke_color, _("  Colour"), "#ff0000")
  ui_meta ("sensitive", "stroke-on")
property_double (stroke_opacity, _("  Opacity"), 100.0)
  value_range (0.0, 100.0)
  ui_meta ("unit", "percent")
property_enum (stroke_mode, _("  Blend mode"), LsBlendModes, ls_blend_modes,
               LS_BLEND_NORMAL)

#else

#define GEGL_OP_FILTER
/* GType 名不能是 gegl_op_xxx 已占用的名字；这个算子独占 lb_layer_style。 */
#define GEGL_OP_NAME     lb_layer_style
#define GEGL_OP_C_SOURCE layer-style.c

#include "gegl-op.h"

#define LS_INF 1e9f

/* ---- 小工具 / small helpers -------------------------------------------- */

static inline gfloat
ls01 (gfloat v)
{
  return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v);
}

static inline gfloat
ls_mix (gfloat a, gfloat b, gfloat t)
{
  return a + (b - a) * t;
}

/* GeglColor → 三个 sRGB 分量（0..1）
 * GeglColor to three sRGB components */
static void
ls_color (GeglColor *c, gfloat out[3])
{
  gdouble px[4] = { 0.0, 0.0, 0.0, 1.0 };

  if (c)
    gegl_color_get_pixel (c, babl_format ("R'G'B'A double"), px);

  out[0] = (gfloat) px[0];
  out[1] = (gfloat) px[1];
  out[2] = (gfloat) px[2];
}

/* ---- 高斯模糊（三次盒式逼近）/ gaussian by three box passes ------------ */

static void
ls_box_slide (gfloat       *a,
              gint          w,
              gint          h,
              gint          r,
              gboolean      vertical,
              gfloat       *tmp)
{
  const gdouble inv = 1.0 / (2 * r + 1);

  if (r < 1)
    return;

  if (vertical)
    {
      for (gint x = 0; x < w; x++)
        {
          gdouble s = 0.0;

          for (gint k = -r; k <= r; k++)
            s += a[(gsize) CLAMP (k, 0, h - 1) * w + x];

          for (gint y = 0; y < h; y++)
            {
              tmp[(gsize) y * w + x] = (gfloat) (s * inv);
              s -= a[(gsize) CLAMP (y - r, 0, h - 1) * w + x];
              s += a[(gsize) CLAMP (y + r + 1, 0, h - 1) * w + x];
            }
        }
    }
  else
    {
      for (gint y = 0; y < h; y++)
        {
          gdouble s = 0.0;

          for (gint k = -r; k <= r; k++)
            s += a[(gsize) y * w + CLAMP (k, 0, w - 1)];

          for (gint x = 0; x < w; x++)
            {
              tmp[(gsize) y * w + x] = (gfloat) (s * inv);
              s -= a[(gsize) y * w + CLAMP (x - r, 0, w - 1)];
              s += a[(gsize) y * w + CLAMP (x + r + 1, 0, w - 1)];
            }
        }
    }

  memcpy (a, tmp, sizeof (gfloat) * (gsize) w * h);
}

/* sigma → 三个盒式半径：让三次盒式的方差等于 sigma²，和 numpy 版同一套公式，
 * 两边的模糊半径逐像素一致，对拍才有意义。
 * Radii whose combined variance equals sigma squared — the same formula as
 * the numpy twin, so both versions blur by exactly the same amount. */
static void
ls_blur (gfloat *a, gint w, gint h, gdouble sigma)
{
  gint    radii[3];
  gint    n = 0;
  gdouble ideal, m_ideal;
  gint    wl, wu, m;
  gfloat *tmp;

  if (sigma <= 0.01 || w <= 0 || h <= 0)
    return;

  ideal = sqrt ((12.0 * sigma * sigma / 3.0) + 1.0);
  wl = (gint) floor (ideal);
  if (wl % 2 == 0)
    wl--;
  wl = MAX (1, wl);
  wu = wl + 2;
  m_ideal = (12.0 * sigma * sigma - 3.0 * wl * wl - 12.0 * wl - 9.0)
            / (-4.0 * wl - 4.0);
  m = CLAMP ((gint) round (m_ideal), 0, 3);

  for (gint i = 0; i < m; i++)
    radii[n++] = (wl - 1) / 2;
  for (gint i = m; i < 3; i++)
    radii[n++] = (wu - 1) / 2;

  tmp = g_new (gfloat, (gsize) w * h);

  for (gint i = 0; i < n; i++)
    {
      if (radii[i] < 1)
        continue;
      ls_box_slide (a, w, h, radii[i], TRUE, tmp);
      ls_box_slide (a, w, h, radii[i], FALSE, tmp);
    }

  g_free (tmp);
}

/* ---- 精确欧氏距离变换 / exact squared euclidean distance transform ---- */
/* 抛物线包络（Felzenszwalb & Huttenlocher），逐行逐列各一趟，O(w·h)。
 * 用它而不是「模糊阈值」：同一个描边宽度在软边和硬边内容上才一样厚。
 * The parabola-envelope transform, one pass per axis, O(w·h). A blurred
 * threshold would give different stroke widths on soft and hard edges. */

static void
ls_dt1d (const gfloat *f, gint n, gfloat *d, gint *v, gfloat *z)
{
  gint k = 0;

  v[0] = 0;
  z[0] = -LS_INF;
  z[1] = LS_INF;

  for (gint q = 1; q < n; q++)
    {
      gfloat s = ((f[q] + (gfloat) q * q) - (f[v[k]] + (gfloat) v[k] * v[k]))
                 / (2.0f * q - 2.0f * v[k]);

      while (s <= z[k] && k > 0)
        {
          k--;
          s = ((f[q] + (gfloat) q * q) - (f[v[k]] + (gfloat) v[k] * v[k]))
              / (2.0f * q - 2.0f * v[k]);
        }

      k++;
      v[k] = q;
      z[k] = s;
      z[k + 1] = LS_INF;
    }

  k = 0;
  for (gint q = 0; q < n; q++)
    {
      while (z[k + 1] < (gfloat) q)
        k++;
      d[q] = (gfloat) (q - v[k]) * (gfloat) (q - v[k]) + f[v[k]];
    }
}

/* mask 非零处为「源」，返回每个像素到最近源的距离（上限 max_d）
 * Distance from every pixel to the nearest non-zero mask pixel, capped. */
static void
ls_edt (const guint8 *mask, gint w, gint h, gfloat *out, gfloat max_d)
{
  const gint   nmax = MAX (w, h);
  gfloat      *f = g_new (gfloat, nmax);
  gfloat      *d = g_new (gfloat, nmax);
  gint        *v = g_new (gint, nmax);
  gfloat      *z = g_new (gfloat, nmax + 1);

  for (gint y = 0; y < h; y++)
    {
      for (gint x = 0; x < w; x++)
        f[x] = mask[(gsize) y * w + x] ? 0.0f : LS_INF;
      ls_dt1d (f, w, d, v, z);
      for (gint x = 0; x < w; x++)
        out[(gsize) y * w + x] = d[x];
    }

  for (gint x = 0; x < w; x++)
    {
      for (gint y = 0; y < h; y++)
        f[y] = out[(gsize) y * w + x];
      ls_dt1d (f, h, d, v, z);
      for (gint y = 0; y < h; y++)
        {
          gfloat dd = sqrtf (MAX (0.0f, d[y]));
          out[(gsize) y * w + x] = MIN (dd, max_d);
        }
    }

  g_free (f);
  g_free (d);
  g_free (v);
  g_free (z);
}

/* 带符号距离：内容内部为正（到背景的距离），外部为负（到内容的距离）
 * Signed distance: positive inside the shape, negative outside. */
static void
ls_signed_distance (const gfloat *alpha, gint w, gint h, gfloat max_d,
                    gfloat *out)
{
  const gsize n = (gsize) w * h;
  guint8     *m = g_new (guint8, n);
  gfloat     *d = g_new (gfloat, n);
  gboolean    solid = FALSE, empty = FALSE;

  for (gsize i = 0; i < n; i++)
    {
      m[i] = alpha[i] > 0.5f ? 1 : 0;
      if (m[i])
        solid = TRUE;
      else
        empty = TRUE;
    }

  if (!solid)                           /* 全空：处处为负 */
    {
      for (gsize i = 0; i < n; i++)
        out[i] = -max_d;
      g_free (m);
      g_free (d);
      return;
    }

  if (!empty)                           /* 全实心：处处为正 */
    {
      for (gsize i = 0; i < n; i++)
        out[i] = max_d;
      g_free (m);
      g_free (d);
      return;
    }

  ls_edt (m, w, h, d, max_d);           /* 每个像素到最近内容的距离 */
  for (gsize i = 0; i < n; i++)
    m[i] = m[i] ? 0 : 1;                /* 反转：到背景的距离 */
  ls_edt (m, w, h, out, max_d);

  for (gsize i = 0; i < n; i++)
    out[i] = alpha[i] > 0.5f ? out[i] : -d[i];

  g_free (m);
  g_free (d);
}

/* ---- 扩展 / spread ----------------------------------------------------- */
/* 把 50% 等值线钉住、加大斜率：扩展与阻塞都走这一条。
 * Pins the 50% contour and steepens the slope; used by both spread and choke. */
static void
ls_spread (gfloat *a, gsize n, gfloat amount)
{
  gfloat thr, k;

  if (amount <= 0.0f)
    return;

  thr = 0.5f * MIN (1.0f, amount);
  k = 0.5f / MAX (1e-4f, 0.5f - thr);

  for (gsize i = 0; i < n; i++)
    a[i] = ls01 ((a[i] - thr) * k);
}

/* ---- 等高线 / contours ------------------------------------------------- */

static gfloat
ls_contour (LsContours kind, gfloat t)
{
  gfloat v;

  t = ls01 (t);

  switch (kind)
    {
      case LS_CONTOUR_CONE:
        v = 1.0f - fabsf (2.0f * t - 1.0f);
        break;
      case LS_CONTOUR_CONE_INVERTED:
        v = fabsf (2.0f * t - 1.0f);
        break;
      case LS_CONTOUR_GAUSS:
        v = expf (-powf ((t - 0.5f) / 0.22f, 2.0f));
        break;
      case LS_CONTOUR_RING:
        v = 1.0f - fabsf (sinf (t * (gfloat) G_PI * 2.0f));
        break;
      case LS_CONTOUR_RING_DOUBLE:
        v = powf (fabsf (sinf (t * (gfloat) G_PI * 2.0f)), 0.6f);
        break;
      case LS_CONTOUR_HOLLOW:
        v = powf (fabsf (2.0f * t - 1.0f), 2.2f);
        break;
      case LS_CONTOUR_ROLLING:
        v = 0.5f - 0.5f * cosf (t * (gfloat) G_PI * 2.0f);
        break;
      case LS_CONTOUR_SAWTOOTH:
        {
          gfloat u = fmodf (t * 2.0f, 1.0f);
          v = fabsf (u * 2.0f - 1.0f);
        }
        break;
      case LS_CONTOUR_SAWTOOTH_DOUBLE:
        v = fmodf (t * 3.0f, 1.0f);
        break;
      case LS_CONTOUR_NOTCHED:
        v = ls01 (1.0f - fabsf (2.0f * t - 1.0f) * 3.0f);
        break;
      case LS_CONTOUR_HALF_ROUND:
        v = sqrtf (ls01 (1.0f - (t - 1.0f) * (t - 1.0f)));
        break;
      default:
        v = t;
        break;
    }

  /* 两端钉成 0 / 1：LUT 版也是这么收边的，不然轮廓两端会浮起来 */
  if (t <= 0.0f)
    return 0.0f;
  if (t >= 1.0f)
    return 1.0f;

  return ls01 (v);
}

static void
ls_apply_contour (gfloat *a, gsize n, LsContours kind)
{
  if (kind == LS_CONTOUR_LINEAR)
    return;

  for (gsize i = 0; i < n; i++)
    a[i] = ls_contour (kind, a[i]);
}

/* ---- 平移（出界补 0）/ shift, zero outside ---------------------------- */

static void
ls_shift (const gfloat *src, gfloat *dst, gint w, gint h, gint dx, gint dy)
{
  memset (dst, 0, sizeof (gfloat) * (gsize) w * h);

  if (abs (dx) >= w || abs (dy) >= h)
    return;

  gint    sxa = MAX (0, -dx), sxb = MIN (w, w - dx);
  gint    sya = MAX (0, -dy), syb = MIN (h, h - dy);
  gsize   row = (gsize) (sxb - sxa);

  for (gint y = sya; y < syb; y++)
    memcpy (dst + (gsize) (y + dy) * w + (sxa + dx),
            src + (gsize) y * w + sxa,
            sizeof (gfloat) * row);
}

/* ---- 混合模式 / blend modes（逐像素，sRGB 值，和 PS 一致） ------------- */

static inline gfloat
ls_lum3 (const gfloat c[3])
{
  return c[0] * 0.3f + c[1] * 0.59f + c[2] * 0.11f;
}

static void
ls_clip_color (gfloat c[3])
{
  gfloat l = ls_lum3 (c);
  gfloat mn = MIN (c[0], MIN (c[1], c[2]));
  gfloat mx = MAX (c[0], MAX (c[1], c[2]));

  if (mn < 0.0f)
    {
      gfloat d = MAX (l - mn, 1e-6f);
      for (gint i = 0; i < 3; i++)
        c[i] = l + (c[i] - l) * l / d;
    }

  if (mx > 1.0f)
    {
      gfloat d = MAX (mx - l, 1e-6f);
      for (gint i = 0; i < 3; i++)
        c[i] = l + (c[i] - l) * (1.0f - l) / d;
    }

  for (gint i = 0; i < 3; i++)
    c[i] = ls01 (c[i]);
}

static void
ls_set_lum (gfloat c[3], gfloat l)
{
  gfloat d = l - ls_lum3 (c);

  for (gint i = 0; i < 3; i++)
    c[i] += d;

  ls_clip_color (c);
}

static gfloat
ls_sat (const gfloat c[3])
{
  return MAX (c[0], MAX (c[1], c[2])) - MIN (c[0], MIN (c[1], c[2]));
}

static void
ls_set_sat (gfloat c[3], gfloat s)
{
  gfloat mn = MIN (c[0], MIN (c[1], c[2]));
  gfloat rng = MAX (MAX (c[0], MAX (c[1], c[2])) - mn, 1e-6f);

  for (gint i = 0; i < 3; i++)
    c[i] = ls01 (mn + (c[i] - mn) * s / rng);
}

static void
ls_blend (const gfloat cb[3], const gfloat cs[3], LsBlendModes mode,
          gfloat out[3])
{
  switch (mode)
    {
      case LS_BLEND_DARKEN:
        for (gint i = 0; i < 3; i++) out[i] = MIN (cb[i], cs[i]);
        break;
      case LS_BLEND_MULTIPLY:
        for (gint i = 0; i < 3; i++) out[i] = cb[i] * cs[i];
        break;
      case LS_BLEND_COLORBURN:
        for (gint i = 0; i < 3; i++)
          out[i] = cs[i] <= 0.0f ? 0.0f
                   : (cb[i] >= 1.0f ? 1.0f
                      : 1.0f - MIN (1.0f, (1.0f - cb[i]) / MAX (cs[i], 1e-6f)));
        break;
      case LS_BLEND_LINEARBURN:
        for (gint i = 0; i < 3; i++) out[i] = ls01 (cb[i] + cs[i] - 1.0f);
        break;
      case LS_BLEND_LIGHTEN:
        for (gint i = 0; i < 3; i++) out[i] = MAX (cb[i], cs[i]);
        break;
      case LS_BLEND_SCREEN:
        for (gint i = 0; i < 3; i++)
          out[i] = 1.0f - (1.0f - cb[i]) * (1.0f - cs[i]);
        break;
      case LS_BLEND_COLORDODGE:
        for (gint i = 0; i < 3; i++)
          out[i] = cs[i] >= 1.0f ? 1.0f
                   : (cb[i] <= 0.0f ? 0.0f
                      : MIN (1.0f, cb[i] / MAX (1.0f - cs[i], 1e-6f)));
        break;
      case LS_BLEND_LINEARDODGE:
        for (gint i = 0; i < 3; i++) out[i] = ls01 (cb[i] + cs[i]);
        break;
      case LS_BLEND_OVERLAY:
        for (gint i = 0; i < 3; i++)
          out[i] = cb[i] <= 0.5f ? 2.0f * cb[i] * cs[i]
                   : 1.0f - 2.0f * (1.0f - cb[i]) * (1.0f - cs[i]);
        break;
      case LS_BLEND_SOFTLIGHT:
        for (gint i = 0; i < 3; i++)
          {
            gfloat b = cb[i], s = cs[i], d;

            d = b <= 0.25f ? ((16.0f * b - 12.0f) * b + 4.0f) * b
                           : sqrtf (MAX (b, 0.0f));
            out[i] = s <= 0.5f ? b - (1.0f - 2.0f * s) * b * (1.0f - b)
                               : b + (2.0f * s - 1.0f) * (d - b);
          }
        break;
      case LS_BLEND_HARDLIGHT:
        for (gint i = 0; i < 3; i++)
          out[i] = cs[i] <= 0.5f ? 2.0f * cb[i] * cs[i]
                   : 1.0f - 2.0f * (1.0f - cb[i]) * (1.0f - cs[i]);
        break;
      case LS_BLEND_VIVIDLIGHT:
        for (gint i = 0; i < 3; i++)
          out[i] = cs[i] <= 0.5f
                   ? ls01 (1.0f - (1.0f - cb[i]) / MAX (2.0f * cs[i], 1e-6f))
                   : ls01 (cb[i] / MAX (2.0f * (1.0f - cs[i]), 1e-6f));
        break;
      case LS_BLEND_PINLIGHT:
        for (gint i = 0; i < 3; i++)
          out[i] = cb[i] > 2.0f * cs[i] ? 2.0f * cs[i]
                   : (cb[i] < 2.0f * cs[i] - 1.0f ? 2.0f * cs[i] - 1.0f
                                                  : cb[i]);
        break;
      case LS_BLEND_LINEARLIGHT:
        for (gint i = 0; i < 3; i++) out[i] = ls01 (cb[i] + 2.0f * cs[i] - 1.0f);
        break;
      case LS_BLEND_HARDMIX:
        for (gint i = 0; i < 3; i++)
          out[i] = cb[i] + cs[i] >= 1.0f ? 1.0f : 0.0f;
        break;
      case LS_BLEND_DIFFERENCE:
        for (gint i = 0; i < 3; i++) out[i] = fabsf (cb[i] - cs[i]);
        break;
      case LS_BLEND_EXCLUSION:
        for (gint i = 0; i < 3; i++)
          out[i] = cb[i] + cs[i] - 2.0f * cb[i] * cs[i];
        break;
      case LS_BLEND_SUBTRACT:
        for (gint i = 0; i < 3; i++) out[i] = ls01 (cb[i] - cs[i]);
        break;
      case LS_BLEND_DIVIDE:
        for (gint i = 0; i < 3; i++)
          out[i] = ls01 (cb[i] / MAX (cs[i], 1e-4f));
        break;
      case LS_BLEND_HUE:
        memcpy (out, cs, sizeof (gfloat) * 3);
        ls_set_sat (out, ls_sat (cb));
        ls_set_lum (out, ls_lum3 (cb));
        break;
      case LS_BLEND_SATURATION:
        memcpy (out, cb, sizeof (gfloat) * 3);
        ls_set_sat (out, ls_sat (cs));
        ls_set_lum (out, ls_lum3 (cb));
        break;
      case LS_BLEND_COLOR:
        memcpy (out, cs, sizeof (gfloat) * 3);
        ls_set_lum (out, ls_lum3 (cb));
        break;
      case LS_BLEND_LUMINOSITY:
        memcpy (out, cb, sizeof (gfloat) * 3);
        ls_set_lum (out, ls_lum3 (cs));
        break;
      case LS_BLEND_DARKERCOLOR:
        memcpy (out, ls_lum3 (cs) < ls_lum3 (cb) ? cs : cb, sizeof (gfloat) * 3);
        break;
      case LS_BLEND_LIGHTERCOLOR:
        memcpy (out, ls_lum3 (cs) > ls_lum3 (cb) ? cs : cb, sizeof (gfloat) * 3);
        break;
      case LS_BLEND_NORMAL:
      default:
        memcpy (out, cs, sizeof (gfloat) * 3);
        break;
    }
}

/* 在内容内部「刷」一层：只改 rgb、不动 alpha，混合模式照常走
 * Paints inside the content: rgb only, alpha untouched. */
static void
ls_paint (gfloat *acc, const gfloat rgb[3], gfloat mask, LsBlendModes mode)
{
  gfloat cb[3], cs[3], b[3];

  if (mask <= 0.0005f)
    return;

  cb[0] = acc[0];
  cb[1] = acc[1];
  cb[2] = acc[2];
  cs[0] = rgb[0];
  cs[1] = rgb[1];
  cs[2] = rgb[2];
  ls_blend (cb, cs, mode, b);

  for (gint i = 0; i < 3; i++)
    acc[i] = ls01 (ls_mix (acc[i], b[i], mask));
}

/* 整层 over（W3C 公式），用于投影 / 外发光 / 描边
 * Full "over" composite for the effects that live on their own layer. */
static void
ls_over (gfloat *acc, const gfloat rgb[3], gfloat sa, LsBlendModes mode)
{
  gfloat da, outa, cb[3], cs[3], b[3];

  if (sa <= 0.0f)
    return;

  da = acc[3];
  cb[0] = acc[0];
  cb[1] = acc[1];
  cb[2] = acc[2];
  cs[0] = rgb[0];
  cs[1] = rgb[1];
  cs[2] = rgb[2];

  ls_blend (cb, cs, mode, b);

  outa = sa + da * (1.0f - sa);

  if (outa <= 1e-6f)
    {
      acc[3] = 0.0f;
      return;
    }

  for (gint i = 0; i < 3; i++)
    acc[i] = ls01 ((sa * (1.0f - da) * cs[i] + sa * da * b[i]
                    + (1.0f - sa) * da * cb[i]) / outa);

  acc[3] = ls01 (outa);
}

/* ---- 渐变 / gradient --------------------------------------------------- */

static gfloat
ls_grad_t (gfloat x, gfloat y, const gfloat box[4], LsGradStyles style,
           gdouble angle, gdouble scale, gboolean reverse)
{
  gfloat cx = (box[0] + box[2]) * 0.5f;
  gfloat cy = (box[1] + box[3]) * 0.5f;
  gfloat ew = MAX (1.0f, box[2] - box[0]);
  gfloat eh = MAX (1.0f, box[3] - box[1]);
  gfloat sx = (gfloat) MAX (0.01, scale);
  gfloat dx = (x - cx) / (ew * 0.5f * sx);
  gfloat dy = (y - cy) / (eh * 0.5f * sx);
  gdouble a = angle * G_PI / 180.0;
  gfloat ca = (gfloat) cos (a), sa = (gfloat) sin (a);
  gfloat t, u;

  switch (style)
    {
      case LS_GRAD_RADIAL:
        t = sqrtf (dx * dx + dy * dy) * 0.5f;
        break;
      case LS_GRAD_ANGLE:
        t = (gfloat) (atan2 (dy, dx) / (2.0 * G_PI));
        t = t - floorf (t) + 0.5f;
        t = t - floorf (t);
        break;
      case LS_GRAD_REFLECTED:
        u = (dx * ca - dy * sa) * 0.5f;
        t = fabsf (u) * 2.0f;
        break;
      case LS_GRAD_DIAMOND:
        t = (fabsf (dx) + fabsf (dy)) * 0.5f;
        break;
      default:
        u = (dx * ca - dy * sa) * 0.5f;
        t = u + 0.5f;
        break;
    }

  t = ls01 (t);

  return reverse ? 1.0f - t : t;
}

/* ---- 几何图案 / procedural patterns ----------------------------------- */

static void
ls_pattern (LsPatterns kind, gint x, gint y, const gfloat box[4],
            gdouble scale, const gfloat c1[3], const gfloat c2[3],
            gfloat out[3])
{
  gfloat cell = (gfloat) MAX (2.0, 18.0 * MAX (0.1, scale));
  gfloat fx = ((gfloat) (x - (gint) box[0]) / cell);
  gfloat fy = ((gfloat) (y - (gint) box[1]) / cell);
  gfloat u = fx - floorf (fx);
  gfloat v = fy - floorf (fy);
  gboolean on = FALSE;

  switch (kind)
    {
      case LS_PAT_STRIPES:
        on = u < 0.5f;
        break;
      case LS_PAT_CHECKER:
        on = ((gint) floorf (fx) + (gint) floorf (fy)) % 2 == 0;
        break;
      case LS_PAT_GRID:
        on = u < 0.12f || v < 0.12f;
        break;
      case LS_PAT_DIAGONAL:
        {
          gfloat s = u + v;
          on = s - floorf (s) < 0.5f;
        }
        break;
      case LS_PAT_RINGS:
        {
          gfloat dx = (u - 0.5f) * 2.0f, dy = (v - 0.5f) * 2.0f;
          gfloat r = sqrtf (dx * dx + dy * dy);
          on = r > 0.45f && r < 0.8f;
        }
        break;
      case LS_PAT_DOTS:
      default:
        {
          gfloat dx = (u - 0.5f) * 2.0f, dy = (v - 0.5f) * 2.0f;
          on = dx * dx + dy * dy < 0.55f;
        }
        break;
    }

  memcpy (out, on ? c1 : c2, sizeof (gfloat) * 3);
}

/* ---- 光照方向 / light direction --------------------------------------- */

static void
ls_offset (gdouble angle, gboolean use_global, gdouble global_angle,
           gdouble distance, gint *dx, gint *dy)
{
  gdouble a = (use_global ? global_angle : angle) * G_PI / 180.0;

  /* PS 的角度是**光源方向**：120° 表示光从左上来，所以阴影往右下走。
   * 反写这一条，投影就会跑到上面去。 */
  *dx = (gint) lround (-distance * cos (a));
  *dy = (gint) lround (distance * sin (a));
}

/* ---- 内容包围盒 / bounding box of the content -------------------------- */

static void
ls_bbox (const gfloat *alpha, gint w, gint h, gfloat box[4])
{
  gint x0 = w, y0 = h, x1 = -1, y1 = -1;

  for (gint y = 0; y < h; y++)
    for (gint x = 0; x < w; x++)
      if (alpha[(gsize) y * w + x] > 0.002f)
        {
          if (x < x0) x0 = x;
          if (x > x1) x1 = x;
          if (y < y0) y0 = y;
          if (y > y1) y1 = y;
        }

  if (x1 < 0)
    {
      box[0] = 0.0f;
      box[1] = 0.0f;
      box[2] = (gfloat) w;
      box[3] = (gfloat) h;
      return;
    }

  box[0] = (gfloat) x0;
  box[1] = (gfloat) y0;
  box[2] = (gfloat) (x1 + 1);
  box[3] = (gfloat) (y1 + 1);
}

/* ---- 斜面高度场 / bevel height field ---------------------------------- */

static gfloat
ls_profile (gfloat x, gfloat depth)
{
  gfloat k;

  x = ls01 (x);
  k = MAX (0.2f, depth);

  return ls01 (1.0f - powf (1.0f - x, 1.0f + k));
}

/* 返回高度图与生效区域；两者都是 w·h 的单通道
 * Fills hgt and region (both w*h single channel). */
static void
ls_height (GeglProperties *o, const gfloat *alpha, gint w, gint h,
           gfloat *hgt, gfloat *region)
{
  const gsize   n = (gsize) w * h;
  gfloat       *smooth = g_new (gfloat, n);
  gfloat       *inv = g_new (gfloat, n);
  gfloat        size = (gfloat) MAX (0.5, o->bevel_size);
  gfloat        depth = (gfloat) o->bevel_depth / 100.0f;

  memcpy (smooth, alpha, sizeof (gfloat) * n);
  ls_blur (smooth, w, h, size * 0.5);

  if (o->bevel_method == LS_METHOD_CHISEL_HARD)
    ls_spread (smooth, n, 0.45f);
  else if (o->bevel_method == LS_METHOD_CHISEL_SOFT)
    ls_spread (smooth, n, 0.2f);

  for (gsize i = 0; i < n; i++)
    {
      gfloat inner = ls01 ((smooth[i] - 0.5f) * 2.0f);   /* 0 边界、1 内部 */
      gfloat outer_r = ls01 ((0.5f - smooth[i]) * 2.0f); /* 外围有多大 */
      gfloat outer_h = ls01 (smooth[i] * 2.0f);          /* 边界最高 */
      gfloat hv, rv;

      switch (o->bevel_style)
        {
          case LS_BEVEL_OUTER:
            hv = ls_profile (outer_h, depth);
            rv = outer_r;
            break;
          case LS_BEVEL_EMBOSS:
            hv = ls_profile (inner, depth) * 0.5f
                 + ls_profile (outer_h, depth) * 0.5f;
            rv = MAX (alpha[i], outer_r);
            break;
          case LS_BEVEL_PILLOW:
            /* 枕状 = 内斜面反过来：内部平台低、边界高，看起来是压进去的 */
            hv = 1.0f - ls_profile (inner, depth);
            rv = alpha[i];
            break;
          default:
            hv = ls_profile (inner, depth);
            rv = alpha[i];
            break;
        }

      hgt[i] = hv;
      region[i] = rv;
    }

  if (o->bevel_style == LS_BEVEL_STROKE)
    {
      gfloat sw = (gfloat) MAX (0.5, o->bevel_stroke_size);
      gfloat *sd = g_new (gfloat, n);

      ls_signed_distance (alpha, w, h, sw + 2.0f, sd);
      for (gsize i = 0; i < n; i++)
        {
          hgt[i] = ls_profile (ls01 (fabsf (sd[i]) / sw), depth);
          region[i] = ls01 (sw - fabsf (sd[i]) + 0.5f);
        }
      g_free (sd);
    }

  if (o->bevel_soften > 0.0)
    ls_blur (hgt, w, h, o->bevel_soften * 0.5);

  if (o->bevel_direction == LS_DIR_DOWN)
    for (gsize i = 0; i < n; i++)
      hgt[i] = 1.0f - hgt[i];

  g_free (smooth);
  g_free (inv);
}

/* ---- 主渲染 / the actual style render --------------------------------- */

static gfloat *
ls_render (GeglProperties *o, const gfloat *src, gint w, gint h,
           gfloat gx, gfloat gy, const gfloat box_in[4])
{
  const gsize  n = (gsize) w * h;
  gfloat      *acc = g_new0 (gfloat, n * 4);
  gfloat      *alpha = g_new (gfloat, n);
  gfloat       box[4];
  gfloat       c[3];

  for (gsize i = 0; i < n; i++)
    alpha[i] = src[i * 4 + 3];

  /* 渐变与图案用**整张图**的包围盒，不是本块的：tile 是分块调用的，用块内
   * 坐标算，每块各跑一遍渐变，接缝处就是一条硬边（实测 70 px 一条）。
   * PS 的「与图层对齐」用的也是图层范围，不是内容的最小外接矩形。 */
  memcpy (box, box_in, sizeof (box));

  /* ================= 下层：投影 / 外发光 ================= */
  if (o->shadow_on)
    {
      gfloat *a = g_memdup2 (alpha, sizeof (gfloat) * n);
      gfloat *b = g_new (gfloat, n);
      gint    dx, dy;

      if (o->shadow_size > 0.0)
        ls_blur (a, w, h, o->shadow_size * 0.5);
      ls_spread (a, n, (gfloat) o->shadow_spread / 100.0f);
      ls_apply_contour (a, n, o->shadow_contour);
      ls_offset (o->shadow_angle, o->shadow_global, o->global_angle,
                 o->shadow_distance, &dx, &dy);
      ls_shift (a, b, w, h, dx, dy);
      ls_color (o->shadow_color, c);

      for (gsize i = 0; i < n; i++)
        ls_over (acc + i * 4, c, b[i] * (gfloat) o->shadow_opacity / 100.0f,
                 LS_BLEND_NORMAL);

      g_free (a);
      g_free (b);
    }

  if (o->glow_on)
    {
      gfloat *a = g_memdup2 (alpha, sizeof (gfloat) * n);
      gfloat  rng = (gfloat) MAX (0.01, o->glow_range / 100.0);

      if (o->glow_size > 0.0)
        ls_blur (a, w, h, o->glow_size * 0.5);
      ls_spread (a, n, (gfloat) o->glow_spread / 100.0f);
      ls_apply_contour (a, n, o->glow_contour);
      ls_color (o->glow_color, c);

      for (gsize i = 0; i < n; i++)
        ls_over (acc + i * 4, c,
                 ls01 (a[i] / rng) * (gfloat) o->glow_opacity / 100.0f,
                 LS_BLEND_NORMAL);

      g_free (a);
    }

  /* ================= 内容 ================= */
  /* 必须 over 叠上去，不能直接赋值：赋值会把已经画好的投影/外发光
   * 整块擦掉（alpha 被源的 0 覆盖），投影看起来就是「完全没出现」。 */
  for (gsize i = 0; i < n; i++)
    ls_over (acc + i * 4, src + i * 4, src[i * 4 + 3], LS_BLEND_NORMAL);

  /* ================= 内侧：内阴影 / 内发光 ================= */
  if (o->ishadow_on)
    {
      gfloat *a = g_new (gfloat, n);
      gfloat *b = g_new (gfloat, n);
      gint    dx, dy;

      for (gsize i = 0; i < n; i++)
        a[i] = 1.0f - alpha[i];
      if (o->ishadow_size > 0.0)
        ls_blur (a, w, h, o->ishadow_size * 0.5);
      ls_spread (a, n, (gfloat) o->ishadow_choke / 100.0f);
      ls_apply_contour (a, n, o->ishadow_contour);
      /* 偏移方向和投影一样（右下）：反相的场往右下挪，左上那段「外面的 1」
       * 才会跑进左上内缘 —— 内阴影才落在左上 */
      ls_offset (o->ishadow_angle, o->ishadow_global, o->global_angle,
                 o->ishadow_distance, &dx, &dy);
      ls_shift (a, b, w, h, dx, dy);
      ls_color (o->ishadow_color, c);

      for (gsize i = 0; i < n; i++)
        ls_paint (acc + i * 4, c,
                  ls01 (b[i] * alpha[i]
                        * (gfloat) o->ishadow_opacity / 100.0f),
                  LS_BLEND_MULTIPLY);

      g_free (a);
      g_free (b);
    }

  if (o->iglow_on)
    {
      gfloat *a = g_new (gfloat, n);
      gfloat  rng = (gfloat) MAX (0.01, o->iglow_range / 100.0);

      for (gsize i = 0; i < n; i++)
        a[i] = 1.0f - alpha[i];
      if (o->iglow_size > 0.0)
        ls_blur (a, w, h, o->iglow_size * 0.5);
      ls_spread (a, n, (gfloat) o->iglow_choke / 100.0f);
      ls_apply_contour (a, n, o->iglow_contour);

      ls_color (o->iglow_color, c);

      for (gsize i = 0; i < n; i++)
        {
          gfloat v = o->iglow_source == LS_GLOW_EDGE ? a[i] : 1.0f - a[i];

          v = ls01 (v / rng) * alpha[i]
              * (gfloat) o->iglow_opacity / 100.0f;
          ls_paint (acc + i * 4, c, v, LS_BLEND_SCREEN);
        }

      g_free (a);
    }

  /* ================= 颜色 / 渐变 / 图案叠加 ================= */
  if (o->color_on)
    {
      ls_color (o->color_color, c);
      for (gsize i = 0; i < n; i++)
        ls_paint (acc + i * 4, c,
                  alpha[i] * (gfloat) o->color_opacity / 100.0f,
                  o->color_mode);
    }

  if (o->grad_on)
    {
      gfloat c1[3], c2[3];

      ls_color (o->grad_color1, c1);
      ls_color (o->grad_color2, c2);

      for (gint y = 0; y < h; y++)
        for (gint x = 0; x < w; x++)
          {
            gsize  i = (gsize) y * w + x;
            gfloat t, cs[3];

            if (alpha[i] <= 0.0005f)
              continue;

            t = ls_grad_t (gx + (gfloat) x + 0.5f, gy + (gfloat) y + 0.5f, box,
                           o->grad_style, o->grad_angle,
                           o->grad_scale / 100.0, o->grad_reverse);
            for (gint k = 0; k < 3; k++)
              cs[k] = ls_mix (c1[k], c2[k], t);

            ls_paint (acc + i * 4, cs,
                      alpha[i] * (gfloat) o->grad_opacity / 100.0f,
                      o->grad_mode);
          }
    }

  if (o->pattern_on)
    {
      gfloat c1[3], c2[3];

      ls_color (o->pattern_color1, c1);
      ls_color (o->pattern_color2, c2);

      for (gint y = 0; y < h; y++)
        for (gint x = 0; x < w; x++)
          {
            gsize  i = (gsize) y * w + x;
            gfloat cs[3];

            if (alpha[i] <= 0.0005f)
              continue;

            ls_pattern (o->pattern_kind, (gint) (gx + x), (gint) (gy + y), box,
                        o->pattern_scale / 100.0, c1, c2, cs);
            ls_paint (acc + i * 4, cs,
                      alpha[i] * (gfloat) o->pattern_opacity / 100.0f,
                      o->pattern_mode);
          }
    }

  /* ================= 光泽 / satin ================= */
  if (o->satin_on)
    {
      gfloat *a = g_new (gfloat, n);
      gfloat *sh = g_new (gfloat, n);
      gfloat *b1 = g_new (gfloat, n);
      gfloat *b2 = g_new (gfloat, n);
      gfloat  size = (gfloat) o->satin_size;
      gint    dx, dy;

      for (gsize i = 0; i < n; i++)
        a[i] = 1.0f - alpha[i];

      ls_offset (o->satin_angle, FALSE, o->global_angle, o->satin_distance,
                 &dx, &dy);
      ls_shift (a, sh, w, h, dx, dy);

      memcpy (b1, a, sizeof (gfloat) * n);
      memcpy (b2, sh, sizeof (gfloat) * n);
      if (size > 0.0)
        {
          ls_blur (b1, w, h, size * 0.5);
          ls_blur (b2, w, h, size * 0.5);
        }

      ls_color (o->satin_color, c);

      for (gsize i = 0; i < n; i++)
        {
          gfloat v = ls01 (0.5f + (b1[i] - b2[i]) * 2.0f);
          gfloat m = o->satin_invert ? ls01 ((v - 0.5f) * 2.0f)
                                     : ls01 ((0.5f - v) * 2.0f);

          ls_paint (acc + i * 4, c,
                    m * alpha[i] * (gfloat) o->satin_opacity / 100.0f,
                    o->satin_mode);
        }

      g_free (a);
      g_free (sh);
      g_free (b1);
      g_free (b2);
    }

  /* ================= 斜面和浮雕 ================= */
  if (o->bevel_on)
    {
      gfloat *hgt = g_new (gfloat, n);
      gfloat *region = g_new (gfloat, n);
      gfloat  hi_c[3], lo_c[3];
      gfloat  depth = (gfloat) o->bevel_depth / 100.0f;
      gfloat  k = 1.5f / MAX (0.15f, depth);
      gfloat  gain = 6.0f / MAX (0.2f, depth);
      gdouble ang = (o->bevel_global ? o->global_angle : o->bevel_angle)
                    * G_PI / 180.0;
      gdouble alt = CLAMP (o->bevel_altitude, 0.0, 89.0) * G_PI / 180.0;
      gfloat  lx = (gfloat) (cos (alt) * cos (ang));
      gfloat  ly = (gfloat) (-cos (alt) * sin (ang));
      gfloat  lz = (gfloat) sin (alt);
      gfloat  hi_op = (gfloat) o->bevel_highlight_opacity / 100.0f;
      gfloat  lo_op = (gfloat) o->bevel_shadow_opacity / 100.0f;

      ls_height (o, alpha, w, h, hgt, region);
      ls_color (o->bevel_highlight_color, hi_c);
      ls_color (o->bevel_shadow_color, lo_c);

      for (gint y = 0; y < h; y++)
        for (gint x = 0; x < w; x++)
          {
            gsize  i = (gsize) y * w + x;
            gint   xm = MAX (0, x - 1), xp = MIN (w - 1, x + 1);
            gint   ym = MAX (0, y - 1), yp = MIN (h - 1, y + 1);
            gfloat gxv = (hgt[(gsize) y * w + xp] - hgt[(gsize) y * w + xm])
                         * 0.5f;
            gfloat gyv = (hgt[(gsize) yp * w + x] - hgt[(gsize) ym * w + x])
                         * 0.5f;
            gfloat nx = -gxv * k, ny = -gyv * k, nz = 1.0f;
            gfloat ln = sqrtf (nx * nx + ny * ny + nz * nz);
            gfloat dot, flat = lz;

            nx /= ln;
            ny /= ln;
            nz /= ln;
            dot = nx * lx + ny * ly + nz * lz;

            if (region[i] <= 0.0005f)
              continue;

            ls_paint (acc + i * 4, lo_c,
                      ls01 ((flat - dot) * gain) * region[i] * lo_op,
                      o->bevel_shadow_mode);
            ls_paint (acc + i * 4, hi_c,
                      ls01 ((dot - flat) * gain) * region[i] * hi_op,
                      o->bevel_highlight_mode);
          }

      g_free (hgt);
      g_free (region);
    }

  /* ================= 描边 / stroke ================= */
  if (o->stroke_on)
    {
      gfloat  size = (gfloat) MAX (0.5, o->stroke_size);
      gfloat *sd = g_new (gfloat, n);
      gfloat *band = g_new (gfloat, n);

      ls_signed_distance (alpha, w, h, size + 2.0f, sd);

      for (gsize i = 0; i < n; i++)
        {
          gfloat b;

          switch (o->stroke_position)
            {
              case LS_STROKE_INSIDE:
                b = MIN (size - sd[i], sd[i]);
                break;
              case LS_STROKE_CENTER:
                b = size * 0.5f - fabsf (sd[i]);
                break;
              default:
                b = MIN (sd[i] + size, -sd[i]);
                break;
            }

          band[i] = ls01 (b + 0.5f);
        }

      ls_color (o->stroke_color, c);

      for (gsize i = 0; i < n; i++)
        ls_over (acc + i * 4, c,
                 band[i] * (gfloat) o->stroke_opacity / 100.0f,
                 o->stroke_mode);

      g_free (sd);
      g_free (band);
    }

  g_free (alpha);

  return acc;
}

/* ---- GEGL 接线 / GEGL plumbing --------------------------------------- */

/* 效果最远能影响多少像素：邻居不够就是「边缘被切掉」的一圈
 * How far an effect can reach; without this margin the edges get clipped. */
static gint
ls_margin (GeglProperties *o)
{
  gdouble m = 4.0;

  if (o->shadow_on)
    m = MAX (m, o->shadow_size * 2.0 + fabs (o->shadow_distance) + 2.0);
  if (o->glow_on)
    m = MAX (m, o->glow_size * 2.0 + 2.0);
  if (o->ishadow_on)
    m = MAX (m, o->ishadow_size * 2.0 + fabs (o->ishadow_distance) + 2.0);
  if (o->iglow_on)
    m = MAX (m, o->iglow_size * 2.0 + 2.0);
  if (o->satin_on)
    m = MAX (m, o->satin_size * 2.0 + fabs (o->satin_distance) + 2.0);
  if (o->bevel_on)
    m = MAX (m, o->bevel_size * 2.0 + o->bevel_soften + 4.0);
  if (o->stroke_on)
    m = MAX (m, o->stroke_size + 2.0);

  return (gint) ceil (m);
}

static void
prepare (GeglOperation *operation)
{
  const Babl *space = gegl_operation_get_source_space (operation, "input");
  const Babl *fmt = babl_format_with_space ("R'G'B'A float", space);

  gegl_operation_set_format (operation, "input", fmt);
  gegl_operation_set_format (operation, "output", fmt);
}

/* 效果要读邻居，所以整张输入都可能被用到（结果仍然只写在 roi 里）
 * The effects read neighbours, so the whole input may be touched; only the
 * roi is written back. */
static GeglRectangle
get_required_for_output (GeglOperation       *operation,
                         const gchar         *input_pad,
                         const GeglRectangle *roi)
{
  GeglRectangle *full =
    gegl_operation_source_get_bounding_box (operation, "input");

  return full ? *full : *roi;
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
  GeglRectangle  *full =
    gegl_operation_source_get_bounding_box (operation, "input");
  GeglRectangle   work, roi;
  gint            margin = ls_margin (o);
  gint            stride;
  gfloat         *src, *out;
  gint            ox, oy;

  if (!full || full->width <= 0 || full->height <= 0)
    return TRUE;

  /* 往外扩一圈再算，最后只写回 result */
  work.x = result->x - margin;
  work.y = result->y - margin;
  work.width = result->width + margin * 2;
  work.height = result->height + margin * 2;

  if (!gegl_rectangle_intersect (&work, &work, full))
    return TRUE;

  if (!gegl_rectangle_intersect (&roi, result, full))
    return TRUE;

  stride = (gint) (sizeof (gfloat) * 4 * (gsize) work.width);
  src = g_new0 (gfloat, (gsize) work.width * work.height * 4);

  gegl_buffer_get (input, &work, 1.0, fmt, src, stride, GEGL_ABYSS_NONE);

  {
    gfloat box[4] = { (gfloat) full->x, (gfloat) full->y,
                      (gfloat) (full->x + full->width),
                      (gfloat) (full->y + full->height) };

    out = ls_render (o, src, work.width, work.height,
                     (gfloat) work.x, (gfloat) work.y, box);
  }

  ox = roi.x - work.x;
  oy = roi.y - work.y;

  gegl_buffer_set (output, &roi, level, fmt,
                   out + ((gsize) oy * work.width + ox) * 4, stride);

  g_free (src);
  g_free (out);

  return TRUE;
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
    "name",            "lb:layer-style",
    "title",           _("Layer Style (live)"),
    "description",     _("Photoshop's layer styles as a live filter: drop "
                         "shadow, inner shadow, outer and inner glow, bevel and "
                         "emboss (five styles), satin, colour / gradient / "
                         "pattern overlay and stroke. The style lives on the "
                         "filter, so nothing is baked into the pixels and every "
                         "slider can be reopened later."),
    "categories",      "light",
    "gimp:menu-path",  "<Image>/SuperMrWang/Layer",
    "gimp:menu-label", _("Layer Style (live)…"),
    NULL);
}

#endif
