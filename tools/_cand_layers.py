#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：跑一次多候选填充，把「图层面板里到底能看到什么」原样打出来。

跑法（仓库根）：
  "D:\\fastsoftware\\GIMP 3\\bin\\gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval -b "exec(open(r'...\\tools\\_cand_layers.py', encoding='utf-8').read())" --quit

环境变量 MODELS=sd15,sdxl,flux；VARS 候选数（默认 3）；PRESET=none|erase。
"""

import importlib.util
import os
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

REPO = r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
SRC = r"D:\ComfyUI\ComfyUI\input\lb-img2img-src.png"
OUTDIR = r"D:\ComfyUI\test-out"
BOX = (10, 1000, 470, 120)

PROMPT = os.environ.get("PROMPT") or (
    "plain white cotton t-shirt fabric with soft folds, natural cloth texture")
PRESET = os.environ.get("PRESET") or "none"
VARS = int(os.environ.get("VARS") or "3")
SEED = 20261124

MODELS = {
    "sd15": ("sd-v1-5-inpainting.ckpt", 25),
    "sdxl": ("sd_xl_base_1.0_inpainting_0.1.safetensors", 30),
    "flux": ("flux1-fill-dev-Q4_K_S.gguf", 20),
}

spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def dump_panel(img, tag):
    """按图层面板的顺序（从上往下）列出每一项。"""
    print("---- 图层面板（%s），从上往下 ----" % tag)
    for idx, it in enumerate(img.get_layers()):
        flags = []
        if it.has_alpha():
            flags.append("alpha")
        try:
            if it.get_mask() is not None:
                flags.append("有蒙版")
        except Exception:
            pass
        off = it.get_offsets()
        try:                       # GIMP 3 返回 (ok, x, y)
            ox, oy = off[1], off[2]
        except Exception:
            ox, oy = getattr(off, "x", 0), getattr(off, "y", 0)
        print("  %2d  %-28s  可见=%s  %-12s 偏移=(%s,%s) 尺寸=%dx%d" % (
            idx, it.get_name(), "是" if it.get_visible() else "否",
            ",".join(flags) or "-", ox, oy,
            it.get_width(), it.get_height()))


for tag in [m.strip() for m in (os.environ.get("MODELS") or "sdxl").split(",")
            if m.strip()]:
    ckpt, steps = MODELS[tag]
    img = Gimp.Image.new(744, 1120, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                Gio.File.new_for_path(SRC))
    layer.set_name("原图")
    img.insert_layer(layer, None, 0)
    img.select_rectangle(Gimp.ChannelOps.REPLACE, *BOX)
    print("\n==== %s  %s  vars=%d  preset=%s" % (tag, ckpt, VARS, PRESET))
    t0 = time.time()
    try:
        result, info = mod.ai_inpaint(
            img, layer, PROMPT,
            checkpoint=ckpt, steps=steps, cfg=7.5, seed=SEED, denoise=1.0,
            grow=8, grow_mask_by=8, feather=4.0,
            variations=VARS, preset=PRESET, variant="auto")
        print("耗时 %.1f s  工作尺寸 %s  order=%s  scores=%s  胜出图层=%s" % (
            time.time() - t0, info.get("work_size"), info.get("order"),
            info.get("scores"), result.get_name()))
    except Exception as exc:
        print("!! 失败：", type(exc).__name__, exc)
    dump_panel(img, tag)
    out = os.path.join(OUTDIR, "cand-%s-panel.png" % tag)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    print("已导出（只含可见图层）" + out)
    img.delete()

print("\n结束")
