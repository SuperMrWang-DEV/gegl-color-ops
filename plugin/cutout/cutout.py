#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 抠图 / 移除背景（AI + 本地两条路）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把主体从背景里抠出来：给图层加一张羽化过的蒙版，主体之外透明；
           也可以顺手铺一层纯色（白底证件照、电商主图）或一张新背景图。
           两条路，按素材挑：
             · **AI 抠图**（menu 第二项）：本机 ComfyUI + ComfyUI-RMBG 的
               BiRefNet（RMBG-2.0），发丝、毛绒、玻璃这类「没有明确边界」的
               主体只有它靠谱；代价是要起 ComfyUI，单张 3~6 秒。
             · **本地抠图**（menu 第一项）：从四条边泛洪选背景，纯色、渐变、
               影棚背景一般都能整块吃掉，毫秒级；复杂背景就别指望它。
           Two routes: RMBG via a local ComfyUI, or flood-fill from the border.

 menu      SuperMrWang → Mask → 抠图 / 移除背景（本地）
           SuperMrWang → Mask → 抠图 / 移除背景（AI）

 usage     选中要抠的图层 → 选菜单项 → 调参数 → 确定。
           本地版：已有选区时**直接把选区当主体**（适合先粗略框选再收边）；
           没有选区才从四边泛洪找背景。
           AI 版：自动探活 ComfyUI，没在跑就按「AI 环境」里配的目录拉起来。

 note      四个坑（都已在代码里绕开）：
           1. **蒙版要走「临时图层 + alpha」再 select-item**。GIMP 的选区
              只能从 item 的 alpha 或通道灰度来；把 AI 的小尺寸 alpha 直接
              在 Python 里插值到 4000×6000 要十几秒，而建一个同尺寸临时图层
              让 GIMP 自己缩（gimp-layer-scale，C 实现）是毫秒级。
           2. **AI 传的是缩略图，不是原图**。RMBG 内部会按 process_res 缩放，
              24MP 原图上传只是白占内存和带宽；缩略图长边 1024 已经比它的
              工作分辨率大。
           3. **本地泛洪要检查覆盖率**。泛洪一个点都没选中时 GIMP 不报错，
              选区是空的，于是「反选」会得到整张图——看起来像是把主体抠成了
              全白。所以先看边框采样点的命中率，低于 35% 直接报错让人调阈值。
           4. **背景层要插在照片下面（pos + 1）**。insert_layer 的 position 是
              从顶部数的；插到 pos 会跑到照片上面，把照片整块盖住。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os as _os
import sys as _sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject, Gegl

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
import cutout_math as CM

try:
    import ai_client
except Exception:                  # 没带 _shared/ai_client.py 的裸装情况
    ai_client = None

try:
    import comfy_launcher            # 连不上时自动拉起 ComfyUI
except Exception:
    comfy_launcher = None


PROC_LOCAL = 'lb-plugin-cutout-local'
PROC_AI = 'lb-plugin-cutout-ai'

MASK_CHANNEL = "Cutout Mask"
BACKGROUND_LAYER = "Background"

# 本地泛洪的采样阈值（GIMP context 里的 0..1）默认值。0.12 在影棚白底和
# 浅灰渐变上都够用；再大就会从主体边缘漏进去（比如白衬衫和白墙分不开）。
LOCAL_THRESHOLD = 0.12
# 每条边撒几个种子点。5 个是折中：再多对纯色背景没意义，再少补不上渐变。
SEEDS_PER_EDGE = 5
# 边缘收缩默认 1px：RMBG 的 alpha 边界一般比真实边缘外扩半像素，收一圈正好
# 把背景色残留压掉；0 会留下明显的白边（尤其深色背景抠到白底上）。
DEFAULT_SHRINK = 1
DEFAULT_FEATHER = 1.5
# 上传给 RMBG 的长边上限。它的 process_res 最大 2048，给 2048 已经超过模型
# 的实际工作分辨率（1024），再大只是让上传变慢。
MAX_UPLOAD_EDGE = 2048


# ---- PDB 小工具 -------------------------------------------------------------

def _pdb(name, **props):
    """按名调用 PDB 过程 / call a PDB procedure by name"""
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def _has_selection(image):
    sel = image.get_selection()
    if sel is None:
        return False
    ok, non_empty, x1, y1, x2, y2 = sel.bounds(image)
    return bool(non_empty) and x2 > x1 and y2 > y1


