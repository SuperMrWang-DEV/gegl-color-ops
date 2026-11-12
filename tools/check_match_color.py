# -*- coding: utf-8 -*-
"""lb:match-color 端到端回归，在 GIMP 的 python-fu 里跑：

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \\
        --batch-interpreter=python-fu-eval \\
        -b "exec(open(r'<repo>/tools/check_match_color.py').read())" --quit

验证的不是 babl 的 RGB→Lab 转换（那是底层库的事），而是 C 算子的规则：
全局统计只计入不透明像素、均值/方差仿射映射、四个滑杆的语义、L/a/b 域
削顶、alpha 保留。做法：测试图以 R'G'B'A float 建 GeglBuffer，喂给算子，
把结果以 CIE Lab alpha float 读回来，与 Python 镜像模型逐像素比对。
"""

import math
import os
import sys

import gi

gi.require_version('Gegl', '0.4')
from gi.repository import Gegl

Gegl.init()

REL = os.path.join('tools', 'check_match_color.py')


def _find_root():
    here = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() \
        else os.getcwd()
    for cand in (here, os.path.dirname(here), os.getcwd()):
        if os.path.exists(os.path.join(cand, 'ops', 'match-color')):
            return cand
    raise RuntimeError('请在仓库根目录运行')


ROOT = _find_root()

FMT_RGB = "R'G'B'A float"
FMT_LAB = "CIE Lab alpha float"
TOL = 5e-3          # float32 + babl 抖动容差
LAB_TOL = 2e-2      # Lab 数值域较大（L 到 100）

PASS = 0
FAIL = 0


def report(label, got, want, tol):
    global PASS, FAIL
    bad = [abs(g - w) for g, w in zip(got, want)]
    worst = max(bad) if bad else 0.0
    if worst <= tol:
        PASS += 1
        print("  ✓ %s" % label, flush=True)
    else:
        FAIL += 1
        i = bad.index(worst)
        print("  ✗ %s  最大偏差 %.4g @[%d] got=%s want=%s"
              % (label, worst, i, got[i], want[i]), flush=True)


# ---- 缓冲工具 / buffer helpers ------------------------------------------

def make_rgb_buf(pixels, w, h):
    """pixels: [(r,g,b,a) 0..255]"""
    data = array_of(pixels)
    buf = Gegl.Buffer.new(FMT_RGB, 0, 0, w, h)
    buf.set(Gegl.Rectangle.new(0, 0, w, h), FMT_RGB, data.tobytes())
    return buf


def array_of(pixels):
    import array as _a
    flat = _a.array('f')
    for p in pixels:
        flat.extend([p[0] / 255.0, p[1] / 255.0, p[2] / 255.0,
                     p[3] / 255.0 if len(p) > 3 else 1.0])
    return flat


def read_lab(buf, w, h):
    data = buf.get(Gegl.Rectangle.new(0, 0, w, h), 1.0, FMT_LAB,
                   Gegl.AbyssPolicy.NONE)
    v = []
    import array as _a
    a = _a.array('f')
    a.frombytes(data)
    for i in range(0, len(a), 4):
        v.append((a[i], a[i + 1], a[i + 2], a[i + 3]))
    return v


# ---- 镜像模型 / python mirror -------------------------------------------

MC_STD_EPS = 1e-3


def stats(px):
    s1 = [0.0] * 3
    s2 = [0.0] * 3
    n = 0
    for p in px:
        if p[3] <= 0.0:
            continue
        for c in range(3):
            s1[c] += p[c]
            s2[c] += p[c] * p[c]
        n += 1
    if n == 0:
        return [0.0] * 3, [0.0] * 3, 0
    mean = [s1[c] / n for c in range(3)]
    std = [math.sqrt(max(s2[c] / n - mean[c] ** 2, 0.0)) for c in range(3)]
    return mean, std, n


def mapped_pixels(lab_in, tgt, src, lum, ci, fade, neutralize):
    fade_k = 1.0 - fade / 100.0
    kL = lum / 100.0 * fade_k
    kC = ci / 100.0 * fade_k
    out = []
    for p in lab_in:
        o = [0.0, 0.0, 0.0, p[3]]
        for c in range(3):
            k = kL if c == 0 else kC
            r = 1.0 if (src[1][c] < MC_STD_EPS or tgt[1][c] < MC_STD_EPS) \
                else src[1][c] / tgt[1][c]
            mu_s = 0.0 if (neutralize and c > 0) else src[0][c]
            v = p[c] * (1.0 + k * (r - 1.0)) + k * (mu_s - tgt[0][c] * r)
            if c == 0:
                v = min(max(v, 0.0), 100.0)
            else:
                v = min(max(v, -128.0), 127.0)
            o[c] = v
        out.append(o)
    return out


