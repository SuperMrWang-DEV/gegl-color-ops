#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：不手描选区，让插件按名称选（"ear"）再往里加耳环。

走两条真实路径：
  1. PDB 过程 lb-plugin-ai-select（就是菜单里「AI Select by Name…」）
  2. ai_inpaint()（就是菜单里「AI Inpaint…」）
中间不写任何坐标——选区完全由 SAM2 给出。

跑法（仓库根）：
  "D:\\fastsoftware\\GIMP 3\\bin\\gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval -b "exec(open(r'...\\tools\\_select_probe.py', encoding='utf-8').read())" --quit
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
OUT = os.environ.get("PROBE_OUT") or r"D:\ComfyUI\test-out\e2e-select-earring.png"
THING = os.environ.get("PROBE_THING") or "ear"
SHIFT_X = int(os.environ.get("PROBE_SHIFT_X") or 0)
SHIFT_Y = int(os.environ.get("PROBE_SHIFT_Y") or 0)
PROMPT = os.environ.get("PROBE_PROMPT") or (
    "a small gold hoop earring hanging from the earlobe, polished yellow gold, "
    "jewelry, photorealistic, sharp focus")

sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))
spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

img = Gimp.Image.new(744, 1120, Gimp.ImageBaseType.RGB)
layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                            Gio.File.new_for_path(SRC))
img.insert_layer(layer, None, 0)
print("载入：", layer.get_width(), layer.get_height())


def sel_bounds(image):
    proc = Gimp.get_pdb().lookup_procedure('gimp-selection-bounds')
    cfg = proc.create_config()
    cfg.set_property('image', image)
    res = proc.run(cfg)
    if res.index(0) != Gimp.PDBStatusType.SUCCESS:
        return None
    return res.index(1), res.index(2), res.index(3), res.index(4), res.index(5)


print("\n== 1. 按名称选区：%r  平移 (%d, %d)" % (THING, SHIFT_X, SHIFT_Y))
proc = Gimp.get_pdb().lookup_procedure(mod.PROC_SELECT)
print("过程已注册：", proc is not None)
cfg = proc.create_config()
cfg.set_property('image', img)
try:                                   # ImageProcedure 吃的是 drawables 数组
    cfg.set_core_object_array('drawables', [layer])
except Exception:
    cfg.set_property('drawables', [layer])
cfg.set_property('object', THING)
cfg.set_property('shift-x', SHIFT_X)
cfg.set_property('shift-y', SHIFT_Y)
t0 = time.time()
res = proc.run(cfg)
status = res.index(0)
print("状态 %s  耗时 %.1f s" % (status, time.time() - t0))
if status != Gimp.PDBStatusType.SUCCESS:
    print("!! 失败：", res.index(1))
b = sel_bounds(img)
print("选区 bounds：", b)
if b:
    print("选区尺寸：%d × %d" % (b[3] - b[1], b[4] - b[2]))

print("\n== 2. 往这个选区里画耳环")
t0 = time.time()
result, info = mod.ai_inpaint(
    img, layer, PROMPT, steps=25, cfg=7.5, seed=20261124, denoise=1.0,
    grow=8, grow_mask_by=8, feather=4.0, variations=3, preset="none")
print("耗时 %.1f s  工作尺寸 %s  倍率 %.2f" % (
    time.time() - t0, info.get("work_size"), info.get("scale") or 1.0))
print("配方", info.get("variant"), "底模", info.get("checkpoint"))
print("分数", info.get("scores"))

Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
               Gio.File.new_for_path(OUT), None)
print("已导出", OUT)
