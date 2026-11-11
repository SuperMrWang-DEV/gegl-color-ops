# -*- coding: utf-8 -*-
"""细探针验收 lb:color-balance：与 PS 在全部整数档上的实测逐像素比对。

cb-probe2.png 是 1024 px 的连续 16 位斜坡，每一档都能看清 0.25 码的细节；
参考图来自 ../cb-cal/out6（三个区间各 -100…100 每一档）与 out5（组合档）。

  python tools/check_color_balance_fine.py            # 抽样（每 10 档 + 全部组合）
  python tools/check_color_balance_fine.py --all      # 全部 609 档（约 10 分钟）
  python tools/check_color_balance_fine.py 25         # 每 25 档抽一档
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAL = os.path.join(os.path.dirname(ROOT), "cb-cal")
PROBE = os.path.join(CAL, "cb-probe2.png")

sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "bc-cal"))
from readpng import read_png            # 16 位按 v/257 浮点读

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]

COMBOS = {
    "c_sm100":  (100, 100, 0), "c_mh100": (0, 100, 100), "c_sh100": (100, 0, 100),
    "c_all100": (100, 100, 100), "c_all50": (50, 50, 50),
    "c_mix1":   (-60, 40, 20), "c_mix2": (40, -60, -20),
    "c_mix3":   (-100, 0, 100), "c_mix4": (100, 0, -100),
}


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


def render(exe, env, shd, mid, hlt, dst):
    cmd = [exe, PROBE, "-o", dst, "--", "lb:color-balance",
           "shadow-cr=%g" % shd, "midtone-cr=%g" % mid, "highlight-cr=%g" % hlt]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败：\n%s\n%s" % (r.stdout, r.stderr))


def stats(ref, got):
    w, h, ga = ref
    w2, h2, gb = got
    assert (w, h) == (w2, h2), "尺寸不一致"
    diffs = []
    worst = None
    for y in range(h):
        for x in range(w):
            pa, pb = ga(x, y), gb(x, y)
            d = max(abs(pa[i] - pb[i]) for i in range(3))
            diffs.append(d)
            if worst is None or d > worst[0]:
                worst = (d, x, y, tuple(round(v, 1) for v in pa),
                         tuple(round(v, 1) for v in pb))
    diffs.sort()
    n = len(diffs)
    return diffs[n // 2], diffs[int(n * .95)], diffs[-1], worst


def main():
    step = 10
    if len(sys.argv) > 1:
        if sys.argv[1] == "--all":
            step = 1
        else:
            step = int(sys.argv[1])

    exe = find_gegl()
    env = gegl_env(exe)
    print("· gegl: %s" % exe)
    print("· 探针: %s" % PROBE)

    groups = {"shd": [], "mid": [], "hlt": [], "combo": []}
    tmp = tempfile.mkdtemp()
    dst = os.path.join(tmp, "o.png")

    for rng in ("shd", "mid", "hlt"):
        for s in range(-100, 101, step):
            if s == 0:
                continue
            ref = os.path.join(CAL, "out6", "%s%d.png" % (rng, s))
            if not os.path.exists(ref):
                continue
            render(exe, env,
                   s if rng == "shd" else 0,
                   s if rng == "mid" else 0,
                   s if rng == "hlt" else 0, dst)
            med, p95, mx, worst = stats(read_png(ref), read_png(dst))
            groups[rng].append((mx, "%s%+d" % (rng, s), med, p95, worst))
            if os.path.exists(dst):
                os.remove(dst)

    for name, (s, m, h) in COMBOS.items():
        ref = os.path.join(CAL, "out5", name + ".png")
        if not os.path.exists(ref):
            continue
        render(exe, env, s, m, h, dst)
        med, p95, mx, worst = stats(read_png(ref), read_png(dst))
        groups["combo"].append((mx, name, med, p95, worst))
        if os.path.exists(dst):
            os.remove(dst)

    print()
    ok = True
    for g, rows in groups.items():
        if not rows:
            continue
        rows.sort(key=lambda r: -r[0])
        med = sorted(r[2] for r in rows)[len(rows) // 2]
        print("== %s ==  %d 组：最大 %.2f 码（%s），中位偏差 %.2f 码"
              % (g, len(rows), rows[0][0], rows[0][1], med))
        for mx, name, m2, p95, worst in rows[:3]:
            print("   %-10s 最大 %5.2f  95%% %5.2f  中位 %5.2f   @(%d,%d) PS %s / GEGL %s"
                  % (name, mx, p95, m2, worst[1], worst[2], worst[3], worst[4]))
        if rows[0][0] > 1.5:
            ok = False
    print("\n结论：%s" % ("全部在 1.5 码以内" if ok else "存在超过 1.5 码的档位"))


if __name__ == "__main__":
    main()
