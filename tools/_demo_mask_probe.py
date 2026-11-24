# -*- coding: utf-8 -*-
"""探针：扩图结果层的图层蒙版在原图区域到底是不是 0。"""
import os
import sys
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gio, Gegl

ROOT = r"C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
sys.path.insert(0, os.path.join(ROOT, "tools"))

spec = importlib.util.spec_from_file_location(
    "ai_expand_plugin", os.path.join(ROOT, "plugin", "ai-outpaint", "ai-outpaint.py"))
emod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emod)

import ai_client
import mock_comfy

srv = mock_comfy.start_mock()
try:
    client = ai_client.ComfyClient(srv.url, timeout=10, poll=0.05)
    W, H = 80, 60
    img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    lay = Gimp.Layer.new(img, "src", W, H, Gimp.ImageType.RGBA_IMAGE, 100,
                         Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    grey = bytes([200, 190, 170, 255]) * (W * H)
    buf = lay.get_shadow_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, W, H), "R'G'B'A u8", grey)
    buf.flush()
    lay.merge_shadow(True)

    info = emod.ai_expand(img, lay, "x", edges="left", amount=20,
                          variations=1, pick="off", client=client, timeout=30)
    print("画布", info["canvas"], "扩边", info["edges"])

    top = img.get_layers()[0]
    mask = top.get_mask()
    print("顶层", top.get_name(), "尺寸", top.get_width(), top.get_height(),
          "有蒙版", mask is not None)
    M = mask
    mw, mh = M.get_width(), M.get_height()
    raw = M.get_buffer().get(Gegl.Rectangle.new(0, 0, mw, mh), 1.0,
                             "Y u8", Gegl.AbyssPolicy.NONE)
    vals = list(bytes(bytearray(raw)))
    print("蒙版尺寸", mw, mh, "取值集合（抽样）", sorted(set(vals[::13]))[:12])
    y = mh // 2
    print("沿 x 的蒙版值（y=%d）：" % y)
    for x in range(0, mw, 4):
        print("   x=%3d  %3d" % (x, vals[y * mw + x]))
    inside = vals[y * mw + min(mw - 1, 60)]
    print("原图深处(x=60) 蒙版 =", inside)
    img.delete()
finally:
    srv.stop()
