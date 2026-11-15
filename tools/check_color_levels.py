# -*- coding: utf-8 -*-
"""验收五个分量色阶算子：lb:hsl-levels / hsb-levels / lch-levels /
cmyk-levels / hsi-levels。

    python tools/check_color_levels.py          # 跑全部
    python tools/check_color_levels.py hsl      # 只跑某个

四类检查：
  A 恒等   —— 默认参数必须把图原样还回来（±1 码，纯 8 位量化）
  B 语义   —— 把某个分量映成常量应得到可验证的结果：
              饱和度/色度 → 0  ⇒ 全图中性灰（|R−G|、|G−B| ≈ 0）
              K → 100          ⇒ 全图近黑
  C 公式   —— HSL / HSB / HSI 用 Python 复算同一套色阶与色彩转换，逐像素对拍
              （色相的弧重映射、gamma、黑白场交叉都在参数里）
  D 透明   —— alpha=0 的像素原样透传，RGB 不被映射

LCh 与 CMYK 的 RGB↔模型转换在 babl 里，Python 无法复算，所以这两个只做
A/B 两类 + 单独一条「色相环转 180° 后色相确实变了」的弱断言。
"""
import math
import os
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from contact_sheet import read_png, write_png     # noqa: E402

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GIMP 3", "bin", "gegl.exe"),
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]

W = 72            # 每行像素数
OK, FAIL = [], []

# 探针的路径与像素数据，main() 里填；用例函数共用（探针固定，不需要传参）
SRC_PATH = None
SRC = None


def find_gegl():
    for c in GEGL_CANDIDATES:
        if c and os.path.exists(c):
            return c
    raise SystemExit("找不到 gegl 可执行文件，用 GEGL_BIN=... 指定")


def gegl_env(exe):
    env = dict(os.environ)
    lib = os.path.join(os.path.dirname(os.path.dirname(exe)), "lib", "gegl-0.4")
    if os.name == "nt":
        dest = os.path.join(os.environ.get("LOCALAPPDATA", ""), "gegl-0.4", "plug-ins")
        env["GEGL_PATH"] = dest + ";" + lib
    else:
        env["GEGL_PATH"] = os.path.expanduser("~/.local/share/gegl-0.4/plug-ins") + ":" + lib
    return env


# ----------------------------------------------------------------- 测试图 ---

def hsl_rgb(h, s, l):
    """标准 HSL -> RGB（0-1 输入输出）。"""
    h = h % 360.0
    c = (1.0 - abs(2.0 * l - 1.0)) * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = l - c / 2.0
    if h < 60:    r, g, b = c, x, 0.0
    elif h < 120: r, g, b = x, c, 0.0
    elif h < 180: r, g, b = 0.0, c, x
    elif h < 240: r, g, b = 0.0, x, c
    elif h < 300: r, g, b = x, 0.0, c
    else:         r, g, b = c, 0.0, x
    return r + m, g + m, b + m


