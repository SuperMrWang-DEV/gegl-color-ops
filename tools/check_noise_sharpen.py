# -*- coding: utf-8 -*-
"""数值回归：锐化与杂色四件套。

    python tools/check_noise_sharpen.py [-v]

    lb:unsharp-mask     锐化 + 光晕抑制
    lb:add-noise        添加杂色（高斯/均匀、单色、可复现）
    lb:reduce-noise     减少杂色（sigma 滤波，保边）
    lb:dust-scratches   蒙尘与划痕（阈值内取中值）

做法：生成小图 → 用 GIMP 自带的 gegl 命令行跑算子 → 读回 PNG 逐像素核对。
判定全部是「结构性」的，不写死某一版的实现细节：恒等、单调、光晕有无、
可复现、噪点方差下降、边缘不动、孤点被抹掉。
"""
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_displace import write_png, read_all

ROOT = os.path.dirname(HERE)
TMP = os.path.join(ROOT, "build", "noise-sharpen-check")
GEGL = os.environ.get("GEGL", r"D:/fastsoftware/GIMP 3/bin/gegl.exe")
SYS_OPS = r"D:/fastsoftware/GIMP 3/lib/gegl-0.4"

VERBOSE = "-v" in sys.argv
PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        if VERBOSE:
            print("  ok   %s %s" % (name, detail))
    else:
        FAIL += 1
        print("  FAIL %s  %s" % (name, detail))


def render(op, src, dst, **params):
    env = dict(os.environ)
    env["GEGL_PATH"] = ";".join([os.path.join(ROOT, "build"), SYS_OPS])
    cmd = [GEGL, src, "-o", dst, "--", op]
    cmd += ["%s=%s" % (k.replace("_", "-"), v) for k, v in params.items()]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 %s\n%s\n%s" % (" ".join(cmd), r.stdout, r.stderr))
    w, h, px = read_all(dst)
    return w, h, px


def gray(px, i):
    return px[i][0]


def mk(name, vals, w, h, alpha=255):
    """vals 是 w*h 个灰度值；返回路径。"""
    px = [(v, v, v, alpha) for v in vals]
    p = os.path.join(TMP, name)
    write_png(p, px, w, h)
    return p


def diff_levels(a, b):
    return max(abs(a[i][0] - b[i][0]) for i in range(len(a)))


