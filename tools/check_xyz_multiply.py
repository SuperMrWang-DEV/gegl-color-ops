#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lb:xyz-multiply（即 经典图像编辑器 照片滤镜）数值验收：与独立写的 Python 实现逐像素比对。

参考实现照着头注释的算法直写（sRGB → D65 XYZ → 标准 Bradford 转到目标白点 →
逐通道乘 → 转回 → sRGB → 可选 SetLum），刻意不采用算子内部「折叠成一个 3×3
矩阵」的写法，这样既能验证矩阵折叠没算错，也能挡住以后改 LUT 引入的漂移。

与 经典图像编辑器 本身的端到端比对见 tools/check_photo_filter.py。

用法：
    python tools/check_xyz_multiply.py            # 8 组参数
    python tools/check_xyz_multiply.py --all      # 白点 × 颜色 × 不透明度 × 保留明度
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.dirname(ROOT)          # 工作区根，标定脚本在 <工作区>/bc-cal
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

WP = {"d50": (0.96422, 1.0, 0.82521), "d55": (0.95682, 1.0, 0.92149),
      "d65": (0.95047, 1.0, 1.08883), "d75": (0.94972, 1.0, 1.22638)}
W65 = WP["d65"]

M_S2X = [[0.4124564, 0.3575761, 0.1804375],
         [0.2126729, 0.7151522, 0.0721750],
         [0.0193339, 0.1191920, 0.9503041]]
M_X2S = [[3.2404542, -1.5371385, -0.4985314],
         [-0.9692660, 1.8760108, 0.0415560],
         [0.0556434, -0.2040259, 1.0572252]]
BRADFORD_CONE = [[0.8951, 0.2664, -0.1614],
                 [-0.7502, 1.7135, 0.0367],
                 [0.0389, -0.0685, 1.0296]]
BRADFORD_CONE_INV = [[0.9869929, -0.1470543, 0.1599627],
                     [0.4323053, 0.5183603, 0.0492912],
                     [-0.0085287, 0.0400428, 0.9684867]]


def mv(m, v):
    return [m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3)]


