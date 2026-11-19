#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · HSL 分量分解 + 曲线 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   在 HSL 空间里调曲线。菜单里是两条，各对应一种模式：

             single   一张数据图（R=S、G=L、B=H/360）三条曲线，compose 一次
                      算完。一层、五条滤镜。
             multi    两张分量层：Hue 层借 HSV 的色相混合模式（HSL 与 HSV 的
                      色相角完全相等），S/L 层用数据图 + 两条曲线算出颜色和
                      色相，正常模式盖上去。

           两者恒等曲线都逐像素还原原图；调哪条曲线就只动那个分量。
           Curve HSL itself in two modes: one packed data layer, or the
           Hue + S/L stack that borrows GIMP's HSV hue mode.

 menu      SuperMrWang → Retouch → HSL Split (Curves) · single
           SuperMrWang → Retouch → HSL Split (Curves) · multi
          图层右键 → SuperMrWang → Retouch → 同上两条
          （single 与 multi 是两个独立的过程，不再是对话框里的下拉）

 usage     选中一个栅格图层 → 取 single 或 multi 那条。生成的结构（自上而下）：

            single 模式

              HSL split       组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 1 · HSL S/L/H   正常模式   ← 一条算子链算出完整 HSL 色
                └─ 原图层（不动，可以隐藏）

            multi 模式

              HSL split       组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 2 · Hue            模式 = HSV 色相   ← 只替换 H
                ├─ 1 · S / L          正常模式          ← 算出 S、L 与色相
                └─ 原图层（不动，可以隐藏）

 note      为什么 multi 是两层、不是三层：HSL 的 S 与 L 是耦合的——

             C = (1 − |2L−1|)·S      V = L + C/2      S_hsv = C/V

           想精确得到 HSL 的 (S, L)，编码器必须同时读到 S 和 L 两个值，而每层
           的曲线只看得到自己那一个分量。所以 S 与 L 放进同一张数据图联合还原；
           这一层算出来的本来就是完整颜色，第三层就不需要了——上面的 Hue 层用
           「HSV 色相」模式只替换色相，S 与 L 原样保留。

           single 把色相也收进 compose，一层就够：少一层图、少一次编码量化。
           代价是少了一个可以单独关掉的开关——multi 里把 Hue 层眼睛一关，就能
           看到「原色相 + 调过 S/L」的中间结果。

           single 的滤镜栈（图层面板里从上往下读，执行顺序相反）：

             1 · decompose   lb:hsl-dual   原图 → (R=S, G=L, B=H/360)
             2 · S curve     gimp:curves     通道 = R（红）
             3 · L curve     gimp:curves     通道 = G（绿）
             4 · H curve     gimp:curves     通道 = B（蓝）
             5 · compose     lb:hsl-compose   (S,L,H) → 真实颜色

           multi 每层的滤镜栈：

             Hue      1 · hue     gegl:component-extract  component=hue
                      2 · H curve gimp:curves   通道 = 值
                      3 · encode  lb:gray-to-component  mode=hue

             S / L    1 · decompose lb:hsl-dual     原图 → (R=S, G=L, B=H)
                      2 · S curve   gimp:curves     通道 = R
                      3 · L curve   gimp:curves     通道 = G
                      4 · compose   lb:hsl-compose  (S,L,H) → 真实颜色

           量程：
             S  0…1
             L  0…1
             H  色相 / 360           0…1

           实测（GIMP 3.2.8，见 tools/check_hsl_split.py）：
             32 位浮点图，恒等曲线往返：   最大 0.02 码
             8 位图，恒等曲线往返：        ≤ 0.5 码
             隐藏原图层后自己还原：         与可见时同值
             只改 S 曲线时 L、H 的偏差：     < 0.01 码

           注意事项：
           - 三条曲线分别挂在**红 / 绿 / 蓝**通道上：S 在红、L 在绿、H 在蓝。
             在图层属性的滤镜里改曲线时记得选对通道；选「值」会把三条数据
             一起改掉。
           - 色相曲线必须是连续的（两端相等、中间不跳变）。整体旋转色相请用
             lb:hue-saturation；这条曲线适合「压缩 / 拉伸某段色相」。
           - 色相角在 L = 0 或 L = 1（纯黑、纯白）上没有意义，曲线改了也看不见。
           - 曲线推到头会把结果推出 sRGB 色域，8 位图按 0/1 裁切。
           - 两种模式都依赖 lb:hsl-dual 与 lb:hsl-compose：GIMP 没有 HSL 分量
             模式，S/L 只能靠数据图联合还原，没有等价回退。编码那步的
             lb:gray-to-component 缺失时自动退回三条曲线。
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


# 精确适配用的两个算子（本仓库 ops/hsl-dual、ops/hsl-compose）
DUAL_OP = "lb:hsl-dual"
COMPOSE_OP = "lb:hsl-compose"

