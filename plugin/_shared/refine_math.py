# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 选择并遮住（精修蒙版的数学层）/ refine maths
 ---------------------------------------------------------------------------
 purpose   纯 Python，不 import gi。蒙版在这里就是一串 0..255（255=主体），
           所有函数都是 `bytes/bytearray in → bytearray out`，不碰 GIMP。
           这样同一套代码既能算对话框里的缩略预览，也能算最终应用的结果——
           预览和应用**不会**各走一套实现，不会出现「预览好看、确定后不一样」。

           顺序（和 PS 的滑杆顺序一致）：
             边缘吸附 → 平滑 → 羽化 → 对比度 → 移动边缘
           羽化放在对比度之前，是因为对比度要能把羽化后的软边重新硬起来；
           反过来做，羽化永远压在上面，那根滑杆就没意义了。

 caveat     GIMP 3 的 Python 里**没有 numpy**（3.2.8 实测），所以模糊只能用
           bytes + accumulate 手写。1600×1067 上一次盒式模糊约 0.3 s，
           三个盒式近似高斯约 1.8 s——这就是「工作尺寸默认 1600」的来源。
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math
from itertools import accumulate

# 工作尺寸默认值：再大就要等好几秒，再小发丝就糊了。
DEFAULT_WORK_LONG_EDGE = 1600
# 边缘吸附只在「半透明带」里做。band 越窄越快，也越不容易把主体内部改坏。
BAND_LO, BAND_HI = 20, 236


# ---- 小工具 / helpers ------------------------------------------------------

def clamp_byte(v):
    if v < 0:
        return 0
    if v > 255:
        return 255
    return int(v)


def _accumulate(values):
    """前缀和。itertools.accumulate 带 initial= 需要 3.8+；GIMP 3 是 3.12。"""
    return list(accumulate(values, initial=0))


def identity_lut():
    return bytes(bytearray(range(256)))


def apply_lut(data, table):
    """整串查表。bytes.translate 是 C 实现，24 MP 的蒙版也就几十毫秒。"""
    return bytes(data).translate(table)


# ---- sRGB / 线性 -----------------------------------------------------------
# GIMP 的**通道**（gimp-selection-save 出来的那个）用 "Y u8" 读出来是**线性**
# 亮度，而选区值（Selection.value）和图层 alpha 是**编码后**的。实测：
# 通道里写 128（线性 0.502）→ 选区读回来 188（sRGB 编码后 0.74）。
# 不做这次转换，蒙版的中间调会整体下压，50% 等值线跟着漂。

def linear_to_srgb_lut():
    table = bytearray(256)
    for v in range(256):
        c = v / 255.0
        s = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055
        table[v] = clamp_byte(round(s * 255.0))
    return bytes(table)


def srgb_to_linear_lut():
    table = bytearray(256)
    for v in range(256):
        c = v / 255.0
        l = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        table[v] = clamp_byte(round(l * 255.0))
    return bytes(table)


# ---- 模糊 / blur -----------------------------------------------------------

def _box_h(src, w, h, r):
    """横向盒式模糊。**边缘按复制处理**（不是补零）：补零会把画布边框压暗，
    一张纯色图模糊完四边会发黑——PS 的羽化从来不是这个行为。"""
    out = bytearray(w * h)
    inv = 1.0 / (2 * r + 1)
    span = 2 * r + 1
    for y in range(h):
        base = y * w
        row = bytes(src[base:base + w])
        cs = _accumulate(row[:1] * r + row + row[-1:] * r)
        if w > 2 * r:
            out[base + r:base + w - r] = bytes(
                clamp_byte(int((cs[i + span] - cs[i]) * inv + 0.5))
                for i in range(r, w - r))
            edge_xs = list(range(r)) + list(range(w - r, w))
        else:
            edge_xs = list(range(w))
        for x in edge_xs:
            out[base + x] = clamp_byte(int((cs[x + span] - cs[x]) * inv + 0.5))
    return out


