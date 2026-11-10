# -*- coding: utf-8 -*-
"""psblend · PS 应用图像/计算的像素内核（供 ps-blend.py 调用）

优先加载同目录的 psblend_core.dll/.so（ctypes，与 common/blend.h 同一套公式，
速度约为纯 Python 的 50 倍）；没有编译产物时退化为纯 Python（结果一致，慢）。

数学口径与 GEGL 的 lb:apply-image / lb:calculations 完全一致：
  - 全部在 8bit sRGB 伽马域计算（输入用 "R'G'B'A float" 读出）
  - 深色/浅色按整像素亮度取整方
  - 结果 = 目标 + (混合结果 - 目标) × 遮罩 × 不透明度
"""

import array
import ctypes
import math
import os

# ---- 混合模式 / blend modes -----------------------------------------------
# 顺序与 Photoshop 对话框一致（Darker Color 在 Linear Burn 之后、
# Lighter Color 在 Linear Dodge 之后），也决定 C 内核的映射表
BLENDS = [
    ("normal", "Normal"), ("darken", "Darken"), ("multiply", "Multiply"),
    ("color-burn", "Color Burn"), ("linear-burn", "Linear Burn"),
    ("darker-color", "Darker Color"), ("lighten", "Lighten"),
    ("screen", "Screen"), ("color-dodge", "Color Dodge"),
    ("linear-dodge", "Linear Dodge (Add)"), ("lighter-color", "Lighter Color"),
    ("overlay", "Overlay"), ("soft-light", "Soft Light"),
    ("hard-light", "Hard Light"), ("vivid-light", "Vivid Light"),
    ("linear-light", "Linear Light"), ("pin-light", "Pin Light"),
    ("hard-mix", "Hard Mix"), ("difference", "Difference"),
    ("exclusion", "Exclusion"), ("subtract", "Subtract"),
    ("divide", "Divide"), ("hue", "Hue"), ("saturation", "Saturation"),
    ("color", "Color"), ("luminosity", "Luminosity"),
]
BLEND_INDEX = {nick: i for i, (nick, _label) in enumerate(BLENDS)}
HUE_START = BLEND_INDEX["hue"]
DARKER_COLOR = BLEND_INDEX["darker-color"]
LIGHTER_COLOR = BLEND_INDEX["lighter-color"]

# ---- 通道 / channels -------------------------------------------------------
# gray = PS 的 Gray（亮度），mask = 图层蒙版（在读图阶段已被解析成灰度数据）
CHANNELS = [("gray", "Gray"), ("red", "Red"), ("green", "Green"),
            ("blue", "Blue"), ("alpha", "Alpha"), ("mask", "Layer mask")]
CH_GRAY, CH_RED, CH_GREEN, CH_BLUE, CH_ALPHA, CH_MASK = range(6)

# 结果模式 / result modes
APPLY_RESULTS = [("composite", "Composite"), ("grey-layer", "New grey layer")]
CALC_RESULTS = [("selection", "Selection"), ("new-channel", "New alpha channel"),
                ("grey-layer", "New grey layer"), ("layer-alpha", "Layer alpha")]


