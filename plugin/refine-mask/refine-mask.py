#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 选择并遮住（精修蒙版边缘）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把一张「差不多」的蒙版修成能用的蒙版：边缘吸附、平滑、羽化、
           对比度、移动边缘、去色边。典型来源是 AI 抠图（RMBG）回来的 alpha、
           魔棒/快速选择出来的粗选区、或者画好的通道。
           PS 的「选择并遮住」里有的，这里**大部分有**，缺的是那支画笔：
           GIMP 插件没法在画布上做交互笔刷，所以「局部加减」交给通道——
           输出到通道之后，用画笔在通道上涂黑白，再「载入通道为选区」。

 menu      SuperMrWang → Mask → 选择并遮住（精修边缘）…

 usage     先做选区（或跑一次抠图留下 Cutout Mask 通道）→ 选菜单项 →
           左边看图、右边拖滑杆 → 确定。

 note      三条非踩不可的：
           1. **通道读出来是线性的**。gimp-selection-save 的通道用 "Y u8"
              读到的是线性亮度，而选区值/图层 alpha 是 sRGB 编码过的
              （实测：通道写 128，选区读回 188）。不做这次转换，精修后
              中间调整体下压，50% 等值线会跟着漂。转换只在读通道那一步做，
              写回走「临时图层 alpha」（直通 0..255），方向不会搞反。
           2. **预览和应用必须是同一套代码**。这里两边都调 refine_math 的
              同一个 refine_mask；区别只是分辨率不同（预览 520 长边、
              精修 1600 长边、都缩放回画布）。两套实现一定会漂。
           3. **吸附要把位移沿法线传播到 ±radius**。只改半透明带不够：
              剖面移过去要落在原来「实心 255」的地方，否则边界塌成硬跳变。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os as _os
import sys as _sys
import time

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

import lb_dialog as _dialog            # noqa: E402
import refine_math as RM               # noqa: E402
import mask_io as MI                  # noqa: E402

PROC = 'lb-plugin-refine-mask'
CHANNEL_NAME = "Refined Mask"
PREVIEW_EDGE = 520
STRIP_ROWS = 512

OUTPUT_SELECTION = "selection"
OUTPUT_MASK = "mask"
OUTPUT_LAYER = "layer"
OUTPUT_CHANNEL = "channel"


# ---- 背景色估计 / background estimate -------------------------------------

