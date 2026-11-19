#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 通道 → 图层蒙版 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   选中一条通道、点一下，就把它变成所选图层的图层蒙版。原生流程是
           「图层 → 蒙版 → 添加图层蒙版 → 选区 → 通道再转选区」，而且一次
           只能对付一个图层；本插件从右键进来，多选几个图层一次做完，还能
           顺手反相。与 layer-to-channel 正好构成一对反向操作。
           Turn a channel into a layer mask on the selected layer(s), straight
           from the layer context menu — the reverse of layer-to-channel.

 menu      图层右键 → SuperMrWang → Mask → Channel to Mask…
           通道面板右键 → SuperMrWang → Mask（右键点中的那条就是源）
           也挂在 SuperMrWang → Mask 下，方便不用鼠标右键的场合。

 usage     **通道从哪来**：通道面板里右键点中的那条 → 面板里选中的那条 →
           图里唯一的通道；也可以在参数里填通道名指定。**蒙版往哪去**：图层面板
           里选中的图层（可多选），每个都挂一份同样的蒙版内容；通道被选中时
           GIMP 会把图层从选中项里顶掉，这时图里只有一层就直接挂它。
           · 图层还没有蒙版 → 按原生方式新建
           · 图层已经有蒙版 → 先丢掉旧的再新建，结果与原生新建完全一致
           · 反相 = 蒙版黑白对调，等于「按通道的补集遮罩」
           **灰度值即遮罩强度**：黑 = 完全遮住，白 = 完全露出，中间灰 = 半透明。

 numbers   **逐位跟随原生。** GIMP 3 没有「通道直接建蒙版」的入口，原生用户
           只能走两步：通道 → 选区 → 选区建蒙版。这里就走同一条路：
           gimp-image-select-item 取通道，create_mask(SELECTION) 建蒙版。
           因此中间灰带着原生的那点漂移——默认 u8 非线性精度下，通道 128
           建出来的蒙版是 188（原生把 Y' 当线性覆盖率直搬）。32 位线性精度
           的图上不漂。要的就是「原生怎样就怎样」，不做补偿。

 note      反相在原生里没有对应动作，做法是先清掉选区再对蒙版整体反相，
           否则反相会只作用于选区内的部分。反相之后选区为空。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject


def _N_(message):
    return message


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


# ---- PDB 小工具 / PDB helpers ----------------------------------------------

def _pdb(name, **props):
    """按名调用 PDB 过程 / call a PDB procedure by name"""
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


# ---- 通道选择 / pick the source channel ------------------------------------

def pick_channel(image, name="", drawables=None):
    """按名字找通道；名字为空则取上下文里的通道。
    Find a channel by name, or take the one in context.

    顺序：参数里点的名字 → 右键点中的那条 → 通道面板里选中的 → 图里唯一的
    通道。GIMP 自己的 select-item 跑完会把通道选中状态清掉，所以后面几路
    兜底是必须的，否则重复运行会误报「没选中通道」。"""
    channels = image.get_channels()
    if name:
        for ch in channels:
            if ch.get_name() == name:
                return ch
        raise RuntimeError(_("No channel named \"%s\".")
                           % (name, name))

    def _chans(items):
        return [i for i in (items or []) if isinstance(i, Gimp.Channel)]

    for bucket in (_chans(drawables),
                   _chans(image.get_selected_drawables()),
                   _chans(image.get_selected_channels())):
        if bucket:
            return bucket[0]

    if len(channels) == 1:
        return channels[0]
    if not channels:
        raise RuntimeError(_("This image has no channels yet; create one in the Channels dock first."))

    raise RuntimeError(
        _("Click the channel to use in the Channels dock and run again (available: %s), or fill in a channel name.")
        % ", ".join(c.get_name() for c in channels))


