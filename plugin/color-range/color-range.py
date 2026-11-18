#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · Color Range（色彩范围）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   「色彩范围」的**真对话框**：选什么，下面就只显示什么。

           GEGL 算子的参数是静态的：lb:color-mask-select 有四个限值属性
           （shadows / highlights / midtone 各一组），GIMP 的通用 GEGL 对话框
           会把它们全摆出来，而且切「选择颜色」时不会跟着变——选「红色」时
           那四根 0–255 的滑杆照样占着界面，选「高光」时又看不出范围是
           192–255 还是整段。这个插件用 GTK 自己搭对话框，按模式换参数页：
           色系只给容差，高光/阴影只给一根「范围」，中间调给上下限。

           像素运算仍然交给算子 lb:color-mask-select，本插件只负责界面与
           「把参数摆对」。Real dialog for Color Range: the mode picks which
           controls exist, and each mode starts at its own default. The
           pixels are still computed by lb:color-mask-select.

 menu      SuperMrWang → Mask → Color Range（色彩范围）
           图层右键 → SuperMrWang → Color Range

 usage     选中栅格图层 → 菜单项 → 选模式 → 拖参数（画面上红色叠加实时预览）
           → 确定。确定时把蒙版写进图层 alpha（预览叠加不会烤进去）。

           每个模式各记各的值：切到「高光」看到的是 192，切到「阴影」是 64，
           切到「中间调」是 64 / 192，切回色系还是它自己的容差。

 note      与菜单里直接选 lb:color-mask-select 的区别：那边是 GEGL 通用对话框
           （四根限值杆常驻、不随模式切换）；这边是定制界面（只显示相关参数、
           切换即回到该模式默认）。两者算出来的像素完全一致——同一份算子。

           确定后是**一次性应用**（蒙版合并进 alpha，不像非破坏滤镜那样还能
           回改）。想保留可回改，用菜单里的算子版本挂成滤镜。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, Gegl, GLib
from gi.repository import Gtk
from gi.repository import Gdk

OP = 'lb:color-mask-select'


def _(message):
    return GLib.dgettext(None, message)


# ---- 模式表 / the mode table -------------------------------------------------
#
# (op 里的枚举值, 界面标签, 控件类型, 该模式的默认范围)
#
# 控件类型决定这个模式在对话框里显示哪几根滑杆：
#   chroma  色系预设 —— 只有容差与最低彩度（没有「范围」，范围是色相环）
#   custom  自定颜色 —— 取色按钮 + 容差 + 最低彩度
#   white   高光 —— 一根「范围」= 从哪个亮度起算（默认 192）
#   black   阴影 —— 一根「范围」= 到哪个亮度为止（默认 64）
#   gray    中间调 —— 两根：下限 / 上限（默认 64 / 192）
#
# 默认范围就是算子里的默认值，逐值相同，切回来时看到的就是这一组。

MODES = [
    ('red',     _("红色 / Red"),        'chroma'),
    ('yellow',  _("黄色 / Yellow"),     'chroma'),
    ('green',   _("绿色 / Green"),      'chroma'),
    ('cyan',    _("青色 / Cyan"),       'chroma'),
    ('blue',    _("蓝色 / Blue"),       'chroma'),
    ('magenta', _("洋红 / Magenta"),    'chroma'),
    ('white',   _("高光 / Highlights"),  'white'),
    ('black',   _("阴影 / Shadows"),     'black'),
    ('gray',    _("中间调 / Midtones"),  'gray'),
    ('custom',  _("自定颜色 / Picked"),   'custom'),
]

DEFAULTS = {
    'fuzziness': 50.0,
    'shadows': 64,
    'highlights': 192,
    'midtone_low': 64,
    'midtone_high': 192,
    'saturation_min': 0.0,
    'feather': 10.0,
}

def _mode_kind(mode):
    for value, _label, kind in MODES:
        if value == mode:
            return kind
    return 'chroma'


# ---- 参数打包 / parameter bundle --------------------------------------------