# ---- multi 模式：分量层 / the component layers ----------------------------
# 每层一条曲线，曲线的灰度结果再编码成「携带该分量」的颜色，混合模式才
# 读得到；下面这些 helper 只服务 multi。
# One curve per layer; the grey output is encoded into a colour that
# carries that component before the blend mode reads it.

# 精确适配用的两个算子（本仓库 ops/hsl-dual、ops/hsl-compose）
DUAL_OP = "lb:hsl-dual"
COMPOSE_OP = "lb:hsl-compose"
GTC_OP = "lb:gray-to-component"

# 色相编码：hsl(g·360°, 1, 0.5) 逐通道。没装 gray-to-component 时退回三条曲线。
def _hsl_to_rgb(h, s, l):
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
    def fn(t):
        return _hsl_to_rgb(t * 360.0, 1.0, 0.5)[k]
    return fn


HUE_ENCODE = tuple(_hue_channel(k) for k in range(3))

_GTC_OK = None


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


def _simple_filter(layer, op, label, props=None):
    """挂一个不需要曲线的算子滤镜（lb:hsl-dual / lb:hsl-compose 这类）。"""
    filt = Gimp.DrawableFilter.new(layer, op, label)
    if props:
        cfg = filt.get_config()
        for key, value in props.items():
            cfg.set_property(key, value)
    filt.update()
    layer.append_filter(filt)
    return filt


def _append_encoder(layer, label, encode):
    """给灰度层挂色相编码：优先 lb:gray-to-component，缺算子时退回三条曲线。"""
    global _GTC_OK
    if _GTC_OK is not False:
        try:
            filt = Gimp.DrawableFilter.new(layer, GTC_OP, label)
            filt.get_config().set_property("mode", "hue")
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


def _require_adapter_ops(layer):
    """确认两个适配算子可用。

    没有它们就没有等价回退：S 与 L 的耦合是二元映射，一维曲线表达不了。
    The adapter pair is mandatory; there is no curve-only fallback."""
    missing = []
    for op in (DUAL_OP, COMPOSE_OP):
        try:
            Gimp.DrawableFilter.new(layer, op, "probe")
        except Exception:
            missing.append(op)
    if missing:
        raise RuntimeError(
            _("Required operations are missing: %s. They are essential for exact HSL fitting (S and L must be computed together and cannot be replaced by a 1D curve). Install this repository's GEGL operations hsl-dual / hsl-compose (./install.sh) and restart GIMP.")
            % ", ".join(missing))


def _link_alpha_mask(image, base, host):
    """把原图层的 alpha 变成整组的蒙版。

    分量层必须不透明（半透明层的混合会按 alpha 做 lerp，实测偏 28 码），
    透明度交给组蒙版：颜色由图层算，透明度由原图给。
    Mask the group with the source alpha; component layers stay opaque."""
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


# ---- 动作 / the action ------------------------------------------------------

