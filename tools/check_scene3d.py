#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""消失点的三维层（反解相机 + 台阶折面）：数学层回归。

跑法：python tools/check_scene3d.py

验的是 _shared/scene3d.py 的**语义**：
  · 由一块平面反解出来的相机，必须和「拍出这块平面的那台相机」一致——
    透视点的三维投影误差应该接近浮点噪声，不是「看着差不多」；
  · 焦距必须由 f² = −(Vu−O)·(Vv−O) 精确复现；
  · 台阶的踏面必须仍然平行于原平面（两组边的消失点不变），
    踢面必须立在法向上（侧棱收敛到 Vw）——这两条错了，楼梯就成了
    一层层贴在画面上的纸片，而 GIMP 不会报任何错；
  · 相邻面片必须严丝合缝（缝不为 0 就是一道道白线）；
  · 整张图沿台阶连续铺开，不是每级各贴一份；
  · 纯 Python 与 numpy 两条路给同一张图。
"""

import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import perspective as P                                      # noqa: E402
import scene3d as S                                          # noqa: E402

PASS = 0
FAIL = []


def ok(label, cond, detail=None):
    global PASS
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL.append(label)
        print("  FAIL %s   %s" % (label, "" if detail is None else detail))


def close(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


# ---- 合成一台真相机 --------------------------------------------------------

W, H = 1200, 900


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def unit(v):
    ln = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / ln for x in v]


def look_at(eye, target):
    f = unit(sub(target, eye))
    r = unit(cross([0.0, 1.0, 0.0], f))
    d = cross(f, r)
    return [r, d, f]


class TrueCam(object):
    def __init__(self, f, eye, target):
        self.f = f
        self.eye = eye
        self.R = look_at(eye, target)

    def project(self, X):
        v = sub(X, self.eye)
        c = [sum(self.R[i][j] * v[j] for j in range(3)) for i in range(3)]
        if c[2] <= 1e-9:
            return None
        return (self.f * c[0] / c[2] + W * 0.5, H * 0.5 - self.f * c[1] / c[2])


def plane_from(cam, pts):
    """把三维四点投到画布上，做成 Plane（点序必须是环序）。"""
    cs = [cam.project(p) for p in pts]
    if any(c is None for c in cs):
        return None
    return P.Plane(cs)


# ---- 1. 反解相机 -----------------------------------------------------------

print("反解相机")
CAM = TrueCam(1000.0, [0.9, 1.7, -1.2], [-0.2, 0.0, 3.2])
FLOOR = lambda s, t: [-2.0 + 4.0 * s, 0.0, 0.6 + 4.0 * t]
pl = plane_from(CAM, [FLOOR(0, 0), FLOOR(1, 0), FLOOR(1, 1), FLOOR(0, 1)])
ok("地板四边形有效", pl.is_valid())

cam = S.camera_from_plane(pl, W, H)
ok("能反解出相机", cam is not None)
ok("焦距精确复现", close(cam.f, CAM.f, 1e-6), "%.6f vs %.6f" % (cam.f, CAM.f))
ok("正方平面的长宽比为 1", close(cam.aspect, 1.0, 1e-9), cam.aspect)
ok("不是近似解", cam.approx is False)
ok("+z 朝相机（相机在平面上方）", cam.toward() is True, cam.eye)

# 三维投影 vs 真相机（z 单位 = 边长 4）
LZ = 4.0
NY = 1.0 if cam.toward() else -1.0
worst = 0.0
for s in (0.0, 0.25, 0.5, 1.0):
    for t in (0.0, 0.5, 1.0):
        for z in (0.0, 0.25, 0.7):
            base = FLOOR(s, t)
            want = CAM.project([base[0], z * LZ * NY, base[2]])
            got = cam.project(s, t, z)
            if want and got:
                worst = max(worst, math.hypot(got[0] - want[0],
                                              got[1] - want[1]))
ok("三维投影与真相机一致", worst < 1e-8, "%.2e px" % worst)

# 焦距的独立验证：随便换几组姿态，f 都必须复现
errs = []
for eye, tgt, f in (([-2.5, 1.2, -2.0], [0.5, 0.2, 4.0], 850.0),
                    ([0.2, 2.6, -3.0], [0.0, 0.0, 2.0], 1400.0),
                    ([3.0, 0.9, -1.0], [-1.0, 0.3, 4.0], 620.0)):
    c2 = TrueCam(f, eye, tgt)
    q = plane_from(c2, [FLOOR(0, 0), FLOOR(1, 0), FLOOR(1, 1), FLOOR(0, 1)])
    cc = S.camera_from_plane(q, W, H)
    errs.append(abs(cc.f - f) if cc else 9e9)
ok("三种姿态的焦距都复现", max(errs) < 1e-5, ["%.2e" % e for e in errs])

# 平行边的矩形：解不出焦距 → 走近似
rect = P.Plane([(200, 200), (800, 200), (800, 560), (200, 560)])
rc = S.camera_from_plane(rect, W, H)
ok("矩形（两边平行）退回正视近似", rc is not None and rc.approx is True,
   None if rc is None else rc.approx)
ok("矩形近似解焦距 = 1.5×长边", close(rc.f, 1800.0, 1e-9), rc.f)
back = [rc.project(s0, t0, 0.0) for (s0, t0) in ((0, 0), (1, 0), (1, 1), (0, 1))]
# 矩形近似：正中间的踢面会侧对相机退化成一条线，必须被丢掉而不是崩
rf, ri = S.stair_faces(rect, W, H, steps=4, rise=0.1, run=0.0)
ok("矩形的台阶不崩（退化面片被丢掉而不是报错）",
   len(rf) > 0 and all(x.is_valid() for x in rf)
   and len(rf) + ri["dropped"] == 2 * ri["steps"],
   (len(rf), ri["dropped"], ri["steps"]))
ok("矩形近似解把四个角投回原处",
   max(math.hypot(a[0] - b[0], a[1] - b[1])
       for a, b in zip(back, rect.corners)) < 1e-9)

# ---- 2. 台阶面片 -----------------------------------------------------------

print("\n台阶几何")
faces, info = S.stair_faces(pl, W, H, steps=6, rise=0.10, run=0.0, edge=2)
ok("面片数 = 2 × 级数（没有退化面片）",
   len(faces) == 2 * info["steps"] == 12 and info["dropped"] == 0,
   (len(faces), info["dropped"]))
ok("全部是凸四边形、面积合理", all(f.is_valid() for f in faces))
ok("run = 0 时铺满整块平面", close(info["run"], 1.0 / 6, 1e-12), info["run"])
ok("总展开长 = 级数 ×(run+rise)",
   close(info["total_v"], 6 * (info["run"] + info["rise"]), 1e-9),
   info["total_v"])
ok("总高 = 级数 × rise", close(info["height"], 6 * 0.10, 1e-12))
ok("踏面/踢面交替", [f.kind for f in faces[:4]] ==
   ["tread", "riser", "tread", "riser"])

seam = 0.0
for k in range(0, len(faces) - 1, 2):
    tr, ri = faces[k], faces[k + 1]
    seam = max(seam,
               math.hypot(tr.quad[3][0] - ri.quad[0][0],
                          tr.quad[3][1] - ri.quad[0][1]),
               math.hypot(tr.quad[2][0] - ri.quad[1][0],
                          tr.quad[2][1] - ri.quad[1][1]))
    if k + 2 < len(faces):
        nx = faces[k + 2]
        seam = max(seam,
                   math.hypot(ri.quad[2][0] - nx.quad[1][0],
                              ri.quad[2][1] - nx.quad[1][1]),
                   math.hypot(ri.quad[3][0] - nx.quad[0][0],
                              ri.quad[3][1] - nx.quad[0][1]))
ok("相邻面片严丝合缝", seam < 1e-9, "%.2e px" % seam)

# 阶梯往上：踏面中心在图像里应逐级升高（y 变小）
ys = [sum(p[1] for p in f.quad) / 4.0 for f in faces if f.kind == "tread"]
ok("踏板逐级升高（图像 y 递减）",
   all(a > b for a, b in zip(ys, ys[1:])), [round(y, 1) for y in ys])

# flip 之后必须反向
faces2, info2 = S.stair_faces(pl, W, H, steps=6, rise=0.10, run=0.0,
                              edge=2, flip=True)
ys2 = [sum(p[1] for p in f.quad) / 4.0 for f in faces2 if f.kind == "tread"]
ok("flip 之后阶梯朝下", all(a < b for a, b in zip(ys2, ys2[1:])))

# ---- 3. 透视一致性（关键：踏面必须还平行于原平面） --------------------------

Vu, Vv = pl.vanish_uv()
Vw = pl.vanish_w(W, H)


def vp_of(q, a0, a1, b0, b1):
    """四边形两组对边的交点（= 那两个方向的消失点）。"""
    return (P.line_intersect(q[a0], q[a1], q[b0], q[b1]),
            P.line_intersect(q[a0], q[b0], q[a1], q[b1]))


def d(a, b):
    if a is None or b is None:
        return 9e9
    return math.hypot(a[0] - b[0], a[1] - b[1])


dev_t = dev_u = dev_w = 0.0
for f in faces:
    p1, p2 = vp_of(f.quad, 0, 1, 3, 2)
    if f.kind == "tread":
        # 踏面：两组边各自平行于平面的 u/v → 消失点必须还是 Vu、Vv
        dev_t = max(dev_t, min(d(p1, Vu), d(p1, Vv)), min(d(p2, Vu), d(p2, Vv)))
    else:
        # 踢面：宽度方向仍是 u（或 v），立起来那条棱必须收敛到 Vw
        dev_u = max(dev_u, min(d(p1, Vu), d(p1, Vv), d(p2, Vu), d(p2, Vv)))
        dev_w = max(dev_w, min(d(p1, Vw), d(p2, Vw)))
ok("踏面仍平行于原平面（消失点不变）",
   dev_t < max(0.05, 1e-9 * max(abs(Vu[0]), abs(Vv[0]))), "%.4f px" % dev_t)
ok("踢面的宽度方向不变", dev_u < max(0.05, 1e-9 * abs(Vu[0])), "%.4f px" % dev_u)
ok("踢面的立柱收敛到法向消失点", dev_w < max(0.05, 1e-9 * abs(Vw[0])),
   "%.4f px（Vw=%s）" % (dev_w, tuple(round(v) for v in Vw)))

# ---- 4. 级数/踏深/朝向 -----------------------------------------------------

print("\n参数")
f3, i3 = S.stair_faces(pl, W, H, steps=20, rise=0.1, run=0.3)
ok("踏深太大自动减级数", i3["steps"] == 3, i3["steps"])
f4, i4 = S.stair_faces(pl, W, H, steps=3, rise=0.1, run=0.0)
ok("级数被尊重（run 自动）", i4["steps"] == 3 and close(i4["run"], 1 / 3, 1e-12))
ok("级数上限截断", S.stair_faces(pl, W, H, steps=99)[1]["steps"] <= S.MAX_STEPS)
for e in range(4):
    fe, ie = S.stair_faces(pl, W, H, steps=4, rise=0.08, run=0.0, edge=e)
    ok("edge=%d 能生成且合法" % e,
       len(fe) == 8 and all(x.is_valid() for x in fe), len(fe))

# ---- 5. 贴图 ---------------------------------------------------------------

print("\n贴图")
SW, SH = 160, 240
src = bytearray(SW * SH * 4)
for y in range(SH):
    for x in range(SW):
        o = (y * SW + x) * 4
        src[o] = int(255 * x / (SW - 1))
        src[o + 1] = int(255 * y / (SH - 1))
        src[o + 2] = 40
        src[o + 3] = 255
src = bytes(src)
canvas = bytes(bytearray(b"\x00\x00\x00\xff" * (W * H)))

t0 = time.time()
out = S.paste_faces(canvas, W, H, src, SW, SH, faces, info["total_v"])
dt = time.time() - t0
ok("贴图返回整幅 RGBA", len(out) == W * H * 4)

def _in_quad(q, x, y):
    """点是否在凸四边形内（同号叉积）。"""
    sign = 0
    for i in range(4):
        ax, ay = q[i]
        bx, by = q[(i + 1) % 4]
        z = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
        if abs(z) < 1e-9:
            continue
        s = 1 if z > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def _edge_dist(q, x, y):
    """点到四边形边界的最短距离（用来容忍 1~2 px 的双线性毛边）。"""
    best = 9e9
    for i in range(4):
        ax, ay = q[i]
        bx, by = q[(i + 1) % 4]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1.0
        t = ((x - ax) * dx + (y - ay) * dy) / L2
        t = min(max(t, 0.0), 1.0)
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best


# 台阶在投影里会自己挡住自己（立起来的踢面盖住后面的踏面），所以判据是
# 「这一点最后被哪块面片画到」——和渲染的顺序完全一致。
worst = 0
checked = 0
for i, f in enumerate(faces):
    M = P.homography(((f.u0, f.v0), (f.u1, f.v0),
                      (f.u1, f.v1), (f.u0, f.v1)), f.quad)
    Mi = P.invert_h(M)
    for (uu, vv) in ((0.5, 0.5), (0.25, 0.3), (0.75, 0.7)):
        u = f.u0 + (f.u1 - f.u0) * uu
        v = f.v0 + (f.v1 - f.v0) * vv
        x, y = P.apply_h_point(M, u, v)
        xi, yi = int(round(x)), int(round(y))
        if not (0 <= xi < W and 0 <= yi < H):
            continue
        # 最后盖住这一点的面
        owner = i
        for j in range(i + 1, len(faces)):
            if _in_quad(faces[j].quad, xi, yi):
                owner = j
        g = faces[owner]
        Mg = g.quad
        Hg = P.homography(((g.u0, g.v0), (g.u1, g.v0),
                          (g.u1, g.v1), (g.u0, g.v1)), Mg)
        ug, vg = P.apply_h_point(P.invert_h(Hg), xi, yi)
        o = (yi * W + xi) * 4
        want_r = int(255 * ug)
        want_g = int(255 * vg / info["total_v"])
        worst = max(worst, abs(out[o] - want_r), abs(out[o + 1] - want_g))
        checked += 1
ok("像素颜色等于它所在面片的 uv（含自遮挡）", worst <= 12,
   "%d 个采样点，最大 %d 色阶" % (checked, worst))

# 连续：沿阶梯走，绿色（v）必须单调增、且跨过大半个动态范围
greens = []
for f in faces:
    uc, vc = 0.5, (f.v0 + f.v1) * 0.5
    M = P.homography(((f.u0, f.v0), (f.u1, f.v0),
                      (f.u1, f.v1), (f.u0, f.v1)), f.quad)
    x, y = P.apply_h_point(M, uc, vc)
    x, y = int(round(x)), int(round(y))
    if 0 <= x < W and 0 <= y < H:
        greens.append(out[(y * W + x) * 4 + 1])
ok("整张图沿台阶连续（不是每级各贴一份）",
   all(b >= a - 2 for a, b in zip(greens, greens[1:]))
   and greens[-1] - greens[0] > 80,
   greens)

# 平面外一个字节都不能动
outside = 0
for y in range(0, H, 7):
    for x in range(0, W, 7):
        o = (y * W + x) * 4
        if out[o:o + 3] == b"\x00\x00\x00":
            continue
        if not any(_in_quad(f.quad, x, y) or _edge_dist(f.quad, x, y) <= 2.0
                   for f in faces):
            outside += 1
ok("台阶之外的像素不动", outside == 0, outside)

# 两路一致
P.USE_NUMPY = False
out_py = S.paste_faces(canvas, W, H, src, SW, SH, faces, info["total_v"])
P.USE_NUMPY = True
diff = max(abs(a - b) for a, b in zip(out, out_py))
ok("纯 Python 与 numpy 贴图一致", diff <= 1, diff)
ok("numpy 贴图够快（%d 面 %.0f ms）" % (len(faces), dt * 1000), dt < 2.0)

# ---- 6. 序列化 -------------------------------------------------------------

print("\n参数串")
for st in ({"on": True, "edge": 2, "steps": 7, "rise": 0.08, "run": 0.2,
            "flip": True},
           {"on": True, "edge": 0, "steps": 1, "rise": 0.01, "run": 0.0,
            "flip": False}):
    s = S.format_stair_string(st)
    back = S.parse_stair_string(s)
    ok("往返：%s" % s,
       back["on"] and back["edge"] == st["edge"] and back["steps"] == st["steps"]
       and close(back["rise"], st["rise"], 1e-6)
       and close(back["run"], st["run"], 1e-6)
       and back["flip"] == st["flip"], back)
ok("空串 = 不开台阶", S.parse_stair_string("")["on"] is False)
ok("烂串不抛异常", S.parse_stair_string("a,b,c")["on"] is False)


print("\n" + "=" * 60)
if FAIL:
    print("失败 %d 项 / 通过 %d 项" % (len(FAIL), PASS))
    for f in FAIL:
        print("  - %s" % f)
    sys.exit(1)
print("全部通过：%d 项检查" % PASS)
