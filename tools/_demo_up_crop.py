# -*- coding: utf-8 -*-
"""超分局部 100% 对比：裁一块 → AI 2x → 同区域并排。"""
import os
import sys
import time
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gio, Gegl

ROOT = r"C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
SRC = r"D:/ComfyUI/ComfyUI/input/lb-img2img-src.png"
OUTDIR = r"D:/ComfyUI/test-out"
CX, CY, CW, CH = 300, 380, 320, 320          # 眉眼这一块
GAP = 10

sys.path.append(os.path.join(ROOT, "plugin", "_shared"))
spec = importlib.util.spec_from_file_location(
    "ai_upscale_plugin", os.path.join(ROOT, "plugin", "ai-upscale", "ai-upscale.py"))
upscale = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upscale)


def crop_image(src_path, cx, cy, cw, ch):
    """新建 cw×ch 画布 + 负偏移 —— 这条写法和 100% 裁切都验证过。"""
    img = Gimp.Image.new(cw, ch, Gimp.ImageBaseType.RGB)
    lay = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                               Gio.File.new_for_path(src_path))
    if lay is None:
        raise RuntimeError("读不到 " + src_path)
    img.insert_layer(lay, None, 0)
    lay.set_offsets(-cx, -cy)
    img.flatten()
    return img


def save(img, name):
    out = os.path.join(OUTDIR, name)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    print("  已导出", out)
    return out


# 1) 裁源块
crop_img = crop_image(SRC, CX, CY, CW, CH)
src_path = save(crop_img, "up-src.png")
layer = crop_img.get_layers()[0]
print("源块", crop_img.get_width(), crop_img.get_height(),
      "层偏移", layer.get_offsets())

# 2) AI 2x
t0 = time.time()
new, info = upscale.ai_upscale(crop_img, layer, factor=2, timeout=300)
print("AI 2x %.1f s  %s → %s  %s" % (time.time() - t0, info["before"],
                                     info["after"], info["model"]))
crop_img.remove_layer(layer)
crop_img.resize(new.get_width(), new.get_height(), 0, 0)
up_path = save(crop_img, "up-2x.png")
crop_img.delete()

# 3) 同区域并排：左=直接放大到显示尺寸，右=AI 2x 的对应区域
left = crop_image(src_path, 40, 40, 240, 240)
left.scale(480, 480)
left_path = save(left, "_up-left.png")
left.delete()

right = crop_image(up_path, 80, 80, 480, 480)
right_path = save(right, "_up-right.png")
right.delete()

W, H = 480 * 2 + GAP, 480
canvas = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
base = Gimp.Layer.new(canvas, "bg", W, H, Gimp.ImageType.RGB_IMAGE, 100,
                      Gimp.LayerMode.NORMAL)
canvas.insert_layer(base, None, 0)
try:
    Gimp.context_set_background(Gegl.Color.new("#111114"))
    base.fill(Gimp.FillType.BACKGROUND)
except Exception:
    pass
x = 0
for p in (left_path, right_path):
    l2 = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, canvas,
                              Gio.File.new_for_path(p))
    canvas.insert_layer(l2, None, 0)
    l2.set_offsets(x, 0)
    x += 480 + GAP
save(canvas, "cmp-upscale-crop.png")
canvas.delete()
print("完成")
