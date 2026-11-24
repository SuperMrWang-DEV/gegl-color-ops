#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 木偶变形 / 网格变形 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把 PS 的「木偶变形」搬过来：在图层上点几个钉子，拖住钉子把内容
           拽过去，钉子之间的像素被平滑地带着走，离钉子远的地方一个字节
           都不动。姿势微调、拉长胳膊、把歪掉的杯子掰正，都不用手动液化。

 menu      SuperMrWang → Distort → 木偶变形（网格变形）…

 usage     选一个图层 → 菜单 → 在画布上点一下放钉子（拖动就顺手拽走）→
           需要的话调「影响半径 / 变形方式」→ 应用。
           右键点钉子删除；选中钉子按 Delete 也能删。

 note      三条非踩不可的：
           1. **PS 的木偶变形不是网格三角形插值，是 ARAP**。这里用的是
              MLS（见 _shared/warp_math.py）：没有线性方程要解，纯 Python
              也跑得动，钉子上严格插值、场光滑。代价是大幅拖拽时它比 ARAP
              更容易拉出「橡皮膜」感——想更硬就用「刚性（保形）」模式。
           2. **预览和应用必须调同一个 build_field + warp_rgba**。两边只是
              分辨率不同（预览 520 长边、应用是全分辨率），参数按比例换算。
              两套实现必然漂。
           3. **没动的行整行抄**。纯 Python 1600×2400 全图重采样要 6 s；
              行级剪枝之后，只动画面一角时是 0.2 s 级。别把 warp_rgba 里
              那段「先按节点扫脏段」删掉，删了就退回六秒。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math as _math
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

import warp_math as WM                 # noqa: E402
import mask_io as MI                  # noqa: E402

try:
    import native_warp as NW           # 预览直接调算子 .dll（ctypes）
except Exception:                      # 没有就退回 numpy 那一路
    NW = None

try:
    import preview_geom as PG         # 预览尺寸按屏幕余量算，不再写死 520
except Exception:
    PG = None

try:                                   # ARAP 要 numpy；没装就只隐藏这一档
    import arap as ARAP               # noqa: E402
except Exception:
    ARAP = None

PROC = 'lb-plugin-puppet-warp'
# 兜底值。真实尺寸由 preview_geom 按屏幕可用区算，C 快路可用时才放开；
# 原来固定 520 是为了让 numpy 那路跟得上手，代价是预览只有一小块。
PREVIEW_EDGE = 520
# 预览用的 ARAP 网格比应用时粗：577 个顶点、拖钉子时 ~15 ms，
# 够跟上手；应用时再用 48 那档，细节更准。
PREVIEW_ARAP_NODES = 34
MODE_SIMILARITY = 'similarity'
MODE_AFFINE = 'affine'
MODE_ARAP = 'arap'
OUTPUT_FILTER = 'filter'
OUTPUT_REPLACE = 'replace'
OUTPUT_LAYER = 'new-layer'
# 非破坏那一路挂的 GEGL 算子（ops/puppet-warp）。它的 pins/mode/radius
# 属性跟这里的 PDB 参数同名同义，所以对话框写回 config 就等于写回滤镜。
FILTER_OP = 'lb:puppet-warp'
PIN_HIT = 11


# ---- 变形本体 --------------------------------------------------------------

def _write_rgba(layer, w, h, rgba):
    """把 RGBA 字节写回图层。没有 alpha 的图层要退回 3 通道，否则 buf.set
    会因为格式不匹配直接抛错（GIMP 不会替你丢通道）。"""
    if len(rgba) != w * h * 4:
        raise RuntimeError(_("Pixel buffer size mismatch: %d bytes for %d×%d")
                           % (len(rgba), w, h))
    has_alpha = bool(layer.has_alpha())
    if has_alpha:
        fmt, data = "R'G'B'A u8", bytes(rgba)
    else:
        n = w * h
        rgb = bytearray(n * 3)
        rgb[0::3] = rgba[0::4]
        rgb[1::3] = rgba[1::4]
        rgb[2::3] = rgba[2::4]
        fmt, data = "R'G'B' u8", bytes(rgb)
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), fmt, data)
    buf.flush()


