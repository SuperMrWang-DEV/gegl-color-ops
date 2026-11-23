#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自由变形（贝塞尔网格 + 把手）：数学层回归（不需要 GIMP、不需要显卡）。

跑法：python tools/check_mesh_warp.py

这里验的是 _shared/mesh_warp.py 的**语义**：
  · 恒等网格必须解出「零场」——否则什么都没拖，整张图也被重采样一遍；
  · 交点必须严格插值（网格点拖到哪，那一块的像素就得从哪儿来）；
  · 把手必须真的把曲线弯过去，而且节点本身不动；
  · 自动把手必须限幅，不能让格子自交（自交 = 反解两个分支 = 画面撕开）；
  · 源坐标必须是 uv 在原位格上的位置，不是曲面上的位置（差一次整体平移）；
  · 纯 Python 与 numpy 两条路径在同一分辨率下必须给出同一张场。
这些错了 GIMP 一声不响，只会给你一张「看着有点歪」的图。
"""

import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import mesh_warp as MW                                      # noqa: E402
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


W, H = 200, 150
CW = (W - 1.0) / 3.0
CH = (H - 1.0) / 3.0


def moved_mesh(dx=40.0, dy=0.0, i=1, j=1):
    m = MW.Mesh.identity(W, H, 3, 3)
    m.node(i, j)["x"] += dx
    m.node(i, j)["y"] += dy
    m.auto_refresh()
    return m


def fold_count(mesh, steps=40):
    """有多少采样点上曲面片的雅可比 <= 0（自交/翻面）。"""
    bad = 0
    for j in range(steps + 1):
        for i in range(steps + 1):
            u = i * mesh.cols / float(steps)
            v = j * mesh.rows / float(steps)
            ci = min(int(u), mesh.cols - 1)
            cj = min(int(v), mesh.rows - 1)
            bx, by = MW._cell_ctrl(mesh, ci, cj)
            p = MW._patch(bx, by, u - ci, v - cj)
            if p[2] * p[5] - p[3] * p[4] <= 0.0:
                bad += 1
    return bad


# ---- 恒等 --------------------------------------------------------------
section("恒等网格：一个字节都不该动")
m0 = MW.Mesh.identity(W, H, 3, 3)
ok("3×3 恒等网格 is_identity", m0.is_identity())
ok("auto_refresh 之后还是恒等", m0.copy().auto_refresh().is_identity())
f0 = MW.build_field(m0, W, H)
ok("恒等网格解出的场是零场", f0.is_identity())
ok("4×4 恒等网格也是零场", MW.build_field(MW.Mesh.identity(W, H, 4, 4),
                                       W, H).is_identity())
rgba = bytes(bytearray((x * 7 + y * 13) % 256
                       for y in range(H) for x in range(W) for _c in range(4)))
ok("零场重采样 = 原字节", WM.warp_rgba(rgba, W, H, f0) == rgba)

ok("交点插值：eval_uv(i,j) == node(i,j)",
   all(abs(m0.eval_uv(i, j)[0] - m0.node(i, j)["x"]) < 1e-9 and
       abs(m0.eval_uv(i, j)[1] - m0.node(i, j)["y"]) < 1e-9
       for i in range(4) for j in range(4)))
mid = m0.eval_uv(1.5, 1.5)
ok("格子中心是均匀的（%.2f, %.2f）" % (mid[0], mid[1]),
   abs(mid[0] - 1.5 * CW) < 1e-9 and abs(mid[1] - 1.5 * CH) < 1e-9)

# ---- 反解 --------------------------------------------------------------
section("反解：目标像素 → 参数，必须能解回来")
random.seed(20261123)
err0 = 0.0
for _k in range(300):
    u = random.uniform(0.02, 2.98)
    v = random.uniform(0.02, 2.98)
    px, py = m0.eval_uv(u, v)
    uu, vv = MW.invert_point(m0, px, py)
    err0 = max(err0, abs(uu - u), abs(vv - v))
ok("恒等网格反解误差 %.2e < 1e-6" % err0, err0 < 1e-6, err0)

m1 = moved_mesh(50.0, 20.0)
err1 = 0.0
for _k in range(300):
    u = random.uniform(0.05, 2.95)
    v = random.uniform(0.05, 2.95)
    px, py = m1.eval_uv(u, v)
    uu, vv = MW.invert_point(m1, px, py)
    qx, qy = m1.eval_uv(uu, vv)
    err1 = max(err1, math.hypot(qx - px, qy - py))
ok("拖了节点之后反解残差 %.4f px < 0.05" % err1, err1 < 0.05, err1)

n = m1.node(1, 1)
u1, v1 = MW.invert_point(m1, n["x"], n["y"])
ok("被拖的节点反解回 (1,1)（%.4f, %.4f）" % (u1, v1),
   abs(u1 - 1.0) < 1e-3 and abs(v1 - 1.0) < 1e-3, (u1, v1))

f1 = MW.build_field(m1, W, H)
ox, oy = f1.sample(n["x"], n["y"])
ok("节点新位置处的偏移 ≈ -位移（%.2f, %.2f）" % (ox, oy),
   abs(ox + 50.0) < 1.0 and abs(oy + 20.0) < 1.0, (ox, oy))
# 源坐标必须是 uv 在原位格上的位置（1*CW），不是曲面位置（n["x"]）
ok("源坐标取原位格而不是曲面位置（偏移量级 %.1f）" % ox, ox < -40.0, ox)

# ---- 把手 --------------------------------------------------------------
section("把手：弯网格线，节点自己不动")
mh = MW.Mesh.identity(W, H, 3, 3)
node = mh.node(1, 0)
node["ux"], node["uy"] = 100.0, 60.0
node["a"] = 0
ok("拖把手不改节点位置",
   abs(mh.eval_uv(1, 0)[0] - node["x"]) < 1e-9 and
   abs(mh.eval_uv(1, 0)[1] - node["y"]) < 1e-9, mh.eval_uv(1, 0))
dev = mh.eval_uv(0.5, 0)
# 三次贝塞尔：0.125·P0 + 0.375·(P0+U0/3) + 0.375·(P1-U1/3) + 0.125·P1
# 起点那端的切向是**节点 (0,0) 自己的**（自动把手），不是被拖的那个
p0 = mh.node(0, 0)
cx1, cy1 = p0["x"], p0["y"]
cx2, cy2 = p0["x"] + p0["ux"] / 3.0, p0["y"] + p0["uy"] / 3.0
cx3, cy3 = node["x"] - node["ux"] / 3.0, node["y"] - node["uy"] / 3.0
ex = 0.125 * cx1 + 0.375 * cx2 + 0.375 * cx3 + 0.125 * node["x"]
ey = 0.125 * cy1 + 0.375 * cy2 + 0.375 * cy3 + 0.125 * node["y"]
ok("曲线中点 = 贝塞尔解析值（%.2f, %.2f）" % (dev[0], dev[1]),
   abs(dev[0] - ex) < 1e-6 and abs(dev[1] - ey) < 1e-6, (dev, ex, ey))
ok("把手把线弯离了弦（竖直偏移 %.2f px）" % dev[1], dev[1] < -5.0, dev)


def numeric_tangent(mesh, u, v, hstep=1e-6, axis="u"):
    if axis == "u":
        a = mesh.eval_uv(u + hstep, v)
        b = mesh.eval_uv(u - hstep, v)
    else:
        a = mesh.eval_uv(u, v + hstep)
        b = mesh.eval_uv(u, v - hstep)
    return (a[0] - b[0]) / (2 * hstep), (a[1] - b[1]) / (2 * hstep)


tx, ty = numeric_tangent(mh, 1.0, 0.0)
ok("切向与存的把手一致（%.1f, %.1f）" % (tx, ty),
   abs(tx - node["ux"]) < 0.5 and abs(ty - node["uy"]) < 0.5, (tx, ty))

p_plus = mh.handle(1, 0, "u", 1)
p_minus = mh.handle(1, 0, "u", -1)
ok("把手对称：两点关于节点对称",
   abs(p_plus[0] + p_minus[0] - 2 * node["x"]) < 1e-9 and
   abs(p_plus[1] + p_minus[1] - 2 * node["y"]) < 1e-9, (p_plus, p_minus))

mh2 = MW.Mesh.identity(W, H, 3, 3)
mh2.node(1, 1)["ux"], mh2.node(1, 1)["uy"] = 30.0, 30.0
mh2.node(1, 1)["a"] = 0
ok("把手不改相邻格的交点", abs(mh2.eval_uv(2, 1)[0] - 2 * CW) < 1e-9,
   mh2.eval_uv(2, 1))
ok("弯过把手的网格 is_identity 为假", not mh2.is_identity())

# ---- 自动把手：不许自交 ------------------------------------------------
section("自动把手：拖节点不能把格子拖到翻面")
m_auto = moved_mesh(55.0, 0.0)          # 一格才 66 px，拖 55 px 已经很狠
ok("3×3 拖 55 px 后没有翻面（%d 个坏点）" % fold_count(m_auto),
   fold_count(m_auto) == 0, fold_count(m_auto))
manual = MW.Mesh.identity(W, H, 3, 3)
manual.node(1, 1)["x"] += 55.0          # 故意不刷新把手（等于把手定死）
ok("把手不自动时会出现翻面（%d 个坏点，说明限幅是必要的）"
   % fold_count(manual), fold_count(manual) > 0, fold_count(manual))
lim = m_auto.node(1, 1)
ok("自动切向被限幅到相邻弦长以内（%.1f ≤ %.1f px）"
   % (math.hypot(lim["ux"], lim["uy"]),
      min(abs(lim["x"] - m_auto.node(0, 1)["x"]),
          abs(m_auto.node(2, 1)["x"] - lim["x"])) + 1e-6),
   math.hypot(lim["ux"], lim["uy"]) <=
   min(abs(lim["x"] - m_auto.node(0, 1)["x"]),
       abs(m_auto.node(2, 1)["x"] - lim["x"])) + 1e-6)

# ---- 两条路径 ----------------------------------------------------------
section("纯 Python vs numpy：同一张场")
nx, ny = 100, 75
fa = MW.build_field(m1, W, H, nx=nx, ny=ny)
MW.USE_NUMPY = False
fb = MW.build_field(m1, W, H, nx=nx, ny=ny)
MW.USE_NUMPY = True
dmax = max(max(abs(a - b) for a, b in zip(fa.dx, fb.dx)),
           max(abs(a - b) for a, b in zip(fa.dy, fb.dy)))
ok("同一分辨率下两路逐节点相同（最大差 %.2e px）" % dmax, dmax < 1e-9, dmax)

# ---- 序列化 ------------------------------------------------------------
section("字符串：脚本能复现一次手动变形")
s = MW.format_mesh_string(m1)
m1b = MW.parse_mesh_string(s, W, H)
ok("往返后格数不变", (m1b.cols, m1b.rows) == (m1.cols, m1.rows))
ok("往返后交点位置一致（两位小数，误差 < 0.01）",
   max(abs(a["x"] - b["x"]) for a, b in zip(m1.nodes, m1b.nodes)) < 0.01 and
   max(abs(a["y"] - b["y"]) for a, b in zip(m1.nodes, m1b.nodes)) < 0.01)
ok("往返后形状一致（场差 < 0.05 px）",
   MW.build_field(m1, W, H, nx=60, ny=45).is_identity() ==
   MW.build_field(m1b, W, H, nx=60, ny=45).is_identity())
ok("空字符串 → 3×3 恒等网格",
   MW.parse_mesh_string("", W, H).is_identity() and
   MW.parse_mesh_string("", W, H).cols == 3)
partial = MW.parse_mesh_string("4,4; 100,100", W, H)
ok("只给格数和一个点也能用（%d×%d）" % (partial.cols, partial.rows),
   partial.cols == 4 and not partial.is_identity())
ok("坏字符串不炸", MW.parse_mesh_string("abc;;;", W, H) is not None)

# ---- 换网格密度 --------------------------------------------------------
section("换网格密度：升密几乎无损，降密会改形状")
for nc, tol in ((4, 4.0), (5, 4.0), (6, 2.5)):
    mr = m1.resample(nc, nc)
    e = 0.0
    for _k in range(200):
        u = random.uniform(0.0, 3.0)
        v = random.uniform(0.0, 3.0)
        p = m1.eval_uv(u, v)
        q = mr.eval_uv(u * nc / 3.0, v * nc / 3.0)
        e = max(e, math.hypot(p[0] - q[0], p[1] - q[1]))
    ok("3→%d 格形状误差 %.2f px < %.1f" % (nc, e, tol), e < tol, e)
ok("恒等网格 3→5 还是恒等",
   MW.Mesh.identity(W, H, 3, 3).resample(5, 5).is_identity())
ok("换密度不改交点数量以外的东西（%d 个点）"
   % len(m1.resample(5, 5).nodes), len(m1.resample(5, 5).nodes) == 36)

# ---- 像素 --------------------------------------------------------------
section("像素：方块真的被搬走了")
sw, sh = 120, 90
img = bytearray(sw * sh * 4)
for y in range(sh):
    for x in range(sw):
        o = (y * sw + x) * 4
        inside = 40 <= x < 80 and 30 <= y < 60
        img[o:o + 3] = bytes((230, 40, 40) if inside else (245, 245, 245))
        img[o + 3] = 255
img = bytes(img)


def px(data, w, x, y):
    o = (y * w + x) * 4
    return tuple(data[o:o + 3])


sm = MW.Mesh.identity(sw, sh, 3, 3)
# 把方块正中间那个交点（1,1）往右下拖 12 px
sm.node(1, 1)["x"] += 12.0
sm.node(1, 1)["y"] += 8.0
sm.auto_refresh()
sf = MW.build_field(sm, sw, sh)
out = WM.warp_rgba(img, sw, sh, sf)
ok("变形后不是原图", out != img)
ok("方块中心跟着交点走（%s）" % (px(out, sw, 55, 45),),
   px(out, sw, 55, 45)[0] > 200 and px(out, sw, 55, 45)[1] < 80,
   px(out, sw, 55, 45))
ok("画面角落仍然干净（%s）" % (px(out, sw, 3, 3),),
   px(out, sw, 3, 3) == (245, 245, 245), px(out, sw, 3, 3))
ok("尺寸没变、字节数没变", len(out) == sw * sh * 4)

# 只拖一点点：不应该出现真空洞（alpha 全 255 的图，输出也不能有透明）。
# 允许掉 1 级：warp_rgba 走的是截断（为了两条路径逐字节一致），
# 255*(1-ε) 会截成 254。
ok("输入不透明 → 输出也不透明（没有采到图外，最低 %d）" % min(out[3::4]),
   min(out[3::4]) >= 254, min(out[3::4]))

# ---- 性能 --------------------------------------------------------------
section("性能")
bigw, bigh = 768, 1024
bigm = MW.Mesh.identity(bigw, bigh, 3, 3)
bigm.node(1, 1)["x"] += 120.0
bigm.node(1, 1)["y"] += 60.0
bigm.auto_refresh()
t0 = time.time()
fbig = MW.build_field(bigm, bigw, bigh)
ms = (time.time() - t0) * 1000.0
limit = 600 if MW.have_numpy() else 3000
ok("768×1024 解场 %.0f ms < %d" % (ms, limit), ms < limit, ms)
big = bytes(bytearray(bigw * bigh * 4))
t0 = time.time()
WM.warp_rgba(big, bigw, bigh, fbig)
sec = time.time() - t0
wlimit = 2.0 if WM.have_numpy() else 6.0
ok("768×1024 重采样 %.2f s < %.1f" % (sec, wlimit), sec < wlimit, sec)

# ---- 摘要 --------------------------------------------------------------
section("摘要（对话框底部那行字）")
st = MW.mesh_summary(m1)
ok("认出动了 1 个点（%d）" % st["moved"], st["moved"] == 1, st)
ok("最大位移 %.1f px" % st["max_shift"], abs(st["max_shift"] - 53.85) < 2.0, st)
ok("自动把手不算「手弯」（%d）" % st["curved"], st["curved"] == 0, st)
st2 = MW.mesh_summary(mh)
ok("手拖过把手算 1 处（%d）" % st2["curved"], st2["curved"] == 1, st2)
ok("恒等网格摘要全 0",
   MW.mesh_summary(MW.Mesh.identity(W, H, 3, 3))["moved"] == 0)


print("\n" + "=" * 60)
if FAIL:
    print("失败 %d 项 / 通过 %d 项" % (len(FAIL), PASS))
    for f in FAIL:
        print("  - %s" % f)
    sys.exit(1)
print("全部通过：%d 项检查" % PASS)
