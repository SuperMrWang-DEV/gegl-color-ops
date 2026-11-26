#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 镜头校正 / Lens Correction
 ---------------------------------------------------------------------------
 菜单     SuperMrWang → Distort → 镜头校正…
 过程     lb-plugin-lens-correction
 算子     lb:lens-correction

 PS「滤镜 → 镜头校正」里真正会用到的三项，一个对话框三个页签：

   畸变    k1 / k2 两个径向系数（Brown–Conrady 的 r²、r⁴ 项），正负决定
           桶形还是枕形；自动缩放把四角兜回画面里，不会留下透明缺口。
   暗角    压暗 / 提亮四周，midpoint 定起始半径、feather 定过渡宽度。
   色差    红、蓝两个通道沿半径各自的偏移（按像素给），绿不动——绿是对焦
           参考，横向色差本来就只错开红蓝。

 三页共用一个算子、一次重采样：像素计算全在 C 里，Python 只负责把滑杆的
 数字写进滤镜参数，所以预览和成品是同一段代码，不可能对不上。

 两个容易踩的地方：
 · 预览要**先缩图再挂滤镜**。几何算子整幅重采样，4000×6000 直接跑要好几秒；
   缩到 560 长边只有二十万像素，拖动才跟得上手。
 · 色差是按像素给的，缩过图之后必须按「原宽 / 预览宽」放大回去，否则预览里
   的紫边比成品细十几倍，等于看不见。

 license  GPL-3.0-or-later，见工程根目录 LICENSE
 ============================================================================"""

import json
import os as _os
import sys as _sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, GLib, GObject, Gtk                # noqa: E402

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

import mask_io as MI                           # noqa: E402

PROC = 'lb-plugin-lens-correction'
OP = 'lb:lens-correction'

OUTPUT_FILTER = 'filter'
OUTPUT_REPLACE = 'replace'
OUTPUT_NEW = 'new'

PREVIEW_EDGE = 560
DEBOUNCE_MS = 70

# 参数名就是算子的属性名（GEGL 用连字符）。
DEFAULTS = {
    'k1': 0.0,
    'k2': 0.0,
    'auto-zoom': True,
    'zoom': 1.0,
    'vignette': 0.0,
    'vignette-midpoint': 0.55,
    'vignette-feather': 0.45,
    'ca-red': 0.0,
    'ca-blue': 0.0,
    'abyss': 'clamp',
    'resampling': 'nohalo',
}


# ---- 滤镜 -------------------------------------------------------------------

def find_filter(drawable):
    try:
        for filt in drawable.get_filters():
            if filt.get_operation_name() == OP:
                return filt
    except Exception:
        pass
    return None


def load_settings(drawable):
    """从已有的滤镜读回参数；没有就返回默认值。"""
    out = dict(DEFAULTS)
    filt = find_filter(drawable)
    if filt is None:
        return out
    try:
        cfg = filt.get_config()
        for key in DEFAULTS:
            out[key] = cfg.get_property(key)
    except Exception:
        pass
    return out


def apply_settings(drawable, settings, output=OUTPUT_FILTER):
    """把参数写到滤镜栈上；output=replace 时顺便烘焙进像素。"""
    filt = find_filter(drawable)
    fresh = filt is None
    if fresh:
        filt = Gimp.DrawableFilter.new(drawable, OP, _("Lens Correction"))
    cfg = filt.get_config()
    for key, val in settings.items():
        if key not in DEFAULTS:
            continue
        cfg.set_property(key, val)
    filt.update()
    if fresh:
        drawable.append_filter(filt)
    if output == OUTPUT_REPLACE:
        drawable.merge_filter(filt)
        return None
    return filt


# ---- 预览 -------------------------------------------------------------------

def _fit(w, h, edge):
    if w >= h:
        return max(1, edge), max(1, int(round(h * edge / float(w))))
    return max(1, int(round(w * edge / float(h)))), max(1, edge)


def preview_rgba(image, drawable, settings, edge=PREVIEW_EDGE):
    """复制图层 → 缩小 → 挂滤镜 → 烘焙 → 读像素 → 删副本。

    先缩再挂是有意的：几何算子整幅重采样，原尺寸跑一次要几秒，滑杆根本
    拖不动；缩到 560 长边之后一次十几毫秒。色差按像素给，缩放比要补回去，
    否则预览里的紫边细到看不见。
    """
    src_w, src_h = drawable.get_width(), drawable.get_height()
    pw, ph = _fit(src_w, src_h, edge)
    scale = src_w / float(pw) if pw else 1.0

    params = dict(settings)
    for key in ('ca-red', 'ca-blue'):
        try:
            params[key] = float(params.get(key) or 0.0) * scale
        except Exception:
            params[key] = 0.0

    tmp = None
    image.undo_disable()
    try:
        tmp = drawable.copy()
        image.insert_layer(tmp, None, 0)
        if (tmp.get_width(), tmp.get_height()) != (pw, ph):
            try:
                tmp.scale(pw, ph, False)
            except Exception:
                pass
        filt = Gimp.DrawableFilter.new(tmp, OP, "lens preview")
        cfg = filt.get_config()
        for key, val in params.items():
            if key in DEFAULTS:
                cfg.set_property(key, val)
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


# ---- 对话框 -----------------------------------------------------------------

def _slider(grid, row, title, lo, hi, step, digits=3):
    """一行：标签 + 滑杆（带数值）。返回 (scale, adjustment)。"""
    label = Gtk.Label(label=title, xalign=0.0)
    label.set_size_request(118, -1)
    adj = Gtk.Adjustment(value=0.0, lower=lo, upper=hi,
                         step_increment=step, page_increment=step * 10)
    sc = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
    sc.set_digits(digits)
    sc.set_hexpand(True)
    sc.set_value_pos(Gtk.PositionType.RIGHT)
    sc.set_size_request(300, -1)
    grid.attach(label, 0, row, 1, 1)
    grid.attach(sc, 1, row, 1, 1)
    return sc


def _page(title):
    grid = Gtk.Grid(row_spacing=6, column_spacing=10,
                    margin_start=12, margin_end=12, margin_top=10,
                    margin_bottom=10)
    grid.set_column_homogeneous(False)
    return grid


def build_dialog(procedure, config, image, drawable):
    """搭界面但不 run()。单独拆出来是为了能在无头环境里截图验收。"""
    settings = load_settings(drawable)

    dlg = Gtk.Dialog(title=_("镜头校正"))
    dlg.set_default_size(940, -1)
    dlg.set_modal(True)
    dlg.set_keep_above(True)
    dlg.add_button(_("取消"), Gtk.ResponseType.CANCEL)
    okb = dlg.add_button(_("应用"), Gtk.ResponseType.OK)
    okb.get_style_context().add_class('suggested-action')

    outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
    outer.set_border_width(10)
    dlg.get_content_area().add(outer)

    # ---- 左侧：三个页签 --------------------------------------------------
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    left.set_size_request(420, -1)
    outer.pack_start(left, False, False, 0)

    nb = Gtk.Notebook()
    nb.set_vexpand(True)

    # 页 1 畸变
    g1 = _page(None)
    k1 = _slider(g1, 0, _("畸变 k1"), -0.5, 0.5, 0.001)
    k2 = _slider(g1, 1, _("畸变 k2"), -0.5, 0.5, 0.001)
    auto = Gtk.CheckButton(label=_("自动缩放（四角兜回画面）"))
    g1.attach(auto, 0, 2, 2, 1)
    zoom = _slider(g1, 3, _("额外缩放"), 0.5, 2.0, 0.01)
    hint1 = Gtk.Label(xalign=0.0)
    hint1.set_line_wrap(True)
    hint1.set_markup(_("k1 为正：从更外面取样，画面收缩——<b>去桶形</b>；\n"
                       "k1 为负：画面膨胀，<b>加桶形 / 鱼眼</b>。"))
    hint1.get_style_context().add_class('dim-label')
    g1.attach(hint1, 0, 4, 2, 1)
    nb.append_page(g1, Gtk.Label(label=_("畸变")))

    # 页 2 暗角
    g2 = _page(None)
    vig = _slider(g2, 0, _("暗角强度 %"), -100, 100, 1, digits=0)
    vmid = _slider(g2, 1, _("起始半径"), 0.0, 1.2, 0.01)
    vfea = _slider(g2, 2, _("羽化宽度"), 0.01, 1.0, 0.01)
    hint2 = Gtk.Label(xalign=0.0)
    hint2.set_line_wrap(True)
    hint2.set_markup(_("半径以半对角线为 1，四角恰为 1；负值压暗，正值提亮。"))
    hint2.get_style_context().add_class('dim-label')
    g2.attach(hint2, 0, 3, 2, 1)
    nb.append_page(g2, Gtk.Label(label=_("暗角")))

    # 页 3 色差
    g3 = _page(None)
    car = _slider(g3, 0, _("红通道偏移 px"), -20, 20, 0.1, digits=1)
    cab = _slider(g3, 1, _("蓝通道偏移 px"), -20, 20, 0.1, digits=1)
    hint3 = Gtk.Label(xalign=0.0)
    hint3.set_line_wrap(True)
    hint3.set_markup(_("按<b>角落</b>处的像素给：正值把那一路往外推，负值往里拉。\n"
                       "紫边通常红蓝各加一点、方向相反；绿通道不动。"))
    hint3.get_style_context().add_class('dim-label')
    g3.attach(hint3, 0, 2, 2, 1)
    nb.append_page(g3, Gtk.Label(label=_("色差")))

    left.pack_start(nb, True, True, 0)

    # 全局：重采样 / 越界
    tail = Gtk.Grid(row_spacing=6, column_spacing=10)
    tail.attach(Gtk.Label(label=_("重采样"), xalign=0.0), 0, 0, 1, 1)
    rs = Gtk.ComboBoxText()
    for key, label in (('nohalo', _('Nohalo（无振铃）')),
                       ('lohalo', _('Lohalo（无振铃，慢）')),
                       ('cubic', _('双三次（更锐，边缘会振铃）')),
                       ('bilinear', _('双线性（最快）')),
                       ('nearest', _('最近邻（硬）'))):
        rs.append(key, label)
    tail.attach(rs, 1, 0, 1, 1)
    tail.attach(Gtk.Label(label=_("越界"), xalign=0.0), 0, 1, 1, 1)
    ab = Gtk.ComboBoxText()
    for key, label in (('clamp', _('拉边（重复边缘像素）')),
                       ('transparent', _('透明（露出下层）')),
                       ('loop', _('循环')),
                       ('black', _('黑'))):
        ab.append(key, label)
    tail.attach(ab, 1, 1, 1, 1)
    left.pack_start(tail, False, False, 0)

    # ---- 右侧：预览 + 输出 ----------------------------------------------
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    outer.pack_start(right, True, True, 0)

    parea = Gtk.DrawingArea()
    parea.set_size_request(PREVIEW_EDGE, 380)
    parea.set_hexpand(True)
    parea.set_vexpand(True)
    right.pack_start(parea, True, True, 0)

    outrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    outrow.pack_start(Gtk.Label(label=_("输出"), xalign=0.0), False, False, 0)
    combo_out = Gtk.ComboBoxText()
    combo_out.append(OUTPUT_FILTER, _("非破坏滤镜（可再改）"))
    combo_out.append(OUTPUT_REPLACE, _("覆盖当前图层"))
    combo_out.append(OUTPUT_NEW, _("复制到新图层"))
    combo_out.set_active_id(OUTPUT_FILTER)
    outrow.pack_start(combo_out, True, True, 0)
    reset = Gtk.Button(label=_("重置"))
    outrow.pack_start(reset, False, False, 0)
    right.pack_start(outrow, False, False, 0)

    # ---- 状态 ------------------------------------------------------------
    ctx = {'rgba': None, 'w': 0, 'h': 0, 'pending': None, 'timer': 0}

    def values():
        out = {
            'k1': k1.get_value(),
            'k2': k2.get_value(),
            'auto-zoom': bool(auto.get_active()),
            'zoom': zoom.get_value(),
            'vignette': vig.get_value(),
            'vignette-midpoint': vmid.get_value(),
            'vignette-feather': vfea.get_value(),
            'ca-red': car.get_value(),
            'ca-blue': cab.get_value(),
            'abyss': ab.get_active_id() or 'clamp',
            'resampling': rs.get_active_id() or 'nohalo',
        }
        return out

    def push_values(src):
        k1.set_value(float(src.get('k1', 0.0)))
        k2.set_value(float(src.get('k2', 0.0)))
        auto.set_active(bool(src.get('auto-zoom', True)))
        zoom.set_value(float(src.get('zoom', 1.0)))
        vig.set_value(float(src.get('vignette', 0.0)))
        vmid.set_value(float(src.get('vignette-midpoint', 0.55)))
        vfea.set_value(float(src.get('vignette-feather', 0.45)))
        car.set_value(float(src.get('ca-red', 0.0)))
        cab.set_value(float(src.get('ca-blue', 0.0)))
        if src.get('abyss'):
            ab.set_active_id(str(src['abyss']))
        if src.get('resampling'):
            rs.set_active_id(str(src['resampling']))

    def draw_preview(_area, cr):
        alloc = parea.get_allocation()
        cr.set_source_rgb(0.16, 0.16, 0.17)
        cr.paint()
        rgba, w, h = ctx['rgba'], ctx['w'], ctx['h']
        if not rgba or not w or not h:
            return False
        scale = min((alloc.width - 16) / float(w),
                    (alloc.height - 16) / float(h))
        scale = max(scale, 0.01)
        dw, dh = w * scale, h * scale
        x = (alloc.width - dw) * 0.5
        y = (alloc.height - dh) * 0.5
        from gi.repository import Gdk
        pb = _pixbuf(rgba, w, h)
        cr.save()
        cr.translate(x, y)
        cr.scale(scale, scale)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0.0, 0.0)
        cr.paint()
        cr.restore()
        cr.set_source_rgba(1, 1, 1, 0.22)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, dw - 1, dh - 1)
        cr.stroke()
        return False

    def refresh_preview():
        try:
            w, h, rgba = preview_rgba(image, drawable, values())
            ctx.update({'rgba': rgba, 'w': w, 'h': h})
        except Exception as exc:
            import traceback
            traceback.print_exc()
            Gimp.message("lens-correction preview: %s" % exc)
        parea.queue_draw()

    def do_refresh():
        ctx['timer'] = 0
        refresh_preview()
        return False

    def schedule(*_a):
        if ctx['timer']:
            GLib.source_remove(ctx['timer'])
        ctx['timer'] = GLib.timeout_add(DEBOUNCE_MS, do_refresh)

    def on_reset(_btn):
        push_values(DEFAULTS)
        schedule()

    for sc in (k1, k2, zoom, vig, vmid, vfea, car, cab):
        sc.connect('value-changed', schedule)
    auto.connect('toggled', schedule)
    rs.connect('changed', schedule)
    ab.connect('changed', schedule)
    reset.connect('clicked', on_reset)
    parea.connect('draw', draw_preview)

    push_values(settings)
    ctx['values'] = values
    ctx['combo_out'] = combo_out
    # 控件句柄：截图脚本要摆一组参数，测试也要能直接读滑杆的值。
    ctx['ctl'] = {'k1': k1, 'k2': k2, 'zoom': zoom, 'auto': auto,
                  'vignette': vig, 'mid': vmid, 'feather': vfea,
                  'ca_red': car, 'ca_blue': cab,
                  'resample': rs, 'abyss': ab}
    ctx['refresh'] = refresh_preview
    refresh_preview()
    return dlg, ctx


def show_dialog(procedure, config, image, drawable):
    dlg, ctx = build_dialog(procedure, config, image, drawable)
    # GTK3 里控件默认不显示，dlg.run() 只 show 对话框自己，不递归 show 子控件。
    dlg.show_all()
    try:
        from gi.repository import GimpUi
        GimpUi.init(procedure.get_name())
        GimpUi.window_set_transient(dlg)
    except Exception:
        pass
    ok = bool(dlg.run())
    settings = ctx['values']()
    output = ctx['combo_out'].get_active_id() if 'combo_out' in ctx else None
    dlg.destroy()
    if not ok:
        return False, None, None
    return True, settings, output


# ---- 过程注册 ---------------------------------------------------------------

def _add_arguments(procedure):
    procedure.add_string_argument(
        "settings", _("Settings"),
        _("JSON object with the operator's own property names: k1, k2, "
          "auto-zoom, zoom, vignette, vignette-midpoint, vignette-feather, "
          "ca-red, ca-blue, abyss, resampling. The dialog writes exactly this "
          "string, so a script can replay it verbatim."),
        "{}", GObject.ParamFlags.READWRITE)
    out = Gimp.Choice.new()
    out.add(OUTPUT_FILTER, 0, _("Live filter (re-editable)"),
            _("Attach as a live filter: pixels stay untouched and re-running "
              "the dialog reads the values back"))
    out.add(OUTPUT_REPLACE, 1, _("Bake into this layer"),
            _("Write the result into the layer pixels"))
    out.add(OUTPUT_NEW, 2, _("Duplicate to a new layer"),
            _("Bake into a copy above the original, leaving it untouched"))
    procedure.add_choice_argument(
        "output", _("Output"), _("Where the result goes"),
        out, OUTPUT_FILTER, GObject.ParamFlags.READWRITE)


def _parse_settings(text):
    data = dict(DEFAULTS)
    try:
        raw = json.loads(text or '{}')
        if isinstance(raw, dict):
            for key, val in raw.items():
                if key in DEFAULTS:
                    data[key] = val
    except Exception:
        pass
    return data


class LensCorrectionPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label(_("镜头校正…"))
        procedure.set_documentation(
            _("Barrel / pincushion distortion, vignetting and lateral "
              "chromatic aberration in one pass"),
            _("The three Lens Correction controls that matter: k1/k2 radial "
              "distortion with an auto scale that keeps the corners in frame, "
              "a radial vignette, and separate red / blue radial shifts for "
              "fringing."),
            name)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        _add_arguments(procedure)
        procedure.add_menu_path("<Image>/SuperMrWang/Distort")
        procedure.add_menu_path("<Layers>/SuperMrWang/Distort")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("没有图层 / no layer selected")))
        drawable = drawables[0]
        if not isinstance(drawable, Gimp.Layer):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("请选一个像素图层（不是通道 / 路径）")))

        try:
            if run_mode == Gimp.RunMode.INTERACTIVE:
                ok, settings, output = show_dialog(procedure, config, image,
                                                   drawable)
                if not ok:
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.CANCEL, None)
            else:
                settings = _parse_settings(config.get_property('settings'))
                output = config.get_property('output') or OUTPUT_FILTER

            if output == OUTPUT_NEW:
                target = drawable.copy()
                image.insert_layer(target, None, 0)
                apply_settings(target, settings, OUTPUT_REPLACE)
            else:
                apply_settings(drawable, settings, output)

            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            import traceback
            traceback.print_exc()
            Gimp.message("lens-correction: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(LensCorrectionPlugin.__gtype__, _sys.argv)
