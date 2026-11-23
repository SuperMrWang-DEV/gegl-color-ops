# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 自由网格变形（Bezier 网格 / FFD）数学
 ---------------------------------------------------------------------------
 purpose   给 GIMP 3 补上 PS 的「编辑 → 变换 → 变形」：图层上盖一张网格，
           拖网格交点改变形状，交点上的**把手**把网格线弯成曲线。
           和木偶变形（warp_math.py 的钉子）是两套东西：那个是「拖内容」，
           这个是「给内容套一个自由曲面」。

           核心是 FFD（Free-Form Deformation）+ 双三次 Bezier 曲面片：
             网格 cols×rows 个格子，每个交点存「位置 P」和「两个切向
             U / V」（就是把手）。一个格子 = 一张 4×4 控制点的 Bezier
             曲面片，把参数 (u,v) 映射到图像坐标。
           变形 = 把这张曲面当成「新位置」，于是要做的是反解：
             对每个目标像素 p，解 P(u,v) = p（Newton），
             然后源坐标取**原位格**上的 (u,v)——不是曲面上的位置。
 ============================================================================"""

import math

try:                        # numpy 可选：装了就走批量 Newton（见 tools/install_gimp_numpy.py）
    import numpy as _np
except Exception:
    _np = None

import warp_math as _wm     # Field / identity_field / grid_extent 都复用它

USE_NUMPY = True

# 反向场的栅格节点数（长边）。曲面本身光滑，140 个点插值误差 < 0.02 px。
GRID_NODES = 140
# 纯 Python 版每个点都要解一次 Newton，节点太多会明显变慢，降到 100。
PY_GRID_NODES = 100
# Newton 迭代次数与收敛阈值（单位：像素）。到 1e-4 就够：偏移场最后要双线性插值。
NEWTON_ITERS = 24
NEWTON_TOL = 1e-4
# 单步最多走 0.75 个格子。**不限步会跨格来回震**：曲面在节点附近被压扁时
# 局部导数很小，Newton 一步就能跨掉一格，落到隔壁格导数大的地方再跳回来。
NEWTON_STEP = 0.75
# 小于这个值当成 0（浮点噪声）。不压成 0 的话恒等网格判不出来，整图白重采样。
ZERO_EPS = 1e-6
# 网格最大格数。再密就没有手拖的意义了。
MAX_CELLS = 12
# 一格里有超过这个比例的采样点雅可比变号，就认为网格自交了（会花屏）。
# 实测：把手转 90° 是 0.00，转 120° 0.06，节点拖过半格 0.14，拖过邻居 0.25。
FOLD_LIMIT = 0.10


def have_numpy():
    return _np is not None and USE_NUMPY


def _dist(a, b):
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


def _seg(arr, val):
    """val 落在断点数组 arr 的第几段，以及段内归一化位置 [0,1]。

    网格允许「自己加分割线」，所以格界不再等距：us / vs 记着每条线的参数
    位置（默认 0,1,…,cols 等分）。参数空间本身永远线性对应原图，所以
    加线只改插值，不改「哪个像素来自哪儿」。
    """
    n = len(arr) - 1
    if val <= arr[0]:
        return 0, 0.0
    if val >= arr[n]:
        return n - 1, 1.0
    lo, hi = 0, n
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if arr[mid] <= val:
            lo = mid
        else:
            hi = mid
    span = arr[lo + 1] - arr[lo]
    return lo, ((val - arr[lo]) / span if span > 0.0 else 0.0)


def _breaks(arr, want, count):
    """把断点数组规整成「长度 count+1、严格递增、首尾刚好 0 / want」。"""
    out = None
    if arr is not None:
        try:
            vals = [float(v) for v in arr]
        except (TypeError, ValueError):
            vals = []
        if len(vals) == count + 1 and all(
                vals[i] < vals[i + 1] for i in range(count)):
            out = vals
    if out is None:
        out = [float(i) for i in range(count + 1)]
    else:
        span = out[count] - out[0]
        if span <= 0.0:
            out = [float(i) for i in range(count + 1)]
        else:                               # 归一化到 0..count，参数范围固定
            k = float(count) / span
            out = [(v - out[0]) * k for v in out]
    return out


# ---- 数据结构 --------------------------------------------------------------

class Mesh(object):
    """一张 cols×rows 格的 Bezier 网格。

    nodes 按行存（j 外层、i 内层），每项：
        x, y    —— 交点现在的位置（图层像素）
        ux, uy  —— 沿 u 方向的切向（∂P/∂u，单位：像素/格，也就是把手长度 ×3）
        vx, vy  —— 沿 v 方向的切向
        a       —— 1 = 把手自动（跟着位置算），0 = 用户拖过、按给定值

    把手对称：一个节点的 U 被左右两个格子共用，所以跨格是 C1 连续的。
    这也是 PS 的手感——拖一边的把手，另一边的曲线跟着一起弯。

    **把手默认是自动的**（a=1）：拖节点时用邻居位置重算切向，并限幅到
    相邻弦长以内。不这么做的话，Bezier 片会「甩过头」——把中间点拖走 80 px，
    右侧那格只剩 26 px 的弦却还带着 66 px 的切向，控制多边形来回折，
    格子自交，反解出两三个分支，画面上撕出一道。
    """

    __slots__ = ("cols", "rows", "w", "h", "nodes", "us", "vs")

    def __init__(self, cols, rows, nodes, w=0, h=0, us=None, vs=None):
        self.cols = max(1, int(cols))
        self.rows = max(1, int(rows))
        self.w = w
        self.h = h
        self.nodes = nodes
        # 格界在参数空间里的位置。等分是 [0,1,…,cols]；「自己加分割线」就是
        # 往这里插一个数，于是格宽不再相等，而参数范围仍是 0..cols。
        self.us = _breaks(us, self.cols, self.cols)
        self.vs = _breaks(vs, self.rows, self.rows)

    def cell_width(self, i):
        """第 i 列在参数空间的宽度（等分时恒为 1）。"""
        i = 0 if i < 0 else (self.cols - 1 if i > self.cols - 1 else i)
        return self.us[i + 1] - self.us[i]

    def cell_height(self, j):
        j = 0 if j < 0 else (self.rows - 1 if j > self.rows - 1 else j)
        return self.vs[j + 1] - self.vs[j]

    def node_width(self, i):
        """节点 i 两侧较窄的那一列宽度（把手限幅用）。"""
        if i <= 0:
            return self.cell_width(0)
        if i >= self.cols:
            return self.cell_width(self.cols - 1)
        return min(self.cell_width(i - 1), self.cell_width(i))

    def node_height(self, j):
        if j <= 0:
            return self.cell_height(0)
        if j >= self.rows:
            return self.cell_height(self.rows - 1)
        return min(self.cell_height(j - 1), self.cell_height(j))

    def uniform(self, tol=1e-9):
        """格界是不是等距的（用来判断「有没有自己加过线」）。"""
        return (all(abs(self.us[i] - i) <= tol for i in range(self.cols + 1))
                and all(abs(self.vs[j] - j) <= tol
                        for j in range(self.rows + 1)))

    # -- 基本访问 ----------------------------------------------------------
    def node(self, i, j):
        return self.nodes[j * (self.cols + 1) + i]

    def cell_size(self):
        """一格大致多宽多高（用原始画布尺寸算，把手长度限幅时用）。

        加了分割线之后格宽不等，这里给的是**最窄**的那格——限幅宁严勿松。
        """
        cw = (float(self.w) - 1.0) / self.cols if self.cols else 1.0
        ch = (float(self.h) - 1.0) / self.rows if self.rows else 1.0
        if self.cols > 1:
            cw *= min(self.cell_width(i) for i in range(self.cols))
        if self.rows > 1:
            ch *= min(self.cell_height(j) for j in range(self.rows))
        return cw, ch

    def auto_refresh(self):
        """把 a=1 的节点的把手按邻居位置重算（并限幅到相邻弦长以内）。

        恒等网格重算出来恰好就是格宽格高，所以这一步不会让恒等网格变脏。
        """
        cols, rows = self.cols, self.rows
        for j in range(rows + 1):
            for i in range(cols + 1):
                n = self.node(i, j)
                if not n.get("a", 1):
                    continue
                # u 方向的切向 + 限幅
                if cols == 1:
                    ax = ay = 0.0
                    lim_u = 0.0
                else:
                    if i == 0:
                        p, q = self.node(0, j), self.node(1, j)
                        span = self.us[1] - self.us[0]
                    elif i == cols:
                        p, q = self.node(cols - 1, j), self.node(cols, j)
                        span = self.us[cols] - self.us[cols - 1]
                    else:
                        p, q = self.node(i - 1, j), self.node(i + 1, j)
                        span = self.us[i + 1] - self.us[i - 1]
                    ax = (q["x"] - p["x"]) / span
                    ay = (q["y"] - p["y"]) / span
                    chords = []
                    if i > 0:
                        chords.append(_dist(self.node(i - 1, j), n))
                    if i < cols:
                        chords.append(_dist(self.node(i + 1, j), n))
                    # 切向是「每参数单位」的位移，限幅要按这一列有多宽换算
                    lim_u = (max(1e-3, min(chords)) / self.node_width(i)
                             if chords else 0.0)
                norm = math.hypot(ax, ay)
                if lim_u > 0.0 and norm > lim_u:
                    k = lim_u / norm
                    ax *= k
                    ay *= k
                n["ux"], n["uy"] = ax, ay

                # v 方向
                if rows == 1:
                    bx_ = by_ = 0.0
                    lim_v = 0.0
                else:
                    if j == 0:
                        p, q = self.node(i, 0), self.node(i, 1)
                        span = self.vs[1] - self.vs[0]
                    elif j == rows:
                        p, q = self.node(i, rows - 1), self.node(i, rows)
                        span = self.vs[rows] - self.vs[rows - 1]
                    else:
                        p, q = self.node(i, j - 1), self.node(i, j + 1)
                        span = self.vs[j + 1] - self.vs[j - 1]
                    bx_ = (q["x"] - p["x"]) / span
                    by_ = (q["y"] - p["y"]) / span
                    chords = []
                    if j > 0:
                        chords.append(_dist(self.node(i, j - 1), n))
                    if j < rows:
                        chords.append(_dist(self.node(i, j + 1), n))
                    lim_v = (max(1e-3, min(chords)) / self.node_height(j)
                             if chords else 0.0)
                norm = math.hypot(bx_, by_)
                if lim_v > 0.0 and norm > lim_v:
                    k = lim_v / norm
                    bx_ *= k
                    by_ *= k
                n["vx"], n["vy"] = bx_, by_
        return self

    # -- 构造 --------------------------------------------------------------
    @classmethod
    def identity(cls, w, h, cols=3, rows=3, us=None, vs=None):
        """恒等网格：交点在栅格上，切向 = 格宽/格高。

        us / vs 给了就按它铺（加了分割线的恒等网格），不给就是等分。
        """
        cols = max(1, min(MAX_CELLS, int(cols)))
        rows = max(1, min(MAX_CELLS, int(rows)))
        cw = (float(w) - 1.0) / cols if w else 1.0
        ch = (float(h) - 1.0) / rows if h else 1.0
        mesh = cls(cols, rows, [], w, h, us, vs)
        us_, vs_ = mesh.us, mesh.vs
        nodes = []
        for j in range(rows + 1):
            for i in range(cols + 1):
                nodes.append({"x": us_[i] * cw, "y": vs_[j] * ch,
                              "ux": cw, "uy": 0.0, "vx": 0.0, "vy": ch, "a": 1})
        mesh.nodes = nodes
        return mesh

    def copy(self):
        return Mesh(self.cols, self.rows,
                    [dict(n) for n in self.nodes], self.w, self.h,
                    list(self.us), list(self.vs))

    def scaled(self, f):
        """整体缩放（图层坐标 → 预览坐标用）。f 是倍率。"""
        nodes = []
        for n in self.nodes:
            nodes.append({"x": n["x"] * f, "y": n["y"] * f,
                          "ux": n["ux"] * f, "uy": n["uy"] * f,
                          "vx": n["vx"] * f, "vy": n["vy"] * f,
                          "a": n.get("a", 1)})
        return Mesh(self.cols, self.rows, nodes, self.w * f, self.h * f,
                    list(self.us), list(self.vs))

    def position_only_copy(self):
        """只保留交点位置、把手全部回到自动（网格线是直的）。"""
        out = Mesh.identity(self.w, self.h, self.cols, self.rows,
                            self.us, self.vs)          # 分割线要留着
        for idx, n in enumerate(self.nodes):
            out.nodes[idx]["x"] = n["x"]
            out.nodes[idx]["y"] = n["y"]
        return out.auto_refresh()

    # -- 恒等判定 ----------------------------------------------------------
    def is_identity(self, tol=1e-6):
        """交点在均匀栅格上、把手等于格宽格高 → 变形量恰好是 0。

        build_field 靠这个**提前短路**：Newton 只能把残差做到 1e-4，
        不短路的话恒等网格也会被算出一层 1e-4 的偏移，整图白白重采样。
        """
        cols, rows = self.cols, self.rows
        cw = (float(self.w) - 1.0) / cols if self.w else 0.0
        ch = (float(self.h) - 1.0) / rows if self.h else 0.0
        # 加了分割线之后「原位」不再是 i*cw —— 参数 u 仍线性对应原图，
        # 所以第 i 条线在原图上的位置是 us[i]/cols（等分时就是 i）。
        for j in range(rows + 1):
            for i in range(cols + 1):
                n = self.node(i, j)
                if (abs(n["x"] - self.us[i] * cw) > tol
                        or abs(n["y"] - self.vs[j] * ch) > tol):
                    return False
                if abs(n["ux"] - cw) > tol or abs(n["uy"]) > tol:
                    return False
                if abs(n["vx"]) > tol or abs(n["vy"] - ch) > tol:
                    return False
        return True

    # -- 求值 --------------------------------------------------------------
    def locate(self, u, v):
        """全局参数 (u,v) → (列号, 行号, 格内 s, 格内 t)。"""
        ci, s = _seg(self.us, u)
        cj, t = _seg(self.vs, v)
        return ci, cj, s, t

    def _cell(self, u, v):
        """全局参数 (u,v) → (格子索引, 格内参数 s,t∈[0,1])。"""
        return self.locate(u, v)

    def eval_uv(self, u, v):
        """参数 (u,v) → 变形后的图像坐标。u∈[0,cols]，v∈[0,rows]。"""
        ci, cj, s, t = self._cell(u, v)
        bx, by = _cell_ctrl(self, ci, cj)
        return _patch(bx, by, s, t)[:2]

    def eval_full(self, u, v):
        """同上，外加两个切向（重采样、插分割线时用）。

        切向一律换算成「每参数单位」（∂P/∂u、∂P/∂v），片内的 ∂P/∂s 要乘格宽。
        等分网格里两者相等，所以老代码看不出区别。
        """
        ci, cj, s, t = self._cell(u, v)
        bx, by = _cell_ctrl(self, ci, cj)
        x, y, psx, psy, ptx, pty = _patch(bx, by, s, t)
        dw = self.us[ci + 1] - self.us[ci]
        dv = self.vs[cj + 1] - self.vs[cj]
        return x, y, psx / dw, psy / dw, ptx / dv, pty / dv

    def grid_polylines(self, steps=10):
        """把变形后的网格线画成一串折线（图像坐标），给对话框用。"""
        steps = max(2, int(steps))
        lines = []
        for i in range(self.cols + 1):                  # 竖线：u 固定
            u = self.us[i]
            pts = []
            for j in range(self.rows):
                for k in range(steps + 1):
                    if j and k == 0:
                        continue                        # 接缝不重复点
                    pts.append(self.eval_uv(u, self.vs[j] + (self.vs[j + 1]
                                                             - self.vs[j])
                                            * k / float(steps)))
            lines.append(pts)
        for j in range(self.rows + 1):                  # 横线：v 固定
            v = self.vs[j]
            pts = []
            for i in range(self.cols):
                for k in range(steps + 1):
                    if i and k == 0:
                        continue
                    pts.append(self.eval_uv(self.us[i] + (self.us[i + 1]
                                                          - self.us[i])
                                            * k / float(steps), v))
            lines.append(pts)
        return lines

    def cells_around(self, i, j):
        """节点 (i,j) 一动就受影响的那几格（最多 4 个）。"""
        return [(ci, cj) for cj in (j - 1, j) for ci in (i - 1, i)
                if 0 <= ci < self.cols and 0 <= cj < self.rows]

    def cell_fold_ratio(self, ci, cj, steps=6):
        """这一格里「雅可比变号」的采样点占比（0 = 完全没翻）。

        用 6×6 而不是 3×3：3×3 太粗，双三次片在四角附近刚翻的时候采不到，
        反过来一个好好的 90° 把手弯曲又会被误报。实测（300 px 图、3×3 格）：
        把手转 90° → 0.00，转 120° → 0.06，节点拖过半格 → 0.14，
        拖过邻居 → 0.25。所以阈值取 0.10。
        """
        if not (0 <= ci < self.cols and 0 <= cj < self.rows):
            return 0.0
        bx, by = _cell_ctrl(self, ci, cj)
        n = max(2, int(steps))
        pos = neg = 0
        for a in range(n + 1):
            s = a / float(n)
            for b in range(n + 1):
                t = b / float(n)
                _, _, psx, psy, ptx, pty = _patch(bx, by, s, t)
                j = psx * pty - psy * ptx
                if j > 0.0:
                    pos += 1
                elif j < 0.0:
                    neg += 1
        if not (pos or neg):
            return 0.0
        return min(pos, neg) / float(pos + neg)

    def cell_folded(self, ci, cj, limit=None):
        """这一格是不是「翻了」——翻了就意味着网格自交。

        一旦自交，映射就不再是一一对应：C 那侧的反向 Newton 会解到翻转的
        那一支，画面上先是一块捏起来的褶子，再大一点整片像素乱飞（白区里
        散着断线和黑点）。与其在采样端猜，不如在**生成网格时**就不让它
        翻过去——拖到快翻的位置就停住（见交互层的二分限幅）。
        """
        if limit is None:
            limit = FOLD_LIMIT
        return self.cell_fold_ratio(ci, cj) > limit

    def folded(self, cells=None):
        """任意一格翻了没有；cells 为空就查全部。"""
        if cells is None:
            cells = [(i, j) for j in range(self.rows)
                     for i in range(self.cols)]
        return any(self.cell_folded(i, j) for i, j in cells)

    def handle(self, i, j, axis, sign):
        """把手圆点的位置：节点 + sign·切向·格宽/3（控制点就在 1/3 格处）。"""
        n = self.node(i, j)
        if axis == "u":
            dw = self.cell_width(i if sign > 0 else i - 1)
            return (n["x"] + sign * n["ux"] * dw / 3.0,
                    n["y"] + sign * n["uy"] * dw / 3.0)
        dv = self.cell_height(j if sign > 0 else j - 1)
        return (n["x"] + sign * n["vx"] * dv / 3.0,
                n["y"] + sign * n["vy"] * dv / 3.0)

    def tangent_from_handle(self, i, j, axis, sign, cx, cy):
        """把手圆点被拖到 (cx,cy) → 反推「每参数单位」的切向。"""
        n = self.node(i, j)
        if axis == "u":
            dw = self.cell_width(i if sign > 0 else i - 1)
            return (sign * (cx - n["x"]) * 3.0 / dw,
                    sign * (cy - n["y"]) * 3.0 / dw)
        dv = self.cell_height(j if sign > 0 else j - 1)
        return (sign * (cx - n["x"]) * 3.0 / dv,
                sign * (cy - n["y"]) * 3.0 / dv)

    # -- 改网格尺寸 --------------------------------------------------------
    def resample(self, cols, rows):
        """换网格密度，形状不变：新交点取原曲面上的点，切向取曲面导数。

        切向是 ∂P/∂u（每格一个参数单位），和网格密度无关，所以直接拿来用。
        """
        cols = max(1, min(MAX_CELLS, int(cols)))
        rows = max(1, min(MAX_CELLS, int(rows)))
        out = Mesh.identity(self.w, self.h, cols, rows)
        # 切向要换算到**新**的格子参数：新一格 = 旧 cols/新 cols 个旧参数单位。
        # 漏掉这个系数，重采样出来的曲面会明显「软」一截（3→5 实测误差 7 px）。
        ku = self.cols / float(cols)
        kv = self.rows / float(rows)
        for j in range(rows + 1):
            for i in range(cols + 1):
                u = i * ku
                v = j * kv
                x, y, ux, uy, vx, vy = self.eval_full(u, v)
                n = out.node(i, j)
                n["x"], n["y"] = x, y
                n["ux"], n["uy"] = ux * ku, uy * ku
                n["vx"], n["vy"] = vx * kv, vy * kv
                # 新节点四周的原节点全是自动把手，新节点才是自动的；
                # 只要有一处手拖过，就把切向定死（不然会把手拖的形状抹掉）。
                i0 = min(int(math.floor(u)), self.cols - 1)
                j0 = min(int(math.floor(v)), self.rows - 1)
                n["a"] = 1 if all(self.node(i0 + a, j0 + b).get("a", 1)
                                  for a in (0, 1) for b in (0, 1)) else 0
        return out


    # -- 自己加分割线（PS 的 Alt+拖网格线） --------------------------------
    def split_u(self, ci, frac=0.5, auto=True):
        """在第 ci 列里插一条竖线，返回**新**网格（失败返回 None）。

        新线的交点和切向都取自原曲面，所以插完画面不动——这是整套改动的
        验收标准（实测偏差见 check_mesh_warp）。切向默认 auto=True，之后
        拖相邻节点时它会跟着重算，跟 PS 的活网格一致。
        """
        ci = int(ci)
        if ci < 0 or ci > self.cols - 1 or self.cols >= MAX_CELLS:
            return None
        frac = min(0.98, max(0.02, float(frac)))
        p = self.us[ci] + (self.us[ci + 1] - self.us[ci]) * frac
        col = [self.eval_full(p, self.vs[j]) for j in range(self.rows + 1)]
        # 参数范围必须跟着 cols 走（源图按 u/cols 铺），所以整条轴按 k 缩放；
        # 切向是「每参数单位」的导数，参数变短 → 导数要除以 k，位置不用动。
        k = (self.cols + 1) / float(self.cols)
        nodes = []
        for j in range(self.rows + 1):
            for i in range(self.cols + 1):
                m = dict(self.node(i, j))
                m["ux"] /= k
                m["uy"] /= k
                nodes.append(m)
                if i == ci:
                    x, y, ux, uy, vx, vy = col[j]
                    nodes.append({"x": x, "y": y,
                                  "ux": ux / k, "uy": uy / k,
                                  "vx": vx, "vy": vy,
                                  "a": 1 if auto else 0})
        us = [v * k for v in
              (list(self.us[:ci + 1]) + [p] + list(self.us[ci + 1:]))]
        return Mesh(self.cols + 1, self.rows, nodes, self.w, self.h,
                    us, list(self.vs))

    def split_v(self, cj, frac=0.5, auto=True):
        """在第 cj 行里插一条横线，返回**新**网格（失败返回 None）。"""
        cj = int(cj)
        if cj < 0 or cj > self.rows - 1 or self.rows >= MAX_CELLS:
            return None
        frac = min(0.98, max(0.02, float(frac)))
        p = self.vs[cj] + (self.vs[cj + 1] - self.vs[cj]) * frac
        row = [self.eval_full(self.us[i], p) for i in range(self.cols + 1)]
        k = (self.rows + 1) / float(self.rows)
        nodes = []
        for j in range(self.rows + 1):
            for i in range(self.cols + 1):
                m = dict(self.node(i, j))
                m["vx"] /= k
                m["vy"] /= k
                nodes.append(m)
            if j == cj:
                for i in range(self.cols + 1):
                    x, y, ux, uy, vx, vy = row[i]
                    nodes.append({"x": x, "y": y, "ux": ux, "uy": uy,
                                  "vx": vx / k, "vy": vy / k,
                                  "a": 1 if auto else 0})
        vs = [v * k for v in
              (list(self.vs[:cj + 1]) + [p] + list(self.vs[cj + 1:]))]
        return Mesh(self.cols, self.rows + 1, nodes, self.w, self.h,
                    list(self.us), vs)


# ---- 曲面片求值 ------------------------------------------------------------

def apply_guarded(mesh, cells, apply, tries=5):
    """按比例 apply(f ∈ [0,1]) 施加一次改动，翻格就退回不翻的最大比例。

    拖节点/把手是一次性给目标位置，目标可能让格子翻过来。翻了映射就不
    一一对应，C 那边反向解出两个分支，画面先是起褶子、再大一点整片花屏。
    这里二分找「翻之前的最大一步」，5 次后精度 1/32 格，手感正好是
    「顶住边界」而不是「突然不动」。

    apply(0.0) 必须把网格还原成改动前的样子——调用方保证。
    返回 True = 完整施加，False = 被限幅。
    """
    apply(1.0)
    if not mesh.folded(cells):
        return True
    lo, hi = 0.0, 1.0
    for _ in range(max(1, int(tries))):
        mid = (lo + hi) * 0.5
        apply(mid)
        if mesh.folded(cells):
            hi = mid
        else:
            lo = mid
    apply(lo)
    return False


def _cell_ctrl(mesh, ci, cj):
    """一个格子的 4×4 控制点网（bx, by 各 16 个，索引 a*4+b，a 沿 u、b 沿 v）。

    边上的 8 个点是「节点 ± 切向/3」；中间 4 个点必须再加一个 twist 修正
    （双线性交叉项 (P11-P10-P01+P00)/9）。少了这一项，恒等网格解出来
    每格中心也偏出去——曲面就不是平面了。
    """
    n00 = mesh.node(ci, cj)
    n01 = mesh.node(ci, cj + 1)
    n10 = mesh.node(ci + 1, cj)
    n11 = mesh.node(ci + 1, cj + 1)
    # 切向存的是「每参数单位」，片内参数 s 跨一整格 dω 个参数单位，
    # 所以控制点偏移要乘格宽；等分时 dω=1，和以前完全一样。
    dw = mesh.us[ci + 1] - mesh.us[ci]
    dv = mesh.vs[cj + 1] - mesh.vs[cj]
    bx = [0.0] * 16
    by = [0.0] * 16

    def put(a, b, x, y):
        bx[a * 4 + b] = x
        by[a * 4 + b] = y

    put(0, 0, n00["x"], n00["y"])
    put(0, 3, n01["x"], n01["y"])
    put(3, 0, n10["x"], n10["y"])
    put(3, 3, n11["x"], n11["y"])

    put(0, 1, n00["x"] + n00["vx"] * dv / 3.0, n00["y"] + n00["vy"] * dv / 3.0)
    put(0, 2, n01["x"] - n01["vx"] * dv / 3.0, n01["y"] - n01["vy"] * dv / 3.0)
    put(3, 1, n10["x"] + n10["vx"] * dv / 3.0, n10["y"] + n10["vy"] * dv / 3.0)
    put(3, 2, n11["x"] - n11["vx"] * dv / 3.0, n11["y"] - n11["vy"] * dv / 3.0)

    put(1, 0, n00["x"] + n00["ux"] * dw / 3.0, n00["y"] + n00["uy"] * dw / 3.0)
    put(2, 0, n10["x"] - n10["ux"] * dw / 3.0, n10["y"] - n10["uy"] * dw / 3.0)
    put(1, 3, n01["x"] + n01["ux"] * dw / 3.0, n01["y"] + n01["uy"] * dw / 3.0)
    put(2, 3, n11["x"] - n11["ux"] * dw / 3.0, n11["y"] - n11["uy"] * dw / 3.0)

    tx = (n11["x"] - n10["x"] - n01["x"] + n00["x"]) / 9.0
    ty = (n11["y"] - n10["y"] - n01["y"] + n00["y"]) / 9.0
    put(1, 1, n00["x"] + (n00["ux"] * dw + n00["vx"] * dv) / 3.0 + tx,
              n00["y"] + (n00["uy"] * dw + n00["vy"] * dv) / 3.0 + ty)
    put(1, 2, n01["x"] + (n01["ux"] * dw - n01["vx"] * dv) / 3.0 + tx,
              n01["y"] + (n01["uy"] * dw - n01["vy"] * dv) / 3.0 + ty)
    put(2, 1, n10["x"] + (-n10["ux"] * dw + n10["vx"] * dv) / 3.0 + tx,
              n10["y"] + (-n10["uy"] * dw + n10["vy"] * dv) / 3.0 + ty)
    put(2, 2, n11["x"] + (-n11["ux"] * dw - n11["vx"] * dv) / 3.0 + tx,
              n11["y"] + (-n11["uy"] * dw - n11["vy"] * dv) / 3.0 + ty)
    return bx, by


def _basis3(s):
    s1 = 1.0 - s
    return (s1 * s1 * s1, 3.0 * s * s1 * s1, 3.0 * s * s * s1, s * s * s)


def _basis2(s):
    s1 = 1.0 - s
    return (s1 * s1, 2.0 * s * s1, s * s)


def _patch(bx, by, s, t):
    """一张曲面片在 (s,t) 处的 P、∂P/∂s、∂P/∂t。"""
    bs = _basis3(s)
    bt = _basis3(t)
    qs = _basis2(s)
    qt = _basis2(t)
    px = py = 0.0
    for a in range(4):
        ka = bs[a]
        base = a * 4
        for b in range(4):
            k = ka * bt[b]
            px += bx[base + b] * k
            py += by[base + b] * k
    psx = psy = 0.0
    for a in range(3):
        ka = 3.0 * qs[a]
        base = a * 4
        for b in range(4):
            k = ka * bt[b]
            psx += (bx[base + 4 + b] - bx[base + b]) * k
            psy += (by[base + 4 + b] - by[base + b]) * k
    ptx = pty = 0.0
    for a in range(4):
        ka = bs[a]
        base = a * 4
        for b in range(3):
            k = ka * 3.0 * qt[b]
            ptx += (bx[base + b + 1] - bx[base + b]) * k
            pty += (by[base + b + 1] - by[base + b]) * k
    return px, py, psx, psy, ptx, pty


# ---- 反解（目标像素 → 参数） -----------------------------------------------

def _initial_uv(mesh, x, y, w=None, h=None):
    """恒等参数当初值：比「找最近节点」稳。

    最近节点在位移大的时候会跳到隔壁格，Newton 顺着就收敛到错的分支
    （曲面折过去的那一侧），画面上表现为一块撕开的像素。

    w/h 是**目标画布**的尺寸，不是 mesh.w —— 预览会把网格缩放一份，
    两者必须用同一个尺寸归一化，否则初值整体偏掉，两条路径（纯 Python /
    numpy）收敛到不同分支，实测能差出 28 px。
    """
    cols, rows = mesh.cols, mesh.rows
    w = float(w if w is not None else mesh.w) - 1.0
    h = float(h if h is not None else mesh.h) - 1.0
    u = x / w * cols if w > 0 else 0.0
    v = y / h * rows if h > 0 else 0.0
    if u < 0.0:
        u = 0.0
    elif u > cols:
        u = cols
    if v < 0.0:
        v = 0.0
    elif v > rows:
        v = rows
    return u, v


def invert_point(mesh, x, y, iters=NEWTON_ITERS, tol=NEWTON_TOL, w=None, h=None):
    """解 P(u,v) = (x,y)。返回 (u, v)；解决不了就返回边界上的近似值。"""
    cols, rows = mesh.cols, mesh.rows
    u, v = _initial_uv(mesh, x, y, w, h)
    us, vs = mesh.us, mesh.vs
    cache = {}
    for _i in range(iters):
        ci, s = _seg(us, u)
        cj, t = _seg(vs, v)
        key = (ci, cj)
        ctrl = cache.get(key)
        if ctrl is None:
            ctrl = _cell_ctrl(mesh, ci, cj)
            cache[key] = ctrl
        bx, by = ctrl
        px, py, psx, psy, ptx, pty = _patch(bx, by, s, t)
        ex = x - px
        ey = y - py
        if ex * ex + ey * ey <= tol * tol:
            break
        det = psx * pty - psy * ptx
        if abs(det) < 1e-9:                     # 折了：这一步没救，保持原位
            break
        du = (pty * ex - ptx * ey) / det
        dv = (-psy * ex + psx * ey) / det
        # du/dv 是**格内参数**的增量，限步也按格算（0.75 格），最后再乘格宽
        step = max(abs(du), abs(dv))
        if step > NEWTON_STEP:                  # 见 NEWTON_STEP 的注释：不限步会震
            k = NEWTON_STEP / step
            du *= k
            dv *= k
        u += du * (us[ci + 1] - us[ci])
        v += dv * (vs[cj + 1] - vs[cj])
        if not (u == u and v == v):             # NaN
            break
        if u < 0.0:
            u = 0.0
        elif u > cols:
            u = cols
        if v < 0.0:
            v = 0.0
        elif v > rows:
            v = rows
    return u, v


def _ctrl_net_np(mesh):
    """把所有格子的控制点网摊成 (ncell, 4, 4) 的两张数组。"""
    np = _np
    cols, rows = mesh.cols, mesh.rows
    n = cols * rows
    bx = np.empty((n, 4, 4), dtype=np.float64)
    by = np.empty((n, 4, 4), dtype=np.float64)
    for cj in range(rows):
        for ci in range(cols):
            cx, cy = _cell_ctrl(mesh, ci, cj)
            c = cj * cols + ci
            bx[c] = np.reshape(cx, (4, 4))
            by[c] = np.reshape(cy, (4, 4))
    return bx, by


def _invert_np(mesh, xs, ys, iters=NEWTON_ITERS, tol=NEWTON_TOL, w=None, h=None):
    """批量 Newton。xs/ys 是 (N,) 目标坐标，返回 (u, v) 两张 (N,) 数组。"""
    np = _np
    cols, rows = mesh.cols, mesh.rows
    bx_net, by_net = _ctrl_net_np(mesh)
    # 初值同 _initial_uv，只是这里是数组（那边是标量的 if 判断，不能直接复用）
    w1 = float(w if w is not None else mesh.w) - 1.0
    h1 = float(h if h is not None else mesh.h) - 1.0
    u = np.clip(xs / w1 * cols if w1 > 0 else np.zeros_like(xs), 0.0, cols)
    v = np.clip(ys / h1 * rows if h1 > 0 else np.zeros_like(ys), 0.0, rows)
    done = np.zeros(u.shape, dtype=bool)
    us = np.asarray(mesh.us, dtype=np.float64)
    vs = np.asarray(mesh.vs, dtype=np.float64)

    for _i in range(iters):
        # 网格允许不等距：用 searchsorted 找格，格内参数归一化到 [0,1]
        ci = np.clip(np.searchsorted(us, u, side="right") - 1, 0, cols - 1)
        cj = np.clip(np.searchsorted(vs, v, side="right") - 1, 0, rows - 1)
        cells = cj * cols + ci
        duw = us[ci + 1] - us[ci]
        dvh = vs[cj + 1] - vs[cj]
        s = (u - us[ci]) / duw
        t = (v - vs[cj]) / dvh
        bxs = bx_net[cells]
        bys = by_net[cells]

        s1 = 1.0 - s
        bs0 = s1 * s1 * s1
        bs1 = 3.0 * s * s1 * s1
        bs2 = 3.0 * s * s * s1
        bs3 = s * s * s
        t1 = 1.0 - t
        bt0 = t1 * t1 * t1
        bt1 = 3.0 * t * t1 * t1
        bt2 = 3.0 * t * t * t1
        bt3 = t * t * t

        px = (bxs[:, 0, 0] * bs0 * bt0 + bxs[:, 0, 1] * bs0 * bt1 +
              bxs[:, 0, 2] * bs0 * bt2 + bxs[:, 0, 3] * bs0 * bt3 +
              bxs[:, 1, 0] * bs1 * bt0 + bxs[:, 1, 1] * bs1 * bt1 +
              bxs[:, 1, 2] * bs1 * bt2 + bxs[:, 1, 3] * bs1 * bt3 +
              bxs[:, 2, 0] * bs2 * bt0 + bxs[:, 2, 1] * bs2 * bt1 +
              bxs[:, 2, 2] * bs2 * bt2 + bxs[:, 2, 3] * bs2 * bt3 +
              bxs[:, 3, 0] * bs3 * bt0 + bxs[:, 3, 1] * bs3 * bt1 +
              bxs[:, 3, 2] * bs3 * bt2 + bxs[:, 3, 3] * bs3 * bt3)
        py = (bys[:, 0, 0] * bs0 * bt0 + bys[:, 0, 1] * bs0 * bt1 +
              bys[:, 0, 2] * bs0 * bt2 + bys[:, 0, 3] * bs0 * bt3 +
              bys[:, 1, 0] * bs1 * bt0 + bys[:, 1, 1] * bs1 * bt1 +
              bys[:, 1, 2] * bs1 * bt2 + bys[:, 1, 3] * bs1 * bt3 +
              bys[:, 2, 0] * bs2 * bt0 + bys[:, 2, 1] * bs2 * bt1 +
              bys[:, 2, 2] * bs2 * bt2 + bys[:, 2, 3] * bs2 * bt3 +
              bys[:, 3, 0] * bs3 * bt0 + bys[:, 3, 1] * bs3 * bt1 +
              bys[:, 3, 2] * bs3 * bt2 + bys[:, 3, 3] * bs3 * bt3)
        ex = xs - px
        ey = ys - py
        err = ex * ex + ey * ey
        done = done | (err <= tol * tol)
        if done.all():
            break

        qs0 = s1 * s1
        qs1 = 2.0 * s * s1
        qs2 = s * s
        qt0 = t1 * t1
        qt1 = 2.0 * t * t1
        qt2 = t * t
        d = 3.0
        dsx = (d * ((bxs[:, 1, 0] - bxs[:, 0, 0]) * qs0 * bt0 +
                    (bxs[:, 1, 1] - bxs[:, 0, 1]) * qs0 * bt1 +
                    (bxs[:, 1, 2] - bxs[:, 0, 2]) * qs0 * bt2 +
                    (bxs[:, 1, 3] - bxs[:, 0, 3]) * qs0 * bt3 +
                    (bxs[:, 2, 0] - bxs[:, 1, 0]) * qs1 * bt0 +
                    (bxs[:, 2, 1] - bxs[:, 1, 1]) * qs1 * bt1 +
                    (bxs[:, 2, 2] - bxs[:, 1, 2]) * qs1 * bt2 +
                    (bxs[:, 2, 3] - bxs[:, 1, 3]) * qs1 * bt3 +
                    (bxs[:, 3, 0] - bxs[:, 2, 0]) * qs2 * bt0 +
                    (bxs[:, 3, 1] - bxs[:, 2, 1]) * qs2 * bt1 +
                    (bxs[:, 3, 2] - bxs[:, 2, 2]) * qs2 * bt2 +
                    (bxs[:, 3, 3] - bxs[:, 2, 3]) * qs2 * bt3))
        dsy = (d * ((bys[:, 1, 0] - bys[:, 0, 0]) * qs0 * bt0 +
                    (bys[:, 1, 1] - bys[:, 0, 1]) * qs0 * bt1 +
                    (bys[:, 1, 2] - bys[:, 0, 2]) * qs0 * bt2 +
                    (bys[:, 1, 3] - bys[:, 0, 3]) * qs0 * bt3 +
                    (bys[:, 2, 0] - bys[:, 1, 0]) * qs1 * bt0 +
                    (bys[:, 2, 1] - bys[:, 1, 1]) * qs1 * bt1 +
                    (bys[:, 2, 2] - bys[:, 1, 2]) * qs1 * bt2 +
                    (bys[:, 2, 3] - bys[:, 1, 3]) * qs1 * bt3 +
                    (bys[:, 3, 0] - bys[:, 2, 0]) * qs2 * bt0 +
                    (bys[:, 3, 1] - bys[:, 2, 1]) * qs2 * bt1 +
                    (bys[:, 3, 2] - bys[:, 2, 2]) * qs2 * bt2 +
                    (bys[:, 3, 3] - bys[:, 2, 3]) * qs2 * bt3))
        dtx = (d * ((bxs[:, 0, 1] - bxs[:, 0, 0]) * bs0 * qt0 +
                    (bxs[:, 0, 2] - bxs[:, 0, 1]) * bs0 * qt1 +
                    (bxs[:, 0, 3] - bxs[:, 0, 2]) * bs0 * qt2 +
                    (bxs[:, 1, 1] - bxs[:, 1, 0]) * bs1 * qt0 +
                    (bxs[:, 1, 2] - bxs[:, 1, 1]) * bs1 * qt1 +
                    (bxs[:, 1, 3] - bxs[:, 1, 2]) * bs1 * qt2 +
                    (bxs[:, 2, 1] - bxs[:, 2, 0]) * bs2 * qt0 +
                    (bxs[:, 2, 2] - bxs[:, 2, 1]) * bs2 * qt1 +
                    (bxs[:, 2, 3] - bxs[:, 2, 2]) * bs2 * qt2 +
                    (bxs[:, 3, 1] - bxs[:, 3, 0]) * bs3 * qt0 +
                    (bxs[:, 3, 2] - bxs[:, 3, 1]) * bs3 * qt1 +
                    (bxs[:, 3, 3] - bxs[:, 3, 2]) * bs3 * qt2))
        dty = (d * ((bys[:, 0, 1] - bys[:, 0, 0]) * bs0 * qt0 +
                    (bys[:, 0, 2] - bys[:, 0, 1]) * bs0 * qt1 +
                    (bys[:, 0, 3] - bys[:, 0, 2]) * bs0 * qt2 +
                    (bys[:, 1, 1] - bys[:, 1, 0]) * bs1 * qt0 +
                    (bys[:, 1, 2] - bys[:, 1, 1]) * bs1 * qt1 +
                    (bys[:, 1, 3] - bys[:, 1, 2]) * bs1 * qt2 +
                    (bys[:, 2, 1] - bys[:, 2, 0]) * bs2 * qt0 +
                    (bys[:, 2, 2] - bys[:, 2, 1]) * bs2 * qt1 +
                    (bys[:, 2, 3] - bys[:, 2, 2]) * bs2 * qt2 +
                    (bys[:, 3, 1] - bys[:, 3, 0]) * bs3 * qt0 +
                    (bys[:, 3, 2] - bys[:, 3, 1]) * bs3 * qt1 +
                    (bys[:, 3, 3] - bys[:, 3, 2]) * bs3 * qt2))

        det = dsx * dty - dsy * dtx
        ok = (np.abs(det) > 1e-9) & (~done)
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        du = np.where(ok, (dty * ex - dtx * ey) * inv, 0.0)
        dv = np.where(ok, (-dsy * ex + dsx * ey) * inv, 0.0)
        step = np.maximum(np.abs(du), np.abs(dv))
        k = np.where(step > NEWTON_STEP, NEWTON_STEP / np.maximum(step, 1e-12), 1.0)
        u = np.clip(u + du * k * duw, 0.0, cols)
        v = np.clip(v + dv * k * dvh, 0.0, rows)
    return u, v


# ---- 反向偏移场 ------------------------------------------------------------

def build_field(mesh, w, h, nodes=GRID_NODES, nx=None, ny=None):
    """解出整张反向偏移场（目标像素 → 源像素），直接能喂给 warp_math.warp_rgba。

    注意源坐标是 **uv 在原位格上的位置**，不是曲面上的位置：
        src = (u/cols·(w-1), v/rows·(h-1))
    曲面只负责「目标像素落在哪个 uv」，源图是按原尺寸铺开的。
    这一步弄反的话，画面会整体按网格平移一次。
    """
    if mesh is None:
        return _wm.identity_field(w, h, nx, ny)
    if nx is None or ny is None:
        nodes = nodes if have_numpy() else min(nodes, PY_GRID_NODES)
        nx, ny = _wm.grid_extent(w, h, nodes)
    field = _wm.identity_field(w, h, nx, ny)
    if mesh.is_identity():
        return field

    cols, rows = float(mesh.cols), float(mesh.rows)
    sx_step = (w - 1.0) / (nx - 1.0) if nx > 1 else 0.0
    sy_step = (h - 1.0) / (ny - 1.0) if ny > 1 else 0.0

    if have_numpy():
        np = _np
        gx = np.arange(nx, dtype=np.float64) * sx_step
        gy = np.arange(ny, dtype=np.float64) * sy_step
        mx, my = np.meshgrid(gx, gy)
        cx = mx.ravel()
        cy = my.ravel()
        u, v = _invert_np(mesh, cx, cy, w=w, h=h)
        srcx = u * (w - 1.0) / cols
        srcy = v * (h - 1.0) / rows
        ox = srcx - cx
        oy = srcy - cy
        ox = np.where(np.abs(ox) < ZERO_EPS, 0.0, ox)
        oy = np.where(np.abs(oy) < ZERO_EPS, 0.0, oy)
        field.dx[:] = ox.tolist()
        field.dy[:] = oy.tolist()
        return field

    dxa, dya = field.dx, field.dy
    kx = (w - 1.0) / cols
    ky = (h - 1.0) / rows
    for j in range(ny):
        y = j * sy_step
        row = j * nx
        for i in range(nx):
            x = i * sx_step
            u, v = invert_point(mesh, x, y, w=w, h=h)
            ox = u * kx - x
            oy = v * ky - y
            dxa[row + i] = 0.0 if -ZERO_EPS < ox < ZERO_EPS else ox
            dya[row + i] = 0.0 if -ZERO_EPS < oy < ZERO_EPS else oy
    return field


# ---- 序列化（脚本 / 对话框写回） -------------------------------------------

def parse_mesh_string(text, w=0, h=0, cols=3, rows=3):
    """把 "cols,rows; x,y,ux,uy,vx,vy[,a]; …" 解析成 Mesh。

    第一段是格数；后面按行优先给交点，每项 6 个数（位置 + 两个切向），
    第 7 个数 1/0 表示把手自动 / 已手拖（缺省按 0，因为都写出来了）。
    写成 2 个数就只给位置、把手按自动算。缺的项按恒等网格补齐——
    这样脚本里只写几个动过的点也能跑。
    """
    mesh = Mesh.identity(w or 2, h or 2, cols, rows)
    chunks = []
    for raw in (text or "").replace("\n", ";").split(";"):
        raw = raw.strip()
        if raw:
            chunks.append(raw)
    if not chunks:
        return mesh
    try:
        head = [float(v) for v in chunks[0].replace(",", " ").split()]
    except ValueError:
        head = []
    if len(head) >= 2:
        mesh = Mesh.identity(w or 2, h or 2, int(head[0]), int(head[1]))
        chunks = chunks[1:]
    # 分割线段：以 u: / v: 开头，只有「自己加过线」时才写出来（老串没有）
    rest = []
    for raw in chunks:
        low = raw.lower()
        if low[:2] in ("u:", "v:"):
            try:
                vals = [float(v) for v in raw[2:].replace(",", " ").split()]
            except ValueError:
                continue
            if low[0] == "u" and len(vals) == mesh.cols + 1:
                mesh.us = _breaks(vals, mesh.cols, mesh.cols)
            elif low[0] == "v" and len(vals) == mesh.rows + 1:
                mesh.vs = _breaks(vals, mesh.rows, mesh.rows)
            continue
        rest.append(raw)
    chunks = rest
    want = (mesh.cols + 1) * (mesh.rows + 1)
    for idx, raw in enumerate(chunks[:want]):
        try:
            vals = [float(v) for v in raw.replace(",", " ").split()]
        except ValueError:
            continue
        if len(vals) < 2:
            continue
        n = mesh.nodes[idx]
        n["x"], n["y"] = vals[0], vals[1]
        if len(vals) >= 6:
            n["ux"], n["uy"], n["vx"], n["vy"] = vals[2:6]
            n["a"] = 0 if len(vals) < 7 or vals[6] < 0.5 else 1
        else:
            n["a"] = 1
        if w > 0:
            n["x"] = min(max(n["x"], 0.0), w - 1.0)
        if h > 0:
            n["y"] = min(max(n["y"], 0.0), h - 1.0)
    return mesh.auto_refresh()


def format_mesh_string(mesh):
    """反向：Mesh → parse_mesh_string 能读回的字符串（两位小数）。

    自己加过分割线时会多写两段 u: / v:（格界位置），没加过就不写——
    老脚本写的串照样能读。
    """
    parts = ["%d,%d" % (mesh.cols, mesh.rows)]
    if not mesh.uniform():
        parts.append("u:" + ",".join("%.4f" % v for v in mesh.us))
        parts.append("v:" + ",".join("%.4f" % v for v in mesh.vs))
    for n in mesh.nodes:
        parts.append("%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%d"
                     % (n["x"], n["y"], n["ux"], n["uy"],
                        n["vx"], n["vy"], int(n.get("a", 1))))
    return "; ".join(parts)


def mesh_summary(mesh):
    """对话框底部那行小字：几个点动过、把手弯了几个、最大位移多少。"""
    if mesh is None:
        return {"cols": 0, "rows": 0, "moved": 0, "curved": 0, "max_shift": 0.0}
    ident = Mesh.identity(mesh.w, mesh.h, mesh.cols, mesh.rows,
                          mesh.us, mesh.vs)
    moved = 0
    curved = 0
    top = 0.0
    for a, b in zip(mesh.nodes, ident.nodes):
        d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
        if d >= 0.5:
            moved += 1
        if d > top:
            top = d
        # 只数「手拖过」的把手：自动把手会跟着位置走，不算用户弯了几处
        if not a.get("a", 1):
            du = math.hypot(a["ux"] - b["ux"], a["uy"] - b["uy"])
            dv = math.hypot(a["vx"] - b["vx"], a["vy"] - b["vy"])
            if max(du, dv) >= 0.5:
                curved += 1
    return {"cols": mesh.cols, "rows": mesh.rows, "moved": moved,
            "curved": curved, "max_shift": top}
