#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""木偶变形（网格变形）：数学层回归（不需要 GIMP、不需要显卡）。

跑法：python tools/check_warp.py

这里验的是 _shared/warp_math.py 的**语义**，不是像素好看不好看：
钉子处必须严格插值、半径外必须一个字节不动、栅格插值不能把场插歪、
行级剪枝不能漏掉该重采样的行。这几条写错，GIMP 一声不响，只会给你一张
局部被抹掉或者整张跟着漂的图。
"""

import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import warp_math as WM                                      # noqa: E402

PASS = 0
FAIL = []


def ok(label, cond, detail=None):
    global PASS
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL.append(label)
        print("  FAIL %s   %s" % (label, detail if detail is not None else ""))


def section(name):
    print("\n" + name)


def make_rgba(w, h, box=None, fg=(220, 40, 40, 255), bg=(250, 250, 250, 255)):
    """白底 + 中间一块纯色方块（RGBA）。"""
    data = bytearray(w * h * 4)
    for i in range(w * h):
        data[i * 4:i * 4 + 4] = bytes(bg)
    if box:
        x1, y1, x2, y2 = box
        for y in range(max(0, y1), min(h, y2)):
            row = y * w
            for x in range(max(0, x1), min(w, x2)):
                o = (row + x) * 4
                data[o:o + 4] = bytes(fg)
    return bytes(data)


def px(rgba, w, x, y):
    o = (y * w + x) * 4
    return tuple(rgba[o:o + 4])


# ---- 1. 恒等 ---------------------------------------------------------------

section("恒等：没钉子 / 钉子没拖")
W, H = 320, 240
base = make_rgba(W, H, (100, 80, 180, 160))

f0 = WM.build_field(W, H, [], radius=0.3 * 320)
ok("空钉子 → 场是恒等", f0.is_identity())
ok("空钉子 → 字节完全一致", WM.warp_rgba(base, W, H, f0) == base)

same = [{"sx": 120, "sy": 100, "dx": 120, "dy": 100}]
f1 = WM.build_field(W, H, same, radius=0.3 * 320)
ok("钉子原位 = 现位 → 场是恒等", f1.is_identity())
ok("钉子原位 = 现位 → 字节完全一致", WM.warp_rgba(base, W, H, f1) == base)
ok("pin_summary：没拖动时 moved = 0",
   WM.pin_summary(same)["moved"] == 0, WM.pin_summary(same))

# ---- 2. 钉子处严格插值 -----------------------------------------------------

section("钉子处严格插值（反向场在 d 处必须给出 s）")
pins = [
    {"sx": 100, "sy": 100, "dx": 130, "dy": 110},
    {"sx": 220, "sy": 150, "dx": 200, "dy": 190},
]
f = WM.build_field(W, H, pins, mode=WM and "similarity", radius=0.6 * 320)
worst = 0.0
for p in pins:
    ox, oy = f.sample(p["dx"], p["dy"])
    want = (p["sx"] - p["dx"], p["sy"] - p["dy"])
    worst = max(worst, math.hypot(ox - want[0], oy - want[1]))
ok("反向场：p→s 在钉子上成立（最大误差 %.3f px）" % worst, worst < 0.05, worst)

fwd = WM.build_field(W, H, pins, mode="similarity", radius=0.6 * 320,
                     forward=True)
worst = 0.0
for p in pins:
    ox, oy = fwd.sample(p["sx"], p["sy"])
    want = (p["dx"] - p["sx"], p["dy"] - p["sy"])
    worst = max(worst, math.hypot(ox - want[0], oy - want[1]))
ok("正向场：s→d 在钉子上成立（最大误差 %.3f px）" % worst, worst < 0.05, worst)

# ---- 3. 单钉子就是平移 -----------------------------------------------------

section("单钉子：半径内近似平移")
one = [{"sx": 100, "sy": 100, "dx": 130, "dy": 110}]
fs = WM.build_field(W, H, one, mode="affine", radius=0.9 * 320)
ox, oy = fs.sample(105, 105)
ok("单钉子远端 ≈ 平移量（%.2f, %.2f / 期望 -30, -10）" % (ox, oy),
   abs(ox + 30) < 1.0 and abs(oy + 10) < 1.0, (ox, oy))

# ---- 4. 局部性 + 连续性 ----------------------------------------------------

section("局部性：半径外严格恒等，边界不能硬跳")
rad = 60.0
fp = WM.build_field(W, H, one, mode="affine", radius=rad)
far = [(20, 20), (300, 20), (300, 220), (20, 220)]
ok("四个角都在半径外且位移为 0",
   all(fp.sample(x, y) == (0.0, 0.0) for x, y in far),
   [fp.sample(x, y) for x, y in far])
ok("半径 +2 px 处位移为 0", fp.sample(130 + rad + 2, 110) == (0.0, 0.0),
   fp.sample(130 + rad + 2, 110))

prev = None
jump = 0.0
for i in range(0, 320, 1):
    ox, oy = fp.sample(i, 110)
    if prev is not None:
        jump = max(jump, math.hypot(ox - prev[0], oy - prev[1]))
    prev = (ox, oy)
# 滑杆边缘本来就是一条斜坡：smoothstep 的最大斜率是 1.5，位移 30 px 摊在
# 半径 60 px 上，理论上限就是 1.5×30/60 = 0.75 px/px。超过它才叫硬跳变。
limit = 1.5 * 30.0 / rad * 1.2
ok("沿 x 每 1 px 的位移变化 < %.2f px（实际 %.3f）" % (limit, jump),
   jump < limit, jump)

# ---- 5. 栅格插值 vs 逐点解 -------------------------------------------------

section("栅格插值：不能把场插歪")
fin = WM.build_field(W, H, pins, mode="affine", radius=0.6 * 320)
norm = WM.normalized_pins(pins)
worst = 0.0
for k in range(40):
    x = (k * 7.7) % (W - 1)
    y = (k * 11.3) % (H - 1)
    ox, oy = fin.sample(x, y)
    tx, ty = WM.mls_point(x, y, norm, mode="affine", radius=0.6 * 320,
                          reverse=True)
    worst = max(worst, math.hypot(ox - (tx - x), oy - (ty - y)))
ok("任意点误差 < 0.05 px（最大 %.4f）" % worst, worst < 0.05, worst)

# ---- 6. 相似 / 仿射 --------------------------------------------------------

section("变形方式：相似保形，仿射可拉伸")
stretch = [(0, 0, 0, 0), (100, 0, 200, 0), (0, 100, 0, 100), (100, 100, 200, 100)]
fa = WM.build_field(400, 400, stretch, mode="affine", radius=0)
fsim = WM.build_field(400, 400, stretch, mode="similarity", radius=0)
diff = math.hypot(*(a - b for a, b in zip(fa.sample(150, 50),
                                          fsim.sample(150, 50))))
ok("拉伸配置下两种模式结果不同（差 %.2f px）" % diff, diff > 2.0, diff)


def col_len(M):
    """2×2 矩阵两列的长度（M 按 m00,m01,m10,m11 存）。"""
    return (math.hypot(M[0], M[2]), math.hypot(M[1], M[3]))


# 这个配置是「x 拉长一倍、y 不动」：仿射解出来各向异性，相似只能等比。
norm_stretch = WM.normalized_pins(stretch)
Ma = WM.mls_matrix(150, 50, norm_stretch, "affine")
Ms = WM.mls_matrix(150, 50, norm_stretch, "similarity")
la, lb = col_len(Ma)
ok("仿射模式确实各向异性（两列长 %.2f / %.2f）" % (la, lb),
   abs(la - lb) > 0.3, (la, lb))
dot = Ms[0] * Ms[1] + Ms[2] * Ms[3]
ok("相似模式两列正交（点积 %.2e）" % dot, abs(dot) < 1e-9, dot)
la, lb = col_len(Ms)
ok("相似模式两列等长（%.4f / %.4f）" % (la, lb), abs(la - lb) < 1e-9, (la, lb))
ok("相似模式没有剪切（m01 == -m10）", abs(Ms[1] + Ms[2]) < 1e-9, Ms)

# ---- 7. 重采样 -------------------------------------------------------------

section("重采样：真的把像素搬过去了")
W2, H2 = 200, 150
img = make_rgba(W2, H2, (60, 50, 110, 100))          # 红方块在 (60..110, 50..100)
move = [{"sx": 85, "sy": 75, "dx": 125, "dy": 75}]   # 整块往右推 40 px
fr = WM.build_field(W2, H2, move, mode="affine", radius=0.9 * 200)
out = WM.warp_rgba(img, W2, H2, fr)
ok("方块中心搬到了新位置", px(out, W2, 105, 75) == (220, 40, 40, 255),
   px(out, W2, 105, 75))
ok("旧位置被背景顶掉（不再是纯红）", px(out, W2, 62, 75) != (220, 40, 40, 255),
   px(out, W2, 62, 75))
ok("画布尺寸没变", len(out) == W2 * H2 * 4)

# 半径外一个字节都不能动：这里用一个小半径，让右下角明确落在圈外
tight = WM.build_field(W2, H2, move, mode="affine", radius=45)
out_t = WM.warp_rgba(img, W2, H2, tight)
ok("半径外的角落一字节没动",
   px(out_t, W2, 190, 140) == px(img, W2, 190, 140),
   px(out_t, W2, 190, 140))

# alpha 也一起被搬
alpha_src = bytearray(W2 * H2 * 4)
for y in range(H2):
    for x in range(W2):
        o = (y * W2 + x) * 4
        alpha_src[o + 3] = 255 if 60 <= x < 110 and 50 <= y < 100 else 0
out_a = WM.warp_rgba(bytes(alpha_src), W2, H2, fr)
ok("alpha 跟着一起变形（新位置不透明）", px(out_a, W2, 105, 75)[3] > 200,
   px(out_a, W2, 105, 75)[3])
ok("alpha 原来不透明的地方变透了", px(out_a, W2, 62, 75)[3] < 60,
   px(out_a, W2, 62, 75)[3])

# 拖到图外不炸（坐标被夹住）
wild = [{"sx": 10, "sy": 10, "dx": -400, "dy": -400}]
fw = WM.build_field(W2, H2, wild, mode="affine", radius=300)
out_w = WM.warp_rgba(img, W2, H2, fw)
ok("钉子拖到图外：不炸、长度不变", len(out_w) == W2 * H2 * 4)
ok("钉子拖到图外：整块被拉到左上（(1,1) 仍是背景）",
   px(out_w, W2, 1, 1)[0] >= 200, px(out_w, W2, 1, 1))

# 尺寸不对要报错，而不是悄悄写回半张图
try:
    WM.warp_rgba(b"\x00" * 10, W2, H2, fr)
    ok("字节数不对时抛 ValueError", False)
except ValueError:
    ok("字节数不对时抛 ValueError", True)

# ---- 8. 行级剪枝 -----------------------------------------------------------

section("行级剪枝：没动的行原样搬，动了的行不能漏")
W3, H3 = 200, 200
# 纯色区域重采样前后字节一模一样，测不出「有没有重采样」，所以用带纹理的图
img3 = bytes(bytearray((i * 37) % 256 for i in range(W3 * H3 * 4)))
only_mid = [{"sx": 100, "sy": 100, "dx": 130, "dy": 100}]
f3 = WM.build_field(W3, H3, only_mid, mode="affine", radius=40)
out3 = WM.warp_rgba(img3, W3, H3, f3)
top_same = px(out3, W3, 100, 2) == px(img3, W3, 100, 2)
bot_same = px(out3, W3, 100, 197) == px(img3, W3, 100, 197)
ok("顶部那一行完全没动", top_same)
ok("底部那一行完全没动", bot_same)
row = [px(out3, W3, x, 100) for x in range(W3)]
changed = sum(1 for a, b in zip(row, [px(img3, W3, x, 100) for x in range(W3)])
              if a != b)
ok("中间那一行确实被重采样了（%d px 变化）" % changed, changed > 10, changed)

# 把剪枝阈值关掉再跑一遍：差别只允许出现在「位移本身小于 0.5 px」的像素上。
# 位移大的像素如果不一样，说明剪枝漏了——那才是真 bug（画面会有接缝）。
keep_eps = WM.IDENTITY_EPS
WM.IDENTITY_EPS = 0.0
try:
    full = WM.warp_rgba(img3, W3, H3, f3)
finally:
    WM.IDENTITY_EPS = keep_eps
leak = 0
for yy in range(H3):
    for xx in range(W3):
        ox, oy = f3.sample(xx, yy)
        if math.hypot(ox, oy) >= 0.5 or (ox == 0.0 and oy == 0.0):
            if px(full, W3, xx, yy) != px(out3, W3, xx, yy):
                leak += 1
ok("剪枝只在「位移 < 0.5 px」的像素上才有差（越界 %d 个）" % leak,
   leak == 0, leak)

# ---- 9. 网格线 / 文本解析 --------------------------------------------------

section("网格线 + 钉子字符串")
lines = WM.mesh_polylines(fr, W2, H2, cols=8, rows=6)
ok("网格线数量 = 竖 %d + 横 %d" % (9, 7), len(lines) == 9 + 7, len(lines))
ok("每条线 25 个点", all(len(l) == 25 for l in lines))
ok("恒等场画出来的网格就是原位",
   WM.mesh_polylines(WM.identity_field(W2, H2, 5, 5), W2, H2, cols=2,
                     rows=2)[0][0] == (0.0, 0.0))

text = "10,20,30,40; 100,100; 50 60 70 80"
parsed = WM.parse_pin_string(text, 200, 150)
ok("解析出 3 个钉子", len(parsed) == 3, parsed)
ok("两个数的项按原位 = 现位", parsed[1]["sx"] == 100 and parsed[1]["dx"] == 100,
   parsed[1])
ok("空格也能分列", parsed[2]["dx"] == 70 and parsed[2]["dy"] == 80, parsed[2])
ok("超范围的会被夹住",
   WM.parse_pin_string("-20,999,500,10", 200, 150)[0]["sx"] == 0.0)
ok("乱码被忽略", WM.parse_pin_string("abc; 1,2,3,4;junk") and
   len(WM.parse_pin_string("abc; 1,2,3,4;junk")) == 1)
round_trip = WM.parse_pin_string(WM.format_pin_string(parsed), 200, 150)
ok("format → parse 往返一致",
   all(abs(a[k] - b[k]) < 0.01 for a, b in zip(parsed, round_trip)
       for k in ("sx", "sy", "dx", "dy"))
   and len(round_trip) == len(parsed))

st = WM.pin_summary([{"sx": 10, "sy": 10, "dx": 10, "dy": 10},
                     {"sx": 50, "sy": 50, "dx": 80, "dy": 90}])
ok("pin_summary 最大位移 %.1f" % st["max_shift"],
   abs(st["max_shift"] - 50.0) < 0.01 and st["count"] == 2 and st["moved"] == 1,
   st)

# ---- 10. 退化输入 ----------------------------------------------------------

section("退化输入")
ok("1×1 图不炸", len(WM.warp_rgba(b"\x10\x20\x30\x40", 1, 1,
                                  WM.build_field(1, 1, [], radius=0))) == 4)
pins_same = [{"sx": 50, "sy": 50, "dx": 50, "dy": 50},
             {"sx": 50, "sy": 50, "dx": 50, "dy": 50}]
ok("两个钉子重合不炸", WM.build_field(100, 100, pins_same,
                                     radius=0).is_identity())
bad = [{"sx": "x", "sy": 1, "dx": 1, "dy": 1}]
ok("坏钉子被剔掉", WM.normalized_pins(bad) == [])
ok("nan 钉子被剔掉",
   WM.normalized_pins([{"sx": float('nan'), "sy": 1, "dx": 1, "dy": 1}]) == [])

# ---- 11. numpy 快路径 ------------------------------------------------------

section("numpy 快路径：和纯 Python 必须一致")
if WM.have_numpy():
    w, h = 320, 420
    pins_np = [{"sx": 90, "sy": 120, "dx": 130, "dy": 140},
               {"sx": 220, "sy": 300, "dx": 200, "dy": 330}]
    f_last = None
    for mode in ("affine", "similarity"):
        WM.USE_NUMPY = True
        f_np = WM.build_field(w, h, pins_np, mode=mode, radius=0.3 * w)
        WM.USE_NUMPY = False
        f_py = WM.build_field(w, h, pins_np, mode=mode, radius=0.3 * w)
        err = max(max(abs(a - b) for a, b in zip(f_np.dx, f_py.dx)),
                  max(abs(a - b) for a, b in zip(f_np.dy, f_py.dy)))
        ok("%s 的场两路一致（最大差 %.1e px）" % (mode, err), err < 1e-9, err)
        f_last = f_np
    ok("两路的网格尺寸一致", (f_np.nx, f_np.ny) == (f_py.nx, f_py.ny),
       (f_np.nx, f_np.ny, f_py.nx, f_py.ny))

    tex = bytes(bytearray((i * 37) % 256 for i in range(w * h * 4)))
    WM.USE_NUMPY = True
    out_np = WM.warp_rgba(tex, w, h, f_last)
    WM.USE_NUMPY = False
    out_py = WM.warp_rgba(tex, w, h, f_py)
    dmax = max(abs(a - b) for a, b in zip(out_np, out_py))
    ndiff = sum(1 for a, b in zip(out_np, out_py) if a != b)
    ok("两路像素最多差 1 级（实测 %d，%d 字节不同）" % (dmax, ndiff),
       dmax <= 1, dmax)
    ok("两路输出长度一致", len(out_np) == len(tex) == len(out_py))
    WM.USE_NUMPY = True
else:
    print("  （没装 numpy，跳过。装上后这两条会自动生效）")

# ---- 12. ARAP --------------------------------------------------------------

section("ARAP：刚性解算")
import arap                                                 # noqa: E402

if arap.available():
    aw, ah = 300, 400
    still = [{"sx": 120, "sy": 160, "dx": 120, "dy": 160}]
    fs = WM.build_field(aw, ah, still, mode="arap", forward=True)
    worst = max(max(abs(v) for v in fs.dx), max(abs(v) for v in fs.dy))
    ok("钉子没拖时位移接近 0（%.3f px）" % worst, worst < 0.1, worst)

    moved = [{"sx": 120, "sy": 160, "dx": 160, "dy": 180}]
    fa = WM.build_field(aw, ah, moved, mode="arap", forward=True)
    gx_, gy_ = fa.sample(120, 160)
    err_pin = math.hypot(gx_ - 40.0, gy_ - 20.0)
    ok("钉子严格跟手（偏差 %.2f px）" % err_pin, err_pin < 1.5, (gx_, gy_))

    far_x, far_y = fa.sample(15, 15)
    far_d = math.hypot(far_x, far_y)
    ok("远处（15,15）基本不动（%.2f px）" % far_d, far_d < 3.0, (far_x, far_y))

    # 保形：同样的强拉伸下，ARAP 的边长畸变应明显小于 MLS 相似
    def edge_dev(field, w, h, cols=10, rows=13):
        devs = []
        for j in range(rows):
            yy = 40 + j * (h - 80) / (rows - 1)
            for i in range(cols - 1):
                x1 = 40 + i * (w - 80) / (cols - 1)
                x2 = 40 + (i + 1) * (w - 80) / (cols - 1)
                a = field.sample(x1, yy)
                b = field.sample(x2, yy)
                l1 = math.hypot((x2 + b[0]) - (x1 + a[0]), b[1] - a[1])
                devs.append(abs(l1 / (x2 - x1) - 1.0))
        devs.sort()
        return devs[len(devs) // 2]

    strong = [{"sx": 100, "sy": 140, "dx": 210, "dy": 150},
              {"sx": 210, "sy": 150, "dx": 100, "dy": 140}]
    d_arap = edge_dev(WM.build_field(aw, ah, strong, mode="arap",
                                     forward=True), aw, ah)
    d_mls = edge_dev(WM.build_field(aw, ah, strong, mode="similarity",
                                    radius=0.6 * aw, forward=True), aw, ah)
    ok("ARAP 边长畸变小于 MLS 相似（%.3f vs %.3f）" % (d_arap, d_mls),
       d_arap < d_mls * 0.5, (d_arap, d_mls))

    t0 = time.time()
    WM.build_field(aw, ah, moved, mode="arap", forward=True)
    first = time.time() - t0
    t0 = time.time()
    for _ in range(3):
        WM.build_field(aw, ah, moved, mode="arap", forward=True)
    cached = (time.time() - t0) / 3.0
    ok("缓存后单次解算够快（首次 %.0f ms，之后 %.0f ms）" %
       (first * 1000, cached * 1000), cached * 1000 < 150.0,
       (first, cached))
    # 只认钉子原位的缓存键：拖动时原位不变，才能一直复用这一次分解
    key = arap._cache_key(aw, ah, fa.nx, fa.ny,
                          [(120.0, 160.0, 160.0, 180.0)])
    ok("分解结果真的进了缓存", key in arap._CACHE)

    # 反向场（真正的变形用这个）：钉子处也要对上
    fb_ = WM.build_field(aw, ah, moved, mode="arap", forward=False)
    bx, by = fb_.sample(160, 180)
    ok("反向场在钉子现位处回到原位（%.2f px 偏差）" %
       math.hypot(160 + bx - 120, 180 + by - 160),
       math.hypot(160 + bx - 120, 180 + by - 160) < 3.0, (bx, by))
else:
    print("  （没装 numpy，ARAP 不可用，跳过）")

# ---- 13. 规模 --------------------------------------------------------------

section("规模：全分辨率够用就行")
big_w, big_h = 1600, 2400
big = bytes(bytearray(big_w * big_h * 4))
bp = [{"sx": 800, "sy": 1200, "dx": 900, "dy": 1260}]
t0 = time.time()
fb = WM.build_field(big_w, big_h, bp, mode="similarity", radius=0.3 * 2400)
field_ms = (time.time() - t0) * 1000.0
ok("1600×2400 解场 < 300 ms（%.0f ms）" % field_ms, field_ms < 300, field_ms)
t0 = time.time()
WM.warp_rgba(big, big_w, big_h, fb)
warp_s = time.time() - t0
warp_limit = 2.5 if WM.have_numpy() else 7.0
ok("1600×2400 局部变形 < %.1f s（%.2f s）" % (warp_limit, warp_s),
   warp_s < warp_limit, warp_s)


print("\n" + "=" * 60)
if FAIL:
    print("失败 %d 项 / 通过 %d 项" % (len(FAIL), PASS))
    for f in FAIL:
        print("  - %s" % f)
    sys.exit(1)
print("全部通过：%d 项检查" % PASS)
