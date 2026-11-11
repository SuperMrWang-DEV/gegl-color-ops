# -*- coding: utf-8 -*-
"""验收 lb:brightness-contrast-ps：用 gegl CLI 渲染标定图，与 PS 实测输出逐像素比对。

参考图的三种来源：
  ../bc-cal/out2/  单参数扫描（b 或 c，步长 5，16 位）
  ../bc-cal/out3/  非 5 倍数档位（验证参数插值）
  ../bc-cal/out/   二维组合 b×c（验证「先 b 后 c」的复合顺序）

    python tools/check_bc_ps.py            # 默认抽样
    python tools/check_bc_ps.py all        # 全部参考图

PS 的 16 位导出换算成 0…255 浮点后比较，报告单通道最大绝对偏差（码）。
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAL = os.path.join(os.path.dirname(ROOT), "bc-cal")
PROBE = os.path.join(CAL, "bc-probe.png")

sys.path.insert(0, HERE)
from contact_sheet import read_png            # noqa: E402

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GIMP 3", "bin", "gegl.exe"),
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]

PAT = re.compile(r'^([nl])_b([+-]\d+)_c([+-]\d+)\.png$')


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


def render(exe, env, b, c, legacy, dst):
    cmd = [exe, PROBE, "-o", dst, "--", "lb:brightness-contrast-ps",
           "brightness=%g" % b, "contrast=%g" % c,
           "legacy=%s" % ("true" if legacy else "false")]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 b=%g c=%g legacy=%s\n%s\n%s"
                         % (b, c, legacy, r.stdout, r.stderr))


def stats(ref, got):
    w, h, A = ref
    w2, h2, B = got
    assert (w, h) == (w2, h2), "尺寸不一致"
    diffs = []
    worst = None
    for y in range(h):
        for x in range(w):
            pa, pb = A[y][x], B[y][x]
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
                out.append((m.group(1) == 'l', int(m.group(2)), int(m.group(3)),
                            os.path.join(p, nm)))
    if limit:
        # 均匀抽样
        n = len(out)
        if n > limit:
            step = n / float(limit)
            out = [out[int(i * step)] for i in range(limit)]
    return out


def main():
    args = sys.argv[1:]
    every = 1
    if args and args[0] == 'all':
        limit = None
        if len(args) > 1:
            every = int(args[1])
    else:
        limit = int(args[0]) if args else 60

    exe = find_gegl()
    env = gegl_env(exe)
    print("· gegl: %s" % exe)

    items = collect(['out2', 'out3', 'out'], limit)
    print("· 参考图 %d 张（out2 单参数 / out3 插值档位 / out 二维组合）\n" % len(items))

    tmp = tempfile.mkdtemp(prefix="bcps-")
    agg = {}
    for legacy, b, c, path in items:
        dst = os.path.join(tmp, "o.png")
        render(exe, env, b, c, legacy, dst)
        ref = read_png(path)
        got = read_png(dst)
        med, p95, mx, pct, worst = stats(ref, got)
        key = 'legacy' if legacy else 'modern'
        agg.setdefault(key, []).append((mx, med, p95, pct, b, c))

    # 打印最差的几组，避免刷屏
    for key in ('modern', 'legacy'):
        rows = sorted(agg.get(key, []), reverse=True)
        if not rows:
            continue
        meds = sorted(r[1] for r in rows)
        print("\n== %s ==  %d 组：整组最大偏差 %.1f 码，中位偏差的中位数 %.2f 码"
              % ('旧版 legacy' if key == 'legacy' else '新版 modern',
                 len(rows), rows[0][0], meds[len(meds) // 2]))
        for mx, med, p95, pct, b, c in rows[:6]:
            print("   b=%+5d c=%+5d   最大 %6.2f   95%% %5.2f   中位 %5.2f   有差异 %4.1f%%"
                  % (b, c, mx, p95, med, pct))


if __name__ == '__main__':
    main()
