#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lb:color-lookup 数值验收：与一份独立写的 Cube LUT 实现逐像素比对。

参考实现刻意不复用算子里的索引写法（这里用 itertools 展开角点、按
(i,j,k) 三维列表取值），这样既能验证「红变化最快」的下标排布，也能守住
domain 归一化、1D shaper 与两种插值。

用法：
    python tools/check_color_lookup.py            # 7 个内置 LUT
    python tools/check_color_lookup.py 某个.cube   # 额外比对指定文件
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.dirname(ROOT)
for _p in (os.path.join(WORK, "bc-cal"), os.path.join(ROOT, "bc-cal"), ROOT):
    sys.path.insert(0, _p)
from readpng import read_png                      # noqa: E402

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
    "gegl",
]


def find_gegl():
    for c in GEGL_CANDIDATES:
        if c and (os.path.exists(c) or c == "gegl"):
            return c
    raise SystemExit("找不到 gegl 可执行文件，用 GEGL_BIN=... 指定")


def env_for_gegl(exe):
    """GEGL_PATH 是替换语义，必须带上 GIMP 自带的 core 算子目录，见 tools/smoke.sh。"""
    env = dict(os.environ)
    ops = os.path.abspath(os.environ.get("OPS_DIR", os.path.join(ROOT, "build")))
    gimp = os.path.dirname(os.path.dirname(os.path.abspath(exe)))
    sys_ops = os.path.join(gimp, "lib", "gegl-0.4")
    if os.name == "nt":
        if os.path.isdir(sys_ops):
            env["GEGL_PATH"] = ops.replace("\\", "/") + ";" + sys_ops.replace("\\", "/")
        else:
            env["GEGL_PATH"] = ops.replace("\\", "/")
    else:
        env["GEGL_PATH"] = ops + ":" + sys_ops
    return env


# ------------------------------------------------------------ 参考实现 ----

