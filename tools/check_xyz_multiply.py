#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lb:xyz-multiply 数值验收：与一份独立写的 Python 实现逐像素比对。

参考实现照着头注释里的算法直写（sRGB → D65 XYZ → 目标白点 → 正片叠底 →
回 D65 → sRGB），刻意不采用算子内部「折叠成一个 3×3 矩阵」的写法，这样
既能验证矩阵折叠没算错，也能挡住以后改 LUT 引入的漂移。

用法：
    python tools/check_xyz_multiply.py            # 6 组参数
    python tools/check_xyz_multiply.py --all      # 加白点 × 不透明度全组合
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
B = [[1.0478112, 0.0228866, -0.0501270],
     [0.0295424, 0.9904844, -0.0170491],
     [-0.0092345, 0.0150436, 0.7521316]]
BINV = [[0.9555766, -0.0230393, 0.0631636],
        [-0.0282895, 1.0099416, 0.0210077],
        [0.0122982, -0.0204830, 1.3299098]]


def mv(m, v):
    return [m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3)]


def ung(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def gam(v):
    v = min(1.0, max(0.0, v))
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1.0 / 2.4) - 0.055


def d65_to_wp(xyz, wp):
    s = [xyz[i] / W65[i] for i in range(3)]
    t = [wp[i] / W65[i] for i in range(3)]
    s = mv(B, s)
    s = [s[i] * t[i] for i in range(3)]
    return mv(BINV, s)


def wp_to_d65(xyz, wp):
    s = [xyz[i] / wp[i] for i in range(3)]
    t = [W65[i] / wp[i] for i in range(3)]
    s = mv(B, s)
    s = [s[i] * t[i] for i in range(3)]
    return mv(BINV, s)


def reference(rgb, wp_name, overlay, alpha):
    wp = WP[wp_name]
    o = d65_to_wp(mv(M_S2X, [ung(c) for c in overlay]), wp)
    b = d65_to_wp(mv(M_S2X, [ung(c) for c in rgb]), wp)
    m = [b[i] * ((1.0 - alpha) + alpha * o[i] / wp[i]) for i in range(3)]
    lin = mv(M_X2S, wp_to_d65(m, wp))
    return [gam(c) for c in lin]


CASES = [
    ("d65", (1.0, 1.0, 1.0), 1.0),
    ("d50", (0.8, 0.7, 0.55), 1.0),
    ("d65", (0.2, 0.9, 0.4), 0.35),
    ("d75", (0.9, 0.5, 0.2), 1.0),
    ("d55", (0.5, 0.5, 0.5), 0.7),
    ("d50", (0.05, 0.02, 0.9), 0.0),
]
ALL_CASES = [(w, c, a) for w in ("d50", "d55", "d65", "d75")
             for c in ((1.0, 1.0, 1.0), (0.8, 0.7, 0.55), (0.15, 0.6, 0.95))
             for a in (1.0, 0.5, 0.0)]


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


def render(dst, wp, overlay, alpha, probe):
    exe = find_gegl()
    cmd = [exe, probe, "-o", dst, "--", "lb:xyz-multiply",
           "white-mode=%s" % wp,
           "overlay-color=rgba(%.3f,%.3f,%.3f,1.0)" % overlay,
           "opacity=%g" % alpha]
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

    src = read_png(probe)
    w, h, get = src

    print("%-6s %-20s %5s %8s %8s %8s" %
          ("白点", "叠加色", "不透明", "最大差", "95%", "中位"))
    worst_all = 0.0
    for wp, overlay, alpha in cases:
        dst = os.path.join(tmp, "o.png")
        if os.path.exists(dst):
            os.remove(dst)
        render(dst, wp, overlay, alpha, probe)
        w2, h2, got = read_png(dst)
        assert (w, h) == (w2, h2), "尺寸不一致"

        diffs = []
        for y in range(h):
            for x in range(w):
                p = get(x, y)
                q = got(x, y)
                ref = reference([p[i] / 255.0 for i in range(3)], wp, overlay, alpha)
                diffs.append(max(abs(ref[i] * 255.0 - q[i]) for i in range(3)))
        diffs.sort()
        mx = diffs[-1]
        worst_all = max(worst_all, mx)
        print("%-6s %-20s %5.2f %8.2f %8.2f %8.2f" %
              (wp, "(%.2f,%.2f,%.2f)" % overlay, alpha,
               mx, diffs[int(len(diffs) * 0.95)], diffs[len(diffs) // 2]))

    print("\n最大差 %.2f 码（0.03 码 ≈ 1 个 16 位 LSB）" % worst_all)
    return 0 if worst_all <= 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
