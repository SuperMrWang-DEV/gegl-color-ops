# -*- coding: utf-8 -*-
"""验收 lb:rgb-domain-grayscale 的着色（Tint）模块：与 经典图像编辑器 实测逐像素比对。

参考图来自 ../bw-cal/out7：18 组 tint（8 个色相 × 2 档饱和度 + 暖棕默认 + 橄榄绿），
黑白六滑块全 0、只开着色，输入是 16 位中性灰阶探针。

    python tools/check_bw_tint_ps.py          # 默认全部
    python tools/check_bw_tint_ps.py 6        # 均匀抽 6 组

着色只对灰度值起作用，所以比对整条灰阶带（每档 32 行，取中间行）。
报告单通道最大绝对偏差，单位是 8 位码。标定残差本身是 0.10 码（16 位量化），
所以「最大偏差 ≤1 码」即视为通过。旧实现（gray×tint）在这里会全线爆表 ~58 码，
改坏了一眼就能看出来。
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAL = os.path.join(os.path.dirname(ROOT), "bw-cal")
PROBE = os.path.join(CAL, "bw-probe.png")
OUT = os.path.join(CAL, "out8")   # tint 已量化到 8bit，与 #RRGGBB 严格同值

sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "bc-cal"))
from readpng import read_png     # 16 位按 v/257 浮点读

LAYOUT = json.load(open(os.path.join(os.path.dirname(ROOT), "colorize-cal", "layout.json")))
GY = LAYOUT["bands"]["gray"]["y"] + 8

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GIMP 3", "bin", "gegl.exe"),
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]


def hsl2rgb(h, s, l):
    def f(n):
        k = (n + h * 12) % 12
        a = s * min(l, 1 - l)
        return l - a * max(-1, min(k - 3, 9 - k, 1))
    return [f(0), f(8), f(4)]


def cases():
    """与 bw-cal 探测脚本完全相同的 18 组 tint / same 18 tints as the probe."""
    out = []
    for hu in [0, 30, 60, 90, 120, 180, 240, 300]:
        for s in [25, 100]:
            out.append(("h%d_s%d" % (hu, s), hsl2rgb(hu / 360, s / 100, 0.5)))
    out += [("brown_def", [0.88, 0.83, 0.70]), ("olive", [0.2, 0.8, 0.4])]
    return out


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


def hexcol(tint):
    """四舍五入（非银行家舍入），与 PS 侧 q8/Math.round 一致。"""
    return "#" + "".join("%02X" % int(c * 255 + 0.5) for c in tint)


def render(exe, env, tint, dst):
    cmd = [exe, PROBE, "-o", dst, "--", "lb:rgb-domain-grayscale",
           "tint-enabled=true", "tint-color=%s" % hexcol(tint), "tint-strength=1"]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 %s\n%s\n%s" % (hexcol(tint), r.stdout, r.stderr))


def band_diffs(ref, got):
    """只比灰阶带的那一行 / compare the grey ramp row only."""
    _, h, ga = ref
    _, h2, gb = got
    assert h == h2, "高度不一致"
    diffs, worst = [], None
    for x in range(ref[0]):
        pa, pb = ga(x, GY), gb(x, GY)
        d = max(abs(pa[i] - pb[i]) for i in range(3))
        diffs.append(d)
        if worst is None or d > worst[0]:
            worst = (d, x, tuple(round(v) for v in pa), tuple(round(v) for v in pb))
    diffs.sort()
    n = len(diffs)
    return diffs[-1], diffs[n // 2], worst


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    exe = find_gegl()
    env = gegl_env(exe)
    print("· gegl: %s" % exe)

    items = [(n, t) for n, t in cases() if os.path.exists(os.path.join(OUT, n + ".png"))]
    if limit and len(items) > limit:
        step = len(items) / float(limit)
        items = [items[int(i * step)] for i in range(limit)]
    print("· 参考图 %d 组（bw-cal/out8，tint 已量化到 8bit）\n" % len(items))

    tmp = tempfile.mkdtemp(prefix="bwtint-")
    rows = []
    for name, tint in items:
        dst = os.path.join(tmp, "o.png")
        render(exe, env, tint, dst)
        mx, med, worst = band_diffs(read_png(os.path.join(OUT, name + ".png")), read_png(dst))
        rows.append((mx, med, name, tint, worst))

    rows.sort(reverse=True)
    print("== %d 组：最大偏差 %.2f 码" % (len(rows), rows[0][0]))
    print("\n全部：")
    for mx, med, name, tint, worst in rows:
        print("   %-11s tint=%s  最大 %6.2f  中位 %5.2f"
              % (name, hexcol(tint), mx, med))
        if worst and worst[0] > 1.0:
            print("        x=%d 参考图像编辑器=%s  GEGL=%s" % (worst[1], worst[2], worst[3]))

    bad = [r for r in rows if r[0] > 1.0]
    print("\n判定：%s" % ("通过（全部 ≤1 码）" if not bad else
                        "未通过，%d 组超过 1 码" % len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
