#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：真跑一次三候选填充，再把挑选窗离屏渲染成 PNG。"""
import importlib.util
import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gimp, Gio, Gtk, Gdk

REPO = r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))
import candidate_picker as CP

spec = importlib.util.spec_from_file_location(
    "aii", os.path.join(REPO, "plugin", "ai-inpaint", "ai-inpaint.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SRC = r"D:\ComfyUI\ComfyUI\input\lb-img2img-src.png"
SEL = (10, 1000, 470, 120)
PROMPT = "plain white cotton t-shirt fabric with soft folds, natural cloth texture"

img = Gimp.Image.new(744, 1120, Gimp.ImageBaseType.RGB)
base = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                            Gio.File.new_for_path(SRC))
img.insert_layer(base, None, 0)
img.select_rectangle(Gimp.ChannelOps.REPLACE, *SEL)
t0 = time.time()
layer, info = mod.ai_inpaint(
    img, base, PROMPT, checkpoint="sd_xl_base_1.0_inpainting_0.1.safetensors",
    steps=30, cfg=7.5, seed=20261124, denoise=1.0, grow=8, grow_mask_by=8,
    feather=4.0, variations=3, preset="none", variant="auto")
print("耗时 %.1f s  order=%s scores=%s picked=%s"
      % (time.time() - t0, info.get("order"), info.get("scores"),
         info.get("picked")))

cands = [it for it in img.get_layers() if it.get_name().startswith("AI Inpaint")]
print("候选图层：", [c.get_name() for c in cands])
lx, ly = cands[0].get_offsets()[1], cands[0].get_offsets()[2]
focus = (SEL[0] - lx, SEL[1] - ly, SEL[2], SEL[3])
print("图层 offsets", lx, ly, "尺寸", cands[0].get_width(), cands[0].get_height(),
      "focus", focus)
print("crop 窗口", CP._crop_box(cands[0].get_width(), cands[0].get_height(), focus))

dlg, ctx = CP.build_dialog(cands, info.get("order"), info.get("scores"),
                           focus=focus)
ctx["select"](1)

outer = dlg.get_content_area().get_children()[0]
dlg.get_content_area().remove(outer)
dlg.destroy()

off = Gtk.OffscreenWindow.new()
off.add(outer)
off.show_all()
while Gtk.events_pending():
    Gtk.main_iteration()
w, h = off.get_size()
pb = Gdk.pixbuf_get_from_window(off.get_window(), 0, 0, w, h)
out = r"D:\ComfyUI\test-out\picker-ui2.png"
pb.savev(out, "png", [], [])
print("saved", out, w, h)
img.delete()
