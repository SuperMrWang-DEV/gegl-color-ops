#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 自由变形（贝塞尔网格 + 把手）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把 PS 的「编辑 → 变换 → 变形」搬过来：图层上盖一张网格，
           拖交点改变形状；选中一个交点会出现四个小圆点——**把手**，
           拖把手可以把网格线弯成曲线，于是画面能做出鼓起来、凹下去、
           翻边这类直线网格做不到的形状。

           和「木偶变形」不是一回事：
             木偶变形 = 在内容上放钉子，拖钉子拽内容（MLS/ARAP，局部）；
             自由变形 = 画面整体套一张自由曲面（FFD，全局，带把手）。

 menu      SuperMrWang → Distort → 自由变形（网格 + 把手）…

 usage     选图层 → 菜单 → 拖网格交点 → 选中交点后拖圆点把手 → 应用。
           右键点交点把那个点复位；Delete 键同样。网格密度可以换（2×2～6×6）。
           Alt+点击画面 = 自己加一条分割线（方向跟着最近的线），上限 12 条。

 note      三条非踩不可的：
           1. **源坐标是 uv 在原位格上的位置，不是曲面上的位置**。
              Newton 只负责解「目标像素落在哪个 uv」，源图按原尺寸铺开。
              这一处弄反，画面会整体按网格平移一次（看着像「没对齐」）。
           2. **把手默认自动**（mesh_warp 的 a=1）：拖节点时按邻居重算切向
              并限幅到相邻弦长以内。不自动的话，Bezier 片会甩过头——
              把中间点拖走 80 px，右边只剩 26 px 的弦却还带 66 px 的切向，
              控制多边形来回折，格子自交，反解出两个分支，画面撕一道。
           3. **预览和应用调同一个 build_field + warp_rgba**，只是分辨率不同。
              两套实现必然漂成「预览好看、确定后不一样」。
           4. **网格可以不等距**（us/vs 是格界，Alt+点击会往里面插数）。加一列时
              参数范围必须按 (cols+1)/cols 缩放（源坐标按 u/cols 铺），切向跟着
              除以同一个系数；格宽不等时把手圆点画在「节点 ± 切向×格宽/3」，
              写成「± 切向/3」会戳到隔壁格、拖起来差一档。
           5. **插线是重拟合，不是精确细分**：每个角只存位置 + 两个切向，面片
              中间四个点的 twist 由四角位置估，细分后两侧对不上。温和变形偏差
              0.6 px、大幅 2~5 px。PS 存整张控制点网，所以它那边是精确的。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math as _math
import os as _os
import sys as _sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject, Gegl, Gdk

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
import mesh_warp as MWM                # noqa: E402
import mask_io as MI                   # noqa: E402

PROC = 'lb-plugin-mesh-warp'
# 预览长边。木偶变形用 520，这里降到 480：网格变形是**全局**的，整幅画面
# 都要重采样（木偶变形只动一小块，大段整行抄过去），520 长边一次要 100 ms 起，
# 拖动会发黏；480 长边约 95 ms，够跟上手。
PREVIEW_EDGE = 480
NODE_HIT = 9          # 交点的点击半径（画布像素）
HANDLE_HIT = 8        # 把手的点击半径
GRID_CHOICES = (2, 3, 4, 5, 6)
OUTPUT_FILTER = 'filter'
OUTPUT_REPLACE = 'replace'
OUTPUT_LAYER = 'new-layer'
# 非破坏那一路挂的 GEGL 算子（ops/mesh-warp）。属性名 mesh 与这里的 PDB
# 参数同名，对话框写回 config 就等于写回滤镜。
FILTER_OP = 'lb:mesh-warp'


# ---- 变形本体 --------------------------------------------------------------

def _write_rgba(layer, w, h, rgba):
    """把 RGBA 字节写回图层。没有 alpha 的图层要退回 3 通道，否则 buf.set
    会因为格式不匹配直接抛错（GIMP 不会替你丢通道）。"""
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
    """能不能变形这个 item。返回 None 就放行，否则抛带人话的异常。"""
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


