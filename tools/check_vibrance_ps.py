# -*- coding: utf-8 -*-
"""验收 lb:vibrance-ps：用 gegl CLI 渲染标定图，与 Photoshop 的真实输出逐像素比对。

    python tools/check_vibrance_ps.py            # 跑 ±60 / ±100 四档
    python tools/check_vibrance_ps.py 60 25 -40  # 指定档位

依赖：GIMP 自带的 gegl.exe（自动查找）+ 已安装的算子（./install.sh）。
PS 的输出图在 ../vibrance-cal/out/vib±N.png（8 位，原地导出）。
报告的是「单通道最大绝对偏差（0-255 码）」，量化本身就有 ±0.5 码，
所以理想结果是中位数 0-1、95 分位 ≤2。
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAL = os.path.join(os.path.dirname(ROOT), "vibrance-cal")
PROBE = os.path.join(CAL, "vibrance-probe.png")

sys.path.insert(0, HERE)
from contact_sheet import read_png            # noqa: E402

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GIMP 3", "bin", "gegl.exe"),
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]


def find_gegl():
    for c in GEGL_CANDIDATES:
        if os.path.exists(c):
            return c
    raise SystemExit("找不到 gegl 可执行文件，用 GEGL_BIN=... 指定")


def gegl_env(exe):
    """GEGL_PATH 需要同时含刚装的模块和 GIMP 自带算子，否则核心算子会缺失。"""
    env = dict(os.environ)
    lib = os.path.join(os.path.dirname(os.path.dirname(exe)), "lib", "gegl-0.4")
    if os.name == "nt":
        dest = os.path.join(os.environ.get("LOCALAPPDATA", ""), "gegl-0.4", "plug-ins")
        env["GEGL_PATH"] = dest + ";" + lib
    else:
        env["GEGL_PATH"] = os.path.expanduser("~/.local/share/gegl-0.4/plug-ins") + ":" + lib
    return env


def render(exe, env, v, dst):
    cmd = [exe, PROBE, "-o", dst, "--", "lb:vibrance-ps", "vibrance=%g" % v]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 v=%g\n%s\n%s" % (v, r.stdout, r.stderr))


def stats(v, a, b):
    """a 为参考（PS），b 为算子输出。返回整幅图上的误差分布。"""
    w, h, A = a
    w2, h2, B = b
    assert (w, h) == (w2, h2), "尺寸不一致"
    diffs, worst = [], None
    for y in range(h):
        for x in range(w):
            pa, pb = A[y][x], B[y][x]
            d = max(abs(pa[i] - pb[i]) for i in range(3))
            diffs.append(d)
            if d and (worst is None or d > worst[0]):
                worst = (d, x, y, pa, pb)
    diffs.sort()
    n = len(diffs)
    same = 100.0 * sum(1 for d in diffs if d == 0) / n
    return (diffs[n // 2], diffs[int(n * 0.95)], diffs[-1],
            sum(diffs) / n, same, worst)


def main():
    vals = [float(x) for x in sys.argv[1:]] or [0, 25, 60, 100, -25, -60, -100]
    exe = find_gegl()
    env = gegl_env(exe)
    print("· gegl: %s" % exe)

    src = read_png(PROBE)
    tmp = tempfile.mkdtemp(prefix="vibps-")
    print("%6s %6s %6s %6s %6s %8s  %s"
          % ("v", "中位", "95%", "最大", "平均", "完全一致", "最差点"))
    bad = 0
    for v in vals:
        dst = os.path.join(tmp, "v%+d.png" % int(v))
        render(exe, env, v, dst)
        got = read_png(dst)

        # v=0 就是恒等：和原图比，用来确认色彩管线没有偷偷改像素
        if int(v) == 0:
            ref = src
        else:
            ref_path = os.path.join(CAL, "out", "vib%+d.png" % int(v))
            if not os.path.exists(ref_path):
                print("%6d  （缺少 PS 参考 %s，跳过）" % (v, os.path.basename(ref_path)))
                continue
            ref = read_png(ref_path)

        med, p95, mx, avg, same, worst = stats(v, ref, got)
        note = ""
        if worst:
            note = "(%d,%d) PS%s 算子%s" % (worst[1], worst[2], worst[3], worst[4])
        print("%6d %6d %6d %6d %6.2f %7.1f%%  %s" % (v, med, p95, mx, avg, same, note))
        if mx > 3:
            bad += 1

    print("\n小结：最大偏差 >3 码的档位 %d 个" % bad)


if __name__ == "__main__":
    main()
