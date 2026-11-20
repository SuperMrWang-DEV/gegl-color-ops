#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · AI 局部重绘 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   在选区里用 AI 重画。框一块地方，写一句提示词，剩下的交给本机的
           ComfyUI（Stable Diffusion）：插件把选区连同周围一圈裁下来、连蒙版
           一起传给 ComfyUI，等它返回重画好的图，再当成新图层贴回原位，并用
           羽化过的选区做图层蒙版——选区内是新像素，边界自然过渡。
           Inpaint a selection with a local ComfyUI (Stable Diffusion) and
           come back with a new masked layer, in one click.

 menu      SuperMrWang → AI → AI Inpaint

 usage     1. 先建选区（选区可以粗糙，边缘由 grow / feather 收拾）；
           2. 跑本插件，填提示词；
           3. 需要 ComfyUI 在跑（默认 http://127.0.0.1:8188，见 README）。

 requirements
           本机 ComfyUI + 一份 SD1.5 底模。插件只用标准库发 HTTP，HTTP 与
           PNG 部分在 plugin/_shared/ai_client.py 里，tools/check_ai_inpaint.py
           拿 mock 服务测它（不需要显卡）。

 note      三个坑（都已在代码里绕开）：
           1. ComfyUI 的 LoadImage 用 **alpha 倒推** mask（mask = 1 - alpha），
              所以白＝要重绘的区域必须写成透明；直接送灰度图会得到全 0 的
              mask，跑完像素纹丝不动；
           2. VAE 是 8× 下采样，裁剪框宽高不是 8 的倍数就会截断，回来的图比
              请求的小，贴回去错位——所以 bbox 一律对齐到 8；
           3. 9 通道的 inpaint 专用底模在 ComfyUI v0.46 上不生效（开关
              noise_mask 都不改像素），工作流走普通 SD1.5 + VAEEncodeForInpaint。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os
import sys
import tempfile

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject, Gio

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

try:
    import ai_client
except Exception as _exc:          # 没带 _shared/ai_client.py 的裸装情况
    ai_client = None
    _AI_IMPORT_ERROR = _exc


# ---- 常量 -------------------------------------------------------------------

MASK_CHANNEL = "AI Mask"
RESULT_LAYER = "AI Inpaint"

DEFAULT_PROMPT = "clean background, seamless, photorealistic, sharp focus"
DEFAULT_NEGATIVE = "blurry, low quality, watermark, text, deformed"

# 周边带多少像素一起送进模型：只给一条缝的话，模型接不上左右两边的纹理和
# 光线；给一圈上下文，重绘处的颜色/光照才对得上。
CONTEXT_PAD = 32


# ---- PDB 小工具 / PDB helpers ----------------------------------------------

def _pdb(name, **props):
    """按名调用 PDB 过程 / call a PDB procedure by name"""
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


# ---- 读像素 / read pixels ---------------------------------------------------

def read_region(layer, x, y, w, h):
    """读图层的一块区域，返回 RGBA 8 位紧排字节（行序自上而下）。

    让 babl 直接转成 u8 比「读 float 再在 Python 里乘 255」快一个数量级
    —— 1 万像素的选区和 400 万的选区差的是秒级。
    Read an RGBA-u8 slab; babl does the conversion, so no per-pixel Python.
    """
    rect = Gegl.Rectangle.new(x, y, w, h)
    raw = layer.get_buffer().get(rect, 1.0, "R'G'B'A u8",
                                 Gegl.AbyssPolicy.NONE)
    data = bytes(bytearray(raw))
    if len(data) != w * h * 4:
        raise RuntimeError(_("Failed to read layer pixels: expected %d bytes, got %d")
                           % (w * h * 4, len(data)))
    return data


def read_mask(image, x, y, w, h):
    """读当前选区的一块，返回灰度 8 位（选中=255，未选=0）。"""
    sel = image.get_selection()
    if sel is None:
        raise RuntimeError(_("No selection"))
    rect = Gegl.Rectangle.new(x, y, w, h)
    raw = sel.get_buffer().get(rect, 1.0, "Y u8", Gegl.AbyssPolicy.NONE)
    data = bytes(bytearray(raw))
    if len(data) != w * h:
        raise RuntimeError(_("Failed to read the selection buffer: expected %d bytes, got %d")
                           % (w * h, len(data)))
    return data


def selection_box(image):
    """当前选区的外接框；没有选区返回 None。"""
    sel = image.get_selection()
    if sel is None:
        return None
    ok, non_empty, x1, y1, x2, y2 = sel.bounds(image)
    if not non_empty or x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


