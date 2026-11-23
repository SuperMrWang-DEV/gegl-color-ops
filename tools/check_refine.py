#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选择并遮住：数学层回归（不需要 GIMP、不需要显卡）。

跑法：python tools/check_refine.py
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import refine_math as RM                                    # noqa: E402

PASS = 0
FAIL = []


def ok(label, cond, detail=None):
    global PASS
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL.append(label)
        print("  FAIL %s   %s" % (label, detail if detail is not None else ""))


def section(title):
    print("\n== %s ==" % title)


def mask_from(fn, w, h):
    return bytes(bytearray(clamp(fn(x, y)) for y in range(h) for x in range(w)))


def clamp(v):
    return 0 if v < 0 else (255 if v > 255 else int(v))


def row(mask, w, y):
    return list(mask[y * w:(y + 1) * w])


def crossing(mask, w, y, lo=0, hi=255):
    """一行上第一个 >= 128 的 x（50% 等值线的近似位置）。"""
    r = row(mask, w, y)
    for x, v in enumerate(r):
        if v >= 128:
            return x
    return w


# ---- 1. LUT ----------------------------------------------------------------
section("1. 查表 / LUT")

lin2srgb = RM.linear_to_srgb_lut()
srgb2lin = RM.srgb_to_linear_lut()
ok("linear→sRGB 端点正确", (lin2srgb[0], lin2srgb[255]) == (0, 255),
   (lin2srgb[0], lin2srgb[255]))
ok("GIMP 实测点：线性 107 → 约 173（通道读回来的真实值）",
   abs(lin2srgb[107] - 173) <= 2, lin2srgb[107])
ok("线性 128 → 约 188（实测值）", abs(lin2srgb[128] - 188) <= 2, lin2srgb[128])
ok("linear→sRGB 单调不减",
   all(lin2srgb[i] <= lin2srgb[i + 1] for i in range(255)))
ok("sRGB→linear 单调不减",
   all(srgb2lin[i] <= srgb2lin[i + 1] for i in range(255)))
ok("两个表互为逆（±2）",
   all(abs(srgb2lin[lin2srgb[i]] - i) <= 2 for i in range(0, 256, 3)),
   [(i, srgb2lin[lin2srgb[i]]) for i in range(0, 256, 51)])

lut = RM.curve_lut(0, 0)
ok("对比度 0 / 移动 0 是恒等表", lut == RM.identity_lut())

lut_c = RM.curve_lut(50, 0)
ok("对比度把 64 压暗、192 提亮", lut_c[64] < 64 and lut_c[192] > 192,
   (lut_c[64], lut_c[192]))
ok("对比度不动 0.5 附近", abs(lut_c[128] - 128) <= 2, lut_c[128])
ok("对比度是 S 形（单调）", all(lut_c[i] <= lut_c[i + 1] for i in range(255)))

lut_up = RM.curve_lut(0, 40)
lut_dn = RM.curve_lut(0, -40)
ok("移动边缘 +40 = 外扩（127 → 更亮）", lut_up[127] > 127, lut_up[127])
ok("移动边缘 -40 = 内缩（127 → 更暗）", lut_dn[127] < 127, lut_dn[127])
ok("移动边缘会连 0 一起抬（外扩就该这样），255 仍夹在 255",
   (lut_up[0] > 0, lut_up[255]) == (True, 255), (lut_up[0], lut_up[255]))
ok("apply_lut 走 C 的 translate（24 MP 也不慢）",
   RM.apply_lut(b"\x00\x80\xff", lut_c) == bytes([lut_c[0], lut_c[128], lut_c[255]]))


# ---- 2. 盒式模糊 -----------------------------------------------------------
section("2. 盒式模糊")

w, h = 32, 8
flat = bytes([77]) * (w * h)
ok("半径 0 = 恒等", RM.box_blur(flat, w, h, 0) == flat)
ok("常数图模糊后还是常数", RM.box_blur(flat, w, h, 3) == flat)

