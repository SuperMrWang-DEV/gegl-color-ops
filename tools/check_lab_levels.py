# -*- coding: utf-8 -*-
"""lb:lab-levels 端到端回归，在 GIMP 的 python-fu 里跑：

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \\
        --batch-interpreter=python-fu-eval \\
        -b "exec(open(r'<repo>/tools/check_lab_levels.py').read())" --quit

算子直接工作在 babl 的 CIE Lab alpha float（D50）上，RGB↔Lab 交给 babl
（不验转换本身）。这里验证 C 算子的规则：a/b gamma 绕中性轴 0 转动（灰白
像素不动）、黑白场交叉自动交换、输出反向（负片）可用、L 通道标准 levels、
alpha≤0 原样透传、LUT 查表与直接求值一致。做法：测试图先经 babl 读成
Lab、以 Lab 格式建输入缓冲（镜像与算子看同一份数值），跑同一套 levels
规则，逐像素比对 Lab 输出。
"""

import os
import sys

import gi

gi.require_version('Gegl', '0.4')
from gi.repository import Gegl

Gegl.init()


def _find_root():
    here = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() \
        else os.getcwd()
    for cand in (here, os.path.dirname(here), os.getcwd()):
        if os.path.exists(os.path.join(cand, 'ops', 'lab-levels')):
            return cand
    raise RuntimeError('请在仓库根目录运行')


ROOT = _find_root()

FMT_RGB = "R'G'B'A float"           # 感知域，测试图入口格式
FMT_LAB = "CIE Lab alpha float"     # 算子工作域（D50 白点）
TOL = 1e-2                          # float32 LUT + babl 抖动容差

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


