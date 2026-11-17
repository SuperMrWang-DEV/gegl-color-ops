#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · HSL 分量分解 + 曲线 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   在 HSL 空间里调曲线。GIMP 有 HSV 和 LCh 的分量混合模式，却没有
           HSL 的——本插件用两个适配算子把 HSL 接到 HSV 上，做到与直接改
           HSL 完全等价：恒等曲线时逐像素还原原图，调 S 曲线就是只动 HSL 的
           饱和度，调 H 曲线就是只动色相。
           Curve HSL itself, by adapting it onto GIMP's HSV component modes.

 menu      颜色 → SuperMrWang → HSL Split (Curves)
           图层右键 → SuperMrWang → HSL Split (Curves)

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              HSL split            组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 2 · Hue          模式 = HSV 色相   ← 只替换 H
                ├─ 1 · S / L        模式 = 正常       ← 一条算子链算出完整 HSL 色
                └─ 原图层（不动，可以隐藏）

 note      为什么是两层，不是三层：HSL 的 S 与 L 是耦合的——

             C = (1 − |2L−1|)·S      V = L + C/2      S_hsv = C/V

           想精确得到 HSL 的 (S, L)，编码器必须同时读到 S 和 L 两个值，而每层
           的曲线只看得到自己那一个分量。把 S 与 L 放进同一张数据图（R=S、
           G=L），两条曲线各挂一个通道，再由 lb:hsl-compose 联合还原——这才
           精确。而这一层算出来的本来就是完整颜色，于是第三层就不需要了：
           上面的 Hue 层用「HSV 色相」模式只替换色相，S 与 L 原样保留。

           对比一下硬凑三层的代价：把 HSL 的 L 直接当 HSV 的 V 用，中亮度饱
           和色实测偏 25～64 码（S=1、L=0.5 时正好差 C/2 = 64 码）；再叠加 S
           与 V 互相污染，最坏 102 码。这不是精度问题，是「两条独立的 1D 曲
           线表达不了二元映射」。

           每层的滤镜栈（图层面板里从上往下读是 2 → 1，执行顺序相反）：

             S/L 层   1 · decompose   lb:hsl-dual     原图 → (R=S, G=L, B=H)
                      2 · S curve     gimp:curves     通道 = R（红）
                      3 · L curve     gimp:curves     通道 = G（绿）
                      4 · compose     lb:hsl-compose  (R,G,B) → 真实 HSL 色

             Hue 层   1 · hue         gegl:component-extract  component=hue
                      2 · H curve     gimp:curves     通道 = 值
                      3 · encode      lb:gray-to-component  mode=hue

           色相从一开始就在 S/L 层的 B 通道里带着，所以把 Hue 层关掉、只留
           S/L 层，你看到的就是「原色相 + 调过的 S/L」——一个很好用的中间
           状态，便于判断到底在改什么。

           实测（GIMP 3.2.8，见 tools/check_hsl_split.py）：
             32 位浮点图，恒等曲线往返：   最大 0.0002 码
             8 位图，恒等曲线往返：        ≤ 1 码
             隐藏原图层后三层自己还原：     与可见时同值

           注意事项：
           - S 曲线挂在**红**通道、L 曲线挂在**绿**通道：在图层属性的滤镜里改
             曲线时记得选对通道。选「值」会把三条数据一起改掉。
           - 色相曲线必须是连续的（两端相等、中间不跳变）。整体旋转色相请用
             lb:hue-saturation。
           - 这套精确适配依赖 lb:hsl-dual 与 lb:hsl-compose 两个算子；缺了
             它们就没有等价回退（二维映射没法用一维曲线凑），插件会直接报错。
           - 图层自带的非破坏滤镜不会被复制（new_from_drawable 只取像素）。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject


def _(message):
    return GLib.dgettext(None, message)


def _identity(t):
    return t


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


# ---- 滤镜栈 / the filter stack ---------------------------------------------

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
            _("缺少适配算子：%s。它们是 HSL 精确适配的必需组件（S 与 L 必须联合"
              "计算，无法用一维曲线代替）。请先安装本仓库的 GEGL 算子的 "
              "hsl-dual / hsl-compose（./install.sh），重启 GIMP 再试。")
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

def split_hsl(image, base, make_group=True):
    """把图层拆成「S/L 联合层 + Hue 层」，在 HSL 空间里调曲线。

    返回最上面那层（Hue）；make_group 时返回包住两层的组。原图层不动，把
    它隐藏掉这两层自己就能还原。
    Split into an S/L layer and a Hue layer that recombine exactly to the
    original, even with the source hidden."""
    if base is None:
        raise RuntimeError(_("没有可以拆分的图层 / no layer to split"))
    if base.is_group():
        raise RuntimeError(
            _("图层组不能拆分：请先选一个栅格图层（右键 → 合并组）"
              " / a layer group has no pixels of its own"))

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
        _append_curve(sl, _("2 · S curve"), _identity,
                      Gimp.HistogramChannel.RED)
        _append_curve(sl, _("3 · L curve"), _identity,
                      Gimp.HistogramChannel.GREEN)
        _simple_filter(sl, COMPOSE_OP, _("4 · compose"))

        # Hue 层：只替换色相，S 和 L 保留下面那层的。
        hue = Gimp.Layer.new_from_drawable(base, image)
        hue.set_name(_("2 · Hue"))
        hue.set_mode(Gimp.LayerMode.HSV_HUE)
        image.insert_layer(hue, host, 0)

        _simple_filter(hue, "gegl:component-extract", _("1 · hue"),
                       {"component": "hue"})
        _append_curve(hue, _("2 · H curve"), _identity,
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
        msg = _("HSL 分量层已建立：%s。S 曲线在「2 · S curve」（红通道）、"
                "L 曲线在「3 · L curve」（绿通道）、色相曲线在 Hue 层的"
                "「2 · H curve」。原图层可以隐藏，这两层自己就能还原。") \
              % (host.get_name() if host else hue.get_name())
        if auto_group:
            msg += _("\n（这张图带透明，已自动分组：透明度靠组蒙版保住。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or hue


# ---- 程序包装 / procedure wrapper ------------------------------------------

class HslSplitPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-hsl-split-curves']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("HSL Split (Curves)"))
        procedure.add_menu_path("<Image>/Colors/SuperMrWang")
        procedure.add_menu_path("<Layers>/SuperMrWang")

        procedure.set_documentation(
            _("在 HSL 空间里调曲线：生成一个 S/L 联合层（红通道 = 饱和度、"
              "绿通道 = 明度）和一个只替换色相的 Hue 层。恒等曲线时精确还原"
              "原图，调哪条曲线就只动那个 HSL 分量。"),
            _("Curve HSL itself. An S/L layer (R = saturation, G = lightness) "
              "plus a hue-only layer on top; identity curves reproduce the "
              "image exactly. Needs lb:hsl-dual and lb:hsl-compose."), name)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把两层放进一个「HSL split」穿透组里；关掉就直接叠在原图层上方"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        try:
            split_hsl(image, drawables[0], config.get_property('group'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("hsl-split-curves: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(HslSplitPlugin.__gtype__, sys.argv)
