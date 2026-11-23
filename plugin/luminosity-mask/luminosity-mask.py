#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 明度蒙版 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把图层的明度拆成七条可以随时载入的通道：亮部 1/2/3、暗部 1/2/3、
           中间调。点一下菜单全部建好，之后双击任意一条就变成选区。
           Luminosity masks: seven channels built from a layer's luminance in
           one click. Double-click any of them to turn it into a selection.

 menu      SuperMrWang → Luminosity Masks → 生成明度蒙版（7 条通道）
           图层右键 → SuperMrWang → Luminosity Masks → 同上

 usage     选中一个栅格图层 → 菜单项。通道面板里会多出（按阈值宽窄排列）：

             明度 · 亮部 1（> 64）      最宽的高光蒙版
             明度 · 亮部 2（> 128）
             明度 · 亮部 3（> 192）     只剩最亮的部分
             明度 · 暗部 1（< 192）     最宽的暗部蒙版
             明度 · 暗部 2（< 128）
             明度 · 暗部 3（< 64）      只剩最深的阴影
             明度 · 中间调（64–192）    两端渐隐的梯形

           用法：双击通道 → 通道变选区 → 曲线 / 色阶只作用在选区里。
           要挂成图层蒙版：选中通道后右键图层（配合 channel-to-mask 插件）。

 note      为什么是通道而不是图层：明度蒙版在 PS 里就是通道，「载入成选区」是
           它的用法。做成灰度图层也能看，但每次都要手动图层转选区。

           每条通道 = 明度做一次色阶拉伸。亮部 n 是「把 t 以上拉到 0…255」，
           暗部 n 是它的反相，中间调是两条之差再归一化——七条都是标准 0…255
           渐变蒙版，叠加时不用再想权重。

           通道名带固定前缀，重跑会先删掉上一批同名通道，不会越点越多。

 precision 蒙版按 8 位生成（256 级）。蒙版本身是渐变，256 级在绝大多数叠加里
           看不出来；真遇上 16 位风光修图露台阶，可以改走 GEGL levels，让精度
           跟着图像走。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GLib, Gegl


# 多语言：查自己的域（gegl-color-ops），语言取自 GIMP 界面设置。
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


# 三档阈值，等于 PS 里 Lights/Darks 1–3 的常用分界。第四档（224）在实际修图
# 里用得很少，三条已经够分层。
T1, T2, T3 = 64, 128, 192


def channel_prefix():
    """通道名统一前缀。不在模块级调 _()：那时 i18n 域未必装好。"""
    return _("Luminosity · ")


# ---- 映射表 / the look-up tables -------------------------------------------

def _lights_lut(t):
    """亮部：t 以下压成 0，t…255 线性拉到 0…255。"""
    denom = float(255 - t) if t < 255 else 1.0
    return bytes(0 if v <= t else min(255, int(round((v - t) * 255.0 / denom)))
                 for v in range(256))


def _invert(table):
    return bytes(255 - b for b in table)


def _mid_lut(lo, hi):
    """中间调：亮部(lo) 减去 亮部(hi)，再按峰值归一化。

    直接相乘会得到一条峰值只有 170 左右的灰蒙蒙曲线；相减之后再归一化，
    峰值才是纯白、两端是纯黑——当蒙版用的时候不用再补一条曲线。
    """
    light_lo = _lights_lut(lo)
    light_hi = _lights_lut(hi)
    raw = [max(0, light_lo[v] - light_hi[v]) for v in range(256)]
    peak = max(raw) or 1
    return bytes(min(255, int(round(v * 255.0 / peak))) for v in raw)


def build_masks():
    """返回 [(通道名, 映射表)]，顺序就是通道面板里自上而下的顺序。"""
    lights1, lights2, lights3 = (_lights_lut(T1), _lights_lut(T2),
                                 _lights_lut(T3))
    return [
        (_("Lights 1 (> %d)") % T1, lights1),
        (_("Lights 2 (> %d)") % T2, lights2),
        (_("Lights 3 (> %d)") % T3, lights3),
        (_("Darks 1 (< %d)") % T3, _invert(lights3)),
        (_("Darks 2 (< %d)") % T2, _invert(lights2)),
        (_("Darks 3 (< %d)") % T1, _invert(lights1)),
        (_("Midtones (%d–%d)") % (T1, T3), _mid_lut(T1, T3)),
    ]


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


