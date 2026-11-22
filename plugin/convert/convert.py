#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 六向转换（通道 / 选区 / 蒙版）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   通道、选区、蒙版、路径四者两两互转，十二个方向一次点到位，不弹参
           数框。原生菜单里这些路分散在四个地方（选择菜单、图层面板右键、通
           道右键、路径右键），而且「蒙版 → 通道」「通道 → 路径」这类没有直
           连，只能绕两步。这里把它们收进同一个 Convert 子菜单，按目标命名，
           一眼找得到。
           Twelve one-click conversions between channels, selections, layer
           masks and paths. No parameter dialog: every direction reads its
           source from the current context and lands in the obvious place.

 menu      SuperMrWang → Convert → Channel to Selection
                              → Selection to Channel
                              → Channel to Mask
                              → Mask to Channel
                              → Selection to Mask
                              → Mask to Selection
                              → Path to Selection
                              → Selection to Path
                              → Path to Channel
                              → Channel to Path
                              → Path to Mask
                              → Mask to Path
           图层右键 → SuperMrWang → Convert（同样十二项）
           通道右键 → SuperMrWang → Convert（以通道为源的那三项）
           路径右键 → SuperMrWang → Convert（以路径为源的那三项）

 usage     源从上下文推断，全自动：
           · 通道 = 通道面板里右键点中的那条；没有就用面板里选中的那条，
             图里只有一条通道时直接用它
           · 选区 = 当前的像素选区（没有选区就是全画布，GIMP 的既有语义）
           · 蒙版 = 选中的那个图层的图层蒙版
           · 路径 = 路径面板里右键点中的那条；没有就用面板里选中的，
             图里只有一条路径时直接用它
           目标也是固定的：选区落到画布、通道新建一条、蒙版挂到选中的图层
           （多选图层时每个都挂）、路径新建一条。已有蒙版重建一张，结果与
           「原生新建」完全一致，重跑即刷新。

 numbers   **结果与 GIMP 原生逐位一致，这是硬指标。** 十二个方向都不碰像素
           缓冲，一律转调 GIMP 自己的过程：

           通道 → 选区   gimp-image-select-item
           选区 → 通道   gimp-selection-save
           选区 → 蒙版   layer.create_mask(SELECTION)
           蒙版 → 选区   gimp-image-select-item
           通道 → 蒙版   原生没有直连，按原生的两步走：通道 → 选区 → 蒙版
           蒙版 → 通道   同上两步：蒙版 → 选区 → 通道

           路径这一组同样只有原生那两步可用：
           路径 → 选区   gimp-image-select-item
           选区 → 路径   plug-in-sel2path（「选择 → 路径」背后的过程）
           通道/蒙版 → 路径   先 select-item 再 sel2path
           路径 → 通道/蒙版   先 select-item 再存通道 / 挂蒙版

           这意味着中间灰会带着 GIMP 原生的那点漂移：默认 u8 非线性精度
           下，通道 128 进选区读回是 188，选区 128 存通道读回是 55。原生
           在「通道 ↔ 选区」交界处把 Y' 值当线性覆盖率直搬，不换算空间；
           而「选区 ↔ 蒙版」之间原生会换算，所以那一对不漂。32 位线性精度
           的图像上通道本身就存线性值，直搬恰好正确，那六个方向都不漂。
           要的就是「原生怎样就怎样」，所以这里不做任何补偿。
           路径只有几何、没有 alpha，凡是「位图 → 路径」都按 50% 等值线
           取轮廓：羽化、渐变、抗锯齿的边缘会在这一步压成硬边界。原生
           To Path 也是这个行为，不是这里的选择。

 note      图层组没有像素，挂不了蒙版，会明确拒绝。
           选区 → 通道 / 蒙版 → 通道 在没有选区时先按 GIMP 语义全选，
           否则原生过程会拒绝执行。
           「→ 路径」在没有选区时直接报错（原生菜单此时也是灰的），不会
           偷偷描一条空路径出来。路径重名自动加序号，重跑不会覆盖旧路径。

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

import lb_dialog as _dialog


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
        raise RuntimeError(_("This image has no channels yet; create one in the Channels dock first."))
    raise RuntimeError(
        _("Click the channel to use in the Channels dock and run again (available: %s).")
        % ", ".join(c.get_name() for c in channels))


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
            _("Nothing selected: select the target layer(s) in the Layers dock and run it from there."))
    return layers


def pick_masked_layer(image, drawables):
    """取第一个带蒙版的图层；都没有就说清楚。
    The first selected layer that actually has a mask."""
    for item in pick_layers(image, drawables):
        if item.get_mask() is not None:
            return item
    raise RuntimeError(
        _("The selected layer has no layer mask."))


