#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 六向转换（通道 / 选区 / 蒙版）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   通道、选区、蒙版三者两两互转，六个方向一次点到位，不弹参数框。
           原生菜单里这六条路分散在三个地方（选择菜单、图层面板右键、通道
           右键），而且「蒙版 → 通道」根本没有直连，只能绕两步。这里把它们
           收进同一个 Convert 子菜单，按目标命名，一眼找得到。
           Six one-click conversions between channels, selections and layer
           masks. No parameter dialog: every direction reads its source from
           the current context and lands in the obvious place.

 menu      SuperMrWang → Convert → Channel to Selection
                              → Selection to Channel
                              → Channel to Mask
                              → Mask to Channel
                              → Selection to Mask
                              → Mask to Selection
           图层右键 → SuperMrWang → Convert（同样六项）
           通道右键 → SuperMrWang → Convert（以通道为源的那两项）

 usage     源从上下文推断，全自动：
           · 通道 = 通道面板里右键点中的那条；没有就用面板里选中的那条，
             图里只有一条通道时直接用它
           · 选区 = 当前的像素选区（没有选区就是全画布，GIMP 的既有语义）
           · 蒙版 = 选中的那个图层的图层蒙版
           目标也是固定的：选区落到画布、通道新建一条、蒙版挂到选中的图层
           （多选图层时每个都挂）。已有蒙版重建一张，结果与「原生新建」
           完全一致，重跑即刷新。

 numbers   **结果与 GIMP 原生逐位一致，这是硬指标。** 六个方向都不碰像素
           缓冲，一律转调 GIMP 自己的过程：

           通道 → 选区   gimp-image-select-item
           选区 → 通道   gimp-selection-save
           选区 → 蒙版   layer.create_mask(SELECTION)
           蒙版 → 选区   gimp-image-select-item
           通道 → 蒙版   原生没有直连，按原生的两步走：通道 → 选区 → 蒙版
           蒙版 → 通道   同上两步：蒙版 → 选区 → 通道

           这意味着中间灰会带着 GIMP 原生的那点漂移：默认 u8 非线性精度
           下，通道 128 进选区读回是 188，选区 128 存通道读回是 55。原生
           在「通道 ↔ 选区」交界处把 Y' 值当线性覆盖率直搬，不换算空间；
           而「选区 ↔ 蒙版」之间原生会换算，所以那一对不漂。32 位线性精度
           的图像上通道本身就存线性值，直搬恰好正确，六个方向都不漂。
           要的就是「原生怎样就怎样」，所以这里不做任何补偿。

 note      图层组没有像素，挂不了蒙版，会明确拒绝。
           选区 → 通道 / 蒙版 → 通道 在没有选区时先按 GIMP 语义全选，
           否则原生过程会拒绝执行。

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


# ---- PDB 小工具 / PDB helpers ----------------------------------------------

