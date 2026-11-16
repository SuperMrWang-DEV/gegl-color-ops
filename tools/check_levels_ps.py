# -*- coding: utf-8 -*-
"""验收 lb:levels（经典图像编辑器 色阶）。

模型（与 C 实现逐行一致，数值刻度 0–255）：
    t   = clamp((v - inLow) / (inHigh - inLow), 0, 1)
    t'  = t ^ (1 / gamma)          # gamma > 1 提亮，< 1 压暗
    out = outLow + t' * (outHigh - outLow)

验证分两层：
  A. 数学层——Python 侧复刻 C 模型，512 点灰阶探针逐像素比对，偏差应 ≤1 码。
  B. 基准层——回放两个公开的 经典图像编辑器 实测点（官方用户社区里用户量出来的像素值），
     用来卡住 gamma 的**方向**和**指数形式**。这两点很要紧：把指数写成
     t^gamma 而不是 t^(1/gamma)，方向会整个反过来，而只做自洽验证是查不
     出来的（C 和 Python 会一起错）。

本机 经典图像编辑器 2025 的 ActionManager 在「色阶」和「创建调整图层」上直接报程序错误
（`Mk` / `Lvls` 都试过，见 lvls-cal/_diag2.txt），无法逐码标定，所以基准取
公开实测值而不是本机标定。

    python tools/check_levels_ps.py
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

W = 256
H = 4
PROBE = None


def find_gegl():
    for c in GEGL_CANDIDATES:
        if c and os.path.exists(c):
            return c
    raise SystemExit("找不到 gegl 可执行文件，用 GEGL_BIN=... 指定")


def gegl_env(exe):
    env = dict(os.environ)
    lib = os.path.join(os.path.dirname(os.path.dirname(exe)), "lib", "gegl-0.4")
    paths = [BUILD, lib]
    env["GEGL_PATH"] = (";" if os.name == "nt" else ":").join(paths)
    return env


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b""))


def make_probe(path):
    """256 列灰阶：第 x 列的灰度恰好是 x，采样不用插值。"""
    rows = []
    for _ in range(H):
        row = bytearray()
        for x in range(W):
            row += bytes((x, x, x))
        rows.append(row)
    write_png(path, W, H, rows)


def render(exe, env, args, dst):
    cmd = [exe, PROBE, "-o", dst, "--", "lb:levels"] + args
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 %s\n%s\n%s" % (args, r.stdout, r.stderr))


# ---------- Python 侧复刻 C 模型 ----------

def levels_one(v, inlow=0.0, gamma=1.0, inhigh=255.0, outlow=0.0, outhigh=255.0):
    span = inhigh - inlow
    if span > 1e-9:
        t = (v - inlow) / span
    else:
        t = 1.0 if v >= inhigh else 0.0
    if t <= 0.0:
        return outlow
    if t >= 1.0:
        return outhigh
    if abs(gamma - 1.0) > 1e-4:
        t = t ** (1.0 / gamma)
    return outlow + t * (outhigh - outlow)


def expected(v, **kw):
    """灰像素 v 经色阶后的 RGB（复合组 + 单通道组，默认恒等）。"""
    comp = levels_one(v, kw.get("inlow", 0.0), kw.get("gamma", 1.0),
                      kw.get("inhigh", 255.0), kw.get("outlow", 0.0),
                      kw.get("outhigh", 255.0))
    r = levels_one(comp, kw.get("r_inlow", 0.0), kw.get("r_gamma", 1.0),
                   kw.get("r_inhigh", 255.0), kw.get("r_outlow", 0.0),
                   kw.get("r_outhigh", 255.0))
    g = levels_one(comp, kw.get("g_inlow", 0.0), kw.get("g_gamma", 1.0),
                   kw.get("g_inhigh", 255.0), kw.get("g_outlow", 0.0),
                   kw.get("g_outhigh", 255.0))
    b = levels_one(comp, kw.get("b_inlow", 0.0), kw.get("b_gamma", 1.0),
                   kw.get("b_inhigh", 255.0), kw.get("b_outlow", 0.0),
                   kw.get("b_outhigh", 255.0))
    return (r, g, b)


def px(img, x):
    return img[2](x, 0)


def diff(a, b):
    return max(abs(a[i] - b[i]) for i in range(3))


def main():
    global PROBE
    exe = find_gegl()
    env = gegl_env(exe)
    tmp = tempfile.mkdtemp(prefix="lv-")
    PROBE = os.path.join(tmp, "probe.png")
    make_probe(PROBE)
    print("· gegl: %s" % exe)
    print("· 探针: 256x4 灰阶，第 x 列灰度 = x\n")

    results = []

    def case(name, args, checks, tol=1.0):
        dst = os.path.join(tmp, "o.png")
        render(exe, env, args, dst)
        img = read_png(dst)
        ok, notes = True, []
        for desc, g, exp in checks:
            got = px(img, g)
            d = diff(exp, got)
            if d > tol:
                ok = False
            notes.append("    %-40s %s  最大偏差 %.2f 码" %
                         (desc, "OK" if d <= tol else "✗", d))
        results.append((name, ok, notes))

    # ---- A. 数学层 ----
    case("全默认恒等", [],
         [("%d 恒等" % g, g, (g, g, g)) for g in (0, 20, 128, 240, 255)])

    case("输入黑场 64", ["in-low=64"],
         [("v=0 归零", 0, expected(0, inlow=64)),
          ("v=64 正好归零", 64, expected(64, inlow=64)),
          ("v=128 中段", 128, expected(128, inlow=64)),
          ("v=240 被拉伸到 235", 240, expected(240, inlow=64))])

    case("输入白场 192", ["in-high=192"],
         [("v=192 正好全白", 192, expected(192, inhigh=192)),
          ("v=255 不动", 255, (255, 255, 255)),
          ("v=96 中段", 96, expected(96, inhigh=192)),
          ("v=20 被拉伸到 27", 20, expected(20, inhigh=192))])

    case("输出收缩 50–200", ["out-low=50", "out-high=200"],
         [("v=0 抬到输出黑场", 0, expected(0, outlow=50, outhigh=200)),
          ("v=255 压到输出白场", 255, expected(255, outlow=50, outhigh=200)),
          ("v=128 线性到中段", 128, expected(128, outlow=50, outhigh=200))])

    case("gamma=2.0 提亮", ["in-gamma=2.0"],
         [("v=128 抬到 ~180", 128, expected(128, gamma=2.0)),
          ("v=64 抬到 ~113", 64, expected(64, gamma=2.0)),
          ("v=0/255 端点不动", 0, (0, 0, 0))])

    case("gamma=0.5 压暗", ["in-gamma=0.5"],
         [("v=128 压到 ~64", 128, expected(128, gamma=0.5)),
          ("v=192 压到 ~144", 192, expected(192, gamma=0.5)),
          ("v=255 端点不动", 255, (255, 255, 255))])

    case("组合 50/0.7/200 → 30/220",
         ["in-low=50", "in-gamma=0.7", "in-high=200",
          "out-low=30", "out-high=220"],
         [("v=125 中段", 125, expected(125, inlow=50, gamma=0.7, inhigh=200,
                                       outlow=30, outhigh=220)),
          ("v=20 落到输出黑场", 20, (30, 30, 30)),
          ("v=240 落到输出白场", 240, (220, 220, 220))])

    # ---- B. 基准层：两个公开的 经典图像编辑器 实测点 ----
    # 来源：官方用户社区「Question on the Gamma(mid-tone) value in levels
    # adjustment layer」里用户量出的像素值 + 公认公式 out = in^(1/gamma)。
    # 154 @ γ0.46 → 84（公式 85.1）；200 @ γ1.646 → 220（公式 219.6）。
    case("经典图像编辑器 实测点 γ=0.46: 154 → 84", ["in-gamma=0.46"],
         [("v=154 期望 ~84", 154, (84.0, 84.0, 84.0)),
          ("v=127 单调压暗", 127, expected(127, gamma=0.46))],
         tol=2.5)

    case("经典图像编辑器 实测点 γ=1.646: 200 → 220", ["in-gamma=1.646"],
         [("v=200 期望 ~220", 200, (220.0, 220.0, 220.0)),
          ("v=128 单调提亮", 128, expected(128, gamma=1.646))],
         tol=2.5)

    # ---- C. 单通道独立性 ----
    case("只动红通道", ["red-in-gamma=0.5"],
         [("红=64 压暗、绿蓝不动", 64,
           (expected(64, r_gamma=0.5)[0], 64, 64)),
          ("红=255 端点不动", 255, (255, 255, 255))])

    # ---- D. gamma 方向（显式断言，防指数形式写反）----
    dst = os.path.join(tmp, "dir.png")
    render(exe, env, ["in-gamma=2.0"], dst)
    up_val = px(read_png(dst), 128)[0]
    render(exe, env, ["in-gamma=0.5"], dst)
    down_val = px(read_png(dst), 128)[0]
    up, down = up_val > 128, down_val < 128
    results.append(("gamma 方向：>1 提亮、<1 压暗", up and down,
                    ["    γ=2.0 时 128 → %.0f（应 >128）%s" % (up_val, "" if up else " ✗"),
                     "    γ=0.5 时 128 → %.0f（应 <128）%s" % (down_val, "" if down else " ✗")]))

    # ---- 汇总 ----
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, notes in results:
        print("%s %s" % ("OK  " if ok else "FAIL", name))
        for n in notes:
            print(n)
    print("\n%d/%d 通过" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