def parse_cube(path):
    """返回 (n1, lut1, n3, lut3)：值已按 domain 归一化到 0..1。"""
    n1 = n3 = 0
    dmin, dmax = [0.0] * 3, [1.0] * 3
    raw = []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            key = s.split()[0].upper()
            if key == "TITLE":
                continue
            if key == "LUT_1D_SIZE":
                n1 = int(s.split()[1])
            elif key == "LUT_3D_SIZE":
                n3 = int(s.split()[1])
            elif key == "DOMAIN_MIN":
                dmin = [float(x) for x in s.split()[1:4]]
            elif key == "DOMAIN_MAX":
                dmax = [float(x) for x in s.split()[1:4]]
            elif key in ("LUT_1D_INPUT_RANGE", "LUT_3D_INPUT_RANGE"):
                a, b = [float(x) for x in s.split()[1:3]]
                dmin, dmax = [a] * 3, [b] * 3
            else:
                v = [float(x) for x in s.split()[:3]]
                if len(v) == 3:
                    raw.append(v)

    def norm(v):
        return [(v[c] - dmin[c]) / (dmax[c] - dmin[c]) if dmax[c] != dmin[c] else v[c]
                for c in range(3)]

    k1 = n1 * 3
    lut1 = [norm(v) for v in raw[:n1]] if n1 else []
    lut3 = [[[[None] * 3 for _ in range(n3)] for _ in range(n3)] for _ in range(n3)]  # [b][g][r]
    body = raw[n1:n1 + n3 ** 3]
    if len(body) < n3 ** 3:
        raise SystemExit("%s: 3D 数据不足（%d < %d）" % (path, len(body), n3 ** 3))
    for idx, v in enumerate(body):
        r = idx % n3
        g = (idx // n3) % n3
        b = idx // (n3 * n3)
        lut3[b][g][r] = norm(v)
    return n1, lut1, n3, lut3


def _shaper(v, n1, lut1):
    if n1 < 2:
        return v
    out = []
    for c in range(3):
        p = max(0.0, min(1.0, v[c])) * (n1 - 1)
        i = min(int(p), n1 - 2)
        t = p - i
        out.append(lut1[i][c] * (1 - t) + lut1[i + 1][c] * t)
    return out


def _tri(v, n3, lut3):
    f = [max(0.0, min(1.0, v[c])) * (n3 - 1) for c in range(3)]
    i = [min(int(f[c]), n3 - 2) for c in range(3)]
    t = [f[c] - i[c] for c in range(3)]
    out = [0.0, 0.0, 0.0]
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = ((t[0] if dr else 1 - t[0]) *
                     (t[1] if dg else 1 - t[1]) *
                     (t[2] if db else 1 - t[2]))
                node = lut3[i[2] + db][i[1] + dg][i[0] + dr]
                for c in range(3):
                    out[c] += w * node[c]
    return out


def _tetra(v, n3, lut3):
    """6 个四面体：先按分量大小排序，再沿三条棱插值。"""
    f = [max(0.0, min(1.0, v[c])) * (n3 - 1) for c in range(3)]
    i = [min(int(f[c]), n3 - 2) for c in range(3)]
    t = [f[c] - i[c] for c in range(3)]

    # 角点简写：c[dr][dg][db]
    def node(dr, dg, db):
        return lut3[i[2] + db][i[1] + dg][i[0] + dr]

    order = sorted(range(3), key=lambda c: -t[c])       # 大的在前
    # 依次走：最大分量方向、次大、最小
    corner = [0, 0, 0]
    corners = [node(0, 0, 0)]
    for axis in order:
        corner[axis] = 1
        corners.append(node(corner[0], corner[1], corner[2]))
    weights = [t[order[0]], t[order[1]], t[order[2]]]
    out = list(corners[0])
    prev = corners[0]
    for k in range(3):
        cur = corners[k + 1]
        for c in range(3):
            out[c] += weights[k] * (cur[c] - prev[c])
        prev = cur
    return out


def reference(rgb, lut, strength=1.0, interp="trilinear"):
    n1, lut1, n3, lut3 = lut
    v = _shaper(rgb, n1, lut1)
    if n3 >= 2:
        v = _tetra(v, n3, lut3) if interp == "tetrahedral" else _tri(v, n3, lut3)
    out = [rgb[c] + (v[c] - rgb[c]) * strength for c in range(3)]
    return [max(0.0, min(1.0, x)) for x in out]      # 算子输出端会夹到 0..1


# --------------------------------------------------------------- LUT 生成 ----

def write_cube(path, n3, fn, n1=0, fn1=None, domain=(0.0, 1.0), title="generated"):
    lines = ['TITLE "%s"' % title]
    if n1:
        lines.append("LUT_1D_SIZE %d" % n1)
    if n3 >= 2:
        lines.append("LUT_3D_SIZE %d" % n3)
    lo, hi = domain
    if (lo, hi) != (0.0, 1.0):
        lines.append("DOMAIN_MIN %.6f %.6f %.6f" % (lo, lo, lo))
        lines.append("DOMAIN_MAX %.6f %.6f %.6f" % (hi, hi, hi))

    def emit(v):
        lines.append("%.6f %.6f %.6f" % tuple(v))

    if n1:
        for i in range(n1):
            emit(fn1(i / (n1 - 1.0)))
    if n3 >= 2:
        for b in range(n3):
            for g in range(n3):
                for r in range(n3):
                    emit(fn(r / (n3 - 1.0), g / (n3 - 1.0), b / (n3 - 1.0)))

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def build_luts(tmp):
    """(名字, 路径, 说明) 列表 —— 覆盖单位元、通道对调、非线性、domain、1D shaper。"""
    out = []

    p = os.path.join(tmp, "id2.cube")
    write_cube(p, 2, lambda r, g, b: (r, g, b), title="identity 2")
    out.append(("identity2", p, "2 格单位元，必须逐字节相同"))

    p = os.path.join(tmp, "id33.cube")
    write_cube(p, 33, lambda r, g, b: (r, g, b), title="identity 33")
    out.append(("identity33", p, "33 格单位元，查插值是否退化"))

    p = os.path.join(tmp, "invert17.cube")
    write_cube(p, 17, lambda r, g, b: (1 - r, 1 - g, 1 - b), title="invert 17")
    out.append(("invert17", p, "反相，闭式可校验"))

    p = os.path.join(tmp, "swap17.cube")
    write_cube(p, 17, lambda r, g, b: (b, g, r), title="swap rb")
    out.append(("swap_rb", p, "R/B 对调，查下标排布"))

    def film(r, g, b):
        # 平滑非线性：提亮暗部 + 轻微交叉串色
        return (r ** 0.85 * 0.95 + 0.02 * g,
                g ** 1.05 * 0.98 + 0.01 * r,
                b ** 0.92 * 1.02 - 0.01 * b)

    p = os.path.join(tmp, "film33.cube")
    write_cube(p, 33, film, title="film 33")
    out.append(("film33", p, "平滑非线性，插值误差的主战场"))

    p = os.path.join(tmp, "film33d255.cube")
    write_cube(p, 33,
               lambda r, g, b: tuple(x * 255.0 for x in film(r, g, b)),
               domain=(0.0, 255.0), title="film 33 domain 255")
    out.append(("film33_d255", p, "DOMAIN_MAX 255，结果须与 film33 一致"))

    def zigzag(r, g, b):
        # 逐格翻转：三线性与四面体在这种表上差得最明显
        n = 8
        par = (round(r * n) + round(g * n) + round(b * n)) % 2
        return (0.1 + 0.8 * par, 0.9 - 0.8 * par, 0.5)

    p = os.path.join(tmp, "zigzag9.cube")
    write_cube(p, 9, zigzag, title="zigzag 9")
    out.append(("zigzag9", p, "逐格翻转，专门区分两种插值"))

    p = os.path.join(tmp, "shaper_only.cube")
    write_cube(p, 0, lambda r, g, b: (r, g, b), n1=256,
               fn1=lambda t: (t ** 0.8, t, t ** 1.25), title="1D only")
    out.append(("shaper_only", p, "纯 1D 表（无 3D），应按通道曲线走"))

    p = os.path.join(tmp, "shaper.cube")
    write_cube(p, 17, lambda r, g, b: (r, g, b), n1=1024,
               fn1=lambda t: (t ** 0.9, t ** 1.0, t ** 1.1), title="shaper + identity")
    out.append(("shaper1d", p, "1D shaper（三通道不同伽马）+ 3D 单位元"))

    return out


# --------------------------------------------------------------- 比对 ----

def make_probe(dst, size=64):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from contact_sheet import write_png
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            row += [(x * 4 + 1) & 0xFF, (y * 4 + 3) & 0xFF, ((x * 7 + y * 3) * 2 + 1) & 0xFF]
        rows.append(row)
    write_png(dst, size, size, rows)


def render(dst, probe, lut_path, strength, interp, exe):
    cmd = [exe, probe, "-o", dst, "--", "lb:color-lookup",
           "file=%s" % lut_path,
           "strength=%g" % strength,
           "interpolation=%s" % interp]
    r = subprocess.run(cmd, env=env_for_gegl(exe), capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败：\n%s\n%s" % (r.stdout, r.stderr))


def compare(exe, probe, src, lut, lut_path, strength, interp, tmp):
    dst = os.path.join(tmp, "out.png")
    if os.path.exists(dst):
        os.remove(dst)
    render(dst, probe, lut_path, strength, interp, exe)
    w, h, got = read_png(dst)
    w0, h0, get = src
    assert (w, h) == (w0, h0)

    diffs = []
    for y in range(h):
        for x in range(w):
            p = get(x, y)
            q = got(x, y)
            ref = reference([p[i] / 255.0 for i in range(3)], lut, strength, interp)
            diffs.append(max(abs(ref[i] * 255.0 - q[i]) for i in range(3)))
    diffs.sort()
    return diffs[-1], diffs[int(len(diffs) * 0.95)], diffs[len(diffs) // 2]


def main():
    exe = find_gegl()
    tmp = tempfile.mkdtemp(prefix="clchk")
    probe = os.path.join(tmp, "probe.png")
    make_probe(probe)
    src = read_png(probe)
    w, h, _ = src

    luts = build_luts(tmp)
    for path in sys.argv[1:]:
        luts.append((os.path.basename(path), path, "命令行指定"))

    print("%-12s %-11s %5s %8s %7s %7s  %s" %
          ("LUT", "插值", "强度", "最大差", "95%", "中位", "说明"))
    worst = 0.0
    for name, path, note in luts:
        n1, lut1, n3, lut3 = parse_cube(path)
        lut = (n1, lut1, n3, lut3)
        for interp in ("trilinear", "tetrahedral"):
            for strength in (1.0, 0.5, 0.0):
                mx, p95, med = compare(exe, probe, src, lut, path,
                                       strength, interp, tmp)
                worst = max(worst, mx)
                print("%-12s %-11s %5.2f %8.2f %7.2f %7.2f  %s" %
                      (name, interp, strength, mx, p95, med, note))

    print("\n最大差 %.2f 码（0.03 码 ≈ 1 个 16 位 LSB）" % worst)
    return 0 if worst <= 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
