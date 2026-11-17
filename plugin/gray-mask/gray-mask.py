#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 灰度图层 → 选区 / Alpha 通道 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把一张黑白（灰度）图层一键变成选区或新建 Alpha 通道。
           原生做法要绕三步：加图层蒙版（灰度副本）→ 蒙版至选区 →
           存储到通道。本插件把这条链压成一次点击，链上的 GEGL 蒙版算子
           （lb:color-mask-select 等）输出的黑白层可以直接接管后续流程。
           Turn a grayscale layer into a selection or a new alpha channel in
           one click; natively this takes mask + mask-to-selection + save.
 menu      SuperMrWang → Convert → Grayscale Layer to Selection / to Channel
 usage     选中黑白图层后点击菜单；批处理用注册参数（operation 0..3、
           invert、name）。核心逻辑在模块级函数里，tools/check_gray_mask.py
           直接调用它们做回归。
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject


def _N_(message):
    return message


def _(message):
    return GLib.dgettext(None, message)


# ---- 核心逻辑（模块级，供回归脚本直接调用） ---------------------------------

def _anchor_pdb(floating):
    """GIMP 3 的锚定只能走 PDB / GIMP 3 anchors via the PDB procedure."""
    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure('gimp-floating-sel-anchor')
    cfg = proc.create_config()
    cfg.set_property('floating-sel', floating)
    proc.run(cfg)


def _pdb_run(name, **props):
    """按名调用 PDB 过程 / call a PDB procedure by name"""
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def _save_selection(image):
    """有选区时先存成通道，返回它；没有选区返回 None。
    Save the current selection into a channel (None if empty)."""
    sel = image.get_selection()
    if not sel.bounds(image)[1]:        # non_empty
        return None
    return _pdb_run('gimp-selection-save', image=image).index(1)


def channel_from_drawable(image, drawable, name):
    """把任意图层的内容转成画布大小的灰度通道，位置与画布对齐。
    Copy a drawable's content into a canvas-sized grayscale channel.

    三个关键点：
    1. edit_copy 会被当前选区裁剪（与选区不相交时复制为空）——复制前
       全选，复制后恢复原选区；
    2. edit_paste 会把内容居中放置，必须 set_offsets 挪回源图层的画布
       位置再锚定；
    3. GIMP 3 里 buffer 不能直接塞进 gegl:buffer-source（python-eval
       段错误），所以走复制/粘贴。
    """
    ok, ox, oy = drawable.get_offsets()

    channel = Gimp.Channel.new(image, name, image.get_width(), image.get_height(),
                               100.0, Gegl_color())
    image.insert_channel(channel, None, -1)

    image.undo_group_start()
    try:
        saved = _save_selection(image)
        _pdb_run('gimp-selection-all', image=image)
        if not Gimp.edit_copy([drawable]):
            raise RuntimeError("copy failed: empty drawable?")
        floating = Gimp.edit_paste(channel, False)[0]
        floating.set_offsets(ox, oy)
        _anchor_pdb(floating)
        if saved is not None:
            image.select_item(Gimp.ChannelOps.REPLACE, saved)
            image.remove_channel(saved)
    finally:
        image.undo_group_end()
    return channel


def Gegl_color():
    """通道显示用的辅助色（淡紫）/ helper tint colour for the channel icon"""
    from gi.repository import Gegl
    c = Gegl.Color()
    c.set_rgba(0.5, 0.5, 1.0, 1.0)
    return c


def gray_to_selection(image, drawable, operation, invert):
    """黑白图层 → 选区。operation: 0 Replace / 1 Add / 2 Subtract / 3 Intersect"""
    ops = (Gimp.ChannelOps.REPLACE, Gimp.ChannelOps.ADD,
           Gimp.ChannelOps.SUBTRACT, Gimp.ChannelOps.INTERSECT)
    op = ops[operation]

    image.undo_group_start()
    try:
        channel = channel_from_drawable(image, drawable, 'lb-gray-to-selection')
        image.select_item(op, channel)
        image.remove_channel(channel)
        if invert:
            pdb_in = Gimp.get_pdb().lookup_procedure('gimp-selection-invert')
            cfg = pdb_in.create_config()
            cfg.set_property('image', image)
            pdb_in.run(cfg)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()


def gray_to_channel(image, drawable, invert, name):
    """黑白图层 → 新建 Alpha 通道。name 为空时沿用图层名。"""
    if not name:
        name = drawable.get_name()
    channel = channel_from_drawable(image, drawable, name)
    if invert:
        channel.invert(False)
    Gimp.displays_flush()
    return channel


# ---- 程序包装 / procedure wrappers ------------------------------------------

class GrayMaskPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-gray-to-selection', 'lb-plugin-gray-to-channel']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*, INDEXED*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        # 注意：add_menu_path 必须在 set_menu_label 之后，否则 GIMP 报
        # 「priv->menu_label != NULL」断言失败，菜单项直接不挂。
        # add_menu_path has to come after set_menu_label, or GIMP fails the
        # 'priv->menu_label != NULL' assertion and the entry never appears.

        if name.endswith('to-selection'):
            procedure.set_documentation(
                _("Grayscale Layer to Selection: turn the active layer's "
                  "grayscale content into the current selection"),
                _("One-click 'grayscale layer -> selection' (mask-copy + "
                  "mask-to-selection fused)."), name)
            procedure.set_menu_label(_("Grayscale Layer to Selection"))
            procedure.add_menu_path("<Image>/SuperMrWang/Convert")
            procedure.add_int_argument(
                "operation", _("Combine"),
                _("0 Replace, 1 Add, 2 Subtract, 3 Intersect"),
                0, 3, 0, GObject.ParamFlags.READWRITE)
            procedure.add_boolean_argument(
                "invert", _("Invert"),
                _("Select the black side instead of the white side"),
                False, GObject.ParamFlags.READWRITE)
        else:
            procedure.set_documentation(
                _("Grayscale Layer to Channel: copy the active layer's "
                  "grayscale content into a new alpha channel"),
                _("One-click 'grayscale layer -> channel'."), name)
            procedure.set_menu_label(_("Grayscale Layer to Channel"))
            procedure.add_menu_path("<Image>/SuperMrWang/Convert")
            procedure.add_boolean_argument(
                "invert", _("Invert"), _("Invert the channel content"),
                False, GObject.ParamFlags.READWRITE)
            procedure.add_string_argument(
                "name", _("Channel name"),
                _("Empty = use the layer name"), "",
                GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no active layer")))
        try:
            drawable = drawables[0]
            if procedure.get_name().endswith('to-selection'):
                gray_to_selection(image, drawable,
                                  config.get_property('operation'),
                                  config.get_property('invert'))
            else:
                gray_to_channel(image, drawable,
                                config.get_property('invert'),
                                config.get_property('name'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("gray-mask: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(GrayMaskPlugin.__gtype__, sys.argv)
