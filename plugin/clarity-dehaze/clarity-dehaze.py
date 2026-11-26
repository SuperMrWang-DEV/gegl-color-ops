#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 清晰度 / 去朦胧 / Clarity & Dehaze
 ---------------------------------------------------------------------------
 菜单     SuperMrWang → Color → 清晰度 / 去朦胧…
 过程     lb-plugin-clarity-dehaze
 算子     lb:clarity-dehaze

 Camera Raw「基本」面板上最常拖的两个滑块，一个对话框：

   清晰度  中频局部对比。不是锐化——锐化动的是高频（像素级边缘），清晰度
           动的是几十像素尺度上的明暗过渡，所以树叶、云、皮肤纹理会被
           「打开」，而细小噪点不会被放大。
   去朦胧  暗通道先验反解大气散射。远景发灰是空气把 A 混进了 J：
           I = J·t + A·(1−t)，暗通道估 t、估 A，再解回 J。

 两组参数都落在同一个算子里，像素计算全在 C 里；Python 只负责把滑杆写进
 滤镜参数，所以预览和成品是同一段代码。

 三个必须记住的点：

 · **半径要按预览缩放比缩回去**。半径是像素单位，预览缩到 560 长边之后
   40 px 的低通相当于原图的 160 px，预览看起来会比成品糊得多。所以两个
   半径都乘「预览宽 / 原宽」，并且不小于 2。
 · **不能拿旧亮度做清晰度**。去朦胧改过 RGB，清晰度必须先按新像素重算
   亮度；算子内部就是这么排的（dehaze 在前，clarity 在后各自算 Y）。
 · **保护边缘不是关掉效果**。tanh 压的是「幅度远超 halo 宽度」的那部分，
   也就是硬边缘两侧的过冲；中频细节幅度小，几乎原样通过。

 license  GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

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

PROC = 'lb-plugin-clarity-dehaze'
OP = 'lb:clarity-dehaze'

OUTPUT_FILTER = 'filter'
OUTPUT_REPLACE = 'replace'
OUTPUT_NEW = 'new'

PREVIEW_EDGE = 560
DEBOUNCE_MS = 80

DEFAULTS = {
    'clarity': 0.0,
    'clarity-radius': 40,
    'clarity-protect': 0.35,
    'dehaze': 0.0,
    'dehaze-radius': 15,
    'dehaze-keep': 0.95,
    'dehaze-saturation': 0.0,
}

