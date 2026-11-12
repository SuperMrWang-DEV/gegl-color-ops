# -*- coding: utf-8 -*-
"""验收 lb:color-grading（无 ACR 参考机，按模型自洽验证）。

本机 PS 2025 未装 Camera Raw，无法像 colorize / color-mask-select 那样做
逐码标定，所以这里验证的是「行为与设计模型一致」：
  1. 全默认 = 恒等
  2. 阴影/中间调/高光各自只作用于自己的亮度段（Python 侧复刻模型算期望值）
  3. 灰像素染色后色相落在轮盘色相上（低饱和收敛 f = t + (1-t)·max(0, 1-s/t)）
  4. Blending = 0 是硬分界，Blending = 100 出现宽过渡
  5. Balance 正值把阴影/高光的势力范围往中间推
  6. 全局轮盘对所有亮度均匀生效
  7. 色相扫掠 + 互补轮盘色无接缝（相邻列不出现跳变条纹——早期的
     「色相收敛」模型在互补色相处会因旋转方向翻转而爆条纹，已改为
     向轮盘色混合）

探针是一张 512x4 的灰阶渐变（灰阶的 Rec.709 luma = 自身灰度，分带位置好算）。

    python tools/check_color_grading.py
"""
import os
import subprocess
import sys
import tempfile
import zlib
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")

sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "bc-cal"))
from readpng import read_png              # 8/16 位统一到 0…255 浮点刻度

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GIMP 3", "bin", "gegl.exe"),
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]

W = 512
H = 4


def find_gegl():
    for c in GEGL_CANDIDATES:
        if c and os.path.exists(c):
            return c
    raise SystemExit("找不到 gegl 可执行文件，用 GEGL_BIN=... 指定")


def gegl_env(exe):
    env = dict(os.environ)
    lib = os.path.join(os.path.dirname(os.path.dirname(exe)), "lib", "gegl-0.4")
    paths = [BUILD, lib]
    if os.name == "nt":
        env["GEGL_PATH"] = ";".join(paths)
    else:
        env["GEGL_PATH"] = ":".join(paths)
    return env


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b""))


def make_probe(path):
    rows = []
    for y in range(H):
        row = bytearray()
        for x in range(W):
            g = round(x * 255 / (W - 1))
            row += bytes((g, g, g))
        rows.append(row)
    write_png(path, W, H, rows)


def make_hue_probe(path):
    """色相 0→360 扫掠，s=0.8 v=0.6：用来看色相方向是否连续。"""
    rows = []
    for y in range(H):
        row = bytearray()
        for x in range(W):
            r, g, b = hsv_to_rgb(x / (W - 1.0), 0.8, 0.6)
            row += bytes((round(r * 255), round(g * 255), round(b * 255)))
        rows.append(row)
    write_png(path, W, H, rows)


def x_for_gray(g):
    """灰度 g 在探针里的 x 坐标"""
    return max(0, min(W - 1, round(g / 255.0 * (W - 1))))


def render(exe, env, args, dst):
    cmd = [exe, PROBE, "-o", dst, "--", "lb:color-grading"] + args
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 %s\n%s\n%s" % (args, r.stdout, r.stderr))


# ---------- Python 侧复刻 C 模型（RGB 入、RGB 出，轮盘色混合） ----------

def smooth_step(val, a, b):
    if b <= a:
        return 0.0 if val <= a else 1.0
    if val <= a:
        return 0.0
    if val >= b:
        return 1.0
    t = (val - a) / (b - a)
    return t * t * (3.0 - 2.0 * t)


def rgb_to_hsv(r, g, b):
    cmax, cmin = max(r, g, b), min(r, g, b)
    delta = cmax - cmin
    v = cmax
    s = delta / cmax if cmax > 0 else 0.0
    h = 0.0
    if delta > 0:
        if cmax == r:   h = (g - b) / delta
        elif cmax == g: h = 2.0 + (b - r) / delta
        else:           h = 4.0 + (r - g) / delta
        h /= 6.0
        if h < 0:
            h += 1.0
    return h, s, v


