#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 任意图层 → 选区 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   右键点一个图层，就把它转成当前选区。GEGL 算子（含本仓库的
           lb:color-mask-select、lb:calculations 等）跑完常常留下一张灰度
           图，它往后的用途多半是当蒙版——原生流程要点四步（复制 → 建通道 →
           粘贴 → 蒙版转选区），本插件一步到位，而且不要求图层是「纯灰度」
           ——彩色图层会按亮度转。
           Turn any layer into the current selection in one click, straight
           from the layer context menu.

 menu      图层右键 → SuperMrWang → Convert → Layer to Selection
           也挂在 SuperMrWang → Convert 下，方便不用鼠标右键的场合。

 usage     选区可选 Gray（亮度）/ R / G / B / Alpha，四种组合方式
           （替换 / 加 / 减 / 交），可反相。核心逻辑是模块级函数，
           tools/check_layer_to_mask.py 直接调用它们做回归。

 note      两个 GIMP 3 的坑（本插件绕开了）：
           1. shadow buffer 的 merge 遵守当前选区，先写临时通道再选它，
              所以动手前要把选区挂起、结束再恢复；
           2. babl 的 "Y' float" 不是亮度加权（纯红会读成 0.51 的 HSL 明度），
              所以彩色图层的 Gray 走临时图层 desaturate，灰度图层才走
              零拷贝的通道切片快捷路径。

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

import lb_dialog as _dialog


# ---- 通道常量 / channel ids ------------------------------------------------
# 与 GEGL 侧的 LB_CH_* 同序，方便脚本里互通
CH_GRAY, CH_RED, CH_GREEN, CH_BLUE, CH_ALPHA = range(5)

CHANNELS = [("gray", "Gray (luminosity)"), ("red", "Red"), ("green", "Green"),
            ("blue", "Blue"), ("alpha", "Alpha")]

OPS = (Gimp.ChannelOps.REPLACE, Gimp.ChannelOps.ADD,
       Gimp.ChannelOps.SUBTRACT, Gimp.ChannelOps.INTERSECT)


# ---- PDB 小工具 / PDB helpers ----------------------------------------------

def _pdb(name, **props):
    """按名调用 PDB 过程 / call a PDB procedure by name"""
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


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


def _luma_via_desaturate(image, layer):
    """彩色图层取亮度：复制一份、去色、读回、删掉。

    babl 的 "Y' float" 给的是 HSL 明度（纯红 0.51），不是加权亮度，所以
    彩色图只能让 GIMP 自己算。复制图层是 C 级操作，比逐像素 Python 循环快
    一个数量级。
    Luminosity for a colour layer: copy -> desaturate -> read -> drop. babl's
    "Y' float" is HSL lightness (pure red reads 0.51), not weighted luma, so
    GIMP has to compute it; a layer copy is far faster than a Python loop."""
    prev = image.get_selected_layers()
    tmp = layer.copy()
    image.insert_layer(tmp, None, 0)
    try:
        _pdb('gimp-drawable-desaturate', drawable=tmp,
             desaturate_mode=Gimp.DesaturateMode.LUMA)
        data = read_rgba(tmp)
        return data[0::4] if len(data) >= 4 else array.array('f')
    finally:
        image.remove_layer(tmp)
        # 临时图层删掉后把「活动图层」还给用户原来选中的，别让面板跳走
        # Give the active-layer selection back: inserting/removing the temporary
        # copy would otherwise leave another layer active in the Layers dock.
        if prev:
            try:
                image.set_selected_layers(prev)
            except Exception:
                pass