def main():
    os.makedirs(TMP, exist_ok=True)

    # ---------- 公共素材 ----------
    # 软边：60 → 200 经过 4 个过渡级，锐化应该把它压陡但不能过冲
    W = H = 16
    soft_row = [60, 60, 60, 75, 95, 130, 165, 190, 200, 200, 200, 200, 200, 200, 200, 200]
    soft = mk("soft.png", [v for _ in range(H) for v in soft_row], W, H)
    # 硬边：60 / 200 一步跳变
    hard = mk("hard.png", [60 if x < 8 else 200 for _ in range(H) for x in range(W)], W, H)
    # 平坦灰 + 固定噪声
    flat = [128 + (17 if (x * 7 + y * 13) % 5 == 0 else -17) for y in range(H) for x in range(W)]
    noisy = mk("noisy.png", flat, W, H)
    # 均匀灰 + 一个亮点（灰尘）
    speck = [100] * (W * H)
    speck[8 * W + 8] = 220
    dusty = mk("dust.png", speck, W, H)

    # ================= lb:unsharp-mask =================
    print("· lb:unsharp-mask")

    _, _, a = render("lb:unsharp-mask", soft, os.path.join(TMP, "u0.png"),
                     radius=2, amount=0, threshold=0, fringe=0)
    _, _, src_px = read_all(soft)
    ok("数量 0 等于原图", diff_levels(a, src_px) <= 1, "max=%d" % diff_levels(a, src_px))

    _, _, a = render("lb:unsharp-mask", soft, os.path.join(TMP, "u1.png"),
                     radius=2, amount=300, threshold=255, fringe=0)
    ok("阈值 255 全判平坦，原样输出", diff_levels(a, src_px) <= 1,
       "max=%d" % diff_levels(a, src_px))

    _, _, plain = render("lb:unsharp-mask", soft, os.path.join(TMP, "u2.png"),
                         radius=2, amount=150, threshold=0, fringe=0)
    row = [gray(plain, 8 * W + x) for x in range(W)]
    ok("不开光晕抑制时过冲", min(row) < 60 or max(row) > 200, "row=%s" % row)

    _, _, clamped = render("lb:unsharp-mask", soft, os.path.join(TMP, "u3.png"),
                           radius=2, amount=150, threshold=0, fringe=100)
    row = [gray(clamped, 8 * W + x) for x in range(W)]
    ok("光晕抑制后不过冲", min(row) >= 60 and max(row) <= 200, "row=%s" % row)

    # 过渡级数：原图两侧有 4 个中间值，锐化后应变少（更陡）
    def mids(r):
        return sum(1 for v in r if 60 < v < 200)
    stem = [gray(src_px, 8 * W + x) for x in range(W)]
    ok("软边被压陡（中间值变少）", mids(row) < mids(stem),
       "%d -> %d" % (mids(stem), mids(row)))

    _, _, a = render("lb:unsharp-mask", hard, os.path.join(TMP, "u4.png"),
                     radius=2, amount=150, threshold=0, fringe=100)
    _, _, hsrc = read_all(hard)
    ok("硬边 + 完全抑制 = 原图（硬边已无过渡可陡化）", diff_levels(a, hsrc) <= 1,
       "max=%d" % diff_levels(a, hsrc))

    # alpha 透传
    alp = mk("alp.png", [120] * (W * H), W, H, alpha=90)
    _, _, a = render("lb:unsharp-mask", alp, os.path.join(TMP, "u5.png"),
                     radius=2, amount=100, threshold=0, fringe=100)
    ok("alpha 原样透传", all(p[3] == 90 for p in a), "alpha=%s" % {p[3] for p in a})

    # ================= lb:add-noise =================
    print("· lb:add-noise")

    _, _, a = render("lb:add-noise", soft, os.path.join(TMP, "n0.png"),
                     amount=0, seed=7, monochrome=False)
    ok("数量 0 等于原图", diff_levels(a, src_px) <= 1, "max=%d" % diff_levels(a, src_px))

    _, _, a1 = render("lb:add-noise", soft, os.path.join(TMP, "n1.png"),
                      amount=20, seed=7, monochrome=False)
    _, _, a2 = render("lb:add-noise", soft, os.path.join(TMP, "n2.png"),
                      amount=20, seed=7, monochrome=False)
    ok("同种子逐位相同", a1 == a2)

    _, _, a3 = render("lb:add-noise", soft, os.path.join(TMP, "n3.png"),
                      amount=20, seed=8, monochrome=False)
    ok("换种子结果不同", a1 != a3)

    _, _, mono = render("lb:add-noise", soft, os.path.join(TMP, "n4.png"),
                        amount=20, seed=7, monochrome=True)
    ok("单色时三通道相等", all(p[0] == p[1] == p[2] for p in mono))

    flat_gray = mk("g128.png", [128] * (W * H), W, H)
    _, _, gn = render("lb:add-noise", flat_gray, os.path.join(TMP, "n5.png"),
                      amount=30, seed=3, monochrome=True)
    mean = statistics.fmean(p[0] for p in gn)
    sd = statistics.pstdev(p[0] for p in gn)
    ok("均值不偏移（±2 码）", abs(mean - 128) <= 2, "mean=%.2f" % mean)
    ok("标准差落在合理区间", 8 <= sd <= 45, "sd=%.1f" % sd)

    _, _, a = render("lb:add-noise", alp, os.path.join(TMP, "n6.png"),
                     amount=40, seed=1)
    ok("alpha 原样透传", all(p[3] == 90 for p in a))

    # ================= lb:reduce-noise =================
    print("· lb:reduce-noise")

    _, _, a = render("lb:reduce-noise", noisy, os.path.join(TMP, "r0.png"),
                     strength=0, radius=2, detail=0)
    _, _, nsrc = read_all(noisy)
    ok("强度 0 等于原图", diff_levels(a, nsrc) <= 1, "max=%d" % diff_levels(a, nsrc))

    _, _, a = render("lb:reduce-noise", noisy, os.path.join(TMP, "r1.png"),
                     strength=80, radius=2, detail=0)
    sd0 = statistics.pstdev(gray(nsrc, i) for i in range(len(nsrc)))
    sd1 = statistics.pstdev(gray(a, i) for i in range(len(a)))
    ok("噪点方差明显下降", sd1 < sd0 * 0.5, "sd %.1f -> %.1f" % (sd0, sd1))
    m0 = statistics.fmean(gray(nsrc, i) for i in range(len(nsrc)))
    m1 = statistics.fmean(gray(a, i) for i in range(len(a)))
    # 孤立亮点会被拉到周围水平（这本就是去噪要做的事），整体只掉一两码；
    # 崩掉才是问题，所以给 3 码的余量。
    ok("整体不漂移", abs(m1 - m0) <= 3, "%.1f -> %.1f" % (m0, m1))

    _, _, a = render("lb:reduce-noise", hard, os.path.join(TMP, "r2.png"),
                     strength=100, radius=3, detail=0)
    _, _, hsrc = read_all(hard)
    ok("边缘不动", diff_levels(a, hsrc) <= 2, "max=%d" % diff_levels(a, hsrc))

    _, _, a = render("lb:reduce-noise", alp, os.path.join(TMP, "r3.png"),
                     strength=80, radius=2)
    ok("alpha 原样透传", all(p[3] == 90 for p in a))

    # ================= lb:dust-scratches =================
    print("· lb:dust-scratches")

    _, _, a = render("lb:dust-scratches", dusty, os.path.join(TMP, "d1.png"),
                     radius=2, threshold=20)
    ok("孤立亮点被抹掉", sum(gray(a, i) for i in range(len(a))) == 100 * len(a),
       "center=%d" % gray(a, 8 * W + 8))

    _, _, a = render("lb:dust-scratches", hard, os.path.join(TMP, "d2.png"),
                     radius=2, threshold=20)
    _, _, hsrc = read_all(hard)
    ok("边缘不被糊（阈值把对侧邻居排除）", diff_levels(a, hsrc) <= 1,
       "max=%d" % diff_levels(a, hsrc))

    uniform = mk("uni.png", [77] * (W * H), W, H)
    _, _, a = render("lb:dust-scratches", uniform, os.path.join(TMP, "d3.png"),
                     radius=3, threshold=0)
    ok("纯色图不变", all(gray(a, i) == 77 for i in range(len(a))))

    _, _, a = render("lb:dust-scratches", alp, os.path.join(TMP, "d4.png"),
                     radius=2, threshold=30)
    ok("alpha 原样透传", all(p[3] == 90 for p in a))

    print("\n%d/%d 通过" % (PASS, PASS + FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