def _vector_path(item):
    """路径面板里点中的可能是路径本身，也可能是它的矢量图层外壳。
    The Paths dock may hand over a Path or the vector layer wrapping it."""
    if isinstance(item, Gimp.Path):
        return item
    if hasattr(item, 'is_vector_layer') and item.is_vector_layer():
        try:
            return item.get_path()
        except Exception:                        # noqa: BLE001
            return None
    return None


def pick_path(image, drawables=None):
    """取源路径，四路兜底，和 pick_channel 同一套顺序：
    1. 上下文里点中的那条（从路径右键进来时 GIMP 直接交过来）；
    2. 路径面板里选中的；
    3. 图里只有一条路径时就是它；
    4. 都不成立才报错，并列出已有路径名。

    Four fallbacks, same order as pick_channel: context item, dock selection,
    the only path in the image, then an error listing what is there."""
    buckets = (list(drawables or []),
               list(image.get_selected_paths()))
    for bucket in buckets:
        for item in bucket:
            path = _vector_path(item)
            if path is not None:
                return path

    paths = image.get_paths()
    if len(paths) == 1:
        return paths[0]

    if not paths:
        raise RuntimeError(_("This image has no paths yet; draw one with the path tool first."))
    raise RuntimeError(
        _("Click the path to use in the Paths dock and run again (available: %s).")
        % ", ".join(p.get_name() for p in paths))


def unique_path_name(image, base, exclude=()):
    """在路径面板里取一个不重名的名字；exclude 是本次刚建出来、还没改名的
    那几条，算重名时要跳开，否则第一条会被自己挤成「Selection 2」。
    A free path name; ids in `exclude` are the ones being renamed right now,
    so they must not count as taken."""
    skip = set(p.get_id() for p in exclude)
    used = set(p.get_name() for p in image.get_paths() if p.get_id() not in skip)
    if base not in used:
        return base
    n = 2
    while "%s %d" % (base, n) in used:
        n += 1
    return "%s %d" % (base, n)


def _sel2path(image, drawables=None):
    """原生「选择 → 路径」：plug-in-sel2path，一次生成一条路径，不连通的
    几块各占一条 stroke。它不回传新路径，只能按 id 做前后差集。
    Native select-to-path: one path per run, one stroke per contour. It
    returns nothing, so the new path is found by diffing ids before/after."""
    proc = Gimp.get_pdb().lookup_procedure('plug-in-sel2path')
    cfg = proc.create_config()
    cfg.set_property('image', image)
    layers = [d for d in (drawables or []) if isinstance(d, Gimp.Layer)]
    if not layers:
        layers = list(image.get_selected_layers()) or list(image.get_layers())
    try:
        cfg.set_core_object_array('drawables', layers)
    except Exception:                            # noqa: BLE001
        pass
    before = set(p.get_id() for p in image.get_paths())
    proc.run(cfg)
    return [p for p in image.get_paths() if p.get_id() not in before]


def selection_to_path(image, drawables=None, base="Selection"):
    """把当前选区描成路径，名字改成好认的（几何结果与原生 To Path 一致）。
    Trace the selection into a path; only the name differs from the native
    Select > To Path result."""
    if selection_empty(image):
        raise RuntimeError(
            _("There is no selection to trace."))
    new = _sel2path(image, drawables)
    if not new:
        raise RuntimeError(
            _("The native tracer produced no path; the selection is too small."))
    for i, path in enumerate(new):
        base_i = base if i == 0 else "%s %d" % (base, i + 1)
        path.set_name(unique_path_name(image, base_i, exclude=new))
    return new[0]


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
            _("A layer group has no pixels and cannot take a mask; merge the group first."))


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


# ---- 带路径的六个方向 / the six path directions ----------------------------
# 路径和位图之间没有直连的原生过程，一律经选区这一站：
# · 位图 → 路径   先 select-item，再 plug-in-sel2path（原生 To Path 的那一步）
# · 路径 → 位图   只有 select-item 一步，后面的存通道 / 挂蒙版照旧
# 经选区就意味着跟着原生的数值语义走，也意味着灰度会被压成 0.5 等值线。

def path_to_selection(image, drawables=None):
    path = pick_path(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, path)
    return path


def channel_to_path(image, drawables=None):
    channel = pick_channel(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, channel)
    path = selection_to_path(image, drawables, "Channel %s" % channel.get_name())
    return channel, path


def mask_to_path(image, drawables):
    layer = pick_masked_layer(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, layer.get_mask())
    path = selection_to_path(image, drawables, "%s Mask" % layer.get_name())
    return layer, path


