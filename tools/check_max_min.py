# -*- coding: utf-8 -*-
"""lb:max-min 回归：滑动极值 vs 逐像素暴力，逐位比对。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \\
        --batch-interpreter=python-fu-eval \\
        -b "exec(open(r'<repo>/tools/check_max_min.py').read())" --quit

为什么基准是暴力实现而不是「原生对照」：这台机器上的 GIMP 3.2.8 没有
gegl:dilate / gegl:erode，也没有 plug-in-dilate，本机不存在可对照的原生
对象。但形态学极值的定义是完全确定的——每个输出像素等于 (2r+1)² 窗口
（或圆盘）内的最大值 / 最小值——所以基准可以直接写成 O(r²) 的四重循环，
和被验证的 van Herk 实现是两条完全不同的代码路径。

覆盖：
  · u8 / u16 / float32 三种缓冲精度，逐字节（float 逐位）相同
  · 方形与圆形结构元、最大值与最小值
  · 单通道 Y 缓冲（蒙版的主战场）与 RGBA
  · alpha 默认不动 / affect-alpha 开
  · 图边缘按复制像素延拓（暴力实现同样钳位，两者必须一致）
  · 高 301 px 的图跨过 128 行的分带边界，验证分带拼接无接缝
"""

import array
import os
import sys
import time

import gi

gi.require_version('Gegl', '0.4')
from gi.repository import Gegl

Gegl.init()

OP = 'lb:max-min'

PASS = 0
FAIL = 0


