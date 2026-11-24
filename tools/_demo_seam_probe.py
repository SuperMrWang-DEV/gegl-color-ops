# -*- coding: utf-8 -*-
"""量成品图跨接缝的像素步进，判断亮线是哪来的。"""
import os
import numpy as np
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gio, Gegl

OUTDIR = r"D:/ComfyUI/test-out"


def read_region(layer, x, y, w, h):
    rect = Gegl.Rectangle.new(x, y, w, h)
    raw = layer.get_buffer().get(rect, 1.0, "R'G'B'A u8",
                                 Gegl.AbyssPolicy.NONE)
    return bytes(bytearray(raw))


def read(path):
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                         Gio.File.new_for_path(path))
    layer = img.get_layers()[0]
    w, h = layer.get_width(), layer.get_height()
    raw = read_region(layer, 0, 0, w, h)
    arr = np.frombuffer(raw, dtype=np.uint8)[: w * h * 4].reshape(h, w, 4)
    img.delete()
    return arr


for name, seam_x, seam_y, axis in (
        ("demo-expand-all-hard2.png", 160, 500, "x"),
        ("demo-expand-all-hard2.png", 500, 160, "y")):
    path = os.path.join(OUTDIR, name)
    if not os.path.exists(path):
        print("缺文件", path)
        continue
    a = read(path)
    h, w = a.shape[:2]
    print("== %s  %dx%d" % (name, w, h))
    if axis == "x":
        row = a[seam_y].astype(int)
        for x in range(seam_x - 14, seam_x + 15):
            print("   x=%4d rgb=%s" % (x, row[x][:3]))
    else:
        col = a[:, seam_x].astype(int)
        for y in range(seam_y - 14, seam_y + 15):
            print("   y=%4d rgb=%s" % (y, col[y][:3]))
