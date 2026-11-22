#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 一键换天 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   选中照片图层 + 指定一张天空图，一次点击完成换天：
           1. 从图像顶边三个种子点做泛洪选择，把连通的天空选出来
              （经典算法，无需 AI 模型，对蓝天/晴天照片效果好）；
           2. 选区按参数收缩/羽化，收掉前景边缘的光晕；
           3. 天空图按 cover 方式缩放、居中裁切，插到照片图层正上方；
           4. 亮度匹配：用两张天空区域直方图均值的 gamma 关系，把新天空
              的亮度拉到与原天空一致（可在对话框关掉）；
           5. 选区转成新天空图层的图层蒙版，前景自然露出；
           6. 可选把选区另存为 "Sky Mask" 通道，供 lb:color-mask-select
              等蒙版算子精修后再重来（蒙版不会被本插件覆盖，手工改通道
              后用 选择→SuperMrWang→Grayscale Layer to Selection 或
              通道→选区 即可重新合成）。
 menu      SuperMrWang → Blend → Sky Replace
 usage     对话框参数：sky-file、threshold（采样阈值 0..0.5）、edge
           （正=收缩 px，负=扩张）、feather（羽化半径）、
           match-brightness、save-mask-channel。核心逻辑在模块级函数
           sky_replace 里，tools/check_sky_replace.py 直接调用做回归。
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math
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


# ---- 核心逻辑（模块级，供回归脚本直接调用） ---------------------------------

def _pdb_run(name, **props):
    """按名调用 PDB 过程 / call a PDB procedure by name"""
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def _histogram_value_mean(drawable):
    """选区内的 VALUE 直方图均值（0..255）/ mean of VALUE histogram in 0..255"""
    res = _pdb_run('gimp-drawable-histogram', drawable=drawable,
                   channel=0, start_range=0.0, end_range=1.0)
    return res.index(1)     # ValueArray[0] 是状态码，均值在 1