def check_drawable(drawable):
    """能不能变形这个 item。返回 None 就放行，否则抛带人话的异常。

    单独拆出来是为了能测：图层组、文字层都没有「可变的像素」，
    等跑到 get_buffer 才炸，报错会变成一堆 gimp 内部信息。
    """
    if drawable is None:
        raise RuntimeError(_("Nothing is selected. Pick a pixel layer first."))
    if not drawable.is_layer():
        raise RuntimeError(_(
            "That is not a layer. Select a normal pixel layer first."))
    if drawable.is_group():
        raise RuntimeError(_(
            "That is a layer group. Pick a single layer inside it — a group "
            "has no pixels of its own to warp."))
    if drawable.is_text_layer() or drawable.is_vector_layer():
        raise RuntimeError(_(
            "That is a text/vector layer. Rasterise it first (Layer → "
            "Discard text information), otherwise there are no pixels to "
            "warp."))
    if drawable.get_width() < 2 or drawable.get_height() < 2:
        raise RuntimeError(_("The layer is %d×%d — too small to warp.")
                           % (drawable.get_width(), drawable.get_height()))


def arap_ok():
    """ARAP 这一档能不能用（要 numpy）。"""
    try:
        return ARAP is not None and ARAP.available() and WM.have_numpy()
    except Exception:
        return False


def find_filter(drawable):
    """图层上已有的木偶变形滤镜（有就返回它，重跑时接着改而不是再叠一条）。"""
    try:
        for filt in drawable.get_filters():
            if filt.get_operation_name() == FILTER_OP:
                return filt
    except Exception:
        pass
    return None


def load_filter_state(drawable):
    """从滤镜 config 里读回钉子/模式/范围。没有滤镜就返回 None。"""
    filt = find_filter(drawable)
    if filt is None:
        return None
    cfg = filt.get_config()
    return {
        'pins': cfg.get_property('pins') or '',
        'mode': cfg.get_property('mode') or MODE_SIMILARITY,
        'radius': float(cfg.get_property('radius') or 30.0),
    }


def apply_filter(drawable, pins, mode=MODE_SIMILARITY, radius=30.0,
                 copy_layer=False):
    """非破坏那一路：把钉子串挂到滤镜栈上，原像素一个字节都不动。

    重跑时更新同一条滤镜；copy_layer=True 先复制图层再挂，原层保持干净。
    """
    layer = drawable
    if copy_layer:
        image = drawable.get_image()
        layer = drawable.copy()
        layer.set_name(drawable.get_name() + _(" (warp filter)"))
        image.insert_layer(layer, None, image.get_item_position(drawable))
    filt = find_filter(layer)
    label = _("Puppet warp")
    if filt is None:
        filt = Gimp.DrawableFilter.new(layer, FILTER_OP, label)
    cfg = filt.get_config()
    cfg.set_property('pins', WM.format_pin_string(pins))
    cfg.set_property('mode', mode)
    cfg.set_property('radius', float(radius))
    filt.update()
    if find_filter(layer) is None:
        layer.append_filter(filt)
    return filt, layer


