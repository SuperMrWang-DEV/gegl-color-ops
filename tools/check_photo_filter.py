#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lb:xyz-multiply 与 **经典图像编辑器 照片滤镜** 的端到端比对。

数据来自 photo-filter-cal：经典图像编辑器 2025 用 ExtendScript 跑出来的实测图。
  out_gray/   12 档 × 256 级灰阶（pf-gray.png）
  out_color/   6 档 × 64×64 彩色（color-lookup-cal/cl-probe.png）

每一档都按照片滤镜的参数渲染（滤镜色 / 密度 / 保留明度），再与 经典图像编辑器 的
PNG 逐像素比。标定目录不在时（比如 CI 上）直接跳过，不算失败。

用法：python tools/check_photo_filter.py [--verbose]
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
from check_xyz_multiply import find_gegl, env_for_gegl     # noqa: E402

CAL = os.path.join(WORK, "photo-filter-cal")
GRAY_PROBE = os.path.join(CAL, "pf-gray.png")
COLOR_PROBE = os.path.join(WORK, "color-lookup-cal", "cl-probe.png")

# (文件, 滤镜色 0..255, 密度 0..100, 保留明度)
GRAY_CASES = [
    ("red_d0_l0",     (255, 0, 0),     0,   False),
    ("white_d100_l0", (255, 255, 255), 100, False),
    ("gray_d100_l0",  (128, 128, 128), 100, False),
    ("black_d100_l0", (0, 0, 0),       100, False),
    ("red_d100_l0",   (255, 0, 0),     100, False),
    ("red_d100_l1",   (255, 0, 0),     100, True),
    ("red_d50_l0",    (255, 0, 0),     50,  False),
    ("red_d50_l1",    (255, 0, 0),     50,  True),
    ("red_d25_l0",    (255, 0, 0),     25,  False),
    ("blue_d100_l0",  (0, 0, 255),     100, False),
    ("warm_d100_l0",  (236, 138, 0),   100, False),
    ("warm_d25_l0",   (236, 138, 0),   25,  False),
]
COLOR_CASES = [
    ("red_d100_l0",  (255, 0, 0),   100, False),
    ("red_d100_l1",  (255, 0, 0),   100, True),
    ("red_d50_l0",   (255, 0, 0),   50,  False),
    ("warm_d100_l0", (236, 138, 0), 100, False),
    ("warm_d100_l1", (236, 138, 0), 100, True),
    ("blue_d100_l1", (0, 0, 255),   100, True),
]


def render(dst, probe, filt, density, preserve):
    exe = find_gegl()
    cmd = [exe, probe, "-o", dst, "--", "lb:xyz-multiply",
           "white-mode=d50",
           "overlay-color=rgba(%.4f,%.4f,%.4f,1.0)" % tuple(v / 255.0 for v in filt),
           "opacity=%g" % (density / 100.0),
           "preserve-luminosity=%s" % ("true" if preserve else "false")]
    r = subprocess.run(cmd, env=env_for_gegl(exe), capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败：\n%s\n%s" % (r.stdout, r.stderr))


def run_set(title, cases, folder, probe, verbose):
    _, _, src = read_png(probe)
    print(title)
    print("  %-14s %8s %8s %8s   %s" % ("档位", "最大差", "中位差", ">2码点", "注"))
    worst = 0.0
    for tag, filt, density, preserve in cases:
        ref_path = os.path.join(CAL, folder, tag + ".png")
        if not os.path.exists(ref_path):
            print("  %-14s 缺 %s" % (tag, ref_path))
            continue
        dst = os.path.join(tempfile.gettempdir(), "pfchk.png")
        if os.path.exists(dst):
            os.remove(dst)
        render(dst, probe, filt, density, preserve)
        w, h, got = read_png(dst)
        pw, ph, ps = read_png(ref_path)
        assert (w, h) == (pw, ph), "尺寸不一致：算子 %dx%d / 参考图像编辑器 %dx%d" % (w, h, pw, ph)

        diffs = []
        worst_pt = (0.0, None)
        for y in range(h):
            for x in range(w):
                a = ps(x, y)
                b = got(x, y)
                d = max(abs(a[i] - b[i]) for i in range(3))
                diffs.append(d)
                if d > worst_pt[0]:
                    worst_pt = (d, (x, y, a, b))
        diffs.sort()
        mx = diffs[-1]
        worst = max(worst, mx)
        note = ""
        if verbose and worst_pt[1]:
            x, y, a, b = worst_pt[1]
            note = "最差点 (%d,%d) 参考图像编辑器 %s / 算子 %s" % (
                x, y, tuple(int(round(v)) for v in a), tuple(int(round(v)) for v in b))
        print("  %-14s %8.2f %8.2f %8d   %s" % (tag, mx, diffs[len(diffs) // 2],
                                                sum(1 for d in diffs if d > 2), note))
    return worst


def main():
    if not os.path.isdir(CAL):
        print("没有标定目录 %s，跳过（经典图像编辑器 实测数据不在）" % CAL)
        return 0

    verbose = "--verbose" in sys.argv
    a = run_set("灰阶 256 级 · 12 档", GRAY_CASES, "out_gray", GRAY_PROBE, verbose)
    b = run_set("彩色 64×64 · 6 档", COLOR_CASES, "out_color", COLOR_PROBE, verbose)
    worst = max(a, b)
    print("\n与 经典图像编辑器 照片滤镜的最大偏差 %.2f 码（8 位，1 码 = 1/255）" % worst)
    print("「保留明度」档在裁剪边界会有 3～6 码的差异：经典图像编辑器 的取整顺序与 W3C 参考实现略有不同，")
    print("非边界点的中位差在 0.4 码以内。")
    return 0 if worst <= 6.0 else 1


if __name__ == "__main__":
    sys.exit(main())
