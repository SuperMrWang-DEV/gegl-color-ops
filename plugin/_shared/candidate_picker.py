#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 候选挑选器 / candidate picker
 ---------------------------------------------------------------------------
 purpose   一次出多张填充结果时，给它们一个能看、能点的界面：几张缩略图
           并排，标上分数与「最优」，点一下换一张，确认后只留选中的那张
           （其余可以保留为隐藏图层，方便反悔）。

 why       在这之前候选只是图层面板里的几个隐藏图层，名字是
           「AI Inpaint 2 (2.46)」——分数是罚分（越小越好），名字里看不出
           画的是什么，不点眼睛就看不见。3 张里挑 1 张这个功能等于没被
           用起来。

 usage     dlg, ctx = build_dialog(layers, order, scores)
           dlg.run() → Gtk.ResponseType.OK 时取 ctx["values"]()
           build_dialog **故意不 run()**：无头回归可以直接调
           ctx["select"](i) / ctx["values"]() 验证，不需要真窗口。

 note      三条：
           1. 缩略图走 mask_io.read_drawable_rgba 的 exact= 分支（临时图层
              + gimp-layer-scale），Python 里自己插值会慢一个数量级。
           2. R'G'B'A u8 是字节序 RGB(A)，cairo 的 RGB24 在小端是 BGRX，
              必须换序；surface 的 buffer 得活到对话框销毁，所以存在 ctx 里。
           3. 这个模块只读像素、只画界面，**不改图像**。可见性与删除都由
              调用方在用户确认之后做。
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import GLib, Gegl

try:
    from lb_i18n import _          # noqa: F811
except Exception:                  # helper 不在：保持可用，只是不翻译
    def _(message):
        return GLib.dgettext(None, message)

import mask_io as MI              # noqa: E402

try:
    import cairo
except Exception:                  # 没有 pycairo：挑选器整体不可用
    cairo = None

TILE = 380       # 缩略图长边（px）
PAD = 6          # 缩略图外面留的白，给选中边框用
GAP = 12         # 两张之间
FOCUS_PAD = 0.30     # 缩略图裁切：选区四周留多少（占选区尺寸的比例）
FOCUS_FLOOR = 340.0  # 裁切窗口长边下限：太小会放大到糊


def available():
    """能不能弹窗（pycairo + Gtk3 都在）。"""
    if cairo is None:
        return False
    try:
        gi.require_version('Gtk', '3.0')
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gtk, Gdk      # noqa: F401
        return True
    except Exception:
        return False


def _crop_box(lw, lh, focus, pad=FOCUS_PAD, floor=FOCUS_FLOOR):
    """选区 → 缩略图该看哪一块（图层坐标）。

    候选图层覆盖的是「选区 + 上下文」，比例常常是 744×496 里只有中间一条
    120 px 是选区。整块缩到 380 px，衣服/耳环就只剩几十像素，三张看起来
    一模一样——挑选器等于没用。所以窗口按「选区 + 30% 边距」算，长边再
    设个下限（太小就别放大到糊），最后夹回图层里。
    """
    if not focus:
        return None
    x, y, w, h = [float(v) for v in focus]
    if w <= 0 or h <= 0:
        return None
    cw, ch = w * (1.0 + 2.0 * pad), h * (1.0 + 2.0 * pad)
    k = max(1.0, floor / max(cw, ch))
    cw, ch = min(cw * k, float(lw)), min(ch * k, float(lh))
    x0 = max(0.0, min(lw - cw, x + w / 2.0 - cw / 2.0))
    y0 = max(0.0, min(lh - ch, y + h / 2.0 - ch / 2.0))
    box = (int(round(x0)), int(round(y0)),
           max(1, int(round(cw))), max(1, int(round(ch))))
    # 已经接近整层：走整层那条路（GIMP 缩放，比这里的手写下采样干净）
    if box[2] * box[3] >= 0.94 * lw * lh:
        return None
    return box


def _box_shrink(px, sw, sh, dw, dh):
    """整数比 box 平均下采样。只在下采样（dw<=sw）时用。"""
    out = bytearray(dw * dh * 4)
    xs = [int(c * sw / dw) for c in range(dw)] + [sw]
    ys = [int(r * sh / dh) for r in range(dh)] + [sh]
    for r in range(dh):
        y0, y1 = ys[r], max(ys[r] + 1, ys[r + 1])
        for c in range(dw):
            x0, x1 = xs[c], max(xs[c] + 1, xs[c + 1])
            sr = sg = sb = sa = 0
            n = 0
            for yy in range(y0, y1):
                base = yy * sw * 4
                for xx in range(x0, x1):
                    i = base + xx * 4
                    sr += px[i]
                    sg += px[i + 1]
                    sb += px[i + 2]
                    sa += px[i + 3]
                    n += 1
            o = (r * dw + c) * 4
            n = max(1, n)
            out[o] = sr // n
            out[o + 1] = sg // n
            out[o + 2] = sb // n
            out[o + 3] = sa // n
    return bytes(out)


