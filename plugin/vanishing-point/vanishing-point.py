#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 消失点（透视平面）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把 PS 的「滤镜 → 消失点」搬过来。在画面上拖出一个四边形，
           它就代表三维世界里的一块矩形：插件据此解出单应矩阵，铺一张
           向消失点收敛的透视网格，然后把图**透视贴**上去，或者把这块
           画面**拉正**成矩形。

           和另外两个变形工具的定位区分：
             木偶变形 = 放钉子拽内容（MLS/ARAP，局部）；
             自由变形 = 套一张贝塞尔网格（FFD，全局，带把手）；
             消失点   = 定义一块**有透视的平面**，贴图 / 拉正都靠它。

 menu      SuperMrWang → Distort → 消失点（透视平面）…

 usage     选图层 → 菜单 →
             · 在画面上拖出一个四边形（这是「平面」）；
             · 拖四个角把它调成贴着墙/地/桌面的透视形状；
             · 拖**边中点**小三角，从这条边再长出一块相邻平面
               （「垂直」= PS 的墙对墙，「延续」= 同一面墙接着铺）；
             · 勾上「做成台阶」：这块平面变成一组踏面/踢面，整张图沿
               台阶连续铺上去（PS 里那个「楼梯」效果）；
             · 右侧选「透视贴图」把图铺到平面上，或「拉正」把平面里
               那块画面展开成新图层。

 note      四条非踩不可的：
           1. **三个互垂方向的消失点，主点是三角形的垂心**。知道平面
              自己的两个消失点，第三方向（垂直那面墙）不用相机内参就
              能算出来。把「垂直消失点」当成「另一组边的交点」会得到
              同一个点，墙会贴到墙自己身上。
           2. **网格线要按齐次分母的符号断开**。世界坐标往远处延伸时
              w 会过零，越过零点那一段是地平线之后的像，和前面连起来
              会画出一条横穿画面的假线。
           3. **延伸平面的两个远角不能取同一个 t**。都取 p + t·(V−p)
              会让新平面两条边严格平行，u 方向消失点跑到 1e16 外——
              等于把透视扔了。q1 必须由「落在 p1 的射线上」和
              「q0q1 过共享边方向的消失点」两条约束解出来。
           4. **台阶要真三维，不能拼四边形。** 一块平面的四角就能定出整台
              相机（f² = −(Vu−O)·(Vv−O)，见 _shared/scene3d.py），有了相机
              才能把「抬高 0.12 个边长」投到正确的位置。拿平面里的
              「按法向平移」凑台阶，越往上级差得越远。

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

import perspective as PERSP            # noqa: E402
import scene3d as S3D                  # noqa: E402
import mask_io as MI                   # noqa: E402

PROC = 'lb-plugin-vanishing-point'
# 预览长边。透视贴图只算平面外接框那一块，比自由变形（整幅重采样）便宜，
# 560 长边大约 40–80 ms。
PREVIEW_EDGE = 560
CORNER_HIT = 11       # 角点点击半径（画布像素）
EDGE_HIT = 10         # 边中点小三角的点击半径
MODE_PASTE = 'paste'
MODE_RECTIFY = 'rectify'
OUTPUT_REPLACE = 'replace'
OUTPUT_LAYER = 'new-layer'
ALONG_W = 'w'
ALONG_V = 'v'


# ---- 本体 ------------------------------------------------------------------

def _write_rgba(layer, w, h, rgba):
    """写回图层。没有 alpha 的图层退回 3 通道，否则 buf.set 格式不匹配。"""
    if len(rgba) != w * h * 4:
        raise RuntimeError(_("Pixel buffer size mismatch: %d bytes for %d×%d")
                           % (len(rgba), w, h))
    if layer.has_alpha():
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
    if drawable is None:
        raise RuntimeError(_("Nothing is selected. Pick a pixel layer first."))
    if not drawable.is_layer():
        raise RuntimeError(_("That is not a layer. Select a normal pixel layer "
                             "first."))
    if drawable.is_group():
        raise RuntimeError(_(
            "That is a layer group. Pick a single layer inside it — a group "
            "has no pixels of its own."))
    if drawable.is_text_layer() or drawable.is_vector_layer():
        raise RuntimeError(_(
            "That is a text/vector layer. Rasterise it first, otherwise there "
            "are no pixels to work with."))
    if drawable.get_width() < 8 or drawable.get_height() < 8:
        raise RuntimeError(_("The layer is %d×%d — too small.")
                           % (drawable.get_width(), drawable.get_height()))


def _tick_wrap(on_tick):
    if not on_tick:
        return None
    # warp/paste 的回调每行调一次 progress(0..1)，Gimp.progress_pulse 不收参数
    return lambda _frac: on_tick()