def find_filter(drawable):
    """图层上已有的网格变形滤镜（重跑时更新它，不再叠一条）。"""
    try:
        for filt in drawable.get_filters():
            if filt.get_operation_name() == FILTER_OP:
                return filt
    except Exception:
        pass
    return None


def load_filter_state(drawable):
    """从滤镜 config 读回网格串。没有滤镜返回 None。"""
    filt = find_filter(drawable)
    if filt is None:
        return None
    return {'mesh': filt.get_config().get_property('mesh') or ''}


def apply_filter(drawable, mesh, copy_layer=False):
    """非破坏那一路：网格串挂到滤镜栈上，原像素一个字节不变。"""
    layer = drawable
    if copy_layer:
        image = drawable.get_image()
        layer = drawable.copy()
        layer.set_name(drawable.get_name() + _(" (warp filter)"))
        image.insert_layer(layer, None, image.get_item_position(drawable))
    filt = find_filter(layer)
    if filt is None:
        filt = Gimp.DrawableFilter.new(layer, FILTER_OP, _("Mesh warp"))
    filt.get_config().set_property('mesh', MWM.format_mesh_string(mesh))
    filt.update()
    if find_filter(layer) is None:
        layer.append_filter(filt)
    return filt, layer


def warp_drawable(drawable, mesh, output=OUTPUT_REPLACE, on_tick=None):
    """全分辨率变形一个图层。返回 info 字典。"""
    image = drawable.get_image()
    w, h = drawable.get_width(), drawable.get_height()
    t0 = time.time()
    if mesh is None:
        raise RuntimeError(_("No mesh — nothing to deform."))
    if mesh.is_identity():
        raise RuntimeError(_("The mesh has not been touched yet — drag a grid "
                             "point (or a handle) away from its original spot "
                             "first."))

    field = MWM.build_field(mesh, w, h)
    if field.is_identity():
        raise RuntimeError(_("The deformation came out empty — the grid points "
                             "cancel each other out."))

    _pw, _ph, rgba = MI.read_drawable_rgba(drawable, max(w, h))
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

    info = MWM.mesh_summary(mesh)
    info.update({"seconds": time.time() - t0, "size": (w, h),
                 "field": field, "layer": layer})
    return info


# ---- 对话框 ----------------------------------------------------------------

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