def _tile_pixels(layer, tile=TILE, focus=None):
    """图层 → (w, h, rgba)，长边不超过 tile。

    focus = 选区在图层里的位置 (x, y, w, h)；给了就只看选区附近，
    None 或等于整层时退回「整层用 GIMP 缩」。
    """
    lw, lh = max(1, layer.get_width()), max(1, layer.get_height())
    crop = _crop_box(lw, lh, focus)
    if crop:
        x, y, cw, ch = crop
        raw = layer.get_buffer().get(
            Gegl.Rectangle.new(x, y, cw, ch), 1.0, "R'G'B'A u8",
            Gegl.AbyssPolicy.NONE)
        px = bytes(bytearray(raw))
        k = float(tile) / max(cw, ch)
        tw = max(1, int(round(cw * k)))
        th = max(1, int(round(ch * k)))
        if (tw, th) != (cw, ch):
            if tw <= cw and th <= ch:
                px = _box_shrink(px, cw, ch, tw, th)
            else:                      # 只放大：最近邻，别糊成一团
                out = bytearray(tw * th * 4)
                for r in range(th):
                    sy = min(ch - 1, int(r * ch / th))
                    for c in range(tw):
                        sx = min(cw - 1, int(c * cw / tw))
                        i = (sy * cw + sx) * 4
                        o = (r * tw + c) * 4
                        out[o:o + 4] = px[i:i + 4]
                px = bytes(out)
        return tw, th, px

    w, h = lw, lh
    k = float(tile) / max(w, h)
    tw = max(1, int(round(w * k)))
    th = max(1, int(round(h * k)))
    pw, ph, px = MI.read_drawable_rgba(layer, tile, exact=(tw, th))
    return pw, ph, px


def _surface(px, w, h):
    """RGBA 字节 → cairo surface。返回 (surface, buf)：buf 必须被引用住。

    小端下 FORMAT_RGB24 的内存顺序是 B,G,R,X，而 GIMP 给的是 R,G,B,A，
    所以逐像素换序（顺手把 alpha 丢掉：候选整块都是不透明的）。
    """
    buf = bytearray(w * h * 4)
    for i in range(w * h):
        j = i * 4
        buf[j] = px[j + 2]
        buf[j + 1] = px[j + 1]
        buf[j + 2] = px[j]
        buf[j + 3] = 255
    surf = cairo.ImageSurface.create_for_data(
        buf, cairo.FORMAT_RGB24, w, h, w * 4)
    return surf, buf


