#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · HSV 分量分解 + 曲线 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把当前图层拆成 HSV 三张分量层（Hue / Saturation / Value），每层挂
           一条可编辑的曲线，再用「颜色」组的三条分量混合模式叠回去。恒等
           曲线时逐位还原原图——所以这是「在 HSV 空间里调曲线」的图层化写法，
           也顺手补了 GIMP 缺 HSL/HSV 分量曲线的问题。
           Split a layer into H / S / V component layers, give each one its own
           editable curve, and stack them back with the HSV blend modes.

 menu      颜色 → SuperMrWang → HSV Split (Curves)
           图层右键 → SuperMrWang → HSV Split (Curves)

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              HSV split            组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 3 Value         分量层：hsv-v 灰 → 曲线         模式 = HSV 明度
                ├─ 2 Saturation    分量层：hsv-s 灰 → 曲线 → 编码 模式 = HSV 饱和度
                ├─ 1 Hue           分量层：hue 灰 → 曲线 → 编码   模式 = HSV 色相
                └─ 原图层（不动，可以隐藏）

           合成顺序自下而上：色相层（全饱和色环）先定 H，饱和度层换 S，明度层
           最后换 V。层序不能反——最底那张必须带真实色相，因为它下面没有东西
           可读；若最底是灰（S=0），上面两层换 H、换 S 时读到的都是 0，怎么换
           都还是灰，把原图层一藏就彻底还原不出来。

           每层的滤镜栈（图层面板里从上往下读是 3 → 2 → 1，实际执行顺序相反）：

              1 · extract   gegl:component-extract —— 抽出该分量，输出灰度
              2 · curve     gimp:curves（通道 = 值）—— 给用户调的那条
              3 · encode    lb:gray-to-component —— 把灰度编码成「携带该分量」
                            的彩色，混合模式才读得出来

           Value 层不需要编码（灰就是 V），所以只有前两条。

 note      为什么要 encode：灰度像素的色相/饱和度是无定义的，把 H 灰度层直接
           设成「HSV 色相」模式不会有任何效果——混合模式从灰里读不出色相。必
           须先把它映射到色环上的真实颜色。

           这一步由本仓库的 GEGL 算子 lb:gray-to-component 一个滤镜完成（不再
           是三条 gimp:curves）。灰度值 g 按模式编码（sRGB 编码值域）：
             hue        hsl(g·360°, 1, 0.5)
             saturation hsv(0°, g, 1) = (1, 1−g, 1−g) —— red 相、V=1
             value      恒等（灰层本身就是 V）

           没装这个算子时自动退回三条曲线编码，结果几乎一致（曲线是 256 点
           查表，色相环上一格 1.4°）。

           实测（GIMP 3.2.8，覆盖全色相/饱和度/明度的测试图，见
           tools/check_hsv_split.py）：
             32 位浮点图，恒等曲线往返：最大通道误差 0.00196（0.50 码）
             8 位图，恒等曲线往返：      最大通道误差 0.00196（0.50 码）
             8 位图，曲线 vs 直接改 HSV 的数学期望：1.84 码

           注意事项：
           - 色相曲线必须是连续的：两端相等、中间不跳变。**整体旋转色相**不
             能用这条曲线做——曲线是 256 项查表，`(t+Δ) mod 1` 这类带跳变的
             映射会在跳变点插值出一条约 1.4° 宽的伪彩带（实测）。要旋转色相
             请用 lb:hue-saturation；这条曲线适合「压缩/拉伸某段色相」这类连
             续映射，例如 t + 0.04·sin(2πt)。
           - 图层自带的非破坏滤镜不会被复制（new_from_drawable 只取像素）。
           - 透明区域没问题：分量混合模式会沿用下层 alpha，不必加蒙版。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math
import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject

from gi.repository import Gegl


def _N_(message):
    return message


def _(message):
    return GLib.dgettext(None, message)


# ---- 编码曲线 / encoding curves --------------------------------------------
# 每条曲线是「灰度 → 某个通道」的一维映射，值域 0..1（sRGB 编码值）。
# One curve per channel: gray in, channel value out, both in encoded sRGB.

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


def _identity(t):
    return t


def _hue_channel(k):
    """Hue 层第 k 通道：hsl(g·360°, 1, 0.5)——饱和度/亮度拉满的色相轮。

    Hue 混合模式只读色相，所以饱和度、明度取什么都无所谓；取满饱和是为了
    让编码值离中灰足够远，8 位下也不容易被量化吃掉。
    """
    def fn(t):
        return _hsl_to_rgb(t * 360.0, 1.0, 0.5)[k]
    return fn


