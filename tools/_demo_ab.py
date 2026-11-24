# -*- coding: utf-8 -*-
"""羽化 24 与 72 的同角 1:1 对照 + 超分 100% 局部对照。"""
import os
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gio, Gegl

OUTDIR = r"D:/ComfyUI/test-out"
GAP = 10

try:
    Gimp.context_set_background(Gegl.Color.new("#111114"))
    BG = Gimp.FillType.BACKGROUND
except Exception:
    BG = Gimp.FillType.WHITE


def crop_to(path, cx, cy, cw, ch, out_path, out_w=None, out_h=None):
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                         Gio.File.new_for_path(path))
    img.resize(cw, ch, -cx, -cy)
    img.flatten()
    if out_w:
        img.scale(int(out_w), int(out_h))
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out_path), None)
    img.delete()
    return out_path


def side(panels, name):
    """panels: [(png_path, w, h)]，等高排成一行。"""
    W = sum(w for _, w, _ in panels) + GAP * (len(panels) - 1)
    H = max(h for _, _, h in panels)
    canvas = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    base = Gimp.Layer.new(canvas, "bg", W, H, Gimp.ImageType.RGB_IMAGE, 100,
                          Gimp.LayerMode.NORMAL)
    canvas.insert_layer(base, None, 0)
    try:
        base.fill(BG)
    except Exception:
        pass
    x = 0
    for path, w, h in panels:
        layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, canvas,
                                     Gio.File.new_for_path(path))
        canvas.insert_layer(layer, None, 0)
        if (layer.get_width(), layer.get_height()) != (w, h):
            layer.scale(w, h, False)
        layer.set_offsets(x, 0)
        x += w + GAP
    out = os.path.join(OUTDIR, name)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, canvas,
                   Gio.File.new_for_path(out), None)
    canvas.delete()
    print("已导出", out)
    return out


a = os.path.join(OUTDIR, "demo-expand-all.png")
b = os.path.join(OUTDIR, "demo-expand-all-hard.png")
if os.path.exists(a) and os.path.exists(b):
    p1 = crop_to(a, 70, 70, 240, 240, os.path.join(OUTDIR, "_ab-soft.png"))
    p2 = crop_to(b, 70, 70, 240, 240, os.path.join(OUTDIR, "_ab-hard.png"))
    side([(p1, 240, 240), (p2, 240, 240)], "ab-mask.png")

src = os.path.join(OUTDIR, "demo-upscale-crop-src.png")
up = os.path.join(OUTDIR, "demo-upscale-crop.png")
if os.path.exists(src) and os.path.exists(up):
    p1 = crop_to(src, 40, 40, 240, 240, os.path.join(OUTDIR, "_up-l.png"),
                 480, 480)
    p2 = crop_to(up, 80, 80, 480, 480, os.path.join(OUTDIR, "_up-r.png"))
    side([(p1, 480, 480), (p2, 480, 480)], "cmp-upscale-crop.png")