def _split_multi(image, base, make_group=True):
    """把图层拆成「S/L 联合层 + Hue 层」，在 HSL 空间里调曲线。

    返回最上面那层（Hue）；make_group 时返回包住两层的组。原图层不动，把
    它隐藏掉这两层自己就能还原。
    Split into an S/L layer and a Hue layer that recombine exactly to the
    original, even with the source hidden."""
    if base is None:
        raise RuntimeError(_("Nothing to split: no layer."))
    if base.is_group():
        raise RuntimeError(
            _("A layer group cannot be split; pick a raster layer first (right-click the group, then Merge Group)."))

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
            host = Gimp.GroupLayer.new(image, _("HSL split"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        # 自下而上：S/L 层先插入（落最底，正常模式），Hue 层最后插到最上。
        sl = Gimp.Layer.new_from_drawable(base, image)
        sl.set_name(_("1 · S / L"))
        sl.set_mode(Gimp.LayerMode.NORMAL)
        image.insert_layer(sl, host, 0)

        _simple_filter(sl, DUAL_OP, _("1 · decompose"))
        _append_curve_points(sl, _("2 · S curve"), IDENTITY_POINTS,
                             Gimp.HistogramChannel.RED)
        _append_curve_points(sl, _("3 · L curve"), IDENTITY_POINTS,
                             Gimp.HistogramChannel.GREEN)
        _simple_filter(sl, COMPOSE_OP, _("4 · compose"))

        # Hue 层：只替换色相，S 和 L 保留下面那层的。
        hue = Gimp.Layer.new_from_drawable(base, image)
        hue.set_name(_("2 · Hue"))
        hue.set_mode(Gimp.LayerMode.HSV_HUE)
        image.insert_layer(hue, host, 0)

        _simple_filter(hue, "gegl:component-extract", _("1 · hue"),
                       {"component": "hue"})
        _append_curve_points(hue, _("2 · H curve"), IDENTITY_POINTS,
                             Gimp.HistogramChannel.VALUE)
        _append_encoder(hue, _("3 · encode"), HUE_ENCODE)

        _link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([host or hue])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("HSL component layers created: %s. The S curve lives in \"2 · S curve\" (red channel), the L curve in \"3 · L curve\" (green channel) and the hue curve in the Hue layer's \"2 · H curve\". Hide the original layers; these two reproduce it on their own.") \
              % (host.get_name() if host else hue.get_name())
        if auto_group:
            msg += _("\n(This image has transparency, so the layers went into a group automatically: the group mask preserves it.)")
        Gimp.message(msg)
    except Exception:
        pass
    return host or hue

def _split_single(image, base, make_group=True):
    """把图层换成一张「S / L / H 三联曲线」的 HSL 层。

    返回那张层；make_group 时返回包住它的组。原图层不动，把它隐藏掉这一层
    自己就能还原。
    Replace the layer with one HSL data layer carrying three curves; it
    reproduces the original on its own, with the source hidden."""
    if base is None:
        raise RuntimeError(_("Nothing to split: no layer."))
    if base.is_group():
        raise RuntimeError(
            _("A layer group cannot be split; pick a raster layer first (right-click the group, then Merge Group)."))

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
            host = Gimp.GroupLayer.new(image, _("HSL split"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        layer = Gimp.Layer.new_from_drawable(base, image)
        layer.set_name(_("1 · HSL S/L/H"))
        layer.set_mode(Gimp.LayerMode.NORMAL)
        image.insert_layer(layer, host, 0)

        _simple_filter(layer, DUAL_OP, _("1 · decompose"))
        _append_curve_points(layer, _("2 · S curve"), IDENTITY_POINTS,
                             Gimp.HistogramChannel.RED)
        _append_curve_points(layer, _("3 · L curve"), IDENTITY_POINTS,
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
        msg = _("HSL layers created: %s. The S curve lives in \"2 · S curve\" (red channel), the L curve in \"3 · L curve\" (green channel) and the hue curve in \"4 · H curve\" (blue channel). Hide the original layer; this one reproduces it on its own.") \
              % (host.get_name() if host else layer.get_name())
        if auto_group:
            msg += _("\n(This image has transparency, so the layers went into a group automatically: the group mask preserves it.)")
        Gimp.message(msg)
    except Exception:
        pass
    return host or layer

def split_hsl(image, base, mode='single', make_group=True):
    """按 mode 生成 single（一层数据图）或 multi（分量层）。

    mode='single'：一张数据图，三条曲线，compose 一次算完。
    mode='multi' ：每层一个分量，用分量混合模式叠回去，可单独开关。
    返回建好的组（或最上面那层）。
    Build the single packed data layer, or the multi component layers."""
    if base is None:
        raise RuntimeError(_("Nothing to split: no layer."))
    if base.is_group():
        raise RuntimeError(
            _("A layer group cannot be split; pick a raster layer first (right-click the group, then Merge Group)."))
    if mode == 'multi':
        return _split_multi(image, base, make_group)
    return _split_single(image, base, make_group)

# ---- 程序包装 / procedure wrapper ------------------------------------------

class HslSplitPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return ['lb-plugin-hsl-split-curves',
                'lb-plugin-hsl-split-curves-multi']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        multi = name.endswith('-multi')
        procedure.set_menu_label(
            _("HSL Split (Curves) · %s") % (_("multi") if multi else _("single")))
        procedure.add_menu_path("<Image>/SuperMrWang/Retouch")
        procedure.add_menu_path("<Layers>/SuperMrWang/Retouch")

        if multi:
            doc_zh = _("Adjust curves in HSL space: multi mode splits the layer into component layers, attaches one curve to each and stacks them back with GIMP's native component blend modes, so every layer can be switched off separately. Identity curves reproduce the original exactly.")
            doc_en = _("Curve HSL itself, multi mode: the old component-layer stack "
                       "on GIMP's native blend modes, one switch per layer.")
        else:
            doc_zh = _("Adjust curves in HSL space: single mode packs the three components into one data image, one curve per channel, then an operation decodes it back to colour. Identity curves reproduce the original exactly; one layer, five filters.")
            doc_en = _("Curve HSL itself, single mode: one packed data layer with "
                       "three curves; identity reproduces the image exactly.")
        procedure.set_documentation(doc_zh, doc_en, name)
        procedure.add_boolean_argument(
            "group", _("Put in a layer group"),
            _("Puts this layer into a pass-through group named HSL split; turn it off to stack it directly above the original layer."),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        try:
            split_hsl(image, drawables[0],
                       'multi' if procedure.get_name().endswith('-multi') else 'single',
                       config.get_property('group'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("hsl-split-curves: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(HslSplitPlugin.__gtype__, sys.argv)