def _sat_channel(k):
    """Saturation 层第 k 通道：hsv(0°, g, 1) = (1, 1−g, 1−g)。

    Saturation 混合模式只读饱和度，所以色相固定成红、明度固定在 1 都无所谓；
    这样编码恰好是一条直线，曲线采样不引入误差。
    """
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
    可用性靠「能不能真的建出这个滤镜」判断（GEGL 没有给 GI 暴露注册表查询）。
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



# ---- 滤镜栈 / the filter stack ---------------------------------------------

def _append_curve(layer, label, fn, channel):
    """在图层上追加一条 gimp:curves（通道级一维映射）。

    trc 必须钉成 NON_LINEAR：曲线在「编码值」上生效，才和分量的语义一致；
    默认的 trc 是感知空间，同一组采样点出来的对比度完全不同。
    Append one channel curve. trc is pinned to NON_LINEAR so the curve works on
    encoded values, which is the space the extracted components live in."""
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


def _component_layer(image, base, title, component, encode, mode, parent):
    """造一张分量层：extract → curve → encode，并挂好混合模式。

    extract 输出的是灰度，alpha 会被写成不透明；不用补蒙版——分量混合模式
    在合成时沿用下层的 alpha，透明区域照样透出去（实测 alpha 逐位一致）。
    Build one component layer: extract -> curve -> encode, with its blend mode.
    No mask is needed: component modes inherit the backdrop alpha."""
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

    _append_curve(layer, _("2 · curve"), _identity, Gimp.HistogramChannel.VALUE)

    if encode:
        _append_encoder(layer, encode[0], _("3 · encode"), encode[1])
    return layer


def _link_alpha_mask(image, base, host):
    """把原图层的 alpha 变成整组的蒙版。

    分量混合模式在源 alpha=1 时才是「纯替换」；若把 alpha 留在分量层上，GIMP
    会按 alpha 把结果与下层 lerp（实测半透明区偏 28 码）。所以三层一律不透明，
    alpha 交给组蒙版：颜色由三层算，透明度由原图给。
    Mask the group with the source alpha: the three component layers must stay
    opaque (a partly transparent blend layer lerps instead of replaces).
    Returns True when a mask was attached."""
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

def split_hsv(image, base, make_group=True):
    """把一个图层拆成 HSV 三张分量层 + 曲线，再用分量混合模式叠回去。

    返回最上面那层（Value）；make_group 时返回的是包住三层的组。原图层不动
    ——把原图层隐藏掉，这三层自己就能叠回原图。
    Split one layer into H/S/V curve layers that recombine to the original,
    even with the source layer hidden. Returns the Value layer, or the group
    holding all three."""
    if base is None:
        raise RuntimeError(_("没有可以拆分的图层 / no layer to split"))
    if base.is_group():
        raise RuntimeError(
            _("图层组不能拆分：请先选一个栅格图层（右键 → 合并组）"
              " / a layer group has no pixels of its own"))

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
        hue = _component_layer(image, base, _("1 · Hue"), "hue",
                               ("hue", HUE_ENCODE),
                               Gimp.LayerMode.HSV_HUE, host)
        sat = _component_layer(image, base, _("2 · Saturation"), "hsv-s",
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
        msg = _("HSV 分量层已建立：%s。改每层「2 · curve」就是调该分量的曲线；"
                "encode 那步别动。原图层可以隐藏，这三层自己就能叠回去。") \
              % (host.get_name() if host else value.get_name())
        if auto_group:
            msg += _("\n（这张图带透明，已自动分组：透明度靠组蒙版保住。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or value


# ---- 程序包装 / procedure wrapper ------------------------------------------

class HsvSplitPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-hsv-split-curves']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("HSV Split (Curves)"))
        procedure.add_menu_path("<Image>/Colors/SuperMrWang")
        procedure.add_menu_path("<Layers>/SuperMrWang")

        procedure.set_documentation(
            _("把图层拆成 H / S / V 三张分量层，每层挂一条可编辑的曲线，再用"
              "「颜色」组的 HSV 色相 / 饱和度 / 明度三条混合模式叠回去。"
              "恒等曲线时逐位还原原图。"),
            _("Split into HSV component layers with per-component curves. The "
              "three layers recombine through the HSV blend modes, so editing a "
              "curve is exactly 'curve the H/S/V channel'."), name)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把三层放进一个「HSV split」穿透组里；关掉就直接叠在原图层上方"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        try:
            split_hsv(image, drawables[0], config.get_property('group'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("hsv-split-curves: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(HsvSplitPlugin.__gtype__, sys.argv)