def _read_thumb(drawable, long_edge):
    """把图层缩到长边 ≤ long_edge，读回 RGBA 8 位。返回 (w, h, bytes)。

    走 GIMP 自己的重采样（临时图层 + gimp-layer-scale），不在 Python 里插值：
    4000×6000 的图在 Python 里做双线性要几十秒，这里只是一次 C 调用。
    """
    w, h = drawable.get_width(), drawable.get_height()
    long_edge = max(64, int(long_edge))
    scale = min(1.0, float(long_edge) / max(w, h, 1))
    tw = max(1, int(round(w * scale)))
    th = max(1, int(round(h * scale)))
    if (tw, th) == (w, h):
        rect = Gegl.Rectangle.new(0, 0, w, h)
        raw = drawable.get_buffer().get(rect, 1.0, "R'G'B'A u8",
                                        Gegl.AbyssPolicy.NONE)
        return w, h, bytes(bytearray(raw))

    image = drawable.get_image()
    tmp = drawable.copy()
    tmp.set_name("lb-cutout-thumb")
    image.insert_layer(tmp, None, image.get_item_position(drawable))
    try:
        _pdb('gimp-layer-scale', layer=tmp, new_width=tw, new_height=th,
             local_origin=False)
        rect = Gegl.Rectangle.new(0, 0, tw, th)
        raw = tmp.get_buffer().get(rect, 1.0, "R'G'B'A u8",
                                   Gegl.AbyssPolicy.NONE)
        data = bytes(bytearray(raw))
    finally:
        image.remove_layer(tmp)
    if len(data) != tw * th * 4:
        raise RuntimeError(_("Failed to read the layer: expected %d bytes, "
                             "got %d") % (tw * th * 4, len(data)))
    return tw, th, data


# ---- 蒙版 → 选区 ------------------------------------------------------------

def _selection_from_mask(image, mw, mh, mask, shrink, feather):
    """把小尺寸灰度蒙版（255=主体）变成画布上的羽化选区。

    做法：建一个 mw×mh 的 RGBA 临时图层，RGB=白、A=蒙版，插进图像后
    gimp-layer-scale 到画布尺寸，再 select-item 取它的 alpha。缩放交给 GIMP，
    Python 侧只搬一次 mw×mh×4 字节。
    """
    canvas_w, canvas_h = image.get_width(), image.get_height()
    mw, mh = max(1, int(mw)), max(1, int(mh))
    if len(mask) != mw * mh:
        raise RuntimeError(_("Mask size mismatch: %d values for %d×%d")
                           % (len(mask), mw, mh))

    tmp = Gimp.Layer.new(image, "lb-cutout-mask", mw, mh,
                         Gimp.ImageType.RGBA_IMAGE, 100.0,
                         Gimp.LayerMode.NORMAL)
    image.insert_layer(tmp, None, 0)
    try:
        n = mw * mh
        data = bytearray(n * 4)
        data[0::4] = b"\xff" * n
        data[1::4] = b"\xff" * n
        data[2::4] = b"\xff" * n
        data[3::4] = bytes(mask)
        buf = tmp.get_buffer()
        buf.set(Gegl.Rectangle.new(0, 0, mw, mh), "R'G'B'A u8", bytes(data))
        buf.flush()
        if (mw, mh) != (canvas_w, canvas_h):
            _pdb('gimp-layer-scale', layer=tmp, new_width=canvas_w,
                 new_height=canvas_h, local_origin=False)
        _pdb('gimp-image-select-item', image=image,
             operation=int(Gimp.ChannelOps.REPLACE), item=tmp)
    finally:
        image.remove_layer(tmp)

    if int(shrink) > 0:
        _pdb('gimp-selection-shrink', image=image, steps=int(shrink))
    if float(feather) > 0:
        _pdb('gimp-selection-feather', image=image, radius=float(feather))


# ---- 本地：从四边泛洪 -------------------------------------------------------