def warp_drawable(drawable, pins, mode=MODE_SIMILARITY, radius=0.30,
                  output=OUTPUT_REPLACE, on_tick=None):
    """全分辨率变形一个图层。返回 info 字典。

    radius 是「长边的百分比」而不是像素：预览和全分辨率各自按自己的长边算，
    同一个数值在两处是同一片区域。
    """
    image = drawable.get_image()
    w, h = drawable.get_width(), drawable.get_height()
    t0 = time.time()
    long_edge = max(w, h)
    pins = WM.normalized_pins(pins)
    moved = WM.pin_summary(pins)["moved"]
    if not pins:
        raise RuntimeError(_("No pins yet — click on the picture to place at "
                             "least one, then drag it."))
    if not moved:
        raise RuntimeError(_("None of the pins has been dragged yet — drag a "
                             "pin away from where you placed it."))
    if mode == MODE_ARAP and not arap_ok():
        raise RuntimeError(_(
            "ARAP needs numpy, which this GIMP's Python does not have. "
            "Run tools/install_gimp_numpy.py, or pick one of the MLS modes."))

    field = WM.build_field(w, h, pins, mode=mode, radius=radius * long_edge)
    if field.is_identity():
        raise RuntimeError(_("The deformation came out empty (pins are too "
                             "close to cancel each other out)."))

    _pw, _ph, rgba = MI.read_drawable_rgba(drawable, long_edge)
    if (_pw, _ph) != (w, h):            # 不该发生，但别让错位的图悄悄写回去
        raise RuntimeError(_("Read the layer at the wrong size: %d×%d, "
                             "expected %d×%d") % (_pw, _ph, w, h))

    if on_tick:
        Gimp.progress_set_text(_("Warping %d×%d…") % (w, h))
        # warp_rgba 每行调一次 progress(0..1)，Gimp.progress_pulse 不收参数，
        # 直接传进去会 TypeError —— 包一层。
        tick = lambda _frac: on_tick()
    else:
        tick = None
    warped = WM.warp_rgba(rgba, w, h, field, progress=tick)

    if output == OUTPUT_LAYER:
        layer = drawable.copy()
        layer.set_name(drawable.get_name() + _(" (warped)"))
        image.insert_layer(layer, None, image.get_item_position(drawable))
    else:
        layer = drawable
    _write_rgba(layer, w, h, warped)

    info = WM.pin_summary(pins)
    info.update({"seconds": time.time() - t0, "size": (w, h),
                 "field": field, "layer": layer})
    return info


# ---- 对话框（画布上放钉子/拖钉子 + 实时预览） -------------------------------

def _fmt_size(w, h):
    return "%d×%d" % (w, h)


def _pixbuf_from_rgba(rgba, w, h):
    from gi.repository import GdkPixbuf
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(bytes(rgba)), GdkPixbuf.Colorspace.RGB, True, 8,
        w, h, w * 4)


def _checker(cr, w, h, size=10):
    cr.set_source_rgb(0.82, 0.82, 0.82)
    cr.paint()
    cr.set_source_rgb(0.70, 0.70, 0.70)
    y = 0
    row = 0
    while y < h:
        x = 0 if row % 2 == 0 else size
        while x < w:
            cr.rectangle(x, y, min(size, w - x), min(size, h - y))
            x += size * 2
        y += size
        row += 1
    cr.fill()


def _read_preview(drawable, w, h):
    """图层 → 预览像素。尺寸按屏幕余量算；C 不可用时 preview_geom 自己收回
    520 长边（numpy 那路再大就跟不上手了）。"""
    if PG is None:
        return MI.read_drawable_rgba(drawable, PREVIEW_EDGE)
    native = False
    if NW is not None:
        try:
            native = NW.puppet_preview().available
        except Exception:
            native = False
    tw, th = PG.preview_size(w, h, native=native)
    return MI.read_drawable_rgba(drawable, max(tw, th), exact=(tw, th))