def path_to_channel(image, drawables=None):
    path = pick_path(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, path)
    channel = save_selection_as_channel(image, path.get_name())
    return path, channel


def path_to_mask(image, drawables):
    path = pick_path(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, path)
    return path, apply_selection_mask(image, drawables)


def path_to_bitmap(image, drawables=None):
    """路径 → 像素图层：真·栅格化，一步出可编辑的位图。

    路径在 GIMP 里只存几何，没有填充色、没有线宽，所以「栅格化」必须替它挑
    一种落笔方式。这里用**前景色填充路径内部**，和原生「编辑 → 用前景色填充
    路径」同义（原生那条内部也是先转选区再填，边缘同样是一像素过渡），这也
    是「矢量图形 → 位图」最常见的那个意思。要的是线稿（描边）而不是实心形状
    时，用原生「编辑 → 描边路径」，本插件不管那条。

    新图层只做路径外接框那么大、偏移对回原位，不铺满整个画布：栅格化一个
    24×24 的图标不该顺手生成一张 4000×3000 的空图层。

    The path is a shape, not a brush: rasterising it here means filling its
    interior with the foreground colour — the same thing the native
    "Edit > Fill with foreground colour" does on a path, with the same
    one-pixel edge falloff. The new layer is cropped to the path's bounding
    box and offset back into place."""
    path = pick_path(image, drawables)
    image.select_item(Gimp.ChannelOps.REPLACE, path)

    ok, non_empty, x1, y1, x2, y2 = image.get_selection().bounds(image)
    if not non_empty or x2 <= x1 or y2 <= y1:
        raise RuntimeError(
            _("This path encloses no area to fill; check that it has at least "
              "one stroke."))

    x, y = int(x1), int(y1)
    w, h = int(x2 - x1), int(y2 - y1)
    layer = Gimp.Layer.new(image, unique_name(image, path.get_name()), w, h,
                           Gimp.ImageType.RGBA_IMAGE, 100.0,
                           Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, 0)
    layer.set_offsets(x, y)
    if not layer.edit_fill(Gimp.FillType.FOREGROUND):
        layer.delete()
        raise RuntimeError(_("Filling the path failed; the image may be in a "
                             "mode that cannot take a new RGBA layer."))
    return path, layer


# ---- 程序包装 / procedure wrapper ------------------------------------------

# 名字 → (菜单标签, 动作, 说明)
DIRECTIONS = [
    ('lb-plugin-conv-channel-to-selection',
     'Channel to Selection',
     'channel-to-selection',
     _("Take the channel selected in the Channels dock and turn it into the "
       "pixel selection."),
     _("Channel to selection: turns the channel selected in the Channels dock into a pixel selection.")),
    ('lb-plugin-conv-selection-to-channel',
     'Selection to Channel',
     'selection-to-channel',
     _("Save the current selection as a new channel."),
     _("Selection to channel: saves the current selection as a new channel.")),
    ('lb-plugin-conv-channel-to-mask',
     'Channel to Mask',
     'channel-to-mask',
     _("Use the selected channel's grey levels as a layer mask on every "
       "selected layer."),
     _("Channel to mask: uses the selected channel's grey as the mask of the selected layer.")),
    ('lb-plugin-conv-mask-to-channel',
     'Mask to Channel',
     'mask-to-channel',
     _("Turn the selected layer's layer mask into a new channel."),
     _("Mask to channel: turns the selected layer's mask into a new channel.")),
    ('lb-plugin-conv-selection-to-mask',
     'Selection to Mask',
     'selection-to-mask',
     _("Use the current selection as a layer mask on every selected layer."),
     _("Selection to mask: attaches the current selection as the mask of the selected layer.")),
    ('lb-plugin-conv-mask-to-selection',
     'Mask to Selection',
     'mask-to-selection',
     _("Turn the selected layer's layer mask into the pixel selection."),
     _("Mask to selection: turns the selected layer's mask into a pixel selection.")),

    # ---- 路径 / paths ------------------------------------------------------
    ('lb-plugin-conv-path-to-selection',
     'Path to Selection',
     'path-to-selection',
     _("Turn the selected path into the pixel selection."),
     _("Path to selection: turns the path selected in the Paths dock into a pixel selection.")),
    ('lb-plugin-conv-selection-to-path',
     'Selection to Path',
     'selection-to-path',
     _("Trace the current selection into a new path (the native "
       "Select > To Path geometry, with a readable name)."),
     _("Selection to path: traces the current selection into a new path (same geometry as the native To Path).")),
    ('lb-plugin-conv-path-to-channel',
     'Path to Channel',
     'path-to-channel',
     _("Rasterise the selected path into a new channel."),
     _("Path to channel: rasterises the selected path into a new channel.")),
    ('lb-plugin-conv-channel-to-path',
     'Channel to Path',
     'channel-to-path',
     _("Trace the selected channel's 50% contour into a new path."),
     _("Channel to path: traces the 50% contour of the selected channel into a new path.")),
    ('lb-plugin-conv-path-to-mask',
     'Path to Mask',
     'path-to-mask',
     _("Rasterise the selected path into a layer mask on every selected "
       "layer."),
     _("Path to mask: rasterises the selected path into the mask of the selected layer.")),
    ('lb-plugin-conv-mask-to-path',
     'Mask to Path',
     'mask-to-path',
     _("Trace the selected layer's mask into a new path."),
     _("Mask to path: traces the outline of the selected layer's mask into a new path.")),

    # 路径 → 真·位图：不是「转成另一种 GIMP 对象」，而是直接落成像素图层。
    # 前面十条都只在 GIMP 的几种对象之间倒腾（选区/通道/蒙版/路径），这是唯一
    # 一条把几何变成可涂抹像素的。
    ('lb-plugin-conv-path-to-bitmap',
     'Path to Bitmap',
     'path-to-bitmap',
     _("Rasterise the selected path into a new pixel layer, filled with the "
       "foreground colour."),
     _("Path to bitmap: rasterises the path into a new pixel layer (filled with the foreground colour), cropped to the path.")),
]

