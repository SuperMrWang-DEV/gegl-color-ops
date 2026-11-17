#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 双曲线磨皮 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   一次点击搭好「提亮 / 压暗」两条曲线层，两张蒙版都是全黑——也就是
           一开始什么都不改。拿白色软画笔在蒙版上涂，涂到提亮层就是提亮，
           涂到压暗层就是压暗；皮肤上的痘印、法令纹、眼袋靠一黑一白反复
           叠加推平，这就是双曲线（dodge & burn）磨皮。
           Set up the classic two-curve dodge & burn stack: one lighten curve,
           one darken curve, each on a black mask. Paint white to dodge or
           burn; untouched areas stay pixel-identical to the original.

 menu      SuperMrWang → Shortcut → 双曲线磨皮 (Dodge & Burn)
           图层右键 → SuperMrWang → Shortcut → 双曲线磨皮

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              双曲线磨皮              组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 2 · 压暗（黑蒙版）  曲线下压，蒙版全黑
                ├─ 1 · 提亮（黑蒙版）  曲线上提，蒙版全黑
                └─ 原图层（不动，可以隐藏）

           两张蒙版都是黑的，所以刚建好时结果与原图逐像素相同。要开始修：

             1. 在图层面板点中某一层的**蒙版**（缩略图旁边的白框）；
             2. 选柔边画笔，前景色纯白，不透明度 10–20%；
             3. 想提亮就涂「1 · 提亮」的蒙版，想压暗就涂「2 · 压暗」的。

           两张蒙版互相独立，来回切换着涂，皮肤就在两条曲线之间被「夹」平。

 note      曲线形状：x ± d·4x(1−x)，两端钉在 0 和 1，中间是一个抛物线鼓包。
           这样不会动黑场和白场，只在中间调上加/减，肤色正好落在这一段。
           d 由「强度」参数给（默认 12%，即 0.5 处抬/压 0.12，约 30 码）。

           为什么不直接用亮度/对比度：曲线一次只改一个末端（提亮只往上、
           压暗只往下），两块蒙版互不干扰；亮度/对比度会同时动两端的斜率，
           叠两层之后容易把对比度越推越硬。

           图层自带非破坏滤镜（gimp:curves），原图不动，强度随时可以改：
           图层面板 → 该层的滤镜 → 「2 · 压暗曲线」/「1 · 提亮曲线」。
           带 alpha 的图会自动分组并把透明度交给组蒙版——蒙版是黑的，所以
           透明区域里那两层本来就不可见，不会把边缘涂实。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject


def _(message):
    return GLib.dgettext(None, message)


# ---- 公共小工具 / helpers ---------------------------------------------------

def _item_position(image, item, fallback=0):
    try:
        proc = Gimp.get_pdb().lookup_procedure('gimp-image-get-item-position')
        cfg = proc.create_config()
        cfg.set_property('image', image)
        cfg.set_property('item', item)
        return proc.run(cfg).index(1)
    except Exception:
        return fallback


def _link_alpha_mask(image, base, host):
    """把原图层的 alpha 变成整组的蒙版。"""
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


def _force_opaque(layer):
    """把 alpha 拉满：显隐只由蒙版决定。

    SMOOTH 三控制点全在顶，比铺 256 个采样点省事，界面上也只有三个抓手。
    """
    filt = Gimp.DrawableFilter.new(layer, "gimp:curves", _("0 · alpha"))
    cfg = filt.get_config()
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.SMOOTH)
    for x in (0.0, 128 / 255.0, 1.0):   # 踩格点，见 split 插件里的注释
        curve.add_point(x, 1.0)
    cfg.set_property("curve", curve)
    cfg.set_property("channel", Gimp.HistogramChannel.ALPHA)
    cfg.set_property("trc", Gimp.TRCType.LINEAR)
    filt.update()
    layer.append_filter(filt)
    return filt


def _curve_fn(amount, sign):
    """x + sign·d·4x(1−x)：两端不动，中间鼓起/凹下。"""
    def fn(x):
        return min(1.0, max(0.0, x + sign * amount * 4.0 * x * (1.0 - x)))
    return fn


# 五个控制点：三点的样条画这条抛物线会差 2.6 码，五点是 0.6 码，手柄也还在
# 一只手数得过来的范围里。
CURVE_STEPS = (0.0, 64 / 255.0, 128 / 255.0, 192 / 255.0, 1.0)


