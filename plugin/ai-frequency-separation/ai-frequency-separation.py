#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 高低频磨皮（AI 预修）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   和「高低频磨皮」搭出来的结构完全一样（低频 = 高斯模糊、高频 =
           颗粒合并 + 高通），唯一的区别：两层的内容不是原图，而是<b>已经修
           过一遍的参考图</b>。

           参考图来自两条路，参数里选：
             AI 参考      ComfyUI 整图低重绘（denoise 0.35）——它认得「这是
                          皮肤」，痘印、泛红、局部色块会被推平，五官和轮廓
                          留住；
             本地参考     整层降采样再放大当低通（毫秒级，零依赖）。

           所以打开这个文件的人看到的不是一张「等你从零开始修」的图，而是
           一张已经做过七成、剩下三成留手的图：低频层上的色块已经铺平，高频
           层上的痘印已经淡掉，接着在高频层补几笔就行。

 menu      SuperMrWang → Retouch → 高低频磨皮（AI 预修）
           图层右键 → SuperMrWang → Retouch → 高低频磨皮（AI 预修）

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              高低频磨皮（AI 预修）   组，穿透混合
                ├─ 2 · 高频（细节）   颗粒合并 + 高通
                ├─ 1 · 低频（影调）   正常 + 高斯模糊
                └─ 原图层（不动，隐藏它也不掉东西）

           两层合成 = 参考图（不是原图），这就是「工作痕迹」：AI 修过的那
           一版已经在画面上了。想对比就按住 Shift 点组的眼睛，或直接关掉组。

           选区存在时，参考图只在选区内替换原图，选区外逐像素等于原图——
           所以可以只修脸、不动头发和背景。

 note      为什么两个入口都留着：原版插件是「干净结构 + 你自己修」，这一版
           是「结构 + 预修」。原版一行没改，两个可以同时装在菜单里。

           高频层恒等的算法与原版一致：H = 0.5 + (参考 − 低频)，颗粒合并叠
           回去 H + L − 0.5 = 参考。所以两层自己就能还原参考图，半径随时可
           以改，改完还是参考图。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os as _os
import sys
import sys as _sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject

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

try:
    import retouch_prep as RP
except Exception as _exc:          # 没带 _shared 的裸装情况
    RP = None
    _IMPORT_ERROR = _exc


PROC = 'lb-plugin-ai-frequency-separation'
PROC_LABEL = _("Frequency Separation (AI prep)")


# ---- 动作 / the action ------------------------------------------------------

def separate(image, base, prep, radius=8.0, make_group=True):
    """按参考图搭「低频 + 高频」两层；合成结果 = 参考图。"""
    if base is None:
        raise RuntimeError(_("Nothing to split: no layer."))
    if base.is_group():
        raise RuntimeError(
            _("A layer group cannot be split; pick a raster layer first "
              "(right-click the group, then Merge Group)."))
    radius = max(0.2, float(radius))

    parent = base.get_parent()
    position = RP.item_position(image, base)
    w, h = prep["w"], prep["h"]
    opaque = False
    try:
        opaque = bool(base.has_alpha())
    except Exception:
        pass

    auto_group = False
    if not make_group:
        if opaque:
            make_group = True
            auto_group = True

    image.undo_group_start()
    try:
        host = None
        if make_group:
            host = RP.new_group(image, _("Frequency Separation (AI prep)"),
                                parent, position)

        low = RP.layer_from_pixels(
            image, _("1 · Low frequency (tone)"), w, h, prep["ref"],
            host, 0, opaque=opaque)
        RP.append_blur(low, radius)

        high = RP.layer_from_pixels(
            image, _("2 · High frequency (detail)"), w, h, prep["ref"],
            host, 0, mode=Gimp.LayerMode.GRAIN_MERGE, opaque=opaque)
        RP.append_highpass(high, radius)

        RP.link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([high])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    return host or high


# ---- 程序包装 / procedure wrapper ------------------------------------------