# 居中的方块（8..23）：关于 15.5 对称，才谈得上「左右对称」
step = mask_from(lambda x, y: 255 if 8 <= x < 24 else 0, w, h)
blurred = RM.box_blur(step, w, h, 2)
r = row(blurred, w, 4)
ok("模糊把硬台阶摊开", len([v for v in r if 0 < v < 255]) >= 3,
   [v for v in r if 0 < v < 255])
ok("模糊后 50% 线还在原处", abs(crossing(blurred, w, 4) - 8) <= 1,
   crossing(blurred, w, 4))
ok("模糊不改变总能量太多（±3%）",
   abs(sum(blurred) - sum(step)) <= 0.03 * sum(step),
   (sum(blurred), sum(step)))
ok("左右对称", r == list(reversed(r)), (r[:6], r[-6:]))

# 竖直方向也要对：中间一块（h=8 → 关于 3.5 对称）
step_v = mask_from(lambda x, y: 255 if 2 <= y < 6 else 0, w, 8)
bv = RM.box_blur(step_v, w, 8, 2)
col = [bv[y * w + 10] for y in range(8)]
ok("竖直方向也摊开且对称", col == list(reversed(col)) and len(set(col)) >= 4, col)

# 单像素尖刺要被抹掉
spike = bytearray(w * h)
spike[4 * w + 10] = 255
smoothed = RM.box_blur(spike, w, h, 2)
ok("单像素尖刺被摊平（不超过 20）", max(smoothed) <= 20, max(smoothed))


# ---- 3. 高斯 ---------------------------------------------------------------
section("3. 高斯（三次盒式逼近）")

ok("sigma=0 时半径表为空", RM._gauss_radii(0) == [])
ok("sigma 越大半径越大",
   sum(RM._gauss_radii(1)) < sum(RM._gauss_radii(6)))
# 高斯用它自己的一刀切：从左边 0 爬到右边 255，才能验「单调」和「50% 不漂」
halves = mask_from(lambda x, y: 255 if x >= 16 else 0, w, h)
g = RM.gaussian_blur(halves, w, h, 3.0)
rg = row(g, w, 4)
ok("高斯后仍是单调剖面（从 0 爬到 255）",
   all(rg[i] <= rg[i + 1] for i in range(w - 1)), rg)
ok("高斯后 50% 线不漂", abs(crossing(g, w, 4) - 16) <= 1, crossing(g, w, 4))
r_half = row(RM.box_blur(halves, w, h, 2), w, 4)
ok("高斯比同半径盒式更软（过渡区更宽）",
   len([v for v in rg if 0 < v < 255]) >= len([v for v in r_half if 0 < v < 255]),
   (len([v for v in rg if 0 < v < 255]),
    len([v for v in r_half if 0 < v < 255])))


# ---- 4. 边缘吸附 -----------------------------------------------------------
section("4. 边缘吸附")

W, H = 60, 20
# 蒙版边界在 x=20（比真实边缘左 6 px，模拟 AI 抠图糊出去的那圈）
mask_edge = mask_from(lambda x, y: 255 if x >= 20 else 0, W, H)
# 画面真实边缘在 x=26：左边暗、右边亮
gray = mask_from(lambda x, y: 30 if x < 26 else 220, W, H)
strength = RM.edge_strength(gray, W, H)
ok("边缘强度在真实边界处最大",
   max(strength[y * W + x] for y in range(H) for x in range(18, 34)) > 100,
   max(strength))
ok("远离边界的地方强度接近 0", strength[10 * W + 5] == 0, strength[10 * W + 5])

# 先把蒙版边界做成软边（硬边在 band 之外不会被处理）
soft = RM.box_blur(mask_edge, W, H, 2)
snapped = RM.snap_to_edges(soft, strength, W, H, radius=8, smart=True)
before = crossing(soft, W, 10)
after = crossing(snapped, W, 10)
ok("吸附把边界往真实边缘推（20+ → 更靠右）", after > before, (before, after))
ok("吸附落在真实边缘附近（26±3）", abs(after - 26) <= 3, (before, after))
ok("吸附不动主体深处", snapped[10 * W + 50] == soft[10 * W + 50])
ok("吸附不动背景深处", snapped[10 * W + 2] == soft[10 * W + 2])
ok("radius=0 时原样返回", RM.snap_to_edges(soft, strength, W, H, 0) == soft)