def _append_curve(layer, label, fn):
    """提亮 / 压暗曲线：SMOOTH 平滑样条，五个控制点。"""
    filt = Gimp.DrawableFilter.new(layer, "gimp:curves", label)
    cfg = filt.get_config()
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.SMOOTH)
    for x in CURVE_STEPS:
        curve.add_point(x, fn(x))
    cfg.set_property("curve", curve)
    cfg.set_property("channel", Gimp.HistogramChannel.VALUE)
    cfg.set_property("trc", Gimp.TRCType.NON_LINEAR)
    filt.update()
    layer.append_filter(filt)
    return filt


# ---- 动作 / the action ------------------------------------------------------

def dodge_burn(image, base, amount=0.12, make_group=True):
    """搭好提亮 / 压暗两条曲线层，蒙版全黑（等价于不动原图）。"""
    if base is None:
        raise RuntimeError(_("没有可以处理的图层 / no layer to work on"))
    if base.is_group():
        raise RuntimeError(
            _("图层组不能处理：请先选一个栅格图层（右键 → 合并组）"
              " / a layer group has no pixels of its own"))
    amount = min(0.4, max(0.01, float(amount)))

    parent = base.get_parent()
    position = _item_position(image, base)

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
            host = Gimp.GroupLayer.new(image, _("双曲线磨皮"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        layers = []
        for name, label, sign, channel_label in (
                (_("1 · 提亮（黑蒙版）"), _("1 · 提亮曲线"), +1.0, _("涂白提亮")),
                (_("2 · 压暗（黑蒙版）"), _("2 · 压暗曲线"), -1.0, _("涂白压暗"))):
            lay = Gimp.Layer.new_from_drawable(base, image)
            lay.set_name(name)
            lay.set_mode(Gimp.LayerMode.NORMAL)
            image.insert_layer(lay, host, 0)
            if base.has_alpha():
                _force_opaque(lay)
            _append_curve(lay, label, _curve_fn(amount, sign))
            mask = lay.create_mask(Gimp.AddMaskType.BLACK)
            if mask is not None:
                lay.add_mask(mask)
            layers.append(lay)

        _link_alpha_mask(image, base, host)

        # 选中最上面的压暗层，并把「编辑蒙版」打开：拿画笔直接涂就生效。
        try:
            image.set_selected_layers([layers[-1]])
            layers[-1].set_edit_mask(True)
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("双曲线磨皮已建立：提亮、压暗两层各挂一条曲线，蒙版全黑，"
                "所以现在与原图完全一致。点中某层的蒙版，用白色柔边画笔"
                "（不透明度 10–20%%）涂抹：涂提亮层变亮，涂压暗层变暗。"
                "强度 %g%%（0.5 处抬/压 %.2f）。") % (amount * 100.0, amount)
        if auto_group:
            msg += _("\n（这张图带透明，已自动分组：透明度靠组蒙版保住。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or layers[-1]


# ---- 程序包装 / procedure wrapper ------------------------------------------

class DodgeBurnPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-dodge-burn']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("双曲线磨皮 (Dodge & Burn)"))
        procedure.add_menu_path("<Image>/SuperMrWang/Shortcut")
        procedure.add_menu_path("<Layers>/SuperMrWang/Shortcut")

        procedure.set_documentation(
            _("双曲线磨皮：生成提亮、压暗两条曲线层，蒙版全黑。用白色柔边画笔"
              "在蒙版上涂抹，涂到哪里就提亮/压暗到哪里，没涂的地方与原图"
              "逐像素相同。"),
            _("Dodge & burn stack: a lighten curve and a darken curve on black "
              "masks. Paint white on a mask to dodge or burn; untouched pixels "
              "stay identical to the original."), name)
        procedure.add_double_argument(
            "amount", _("强度（%）"),
            _("曲线在中间调抬升/下压的幅度：12 表示 0.5 处抬 0.12（约 30 码）"),
            1.0, 40.0, 12.0, GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把两层放进一个「双曲线磨皮」穿透组里；关掉就直接叠在原图层上方"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if len(drawables) != 1:
            raise RuntimeError(_("请选择一个图层 / select exactly one layer"))
        dodge_burn(image, drawables[0],
                   config.get_property("amount") / 100.0,
                   config.get_property("group"))
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


if __name__ == '__main__':
    Gimp.main(DodgeBurnPlugin.__gtype__, sys.argv)