BY_KEY = dict((d[2], d) for d in DIRECTIONS)


class ConvertPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

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
            # 以通道为源的三条也挂到通道面板右键：GIMP 会把点中的那条作为
            # drawable 传进来，取源不用再去别处点一下。
            # The three channel-source directions also live in the Channels
            # dock context menu, where GIMP hands the clicked channel over.
            procedure.add_menu_path("<Channels>/SuperMrWang/Convert")
        if key.startswith('path-to'):
            # 路径右键同理：点中的那条直接在上下文里。
            # Same for the Paths dock: the clicked path arrives in context.
            procedure.add_menu_path("<Paths>/SuperMrWang/Convert")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image")))
        if not _dialog.run_dialog(procedure, run_mode, config):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, None)

        key = procedure.get_name()[len('lb-plugin-conv-'):]
        try:
            if key == 'channel-to-selection':
                src = channel_to_selection(image, drawables)
                note = _("Channel \"%s\" to selection") % src.get_name()
            elif key == 'selection-to-channel':
                dst = selection_to_channel(image)
                note = _("Selection to channel \"%s\"") % dst.get_name()
            elif key == 'channel-to-mask':
                src, masks = channel_to_mask(image, drawables)
                note = _("Channel \"%s\" to the mask of %d layer(s)") % (src.get_name(),
                                                          len(masks))
            elif key == 'mask-to-channel':
                dst = mask_to_channel(image, drawables)
                note = _("Mask to channel \"%s\"") % dst.get_name()
            elif key == 'selection-to-mask':
                masks = selection_to_mask(image, drawables)
                note = _("Selection to the mask of %d layer(s)") % len(masks)
            elif key == 'mask-to-selection':
                src = mask_to_selection(image, drawables)
                note = _("Mask \"%s\" to selection") % src.get_name()
            elif key == 'path-to-selection':
                src = path_to_selection(image, drawables)
                note = _("Path \"%s\" to selection") % src.get_name()
            elif key == 'selection-to-path':
                dst = selection_to_path(image, drawables)
                note = _("Selection to path \"%s\"") % dst.get_name()
            elif key == 'path-to-channel':
                src, dst = path_to_channel(image, drawables)
                note = _("Path \"%s\" to channel \"%s\"") % (src.get_name(),
                                                     dst.get_name())
            elif key == 'channel-to-path':
                src, dst = channel_to_path(image, drawables)
                note = _("Channel \"%s\" to path \"%s\"") % (src.get_name(),
                                                     dst.get_name())
            elif key == 'path-to-mask':
                src, masks = path_to_mask(image, drawables)
                note = _("Path \"%s\" to the mask of %d layer(s)") % (src.get_name(),
                                                          len(masks))
            elif key == 'mask-to-path':
                src, dst = mask_to_path(image, drawables)
                note = _("Mask \"%s\" to path \"%s\"") % (src.get_name(),
                                                     dst.get_name())
            elif key == 'path-to-bitmap':
                src, dst = path_to_bitmap(image, drawables)
                note = _("Path \"%s\" rasterised into layer \"%s\"") % (
                    src.get_name(), dst.get_name())
            else:
                raise RuntimeError(_("Unknown direction"))
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
