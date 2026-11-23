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


def have_numpy():
    return _np is not None and USE_NUMPY


def _dist(a, b):
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


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

    __slots__ = ("cols", "rows", "w", "h", "nodes")

    def __init__(self, cols, rows, nodes, w=0, h=0):
        self.cols = max(1, int(cols))
        self.rows = max(1, int(rows))
        self.w = w
        self.h = h
        self.nodes = nodes

    # -- 基本访问 ----------------------------------------------------------
    def node(self, i, j):
        return self.nodes[j * (self.cols + 1) + i]

    def cell_size(self):
        """一格大致多宽多高（用原始画布尺寸算，把手长度限幅时用）。"""
        cw = (float(self.w) - 1.0) / self.cols if self.cols else 1.0
        ch = (float(self.h) - 1.0) / self.rows if self.rows else 1.0
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
                        ax, ay = q["x"] - p["x"], q["y"] - p["y"]
                    elif i == cols:
                        p, q = self.node(cols - 1, j), self.node(cols, j)
                        ax, ay = q["x"] - p["x"], q["y"] - p["y"]
                    else:
                        p, q = self.node(i - 1, j), self.node(i + 1, j)
                        ax, ay = (q["x"] - p["x"]) * 0.5, (q["y"] - p["y"]) * 0.5
                    chords = []
                    if i > 0:
                        chords.append(_dist(self.node(i - 1, j), n))
                    if i < cols:
                        chords.append(_dist(self.node(i + 1, j), n))
                    lim_u = max(1e-3, min(chords)) if chords else 0.0
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
                        bx_, by_ = q["x"] - p["x"], q["y"] - p["y"]
                    elif j == rows:
                        p, q = self.node(i, rows - 1), self.node(i, rows)
                        bx_, by_ = q["x"] - p["x"], q["y"] - p["y"]
                    else:
                        p, q = self.node(i, j - 1), self.node(i, j + 1)
                        bx_, by_ = (q["x"] - p["x"]) * 0.5, (q["y"] - p["y"]) * 0.5
                    chords = []
                    if j > 0:
                        chords.append(_dist(self.node(i, j - 1), n))
                    if j < rows:
                        chords.append(_dist(self.node(i, j + 1), n))
                    lim_v = max(1e-3, min(chords)) if chords else 0.0
                norm = math.hypot(bx_, by_)
                if lim_v > 0.0 and norm > lim_v:
                    k = lim_v / norm
                    bx_ *= k
                    by_ *= k
                n["vx"], n["vy"] = bx_, by_
        return self

    # -- 构造 --------------------------------------------------------------
    @classmethod
    def identity(cls, w, h, cols=3, rows=3):
        """恒等网格：交点在均匀栅格上，切向 = 格宽/格高。"""
        cols = max(1, min(MAX_CELLS, int(cols)))
        rows = max(1, min(MAX_CELLS, int(rows)))
        cw = (float(w) - 1.0) / cols if w else 1.0
        ch = (float(h) - 1.0) / rows if h else 1.0
        nodes = []
        for j in range(rows + 1):
            for i in range(cols + 1):
                nodes.append({"x": i * cw, "y": j * ch,
                              "ux": cw, "uy": 0.0, "vx": 0.0, "vy": ch, "a": 1})
        return cls(cols, rows, nodes, w, h)

    def copy(self):
        return Mesh(self.cols, self.rows,
                    [dict(n) for n in self.nodes], self.w, self.h)

    def scaled(self, f):
        """整体缩放（图层坐标 → 预览坐标用）。f 是倍率。"""
        nodes = []
        for n in self.nodes:
            nodes.append({"x": n["x"] * f, "y": n["y"] * f,
                          "ux": n["ux"] * f, "uy": n["uy"] * f,
                          "vx": n["vx"] * f, "vy": n["vy"] * f,
                          "a": n.get("a", 1)})
        return Mesh(self.cols, self.rows, nodes, self.w * f, self.h * f)

    def position_only_copy(self):
        """只保留交点位置、把手全部回到自动（网格线是直的）。"""
        out = Mesh.identity(self.w, self.h, self.cols, self.rows)
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
        for j in range(rows + 1):
            for i in range(cols + 1):
                n = self.node(i, j)
                if abs(n["x"] - i * cw) > tol or abs(n["y"] - j * ch) > tol:
                    return False
                if abs(n["ux"] - cw) > tol or abs(n["uy"]) > tol:
                    return False
                if abs(n["vx"]) > tol or abs(n["vy"] - ch) > tol:
                    return False
        return True

    # -- 求值 --------------------------------------------------------------
    def _cell(self, u, v):
        """全局参数 (u,v) → (格子索引, 格内参数 s,t)。"""
        cols, rows = self.cols, self.rows
        ci = int(math.floor(u))
        cj = int(math.floor(v))
        if ci < 0:
            ci = 0
        elif ci > cols - 1:
            ci = cols - 1
        if cj < 0:
            cj = 0
        elif cj > rows - 1:
            cj = rows - 1
        s = u - ci
        t = v - cj
        # 边界外一律按边界算：Bezier 在 [0,1] 之外是外插，三次曲线会飞出去
        if s < 0.0:
            s = 0.0
        elif s > 1.0:
            s = 1.0
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        return ci, cj, s, t

    def eval_uv(self, u, v):
        """参数 (u,v) → 变形后的图像坐标。u∈[0,cols]，v∈[0,rows]。"""
        ci, cj, s, t = self._cell(u, v)
        bx, by = _cell_ctrl(self, ci, cj)
        return _patch(bx, by, s, t)[:2]

    def eval_full(self, u, v):
        """同上，外加两个切向（重采样网格时用）。"""
        ci, cj, s, t = self._cell(u, v)
        bx, by = _cell_ctrl(self, ci, cj)
        return _patch(bx, by, s, t)

    def grid_polylines(self, steps=10):
        """把变形后的网格线画成一串折线（图像坐标），给对话框用。"""
        steps = max(2, int(steps))
        lines = []
        for i in range(self.cols + 1):                  # 竖线：u 固定
            pts = []
            for j in range(self.rows):
                for k in range(steps + 1):
                    if j and k == 0:
                        continue                        # 接缝不重复点
                    pts.append(self.eval_uv(i, j + k / float(steps)))
            lines.append(pts)
        for j in range(self.rows + 1):                  # 横线：v 固定
            pts = []
            for i in range(self.cols):
                for k in range(steps + 1):
                    if i and k == 0:
                        continue
                    pts.append(self.eval_uv(i + k / float(steps), j))
            lines.append(pts)
        return lines

    def handle(self, i, j, axis, sign):
        """把手圆点的位置：节点 + sign·切向/3（控制点就在 1/3 处）。"""
        n = self.node(i, j)
        if axis == "u":
            return (n["x"] + sign * n["ux"] / 3.0,
                    n["y"] + sign * n["uy"] / 3.0)
        return (n["x"] + sign * n["vx"] / 3.0,
                n["y"] + sign * n["vy"] / 3.0)

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