def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _luma(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ch_value(ch, r, g, b, a):
    if ch == CH_RED:
        return r
    if ch == CH_GREEN:
        return g
    if ch == CH_BLUE:
        return b
    if ch == CH_ALPHA:
        return a
    return _luma(r, g, b)


# ---- 纯 Python 混合公式（与 blend.h 一致） ---------------------------------

def _sep(mode, a, b):
    if mode == BLEND_INDEX["normal"]:
        return b
    if mode == BLEND_INDEX["darken"]:
        return min(a, b)
    if mode == BLEND_INDEX["multiply"]:
        return a * b
    if mode == BLEND_INDEX["color-burn"]:
        return 0.0 if b <= 0.0 else _clamp01(1.0 - (1.0 - a) / b)
    if mode == BLEND_INDEX["linear-burn"]:
        return _clamp01(a + b - 1.0)
    if mode == BLEND_INDEX["darker-color"]:
        return min(a, b)
    if mode == BLEND_INDEX["lighten"]:
        return max(a, b)
    if mode == BLEND_INDEX["screen"]:
        return 1.0 - (1.0 - a) * (1.0 - b)
    if mode == BLEND_INDEX["color-dodge"]:
        return 1.0 if b >= 1.0 else _clamp01(a / (1.0 - b))
    if mode == BLEND_INDEX["linear-dodge"]:
        return _clamp01(a + b)
    if mode == BLEND_INDEX["lighter-color"]:
        return max(a, b)
    if mode == BLEND_INDEX["overlay"]:
        return 2.0 * a * b if a <= 0.5 else 1.0 - 2.0 * (1.0 - a) * (1.0 - b)
    if mode == BLEND_INDEX["soft-light"]:
        if b <= 0.5:
            return a - (1.0 - 2.0 * b) * a * (1.0 - a)
        d = ((16.0 * a - 12.0) * a + 4.0) * a if a <= 0.25 else math.sqrt(a)
        return a + (2.0 * b - 1.0) * (d - a)
    if mode == BLEND_INDEX["hard-light"]:
        return 2.0 * a * b if b <= 0.5 else 1.0 - 2.0 * (1.0 - a) * (1.0 - b)
    if mode == BLEND_INDEX["vivid-light"]:
        if b <= 0.5:
            return 0.0 if 2.0 * b <= 0.0 else _clamp01(1.0 - (1.0 - a) / (2.0 * b))
        bb = 2.0 * b - 1.0
        return 1.0 if bb >= 1.0 else _clamp01(a / (1.0 - bb))
    if mode == BLEND_INDEX["linear-light"]:
        return _clamp01(a + 2.0 * b - 1.0)
    if mode == BLEND_INDEX["pin-light"]:
        return min(a, 2.0 * b) if b <= 0.5 else max(a, 2.0 * b - 1.0)
    if mode == BLEND_INDEX["hard-mix"]:
        return 1.0 if a + b >= 1.0 else 0.0
    if mode == BLEND_INDEX["difference"]:
        return abs(a - b)
    if mode == BLEND_INDEX["exclusion"]:
        return a + b - 2.0 * a * b
    if mode == BLEND_INDEX["subtract"]:
        return _clamp01(a - b)
    if mode == BLEND_INDEX["divide"]:
        return 1.0 if b <= 0.0 else _clamp01(a / b)
    return b


def _hsv_rgb(r, g, b):
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn
    s = 0.0 if mx <= 0.0 else d / mx
    if d <= 0.0:
        return 0.0, s, mx
    if mx == r:
        h = ((g - b) / d) % 6.0
    elif mx == g:
        h = (b - r) / d + 2.0
    else:
        h = (r - g) / d + 4.0
    return h * 60.0, s, mx


def _rgb_hsv(h, s, v):
    c = v * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = v - c
    if h < 60.0:
        rr, gg, bb = c, x, 0.0
    elif h < 120.0:
        rr, gg, bb = x, c, 0.0
    elif h < 180.0:
        rr, gg, bb = 0.0, c, x
    elif h < 240.0:
        rr, gg, bb = 0.0, x, c
    elif h < 300.0:
        rr, gg, bb = x, 0.0, c
    else:
        rr, gg, bb = c, 0.0, x
    return _clamp01(rr + m), _clamp01(gg + m), _clamp01(bb + m)


def _blend_pixel(mode, a1, a2, a3, b1, b2, b3):
    """整像素混合；单通道调用时三个分量传同一个值。"""
    if mode == DARKER_COLOR or mode == LIGHTER_COLOR:
        la = _luma(a1, a2, a3)
        lb_ = _luma(b1, b2, b3)
        take_b = lb_ < la if mode == DARKER_COLOR else lb_ > la
        return (b1, b2, b3) if take_b else (a1, a2, a3)
    if mode >= HUE_START:
        ha, sa, va = _hsv_rgb(a1, a2, a3)
        hb, sb, vb = _hsv_rgb(b1, b2, b3)
        if mode == BLEND_INDEX["hue"]:
            return _rgb_hsv(hb, sa, va)
        if mode == BLEND_INDEX["saturation"]:
            return _rgb_hsv(ha, sb, va)
        if mode == BLEND_INDEX["color"]:
            return _rgb_hsv(hb, sb, va)
        return _rgb_hsv(ha, sa, vb)
    return (_clamp01(_sep(mode, a1, b1)),
            _clamp01(_sep(mode, a2, b2)),
            _clamp01(_sep(mode, a3, b3)))


# ---- C 内核（可选加速） ----------------------------------------------------

_CORE = None
_CORE_TRIED = False


def _load_core():
    global _CORE, _CORE_TRIED
    if _CORE_TRIED:
        return _CORE
    _CORE_TRIED = True
    try:
        import ctypes
        here = os.path.dirname(os.path.abspath(__file__))
        path = None
        for name in ("psblend_core.dll", "psblend_core.so", "psblend_core.dylib"):
            cand = os.path.join(here, name)
            if os.path.exists(cand):
                path = cand
                break
        if path is None:
            return None
        lib = ctypes.CDLL(path)
        fp = ctypes.POINTER(ctypes.c_float)
        lib.psblend_apply.restype = None
        lib.psblend_apply.argtypes = [fp, fp, fp, fp, ctypes.c_long,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_float, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.psblend_calc.restype = None
        lib.psblend_calc.argtypes = [fp, fp, fp, fp, ctypes.c_long,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_float,
                                     ctypes.c_int, ctypes.c_int]
        _CORE = lib
    except Exception:
        _CORE = None
    return _CORE


def _ptr(arr):
    addr, _ = arr.buffer_info()
    return ctypes.cast(addr, ctypes.POINTER(ctypes.c_float))


# ---- 两个入口（与 C 内核同签名语义） ---------------------------------------

def apply_image(inb, auxb, maskb, n, blend, tch, sch, opacity,
                use_mask, inv_mask, keep_transp, grey_out):
    """应用图像：inb/auxb/maskb 为 array('f') RGBA，返回 array('f') RGBA。"""
    core = _load_core()
    if core is not None:
        out = array.array("f", bytes(n * 16))
        m = _ptr(maskb) if maskb is not None else None
        core.psblend_apply(_ptr(inb), _ptr(auxb), m, _ptr(out),
                           ctypes.c_long(n), blend, tch, sch,
                           ctypes.c_float(opacity), use_mask, inv_mask,
                           keep_transp, grey_out)
        return out

    # ---- 纯 Python 兜底 ----
    out = array.array("f", bytes(n * 16))
    for i in range(n):
        j = i * 4
        ir, ig, ib, ia = inb[j], inb[j + 1], inb[j + 2], inb[j + 3]
        sr, sg, sb, sa = auxb[j], auxb[j + 1], auxb[j + 2], auxb[j + 3]
        orr, org, ob, oa = ir, ig, ib, ia

        if keep_transp and ia <= 0.0:
            out[j], out[j + 1], out[j + 2], out[j + 3] = ir, ig, ib, ia
            continue

        if use_mask:
            k = opacity
            if maskb is not None:
                v = _ch_value(0, maskb[j], maskb[j + 1], maskb[j + 2], maskb[j + 3])
            else:
                v = _ch_value(0, sr, sg, sb, sa)
            k *= (1.0 - v) if inv_mask else v
            k = _clamp01(k)
        else:
            k = opacity

        if tch == 0:
            if blend >= HUE_START or blend in (DARKER_COLOR, LIGHTER_COLOR):
                # 色相类与深/浅色是整像素语义，直接用 aux 的 RGB
                br, bg, bb = _blend_pixel(blend, ir, ig, ib, sr, sg, sb)
            else:
                # 可分离模式：Gray 源取亮度作标量，压进每一个通道
                s = _luma(sr, sg, sb) if sch == CH_GRAY else \
                    _ch_value(sch, sr, sg, sb, sa)
                br = _clamp01(_sep(blend, ir, s))
                bg = _clamp01(_sep(blend, ig, s))
                bb = _clamp01(_sep(blend, ib, s))
            orr = ir + (br - ir) * k
            org = ig + (bg - ig) * k
            ob = ib + (bb - ib) * k
        else:
            tv = _ch_value(tch, ir, ig, ib, ia)
            sv = _luma(sr, sg, sb) if sch == CH_GRAY else \
                _ch_value(sch, sr, sg, sb, sa)
            nv = tv + (_clamp01(_sep(blend, tv, sv)) - tv) * k
            if tch == 1:
                orr = nv
            elif tch == 2:
                org = nv
            elif tch == 3:
                ob = nv
            else:
                oa = nv

        if grey_out:
            g = _luma(orr, org, ob)
            out[j], out[j + 1], out[j + 2], out[j + 3] = g, g, g, 1.0
        else:
            out[j], out[j + 1], out[j + 2], out[j + 3] = \
                _clamp01(orr), _clamp01(org), _clamp01(ob), _clamp01(oa)
    return out


def calculations(inb, auxb, maskb, n, ch1, inv1, ch2, inv2, blend, opacity,
                 use_mask, inv_mask):
    """计算：两路通道混合，返回灰度 array('f') RGBA（alpha=1）。"""
    core = _load_core()
    if core is not None:
        out = array.array("f", bytes(n * 16))
        m = _ptr(maskb) if maskb is not None else None
        core.psblend_calc(_ptr(inb), _ptr(auxb), m, _ptr(out), ctypes.c_long(n),
                          ch1, inv1, ch2, inv2, blend,
                          ctypes.c_float(opacity), use_mask, inv_mask)
        return out

    out = array.array("f", bytes(n * 16))
    for i in range(n):
        j = i * 4
        v1 = _ch_value(ch1, inb[j], inb[j + 1], inb[j + 2], inb[j + 3])
        v2 = _ch_value(ch2, auxb[j], auxb[j + 1], auxb[j + 2], auxb[j + 3])
        if inv1:
            v1 = 1.0 - v1
        if inv2:
            v2 = 1.0 - v2

        if use_mask:
            k = opacity
            if maskb is not None:
                v = _ch_value(0, maskb[j], maskb[j + 1], maskb[j + 2], maskb[j + 3])
            else:
                v = _ch_value(0, auxb[j], auxb[j + 1], auxb[j + 2], auxb[j + 3])
            k *= (1.0 - v) if inv_mask else v
            k = _clamp01(k)
        else:
            k = opacity

        if ch1 == 0 or ch2 == 0 or blend >= HUE_START \
                or blend in (DARKER_COLOR, LIGHTER_COLOR):
            # 涉及整像素语义时把两个标量塞进三通道统一处理
            g1 = g2 = v1
            r, g, b = _blend_pixel(blend, g1, g1, g1, v2, v2, v2)
            blended = (r + g + b) / 3.0
        else:
            blended = _clamp01(_sep(blend, v1, v2))
        grey = v1 + (blended - v1) * k
        out[j], out[j + 1], out[j + 2], out[j + 3] = grey, grey, grey, 1.0
    return out