def resolve_layers(image, drawables):
    """目标图层：上下文 → 图层面板选中 → 图里唯一的那层。
    Selecting a channel deselects layers, so a fallback is needed to keep the
    Channels-dock route usable."""
    layers = [d for d in (drawables or []) if isinstance(d, Gimp.Layer)]
    if not layers:
        layers = list(image.get_selected_layers())
    if not layers:
        all_layers = image.get_layers()
        if len(all_layers) == 1:
            layers = [all_layers[0]]
    return layers


# ---- 动作 / the action ------------------------------------------------------

def channel_to_mask(image, layer, channel, invert=False):
    """给一个图层挂上「通道 → 蒙版」，返回那块蒙版。

    走的就是原生那两步：通道变选区，再用选区建蒙版。invert 为真时黑白对调。
    Same two steps the native UI takes: channel to selection, selection to
    mask. invert flips black and white afterwards."""
    if layer is None:
        raise RuntimeError(_("No layer selected."))
    if layer.is_group():
        raise RuntimeError(_("A layer group has no pixels and cannot take a mask; merge the group first."))

    image.undo_group_start()
    try:
        image.select_item(Gimp.ChannelOps.REPLACE, channel)

        if layer.get_mask() is not None:    # 丢掉旧的，结果与原生新建一致
            _pdb('gimp-layer-remove-mask', layer=layer,
                 mode=Gimp.MaskApplyMode.DISCARD)

        mask = layer.create_mask(Gimp.AddMaskType.SELECTION)
        layer.add_mask(mask)

        if invert:
            # 反相也遵守选区，先清掉选区才是整块蒙版对调。
            # Invert honours the selection, so drop it before flipping.
            _pdb('gimp-selection-none', image=image)
            mask.invert(False)
    finally:
        image.undo_group_end()

    return mask


# ---- 程序包装 / procedure wrapper ------------------------------------------

class ChannelToMaskPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return ['lb-plugin-channel-to-mask']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*, INDEXED*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("Channel to Mask..."))
        procedure.add_menu_path("<Layers>/SuperMrWang/Mask")
        procedure.add_menu_path("<Image>/SuperMrWang/Mask")
        # 通道面板右键：GIMP 会把点中的通道作为 drawable 传进来
        procedure.add_menu_path("<Channels>/SuperMrWang/Mask")

        procedure.set_documentation(
            _("Channel to Mask: take a channel (the one selected in the "
              "Channels dock, or one you name) and use its grey levels as a "
              "layer mask on the selected layer(s). Black hides, white shows, "
              "mid grey is partial. Results match GIMP's own channel-to-"
              "selection-to-mask route exactly; layers that already have a "
              "mask get a fresh one built the same way."),
            _("One click 'channel -> layer mask' for every selected layer. "
              "Grey levels become mask strength; invert flips black and "
              "white. The reverse of Layer to Channel."), name)

        procedure.add_string_argument(
            "channel-name", _("Channel name"),
            _("Empty = the channel currently selected in the Channels dock"),
            "", GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "invert", _("Invert"),
            _("Swap black and white: mask by the channel's complement"),
            False, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))

        name = config.get_property('channel-name')
        invert = config.get_property('invert')
        try:
            channel = pick_channel(image, name, drawables)
            layers = resolve_layers(image, drawables)
            done = 0
            for layer in layers:
                channel_to_mask(image, layer, channel, invert)
                done += 1
            if not done:
                raise RuntimeError(_("Nothing selected but layers."))
        except Exception as exc:
            Gimp.message("channel-to-mask: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))

        Gimp.displays_flush()
        try:
            Gimp.message(_("Masked %d layer(s) with channel \u201c%s\u201d%s")
                         % (done, channel.get_name(),
                            _(" (inverted)") if invert else ""))
        except Exception:
            pass
        return procedure.new_return_values(
            Gimp.PDBStatusType.SUCCESS, GLib.Error())


if __name__ == '__main__':
    Gimp.main(ChannelToMaskPlugin.__gtype__, sys.argv)