def _pdb(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


# ---- 源与目标 / sources and sinks ------------------------------------------

def selection_empty(image):
    sel = image.get_selection()
    return sel is None or not sel.bounds(image)[1]        # non_empty


def selection_all_if_empty(image):
    """原生过程在没有选区时会拒绝执行，这里按 GIMP 语义补一次全选。
    Native procedures refuse to run without a selection; select all first."""
    if selection_empty(image):
        _pdb('gimp-selection-all', image=image)


def _channels_in(items):
    return [i for i in (items or []) if isinstance(i, Gimp.Channel)]


def pick_channel(image, drawables=None):
    """取源通道，四路兜底：
    1. 上下文里点中的那条（从通道面板右键进来时，GIMP 直接把它作为 drawable
       传进来，此时它多半没有被记成「已选中」）；
    2. 通道面板里选中的那条；
    3. 图里只有一条通道时就是它（最常见的单通道场景，省得再点一次）；
    4. 都不成立才报错，并把现有通道名列出来。

    Four fallbacks, because GIMP's own select-item clears the channel selection
    afterwards: the item in context, then the dock selection, then the only
    channel in the image, then a clear error listing what is available."""
    for bucket in (_channels_in(drawables),
                   _channels_in(image.get_selected_drawables()),
                   _channels_in(image.get_selected_channels())):
        if bucket:
            return bucket[0]

    channels = image.get_channels()
    if len(channels) == 1:
        return channels[0]

    if not channels:
        raise RuntimeError(_("这张图没有通道，先在通道面板新建一条 "
                             "/ this image has no channels yet"))
    raise RuntimeError(
        _("要在通道面板里点一下要用的通道再运行（现有：%s）"
          " / click the channel to use in the Channels dock first (have: %s)")
        % (", ".join(c.get_name() for c in channels),
           ", ".join(c.get_name() for c in channels)))


def pick_layers(image, drawables):
    """取目标图层：上下文里的图层 → 图层面板里选中的 → 图里唯一的图层。
    Target layers: from the context, then the Layers dock, then the only layer.

    通道被选中时，GIMP 会把图层从选中项里顶掉，所以通道 → 蒙版那一步得靠
    这一步兜底；原生没有这个入口，没有「标准答案」可抄。"""
    layers = [d for d in (drawables or []) if isinstance(d, Gimp.Layer)]
    if not layers:
        layers = list(image.get_selected_layers())
    if not layers:
        all_layers = image.get_layers()
        if len(all_layers) == 1:
            layers = [all_layers[0]]
    if not layers:
        raise RuntimeError(
            _("选中的不是图层：请在图层面板选中要挂蒙版的图层，再从图层面板 "
              "右键运行 / no layer in context: select the target layer(s) in "
              "the Layers dock and run it from there"))
    return layers


def pick_masked_layer(image, drawables):
    """取第一个带蒙版的图层；都没有就说清楚。
    The first selected layer that actually has a mask."""
    for item in pick_layers(image, drawables):
        if item.get_mask() is not None:
            return item
    raise RuntimeError(
        _("选中的图层没有图层蒙版 / the selected layer has no layer mask"))


def unique_name(image, base):
    used = set(c.get_name() for c in image.get_channels())
    if base not in used:
        return base
    n = 2
    while "%s %d" % (base, n) in used:
        n += 1
    return "%s %d" % (base, n)


def check_layer(layer):
    """图层组没有像素，挂不了蒙版。
    A layer group has no pixels and cannot take a mask."""
    if layer.is_group():
        raise RuntimeError(
            _("图层组没有像素，挂不了蒙版：请先合并图层组 "
              "/ a layer group cannot take a mask"))


def drop_mask(image, layer):
    """已有蒙版先丢掉，让下面的 create_mask(SELECTION) 与原生新建同源。
    Drop the existing mask so the new one is built exactly like a fresh one."""
    if layer.get_mask() is not None:
        _pdb('gimp-layer-remove-mask', layer=layer,
             mode=Gimp.MaskApplyMode.DISCARD)


def save_selection_as_channel(image, base):
    """当前选区存成通道（原生 gimp-selection-save），再改成好认的名字。
    Save the selection as a channel with the native procedure, then rename."""
    selection_all_if_empty(image)
    channel = _pdb('gimp-selection-save', image=image).index(1)
    channel.set_name(unique_name(image, base))
    return channel


def apply_selection_mask(image, drawables):
    """把当前选区挂成所选图层的蒙版（原生 create_mask(SELECTION)）。
    Install the current selection as a mask via the native mask type."""
    selection_all_if_empty(image)
    masks = []
    for layer in pick_layers(image, drawables):
        check_layer(layer)
        drop_mask(image, layer)
        mask = layer.create_mask(Gimp.AddMaskType.SELECTION)
        layer.add_mask(mask)
        masks.append(mask)
    return masks


# ---- 六个方向 / the six directions ----------------------------------------

def channel_to_selection(image, drawables=None):
    """原生 gimp-image-select-item：通道值当线性覆盖率直搬。
    Native select-item: the channel's values are taken as linear coverage."""
    channel = pick_channel(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, channel)
    return channel


def selection_to_channel(image):
    return save_selection_as_channel(image, "Selection")


def channel_to_mask(image, drawables):
    """原生两步：通道 → 选区 → 蒙版（GIMP 3 没有通道直接建蒙版的入口）。
    Native two steps: channel -> selection -> mask; GIMP 3 has no direct one."""
    channel = pick_channel(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, channel)
    return channel, apply_selection_mask(image, drawables)


def mask_to_channel(image, drawables):
    """原生两步：蒙版 → 选区 → 通道。
    Native two steps: mask -> selection -> channel."""
    layer = pick_masked_layer(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, layer.get_mask())
    return save_selection_as_channel(image, "%s Mask" % layer.get_name())


def selection_to_mask(image, drawables):
    return apply_selection_mask(image, drawables)


def mask_to_selection(image, drawables):
    layer = pick_masked_layer(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, layer.get_mask())
    return layer


# ---- 程序包装 / procedure wrapper ------------------------------------------

# 名字 → (菜单标签, 动作, 说明)
DIRECTIONS = [
    ('lb-plugin-conv-channel-to-selection',
     'Channel to Selection',
     'channel-to-selection',
     _("Take the channel selected in the Channels dock and turn it into the "
       "pixel selection."),
     _("通道 → 选区：把通道面板里选中的那条通道变成像素选区")),
    ('lb-plugin-conv-selection-to-channel',
     'Selection to Channel',
     'selection-to-channel',
     _("Save the current selection as a new channel."),
     _("选区 → 通道：把当前选区存成一条新通道")),
    ('lb-plugin-conv-channel-to-mask',
     'Channel to Mask',
     'channel-to-mask',
     _("Use the selected channel's grey levels as a layer mask on every "
       "selected layer."),
     _("通道 → 蒙版：用选中通道的灰度做所选图层的蒙版")),
    ('lb-plugin-conv-mask-to-channel',
     'Mask to Channel',
     'mask-to-channel',
     _("Turn the selected layer's layer mask into a new channel."),
     _("蒙版 → 通道：把所选图层的蒙版变成一条新通道")),
    ('lb-plugin-conv-selection-to-mask',
     'Selection to Mask',
     'selection-to-mask',
     _("Use the current selection as a layer mask on every selected layer."),
     _("选区 → 蒙版：把当前选区挂成所选图层的蒙版")),
    ('lb-plugin-conv-mask-to-selection',
     'Mask to Selection',
     'mask-to-selection',
     _("Turn the selected layer's layer mask into the pixel selection."),
     _("蒙版 → 选区：把所选图层的蒙版变成像素选区")),
]

BY_KEY = dict((d[2], d) for d in DIRECTIONS)


class ConvertPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return [d[0] for d in DIRECTIONS]

    def do_create_procedure(self, name):
        key = name[len('lb-plugin-conv-'):]
        proc_name, label, _direction, doc_en, doc_zh = BY_KEY[key]

        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*, INDEXED*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        # 零参数：源和目标都从上下文推断，点菜单直接执行，不弹对话框。
        # No arguments at all: source and sink come from the context, so the
        # menu item runs straight away instead of opening a dialog.
        procedure.set_documentation(doc_en, doc_zh, name)
        procedure.set_menu_label(_(label))
        procedure.add_menu_path("<Image>/SuperMrWang/Convert")
        procedure.add_menu_path("<Layers>/SuperMrWang/Convert")
        if key.startswith('channel-to'):
            # 以通道为源的两条也挂到通道面板右键：GIMP 会把点中的那条作为
            # drawable 传进来，取源不用再去别处点一下。
            # The two channel-source directions also live in the Channels dock
            # context menu, where GIMP hands the clicked channel over.
            procedure.add_menu_path("<Channels>/SuperMrWang/Convert")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image")))

        key = procedure.get_name()[len('lb-plugin-conv-'):]
        try:
            if key == 'channel-to-selection':
                src = channel_to_selection(image, drawables)
                note = _("通道「%s」→ 选区") % src.get_name()
            elif key == 'selection-to-channel':
                dst = selection_to_channel(image)
                note = _("选区 → 通道「%s」") % dst.get_name()
            elif key == 'channel-to-mask':
                src, masks = channel_to_mask(image, drawables)
                note = _("通道「%s」→ %d 个图层的蒙版") % (src.get_name(),
                                                          len(masks))
            elif key == 'mask-to-channel':
                dst = mask_to_channel(image, drawables)
                note = _("蒙版 → 通道「%s」") % dst.get_name()
            elif key == 'selection-to-mask':
                masks = selection_to_mask(image, drawables)
                note = _("选区 → %d 个图层的蒙版") % len(masks)
            elif key == 'mask-to-selection':
                src = mask_to_selection(image, drawables)
                note = _("蒙版「%s」→ 选区") % src.get_name()
            else:
                raise RuntimeError(_("未知方向 / unknown direction"))
        except Exception as exc:
            Gimp.message("convert: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))

        Gimp.displays_flush()
        try:
            Gimp.message(note)
        except Exception:
            pass
        return procedure.new_return_values(
            Gimp.PDBStatusType.SUCCESS, GLib.Error())


if __name__ == '__main__':
    Gimp.main(ConvertPlugin.__gtype__, sys.argv)