def _add_source_argument(procedure):
    """参考图来源。Gimp.Choice 造不出来就退回字符串参数。"""
    try:
        choice = Gimp.Choice.new()
        # gimp_choice_add(choice, nick, id, label, help)：help 不能是 None
        choice.add("ai", 0, _("AI reference (ComfyUI, low denoise)"), "")
        choice.add("local", 1, _("Local reference (blurred, no ComfyUI)"), "")
        procedure.add_choice_argument(
            "source", _("Reference from"),
            _("\"AI\" sends the layer through ComfyUI at low denoise; \"Local\" "
              "blurs a downscaled copy instead. AI falls back to Local when "
              "ComfyUI is not running."),
            choice, "ai", GObject.ParamFlags.READWRITE)
    except Exception:
        procedure.add_string_argument(
            "source", _("Reference from (ai / local)"),
            _("ai = ComfyUI, local = blurred copy"), "ai",
            GObject.ParamFlags.READWRITE)


class AiFrequencySeparationPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(PROC_LABEL)
        procedure.add_menu_path("<Image>/SuperMrWang/Retouch")
        procedure.add_menu_path("<Layers>/SuperMrWang/Retouch")
        procedure.set_documentation(
            _("Frequency Separation (AI prep): builds the usual low/high frequency "
              "pair, but the pixels come from a reference that was already retouched "
              "— a low-denoise ComfyUI pass or a blurred copy. The composite is that "
              "reference, so you open a file with the work already started."),
            _("Low/high frequency pair built on a pre-retouched reference"), name)

        procedure.add_string_argument(
            "prompt", _("What the retouch should look like"),
            _("Only used by the AI reference. Leave empty for \"clean natural skin\"."),
            "", GObject.ParamFlags.READWRITE)
        _add_source_argument(procedure)
        procedure.add_double_argument(
            "radius", _("Split radius (px)"),
            _("Standard deviation of the low-frequency blur; also the cutoff between "
              "tone and texture."),
            0.2, 100.0, 8.0, GObject.ParamFlags.READWRITE)
        procedure.add_double_argument(
            "denoise", _("AI denoise"),
            _("How far ComfyUI may move the pixels: 0.2 barely touches them, 0.5 "
              "starts changing features. Ignored by the local reference."),
            0.05, 0.9, 0.35, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument(
            "server", _("ComfyUI address"),
            _("Empty = $LB_COMFY_URL, else http://127.0.0.1:8188"),
            "", GObject.ParamFlags.READWRITE)
        procedure.add_string_argument(
            "checkpoint", _("Checkpoint"),
            _("Model file name; empty picks the first one ComfyUI offers"),
            "", GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "steps", _("AI steps"), _("Sampling steps for the reference pass"),
            1, 60, 20, GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "group", _("Put in a layer group"),
            _("Puts both layers into a pass-through group; turn it off to stack them "
              "directly above the original layer."),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if RP is None:
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR,
                GLib.Error(_("plugin/_shared/retouch_prep.py is missing: install the "
                             "_shared folder next to the plug-in")))
        if image is None or len(drawables) != 1:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("Select exactly one layer.")))
        try:
            base = drawables[0]
            prep = RP.prepare(
                image, base,
                source=config.get_property("source") or "ai",
                radius=config.get_property("radius"),
                denoise=config.get_property("denoise"),
                prompt=config.get_property("prompt") or "",
                server=config.get_property("server") or "",
                checkpoint=config.get_property("checkpoint") or "",
                steps=config.get_property("steps"))
            separate(image, base, prep,
                     config.get_property("radius"),
                     config.get_property("group"))
            Gimp.message(RP.summarize(
                prep,
                _("The low layer already has the reference's tone, the high layer its "
                  "texture: refine on the high layer, adjust colour on the low one. "
                  "Hide the group to compare with the original.")))
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                               GLib.Error())
        except Exception as exc:
            Gimp.message("ai-frequency-separation: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(AiFrequencySeparationPlugin.__gtype__, sys.argv)
