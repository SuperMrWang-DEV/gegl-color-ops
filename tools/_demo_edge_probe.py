# -*- coding: utf-8 -*-
"""逐列/逐行差分，找成品图里真正的硬边位置。"""
import os
import numpy as np
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gio, Gegl

OUTDIR = r"D:/ComfyUI/test-out"


def read(path):
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                         Gio.File.new_for_path(path))
    layer = img.get_layers()[0]
    w, h = layer.get_width(), layer.get_height()
    rect = Gegl.Rectangle.new(0, 0, w, h)
    raw = layer.get_buffer().get(rect, 1.0, "R'G'B'A u8",
                                 Gegl.AbyssPolicy.NONE)
    arr = np.frombuffer(bytes(bytearray(raw)), dtype=np.uint8)
    arr = arr[: w * h * 4].reshape(h, w, 4)[:, :, :3].astype(np.int16)
    img.delete()
    return arr


for name, seam, axis in (("demo-expand-h.png", 240, 0),
                         ("demo-expand-all.png", 160, 0),
                         ("demo-expand-v.png", 200, 1)):
    path = os.path.join(OUTDIR, name)
    if not os.path.exists(path):
        continue
    a = read(path)
    if axis == 0:
        d = np.abs(np.diff(a, axis=1)).mean(axis=(0, 2))
        lo, hi = max(0, seam - 60), seam + 60
        seg = d[lo:hi]
        top = np.argsort(seg)[-6:][::-1] + lo
        print("== %s 列差（接缝 x=%d）" % (name, seam))
        print("   最硬的 6 列:", [(int(i), round(float(d[i]), 2)) for i in top])
        print("   x=%d 处 %.2f, 全场中位 %.2f" % (seam, d[seam],
                                                 float(np.median(d))))
    else:
        d = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))
        lo, hi = max(0, seam - 60), seam + 60
        seg = d[lo:hi]
        top = np.argsort(seg)[-6:][::-1] + lo
        print("== %s 行差（接缝 y=%d）" % (name, seam))
        print("   最硬的 6 行:", [(int(i), round(float(d[i]), 2)) for i in top])
        print("   y=%d 处 %.2f, 全场中位 %.2f" % (seam, d[seam],
                                                 float(np.median(d))))
