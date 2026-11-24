# -*- coding: utf-8 -*-
"""探针：AI 扩图 / AI 超分 在真机（真 ComfyUI + 真 GIMP）上跑一遍。

    "GIMP/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/_expand_upscale_probe.py', encoding='utf-8').read())" --quit

环境变量：
    CASES=expand-sdxl,expand-flux,upscale   默认全跑
"""

import os
import sys
import time
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

ROOT = r"C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
SRC = r"D:/ComfyUI/ComfyUI/input/lb-img2img-src.png"
OUTDIR = r"D:/ComfyUI/test-out"
SW, SH = 744, 1120

for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "plugin", "_shared")):
    if _p not in sys.path:
        sys.path.append(_p)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


expand = load(os.path.join(ROOT, "plugin", "ai-outpaint", "ai-outpaint.py"),
              "ai_expand_plugin")
upscale = load(os.path.join(ROOT, "plugin", "ai-upscale", "ai-upscale.py"),
               "ai_upscale_plugin")

CASES = [c.strip() for c in
         (os.environ.get("CASES") or "expand-sdxl,expand-flux,upscale").split(",")
         if c.strip()]


def new_image():
    img = Gimp.Image.new(SW, SH, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(SRC))
    img.insert_layer(layer, None, 0)
    return img, layer


def save(img, name):
    out = os.path.join(OUTDIR, name)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path(out),
                   None)
    print("已导出", out)
    return out


for case in CASES:
    img, layer = new_image()
    try:
        if case.startswith("expand"):
            flux = case.endswith("flux")
            args = dict(edges="horizontal", amount=240, variations=2,
                        pick="off", timeout=900)
            if os.environ.get("FEATHER"):
                args["feather"] = int(os.environ["FEATHER"])
            if flux:
                args["checkpoint"] = "flux1-fill-dev-Q4_K_S.gguf"
                args["steps"] = 20
                args["variations"] = 1
            t0 = time.time()
            info = expand.ai_expand(img, layer,
                                    "a quiet street at dusk, soft overcast "
                                    "light, matching the scene", **args)
            print("[%s] %.1f s  画布 %s  每边 %s  底模 %s" % (
                case, time.time() - t0, info["canvas"], info["edges"],
                info["checkpoint"]))
            print("        候选分数", info.get("scores"), "修补", info.get("cleanup"))
            save(img, "%s%s.png" % (case, os.environ.get("OUT_TAG") or ""))
        else:
            t0 = time.time()
            new, info = upscale.ai_upscale(img, layer, factor=2, timeout=300)
            print("[%s] %.1f s  %s → %s  模型 %s" % (
                case, time.time() - t0, info["before"], info["after"],
                info["model"]))
            # 只导出新层：删掉原层再把画布缩到新层大小，否则存出来的还是
            # 原来那块画布（大图层超出的部分被裁掉）
            img.remove_layer(layer)
            img.resize(new.get_width(), new.get_height(), 0, 0)
            save(img, "%s%s.png" % (case, os.environ.get("OUT_TAG") or ""))
    except Exception as exc:
        print("!! %s 失败：%s: %s" % (case, type(exc).__name__, exc))
    finally:
        img.delete()

print("探针结束")