def hsv_to_rgb(h, s, v):
    h = h % 1.0
    s = min(1.0, max(0.0, s))
    v = min(1.0, max(0.0, v))
    c = v * s
    x = c * (1.0 - abs((h * 6.0) % 2.0 - 1.0))
    m = v - c
    if h < 1/6:   rgb = (c, x, 0.0)
    elif h < 2/6: rgb = (x, c, 0.0)
    elif h < 3/6: rgb = (0.0, c, x)
    elif h < 4/6: rgb = (0.0, x, c)
    elif h < 5/6: rgb = (x, 0.0, c)
    else:         rgb = (c, 0.0, x)
    return tuple(ch + m for ch in rgb)


def apply_wheel(rgb, hue_deg, sat_ui, lum_ui, w):
    """与 C 的 apply_wheel 逐行对应：V 调整后，向同明度的轮盘纯色混合。"""
    if w < 0.001:
        return rgb
    r, g, b = rgb
    h, s, v = rgb_to_hsv(r, g, b)
    v = min(1.0, max(0.0, v + lum_ui * 0.005 * w))
    t = sat_ui * 0.01 * w
    if t < 0.001:
        return hsv_to_rgb(h, s, v)
    t = min(t, 1.0)
    base = hsv_to_rgb(h, s, v)
    tint = hsv_to_rgb(hue_deg / 360.0, 1.0, v)
    return tuple(base[i] * (1.0 - t) + tint[i] * t for i in range(3))


def expected_rgb(rgb255, **kw):
    """像素经 color-grading 后的期望 RGB（0…255 刻度）。"""
    r, g, b = [c / 255.0 for c in rgb255]
    L = 0.2126 * r + 0.7152 * g + 0.0722 * b
    L = min(1.0, max(0.0, L))
    feather = min(100.0, max(0.0, kw.get("blending", 50.0))) * 0.0025
    shift = min(100.0, max(-100.0, kw.get("balance", 0.0))) * 0.0025
    split1, split2 = 0.30 - shift, 0.70 - shift
    w_sh = 1.0 - smooth_step(L, split1 - feather, split1 + feather)
    w_hi = smooth_step(L, split2 - feather, split2 + feather)
    w_md = min(1.0, max(0.0, 1.0 - w_sh - w_hi))

    cur = (r, g, b)
    cur = apply_wheel(cur, kw.get("global_hue", 0), kw.get("global_sat", 0), kw.get("global_lum", 0), 1.0)
    cur = apply_wheel(cur, kw.get("shadow_hue", 0), kw.get("shadow_sat", 0), kw.get("shadow_lum", 0), w_sh)
    cur = apply_wheel(cur, kw.get("mid_hue", 0), kw.get("mid_sat", 0), kw.get("mid_lum", 0), w_md)
    cur = apply_wheel(cur, kw.get("high_hue", 0), kw.get("high_sat", 0), kw.get("high_lum", 0), w_hi)
    return tuple(c * 255.0 for c in cur)


def expected_gray(g, **kw):
    return expected_rgb((g, g, g), **kw)


def px(img, x):
    return img[2](x, 0)


def diff(a, b):
    return max(abs(a[i] - b[i]) for i in range(3))


