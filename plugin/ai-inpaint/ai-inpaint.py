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

 menu      SuperMrWang → AI → AI Inpaint…（简版：只问画什么）
           SuperMrWang → AI → AI Inpaint (Advanced)…（全参数）

 usage     1. 先建选区（选区可以粗糙，边缘由 grow / feather 收拾）；
           2. 跑本插件，填提示词——常用词可以直接写中文（prompt_tools
              会翻成英文），或者在下拉里选个主体；
           3. 需要 ComfyUI 在跑（默认 http://127.0.0.1:8188，见 README）。

 requirements
           本机 ComfyUI + 一份 SD1.5 底模。插件只用标准库发 HTTP，HTTP 与
           PNG 部分在 plugin/_shared/ai_client.py 里，tools/check_ai_inpaint.py
           拿 mock 服务测它（不需要显卡）。

 note      四个坑（都已在代码里绕开）：
           1. ComfyUI 的 LoadImage 用 **alpha 倒推** mask（mask = 1 - alpha），
              所以白＝要重绘的区域必须写成透明；直接送灰度图会得到全 0 的
              mask，跑完像素纹丝不动；
           2. VAE 是 8× 下采样，裁剪框宽高不是 8 的倍数就会截断，回来的图比
              请求的小，贴回去错位——所以 bbox 一律对齐到 8；
           3. 9 通道的 inpaint 专用底模在 ComfyUI v0.46 上不生效（开关
              noise_mask 都不改像素），工作流走普通 SD1.5 + VAEEncodeForInpaint；
           4. **画幅比例**。SD 只在自己训练过的比例附近画得对，选区是眼睛那
              样一条 1024×400（2.56:1）时，SDXL 会把整块画成平涂海报——一句
              "sunglasses" 出来是一块绿底配重复白色箭头（2026-11-23 用户报的
              「输入 sunglasses 却给了我这个」）。ai_client.plan_canvas_rect()
              会把画布补到 ≤2:1（优先往画面里长真像素，画布到边才复制边缘），
              补出来的那圈贴回时被蒙版挡住，不会露出来。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os
import re
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

import lb_dialog as _dialog

try:
    import ai_client
except Exception as _exc:          # 没带 _shared/ai_client.py 的裸装情况
    ai_client = None
    _AI_IMPORT_ERROR = _exc

try:
    import prompt_tools
except Exception:                  # 没带 prompt_tools.py：只用英文，不影响其他功能
    prompt_tools = None


# ---- 常量 -------------------------------------------------------------------

MASK_CHANNEL = "AI Mask"
RESULT_LAYER = "AI Inpaint"

# 提示词**故意留空**：以前这里预填了一句 "clean background, seamless…"，
# 结果点菜单直接确定的人会得到一块跟画面毫无关系的干净色块——AI 老老实实
# 画了「干净背景」，只是没人要。现在空着，不填就报错说清楚怎么填。
DEFAULT_PROMPT = ""
# 底模在「比例不正常 + 全量重绘」时会往平涂海报的方向跑（画出来像矢量插画、
# 甚至像路牌）。这是照片修图插件，所以默认把插画类风格压在负面里——用户想
# 要画风自己改这一栏就行。
DEFAULT_NEGATIVE = ("blurry, low quality, watermark, text, deformed, "
                    "illustration, cartoon, flat graphic, poster, "
                    "vector art, cgi, 3d render")

# SD1.5 / SDXL 的文本编码器只认英文（OpenCLIP，词表里没有汉字）。中文提示词
# 会被切成一片未知 token，等价于「随机重绘」——这是「画出来的东西跟图完全不
# 搭」最常见的原因，比模型能力问题的概率高得多，所以直接拦下来。
_CJK_RE = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
                     "\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")


