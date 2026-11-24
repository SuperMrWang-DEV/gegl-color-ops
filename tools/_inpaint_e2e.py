#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：走插件真实路径（无头 GIMP）跑一次 AI 填充，看会不会乱画。

和 _inpaint_probe.py 的区别：这里走 ai_inpaint() 全流程——选区外扩、
fit_context 补上下文、work_size 缩放、多候选打分、接缝/颗粒补偿，最后把
结果图层导出成 PNG。用户看到的就是这张。

跑法（在仓库根）：
  "D:\\fastsoftware\\GIMP 3\\bin\\gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval -b "exec(open(r'...\\tools\\_inpaint_e2e.py', encoding='utf-8').read())" --quit
"""

import importlib.util
import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

REPO = r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
SRC = os.environ.get("PROBE_SRC") or r"D:\ComfyUI\test-out\face-src.png"
OUT = os.environ.get("PROBE_OUT") or r"D:\ComfyUI\test-out\e2e-auto.png"

CKPT = os.environ.get("PROBE_CKPT", "")   # 空 = 自动挑（现在优先 inpaint 专用）
BOX = (640, 10, 260, 100)
PROMPT = "smooth forehead skin with natural freckles, photorealistic, soft light"

sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))
spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

img = Gimp.Image.new(1024, 512, Gimp.ImageBaseType.RGB)
layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                            Gio.File.new_for_path(SRC))
img.insert_layer(layer, None, 0)
print("载入图层：", layer.get_width(), layer.get_height())

img.select_rectangle(Gimp.ChannelOps.REPLACE, BOX[0], BOX[1], BOX[2], BOX[3])
t0 = time.time()
result, info = mod.ai_inpaint(
    img, layer, PROMPT,
    checkpoint=CKPT, steps=20, cfg=7.5, seed=12345, denoise=1.0,
    grow=8, grow_mask_by=8, feather=4.0,
    variations=1, preset="none",
    variant=os.environ.get("PROBE_VARIANT", "auto"))
print("耗时 %.1f s  工作尺寸 %s  倍率 %.2f" % (
    time.time() - t0, info.get("work_size"), info.get("scale") or 1.0))
print("配方：", info.get("variant"), " 底模：", info.get("checkpoint"))
print("分数：", info.get("scores"), " 修复：", info.get("cleanup"))

Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
               Gio.File.new_for_path(OUT), None)
print("已导出", OUT)
