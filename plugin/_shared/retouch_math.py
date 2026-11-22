#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 磨皮预修的纯数学层（不 import gi，可在普通 Python 里测）
 ---------------------------------------------------------------------------
 干什么   给定「原图亮度」和「参考图亮度」，算出三样东西：

           delta   = 参考 − 原图       （正数=这里该提亮，负数=该压暗）
           蒙版    提亮 / 压暗两张 8 位灰度（双曲线磨皮用）
           灰层    128±偏移的 8 位灰度（中性灰磨皮用，柔光下正好抵消 delta）

 为什么单独一层   磨皮插件里最容易错的就是这些公式，而它们一行 GIMP API 都不
           需要。放在这里就能在 CI 上（无显卡、无 GIMP）跑断言：反解出来的
           灰层放进柔光公式，必须能把原图推回参考图。

 单位   像素一律 0…1 的浮点（不是 0…255），8 位量化只在最后出口做一次。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math

# Rec.709 亮度权重。皮肤上蓝通道几乎不贡献亮度，用 0.299/0.587/0.114 会把
# 偏黄的肤色算暗一档，蒙版跟着偏。
LUMA_R, LUMA_G, LUMA_B = 0.2126, 0.7152, 0.0722


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


# ---- 亮度 / luminance -------------------------------------------------------

def luma(rgba, n=None):
    """RGBA 8 位紧排字节 → 每像素亮度（0…1 浮点）。"""
    if n is None:
        n = len(rgba) // 4
    out = [0.0] * n
    r, g, b = LUMA_R, LUMA_G, LUMA_B
    for i in range(n):
        j = i * 4
        out[i] = (rgba[j] * r + rgba[j + 1] * g + rgba[j + 2] * b) / 255.0
    return out


def luma_from_rgb(rgb, n):
    """RGB 3 通道紧排（PNG 解出来的那种）→ 亮度。"""
    out = [0.0] * n
    for i in range(n):
        j = i * 3
        out[i] = (rgb[j] * LUMA_R + rgb[j + 1] * LUMA_G + rgb[j + 2] * LUMA_B) / 255.0
    return out


# ---- 平滑 / smoothing -------------------------------------------------------
# 用盒式模糊（滑动窗口）近似高斯：三遍盒式模糊已经足够接近，而它每遍是
# O(像素数)，不随半径增长。蒙版本来就是低频的，不需要真高斯。

def box_blur(vals, w, h, radius=2, passes=3):
    """二维盒式模糊（先横后竖，边界夹取）。radius 以像素计。"""
    if radius <= 0 or w <= 0 or h <= 0:
        return list(vals)
    cur = list(vals)
    r = int(radius)
    for _ in range(passes):
        cur = _blur_axis(cur, w, h, r, horizontal=True)
        cur = _blur_axis(cur, w, h, r, horizontal=False)
    return cur


def _blur_axis(vals, w, h, r, horizontal):
    out = [0.0] * (w * h)
    span = 2 * r + 1
    if horizontal:
        for y in range(h):
            base = y * w
            acc = 0.0
            for k in range(-r, r + 1):
                acc += vals[base + (0 if k < 0 else (w - 1 if k > w - 1 else k))]
            for x in range(w):
                out[base + x] = acc / span
                i_out = x - r
                i_in = x + r + 1
                acc -= vals[base + (0 if i_out < 0 else i_out)]
                acc += vals[base + (w - 1 if i_in > w - 1 else i_in)]
    else:
        for x in range(w):
            acc = 0.0
            for k in range(-r, r + 1):
                acc += vals[(0 if k < 0 else (h - 1 if k > h - 1 else k)) * w + x]
            for y in range(h):
                out[y * w + x] = acc / span
                i_out = y - r
                i_in = y + r + 1
                acc -= vals[(0 if i_out < 0 else i_out) * w + x]
                acc += vals[(h - 1 if i_in > h - 1 else i_in) * w + x]
    return out


def diff(ref_luma, base_luma):
    """逐像素参考减原图。正数=参考更亮（该提亮），负数=该压暗。"""
    return [r - b for r, b in zip(ref_luma, base_luma)]


# ---- 双曲线：差值 → 两张蒙版 ------------------------------------------------

