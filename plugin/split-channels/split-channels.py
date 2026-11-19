#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 图层 → 分通道（一次拆出 R/G/B/Alpha） —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把一个图层的每条分量各存成一条通道，一步到位。原生做法是逐条
           「通道对话框 → 新建 → 复制粘贴 → 合并」，四条就是十六步；本插件
           一次建好，原图层自动隐藏留作对照。
           Split one layer into per-component channels (R/G/B/A) in a single
           step; the source layer is hidden so it stays available as a
           reference.

 menu      SuperMrWang → Convert → Split Channels
           也挂在图层右键 SuperMrWang → Convert 下，点哪个拆哪个。

 usage     默认拆 R / G / B / Alpha 四路，命名为「图层名 R」「图层名 G」
           「图层名 B」「图层名 Alpha」，同名通道已存在时自动加序号。灰度图
           只拆 Gray（RGB 三路此时完全相同，拆出来没有意义），带透明才加
           Alpha。可选「含 Alpha」关掉就只出三色通道，「隐藏源图层」关掉则
           让原图和通道并存。核心逻辑是模块级函数，tools/check_split_channels.py
           直接调用做回归。

 note      两个 GIMP 3 的坑（本插件绕开了）：
           1. shadow buffer 的 merge 遵守当前选区，写通道前必须先把选区
              挂起，否则通道只有选区内有内容、其余全黑；
           2. 图层可以比画布小、可以带偏移，没盖到的区域必须补 0，不能
              当成「图层自己的尺寸」去建通道，否则通道尺寸不对、贴上去错位。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import array
import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject

from gi.repository import Gegl


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


# ---- 通道常量 / channel ids ------------------------------------------------
# 与 GEGL 侧的 LB_CH_*、layer-to-channel 的 CH_* 同序，方便脚本里互通
CH_GRAY, CH_RED, CH_GREEN, CH_BLUE, CH_ALPHA = range(5)


# ---- PDB 小工具 / PDB helpers ----------------------------------------------

def _pdb(name, **props):
    """按名调用 PDB 过程 / call a PDB procedure by name"""
    proc = Gimp.get_pdb().lookup_procedure(name)
    if proc is None:
        raise RuntimeError(_('PDB 过程不存在 / no such procedure: %s') % name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def _tint(r, g, b):
    """通道缩略图的显示色 / thumbnail tint for a channel"""
    c = Gegl.Color()
    c.set_rgba(r, g, b, 1.0)
    return c


# 只存数值、不存 Gegl.Color 对象：插件进程在 Gimp.main() 之前 import 本模块，
# 那时 babl 还没初始化，模块级构造 Gegl.Color 会直接 babl_fatal
# （"you must call babl_init first"），整个插件注册不上。
# Store plain numbers, not Gegl.Color: this module is imported before
# Gimp.main(), when babl is not initialised yet.
TINT_RGBA = {
    CH_GRAY: (0.72, 0.72, 0.72),
    CH_RED: (1.00, 0.45, 0.45),
    CH_GREEN: (0.45, 1.00, 0.45),
    CH_BLUE: (0.50, 0.55, 1.00),
    CH_ALPHA: (0.86, 0.86, 0.86),
}


def tint_for(cid):
    """按通道取缩略图颜色（延迟构造）/ lazily build the tint colour"""
    return _tint(*TINT_RGBA[cid])

# 后缀与中文说明 / suffix + label per component
SUFFIX = {
    CH_GRAY: 'Gray',
    CH_RED: 'R',
    CH_GREEN: 'G',
    CH_BLUE: 'B',
    CH_ALPHA: 'Alpha',
}


# ---- 选区挂起 / selection suspend ------------------------------------------

def selection_save(image):
    """把当前选区存成临时通道返回；本来没选区则返回 None。
    Save the current selection to a throw-away channel, or None if empty."""
    try:
        sel = image.get_selection()
        if sel is None or not sel.bounds(image)[1]:      # non_empty
            return None
        return _pdb('gimp-selection-save', image=image).index(1)
    except Exception:
        return None


def selection_clear(image):
    _pdb('gimp-selection-none', image=image)


def selection_restore(image, channel):
    if channel is None:
        return
    try:
        image.select_item(Gimp.ChannelOps.REPLACE, channel)
    except Exception:
        pass


# ---- 读图层 / read a layer plane -------------------------------------------

def read_rgba(layer):
    """读出图层本地的 RGBA 浮点数据 / the layer's own RGBA floats."""
    w, h = layer.get_width(), layer.get_height()
    if w <= 0 or h <= 0:
        return array.array('f')
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                 "R'G'B'A float", Gegl.AbyssPolicy.NONE)
    data = array.array('f')
    data.frombytes(bytes(bytearray(raw)))
    return data


def to_canvas(plane, lw, lh, ox, oy, iw, ih):
    """把「图层本地」的一路平面铺到画布大小，没盖到的区域是 0。

    图层可以比画布小、可以带偏移（甚至负偏移），直接按图层尺寸建通道会
    尺寸不对、位置也错，所以统一铺一遍。
    Flatten a layer-local plane onto the canvas; uncovered areas stay 0."""
    out = array.array('f', bytes(iw * ih * 4))
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(iw, ox + lw), min(ih, oy + lh)
    if x1 <= x0 or y1 <= y0:
        return out
    for row in range(y1 - y0):
        s = (y0 - oy + row) * lw + (x0 - ox)
        d = (y0 + row) * iw + x0
        out[d:d + (x1 - x0)] = plane[s:s + (x1 - x0)]
    return out


