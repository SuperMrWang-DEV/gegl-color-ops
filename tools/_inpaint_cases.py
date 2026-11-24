#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：一次 GIMP 会话里跑几个 AI 填充用例。

用例见 CASES 表：1 = 智能填充（抹掉衣服上的字母），2 = 指定物体（耳垂上
生成一个金耳环）。都走 ai_inpaint() 全流程，和用户在对话框里点「确定」
完全同一条代码路径。

跑法（仓库根）：
  "D:\\fastsoftware\\GIMP 3\\bin\\gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval -b "exec(open(r'...\\tools\\_inpaint_cases.py', encoding='utf-8').read())" --quit

环境变量 CASES=1,2 选跑哪几个；PROBE_SRC 换源图。
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

# (编号, 盒子 x/y/w/h, 提示词, 输出名, 说明)
CASES = {
    "1": dict(box=(55, 1016, 402, 104),
              prompt="plain white cotton t-shirt fabric, seamless, clean, "
                     "no text, no logo",
              out="case1-shirt.png",
              note="智能填充：抹掉衣服上的字母/logo"),
    "2": dict(box=(182, 628, 70, 100),
              prompt="a small gold hoop earring hanging from the earlobe, "
                     "polished yellow gold, jewelry, photorealistic, sharp focus",
              out="case2-earring.png",
              note="指定物体：耳垂上生成一个金耳环"),
    "3": dict(box=(10, 1000, 470, 120),
              prompt="plain white cotton t-shirt fabric with soft folds, "
                     "natural cloth texture",
              out="case3-shirt2.png",
              note="智能填充第二轮：整块 logo 全包住，提示词不提「文字」"),
    "4": dict(box=(430, 590, 80, 78),
              prompt="smooth natural skin, freckles, soft light, photorealistic",
              out="case4-skin.png",
              note="智能填充：一块纯皮肤（考验接缝和纹理）"),
}

sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))
spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

want = [c.strip() for c in (os.environ.get("CASES") or "1,2").split(",") if c.strip()]
for key in want:
    case = CASES[key]
    img = Gimp.Image.new(744, 1120, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                Gio.File.new_for_path(SRC))
    img.insert_layer(layer, None, 0)
    if (layer.get_width(), layer.get_height()) != (744, 1120):
        print("!! 源图尺寸不符：", layer.get_width(), layer.get_height())
    img.select_rectangle(Gimp.ChannelOps.REPLACE, *case["box"])
    print("\n==== 用例 %s  %s" % (key, case["note"]))
    print("盒子", case["box"], "提示词", case["prompt"])
    t0 = time.time()
    ok = True
    try:
        result, info = mod.ai_inpaint(
            img, layer, case["prompt"],
            checkpoint="", steps=25, cfg=7.5, seed=20261124, denoise=1.0,
            grow=8, grow_mask_by=8, feather=4.0,
            variations=3, preset="none", variant="auto")
        print("耗时 %.1f s  工作尺寸 %s  倍率 %.2f" % (
            time.time() - t0, info.get("work_size"), info.get("scale") or 1.0))
        print("配方", info.get("variant"), "底模", info.get("checkpoint"))
        print("候选分数", info.get("scores"), "修复", info.get("cleanup"))
    except Exception as exc:                      # 探针：把异常打全，别静默
        ok = False
        print("!! 失败：", type(exc).__name__, exc)
    out = os.path.join(OUTDIR, case["out"])
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    print(("已导出 " if ok else "已导出（含失败结果）") + out)
    img.delete()

print("\n全部用例结束")