def mm(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def ung(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def gam(v):
    v = min(1.0, max(0.0, v))
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1.0 / 2.4) - 0.055


def bradford(src_wp, dst_wp):
    """标准 Bradford：B⁻¹ · diag(ρ_dst/ρ_src) · B，ρ = B·W（B 是锥响应矩阵）"""
    cs = mv(BRADFORD_CONE, src_wp)
    cd = mv(BRADFORD_CONE, dst_wp)
    s = [cd[i] / cs[i] for i in range(3)]
    d = [[s[i] if i == j else 0.0 for j in range(3)] for i in range(3)]
    return mm(BRADFORD_CONE_INV, mm(d, BRADFORD_CONE))


def set_lum(c, l):
    """W3C Luminosity：SetLum + ClipColor，刻度 0…1，权重 Rec.601"""
    def lum(v):
        return 0.3 * v[0] + 0.59 * v[1] + 0.11 * v[2]

    d = l - lum(c)
    c = [v + d for v in c]
    n, x = min(c), max(c)
    if n < 0.0 and (l - n):
        c = [l + (v - l) * l / (l - n) for v in c]
    if x > 1.0 and (x - l):
        c = [l + (v - l) * (1.0 - l) / (x - l) for v in c]
    return c


def reference(rgb, wp_name, overlay, alpha, preserve=True):
    wp = WP[wp_name]
    a = bradford(W65, wp)
    ai = bradford(wp, W65)
    o = mv(a, mv(M_S2X, [ung(c) for c in overlay]))
    v = mv(a, mv(M_S2X, [ung(c) for c in rgb]))
    m = [v[i] * ((1.0 - alpha) + alpha * o[i] / wp[i]) for i in range(3)]
    out = [gam(c) for c in mv(M_X2S, mv(ai, m))]
    if preserve:
        out = set_lum(out, 0.3 * rgb[0] + 0.59 * rgb[1] + 0.11 * rgb[2])
    return out


CASES = [
    ("d50", (1.0, 1.0, 1.0), 1.0, True),
    ("d50", (1.0, 0.0, 0.0), 1.0, False),
    ("d50", (1.0, 0.0, 0.0), 1.0, True),
    ("d50", (0.8, 0.7, 0.55), 0.5, True),
    ("d65", (0.2, 0.9, 0.4), 0.35, False),
    ("d75", (0.9, 0.5, 0.2), 1.0, True),
    ("d55", (0.5, 0.5, 0.5), 0.7, False),
    ("d65", (0.05, 0.02, 0.9), 0.0, True),
]
ALL_CASES = [(w, c, a, p) for w in ("d50", "d55", "d65", "d75")
             for c in ((1.0, 1.0, 1.0), (0.8, 0.7, 0.55), (0.15, 0.6, 0.95))
             for a in (1.0, 0.5, 0.0) for p in (True, False)]


def find_gegl():
    for c in GEGL_CANDIDATES:
        if c and (os.path.exists(c) or c == "gegl"):
            return c
    raise SystemExit("找不到 gegl 可执行文件，用 GEGL_BIN=... 指定")


def env_for_gegl(exe):
    """GEGL 只认一个 GEGL_PATH：插件目录必须带上 GIMP 自带的 core 算子目录，
    否则连 gegl:nop 都加载不到（Windows 上表现为 segfault），见 tools/smoke.sh。
    """
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


def render(dst, wp, overlay, alpha, preserve, probe):
    exe = find_gegl()
    cmd = [exe, probe, "-o", dst, "--", "lb:xyz-multiply",
           "white-mode=%s" % wp,
           "overlay-color=rgba(%.3f,%.3f,%.3f,1.0)" % overlay,
           "opacity=%g" % alpha,
           "preserve-luminosity=%s" % ("true" if preserve else "false")]
    r = subprocess.run(cmd, env=env_for_gegl(exe), capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败：\n%s\n%s" % (r.stdout, r.stderr))


def make_probe(dst):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from contact_sheet import write_png
    w = h = 64
    rows = []
    for y in range(h):
        rows.append([v for x in range(w)
                     for v in ((x * 4 + 2) & 0xFF, (y * 4 + 2) & 0xFF,
                               ((x + y) * 2 + 1) & 0xFF)])
    write_png(dst, w, h, rows)


def main():
    cases = ALL_CASES if "--all" in sys.argv else CASES
    tmp = tempfile.mkdtemp(prefix="xyzchk")
    probe = os.path.join(tmp, "probe.png")
    make_probe(probe)

    w, h, get = read_png(probe)

    print("%-5s %-20s %5s %4s %8s %8s %8s" %
          ("白点", "滤镜色", "密度", "保明", "最大差", "95%", "中位"))
    worst_all = 0.0
    for wp, overlay, alpha, preserve in cases:
        dst = os.path.join(tmp, "o.png")
        if os.path.exists(dst):
            os.remove(dst)
        render(dst, wp, overlay, alpha, preserve, probe)
        w2, h2, got = read_png(dst)
        assert (w, h) == (w2, h2), "尺寸不一致"

        diffs = []
        for y in range(h):
            for x in range(w):
                p = get(x, y)
                q = got(x, y)
                ref = reference([p[i] / 255.0 for i in range(3)], wp, overlay, alpha, preserve)
                diffs.append(max(abs(ref[i] * 255.0 - q[i]) for i in range(3)))
        diffs.sort()
        mx = diffs[-1]
        worst_all = max(worst_all, mx)
        print("%-5s %-20s %5.2f %4s %8.2f %8.2f %8.2f" %
              (wp, "(%.2f,%.2f,%.2f)" % overlay, alpha, "是" if preserve else "否",
               mx, diffs[int(len(diffs) * 0.95)], diffs[len(diffs) // 2]))

    print("\n最大差 %.2f 码（0.03 码 ≈ 1 个 16 位 LSB）" % worst_all)
    return 0 if worst_all <= 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
