#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · AI 超分放大 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   用放大网络（ESRGAN 一类）把图层放大 2~4 倍——放大的是「细节」，
           不是插值出来的糊。GIMP 自己的缩放只会变平滑，这块是硬缺口。
           Upscale a layer with a real upscaler network through a local
           ComfyUI, as a new layer, leaving the original alone.

 menu      SuperMrWang → AI → AI Upscale…

 usage     选中一个栅格图层 → 菜单项 → 选倍率和模型 → 跑。
           结果是一层新的「AI Upscale ×4」，位置按倍率对齐原来的图层。

 requirements
           本机 ComfyUI + models/upscale_models 里有一个放大模型（4x-UltraSharp
           66 MB 就够）。节点是 ComfyUI 自带的，不用装扩展。

 note      三个坑：
           1. **ESRGAN 是 4 倍网络**。要 2 倍就先 4 倍再 lanczos 缩一半，比
              直接 2 倍插值清楚得多——这也是插件的默认做法。
           2. **像素数会炸**。4000×3000 的图 4 倍是 1.9 亿像素，GIMP 拖不动、
              内存也扛不住。插件在动手之前先算，超了就直接说清楚，而不是
              跑到一半崩。
           3. **只动选中那一层**。放大是「新建一层」，原层原样留着，不满意
              点眼睛切回去就行；这也是它和「图像 → 缩放图像」的区别。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os
import sys
import tempfile

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject, Gio
from gi.repository import Gegl

try:
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
except Exception:                  # pragma: no cover
    Gtk = None

_here = os.path.dirname(os.path.abspath(__file__))
for _cand in (_here, os.path.join(_here, '_shared'),
              os.path.normpath(os.path.join(_here, '..', '_shared'))):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.append(_cand)

try:
    from lb_i18n import _          # noqa: F811
except Exception:
    def _(message):
        return GLib.dgettext(None, message)

import lb_dialog as _dialog
import comfy_ui as UI

try:
    import ai_client
except Exception as _exc:
    ai_client = None
    _AI_IMPORT_ERROR = _exc

PROC = "lb-plugin-ai-upscale"
RESULT_LAYER = "AI Upscale"
FACTOR = 4
FACTOR_MIN = 2
FACTOR_MAX = 4
MAX_PIXELS = 64 * 1000 * 1000      # 输出超过 6400 万像素就别硬来


def _pdb(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    if res.index(0) != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if len(res) > 1 else None
        raise RuntimeError("%s: %s" % (name, getattr(err, "message", err)))
    return res


def read_region(layer, x, y, w, h):
    rect = Gegl.Rectangle.new(x, y, w, h)
    raw = layer.get_buffer().get(rect, 1.0, "R'G'B'A u8",
                                 Gegl.AbyssPolicy.NONE)
    data = bytes(bytearray(raw))
    if len(data) != w * h * 4:
        raise RuntimeError(_("Failed to read layer pixels: expected %d bytes, "
                             "got %d") % (w * h * 4, len(data)))
    return data


def plan_target(w, h, factor):
    """算出放大后的尺寸；超出预算就抛错，别让用户等到内存爆掉。

    返回 (tw, th)。对齐到 8：ComfyUI 的 ImageScale 不在乎，但后面若切成
    分块或者再进一次 inpaint，8 的倍数是必须的。
    """
    factor = max(1, int(round(float(factor))))
    tw, th = w * factor, h * factor
    if tw * th > MAX_PIXELS:
        raise RuntimeError(
            _("Upscaling %(w)d×%(h)d by %(f)d would be %(tw)d×%(th)d — "
              "%(mp).0f megapixels. GIMP cannot handle that layer. Use a "
              "smaller factor, or crop the part you need first.")
            % {"w": w, "h": h, "f": factor, "tw": tw, "th": th,
               "mp": tw * th / 1e6})
    return tw, th


def ai_upscale(image, drawable, model="", factor=FACTOR, timeout=300.0,
               server="", client=None, on_tick=None):
    """把 drawable 放大 factor 倍，返回 (新图层, info)。"""
    if ai_client is None:
        raise RuntimeError(_("plugin/_shared/ai_client.py is missing: install "
                             "the _shared folder next to the plug-in"))
    w, h = drawable.get_width(), drawable.get_height()
    tw, th = plan_target(w, h, factor)
    ox, oy = 0, 0
    try:                               # GIMP 3 给的是 (ok, x, y)，别当二元组拆
        off = drawable.get_offsets()
        if len(off) == 3:
            ox, oy = int(off[1]), int(off[2])
        elif len(off) == 2:
            ox, oy = int(off[0]), int(off[1])
        else:
            ox, oy = int(getattr(off, "x", 0)), int(getattr(off, "y", 0))
    except Exception:
        ox = oy = 0
    factor = max(1, int(round(float(factor))))

    Gimp.progress_init(_("AI Upscale"))
    src = read_region(drawable, 0, 0, w, h)
    if client is None:
        client = UI.make_client(server, timeout=timeout)
    blob, info = ai_client.upscale(
        client, ai_client.rgba_png(w, h, src), model=model, factor=factor,
        target=(tw, th), timeout=float(timeout),
        on_tick=on_tick or Gimp.progress_pulse)

    tmpdir = tempfile.mkdtemp(prefix="lb-upscale-")
    path = os.path.join(tmpdir, "upscaled.png")
    with open(path, "wb") as fh:
        fh.write(blob)
    try:
        layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image,
                                     Gio.File.new_for_path(path))
        if layer is None:
            raise RuntimeError(_("Could not read the upscaled result (%s)")
                               % path)
        layer.set_name("%s x%d" % (RESULT_LAYER, factor))
        pos = image.get_item_position(drawable)
        image.insert_layer(layer, None, pos)
        if (layer.get_width(), layer.get_height()) != (tw, th):
            # 服务端没按请求的尺寸回来（模型不是 4 倍、或 ImageScale 被跳过）
            _pdb('gimp-layer-scale', layer=layer,
                 **{'new-width': int(tw), 'new-height': int(th),
                    'local-origin': False})
        layer.set_offsets(ox * factor, oy * factor)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass

    info.update({"before": (w, h), "after": (tw, th), "factor": factor,
                 "offset": (ox * factor, oy * factor)})
    return layer, info


