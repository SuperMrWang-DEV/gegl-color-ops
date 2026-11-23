#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""消失点（透视平面）：数学层回归（不需要 GIMP、不需要显卡）。

跑法：python tools/check_perspective.py

这里验的是 _shared/perspective.py 的**语义**：
  · 4 点单应必须严格插值四个角（差一点就是整幅贴图错位）；
  · 三个互垂方向的消失点必须构成「以主点为垂心」的三角形——
    这一条错了，第二面墙就会贴到第一面墙自己身上；
  · 网格必须真的经过平面四角，而且不能在「地平线之后」连出假线；
  · 透视贴图只动平面内部，外面一个字节都不能变；
  · 拉正和贴图必须互逆（不然「贴上去再拉下来」就是两张图）；
  · 从边延伸出来的平面必须保持透视（两条边都收敛到对应的消失点）；
  · 纯 Python 与 numpy 两条路给同一张图。

这些错了 GIMP 不会报错，只会给你一张「看着怪怪的」图。
"""

import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import perspective as P                                      # noqa: E402

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


# ---- 合成相机：造一个「真」的透视场景 ---------------------------------------

def _rot(ax, ay, az):
    ca, sa = math.cos(ax), math.sin(ax)
    cb, sb = math.cos(ay), math.sin(ay)
    cc, sc = math.cos(az), math.sin(az)
    Rx = [[1, 0, 0], [0, ca, -sa], [0, sa, ca]]
    Ry = [[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]]
    Rz = [[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]]

    def mm(A, B):
        return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)]
                for i in range(3)]
    return mm(Rz, mm(Ry, Rx))


def _project(K, R, t, X):
    v = [sum(R[i][j] * X[j] for j in range(3)) + t[i] for i in range(3)]
    p = [K[i][0] * v[0] + K[i][1] * v[1] + K[i][2] * v[2] for i in range(3)]
    if abs(p[2]) < 1e-12:
        return None
    return (p[0] / p[2], p[1] / p[2])


def _dir_pixel(K, R, d):
    v = [sum(R[i][j] * d[j] for j in range(3)) for i in range(3)]
    p = [K[i][0] * v[0] + K[i][1] * v[1] + K[i][2] * v[2] for i in range(3)]
    if abs(p[2]) < 1e-12:
        return None
    return (p[0] / p[2], p[1] / p[2])


W, H = 1200, 900
CX, CY = W / 2.0, H / 2.0


def make_scene(f, ax, ay, az, tx, ty, tz):
    K = [[f, 0, CX], [0, f, CY], [0, 0, 1]]
    R = _rot(ax, ay, az)
    t = [tx, ty, tz]
    rect = [(-1.5, -1.0, 0.0), (1.5, -1.0, 0.0),
            (1.5, 1.0, 0.0), (-1.5, 1.0, 0.0)]
    cs = [_project(K, R, t, p) for p in rect]
    if any(c is None for c in cs):
        return None
    return K, R, t, cs


# ---- 1. 单应 ---------------------------------------------------------------

section("单应")

pl = P.Plane([(100, 120), (900, 80), (1020, 700), (60, 780)])
Hm = pl.H()
worst = 0.0
for i, (u, v) in enumerate(P.UNIT4):
    X, Y = P.apply_h_point(Hm, u, v)
    worst = max(worst, math.hypot(X - pl.corners[i][0], Y - pl.corners[i][1]))
ok("四角被严格插值（残差 < 1e-9 px）", worst < 1e-9, "%.2e" % worst)

Hi = pl.Hinv()
worst = 0.0
for (u, v), c in zip(P.UNIT4, pl.corners):
    s, t = P.apply_h_point(Hi, c[0], c[1])
    worst = max(worst, math.hypot(s - u, t - v))
ok("逆单应把图上的角送回 (0,0)…(1,1)", worst < 1e-9, "%.2e" % worst)

# 世界里的正方形四边等长 → 图像上四角连起来仍是四边形；
# 关键是「直线还是直线」：世界直线中点的像必须等于两端点像的中点吗？不，
# 射影变换保直线不保比例。所以验「世界线上三点共线 → 像也共线」。
a = P.apply_h_point(Hm, 0.2, 0.0)
b = P.apply_h_point(Hm, 0.8, 0.0)
m = P.apply_h_point(Hm, 0.5, 0.0)
cross = (b[0] - a[0]) * (m[1] - a[1]) - (b[1] - a[1]) * (m[0] - a[0])
ok("直线还是直线（三点共线）", abs(cross) < 1e-6, "%.2e" % cross)

# 归一化到底有没有用：原始像素直接解 8x8 与 Hartley 版比较
raw_src = [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]
raw_dst = [(80, 60), (920, 20), (980, 960), (40, 900)]
h_direct = P.homography(raw_src, raw_dst)
err = 0.0
for (x, y), (X, Y) in zip(raw_src, raw_dst):
    px, py = P.apply_h_point(h_direct, x, y)
    err = max(err, math.hypot(px - X, py - Y))
ok("四点单应（大坐标）仍精确", err < 1e-8, "%.2e" % err)


# ---- 2. 消失点：主点是三个消失点三角形的垂心 --------------------------------

section("消失点（用真 3D 场景反推）")

random.seed(20261123)
max_u = max_v = max_w = 0.0
count = 0
samples = []
for _ in range(80):
    sc = make_scene(random.uniform(700, 1600),
                    random.uniform(-0.7, 0.7),
                    random.uniform(-0.7, 0.7),
                    random.uniform(-0.5, 0.5),
                    random.uniform(-3, 3), random.uniform(-3, 3),
                    random.uniform(6, 14))
    if sc is None:
        continue
    K, R, t, cs = sc
    q = P.Plane(cs)
    if not q.is_valid():
        continue
    Vu, Vv = q.vanish_uv()
    tu = _dir_pixel(K, R, (1, 0, 0))
    tv = _dir_pixel(K, R, (0, 1, 0))
    tw = _dir_pixel(K, R, (0, 0, 1))
    if Vu is None or Vv is None or tw is None:
        continue
    Vw = P.third_vanish(Vu, Vv, CX, CY)
    if Vw is None:
        continue
    count += 1
    eu = math.hypot(Vu[0] - tu[0], Vu[1] - tu[1])
    ev = math.hypot(Vv[0] - tv[0], Vv[1] - tv[1])
    ew = math.hypot(Vw[0] - tw[0], Vw[1] - tw[1])
    max_u, max_v, max_w = max(max_u, eu), max(max_v, ev), max(max_w, ew)
    if len(samples) < 3:
        samples.append((Vu, Vv, Vw, tu, tv, tw))

ok("样本够多（%d 个场景）" % count, count >= 40, count)
ok("平面 u 方向的消失点 = 真实消失点", max_u < 1e-6, "%.3e px" % max_u)
ok("平面 v 方向的消失点 = 真实消失点", max_v < 1e-6, "%.3e px" % max_v)
ok("垂心法求出的第三方向消失点 = 真实消失点", max_w < 1e-6, "%.3e px" % max_w)

for i, (Vu, Vv, Vw, tu, tv, tw) in enumerate(samples):
    print("     样本 %d：Vu(%.1f,%.1f) Vv(%.1f,%.1f) Vw(%.1f,%.1f)"
          % (i, Vu[0], Vu[1], Vv[0], Vv[1], Vw[0], Vw[1]))

# 垂心关系本身：三角形 Vu Vv Vw 的三条高必须都过主点
if samples:
    Vu, Vv, Vw = samples[0][0], samples[0][1], samples[0][2]
    # 垂心：主点 O 满足 (Vu−O)⊥(Vv−Vw) 且 (Vv−O)⊥(Vu−Vw)
    o = (CX, CY)
    t1 = (Vu[0] - o[0]) * (Vv[0] - Vw[0]) + (Vu[1] - o[1]) * (Vv[1] - Vw[1])
    t2 = (Vv[0] - o[0]) * (Vu[0] - Vw[0]) + (Vv[1] - o[1]) * (Vu[1] - Vw[1])
    scale = max(1.0, math.hypot(*Vw) * math.hypot(*Vv))
    ok("三角形 VuVvVw 的垂心就是主点（两个点积为 0）",
       abs(t1) / scale < 1e-6 and abs(t2) / scale < 1e-6,
       "%.2e / %.2e" % (abs(t1) / scale, abs(t2) / scale))

# 平行投影（无透视）时不该硬造消失点
flat = P.Plane([(100, 100), (500, 100), (500, 400), (100, 400)])
Vu, Vv = flat.vanish_uv()
ok("轴对齐矩形没有消失点（返回 None 而不是编一个）",
   Vu is None and Vv is None, (Vu, Vv))
ok("没有消失点时第三方向也返回 None",
   P.third_vanish(Vu, Vv, CX, CY) is None)


# ---- 3. 透视网格 -----------------------------------------------------------

section("透视网格")

sc = make_scene(1000.0, 0.15, -0.35, 0.1, 0.5, -0.3, 9.0)
plane = P.Plane(sc[3])
lines = plane.grid_lines(steps=4, reach=1.0)
ok("网格有折线（%d 条）" % len(lines), len(lines) >= 8, len(lines))

# 每条折线都必须落在画布附近，不能有横穿画面的假线
maxlen = 0.0
for ln in lines:
    xs = [p[0] for p in ln]
    ys = [p[1] for p in ln]
    maxlen = max(maxlen, math.hypot(max(xs) - min(xs), max(ys) - min(ys)))
ok("没有越过地平线的假线段（最长段 %.0f px）" % maxlen, maxlen < 6000.0)

# 世界 s=0 与 t=0 的两条线必须过 corners[0]。
# 采样点不会正好落在角上，所以量「点到折线各段」的距离。
def _pt_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2
    t = min(max(t, 0.0), 1.0)
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


hit0 = 1e9
c0 = plane.corners[0]
for ln in lines:
    for i in range(len(ln) - 1):
        hit0 = min(hit0, _pt_seg(c0, ln[i], ln[i + 1]))
ok("网格线穿过平面的角点", hit0 < 0.5, "%.2f px" % hit0)

# 网格是「世界里等距」：s=0.25 与 s=0.5 两条线，在图像上间距应被透视压缩
def _line_at(s, samples=40):
    pts = []
    for j in range(samples + 1):
        t = -0.2 + 1.4 * j / float(samples)
        X, Y, ww = P.apply_h(plane.H(), s, t)
        if ww > P.W_EPS and math.isfinite(X) and math.isfinite(Y):
            pts.append((X, Y))
    return pts


l25 = _line_at(0.25)
l50 = _line_at(0.50)
mid25 = l25[len(l25) // 2]
mid50 = l50[len(l50) // 2]
ok("网格线在图像上确实分开（有透视量）",
   math.hypot(mid25[0] - mid50[0], mid25[1] - mid50[1]) > 2.0)


# ---- 4. 透视贴图 -----------------------------------------------------------

section("透视贴图")

sw, sh = 160, 120
src = bytearray(sw * sh * 4)
for y in range(sh):
    for x in range(sw):
        o = (y * sw + x) * 4
        src[o] = int(255 * x / (sw - 1))
        src[o + 1] = int(255 * y / (sh - 1))
        src[o + 2] = 128
        src[o + 3] = 255
src = bytes(src)

BG = (30, 30, 40, 255)
canvas = bytes(bytearray(bytes(BG) * (W * H)))
t0 = time.time()
pasted = P.paste_into(canvas, W, H, src, sw, sh, pl.corners)
dt = time.time() - t0
ok("贴图返回同样大小的 RGBA", len(pasted) == W * H * 4)

# 平面内部：颜色必须对得上源图
bad = 0
for t in [i / 20.0 for i in range(1, 20)]:
    for s in [i / 20.0 for i in range(1, 20)]:
        X, Y = P.apply_h_point(pl.H(), s, t)
        o = (int(Y) * W + int(X)) * 4
        exp = (int(255 * s), int(255 * t), 128)
        if max(abs(pasted[o + i] - exp[i]) for i in range(3)) > 6:
            bad += 1
ok("平面内部的像素来自源图的对应位置", bad == 0, "%d/361 超差" % bad)

# 平面外：一个字节都不能动。pad 是**往外扩**（正数），用来跳过边界上
# 双线性那 1~2 px 的过渡——扩张后仍在外面的，才算真的「平面外」。
outside_bad = 0
for y in range(0, H, 7):
    for x in range(0, W, 7):
        if not pl.contains(x, y, pad=0.01):
            o = (y * W + x) * 4
            if pasted[o:o + 4] != bytes(BG):
                outside_bad += 1
ok("平面外完全没动（%d 个取样点）" % (len(range(0, H, 7)) * len(range(0, W, 7))),
   outside_bad == 0, outside_bad)

# 源 alpha=0 的地方不能盖住底图
half = bytearray(src)
for y in range(sh):
    for x in range(sw // 2):
        half[(y * sw + x) * 4 + 3] = 0
half = bytes(half)
mixed = P.paste_into(canvas, W, H, half, sw, sh, pl.corners)
X, Y = P.apply_h_point(pl.H(), 0.2, 0.5)
o = (int(Y) * W + int(X)) * 4
ok("源图透明的地方透出底图（alpha 混合）",
   mixed[o:o + 4] == bytes(BG), list(mixed[o:o + 4]))

print("     贴图 1200×900 用时 %.0f ms" % (dt * 1000))


# ---- 5. 拉正 ---------------------------------------------------------------

section("拉正")

ow, oh = P.rectify_size(pl.corners)
ok("拉正尺寸来自四边形边长", ow > 100 and oh > 100, (ow, oh))
back = P.rectify(pasted, W, H, pl.corners, ow, oh)
ok("拉正返回 ow×oh×4", len(back) == ow * oh * 4)

worst = 0
for y in range(6, oh - 6, 3):
    for x in range(6, ow - 6, 3):
        sx = min(sw - 1, int(x * sw / ow))
        sy = min(sh - 1, int(y * sh / oh))
        a = src[(sy * sw + sx) * 4:(sy * sw + sx) * 4 + 3]
        o = (y * ow + x) * 4
        worst = max(worst, max(abs(a[i] - back[o + i]) for i in range(3)))
ok("贴上去再拉下来 ≈ 原图（最大通道差 %d）" % worst, worst <= 6, worst)

# 拉正必须真的把透视拉平：源图左边的竖线在输出里也必须是竖线
def _edge_x(t):
    """输出里第 t 行第一个不透明像素的 x。"""
    y = int(t * (oh - 1))
    for x in range(ow):
        if back[(y * ow + x) * 4 + 3] > 0:
            return x
    return -1


x1, x2 = _edge_x(0.15), _edge_x(0.85)
ok("拉正后左右两边是竖直的（上下两处边缘 x 差 < 2 px）",
   x1 >= 0 and abs(x1 - x2) <= 2, (x1, x2))

# 输出尺寸和四边形形状有关，不能是常数
pl2 = P.Plane([(100, 100), (600, 100), (600, 500), (100, 500)])
ok("不同四边形给出不同拉正尺寸",
   P.rectify_size(pl2.corners) != (ow, oh),
   (P.rectify_size(pl2.corners), (ow, oh)))


# ---- 6. 延伸平面 -----------------------------------------------------------

section("沿边延伸相邻平面")

sc = make_scene(1000.0, 0.1, -0.4, 0.05, 0.4, -0.2, 9.0)
base = P.Plane(sc[3])
Vu, Vv = base.vanish_uv()
Vw = base.vanish_w(W, H)
ok("基础平面有效且三个消失点都在", base.is_valid() and Vw is not None)

for side in range(4):
    ext = base.extend(side, along="w", amount=0.6, w=W, h=H)
    p0, p1 = base.edge(side)
    same = (abs(ext.corners[0][0] - p0[0]) < 1e-9 and
            abs(ext.corners[0][1] - p0[1]) < 1e-9 and
            abs(ext.corners[1][0] - p1[0]) < 1e-9 and
            abs(ext.corners[1][1] - p1[1]) < 1e-9)
    ok("第 %d 条边延伸出的平面与它严格共用这条边" % side, same)
    ok("第 %d 条边延伸出的平面是凸四边形" % side, ext.is_valid())

ext = base.extend(1, along="w", amount=0.6, w=W, h=H)
q0, q1 = ext.corners[3], ext.corners[2]
# q0 必须落在 p0→Vw 的直线上（深度线指向垂直消失点）
d0 = abs((q0[0] - base.corners[1][0]) * (Vw[1] - base.corners[1][1]) -
         (q0[1] - base.corners[1][1]) * (Vw[0] - base.corners[1][0]))
d0 /= max(1e-9, math.hypot(Vw[0] - base.corners[1][0],
                           Vw[1] - base.corners[1][1]))
ok("新平面的深度线指向垂直消失点（残差 < 0.01 px）", d0 < 0.01, "%.2e" % d0)

# q1 必须落在「过 q0 与共享边方向消失点」的直线上
d1 = abs((q1[0] - q0[0]) * (Vv[1] - q0[1]) - (q1[1] - q0[1]) * (Vv[0] - q0[0]))
d1 /= max(1e-9, math.hypot(Vv[0] - q0[0], Vv[1] - q0[1]))
ok("新平面的另一条边收敛到共享边方向的消失点（残差 < 0.01 px）",
   d1 < 0.01, "%.2e" % d1)

# 同一 t 的偷懒写法会得到平行边 —— 这里确认我们没犯
d01 = (base.corners[1][0] - base.corners[0][0],
       base.corners[1][1] - base.corners[0][1])
d23 = (q1[0] - q0[0], q1[1] - q0[1])
cross = abs(d01[0] * d23[1] - d01[1] * d23[0])
ok("两条边不平行（否则等于丢了透视）", cross > 1e-3, "%.4f" % cross)

# 同向延伸：新平面的 u 方向消失点应等于原平面的 v 方向消失点
ext_v = base.extend(1, along="v", amount=0.6, w=W, h=H)
eu, ev = ext_v.vanish_uv()
dv = math.hypot(eu[0] - Vv[0], eu[1] - Vv[1]) if (eu and Vv) else 1e9
ok("同向延伸的平面共享同一个消失点", dv < 1e-6, "%.2e px" % dv)

# 平行投影（没有消失点）时退化成平移，不能抛
flat_plane = P.Plane([(100, 100), (500, 100), (500, 400), (100, 400)])
fe = flat_plane.extend(1, along="w", amount=0.6, w=W, h=H)
ok("没有消失点时按法向平移兜底（不抛异常、仍是凸的）",
   fe.is_valid(), [tuple(c) for c in fe.corners])


# ---- 7. 双路一致 -----------------------------------------------------------

section("纯 Python / numpy 双路一致")

P.USE_NUMPY = True
p_np = P.paste_into(canvas, W, H, src, sw, sh, pl.corners)
r_np = P.rectify(p_np, W, H, pl.corners, ow, oh)
t0 = time.time()
p_np2 = P.paste_into(canvas, W, H, src, sw, sh, pl.corners)
dt_np = time.time() - t0
P.USE_NUMPY = False
t0 = time.time()
p_py = P.paste_into(canvas, W, H, src, sw, sh, pl.corners)
dt_py = time.time() - t0
r_py = P.rectify(p_py, W, H, pl.corners, ow, oh)
P.USE_NUMPY = True

diff = max(abs(a - b) for a, b in zip(p_np, p_py))
ok("贴图两路最大差 ≤ 1", diff <= 1, diff)
diff = max(abs(a - b) for a, b in zip(r_np, r_py))
ok("拉正两路最大差 ≤ 1", diff <= 1, diff)
print("     贴图 numpy %.0f ms / 纯 Python %.0f ms" % (dt_np * 1000, dt_py * 1000))


# ---- 8. 序列化与校验 -------------------------------------------------------

section("序列化与校验")

s = P.format_plane_string([pl, ext])
back_planes = P.parse_plane_string(s, W, H)
ok("平面串往返得到同样多的平面", len(back_planes) == 2, len(back_planes))
worst = 0.0
for a, b in zip([pl, ext], back_planes):
    for i in range(4):
        worst = max(worst, abs(a.corners[i][0] - b.corners[i][0]),
                    abs(a.corners[i][1] - b.corners[i][1]))
ok("往返角点误差 < 0.01 px（两位小数）", worst < 0.01, "%.4f" % worst)

ok("空串解析成空列表", P.parse_plane_string("") == [])
ok("乱七八糟的串不抛异常", P.parse_plane_string("abc|;;|1,2") == [])
three = P.parse_plane_string("10,10,100,10,100,100", W, H)
ok("只给三个角时第四角补成平行四边形",
   len(three) == 1 and abs(three[0].corners[3][0] - 10.0) < 1e-6)

orig = P.default_quad(W, H)
ok("默认平面是有效凸四边形", orig.is_valid())

tiny = P.Plane([(10, 10), (12, 10), (12, 12), (10, 12)])
ok("太小的四边形被判为无效", not tiny.is_valid())

concave = P.Plane([(0, 0), (400, 0), (200, 120), (0, 300)])
ok("凹四边形被判为无效", not concave.is_valid())

ok("凸性检查不吃轴对齐矩形",
   P.Plane([(0, 0), (10, 0), (10, 10), (0, 10)]).is_valid())

summary = P.plane_summary([pl, ext], W, H)
ok("摘要里有平面数、消失点和拉正尺寸",
   summary["count"] == 2 and summary["valid"] == 2
   and summary["rectified"] is not None)


print("\n" + "=" * 60)
if FAIL:
    print("失败 %d 项 / 通过 %d 项" % (len(FAIL), PASS))
    for f in FAIL:
        print("  - %s" % f)
    sys.exit(1)
print("全部通过：%d 项检查" % PASS)
