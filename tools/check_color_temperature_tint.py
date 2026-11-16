# -*- coding: utf-8 -*-
"""验收 lb:color-temperature-tint：用 gegl CLI 渲染全色域探针，与 经典图像编辑器 2026 的
真实导出逐色块比对。

    python tools/check_color_temperature_tint.py            # 跑默认几组
    python tools/check_color_temperature_tint.py 60 -40 25 25   # 指定 (色温,色调) 对

依赖：GIMP 自带的 gegl.exe（自动查找）+ 已安装的算子（./install.sh）。
参考图在 ../vibrance-cal/out2026/g_t±NNN_n±NNN.png（经典图像编辑器 2026 导出）。
标定数据不在仓库里时（CI 环境）自动跳过，退出码 0。

比对的是 32³ = 32768 个色块的**块中心**，不是全图像素：探针就是按色块造的，
块中心才是纯色；经典图像编辑器 侧任何通道 ≥249 的样本直接跳过 —— 那边已经削平，
比不出东西，硬算只会把统计拉偏。
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAL = os.path.join(os.path.dirname(ROOT), "vibrance-cal")
PROBE = os.path.join(CAL, "allprobe.png")
N, CELL, COLS = 32, 8, 128

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
        if c and os.path.exists(c):
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


def render(exe, env, t, n, dst):
    cmd = [exe, PROBE, "-o", dst, "--", "lb:color-temperature-tint",
           "temperature=%g" % t, "tint=%g" % n]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 (%g,%g)\n%s\n%s" % (t, n, r.stdout, r.stderr))


def stats(ref, got):
    w, h, A = ref
    w2, h2, B = got
    assert (w, h) == (w2, h2), "尺寸不一致"
    diffs = []
    for i in range(N * N * N):
        x = (i % COLS) * CELL + CELL // 2
        y = (i // COLS) * CELL + CELL // 2
        pa, pb = A[y][x], B[y][x]
        if max(pa) >= 249:
            continue
        diffs.append(max(abs(pa[k] - pb[k]) for k in range(3)))
    diffs.sort()
    if not diffs:
        return None
    m = len(diffs)
    return (diffs[m // 2], diffs[int(m * 0.9)], diffs[int(m * 0.99)], diffs[-1],
            100.0 * sum(1 for d in diffs if d > 6) / m, m)


def main():
    args = sys.argv[1:]
    if args:
        pairs = [(float(args[i]), float(args[i + 1])) for i in range(0, len(args) - 1, 2)]
    else:
        pairs = [(0, 0), (25, 0), (-25, 0), (0, 25), (0, -25),
                 (60, 60), (30, -40), (-45, 30), (-38, -62)]

    if not os.path.exists(PROBE):
        print("· 没有标定探针 %s，跳过（CI 环境正常）" % os.path.basename(PROBE))
        return 0

    exe = find_gegl()
    env = gegl_env(exe)
    print("· gegl: %s" % exe)
    tmp = tempfile.mkdtemp(prefix="ttps-")
    print("%9s %9s %6s %6s %6s %6s %8s"
          % ("色温", "色调", "中位", "p90", "p99", "最大", ">6码"))
    bad = 0
    for t, n in pairs:
        ref_path = os.path.join(CAL, "out2026", "g_t%+04d_n%+04d.png" % (t, n))
        if not os.path.exists(ref_path):
            print("%9g %9g  （缺少 经典图像编辑器 参考 %s，跳过）" % (t, n, os.path.basename(ref_path)))
            continue
        dst = os.path.join(tmp, "t%+d_n%+d.png" % (int(t), int(n)))
        render(exe, env, t, n, dst)
        s = stats(read_png(ref_path), read_png(dst))
        if not s:
            print("%9g %9g  （没有可比样本）" % (t, n))
            continue
        med, p90, p99, mx, over, cnt = s
        print("%9g %9g %6.1f %6.1f %6.1f %6.1f %7.1f%%  n=%d"
              % (t, n, med, p90, p99, mx, over, cnt))
        if med > 6:
            bad += 1

    print("\n小结：中位偏差 >6 码的档位 %d 个" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