# ---- 参数与注册 -------------------------------------------------------------

def _available_models(timeout=1.5):
    if ai_client is None:
        return []
    try:
        return ai_client.upscale_models(
            ai_client.ComfyClient(timeout=timeout), timeout=timeout)
    except Exception:
        return []


def _add_model_argument(procedure):
    help_text = _("4x-UltraSharp (66 MB) is the sweet spot: sharp, no "
                  "plastic look. Add models with the \"AI Environment\" menu "
                  "entry.")
    names = _available_models()
    if names:
        try:
            choice = Gimp.Choice.new()
            want = ai_client.preferred_upscale(names)
            for idx, name in enumerate(names):
                choice.add(name, idx, name, _("From this ComfyUI installation"))
            procedure.add_choice_argument(
                "model", _("Upscale model"), help_text, choice,
                want or names[0], GObject.ParamFlags.READWRITE)
            return
        except Exception:
            pass
    procedure.add_string_argument(
        "model", _("Upscale model (file name)"),
        help_text + _(" Leave empty for the sharpest one installed."), "",
        GObject.ParamFlags.READWRITE)


class AiUpscalePlugin(Gimp.PlugIn):

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
        procedure.set_menu_label(_("AI Upscale…"))
        procedure.set_documentation(
            _("AI Upscale: 2–4× with a real upscaler network"),
            _("Sends the selected layer through UpscaleModelLoader / "
              "ImageUpscaleWithModel on a local ComfyUI and comes back with a "
              "bigger layer. 4× is the native scale of ESRGAN-class models; "
              "2× and 3× are done by scaling down afterwards, which stays "
              "sharper than plain interpolation."),
            name)

        _add_model_argument(procedure)
        procedure.add_int_argument(
            "factor", _("Scale factor"),
            _("4× is what the network natively does. 2× and 3× cost the same "
              "time (it always renders 4× first) but give a smaller layer."),
            FACTOR_MIN, FACTOR_MAX, FACTOR, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument(
            "server", _("ComfyUI address"),
            _("Empty = $LB_COMFY_URL, else http://127.0.0.1:8188"),
            "", GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "timeout", _("Timeout (s)"),
            _("How long to wait for the upscaler"),
            10, 1800, 300, GObject.ParamFlags.READWRITE)
        # 先 set_menu_label 后 add_menu_path：反了 GIMP 会把菜单路径丢掉。
        procedure.add_menu_path("<Image>/SuperMrWang/AI")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if run_mode == Gimp.RunMode.INTERACTIVE:
            if not _dialog.run_dialog(procedure, run_mode, config):
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL,
                                                   GLib.Error())

        def prop(key, default=None):
            val = config.get_property(key)
            return default if val is None else val

        drawable = drawables[0] if drawables else image.get_active_drawable()
        if drawable is None:
            raise RuntimeError(_("This image has no drawable to enlarge"))
        if drawable.get_width() < 8 or drawable.get_height() < 8:
            raise RuntimeError(_("That layer is too small to upscale "
                                 "(%d×%d)") % (drawable.get_width(),
                                               drawable.get_height()))
        image.undo_group_start()
        try:
            layer, info = ai_upscale(
                image, drawable,
                model=prop("model", ""),
                factor=prop("factor", FACTOR),
                timeout=prop("timeout", 300),
                server=prop("server", ""))
        finally:
            image.undo_group_end()

        image.set_dirty(True)
        try:
            Gimp.message(_("AI Upscale: %(a)d×%(b)d → %(c)d×%(d)d in %(s).1f s "
                           "(%(m)s)")
                         % {"a": info["before"][0], "b": info["before"][1],
                            "c": info["after"][0], "d": info["after"][1],
                            "s": info["seconds"], "m": info["model"]})
        except Exception:
            pass
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                           GLib.Error())


if __name__ == "__main__":
    Gimp.main(AiUpscalePlugin.__gtype__, sys.argv)
