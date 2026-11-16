# -*- coding: utf-8 -*-
"""验收 lb:color-balance：gegl CLI 渲染标定图，与 经典图像编辑器 实测逐像素比对。

参考图来自 ../cb-cal/out1（结构探测）与 out2（步长扫描 + 组合 + 保留明度）。
误差单位是 8 位码。分组统计，因为两类模式的性质完全不同：

  single   单区间单独给值（原版路径的主战场）
  combo    两三区间同时给值（考复合顺序）
  preserve 保留明度（MATLAB 路径）

    python tools/check_color_balance_ps.py
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAL = os.path.join(os.path.dirname(ROOT), "cb-cal")
PROBE = os.path.join(CAL, "cb-probe.png")

sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "bc-cal"))
from readpng import read_png            # 16 位按 v/257 浮点读

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]


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


def parse(name):
    """文件名 → (shd, mid, hlt, preserve, 分组)。返回 None 表示不认识的档位。"""
    m = {'cr': 0, 'mg': 1, 'yb': 2}
    base = name[:-4]
    prs = base.endswith('_p')
    if prs:
        base = base[:-2]

    # out1 的写法
    mm = re.match(r'^(mid|shd|hlt)_(cr|mg|yb)([+-]\d+)$', base)
    if mm:
        rng, ax, val = mm.group(1), mm.group(2), int(mm.group(3))
        t = [0, 0, 0]
        t[m[ax]] = val
        s = t if rng == 'shd' else [0, 0, 0]
        midt = t if rng == 'mid' else [0, 0, 0]
        h = t if rng == 'hlt' else [0, 0, 0]
        return (s, midt, h, prs, 'preserve' if prs else 'single')
    if re.match(r'^all_cr[+-]\d+$', base):
        v = int(re.search(r'([+-]\d+)$', base).group(1))
        return ([v, 0, 0], [v, 0, 0], [v, 0, 0], prs,
                'preserve' if prs else 'combo')

    # out2 的写法
    mm = re.match(r'^(mid|shd|hlt)([+-])(cr|mg|yb)(\d+)$', base)
    if mm:
        rng, sign, ax, mag = mm.group(1), mm.group(2), mm.group(3), int(mm.group(4))
        v = mag if sign == '+' else -mag
        t = [0, 0, 0]
        t[m[ax]] = v
        s = t if rng == 'shd' else [0, 0, 0]
        midt = t if rng == 'mid' else [0, 0, 0]
        h = t if rng == 'hlt' else [0, 0, 0]
        return (s, midt, h, prs, 'preserve' if prs else 'single')

    if base == 'combo_sm':
        return ([100, 0, 0], [100, 0, 0], [0, 0, 0], prs, 'combo')
    if base == 'combo_mh':
        return ([0, 0, 0], [100, 0, 0], [100, 0, 0], prs, 'combo')
    if base == 'combo_sh':
        return ([100, 0, 0], [0, 0, 0], [100, 0, 0], prs, 'combo')
    if base == 'combo_all50':
        return ([50, 0, 0], [50, 0, 0], [50, 0, 0], prs, 'combo')
    if base == 'combo_all100':
        return ([100, 0, 0], [100, 0, 0], [100, 0, 0], prs, 'combo')
    return None


def render(exe, env, s, m, h, prs, dst):
    cmd = [exe, PROBE, "-o", dst, "--", "lb:color-balance",
           "shadow-cr=%g" % s[0], "shadow-mg=%g" % s[1], "shadow-yb=%g" % s[2],
           "midtone-cr=%g" % m[0], "midtone-mg=%g" % m[1], "midtone-yb=%g" % m[2],
           "highlight-cr=%g" % h[0], "highlight-mg=%g" % h[1], "highlight-yb=%g" % h[2],
           "preserve-luminosity=%s" % ("true" if prs else "false")]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 %s\n%s\n%s" % (cmd[:2], r.stdout, r.stderr))


def stats(ref, got):
    w, h, ga = ref
    w2, h2, gb = got
    assert (w, h) == (w2, h2)
    diffs = []
    worst = None
    for y in range(h):
        for x in range(w):
            pa, pb = ga(x, y), gb(x, y)
            d = max(abs(pa[i] - pb[i]) for i in range(3))
            diffs.append(d)
            if worst is None or d > worst[0]:
                worst = (d, x, y, tuple(round(v) for v in pa), tuple(round(v) for v in pb))
    diffs.sort()
    n = len(diffs)
    return diffs[n // 2], diffs[int(n * .95)], diffs[-1], worst


def main():
    exe = find_gegl()
    env = gegl_env(exe)
    print("· gegl: %s" % exe)

    items = []
    for d in ('out1', 'out2'):
        p = os.path.join(CAL, d)
        if not os.path.isdir(p):
            continue
        for nm in sorted(os.listdir(p)):
            if not nm.endswith('.png'):
                continue
            info = parse(nm)
            if info:
                items.append(info + (os.path.join(p, nm),))
    print("· 参考图 %d 组\n" % len(items))

    tmp = tempfile.mkdtemp(prefix="cbps-")
    groups = {}
    for s, m, h, prs, grp, path in items:
        dst = os.path.join(tmp, "o.png")
        render(exe, env, s, m, h, prs, dst)
        med, p95, mx, worst = stats(read_png(path), read_png(dst))
        groups.setdefault(grp, []).append((mx, med, p95, os.path.basename(path), worst))

    for grp in ('single', 'combo', 'preserve'):
        rows = groups.get(grp, [])
        if not rows:
            continue
        rows.sort(reverse=True)
        meds = sorted(r[1] for r in rows)
        print("== %s ==  %d 组：最大偏差 %.1f 码，中位偏差的中位数 %.2f 码"
              % (grp, len(rows), rows[0][0], meds[len(meds) // 2]))
        for mx, med, p95, nm, worst in rows[:5]:
            print("   %-18s 最大 %6.1f  95%% %6.1f  中位 %5.1f" % (nm, mx, p95, med))
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
