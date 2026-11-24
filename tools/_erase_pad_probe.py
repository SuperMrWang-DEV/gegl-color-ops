#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：验证「选区顶到图像边缘时，补边把脏像素喂给模型」这个猜想。

做法：把 ai_client.pad_edge_rgba 换成「补边填纯白布色」的版本，其余完全不动，
再跑一遍 SDXL 的全包框抹除。如果底部那条暗带消失，就说明暗带来自补边复制的
logo 像素，而不是模型自己画错。

环境变量 PAD_RGB=250,250,252 换补边颜色；MODELS 默认 sdxl。
"""

import importlib.util
import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

REPO = r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
SRC = r"D:\ComfyUI\ComfyUI\input\lb-img2img-src.png"
OUTDIR = r"D:\ComfyUI\test-out"
BOX = (10, 1000, 470, 120)
PROMPT = ("plain white cotton t-shirt fabric with soft folds, "
          "natural cloth texture")
SEED = 20261124
PAD_RGB = tuple(int(v) for v in (os.environ.get("PAD_RGB") or "250,250,252").split(","))

sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))
import ai_client as A


def pad_flat(data, w, h, left=0, top=0, right=0, bottom=0):
    """和 pad_edge_rgba 同签名，但补出来的地方填一个平色。"""
    left, top, right, bottom = (max(0, int(v)) for v in (left, top, right, bottom))
    if not (left or top or right or bottom):
        return w, h, data
    nw, nh = w + left + right, h + top + bottom
    px = bytes((PAD_RGB[0], PAD_RGB[1], PAD_RGB[2], 255))
    band = px * nw
    out = bytearray(band * top)
    for yy in range(h):
        row = data[yy * w * 4:(yy + 1) * w * 4]
        out += px * left + row + px * right
    out += band * bottom
    return nw, nh, bytes(out)


A.pad_edge_rgba = pad_flat
print("补边改成平色 %s" % (PAD_RGB,))

spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.ai_client.pad_edge_rgba is pad_flat, "插件没走同一个 ai_client"

MODELS = {
    "sd15": ("sd-v1-5-inpainting.ckpt", 25),
    "sdxl": ("sd_xl_base_1.0_inpainting_0.1.safetensors", 30),
    "flux": ("flux1-fill-dev-Q4_K_S.gguf", 20),
}
want = [m.strip() for m in (os.environ.get("MODELS") or "sdxl").split(",") if m.strip()]

for tag in want:
    ckpt, steps = MODELS[tag]
    img = Gimp.Image.new(744, 1120, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                Gio.File.new_for_path(SRC))
    img.insert_layer(layer, None, 0)
    img.select_rectangle(Gimp.ChannelOps.REPLACE, *BOX)
    print("\n==== %s  %s" % (tag, ckpt))
    t0 = time.time()
    try:
        result, info = mod.ai_inpaint(
            img, layer, PROMPT, checkpoint=ckpt, steps=steps, cfg=7.5,
            seed=SEED, denoise=1.0, grow=8, grow_mask_by=8, feather=4.0,
            variations=1, preset="none", variant="auto")
        print("耗时 %.1f s  工作尺寸 %s  倍率 %.2f  pads %s" % (
            time.time() - t0, info.get("work_size"), info.get("scale") or 1.0,
            info.get("pads")))
        print("修复", info.get("cleanup"))
    except Exception as exc:
        print("!! 失败：", type(exc).__name__, exc)
    out = os.path.join(OUTDIR, "erase-padflat-%s.png" % tag)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    print("已导出 " + out)
    img.delete()

print("\n结束")