def build_dialog(config, image, drawable, w, h):
    """建出对话框，返回 (dlg, ctx)。**故意不 run()**：无头回归直接调
    ctx["render"]() 就能验证「拖了钉子之后预览真的变了」。

    画布坐标 = 预览坐标（1:1），所以钉子存的是**图层坐标**，
    k = 预览 1 px 换多少图层 px。
    """
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk

    pw, ph, prgba = _read_preview(drawable, w, h)
    k = float(w) / max(pw, 1)

    dlg = Gtk.Dialog.new()
    dlg.set_title(_("Puppet Warp"))
    dlg.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
    dlg.add_button(_("_Apply"), Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    dlg.set_resizable(False)

    outer = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 12)
    outer.set_border_width(10)
    dlg.get_content_area().add(outer)

    left = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
    frame = Gtk.Frame.new()
    area = Gtk.DrawingArea.new()
    area.set_size_request(pw, ph)
    area.set_can_focus(True)
    area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                    Gdk.EventMask.BUTTON_RELEASE_MASK |
                    Gdk.EventMask.POINTER_MOTION_MASK)
    frame.add(area)
    left.add(frame)
    hint = Gtk.Label.new(_("Click to drop a pin · drag a pin to pull the "
                           "picture · right-click a pin to delete it"))
    hint.set_xalign(0.0)
    hint.set_line_wrap(True)
    hint.set_max_width_chars(44)
    left.add(hint)
    outer.add(left)

    right = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
    right.set_size_request(250, -1)
    outer.add(right)

    title = Gtk.Label.new("")
    title.set_xalign(0.0)
    title.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("Pins")))
    right.add(title)

    mode_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    lbl = Gtk.Label.new(_("Deformation"))
    lbl.set_xalign(0.0)
    lbl.set_size_request(96, -1)
    combo_mode = Gtk.ComboBoxText.new()
    combo_mode.append(MODE_SIMILARITY, _("Rigid (keeps shapes)"))
    combo_mode.append(MODE_AFFINE, _("Free (allows stretching)"))
    if arap_ok():
        combo_mode.append(MODE_ARAP, _("ARAP (best at bending)"))
    combo_mode.set_active_id(config.get_property('mode') or MODE_SIMILARITY)
    combo_mode.set_hexpand(True)
    mode_row.add(lbl)
    mode_row.add(combo_mode)
    right.add(mode_row)

    radius_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    rlbl = Gtk.Label.new(_("Falloff"))
    rlbl.set_xalign(0.0)
    rlbl.set_size_request(96, -1)
    s_radius = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1)
    s_radius.set_digits(0)
    s_radius.set_value(float(config.get_property('radius') or 30))
    s_radius.set_draw_value(True)
    s_radius.set_hexpand(True)
    radius_row.add(rlbl)
    radius_row.add(s_radius)
    right.add(radius_row)

    mesh = Gtk.CheckButton.new_with_label(_("Show the mesh"))
    mesh.set_active(True)
    right.add(mesh)

    out_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    out_lbl = Gtk.Label.new(_("Output"))
    out_lbl.set_xalign(0.0)
    out_lbl.set_size_request(96, -1)
    combo_out = Gtk.ComboBoxText.new()
    combo_out.append(OUTPUT_FILTER, _("Non-destructive filter (editable)"))
    combo_out.append(OUTPUT_REPLACE, _("Replace this layer"))
    combo_out.append(OUTPUT_LAYER, _("Copy to a new layer"))
    combo_out.set_active_id(config.get_property('output') or OUTPUT_FILTER)
    combo_out.set_hexpand(True)
    out_row.add(out_lbl)
    out_row.add(combo_out)
    right.add(out_row)

    btn_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 6)
    b_del = Gtk.Button.new_with_label(_("Delete selected"))
    b_clear = Gtk.Button.new_with_label(_("Clear pins"))
    btn_row.add(b_del)
    btn_row.add(b_clear)
    right.add(btn_row)

    note = Gtk.Label.new("")
    note.set_line_wrap(True)
    note.set_xalign(0.0)
    right.add(note)

    ctx = {
        "pins": WM.parse_pin_string(config.get_property('pins') or "", w, h),
        "selected": -1,
        "drag": None,
        "prgba": prgba, "pw": pw, "ph": ph, "k": k, "w": w, "h": h,
        "warped": prgba, "mesh": None, "id": 0,
        "area": area, "note": note, "dialog": dlg,
        "combo_mode": combo_mode, "combo_out": combo_out,
        "s_radius": s_radius, "pins_mesh": mesh,
    }

    def values():
        return {
            "mode": combo_mode.get_active_id() or MODE_SIMILARITY,
            "radius": s_radius.get_value(),
            "output": combo_out.get_active_id() or OUTPUT_FILTER,
            "show_mesh": bool(mesh.get_active()),
            "pins": [dict(p) for p in ctx["pins"]],
        }

    def render():
        """预览：把钉子缩到预览空间、解场、重采样。应用走的是同一个
        build_field + warp_rgba，只是 w/h 换成全分辨率。"""
        ctx["id"] = 0
        v = values()
        t0 = time.time()
        pins_prev = [{"sx": p["sx"] / k, "sy": p["sy"] / k,
                      "dx": p["dx"] / k, "dy": p["dy"] / k}
                     for p in v["pins"]]
        radius_prev = v["radius"] / 100.0 * max(pw, ph)
        try:
            # 先走 C（算子里同一个 pw_mls_reverse / ARAP 场 + pw_sample）：
            # 480×360 实测 80～100 ms 降到 10 ms 级，拖动才跟手。
            out = None
            if NW is not None:
                out = NW.puppet_preview().render(
                    WM.format_pin_string(pins_prev), prgba, pw, ph,
                    mode=v["mode"], radius=v["radius"])
            if out is not None:
                ctx["warped"] = out
                ctx["preview_path"] = "c"
            else:
                field = WM.build_field(pw, ph, pins_prev, mode=v["mode"],
                                       radius=radius_prev,
                                       arap_nodes=PREVIEW_ARAP_NODES)
                if field.is_identity():
                    ctx["warped"] = prgba
                else:
                    ctx["warped"] = WM.warp_rgba(prgba, pw, ph, field)
                ctx["preview_path"] = "py"
            if v["show_mesh"]:
                fwd = WM.build_field(pw, ph, pins_prev, mode=v["mode"],
                                     radius=radius_prev, forward=True,
                                     arap_nodes=PREVIEW_ARAP_NODES)
                ctx["mesh"] = WM.mesh_polylines(fwd, pw, ph, cols=10, rows=10)
            else:
                ctx["mesh"] = None
            st = WM.pin_summary(v["pins"])
            if v["mode"] == MODE_ARAP:
                # ARAP 是全局解算，没有「影响半径」这个概念：它靠弱锚定
                # 让远处待着，所以这一档下 falloff 滑杆是灰的。
                tail = _("ARAP · falloff not used")
            else:
                tail = _("falloff %.0f px") % (v["radius"] / 100.0 * max(w, h))
            note.set_text(_("%d pins, %d dragged, max shift %.1f px\n"
                            "preview %s of %s · %.0f ms · %s (%s)") % (
                st["count"], st["moved"], st["max_shift"],
                _fmt_size(pw, ph), _fmt_size(w, h),
                (time.time() - t0) * 1000.0, tail,
                "C" if ctx.get("preview_path") == "c" else "py"))
        except Exception as exc:
            note.set_text(_("Preview failed: %s") % exc)
        area.queue_draw()
        return False

    def schedule(delay=45):
        # 预览开大以后一帧 20～50 ms，防抖要跟着压下来（原来 70 是按 9 ms
        # 一帧定的，现在再等 70 ms 手会觉得拖泥带水）。
        if ctx["id"]:
            GLib.source_remove(ctx["id"])
        ctx["id"] = GLib.timeout_add(delay, render)

    def draw(_area, cr):
        # 画布可能比图宽（左边的提示语会把这一列撑开），所以底色按**分配到的
        # 尺寸**铺，不然右边会留一条没画的灰边。
        _checker(cr, _area.get_allocated_width(), _area.get_allocated_height())
        try:
            pix = _pixbuf_from_rgba(ctx["warped"], pw, ph)
            Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
            cr.paint()
        except Exception:
            pass
        if ctx["mesh"]:
            cr.set_line_width(1.0)
            cr.set_source_rgba(0.15, 0.65, 1.0, 0.55)
            for line in ctx["mesh"]:
                cr.move_to(line[0][0], line[0][1])
                for px, py in line[1:]:
                    cr.line_to(px, py)
                cr.stroke()
        for idx, pin in enumerate(ctx["pins"]):
            cx, cy = pin["dx"] / k, pin["dy"] / k
            selected = (idx == ctx["selected"])
            cr.set_line_width(2.0)
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.55)
            cr.arc(cx, cy, PIN_HIT * 0.55 + 1.5, 0, 2 * _math.pi)
            cr.fill()
            if selected:
                cr.set_source_rgba(1.0, 0.38, 0.10, 0.95)
            else:
                cr.set_source_rgba(1.0, 0.83, 0.20, 0.95)
            cr.arc(cx, cy, PIN_HIT * 0.55, 0, 2 * _math.pi)
            cr.fill_preserve()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.9)
            cr.stroke()
            if selected:
                cr.set_line_width(1.0)
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.6)
                cr.arc(cx, cy, PIN_HIT * 0.55 + 4, 0, 2 * _math.pi)
                cr.stroke()
        if not ctx["pins"]:
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.55)
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(15)
            cr.move_to(14, ph - 18)
            cr.show_text(_("Click on the picture to place the first pin"))

    def hit(x, y):
        best, best_d = -1, PIN_HIT ** 2
        for idx, pin in enumerate(ctx["pins"]):
            dx = pin["dx"] / k - x
            dy = pin["dy"] / k - y
            d = dx * dx + dy * dy
            if d <= best_d:
                best, best_d = idx, d
        return best

    def on_press(_area, ev):
        x, y = ev.x, ev.y
        idx = hit(x, y)
        if ev.button == 3:                      # 右键：删钉子
            if idx >= 0:
                del ctx["pins"][idx]
                ctx["selected"] = -1
                ctx["drag"] = None
                schedule(0)
            return True
        if ev.button != 1:
            return False
        area.grab_focus()
        if idx < 0:
            ix = min(max(x * k, 0.0), w - 1.0)
            iy = min(max(y * k, 0.0), h - 1.0)
            ctx["pins"].append({"sx": ix, "sy": iy, "dx": ix, "dy": iy})
            idx = len(ctx["pins"]) - 1
        ctx["selected"] = idx
        ctx["drag"] = (idx, x, y)
        schedule(0)
        return True

    def on_motion(_area, ev):
        drag = ctx["drag"]
        if not drag:
            return False
        idx, last_x, last_y = drag
        pin = ctx["pins"][idx]
        pin["dx"] = min(max(pin["dx"] + (ev.x - last_x) * k, 0.0), w - 1.0)
        pin["dy"] = min(max(pin["dy"] + (ev.y - last_y) * k, 0.0), h - 1.0)
        ctx["drag"] = (idx, ev.x, ev.y)
        schedule(70)                            # 拖动时按 70 ms 节流渲染
        return True

    def on_release(_area, _ev):
        if ctx["drag"]:
            ctx["drag"] = None
            render()
        return True

    def on_key(_w, ev):
        from gi.repository import Gdk
        if ev.keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            if 0 <= ctx["selected"] < len(ctx["pins"]):
                del ctx["pins"][ctx["selected"]]
                ctx["selected"] = -1
                schedule(0)
                return True
        return False

    def delete_selected(_b=None):
        if 0 <= ctx["selected"] < len(ctx["pins"]):
            del ctx["pins"][ctx["selected"]]
            ctx["selected"] = -1
            ctx["drag"] = None
        schedule(0)

    def clear_pins(_b=None):
        ctx["pins"] = []
        ctx["selected"] = -1
        ctx["drag"] = None
        schedule(0)

    area.connect("draw", draw)
    area.connect("button-press-event", on_press)
    area.connect("motion-notify-event", on_motion)
    area.connect("button-release-event", on_release)
    dlg.connect("key-press-event", on_key)
    b_del.connect("clicked", delete_selected)
    b_clear.connect("clicked", clear_pins)

    def sync_radius(*_a):
        """ARAP 没有影响半径，这一档把滑杆灰掉，免得拖了没反应。"""
        s_radius.set_sensitive(combo_mode.get_active_id() != MODE_ARAP)

    for widget in (combo_mode, combo_out):
        widget.connect("changed", lambda *_a: schedule(0))
    combo_mode.connect("changed", sync_radius)
    sync_radius()
    s_radius.connect("value-changed", lambda *_a: schedule(90))
    mesh.connect("toggled", lambda *_a: schedule(0))

    ctx["render"] = render
    ctx["values"] = values
    ctx["schedule"] = schedule
    render()
    outer.show_all()
    return dlg, ctx