def select_sky(image, drawable, threshold, edge, feather):
    """泛洪选天空：顶边三个种子点 → 收缩/扩张 → 羽化。

    GIMP 3 的 gimp-image-select-contiguous-color 只剩 5 个参数，采样阈值、
    判据等全部走 context；这里用 context_push/pop 避免污染用户设置。
    返回 (ok, message)：任一种子没选中任何像素都算天空识别失败。
    """
    w, h = image.get_width(), image.get_height()

    Gimp.context_push()
    Gimp.context_set_sample_threshold(threshold)
    Gimp.context_set_sample_merged(False)
    Gimp.context_set_antialias(True)
    Gimp.context_set_sample_criterion(Gimp.SelectCriterion.COMPOSITE)
    Gimp.context_set_sample_transparent(False)

    seeds = [(1, 1), (w - 2, 1), (w // 2, 1)]       # 左上 / 顶中 / 右上
    try:
        for i, (x, y) in enumerate(seeds):
            _pdb_run('gimp-image-select-contiguous-color', image=image,
                     operation=int(Gimp.ChannelOps.REPLACE if i == 0
                                   else Gimp.ChannelOps.ADD),
                     drawable=drawable, x=x, y=y)

        sel = image.get_selection()
        if not sel.bounds(image)[1]:                 # non_empty
            return False, "种子点均未选中天空：调大 threshold 或换用顶部有天空的图"

        # 顶行覆盖率：泛洪结果必须盖住顶边扫描线的大部分，否则不认为
        # 找到了天空（面积检查靠 bounds 会把羽化/条纹误判进来）
        cov = sum(sel.value(image, x, 2) for x in (w // 4, w // 2, 3 * w // 4))
        if cov / (3.0 * 255.0) < 0.6:
            _pdb_run('gimp-selection-none', image=image)
            return False, ("顶部扫描线大部分不是天空（覆盖率 %.0f%%）："
                           "调大 threshold 或确认照片顶部有天空"
                           % (100.0 * cov / (3.0 * 255.0)))

        if edge > 0:
            _pdb_run('gimp-selection-shrink', image=image, steps=edge)
        elif edge < 0:
            _pdb_run('gimp-selection-grow', image=image, steps=-edge)
        if feather > 0:
            _pdb_run('gimp-selection-feather', image=image, radius=feather)
    finally:
        Gimp.context_pop()
    return True, ""


def sky_replace(image, drawable, sky_file, threshold=0.15, edge=1, feather=2.0,
                match_brightness=True, save_mask_channel=True):
    """一键换天核心流程。sky_file 是 GLib.File。

    返回 (sky_layer, mask, channel_or_None)。
    """
    if sky_file is None or not sky_file.query_exists():
        raise RuntimeError("sky file not found: %s" %
                           (sky_file.get_path() if sky_file else None))

    w, h = image.get_width(), image.get_height()

    image.undo_group_start()
    try:
        ok, msg = select_sky(image, drawable, threshold, edge, feather)
        if not ok:
            raise RuntimeError(msg)

        old_mean = _histogram_value_mean(drawable)   # 原天空区域亮度

        # Sky Mask 通道（选区还活着，先存后用）
        channel = None
        if save_mask_channel:
            channel = _pdb_run('gimp-selection-save', image=image).index(1)
            channel.set_name("Sky Mask")

        # 载入天空图 → 插到照片图层正上方（照片不透明，放下面会被完全盖住；
        # 靠蒙版只露出天空区，前景照样显示下面的照片）
        sky_layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE,
                                         image, sky_file)
        if sky_layer is None:
            raise RuntimeError("failed to load sky file")
        sky_layer.set_name("Sky")
        pos = image.get_item_position(drawable)
        image.insert_layer(sky_layer, None, pos)

        # cover 缩放 + 居中裁切：缩放系数取宽高比的较大者，画布只露出中间
        lw, lh = sky_layer.get_width(), sky_layer.get_height()
        s = max(w / lw, h / lh)
        nw = max(w, round(lw * s))
        nh = max(h, round(lh * s))
        _pdb_run('gimp-layer-scale', layer=sky_layer, new_width=nw,
                 new_height=nh, local_origin=False)
        sky_layer.set_offsets((w - nw) // 2, (h - nh) // 2)

        # 亮度匹配：GIMP levels 的 gamma>1 是提亮（曲线 = in^(1/γ)），
        # 所以 γ = ln(新均值/255) / ln(旧均值/255)；保黑保白只动中间调
        if match_brightness and 0.02 < old_mean / 255.0 < 0.98:
            new_mean = _histogram_value_mean(sky_layer)   # 选区仍限定天空区域
            if 0.02 < new_mean / 255.0 < 0.98:
                gamma = math.log(new_mean / 255.0) / math.log(old_mean / 255.0)
                gamma = min(max(gamma, 0.2), 5.0)
                _pdb_run('gimp-drawable-levels', drawable=sky_layer,
                         channel=0, low_input=0.0, high_input=1.0,
                         clamp_input=True, gamma=gamma,
                         low_output=0.0, high_output=1.0, clamp_output=True)

        # 选区 → 天空图层的蒙版：白=天空露出新图，黑=前景盖住新图
        mask = sky_layer.create_mask(Gimp.AddMaskType.SELECTION)
        sky_layer.add_mask(mask)

        _pdb_run('gimp-selection-none', image=image)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return sky_layer, mask, channel


# ---- 程序包装 / procedure wrapper -------------------------------------------

class SkyReplacePlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return ['lb-plugin-sky-replace']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        procedure.set_menu_label(_("Sky Replace"))
        procedure.add_menu_path("<Image>/SuperMrWang/Blend")
        procedure.set_documentation(
            _("Sky Replace: flood-select the sky from the top edge, insert a "
              "sky image below the photo layer and mask it with the selection"),
            _("One-click sky replacement (classic flood-fill segmentation, "
              "cover scaling, brightness matching, selection as layer mask)."),
            name)
        procedure.add_file_argument(
            "sky-file", _("Sky image"),
            _("New sky picture; it is scaled to cover the canvas"),
            Gimp.FileChooserAction.OPEN, False, None,
            GObject.ParamFlags.READWRITE)
        procedure.add_double_argument(
            "threshold", _("Threshold"),
            _("Flood-fill sample threshold (0..0.5)"), 0.0, 0.5, 0.15,
            GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "edge", _("Edge shift"),
            _("Positive shrinks the sky mask by n px, negative grows it"),
            -10, 10, 1, GObject.ParamFlags.READWRITE)
        procedure.add_double_argument(
            "feather", _("Feather"),
            _("Feather radius of the sky mask"), 0.0, 50.0, 2.0,
            GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "match-brightness", _("Match brightness"),
            _("Gamma-match the new sky brightness to the old sky region"),
            True, GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "save-mask-channel", _("Save mask channel"),
            _("Keep the sky mask as a 'Sky Mask' channel for refinement"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no active layer")))
        if not _dialog.run_dialog(procedure, run_mode, config):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, None)
        try:
            sky_replace(image, drawables[0],
                        config.get_property('sky-file'),
                        config.get_property('threshold'),
                        config.get_property('edge'),
                        config.get_property('feather'),
                        config.get_property('match-brightness'),
                        config.get_property('save-mask-channel'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("sky-replace: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(SkyReplacePlugin.__gtype__, sys.argv)
