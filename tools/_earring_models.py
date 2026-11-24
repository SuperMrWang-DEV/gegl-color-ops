#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：同一张原图、同一个耳环盒子，换底模各画一遍。

和 tools/_inpaint_cases.py 的用例 2 完全一致（源图 lb-img2img-src.png，
盒子 182,628,70,100，同一提示词、同一种子），只换 checkpoint：
  sd15 = sd-v1-5-inpainting.ckpt            （老基线）
  sdxl = sd_xl_base_1.0_inpainting_0.1      （新装）
  flux = flux1-fill-dev-Q4_K_S.gguf         （新装，走 GGUF + Flux 专用图）

跑法（仓库根）：
  "D:\\fastsoftware\\GIMP 3\\bin\\gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval -b "exec(open(r'...\\tools\\_earring_models.py', encoding='utf-8').read())" --quit

环境变量 MODELS=sd15,sdxl,flux 选跑哪几个；VARS 覆盖候选数（默认 1，方便同种子对比）。
"""

import importlib.util
import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

REPO = r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
SRC = os.environ.get("PROBE_SRC") or r"D:\ComfyUI\ComfyUI\input\lb-img2img-src.png"
OUTDIR = r"D:\ComfyUI\test-out"

BOX = (182, 628, 70, 100)
PROMPT = ("a small gold hoop earring hanging from the earlobe, "
          "polished yellow gold, jewelry, photorealistic, sharp focus")
SEED = 20261124
VARS = int(os.environ.get("VARS") or "1")
TAG = os.environ.get("OUT_TAG") or ""

# 标签 → (checkpoint 文件名, steps, 说明)
MODELS = {
    "sd15": ("sd-v1-5-inpainting.ckpt", 25, "SD1.5 inpaint 512"),
    "sdxl": ("sd_xl_base_1.0_inpainting_0.1.safetensors", 30, "SDXL inpaint 1024"),
    "flux": ("flux1-fill-dev-Q4_K_S.gguf", 20, "Flux Fill GGUF 1024"),
}

sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))
spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

want = [m.strip() for m in (os.environ.get("MODELS") or "sd15,sdxl,flux").split(",") if m.strip()]
for tag in want:
    ckpt, steps, note = MODELS[tag]
    img = Gimp.Image.new(744, 1120, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                Gio.File.new_for_path(SRC))
    img.insert_layer(layer, None, 0)
    if (layer.get_width(), layer.get_height()) != (744, 1120):
        print("!! 源图尺寸不符：", layer.get_width(), layer.get_height())
    img.select_rectangle(Gimp.ChannelOps.REPLACE, *BOX)
    print("\n==== %s  %s  %s  steps=%d vars=%d" % (tag, ckpt, note, steps, VARS))
    t0 = time.time()
    ok = True
    try:
        result, info = mod.ai_inpaint(
            img, layer, PROMPT,
            checkpoint=ckpt, steps=steps, cfg=7.5, seed=SEED, denoise=1.0,
            grow=8, grow_mask_by=8, feather=4.0,
            variations=VARS, preset="none", variant="auto")
        print("耗时 %.1f s  工作尺寸 %s  倍率 %.2f" % (
            time.time() - t0, info.get("work_size"), info.get("scale") or 1.0))
        print("配方", info.get("variant"), "底模", info.get("checkpoint"))
        print("候选分数", info.get("scores"), "修复", info.get("cleanup"))
    except Exception as exc:                      # 探针：把异常打全，别静默
        ok = False
        print("!! 失败：", type(exc).__name__, exc)
    out = os.path.join(OUTDIR, "earring-%s%s.png" % (tag, TAG))
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    print(("已导出 " if ok else "已导出（含失败结果）") + out)
    img.delete()

print("\n全部用例结束")