def report_bool(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  ✓ %s" % label, flush=True)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (label, detail), flush=True)


# ---- 镜像模型：Lab 域 levels 规则（与 lab-levels.c 逐条对应） -------------

EPS = 1e-12


def levels(val, ib, iw, g, ob, ow):
    """L 通道：标准 levels，黑白场交叉自动交换，输出反向 clamp 到真实界。"""
    if ib > iw:
        ib, iw = iw, ib
    val = min(max(val, ib), iw)
    if abs(iw - ib) < EPS:
        return val
    norm = (val - ib) / (iw - ib)
    norm = max(norm, EPS) ** (1.0 / g)
    val = ob + norm * (ow - ob)
    return min(max(val, min(ob, ow)), max(ob, ow))


def levels_signed(val, ib, iw, g, ob, ow):
    """a/b 通道：gamma 绕中性轴 0，负/正半轴各自归一化。"""
    if ib > iw:
        ib, iw = iw, ib
    val = min(max(val, ib), iw)
    neg = val < 0.0
    lo = ib if neg else 0.0
    hi = 0.0 if neg else iw
    span = hi - lo
    if abs(span) < EPS:
        return val
    norm = (val - lo) / span
    norm = max(norm, EPS) ** (1.0 / g)
    olo = ob if neg else 0.0
    ohi = 0.0 if neg else ow
    val = olo + norm * (ohi - olo)
    return min(max(val, min(olo, ohi)), max(olo, ohi))


def mirror(lab_in, props):
    """lab_in: [(L,a,b,alpha)]；返回期望的 [(L,a,b,alpha)]。"""
    Lb = props.get('L_in_black', 0.0);  Lw = props.get('L_in_white', 100.0)
    Lg = props.get('L_gamma', 1.0)
    Lob = props.get('L_out_black', 0.0); Low = props.get('L_out_white', 100.0)
    ab = props.get('a_in_black', -128.0); aw = props.get('a_in_white', 127.0)
    ag = props.get('a_gamma', 1.0)
    aob = props.get('a_out_black', -128.0); aow = props.get('a_out_white', 127.0)
    bb = props.get('b_in_black', -128.0); bw = props.get('b_in_white', 127.0)
    bg = props.get('b_gamma', 1.0)
    bob = props.get('b_out_black', -128.0); bow = props.get('b_out_white', 127.0)
    out = []
    for p in lab_in:
        L, ach, bch, a = p
        if a <= 0.0:
            out.append((L, ach, bch, 0.0))
            continue
        L = levels(L, Lb, Lw, Lg, Lob, Low)
        ach = levels_signed(ach, ab, aw, ag, aob, aow)
        bch = levels_signed(bch, bb, bw, bg, bob, bow)
        out.append((L, ach, bch, a))
    return out


# ---- 跑算子 / run the op -------------------------------------------------

def make_buf(fmt, data, w, h):
    import array as _a
    flat = _a.array('f')
    for p in data:
        flat.extend(list(p))
    buf = Gegl.Buffer.new(fmt, 0, 0, w, h)
    buf.set(Gegl.Rectangle.new(0, 0, w, h), fmt, flat.tobytes())
    return buf


def read_fmt(buf, fmt, w, h):
    import array as _a
    data = buf.get(Gegl.Rectangle.new(0, 0, w, h), 1.0, fmt,
                   Gegl.AbyssPolicy.NONE)
    a = _a.array('f')
    a.frombytes(data)
    return [tuple(a[i:i + 4]) for i in range(0, len(a), 4)]


def run_op(in_buf, w, h, **props):
    root = Gegl.Node.new()
    s1 = root.create_child("gegl:buffer-source")
    s1.set_property("buffer", in_buf)
    op = root.create_child("lb:lab-levels")
    for k, v in props.items():
        op.set_property(k.replace('_', '-'), v)
    s1.connect_to("output", op, "input")
    out = Gegl.Buffer.new(FMT_LAB, 0, 0, w, h)
    op.blit_buffer(out, Gegl.Rectangle.new(0, 0, w, h), 0,
                   Gegl.AbyssPolicy.NONE)
    return out


def check(label, in_px, props):
    """in_px: [(r,g,b,a) 0..255 感知值]。先经 babl 转成 Lab 建缓冲，
    再喂算子——保证镜像与算子看到的是同一份数值（避免两条 babl
    转换路径的浮点路径差被 gamma 放大）。返回 (Lab 输出, Lab 输入)。"""
    w = len(in_px)
    h = 1
    rgb_buf = make_buf(FMT_RGB, [(p[0] / 255.0, p[1] / 255.0, p[2] / 255.0,
                                  p[3] / 255.0 if len(p) > 3 else 1.0)
                                 for p in in_px], w, h)
    lab_in = read_fmt(rgb_buf, FMT_LAB, w, h)   # babl 读出 Lab 数值
    inb = make_buf(FMT_LAB, lab_in, w, h)       # 以 Lab 建输入缓冲
    out = run_op(inb, w, h, **props)
    got = read_fmt(out, FMT_LAB, w, h)

    want = mirror(lab_in, props)

    report(label, [v for p in got for v in p],
           [v for p in want for v in p], TOL)
    return got, lab_in


# ---- 测试图 / fixtures ---------------------------------------------------

WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
G64 = (64, 64, 64, 255)
G128 = (128, 128, 128, 255)
G192 = (192, 192, 192, 255)
RED = (200, 60, 40, 255)
TEAL = (30, 160, 140, 255)
MAG = (190, 40, 180, 255)
GRAYS = [WHITE, G192, G128, G64, BLACK]

print("== lb:lab-levels 端到端 ==", flush=True)

# 1. 恒等：默认参数（LUT 恒等映射应与输入逐位一致）
got1, lab1 = check("恒等（默认参数）",
                   [RED, TEAL, MAG, G128, G64, WHITE, BLACK], {})
report("恒等输出与输入 Lab 一致",
       [v for p in got1 for v in p], [v for p in lab1 for v in p], 1e-3)

# 2. 关键回归：a/b gamma≠1 时中性（灰白）像素不动
got2, lab2 = check("a/b gamma=2.0 灰白不动", GRAYS,
                   {"a_gamma": 2.0, "b_gamma": 0.5})
report("灰白像素 a/b 保持 ≈ 0",
       [v for p in got2 for v in p[1:3]],
       [0.0] * (len(GRAYS) * 2), 1e-3)
report("灰白像素 L 不变",
       [p[0] for p in got2], [p[0] for p in lab2], 1e-3)

# 3. a gamma 对彩色中间调：红/洋红 a>0 会被增强
check("a gamma=2.0 彩色像素走镜像", [RED, MAG, TEAL], {"a_gamma": 2.0})

# 4. L gamma：中间调提亮/压暗
check("L gamma=0.5", [G64, G128, G192, RED], {"L_gamma": 0.5})
check("L gamma=2.0", [G64, G128, G192, RED], {"L_gamma": 2.0})

# 5. L 黑白场：重映射 + 削顶
got5, lab5 = check("L 输入黑场 50（暗部削顶变黑）", GRAYS,
                   {"L_in_black": 50.0})
report("L<50 全部削到 0",
       [p[0] for p in got5 if lab5[GRAYS.index(WHITE)] is not None][:0] +
       [p[0] for i, p in enumerate(got5) if lab5[i][0] < 50.0],
       [0.0] * sum(1 for p in lab5 if p[0] < 50.0), 1e-3)
check("L 输入黑白场 20..90", GRAYS,
      {"L_in_black": 20.0, "L_in_white": 90.0})

# 6. L 输出反向（负片）：out 100→0，黑白互换且严格单调
got6, lab6 = check("L 输出反向 100→0（负片）", GRAYS,
                   {"L_out_black": 100.0, "L_out_white": 0.0})
rs6 = [p[0] for p in got6]
# GRAYS 顺序是 白→黑，负片后应为 黑→白：严格递增，首像素≈0、尾像素≈100
report_bool("反向输出黑白互换且单调递增",
            all(rs6[i] < rs6[i + 1] - 2.0 for i in range(len(rs6) - 1))
            and rs6[0] < 5.0 and rs6[-1] > 95.0,
            "L 序列=%s" % [round(v, 1) for v in rs6])

# 7. a 输入交叉：自动交换而不是塌成单值
got7, lab7 = check("a 输入交叉 100..-100 自动交换", [RED, MAG, TEAL],
                   {"a_in_black": 100.0, "a_in_white": -100.0})
as7 = [p[1] for p in got7]
report_bool("交叉后输出不塌成单值（三像素 a 互异）",
            max(as7) - min(as7) > 5.0,
            "a 序列=%s" % [round(v, 1) for v in as7])

# 8. a/b 输出反向（色度负片）
check("a/b 输出反向（色度负片）", [RED, MAG, TEAL, G128],
      {"a_out_black": 127.0, "a_out_white": -128.0,
       "b_out_black": 127.0, "b_out_white": -128.0})

# 9. 透明像素透传：极端参数下 alpha=0 的 Lab 原样
half_alpha = [RED, (10, 20, 30, 0), G64, (255, 0, 0, 0), G192, (0, 255, 0, 0)]
got9, lab9 = check("透明像素 Lab 原样透传", half_alpha,
                   {"L_gamma": 3.0, "a_gamma": 0.3, "L_in_black": 30.0})
report("透明像素与输入 Lab 一致",
       [v for i, p in enumerate(got9) if half_alpha[i][3] == 0 for v in p],
       [v for i, p in enumerate(lab9) if half_alpha[i][3] == 0 for v in p],
       1e-6)

# 10. alpha 保留
got10, lab10 = check("半透明 alpha 保留",
                     [(RED[0], RED[1], RED[2], 128), G128],
                     {"L_gamma": 0.5})
report("alpha 通道不变", [p[3] for p in got10],
       [128 / 255.0, 1.0], 1e-6)

# 11. 组合拳：全部滑杆一起动（镜像模型整体校验）
check("组合参数整体校验", [RED, TEAL, MAG, G64, G192, WHITE, BLACK],
      {"L_in_black": 10.0, "L_in_white": 95.0, "L_gamma": 1.3,
       "L_out_black": 5.0, "L_out_white": 98.0,
       "a_in_black": -100.0, "a_in_white": 110.0, "a_gamma": 1.4,
       "a_out_black": -110.0, "a_out_white": 120.0,
       "b_in_black": -90.0, "b_in_white": 120.0, "b_gamma": 0.7,
       "b_out_black": -120.0, "b_out_white": 100.0})

print("== 结果: %d 通过 / %d 失败 ==" % (PASS, FAIL), flush=True)
if FAIL:
    sys.stdout.flush()
    os._exit(1)
