#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收 lb:shadows-highlights：算子 vs 独立 Python 参考实现（平场）+ 经典图像编辑器 实测曲线。

四组检查，全部不需要 参考图像编辑器：

  1. 平场 LUT   算子渲染灰阶竖带，与这里直写的参考实现逐点比（1 码以内）
  2. 彩色平场   同上，但走颜色校正分支（色度不放大 / 收在色域内）
  3. 结构性质   amount=0 恒等、中间调支点 128、半径对平场无影响、修剪保留端点
  4. 经典图像编辑器 对照    若 ../shadows-highlights-cal/data/curve.csv 在，附带比一遍 经典图像编辑器 实测

参考实现照算子头注释的模型直写：遮罩 = 1 − 正则化不完全 Beta 的 CDF、曲线 = 自屏幕
1 − (1−v)^q、强度 = amount^0.6216 分段。刻意不复用 C 里的表，只共用 经典图像编辑器 拟合出来的
20×2 / 11×3 系数 —— 这样能挡住插值、量化、分支写错，也挡住以后改表引入的漂移。

    python tools/check_shadows_highlights.py          # 全部
    python tools/check_shadows_highlights.py --fast    # 跳过 经典图像编辑器 对照
"""
import os
import re
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.dirname(ROOT)
CAL = os.path.join(WORK, "shadows-highlights-cal")

sys.path.insert(0, os.path.join(WORK, "bc-cal"))
from readpng import read_png                      # noqa: E402

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GIMP 3", "bin", "gegl.exe"),
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]

# ---- 经典图像编辑器 拟合系数（与 shadows-highlights.c 中的表相同）/ fitted coefficients ----
BETA = [(1.9468, 22.9366), (1.7770, 18.3471), (1.6403, 14.7559), (1.5270, 11.9346),
        (1.4269, 9.6467), (1.3470, 7.8430), (1.2807, 6.4038), (1.2240, 5.2384),
        (1.1772, 4.2967), (1.1373, 3.5350), (1.1021, 2.9109), (1.0755, 2.4186),
        (1.0508, 2.0189), (1.0307, 1.7034), (1.0140, 1.4583), (1.0015, 1.2758),
        (1.0000, 1.1403), (1.0000, 1.0510), (1.0000, 1.0002), (1.0000, 1.0000)]
COLOR_UP = [(0, 0.0), (1, 0.1566), (2, 0.2271), (5, 0.3776), (10, 0.5653), (20, 0.8669),
            (30, 1.1299), (40, 1.3748), (50, 1.6093), (60, 1.8375), (75, 2.1721),
            (100, 2.7193)]
COLOR_DOWN = [(0, 0.0), (1, -0.0145), (5, -0.0709), (10, -0.1373), (20, -0.2570),
              (30, -0.3612), (50, -0.5312), (75, -0.6866), (100, -0.7968)]
MIDTONE = [(-100, -0.6955, 2.267), (-75, -0.5873, 2.362), (-50, -0.4429, 2.492),
           (-25, -0.2514, 2.667), (-10, -0.1088, 2.803), (0, 0.0000, 2.900),
           (10, 0.1206, 3.016), (25, 0.3262, 3.216), (50, 0.7423, 3.625),
           (75, 1.2635, 4.160), (100, 1.9032, 4.850)]



# ------------------------------------------------------------------ 写 PNG ---
def write_png(path, w, h, rows):
    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c))

    raw = b''.join(b'\x00' + bytes(r) for r in rows)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n'
                + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw, 6))
                + chunk(b'IEND', b''))


def bands(path, colours, band=96, height=40):
    """每种颜色一条竖带 / one vertical band per colour."""
    row = []
    for c in colours:
        row += list(c) * band
    write_png(path, len(colours) * band, height, [row] * height)
    return [i * band + band // 2 for i in range(len(colours))]


# -------------------------------------------------------------- 参考实现 ---
def interp1(tab, x):
    if x <= tab[0][0]:
        return tab[0][1]
    for (x0, y0), (x1, y1) in zip(tab, tab[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return tab[-1][1]


def mask_table(tone):
    t = min(max(tone, 0.0), 95.0) / 5.0
    i0 = min(int(t), 18)
    f = t - i0
    a = BETA[i0][0] + (BETA[i0 + 1][0] - BETA[i0][0]) * f
    b = BETA[i0][1] + (BETA[i0 + 1][1] - BETA[i0][1]) * f

    sub = 16
    dens = []
    for i in range(255 * sub):
        xs = (i + 0.5) / (255.0 * sub)
        dens.append((xs ** (a - 1.0)) * ((1.0 - xs) ** (b - 1.0)))
    total = sum(dens)

    out, cum = [1.0], 0.0
    for lv in range(1, 256):
        cum += sum(dens[(lv - 1) * sub:lv * sub])
        out.append(1.0 - cum / total)
    return out


def strength(amount):
    u = (min(max(amount, 0.0), 100.0) / 100.0) ** 0.6216
    return u / 0.3 if u <= 0.3 else (1.0 + 20.0 * u) / 7.0


def lift(s, v):
    n = min(max(int(s), 0), 2)
    t = min(max(s - n, 0.0), 1.0)
    lo = min(max(1.0 - v, 0.0), 1.0) ** (1 << n)
    return 1.0 - ((1.0 - t) * lo + t * lo * lo)


def cl(x, lo=0.0, hi=1.0):
    return lo if x < lo else (hi if x > hi else x)


def reference(rgb, sa, sw, ha, hw, cc, mc):
    """平场：邻域 = 自身。返回 0…255 三通道 / flat field, nb == self."""
    r, g, b = [c / 255.0 for c in rgb]
    lum = (max(r, g, b) + 0.299 * r + 0.587 * g + 0.114 * b) * 0.5
    lv = int(cl(round(lum * 255.0), 0, 255))

    adj = [r, g, b]
    if sa > 0:
        m = mask_table(sw)[lv]
        s = strength(sa)
        adj = [a + m * (lift(s, a) - a) for a in adj]
    if ha > 0:
        m = mask_table(hw)[255 - lv]
        s = strength(ha)
        adj = [a - m * (lift(s, 1.0 - a) - (1.0 - a)) for a in adj]

    y1 = 0.299 * r + 0.587 * g + 0.114 * b
    ym = cl(0.299 * adj[0] + 0.587 * adj[1] + 0.114 * adj[2])
    if mc != 0:
        k = interp1([(m[0], m[1]) for m in MIDTONE], mc)
        p = interp1([(m[0], m[2]) for m in MIDTONE], mc)
        ym = cl(ym + k * (ym - 0.5) * (max(0.0, 4.0 * ym * (1.0 - ym)) ** p))

    den = max(ym, y1, 1e-6)
    f = abs(ym - y1) / den
    gain = (2.718281828459045 ** (interp1(COLOR_UP, cc) * f) if cc >= 0
            else 1.0 + interp1(COLOR_DOWN, -cc) * f)

    diff = [(q - y1) * gain for q in (r, g, b)]
    k = 1.0
    for d in diff:
        if d > 1e-9:
            k = min(k, (1.0 - ym) / d)
        elif d < -1e-9:
            k = min(k, ym / (-d))
    k = cl(k)
    return [cl(ym + k * d) * 255.0 for d in diff]


# ------------------------------------------------------------------ 运行 ---
def find_gegl():
    for c in GEGL_CANDIDATES:
        if c and os.path.exists(c):
            return c
    raise SystemExit("找不到 gegl 可执行文件，用 GEGL_BIN=... 指定")


def gegl_env(exe):
    env = dict(os.environ)
    lib = os.path.join(os.path.dirname(os.path.dirname(exe)), "lib", "gegl-0.4")
    sep = ";" if os.name == "nt" else ":"
    build = os.path.join(ROOT, "build")
    parts = [build]
    if os.name == "nt":
        parts.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "gegl-0.4", "plug-ins"))
    else:
        parts.append(os.path.expanduser("~/.local/share/gegl-0.4/plug-ins"))
    parts.append(lib)
    env["GEGL_PATH"] = sep.join([p for p in parts if p])
    return env


def render(exe, env, src, dst, **kw):
    args = [exe, src, "-o", dst, "--", "lb:shadows-highlights"]
    args += ["%s=%s" % (k.replace("_", "-"), v) for k, v in kw.items()]
    r = subprocess.run(args, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 %s\n%s\n%s" % (kw, r.stdout, r.stderr))


def diff_at(path, xs, y, ref):
    _, _, get = read_png(path)
    out, worst = [], (0.0, None)
    for x, want in zip(xs, ref):
        got = get(x, y)
        d = max(abs(got[i] - want[i]) for i in range(3))
        out.append(d)
        if d > worst[0]:
            worst = (d, x, tuple(round(v, 1) for v in want), tuple(round(v, 1) for v in got))
    return max(out), worst


def main():
    fast = "--fast" in sys.argv
    exe = find_gegl()
    env = gegl_env(exe)
    tmp = tempfile.mkdtemp(prefix="shps-")
    print("· gegl: %s" % exe)
    print("· 临时目录: %s\n" % tmp)

    fails = 0
    # 必须覆盖 0 和 255：修剪端点的检查靠这两条带
    greys = sorted(set(list(range(0, 256, 16))
                       + [1, 7, 23, 39, 55, 71, 87, 103, 119, 135, 254, 255]))
    src = os.path.join(tmp, "bands.png")
    xs = bands(src, [(v, v, v) for v in greys])

    sets = [(100, 50, 0, 50, 20, 0), (35, 50, 0, 50, 20, 0),
            (0, 50, 100, 50, 20, 0), (100, 50, 100, 50, 20, 0),
            (100, 100, 0, 50, 20, 0), (75, 30, 60, 70, 20, 40)]
    print("== 1. 平场 LUT（参考实现 vs 算子）/ flat-field LUT")
    for sa, sw, ha, hw, cc, mc in sets:
        dst = os.path.join(tmp, "lut_%d_%d_%d_%d_%d_%d.png" % (sa, sw, ha, hw, cc, mc))
        render(exe, env, src, dst, shadows_amount=sa, shadows_width=sw,
               shadows_radius=10, highlights_amount=ha, highlights_width=hw,
               highlights_radius=10, color_correction=cc, midtone_contrast=mc,
               black_clip=0, white_clip=0)
        want = [reference((v, v, v), sa, sw, ha, hw, cc, mc) for v in greys]
        mx, worst = diff_at(dst, xs, 20, want)
        ok = mx <= 1.5
        fails += 0 if ok else 1
        print("   s%-3d/%-3d h%-3d/%-3d cc%-3d mc%-3d  max %4.1f 码  %s"
              % (sa, sw, ha, hw, cc, mc, mx, "OK" if ok else "FAIL %s" % (worst,)))

    print("\n== 2. 彩色平场（颜色校正分支）/ coloured flat fields")
    cols = [(200, 60, 40), (40, 160, 90), (30, 70, 200), (130, 110, 180),
            (250, 240, 60), (90, 90, 90)]
    csrc = os.path.join(tmp, "cols.png")
    cxs = bands(csrc, cols)
    for cc in (100, 20, -50, -100):
        dst = os.path.join(tmp, "col_%d.png" % (cc + 200))
        render(exe, env, csrc, dst, shadows_amount=100, shadows_width=50,
               shadows_radius=10, highlights_amount=100, highlights_width=50,
               highlights_radius=10, color_correction=cc, midtone_contrast=0,
               black_clip=0, white_clip=0)
        want = [reference(c, 100, 50, 100, 50, cc, 0) for c in cols]
        mx, worst = diff_at(dst, cxs, 20, want)
        ok = mx <= 1.5
        fails += 0 if ok else 1
        print("   color-correction %+4d  max %4.1f 码  %s"
              % (cc, mx, "OK" if ok else "FAIL %s" % (worst,)))

    print("\n== 3. 结构性质 / structural invariants")
    base = dict(shadows_radius=10, highlights_radius=10, color_correction=20,
                midtone_contrast=0, black_clip=0, white_clip=0)

    d0 = os.path.join(tmp, "ident.png")
    render(exe, env, src, d0, shadows_amount=0, shadows_width=50,
           highlights_amount=0, highlights_width=50, **base)
    ident_max = max(abs(read_png(d0)[2](x, 20)[i] - v)
                    for v, x in zip(greys, xs) for i in range(3))
    ok = ident_max == 0
    fails += 0 if ok else 1
    print("   amount=0 恒等                        max %4.1f 码  %s"
          % (ident_max, "OK" if ok else "FAIL"))

    # 128 灰是中间调的固定点（4y(1-y)=1 但 y-0.5=0）
    pivot = reference((128, 128, 128), 0, 50, 0, 50, 20, 100)[0]
    ok = abs(pivot - 128) <= 1.0
    fails += 0 if ok else 1
    print("   中间调支点 128 (mc=100)              → %.1f      %s"
          % (pivot, "OK" if ok else "FAIL"))

    # 平场上半径不该有影响：带 96px 宽，半径 2 / 8 的 3σ 都远小于半带
    r1, r2 = os.path.join(tmp, "r2.png"), os.path.join(tmp, "r8.png")
    for rr, dst in ((2, r1), (8, r2)):
        render(exe, env, src, dst, shadows_amount=100, shadows_width=50,
               shadows_radius=rr, highlights_amount=100, highlights_width=50,
               highlights_radius=rr, color_correction=20, midtone_contrast=0,
               black_clip=0, white_clip=0)
    mx, worst = diff_at(r1, xs, 20, [read_png(r2)[2](x, 20) for x in xs])
    ok = mx <= 1.0
    fails += 0 if ok else 1
    print("   平场与半径无关 (2 vs 8)              max %4.1f 码  %s"
          % (mx, "OK" if ok else "FAIL"))

    # 默认修剪 0.01% 在满量程图上不该动端点
    dc = os.path.join(tmp, "clip.png")
    render(exe, env, src, dc, shadows_amount=100, shadows_width=50,
           highlights_amount=100, highlights_width=50, color_correction=20,
           midtone_contrast=0, shadows_radius=10, highlights_radius=10)
    _, _, gc = read_png(dc)
    e0, e1 = gc(xs[0], 20)[0], gc(xs[-1], 20)[0]
    ok = abs(e0) <= 1 and abs(e1 - 255) <= 1
    fails += 0 if ok else 1
    print("   默认修剪保留端点 (0 / 255)            → %.1f / %.1f  %s"
          % (e0, e1, "OK" if ok else "FAIL"))

    if not fast:
        csvp = os.path.join(CAL, "data", "curve.csv")
        rampp = os.path.join(CAL, "ramp-2.png")
        print("\n== 4. 经典图像编辑器 实测对照 / against 经典图像编辑器")
        if not (os.path.exists(csvp) and os.path.exists(rampp)):
            print("   跳过：没有 %s 或 ramp-2.png（标定数据不在本仓库时正常）" % csvp)
        else:
            import csv as _csv
            rows = {}
            for r in _csv.DictReader(open(csvp, encoding="utf-8")):
                rows.setdefault(r["case"], {})[int(r["level"])] = float(r["r"])
            for tag, ref in sorted(rows.items()):
                kw = dict(base)
                mb = re.match(r"^both_a(\d+)$", tag)
                ms = re.match(r"^([sh])_a(\d+)_w(\d+)$", tag)
                if mb:
                    a = int(mb.group(1))
                    kw.update(shadows_amount=a, shadows_width=50,
                              highlights_amount=a, highlights_width=50)
                elif ms:
                    a, w = int(ms.group(2)), int(ms.group(3))
                    if ms.group(1) == "s":
                        kw.update(shadows_amount=a, shadows_width=w, highlights_amount=0)
                    else:
                        kw.update(shadows_amount=0, highlights_amount=a,
                                  highlights_width=w)
                else:
                    continue
                dst = os.path.join(tmp, "ps_" + tag + ".png")
                render(exe, env, rampp, dst, **kw)
                _, hh, gp = read_png(dst)
                d = sorted(abs(gp(i * 200 + 100, hh // 2)[0] - ref[v])
                           for i, v in enumerate(sorted(ref)))
                ok = d[-1] <= 6.0
                fails += 0 if ok else 1
                print("   %-14s max %4.1f 码  中位 %4.1f  %s"
                      % (tag, d[-1], d[len(d) // 2], "OK" if ok else "FAIL"))

    print("\n%s（%d 项失败）" % ("全部通过" if fails == 0 else "有失败项", fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
