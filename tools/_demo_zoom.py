# -*- coding: utf-8 -*-
"""把一张图的某个区域 100% 裁出来，用于检查接缝。"""
import os
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

OUTDIR = r"D:/ComfyUI/test-out"

JOBS = [
    ("demo-expand-all.png", (60, 60, 460, 460), "zoom-all-corner"),
    ("demo-expand-all.png", (300, 560, 460, 460), "zoom-all-mid"),
    ("demo-expand-h.png", (180, 300, 460, 460), "zoom-h-seam"),
    ("demo-expand-v.png", (140, 120, 460, 460), "zoom-v-seam"),
    ("demo-expand-all.png", (110, 110, 160, 160), "zoom-all-tight"),
    ("demo-expand-all-hard.png", (70, 70, 240, 240), "zoom-hard-corner"),
    ("demo-expand-all-hard2.png", (60, 60, 300, 300), "zoom-h2-corner"),
    ("demo-expand-all-hard2.png", (120, 400, 300, 300), "zoom-h2-left"),
    ("demo-expand-h.png", (200, 640, 160, 160), "zoom-h-tight"),
]

for src, (cx, cy, cw, ch), name in JOBS:
    path = os.path.join(OUTDIR, src)
    if not os.path.exists(path):
        print("缺文件", path)
        continue
    img = Gimp.Image.new(cw, ch, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(path))
    img.insert_layer(layer, None, 0)
    layer.set_offsets(-cx, -cy)
    img.flatten()
    out = os.path.join(OUTDIR, "%s.png" % name)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    print("已导出", out)
    img.delete()