def build_dialog(config, image, drawable, w, h):
    """建出对话框，返回 (dlg, ctx)。**故意不 run()**：无头回归直接调
    ctx["render"]() 就能验证「拖了把手之后预览真的变了」。

    画布坐标 = 预览坐标（1:1），网格存的是**图层坐标**，k = 预览 1 px
    换多少图层 px。拖的时候一律先乘 k 换算回图层坐标再写进网格。
    """
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk

    pw, ph, prgba = MI.read_drawable_rgba(drawable, PREVIEW_EDGE)
    k = float(w) / max(pw, 1)

    dlg = Gtk.Dialog.new()
    dlg.set_title(_("Free Transform (Mesh + Handles)"))
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
    hint = Gtk.Label.new(_("Drag a grid point to move it · select a point to "
                           "get its handles, drag the round dots to bend the "
                           "lines · right-click resets a point"))
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
    title.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("Mesh")))
    right.add(title)

    grid_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    glbl = Gtk.Label.new(_("Grid"))
    glbl.set_xalign(0.0)
    glbl.set_size_request(96, -1)
    combo_grid = Gtk.ComboBoxText.new()
    for n in GRID_CHOICES:
        combo_grid.append(str(n), _("%d × %d cells") % (n, n))
    # 「custom」= 自己 Alt+点击加过线，格数不再是正方形
    combo_grid.append("0", _("custom (you added lines)"))
    combo_grid.set_active_id("3")
    combo_grid.set_hexpand(True)
    grid_row.add(glbl)
    grid_row.add(combo_grid)
    right.add(grid_row)

    mesh = MWM.parse_mesh_string(config.get_property('mesh') or "", w, h)
    if mesh.uniform() and mesh.cols == mesh.rows and mesh.cols in GRID_CHOICES:
        combo_grid.set_active_id(str(mesh.cols))
    else:
        combo_grid.set_active_id("0")

    show_mesh = Gtk.CheckButton.new_with_label(_("Show the mesh"))
    show_mesh.set_active(True)
    right.add(show_mesh)
    show_handles = Gtk.CheckButton.new_with_label(_("Show the handles"))
    show_handles.set_active(True)
    right.add(show_handles)

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
    b_reset = Gtk.Button.new_with_label(_("Reset selected"))
    b_clear = Gtk.Button.new_with_label(_("Reset all"))
    btn_row.add(b_reset)
    btn_row.add(b_clear)
    right.add(btn_row)

    note = Gtk.Label.new("")
    note.set_line_wrap(True)
    note.set_xalign(0.0)
    right.add(note)

    ctx = {
        "mesh": mesh,
        "selected": -1,
        "drag": None,
        "prgba": prgba, "pw": pw, "ph": ph, "k": k, "w": w, "h": h,
        "warped": prgba, "lines": None, "id": 0, "preview_mesh": None,
        "area": area, "note": note, "dialog": dlg,
        "combo_grid": combo_grid, "combo_out": combo_out,
        "check_mesh": show_mesh, "check_handles": show_handles,
    }

    def values():
        return {
            "mesh": ctx["mesh"].copy(),
            "grid": int(combo_grid.get_active_id() or 3),
            "output": combo_out.get_active_id() or OUTPUT_FILTER,
            "show_mesh": bool(show_mesh.get_active()),
            "show_handles": bool(show_handles.get_active()),
        }

    def render():
        """预览：网格缩到预览空间 → 解场 → 重采样。应用走同一个
        build_field + warp_rgba，只是 w/h 换成全分辨率。"""
        ctx["id"] = 0
        v = values()
        t0 = time.time()
        mp = v["mesh"].scaled(1.0 / k)
        ctx["preview_mesh"] = mp
        try:
            field = MWM.build_field(mp, pw, ph)
            if field.is_identity():
                ctx["warped"] = prgba
            else:
                ctx["warped"] = WM.warp_rgba(prgba, pw, ph, field)
            ctx["lines"] = mp.grid_polylines(steps=12) if v["show_mesh"] else None
            st = MWM.mesh_summary(v["mesh"])
            tail = ""
            if st["curved"]:
                tail = _(" · %d bent") % st["curved"]
            note.set_text(_("%d×%d cells · %d moved%s · max shift %.1f px\n"
                            "preview %s of %s · %.0f ms") % (
                st["cols"], st["rows"], st["moved"], tail, st["max_shift"],
                _fmt_size(pw, ph), _fmt_size(w, h),
                (time.time() - t0) * 1000.0))
        except Exception as exc:
            note.set_text(_("Preview failed: %s") % exc)
        area.queue_draw()
        return False

    def schedule(delay=70):
        if ctx["id"]:
            GLib.source_remove(ctx["id"])
        ctx["id"] = GLib.timeout_add(delay, render)

    # -- 画 ----------------------------------------------------------------
    def draw(_area, cr):
        # 底色按**分配到的尺寸**铺：左边提示语会把这一列撑宽，不铺就留灰边
        _checker(cr, _area.get_allocated_width(), _area.get_allocated_height())
        try:
            pix = _pixbuf_from_rgba(ctx["warped"], pw, ph)
            Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
            cr.paint()
        except Exception:
            pass

        m = ctx["preview_mesh"]
        if m is None:
            return
        # 原位网格（虚线）：让人看得出「被推走了多远」
        if ctx["lines"]:
            cr.set_dash([3, 3])
            cr.set_line_width(1.0)
            cr.set_source_rgba(0.05, 0.05, 0.05, 0.35)
            ih = MWM.Mesh.identity(m.w, m.h, m.cols, m.rows)
            for i in range(m.cols + 1):
                cr.move_to(ih.node(i, 0)["x"], ih.node(i, 0)["y"])
                cr.line_to(ih.node(i, m.rows)["x"], ih.node(i, m.rows)["y"])
            for j in range(m.rows + 1):
                cr.move_to(ih.node(0, j)["x"], ih.node(0, j)["y"])
                cr.line_to(ih.node(m.cols, j)["x"], ih.node(m.cols, j)["y"])
            cr.stroke()
            cr.set_dash([])

            cr.set_line_width(1.2)
            cr.set_source_rgba(0.15, 0.65, 1.0, 0.75)
            for line in ctx["lines"]:
                cr.move_to(line[0][0], line[0][1])
                for px, py in line[1:]:
                    cr.line_to(px, py)
                cr.stroke()

        sel = ctx["selected"]
        # 选中节点的把手：一根线 + 两个圆点（对称，所以两端都画）
        if sel >= 0 and ctx["check_handles"].get_active():
            j, i = divmod(sel, m.cols + 1)
            n = m.node(i, j)
            cx, cy = n["x"], n["y"]
            for axis in ("u", "v"):
                cr.set_line_width(1.0)
                cr.set_source_rgba(1.0, 0.38, 0.10, 0.9)
                cr.move_to(cx, cy)
                for sign in (1, -1):
                    hx, hy = m.handle(i, j, axis, sign)
                    cr.line_to(hx, hy)
                cr.stroke()
                for sign in (1, -1):
                    hx, hy = m.handle(i, j, axis, sign)
                    cr.set_source_rgba(1.0, 0.95, 0.85, 0.95)
                    cr.arc(hx, hy, HANDLE_HIT * 0.5, 0, 2 * _math.pi)
                    cr.fill_preserve()
                    cr.set_source_rgba(0.75, 0.25, 0.05, 0.95)
                    cr.set_line_width(1.2)
                    cr.stroke()

        for idx in range(len(m.nodes)):
            j, i = divmod(idx, m.cols + 1)
            n = m.node(i, j)
            cx, cy = n["x"], n["y"]
            if idx == sel:
                cr.set_source_rgba(1.0, 0.38, 0.10, 0.95)
            else:
                cr.set_source_rgba(1.0, 0.85, 0.25, 0.95)
            cr.rectangle(cx - 3.0, cy - 3.0, 6.0, 6.0)
            cr.fill_preserve()
            cr.set_line_width(1.2)
            cr.set_source_rgba(0.05, 0.05, 0.05, 0.75)
            cr.stroke()

        if ctx["mesh"].is_identity():
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.6)
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(15)
            cr.move_to(14, ph - 18)
            cr.show_text(_("Drag a grid point to start shaping"))

    # -- 命中 --------------------------------------------------------------
    def hit_node(x, y):
        """画布坐标 → 节点索引，-1 表示没点到。"""
        best, best_d = -1, NODE_HIT ** 2
        m = ctx["preview_mesh"]
        for idx in range(len(m.nodes)):
            j, i = divmod(idx, m.cols + 1)
            n = m.node(i, j)
            d = (n["x"] - x) ** 2 + (n["y"] - y) ** 2
            if d <= best_d:
                best, best_d = idx, d
        return best

    def hit_handle(x, y):
        """只查选中节点的四个把手圆点。返回 (axis, sign) 或 None。"""
        sel = ctx["selected"]
        if sel < 0:
            return None
        m = ctx["preview_mesh"]
        j, i = divmod(sel, m.cols + 1)
        best, best_d = None, HANDLE_HIT ** 2
        for axis in ("u", "v"):
            for sign in (1, -1):
                hx, hy = m.handle(i, j, axis, sign)
                d = (hx - x) ** 2 + (hy - y) ** 2
                if d <= best_d:
                    best, best_d = (axis, sign), d
        return best

    # -- 自己加分割线 ------------------------------------------------------
    def add_line(x, y):
        """Alt+点击：在点到的位置加一条网格线（方向跟着最近的网格线）。

        新线取原曲面上的点和切向，所以画面几乎不动——实测见
        check_mesh_warp。「加线」是重拟合，形状变化在 1 px 量级。
        """
        mp = ctx["preview_mesh"]
        m = ctx["mesh"]
        if mp is None or m is None:
            return False
        try:
            u, v = MWM.invert_point(mp, x, y, w=pw, h=ph)
        except Exception as exc:
            note.set_text(_("Could not add a line: %s") % exc)
            return False
        # 哪一边的线离得更近（按像素，格宽不等也公平）
        d_u = min(abs(mp.eval_uv(mp.us[i], v)[0] - x)
                  for i in range(mp.cols + 1))
        d_v = min(abs(mp.eval_uv(u, mp.vs[j])[1] - y)
                  for j in range(mp.rows + 1))
        if d_u <= d_v:
            ci, _cj, s, _t = m.locate(u, v)
            new = m.split_u(ci, s)
        else:
            _ci, cj, _s, t = m.locate(u, v)
            new = m.split_v(cj, t)
        if new is None:
            note.set_text(_("Grid is already at the maximum of %d lines.")
                          % (MWM.MAX_CELLS + 1))
            return False
        ctx["mesh"] = new
        ctx["selected"] = -1
        ctx["drag"] = None
        gid = str(new.cols) if (new.cols == new.rows
                                and new.cols in GRID_CHOICES) else "0"
        if combo_grid.get_active_id() != gid:
            combo_grid.set_active_id(gid)
        schedule(0)
        return True

    # -- 交互 --------------------------------------------------------------
    def on_press(_area, ev):
        x, y = ev.x, ev.y
        m = ctx["mesh"]
        if (ev.button == 1 and (ev.state & (Gdk.ModifierType.ALT_MASK
                                           | Gdk.ModifierType.MOD1_MASK))):
            return add_line(x, y)                # Alt+点击 = 加一条线
        if ev.button == 3:                       # 右键：这个点复位
            idx = hit_node(x, y)
            if idx >= 0:
                j, i = divmod(idx, m.cols + 1)
                ident = MWM.Mesh.identity(m.w, m.h, m.cols, m.rows)
                n, src = m.node(i, j), ident.node(i, j)
                n["x"], n["y"] = src["x"], src["y"]
                n["a"] = 1
                m.auto_refresh()
                schedule(0)
            return True
        if ev.button != 1:
            return False
        area.grab_focus()
        hh = hit_handle(x, y)
        if hh is not None:
            ctx["drag"] = ("handle", hh[0], hh[1])
            schedule(0)
            return True
        idx = hit_node(x, y)
        if idx < 0:
            ctx["selected"] = -1
            ctx["drag"] = None
            schedule(0)
            return True
        ctx["selected"] = idx
        ctx["drag"] = ("node", idx, None)
        schedule(0)
        return True

    def set_node_pos(idx, cx, cy):
        """把第 idx 个交点挪到画布坐标 (cx, cy)。拖拽和回归都走这一条。"""
        m = ctx["mesh"]
        if not (0 <= idx < len(m.nodes)):
            return
        j, i = divmod(idx, m.cols + 1)
        n = m.node(i, j)
        n["x"] = min(max(cx * k, 0.0), w - 1.0)
        n["y"] = min(max(cy * k, 0.0), h - 1.0)
        m.auto_refresh()                        # 自动把手跟着新位置重算

    def set_handle(axis, sign, cx, cy):
        """把选中节点的把手拖到画布坐标 (cx, cy)（对称：两端一起动）。"""
        sel = ctx["selected"]
        m = ctx["mesh"]
        if sel < 0 or not (0 <= sel < len(m.nodes)):
            return
        j, i = divmod(sel, m.cols + 1)
        n = m.node(i, j)
        # 把手圆点画在 节点 ± 切向/3 处，所以拖到哪就反推切向 = 3·(点-节点)
        tx, ty = m.tangent_from_handle(i, j, axis, sign, cx * k, cy * k)
        cw, ch = m.cell_size()
        # 限幅按**像素**算：切向 × 格宽 才是这一段实际跨了多少像素
        span = m.cell_width(i) if axis == "u" else m.cell_height(j)
        lim = max(3.0, 3.0 * max(cw, ch)) / (span if span > 0 else 1.0)
        ln = _math.hypot(tx, ty)
        if ln > lim:
            tx, ty = tx * lim / ln, ty * lim / ln
        elif ln < 0.5:
            tx, ty = (0.5 * tx / ln if ln else 0.0,
                      0.5 * ty / ln if ln else 0.0)
        if axis == "u":
            n["ux"], n["uy"] = tx, ty
        else:
            n["vx"], n["vy"] = tx, ty
        n["a"] = 0                              # 手拖过之后不再自动

    def on_motion(_area, ev):
        drag = ctx["drag"]
        if not drag:
            return False
        if drag[0] == "node":
            set_node_pos(drag[1], ev.x, ev.y)
        else:
            set_handle(drag[1], drag[2], ev.x, ev.y)
        schedule(70)
        return True

    def on_release(_area, _ev):
        if ctx["drag"]:
            ctx["drag"] = None
            render()
        return True

    def on_key(_w, ev):
        from gi.repository import Gdk
        if ev.keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            reset_selected()
            return True
        return False

    def reset_selected(_b=None):
        sel = ctx["selected"]
        m = ctx["mesh"]
        if 0 <= sel < len(m.nodes):
            j, i = divmod(sel, m.cols + 1)
            ident = MWM.Mesh.identity(m.w, m.h, m.cols, m.rows)
            n, src = m.node(i, j), ident.node(i, j)
            n["x"], n["y"] = src["x"], src["y"]
            n["a"] = 1
            m.auto_refresh()
        schedule(0)

    def reset_all(_b=None):
        ctx["mesh"] = MWM.Mesh.identity(w, h, ctx["mesh"].cols,
                                        ctx["mesh"].rows,
                                        ctx["mesh"].us, ctx["mesh"].vs)
        ctx["selected"] = -1
        ctx["drag"] = None
        schedule(0)

    def on_grid(_b=None):
        gid = combo_grid.get_active_id()
        if gid in (None, "", "0"):               # 「custom」= 自己加过线
            return
        want = int(gid)
        if want == ctx["mesh"].cols and want == ctx["mesh"].rows:
            return
        ctx["mesh"] = ctx["mesh"].resample(want, want)
        ctx["selected"] = -1
        ctx["drag"] = None
        schedule(0)

    area.connect("draw", draw)
    area.connect("button-press-event", on_press)
    area.connect("motion-notify-event", on_motion)
    area.connect("button-release-event", on_release)
    dlg.connect("key-press-event", on_key)
    b_reset.connect("clicked", reset_selected)
    b_clear.connect("clicked", reset_all)
    combo_grid.connect("changed", on_grid)
    combo_out.connect("changed", lambda *_a: None)
    show_mesh.connect("toggled", lambda *_a: schedule(0))
    show_handles.connect("toggled", lambda *_a: schedule(0))

    ctx["render"] = render
    ctx["values"] = values
    ctx["schedule"] = schedule
    ctx["hit_node"] = hit_node
    ctx["hit_handle"] = hit_handle
    ctx["set_node_pos"] = set_node_pos
    ctx["set_handle"] = set_handle
    ctx["reset_all"] = reset_all
    ctx["add_line"] = add_line
    render()
    outer.show_all()
    return dlg, ctx