# ---- 裁切框 / crop rect -----------------------------------------------------

def crop_rect(image, box, grow=8, pad=CONTEXT_PAD):
    """选区外接框 → 「加宽 + 对齐」后的裁切框 (x, y, w, h)。

    两步：先按 grow 外扩（蒙版往前提一点，接缝不会留一圈原像素），再按 pad
    带上周围上下文，最后由 ai_client.align_rect 把宽高对齐到 8 的倍数。
    """
    iw, ih = image.get_width(), image.get_height()
    x1, y1, x2, y2 = box
    x1 -= grow + pad
    y1 -= grow + pad
    x2 += grow + pad
    y2 += grow + pad
    x1 = max(0, min(iw - 1, x1))
    y1 = max(0, min(ih - 1, y1))
    x2 = max(x1 + 1, min(iw, x2))
    y2 = max(y1 + 1, min(ih, y2))
    return ai_client.align_rect(x1, y1, x2 - x1, y2 - y1, iw, ih)


# ---- 贴回 / paste back ------------------------------------------------------

def paste_result(image, drawable, png_path, rect, mask_channel):
    """把重绘结果贴成新图层，位置对齐原裁切框，蒙版取 mask_channel。

    返回新图层。返回图尺寸与请求不符时（服务端截断过）先缩回原尺寸，免得
    贴上去整体错位。
    """
    x, y, w, h = rect
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image,
                                 Gio.File.new_for_path(png_path))
    if layer is None:
        raise RuntimeError(_("Could not read the inpainting result (%s)") % png_path)
    if (layer.get_width(), layer.get_height()) != (w, h):
        _pdb('gimp-layer-scale', layer=layer, new_width=w, new_height=h,
             local_origin=False)
    layer.set_name(RESULT_LAYER)
    pos = image.get_item_position(drawable)
    image.insert_layer(layer, None, pos)
    layer.set_offsets(x, y)

    if mask_channel is not None:
        image.select_item(Gimp.ChannelOps.REPLACE, mask_channel)
        mask = layer.create_mask(Gimp.AddMaskType.SELECTION)
        layer.add_mask(mask)
    return layer


# ---- 主流程 / the whole thing ----------------------------------------------

def ai_inpaint(image, drawable, prompt, negative=DEFAULT_NEGATIVE,
               server="", checkpoint="", steps=25, cfg=7.5, seed=-1,
               denoise=1.0, grow=8, grow_mask_by=8, feather=4.0,
               timeout=600.0, keep_mask=True, client=None, on_tick=None):
    """选区 → AI 重绘 → 新图层。返回 (layer, info)。

    client 参数是给回归脚本塞 mock 用的；正常情况留空，按 server 现建一个。
    """
    if ai_client is None:
        raise RuntimeError(_("plugin/_shared/ai_client.py is missing: install the _shared "
                             "folder next to the plug-in"))
    if not prompt or not prompt.strip():
        raise RuntimeError(_("The prompt is empty: describe what should appear "
                        "(English works best)"))

    box = selection_box(image)
    if box is None:
        raise RuntimeError(
            _("Make a selection first: frame what you want repainted "
              "(a rough one is fine — grow/feather cleans up the edges)."))

    undo_started = False
    result = None
    tmpdir = tempfile.mkdtemp(prefix="lb-ai-inpaint-")
    png_path = os.path.join(tmpdir, "result.png")
    try:
        image.undo_group_start()
        undo_started = True

        # 1) 选区外扩：蒙版往前吃一点，接缝处不会露出原像素
        if grow > 0:
            _pdb('gimp-selection-grow', image=image, steps=int(grow))

        rect = crop_rect(image, selection_box(image) or box, grow=0)
        x, y, w, h = rect
        Gimp.progress_init(_("AI Inpaint"))

        # 2) 送出去的两张图：裁切区域 + 硬边蒙版（白=重绘）
        gray = read_mask(image, x, y, w, h)
        flat = Gimp.Layer.new_from_visible(image, image, "lb-ai-src")
        try:
            src = read_region(flat, x, y, w, h)
        finally:
            flat.delete()

        # 3) 贴回时用的软边蒙版：羽化后存成通道，等结果回来再选它
        mask_channel = None
        if feather > 0:
            _pdb('gimp-selection-feather', image=image, radius=float(feather))
        mask_channel = _pdb('gimp-selection-save', image=image).index(1)
        mask_channel.set_name(MASK_CHANNEL)

        # 4) 交给 ComfyUI
        if client is None:
            client = ai_client.ComfyClient(server, timeout=min(timeout, 60.0))
        seed = ai_client.random_seed() if int(seed) < 0 else int(seed)
        blob, info = ai_client.inpaint(
            client,
            ai_client.rgba_png(w, h, src),
            ai_client.mask_png(w, h, gray),
            prompt.strip(), negative=negative or "", checkpoint=checkpoint,
            steps=int(steps), cfg=float(cfg), seed=seed,
            denoise=float(denoise), grow_mask_by=int(grow_mask_by),
            timeout=float(timeout), on_tick=on_tick or Gimp.progress_pulse)

        # 5) 落盘 → 当图层读回来（GIMP 自己解 PNG，比手写解码靠谱）
        with open(png_path, "wb") as fh:
            fh.write(blob)
        result = paste_result(image, drawable, png_path, rect, mask_channel)
        info["rect"] = rect
        info["seed"] = seed

        _pdb('gimp-selection-none', image=image)
        if not keep_mask and mask_channel is not None:
            image.remove_channel(mask_channel)
    finally:
        if undo_started:
            image.undo_group_end()
        try:
            os.remove(png_path)
        except OSError:
            pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
        Gimp.progress_end()
    Gimp.displays_flush()
    return result, info