# 没有可吸附的边缘时不该乱动
flat_gray = bytes([128]) * (W * H)
flat_strength = RM.edge_strength(flat_gray, W, H)
still = RM.snap_to_edges(soft, flat_strength, W, H, radius=8, smart=True)
ok("画面没有边缘时不乱动", abs(crossing(still, W, 10) - before) <= 1,
   (before, crossing(still, W, 10)))


# ---- 5. 主流程 -------------------------------------------------------------
section("5. 精修主流程")

base = RM.box_blur(mask_edge, W, H, 2)
ok("全部参数为 0 = 恒等", RM.refine_mask(base, W, H) == base)

feathered = RM.refine_mask(base, W, H, feather=8.0)
ok("羽化让过渡区变宽",
   len([v for v in row(feathered, W, 10) if 0 < v < 255])
   > len([v for v in row(base, W, 10) if 0 < v < 255]),
   (len([v for v in row(feathered, W, 10) if 0 < v < 255]),
    len([v for v in row(base, W, 10) if 0 < v < 255])))

hard = RM.refine_mask(feathered, W, H, contrast=100)
ok("对比度 100 能把羽化的软边重新压硬",
   len([v for v in row(hard, W, 10) if 0 < v < 255])
   < len([v for v in row(feathered, W, 10) if 0 < v < 255]))

grow = RM.refine_mask(base, W, H, shift=50)
shrink = RM.refine_mask(base, W, H, shift=-50)
ok("移动边缘 +50 外扩", crossing(grow, W, 10) < crossing(base, W, 10),
   (crossing(grow, W, 10), crossing(base, W, 10)))
ok("移动边缘 -50 内缩", crossing(shrink, W, 10) > crossing(base, W, 10),
   (crossing(shrink, W, 10), crossing(base, W, 10)))

smooth = RM.refine_mask(base, W, H, smooth=3.0)
ok("平滑不改变 50% 位置（±1）",
   abs(crossing(smooth, W, 10) - crossing(base, W, 10)) <= 1)

st = RM.mask_stats(base)
ok("mask_stats 三项加起来等于像素数",
   st["solid"] + st["empty"] + st["soft"] == st["pixels"], st)


# ---- 6. 去色边 -------------------------------------------------------------
section("6. 去色边")

FW, FH = 24, 6
# 合成：前景红 (220,30,30)，背景白 (250,250,250)，边界 alpha 0.5
fg, bgc = (220, 30, 30), (250, 250, 250)
alphas = [0 if x < 10 else (128 if x < 13 else 255) for x in range(FW)]
rgba = bytearray(FW * FH * 4)
mask = bytearray(FW * FH)
bg_plane = bytearray(FW * FH * 3)
for y in range(FH):
    for x in range(FW):
        i = y * FW + x
        a = alphas[x]
        mask[i] = a
        bg_plane[i * 3:i * 3 + 3] = bytes(bgc)
        af = a / 255.0
        for c in range(3):
            rgba[i * 4 + c] = clamp(round(fg[c] * af + bgc[c] * (1 - af)))
        rgba[i * 4 + 3] = 255

ok("合成出来的边缘像素确实是「红混白」的浅红",
   rgba[(3 * FW + 11) * 4] > 200 and rgba[(3 * FW + 11) * 4 + 1] > 120,
   rgba[(3 * FW + 11) * 4:(3 * FW + 11) * 4 + 3])

fixed, changed = RM.decontaminate(rgba, mask, bg_plane, FW, FH, strength=1.0)
ok("去色边处理了边缘带", changed > 0, changed)
new_edge = fixed[(3 * FW + 11) * 4:(3 * FW + 11) * 4 + 3]
ok("边缘像素被拉回前景色（红通道降下来）",
   abs(new_edge[0] - fg[0]) <= 12, (new_edge, fg))
ok("边缘像素绿通道也回到前景（不再发白）",
   abs(new_edge[1] - fg[1]) <= 12, (new_edge, fg))
