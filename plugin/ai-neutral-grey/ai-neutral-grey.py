#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 中性灰磨皮（AI 预修）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   还是那张 50% 灰、柔光混合的层，区别是<b>它不再是平的 128</b>：
           插件先算一张参考图（AI 低重绘，或本地模糊），把「参考比原图亮多
           少 / 暗多少」反解成柔光需要的灰度，直接写进灰层。

           打开文件的人看到的是一张已经做过一轮中性灰的图：肤色被拉平了一
           截，痘印和阴影被抬起来七成，接着用白 / 黑低透明度画笔在没到位的
           地方补几笔，或者用 #808080 把画过头的地方擦回去。

 menu      SuperMrWang → Retouch → 中性灰磨皮（AI 预修）
           图层右键 → SuperMrWang → Retouch → 中性灰磨皮（AI 预修）

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              中性灰磨皮（AI 预修）    组，穿透混合
                └─ 1 · 中性灰（已预校正）  柔光 + 128±偏移的像素
                   └─ 原图层（不动）

           灰层的每个像素都是「要让这里变成参考图，柔光需要多亮」的解析解，
           不是估的：公式反解见 retouch_math.grey_for_delta，回归里会把灰层
           代回柔光公式验证（误差 ≤ 1 码）。

 note      这张层是像素，不是蒙版——所以它比双曲线那版更「耐改」：橡皮擦、
           选区填充、渐变、复制粘贴都能用，代价是一旦画过头，只能靠 #808080
           盖回去（双曲线那版把蒙版涂黑就行）。

           预修比例默认 70%：参考图本身有误差，一次补平通常过头。参数可调，
           100% 等于完全交给参考图。

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

import lb_dialog as _dialog

try:
    import retouch_prep as RP
    import retouch_math as RM
except Exception as _exc:          # 没带 _shared 的裸装情况
    RP = None
    RM = None
    _IMPORT_ERROR = _exc


PROC = 'lb-plugin-ai-neutral-grey'
PROC_LABEL = _("Neutral Grey (AI prep)")


# ---- 动作 / the action ------------------------------------------------------

def neutral_grey(image, base, prep, strength=0.7, make_group=True):
    """建一张 128±偏移的柔光层；偏移按参考图的差值反解。"""
    if base is None:
        raise RuntimeError(_("Nothing to work on: no layer."))
    if base.is_group():
        raise RuntimeError(
            _("A layer group has no pixels of its own; pick a raster layer "
              "(right-click the group, then Merge Group)."))
    strength = min(1.0, max(0.0, float(strength)))

    ww, wh = prep["work_w"], prep["work_h"]
    grey = RM.grey_for_delta(prep["base_luma"], prep["delta"], strength)
    w, h = prep["w"], prep["h"]
    if (ww, wh) != (w, h):
        grey = RP.scale_gray(grey, ww, wh, w, h)

    # 灰层是 RGB 三通道同值 + 不透明 alpha
    rgba = bytearray(w * h * 4)
    rgba[0::4] = grey
    rgba[1::4] = grey
    rgba[2::4] = grey
    rgba[3::4] = b"\xff" * (w * h)

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
            host = RP.new_group(image, _("Neutral Grey (AI prep)"),
                                parent, position)

        lay = RP.layer_from_pixels(
            image, _("1 · Neutral grey (pre-corrected)"), w, h, bytes(rgba),
            host, 0, mode=Gimp.LayerMode.SOFTLIGHT, opaque=opaque)
        try:
            ok, ox, oy = base.get_offsets()
            if ok:
                lay.set_offsets(ox, oy)
        except Exception:
            pass

        RP.link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([lay])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    return host or lay


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


class AiNeutralGreyPlugin(Gimp.PlugIn):

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
            _("Neutral Grey (AI prep): a 50% grey Soft Light layer whose pixels are "
              "already shifted toward a reference retouch, so the dodging and burning "
              "is partly done when the file opens. White brush lightens, black "
              "darkens, #808080 erases."),
            _("Soft Light grey layer pre-corrected from an AI reference"), name)

        procedure.add_string_argument(
            "prompt", _("What the retouch should look like"),
            _("Only used by the AI reference. Leave empty for \"clean natural skin\"."),
            "", GObject.ParamFlags.READWRITE)
        _add_source_argument(procedure)
        procedure.add_double_argument(
            "prepaint", _("Pre-correct amount (%)"),
            _("How much of the measured difference is baked into the grey layer. "
              "70 leaves the last 30% for your brush."),
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
            _("Puts the grey layer into a pass-through group."),
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
        if not _dialog.run_dialog(procedure, run_mode, config):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, None)
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
            neutral_grey(image, base, prep,
                         config.get_property("prepaint") / 100.0,
                         config.get_property("group"))
            Gimp.message(RP.summarize(
                prep,
                _("The grey layer is no longer flat 128: it already pushes the skin "
                  "toward the reference. Paint white / black at 5–15% to finish, or "
                  "#808080 to take a correction back.")))
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                               GLib.Error())
        except Exception as exc:
            Gimp.message("ai-neutral-grey: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(AiNeutralGreyPlugin.__gtype__, sys.argv)
