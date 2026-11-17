#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · HSV 分量分解 + 曲线 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   在 HSV 空间里调曲线。GIMP 自己有 HSV 的三个分量混合模式，但要用它们
           就得把图层拆成三层、每层 extract → 曲线 → 编码三四个滤镜，8 位图上
           还要靠组内浮点缓冲才不偏色。这里换成和 HSI 插件一样的做法：两个适配
           算子把 S、V、H 打包进一张数据图，三条曲线各管一个，再一起解回来。
           Curve HSV itself: one data layer (R = S, G = V, B = H/360) with three
           curves, instead of three encoded component layers.

 menu      颜色 → SuperMrWang → Shortcut → HSV Split (Curves)
           图层右键 → SuperMrWang → Shortcut → HSV Split (Curves)

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              HSV split       组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 1 · HSV S/V/H   正常模式   ← 一条算子链算出完整 HSV 色
                └─ 原图层（不动，可以隐藏）

 note      和 HSI 那个插件同一个骨架：三个分量挤进一张数据图，一次算完再还原。
           旧版是三张分量层（色相 / 饱和度 / 明度）各自挂一个分量混合模式，
           每层都要先抽出灰度、曲完再编码成「携带该分量」的颜色，最后靠混合模式
           叠回去；三层意味着三次编码、三次量化。现在 S、V、H 一起进 compose，
           一次算完——层数从三降到一，滤镜条数从十条降到五条。

           代价和 HSI 那里一样：少了一层可以单独关掉的开关。

           滤镜栈（图层面板里从上往下读，执行顺序相反）：

             1 · decompose   lb:hsv-dual   原图 → (R=S, G=V, B=H/360)
             2 · S curve     gimp:curves     通道 = R（红）
             3 · V curve     gimp:curves     通道 = G（绿）
             4 · H curve     gimp:curves     通道 = B（蓝）
             5 · compose     lb:hsv-compose   (S,V,H) → 真实颜色

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
           - 这套精确适配依赖 lb:hsv-dual 与 lb:hsv-compose 两个算子；缺了它们就没有
             等价回退，插件会直接报错。
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


# 精确适配用的两个算子（本仓库 ops/hsv-dual、ops/hsv-compose）
DUAL_OP = "lb:hsv-dual"
COMPOSE_OP = "lb:hsv-compose"


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
            _("缺少适配算子：%s。它们是 HSV 精确适配的必需组件（三个分量必须"
              "在同一张数据图里一起算）。请先安装本仓库的 GEGL 算子 hsv-dual / "
              "hsv-compose（./install.sh），重启 GIMP 再试。") % ", ".join(missing))


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


# ---- 动作 / the action ------------------------------------------------------

def split_hsv(image, base, make_group=True):
    """把图层换成一张「S / V / H 三联曲线」的 HSV 层。

    返回那张层；make_group 时返回包住它的组。原图层不动，把它隐藏掉这一层
    自己就能还原。
    Replace the layer with one HSV data layer carrying three curves; it
    reproduces the original on its own, with the source hidden."""
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
            host = Gimp.GroupLayer.new(image, _("HSV split"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        layer = Gimp.Layer.new_from_drawable(base, image)
        layer.set_name(_("1 · HSV S/V/H"))
        layer.set_mode(Gimp.LayerMode.NORMAL)
        image.insert_layer(layer, host, 0)

        _simple_filter(layer, DUAL_OP, _("1 · decompose"))
        _append_curve(layer, _("2 · S curve"), _identity, Gimp.HistogramChannel.RED)
        _append_curve(layer, _("3 · V curve"), _identity, Gimp.HistogramChannel.GREEN)
        _append_curve(layer, _("4 · H curve"), _identity, Gimp.HistogramChannel.BLUE)
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
        msg = _("HSV 层已建立：%s。S 曲线在「2 · S curve」（红通道）、V 曲线在「3 · V curve」（绿通道）、色相曲线在「4 · H curve」（蓝通道）。 原图层可以隐藏，这一层自己就能还原。") \
              % (host.get_name() if host else layer.get_name())
        if auto_group:
            msg += _("\n（这张图带透明，已自动分组：透明度靠组蒙版保住。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or layer


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
        procedure.add_menu_path("<Image>/Colors/SuperMrWang/Shortcut")
        procedure.add_menu_path("<Layers>/SuperMrWang/Shortcut")

        procedure.set_documentation(
            _("在 HSV 空间里调曲线：生成一张三联数据图（红通道 = 饱和度、绿通道 = 明度、蓝通道 = 色相），三条曲线各管一个分量。恒等曲线时精确还原原图，调哪条曲线就只动那个 HSV 分量。"),
            _("Curve HSV itself. One data layer (R = saturation, G = value, B = hue/360) with three curves; identity curves reproduce the image exactly. Needs lb:hsv-dual and lb:hsv-compose."), name)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把这一层放进一个「HSV split」穿透组里；关掉就直接叠在原图层上方"),
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