ok("完全透明的像素不动",
   fixed[(3 * FW + 0) * 4:(3 * FW + 0) * 4 + 3]
   == rgba[(3 * FW + 0) * 4:(3 * FW + 0) * 4 + 3])
ok("完全不透明的像素不动", fixed[(3 * FW + 20) * 4:(3 * FW + 20) * 4 + 3]
   == rgba[(3 * FW + 20) * 4:(3 * FW + 20) * 4 + 3])
ok("strength=0 时原样返回", RM.decontaminate(rgba, mask, bg_plane, FW, FH, 0)[1] == 0)
half, _ = RM.decontaminate(rgba, mask, bg_plane, FW, FH, strength=0.5)
he = half[(3 * FW + 11) * 4 + 1]
ok("strength 是线性插值（一半在中间）",
   rgba[(3 * FW + 11) * 4 + 1] > he > new_edge[1] or
   rgba[(3 * FW + 11) * 4 + 1] < he < new_edge[1],
   (rgba[(3 * FW + 11) * 4 + 1], he, new_edge[1]))


# ---- 7. 预览合成 -----------------------------------------------------------
section("7. 预览合成")

PW, PH = 16, 4
gray_rgba = bytearray(PW * PH * 4)
for i in range(PW * PH):
    gray_rgba[i * 4:i * 4 + 3] = b"\x80\x80\x80"
    gray_rgba[i * 4 + 3] = 255
pmask = mask_from(lambda x, y: 255 if x >= 8 else 0, PW, PH)

white_bg = RM.compose_preview(gray_rgba, pmask, PW, PH, "white")
ok("白底：透明处纯白", white_bg[0:3] == b"\xff\xff\xff", white_bg[0:3])
ok("白底：不透明处是原像素", white_bg[(2 * PW + 12) * 4:(2 * PW + 12) * 4 + 3]
   == b"\x80\x80\x80")
black_bg = RM.compose_preview(gray_rgba, pmask, PW, PH, "black")
ok("黑底：透明处纯黑", black_bg[0:3] == b"\x00\x00\x00", black_bg[0:3])
checker = RM.compose_preview(gray_rgba, pmask, PW, PH, "checker", cell=2)
vals = set(checker[(0 * PW + x) * 4] for x in range(4))
ok("棋盘格有两种深浅", len(vals) == 2, vals)
red = RM.compose_preview(gray_rgba, pmask, PW, PH, "red")
ok("红蒙版：主体内偏红", red[(2 * PW + 12) * 4] > red[(2 * PW + 12) * 4 + 1],
   red[(2 * PW + 12) * 4:(2 * PW + 12) * 4 + 3])
ok("红蒙版：主体外不动", red[(2 * PW + 2) * 4:(2 * PW + 2) * 4 + 3] == b"\x80\x80\x80")


# ---- 8. 性能与边界 ---------------------------------------------------------
section("8. 性能 / 边界")

import time                                               # noqa: E402
big = mask_from(lambda x, y: 255 if x > 200 else 0, 400, 300)
t0 = time.time()
RM.gaussian_blur(big, 400, 300, 4.0)
dt = time.time() - t0
ok("400×300 高斯 < 1 s（当前 %.2fs）" % dt, dt < 1.0, dt)

ok("宽度 1 的图不炸", len(RM.box_blur(b"\x00\xff", 1, 2, 3)) == 2)
ok("半径大于图宽的模糊不炸", len(RM.box_blur(bytes(4), 2, 2, 7)) == 4)
ok("luma 权重和为 256", 77 + 150 + 29 == 256)
ok("luma 黑白端点", (RM.luma(b"\x00\x00\x00\xff", 1, 1)[0],
                    RM.luma(b"\xff\xff\xff\xff", 1, 1)[0]) == (0, 255))


print("\n" + "=" * 60)
if FAIL:
    print("失败 %d 项 / 通过 %d 项" % (len(FAIL), PASS))
    for f in FAIL:
        print("  - %s" % f)
    sys.exit(1)
print("全部通过：%d 项检查" % PASS)