def rgb_to_hue_deg(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d <= 0:
        return None
    if mx == r: h = ((g - b) / d) % 6
    elif mx == g: h = (b - r) / d + 2
    else: h = (r - g) / d + 4
    return h * 60.0


def run_case(exe, env, tmp, name, args, checks):
    dst = os.path.join(tmp, "o.png")
    render(exe, env, args, dst)
    img = read_png(dst)
    ok, notes = True, []
    for desc, g, expect in checks:
        got = px(img, x_for_gray(g))
        d = diff(expect, got)
        if d > 1.5:
            ok = False
        notes.append("    %-42s %s  最大偏差 %.2f 码" % (desc, "OK" if d <= 1.5 else "✗", d))
    return ok, notes


def main():
    global PROBE
    exe = find_gegl()
    env = gegl_env(exe)
    tmp = tempfile.mkdtemp(prefix="cg-")
    PROBE = os.path.join(tmp, "probe.png")
    make_probe(PROBE)
    print("· gegl: %s" % exe)
    print("· 探针: 512x4 灰阶渐变（luma = 灰度/255）\n")

    results = []

    def case(name, args, checks):
        ok, notes = run_case(exe, env, tmp, name, args, checks)
        results.append((name, ok, notes))

    case("全默认恒等", [],
         [("g=20 恒等", 20, (20, 20, 20)),
          ("g=128 恒等", 128, (128, 128, 128)),
          ("g=240 恒等", 240, (240, 240, 240))])

    case("阴影明度 +40", ["shadow-lum=40"],
         [("g=20 提亮 (模型期望)", 20, expected_gray(20, shadow_lum=40)),
          ("g=100 过渡区 (模型期望)", 100, expected_gray(100, shadow_lum=40)),
          ("g=240 高光不动", 240, (240, 240, 240))])

    case("阴影染色 蓝 sat50 hue210", ["shadow-hue=210", "shadow-sat=50"],
         [("g=20 落在轮盘色相 (模型期望)", 20, expected_gray(20, shadow_hue=210, shadow_sat=50)),
          ("g=240 高光不动", 240, (240, 240, 240))])

    img = read_png(os.path.join(tmp, "o.png"))
    hue = rgb_to_hue_deg(*[v / 255.0 for v in px(img, x_for_gray(20))])
    ok_hue = hue is not None and abs((hue - 210 + 180) % 360 - 180) < 2.0
    results.append(("染色像素色相 ≈ 210°", ok_hue,
                    ["    实测色相 %.1f°  %s" % (hue if hue is not None else -1, "OK" if ok_hue else "✗")]))

    case("高光染色 橙 sat80 hue40", ["high-hue=40", "high-sat=80"],
         [("g=240 落位 (模型期望)", 240, expected_gray(240, high_hue=40, high_sat=80)),
          ("g=20 阴影不动", 20, (20, 20, 20))])

    case("中间调染色 绿 sat100 hue120", ["mid-hue=120", "mid-sat=100"],
         [("g=128 落位 (模型期望)", 128, expected_gray(128, mid_hue=120, mid_sat=100)),
          ("g=20 阴影不动", 20, (20, 20, 20)),
          ("g=240 高光不动", 240, (240, 240, 240))])

    case("Blending=0 硬分界", ["shadow-sat=100", "shadow-hue=210", "blending=0"],
         [("g=70 阴影内染色 (模型期望)", 70, expected_gray(70, shadow_hue=210, shadow_sat=100, blending=0)),
          ("g=80 分界之外不动", 80, (80, 80, 80))])

    case("Blending=100 宽过渡", ["shadow-sat=100", "shadow-hue=210", "blending=100"],
         [("g=80 进入过渡带 (模型期望)", 80, expected_gray(80, shadow_hue=210, shadow_sat=100, blending=100)),
          ("g=100 继续过渡 (模型期望)", 100, expected_gray(100, shadow_hue=210, shadow_sat=100, blending=100))])

    case("Balance=+100 偏高光", ["high-sat=100", "high-hue=40", "balance=100"],
         [("g=127 中间调也吃到高光 (模型期望)", 127, expected_gray(127, high_hue=40, high_sat=100, balance=100)),
          ("g=20 深阴影不动", 20, (20, 20, 20))])

    case("Balance 默认时高光不越界", ["high-sat=100", "high-hue=40"],
         [("g=127 中间调不吃高光", 127, (127, 127, 127))])

    case("全局轮盘 均匀生效", ["global-hue=30", "global-sat=60"],
         [("g=20 (模型期望)", 20, expected_gray(20, global_hue=30, global_sat=60)),
          ("g=128 (模型期望)", 128, expected_gray(128, global_hue=30, global_sat=60)),
          ("g=240 (模型期望)", 240, expected_gray(240, global_hue=30, global_sat=60))])

    # 色相扫掠 + 互补轮盘色（180°）：相邻列不允许出现跳变条纹
    PROBE = os.path.join(tmp, "hue.png")
    make_hue_probe(PROBE)
    dst = os.path.join(tmp, "hue-out.png")
    render(exe, env, ["global-hue=180", "global-sat=40"], dst)
    himg = read_png(dst)
    mx = max(diff(px(himg, x - 1), px(himg, x)) for x in range(1, W))
    results.append(("互补色相无接缝", mx <= 8,
                    ["    色相扫掠相邻列最大跳变 %.1f 码（阈值 8）  %s"
                     % (mx, "OK" if mx <= 8 else "✗")]))

    npass = sum(1 for _, ok, _ in results if ok)
    for name, ok, notes in results:
        print("== %s  %s" % ("OK " if ok else "✗  ", name))
        for n in notes:
            print(n)
        print()
    print("· 通过 %d / %d 项" % (npass, len(results)))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
