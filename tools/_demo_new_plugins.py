# -*- coding: utf-8 -*-
"""演示：在真机（真 ComfyUI + 真 GIMP）上跑 AI 扩图 / AI 超分 几组例子。

    "GIMP/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/_demo_new_plugins.py', encoding='utf-8').read())" --quit

环境变量：
    CASES=expand-h,expand-v,expand-all,upscale-2x,upscale-crop
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
         (os.environ.get("CASES")
          or "expand-h,expand-v,expand-all,upscale-2x,upscale-crop").split(",")
         if c.strip()]

TAG = os.environ.get("OUT_TAG") or ""

PROMPT = ("a young woman leaning against a light grey wall with a teal "
          "painted window frame, soft natural daylight, photorealistic")


def new_image(w=SW, h=SH):
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(SRC))
    if layer is not None:
        img.insert_layer(layer, None, 0)
    return img, layer


def save(img, name):
    out = os.path.join(OUTDIR, name)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    print("  已导出", out)
    return out


def run_expand(name, edges, amount):
    img, layer = new_image()
    try:
        t0 = time.time()
        kw = {}
        if os.environ.get("FEATHER"):
            kw["feather"] = int(os.environ["FEATHER"])
        info = expand.ai_expand(img, layer, PROMPT, edges=edges, amount=amount,
                                variations=2, pick="off", timeout=900, **kw)
        dt = time.time() - t0
        print("[%s] %.1f s  画布 %s  扩边 %s" % (name, dt, info["canvas"],
                                                info["edges"]))
        print("        底模 %s  分数 %s  修补 %s" % (
            info["checkpoint"], info.get("scores"), info.get("cleanup")))
        save(img, "demo-%s%s.png" % (name, TAG))
        return {"name": name, "sec": dt, "canvas": info["canvas"],
                "checkpoint": info["checkpoint"]}
    except Exception as exc:
        print("!! %s 失败：%s: %s" % (name, type(exc).__name__, exc))
        return None
    finally:
        img.delete()


def run_upscale(name, factor, crop=None):
    img, layer = new_image()
    try:
        if crop:
            cx, cy, cw, ch = crop
            img.resize(cw, ch, -cx, -cy)
            layer = img.flatten()
        t0 = time.time()
        new, info = upscale.ai_upscale(img, layer, factor=factor, timeout=300)
        dt = time.time() - t0
        print("[%s] %.1f s  %s → %s  模型 %s" % (
            name, dt, info["before"], info["after"], info["model"]))
        base = os.path.join(OUTDIR, "demo-%s%s-src.png" % (name, TAG))
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                       Gio.File.new_for_path(base), None)
        img.remove_layer(layer)
        img.resize(new.get_width(), new.get_height(), 0, 0)
        save(img, "demo-%s%s.png" % (name, TAG))
        return {"name": name, "sec": dt, "before": info["before"],
                "after": info["after"], "src": base}
    except Exception as exc:
        print("!! %s 失败：%s: %s" % (name, type(exc).__name__, exc))
        return None
    finally:
        img.delete()


results = []
for case in CASES:
    if case == "expand-h":
        results.append(run_expand(case, "horizontal", 240))
    elif case == "expand-v":
        results.append(run_expand(case, "vertical", 200))
    elif case == "expand-all":
        results.append(run_expand(case, "all", 160))
    elif case == "upscale-2x":
        results.append(run_upscale(case, 2))
    elif case == "upscale-crop":
        # 脸上方一块 320×320：留给自己在拼图里做 100% 像素对比
        results.append(run_upscale(case, 2, crop=(300, 380, 320, 320)))

print("演示生成结束：", [r["name"] for r in results if r])
