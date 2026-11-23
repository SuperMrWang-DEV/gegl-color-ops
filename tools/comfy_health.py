# -*- coding: utf-8 -*-
"""体检：ComfyUI 服务是否可用（列底模 + 真跑一张 img2img）。"""
import os
import sys
import time
import importlib.util

REPO = r"C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
spec = importlib.util.spec_from_file_location(
    "ai_client", os.path.join(REPO, "plugin", "_shared", "ai_client.py"))
AC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AC)

server = AC.normalize_server("")
print("server:", server)
c = AC.ComfyClient(server)

h = c.probe()
print("alive:", h["ok"], "| comfyui:", h["version"], "| err:", h["error"])
if not h["ok"]:
    raise SystemExit(1)
sysinfo = (c.stats().get("system") or {})
print("python:", (sysinfo.get("python_version") or "")[:6],
      "| torch:", sysinfo.get("pytorch_version"))

ckpts = c.checkpoints()
print("底模 %d 个:" % len(ckpts))
for k in ckpts:
    print("  -", k, "| family:", AC.detect_family(k))

W = H = 512
rgba = bytearray(W * H * 4)
for y in range(H):
    for x in range(W):
        o = (y * W + x) * 4
        rgba[o] = 80 + x * 120 // W
        rgba[o + 1] = 110 + y * 90 // H
        rgba[o + 2] = 150
        rgba[o + 3] = 255
src = AC.rgba_png(W, H, bytes(rgba))
print("source png: %d bytes (%dx%d)" % (len(src), W, H))

t0 = time.time()
blob, info = AC.img2img(c, src, "clean natural skin, soft light",
                        steps=12, denoise=0.35, timeout=300)
print("ok  %s  %.1f s  %d bytes  ckpt=%s"
      % (info["filename"], time.time() - t0, len(blob), info["checkpoint"]))
out = os.path.join(os.environ.get("TEMP", "."), "comfy-health.png")
open(out, "wb").write(blob)
print("saved:", out)
