#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 双曲线磨皮（AI 预修）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   结构还是那两条曲线（提亮 / 压暗，各自压在一张蒙版下），区别是
           <b>蒙版已经不是全黑</b>：插件先算出一张参考图（AI 低重绘，或本地
           模糊），再把「参考比原图亮多少 / 暗多少」折成蒙版浓度，预先涂上
           去七成。

           打开文件的人看到的是一张已经做过一轮明暗均化的图：痘印、法令纹
           阴影、油光这些「该提亮的暗块 / 该压暗的亮块」已经被淡淡的白色
           盖住，接着用低透明度画笔在没涂到的地方补几笔就行。

 menu      SuperMrWang → Retouch → 双曲线磨皮（AI 预修）
           图层右键 → SuperMrWang → Retouch → 双曲线磨皮（AI 预修）

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              双曲线磨皮（AI 预修）  组，穿透混合
                ├─ 2 · 压暗（已预涂）  正常 + 压暗曲线 + 预涂蒙版
                ├─ 1 · 提亮（已预涂）  正常 + 提亮曲线 + 预涂蒙版
                └─ 原图层（不动）

           蒙版浓度是按像素自己算的，不是全图一个系数：曲线在暗部与亮部的
           斜率差很多（x + d·4x(1−x) 两端不动），同一个「提亮量」在暗部需要
           更浓的蒙版才够。所以预涂的是「补平差值所需的浓度 × 预修比例」。

 note      为什么预涂不要 100%：一次补平的结果通常过头——参考图本身也有
           误差，而且人眼对「刚好」的判断需要留手。默认 70%，参数可调；
           想完全交给 AI 就设 100%，想只做提示就设 30%。

           原版「双曲线磨皮」一行没改：它给的是全黑蒙版 + 你自己画，这一版
           给的是已经画过一轮的蒙版。两个可以同时装。

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
    import retouch_math as RM
except Exception as _exc:          # 没带 _shared 的裸装情况
    RP = None
    RM = None
    _IMPORT_ERROR = _exc


PROC = 'lb-plugin-ai-dodge-burn'
PROC_LABEL = _("Dodge & Burn (AI prep)")


# ---- 动作 / the action ------------------------------------------------------

def dodge_burn(image, base, prep, amount=0.12, strength=0.7, make_group=True):
    """建两条曲线层，蒙版按差值预涂 white，其余黑（= 不动原图）。"""
    if base is None:
        raise RuntimeError(_("Nothing to work on: no layer."))
    if base.is_group():
        raise RuntimeError(
            _("A layer group has no pixels of its own; pick a raster layer "
              "(right-click the group, then Merge Group)."))
    amount = min(0.4, max(0.01, float(amount)))
    strength = min(1.0, max(0.0, float(strength)))

    ww, wh = prep["work_w"], prep["work_h"]
    dodge, burn = RM.dodge_burn_masks(prep["base_luma"], prep["delta"],
                                      amount, strength)
    w, h = prep["w"], prep["h"]
    if (ww, wh) != (w, h):
        dodge = RP.scale_gray(dodge, ww, wh, w, h)
        burn = RP.scale_gray(burn, ww, wh, w, h)

    parent = base.get_parent()
    position = RP.item_position(image, base)
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
            host = RP.new_group(image, _("Dodge & Burn (AI prep)"),
                                parent, position)

        layers = []
        for name, label, sign, pixels in (
                (_("1 · Dodge (pre-painted)"), _("1 · Dodge curve"), +1.0, dodge),
                (_("2 · Burn (pre-painted)"), _("2 · Burn curve"), -1.0, burn)):
            lay = RP.layer_from_pixels(image, name, w, h, prep["base"],
                                       host, 0, opaque=opaque)
            RP.append_curve(lay, label, RP.curve_fn(amount, sign))
            mask = lay.create_mask(Gimp.AddMaskType.BLACK)
            if mask is not None:
                RP.write_mask_pixels(mask, w, h, pixels)
                lay.add_mask(mask)
            layers.append(lay)

        RP.link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([layers[-1]])
            layers[-1].set_edit_mask(True)
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    return host or layers[-1]


# ---- 程序包装 / procedure wrapper ------------------------------------------

def _add_source_argument(procedure):
    try:
        choice = Gimp.Choice.new()
        choice.add("ai", 0, _("AI reference (ComfyUI, low denoise)"), "")
        choice.add("local", 1, _("Local reference (blurred, no ComfyUI)"), "")
        procedure.add_choice_argument(
            "source", _("Reference from"),
            _("\"AI\" sends the layer through ComfyUI at low denoise; \"Local\" "
              "blurs a downscaled copy. AI falls back to Local when ComfyUI is "
              "not running."),
            choice, "ai", GObject.ParamFlags.READWRITE)
    except Exception:
        procedure.add_string_argument(
            "source", _("Reference from (ai / local)"),
            _("ai = ComfyUI, local = blurred copy"), "ai",
            GObject.ParamFlags.READWRITE)


class AiDodgeBurnPlugin(Gimp.PlugIn):

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
            _("Dodge & Burn (AI prep): the usual dodge and burn curve layers, but "
              "their masks come pre-painted from a reference retouch — white where "
              "the reference is brighter (dodge) or darker (burn). You open a file "
              "with the dodging already started."),
            _("Dodge & burn with masks pre-painted from an AI reference"), name)

        procedure.add_string_argument(
            "prompt", _("What the retouch should look like"),
            _("Only used by the AI reference. Leave empty for \"clean natural skin\"."),
            "", GObject.ParamFlags.READWRITE)
        _add_source_argument(procedure)
        procedure.add_double_argument(
            "amount", _("Curve strength (%)"),
            _("How far each curve lifts or lowers the midtones: 12 means 0.12 at 0.5."),
            1.0, 40.0, 12.0, GObject.ParamFlags.READWRITE)
        procedure.add_double_argument(
            "prepaint", _("Pre-paint amount (%)"),
            _("How much of the measured difference is painted in already. 70 leaves "
              "the last 30% for your brush; 100 hands the whole correction over."),
            0.0, 100.0, 70.0, GObject.ParamFlags.READWRITE)
        procedure.add_double_argument(
            "radius", _("Reference radius (px, local only)"),
            _("Cutoff of the local low-pass reference; ignored by the AI reference."),
            2.0, 128.0, 12.0, GObject.ParamFlags.READWRITE)
        procedure.add_double_argument(
            "denoise", _("AI denoise"),
            _("How far ComfyUI may move the pixels: 0.2 barely touches them, 0.5 "
              "starts changing features."),
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
            _("Puts both curve layers into a pass-through group."),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if RP is None or RM is None:
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
            dodge_burn(image, base, prep,
                       config.get_property("amount") / 100.0,
                       config.get_property("prepaint") / 100.0,
                       config.get_property("group"))
            Gimp.message(RP.summarize(
                prep,
                _("The dodge and burn masks are already painted where the reference "
                  "differs from your layer. Click a mask and paint more white with a "
                  "soft brush to finish; #000000 takes a stroke back.")))
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                               GLib.Error())
        except Exception as exc:
            Gimp.message("ai-dodge-burn: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(AiDodgeBurnPlugin.__gtype__, sys.argv)
