#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · HSV 分量分解 + 曲线 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   在 HSV 空间里调曲线。菜单里是两条，各对应一种模式：

             single   一张数据图（R=S、G=V、B=H/360）三条曲线，compose 一次
                      算完。一层、五条滤镜。
             multi    三张分量层（Hue / Saturation / Value），每层 extract →
                      曲线 → 编码，再用 GIMP 原生的 HSV 分量混合模式叠回去。
                      三层、十条滤镜。

           两者恒等曲线都逐像素还原原图；调哪条曲线就只动那个分量。
           Curve HSV itself, in one of two modes: a single packed data layer
           (single) or three component layers on the native HSV blend modes
           (multi).

 menu      SuperMrWang → Retouch → HSV Split (Curves) · single
           SuperMrWang → Retouch → HSV Split (Curves) · multi
          图层右键 → SuperMrWang → Retouch → 同上两条
          （single 与 multi 是两个独立的过程，不再是对话框里的下拉）

 usage     选中一个栅格图层 → 取 single 或 multi 那条。生成的结构（自上而下）：

            single 模式

              HSV split       组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 1 · HSV S/V/H   正常模式   ← 一条算子链算出完整 HSV 色
                └─ 原图层（不动，可以隐藏）

            multi 模式

              HSV split       组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 3 · Value       模式 = HSV 明度   ← 只替换 V
                ├─ 2 · Saturation  模式 = HSV 饱和度 ← 只替换 S
                ├─ 1 · Hue         模式 = HSV 色相   ← 只替换 H
                └─ 原图层（不动，可以隐藏）

 note      single 的骨架和 HSI 插件一样：三个分量挤进一张数据图，一次算完再还原，
          层数一、滤镜五条、只编码一次，误差最小。

          multi 是旧版结构：每层先抽出灰度、曲完再编码成「携带该分量」的颜色，
          靠混合模式叠回去。代价是三层、十四个滤镜、三次编码三次量化；换来的
          是每层都能单独关掉——把 Hue 层开关一拨，就能只看调过 S/V 的中间结果。
          分量混合模式只在源 alpha=1 时是纯替换，所以三层一律不透明，透明度
          交给组蒙版。

          single 的滤镜栈（图层面板里从上往下读，执行顺序相反）：

             1 · decompose   lb:hsv-dual   原图 → (R=S, G=V, B=H/360)
             2 · S curve     gimp:curves     通道 = R（红）
             3 · V curve     gimp:curves     通道 = G（绿）
             4 · H curve     gimp:curves     通道 = B（蓝）
             5 · compose     lb:hsv-compose   (S,V,H) → 真实颜色

          multi 每层的滤镜栈：

             Hue        1 · extract  gegl:component-extract  component=hue
                        2 · curve    gimp:curves   通道 = 值
                        3 · encode   lb:gray-to-component  mode=hue

             Saturation 同上，extract hsv-s / encode saturation（编码是一条
                        直线 (1, 1−g, 1−g)，曲线采样不引入误差）

             Value      只有 extract hsv-v + curve，不需要编码

           量程：
             S  HSV 饱和度           0…1
             V  HSV 明度（= max）    0…1
             H  色相 / 360           0…1

           实测（GIMP 3.2.8，见 tools/check_hsv_split.py）：
             32 位浮点图，恒等曲线往返：   最大 0.02 码
             8 位图，恒等曲线往返：        ≤ 0.5 码
             隐藏原图层后自己还原：         与可见时同值
             只改 S 曲线时 V、H 的偏差：     < 0.01 码

           注意事项：
           - 三条曲线分别挂在**红 / 绿 / 蓝**通道上：S 在红、V 在绿、H 在蓝。
             在图层属性的滤镜里改曲线时记得选对通道；选「值」会把三条数据
             一起改掉。
           - 色相曲线必须是连续的（两端相等、中间不跳变）。整体旋转色相请用
             lb:hue-saturation；这条曲线适合「压缩 / 拉伸某段色相」。
           - V = 0 的像素（纯黑）没有色相与饱和度，曲线改了也看不出来。
           - 曲线推到头会把结果推出 sRGB 色域，8 位图按 0/1 裁切。
           - single 模式依赖 lb:hsv-dual 与 lb:hsv-compose 两个算子；缺了它们
             就没有等价回退，插件会报错。multi 模式只用 GIMP 自带的
             gegl:component-extract + 分量混合模式，不需要这两个算子（编码那步
             的 lb:gray-to-component 缺失时自动退回三条曲线）。
           - 图层自带的非破坏滤镜不会被复制（new_from_drawable 只取像素）。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject


