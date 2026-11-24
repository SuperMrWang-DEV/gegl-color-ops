#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成所有算子对比图共用的测试卡（960×640）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/make_test_card.py').read())" --quit

上半是真实照片（有自然纹理和真实色，看得出肤色、草木、天空这类偏色），
下半是三条测试带：

· 中间偏左 24 色卡 —— 色相/饱和度/通道混合类算子在这里最直观
· 中下 11 级灰阶阶梯 + 肤色渐变 —— 明暗映射、曲线、色阶看这里
· 右下 细栅格 + 确定性噪声 —— 锐化、降噪、噪点类算子看这里

照片和测试带放在同一张卡上，是为了让「整幅都变」和「只动某些色」能在一张图里
同时看出来。
"""
import os

import cairo

ROOT = os.environ.get("LB_REPO") or \
    r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
PHOTO = r"D:\ComfyUI\test-out\t2i.png"
OUT = os.path.join(ROOT, "tools", "_testcard.png")

W, H = 960, 640
PHOTO_H = 420
BAND_Y = PHOTO_H
BAND_H = H - PHOTO_H
COL = W / 3.0

# 近似 Macbeth 的 24 色（sRGB 0…1）
CHART = [
    (0.45, 0.32, 0.26), (0.76, 0.58, 0.53), (0.36, 0.48, 0.62),
    (0.35, 0.42, 0.27), (0.50, 0.50, 0.68), (0.40, 0.72, 0.63),
    (0.85, 0.48, 0.18), (0.29, 0.36, 0.64), (0.76, 0.33, 0.36),
    (0.36, 0.24, 0.42), (0.62, 0.74, 0.24), (0.90, 0.63, 0.18),
    (0.20, 0.24, 0.58), (0.28, 0.58, 0.30), (0.69, 0.20, 0.23),
    (0.93, 0.78, 0.12), (0.60, 0.24, 0.55), (0.12, 0.66, 0.72),
    (0.94, 0.94, 0.92), (0.79, 0.79, 0.77), (0.63, 0.63, 0.61),
    (0.47, 0.47, 0.46), (0.32, 0.32, 0.31), (0.18, 0.18, 0.18),
]


def photo(cr):
    src = cairo.ImageSurface.create_from_png(PHOTO)
    sw, sh = src.get_width(), src.get_height()
    # 源图按 960:420 的比例居中裁一条，避免拉伸变形
    want = sw * PHOTO_H / float(W)          # 需要的高度
    if want <= sh:
        sy = (sh - want) / 2.0
    else:
        sy, want = 0.0, sh
    cr.save()
    cr.rectangle(0, 0, W, PHOTO_H)
    cr.clip()
    cr.translate(0, 0)
    cr.scale(W / float(sw), PHOTO_H / float(want))
    cr.set_source_surface(src, 0, -sy)
    cr.get_source().set_filter(cairo.FILTER_GOOD)
    cr.paint()
    cr.restore()


def color_chart(cr, x0, y0):
    cols, rows = 6, 4
    cw, ch = COL / cols, BAND_H / float(rows)
    for i, (r, g, b) in enumerate(CHART):
        cx = x0 + (i % cols) * cw
        cy = y0 + (i // cols) * ch
        cr.set_source_rgb(r, g, b)
        cr.rectangle(cx + 1, cy + 1, cw - 2, ch - 2)
        cr.fill()


def gray_wedge(cr, x0, y0):
    # 上半：11 级阶梯（看得见量化）；下半：连续灰阶 + 肤色渐变
    steps, sw = 11, COL / 11.0
    for i in range(steps):
        v = i / float(steps - 1)
        cr.set_source_rgb(v, v, v)
        cr.rectangle(x0 + i * sw, y0, sw + 1, BAND_H / 2.0 - 12)
        cr.fill()
    # 连续灰阶
    grad = cairo.LinearGradient(x0, 0, x0 + COL, 0)
    grad.add_color_stop_rgb(0, 0, 0, 0)
    grad.add_color_stop_rgb(1, 1, 1, 1)
    cr.set_source(grad)
    cr.rectangle(x0, y0 + BAND_H / 2.0 - 10, COL / 2.0, BAND_H / 2.0 + 10)
    cr.fill()
    # 肤色（浅 → 深），用来判断饱和度/肤色保护
    sk = cairo.LinearGradient(x0 + COL / 2.0, 0, x0 + COL, 0)
    sk.add_color_stop_rgb(0.0, 0.98, 0.86, 0.76)
    sk.add_color_stop_rgb(0.5, 0.82, 0.62, 0.48)
    sk.add_color_stop_rgb(1.0, 0.45, 0.29, 0.21)
    cr.set_source(sk)
    cr.rectangle(x0 + COL / 2.0, y0 + BAND_H / 2.0 - 10,
                 COL / 2.0, BAND_H / 2.0 + 10)
    cr.fill()


def texture(cr, x0, y0):
    """上半细栅格（锐化看得到边缘），下半确定性噪声（降噪看得到颗粒）。"""
    half = BAND_H / 2.0
    cr.set_source_rgb(0.5, 0.5, 0.5)
    cr.rectangle(x0, y0, COL, half - 4)
    cr.fill()
    cr.set_line_width(1.0)
    cr.set_source_rgb(0.12, 0.12, 0.12)
    for i in range(0, int(COL), 4):
        cr.move_to(x0 + i + 0.5, y0)
        cr.line_to(x0 + i + 0.5, y0 + half - 4)
    for j in range(0, int(half) - 4, 4):
        cr.move_to(x0, y0 + j + 0.5)
        cr.line_to(x0 + COL, y0 + j + 0.5)
    cr.stroke()
    cr.set_source_rgb(0.95, 0.95, 0.95)
    cr.arc(x0 + COL * 0.5, y0 + half * 0.45, 16, 0, 6.2832)
    cr.fill()

    # 噪声块：固定 LCG，保证每次生成完全一致（回归要能逐字节比较）
    nw, nh = 160, 80
    stride = nw * 4
    buf = bytearray(stride * nh)
    seed = 0x2F6E2B1
    for i in range(nw * nh):
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        v = 60 + (seed >> 16) % 140
        o = i * 4
        buf[o] = v
        buf[o + 1] = v + (seed >> 8) % 12
        buf[o + 2] = v - (seed >> 4) % 12
        buf[o + 3] = 255
    ns = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, nw, nh, stride)
    cr.save()
    cr.rectangle(x0, y0 + half + 4, COL, half - 4)
    cr.clip()
    cr.translate(x0, y0 + half + 4)
    cr.scale(COL / float(nw), (half - 4) / float(nh))
    cr.set_source_surface(ns, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_NEAREST)
    cr.paint()
    cr.restore()


surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
cr = cairo.Context(surface)
cr.set_source_rgb(1, 1, 1)
cr.paint()

photo(cr)
color_chart(cr, 0, BAND_Y)
gray_wedge(cr, COL, BAND_Y)
texture(cr, COL * 2, BAND_Y)

# 分栏细线
cr.set_source_rgba(0, 0, 0, 0.45)
cr.set_line_width(1)
for x in (COL, COL * 2):
    cr.move_to(x + 0.5, BAND_Y)
    cr.line_to(x + 0.5, H)
cr.move_to(0, BAND_Y + 0.5)
cr.line_to(W, BAND_Y + 0.5)
cr.stroke()

os.makedirs(os.path.dirname(OUT), exist_ok=True)
surface.write_to_png(OUT)
print("saved", OUT, W, H)

# 第二张：同样的内容缩到中间七成、带圆角，四周透明。
# 图层样式（投影/发光）和所有吃 alpha 的算子都得有透明区域才看得出来，
# 拿不透明的卡去跑，结果和原图一模一样。
ALPHA_OUT = os.path.join(ROOT, "tools", "_testcard_alpha.png")
asurf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
acr = cairo.Context(asurf)
acr.set_source_rgba(0, 0, 0, 0)
acr.paint()

SCALE, RAD = 0.72, 26
dw, dh = W * SCALE, H * SCALE
ax, ay = (W - dw) / 2.0, (H - dh) / 2.0
acr.new_path()
acr.move_to(ax + RAD, ay)
acr.line_to(ax + dw - RAD, ay)
acr.arc(ax + dw - RAD, ay + RAD, RAD, -1.5708, 0)
acr.line_to(ax + dw, ay + dh - RAD)
acr.arc(ax + dw - RAD, ay + dh - RAD, RAD, 0, 1.5708)
acr.line_to(ax + RAD, ay + dh)
acr.arc(ax + RAD, ay + dh - RAD, RAD, 1.5708, 3.1416)
acr.line_to(ax, ay + RAD)
acr.arc(ax + RAD, ay + RAD, RAD, 3.1416, 4.7124)
acr.close_path()
acr.clip()
acr.translate(ax, ay)
acr.scale(SCALE, SCALE)
acr.set_source_surface(surface, 0, 0)
acr.get_source().set_filter(cairo.FILTER_GOOD)
acr.paint()
asurf.write_to_png(ALPHA_OUT)
print("saved", ALPHA_OUT, W, H)