def _box_v(src, w, h, r):
    out = bytearray(w * h)
    inv = 1.0 / (2 * r + 1)
    span = 2 * r + 1
    for x in range(w):
        col = bytes(src[x::w])
        cs = _accumulate(col[:1] * r + col + col[-1:] * r)
        vals = bytearray(h)
        if h > 2 * r:
            vals[r:h - r] = bytes(
                clamp_byte(int((cs[i + span] - cs[i]) * inv + 0.5))
                for i in range(r, h - r))
            edge_ys = list(range(r)) + list(range(h - r, h))
        else:
            edge_ys = list(range(h))
        for y in edge_ys:
            vals[y] = clamp_byte(int((cs[y + span] - cs[y]) * inv + 0.5))
        out[x::w] = vals
    return out


def box_blur(src, w, h, radius, passes=1):
    r = int(round(radius))
    if r < 1 or passes < 1:
        return bytes(src)
    cur = bytes(src)
    for _ in range(passes):
        cur = _box_v(_box_h(cur, w, h, r), w, h, r)
    return cur


def _gauss_radii(sigma, boxes=3):
    """用 n 次盒式模糊逼近高斯（Kutskir 的做法）：给定 sigma 求每次的半径。"""
    if sigma <= 0:
        return []
    ideal = math.sqrt((12.0 * sigma * sigma / boxes) + 1.0)
    wl = int(math.floor(ideal))
    if wl % 2 == 0:
        wl -= 1
    wl = max(1, wl)
    wu = wl + 2
    m_ideal = (12.0 * sigma * sigma - boxes * wl * wl - 4.0 * boxes * wl
               - 3.0 * boxes) / (-4.0 * wl - 4.0)
    m = int(round(m_ideal))
    sizes = [wl] * m + [wu] * (boxes - m)
    return [(s - 1) // 2 for s in sizes]


def gaussian_blur(src, w, h, sigma):
    cur = bytes(src)
    for r in _gauss_radii(sigma):
        if r >= 1:
            cur = _box_v(_box_h(cur, w, h, r), w, h, r)
    return cur


# ---- 曲线：对比度 / 移动边缘 ----------------------------------------------

def curve_lut(contrast=0.0, shift=0.0):
    """一条表搞定「对比度」和「移动边缘」。

    contrast 0..100 → 斜率 1..5，绕 0.5 转，两端夹死（硬边）。
    shift   -100..100 → 整体加/减最多 0.4 的 alpha：正值外扩、负值内缩，
            和 PS 的 Shift Edge 同向。
    """
    k = 1.0 + max(0.0, float(contrast)) / 100.0 * 4.0
    # 位移量按「整个 alpha 量程」算：100% 就能把 50% 线推过整条软边
    # （PS 的 Shift Edge 也是按羽化宽度给百分比）。0.4 那版只挪了 40%，
    # 4 px 羽化的边在 100% 时才动 1.6 px，滑杆像坏的一样。
    off = max(-1.0, min(1.0, float(shift) / 100.0))
    table = bytearray(256)
    for v in range(256):
        a = v / 255.0
        a = 0.5 + (a - 0.5) * k + off
        table[v] = clamp_byte(round(a * 255.0))
    return bytes(table)


# ---- 边缘吸附 / snap to image edges ---------------------------------------

def luma(rgba, w, h):
    """RGBA → 灰度（就地为边缘吸附用，够用即可，不做色彩管理）。"""
    out = bytearray(w * h)
    for i in range(w * h):
        j = i * 4
        out[i] = (rgba[j] * 77 + rgba[j + 1] * 150 + rgba[j + 2] * 29) >> 8
    return out


def edge_strength(gray, w, h):
    """|∇| 的近似（中心差分），0..255。只用来比大小，不做阈值语义。"""
    out = bytearray(w * h)
    if w < 3 or h < 3:
        return out
    for y in range(1, h - 1):
        base = y * w
        cur = gray[base:base + w]
        up = gray[base - w:base]
        dn = gray[base + w:base + 2 * w]
        row = bytearray(w)
        row[1:w - 1] = bytes(
            min(255, abs(dn[i] - up[i]) + abs(cur[i - 1] - cur[i + 1]))
            for i in range(1, w - 1))
        out[base:base + w] = row
    return out


def _sample(src, w, h, x, y):
    """双线性采样，越界夹紧。"""
    x = 0.0 if x < 0 else (w - 1.001 if x > w - 1 else x)
    y = 0.0 if y < 0 else (h - 1.001 if y > h - 1 else y)
    x0 = int(x)
    y0 = int(y)
    fx = x - x0
    fy = y - y0
    x1 = min(x0 + 1, w - 1)
    y1 = min(y0 + 1, h - 1)
    a = src[y0 * w + x0] * (1 - fx) + src[y0 * w + x1] * fx
    b = src[y1 * w + x0] * (1 - fx) + src[y1 * w + x1] * fx
    return int(a * (1 - fy) + b * fy + 0.5)


def snap_to_edges(mask, strength, w, h, radius=0, smart=True,
                  ratio=1.35, band=(BAND_LO, BAND_HI)):
    """把蒙版的 50% 等值线往画面里真实的边缘上推。

    和 PS 的「边缘检测半径」不是同一个算法：PS 是找边缘后重算一张蒙版，
    这里是**沿法线平移整段剖面**——每个半透明像素找 ±radius 内最强的图像
    边缘，明显强于当前位置就把蒙版往那儿挪（双线性重采样）。效果一样是把
    「糊出去两像素」的边界收回到真实的边上，做法更土、但每一步可测。

    两个必须这样的细节（都是踩出来的）：
      1. 位移要**沿法线传播到 ±radius**。只改半透明带是不够的：剖面移过去
         之后要落在原来「实心 255」的地方，那段得有人接住，否则边界会变成
         一道硬跳变（实测：软边在 17..22、真边缘在 26，只改带内的话边界会
         塌成 22 处的一刀切）。
      2. smart=True 只在找到**明显更强**（默认 1.35 倍）的边缘时才动；关掉就
         只要±radius 内有更大的就动，边缘会被拉得更凶。
    """
    radius = int(round(radius))
    if radius < 1 or w < 3 or h < 3:
        return bytes(mask)
    radius = min(radius, 12)
    lo, hi = band
    need = 1.0 if smart else 1.0 / max(ratio, 1.01)

    dx = [0.0] * (w * h)
    dy = [0.0] * (w * h)
    moved = bytearray(w * h)

    for y in range(1, h - 1):
        base = y * w
        for x in range(1, w - 1):
            i = base + x
            a = mask[i]
            if a <= lo or a >= hi:
                continue
            gx = int(mask[i + 1]) - int(mask[i - 1])
            gy = int(mask[i + w]) - int(mask[i - w])
            norm = math.hypot(gx, gy)
            if norm < 6.0:
                continue
            nx, ny = gx / norm, gy / norm
            e0 = strength[i]
            best_t, best_e = 0, e0
            for t in range(1, radius + 1):
                for s in (t, -t):
                    sx = int(round(x + s * nx))
                    sy = int(round(y + s * ny))
                    if sx < 1 or sy < 1 or sx >= w - 1 or sy >= h - 1:
                        continue
                    e = strength[sy * w + sx]
                    if e > best_e:
                        best_e, best_t = e, s
            if not best_t or best_e <= need * max(e0, 1):
                continue
            vx, vy = best_t * nx, best_t * ny
            for k in range(-radius, radius + 1):
                px = int(round(x + k * nx))
                py = int(round(y + k * ny))
                if px < 1 or py < 1 or px >= w - 1 or py >= h - 1:
                    continue
                j = py * w + px
                if not moved[j]:
                    moved[j] = 1
                    dx[j], dy[j] = vx, vy

    out = bytearray(mask)
    for i in range(w * h):
        if moved[i]:
            x = i % w
            y = i // w
            out[i] = _sample(mask, w, h, x - dx[i], y - dy[i])
    return out


# ---- 去色边 / decontaminate ----------------------------------------------

def decontaminate(rgba, mask, bg, w, h, strength=1.0,
                  band=(4, 250)):
    """按 alpha 反解前景色，把边缘上挂着的背景色抠掉。

    模型就是合成公式 C = a·F + (1-a)·B：已知 C（边缘像素）、a（蒙版）、
    B（估出来的背景色），反解 F = (C - (1-a)·B) / a。a 很小时反解会炸，
    所以 band 下限之外不动；strength 只是把结果往 F 拉多少。

    bg 是 w×h×3 的背景色估计（调用方给：模糊过的「纯背景」图层）。
    返回 (新 rgba, 改动的像素数)。
    """
    s = max(0.0, min(1.0, float(strength)))
    if s <= 0.0:
        return bytes(rgba), 0
    lo, hi = band
    out = bytearray(rgba)
    changed = 0
    for i in range(w * h):
        a = mask[i]
        if a <= lo or a >= hi:
            continue
        alpha = a / 255.0
        j = i * 4
        k = i * 3
        inv = 1.0 / alpha
        for c in range(3):
            fg = (rgba[j + c] - (1.0 - alpha) * bg[k + c]) * inv
            fg = 0.0 if fg < 0.0 else (255.0 if fg > 255.0 else fg)
            cur = out[j + c]
            out[j + c] = clamp_byte(round(cur + (fg - cur) * s))
        changed += 1
    return bytes(out), changed


# ---- 主流程 / pipeline -----------------------------------------------------

def refine_mask(mask, w, h, gray=None, radius=0, smart=True, smooth=0.0,
                feather=0.0, contrast=0.0, shift=0.0):
    """蒙版精修主流程。gray 是 w×h 的灰度图，只有 radius>0 时才需要。"""
    cur = bytes(mask)
    if radius > 0 and gray is not None:
        st = edge_strength(gray, w, h)
        cur = snap_to_edges(cur, st, w, h, radius=radius, smart=smart)
    if smooth > 0:
        cur = box_blur(cur, w, h, smooth, passes=1)
    if feather > 0:
        cur = gaussian_blur(cur, w, h, feather / 2.0)
    if contrast or shift:
        cur = apply_lut(cur, curve_lut(contrast, shift))
    return cur


def mask_stats(mask, w=0, h=0):
    """覆盖率统计：给提示文案和回归用。"""
    n = len(mask)
    soft = sum(1 for v in mask if 0 < v < 255)
    full = sum(1 for v in mask if v >= 250)
    empty = sum(1 for v in mask if v <= 5)
    return {"pixels": n, "solid": full, "empty": empty, "soft": soft,
            "solid_ratio": (full / n) if n else 0.0}


# ---- 预览合成 / preview composite -----------------------------------------

def compose_preview(rgba, mask, w, h, mode="checker", cell=8):
    """把精修后的蒙版合成成一张能直接塞进 Gtk.Image 的 RGBA。

    mode  checker/white/black/red（red = PS 那种半透明红蒙版）。
    """
    out = bytearray(w * h * 4)
    for y in range(h):
        base = y * w
        for x in range(w):
            i = base + x
            j = i * 4
            a = mask[i]
            if mode == "red":
                r, g, b = rgba[j], rgba[j + 1], rgba[j + 2]
                t = a / 255.0 * 0.5
                out[j] = clamp_byte(round(r + (255 - r) * t))
                out[j + 1] = clamp_byte(round(g * (1 - t)))
                out[j + 2] = clamp_byte(round(b * (1 - t)))
                out[j + 3] = 255
                continue
            if mode == "white":
                cr = cg = cb = 255
            elif mode == "black":
                cr = cg = cb = 0
            else:                                   # 棋盘格
                light = ((x // cell) + (y // cell)) % 2 == 0
                cr = cg = cb = 230 if light else 170
            af = a / 255.0
            out[j] = clamp_byte(round(rgba[j] * af + cr * (1 - af)))
            out[j + 1] = clamp_byte(round(rgba[j + 1] * af + cg * (1 - af)))
            out[j + 2] = clamp_byte(round(rgba[j + 2] * af + cb * (1 - af)))
            out[j + 3] = 255
    return bytes(out)
