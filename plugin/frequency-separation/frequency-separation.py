#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 高低频磨皮 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   一次点击搭好「低频 / 高频」两张可编辑图层：低频管影调与颜色，高频
           管毛孔、痘印这类细节，两层叠起来就是原图。修皮肤时在低频层上抹
           平色块、在高频层上克隆或涂抹细节，互不干扰——这就是常说的
           frequency separation。
           Build a low/high frequency pair in one click: tone and colour live
           on the low layer, pores and blemishes on the high layer, and the
           two recombine to the original pixel for pixel.

 menu      SuperMrWang → Shortcut → 高低频磨皮 (Frequency Separation)
           图层右键 → SuperMrWang → Shortcut → 高低频磨皮

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              高低频磨皮            组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 2 · 高频（细节）  模式 = 颗粒合并   滤镜 = 高通
                ├─ 1 · 低频（影调）  模式 = 正常       滤镜 = 高斯模糊
                └─ 原图层（不动，可以隐藏）

           合成关系（编码值，0…1）：

              低频 L = 高斯模糊(原图, r)
              高频 H = 0.5 + (原图 − L)        ← 中灰偏移的细节图
              颗粒合并(H, L) = H + L − 0.5 = 原图

           所以恒等时两层自己就能还原原图，把原图层隐藏掉也不掉东西。想改
           磨皮力度就调低频层的模糊半径（图层面板 → 滤镜 → 高斯模糊），或
           直接在高频层上涂抹：频率分界由半径决定，半径越大细节越少。

 note      为什么高频层用「颗粒合并」而不是常见的「颗粒提取」：颗粒提取只是
           把 (原图 − L) 显示成灰图，它自己不能与低频层拼回原图；要让
           H + L − 0.5 = 原图，H 必须携带 +0.5 的偏移，落点就是颗粒合并。

           为什么 high-pass 的 contrast 钉成 2：gegl:high-pass 的 contrast
           是「差值放大倍数的一半」——默认 1 只输出 0.5 + 0.5·(原图 − 模糊)，
           叠回去还差一半细节。实测 contrast=2 时 H 与 0.5 + (原图 − L) 逐
           像素一致（8 位图上差 1 码以内），这也是本插件不自己写算子的原因。

           注意事项：
           - 高频层是中灰偏移图，单独看是一张灰蒙蒙的图，这是正常的；它的
             内容在「颗粒合并」模式下才与低频层合成为彩色。
           - 两层都带非破坏滤镜，原图不动；调半径随时可逆。
           - 极端反差的边缘（比如黑边贴着白墙）在中灰偏移后可能超出 0…1，
             8 位图会裁掉一点（最多 2 码），32 位浮点图不裁。人像皮肤不会
             碰到这个范围。
           - 图层组输入会被拒绝：组没有自己的像素。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject


def _(message):
    return GLib.dgettext(None, message)


BLUR_OP = "gegl:gaussian-blur"
HIGHPASS_OP = "gegl:high-pass"


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
    """把原图层的 alpha 变成整组的蒙版（组内两层保持不透明）。"""
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
    """把 alpha 拉满：透明度只由组蒙版负责，避免混合模式按半透明做插值。"""
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


def _append_blur(layer, radius):
    filt = Gimp.DrawableFilter.new(layer, BLUR_OP, _("高斯模糊（低频）"))
    cfg = filt.get_config()
    cfg.set_property("std-dev-x", float(radius))
    cfg.set_property("std-dev-y", float(radius))
    filt.update()
    layer.append_filter(filt)
    return filt


def _append_highpass(layer, radius):
    filt = Gimp.DrawableFilter.new(layer, HIGHPASS_OP, _("高通（高频）"))
    cfg = filt.get_config()
    cfg.set_property("std-dev", float(radius))
    # contrast 是「差值放大倍数的一半」，2 才输出完整的 (原图 − 模糊)。
    cfg.set_property("contrast", 2.0)
    filt.update()
    layer.append_filter(filt)
    return filt


# ---- 动作 / the action ------------------------------------------------------

def separate(image, base, radius=8.0, make_group=True):
    """把图层拆成低频 + 高频两层；恒等时两层合成 = 原图。"""
    if base is None:
        raise RuntimeError(_("没有可以拆分的图层 / no layer to split"))
    if base.is_group():
        raise RuntimeError(
            _("图层组不能拆分：请先选一个栅格图层（右键 → 合并组）"
              " / a layer group has no pixels of its own"))
    radius = max(0.2, float(radius))

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
            host = Gimp.GroupLayer.new(image, _("高低频磨皮"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        low = Gimp.Layer.new_from_drawable(base, image)
        low.set_name(_("1 · 低频（影调）"))
        low.set_mode(Gimp.LayerMode.NORMAL)
        image.insert_layer(low, host, 0)
        if base.has_alpha():
            _force_opaque(low)
        _append_blur(low, radius)

        high = Gimp.Layer.new_from_drawable(base, image)
        high.set_name(_("2 · 高频（细节）"))
        high.set_mode(Gimp.LayerMode.GRAIN_MERGE)
        image.insert_layer(high, host, 0)
        if base.has_alpha():
            _force_opaque(high)
        _append_highpass(high, radius)

        _link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([high])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("高低频磨皮已建立：低频层（高斯模糊 %g px，管影调与颜色）、"
                "高频层（颗粒合并，管毛孔与痘印）。原图层可以隐藏，两层自己"
                "就能还原。改磨皮力度＝改低频层的高斯模糊半径。") % radius
        if auto_group:
            msg += _("\n（这张图带透明，已自动分组：透明度靠组蒙版保住。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or high


# ---- 程序包装 / procedure wrapper ------------------------------------------

class FrequencySeparationPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-frequency-separation']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("高低频磨皮 (Frequency Separation)"))
        procedure.add_menu_path("<Image>/SuperMrWang/Shortcut")
        procedure.add_menu_path("<Layers>/SuperMrWang/Shortcut")

        procedure.set_documentation(
            _("高低频磨皮：一次生成低频（高斯模糊，管影调与颜色）与高频"
              "（颗粒合并，管细节与质感）两层，恒等时合成就是原图。在低频层"
              "抹平色块、在高频层修细节，互不干扰。"),
            _("Frequency separation: one click builds a blurred low-frequency "
              "layer (tone/colour) and a high-pass high-frequency layer "
              "(detail) that recombine to the original."), name)
        procedure.add_double_argument(
            "radius", _("分离半径（px）"),
            _("高斯模糊的标准差。越大，进低频的东西越多、高频留下的细节越少"),
            0.2, 100.0, 8.0, GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把两层放进一个「高低频磨皮」穿透组里；关掉就直接叠在原图层上方"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if len(drawables) != 1:
            raise RuntimeError(_("请选择一个图层 / select exactly one layer"))
        separate(image, drawables[0],
                 config.get_property("radius"),
                 config.get_property("group"))
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


if __name__ == '__main__':
    Gimp.main(FrequencySeparationPlugin.__gtype__, sys.argv)
