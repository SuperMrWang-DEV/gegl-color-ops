#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 曲线 / Curves
 ---------------------------------------------------------------------------
 菜单     SuperMrWang → Curves → LAB / LCh / HSV / CMYK Curves…
 过程     lb-curves-lab / lb-curves-lch / lb-curves-hsv / lb-curves-cmyk
 算子     lb:lab-curves / lb:lch-curves / lb:hsv-curves / lb:cmyk-curves

 对话框是曲线的编辑界面，算子才是干活的那一层。对话框只做三件事：把控制点
 画出来、让用户拖、把结果写成算子认的字符串挂到图层滤镜栈上。像素计算一行
 都不在 Python 里——所以对话框里看到的曲线和最终结果必然一致（两边同算法，
 见 _shared/curve_math.py 与 common/curve.h 的对拍）。

 The dialog only edits control points and writes the string the operator
 understands; not a single pixel is computed in Python, so what the graph
 shows and what the filter does cannot drift apart.

 三个坑（都在代码里绕开了）：
 · 预览要多挂一条临时图层再烘焙。GEGL 滤镜是显示层，直接读 drawable 拿到
   的是**没有滤镜**的原始像素；必须 merge_filter 之后才读得到结果。
 · 临时图层会进 undo 历史，用 undo_disable/enable 包住，否则用户按一次
   撤销只撤掉了看不见的预览层。
 · 色相分量是**偏移曲线**（0.5 = 不偏），不是对角线。画对角线就成了整体
   旋转 + 接缝，见 common/curve.h 的说明。

 license  GPL-3.0-or-later，见工程根目录 LICENSE
 ============================================================================"""

import os as _os
import sys as _sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GLib, GObject, Gegl          # noqa: E402

_here = _os.path.dirname(_os.path.abspath(__file__))
for _cand in (_os.path.join(_here, '_shared'),
              _os.path.normpath(_os.path.join(_here, '..', '_shared'))):
    if _os.path.isdir(_cand) and _cand not in _sys.path:
        _sys.path.append(_cand)

try:
    from lb_i18n import _                       # noqa: F811
except Exception:
    def _(s):
        return s

import curve_math as CM                        # noqa: E402
import mask_io as MI                           # noqa: E402

PROCS = [
    ('lb-plugin-curves-lab', 'lab'),
    ('lb-plugin-curves-lch', 'lch'),
    ('lb-plugin-curves-hsv', 'hsv'),
    ('lb-plugin-curves-cmyk', 'cmyk'),
]
PROC2SPACE = dict(PROCS)

OUTPUT_FILTER = 'filter'
OUTPUT_REPLACE = 'replace'

PREVIEW_EDGE = 560     # 预览长边：和曲线画布同高，横图约 560×373，不再留一大块空
GRAPH = 380            # 曲线画布边长：曲线要能看出过冲和折点的位置
GPAD = 9               # 画布内边距：端点画在 0/1 上，不留边会被框裁掉半个圆
HIT = 12               # 抓点的半径（px）
DEBOUNCE_MS = 70       # 拖动时预览的去抖间隔


# ---- 图层与滤镜 -------------------------------------------------------------

def find_filter(drawable, op):
    try:
        for filt in drawable.get_filters():
            if filt.get_operation_name() == op:
                return filt
    except Exception:
        pass
    return None


def load_curves(drawable, op):
    filt = find_filter(drawable, op)
    if filt is None:
        return None
    try:
        return filt.get_config().get_property('curves') or ''
    except Exception:
        return None


def apply_curves(drawable, op, curves_str, output=OUTPUT_FILTER):
    """把曲线串写到滤镜栈上。output=replace 时顺便烘焙进像素。"""
    filt = find_filter(drawable, op)
    fresh = filt is None
    if fresh:
        filt = Gimp.DrawableFilter.new(drawable, op, _("Curves"))
    filt.get_config().set_property('curves', curves_str)
    filt.update()
    if fresh:
        drawable.append_filter(filt)
    if output == OUTPUT_REPLACE:
        drawable.merge_filter(filt)
        return None
    return filt


def _fit(w, h, edge):
    if w >= h:
        return max(1, edge), max(1, int(round(h * edge / float(w))))
    return max(1, int(round(w * edge / float(h)))), max(1, edge)


def preview_rgba(image, drawable, op, curves_str, edge=PREVIEW_EDGE):
    """复制图层 → 挂滤镜 → 烘焙 → 读像素 → 删副本。

    滤镜是显示层，不烘焙读到的还是原像素，所以 merge_filter 这一步不能省。
    整段关掉 undo：临时图层不该出现在用户的历史里。
    """
    pw, ph = _fit(drawable.get_width(), drawable.get_height(), edge)
    tmp = None
    image.undo_disable()
    try:
        tmp = drawable.copy()
        image.insert_layer(tmp, None, 0)
        # 先在 C 里缩到预览尺寸再挂滤镜：整幅复制 + 整幅烘焙，4000×6000 要几秒；
        # 缩完只在几十万像素上算，滤镜那一步可以忽略。缩放本身是毫秒级。
        if (tmp.get_width(), tmp.get_height()) != (pw, ph):
            try:
                tmp.scale(pw, ph, False)
            except Exception:
                pass
        filt = Gimp.DrawableFilter.new(tmp, op, "curves preview")
        filt.get_config().set_property('curves', curves_str)
        filt.update()
        tmp.append_filter(filt)
        try:
            tmp.merge_filter(filt)
        except Exception:
            pass
        return MI.read_drawable_rgba(tmp, edge, exact=(pw, ph))
    finally:
        try:
            if tmp is not None:
                image.remove_layer(tmp)
        except Exception:
            pass
        image.undo_enable()


def _pixbuf(rgba, w, h):
    from gi.repository import GdkPixbuf
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(bytes(rgba)), GdkPixbuf.Colorspace.RGB, True, 8,
        w, h, w * 4)


# ---- 自绘：一张曲线 ---------------------------------------------------------

def _grid(cr, s, ring):
    cr.set_source_rgb(0.20, 0.20, 0.20)
    cr.paint()
    cr.set_line_width(1.0)
    for i in range(1, 4):
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.move_to(i * s / 4.0, 0); cr.line_to(i * s / 4.0, s)
        cr.move_to(0, i * s / 4.0); cr.line_to(s, i * s / 4.0)
        cr.stroke()

    # 参考线：普通分量画对角线；色相画中轴（0.5 = 不偏）
    cr.set_source_rgba(1, 1, 1, 0.28)
    cr.set_dash([4, 4])
    if ring:
        cr.move_to(0, s * 0.5); cr.line_to(s, s * 0.5)
    else:
        cr.move_to(0, s); cr.line_to(s, 0)
    cr.stroke()
    cr.set_dash([])


def _curve_path(cr, s, lut):
    cr.move_to(0, s - lut[0] * s)
    n = len(lut)
    for i in range(1, n, 4):
        cr.line_to(i * s / (n - 1.0), s - lut[i] * s)
    cr.line_to(s, s - lut[-1] * s)


def draw_graph(cr, s, points, lut, ring, accent=(0.95, 0.78, 0.25)):
    _grid(cr, s, ring)

    cr.set_line_width(2.0)
    cr.set_source_rgb(*accent)
    _curve_path(cr, s, lut)
    cr.stroke()

    for i, (x, y) in enumerate(points):
        cx, cy = x * s, s - y * s
        cr.set_source_rgb(0.12, 0.12, 0.12)
        cr.arc(cx, cy, 5.0, 0, 6.2832)
        cr.fill_preserve()
        cr.set_source_rgb(*accent)
        cr.set_line_width(2.0)
        cr.stroke()


def _label(text, bold=False, dim=False, xalign=0.0):
    """带点层次的标签。GTK 里没有现成的「小节标题」样式，用 Pango 标记最省事。"""
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    lbl = Gtk.Label.new()
    esc = GLib.markup_escape_text(text)
    if bold:
        lbl.set_markup("<b>%s</b>" % esc)
    elif dim:
        lbl.set_markup("<small><span alpha='62%%'>%s</span></small>" % esc)
    else:
        lbl.set_text(text)
    lbl.set_xalign(xalign)
    return lbl


# ---- 对话框 -----------------------------------------------------------------

def build_dialog(procedure, config, image, drawable, space):
    """建出对话框但**不 run()**：无头回归直接调 ctx['refresh']() 验证预览变了。"""
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk

    op = CM.SPACES[space]['op']
    parts = CM.SPACES[space]['parts']

    # 从图层上已有的滤镜读回，重开对话框能接着改
    text = load_curves(drawable, op) or (config.get_property('curves') or '')
    state = CM.parse_set(space, text)

    dlg = Gtk.Dialog.new()
    dlg.set_title(_(CM.SPACES[space]['title']))
    dlg.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
    dlg.add_button(_("_Apply"), Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)
    dlg.set_resizable(False)

    outer = Gtk.Box.new(Gtk.Orientation.VERTICAL, 14)
    outer.set_border_width(16)
    dlg.get_content_area().add(outer)

    top = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 18)
    outer.add(top)

    # 左：预览
    left = Gtk.Box.new(Gtk.Orientation.VERTICAL, 8)
    head_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    plabel = _label(_("Preview"), bold=True)
    plabel.set_hexpand(True)
    head_row.add(plabel)
    head_row.add(_label("%d × %d" % (drawable.get_width(),
                                     drawable.get_height()), dim=True,
                        xalign=1.0))
    left.add(head_row)

    pframe = Gtk.Frame.new()
    pframe.set_border_width(3)
    parea = Gtk.DrawingArea.new()
    pw, ph = _fit(drawable.get_width(), drawable.get_height(), PREVIEW_EDGE)
    parea.set_size_request(pw, ph)
    pframe.add(parea)
    left.add(pframe)
    top.add(left)

    # 中间：一道竖线，把「看图」和「调曲线」分开
    top.add(Gtk.Separator.new(Gtk.Orientation.VERTICAL))

    # 右：曲线画布
    right = Gtk.Box.new(Gtk.Orientation.VERTICAL, 12)
    right.set_hexpand(True)
    right.set_valign(Gtk.Align.CENTER)
    top.add(right)

    chan_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    chan_row.add(_label(_("Channel"), bold=True))
    combo = Gtk.ComboBoxText.new()
    for name, ring in parts:
        combo.append(name, name + (_("  (hue shift)") if ring else ""))
    combo.set_active(0)
    combo.set_hexpand(True)
    chan_row.add(combo)

    reset = Gtk.Button.new_with_label(_("Reset"))
    chan_row.add(reset)
    right.add(chan_row)

    gframe = Gtk.Frame.new()
    gframe.set_border_width(3)
    garea = Gtk.DrawingArea.new()
    # 画布是正方形，尺寸固定；多出来的高度靠整列居中吸收，而不是把画布拉成长条
    # （拉长会让曲线在图里只剩中间一小块，四周全是暗边）。竖图时左栏更高，
    # 右列居中即可，不会在画布下面留一大块空白。
    garea.set_size_request(GRAPH, GRAPH)
    garea.set_can_focus(True)
    garea.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                     Gdk.EventMask.BUTTON_RELEASE_MASK |
                     Gdk.EventMask.POINTER_MOTION_MASK)
    gframe.add(garea)
    right.add(gframe)

    # 底栏：左侧提示，右侧输出方式。拉到全宽，两栏的视觉高度才对得齐
    outer.add(Gtk.Separator.new(Gtk.Orientation.HORIZONTAL))
    bottom = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 12)
    outer.add(bottom)

    hint = _label(_("Click to add a point · drag to bend · right-click "
                    "a point to remove it"), dim=True)
    hint.set_hexpand(True)
    hint.set_line_wrap(True)
    hint.set_max_width_chars(56)
    hint.set_valign(Gtk.Align.CENTER)
    bottom.add(hint)

    out_row = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    out_row.add(_label(_("Output"), bold=True))
    combo_out = Gtk.ComboBoxText.new()
    combo_out.append(OUTPUT_FILTER, _("Live filter (re-editable)"))
    combo_out.append(OUTPUT_REPLACE, _("Bake into this layer"))
    combo_out.set_active_id(config.get_property('output') or OUTPUT_FILTER)
    combo_out.set_size_request(240, -1)
    out_row.add(combo_out)
    bottom.add(out_row)

    ctx = {
        'dlg': dlg, 'state': state, 'space': space, 'op': op,
        'chan': 0, 'drag': None, 'pending': False,
        'pixbuf': None, 'parea': parea, 'garea': garea,
        'combo': combo, 'combo_out': combo_out, 'config': config,
        'text': lambda: CM.format_set(
            {n: state[n] for n, _r in parts}),
    }

    def ring_of(idx):
        return parts[idx][1]

    def current():
        return state[parts[ctx['chan']][0]]

    # -- 预览：去抖，避免每个 motion 都复制一次图层
    def refresh_preview():
        ctx['pending'] = False
        try:
            w, h, rgba = preview_rgba(image, drawable, op, ctx['text']())
            ctx['pixbuf'] = _pixbuf(rgba, w, h)
        except Exception as exc:
            Gimp.message("curves preview: %s" % exc)
            return False
        parea.queue_draw()
        return False

    def schedule():
        if ctx['pending']:
            return
        ctx['pending'] = True
        GLib.timeout_add(DEBOUNCE_MS, refresh_preview)

    def redraw_graph():
        garea.queue_draw()

    def geom(area):
        """画布可以用多大：取分配尺寸里最大的正方形，居中。"""
        aw, ah = area.get_allocated_width(), area.get_allocated_height()
        side = float(max(GRAPH, min(aw, ah)))
        return (aw - side) / 2.0, (ah - side) / 2.0, side - 2 * GPAD

    def on_draw_graph(_area, cr):
        lut, _id = CM.build(current())
        x0, y0, side = geom(garea)
        cr.translate(x0 + GPAD, y0 + GPAD)
        draw_graph(cr, side, current(), lut, ring_of(ctx['chan']))
        return False

    def on_draw_preview(_area, cr):
        # 底色跟曲线画布一致，图比画布小时留边而不是露出窗口灰
        cr.set_source_rgb(0.20, 0.20, 0.20)
        cr.paint()
        pb = ctx['pixbuf']
        if pb is not None:
            from gi.repository import Gdk
            w, h = _area.get_allocated_width(), _area.get_allocated_height()
            cr.save()
            cr.translate((w - pb.get_width()) / 2.0,
                         (h - pb.get_height()) / 2.0)
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.paint()
            cr.restore()
        return False

    # -- 鼠标：加点 / 拖点 / 右键删点
    def hit_index(mx, my):
        pts = current()
        x0, y0, side = geom(garea)
        best, bd = None, HIT * HIT
        for i, (x, y) in enumerate(pts):
            dx = x0 + GPAD + x * side - mx
            dy = y0 + GPAD + (1.0 - y) * side - my
            d = dx * dx + dy * dy
            if d <= bd:
                best, bd = i, d
        return best

    def to_data(mx, my):
        x0, y0, side = geom(garea)
        return (min(max((mx - x0 - GPAD) / side, 0.0), 1.0),
                min(max(1.0 - (my - y0 - GPAD) / side, 0.0), 1.0))

    def on_press(_area, ev):
        pts = current()
        idx = hit_index(ev.x, ev.y)
        if ev.button == 3:
            if idx is not None and 0 < idx < len(pts) - 1:
                pts.pop(idx)
                redraw_graph(); schedule()
            return True
        if idx is None:
            x, y = to_data(ev.x, ev.y)
            pts.append((x, y))
            pts.sort(key=lambda p: p[0])
            idx = min(range(len(pts)), key=lambda i: abs(pts[i][0] - x))
        ctx['drag'] = idx
        garea.grab_focus()
        redraw_graph()
        return True

    def on_motion(_area, ev):
        if ctx['drag'] is None:
            return False
        pts = current()
        i = ctx['drag']
        x, y = to_data(ev.x, ev.y)
        # 端点锁在 0 / 1 上，只许上下动；中间点夹在左右邻居之间，防止折回
        if i == 0:
            x = 0.0
        elif i == len(pts) - 1:
            x = 1.0
        else:
            lo = pts[i - 1][0] + 1e-3
            hi = pts[i + 1][0] - 1e-3
            x = min(max(x, lo), hi)
        pts[i] = (x, y)
        redraw_graph()
        schedule()
        return True

    def on_release(_area, _ev):
        ctx['drag'] = None
        return True

    def on_chan(_combo):
        ctx['chan'] = combo.get_active()
        redraw_graph()

    def on_reset(_btn):
        state[parts[ctx['chan']][0]] = CM.default_points(ring_of(ctx['chan']))
        redraw_graph(); schedule()

    garea.connect('draw', on_draw_graph)
    parea.connect('draw', on_draw_preview)
    garea.connect('button-press-event', on_press)
    garea.connect('motion-notify-event', on_motion)
    garea.connect('button-release-event', on_release)
    combo.connect('changed', on_chan)
    reset.connect('clicked', on_reset)

    ctx['refresh'] = refresh_preview
    ctx['text_fn'] = ctx['text']
    refresh_preview()          # 首帧：让预览立刻有东西
    return dlg, ctx


def show_dialog(procedure, config, image, drawable, space):
    dlg, ctx = build_dialog(procedure, config, image, drawable, space)
    # GTK3 里控件默认不显示，`dlg.run()` 只 show 对话框自己，不会递归 show 子控件
    # —— 少了这一句，弹出来就只有一个标题栏加「取消/应用」，正文整块是空的。
    dlg.show_all()
    try:
        gi.require_version('GimpUi', '3.0')
        from gi.repository import GimpUi
        GimpUi.init(procedure.get_name())
        GimpUi.window_set_transient(dlg)
    except Exception:
        pass
    ok = bool(dlg.run())
    text = ctx['text']()
    output = ctx['combo_out'].get_active_id() or OUTPUT_FILTER
    dlg.destroy()
    if not ok:
        return False, None, None
    config.set_property('curves', text)
    config.set_property('output', output)
    return True, text, output


# ---- 过程注册 ---------------------------------------------------------------

def _add_arguments(procedure):
    procedure.add_string_argument(
        "curves", _("Curves"),
        _("Control points per component, as \"L 0,0 0.3,0.2 1,1|a 0,0 1,1\". "
          "The hue component of LCh and HSV is an offset curve: 0.5 means no "
          "shift, a flat line at another height rotates the whole ring."),
        "", GObject.ParamFlags.READWRITE)
    out = Gimp.Choice.new()
    out.add(OUTPUT_FILTER, 0, _("Live filter (re-editable)"),
            _("Attach the curves as a live filter: pixels stay untouched and "
              "re-running the dialog reads them back"))
    out.add(OUTPUT_REPLACE, 1, _("Bake into this layer"),
            _("Write the result into the layer pixels"))
    procedure.add_choice_argument(
        "output", _("Output"), _("Where the result goes"),
        out, OUTPUT_FILTER, GObject.ParamFlags.READWRITE)


class CurvesPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [name for name, _s in PROCS]

    def do_create_procedure(self, name):
        space = PROC2SPACE.get(name)
        if space is None:
            return None
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        title = _(CM.SPACES[space]['title'])
        procedure.set_menu_label(title)
        procedure.set_documentation(
            _("Free-form curves per component in the %s space" % space.upper()),
            _("Drag the curve to remap one component; the picture updates as "
              "you drag. The hue component is an offset curve, so a flat line "
              "rotates the whole hue ring without a seam."),
            name)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        _add_arguments(procedure)
        procedure.add_menu_path("<Image>/SuperMrWang/Curves")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        drawable = drawables[0]
        space = PROC2SPACE[procedure.get_name()]
        op = CM.SPACES[space]['op']
        try:
            if run_mode == Gimp.RunMode.INTERACTIVE:
                ok, text, output = show_dialog(procedure, config, image,
                                               drawable, space)
                if not ok:
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.CANCEL, None)
            else:
                text = config.get_property('curves') or ''
                output = config.get_property('output') or OUTPUT_FILTER

            if not (text or '').strip():
                return procedure.new_return_values(
                    Gimp.PDBStatusType.SUCCESS, GLib.Error())

            apply_curves(drawable, op, text, output)
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            import traceback
            traceback.print_exc()
            Gimp.message("curves: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(CurvesPlugin.__gtype__, _sys.argv)