def _luminance_u8(image, layer):
    """复制一份、去色成明度、读出 8 位单通道，然后删掉副本。

    desaturate 走 PDB 直接改像素（改的是副本），比挂滤镜再烘焙少一步，也不
    用关心投影有没有刷新。用 LUMINANCE 而不是 LIGHTNESS：按人眼对 R/G/B 的
    敏感度加权，红绿两块在 LIGHTNESS 下亮度相同、在 LUMINANCE 下能分开。
    """
    w, h = layer.get_width(), layer.get_height()
    probe = layer.copy()
    if probe is None:
        raise RuntimeError(_("Could not copy the layer."))
    image.insert_layer(probe, layer.get_parent(), _item_position(image, layer))
    try:
        proc = Gimp.get_pdb().lookup_procedure('gimp-drawable-desaturate')
        cfg = proc.create_config()
        cfg.set_property('drawable', probe)
        cfg.set_property('desaturate-mode', Gimp.DesaturateMode.LUMINANCE)
        proc.run(cfg)
        probe.update(0, 0, w, h)
        rect = Gegl.Rectangle.new(0, 0, w, h)
        raw = probe.get_buffer().get(rect, 1.0, "Y u8", Gegl.AbyssPolicy.NONE)
        return w, h, bytes(bytearray(raw))
    finally:
        image.remove_layer(probe)


def _drop_previous(image):
    """删掉上一批同前缀的通道，重跑不会越积越多。"""
    prefix = channel_prefix()
    for ch in list(image.get_channels()):
        try:
            if ch.get_name().startswith(prefix):
                image.remove_channel(ch)
        except Exception:
            pass


def _add_channel(image, name, w, h, data):
    ch = Gimp.Channel.new(image, name, w, h, 100.0, Gegl.Color.new("black"))
    if ch is None:
        raise RuntimeError(_("Could not create a channel."))
    image.insert_channel(ch, None, len(image.get_channels()))
    buf = ch.get_buffer()
    rect = Gegl.Rectangle.new(0, 0, w, h)
    buf.set(rect, "Y u8", data)
    buf.flush()
    ch.update(0, 0, w, h)
    return ch


# ---- 动作 / the action ------------------------------------------------------

def create_masks(image, layer):
    if layer is None:
        raise RuntimeError(_("Nothing to work on: no layer."))
    if layer.is_group():
        raise RuntimeError(
            _("A layer group has no pixels of its own; pick a raster layer "
              "(right-click the group, then Merge Group)."))

    image.undo_group_start()
    try:
        w, h, luma = _luminance_u8(image, layer)
        _drop_previous(image)
        prefix = channel_prefix()
        made = []
        for name, table in build_masks():
            made.append(_add_channel(image, prefix + name, w, h,
                                     luma.translate(table)))
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    return made


# ---- 插件主体 / the plug-in -------------------------------------------------

PROC_NAME = 'lb-plugin-luminosity-mask'


class LuminosityMaskPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC_NAME]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        # 零参数：点了就建，不弹对话框
        procedure.set_documentation(
            "Luminosity Masks: seven channels (Lights/Darks 1-3 and Midtones) "
            "built from the selected layer's luminance. Double-click a channel "
            "to load it as a selection.",
            "明度蒙版：按当前图层的明度生成七条通道（亮部/暗部各 3 档 + 中间调）。"
            "双击通道即可载入为选区。", name)
        procedure.set_menu_label(_("Luminosity Masks (7 channels)"))
        procedure.add_menu_path("<Image>/SuperMrWang/Luminosity Masks")
        procedure.add_menu_path("<Layers>/SuperMrWang/Luminosity Masks")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(_("No image")))
        if len(drawables) != 1:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("Select exactly one layer.")))
        if not _dialog.run_dialog(procedure, run_mode, config):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, None)

        try:
            made = create_masks(image, drawables[0])
        except RuntimeError as exc:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(str(exc)))
        Gimp.message(_("Added %d luminosity channels: double-click one to load "
                       "it as a selection.") % len(made))
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


if __name__ == '__main__':
    Gimp.main(LuminosityMaskPlugin.__gtype__, sys.argv)
