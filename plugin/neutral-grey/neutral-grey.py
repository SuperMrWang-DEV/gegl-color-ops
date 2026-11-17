#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 中性灰磨皮 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   一次点击加一张 50% 中性灰图层，混合模式柔光。中性灰在柔光下对
           底图是恒等变换——什么都不改；拿白色软画笔在灰层上涂就是提亮、
           拿黑色涂就是压暗。皮肤的不平靠这一点点加减推平，原图像素一个
           都没动，随时可以整层删掉重来。
           A 50% grey layer in Soft Light: identity on the backdrop, so white
           strokes dodge and black strokes burn without touching the pixels
           underneath.

 menu      颜色 → SuperMrWang → Shortcut → 中性灰磨皮 (Neutral Grey)
           图层右键 → SuperMrWang → Shortcut → 中性灰磨皮

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              中性灰磨皮                    组，穿透混合（带 alpha 时组上还有蒙版）
                ├─ 1 · 中性灰（白提亮/黑压暗） 模式 = 柔光，整层 50% 灰
                └─ 原图层（不动，可以隐藏）

           刚建好时灰层是纯 0.5 灰，柔光叠上去与原图逐像素相同。开始修：

             1. 点中「1 · 中性灰」这一层；
             2. 柔边画笔，不透明度 5–15%，流量 10–30%；
             3. 白色涂＝提亮（推平暗斑、眼袋），黑色涂＝压暗（收一收高光、
                压住油光）。涂过头就用 50% 灰（#808080）盖回去。

 note      为什么是柔光而不是叠加：柔光在 0.5 处是恒等映射，且斜率平缓，
           一两笔的改动落在几个码以内，适合反复叠加微调；叠加模式在 0.5 处
           虽然也恒等，但斜率是 2 倍，同样力度下手重一倍、更容易出色斑。

           图层用 0.5 的编码值填充（8 位图上就是 128），不是 Lab 中灰：
           Lab 的 L*=50 换算到 sRGB 是 0.46 左右，柔光叠上去会把整张图压暗
           一点点，起不到「什么都不改」的作用。

           带 alpha 的图会自动分组：灰层本身铺满图层范围，组蒙版用原图
           alpha 把透明区域切掉，不会把抠图的边缘涂实。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import array
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GLib, GObject, Gegl


def _(message):
    return GLib.dgettext(None, message)


MID_GREY = 0.5


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


def _fill_grey(layer):
    """把整层写成 0.5 编码灰（8 位图即 128），不走上下文的前景色。

    写完必须 flush 再 update：只改私有 buffer 而不通知核心，投影和图层
    缩略图还停在「新建图层的空内容」上，界面上这张「中性灰」会显示成
    一块黑（无 alpha 的图尤其明显）。导出能拿到正确像素，肉眼却是黑的
    ——GIMP 3 的坑，和 blend 那边一样。
    Without the flush + update the private buffer holds 0.5 but the
    projection is never invalidated, so the layer shows up black."""
    w, h = layer.get_width(), layer.get_height()
    rect = Gegl.Rectangle.new(0, 0, w, h)
    buf = layer.get_buffer()
    if layer.has_alpha():
        px = array.array('f', [MID_GREY, MID_GREY, MID_GREY, 1.0] * (w * h))
        buf.set(rect, "R'G'B'A float", px.tobytes())
    else:
        px = array.array('f', [MID_GREY, MID_GREY, MID_GREY] * (w * h))
        buf.set(rect, "R'G'B' float", px.tobytes())
    buf.flush()
    layer.update(0, 0, w, h)


# ---- 动作 / the action ------------------------------------------------------

def neutral_grey(image, base, make_group=True):
    """在原图层上方加一张 50% 灰的柔光层；恒等时结果 = 原图。"""
    if base is None:
        raise RuntimeError(_("没有可以处理的图层 / no layer to work on"))
    if base.is_group():
        raise RuntimeError(
            _("图层组不能处理：请先选一个栅格图层（右键 → 合并组）"
              " / a layer group has no pixels of its own"))

    parent = base.get_parent()
    position = _item_position(image, base)
    w, h = base.get_width(), base.get_height()
    try:
        ok, ox, oy = base.get_offsets()
        if not ok:
            ox = oy = 0
    except Exception:
        ox = oy = 0

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
            host = Gimp.GroupLayer.new(image, _("中性灰磨皮"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        itype = (Gimp.ImageType.RGBA_IMAGE if base.has_alpha()
                 else Gimp.ImageType.RGB_IMAGE)
        lay = Gimp.Layer.new(image, _("1 · 中性灰（白提亮 / 黑压暗）"),
                             w, h, itype, 100.0, Gimp.LayerMode.SOFTLIGHT)
        image.insert_layer(lay, host, 0)
        lay.set_offsets(ox, oy)
        _fill_grey(lay)

        _link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([lay])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("中性灰磨皮已建立：一张 50% 灰的柔光层，现在与原图完全一致。"
                "点中这一层，用柔边画笔（不透明度 5–15%）涂抹：白色提亮、"
                "黑色压暗，涂过头用 #808080 盖回去。")
        if auto_group:
            msg += _("\n（这张图带透明，已自动分组：透明度靠组蒙版保住。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or lay


# ---- 程序包装 / procedure wrapper ------------------------------------------

class NeutralGreyPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-neutral-grey']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("中性灰磨皮 (Neutral Grey)"))
        procedure.add_menu_path("<Image>/Colors/SuperMrWang/Shortcut")
        procedure.add_menu_path("<Layers>/SuperMrWang/Shortcut")

        procedure.set_documentation(
            _("中性灰磨皮：加一张 50% 灰的柔光层，恒等时与原图逐像素相同。"
              "白色画笔提亮、黑色画笔压暗，反复涂抹把皮肤推平。"),
            _("Neutral grey dodge & burn: a 50% grey Soft Light layer, identity "
              "on the backdrop; paint white to lighten, black to darken."), name)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把灰层放进一个「中性灰磨皮」穿透组里；关掉就直接叠在原图层上方"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if len(drawables) != 1:
            raise RuntimeError(_("请选择一个图层 / select exactly one layer"))
        neutral_grey(image, drawables[0], config.get_property("group"))
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


if __name__ == '__main__':
    Gimp.main(NeutralGreyPlugin.__gtype__, sys.argv)
