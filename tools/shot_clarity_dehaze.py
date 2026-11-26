# -*- coding: utf-8 -*-
"""把「清晰度 / 去朦胧」的对话框画成 PNG（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/shot_clarity_dehaze.py').read())" --quit

对话框是 toplevel，塞不进 OffscreenWindow，所以直接 cairo 画进 ImageSurface。
样图刻意做成「远处有雾、近处有纹理」，这样两个滑块的效果在预览里都看得见。
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
    if os.path.exists(os.path.join(cand, "plugin", "clarity-dehaze",
                                   "clarity-dehaze.py")):
        ROOT = cand
        break
HERE = os.path.join(ROOT, "tools")
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

spec = importlib.util.spec_from_file_location(
    "clarity_dehaze",
    os.path.join(ROOT, "plugin", "clarity-dehaze", "clarity-dehaze.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _hash2(ix, iy):
    return (math.sin(ix * 127.1 + iy * 311.7) * 43758.5453) % 1.0


def _vnoise(x, y, scale):
    """双线性插值的值噪声：比 sin 叠加自然，不会有规则条纹。"""
    fx, fy = x / scale, y / scale
    ix, iy = int(fx), int(fy)
    tx, ty = fx - ix, fy - iy
    tx = tx * tx * (3.0 - 2.0 * tx)
    ty = ty * ty * (3.0 - 2.0 * ty)
    a = _hash2(ix, iy)
    b = _hash2(ix + 1, iy)
    c = _hash2(ix, iy + 1)
    d = _hash2(ix + 1, iy + 1)
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty


def make_scene(w=640, h=480):
    """三层山脊（越远雾越厚）+ 近处带纹理的草坡。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    lay = Gimp.Layer.new(img, "DSC_0912.NEF", w, h, Gimp.ImageType.RGBA_IMAGE,
                         100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    img.set_selected_layers([lay])
    horizon = int(h * 0.52)
    air = (208, 216, 224)
    data = bytearray(w * h * 4)

    for y in range(h):
        for x in range(w):
            # 山脊高度：三条不同频率的平滑曲线，越远越靠上
            r1 = horizon * 0.40 + 26 * math.sin(x * 0.0085 + 0.6)
            r2 = horizon * 0.66 + 20 * math.sin(x * 0.013 + 2.4)
            r3 = horizon * 0.90 + 14 * math.sin(x * 0.019 + 4.1)

            # 雾随距离连续变薄：按层跳 t 会在山脊之间留下硬灰带。
            t = 0.40 + 0.55 * min(1.0, y / float(max(horizon, 1)))

            if y < r1:
                k = y / max(r1, 1.0)
                jr, jg, jb = (88 + 66 * k, 126 + 58 * k, 174 + 40 * k)
            elif y < r2:
                shade = 0.85 + 0.15 * _vnoise(x, y, 40.0)
                jr, jg, jb = (104 * shade, 120 * shade, 128 * shade)
            elif y < r3:
                shade = 0.80 + 0.20 * _vnoise(x, y, 26.0)
                jr, jg, jb = (70 * shade, 92 * shade, 78 * shade)
            else:
                tex = (0.50 * _vnoise(x, y, 19.0) +
                       0.32 * _vnoise(x, y, 7.0) +
                       0.18 * _vnoise(x, y, 3.0))
                tex = max(0.0, min(1.0, tex))
                near = 1.0 - min(1.0, (y - horizon) / float(h - horizon)) * 0.45
                jr = (52 + 78 * tex) * near
                jg = (86 + 84 * tex) * near
                jb = (44 + 50 * tex) * near
                t = 0.94

            o = (y * w + x) * 4
            data[o] = int(round(jr * t + air[0] * (1.0 - t)))
            data[o + 1] = int(round(jg * t + air[1] * (1.0 - t)))
            data[o + 2] = int(round(jb * t + air[2] * (1.0 - t)))
            data[o + 3] = 255

    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8",
                         bytes(data))
    lay.get_buffer().flush()
    return img, lay


img, lay = make_scene()
dlg, ctx = mod.build_dialog(None, None, img, lay)

# 摆一组看得见效果的参数：中等清晰度 + 明显去雾 + 一点饱和补偿
ctl = ctx['ctl']
ctl['clarity'].set_value(46.0)
ctl['cradius'].set_value(40.0)
ctl['dehaze'].set_value(62.0)
ctl['dradius'].set_value(15.0)
ctl['sat'].set_value(18.0)

dlg.show_all()
for _ in range(120):
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

out = os.path.join(HERE, "site", "plugin-shots", "clarity-dehaze")
os.makedirs(out, exist_ok=True)
path = os.path.join(out, "dialog.png")
surf.write_to_png(path)
print("wrote", path, os.path.getsize(path) // 1024, "KB")
dlg.destroy()
img.delete()
