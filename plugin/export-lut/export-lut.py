#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 导出 3D LUT —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把当前图层挂着的非破坏滤镜栈，烘成一个 .cube（Adobe Cube /
           Iridas Cube）。之后这份调色就能脱离 GIMP 工程单独走：给视频、
           给别的图、给 lb:color-lookup，甚至给达芬奇和剪映。
           Bake the layer's non-destructive filter stack into a .cube, so the
           grade can travel without the project.

 menu      SuperMrWang → Export → 3D LUT…
           图层右键 → SuperMrWang → Export → 3D LUT…

 usage     选中挂着滤镜的图层 → 菜单项 → 选尺寸（17 / 33 / 65）→ 选输出路径
           → 导出。对话框顶部会把栈里的算子列出来；带「近似」标记的是
           模糊 / 变形 / 降噪这类看邻居像素的算子，烘成 LUT 只能近似。

           尺寸怎么选：
             17³  最省，粗调色够用，文件约 60 KB
             33³  默认，和大多数调色软件一致
             65³  曲线很陡（比如强力 S 曲线、局部色相压缩）才需要

 note      实现照 RawTherapee 的 CubeLUT（PR #7676）与 OpenColorIO 的
           FileFormatIridasCube::bake()：都先造一张「单位图」，让整条管线
           过一遍，再按红变化最快的顺序写成 .cube。这里单位图是
           宽 size²、高 size，像素 (x=g·size+r, y=b) 编码 (r,g,b)。

           只有逐像素算子能被 LUT 完整表示。含空间算子的栈照样能导，
           但结果只是近似——导出后建议用 lb:color-lookup 贴回原图标尺看一眼。

           图层上有蒙版时，蒙版会让滤镜只作用在一部分像素上，烘出来没有
           意义，所以遇到蒙版会先提示、且只在副本上摘掉蒙版（原图不动）。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, GLib
from gi.repository import Gtk

# _shared 在仓库里与插件目录并排，装成单文件时在同一层，两处都试。
_here = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(_here, '_shared'),
              os.path.normpath(os.path.join(_here, '..', '_shared'))):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.append(_cand)
try:
    from lb_i18n import _
except Exception:                        # helper 不在：保持可用，只是不翻译
    def _(message):
        return GLib.dgettext(None, message)

import lut_bake as LB                     # noqa: E402

PROC = 'lb-plugin-export-lut'
SIZES = (17, 33, 65)


def _stack_rows(layer):
    """把滤镜栈整理成显示用的行：[(算子名, 是否近似), …]，顶在上。"""
    rows = []
    for name in LB.filter_names(layer):
        rows.append((LB.short_op(name), LB.is_spatial(name)))
    return rows


class ExportLutPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        procedure.set_documentation(
            "Bake the layer's filter stack into a 3D LUT (.cube)",
            "把当前图层的滤镜栈烘成一个 .cube（Adobe Cube）",
            name)
        procedure.set_menu_label(_("导出 3D LUT…"))
        procedure.add_menu_path("<Image>/SuperMrWang/Export")
        procedure.add_menu_path("<Layers>/SuperMrWang/Export")
        return procedure

    # ------------------------------------------------------------------ run
    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(_("没有图层")))

        layer = drawables[0]
        if not isinstance(layer, Gimp.Layer):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("请选一个像素图层（不是通道 / 路径）")))

        rows = _stack_rows(layer)
        if not rows:
            Gimp.message(_("图层「%s」上没有滤镜。\n\n"
                           "这个命令是把滤镜栈烘成 LUT，所以先给它挂上调整"
                           "（菜单 Colors / Filters 里的算子会以非破坏滤镜的"
                           "形式挂在图层上），再来导出。") % layer.get_name())
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(_("没有滤镜")))

        if run_mode != Gimp.RunMode.INTERACTIVE:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("这个命令需要交互界面（要选尺寸和路径）")))

        size, path = _ask(image, layer, rows)
        if not path:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, None)

        t0 = time.time()
        try:
            spatial = LB.bake_to_cube(image, layer, path, size)
        except Exception as exc:
            Gimp.message(_("导出失败：%s") % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))

        note = _("已导出 %(name)s\n\n%(n)d 个格点（%(s)d³），%(size)s KB，用时 %(t).2f 秒")
        note = note % {'name': os.path.basename(path), 'n': size ** 3,
                       's': size,
                       'size': '%.0f' % (os.path.getsize(path) / 1024.0),
                       't': time.time() - t0}
        if spatial:
            note += "\n\n" + _("注意：栈里有 %s，它们看邻居像素，"
                               "烘成 LUT 后只是近似。") % "、".join(
                                   LB.short_op(x) for x in spatial)
        Gimp.message(note)
        return procedure.new_return_values(
            Gimp.PDBStatusType.SUCCESS, GLib.Error())


# ------------------------------------------------------------------- 对话框