def local_background_selection(image, drawable, threshold=LOCAL_THRESHOLD,
                               per_edge=SEEDS_PER_EDGE):
    """泛洪选中背景，然后反选成主体。返回 (主体占比, 背景覆盖率)。

    注意：**这会就地改选区**。调用方负责之前的「已有选区」判断。
    """
    canvas_w, canvas_h = image.get_width(), image.get_height()
    lw, lh = drawable.get_width(), drawable.get_height()
    ok, ox, oy = drawable.get_offsets()
    if not ok:
        ox = oy = 0
    seeds = CM.offset_seeds(CM.edge_seeds(canvas_w, canvas_h, per_edge),
                            ox, oy, lw, lh)
    if not seeds:
        raise RuntimeError(_("The layer is empty — nothing to cut out"))

    Gimp.context_push()
    Gimp.context_set_sample_threshold(float(threshold))
    Gimp.context_set_sample_merged(False)
    Gimp.context_set_antialias(True)
    Gimp.context_set_sample_criterion(Gimp.SelectCriterion.COMPOSITE)
    Gimp.context_set_sample_transparent(False)
    try:
        for i, (x, y) in enumerate(seeds):
            _pdb('gimp-image-select-contiguous-color', image=image,
                 operation=int(Gimp.ChannelOps.REPLACE if i == 0
                               else Gimp.ChannelOps.ADD),
                 drawable=drawable, x=int(x), y=int(y))
    finally:
        Gimp.context_pop()

    if not _has_selection(image):
        raise RuntimeError(
            _("The flood fill selected nothing. Raise the threshold, or use "
              "the AI route for busy backgrounds."))

    # 覆盖率：边框上再取一圈点（和种子错开一点），看有多少真的落在背景选区里。
    # 不查这一条的话，「只选中主体的一小块」也会被当成成功，反选后主体就
    # 只剩一个洞。
    probe = CM.edge_seeds(canvas_w, canvas_h, max(3, per_edge * 2), inset=1)
    sel = image.get_selection()
    values = [sel.value(image, x, y) for (x, y) in probe]
    cover = CM.coverage(values)
    if cover < 0.35:
        _pdb('gimp-selection-none', image=image)
        raise RuntimeError(
            _("Only %.0f%% of the border matched the background — the "
              "background is probably not plain enough. Raise the threshold, "
              "or use the AI route (RMBG) instead.")
            % (100.0 * cover))

    # 背景 → 反选 → 主体
    _pdb('gimp-selection-invert', image=image)
    if not _has_selection(image):
        _pdb('gimp-selection-none', image=image)
        raise RuntimeError(
            _("The flood fill covered the whole image, so nothing is left as "
              "the subject. Lower the threshold, or use the AI route (RMBG) "
              "for photos where the background is not plain."))
    return cover


# ---- 输出：蒙版 + 背景 ------------------------------------------------------

def _apply_output(image, drawable, background, color, bgfile, keep_mask):
    """把当前选区（= 主体）落成图层蒙版，并按需要垫背景。返回 (mask, channel, bg)。"""
    channel = None
    if keep_mask:
        channel = _pdb('gimp-selection-save', image=image).index(1)
        channel.set_name(MASK_CHANNEL)

    mask = drawable.create_mask(Gimp.AddMaskType.SELECTION)
    drawable.add_mask(mask)
    _pdb('gimp-selection-none', image=image)

    bg = None
    pos = image.get_item_position(drawable)
    if background == "color":
        canvas_w, canvas_h = image.get_width(), image.get_height()
        bg = Gimp.Layer.new(image, BACKGROUND_LAYER, canvas_w, canvas_h,
                            Gimp.ImageType.RGB_IMAGE, 100.0,
                            Gimp.LayerMode.NORMAL)
        # pos + 1：插在照片**下面**（position 从顶上数）
        image.insert_layer(bg, None, pos + 1)
        Gimp.context_push()
        try:
            Gimp.context_set_foreground(color or Gegl.Color.new("#ffffff"))
            _pdb('gimp-drawable-edit-fill', drawable=bg,
                 fill_type=int(Gimp.FillType.FOREGROUND))
        finally:
            Gimp.context_pop()
    elif background == "image" and bgfile is not None and bgfile.query_exists():
        canvas_w, canvas_h = image.get_width(), image.get_height()
        bg = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, bgfile)
        if bg is None:
            raise RuntimeError(_("Could not load the background image"))
        bg.set_name(BACKGROUND_LAYER)
        image.insert_layer(bg, None, pos + 1)
        lw, lh = bg.get_width(), bg.get_height()
        nw, nh, ox, oy = CM.fit_cover(lw, lh, canvas_w, canvas_h)
        if (nw, nh) != (lw, lh):
            _pdb('gimp-layer-scale', layer=bg, new_width=nw, new_height=nh,
                 local_origin=False)
        bg.set_offsets(ox, oy)
    return mask, channel, bg


# ---- 两条主流程 -------------------------------------------------------------

