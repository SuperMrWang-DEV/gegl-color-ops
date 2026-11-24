#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：把「候选打分」的真实输入落盘，好在离线复算。

包装 ai-inpaint 的 rank_layers：把填充前的画布、硬边蒙版、每张候选的原尺寸
像素都存到 D:/ComfyUI/test-out/rankin/，然后照常返回原来的排序与分数。

跑法（仓库根，MODELS 默认 flux）：
  "D:\\fastsoftware\\GIMP 3\\bin\\gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval -b "exec(open(r'...\\tools\\_erase_rank_dump.py', encoding='utf-8').read())" --quit
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
DUMP = os.path.join(OUTDIR, os.environ.get("DUMP_DIR") or "rankin")
BOX = (10, 1000, 470, 120)
PROMPT = os.environ.get("PROMPT") or (
    "plain white cotton t-shirt fabric with soft folds, natural cloth texture")
SEED = 20261124

MODELS = {
    "sd15": ("sd-v1-5-inpainting.ckpt", 25),
    "sdxl": ("sd_xl_base_1.0_inpainting_0.1.safetensors", 30),
    "flux": ("flux1-fill-dev-Q4_K_S.gguf", 20),
}
TAG = os.environ.get("MODELS") or "flux"
ckpt, steps = MODELS[TAG]

sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))
import ai_client as A

spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

os.makedirs(DUMP, exist_ok=True)
CALLS = {"n": 0}


def _save_rgba(name, data, w, h):
    path = os.path.join(DUMP, name)
    open(path, "wb").write(A.rgba_png(w, h, data))
    print("    dumped %s (%dx%d)" % (name, w, h))


def rank_dump(original, mask, layers, w, h, removal):
    order, scores = mod._rank_layers_orig(original, mask, layers, w, h, removal)
    if CALLS["n"] == 0:                     # 只留第一次，够分析就行
        CALLS["n"] = 1
        _save_rgba("base.png", original, w, h)
        gray = bytearray()
        for v in mask:
            gray += bytes((v, v, v, 255))
        _save_rgba("mask.png", bytes(gray), w, h)
        for i, layer in enumerate(layers):
            _save_rgba("cand%d.png" % i, mod.read_region(layer, 0, 0, w, h), w, h)
        print("    removal=%s  scores=%s  order=%s" % (
            removal, [round(s.total, 3) for s in scores], order))
    return order, scores


mod._rank_layers_orig = mod.rank_layers
mod.rank_layers = rank_dump

img = Gimp.Image.new(744, 1120, Gimp.ImageBaseType.RGB)
layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                            Gio.File.new_for_path(SRC))
img.insert_layer(layer, None, 0)
img.select_rectangle(Gimp.ChannelOps.REPLACE, *BOX)
print("==== %s  %s  (removal 会是 False，因为写了提示词)" % (TAG, ckpt))
t0 = time.time()
try:
    result, info = mod.ai_inpaint(
        img, layer, PROMPT, checkpoint=ckpt, steps=steps, cfg=7.5,
        seed=SEED, denoise=1.0, grow=8, grow_mask_by=8, feather=4.0,
        variations=3, preset="none", variant="auto")
    print("耗时 %.1f s  工作尺寸 %s  候选 %s" % (
        time.time() - t0, info.get("work_size"), info.get("scores")))
except Exception as exc:
    print("!! 失败：", type(exc).__name__, exc)
out = os.path.join(OUTDIR, "rankdump-%s.png" % TAG)
Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
               Gio.File.new_for_path(out), None)
print("已导出 " + out)
img.delete()
print("结束")