def layer_plane(image, layer, channel):
    """把图层的一个通道铺到画布大小，返回长度 w*h 的 0..1 浮点数组。

    图层可以比画布小、可以带偏移，没盖到的地方是 0（选区里就是不选中）。
    Flatten one channel of a layer onto the canvas; areas the layer does not
    cover stay 0 (i.e. not selected)."""
    iw, ih = image.get_width(), image.get_height()
    out = array.array('f', bytes(iw * ih * 4))
    if layer.is_group():
        raise RuntimeError(_("A layer group cannot be converted directly; right-click it and Merge Layer Group first."))
    lw, lh = layer.get_width(), layer.get_height()
    if lw <= 0 or lh <= 0:
        return out

    data = read_rgba(layer)
    if len(data) < lw * lh * 4:
        return out

    if channel == CH_ALPHA:
        plane = data[3::4]
    elif channel == CH_RED:
        plane = data[0::4]
    elif channel == CH_GREEN:
        plane = data[1::4]
    elif channel == CH_BLUE:
        plane = data[2::4]
    else:                                   # Gray / 亮度
        r, g, b = data[0::4], data[1::4], data[2::4]
        if r == g and g == b:
            plane = r                       # 灰度内容：零拷贝，最快路径
        else:
            plane = _luma_via_desaturate(image, layer)

    if len(plane) < lw * lh:                # 理论上不会发生，防御一下
        return out

    ok, ox, oy = layer.get_offsets()
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(iw, ox + lw), min(ih, oy + lh)
    if x1 <= x0 or y1 <= y0:
        return out
    for row in range(y1 - y0):
        s = (y0 - oy + row) * lw + (x0 - ox)
        d = (y0 + row) * iw + x0
        out[d:d + (x1 - x0)] = plane[s:s + (x1 - x0)]
    return out


# ---- 写通道 / write a channel ----------------------------------------------

def write_channel(image, plane, name):
    """新建画布大小的 Alpha 通道并写入 0..1 数据（单通道直接写，省内存）。

    必须在「没有选区」的状态下调用——shadow buffer 的合并会遵守选区，
    否则通道只有选区内有内容。
    Create a canvas-sized channel and fill it. Must run while no selection is
    active: shadow merges honour the selection and would clip the write."""
    iw, ih = image.get_width(), image.get_height()
    ch = Gimp.Channel.new(image, name, iw, ih, 100.0,
                          _tint())
    image.insert_channel(ch, None, -1)
    r = Gegl.Rectangle.new(0, 0, iw, ih)
    shadow = ch.get_shadow_buffer()
    shadow.set(r, "Y' float", plane.tobytes())
    shadow.flush()                          # 不 flush，merge 读到的是空 backend
    ch.merge_shadow(True)
    return ch


def _tint():
    """通道缩略图用的淡紫色 / tint colour for the channel thumbnail"""
    c = Gegl.Color()
    c.set_rgba(0.5, 0.5, 1.0, 1.0)
    return c


# ---- 动作 / the action ------------------------------------------------------

def layer_to_selection(image, layer, channel=CH_GRAY, invert=False, operation=0):
    """图层 → 选区。operation: 0 Replace / 1 Add / 2 Subtract / 3 Intersect"""
    saved = selection_save(image)
    selection_clear(image)                  # 否则写通道会被旧选区截断
    image.undo_group_start()
    try:
        plane = layer_plane(image, layer, channel)
        tmp = write_channel(image, plane, 'lb-layer-to-selection')
        if saved is not None:               # 加法/减法/交集要先有原选区
            selection_restore(image, saved)
        image.select_item(OPS[operation], tmp)
        if invert:
            _pdb('gimp-selection-invert', image=image)
        image.remove_channel(tmp)
        if saved is not None:
            image.remove_channel(saved)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()


# ---- 程序包装 / procedure wrapper ------------------------------------------

class LayerToSelectionPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return ['lb-plugin-layer-to-selection']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*, INDEXED*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("Layer to Selection"))
        # 两个入口：图层右键菜单（点哪个转哪个）+ 选择菜单
        procedure.add_menu_path("<Layers>/SuperMrWang/Convert")
        procedure.add_menu_path("<Image>/SuperMrWang/Convert")

        procedure.set_documentation(
            _("Layer to Selection: turn the clicked layer into the current "
              "selection (Gray/R/G/B/Alpha, invert, four combine modes)"),
            _("One click 'any layer -> selection', no copy/paste detour."),
            name)
        procedure.add_int_argument(
            "channel", _("Channel"),
            _("0 Gray (luminosity), 1 Red, 2 Green, 3 Blue, 4 Alpha"),
            0, 4, 0, GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "invert", _("Invert"),
            _("Select the dark side instead of the bright side"),
            False, GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "operation", _("Combine"),
            _("0 Replace, 1 Add, 2 Subtract, 3 Intersect"),
            0, 3, 0, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        if not _dialog.run_dialog(procedure, run_mode, config):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, None)
        try:
            layer_to_selection(image, drawables[0],
                               config.get_property('channel'),
                               config.get_property('invert'),
                               config.get_property('operation'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("layer-to-selection: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(LayerToSelectionPlugin.__gtype__, sys.argv)