def _curve_slope(x, amount):
    """曲线 x + amount·4x(1−x) 在中灰附近的斜率。

    这条曲线两端不动、中间最鼓，所以同样的「提亮量」在暗部与亮部需要的
    蒙版浓度完全不同——蒙版必须按像素自己的亮度算，不能全图一个系数。
    """
    return max(0.06, amount * 4.0 * x * (1.0 - x))


def dodge_burn_masks(base_luma, delta, amount=0.12, strength=0.7, noise=0.004):
    """差值 → (提亮蒙版, 压暗蒙版)，都是 0…255 的 bytearray。

    strength 是「预修多少」：1.0 表示一次就把差值补平，0.7 表示先补七成，
    剩下的留给用户拿画笔收尾——插件默认 0.7，留一点手感。
    noise 是死区：小于它当作噪声，不涂。
    """
    n = len(base_luma)
    dodge = bytearray(n)
    burn = bytearray(n)
    for i in range(n):
        d = delta[i]
        if d > noise or d < -noise:
            a = abs(d) * strength / _curve_slope(base_luma[i], amount)
            v = int(round(clamp(a) * 255.0))
            if d > 0:
                dodge[i] = v
            else:
                burn[i] = v
    return dodge, burn


# ---- 中性灰：差值 → 灰层 ----------------------------------------------------
# 柔光公式（W3C，也是 GIMP 的 softlight）：
#   g ≤ 0.5:  out = x + (2g−1)·x·(1−x)
#   g > 0.5:  out = x + (2g−1)·(D(x) − x)
#   D(x) = ((16x−12)x+4)x  (x ≤ 0.25)，否则 sqrt(x)
# 两段都能解析反解出 g，不用迭代——迭代在 50 万像素上要好几秒。

def _d(x):
    if x <= 0.25:
        return ((16.0 * x - 12.0) * x + 4.0) * x
    return math.sqrt(x)


def grey_for_delta(base_luma, delta, strength=0.7):
    """差值 → 灰层 8 位值（128 = 不动）。strength 同上，只补一部分。"""
    n = len(base_luma)
    out = bytearray(n)
    for i in range(n):
        x = clamp(base_luma[i])
        d = delta[i] * strength
        g = 0.5
        if d > 0:
            denom = 2.0 * (_d(x) - x)
            if denom > 1e-4:
                g = 0.5 + d / denom
        elif d < 0:
            denom = 2.0 * x * (1.0 - x)
            if denom > 1e-4:
                g = 0.5 + d / denom
        out[i] = int(round(clamp(g) * 255.0))
    return out


def soft_light(x, g):
    """柔光合成，供回归验证 grey_for_delta 是否反解正确。"""
    if g <= 0.5:
        return x + (2.0 * g - 1.0) * x * (1.0 - x)
    return x + (2.0 * g - 1.0) * (_d(x) - x)


# ---- 组合 / compose ---------------------------------------------------------

def blend_rgba(base, ref, alpha, n=None):
    """按逐像素 alpha（0…1）把参考图混进原图，返回 RGBA 字节。

    选区就是这么生效的：选区外 alpha=0，参考图留在原地，预修只落在选区内。
    单纯「只算选区内的 delta」不够——低频层是整层的像素，必须整层混。
    """
    if n is None:
        n = len(base) // 4
    out = bytearray(base)
    for i in range(n):
        a = alpha[i] if alpha is not None else 1.0
        if a <= 0.0:
            continue
        j = i * 4
        if a >= 1.0:
            out[j:j + 3] = ref[j:j + 3]
            continue
        ia = 1.0 - a
        out[j] = int(round(base[j] * ia + ref[j] * a))
        out[j + 1] = int(round(base[j + 1] * ia + ref[j + 1] * a))
        out[j + 2] = int(round(base[j + 2] * ia + ref[j + 2] * a))
    return bytes(out)


def alpha_from_gray(gray):
    """8 位灰度（选区）→ 0…1 浮点。"""
    return [v / 255.0 for v in gray]


def stats(delta):
    """调试/自检用：差值的最大值与绝对值均值。"""
    if not delta:
        return 0.0, 0.0
    return max(delta), sum(abs(d) for d in delta) / len(delta)