def defaults_for(mode):
    """某个模式在界面上的那组默认值。"""
    kind = _mode_kind(mode)
    out = {
        'mask_mode': mode,
        'fuzziness': DEFAULTS['fuzziness'],
        'feather': DEFAULTS['feather'],
        'saturation_min': DEFAULTS['saturation_min'],
        'custom_color': (1.0, 0.0, 0.0, 1.0),
        'invert': False,
        'preview_red_mask': True,
    }
    if kind == 'white':
        out['highlights_limit'] = DEFAULTS['highlights']
    elif kind == 'black':
        out['shadows_limit'] = DEFAULTS['shadows']
    elif kind == 'gray':
        out['midtone_low'] = DEFAULTS['midtone_low']
        out['midtone_high'] = DEFAULTS['midtone_high']
    return out


def _gegl_color(rgba):
    color = Gegl.Color()
    color.set_rgba(float(rgba[0]), float(rgba[1]),
                   float(rgba[2]), float(rgba[3]) if len(rgba) > 3 else 1.0)
    return color


def push_config(filt, params):
    """把一整套参数写进滤镜配置并刷新。"""
    cfg = filt.get_config()
    cfg.set_property('mask-mode', params['mask_mode'])
    cfg.set_property('fuzziness', float(params['fuzziness']))
    cfg.set_property('feather', float(params['feather']))
    cfg.set_property('saturation-min', float(params['saturation_min']))
    cfg.set_property('invert', bool(params['invert']))
    cfg.set_property('preview-red-mask', bool(params['preview_red_mask']))
    if 'custom_color' in params:
        cfg.set_property('custom-color', _gegl_color(params['custom_color']))
    if 'shadows_limit' in params:
        cfg.set_property('shadows-limit', int(params['shadows_limit']))
    if 'highlights_limit' in params:
        cfg.set_property('highlights-limit', int(params['highlights_limit']))
    if 'midtone_low' in params:
        cfg.set_property('midtone-low', int(params['midtone_low']))
    if 'midtone_high' in params:
        cfg.set_property('midtone-high', int(params['midtone_high']))
    filt.update()


def _require_op(layer):
    try:
        probe = Gimp.DrawableFilter.new(layer, OP, "probe")
    except Exception:
        raise RuntimeError(
            _("缺少算子 lb:color-mask-select（色彩范围的像素引擎）。"
              "先装 dist 里的 Windows/Linux 算子包，或 ./build.sh 自编。"
              " / lb:color-mask-select is not installed"))
    try:
        probe.delete()
    except Exception:
        pass


# ---- 无界面路径 / the non-interactive path ----------------------------------

def _check_target(layer):
    if layer is None:
        raise RuntimeError(_("没有可以处理的图层 / no layer to work on"))
    if layer.is_group():
        raise RuntimeError(
            _("图层组没有像素：请选一个栅格图层"
              " / a layer group has no pixels of its own"))


def apply_once(image, layer, params):
    """一次性把蒙版写进 alpha（预览叠加不烤进去）。"""
    _check_target(layer)
    _require_op(layer)
    if not layer.has_alpha():
        layer.add_alpha()
    filt = Gimp.DrawableFilter.new(layer, OP, _("色彩范围"))
    params = dict(params)
    params['preview_red_mask'] = False
    push_config(filt, params)
    layer.append_filter(filt)
    layer.merge_filter(filt)
    Gimp.displays_flush()


# ---- 对话框 / the dialog ----------------------------------------------------

def _scale(lo, hi, value, step=1.0):
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    scale.set_value(value)
    scale.set_digits(0)
    scale.set_draw_value(True)
    scale.set_value_pos(Gtk.PositionType.RIGHT)
    scale.set_hexpand(True)
    scale.set_size_request(220, -1)
    return scale