# 多语言：查自己的域（gegl-color-ops），语言取自 GIMP 界面设置。
# helper 在 plugin/_shared/ 下；装成单文件时退回 GIMP 默认域。
import os as _os
import sys as _sys

_here = _os.path.dirname(_os.path.abspath(__file__))
for _cand in (_os.path.join(_here, '_shared'),
              _os.path.normpath(_os.path.join(_here, '..', '_shared'))):
    if _os.path.isdir(_cand) and _cand not in _sys.path:
        _sys.path.append(_cand)
try:
    from lb_i18n import _          # noqa: F811
except Exception:                  # helper 不在：保持可用，只是不翻译
    def _(message):
        return GLib.dgettext(None, message)


# 精确适配用的两个算子（本仓库 ops/hsv-dual、ops/hsv-compose）
DUAL_OP = "lb:hsv-dual"
COMPOSE_OP = "lb:hsv-compose"


# ---- 曲线 / curves ----------------------------------------------------------
#
# 曲线分两种，写法不一样：
#
#   1. 给人调的曲线（各分量层上那条 2 · xxx curve）——SMOOTH 平滑样条 +
#      三个控制点 (0,0) (128,128) (255,255)。三个抓手，拖一个整条线跟着走。
#      用 FREE 就得铺 256 个采样点，想动某一段得在一堆点里找准，手拖不动。
#
#   2. 机器编码表（LIGHT_ENCODE / HUE_ENCODE / scale 这类）——它们不是给人
#      调的，而是把分量的数值范围搬到 0…255 上（比如 L* 0…100 要铺满灰阶），
#      形状是算出来的，只能用采样点表逼近，所以留 FREE。

# 控制点必须踩在 1/255 的格子上，别写 0.5。
#
# 曲线的 y 只认 0…255 的整数档，x 也是：写 0.5 表示 127.5/255，落在两档之间，
# GIMP 会把它挪到某一侧，于是这条"对角直线"并不真的过对角——恒等状态下能差
# 半档，8 位图上还会把相邻两档并成一级（256 级只剩 217 级）。写成 128/255 或
# 127/255（落在格点上）之后，恒等往返实测 0 码（逐像素完全相等），256 级一级不少，
# 而控制点仍然只有三个，照样拖得动。
IDENTITY_POINTS = ((0.0, 0.0), (128 / 255.0, 128 / 255.0), (1.0, 1.0))


def _point_curve(points):
    """按控制点造一条平滑曲线（SMOOTH）。/ A smooth curve through points."""
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.SMOOTH)
    for x, y in points:
        curve.add_point(float(x), float(y))
    return curve


def _append_curve_points(layer, label, points, channel=None):
    """追加一条可编辑的平滑曲线（少量控制点）。channel=None 即「值」通道。"""
    filt = Gimp.DrawableFilter.new(layer, "gimp:curves", label)
    cfg = filt.get_config()
    cfg.set_property("curve", _point_curve(points))
    cfg.set_property("channel",
                     channel if channel is not None
                     else Gimp.HistogramChannel.VALUE)
    cfg.set_property("trc", Gimp.TRCType.NON_LINEAR)
    filt.update()
    layer.append_filter(filt)
    return filt


# ---- 滤镜栈 / the filter stack ---------------------------------------------

# 下面这个只给机器编码表用：形状是算出来的（分量范围 → 0…255），
# 只能用采样点逼近，所以是 FREE。给人调的曲线走 _append_curve_points。
def _append_curve(layer, label, fn, channel):
    """在图层上追加一条 gimp:curves（通道级一维映射）。

    trc 钉成 NON_LINEAR：曲线在编码值上生效，与分量语义一致。
    Append one channel curve, pinned to encoded (NON_LINEAR) values."""
    filt = Gimp.DrawableFilter.new(layer, "gimp:curves", label)
    cfg = filt.get_config()
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.FREE)
    n = curve.get_n_samples()
    for i in range(n):
        x = i / float(n - 1)
        curve.set_sample(x, min(1.0, max(0.0, fn(x))))
    cfg.set_property("curve", curve)
    cfg.set_property("channel", channel)
    cfg.set_property("trc", Gimp.TRCType.NON_LINEAR)
    filt.update()
    layer.append_filter(filt)
    return filt


