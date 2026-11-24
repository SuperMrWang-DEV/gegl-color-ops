#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：同一张原图、同一块衣服 logo，换底模做「智能填充」（抹除）。

和 tools/_inpaint_cases.py 的用例 1/3 同源：源图 lb-img2img-src.png，
提示词用「正面材质描述」那版（写 no text/no logo 反而把 logo 拉回来，
2026-11-24 已验证）。只换 checkpoint。

三种框：
  tight = (55,1016,402,104)  没包全，左边缘露着红蓝弧线（旧模型的失败现场）
  full  = (10,1000,470,120)  整块 logo 包住（正确用法）

跑法（仓库根）：
  "D:\\fastsoftware\\GIMP 3\\bin\\gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval -b "exec(open(r'...\\tools\\_erase_models.py', encoding='utf-8').read())" --quit

环境变量 MODELS=sd15,sdxl,flux；BOX=tight|full（默认 full）；VARS 候选数（默认 1）。
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

BOXES = {
    "tight": (55, 1016, 402, 104),
    "full": (10, 1000, 470, 120),
}
BOX = BOXES[os.environ.get("BOX") or "full"]
BOX_TAG = os.environ.get("BOX") or "full"

PROMPT = os.environ.get("PROMPT") or (
    "plain white cotton t-shirt fabric with soft folds, natural cloth texture")
SEED = 20261124
VARS = int(os.environ.get("VARS") or "1")
PRESET = os.environ.get("PRESET") or "none"

MODELS = {
    "sd15": ("sd-v1-5-inpainting.ckpt", 25, "SD1.5 inpaint 512"),
    "sdxl": ("sd_xl_base_1.0_inpainting_0.1.safetensors", 30, "SDXL inpaint 1024"),
    "flux": ("flux1-fill-dev-Q4_K_S.gguf", 20, "Flux Fill GGUF 1024"),
}

sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))
import ai_client as A

spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def logo_stats(path, box):
    """框内「像 logo」的像素占比，以及白布的平均亮度/色偏。

    原 logo 是深蓝 (30,50,140) 与鲜红 (220,40,70)：
      蓝判据 b-r>60 且 b>110；红判据 r-g>80 且 r>150。
    白布亮度用框内中位亮度，色偏用 median(b-r)。
    """
    w, h, ch, data = A.decode_png(open(path, "rb").read())
    x, y, cw, chh = box
    x2, y2 = min(w, x + cw), min(h, y + chh)
    total = blue = red = 0
    lums, skews = [], []
    for row in range(max(0, y), y2):
        base = row * w * 4
        for col in range(max(0, x), x2):
            i = base + col * 4
            r, g, b = data[i], data[i + 1], data[i + 2]
            total += 1
            if b - r > 60 and b > 110:
                blue += 1
            elif r - g > 80 and r > 150:
                red += 1
            lums.append((r + g + b) // 3)
            skews.append(b - r)
    lums.sort()
    skews.sort()
    n = max(1, total)
    return {
        "blue": 100.0 * blue / n,
        "red": 100.0 * red / n,
        "lum": lums[len(lums) // 2] if lums else 0,
        "skew": skews[len(skews) // 2] if skews else 0,
        "px": total,
    }


want = [m.strip() for m in (os.environ.get("MODELS") or "sd15,sdxl,flux").split(",") if m.strip()]
print("源图 %s" % SRC)
print("框 %s %s  预设 %s  提示词 %s" % (BOX_TAG, BOX, PRESET, PROMPT))
base = logo_stats(SRC, BOX)
print("原图框内：蓝 %.2f%%  红 %.2f%%  中位亮度 %d  b-r %+d" % (
    base["blue"], base["red"], base["lum"], base["skew"]))

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
            variations=VARS, preset=PRESET, variant="auto")
        print("耗时 %.1f s  工作尺寸 %s  倍率 %.2f  配方 %s" % (
            time.time() - t0, info.get("work_size"), info.get("scale") or 1.0,
            info.get("variant")))
        print("候选分数", info.get("scores"), "修复", info.get("cleanup"))
    except Exception as exc:                      # 探针：把异常打全，别静默
        ok = False
        print("!! 失败：", type(exc).__name__, exc)
    out = os.path.join(OUTDIR, "erase-%s-%s%s.png" % (BOX_TAG, tag,
                                                      os.environ.get("OUT_TAG") or ""))
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    try:
        st = logo_stats(out, BOX)
        print("残留：蓝 %.2f%%  红 %.2f%%  中位亮度 %d  b-r %+d" % (
            st["blue"], st["red"], st["lum"], st["skew"]))
    except Exception as exc:
        print("!! 统计失败：", exc)
    print(("已导出 " if ok else "已导出（含失败结果）") + out)
    img.delete()

print("\n全部用例结束")