def build_dialog(layers, order, scores, tile=TILE, title=None, note=None,
                 focus=None):
    """建出挑选窗口，返回 (dlg, ctx)。**不 run()**。

    ctx["select"](i)  选中第 i 个候选（0 起，对应 layers 下标）
    ctx["values"]()   {"index": 选中下标, "keep_all": 是否保留其余候选}
    """
    if not available():
        raise RuntimeError(_("GTK/cairo unavailable — no picker in this build"))
    from gi.repository import Gtk, Gdk

    n = len(layers)
    if n < 2:
        raise ValueError("picker needs at least two candidates")

    order = list(order or range(n))
    scores = list(scores or [])
    best = order[0] if order else 0

    tiles = []
    tw_sum = th_sum = 0
    for index, layer in enumerate(layers):
        w, h, px = _tile_pixels(layer, tile, focus=focus)
        surf, buf = _surface(px, w, h)
        tiles.append({"index": index, "w": w, "h": h,
                      "surface": surf, "buf": buf,
                      "score": scores[index] if index < len(scores) else None,
                      "rank": order.index(index) if index in order else 99})
        tw_sum = max(tw_sum, w)
        th_sum = max(th_sum, h)

    dlg = Gtk.Dialog.new()
    dlg.set_title(title or _("Pick a candidate"))
    dlg.add_button(_("Keep the _best"), Gtk.ResponseType.CANCEL)
    dlg.add_button(_("_Use selected"), Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    dlg.set_resizable(False)

    outer = Gtk.Box.new(Gtk.Orientation.VERTICAL, 8)
    outer.set_border_width(10)
    dlg.get_content_area().add(outer)

    row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, GAP)
    outer.add(row)

    area_w, area_h = tw_sum + PAD * 2, th_sum + PAD * 2
    ctx = {"tiles": tiles, "selected": best, "order": order,
           "areas": [], "labels": []}

    def draw(area, cr, i):
        t = tiles[i]
        x = (area_w - t["w"]) // 2
        y = (area_h - t["h"]) // 2
        cr.set_source_surface(t["surface"], x, y)
        cr.paint()
        # 边框：选中的是蓝实线，最优的那张没选中时给一圈淡绿
        if ctx["selected"] == i:
            cr.set_source_rgb(0.16, 0.52, 1.0)
            cr.set_line_width(3.0)
        elif t["index"] == best:
            cr.set_source_rgb(0.24, 0.62, 0.36)
            cr.set_line_width(1.5)
        else:
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.35)
            cr.set_line_width(1.0)
        cr.rectangle(1.0, 1.0, area_w - 2.0, area_h - 2.0)
        cr.stroke()
        return False

    def on_press(area, event, i):
        if event.button == 1:
            ctx["select"](i)
            return True
        return False

    for i, t in enumerate(tiles):
        col = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
        area = Gtk.DrawingArea.new()
        area.set_size_request(area_w, area_h)
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        area.connect("draw", draw, i)
        area.connect("button-press-event", on_press, i)
        col.add(area)
        ctx["areas"].append(area)

        head = Gtk.Label.new("")
        head.set_xalign(0.5)
        col.add(head)
        ctx["labels"].append(head)
        row.add(col)

    keep = Gtk.CheckButton.new_with_label(
        _("Keep the other candidates as hidden layers"))
    keep.set_active(True)
    keep.set_tooltip_text(
        _("Unchecked: the candidates you did not pick are deleted. Either way "
          "this is one undo step."))
    outer.add(keep)

    hint = Gtk.Label.new("")
    hint.set_xalign(0.0)
    hint.set_line_wrap(True)
    hint.set_max_width_chars(78)
    hint.set_markup("<small>%s</small>" % GLib.markup_escape_text(
        note or _("Click a thumbnail to choose it. The numbers are penalty "
                  "scores — lower is better; the smallest one is the pick the "
                  "plug-in would have made on its own.")))
    outer.add(hint)

    def refresh_labels():
        for i, t in enumerate(tiles):
            bits = ["<b>#%d</b>" % (i + 1)]
            if t["score"] is not None:
                bits.append("%.2f" % t["score"])
            if t["index"] == best:
                bits.append("<span foreground='#3d9e5a'>%s</span>"
                            % GLib.markup_escape_text(_("auto pick")))
            if ctx["selected"] == i:
                bits.append("<b>%s</b>" % GLib.markup_escape_text(_("chosen")))
            ctx["labels"][i].set_markup("  ".join(bits))
            ctx["labels"][i].set_tooltip_text(
                _("Candidate #%d · penalty %.2f · lower is better")
                % (i + 1, t["score"] or 0.0))

    def select(i):
        if 0 <= i < len(tiles):
            ctx["selected"] = i
            for area in ctx["areas"]:
                area.queue_draw()
            refresh_labels()

    def values():
        return {"index": ctx["selected"], "keep_all": bool(keep.get_active())}

    def on_key(_w, event):
        from gi.repository import Gdk as _Gdk
        if event.keyval in (_Gdk.KEY_Left, _Gdk.KEY_Up):
            select(ctx["selected"] - 1)
            return True
        if event.keyval in (_Gdk.KEY_Right, _Gdk.KEY_Down):
            select(ctx["selected"] + 1)
            return True
        # 数字键 1..9 直接跳
        if _Gdk.KEY_1 <= event.keyval <= _Gdk.KEY_9:
            select(event.keyval - _Gdk.KEY_1)
            return True
        return False

    dlg.connect("key-press-event", on_key)

    ctx["select"] = select
    ctx["values"] = values
    ctx["keep"] = keep
    refresh_labels()
    outer.show_all()
    return dlg, ctx


def choose(layers, order, scores, tile=TILE, note=None, focus=None):
    """弹窗挑一张；用户放弃时返回 None（调用方按「用最优那张」处理）。"""
    if not available() or len(layers) < 2:
        return None
    from gi.repository import Gtk
    dlg, ctx = build_dialog(layers, order, scores, tile=tile, note=note,
                            focus=focus)
    try:
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            return ctx["values"]()
        return None
    finally:
        dlg.destroy()