def _check_prompt(prompt, preset="none"):
    """空提示词不往下走；中文先翻成英文再判断。

    以前这里是一刀切「有汉字就报错」——技术上正确，用起来很糟：用户脑子里
    的话就是「画一只小猫」。现在 prompt_tools 有一张常用词表，能翻的直接翻；
    翻不掉的词点名报出来，绝不把半截中文静默送进模型（那等于随机重绘）。
    """
    text = (prompt or "").strip()
    if prompt_tools is not None:
        try:
            final = prompt_tools.compose(text, preset)
        except ValueError as exc:
            raise RuntimeError(
                _("Some words in the prompt are not in the built-in Chinese "
                  "dictionary: %s. SD models only read English — rephrase with "
                  "common words, or write that part in English.") % str(exc))
        if not final:
            raise RuntimeError(
                _("The prompt is empty — this box is what the AI paints, so it "
                  "must say what should appear. Describe the RESULT, not the thing "
                  "you want gone: to erase a bottle, write \"empty wooden table, "
                  "wood grain\" instead of \"remove the bottle\"."))
        return final

    # 没有 prompt_tools（裸装）：退回老规则，至少不静默送中文
    if not text:
        raise RuntimeError(
            _("The prompt is empty — this box is what the AI paints, so it "
              "must say what should appear. Describe the RESULT, not the thing "
              "you want gone: to erase a bottle, write \"empty wooden table, "
              "wood grain\" instead of \"remove the bottle\"."))
    if _CJK_RE.search(text):
        raise RuntimeError(
            _("The prompt contains Chinese/Japanese/Korean characters. SD1.5 "
              "and SDXL can only read English — anything else is treated as "
              "random noise, which is why the result looked unrelated to your "
              "picture. Write it in English, e.g. \"empty wooden table, wood "
              "grain, soft daylight\", and put what you want removed into the "
              "negative prompt."))
    return text

# 周边带多少像素一起送进模型：只给一条缝的话，模型接不上左右两边的纹理和
# 光线；给一圈上下文，重绘处的颜色/光照才对得上。
CONTEXT_PAD = 32


# ---- PDB 小工具 / PDB helpers ----------------------------------------------

def _pdb(name, **props):
    """按名调用 PDB 过程 / call a PDB procedure by name

    proc.run() 不抛异常——失败只是把状态塞在返回值第 0 位，不看就等于静默
    失败（2026-11-20 踩过：layer-scale 参数名写错，缩放没做，贴回去整块错位）。
    """
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    status = res.index(0)
    if status != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if len(res) > 1 else None
        raise RuntimeError("%s: %s" % (name, getattr(err, "message", err)))
    return res


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


# ---- 缩放 / resize ----------------------------------------------------------
# 底模有它自己的舒适分辨率（SD1.5 ≈ 512、SDXL ≈ 1024），裁切框大小由用户选区
# 决定，两者一般对不上。送模型前把这块缩放到目标长边，回来再缩回原尺寸贴。
#
# 走 GIMP 自己的重采样（gimp-layer-scale）而不是在 Python 里逐像素插值：
# 512² 的单精度插值在 Python 里要 1~2 秒，而这里只是内存里一次 C 调用。

def _scale_rgba(data, w, h, nw, nh):
    """把一块 RGBA 8 位紧排像素缩放到 nw×nh，返回同格式字节。"""
    if (w, h) == (nw, nh):
        return data
    tmp = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    try:
        layer = Gimp.Layer.new(tmp, "lb-scale", w, h,
                               Gimp.ImageType.RGBA_IMAGE, 100.0,
                               Gimp.LayerMode.NORMAL)
        tmp.insert_layer(layer, None, 0)
        # 直接往 shadow buffer 里灌：比建选区再 fill 少绕两圈，颜色也确定
        shadow = layer.get_shadow_buffer()
        shadow.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", data)
        shadow.flush()
        layer.merge_shadow(True)
        if (w, h) != (nw, nh):
            # PDB 的参数名是连字符（new-width），写成 new_width 会报
            # "Calling error"——GObject 属性名和 PDB 参数名不是一回事
            _pdb('gimp-layer-scale', layer=layer,
                 **{'new-width': int(nw), 'new-height': int(nh),
                    'local-origin': False})
        return read_region(layer, 0, 0, nw, nh)
    finally:
        # 不收尾 GIMP 会在日志里报「插件漏出了图像」
        tmp.delete()