def _simple_filter(layer, op, label):
    """挂一个不需要曲线的算子滤镜（lb:hsv-dual / lb:hsv-compose 这类）。"""
    filt = Gimp.DrawableFilter.new(layer, op, label)
    filt.update()
    layer.append_filter(filt)
    return filt


def _require_adapter_ops(layer):
    """确认两个适配算子可用。"""
    missing = []
    for op in (DUAL_OP, COMPOSE_OP):
        try:
            Gimp.DrawableFilter.new(layer, op, "probe")
        except Exception:
            missing.append(op)
    if missing:
        raise RuntimeError(
            _("Required operations are missing: %s. They are essential for exact HSV fitting (all three components must be evaluated in the same data image). Install this repository's GEGL operations hsv-dual / hsv-compose (./install.sh) and restart GIMP.") % ", ".join(missing))


def _link_alpha_mask(image, base, host):
    """把原图层的 alpha 变成整组的蒙版。

    分量层必须不透明（半透明层的混合会按 alpha 做 lerp），透明度交给组蒙版。
    Mask the group with the source alpha; the data layer stays opaque."""
    if host is None:
        return False
    try:
        if not base.has_alpha():
            return False
    except Exception:
        return False

    saved = None
    try:
        if not Gimp.Selection.is_empty(image):
            saved = Gimp.Selection.save(image)
    except Exception:
        saved = None

    try:
        image.select_item(Gimp.ChannelOps.REPLACE, base)
        mask = host.create_mask(Gimp.AddMaskType.SELECTION)
        if mask is None:
            return False
        host.add_mask(mask)
        return True
    except Exception:
        return False
    finally:
        try:
            if saved is not None:
                image.select_item(Gimp.ChannelOps.REPLACE, saved)
                image.remove_channel(saved)
            else:
                Gimp.Selection.none(image)
        except Exception:
            pass


def _item_position(image, item, fallback=0):
    try:
        proc = Gimp.get_pdb().lookup_procedure('gimp-image-get-item-position')
        cfg = proc.create_config()
        cfg.set_property('image', image)
        cfg.set_property('item', item)
        return proc.run(cfg).index(1)
    except Exception:
        return fallback


# ---- multi 模式：分量层 / the component layers ------------------------------
# 每层一条曲线，但曲线的结果必须先「编码」成一张携带该分量的彩色图，混合模式
# 才读得到。下面三组函数就是三种分量的编码器。
# One curve per layer, but the curve's grey output has to be encoded into a
# colour that carries that component before the blend mode can read it.

def _hsl_to_rgb(h, s, l):
    """h∈[0,360) s,l∈[0,1] → (r,g,b)；与 GEGL 的 hsl 编码同口径。"""
    c = (1.0 - abs(2.0 * l - 1.0)) * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = l - c / 2.0
    if h < 60.0:
        r, g, b = c, x, 0.0
    elif h < 120.0:
        r, g, b = x, c, 0.0
    elif h < 180.0:
        r, g, b = 0.0, c, x
    elif h < 240.0:
        r, g, b = 0.0, x, c
    elif h < 300.0:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return r + m, g + m, b + m


def _hue_channel(k):
    """Hue 层第 k 通道：hsl(g·360°, 1, 0.5)——饱和度/亮度拉满的色相轮。

    Hue 混合模式只读色相，所以饱和度、明度取什么都无所谓；取满饱和是为了
    让编码值离中灰足够远，8 位下也不容易被量化吃掉。"""
    def fn(t):
        return _hsl_to_rgb(t * 360.0, 1.0, 0.5)[k]
    return fn


def _sat_channel(k):
    """Saturation 层第 k 通道：hsv(0°, g, 1) = (1, 1−g, 1−g)。

    Saturation 混合模式只读饱和度，所以色相固定成红、明度固定在 1 都无所谓；
    这样编码恰好是一条直线，曲线采样不引入误差。"""
    if k == 0:
        return lambda t: 1.0
    return lambda t: 1.0 - t


HUE_ENCODE = tuple(_hue_channel(k) for k in range(3))
SAT_ENCODE = tuple(_sat_channel(k) for k in range(3))

# 一个滤镜顶三条曲线的编码算子（本仓库 ops/gray-to-component）
GTC_OP = "lb:gray-to-component"

