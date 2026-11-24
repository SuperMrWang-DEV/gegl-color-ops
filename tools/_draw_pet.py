#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：在空地板上的指定区域「画」一只小猫 / 小狗。

跟对话框里点「确定」走同一条路径（ai_inpaint）。三个用例：
  1 小猫，框宽松（四周留白，含地面阴影位置）
  2 小猫，框紧贴（故意不留白，用来对比接缝/切头）
  3 小狗，框中等

跑法（仓库根）：
  "D:\\fastsoftware\\GIMP 3\\bin\\gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval -b "exec(open(r'...\\tools\\_draw_pet.py', encoding='utf-8').read())" --quit

环境变量 CASES=1,3 选跑；PROBE_SRC 换底图。
"""

import importlib.util
import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

REPO = r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
SRC = os.environ.get("PROBE_SRC") or r"D:\ComfyUI\test-out\scene-src.png"
OUTDIR = r"D:\ComfyUI\test-out"

# (编号, 盒子 x/y/w/h, 预设, 细节提示词, 输出名, 说明)
CASES = {
    "1": dict(box=(230, 690, 310, 320), preset="cat",
              prompt="a ginger tabby kitten sitting on the light oak wooden "
                     "floor, orange and white fur, looking at the camera, "
                     "natural window light, soft shadow on the floor, "
                     "photorealistic, sharp focus",
              out="pet1-cat-loose.png",
              note="小猫 / 框宽松（四周留白 + 含投影位置）"),
    "2": dict(box=(300, 780, 170, 190), preset="cat",
              prompt="a ginger tabby kitten sitting on the light oak wooden "
                     "floor, orange and white fur, natural window light, "
                     "photorealistic, sharp focus",
              out="pet2-cat-tight.png",
              note="小猫 / 框紧贴（不留白，看接缝会不会露）"),
    "3": dict(box=(420, 760, 290, 250), preset="dog",
              prompt="a small cream puppy sitting on the light oak wooden "
                     "floor, floppy ears, looking at the camera, natural "
                     "window light, soft shadow on the floor, photorealistic",
              out="pet3-dog.png",
              note="小狗 / 框中等的"),
    "4": dict(box=(230, 690, 310, 320), preset="cat",
              prompt="an orange tabby cat sitting flat on the wooden floor, "
                     "all four paws resting on the boards, dark soft contact "
                     "shadow directly under the body, ambient occlusion where "
                     "fur meets floor, same lighting as the room, "
                     "photorealistic, sharp focus",
              out="pet4-cat-shadow.png",
              note="小猫 / 提示词强调落地 + 接触阴影"),
    "5": dict(box=(420, 760, 290, 250), preset="dog",
              prompt="a small cream puppy standing on the wooden floor, paws "
                     "resting on the boards, dark soft contact shadow under "
                     "the body, ambient occlusion where fur meets floor, same "
                     "lighting as the room, photorealistic",
              out="pet5-dog-shadow.png",
              note="小狗 / 提示词强调落地 + 接触阴影"),
    "6": dict(box=(230, 690, 310, 320), preset="cat",
              prompt="orange tabby, looking at the camera, natural window light",
              out="pet6-cat-preset.png",
              note="小猫 / 只用新预设 + 一句短细节"),
}

sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))
spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

want = [c.strip() for c in (os.environ.get("CASES") or "1,2,3").split(",") if c.strip()]
for key in want:
    case = CASES[key]
    img = Gimp.Image.new(1024, 1024, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                Gio.File.new_for_path(SRC))
    img.insert_layer(layer, None, 0)
    if (layer.get_width(), layer.get_height()) != (1024, 1024):
        print("!! 底图尺寸不符：", layer.get_width(), layer.get_height())
    img.select_rectangle(Gimp.ChannelOps.REPLACE, *case["box"])
    print("\n==== 用例 %s  %s" % (key, case["note"]))
    print("盒子", case["box"], "预设", case["preset"])
    t0 = time.time()
    ok = True
    try:
        result, info = mod.ai_inpaint(
            img, layer, case["prompt"],
            checkpoint="", steps=25, cfg=7.5, seed=20261124, denoise=1.0,
            grow=8, grow_mask_by=8, feather=4.0,
            variations=3, preset=case["preset"], variant="auto")
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