def apply_planes(drawable, planes, mode=MODE_PASTE, output=OUTPUT_REPLACE,
                 stairs=None, on_tick=None):
    """按第一个平面干活。返回 info 字典。"""
    image = drawable.get_image()
    w, h = drawable.get_width(), drawable.get_height()
    t0 = time.time()
    if not planes:
        raise RuntimeError(_("No plane yet — drag a quadrilateral over the "
                             "picture first (or pass one in the planes "
                             "argument)."))
    plane = planes[0]
    if not plane.is_valid():
        raise RuntimeError(_(
            "That quadrilateral is too small or has a concave corner — drag "
            "its corners into a proper convex shape."))

    pw, ph, rgba = MI.read_drawable_rgba(drawable, max(w, h))
    if (pw, ph) != (w, h):
        raise RuntimeError(_("Read the layer at the wrong size: %d×%d, "
                             "expected %d×%d") % (pw, ph, w, h))

    tick = _tick_wrap(on_tick)
    stair_info = None
    if mode == MODE_RECTIFY:
        ow, oh = PERSP.rectify_size(plane.corners)
        if on_tick:
            Gimp.progress_set_text(_("Rectifying %d×%d…") % (ow, oh))
        out = PERSP.rectify(rgba, w, h, plane.corners, ow, oh, progress=tick)
        layer = Gimp.Layer.new(image, drawable.get_name() + _(" (rectified)"),
                               ow, oh, Gimp.ImageType.RGBA_IMAGE, 100,
                               Gimp.LayerMode.NORMAL)
        image.insert_layer(layer, None, image.get_item_position(drawable))
        layer.get_buffer().set(Gegl.Rectangle.new(0, 0, ow, oh),
                               "R'G'B'A u8", out)
        # 摆到平面质心上，和原图对得上位置
        gx, gy = plane.centroid()
        layer.set_offsets(int(round(gx - ow * 0.5)), int(round(gy - oh * 0.5)))
        size = (ow, oh)
    else:
        if stairs and stairs.get("on"):
            if on_tick:
                Gimp.progress_set_text(_("Folding the picture over the "
                                         "steps…"))
            faces, stair_info = S3D.stair_faces(
                plane, w, h, steps=stairs.get("steps", 6),
                rise=stairs.get("rise", 0.12), run=stairs.get("run", 0.0),
                edge=stairs.get("edge", 0), flip=stairs.get("flip", False))
            if not faces:
                raise RuntimeError(_(
                    "This quadrilateral cannot be read as a plane (%s) — drag "
                    "its corners into a convex quad with some perspective.")
                    % (stair_info.get("reason") or "?"))
            out = S3D.paste_faces(rgba, w, h, rgba, w, h, faces,
                                  stair_info["total_v"], mix=True,
                                  progress=tick)
        else:
            if on_tick:
                Gimp.progress_set_text(_("Pasting into the plane…"))
            out = PERSP.paste_into(rgba, w, h, rgba, w, h, plane.corners,
                                   mix=True, progress=tick)
        if output == OUTPUT_LAYER:
            layer = drawable.copy()
            layer.set_name(drawable.get_name() + _(" (vanishing point)"))
            image.insert_layer(layer, None, image.get_item_position(drawable))
        else:
            layer = drawable
        _write_rgba(layer, w, h, out)
        size = (w, h)

    Vu, Vv = plane.vanish_uv()
    Vw = plane.vanish_w(w, h)
    return {"seconds": time.time() - t0, "size": size, "layer": layer,
            "vanish": (Vu, Vv, Vw), "mode": mode, "stairs": stair_info,
            "rectified": PERSP.rectify_size(plane.corners)}


# ---- 对话框 ----------------------------------------------------------------

def _fmt_size(w, h):
    return "%d×%d" % (w, h)


def _cfg_str(config, name):
    """读字符串属性。老版本的过程没有这个参数时返回空串，别让对话框炸掉。"""
    try:
        return config.get_property(name) or ""
    except Exception:
        return ""


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


def scale_plane(plane, f):
    """整体缩放（图层坐标 ↔ 预览坐标）。"""
    return PERSP.Plane([[c[0] * f, c[1] * f] for c in plane.corners])