def background_grid(rgba, mask, w, h, cells=24, step=2):
    """把「背景色」估成一张 24×24 的粗网格。

    只统计蒙版接近 0 的像素。整张图取一个常数在渐变背景上会翻车（上面留白、
    下面带暖色），所以按格子取；空格子用全图均值补，再做一次 3×3 平滑。
    坐标是**工作尺寸**的，用的时候按比例换算。
    """
    gw = gh = cells
    sum_r = [0] * (gw * gh)
    sum_g = [0] * (gw * gh)
    sum_b = [0] * (gw * gh)
    cnt = [0] * (gw * gh)
    all_r = all_g = all_b = all_n = 0
    for y in range(0, h, step):
        base = y * w
        cy = min(gh - 1, y * gh // max(h, 1))
        for x in range(0, w, step):
            i = base + x
            if mask[i] >= 40:
                continue
            j = i * 4
            r, g, b = rgba[j], rgba[j + 1], rgba[j + 2]
            c = cy * gw + min(gw - 1, x * gw // max(w, 1))
            sum_r[c] += r
            sum_g[c] += g
            sum_b[c] += b
            cnt[c] += 1
            all_r += r
            all_g += g
            all_b += b
            all_n += 1

    if all_n:
        mean = (all_r / all_n, all_g / all_n, all_b / all_n)
    else:                                   # 整张图都是主体：没有背景可估
        mean = (128.0, 128.0, 128.0)
    grid = []
    for c in range(gw * gh):
        n = cnt[c]
        grid.append(((sum_r[c] / n, sum_g[c] / n, sum_b[c] / n)
                     if n else mean))
    # 3×3 平滑：空格子会被邻近格子带过来，避免整块跳色
    smoothed = []
    for cy in range(gh):
        for cx in range(gw):
            acc = [0.0, 0.0, 0.0]
            got = 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = cy + dy, cx + dx
                    if 0 <= yy < gh and 0 <= xx < gw:
                        src = grid[yy * gw + xx]
                        acc[0] += src[0]
                        acc[1] += src[1]
                        acc[2] += src[2]
                        got += 1
            smoothed.append((acc[0] / got, acc[1] / got, acc[2] / got))
    return gw, gh, smoothed, mean


def grid_color(grid, gw, gh, x, y, w, h):
    c = min(gh - 1, y * gh // max(h, 1)) * gw + min(gw - 1, x * gw // max(w, 1))
    return grid[c]


# ---- 去色边（在图层像素上，按条带处理） ------------------------------------

def decontaminate_layer(layer, grid, gw, gh, mw, mh, strength=0.5,
                        band=(8, 250), reach=6):
    """把边缘半透明像素的颜色往「里面那层实心前景色」上拉。

    为什么不是教科书里的 C = a·F + (1-a)·B 反解：反解会把**本来就干净**的
    半透明像素也拧一下（实测：纯红 220,40,40 在 alpha=0.5 处会被反解成
    203,0,0，边缘发暗）。PS 的做法是「用附近的实心前景色去替换边缘色」，
    这里照做：沿 alpha 梯度往里走最多 reach 像素，找到第一个 alpha≥250 的
    像素，就把它当 F；走不到才退回反解公式（用背景网格估的 B）。

    性能：bytes.translate + find 先挑出半透明像素（C 扫一遍），只有这些位置
    进 Python 循环；按 512 行一条带读写，不把整张 24 MP 的 RGBA 搬进内存。
    """
    s = max(0.0, min(1.0, float(strength)))
    if s <= 0.0:
        return 0
    w, h = layer.get_width(), layer.get_height()
    buf = layer.get_buffer()
    lo, hi = band
    flag_tbl = bytes(bytearray(1 if lo < v < hi else 0 for v in range(256)))
    total = 0
    for y0 in range(0, h, STRIP_ROWS):
        rows = min(STRIP_ROWS, h - y0)
        rect = Gegl.Rectangle.new(0, y0, w, rows)
        data = bytearray(buf.get(rect, 1.0, "R'G'B'A u8",
                                 Gegl.AbyssPolicy.NONE))
        alpha = bytes(data[3::4])
        flags = alpha.translate(flag_tbl)
        if b"\x01" not in flags:
            continue
        pos = flags.find(b"\x01")
        changed = 0
        while pos != -1:
            a = data[pos * 4 + 3]
            alpha_f = a / 255.0
            x = pos % w
            row = pos // w
            ly = y0 + row
            j = pos * 4

            # alpha 梯度 = 指向「更实心」的方向
            left = alpha[pos - 1] if x > 0 else a
            right = alpha[pos + 1] if x < w - 1 else a
            up = alpha[pos - w] if row > 0 else a
            down = alpha[pos + w] if row < rows - 1 else a
            gx = int(right) - int(left)
            gy = int(down) - int(up)
            fg = None
            if gx or gy:
                norm = (gx * gx + gy * gy) ** 0.5
                nx, ny = gx / norm, gy / norm
                for k in range(1, reach + 1):
                    sx = int(round(x + k * nx))
                    sy = row + int(round(k * ny))
                    if sx < 0 or sy < 0 or sx >= w or sy >= rows:
                        break
                    si = sy * w + sx
                    if alpha[si] >= 250:
                        fg = (data[si * 4], data[si * 4 + 1],
                              data[si * 4 + 2])
                        break
            if fg is None:
                br, bg, bb = grid_color(grid, gw, gh,
                                        x * mw // max(w, 1),
                                        ly * mh // max(h, 1), mw, mh)
                inv = 1.0 / alpha_f
                fg = []
                for c, bgv in ((0, br), (1, bg), (2, bb)):
                    val = (data[j + c] - (1.0 - alpha_f) * bgv) * inv
                    fg.append(0.0 if val < 0.0 else (255.0 if val > 255.0
                                                     else val))
            for c in range(3):
                cur = data[j + c]
                data[j + c] = RM.clamp_byte(round(cur + (fg[c] - cur) * s))
            changed += 1
            pos = flags.find(b"\x01", pos + 1)
        if changed:
            buf.set(rect, "R'G'B'A u8", bytes(data))
            buf.flush()
            total += changed
    return total


# ---- 主流程 / pipeline -----------------------------------------------------

def _work_scale(canvas_w, work_w):
    return float(work_w) / max(canvas_w, 1)


def refine_selection(image, drawable, radius=0, smart=True, smooth=1.0,
                     feather=1.0, contrast=10.0, shift=0.0,
                     decontaminate=0.0, output=OUTPUT_MASK, work_size=0,
                     on_tick=None):
    """读蒙版 → 精修 → 按 output 落地。返回 info 字典。"""
    t0 = time.time()
    canvas_w, canvas_h = image.get_width(), image.get_height()
    work = int(work_size or 0)
    if work <= 0 or work > max(canvas_w, canvas_h):
        work = 0                              # 0 = 原分辨率
    w, h, mask, source = MI.current_mask(image, work)
    k = _work_scale(canvas_w, w)              # 画布像素 → 工作像素

    def tick(*_a):
        if on_tick:
            on_tick()

    if on_tick:
        Gimp.progress_set_text(_("Refining the mask…"))
    # 精确按 (w, h) 读：图层可能比画布小（或者有偏移），那时按长边缩会得到
    # 另一个宽高比，后面和蒙版对不上，直接崩在索引上。
    # 注意别用「_」接返回值：模块级的 _ 是翻译函数，接一次就变成 int
    _dw, _dh, rgba = MI.read_drawable_rgba(drawable, max(w, h),
                                          exact=(w, h))
    if len(rgba) != w * h * 4:
        raise RuntimeError(_("Layer and mask do not match: %d bytes for %d×%d")
                           % (len(rgba), w, h))
    gray = RM.luma(rgba, w, h) if radius > 0 else None
    tick()

    before = RM.mask_stats(mask)
    refined = RM.refine_mask(
        mask, w, h, gray=gray,
        radius=radius * k if radius > 0 else 0,
        smart=smart,
        smooth=smooth * k,
        feather=feather * k,
        contrast=contrast, shift=shift)
    after = RM.mask_stats(refined)
    tick()

    info = {"source": source, "work": (w, h), "canvas": (canvas_w, canvas_h),
            "before": before, "after": after, "output": output,
            "decontaminated": 0, "layer": None,
            "seconds": 0.0}
    if (w, h) != (canvas_w, canvas_h):
        w2, h2, refined_canvas = MI.scale_mask(refined, w, h,
                                               canvas_w, canvas_h)
        if (w2, h2) != (canvas_w, canvas_h):
            raise RuntimeError(_("Could not scale the mask back to the canvas"))
    else:
        refined_canvas = refined

    if output == OUTPUT_SELECTION or output == OUTPUT_CHANNEL:
        MI.selection_from_mask(image, refined_canvas, canvas_w, canvas_h)
        if output == OUTPUT_CHANNEL:
            ch = MI._pdb('gimp-selection-save', image=image).index(1)
            ch.set_name(CHANNEL_NAME)
    elif output == OUTPUT_MASK:
        if drawable.is_group():
            raise RuntimeError(_("A layer group cannot take a mask. Pick a "
                                 "raster layer, or use \"New layer\" output."))
        if drawable.get_mask() is not None:
            raise RuntimeError(_("This layer already has a mask. Delete it "
                                 "first (or use \"New layer\" output), so the "
                                 "old mask is not thrown away silently."))
        MI.selection_from_mask(image, refined_canvas, canvas_w, canvas_h)
        mask_obj = drawable.create_mask(Gimp.AddMaskType.SELECTION)
        drawable.add_mask(mask_obj)
        MI.pdb('gimp-selection-none', image=image)
    elif output == OUTPUT_LAYER:
        MI.selection_from_mask(image, refined_canvas, canvas_w, canvas_h)
        layer = drawable.copy()
        layer.set_name(_("Refined layer"))
        image.insert_layer(layer, None, image.get_item_position(drawable))
        mask_obj = layer.create_mask(Gimp.AddMaskType.SELECTION)
        layer.add_mask(mask_obj)
        MI.pdb('gimp-selection-none', image=image)
        MI.pdb('gimp-layer-remove-mask', layer=layer,
               mode=int(Gimp.MaskApplyMode.APPLY))
        if decontaminate > 0:
            if on_tick:
                Gimp.progress_set_text(_("Removing the colour fringe…"))
            gw, gh, grid, _mean = background_grid(rgba, refined, w, h)
            info["decontaminated"] = decontaminate_layer(
                layer, grid, gw, gh, w, h, strength=decontaminate / 100.0)
        info["layer"] = layer
    else:
        raise RuntimeError(_("Unknown output mode: %s") % output)

    info["seconds"] = time.time() - t0
    return info


# ---- 对话框（带实时预览） --------------------------------------------------

def _fmt_size(w, h):
    return "%d×%d" % (w, h)


def _scale_row(box, label, lo, hi, step, value, digits=0):
    """一行滑杆：左边名字 + 右边数值。返回 Gtk.Scale。"""
    from gi.repository import Gtk
    row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    name = Gtk.Label.new(label)
    name.set_xalign(0.0)
    name.set_size_request(96, -1)
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    scale.set_digits(digits)
    scale.set_value(value)
    scale.set_draw_value(True)
    scale.set_hexpand(True)
    row.add(name)
    row.add(scale)
    box.add(row)
    return scale


def build_dialog(config, image, drawable, w, h, mask):
    """建出对话框，返回 (dlg, ctx)。**故意不 run()**：无头回归可以直接调
    ctx["render"] 验证预览真的画出来了（div 里没有窗口也能建 Gtk 控件）。

    预览和应用调的是同一个 refine_mask，只是分辨率不同；参数按画布像素给，
    这里按比例换算（否则 6000 px 原图上「半径 4」在 520 的预览里会变成
    0.3 px，看起来像滑杆坏了）。
    """
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GdkPixbuf

    canvas_w, canvas_h = image.get_width(), image.get_height()
    pw, ph, prgba = MI.read_drawable_rgba(drawable, PREVIEW_EDGE)
    pmw, pmh, pmask = MI.scale_mask(mask, w, h, pw, ph)
    pgray = RM.luma(prgba, pw, ph)

    dlg = Gtk.Dialog.new()
    dlg.set_title(_("Select and Mask — refine the edge"))
    dlg.set_default_size(820, 480)
    dlg.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
    dlg.add_button(_("_Apply"), Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)

    area = dlg.get_content_area()
    area.set_border_width(10)
    area.set_spacing(6)

    outer = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 12)
    area.add(outer)

    # ---- 左：预览 ----
    left = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
    frame = Gtk.Frame.new()
    preview = Gtk.Image.new()
    frame.add(preview)
    left.add(frame)
    mode_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 4)
    left.add(mode_row)
    modes = [("checker", _("Checker")), ("white", _("White")),
             ("black", _("Black")), ("red", _("Red overlay"))]
    buttons = {}
    first = None
    for key, label in modes:
        btn = Gtk.RadioButton.new_with_label_from_widget(first, label)
        if first is None:
            first = btn
        buttons[key] = btn
        mode_row.add(btn)
    outer.add(left)

    # ---- 右：滑杆 ----
    right = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
    right.set_size_request(320, -1)
    outer.add(right)

    s_radius = _scale_row(right, _("Edge radius"), 0, 12, 1,
                          config.get_property('radius') or 0)
    s_radius.set_tooltip_text(_(
        "Search within ±N px for a real edge in the picture and pull the "
        "mask to it. 0 = off (an approximation of Photoshop's Smart Radius)"))
    smart = Gtk.CheckButton.new_with_label(_("Only snap to clearly stronger edges"))
    smart.set_active(bool(config.get_property('smart')))
    right.add(smart)
    s_smooth = _scale_row(right, _("Smooth"), 0, 10, 0.5,
                          config.get_property('smooth'), digits=1)
    s_feather = _scale_row(right, _("Feather"), 0, 30, 0.5,
                           config.get_property('feather'), digits=1)
    s_contrast = _scale_row(right, _("Contrast"), 0, 100, 1,
                            config.get_property('contrast'))
    s_shift = _scale_row(right, _("Shift edge"), -100, 100, 1,
                         config.get_property('shift'))
    s_shift.set_tooltip_text(_("Positive expands the mask, negative contracts it"))
    s_decon = _scale_row(right, _("Decontaminate"), 0, 100, 1,
                         config.get_property('decontaminate'))

    out_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    out_lbl = Gtk.Label.new(_("Output"))
    out_lbl.set_xalign(0.0)
    out_lbl.set_size_request(96, -1)
    combo = Gtk.ComboBoxText.new()
    out_items = [(OUTPUT_MASK, _("Layer mask")),
                 (OUTPUT_LAYER, _("New layer (transparent)")),
                 (OUTPUT_SELECTION, _("Selection")),
                 (OUTPUT_CHANNEL, _("Channel + selection"))]
    for idx, (key, label) in enumerate(out_items):
        combo.append(key, label)
        if key == (config.get_property('output') or OUTPUT_MASK):
            combo.set_active(idx)
    if combo.get_active() < 0:
        combo.set_active(0)
    out_row.add(out_lbl)
    out_row.add(combo)
    right.add(out_row)

    note = Gtk.Label.new("")
    note.set_xalign(0.0)
    note.set_line_wrap(True)
    right.add(note)

    state = {"id": 0}

    def values():
        return {
            "radius": s_radius.get_value(),
            "smart": smart.get_active(),
            "smooth": s_smooth.get_value(),
            "feather": s_feather.get_value(),
            "contrast": s_contrast.get_value(),
            "shift": s_shift.get_value(),
            "decontaminate": s_decon.get_value(),
            "output": combo.get_active_id() or OUTPUT_MASK,
        }

    def render():
        state["id"] = 0
        v = values()
        k = float(pw) / max(canvas_w, 1)   # 画布像素 → 预览像素
        mode = "checker"
        for key, btn in buttons.items():
            if btn.get_active():
                mode = key
                break
        t0 = time.time()
        try:
            out = RM.refine_mask(
                pmask, pw, ph, gray=pgray,
                radius=v["radius"] * k if v["radius"] > 0 else 0,
                smart=v["smart"],
                smooth=v["smooth"] * k, feather=v["feather"] * k,
                contrast=v["contrast"], shift=v["shift"])
            composed = RM.compose_preview(prgba, out, pw, ph, mode)
            pix = GdkPixbuf.Pixbuf.new_from_bytes(
                GLib.Bytes.new(composed), GdkPixbuf.Colorspace.RGB,
                True, 8, pw, ph, pw * 4)
            preview.set_from_pixbuf(pix)
            st = RM.mask_stats(out)
            note.set_text(_("Preview %s · refine runs at %s · image %s\n"
                            "%.0f%% kept (soft edge %.1f%%) · %.0f ms") % (
                _fmt_size(pw, ph), _fmt_size(w, h), _fmt_size(canvas_w, canvas_h),
                100.0 * st["solid_ratio"],
                100.0 * st["soft"] / max(st["pixels"], 1),
                (time.time() - t0) * 1000.0))
        except Exception as exc:
            note.set_text(_("Preview failed: %s") % exc)
        return False

    def schedule(*_a):
        if state["id"]:
            GLib.source_remove(state["id"])
        state["id"] = GLib.timeout_add(90, render)

    for widget in (s_radius, s_smooth, s_feather, s_contrast, s_shift, s_decon):
        widget.connect("value-changed", schedule)
    smart.connect("toggled", schedule)
    for btn in buttons.values():
        btn.connect("toggled", schedule)

    render()
    area.show_all()
    return dlg, {"render": render, "values": values, "note": note,
                 "preview": preview, "state": state, "dialog": dlg,
                 "buttons": buttons, "scales": (s_radius, s_smooth, s_feather,
                                                s_contrast, s_shift, s_decon),
                 "smart": smart, "combo": combo}


def show_dialog(procedure, config, image, drawable, w, h, mask):
    """弹窗：左边预览、右边滑杆。True = 应用（参数已写回 config）。"""
    try:
        dlg, ctx = build_dialog(config, image, drawable, w, h, mask)
        from gi.repository import Gtk
    except Exception as exc:
        Gimp.message(_("This build of GIMP has no GTK — running with the "
                       "current values. (%s)") % exc)
        return True

    resp = dlg.run()
    if ctx["state"]["id"]:
        GLib.source_remove(ctx["state"]["id"])
    if resp != Gtk.ResponseType.OK:
        dlg.destroy()
        return False

    v = ctx["values"]()
    for key in ("radius", "smooth", "feather", "contrast", "shift",
                "decontaminate"):
        config.set_property(key, float(v[key]))
    config.set_property("smart", bool(v["smart"]))
    config.set_property("output", v["output"])
    dlg.destroy()
    return True


# ---- 过程注册 --------------------------------------------------------------

def _add_arguments(procedure):
    procedure.add_double_argument(
        "radius", _("Edge radius"),
        _("Search within ±N px along the normal for a real edge in the "
          "picture and pull the mask to it; 0 turns it off. This is an "
          "approximation of Photoshop's Smart Radius (it moves the profile, "
          "it does not rebuild the matte)."), 0.0, 12.0, 0.0,
        GObject.ParamFlags.READWRITE)
    procedure.add_boolean_argument(
        "smart", _("Only snap to clearly stronger edges"),
        _("On: move only when the found edge is at least 1.35× stronger than "
          "the current position. Off: snap to anything stronger within the "
          "radius, which pulls harder."), True, GObject.ParamFlags.READWRITE)
    procedure.add_double_argument(
        "smooth", _("Smooth"),
        _("Round off jaggies and stray specks on the mask edge"),
        0.0, 10.0, 1.0, GObject.ParamFlags.READWRITE)
    procedure.add_double_argument(
        "feather", _("Feather"),
        _("Soften the transition; 0 keeps the edge hard"),
        0.0, 30.0, 1.0, GObject.ParamFlags.READWRITE)
    procedure.add_double_argument(
        "contrast", _("Contrast"),
        _("Push the soft part of the mask towards 0 and 255 — this is what "
          "turns a mushy edge into a crisp one"), 0.0, 100.0, 10.0,
        GObject.ParamFlags.READWRITE)
    procedure.add_double_argument(
        "shift", _("Shift edge"),
        _("Positive expands the mask, negative contracts it; the 50% line "
          "moves, the softness stays"), -100.0, 100.0, 0.0,
        GObject.ParamFlags.READWRITE)
    procedure.add_double_argument(
        "decontaminate", _("Decontaminate"),
        _("Pull the colour of half-transparent edge pixels back to the "
          "foreground colour (removes the white/green fringe). Only used by "
          "the \"New layer\" output, because the others do not touch pixels"),
        0.0, 100.0, 0.0, GObject.ParamFlags.READWRITE)
    choice = Gimp.Choice.new()
    choice.add(OUTPUT_MASK, 0, _("Layer mask"),
               _("Add the refined mask to the current layer"))
    choice.add(OUTPUT_LAYER, 1, _("New layer (transparent)"),
               _("Copy the layer, bake the mask into its alpha, and "
                 "decontaminate the edge colours"))
    choice.add(OUTPUT_SELECTION, 2, _("Selection"),
               _("Replace the selection; nothing else changes"))
    choice.add(OUTPUT_CHANNEL, 3, _("Channel + selection"),
               _("Store the result as a \"Refined Mask\" channel and keep it "
                 "as the selection — paint on the channel with a brush to "
                 "add or remove areas, then load it again"))
    procedure.add_choice_argument(
        "output", _("Output"), _("Where the refined mask goes"),
        choice, OUTPUT_MASK, GObject.ParamFlags.READWRITE)
    procedure.add_int_argument(
        "work-size", _("Working size"),
        _("Long edge the mask is refined at, then scaled back to the canvas "
          "with C code. 0 = full resolution (slow: pure Python, no numpy in "
          "GIMP's Python)"), 0, 8000, 1600, GObject.ParamFlags.READWRITE)


class RefineMaskPlugin(Gimp.PlugIn):

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
        procedure.set_menu_label(_("Select and Mask"))
        procedure.set_documentation(
            _("Refine a selection or mask: snap to edges, smooth, feather, "
              "contrast, shift, decontaminate"),
            _("Takes the current selection (or the mask channel left by Cut "
              "Out) and turns a rough edge into a usable one. Opens a dialog "
              "with a live preview; the same code runs at full resolution "
              "when you press Apply."),
            name)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        _add_arguments(procedure)
        procedure.add_menu_path("<Image>/SuperMrWang/Mask")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        drawable = drawables[0]
        try:
            work = int(config.get_property('work-size') or 0)
            w, h, mask, _source = MI.current_mask(image, work)
            if run_mode == Gimp.RunMode.INTERACTIVE:
                if not show_dialog(procedure, config, image, drawable, w, h, mask):
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.CANCEL, None)
            info = refine_selection(
                image, drawable,
                radius=config.get_property('radius'),
                smart=config.get_property('smart'),
                smooth=config.get_property('smooth'),
                feather=config.get_property('feather'),
                contrast=config.get_property('contrast'),
                shift=config.get_property('shift'),
                decontaminate=config.get_property('decontaminate'),
                output=config.get_property('output'),
                work_size=work,
                on_tick=Gimp.progress_pulse)
            msg = _("Refined at %s in %.1f s — solid area %.0f%% → %.0f%%.") % (
                _fmt_size(info["work"][0], info["work"][1]),
                info["seconds"],
                100.0 * info["before"]["solid_ratio"],
                100.0 * info["after"]["solid_ratio"])
            if info.get("decontaminated"):
                msg += " " + _("Decontaminated %d edge pixels.") % \
                    info["decontaminated"]
            if info["output"] == OUTPUT_CHANNEL:
                msg += " " + _("Paint on the \"Refined Mask\" channel to add "
                               "or remove areas, then load it as a selection.")
            Gimp.message(msg)
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("refine-mask: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(RefineMaskPlugin.__gtype__, _sys.argv)