def _ensure_comfy(server=""):
    """AI 操作前的一次性保险：没在跑就按配置的目录拉起来。"""
    if comfy_launcher is None:
        return None
    res = comfy_launcher.ensure_running(server)
    if not res.get("ok"):
        lines = [_("ComfyUI is not running and could not be started: %s")
                 % (res.get("error") or "?")]
        log = (res.get("log") or "").strip()
        if log:
            lines.append(_("Last lines of the log:"))
            lines += ["    " + r for r in log.splitlines()[-10:]]
        lines.append(_("Or use the local route: SuperMrWang → Mask → "
                       "Cut Out (Local) — it needs no ComfyUI."))
        raise RuntimeError("\n".join(lines))
    return res


def cutout_ai(image, drawable, server="", model="", resolution=1024,
              sensitivity=1.0, refine=True, shrink=DEFAULT_SHRINK,
              feather=DEFAULT_FEATHER, background="transparent", color=None,
              bgfile=None, keep_mask=True, timeout=600.0, client=None,
              on_tick=None):
    """AI 抠图：缩略图 → RMBG → alpha 蒙版 → 图层蒙版 (+ 背景)。

    返回 (drawable, info)。info 里有模型、耗时、前景占比——回归和提示文案都用。
    """
    if ai_client is None:
        raise RuntimeError(_("plugin/_shared/ai_client.py is missing: install "
                             "the _shared folder next to the plug-in"))
    if client is None:
        _ensure_comfy(server)

    tw, th, rgba = _read_thumb(drawable, MAX_UPLOAD_EDGE)
    png = ai_client.rgba_png(tw, th, rgba)

    own_client = client is None
    if own_client:
        client = ai_client.ComfyClient(server, timeout=min(timeout, 60.0))
    blob, cinfo = ai_client.cutout(
        client, png, model=model, sensitivity=sensitivity,
        process_res=int(resolution), refine_foreground=bool(refine),
        timeout=timeout, on_tick=on_tick)

    dw, dh, dch, dpx = ai_client.decode_png(blob)
    if dch != 4:
        raise RuntimeError(_("RMBG returned an image without alpha — the "
                             "ComfyUI-RMBG node may be an incompatible build"))
    mask = CM.alpha_to_mask(bytes(dpx[3::4]))
    ratio, lo, hi = CM.mask_stats(mask)
    if ratio < 0.005:
        raise RuntimeError(_("RMBG found no subject (%.1f%% of the pixels kept). "
                             "Try another model or the local route.")
                           % (100.0 * ratio))
    if ratio > 0.995:
        raise RuntimeError(_("RMBG kept the whole image — probably no clear "
                             "subject. Try another model or the local route."))

    background = CM.normalize_background(background, have_color=bool(color),
                                         have_image=bgfile is not None)
    image.undo_group_start()
    try:
        _selection_from_mask(image, dw, dh, mask, shrink, feather)
        _mask, channel, bg = _apply_output(image, drawable, background,
                                           color, bgfile, keep_mask)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return drawable, {"model": cinfo.get("model", model),
                      "seconds": cinfo.get("seconds"),
                      "foreground": ratio, "mask_min": lo, "mask_max": hi,
                      "mask_size": (dw, dh), "thumb": (tw, th),
                      "background": background,
                      "channel": channel.get_name() if channel else "",
                      "background_layer": bg.get_name() if bg else ""}


def cutout_local(image, drawable, threshold=LOCAL_THRESHOLD,
                 per_edge=SEEDS_PER_EDGE, shrink=DEFAULT_SHRINK,
                 feather=DEFAULT_FEATHER, background="transparent", color=None,
                 bgfile=None, keep_mask=True, use_selection=True):
    """本地抠图：有选区就拿选区当主体，没有就从四边泛洪选背景再反选。"""
    if drawable.get_width() <= 0 or drawable.get_height() <= 0:
        raise RuntimeError(_("The layer is empty — nothing to cut out"))
    if drawable.is_group():
        raise RuntimeError(_("A layer group has no pixels of its own; pick a "
                             "raster layer (right-click the group, then Merge "
                             "Group)."))

    background = CM.normalize_background(background, have_color=bool(color),
                                         have_image=bgfile is not None)
    used_selection = bool(use_selection) and _has_selection(image)
    cover = None

    image.undo_group_start()
    try:
        if used_selection:
            # 用户已经框好了主体：只做边缘收尾，不去碰泛洪
            if int(shrink) > 0:
                _pdb('gimp-selection-shrink', image=image, steps=int(shrink))
            if float(feather) > 0:
                _pdb('gimp-selection-feather', image=image,
                     radius=float(feather))
        else:
            cover = local_background_selection(image, drawable, threshold,
                                               per_edge)
            if int(shrink) > 0:
                _pdb('gimp-selection-shrink', image=image, steps=int(shrink))
            if float(feather) > 0:
                _pdb('gimp-selection-feather', image=image,
                     radius=float(feather))
        _mask, channel, bg = _apply_output(image, drawable, background,
                                           color, bgfile, keep_mask)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return drawable, {"used_selection": used_selection,
                      "border_coverage": cover,
                      "background": background,
                      "channel": channel.get_name() if channel else "",
                      "background_layer": bg.get_name() if bg else ""}