def show_dialog(procedure, config, image, drawable, w, h):
    """弹窗。True = 应用（钉子/参数已写回 config）。"""
    try:
        dlg, ctx = build_dialog(config, image, drawable, w, h)
        from gi.repository import Gtk
    except Exception as exc:
        Gimp.message(_("This build of GIMP has no GTK — nothing to click on. "
                       "(%s). Pass pins through the pins argument instead: "
                       "sx,sy,dx,dy; …") % exc)
        return False

    resp = dlg.run()
    if ctx["id"]:
        GLib.source_remove(ctx["id"])
    if resp != Gtk.ResponseType.OK:
        dlg.destroy()
        return False

    v = ctx["values"]()
    config.set_property("pins", WM.format_pin_string(v["pins"]))
    config.set_property("mode", v["mode"])
    config.set_property("radius", float(v["radius"]))
    config.set_property("output", v["output"])
    dlg.destroy()
    return True


# ---- 过程注册 --------------------------------------------------------------

def _add_arguments(procedure):
    procedure.add_string_argument(
        "pins", _("Pins"),
        _("sx,sy,dx,dy; sx,sy,dx,dy — where each pin was placed and where it "
          "was dragged to, in layer pixels. Leave empty to place the pins by "
          "clicking on the picture (interactive run). This is what the dialog "
          "writes back, so a script can drive the warp without a mouse."),
        "", GObject.ParamFlags.READWRITE)
    mode = Gimp.Choice.new()
    mode.add(MODE_SIMILARITY, 0, _("Rigid (keeps shapes)"),
             _("MLS similarity: the local transform can only rotate, translate "
               "and scale uniformly, so corners stay square — this is the one "
               "that looks like Photoshop's puppet warp"))
    mode.add(MODE_AFFINE, 1, _("Free (allows stretching)"),
             _("Full MLS affine: the picture can also shear and stretch. "
               "Better for pulling something longer, worse on faces"))
    mode.add(MODE_ARAP, 2, _("ARAP (best at bending)"),
             _("As-rigid-as-possible on a mesh: every patch may only rotate "
               "and translate, so bending an arm does not squash it. The "
               "closest to Photoshop's behaviour on big bends. Needs numpy "
               "(run tools/install_gimp_numpy.py); Falloff is not used in this "
               "mode"))
    procedure.add_choice_argument(
        "mode", _("Deformation"), _("How the pixels between pins are solved"),
        mode, MODE_SIMILARITY, GObject.ParamFlags.READWRITE)
    procedure.add_double_argument(
        "radius", _("Falloff"),
        _("How far a pin reaches, as a percentage of the long edge. Outside "
          "that circle the picture is left untouched — byte for byte. Small "
          "values make it a local nudge, large values make the whole picture "
          "follow the pins"), 5.0, 100.0, 30.0, GObject.ParamFlags.READWRITE)
    output = Gimp.Choice.new()
    output.add(OUTPUT_FILTER, 0, _("Non-destructive filter"),
               _("Attach the warp as a live filter on the layer: the pixels "
                 "stay untouched and re-running the dialog reads the pins back "
                 "from the filter, so the warp can be re-edited or switched "
                 "off at any time. This is what the dialog picks by default"))
    output.add(OUTPUT_REPLACE, 1, _("Replace this layer"),
               _("Bake the warp into the current layer"))
    output.add(OUTPUT_LAYER, 2, _("Copy to a new layer"),
               _("Keep the original and put the warped copy above it"))
    procedure.add_choice_argument(
        "output", _("Output"), _("Where the warped pixels go"),
        output, OUTPUT_REPLACE, GObject.ParamFlags.READWRITE)


class PuppetWarpPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label(_("Puppet Warp"))
        procedure.set_documentation(
            _("Warp a layer by dragging pins: MLS deformation, editable pins, "
              "live preview"),
            _("Drop pins on the layer and drag them; the pixels between pins "
              "follow smoothly and the area outside the falloff stays "
              "untouched. Rigid mode keeps shapes, free mode allows stretch. "
              "The pins can also be passed as a string, so this works from a "
              "script."),
            name)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        _add_arguments(procedure)
        procedure.add_menu_path("<Image>/SuperMrWang/Distort")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        drawable = drawables[0]
        try:
            check_drawable(drawable)
            # 图层上已经挂着滤镜：把钉子读回来当默认值，弹窗里能接着改
            loaded = load_filter_state(drawable)
            if run_mode == Gimp.RunMode.INTERACTIVE:
                if loaded:
                    config.set_property('pins', loaded['pins'])
                    config.set_property('mode', loaded['mode'])
                    config.set_property('radius', loaded['radius'])
                    config.set_property('output', OUTPUT_FILTER)
                else:
                    # 全新一次交互：默认走非破坏（破坏性那两档仍在下拉里，
                    # 选一次就会记住，只是每次弹窗仍以滤镜为默认）
                    config.set_property('output', OUTPUT_FILTER)
                if not show_dialog(procedure, config, image, drawable,
                                   drawable.get_width(), drawable.get_height()):
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.CANCEL, None)
            pins = WM.parse_pin_string(config.get_property('pins') or "",
                                       drawable.get_width(),
                                       drawable.get_height())
            mode = config.get_property('mode') or MODE_SIMILARITY
            radius_pct = float(config.get_property('radius') or 30.0)
            output = config.get_property('output') or OUTPUT_REPLACE
            if output == OUTPUT_FILTER:
                # 别用下划线去接 apply_filter 的返回值：模块级 `_` 是翻译函数，
                # 在这里被绑成滤镜对象，下一行 _("…") 就会炸
                # 「'DrawableFilter' object is not callable」。
                _filt, layer = apply_filter(drawable, pins, mode=mode,
                                        radius=radius_pct)
                Gimp.message(_("Attached a live puppet-warp filter to “%s” — "
                               "%d pins. The pixels are untouched: adjust the "
                               "filter or run the dialog again to re-edit.")
                             % (layer.get_name(), len(pins)))
                return procedure.new_return_values(
                    Gimp.PDBStatusType.SUCCESS, GLib.Error())
            info = warp_drawable(
                drawable, pins,
                mode=mode,
                radius=radius_pct / 100.0,
                output=output,
                on_tick=Gimp.progress_pulse)
            Gimp.message(_("Warped %s in %.1f s — %d pins, max shift %.1f px.")
                         % (_fmt_size(info["size"][0], info["size"][1]),
                            info["seconds"], info["count"],
                            info["max_shift"]))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            import traceback      # 出错时把栈也打出来，否则只剩一句 str(exc)
            traceback.print_exc()
            Gimp.message("puppet-warp: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(PuppetWarpPlugin.__gtype__, _sys.argv)