def _ask(image, layer, rows):
    """选尺寸 + 输出路径。返回 (size, path)；取消时 path 为 None。"""
    dlg, combo, entry = build_dialog(image, layer, rows)
    path = None
    if dlg.run() == Gtk.ResponseType.OK:
        path = entry.get_text().strip()
        if path and not path.lower().endswith('.cube'):
            path += '.cube'
        if not path:
            Gimp.message(_("没给输出路径，没有导出。"))
    size = int(combo.get_active_id() or 33)
    dlg.destroy()
    return size, path


def build_dialog(image, layer, rows):
    """搭界面但不 run()。单独拆出来是为了能在无头环境里截图验收。"""
    dlg = Gtk.Dialog(title=_("导出 3D LUT"))
    dlg.set_default_size(560, -1)
    dlg.set_modal(True)
    dlg.set_keep_above(True)
    dlg.add_button(_("取消"), Gtk.ResponseType.CANCEL)
    okb = dlg.add_button(_("导出"), Gtk.ResponseType.OK)
    okb.get_style_context().add_class("suggested-action")

    box = dlg.get_content_area()
    box.set_margin_start(18)
    box.set_margin_end(18)
    box.set_margin_top(14)
    box.set_margin_bottom(6)
    box.set_spacing(10)

    head = Gtk.Label()
    head.set_xalign(0)
    head.set_line_wrap(True)
    spatial_n = sum(1 for _, s in rows if s)
    head.set_markup(
        _("<b>图层「%s」</b> · %d 个滤镜%s") % (
            GLib.markup_escape_text(layer.get_name(), -1), len(rows),
            _("（其中 %d 个是空间算子）") % spatial_n if spatial_n else ""))
    box.pack_start(head, False, False, 0)

    # 栈清单：顶在上；近似的用灰字标出来
    stack = Gtk.Label()
    stack.set_xalign(0)
    stack.set_line_wrap(True)
    parts = []
    for name, approx in rows:
        if approx:
            parts.append('<span foreground="#c0616b">%s · 近似</span>'
                         % GLib.markup_escape_text(name, -1))
        else:
            parts.append(GLib.markup_escape_text(name, -1))
    stack.set_markup("  →  ".join(parts))
    box.pack_start(stack, False, False, 0)

    # 尺寸
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    lab = Gtk.Label(label=_("LUT 尺寸"))
    lab.set_xalign(0)
    lab.set_size_request(90, -1)
    row.pack_start(lab, False, False, 0)
    combo = Gtk.ComboBoxText()
    for s in SIZES:
        hint = {17: _("%d³ · 最省，粗调色够用"),
                33: _("%d³ · 默认，通用"),
                65: _("%d³ · 曲线很陡才需要")}[s]
        combo.append(str(s), hint % s)
    combo.set_active(1)
    row.pack_start(combo, False, False, 0)
    box.pack_start(row, False, False, 0)

    # 路径
    row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    lab2 = Gtk.Label(label=_("输出文件"))
    lab2.set_xalign(0)
    lab2.set_size_request(90, -1)
    row2.pack_start(lab2, False, False, 0)
    entry = Gtk.Entry()
    entry.set_hexpand(True)
    base = os.path.splitext(os.path.basename(image.get_name() or ''))[0]
    entry.set_text(os.path.join(
        GLib.get_home_dir(),
        (base or 'grade') + '.cube'))
    row2.pack_start(entry, True, True, 0)
    browse = Gtk.Button(label=_("浏览…"))
    row2.pack_start(browse, False, False, 0)
    box.pack_start(row2, False, False, 0)

    tip = Gtk.Label()
    tip.set_xalign(0)
    tip.set_line_wrap(True)
    tip.set_markup(_("<small>只有逐像素算子能被 LUT 完整表示。"
                     "模糊、变形、降噪、图层样式这些会变成近似。"
                     "原图不会被修改。</small>"))
    box.pack_start(tip, False, False, 0)

    def on_browse(_btn):
        fc = Gtk.FileChooserDialog(
            title=_("保存为 .cube"), transient_for=dlg,
            action=Gtk.FileChooserAction.SAVE)
        fc.add_buttons(_("取消"), Gtk.ResponseType.CANCEL,
                       _("选择"), Gtk.ResponseType.ACCEPT)
        fc.set_do_overwrite_confirmation(True)
        flt = Gtk.FileFilter()
        flt.set_name(_("Adobe Cube LUT (*.cube)"))
        flt.add_pattern("*.cube")
        fc.add_filter(flt)
        cur = entry.get_text().strip()
        if cur:
            fc.set_filename(cur)
        if fc.run() == Gtk.ResponseType.ACCEPT:
            entry.set_text(fc.get_filename())
        fc.destroy()

    browse.connect("clicked", on_browse)
    dlg.show_all()
    return dlg, combo, entry


if __name__ == '__main__':
    Gimp.main(ExportLutPlugin.__gtype__, sys.argv)