# ---- 跑算子 / run the op -------------------------------------------------

def run_op(in_buf, aux_buf, w, h, **props):
    root = Gegl.Node.new()
    s1 = root.create_child("gegl:buffer-source")
    s1.set_property("buffer", in_buf)
    op = root.create_child("lb:match-color")
    for k, v in props.items():
        op.set_property(k.replace('_', '-'), v)
    s1.connect_to("output", op, "input")
    if aux_buf is not None:
        s2 = root.create_child("gegl:buffer-source")
        s2.set_property("buffer", aux_buf)
        s2.connect_to("output", op, "aux")
    out = Gegl.Buffer.new(FMT_LAB, 0, 0, w, h)
    op.blit_buffer(out, Gegl.Rectangle.new(0, 0, w, h), 0,
                   Gegl.AbyssPolicy.NONE)
    return out


def check(label, in_px, aux_px, w, h, props, expect_fn, tol=LAB_TOL):
    inb = make_rgb_buf(in_px, w, h)
    auxb = make_rgb_buf(aux_px, w, h) if aux_px is not None else None
    out = run_op(inb, auxb, w, h, **props)
    got = read_lab(out, w, h)

    lab_in = read_lab(inb, w, h)   # babl 读出：与算子看到的一致
    lab_aux = read_lab(auxb, w, h) if auxb is not None else None
    want = expect_fn(lab_in, lab_aux)

    got_flat = [v for p in got for v in p]
    want_flat = [v for p in want for v in p]
    report(label, got_flat, want_flat, tol)
    return got


# ---- 测试图 / fixtures ---------------------------------------------------