# ---- 程序包装 / procedure wrapper ------------------------------------------

class AiInpaintPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return ['lb-plugin-ai-inpaint']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        procedure.set_menu_label(_("AI Inpaint"))
        procedure.add_menu_path("<Image>/SuperMrWang/AI")
        procedure.set_documentation(
            _("AI Inpaint: repaint the selection with a local ComfyUI / "
              "Stable Diffusion and paste the result back as a masked layer"),
            _("Selection + prompt -> ComfyUI inpaint -> new layer with a "
              "feathered selection mask. Requires a running ComfyUI "
              "(default http://127.0.0.1:8188)."),
            name)

        procedure.add_string_argument(
            "prompt", _("Prompt"),
            _("What should appear in the selection (English works best)"),
            DEFAULT_PROMPT, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument(
            "negative", _("Negative prompt"),
            _("What to keep out of the result"),
            DEFAULT_NEGATIVE, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument(
            "server", _("ComfyUI address"),
            _("Empty = $LB_COMFY_URL, else http://127.0.0.1:8188"),
            "", GObject.ParamFlags.READWRITE)
        procedure.add_string_argument(
            "checkpoint", _("Checkpoint"),
            _("Model file name; empty picks the first one ComfyUI offers"),
            "", GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "steps", _("Steps"), _("Sampling steps (25 is a good default)"),
            1, 150, 25, GObject.ParamFlags.READWRITE)
        procedure.add_double_argument(
            "cfg", _("CFG"), _("Prompt guidance strength"),
            1.0, 20.0, 7.5, GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "seed", _("Seed"), _("Random seed; -1 picks a new one each run"),
            -1, 2 ** 31 - 1, -1, GObject.ParamFlags.READWRITE)
        procedure.add_double_argument(
            "denoise", _("Denoise"),
            _("1.0 fully repaints the masked area, lower keeps more of it"),
            0.1, 1.0, 1.0, GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "grow", _("Grow mask"),
            _("Pixels to expand the selection before sending (softens seams)"),
            0, 64, 8, GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "grow-mask-by", _("Model mask grow"),
            _("Extra pixels the model may touch (8 px = 1 latent cell; "
              "bigger = fewer seams, more drift)"), 0, 64, 8,
            GObject.ParamFlags.READWRITE)
        procedure.add_double_argument(
            "feather", _("Feather"),
            _("Feather radius of the layer mask used when pasting back"),
            0.0, 100.0, 4.0, GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "timeout", _("Timeout (s)"),
            _("How long to wait for ComfyUI before giving up"),
            30, 3600, 600, GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "keep-mask", _("Keep mask channel"),
            _("Keep the 'AI Mask' channel so the result can be re-masked later"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        try:
            ai_inpaint(image, drawables[0],
                       config.get_property('prompt'),
                       config.get_property('negative'),
                       config.get_property('server'),
                       config.get_property('checkpoint'),
                       config.get_property('steps'),
                       config.get_property('cfg'),
                       config.get_property('seed'),
                       config.get_property('denoise'),
                       config.get_property('grow'),
                       config.get_property('grow-mask-by'),
                       config.get_property('feather'),
                       config.get_property('timeout'),
                       config.get_property('keep-mask'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("ai-inpaint: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(AiInpaintPlugin.__gtype__, sys.argv)