# ---- 曲面片求值 ------------------------------------------------------------

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
    bx = [0.0] * 16
    by = [0.0] * 16

    def put(a, b, x, y):
        bx[a * 4 + b] = x
        by[a * 4 + b] = y

    put(0, 0, n00["x"], n00["y"])
    put(0, 3, n01["x"], n01["y"])
    put(3, 0, n10["x"], n10["y"])
    put(3, 3, n11["x"], n11["y"])

    put(0, 1, n00["x"] + n00["vx"] / 3.0, n00["y"] + n00["vy"] / 3.0)
    put(0, 2, n01["x"] - n01["vx"] / 3.0, n01["y"] - n01["vy"] / 3.0)
    put(3, 1, n10["x"] + n10["vx"] / 3.0, n10["y"] + n10["vy"] / 3.0)
    put(3, 2, n11["x"] - n11["vx"] / 3.0, n11["y"] - n11["vy"] / 3.0)

    put(1, 0, n00["x"] + n00["ux"] / 3.0, n00["y"] + n00["uy"] / 3.0)
    put(2, 0, n10["x"] - n10["ux"] / 3.0, n10["y"] - n10["uy"] / 3.0)
    put(1, 3, n01["x"] + n01["ux"] / 3.0, n01["y"] + n01["uy"] / 3.0)
    put(2, 3, n11["x"] - n11["ux"] / 3.0, n11["y"] - n11["uy"] / 3.0)

    tx = (n11["x"] - n10["x"] - n01["x"] + n00["x"]) / 9.0
    ty = (n11["y"] - n10["y"] - n01["y"] + n00["y"]) / 9.0
    put(1, 1, n00["x"] + (n00["ux"] + n00["vx"]) / 3.0 + tx,
              n00["y"] + (n00["uy"] + n00["vy"]) / 3.0 + ty)
    put(1, 2, n01["x"] + (n01["ux"] - n01["vx"]) / 3.0 + tx,
              n01["y"] + (n01["uy"] - n01["vy"]) / 3.0 + ty)
    put(2, 1, n10["x"] + (-n10["ux"] + n10["vx"]) / 3.0 + tx,
              n10["y"] + (-n10["uy"] + n10["vy"]) / 3.0 + ty)
    put(2, 2, n11["x"] + (-n11["ux"] - n11["vx"]) / 3.0 + tx,
              n11["y"] + (-n11["uy"] - n11["vy"]) / 3.0 + ty)
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
    cache = {}
    for _i in range(iters):
        ci = int(math.floor(u))
        cj = int(math.floor(v))
        ci = 0 if ci < 0 else (cols - 1 if ci > cols - 1 else ci)
        cj = 0 if cj < 0 else (rows - 1 if cj > rows - 1 else cj)
        key = (ci, cj)
        ctrl = cache.get(key)
        if ctrl is None:
            ctrl = _cell_ctrl(mesh, ci, cj)
            cache[key] = ctrl
        bx, by = ctrl
        px, py, psx, psy, ptx, pty = _patch(bx, by, u - ci, v - cj)
        ex = x - px
        ey = y - py
        if ex * ex + ey * ey <= tol * tol:
            break
        det = psx * pty - psy * ptx
        if abs(det) < 1e-9:                     # 折了：这一步没救，保持原位
            break
        du = (pty * ex - ptx * ey) / det
        dv = (-psy * ex + psx * ey) / det
        step = max(abs(du), abs(dv))
        if step > NEWTON_STEP:                  # 见 NEWTON_STEP 的注释：不限步会震
            k = NEWTON_STEP / step
            du *= k
            dv *= k
        u += du
        v += dv
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

    for _i in range(iters):
        ci = np.clip(np.floor(u).astype(np.int64), 0, cols - 1)
        cj = np.clip(np.floor(v).astype(np.int64), 0, rows - 1)
        cells = cj * cols + ci
        s = u - ci
        t = v - cj
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
        u = np.clip(u + du * k, 0.0, cols)
        v = np.clip(v + dv * k, 0.0, rows)
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
    """反向：Mesh → parse_mesh_string 能读回的字符串（两位小数）。"""
    parts = ["%d,%d" % (mesh.cols, mesh.rows)]
    for n in mesh.nodes:
        parts.append("%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%d"
                     % (n["x"], n["y"], n["ux"], n["uy"],
                        n["vx"], n["vy"], int(n.get("a", 1))))
    return "; ".join(parts)


def mesh_summary(mesh):
    """对话框底部那行小字：几个点动过、把手弯了几个、最大位移多少。"""
    if mesh is None:
        return {"cols": 0, "rows": 0, "moved": 0, "curved": 0, "max_shift": 0.0}
    ident = Mesh.identity(mesh.w, mesh.h, mesh.cols, mesh.rows)
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
