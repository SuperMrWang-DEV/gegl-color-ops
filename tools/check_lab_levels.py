# -*- coding: utf-8 -*-
"""lb:lab-levels 端到端回归，在 GIMP 的 python-fu 里跑：

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \\
        --batch-interpreter=python-fu-eval \\
        -b "exec(open(r'<repo>/tools/check_lab_levels.py').read())" --quit

验证的不是 RGB↔Lab 转换本身（镜像同一套 D65 公式），而是 C 算子的规则：
a/b gamma 绕中性轴 0 转动（灰白像素不动）、黑白场交叉自动交换、输出反向
（负片）可用、L 通道标准 levels、alpha≤0 原样透传。做法：测试图以
R'G'B'A float 建 GeglBuffer，喂给算子；镜像侧以 RGBA float（线性光）读入、
跑同一套 D65 公式与 levels 规则，再把期望值经 babl 转回感知域逐像素比对。
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

FMT_RGB = "R'G'B'A float"   # 感知域（babl 命名，带 ' 表示已编码）
FMT_LIN = "RGBA float"      # 线性光，算子实际处理的域
TOL = 5e-3                  # float32 + babl 往返抖动容差

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


# ---- 镜像模型：D65 Lab + levels 规则（与 lab-levels.c 逐条对应） ----------

EPS = 1e-12


def lab_forward(t):
    t = max(t, EPS)
    return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0


def lab_inverse(t):
    return t ** 3 if t > 0.206893 else (t - 16.0 / 116.0) / 7.787


def rgb_to_lab(r, g, b):
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    fx = lab_forward(x / 0.95047)
    fy = lab_forward(y)
    fz = lab_forward(z / 1.08883)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def lab_to_rgb(L, a, b):
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    x = lab_inverse(fx) * 0.95047
    y = lab_inverse(fy)
    z = lab_inverse(fz) * 1.08883
    return (x * 3.2404542 + y * -1.5371385 + z * -0.4985314,
            x * -0.9692660 + y * 1.8760108 + z * 0.0415560,
            x * 0.0556434 + y * -0.2040259 + z * 1.0572252)


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


def mirror(pixels_lin, props):
    """pixels_lin: 线性光 RGBA；返回期望的线性光 RGBA。"""
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
    for p in pixels_lin:
        r, g, b, a = p
        if a <= 0.0:
            out.append((r, g, b, 0.0))
            continue
        L, ach, bch = rgb_to_lab(r, g, b)
        L = levels(L, Lb, Lw, Lg, Lob, Low)
        ach = levels_signed(ach, ab, aw, ag, aob, aow)
        bch = levels_signed(bch, bb, bw, bg, bob, bow)
        nr, ng, nb = lab_to_rgb(L, ach, bch)
        out.append((min(max(nr, 0.0), 1.0),
                    min(max(ng, 0.0), 1.0),
                    min(max(nb, 0.0), 1.0), a))
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
    out = Gegl.Buffer.new(FMT_RGB, 0, 0, w, h)
    op.blit_buffer(out, Gegl.Rectangle.new(0, 0, w, h), 0,
                   Gegl.AbyssPolicy.NONE)
    return out


def check(label, in_px, props):
    """in_px: [(r,g,b,a) 0..255 感知值]。"""
    w = len(in_px)
    h = 1
    inb = make_buf(FMT_RGB, [(p[0] / 255.0, p[1] / 255.0, p[2] / 255.0,
                              p[3] / 255.0 if len(p) > 3 else 1.0)
                             for p in in_px], w, h)
    out = run_op(inb, w, h, **props)
    got = read_fmt(out, FMT_RGB, w, h)

    lin_in = read_fmt(inb, FMT_LIN, w, h)          # 算子看到的线性光
    want_lin = mirror(lin_in, props)
    want_buf = make_buf(FMT_LIN, want_lin, w, h)   # 经 babl 转回感知域
    want = read_fmt(want_buf, FMT_RGB, w, h)

    report(label, [v for p in got for v in p],
           [v for p in want for v in p], TOL)
    return got


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

# 1. 恒等：默认参数 → 原样
check("恒等（默认参数）", [RED, TEAL, MAG, G128, G64, WHITE, BLACK], {})

# 2. 关键回归：a/b gamma≠1 时中性（灰白）像素不动
got2 = check("a/b gamma=2.0 灰白不动", GRAYS,
             {"a_gamma": 2.0, "b_gamma": 0.5})
report("灰白像素 RGB 偏差 ≈ 0",
       [v for p in got2 for v in p[:3]],
       [v / 255.0 for p in GRAYS for v in p[:3]], 1.5e-2)

# 3. a gamma 对彩色中间调：镜像模型比对（红 a>0 会被增强）
check("a gamma=2.0 彩色像素走镜像", [RED, MAG, TEAL], {"a_gamma": 2.0})

# 4. L gamma：中间调提亮/压暗
check("L gamma=0.5", [G64, G128, G192, RED], {"L_gamma": 0.5})
check("L gamma=2.0", [G64, G128, G192, RED], {"L_gamma": 2.0})

# 5. L 黑白场：重映射 + 削顶
check("L 输入黑场 50（暗部削顶变黑）", GRAYS, {"L_in_black": 50.0})
check("L 输入黑白场 20..90", GRAYS, {"L_in_black": 20.0, "L_in_white": 90.0})

# 6. L 输出反向（负片）：out 100→0，黑白互换且严格单调
got6 = check("L 输出反向 100→0（负片）", GRAYS,
             {"L_out_black": 100.0, "L_out_white": 0.0})


def _monotone_decreasing(seq, margin=0.02):
    return all(seq[i] > seq[i + 1] + margin for i in range(len(seq) - 1))


rs6 = [p[0] for p in got6]
# GRAYS 顺序是 白→黑，负片后应为 黑→白：严格递增，首像素≈0、尾像素≈1
report_bool("反向输出黑白互换且单调递增",
            all(rs6[i] < rs6[i + 1] - 0.02 for i in range(len(rs6) - 1))
            and rs6[0] < 0.1 and rs6[-1] > 0.9,
            "R 序列=%s" % [round(v, 3) for v in rs6])

# 7. a 输入交叉：自动交换而不是塌成单值
got7 = check("a 输入交叉 100..-100 自动交换", [RED, MAG, TEAL],
             {"a_in_black": 100.0, "a_in_white": -100.0})
rs7 = [p[0] for p in got7]
report_bool("交叉后输出不塌成单值（三像素 R 互异）",
            max(rs7) - min(rs7) > 0.1,
            "R 序列=%s" % [round(v, 3) for v in rs7])

# 8. a/b 输出反向（色度负片）
check("a/b 输出反向（色度负片）", [RED, MAG, TEAL, G128],
      {"a_out_black": 127.0, "a_out_white": -128.0,
       "b_out_black": 127.0, "b_out_white": -128.0})

# 9. 透明像素透传：极端参数下 alpha=0 的 RGB 原样
half_alpha = [RED, (10, 20, 30, 0), G64, (255, 0, 0, 0), G192, (0, 255, 0, 0)]
got9 = check("透明像素 RGB 原样透传", half_alpha,
             {"L_gamma": 3.0, "a_gamma": 0.3, "L_in_black": 30.0})
report("透明像素与输入逐位一致",
       [v for i, p in enumerate(got9) if half_alpha[i][3] == 0
        for v in p[:3]],
       [half_alpha[i][c] / 255.0 for i, p in enumerate(half_alpha)
        if p[3] == 0 for c in range(3)], 1e-6)

# 10. alpha 保留
got10 = check("半透明 alpha 保留", [(RED[0], RED[1], RED[2], 128), G128],
              {"L_gamma": 0.5})
report("alpha 通道不变", [p[3] for p in got10], [128 / 255.0, 1.0], 1e-6)

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
