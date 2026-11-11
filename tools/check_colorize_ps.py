# -*- coding: utf-8 -*-
"""验收 lb:colorize-hsl：用 gegl CLI 渲染标定图，与 PS 实测的着色输出逐像素比对。

参考图来自 ../colorize-cal/out1（结构探测 15 组）与 out2（密集扫描 89 组）。

    python tools/check_colorize_ps.py          # 默认全部
    python tools/check_colorize_ps.py 30       # 均匀抽 30 组

报告单通道最大绝对偏差，单位是 8 位码（输出 0…255 刻度）。
标定残差本身是 0.03 码（16 位量化），所以「最大偏差 ≤1 码」即视为通过。
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAL = os.path.join(os.path.dirname(ROOT), "colorize-cal")
PROBE = os.path.join(CAL, "col-probe.png")

sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "bc-cal"))
from readpng import read_png              # 16 位按 v/257 浮点读，不能用 tools/contact_sheet
                                          # 里的 v*255//65535（整数下取整，会凭空造 1 码误差）

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GIMP 3", "bin", "gegl.exe"),
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]

PAT = re.compile(r'^h(-?\d+)_s(\d+)_l([+-]\d+)\.png$')


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


def render(exe, env, h, s, l, dst):
    cmd = [exe, PROBE, "-o", dst, "--", "lb:colorize-hsl",
           "hue=%g" % h, "saturation=%g" % s, "lightness=%g" % l]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 h=%g s=%g l=%g\n%s\n%s"
                         % (h, s, l, r.stdout, r.stderr))


def stats(ref, got):
    w, h, ga = ref
    w2, h2, gb = got
    assert (w, h) == (w2, h2), "尺寸不一致"
    diffs, worst = [], None
    for y in range(h):
        for x in range(w):
            pa, pb = ga(x, y), gb(x, y)
            d = max(abs(pa[i] - pb[i]) for i in range(3))
            diffs.append(d)
            if worst is None or d > worst[0]:
                worst = (d, x, y, tuple(round(v) for v in pa), tuple(round(v) for v in pb))
    diffs.sort()
    n = len(diffs)
    return (diffs[n // 2], diffs[int(n * 0.95)], diffs[-1],
            100.0 * sum(1 for d in diffs if d > 0.6) / n, worst)


def collect(dirs, limit=None):
    out = []
    for d in dirs:
        p = os.path.join(CAL, d)
        if not os.path.isdir(p):
            continue
        for nm in sorted(os.listdir(p)):
            m = PAT.match(nm)
            if m:
                out.append((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            os.path.join(p, nm)))
    if limit and len(out) > limit:
        step = len(out) / float(limit)
        out = [out[int(i * step)] for i in range(limit)]
    return out


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    exe = find_gegl()
    env = gegl_env(exe)
    print("· gegl: %s" % exe)

    items = collect(['out1', 'out2'], limit)
    print("· 参考图 %d 组（out1 结构探测 + out2 密集扫描）\n" % len(items))

    tmp = tempfile.mkdtemp(prefix="colps-")
    rows = []
    for h, s, l, path in items:
        dst = os.path.join(tmp, "o.png")
        render(exe, env, h, s, l, dst)
        med, p95, mx, pct, worst = stats(read_png(path), read_png(dst))
        rows.append((mx, med, p95, pct, h, s, l, worst))

    rows.sort(reverse=True)
    meds = sorted(r[1] for r in rows)
    print("== %d 组：最大偏差 %.2f 码；中位偏差的中位数 %.3f 码；95%% 偏差的中位数 %.3f 码"
          % (len(rows), rows[0][0], meds[len(meds) // 2],
             sorted(r[2] for r in rows)[len(rows) // 2]))
    print("\n最差的 8 组：")
    for mx, med, p95, pct, h, s, l, worst in rows[:8]:
        print("   h=%+4d s=%3d l=%+4d   最大 %6.2f  95%% %5.2f  中位 %5.2f  有差异 %4.1f%%"
              % (h, s, l, mx, p95, med, pct))
        if worst and worst[0] > 1.0:
            print("        在 (%d,%d) PS=%s  GEGL=%s" % (worst[1], worst[2], worst[3], worst[4]))

    bad = [r for r in rows if r[0] > 1.0]
    print("\n判定：%s" % ("通过（全部 ≤1 码）" if not bad else
                        "未通过，%d 组超过 1 码" % len(bad)))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
