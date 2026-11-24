# -*- coding: utf-8 -*-
"""量扩图成品的接缝：跨边界的亮度剖面 + 内外色差。

    IMG=demo-expand-all.png SEAM_L=160 SEAM_T=160 \
    gimp-console-3.2.exe -i -c -d -f --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/_demo_seam_metric.py', encoding='utf-8').read())" --quit

剖面按 8 px 分箱取均值；亮边表现为「边界处凸起、两侧回落」。
"""
import os
import numpy as np
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gio, Gegl

OUTDIR = r"D:/ComfyUI/test-out"
IMG = os.environ.get("IMG") or "demo-expand-all.png"
SEAM_L = int(os.environ.get("SEAM_L") or 160)
SEAM_T = int(os.environ.get("SEAM_T") or 160)
BIN = 8
REACH = 72


def read(path):
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                         Gio.File.new_for_path(path))
    layer = img.get_layers()[0]
    w, h = layer.get_width(), layer.get_height()
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                 "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    a = np.frombuffer(bytes(bytearray(raw)), dtype=np.uint8)[: w * h * 4]
    a = a.reshape(h, w, 4)[:, :, :3].astype(np.float32)
    img.delete()
    return a


a = read(os.path.join(OUTDIR, IMG))
h, w = a.shape[:2]
lum = a.mean(axis=2)
print("== %s  %dx%d  左交界 x=%d  上交界 y=%d" % (IMG, w, h, SEAM_L, SEAM_T))

# 横向剖面：在避开主体的下半幅取样（那里是干净的墙面）
ys = slice(int(h * 0.62), int(h * 0.80))
print("-- 跨左交界（x），取样 y=%.0f%%~%.0f%%" % (62, 80))
for x0 in ([] if not SEAM_L else range(SEAM_L - REACH, SEAM_L + REACH, BIN)):
    seg = lum[ys, x0:x0 + BIN]
    mark = " <-- 交界" if x0 <= SEAM_L < x0 + BIN else ""
    print("   x=%4d  L=%6.2f%s" % (x0, seg.mean(), mark))

xs = slice(int(w * 0.30), int(w * 0.55))
print("-- 跨上交界（y），取样 x=30%%~55%%")
for y0 in ([] if not SEAM_T else range(SEAM_T - REACH, SEAM_T + REACH, BIN)):
    seg = lum[y0:y0 + BIN, xs]
    mark = " <-- 交界" if y0 <= SEAM_T < y0 + BIN else ""
    print("   y=%4d  L=%6.2f%s" % (y0, seg.mean(), mark))

# 内外色差：交界两侧各取一条带（跳过斜坡本身）
def band_mean(y0, y1, x0, x1):
    return a[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)


inside = band_mean(SEAM_T + 40, SEAM_T + 140, SEAM_L + 40, SEAM_L + 240)
outside = band_mean(SEAM_T + 40, SEAM_T + 140, SEAM_L - 140, SEAM_L - 40)
print("-- 内外色差（左上角附近，两侧各 100px 带）")
print("   内 rgb=%s" % np.round(inside, 1))
print("   外 rgb=%s" % np.round(outside, 1))
print("   差 rgb=%s  |dL|=%.2f" % (np.round(outside - inside, 1),
                                 float(np.abs(outside - inside).mean())))