def build_dialog(config, image, drawable, w, h):
    """建对话框，返回 (dlg, ctx)。故意不 run()：无头回归可以直接调
    ctx["render"]() / ctx["add_plane"]() / ctx["extend_from"]()。"""
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk

    pw, ph, prgba = MI.read_drawable_rgba(drawable, PREVIEW_EDGE)
    k = float(w) / max(pw, 1)

    dlg = Gtk.Dialog.new()
    dlg.set_title(_("Vanishing Point (Perspective Planes)"))
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
    hint = Gtk.Label.new(_("Drag on empty space to make a plane · drag its "
                           "corners to fit the perspective · drag the little "
                           "triangle on an edge to grow a neighbouring plane "
                           "· right-click a plane to delete it"))
    hint.set_xalign(0.0)
    hint.set_line_wrap(True)
    hint.set_max_width_chars(48)
    left.add(hint)
    outer.add(left)

    right = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
    right.set_size_request(258, -1)
    outer.add(right)

    title = Gtk.Label.new("")
    title.set_xalign(0.0)
    title.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("Plane")))
    right.add(title)

    planes0 = PERSP.parse_plane_string(config.get_property('planes') or "", w, h)
    if not planes0:
        planes0 = [PERSP.default_quad(w, h)]

    mode_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    mode_lbl = Gtk.Label.new(_("Mode"))
    mode_lbl.set_xalign(0.0)
    mode_lbl.set_size_request(92, -1)
    combo_mode = Gtk.ComboBoxText.new()
    combo_mode.append(MODE_PASTE, _("Paste the picture into the plane"))
    combo_mode.append(MODE_RECTIFY, _("Rectify the plane to a flat layer"))
    combo_mode.set_active_id(config.get_property('mode') or MODE_PASTE)
    combo_mode.set_hexpand(True)
    mode_row.add(mode_lbl)
    mode_row.add(combo_mode)
    right.add(mode_row)

    along_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    along_lbl = Gtk.Label.new(_("Grow"))
    along_lbl.set_xalign(0.0)
    along_lbl.set_size_request(92, -1)
    combo_along = Gtk.ComboBoxText.new()
    combo_along.append(ALONG_W, _("Perpendicular (a wall next to this one)"))
    combo_along.append(ALONG_V, _("In the same plane"))
    combo_along.set_active_id(config.get_property('along') or ALONG_W)
    combo_along.set_hexpand(True)
    along_row.add(along_lbl)
    along_row.add(combo_along)
    right.add(along_row)

    steps_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    steps_lbl = Gtk.Label.new(_("Grid"))
    steps_lbl.set_xalign(0.0)
    steps_lbl.set_size_request(92, -1)
    spin_steps = Gtk.SpinButton.new_with_range(2, 10, 1)
    spin_steps.set_value(4)
    spin_steps.set_hexpand(True)
    steps_row.add(steps_lbl)
    steps_row.add(spin_steps)
    right.add(steps_row)

    show_grid = Gtk.CheckButton.new_with_label(_("Show the perspective grid"))
    show_grid.set_active(True)
    right.add(show_grid)
    show_vanish = Gtk.CheckButton.new_with_label(_("Mark the vanishing points"))
    show_vanish.set_active(True)
    right.add(show_vanish)

    # -- 台阶 ----------------------------------------------------------
    stair_frame = Gtk.Frame.new()
    sbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
    sbox.set_border_width(6)
    stair_frame.add(sbox)
    chk_stair = Gtk.CheckButton.new_with_label(_("Fold this plane into stairs"))
    sbox.add(chk_stair)
    sgrid = Gtk.Grid.new()
    sgrid.set_row_spacing(3)
    sgrid.set_column_spacing(6)
    combo_edge = Gtk.ComboBoxText.new()
    combo_edge.append("2", _("from the far edge"))
    combo_edge.append("0", _("from the near edge"))
    combo_edge.append("1", _("from the right edge"))
    combo_edge.append("3", _("from the left edge"))
    combo_edge.set_active_id("2")
    spin_n = Gtk.SpinButton.new_with_range(1, 24, 1)
    spin_n.set_value(6)
    spin_rise = Gtk.SpinButton.new_with_range(0.01, 1.0, 0.01)
    spin_rise.set_value(0.10)
    spin_rise.set_digits(2)
    spin_run = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.01)
    spin_run.set_value(0.0)
    spin_run.set_digits(2)
    chk_flip = Gtk.CheckButton.new_with_label(_("flip"))
    for row, (lbl, wdg) in enumerate((
            (_("Starts"), combo_edge),
            (_("Steps"), spin_n),
            (_("Rise"), spin_rise),
            (_("Run"), spin_run))):
        l = Gtk.Label.new(lbl)
        l.set_xalign(0.0)
        sgrid.attach(l, 0, row, 1, 1)
        wdg.set_hexpand(True)
        sgrid.attach(wdg, 1, row, 1, 1)
    sgrid.attach(chk_flip, 0, 4, 2, 1)
    sbox.add(sgrid)
    stair_note = Gtk.Label.new(_("Run 0 = fill the plane. Stairs need a "
                                "camera, so the quad must have perspective."))
    stair_note.set_line_wrap(True)
    stair_note.set_xalign(0.0)
    stair_note.set_max_width_chars(30)
    sbox.add(stair_note)
    right.add(stair_frame)

    st0 = S3D.parse_stair_string(_cfg_str(config, 'stairs'))
    chk_stair.set_active(bool(st0.get("on")))
    combo_edge.set_active_id(str(st0.get("edge", 2)))
    spin_n.set_value(st0.get("steps", 6))
    spin_rise.set_value(st0.get("rise", 0.10))
    spin_run.set_value(st0.get("run", 0.0))
    chk_flip.set_active(bool(st0.get("flip")))

    out_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    out_lbl = Gtk.Label.new(_("Output"))
    out_lbl.set_xalign(0.0)
    out_lbl.set_size_request(92, -1)
    combo_out = Gtk.ComboBoxText.new()
    combo_out.append(OUTPUT_REPLACE, _("Replace this layer"))
    combo_out.append(OUTPUT_LAYER, _("Copy to a new layer"))
    combo_out.set_active_id(config.get_property('output') or OUTPUT_REPLACE)
    combo_out.set_hexpand(True)
    out_row.add(out_lbl)
    out_row.add(combo_out)
    right.add(out_row)

    btn_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 6)
    b_new = Gtk.Button.new_with_label(_("New plane"))
    b_del = Gtk.Button.new_with_label(_("Delete plane"))
    btn_row.add(b_new)
    btn_row.add(b_del)
    right.add(btn_row)

    note = Gtk.Label.new("")
    note.set_line_wrap(True)
    note.set_xalign(0.0)
    right.add(note)

    ctx = {
        "planes": planes0,
        "sel": 0,
        "drag": None,
        "ext_src": None,          # (plane, side)：边中点拖动时的源
        "prgba": prgba, "pw": pw, "ph": ph, "k": k, "w": w, "h": h,
        "preview": prgba, "id": 0, "lines": [], "vpoints": None,
        "faces": [], "sinfo": None,
        "area": area, "note": note, "dialog": dlg,
    }

    def values():
        return {
            "planes": [p.copy() for p in ctx["planes"]],
            "mode": combo_mode.get_active_id() or MODE_PASTE,
            "along": combo_along.get_active_id() or ALONG_W,
            "output": combo_out.get_active_id() or OUTPUT_REPLACE,
            "steps": int(spin_steps.get_value()),
            "show_grid": bool(show_grid.get_active()),
            "show_vanish": bool(show_vanish.get_active()),
            "stairs": {
                "on": bool(chk_stair.get_active()),
                "edge": int(combo_edge.get_active_id() or 2),
                "steps": int(spin_n.get_value()),
                "rise": float(spin_rise.get_value()),
                "run": float(spin_run.get_value()),
                "flip": bool(chk_flip.get_active()),
            },
        }

    def _sel_plane():
        i = ctx["sel"]
        if 0 <= i < len(ctx["planes"]):
            return ctx["planes"][i]
        return None

    def render():
        ctx["id"] = 0
        v = values()
        t0 = time.time()
        sp = _sel_plane()
        try:
            if sp is None:
                ctx["preview"] = prgba
                ctx["lines"] = []
                ctx["vpoints"] = None
                note.set_text(_("No plane — drag on the picture to make one."))
            else:
                pv = scale_plane(sp, 1.0 / k)
                st = v["stairs"]
                ctx["faces"] = []
                ctx["sinfo"] = None
                if v["mode"] == MODE_PASTE and pv.is_valid():
                    if st["on"]:
                        faces, sinfo = S3D.stair_faces(
                            pv, pw, ph, steps=st["steps"],
                            rise=st["rise"], run=st["run"],
                            edge=st["edge"], flip=st["flip"])
                        ctx["faces"] = faces
                        ctx["sinfo"] = sinfo
                        ctx["preview"] = (
                            S3D.paste_faces(prgba, pw, ph, prgba, pw, ph,
                                            faces, sinfo["total_v"], mix=True)
                            if faces else prgba)
                    else:
                        ctx["preview"] = PERSP.paste_into(
                            prgba, pw, ph, prgba, pw, ph, pv.corners, mix=True)
                else:
                    ctx["preview"] = prgba
                ctx["lines"] = ([] if st["on"] else
                                (pv.grid_lines(steps=v["steps"], reach=1.1)
                                 if v["show_grid"] else []))
                Vu, Vv = pv.vanish_uv()
                Vw = pv.vanish_w(pw, ph)
                ctx["vpoints"] = (Vu, Vv, Vw)
                ow, oh = PERSP.rectify_size(sp.corners)
                pct = ""
                if v["mode"] == MODE_RECTIFY:
                    pct = _(" · rectified %s") % _fmt_size(ow, oh)
                note.set_text(_("plane %d of %d · %d×%d px · grid %d%s\n"
                                "preview %s of %s · %.0f ms") % (
                    ctx["sel"] + 1, len(ctx["planes"]),
                    int(sp.corners[1][0] - sp.corners[0][0]),
                    int(sp.corners[3][1] - sp.corners[0][1]),
                    v["steps"], pct, _fmt_size(pw, ph), _fmt_size(w, h),
                    (time.time() - t0) * 1000.0))
                if st["on"]:
                    si = ctx.get("sinfo") or {}
                    cam = si.get("cam")
                    if ctx.get("faces") and cam is not None:
                        tag = ""
                        if cam.approx:
                            tag = _(" (approximate — this quad has no "
                                    "perspective, so the steps may look flat)")
                        note.set_text(note.get_text() + "\n" + _(
                            "stairs %d × rise %.2f · run %.2f · unfolded %.2f"
                            "\nfocal ≈ %d%s") % (
                            si["steps"], si["rise"], si["run"], si["total_v"],
                            int(round(cam.f)), tag))
                    else:
                        note.set_text(note.get_text() + "\n" + _(
                            "No camera from this quad — make it a trapezoid "
                            "(one edge nearer than the other)."))
        except Exception as exc:
            note.set_text(_("Preview failed: %s") % exc)
        area.queue_draw()
        return False

    def schedule(delay=60):
        if ctx["id"]:
            GLib.source_remove(ctx["id"])
        ctx["id"] = GLib.timeout_add(delay, render)

    # -- 画 ----------------------------------------------------------------
    def draw(_area, cr):
        _checker(cr, _area.get_allocated_width(), _area.get_allocated_height())
        try:
            pix = _pixbuf_from_rgba(ctx["preview"], pw, ph)
            Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
            cr.paint()
        except Exception:
            pass

        # 未选中的平面：细轮廓
        for idx, p in enumerate(ctx["planes"]):
            if idx == ctx["sel"]:
                continue
            pv = scale_plane(p, 1.0 / k)
            cr.set_line_width(1.0)
            cr.set_source_rgba(0.30, 0.72, 1.0, 0.45)
            c = pv.corners
            cr.move_to(c[0][0], c[0][1])
            for q in c[1:] + [c[0]]:
                cr.line_to(q[0], q[1])
            cr.stroke()

        sp = _sel_plane()
        if sp is not None:
            pv = scale_plane(sp, 1.0 / k)
            # 网格
            if ctx["lines"]:
                cr.set_line_width(1.2)
                cr.set_source_rgba(0.15, 0.70, 1.0, 0.72)
                for line in ctx["lines"]:
                    cr.move_to(line[0][0], line[0][1])
                    for px, py in line[1:]:
                        cr.line_to(px, py)
                    cr.stroke()
            # 台阶面片：踏面亮黄、踢面暗一点，一眼看出哪块是立起来的
            for fc in (ctx.get("faces") or []):
                cr.set_line_width(1.3)
                if fc.kind == "riser":
                    cr.set_source_rgba(1.0, 0.55, 0.15, 0.70)
                else:
                    cr.set_source_rgba(1.0, 0.85, 0.35, 0.80)
                q = fc.quad
                cr.move_to(q[0][0], q[0][1])
                for pt in q[1:]:
                    cr.line_to(pt[0], pt[1])
                cr.close_path()
                cr.stroke()
            # 边框
            cr.set_line_width(1.8)
            cr.set_source_rgba(1.0, 0.62, 0.12, 0.95)
            c = pv.corners
            cr.move_to(c[0][0], c[0][1])
            for q in c[1:] + [c[0]]:
                cr.line_to(q[0], q[1])
            cr.stroke()

            # 消失点
            if ctx["vpoints"] and ctx["vpoints"]:
                for vp, col in zip(ctx["vpoints"],
                                   ((1.0, 0.35, 0.30), (0.35, 1.0, 0.45),
                                    (0.55, 0.45, 1.0))):
                    if vp is None:
                        continue
                    if not (abs(vp[0]) < 1e6 and abs(vp[1]) < 1e6):
                        continue
                    if not (-4000 < vp[0] < pw + 4000 and
                            -4000 < vp[1] < ph + 4000):
                        continue
                    cr.set_line_width(1.2)
                    cr.set_source_rgba(col[0], col[1], col[2], 0.85)
                    cr.arc(vp[0], vp[1], 5.0, 0, 2 * _math.pi)
                    cr.stroke()
                    cr.move_to(vp[0] - 9, vp[1])
                    cr.line_to(vp[0] + 9, vp[1])
                    cr.move_to(vp[0], vp[1] - 9)
                    cr.line_to(vp[0], vp[1] + 9)
                    cr.stroke()

            # 边中点小三角（拖它长出新平面）
            for side in range(4):
                mx, my = pv.edge_mid(side)
                a, b = pv.edge(side)
                dx, dy = b[0] - a[0], b[1] - a[1]
                ln = _math.hypot(dx, dy) or 1.0
                nx, ny = dy / ln, -dx / ln
                gx, gy = pv.centroid()
                if (mx + nx - gx) ** 2 + (my + ny - gy) ** 2 < \
                   (mx - nx - gx) ** 2 + (my - ny - gy) ** 2:
                    nx, ny = -nx, -ny
                cr.set_source_rgba(1.0, 0.55, 0.10, 0.9)
                cr.move_to(mx + nx * 8, my + ny * 8)
                cr.line_to(mx - ny * 5, my + nx * 5)
                cr.line_to(mx + ny * 5, my - nx * 5)
                cr.close_path()
                cr.fill()

            # 角点
            for idx, q in enumerate(c):
                cr.set_source_rgba(1.0, 0.92, 0.30, 0.98)
                cr.rectangle(q[0] - 4, q[1] - 4, 8, 8)
                cr.fill_preserve()
                cr.set_line_width(1.2)
                cr.set_source_rgba(0.05, 0.05, 0.05, 0.8)
                cr.stroke()

        if not ctx["planes"]:
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.65)
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(15)
            cr.move_to(14, ph - 18)
            cr.show_text(_("Drag a quadrilateral to start a plane"))

    # -- 命中 --------------------------------------------------------------
    def hit_corner(x, y):
        sp = _sel_plane()
        if sp is None:
            return -1
        pv = scale_plane(sp, 1.0 / k)
        best, best_d = -1, CORNER_HIT ** 2
        for idx, q in enumerate(pv.corners):
            d = (q[0] - x) ** 2 + (q[1] - y) ** 2
            if d <= best_d:
                best, best_d = idx, d
        return best

    def hit_edge_mid(x, y):
        sp = _sel_plane()
        if sp is None:
            return -1
        pv = scale_plane(sp, 1.0 / k)
        best, best_d = -1, EDGE_HIT ** 2
        for side in range(4):
            mx, my = pv.edge_mid(side)
            d = (mx - x) ** 2 + (my - y) ** 2
            if d <= best_d:
                best, best_d = side, d
        return best

    def hit_plane(x, y):
        """点在哪个平面里（从后往前，后建的在上）。"""
        for idx in range(len(ctx["planes"]) - 1, -1, -1):
            if ctx["planes"][idx].contains(x * k, y * k):
                return idx
        return -1

    # -- 交互 --------------------------------------------------------------
    def add_plane(cx0, cy0, cx1, cy1):
        """画布坐标下拖出的矩形 → 新平面（图层坐标）。"""
        x0 = min(cx0, cx1) * k
        x1 = max(cx0, cx1) * k
        y0 = min(cy0, cy1) * k
        y1 = max(cy0, cy1) * k
        if (x1 - x0) < 8 or (y1 - y0) < 8:
            return -1
        p = PERSP.Plane([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
        ctx["planes"].append(p)
        ctx["sel"] = len(ctx["planes"]) - 1
        return ctx["sel"]

    def set_corner(idx, cx, cy):
        """把当前平面的第 idx 个角移到画布坐标。"""
        sp = _sel_plane()
        if sp is None:
            return
        sp.move_corner(idx, min(max(cx * k, 0.0), w - 1.0),
                       min(max(cy * k, 0.0), h - 1.0))

    def extend_from(side, cx, cy):
        """从第 side 条边长出一块新平面，拖动量决定它有多深。

        amount 用「鼠标离这条边有多远 / 边长」来量，所以拖得越远墙越深。
        """
        src = ctx["ext_src"]
        if src is None:
            return
        base, side = src
        pv = scale_plane(base, 1.0 / k)
        a, b = pv.edge(side)
        mx, my = pv.edge_mid(side)
        dx, dy = b[0] - a[0], b[1] - a[1]
        chord = _math.hypot(dx, dy) or 1.0
        nx, ny = dy / chord, -dx / chord
        gx, gy = pv.centroid()
        if (mx + nx - gx) ** 2 + (my + ny - gy) ** 2 < \
           (mx - nx - gx) ** 2 + (my - ny - gy) ** 2:
            nx, ny = -nx, -ny
        dist = abs((cx - mx) * nx + (cy - my) * ny)
        amount = min(max(dist / chord, 0.08), 2.0)
        newp = base.extend(side, along=(combo_along.get_active_id() or ALONG_W),
                           amount=amount, w=w, h=h)
        if 0 <= ctx["sel"] < len(ctx["planes"]):
            ctx["planes"][ctx["sel"]] = newp
        else:
            ctx["planes"].append(newp)
            ctx["sel"] = len(ctx["planes"]) - 1

    def on_press(_area, ev):
        x, y = ev.x, ev.y
        if ev.button == 3:
            idx = hit_plane(x, y)
            if idx >= 0:
                ctx["planes"].pop(idx)
                ctx["sel"] = min(idx, len(ctx["planes"]) - 1)
                schedule(0)
            return True
        if ev.button != 1:
            return False
        area.grab_focus()
        ci = hit_corner(x, y)
        if ci >= 0:
            ctx["drag"] = ("corner", ci)
            schedule(0)
            return True
        ei = hit_edge_mid(x, y)
        if ei >= 0:
            sp = _sel_plane()
            if sp is not None:
                ctx["ext_src"] = (sp.copy(), ei)
                ctx["drag"] = ("edge", ei)
                schedule(0)
            return True
        idx = hit_plane(x, y)
        if idx >= 0:
            ctx["sel"] = idx
            ctx["drag"] = ("move", idx)
            ctx["move_from"] = (x, y, [list(c) for c in ctx["planes"][idx].corners])
            schedule(0)
            return True
        # 空白：拖出一个新平面
        ctx["sel"] = -1
        ctx["drag"] = ("new", x, y)
        schedule(0)
        return True

    def on_motion(_area, ev):
        drag = ctx["drag"]
        if not drag:
            return False
        kind = drag[0]
        if kind == "corner":
            set_corner(drag[1], ev.x, ev.y)
        elif kind == "edge":
            extend_from(drag[1], ev.x, ev.y)
        elif kind == "move":
            fx, fy, base = ctx["move_from"]
            p = ctx["planes"][drag[1]]
            dx = (ev.x - fx) * k
            dy = (ev.y - fy) * k
            for i in range(4):
                p.corners[i][0] = min(max(base[i][0] + dx, 0.0), w - 1.0)
                p.corners[i][1] = min(max(base[i][1] + dy, 0.0), h - 1.0)
            p.invalidate()
        elif kind == "new":
            x0, y0 = drag[1], drag[2]
            if ctx["sel"] < 0 or len(ctx["planes"]) <= ctx["sel"]:
                add_plane(x0, y0, ev.x, ev.y)
            else:
                p = ctx["planes"][ctx["sel"]]
                p.corners = [[min(x0, ev.x) * k, min(y0, ev.y) * k],
                             [max(x0, ev.x) * k, min(y0, ev.y) * k],
                             [max(x0, ev.x) * k, max(y0, ev.y) * k],
                             [min(x0, ev.x) * k, max(y0, ev.y) * k]]
                p.invalidate()
        schedule(60)
        return True

    def on_release(_area, _ev):
        if ctx["drag"]:
            kind = ctx["drag"][0]
            ctx["drag"] = None
            ctx["ext_src"] = None
            if kind == "new":
                sp = _sel_plane()
                # 拖得太小就当没建
                if sp is not None:
                    xs = [c[0] for c in sp.corners]
                    ys = [c[1] for c in sp.corners]
                    if (max(xs) - min(xs)) < 10 or (max(ys) - min(ys)) < 10:
                        ctx["planes"].pop(ctx["sel"])
                        ctx["sel"] = len(ctx["planes"]) - 1
            render()
        return True

    def on_key(_w, ev):
        if ev.keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            if 0 <= ctx["sel"] < len(ctx["planes"]):
                ctx["planes"].pop(ctx["sel"])
                ctx["sel"] = min(ctx["sel"], len(ctx["planes"]) - 1)
                schedule(0)
            return True
        if ev.keyval == Gdk.KEY_Escape and ctx["drag"]:
            ctx["drag"] = None
            return True
        return False

    def new_plane(_b=None):
        # 摆一个居中、稍微带点透视的默认平面，省得用户从零拖
        q = PERSP.default_quad(w, h)
        ctx["planes"].append(q)
        ctx["sel"] = len(ctx["planes"]) - 1
        schedule(0)

    def del_plane(_b=None):
        if 0 <= ctx["sel"] < len(ctx["planes"]):
            ctx["planes"].pop(ctx["sel"])
            ctx["sel"] = min(ctx["sel"], len(ctx["planes"]) - 1)
            schedule(0)

    area.connect("draw", draw)
    area.connect("button-press-event", on_press)
    area.connect("motion-notify-event", on_motion)
    area.connect("button-release-event", on_release)
    dlg.connect("key-press-event", on_key)
    b_new.connect("clicked", new_plane)
    b_del.connect("clicked", del_plane)
    combo_mode.connect("changed", lambda *_a: schedule(0))
    combo_along.connect("changed", lambda *_a: schedule(0))
    spin_steps.connect("value-changed", lambda *_a: schedule(0))
    show_grid.connect("toggled", lambda *_a: schedule(0))
    show_vanish.connect("toggled", lambda *_a: schedule(0))
    chk_stair.connect("toggled", lambda *_a: schedule(0))
    combo_edge.connect("changed", lambda *_a: schedule(0))
    spin_n.connect("value-changed", lambda *_a: schedule(0))
    spin_rise.connect("value-changed", lambda *_a: schedule(0))
    spin_run.connect("value-changed", lambda *_a: schedule(0))
    chk_flip.connect("toggled", lambda *_a: schedule(0))

    ctx["render"] = render
    ctx["values"] = values
    ctx["schedule"] = schedule
    ctx["hit_corner"] = hit_corner
    ctx["hit_edge_mid"] = hit_edge_mid
    ctx["hit_plane"] = hit_plane
    ctx["add_plane"] = add_plane
    ctx["set_corner"] = set_corner
    ctx["extend_from"] = extend_from
    ctx["new_plane"] = new_plane
    ctx["del_plane"] = del_plane
    ctx["scale_plane"] = scale_plane
    render()
    outer.show_all()
    return dlg, ctx


def show_dialog(procedure, config, image, drawable, w, h):
    """弹窗。True = 应用（平面/模式/输出已写回 config）。"""
    try:
        dlg, ctx = build_dialog(config, image, drawable, w, h)
        from gi.repository import Gtk
    except Exception as exc:
        Gimp.message(_("This build of GIMP has no GTK — nothing to click on. "
                       "(%s). Pass the plane through the planes argument "
                       "instead: \"x0,y0,x1,y1,x2,y2,x3,y3\".") % exc)
        return False

    resp = dlg.run()
    if ctx["id"]:
        GLib.source_remove(ctx["id"])
    if resp != Gtk.ResponseType.OK:
        dlg.destroy()
        return False

    v = ctx["values"]()
    config.set_property("planes", PERSP.format_plane_string(v["planes"]))
    config.set_property("mode", v["mode"])
    config.set_property("along", v["along"])
    config.set_property("output", v["output"])
    config.set_property("stairs", S3D.format_stair_string(
        v["stairs"] if v["stairs"].get("on") else None))
    dlg.destroy()
    return True


# ---- 过程注册 --------------------------------------------------------------

def _add_arguments(procedure):
    procedure.add_string_argument(
        "planes", _("Planes"),
        _("One or more quadrilaterals separated by “|”, each as "
          "x0,y0,x1,y1,x2,y2,x3,y3 (corners in layer pixels, in order "
          "top-left, top-right, bottom-right, bottom-left). The FIRST plane "
          "is the one used; the rest are kept so a dialog session can be "
          "replayed. Better: leave it empty and drag a quadrilateral in the "
          "dialog."),
        "", GObject.ParamFlags.READWRITE)
    mode = Gimp.Choice.new()
    mode.add(MODE_PASTE, 0, _("Paste the picture into the plane"),
             _("Put the whole layer into the plane, perspective-matching the "
               "quadrilateral; pixels outside stay untouched"))
    mode.add(MODE_RECTIFY, 1, _("Rectify the plane to a flat layer"),
             _("Undo the perspective: the quadrilateral becomes a rectangular "
               "new layer"))
    procedure.add_choice_argument(
        "mode", _("Mode"), _("What to do with the plane"), mode, MODE_PASTE,
        GObject.ParamFlags.READWRITE)
    along = Gimp.Choice.new()
    along.add(ALONG_W, 0, _("Perpendicular"),
              _("The next plane is perpendicular to this one (a wall next to "
                "this wall)"))
    along.add(ALONG_V, 1, _("In the same plane"),
              _("The next plane continues this one (same wall, further on)"))
    procedure.add_choice_argument(
        "along", _("Grow"), _("Which way a plane grown from an edge goes"),
        along, ALONG_W, GObject.ParamFlags.READWRITE)
    procedure.add_string_argument(
        "stairs", _("Stairs"),
        _("Fold the plane into a staircase: \"edge,steps,rise,run,flip\" "
          "(edge 0..3 = which side the steps start from, rise/run in plane "
          "side lengths, 0 run = fill the plane). Empty = plain plane. The "
          "picture is then wrapped over the steps continuously instead of "
          "being pasted flat."),
        "", GObject.ParamFlags.READWRITE)
    output = Gimp.Choice.new()
    output.add(OUTPUT_REPLACE, 0, _("Replace this layer"),
               _("Bake the result into the current layer"))
    output.add(OUTPUT_LAYER, 1, _("Copy to a new layer"),
               _("Keep the original and put the result above it"))
    procedure.add_choice_argument(
        "output", _("Output"), _("Where the pixels go"), output,
        OUTPUT_REPLACE, GObject.ParamFlags.READWRITE)


class VanishingPointPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label(_("Vanishing Point (Perspective)"))
        procedure.set_documentation(
            _("Define a perspective plane on the picture, then paste into it "
              "or rectify it back to a flat rectangle"),
            _("Three mutually perpendicular directions have their vanishing "
              "points at the corners of a triangle whose orthocentre is the "
              "principal point — so a second, perpendicular plane can be "
              "derived from the first without any camera calibration. The "
              "grid you see is drawn by projecting evenly spaced world lines, "
              "which is why it converges to those points."),
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
            w, h = drawable.get_width(), drawable.get_height()
            if run_mode == Gimp.RunMode.INTERACTIVE:
                if not show_dialog(procedure, config, image, drawable, w, h):
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.CANCEL, None)
            planes = PERSP.parse_plane_string(
                config.get_property('planes') or "", w, h)
            if not planes:
                raise RuntimeError(_("No plane given — drag one in the dialog "
                                     "or pass the planes argument."))
            info = apply_planes(
                drawable, planes,
                mode=config.get_property('mode') or MODE_PASTE,
                output=config.get_property('output') or OUTPUT_REPLACE,
                stairs=S3D.parse_stair_string(_cfg_str(config, 'stairs')),
                on_tick=Gimp.progress_pulse)
            Vu, Vv, Vw = info["vanish"]
            if info["mode"] == MODE_RECTIFY:
                what = _("rectified to %s") % _fmt_size(*info["size"])
            elif info.get("stairs"):
                what = _("folded into %d steps") % info["stairs"]["steps"]
            else:
                what = _("pasted into a %s plane") % _fmt_size(*info["size"])
            Gimp.message(_("Done in %.1f s — %s.") % (info["seconds"], what))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("vanishing-point: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(VanishingPointPlugin.__gtype__, _sys.argv)