class ColorRangeDialog(Gtk.Dialog):

    def __init__(self, image, layer, filt):
        Gtk.Dialog.__init__(self, title=_("色彩范围 / Color Range"))
        self.image = image
        self.layer = layer
        self.filt = filt
        self._pending = 0

        self.set_modal(True)
        self.set_default_size(430, -1)
        self.add_button(_("取消"), Gtk.ResponseType.CANCEL)
        self.add_button(_("确定"), Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        area = self.get_content_area()
        area.set_spacing(8)
        area.set_border_width(10)

        # —— 选择模式 ——
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        label = Gtk.Label(label=_("选择"))
        label.set_xalign(0.0)
        label.set_size_request(74, -1)
        head.pack_start(label, False, False, 0)
        self.combo = Gtk.ComboBoxText()
        self.combo.set_hexpand(True)
        for value, text, _kind in MODES:
            self.combo.append(value, text)
        head.pack_start(self.combo, True, True, 0)
        area.pack_start(head, False, False, 0)

        # —— 每个模式一页，各自从自己的默认值起步 ——
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.set_hexpand(True)
        self.state = {}          # mode → dict(控件)
        for value, _text, kind in MODES:
            self.stack.add_named(self._build_page(value, kind), value)
        area.pack_start(self.stack, False, False, 0)

        area.pack_start(Gtk.Separator(), False, False, 4)

        # —— 公共参数 ——
        common = Gtk.Grid()
        common.set_column_spacing(10)
        common.set_row_spacing(6)
        common.set_hexpand(True)
        r = 0
        self.feather = self._row(common, r, _("羽化"), _scale(0, 100, DEFAULTS['feather']))
        r += 1
        area.pack_start(common, False, False, 0)

        checks = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.invert = Gtk.CheckButton(label=_("反相"))
        self.preview = Gtk.CheckButton(label=_("红色叠加预览"))
        self.preview.set_active(True)
        checks.pack_start(self.invert, False, False, 0)
        checks.pack_start(self.preview, False, False, 0)
        area.pack_start(checks, False, False, 0)

        hint = Gtk.Label()
        hint.set_xalign(0.0)
        hint.set_line_wrap(True)
        hint.set_markup(_("<small>确定后蒙版写入图层 alpha（红色叠加只用于预览，不会烤进去）。</small>"))
        area.pack_start(hint, False, False, 0)

        # —— 信号 ——
        self.combo.connect('changed', self._on_mode_changed)
        self.feather.connect('value-changed', self._queue)
        self.invert.connect('toggled', self._queue)
        self.preview.connect('toggled', self._queue)
        for mode_state in self.state.values():
            for widget in mode_state['signals']:
                widget.connect('value-changed', self._queue)

        self.combo.set_active_id('red')
        self._on_mode_changed(self.combo)

        area.show_all()

    # —— 一页参数 ——
    def _row(self, grid, row, text, widget):
        label = Gtk.Label(label=text)
        label.set_xalign(0.0)
        label.set_size_request(74, -1)
        grid.attach(label, 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)
        return widget

    def _build_page(self, mode, kind):
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(6)
        grid.set_hexpand(True)
        st = {'signals': [], 'kind': kind}
        r = 0

        if kind in ('chroma', 'custom'):
            st['fuzziness'] = self._row(
                grid, r, _("颜色容差"),
                _scale(0, 200, DEFAULTS['fuzziness']))
            st['signals'].append(st['fuzziness'])
            r += 1
            if kind == 'custom':
                self.color_button = Gtk.ColorButton()
                rgba = Gdk.RGBA()
                rgba.red, rgba.green, rgba.blue, rgba.alpha = 1.0, 0.0, 0.0, 1.0
                self.color_button.set_rgba(rgba)
                self.color_button.set_use_alpha(False)
                self.color_button.connect('color-set', self._queue)
                self._row(grid, r, _("自定颜色"), self.color_button)
                st['color_button'] = self.color_button
                r += 1
            st['saturation_min'] = self._row(
                grid, r, _("最低彩度"),
                _scale(0, 100, DEFAULTS['saturation_min']))
            st['signals'].append(st['saturation_min'])
        elif kind == 'white':
            st['highlights_limit'] = self._row(
                grid, r, _("范围"), _scale(0, 255, DEFAULTS['highlights']))
            st['signals'].append(st['highlights_limit'])
            r += 1
            st['fuzziness'] = self._row(
                grid, r, _("颜色容差"), _scale(0, 200, DEFAULTS['fuzziness']))
            st['signals'].append(st['fuzziness'])
            note = Gtk.Label()
            note.set_xalign(0.0)
            note.set_markup(_("<small>亮度 ≥ 这个值算高光，往下是过渡带。</small>"))
            r += 1
            grid.attach(note, 1, r, 1, 1)
        elif kind == 'black':
            st['shadows_limit'] = self._row(
                grid, r, _("范围"), _scale(0, 255, DEFAULTS['shadows']))
            st['signals'].append(st['shadows_limit'])
            r += 1
            st['fuzziness'] = self._row(
                grid, r, _("颜色容差"), _scale(0, 200, DEFAULTS['fuzziness']))
            st['signals'].append(st['fuzziness'])
            note = Gtk.Label()
            note.set_xalign(0.0)
            note.set_markup(_("<small>亮度 ≤ 这个值算阴影，往上是过渡带。</small>"))
            r += 1
            grid.attach(note, 1, r, 1, 1)
        elif kind == 'gray':
            st['midtone_low'] = self._row(
                grid, r, _("范围下限"), _scale(0, 255, DEFAULTS['midtone_low']))
            st['signals'].append(st['midtone_low'])
            r += 1
            st['midtone_high'] = self._row(
                grid, r, _("范围上限"), _scale(0, 255, DEFAULTS['midtone_high']))
            st['signals'].append(st['midtone_high'])
            r += 1
            st['fuzziness'] = self._row(
                grid, r, _("颜色容差"), _scale(0, 200, DEFAULTS['fuzziness']))
            st['signals'].append(st['fuzziness'])
        self.state[mode] = st
        return grid

    # —— 切换模式 ——
    def _on_mode_changed(self, combo):
        mode = combo.get_active_id()
        if mode:
            self.stack.set_visible_child_name(mode)
            self._queue()

    # —— 预览（合并 60 ms 内的连续改动）——
    def _queue(self, *_args):
        if self._pending:
            return
        self._pending = GLib.timeout_add(60, self._flush)

    def _flush(self):
        self._pending = 0
        try:
            push_config(self.filt, self.collect())
        except Exception as exc:
            Gimp.message("color-range preview: %s" % exc)
        return False

    def collect(self):
        mode = self.combo.get_active_id() or 'red'
        kind = _mode_kind(mode)
        st = self.state[mode]
        params = defaults_for(mode)
        params['feather'] = self.feather.get_value()
        params['invert'] = self.invert.get_active()
        params['preview_red_mask'] = self.preview.get_active()
        for key in ('fuzziness', 'saturation_min', 'highlights_limit',
                    'shadows_limit', 'midtone_low', 'midtone_high'):
            if key in st:
                params[key] = st[key].get_value()
        if kind == 'custom' and 'color_button' in st:
            rgba = st['color_button'].get_rgba()
            params['custom_color'] = (rgba.red, rgba.green, rgba.blue, 1.0)
        return params



# ---- 动作 / the action ------------------------------------------------------

def color_range(image, layer):
    """挂预览滤镜 → 弹对话框 → 确定则合并进 alpha，取消则撤掉。"""
    _check_target(layer)
    _require_op(layer)

    image.undo_group_start()
    added_alpha = False
    try:
        if not layer.has_alpha():
            layer.add_alpha()
            added_alpha = True

        filt = Gimp.DrawableFilter.new(layer, OP, _("色彩范围（预览）"))
        push_config(filt, defaults_for('red'))
        layer.append_filter(filt)
        Gimp.displays_flush()

        dialog = ColorRangeDialog(image, layer, filt)
        response = dialog.run()
        params = dialog.collect() if response == Gtk.ResponseType.OK else None
        dialog.destroy()

        if params is None:
            filt.delete()
            Gimp.displays_flush()
            if added_alpha:
                image.undo_group_end()
                try:
                    image.undo()
                except Exception:
                    pass
                return False
            image.undo_group_end()
            return False

        params['preview_red_mask'] = False
        push_config(filt, params)
        layer.merge_filter(filt)
        Gimp.displays_flush()
    except Exception:
        try:
            image.undo_group_end()
        except Exception:
            pass
        raise
    image.undo_group_end()
    return True


# ---- 程序包装 / procedure wrapper ------------------------------------------

class ColorRangePlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-color-range']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("Color Range（色彩范围）"))
        procedure.add_menu_path("<Image>/SuperMrWang/Mask")
        procedure.add_menu_path("<Layers>/SuperMrWang")

        procedure.set_documentation(
            _("色彩范围的定制对话框：选哪种颜色，下面就只显示那种颜色的参数，"
              "切换时回到该模式自己的默认值（高光 192、阴影 64、中间调 64/192）。"
              "确定后蒙版写进图层 alpha。"),
            _("A custom Color Range dialog: the mode picks which controls exist, "
              "and each mode starts at its own default (highlights 192, "
              "shadows 64, midtones 64/192). The mask lands in the layer alpha."),
            name)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        layer = drawables[0]
        try:
            if run_mode == Gimp.RunMode.INTERACTIVE:
                color_range(image, layer)
            else:
                apply_once(image, layer, defaults_for('red'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("color-range: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(ColorRangePlugin.__gtype__, sys.argv)