_GTC_OK = None


def _append_encoder(layer, mode, label, encode):
    """给灰度层挂编码：优先 lb:gray-to-component，缺算子时退回三条曲线。

    mode 是算子的分量名（hue / saturation / …）；encode 是等价的曲线三元组。
    Attach the encoder. Falls back to three curve filters when the GEGL op is
    not installed, so the plugin still works on a bare GIMP."""
    global _GTC_OK
    if _GTC_OK is not False:
        try:
            filt = Gimp.DrawableFilter.new(layer, GTC_OP, label)
            cfg = filt.get_config()
            cfg.set_property("mode", mode)
            filt.update()
            layer.append_filter(filt)
            _GTC_OK = True
            return [filt]
        except Exception:
            _GTC_OK = False

    added = []
    for channel, fn in zip((Gimp.HistogramChannel.RED,
                            Gimp.HistogramChannel.GREEN,
                            Gimp.HistogramChannel.BLUE), encode):
        added.append(_append_curve(layer, label, fn, channel))
    return added


def _component_layer(image, base, title, component, encode, mode, parent):
    """造一张分量层：extract → curve → encode，并挂好混合模式。

    extract 输出的是灰度，alpha 会被写成不透明；不用补蒙版——分量混合模式
    在合成时沿用下层的 alpha，透明区域照样透出去（实测 alpha 逐位一致）。
    Build one component layer: extract -> curve -> encode, with its blend mode."""
    layer = Gimp.Layer.new_from_drawable(base, image)
    layer.set_name(title)
    layer.set_mode(mode)
    image.insert_layer(layer, parent, 0)

    filt = Gimp.DrawableFilter.new(
        layer, "gegl:component-extract", _("1 · extract"))
    cfg = filt.get_config()
    cfg.set_property("component", component)
    filt.update()
    layer.append_filter(filt)

    _append_curve_points(layer, _("2 · curve"), IDENTITY_POINTS,
                         Gimp.HistogramChannel.VALUE)

    if encode:
        _append_encoder(layer, encode[0], _("3 · encode"), encode[1])
    return layer


# ---- 动作 / the action ------------------------------------------------------

def _check_base(base):
    if base is None:
        raise RuntimeError(_("Nothing to split: no layer."))
    if base.is_group():
        raise RuntimeError(
            _("A layer group cannot be split; pick a raster layer first (right-click the group, then Merge Group)."))