W, H = 4, 4
GRAY = (128, 128, 128, 255)
RED = (200, 60, 40, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
G64 = (64, 64, 64, 255)
G192 = (192, 192, 192, 255)

checker_bw = [WHITE if (x + y) % 2 == 0 else BLACK
              for y in range(H) for x in range(W)]
checker_gr = [G192 if (x + y) % 2 == 0 else G64
              for y in range(H) for x in range(W)]
uniform_gray = [GRAY] * (W * H)
uniform_red = [RED] * (W * H)


print("== lb:match-color 端到端 ==", flush=True)

# 1. 恒等：aux = input，默认滑杆 → 原样
check("恒等（aux=自身，默认参数）", checker_bw, checker_bw, W, H, {},
      lambda li, la: li)

# 2. 均值迁移：均匀灰目标 + 均匀红来源 → σ 都为 0（比值保护 1），
#    (v−μt)=0，输出恰好是来源均值色
red_lab = read_lab(make_rgb_buf([RED], 1, 1), 1, 1)[0]
check("均匀目标 → 恰好变来源均值色", uniform_gray, uniform_red, W, H, {},
      lambda li, la: [(red_lab[0], red_lab[1], red_lab[2], 1.0)] * (W * H))

# 3. 方差缩放：黑白棋盘 → 灰 64/192 棋盘，逐像素线性映射
def _case3(li, la):
    tgt = stats(li)
    src = stats(la)
    return mapped_pixels(li, tgt, src, 100.0, 100.0, 0.0, False)


check("方差缩放（黑白→64/192 棋盘）", checker_bw, checker_gr, W, H, {}, _case3)

# 4. 亮度滑杆：来源给对比度，亮度 1 → L 几乎不动；200 → 双倍修正
def _case4a(li, la):
    tgt = stats(li)
    src = stats(la)
    return mapped_pixels(li, tgt, src, 1.0, 100.0, 0.0, False)


def _case4b(li, la):
    tgt = stats(li)
    src = stats(la)
    return mapped_pixels(li, tgt, src, 200.0, 100.0, 0.0, False)


check("亮度 1 → L 几乎不动", checker_bw, checker_gr, W, H,
      {"luminance": 1.0}, _case4a)
check("亮度 200 → 双倍 L 修正", checker_bw, checker_gr, W, H,
      {"luminance": 200.0}, _case4b)

# 5. 颜色强度：均匀灰 + 均匀红，颜色强度 1 → a/b 偏移几乎为 0
def _case5(li, la):
    tgt = stats(li)
    src = stats(la)
    return mapped_pixels(li, tgt, src, 100.0, 1.0, 0.0, False)


check("颜色强度 1 → 色度几乎不动", uniform_gray, uniform_red, W, H,
      {"color_intensity": 1.0}, _case5)

# 6. 渐隐：fade=100 完全恒等；fade=50 走一半
check("渐隐 100 → 恒等", checker_bw, checker_gr, W, H, {"fade": 100.0},
      lambda li, la: li)


def _case6(li, la):
    tgt = stats(li)
    src = stats(la)
    return mapped_pixels(li, tgt, src, 100.0, 100.0, 50.0, False)


check("渐隐 50 → 走一半", checker_bw, checker_gr, W, H, {"fade": 50.0}, _case6)

# 7. 中和：均匀红目标，aux=自身，输出 a/b 均值 = 0（去色偏）
def _case7(li, la):
    tgt = stats(li)
    src = stats(la)
    return mapped_pixels(li, tgt, src, 100.0, 100.0, 0.0, True)


got7 = check("中和去掉红色偏", uniform_red, uniform_red, W, H,
             {"neutralize": True}, _case7)
mean_a = sum(p[1] for p in got7) / len(got7)
mean_b = sum(p[2] for p in got7) / len(got7)
report("中和后输出均值 a/b ≈ 0", [mean_a, mean_b], [0.0, 0.0], 0.05)

# 8. aux 透明洞不进统计：半透明红的 aux（一半不透明红、一半 alpha=0），
#    若洞被计入，均值会被拖向黑
half_red = [RED if y < H // 2 else (0, 0, 0, 0)
            for y in range(H) for x in range(W)]
check("aux 透明洞不进统计（输出=红均值）", uniform_gray, half_red, W, H, {},
      lambda li, la: [(red_lab[0], red_lab[1], red_lab[2], 1.0)] * (W * H))

# 9. 目标透明像素：alpha 保留、透明像素不进目标统计
tgt_hole = [GRAY if y < H // 2 else (128, 128, 128, 0)
            for y in range(H) for x in range(W)]


def _case9(li, la):
    tgt = stats(li)     # 只有上半（不透明）参与
    src = stats(la)
    return mapped_pixels(li, tgt, src, 100.0, 100.0, 0.0, False)


check("目标透明像素 alpha 保留", tgt_hole, uniform_red, W, H, {}, _case9)
out9 = check("目标透明像素 alpha=0 原样", tgt_hole, uniform_red, W, H, {},
             _case9)
report("下半 alpha 仍为 0", [p[3] for p in out9[H // 2 * W:]],
       [0.0] * (W * H // 2), 1e-6)

# 10. 多行块：100 行棋盘（跨 4 个 32 行块），统计必须与小块完全一致
WH2 = 8
HH2 = 100
checker_big = [WHITE if (x + y) % 2 == 0 else BLACK
               for y in range(HH2) for x in range(WH2)]
checker_gr2 = [G192 if (x + y) % 2 == 0 else G64
               for y in range(HH2) for x in range(WH2)]


def _case10(li, la):
    tgt = stats(li)
    src = stats(la)
    return mapped_pixels(li, tgt, src, 100.0, 100.0, 0.0, False)


inb = make_rgb_buf(checker_big, WH2, HH2)
auxb = make_rgb_buf(checker_gr2, WH2, HH2)
out = run_op(inb, auxb, WH2, HH2)
got = read_lab(out, WH2, HH2)
lab_in = read_lab(inb, WH2, HH2)
lab_aux = read_lab(auxb, WH2, HH2)
want = _case10(lab_in, lab_aux)
report("100 行跨块结果与模型一致",
       [v for p in got for v in p], [v for p in want for v in p], LAB_TOL)

# 11. 无 aux：来源退化为本层自身 → 恒等
check("无 aux → 恒等", checker_gr, None, W, H, {}, lambda li, la: li)

# 12. 削顶：极端映射越出 Lab 域时削到边界
big_white = [WHITE] * (W * H)
def _case12(li, la):
    tgt = stats(li)
    src = stats(la)
    return mapped_pixels(li, tgt, src, 200.0, 200.0, 0.0, False)


check("亮度 200 恒等图不越界", big_white, big_white, W, H,
      {"luminance": 200.0, "color_intensity": 200.0}, _case12)

print("\n结果: %d/%d 通过%s" % (PASS, PASS + FAIL,
                              "" if FAIL == 0 else "（%d 项失败）" % FAIL),
      flush=True)
