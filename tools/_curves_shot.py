#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：把曲线对话框离屏渲染成 PNG（四个空间各一张）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/_curves_shot.py').read())" --quit

不起真窗口：build_dialog() 造出来但不 run()，整个对话框塞进
Gtk.OffscreenWindow，迭代主循环让 draw 回调跑完，再抓像素。预览那一栏
照样走真实链路（复制图层 → 挂滤镜 → merge_filter → 读回），所以截出来的
预览就是用户拖完曲线会看到的画面。
"""
import importlib.util
import os
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gimp, Gio, Gtk, Gdk

REPO = r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
OUT = r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\outputs"
SRC = r"D:\ComfyUI\test-out\t2i.png"

sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))

spec = importlib.util.spec_from_file_location(
    "cur", os.path.join(REPO, "plugin", "curves", "curves.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
import curve_math as CM

# (空间, 要展示的分量, 曲线串, 标题)
TITLE_H = 34
GAP = 14
CASES = [
    ("lab",  "L", "L 0,0 0.25,0.18 0.75,0.84 1,1|a 0,0 1,1|b 0,0 1,1",
     "LAB   ·   L 通道 S 形 → 提对比"),
    ("lch",  "h", "L 0,0 1,1|C 0,0 1,1|h 0,0.62 0.15,0.62 0.35,0.5 "
                  "0.85,0.5 1,0.62",
     "LCh   ·   色相偏移曲线 → 红转橙金、黄转绿"),
    ("hsv",  "S", "H 0,0.5 1,0.5|S 0,0 0.3,0.42 0.7,0.85 1,1|V 0,0 1,1",
     "HSV   ·   S 通道上凸 → 饱和度提高"),
    ("cmyk", "Y", "C 0,0 1,1|M 0,0 1,1|Y 0,0 0.5,0.38 1,0.9|K 0,0 1,1",
     "CMYK  ·   Y 通道下压 → 褪黄偏洋红"),
]


def draw_title(cr, text, w):
    cr.select_font_face("Microsoft YaHei", 0, 1)   # NORMAL / BOLD
    cr.set_font_size(15)
    cr.set_source_rgb(0.09, 0.09, 0.11)
    cr.move_to(12, 23)
    cr.show_text(text)
    cr.set_source_rgb(0.84, 0.84, 0.86)
    cr.set_line_width(1)
    cr.move_to(0, TITLE_H - 0.5)
    cr.line_to(w, TITLE_H - 0.5)
    cr.stroke()


class Cfg:
    def __init__(self, text):
        self.text = text

    def get_property(self, key):
        return self.text if key == "curves" else "filter"


def pump(rounds=40):
    for _ in range(rounds):
        while Gtk.events_pending():
            Gtk.main_iteration()
        import time
        time.sleep(0.02)


os.makedirs(OUT, exist_ok=True)

img = Gimp.Image.new(512, 512, Gimp.ImageBaseType.RGB)
layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                            Gio.File.new_for_path(SRC))
img.insert_layer(layer, None, 0)

made = []
for space, chan, text, title in CASES:
    dlg, ctx = mod.build_dialog(None, Cfg(text), img, layer, space)
    names = [n for n, _ring in CM.SPACES[space]["parts"]]
    ctx["combo"].set_active(names.index(chan))
    ctx["refresh"]()

    # 对话框是 toplevel，塞不进 OffscreenWindow（"Can't set a parent on a
    # toplevel widget"）。只把 content_area 的主体搬出来，action area 不要。
    # 注意：这一句 show_all 会**掩盖**插件自身忘写 show_all 的 bug —— 早先四张
    # 截图看起来都正常，实际菜单里弹出来只有一个空壳。要验真实显示效果用
    # tools/_curves_dialog_e2e.py（走 show_dialog 的真实路径）。
    dlg.show_all()
    pump(4)
    body = dlg.get_content_area().get_children()[0]
    dlg.get_content_area().remove(body)
    dlg.hide()

    off = Gtk.OffscreenWindow.new()
    off.add(body)
    # 离屏窗口不会自己撑到内容的自然宽度（get_size 停在 644，右边的下拉框
    # 就被裁掉了），先问内容要多少，再把窗口 resize 过去，布局才收敛。
    nw = max(body.get_preferred_width()) + 16   # 自然宽度还差一截，见下
    nh = max(body.get_preferred_height())
    off.set_default_size(nw, nh)
    off.show_all()
    off.resize(nw, nh)
    pump(20)
    w, h = off.get_size()
    print("  natural %dx%d -> window %dx%d" % (nw, nh, w, h))

    # pixbuf_get_from_window 在离屏窗口上抓不到 DrawingArea 的内容（拿到的是
    # 空表面），改成直接 cairo 递归绘制：widget.draw() 会把子控件的 draw
    # 回调全跑一遍，画进 ImageSurface，再存 PNG。
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h + TITLE_H)
    cr = cairo.Context(surface)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    draw_title(cr, title, w)
    cr.translate(0, TITLE_H)
    off.draw(cr)
    cr.identity_matrix()

    path = os.path.join(OUT, "curves-%s.png" % space)
    surface.write_to_png(path)
    print("saved %s  %dx%d  chan=%s" % (path, w, h + TITLE_H, chan))
    made.append((path, w, h + TITLE_H))

    off.remove(body)
    dlg.destroy()
    pump(4)

img.delete()

# 2×2 拼一张，顺序按 CASES
if len(made) == 4:
    import cairo
    cw = max(m[1] for m in made)
    chh = max(m[2] for m in made)
    sheet = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                               cw * 2 + GAP * 3, chh * 2 + GAP * 3)
    sc = cairo.Context(sheet)
    sc.set_source_rgb(0.97, 0.97, 0.98)
    sc.paint()
    for i, (path, _ww, _hh) in enumerate(made):
        src = cairo.ImageSurface.create_from_png(path)
        x = GAP + (i % 2) * (cw + GAP)
        y = GAP + (i // 2) * (chh + GAP)
        sc.set_source_surface(src, x, y)
        sc.paint()
    sheet_path = os.path.join(OUT, "curves-all.png")
    sheet.write_to_png(sheet_path)
    print("saved %s" % sheet_path)

print("done")