def _scale_gray(data, w, h, nw, nh):
    """单通道灰度（选区内 255 / 外 0）缩放。借用 RGBA 通道跑同一条重采样。"""
    if (w, h) == (nw, nh):
        return data
    # 切片赋值是 C 级 memcpy，比逐像素循环快两个数量级（1024² 差 200ms）
    rgba = bytearray(w * h * 4)
    rgba[0::4] = data
    rgba[1::4] = data
    rgba[2::4] = data
    rgba[3::4] = b"\xff" * (w * h)
    out = _scale_rgba(bytes(rgba), w, h, nw, nh)
    return bytes(out[0::4])


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
    layer.set_name(RESULT_LAYER)
    pos = image.get_item_position(drawable)
    # 先插进图像再缩放：file_load_layer 返回的图层还没归属任何图像，此时
    # gimp-layer-scale 会报 "cannot be used because it has not been added to an
    # image"（2026-11-20）
    image.insert_layer(layer, None, pos)
    if (layer.get_width(), layer.get_height()) != (w, h):
        _pdb('gimp-layer-scale', layer=layer,
             **{'new-width': w, 'new-height': h, 'local-origin': False})
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
               timeout=600.0, keep_mask=True, scale=0.0, client=None,
               on_tick=None, preset="none"):
    """选区 → AI 重绘 → 新图层。返回 (layer, info)。

    client 参数是给回归脚本塞 mock 用的；正常情况留空，按 server 现建一个。
    scale 是送给模型前的缩放倍率；0 = 按底模自动算（SD1.5→512、SDXL→1024）。
    preset 是「菜里先放一份主料」：选「小猫」就相当于提示词前面带上
    "a small cat, fluffy fur, detailed eyes"，用户写的细节再接在后面。
    """
    if ai_client is None:
        raise RuntimeError(_("plugin/_shared/ai_client.py is missing: install the _shared "
                             "folder next to the plug-in"))
    prompt = _check_prompt(prompt, preset)
    if prompt_tools is not None and negative:
        negative = prompt_tools.polish_negative(negative)

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
        iw, ih = image.get_width(), image.get_height()
        # 4) 画布比例：超宽/超高的裁剪条会被 SD 画成「平涂海报 + 重复图形」，
        #    所以先往画面里长高（真实上下文最好），画布到边了才补边。
        cx, cy, cw, ch, pl, pt, pr, pb = ai_client.plan_canvas_rect(
            rect[0], rect[1], rect[2], rect[3], iw, ih)
        Gimp.progress_init(_("AI Inpaint"))

        # 2) 送出去的两张图：裁切区域 + 硬边蒙版（白=重绘）
        #    画布可以超出图像边界，先求交再补边
        ix1, iy1 = max(0, cx), max(0, cy)
        ix2 = min(iw, cx + cw)
        iy2 = min(ih, cy + ch)
        rw, rh = ix2 - ix1, iy2 - iy1
        if rw <= 0 or rh <= 0:
            raise RuntimeError(_("The selection is outside the image"))
        gray = read_mask(image, ix1, iy1, rw, rh)
        flat = Gimp.Layer.new_from_visible(image, image, "lb-ai-src")
        try:
            src = read_region(flat, ix1, iy1, rw, rh)
        finally:
            flat.delete()
        src = ai_client.pad_edge_rgba(src, rw, rh, ix1 - cx, iy1 - cy,
                                      (cx + cw) - ix2, (cy + ch) - iy2)[2]
        gray = ai_client.pad_gray(gray, rw, rh, ix1 - cx, iy1 - cy,
                                  (cx + cw) - ix2, (cy + ch) - iy2)[2]
        w, h = cw, ch

        # 3) 贴回时用的软边蒙版：羽化后存成通道，等结果回来再选它
        mask_channel = None
        if feather > 0:
            _pdb('gimp-selection-feather', image=image, radius=float(feather))
        mask_channel = _pdb('gimp-selection-save', image=image).index(1)
        mask_channel.set_name(MASK_CHANNEL)

        # 5) 缩放到这个底模的舒适长边，再交给 ComfyUI
        if client is None:
            client = ai_client.ComfyClient(server, timeout=min(timeout, 60.0))
        checkpoint = checkpoint or client.first_checkpoint()
        target = ai_client.family_target(checkpoint)
        factor = float(scale) if float(scale) > 0 else ai_client.work_scale(w, h, target)
        ww = max(ai_client.SIZE_ALIGN,
                 int(round(w * factor)) // ai_client.SIZE_ALIGN * ai_client.SIZE_ALIGN)
        hh = max(ai_client.SIZE_ALIGN,
                 int(round(h * factor)) // ai_client.SIZE_ALIGN * ai_client.SIZE_ALIGN)
        src_work = _scale_rgba(src, w, h, ww, hh)
        gray_work = _scale_gray(gray, w, h, ww, hh)

        seed = ai_client.random_seed() if int(seed) < 0 else int(seed)
        blob, info = ai_client.inpaint(
            client,
            ai_client.rgba_png(ww, hh, src_work),
            ai_client.mask_png(ww, hh, gray_work),
            prompt.strip(), negative=negative or "", checkpoint=checkpoint,
            steps=int(steps), cfg=float(cfg), seed=seed,
            denoise=float(denoise), grow_mask_by=int(grow_mask_by),
            timeout=float(timeout), on_tick=on_tick or Gimp.progress_pulse)

        # 6) 落盘 → 当图层读回来（GIMP 自己解 PNG，比手写解码靠谱）
        #    贴的是**工作画布**的位置：补边那圈像素会被下面的选区蒙版整圈挡掉
        with open(png_path, "wb") as fh:
            fh.write(blob)
        result = paste_result(image, drawable, png_path, (cx, cy, cw, ch),
                              mask_channel)
        info["rect"] = (cx, cy, cw, ch)
        info["source_rect"] = rect
        info["pads"] = (pl, pt, pr, pb)
        info["seed"] = seed
        info["checkpoint"] = checkpoint
        info["work_size"] = (ww, hh)
        info["scale"] = factor

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
# 两个入口，同一个实现：
#   AI Inpaint…            只问「画什么」——提示词 + 常见主体下拉。大多数时候
#                          只该看到这两个框，而不是十几个采样参数。
#   AI Inpaint (Advanced)… 老入口，steps/cfg/seed/grow/feather 全在。
# 为什么要拆：GIMP 的参数对话框是一次性铺开所有参数的，没法折叠。参数一多，
# 真正的那个输入框就被埋掉了——用户会以为「只能重绘，不能指定画什么」。

PROC_QUICK = 'lb-plugin-ai-inpaint'
PROC_ADVANCED = 'lb-plugin-ai-inpaint-advanced'


def _add_preset_argument(procedure):
    """主体下拉。Gimp.Choice 造不出来（老版本绑定）就退回字符串参数。"""
    if prompt_tools is None:
        return
    try:
        choice = Gimp.Choice.new()
        for idx, (pid, label, _prompt) in enumerate(prompt_tools.PRESETS):
            # gimp_choice_add(choice, nick, id, label, help)：id 是整数、nick
            # 才是配置里存的那个字符串。参数给错只会在运行时抛 TypeError，
            # 静默退化成文本框——界面上看不出区别，只是下拉没了。
            choice.add(pid, idx, _(label), "")   # help 不能给 None，会 TypeError
        procedure.add_choice_argument(
            "preset", _("What to paint"),
            _("Pick a subject and the prompt starts from it — the prompt box "
              "then only needs the details (colour, pose, surroundings)"),
            choice, "none", GObject.ParamFlags.READWRITE)
    except Exception:
        procedure.add_string_argument(
            "preset", _("What to paint (none / cat / dog / person / flower / "
                        "tree / coffee / food / car)"),
            _("Leave empty for none"), "none", GObject.ParamFlags.READWRITE)


class AiInpaintPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC_QUICK, PROC_ADVANCED]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.add_string_argument(
            "prompt", _("Prompt — what the selection should become"),
            _("Describe the RESULT. Chinese is fine for common words (the "
              "plug-in translates them); SD itself only reads English. To "
              "remove a bottle, write \"empty wooden table, wood grain\" "
              "rather than \"remove the bottle\". Keep the selection tight "
              "around the thing you are painting — the model scales what it "
              "draws to fill the mask."),
            DEFAULT_PROMPT, GObject.ParamFlags.READWRITE)
        _add_preset_argument(procedure)
        procedure.add_string_argument(
            "negative", _("Negative prompt"),
            _("What must not appear — put the thing you are deleting here"),
            DEFAULT_NEGATIVE, GObject.ParamFlags.READWRITE)

        if name == PROC_ADVANCED:
            self._add_advanced_arguments(procedure)
            procedure.set_menu_label(_("AI Inpaint (Advanced)…"))
            procedure.set_documentation(
                _("AI Inpaint (Advanced): every sampling and blending knob"),
                _("Selection + prompt -> ComfyUI inpaint -> new layer with a "
                  "feathered selection mask. Exposes steps/CFG/seed/denoise/"
                  "mask grow/feather/working scale."),
                name)
        else:
            procedure.set_menu_label(_("AI Inpaint…"))
            procedure.set_documentation(
                _("AI Inpaint: frame the area, say what should be there, done"),
                _("Selection + prompt -> ComfyUI inpaint -> new layer. Only "
                  "asks what to paint; the sampling settings use good "
                  "defaults. Use \"AI Inpaint (Advanced)\" to change them."),
                name)
        # add_menu_path 必须在 set_menu_label 之后：GIMP 会把「先挂菜单、后设
        # 标签」的路径直接丢掉（pluginrc 里 menu-path 数会写成 0），菜单里
        # 就整个没有这一项。065b70d 拆简版/高级版时把顺序调换过，AI 菜单
        # 因此消失了一整轮。
        procedure.add_menu_path("<Image>/SuperMrWang/AI")
        return procedure

    def _add_advanced_arguments(self, procedure):
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
        procedure.add_double_argument(
            "scale", _("Working scale"),
            _("0 = fit the model's native size (SD1.5 512, SDXL 1024); "
              "1.0 = send the crop unchanged"),
            0.0, 4.0, 0.0, GObject.ParamFlags.READWRITE)

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        if not _dialog.run_dialog(procedure, run_mode, config):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, None)
        adv = procedure.get_name() == PROC_ADVANCED

        def prop(key, fallback):
            # 简版没有这些参数，get_property 会返回 NULL，直接喂给 ai_inpaint
            # 会 TypeError，所以统一在门口兜一次默认值
            if not adv:
                return fallback
            value = config.get_property(key)
            return fallback if value is None else value

        try:
            ai_inpaint(image, drawables[0],
                       config.get_property('prompt') or "",
                       config.get_property('negative') or "",
                       prop('server', ""),
                       prop('checkpoint', ""),
                       prop('steps', 25),
                       prop('cfg', 7.5),
                       prop('seed', -1),
                       prop('denoise', 1.0),
                       prop('grow', 8),
                       prop('grow-mask-by', 8),
                       prop('feather', 4.0),
                       prop('timeout', 600),
                       prop('keep-mask', True),
                       prop('scale', 0.0),
                       preset=config.get_property('preset') or "none")
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("ai-inpaint: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(AiInpaintPlugin.__gtype__, sys.argv)