def build_probe(path):
    """四行探针：色相环 / 灰阶 / 同色相下的饱和度斜坡 / 深浅交替的饱和色。"""
    rows = []
    row = []
    for i in range(W):
        r, g, b = hsl_rgb(360.0 * i / W, 1.0, 0.5)
        row += [int(round(v * 255)) for v in (r, g, b)]
    rows.append(row)

    row = []
    for i in range(W):
        v = int(round(255.0 * i / (W - 1)))
        row += [v, v, v]
    rows.append(row)

    row = []
    for i in range(W):
        r, g, b = hsl_rgb(30.0, i / (W - 1.0), 0.55)
        row += [int(round(v * 255)) for v in (r, g, b)]
    rows.append(row)

    row = []
    for i in range(W):
        l = 0.30 if (i // 6) % 2 == 0 else 0.62
        r, g, b = hsl_rgb((i * 15.0) % 360.0, 0.85, l)
        row += [int(round(v * 255)) for v in (r, g, b)]
    rows.append(row)

    write_png(path, W, len(rows), rows)
    return read_png(path)


def build_alpha_probe(path):
    """上行不透明、下行全透明；RGB 用饱和色，便于检查透明处有没有被映射。"""
    rows = []
    alpha = []
    for a in (255, 0):
        row, al = [], []
        for i in range(W):
            r, g, b = hsl_rgb((i * 17.0) % 360.0, 0.9, 0.5)
            row += [int(round(v * 255)) for v in (r, g, b)]
            al.append(a)
        rows.append(row)
        alpha.append(al)

    raw = b""
    for row, al in zip(rows, alpha):
        line = bytearray()
        for i in range(W):
            line += bytes(row[i * 3:i * 3 + 3]) + bytes([al[i]])
        raw += b"\x00" + bytes(line)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    open(path, "wb").write(b"\x89PNG\r\n\x1a\n"
                           + chunk(b"IHDR", struct.pack(">IIBBBBB", W, 2, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9))
                           + chunk(b"IEND", b""))
    return alpha


# ------------------------------------------------------------- 色阶复算 ---

def wrap360(a):
    a = math.fmod(a, 360.0)
    return a + 360.0 if a < 0 else a


def arc(a, b):
    return wrap360(b - a)


def lv_linear(v, ib, iw, gamma, ob, ow):
    if ib > iw:
        ib, iw = iw, ib
    if abs(iw - ib) < 1e-9:
        return v
    v = min(max(v, ib), iw)
    t = max((v - ib) / (iw - ib), 1e-9) ** (1.0 / gamma)
    v = ob + t * (ow - ob)
    return min(max(v, min(ob, ow)), max(ob, ow))


def lv_hue(h, ia, ib, gamma, oa, ob):
    in_span, out_span, z = arc(ia, ib), arc(oa, ob), arc(ia, h)
    if in_span < 1e-3:
        in_span = 360.0
    if out_span < 1e-3:
        out_span = 360.0
    if z <= in_span:
        t, base, span = z / in_span, oa, out_span
    else:
        rest = 360.0 - in_span
        t = 0.0 if rest < 1e-3 else (z - in_span) / rest
        base, span = oa + out_span, 360.0 - out_span
    return wrap360(base + span * max(t, 0.0) ** (1.0 / gamma))


# --------------------------------------------------------------- 渲染 ---

def render(exe, env, op, src, dst, props):
    cmd = [exe, src, "-o", dst, "--", op] + ["%s=%g" % (k, v) for k, v in props.items()]
    r = subprocess.run(cmd, env=env, capture_output=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("渲染失败 %s %s\n%s\n%s"
                         % (op, props, r.stdout.decode("utf-8", "replace"),
                            r.stderr.decode("utf-8", "replace")))


def diff(a, b):
    """返回 (中位, 最大, 最差点)。"""
    w, h, A = a
    _, _, B = b
    ds, worst = [], None
    for y in range(h):
        for x in range(w):
            d = max(abs(A[y][x][i] - B[y][x][i]) for i in range(3))
            ds.append(d)
            if worst is None or d > worst[0]:
                worst = (d, x, y, A[y][x], B[y][x])
    ds.sort()
    return ds[len(ds) // 2], ds[-1], worst


def report(name, ok, detail=""):
    (OK if ok else FAIL).append(name)
    print("%s %-46s %s" % ("✓" if ok else "✗", name, detail))


# ----------------------------------------------------------------- 用例 ---

def test_identity(exe, env, op, tmp, tol=1):
    dst = os.path.join(tmp, "id-%s.png" % op.replace(":", "-"))
    render(exe, env, op, SRC_PATH, dst, {})
    med, mx, _ = diff(SRC, read_png(dst))
    report("%s 恒等（默认参数）" % op, mx <= tol, "中位 %d 最大 %d" % (med, mx))


def test_neutral(exe, env, op, tmp, props, name):
    dst = os.path.join(tmp, "n-%s-%d.png" % (op.replace(":", "-"), abs(hash(name)) % 9999))
    render(exe, env, op, SRC_PATH, dst, props)
    w, h, B = read_png(dst)
    worst = 0
    for y in range(h):
        for x in range(w):
            p = B[y][x]
            worst = max(worst, abs(p[0] - p[1]), abs(p[1] - p[2]))
    report("%s %s" % (op, name), worst <= 2, "最大通道差 %d" % worst)


def test_black(exe, env, op, tmp, props, name, thr=12):
    dst = os.path.join(tmp, "b-%s-%d.png" % (op.replace(":", "-"), abs(hash(name)) % 9999))
    render(exe, env, op, SRC_PATH, dst, props)
    w, h, B = read_png(dst)
    worst = max(max(p) for y in range(h) for p in B[y])
    report("%s %s" % (op, name), worst <= thr, "最亮通道 %d" % worst)


def test_formula(exe, env, op, kind, tmp, props, tol=2):
    """用 Python 复算 HSL/HSB/HSI 的整条链路，逐像素对拍。"""
    dst = os.path.join(tmp, "f-%s-%s.png" % (op.replace(":", "-"), kind))
    render(exe, env, op, SRC_PATH, dst, props)
    got = read_png(dst)[2]
    w, h, A = SRC
    worst, worst_at = 0, None

    for y in range(h):
        for x in range(w):
            r, g, b = [A[y][x][i] / 255.0 for i in range(3)]

            if kind == "hsl":
                mx, mn = max(r, g, b), min(r, g, b)
                l = (mx + mn) / 2.0
                c = mx - mn
                s = 0.0 if c < 1e-9 else c / (1.0 - abs(2.0 * l - 1.0))
                if c < 1e-9:
                    hh = 0.0
                elif mx == r:
                    hh = 60.0 * ((g - b) / c) % 360.0
                elif mx == g:
                    hh = 60.0 * ((b - r) / c) + 120.0
                else:
                    hh = 60.0 * ((r - g) / c) + 240.0
                hh = lv_hue(hh, props["h-in-black"], props["h-in-white"], props["h-gamma"],
                            props["h-out-black"], props["h-out-white"])
                s = lv_linear(s * 100, props["s-in-black"], props["s-in-white"], props["s-gamma"],
                              props["s-out-black"], props["s-out-white"]) / 100.0
                l = lv_linear(l * 100, props["l-in-black"], props["l-in-white"], props["l-gamma"],
                              props["l-out-black"], props["l-out-white"]) / 100.0
                pred = hsl_rgb(hh, s, l)

            elif kind == "hsb":
                mx, mn = max(r, g, b), min(r, g, b)
                v = mx
                c = mx - mn
                s = 0.0 if mx < 1e-9 else c / mx
                if c < 1e-9:
                    hh = 0.0
                elif mx == r:
                    hh = 60.0 * ((g - b) / c) % 360.0
                elif mx == g:
                    hh = 60.0 * ((b - r) / c) + 120.0
                else:
                    hh = 60.0 * ((r - g) / c) + 240.0
                hh = lv_hue(hh, props["h-in-black"], props["h-in-white"], props["h-gamma"],
                            props["h-out-black"], props["h-out-white"])
                s = lv_linear(s * 100, props["s-in-black"], props["s-in-white"], props["s-gamma"],
                              props["s-out-black"], props["s-out-white"]) / 100.0
                v = lv_linear(v * 100, props["b-in-black"], props["b-in-white"], props["b-gamma"],
                              props["b-out-black"], props["b-out-white"]) / 100.0
                # HSV -> RGB
                cc = v * s
                xx = cc * (1.0 - abs((hh / 60.0) % 2.0 - 1.0))
                m = v - cc
                if hh < 60:    rr, gg, bb = cc, xx, 0.0
                elif hh < 120: rr, gg, bb = xx, cc, 0.0
                elif hh < 180: rr, gg, bb = 0.0, cc, xx
                elif hh < 240: rr, gg, bb = 0.0, xx, cc
                elif hh < 300: rr, gg, bb = xx, 0.0, cc
                else:          rr, gg, bb = cc, 0.0, xx
                pred = (rr + m, gg + m, bb + m)

            else:   # hsi
                I = (r + g + b) / 3.0
                mn = min(r, g, b)
                if I < 1e-9 or max(r, g, b) - mn < 1e-9:
                    hh, s = 0.0, 0.0
                else:
                    s = 1.0 - mn / I
                    num = 0.5 * ((r - g) + (r - b))
                    den = math.sqrt((r - g) ** 2 + (r - b) * (g - b))
                    if den < 1e-9:
                        hh = 0.0
                    else:
                        theta = math.degrees(math.acos(max(-1.0, min(1.0, num / den))))
                        hh = theta if b <= g else 360.0 - theta
                hh = lv_hue(hh, props["h-in-black"], props["h-in-white"], props["h-gamma"],
                            props["h-out-black"], props["h-out-white"])
                s = lv_linear(s * 100, props["s-in-black"], props["s-in-white"], props["s-gamma"],
                              props["s-out-black"], props["s-out-white"]) / 100.0
                I = lv_linear(I * 100, props["i-in-black"], props["i-in-white"], props["i-gamma"],
                              props["i-out-black"], props["i-out-white"]) / 100.0
                s = min(max(s, 0.0), 1.0)
                I = min(max(I, 0.0), 1.0)
                hh = wrap360(hh)
                if hh < 120:
                    lo = I * (1 - s)
                    hi = I * (1 + s * math.cos(math.radians(hh)) /
                              math.cos(math.radians(60 - hh)))
                    mid = 3 * I - lo - hi
                    pred = (hi, mid, lo)
                elif hh < 240:
                    a = hh - 120
                    lo = I * (1 - s)
                    hi = I * (1 + s * math.cos(math.radians(a)) /
                              math.cos(math.radians(60 - a)))
                    mid = 3 * I - lo - hi
                    pred = (lo, hi, mid)
                else:
                    a = hh - 240
                    lo = I * (1 - s)
                    hi = I * (1 + s * math.cos(math.radians(a)) /
                              math.cos(math.radians(60 - a)))
                    mid = 3 * I - lo - hi
                    pred = (mid, lo, hi)

            exp = [int(round(min(max(v, 0.0), 1.0) * 255)) for v in pred]
            d = max(abs(exp[i] - got[y][x][i]) for i in range(3))
            if d > worst:
                worst, worst_at = d, (x, y, exp, got[y][x])

    report("%s 公式对拍（%s）" % (op, kind), worst <= tol,
           "最大 %d %s" % (worst, "" if worst <= tol else worst_at))


def test_alpha(exe, env, op, tmp):
    src = os.path.join(tmp, "alpha.png")
    alpha = build_alpha_probe(src)
    out = os.path.join(tmp, "alpha-out.png")
    render(exe, env, op, src, out, {"l-out-black": 0.0, "l-out-white": 30.0,
                                    "h-out-black": 200.0, "h-out-white": 200.0})
    w, h, B = read_png(out)
    A = read_png(src)[2]
    bad_rgb = max(max(abs(A[1][x][i] - B[1][x][i]) for i in range(3)) for x in range(w))
    report("%s 透明像素透传" % op, bad_rgb == 0, "透明行 RGB 最大偏移 %d" % bad_rgb)


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    exe = find_gegl()
    env = gegl_env(exe)
    tmp = tempfile.mkdtemp(prefix="clchk-")
    global SRC_PATH, SRC
    SRC_PATH = os.path.join(tmp, "probe.png")
    SRC = build_probe(SRC_PATH)
    src = SRC
    print("· gegl %s\n· 探针 %s（%dx%d）" % (exe, SRC_PATH, W, 4))

    def run(key):
        return not want or key in want

    if run("hsl"):
        p = {"h-in-black": 30.0, "h-in-white": 330.0, "h-gamma": 1.4,
             "h-out-black": 0.0, "h-out-white": 300.0,
             "s-in-black": 10.0, "s-in-white": 90.0, "s-gamma": 0.8,
             "s-out-black": 0.0, "s-out-white": 100.0,
             "l-in-black": 5.0, "l-in-white": 95.0, "l-gamma": 1.1,
             "l-out-black": 5.0, "l-out-white": 95.0}
        test_identity(exe, env, "lb:hsl-levels", tmp)
        test_neutral(exe, env, "lb:hsl-levels", tmp,
                     {"s-out-black": 0.0, "s-out-white": 0.0}, "饱和度归零 → 中性灰")
        test_black(exe, env, "lb:hsl-levels", tmp,
                   {"l-out-black": 0.0, "l-out-white": 0.0}, "明度归零 → 全黑")
        test_formula(exe, env, "lb:hsl-levels", "hsl", tmp, p)
        test_alpha(exe, env, "lb:hsl-levels", tmp)

    if run("hsb"):
        p = {"h-in-black": 0.0, "h-in-white": 360.0, "h-gamma": 1.0,
             "h-out-black": 40.0, "h-out-white": 40.0,
             "s-in-black": 15.0, "s-in-white": 100.0, "s-gamma": 1.2,
             "s-out-black": 0.0, "s-out-white": 100.0,
             "b-in-black": 0.0, "b-in-white": 100.0, "b-gamma": 1.0,
             "b-out-black": 10.0, "b-out-white": 90.0}
        test_identity(exe, env, "lb:hsb-levels", tmp)
        test_neutral(exe, env, "lb:hsb-levels", tmp,
                     {"s-out-black": 0.0, "s-out-white": 0.0}, "饱和度归零 → 中性灰")
        test_formula(exe, env, "lb:hsb-levels", "hsb", tmp, p)

    if run("hsi"):
        p = {"h-in-black": 0.0, "h-in-white": 360.0, "h-gamma": 1.0,
             "h-out-black": 25.0, "h-out-white": 25.0,
             "s-in-black": 0.0, "s-in-white": 100.0, "s-gamma": 0.9,
             "s-out-black": 20.0, "s-out-white": 80.0,
             "i-in-black": 0.0, "i-in-white": 100.0, "i-gamma": 1.0,
             "i-out-black": 5.0, "i-out-white": 95.0}
        test_identity(exe, env, "lb:hsi-levels", tmp)
        test_neutral(exe, env, "lb:hsi-levels", tmp,
                     {"s-out-black": 0.0, "s-out-white": 0.0}, "饱和度归零 → 中性灰")
        test_formula(exe, env, "lb:hsi-levels", "hsi", tmp, p)

    if run("lch"):
        test_identity(exe, env, "lb:lch-levels", tmp)
        test_neutral(exe, env, "lb:lch-levels", tmp,
                     {"c-out-black": 0.0, "c-out-white": 0.0}, "色度归零 → 中性灰")
        # 色相环转 180°：色相环那一行的平均色相必须整体翻转
        dst = os.path.join(tmp, "lch-hue.png")
        render(exe, env, "lb:lch-levels", SRC_PATH, dst,
               {"h-out-black": 180.0, "h-out-white": 180.0})
        w, h, B = read_png(dst)
        moved = 0
        for x in range(w):
            d = max(abs(B[0][x][i] - src[2][0][x][i]) for i in range(3))
            if d > 40:
                moved += 1
        report("lb:lch-levels 色相环 +180°", moved >= w * 0.8,
               "%d/%d 个采样点明显变色" % (moved, w))

    if run("cmyk"):
        test_identity(exe, env, "lb:cmyk-levels", tmp)
        test_neutral(exe, env, "lb:cmyk-levels", tmp,
                     {"c-out-black": 0.0, "c-out-white": 0.0,
                      "m-out-black": 0.0, "m-out-white": 0.0,
                      "y-out-black": 0.0, "y-out-white": 0.0}, "C/M/Y 归零 → 只剩 K 的中性图")
        test_black(exe, env, "lb:cmyk-levels", tmp,
                   {"k-out-black": 100.0, "k-out-white": 100.0}, "K 拉满 → 近黑")

    print("\n结果：%d 通过，%d 失败" % (len(OK), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  ✗ %s" % f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
