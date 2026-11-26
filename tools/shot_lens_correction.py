# -*- coding: utf-8 -*-
"""把「镜头校正」的对话框画成 PNG（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/shot_lens_correction.py').read())" --quit

对话框是 toplevel，塞不进 OffscreenWindow，所以直接 cairo 画进 ImageSurface。
"""
import importlib.util
import math
import os
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, Gegl, Gtk

import cairo

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
for cand in (ROOT, os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))):
    if os.path.exists(os.path.join(cand, "plugin", "lens-correction",
                                   "lens-correction.py")):
        ROOT = cand
        break
HERE = os.path.join(ROOT, "tools")
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

spec = importlib.util.spec_from_file_location(
    "lens_correction",
    os.path.join(ROOT, "plugin", "lens-correction", "lens-correction.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def make_scene(w=640, h=480):
    """一张能看出几何与暗角的样图：渐变底 + 网格 + 中心圆环。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    lay = Gimp.Layer.new(img, "DSC_0417.NEF", w, h, Gimp.ImageType.RGBA_IMAGE,
                         100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    img.set_selected_layers([lay])
    cx, cy = w * 0.5, h * 0.5
    data = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            u = x / float(w - 1)
            v = y / float(h - 1)
            r = int(40 + 190 * u)
            g = int(70 + 110 * v)
            b = int(180 - 90 * u + 40 * v)
            # 网格：每 40 px 一条，深灰
            if x % 40 == 0 or y % 40 == 0:
                r, g, b = 28, 30, 34
            # 中心圆环
            d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            if 148 <= d < 156:
                r, g, b = 250, 245, 230
            elif 60 <= d < 66:
                r, g, b = 250, 120, 60
            o = (y * w + x) * 4
            data[o] = max(0, min(255, r))
            data[o + 1] = max(0, min(255, g))
            data[o + 2] = max(0, min(255, b))
            data[o + 3] = 255
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8",
                         bytes(data))
    lay.get_buffer().flush()
    return img, lay


img, lay = make_scene()
dlg, ctx = mod.build_dialog(None, None, img, lay)

# 摆一组看得见效果的参数：轻度去桶形 + 一点暗角 + 一点色差
ctl = ctx['ctl']
ctl['k1'].set_value(0.085)
ctl['vignette'].set_value(-28.0)
ctl['ca_red'].set_value(1.2)
ctl['ca_blue'].set_value(-1.2)

dlg.show_all()
for _ in range(80):
    while Gtk.events_pending():
        Gtk.main_iteration()

w = dlg.get_allocated_width()
h = dlg.get_allocated_height()
print("size", w, h)
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
cr = cairo.Context(surf)
cr.set_source_rgba(0.92, 0.92, 0.92, 1)
cr.paint()
dlg.draw(cr)

out = os.path.join(HERE, "site", "plugin-shots", "lens-correction")
os.makedirs(out, exist_ok=True)
path = os.path.join(out, "dialog.png")
surf.write_to_png(path)
print("wrote", path, os.path.getsize(path) // 1024, "KB")
dlg.destroy()
img.delete()
