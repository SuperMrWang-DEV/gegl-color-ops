# -*- coding: utf-8 -*-
"""量一下对话框预览的刷新耗时（放大预览后的手感检查）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/_curves_perf.py').read())" --quit
"""
import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

ROOT = os.environ.get("LB_REPO") or \
    r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))
sys.path.insert(0, os.path.join(ROOT, "plugin", "curves"))

import importlib.util
spec = importlib.util.spec_from_file_location(
    "lb_curves_perf", os.path.join(ROOT, "plugin", "curves", "curves.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Cfg(object):
    def get_property(self, _n):
        return None


def bench(path, space="lab"):
    img = Gimp.Image.new(1, 1, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(path))
    img.insert_layer(layer, None, 0)
    img.resize(img.get_width(), img.get_height(), 0, 0)
    dlg, ctx = mod.build_dialog(None, Cfg(), img, layer, space)
    dlg.show_all()
    t = []
    for _ in range(4):
        t0 = time.time()
        ctx["refresh"]()
        t.append((time.time() - t0) * 1000.0)
    pb = ctx["pixbuf"]
    print("  %-26s %4dx%-4d  预览 %dx%d  首帧 %.0f ms  后续 %s ms" % (
        os.path.basename(path), layer.get_width(), layer.get_height(),
        pb.get_width(), pb.get_height(), t[0],
        " ".join("%.0f" % x for x in t[1:])))
    dlg.destroy()
    img.delete()


def big_copy(src, dst, w, h):
    """没有 PIL，就借 GIMP 自己缩一张大图出来当压力样本。"""
    img = Gimp.Image.new(1, 1, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(src))
    img.insert_layer(layer, None, 0)
    img.resize(w, h, 0, 0)
    layer.scale(w, h, False)
    img.flatten()
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(dst), None)
    img.delete()


BIG = os.path.join(ROOT, "tools", "_testcard_big.png")
if not os.path.exists(BIG):
    big_copy(os.path.join(ROOT, "tools", "_testcard.png"), BIG, 1600, 1067)

for p in [os.path.join(ROOT, "tools", "_testcard.png"), BIG,
          r"D:\ComfyUI\test-out\up-src.png"]:
    if os.path.exists(p):
        bench(p)
    else:
        print("缺图", p)