def _split_multi(image, base, make_group=True):
    """multi：拆成三张分量层，用 HSV 的三个分量混合模式叠回去。

    返回最上面那层（Value）；make_group 时返回包住三层的组。
    Split into H / S / V component layers that recombine through the native
    HSV blend modes. Returns the Value layer, or the group holding all three."""
    _check_base(base)

    parent = base.get_parent()
    position = _item_position(image, base)

    # 带 alpha 的图层必须分组：透明度靠组蒙版保住，散层没有地方挂。
    auto_group = False
    if not make_group:
        try:
            if base.has_alpha():
                make_group = True
                auto_group = True
        except Exception:
            pass

    image.undo_group_start()
    try:
        host = None
        if make_group:
            host = Gimp.GroupLayer.new(image, _("HSV split"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        # 自下而上造：Hue 最先插入（落到组的最底），Value 最后插到最上。
        # 顺序不能反：分量混合模式只替换一个分量，另外两个从下行读。最底那张
        # 必须是「带真实色相的全饱和色」（hsl 色环），因为它下面什么都没有；
        # 若最底是灰（V 层），它的 S=0，上面两层替换 H/S 时读到的都是 0，
        # 怎么换都是灰——把原图层藏起来就彻底还原不出来。
        _component_layer(image, base, _("1 · Hue"), "hue",
                         ("hue", HUE_ENCODE),
                         Gimp.LayerMode.HSV_HUE, host)
        _component_layer(image, base, _("2 · Saturation"), "hsv-s",
                         ("saturation", SAT_ENCODE),
                         Gimp.LayerMode.HSV_SATURATION, host)
        value = _component_layer(image, base, _("3 · Value"), "hsv-v", None,
                                 Gimp.LayerMode.HSV_VALUE, host)

        _link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([host or value])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("HSV component layers created (multi mode): %s. Editing each layer's \"2 · curve\" adjusts that component; leave the encode step alone. Every layer can be switched off separately. Hide the original layer; these three stack back on their own.") \
              % (host.get_name() if host else value.get_name())
        if auto_group:
            msg += _("\n(This image has transparency, so the layers went into a group automatically: the group mask preserves it.)")
        Gimp.message(msg)
    except Exception:
        pass
    return host or value


def split_hsv(image, base, mode='single', make_group=True):
    """按 mode 生成 single（一层数据图）或 multi（三张分量层）。

    mode='single'：一层，五条滤镜，恒等曲线时逐像素还原原图。
    mode='multi' ：三层，走 GIMP 原生的 HSV 分量混合模式，每层可单独关掉。
    返回建好的组（或最上面那层）。
    Build the single packed data layer, or the three component layers."""
    _check_base(base)
    if mode == 'multi':
        return _split_multi(image, base, make_group)

    _require_adapter_ops(base)

    parent = base.get_parent()
    position = _item_position(image, base)

    # 带 alpha 的图层必须分组：透明度靠组蒙版保住，散层没有地方挂。
    auto_group = False
    if not make_group:
        try:
            if base.has_alpha():
                make_group = True
                auto_group = True
        except Exception:
            pass

    image.undo_group_start()
    try:
        host = None
        if make_group:
            host = Gimp.GroupLayer.new(image, _("HSV split"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        layer = Gimp.Layer.new_from_drawable(base, image)
        layer.set_name(_("1 · HSV S/V/H"))
        layer.set_mode(Gimp.LayerMode.NORMAL)
        image.insert_layer(layer, host, 0)

        _simple_filter(layer, DUAL_OP, _("1 · decompose"))
        _append_curve_points(layer, _("2 · S curve"), IDENTITY_POINTS,
                             Gimp.HistogramChannel.RED)
        _append_curve_points(layer, _("3 · V curve"), IDENTITY_POINTS,
                             Gimp.HistogramChannel.GREEN)
        _append_curve_points(layer, _("4 · H curve"), IDENTITY_POINTS,
                             Gimp.HistogramChannel.BLUE)
        _simple_filter(layer, COMPOSE_OP, _("5 · compose"))

        _link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([host or layer])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("HSV layers created: %s. The S curve lives in \"2 · S curve\" (red channel), the V curve in \"3 · V curve\" (green channel) and the hue curve in \"4 · H curve\" (blue channel). Hide the original layer; this one reproduces it on its own.") \
              % (host.get_name() if host else layer.get_name())
        if auto_group:
            msg += _("\n(This image has transparency, so the layers went into a group automatically: the group mask preserves it.)")
        Gimp.message(msg)
    except Exception:
        pass
    return host or layer


# ---- 程序包装 / procedure wrapper ------------------------------------------

class HsvSplitPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return ['lb-plugin-hsv-split-curves',
                'lb-plugin-hsv-split-curves-multi']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        multi = name.endswith('-multi')
        procedure.set_menu_label(
            _("HSV Split (Curves) · %s") % (_("multi") if multi else _("single")))
        procedure.add_menu_path("<Image>/SuperMrWang/Retouch")
        procedure.add_menu_path("<Layers>/SuperMrWang/Retouch")

        if multi:
            doc_zh = _("Adjust curves in HSV space: multi mode splits the layer into component layers, attaches one curve to each and stacks them back with GIMP's native component blend modes, so every layer can be switched off separately. Identity curves reproduce the original exactly.")
            doc_en = _("Curve HSV itself, multi mode: the old component-layer stack "
                       "on GIMP's native blend modes, one switch per layer.")
        else:
            doc_zh = _("Adjust curves in HSV space: single mode packs the three components into one data image, one curve per channel, then an operation decodes it back to colour. Identity curves reproduce the original exactly; one layer, five filters.")
            doc_en = _("Curve HSV itself, single mode: one packed data layer with "
                       "three curves; identity reproduces the image exactly.")
        procedure.set_documentation(doc_zh, doc_en, name)

        procedure.add_boolean_argument(
            "group", _("Put in a layer group"),
            _("Puts the result into a pass-through group named HSV split; turn it off to stack it directly above the original layer."),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        try:
            split_hsv(image, drawables[0],
                      'multi' if procedure.get_name().endswith('-multi') else 'single',
                      config.get_property('group'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("hsv-split-curves: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(HsvSplitPlugin.__gtype__, sys.argv)