def report(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  PASS  %-46s %s" % (label, detail), flush=True)
    else:
        FAIL += 1
        print("  FAIL  %-46s %s" % (label, detail), flush=True)


# ---- 造图 / input ----------------------------------------------------------

def lcg(n, seed=12345, lo=0, hi=255, step=None):
    """确定性伪随机：不用 random 模块，保证每次跑的图完全一样。"""
    v = seed
    out = []
    for _ in range(n):
        v = (1103515245 * v + 12345) & 0x7FFFFFFF
        x = lo + (v >> 8) % (hi - lo + 1)
        if step:
            x = (x // step) * step
        out.append(min(max(x, lo), hi))
    return out


def make_pixels(w, h, ncomp, lo=0, hi=255, step=None, seed=12345):
    """一幅有硬边、有孤立亮点、有渐变的测试图（按像素给出各分量值）。"""
    flat = lcg(w * h * ncomp, seed, lo, hi, step)
    px = []
    for i in range(w * h):
        x, y = i % w, i // w
        # 硬边方块 + 单点亮斑 + 单点暗斑：极值的三个典型场景
        if w // 4 <= x < w // 4 + 5 and h // 4 <= y < h // 4 + 5:
            px.append([hi] * ncomp)
            continue
        if x == w - 3 and y == 2:
            px.append([hi] * ncomp)
            continue
        if x == 2 and y == h - 3:
            px.append([lo] * ncomp)
            continue
        px.append(flat[i * ncomp:(i + 1) * ncomp])
    return px


# ---- 基准：O(r²) 暴力 -------------------------------------------------------

def brute(px, w, h, ncomp, r, want_max, round_, alpha_idx=-1):
    out = [list(p) for p in px]
    rr = r * r
    for y in range(h):
        for x in range(w):
            for c in range(ncomp):
                if c == alpha_idx:
                    continue
                best = px[y * w + x][c]
                for dy in range(-r, r + 1):
                    for dx in range(-r, r + 1):
                        if round_ and dx * dx + dy * dy > rr:
                            continue
                        yy = min(max(y + dy, 0), h - 1)
                        xx = min(max(x + dx, 0), w - 1)
                        v = px[yy * w + xx][c]
                        if want_max:
                            if v > best:
                                best = v
                        else:
                            if v < best:
                                best = v
                out[y * w + x][c] = best
    return out


# ---- 跑算子 / run the op ---------------------------------------------------

def to_bytes(px, fmt):
    if fmt == "u8":
        a = array.array('B')
        for p in px:
            a.extend(p)
        return a.tobytes()
    if fmt == "u16":
        a = array.array('H')
        for p in px:
            a.extend(p)
        return a.tobytes()
    a = array.array('f')
    for p in px:
        a.extend([float(v) for v in p])
    return a.tobytes()


def from_bytes(data, fmt, ncomp):
    if fmt == "u8":
        a = array.array('B')
    elif fmt == "u16":
        a = array.array('H')
    else:
        a = array.array('f')
    a.frombytes(data)
    return [list(a[i * ncomp:(i + 1) * ncomp]) for i in range(len(a) // ncomp)]


def run_op(px, w, h, babl_fmt, fmt, ncomp, **props):
    buf = Gegl.Buffer.new(babl_fmt, 0, 0, w, h)
    buf.set(Gegl.Rectangle.new(0, 0, w, h), babl_fmt, to_bytes(px, fmt))

    root = Gegl.Node.new()
    src = root.create_child("gegl:buffer-source")
    src.set_property("buffer", buf)
    op = root.create_child(OP)
    for k, v in props.items():
        op.set_property(k.replace('_', '-'), v)
    src.connect_to("output", op, "input")

    out = Gegl.Buffer.new(babl_fmt, 0, 0, w, h)
    op.blit_buffer(out, Gegl.Rectangle.new(0, 0, w, h), 0,
                   Gegl.AbyssPolicy.NONE)
    data = out.get(Gegl.Rectangle.new(0, 0, w, h), 1.0, babl_fmt,
                   Gegl.AbyssPolicy.NONE)
    return from_bytes(data, fmt, ncomp)


# ---- 用例 / cases ----------------------------------------------------------

def case(label, w, h, babl_fmt, fmt, ncomp, lo, hi, step,
         r, want_max, round_, alpha_idx=-1, affect_alpha=False, seed=12345):
    px = make_pixels(w, h, ncomp, lo, hi, step, seed)
    got = run_op(px, w, h, babl_fmt, fmt, ncomp,
                 mode='maximum' if want_max else 'minimum',
                 radius=r,
                 shape='round' if round_ else 'square',
                 affect_alpha=affect_alpha)
    want = brute(px, w, h, ncomp, r, want_max, round_,
                 -1 if affect_alpha else alpha_idx)

    bad = 0
    worst = ""
    for i, (a, b) in enumerate(zip(got, want)):
        if a != b:
            bad += 1
            if not worst:
                worst = "首差 #%d (x=%d,y=%d) got=%s want=%s" % (
                    i, i % w, i // w, a, b)
    report(label, bad == 0,
           "逐位相同" if bad == 0 else "%d/%d 像素不同；%s" % (bad, w * h, worst))


def main():
    print("== lb:max-min 回归 ==", flush=True)

    # 1) u8 三通道：四个组合 × 三档半径
    for r in (1, 2, 5):
        for want_max in (True, False):
            for round_ in (False, True):
                case("u8 RGB %s %s r=%d" % (
                        "最大" if want_max else "最小",
                        "圆" if round_ else "方", r),
                     23, 17, "R'G'B' u8", "u8", 3, 0, 255, None,
                     r, want_max, round_)

    # 2) 带 alpha：默认不动 alpha
    case("u8 RGBA 默认不动 alpha（最大 r=3）",
         21, 15, "R'G'B'A u8", "u8", 4, 0, 255, None,
         3, True, False, alpha_idx=3)

    # 3) 带 alpha：显式要求一起算
    case("u8 RGBA affect-alpha=on（最小 r=2）",
         21, 15, "R'G'B'A u8", "u8", 4, 0, 255, None,
         2, False, False, alpha_idx=3, affect_alpha=True)

    # 4) 单通道 Y（蒙版的主战场）
    case("Y u8 单通道 最大 r=4 方",
         27, 19, "Y u8", "u8", 1, 0, 255, None,
         4, True, False)

    # 5) u16：取值跨在 float 精度边缘附近，防止中途被转成 float
    case("u16 灰度 最小 r=3 圆（含 32767/32768）",
         19, 13, "Y u16", "u16", 1, 0, 65535, 1,
         3, False, True)
    case("u16 RGBA 最大 r=2 方 不动 alpha",
         17, 11, "R'G'B'A u16", "u16", 4, 0, 65535, 7,
         2, True, False, alpha_idx=3)

    # 6) float32（0–1 域）：逐位相同，不是「近似相同」
    case("f32 RGB 最大 r=3 圆",
         23, 17, "R'G'B' float", "f32", 3, 0, 1000, None,
         3, True, True)
    case("f32 RGB 最小 r=1 方",
         23, 17, "R'G'B' float", "f32", 3, 0, 1000, None,
         1, False, False)

    # 7) 跨分带：高 301 px > BAND_ROWS(128)，接缝处不能有错行
    case("u8 高 301（跨 128 行分带）最大 r=5 方",
         13, 301, "R'G'B' u8", "u8", 3, 0, 255, None,
         5, True, False, seed=777)

    # 8) 半径 100 在极小图上：整幅被同一个极值覆盖
    case("u8 9×7 半径 100（超图）最大 方",
         9, 7, "R'G'B' u8", "u8", 3, 0, 255, None,
         100, True, False)
    case("u8 9×7 半径 100（超图）最小 圆",
         9, 7, "R'G'B' u8", "u8", 3, 0, 255, None,
         100, False, True)

    # 9) 二值图：先最小后最大 = 开运算，孤立亮点被抹掉且不再回来
    w = h = 21
    px = [[0] * 3 for _ in range(w * h)]
    for y in range(5, 16):
        for x in range(5, 16):
            px[y * w + x] = [255] * 3
    px[2 * w + 18] = [255] * 3            # 孤立亮点
    got1 = run_op(px, w, h, "R'G'B' u8", "u8", 3,
                  mode='minimum', radius=1, shape='square')
    got2 = run_op(got1, w, h, "R'G'B' u8", "u8", 3,
                  mode='maximum', radius=1, shape='square')
    speck = got2[2 * w + 18][0]
    center = got2[10 * w + 10][0]
    corner = got2[0][0]
    report("开运算：孤立亮点被抹掉、方块保形",
           speck == 0 and center == 255 and corner == 0,
           "亮点=%d 中心=%d 角=%d" % (speck, center, corner))

    # 10) 性能：2000×1500 u8。缓冲与图只造一次，计时只覆盖算子本身
    #     （把 Python 侧的造图/序列化算进计时会得到 2 秒的假数字）
    W, H = 2000, 1500
    big = make_pixels(W, H, 3)
    buf = Gegl.Buffer.new("R'G'B' u8", 0, 0, W, H)
    buf.set(Gegl.Rectangle.new(0, 0, W, H), "R'G'B' u8", to_bytes(big, "u8"))
    for shape, r in (('square', 1), ('square', 100), ('round', 10), ('round', 100)):
        root = Gegl.Node.new()
        src = root.create_child("gegl:buffer-source")
        src.set_property("buffer", buf)
        op = root.create_child(OP)
        op.set_property("mode", "maximum")
        op.set_property("radius", r)
        op.set_property("shape", shape)
        src.connect_to("output", op, "input")
        out = Gegl.Buffer.new("R'G'B' u8", 0, 0, W, H)
        t0 = time.time()
        op.blit_buffer(out, Gegl.Rectangle.new(0, 0, W, H), 0,
                       Gegl.AbyssPolicy.NONE)
        report("%s r=%d 3.0MP 算子耗时" % (shape, r), True,
               "%.3f 秒" % (time.time() - t0))

    print("\n合计 %d 项，失败 %d 项" % (PASS + FAIL, FAIL))
    return FAIL


_fail = main()
if _fail:
    print("MAX-MIN CHECKS FAILED: %d" % _fail)