# ---- 程序注册 ---------------------------------------------------------------

def _add_model_argument(procedure):
    """抠图模型下拉：连得上 ComfyUI 就把可选模型列出来，连不上退回文本框。"""
    names = []
    if ai_client is not None:
        try:
            names = ai_client.cutout_models(ai_client.ComfyClient(timeout=1.5))
        except Exception:
            names = []
    help_text = _("RMBG-2.0 (BiRefNet) gives the cleanest hair and fur; "
                  "INSPYRENET is faster, BEN/BEN2 are lighter models. "
                  "Needs the ComfyUI-RMBG custom node pack.")
    if names:
        try:
            choice = Gimp.Choice.new()
            for idx, name in enumerate(names):
                choice.add(name, idx, name, _("From this ComfyUI installation"))
            procedure.add_choice_argument(
                "model", _("Cut-out model"), help_text, choice, names[0],
                GObject.ParamFlags.READWRITE)
            return
        except Exception:
            pass
    procedure.add_string_argument(
        "model", _("Cut-out model (RMBG-2.0 / INSPYRENET / BEN / BEN2)"),
        help_text, "RMBG-2.0", GObject.ParamFlags.READWRITE)


def _add_background_arguments(procedure):
    """输出背景：透明 / 纯色 / 一张图。三个参数总是都在，选了哪个用哪个。"""
    choice = Gimp.Choice.new()
    choice.add("transparent", 0, _("Transparent"),
               _("Just add the mask; export as PNG to keep transparency"))
    choice.add("color", 1, _("Solid colour"),
               _("Put a flat colour layer under the cut-out"))
    choice.add("image", 2, _("Image"),
               _("Put a picture under the cut-out, scaled to cover the canvas"))
    procedure.add_choice_argument(
        "background", _("Output background"), _("What goes behind the subject"),
        choice, "transparent", GObject.ParamFlags.READWRITE)
    # 签名是 (name, nick, blurb, has_alpha, default, flags)：has_alpha 漏掉
    # 会直接 TypeError，而且只在 GIMP 真去建过程时炸（import 阶段看不出来）。
    procedure.add_color_argument(
        "color", _("Background colour"),
        _("Used when the output background is \"Solid colour\""),
        False, Gegl.Color.new("#ffffff"), GObject.ParamFlags.READWRITE)
    procedure.add_file_argument(
        "bg-file", _("Background image"),
        _("Used when the output background is \"Image\"; scaled to cover"),
        Gimp.FileChooserAction.OPEN, True, None,
        GObject.ParamFlags.READWRITE)


def _add_edge_arguments(procedure, shrink_default=DEFAULT_SHRINK):
    procedure.add_int_argument(
        "shrink", _("Shrink edge"),
        _("Pull the mask in by n pixels — removes the background-coloured "
          "fringe around the subject"), 0, 8, shrink_default,
        GObject.ParamFlags.READWRITE)
    procedure.add_double_argument(
        "feather", _("Feather"),
        _("Softens the mask edge; 0 keeps it hard"), 0.0, 30.0,
        DEFAULT_FEATHER, GObject.ParamFlags.READWRITE)
    procedure.add_boolean_argument(
        "keep-mask", _("Keep mask channel"),
        _("Store the mask as a \"Cutout Mask\" channel so a selection can be "
          "rebuilt later"), True, GObject.ParamFlags.READWRITE)


class CutoutPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC_LOCAL, PROC_AI]

    def do_create_procedure(self, name):
        is_ai = name == PROC_AI
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        if is_ai:
            procedure.set_menu_label(_("Cut Out (AI)"))
            procedure.set_documentation(
                _("Cut out the subject with RMBG (BiRefNet) on a local "
                  "ComfyUI, then mask the layer"),
                _("Sends a downscaled copy to ComfyUI-RMBG, turns the returned "
                  "alpha into a feathered layer mask, and can put a flat "
                  "colour or a picture underneath. Best for hair and fur."),
                name)
            _add_model_argument(procedure)
            procedure.add_int_argument(
                "resolution", _("AI working size"),
                _("Long edge sent to ComfyUI (and RMBG's process_res); "
                  "1024 is the model's native size"),
                512, 2048, 1024, GObject.ParamFlags.READWRITE)
            procedure.add_double_argument(
                "sensitivity", _("Sensitivity"),
                _("Higher keeps more of the subject's soft edges"),
                0.0, 1.0, 1.0, GObject.ParamFlags.READWRITE)
            procedure.add_boolean_argument(
                "refine", _("Clean edge colour"),
                _("RMBG's foreground colour estimation — removes the "
                  "background colour bleeding into the edge"), True,
                GObject.ParamFlags.READWRITE)
            _add_edge_arguments(procedure)
            _add_background_arguments(procedure)
            procedure.add_menu_path("<Image>/SuperMrWang/Mask")
        else:
            procedure.set_menu_label(_("Cut Out (Local)"))
            procedure.set_documentation(
                _("Cut out the subject by flood-filling the background from "
                  "the border (or use the current selection as the subject)"),
                _("Classic route, no ComfyUI. Plain, gradient or studio "
                  "backgrounds work well; use the AI route for busy scenes. "
                  "If a selection exists it is treated as the subject."),
                name)
            procedure.add_double_argument(
                "threshold", _("Background threshold"),
                _("Colour tolerance of the border flood fill (0..0.5); raise "
                  "it for noisy backgrounds, lower it if the subject is "
                  "being eaten"), 0.0, 0.5, LOCAL_THRESHOLD,
                GObject.ParamFlags.READWRITE)
            procedure.add_int_argument(
                "seeds", _("Seed points per edge"),
                _("How many points per border are used to start the flood "
                  "fill; more helps with gradient backgrounds"),
                1, 20, SEEDS_PER_EDGE, GObject.ParamFlags.READWRITE)
            procedure.add_boolean_argument(
                "use-selection", _("Use existing selection as the subject"),
                _("When a selection exists, treat it as the subject and only "
                  "refine its edge (no flood fill)"), True,
                GObject.ParamFlags.READWRITE)
            _add_edge_arguments(procedure)
            _add_background_arguments(procedure)
            procedure.add_menu_path("<Image>/SuperMrWang/Mask")

        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        if not _dialog.run_dialog(procedure, run_mode, config):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, None)

        drawable = drawables[0]
        try:
            if procedure.get_name() == PROC_AI:
                layer, info = cutout_ai(
                    image, drawable,
                    model=config.get_property('model') or "",
                    resolution=config.get_property('resolution'),
                    sensitivity=config.get_property('sensitivity'),
                    refine=config.get_property('refine'),
                    shrink=config.get_property('shrink'),
                    feather=config.get_property('feather'),
                    background=config.get_property('background'),
                    color=config.get_property('color'),
                    bgfile=config.get_property('bg-file'),
                    keep_mask=config.get_property('keep-mask'),
                    on_tick=Gimp.progress_pulse)
                msg = _("Cut out with %s in %.1f s — subject kept %.0f%%.") % (
                    info.get("model", "RMBG"),
                    info.get("seconds") or 0.0,
                    100.0 * float(info.get("foreground") or 0.0))
            else:
                layer, info = cutout_local(
                    image, drawable,
                    threshold=config.get_property('threshold'),
                    per_edge=config.get_property('seeds'),
                    shrink=config.get_property('shrink'),
                    feather=config.get_property('feather'),
                    background=config.get_property('background'),
                    color=config.get_property('color'),
                    bgfile=config.get_property('bg-file'),
                    keep_mask=config.get_property('keep-mask'),
                    use_selection=config.get_property('use-selection'))
                msg = _("Cut out locally.")
            if info.get("background") == "transparent":
                msg += " " + _("Export as PNG to keep the transparency.")
            elif info.get("background") == "color":
                msg += " " + _("A solid colour layer was added underneath.")
            elif info.get("background") == "image":
                msg += " " + _("The background image was added underneath.")
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("cutout: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(CutoutPlugin.__gtype__, _sys.argv)