def split_planes(image, layer, include_alpha=True):
    """返回 [(通道 id, 画布大小的浮点平面)]。

    一次读完整层数据再切片，比「每个通道各读一遍 buffer」快得多；切片是
    C 级的 array 步进，不经过 Python 循环。
    Read the layer once, then slice — far faster than one buffer read per
    channel."""
    if layer.is_group():
        raise RuntimeError(_('图层组不能拆分通道：请先右键 → 合并图层组 '
                             '/ a layer group has no pixels of its own'))
    lw, lh = layer.get_width(), layer.get_height()
    iw, ih = image.get_width(), image.get_height()
    if iw <= 0 or ih <= 0:
        raise RuntimeError(_('画布尺寸为 0 / empty canvas'))

    data = read_rgba(layer)
    if len(data) < lw * lh * 4:
        raise RuntimeError(_('读不到图层像素 / could not read layer pixels'))
    ok, ox, oy = layer.get_offsets()

    out = []
    if image.get_base_type() == Gimp.ImageBaseType.GRAY:
        # 灰度图 R=G=B，拆三路只是三份一样的黑，没有意义
        out.append((CH_GRAY, to_canvas(data[0::4], lw, lh, ox, oy, iw, ih)))
    else:
        out.append((CH_RED, to_canvas(data[0::4], lw, lh, ox, oy, iw, ih)))
        out.append((CH_GREEN, to_canvas(data[1::4], lw, lh, ox, oy, iw, ih)))
        out.append((CH_BLUE, to_canvas(data[2::4], lw, lh, ox, oy, iw, ih)))

    if include_alpha and layer.has_alpha():
        out.append((CH_ALPHA, to_canvas(data[3::4], lw, lh, ox, oy, iw, ih)))
    return out


# ---- 写通道 / write a channel ----------------------------------------------

def write_channel(image, plane, name, tint):
    """新建画布大小的通道并写入 0..1 数据（单通道直接写，省内存）。

    必须在「没有选区」的状态下调用——shadow buffer 的合并会遵守选区，
    否则通道只有选区内有内容。
    Create a canvas-sized channel and fill it. Must run while no selection is
    active: shadow merges honour the selection and would clip the write."""
    iw, ih = image.get_width(), image.get_height()
    ch = Gimp.Channel.new(image, name, iw, ih, 100.0, tint)
    image.insert_channel(ch, None, -1)
    r = Gegl.Rectangle.new(0, 0, iw, ih)
    shadow = ch.get_shadow_buffer()
    shadow.set(r, "Y' float", plane.tobytes())
    shadow.flush()                          # 不 flush，merge 读到的是空 backend
    ch.merge_shadow(True)
    ch.set_visible(False)                   # 新建通道默认别叠到画布上
    return ch


def unique_name(image, base):
    """通道重名时加序号 / add a number when the name is taken"""
    names = set()
    for c in image.get_channels():
        names.add(c.get_name())
    if base not in names:
        return base
    i = 2
    while '%s %d' % (base, i) in names:
        i += 1
    return '%s %d' % (base, i)


# ---- 动作 / the action ------------------------------------------------------

def split_channels(image, layer, include_alpha=True, hide_source=True,
                   prefix=''):
    """图层 → 多条通道，返回新建的通道列表。

    原图层默认隐藏而不删除：拆分结果在通道面板里，画布上留着原图方便对照，
    随时能把眼睛点回来。
    Layer -> channels. The source layer is hidden by default (not deleted) so
    you can flip back to it while comparing."""
    if layer is None:
        raise RuntimeError(_('没有选中图层 / no layer selected'))

    base = prefix.strip() or layer.get_name()
    planes = split_planes(image, layer, include_alpha)

    saved = selection_save(image)
    selection_clear(image)                  # 写通道前必须无选区
    image.undo_group_start()
    created = []
    try:
        for cid, plane in planes:
            name = unique_name(image, '%s %s' % (base, SUFFIX[cid]))
            created.append(write_channel(image, plane, name, tint_for(cid)))
        if hide_source:
            layer.set_visible(False)
        if saved is not None:
            selection_restore(image, saved)
            image.remove_channel(saved)
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        Gimp.message(_('已拆出 %d 条通道：%s') % (
            len(created), '、'.join(c.get_name() for c in created)))
    except Exception:
        pass
    return created


# ---- 程序包装 / procedure wrapper ------------------------------------------

class SplitChannelsPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return ['lb-plugin-split-channels']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("Split Channels"))
        # 两个入口：图层右键菜单（点哪个拆哪个）+ 图像菜单
        procedure.add_menu_path("<Layers>/SuperMrWang/Convert")
        procedure.add_menu_path("<Image>/SuperMrWang/Convert")

        procedure.set_documentation(
            _("Split Channels: store each component of the layer as its own "
              "channel (R / G / B / Alpha; grayscale images yield Gray). The "
              "source layer is hidden afterwards so it stays available as a "
              "reference."),
            _("One click 'one layer -> per-component channels', no manual "
              "channel-by-channel copy/paste."), name)
        procedure.add_boolean_argument(
            "include-alpha", _("Include Alpha"),
            _("Also store the transparency as a channel (only when the layer "
              "has one)"),
            True, GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "hide-source", _("Hide source layer"),
            _("Hide the original layer after splitting so the canvas shows "
              "you the result"),
            True, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument(
            "prefix", _("Name prefix"),
            _("Empty = use the layer name; channels become \"<prefix> R\", "
              "\"<prefix> G\", ..."), "",
            GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_('No image or no layer selected')))
        try:
            split_channels(image, drawables[0],
                           config.get_property('include-alpha'),
                           config.get_property('hide-source'),
                           config.get_property('prefix'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("split-channels: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(SplitChannelsPlugin.__gtype__, sys.argv)