def show_dialog(procedure, config, image, drawable, w, h):
    """弹窗。True = 应用（网格/输出已写回 config）。"""
    try:
        dlg, ctx = build_dialog(config, image, drawable, w, h)
        from gi.repository import Gtk
    except Exception as exc:
        Gimp.message(_("This build of GIMP has no GTK — nothing to click on. "
                       "(%s). Pass the mesh through the mesh argument instead: "
                       "\"3,3; x,y,ux,uy,vx,vy; …\"") % exc)
        return False

    resp = dlg.run()
    if ctx["id"]:
        GLib.source_remove(ctx["id"])
    if resp != Gtk.ResponseType.OK:
        dlg.destroy()
        return False

    v = ctx["values"]()
    config.set_property("mesh", MWM.format_mesh_string(v["mesh"]))
    config.set_property("output", v["output"])
    dlg.destroy()
    return True


# ---- 过程注册 --------------------------------------------------------------

def _add_arguments(procedure):
    procedure.add_string_argument(
        "mesh", _("Mesh"),
        _("cols,rows; then one x,y,ux,uy,vx,vy[,auto] per grid point, row by "
          "row. ux/uy and vx/vy are the two handle vectors (the derivative of "
          "the surface, i.e. three times the distance to the handle dot); "
          "auto=1 means the handle is derived from the neighbours. Leave empty "
          "to get a 3×3 grid and drag the points on the picture instead. This "
          "is what the dialog writes back, so a script can replay a warp."),
        "", GObject.ParamFlags.READWRITE)
    output = Gimp.Choice.new()
    output.add(OUTPUT_FILTER, 0, _("Non-destructive filter"),
               _("Attach the mesh as a live filter on the layer: pixels stay "
                 "untouched and re-running the dialog reads the grid back from "
                 "it. This is what the dialog picks by default"))
    output.add(OUTPUT_REPLACE, 1, _("Replace this layer"),
               _("Bake the warp into the current layer"))
    output.add(OUTPUT_LAYER, 2, _("Copy to a new layer"),
               _("Keep the original and put the warped copy above it"))
    procedure.add_choice_argument(
        "output", _("Output"), _("Where the warped pixels go"),
        output, OUTPUT_REPLACE, GObject.ParamFlags.READWRITE)


class MeshWarpPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label(_("Free Transform (Mesh)"))
        procedure.set_documentation(
            _("Warp a layer with a Bezier grid: drag the grid points, bend the "
              "lines with their handles, see it live"),
            _("A grid is laid over the layer. Dragging a grid point moves the "
              "picture with it; selecting a point shows its two handles, and "
              "dragging a handle bends the grid line into a curve, so bulges "
              "and tucks are possible. The mesh can also be passed as a "
              "string, so this works from a script."),
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
            # 已经挂着滤镜：把网格读回来当默认值，弹窗里能接着拖
            loaded = load_filter_state(drawable)
            if run_mode == Gimp.RunMode.INTERACTIVE:
                if loaded:
                    config.set_property('mesh', loaded['mesh'])
                config.set_property('output', OUTPUT_FILTER)
                if not show_dialog(procedure, config, image, drawable,
                                   drawable.get_width(), drawable.get_height()):
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.CANCEL, None)
            mesh = MWM.parse_mesh_string(config.get_property('mesh') or "",
                                         drawable.get_width(),
                                         drawable.get_height())
            output = config.get_property('output') or OUTPUT_REPLACE
            if output == OUTPUT_FILTER:
                # 别用下划线去接 apply_filter 的返回值：模块级 `_` 是翻译函数，
                # 在这里被绑成滤镜对象，下一行 _("…") 就会炸
                # 「'DrawableFilter' object is not callable」。
                _filt, layer = apply_filter(drawable, mesh)
                Gimp.message(_("Attached a live mesh-warp filter to “%s” — "
                               "%d×%d cells. The pixels are untouched: adjust "
                               "the filter or run the dialog again to re-edit.")
                             % (layer.get_name(), mesh.cols, mesh.rows))
                return procedure.new_return_values(
                    Gimp.PDBStatusType.SUCCESS, GLib.Error())
            info = warp_drawable(
                drawable, mesh,
                output=output,
                on_tick=Gimp.progress_pulse)
            Gimp.message(_("Warped %s in %.1f s — %d×%d cells, %d points moved.")
                         % (_fmt_size(info["size"][0], info["size"][1]),
                            info["seconds"], info["cols"], info["rows"],
                            info["moved"]))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            import traceback      # 出错时把栈也打出来，否则只剩一句 str(exc)
            traceback.print_exc()
            Gimp.message("mesh-warp: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(MeshWarpPlugin.__gtype__, _sys.argv)
