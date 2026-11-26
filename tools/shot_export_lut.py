# -*- coding: utf-8 -*-
"""把「导出 3D LUT」的对话框画成 PNG（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/shot_export_lut.py').read())" --quit

对话框是 toplevel，塞不进 OffscreenWindow，所以直接 cairo 画进 ImageSurface。
"""
import importlib.util
import os
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, Gtk

import cairo

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
for cand in (ROOT, os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))):
    if os.path.exists(os.path.join(cand, "plugin", "export-lut",
                                   "export-lut.py")):
        ROOT = cand
        break
HERE = os.path.join(ROOT, "tools")
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

spec = importlib.util.spec_from_file_location(
    "export_lut", os.path.join(ROOT, "plugin", "export-lut", "export-lut.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# 造一张带三个滤镜（含一个空间算子）的图层，截图里就能看到「近似」标记
img = Gimp.Image.new_with_precision(640, 480, Gimp.ImageBaseType.RGB,
                                    Gimp.Precision.U8_PERCEPTUAL)
lay = Gimp.Layer.new(img, "IMG_2041.CR3", 640, 480, Gimp.ImageType.RGBA_IMAGE,
                     100.0, Gimp.LayerMode.NORMAL)
img.insert_layer(lay, None, 0)
img.set_selected_layers([lay])
for op, props in (("gimp:brightness-contrast", {"brightness": 0.06}),
                  ("lb:lab-levels", {"L-out-white": 92.0}),
                  ("lb:unsharp-mask", {"radius": 3.0, "amount": 0.4})):
    f = Gimp.DrawableFilter.new(lay, op, op)
    c = f.get_config()
    for k, v in props.items():
        c.set_property(k, v)
    lay.append_filter(f)

rows = mod._stack_rows(lay)
print("stack:", rows)

dlg, combo, entry = mod.build_dialog(img, lay, rows)
entry.set_text("C:/Users/Administrator/Pictures/IMG_2041-grade.cube")
while Gtk.events_pending():
    Gtk.main_iteration()

w = dlg.get_allocated_width()
h = dlg.get_allocated_height()
print("size", w, h)
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
cr = cairo.Context(surf)
cr.set_source_rgba(1, 1, 1, 1)
cr.paint()
dlg.draw(cr)

out = os.path.join(HERE, "site", "plugin-shots", "export-lut")
os.makedirs(out, exist_ok=True)
path = os.path.join(out, "dialog.png")
surf.write_to_png(path)
print("wrote", path, os.path.getsize(path) // 1024, "KB")
dlg.destroy()
img.delete()