# 百分比 → 0..1 的倍数关系，用于把「强度」换算成滑杆刻度。
_RADIUS_KEYS = ('clarity-radius', 'dehaze-radius')


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
    filt = find_filter(drawable)
    fresh = filt is None
    if fresh:
        filt = Gimp.DrawableFilter.new(drawable, OP, _("清晰度 / 去朦胧"))
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

    半径是像素单位，缩图后必须乘缩放比，否则预览里的低通半径在原图上
    大了十几倍，看起来像糊了一层。下限 2 是算子的最小值。
    """
    src_w, src_h = drawable.get_width(), drawable.get_height()
    pw, ph = _fit(src_w, src_h, edge)
    scale = pw / float(src_w) if src_w else 1.0

    params = dict(settings)
    for key in _RADIUS_KEYS:
        try:
            params[key] = max(2, int(round(float(params.get(key) or 0) * scale)))
        except Exception:
            params[key] = DEFAULTS[key]

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
        filt = Gimp.DrawableFilter.new(tmp, OP, "clarity preview")
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
    label = Gtk.Label(label=title, xalign=0.0)
    label.set_size_request(124, -1)
    adj = Gtk.Adjustment(value=0.0, lower=lo, upper=hi,
                         step_increment=step, page_increment=step * 10)
    sc = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
    sc.set_digits(digits)
    sc.set_hexpand(True)
    sc.set_value_pos(Gtk.PositionType.RIGHT)
    sc.set_size_request(290, -1)
    grid.attach(label, 0, row, 1, 1)
    grid.attach(sc, 1, row, 1, 1)
    return sc


def _grid(top=6):
    g = Gtk.Grid(row_spacing=6, column_spacing=10,
                 margin_start=12, margin_end=12,
                 margin_top=top, margin_bottom=6)
    g.set_column_homogeneous(False)
    return g


def _hint(grid, row, markup):
    lab = Gtk.Label(xalign=0.0)
    lab.set_line_wrap(True)
    lab.set_markup(markup)
    lab.get_style_context().add_class('dim-label')
    grid.attach(lab, 0, row, 2, 1)
    return lab


def build_dialog(procedure, config, image, drawable):
    """搭界面但不 run()。拆出来是为了无头环境里截图验收。"""
    settings = load_settings(drawable)

    dlg = Gtk.Dialog(title=_("清晰度 / 去朦胧"))
    dlg.set_default_size(950, -1)
    dlg.set_modal(True)
    dlg.set_keep_above(True)
    dlg.add_button(_("取消"), Gtk.ResponseType.CANCEL)
    okb = dlg.add_button(_("应用"), Gtk.ResponseType.OK)
    okb.get_style_context().add_class('suggested-action')

    outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
    outer.set_border_width(10)
    dlg.get_content_area().add(outer)

    # ---- 左侧 ------------------------------------------------------------
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    left.set_size_request(440, -1)
    outer.pack_start(left, False, False, 0)

    f1 = Gtk.Frame(label=_("清晰度 · 中频局部对比"))
    g1 = _grid(8)
    clarity = _slider(g1, 0, _("强度"), -100, 100, 1, digits=0)
    crad = _slider(g1, 1, _("半径 px"), 4, 400, 1, digits=0)
    cprot = _slider(g1, 2, _("边缘保护"), 0.0, 1.0, 0.01, digits=2)
    _hint(g1, 3, _("强度为正：纹理被「打开」；为负：往柔化方向走。\n"
                   "半径决定多宽的明暗过渡算中频——40 px 左右接近 Camera Raw，\n"
                   "边缘保护压住硬边两侧的亮边/黑边，越大越平。"))
    f1.add(g1)
    left.pack_start(f1, False, False, 0)

    f2 = Gtk.Frame(label=_("去朦胧 · 暗通道先验"))
    g2 = _grid(8)
    dehaze = _slider(g2, 0, _("强度"), -100, 100, 1, digits=0)
    drad = _slider(g2, 1, _("窗口 px"), 4, 200, 1, digits=0)
    dkeep = _slider(g2, 2, _("保留雾量"), 0.5, 1.0, 0.01, digits=2)
    dsat = _slider(g2, 3, _("饱和补偿 %"), -100, 100, 1, digits=0)
    _hint(g2, 4, _("强度为负等于<b>加雾</b>（做纵深用）。窗口要比雾里最亮的\n"
                   "东西大，否则透射率会跟着物体走而不是跟着远近走。"))
    f2.add(g2)
    left.pack_start(f2, False, False, 0)

    hint = Gtk.Label(xalign=0.0)
    hint.set_line_wrap(True)
    hint.get_style_context().add_class('dim-label')
    hint.set_markup(_("两组参数落在同一个算子上：先去雾、再清晰度，一次算出，\n"
                      "预览与成品是同一段代码。"))
    left.pack_start(hint, False, False, 0)

    # ---- 右侧：预览 + 输出 ----------------------------------------------
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    outer.pack_start(right, True, True, 0)

    parea = Gtk.DrawingArea()
    parea.set_size_request(PREVIEW_EDGE, 400)
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
    ctx = {'rgba': None, 'w': 0, 'h': 0, 'timer': 0}

    def values():
        return {
            'clarity': float(clarity.get_value()),
            'clarity-radius': int(round(crad.get_value())),
            'clarity-protect': float(cprot.get_value()),
            'dehaze': float(dehaze.get_value()),
            'dehaze-radius': int(round(drad.get_value())),
            'dehaze-keep': float(dkeep.get_value()),
            'dehaze-saturation': float(dsat.get_value()),
        }

    def push_values(src):
        clarity.set_value(float(src.get('clarity', 0.0)))
        crad.set_value(float(src.get('clarity-radius', 40)))
        cprot.set_value(float(src.get('clarity-protect', 0.35)))
        dehaze.set_value(float(src.get('dehaze', 0.0)))
        drad.set_value(float(src.get('dehaze-radius', 15)))
        dkeep.set_value(float(src.get('dehaze-keep', 0.95)))
        dsat.set_value(float(src.get('dehaze-saturation', 0.0)))

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
            Gimp.message("clarity-dehaze preview: %s" % exc)
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

    for sc in (clarity, crad, cprot, dehaze, drad, dkeep, dsat):
        sc.connect('value-changed', schedule)
    reset.connect('clicked', on_reset)
    parea.connect('draw', draw_preview)

    push_values(settings)
    ctx['values'] = values
    ctx['combo_out'] = combo_out
    ctx['ctl'] = {'clarity': clarity, 'cradius': crad, 'cprotect': cprot,
                  'dehaze': dehaze, 'dradius': drad, 'keep': dkeep,
                  'sat': dsat}
    ctx['refresh'] = refresh_preview
    refresh_preview()
    return dlg, ctx


def show_dialog(procedure, config, image, drawable):
    dlg, ctx = build_dialog(procedure, config, image, drawable)
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
        _("JSON object with the operator's own property names: clarity, "
          "clarity-radius, clarity-protect, dehaze, dehaze-radius, "
          "dehaze-keep, dehaze-saturation. The dialog writes exactly this "
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


class ClarityDehazePlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label(_("清晰度 / 去朦胧…"))
        procedure.set_documentation(
            _("Mid-frequency local contrast and dark-channel dehazing"),
            _("Clarity opens up mid-frequency texture without touching fine "
              "detail; Dehaze inverts atmospheric scattering with the dark "
              "channel prior. Both live in one operator, so preview and result "
              "are the same code."),
            name)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        _add_arguments(procedure)
        procedure.add_menu_path("<Image>/SuperMrWang/Color")
        procedure.add_menu_path("<Layers>/SuperMrWang/Color")
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
            Gimp.message("clarity-dehaze: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(ClarityDehazePlugin.__gtype__, _sys.argv)
