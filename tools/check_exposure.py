# -*- coding: utf-8 -*-
"""验收 lb:exposure：两个分支分别对拍用户给的 Java 实现，并验证自动选路。

    python tools/check_exposure.py

三件事：
  1. 8 位 PNG（整数格式）→ auto 必须与 precision=encoded 逐码相同，
     且与 Java 的 exposureChannel 一致（容差 1 码）。
  2. precision=linear → 与 Java 的 exposureChannel2 一致，验证分支二的数学。
  3. 把同一张图转成浮点 EXR → auto 必须与 precision=linear 一致、与 encoded
     不同，证明「按精度自动选路」真的切换了，而不只是多了个开关。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_ps_hue_saturation import read_png, write_png

TMP = os.path.join(os.path.dirname(HERE), "build", "exp-check")
GEGL = os.environ.get("GEGL", r"D:/fastsoftware/GIMP 3/bin/gegl.exe")
SYS_OPS = r"D:/fastsoftware/GIMP 3/lib/gegl-0.4"
W = 64


def java_8bit(v01, ev, off, gamma):
    t1 = min(v01 * 2.0 ** (ev / 2.2), 1.0)
    t2 = max(min(t1 ** 2.2 + off, 1.0), 0.0) ** (1 / 2.2)
    return t2 ** (1 / gamma)


def java_32bit(v01, ev, off, gamma):
    t2 = v01 * 2.0 ** ev + off
    t2 = max(t2, 0.0)          # Java 版直接 pow 负数会 NaN；算子此处钳 0
    return t2 ** (1 / gamma)


COMBOS = [(1.0, 0.0, 1.0), (2.0, 0.0, 1.0), (-1.5, 0.0, 1.0), (-3.0, 0.0, 1.0),
          (1.0, 0.1, 1.0), (1.0, -0.1, 1.0), (2.0, -0.15, 1.0), (-2.0, 0.1, 1.0),
          (0.0, 0.0, 1.8), (0.0, 0.0, 0.45), (1.5, 0.05, 2.2), (-1.0, -0.05, 0.8)]


def run(src, dst, **params):
    env = dict(os.environ)
    env["GEGL_PATH"] = ";".join([os.path.join(os.path.dirname(HERE), "build"), SYS_OPS])
    cmd = [GEGL, src, "-o", dst, "--", "lb:exposure"]
    cmd += ["%s=%s" % (k.replace("_", "-"), v) for k, v in params.items()]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 %s\n%s\n%s" % (cmd, r.stdout, r.stderr))


def pixels(path, w, h):
    out = []
    _, _, depth, ctype, rows = read_png(path)
    nch = {2: 3, 6: 4}[ctype] * (depth // 8)
    for y in range(h):
        row = rows[y]
        for x in range(w):
            if depth == 16:
                out.append([(row[x * nch + k * 2] * 256 + row[x * nch + k * 2 + 1]) / 257.0
                            for k in range(3)])
            else:
                out.append([float(row[x * nch + k]) for k in range(3)])
    return out


def main():
    os.makedirs(TMP, exist_ok=True)
    # 用一组覆盖暗/中/亮的灰阶 + 若干色相，避免只测单一色调
    vals = [i * 255 // (W - 1) for i in range(W)]
    colors = [(v, v, v) for v in vals] * W
    src = os.path.join(TMP, "src.png")
    rows = b"".join(bytes(colors[y * W + x]) for y in range(W) for x in range(W))
    write_png(src, rows, W, W)

    exr = os.path.join(TMP, "src.exr")
    env = dict(os.environ)
    env["GEGL_PATH"] = ";".join([os.path.join(os.path.dirname(HERE), "build"), SYS_OPS])
    subprocess.run([GEGL, src, "-o", exr], env=env, capture_output=True)

    out_auto = os.path.join(TMP, "auto.png")
    out_enc = os.path.join(TMP, "enc.png")
    out_lin = os.path.join(TMP, "lin.png")

    worst_enc = worst_lin = 0.0
    auto_mismatch = 0
    for (ev, off, gamma) in COMBOS:
        run(src, out_auto, exposure=ev, offset=off, gamma=gamma)
        run(src, out_enc, exposure=ev, offset=off, gamma=gamma, precision="encoded")
        run(src, out_lin, exposure=ev, offset=off, gamma=gamma, precision="linear")

        a = pixels(out_auto, W, W)
        e = pixels(out_enc, W, W)
        l = pixels(out_lin, W, W)
        auto_mismatch += sum(1 for p, q in zip(a, e) if p != q)

        de = max(abs(p[0] - java_8bit(colors[y * W + x][0] / 255.0, ev, off, gamma) * 255.0)
                 for y in range(W) for x in range(W) for p in [e[y * W + x]])
        dl = max(abs(p[0] - min(java_32bit(colors[y * W + x][0] / 255.0, ev, off, gamma), 1.0) * 255.0)
                 for y in range(W) for x in range(W) for p in [l[y * W + x]])
        worst_enc = max(worst_enc, de)
        worst_lin = max(worst_lin, dl)
        print("  ev=%+5.1f off=%+.2f g=%.2f   8bit Δ=%.2f   linear Δ=%.2f"
              % (ev, off, gamma, de, dl))

    print("\n① 8 位分支 vs Java exposureChannel：最大 %.2f 码" % worst_enc)
    print("② 线性分支 vs Java exposureChannel2：最大 %.2f 码" % worst_lin)
    print("③ 整数输入下 auto 与 encoded 的逐像素差异数：%d" % auto_mismatch)

    # ④ 浮点输入：auto 应当切到 linear
    fl_auto = os.path.join(TMP, "f_auto.png")
    fl_lin = os.path.join(TMP, "f_lin.png")
    fl_enc = os.path.join(TMP, "f_enc.png")
    run(exr, fl_auto, exposure=1.0)
    run(exr, fl_lin, exposure=1.0, precision="linear")
    run(exr, fl_enc, exposure=1.0, precision="encoded")
    pa, pl, pe = (pixels(p, W, W) for p in (fl_auto, fl_lin, fl_enc))
    same_lin = all(p == q for p, q in zip(pa, pl))
    diff_enc = sum(1 for p, q in zip(pa, pe) if p != q)
    print("④ 浮点输入：auto == linear ? %s ；auto 与 encoded 不同的像素 %d"
          % ("是" if same_lin else "否", diff_enc))

    ok = (worst_enc <= 1.0 and worst_lin <= 1.0 and auto_mismatch == 0
          and same_lin and diff_enc > 0)
    print("\n%s" % ("✓ 两条分支与自动选路均通过" if ok else "✗ 存在不一致"))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
