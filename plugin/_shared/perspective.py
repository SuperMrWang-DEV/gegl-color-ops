# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 消失点 / 透视平面数学
 ---------------------------------------------------------------------------
 purpose   给 GIMP 3 补上 PS 的「滤镜 → 消失点」（Vanishing Point）。

           一个**平面**就是画布上的一个四边形，它代表三维世界里的一块矩形。
           四边形四角 ↔ 世界坐标的 (0,0)/(1,0)/(1,1)/(0,1)，于是有一个
           单应矩阵 H 把世界平面的 (s,t) 映射到图像坐标。

           三个能力都建在这一个 H 上：
             1. **透视网格**——世界里等距的线投到图像上，自然收敛到消失点；
             2. **贴图**——把一张图按「四角对四角」透视变形贴到平面上；
             3. **拉正**——反过来，把平面里的一块逆透视拉成矩形。

           还有一条纯射影几何的事实撑着「多平面」：
             三个**互相垂直**方向的消失点构成一个三角形，而主点（画布中心）
             正是这个三角形的**垂心**。所以知道两个消失点就能算出第三个——
             不用相机内参、不用焦距，只假设「主点在画面中心」。
             相邻的那面垂直墙就是这么定出来的。

 note      三条非踩不可的：
           1. **单应必须归一化坐标再解**（Hartley）。直接拿原始像素解 8×8，
             条件数差到 1e8，纯 Python 的高斯消元会掉到 1e-3 精度，
             四边形一歪就贴图错位。
           2. **网格线要按分母符号断开**。世界坐标往外延伸时 w 会过零，
             越过零点的那一段是「地平线之后」的像，和前面的点连起来
             会画出一条横穿画面的假线。
           3. **第四消失点不是「再取一个交点」**，是垂心关系。把
             垂直方向的 vanish point 当成「另一组边的交点」会得到同一个
             消失点，墙就贴到墙自己身上去了。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math

try:                        # numpy 可选：装了就走向量化采样（tools/install_gimp_numpy.py）
    import numpy as _np
except Exception:
    _np = None

USE_NUMPY = True

# 世界坐标里四角的固定顺序：左上 → 右上 → 右下 → 左下。
# 「左上」只是约定，不要求是图像里视觉上的左上——只要四个点按环序给出。
UNIT4 = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))

# 四边形最少要有这么大面积（像素²），再小就没法解单应了
MIN_AREA = 64.0
# 单应的分母（w）小于这个值就当作「在无穷远」，跳过
W_EPS = 1e-7
# 投影结果超过这个绝对值就当出界（避免 cairo 处理 1e9 的坐标）
CLAMP = 4.0e4


def have_numpy():
    return _np is not None and USE_NUMPY


# ---- 3×3 小工具 ------------------------------------------------------------

def _mat_mul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def _mat_inv(M):
    a, b, c = M[0]
    d, e, f = M[1]
    g, h, i = M[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-14:
        raise ValueError("singular matrix")
    inv = [[(e * i - f * h), -(b * i - c * h), (b * f - c * e)],
           [-(d * i - f * g), (a * i - c * g), -(a * f - c * d)],
           [(d * h - e * g), -(a * h - b * g), (a * e - b * d)]]
    return [[v / det for v in row] for row in inv]


def _solve_linear(A, b):
    """高斯消元（列主元）。纯 Python，8×8 也就几百次乘加。"""
    n = len(A)
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-14:
            raise ValueError("singular system")
        if piv != col:
            M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        row = M[col]
        for k in range(col, n + 1):
            row[k] /= pv
        for r in range(n):
            if r == col:
                continue
            factor = M[r][col]
            if factor == 0.0:
                continue
            rr = M[r]
            for k in range(col, n + 1):
                rr[k] -= factor * row[k]
    return [M[i][n] for i in range(n)]


# ---- 单应 ------------------------------------------------------------------

def _normalize(pts):
    """Hartley 归一化：平移到质心、缩放到平均距离 √2。"""
    n = float(len(pts))
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    d = sum(math.hypot(p[0] - cx, p[1] - cy) for p in pts) / n
    s = (math.sqrt(2.0) / d) if d > 1e-12 else 1.0
    T = [[s, 0.0, -s * cx], [0.0, s, -s * cy], [0.0, 0.0, 1.0]]
    return [((p[0] - cx) * s, (p[1] - cy) * s) for p in pts], T


def homography(src, dst):
    """4 个（或更多）点对 → 8 个参数 h0..h7（h8 固定为 1）。

    返回的元组满足：
        w  = h6*x + h7*y + 1
        X  = (h0*x + h1*y + h2) / w
        Y  = (h3*x + h4*y + h5) / w
    """
    if len(src) != len(dst):
        raise ValueError("src/dst length mismatch")
    if len(src) < 4:
        raise ValueError("need at least 4 point pairs")
    sn, Ts = _normalize(src)
    dn, Td = _normalize(dst)
    A, b = [], []
    for (x, y), (X, Y) in zip(sn, dn):
        A.append([x, y, 1.0, 0.0, 0.0, 0.0, -X * x, -X * y])
        b.append(X)
        A.append([0.0, 0.0, 0.0, x, y, 1.0, -Y * x, -Y * y])
        b.append(Y)
    if len(A) > 8:                      # 超定（>4 点）：正规方程
        AtA = [[sum(A[k][i] * A[k][j] for k in range(len(A)))
                for j in range(8)] for i in range(8)]
        Atb = [sum(A[k][i] * b[k] for k in range(len(A))) for i in range(8)]
        h = _solve_linear(AtA, Atb)
    else:
        h = _solve_linear(A, b)
    Hn = [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]]
    H = _mat_mul(_mat_inv(Td), _mat_mul(Hn, Ts))
    if abs(H[2][2]) < 1e-14:            # h8 归一化
        k = 1.0
    else:
        k = 1.0 / H[2][2]
    return tuple((H[i][j] * k) for i in range(3) for j in range(3))[:8]


def invert_h(H):
    """单应求逆。直接用换向的点对重解，比矩阵求逆稳。"""
    h0, h1, h2, h3, h4, h5, h6, h7 = H
    M = [[h0, h1, h2], [h3, h4, h5], [h6, h7, 1.0]]
    I = _mat_inv(M)
    k = 1.0 / I[2][2]
    return (I[0][0] * k, I[0][1] * k, I[0][2] * k,
            I[1][0] * k, I[1][1] * k, I[1][2] * k,
            I[2][0] * k, I[2][1] * k)


def apply_h(H, x, y):
    """(x,y) → (X, Y, w)。w 是齐次分母，判断「地平线之后」要用。"""
    h0, h1, h2, h3, h4, h5, h6, h7 = H
    w = h6 * x + h7 * y + 1.0
    if abs(w) < W_EPS:
        return (float("nan"), float("nan"), w)
    return ((h0 * x + h1 * y + h2) / w, (h3 * x + h4 * y + h5) / w, w)


def apply_h_point(H, x, y):
    """同上，但只要坐标（不要分母）。"""
    X, Y, _w = apply_h(H, x, y)
    return X, Y


def line_intersect(a, b, c, d):
    """直线 ab 与 cd 的交点。平行/重合返回 None。"""
    x1, y1 = a
    x2, y2 = b
    x3, y3 = c
    x4, y4 = d
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4)
          - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
    py = ((x1 * y2 - y1 * x2) * (y3 - y4)
          - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
    return px, py


def third_vanish(Vu, Vv, ox=0.0, oy=0.0):
    """三个互垂方向的消失点：主点（ox,oy）是它们的垂心。

    已知 Vu、Vv，求 Vw：
        Vw 在「过 Vu 且垂直于 (Vv−O)」的直线上，也在「过 Vv 且垂直于
        (Vu−O)」的直线上。两线交点即 Vw。

    退化（Vu/Vv 跑向无穷远、或和主点重合）返回 None。
    """
    if Vu is None or Vv is None:
        return None
    d1 = (Vv[0] - ox, Vv[1] - oy)
    d2 = (Vu[0] - ox, Vu[1] - oy)
    if math.hypot(*d1) < 1e-6 or math.hypot(*d2) < 1e-6:
        return None
    # 过 Vu、方向垂直于 d1
    a1 = Vu
    b1 = (Vu[0] - d1[1], Vu[1] + d1[0])
    a2 = Vv
    b2 = (Vv[0] - d2[1], Vv[1] + d2[0])
    p = line_intersect(a1, b1, a2, b2)
    if p is None:
        return None
    if not (math.isfinite(p[0]) and math.isfinite(p[1])):
        return None
    if abs(p[0]) > 1e6 or abs(p[1]) > 1e6:
        return None
    return p


# ---- 平面 ------------------------------------------------------------------

def quad_area(c):
    a = 0.0
    for i in range(4):
        x0, y0 = c[i]
        x1, y1 = c[(i + 1) % 4]
        a += x0 * y1 - x1 * y0
    return abs(a) * 0.5


def is_convex(c):
    """四角必须构成凸四边形。凹的四边形单应会把画面折出来。"""
    signs = []
    for i in range(4):
        x0, y0 = c[i]
        x1, y1 = c[(i + 1) % 4]
        x2, y2 = c[(i + 2) % 4]
        z = (x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)
        if abs(z) < 1e-9:
            continue
        signs.append(1 if z > 0 else -1)
    return len(set(signs)) <= 1 and len(signs) >= 3


class Plane(object):
    """一块透视平面。corners 是画布坐标下的四个角，按环序。

    corners[0] ↔ 世界 (0,0)，[1] ↔ (1,0)，[2] ↔ (1,1)，[3] ↔ (0,1)。
    「世界」是这块平面的参数空间：贴图时整张源图铺满 [0,1]²，
    网格按 s = k/N 画就成了透视网格。
    """

    __slots__ = ("corners", "_H", "_Hi")

    def __init__(self, corners):
        self.corners = [[float(p[0]), float(p[1])] for p in corners[:4]]
        if len(self.corners) != 4:
            raise ValueError("a plane needs exactly 4 corners")
        self._H = None
        self._Hi = None

    # -- 基本 --------------------------------------------------------------
    def copy(self):
        return Plane([list(p) for p in self.corners])

    def centroid(self):
        return (sum(p[0] for p in self.corners) / 4.0,
                sum(p[1] for p in self.corners) / 4.0)

    def edge(self, i):
        return self.corners[i % 4], self.corners[(i + 1) % 4]

    def edge_mid(self, i):
        a, b = self.edge(i)
        return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

    def is_valid(self):
        return quad_area(self.corners) >= MIN_AREA and is_convex(self.corners)

    def invalidate(self):
        self._H = None
        self._Hi = None

    def move_corner(self, i, x, y):
        self.corners[i % 4] = [float(x), float(y)]
        self.invalidate()

    # -- 矩阵 --------------------------------------------------------------
    def H(self):
        """世界 (s,t) → 图像。"""
        if self._H is None:
            self._H = homography(UNIT4, self.corners)
        return self._H

    def Hinv(self):
        """图像 → 世界 (s,t)。"""
        if self._Hi is None:
            self._Hi = homography(self.corners, UNIT4)
        return self._Hi

    def to_world(self, x, y):
        return apply_h_point(self.Hinv(), x, y)

    def to_image(self, s, t):
        return apply_h_point(self.H(), s, t)

    def contains(self, x, y, pad=0.0):
        s, t = self.to_world(x, y)
        if not (math.isfinite(s) and math.isfinite(t)):
            return False
        return (-pad <= s <= 1.0 + pad) and (-pad <= t <= 1.0 + pad)

    # -- 消失点 ------------------------------------------------------------
    def vanish_uv(self):
        """平面自身两个方向（u = 上边方向，v = 左边方向）的消失点。

        平行的一对边在图像里本该交于无穷远——那就是「没有透视」，
        返回 None。
        """
        c = self.corners
        Vu = line_intersect(c[0], c[1], c[3], c[2])
        Vv = line_intersect(c[0], c[3], c[1], c[2])
        return Vu, Vv

    def vanish_w(self, w, h):
        """垂直于平面方向的消失点（靠垂心关系算，见 third_vanish）。"""
        Vu, Vv = self.vanish_uv()
        return third_vanish(Vu, Vv, w * 0.5, h * 0.5)

    # -- 延伸 --------------------------------------------------------------
    def extend(self, side, along="w", amount=0.6, w=0.0, h=0.0):
        """沿第 side 条边拖出一块新平面，和原平面共用这条边。

        along="w"  —— 垂直于这块平面（PS 的默认：右墙 → 正对着的那面墙）；
        along="v"  —— 在这块平面自己的世界里接着铺（同方向延伸）。

        新平面的两个远角**不能**都取「p + t·(V−p) 里的同一个 t**：
        那样 q1−q0 会恰好平行于 p1−p0，等于把透视扔了（实测新平面的
        u 方向消失点跑到 1e16 之外）。正确做法是让 q0 落在 p0 的射线上，
        再让 q1 落在 p1 的射线上**而且** q0q1 过共享边方向的消失点——
        那一族平行线本来就该收敛到那儿。
        """
        side = int(side) % 4
        p0, p1 = self.edge(side)
        Vu, Vv = self.vanish_uv()
        # 共享边本身就是新平面的「u」方向
        Vside = Vu if side in (0, 2) else Vv
        if along == "w":
            Vout = third_vanish(Vu, Vv, w * 0.5, h * 0.5)
        else:
            Vout = Vv if side in (0, 2) else Vu

        chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) or 1.0
        # 边的外法向：朝远处延伸的那一侧
        nx, ny = (p1[1] - p0[1]) / chord, -(p1[0] - p0[0]) / chord
        cx, cy = self.centroid()
        mx, my = (p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5
        if (mx + nx - cx) ** 2 + (my + ny - cy) ** 2 < \
           (mx - nx - cx) ** 2 + (my - ny - cy) ** 2:
            nx, ny = -nx, -ny

        d = amount * chord
        flat = Plane([[p0[0], p0[1]], [p1[0], p1[1]],
                      [p1[0] + nx * d, p1[1] + ny * d],
                      [p0[0] + nx * d, p0[1] + ny * d]])
        if Vout is None or Vside is None:
            # 这个方向上压根没有消失点（近似平行投影）：按法向平移。
            # 网格不收敛，但形状是对的。
            return flat

        # 深度线必须指向 Vout。Vout 落在平面哪一侧不确定，先把它翻到外侧。
        ux, uy = Vout[0] - p0[0], Vout[1] - p0[1]
        if ux * nx + uy * ny <= 0.0:
            ux, uy = -ux, -uy
        ln = math.hypot(ux, uy)
        if ln < 1e-6:
            return flat
        q0 = (p0[0] + ux * d / ln, p0[1] + uy * d / ln)
        # q1：既在 p1→Vout 的直线上，又在过 q0 与 Vside 的直线上
        q1 = line_intersect(p1, Vout, q0, Vside)
        if q1 is None or not (math.isfinite(q1[0]) and math.isfinite(q1[1])) \
           or abs(q1[0]) > 1e6 or abs(q1[1]) > 1e6:
            return flat
        out = Plane([p0, p1, q1, q0])
        # 交点落在错的一侧时四边形会翻折，宁可退回平行版
        if not out.is_valid():
            return flat
        return out

    # -- 网格 --------------------------------------------------------------
    def grid_lines(self, steps=4, reach=1.6, samples=26):
        """透视网格。返回若干条折线（每条是点列表，画布坐标）。

        s/t 从 −reach 走到 1+reach，所以网格会越过四边形往外延伸、
        收敛到消失点——这才是「消失点」看着该有的样子。
        """
        steps = max(1, int(steps))
        H = self.H()
        out = []
        lo, hi = -reach, 1.0 + reach
        n = steps * 1
        k0 = int(math.floor(lo * n))
        k1 = int(math.ceil(hi * n))
        for k in range(k0, k1 + 1):
            v = k / float(n)
            if v < lo - 1e-9 or v > hi + 1e-9:
                continue
            for vertical in (False, True):
                pts, cur = [], []
                for j in range(samples + 1):
                    u = lo + (hi - lo) * j / float(samples)
                    sx, sy = (v, u) if vertical else (u, v)
                    X, Y, ww = apply_h(H, sx, sy)
                    ok = (ww > W_EPS and math.isfinite(X) and math.isfinite(Y)
                          and abs(X) < CLAMP and abs(Y) < CLAMP)
                    if ok:
                        cur.append((X, Y))
                    else:
                        if len(cur) >= 2:
                            pts.append(cur)
                        cur = []
                if len(cur) >= 2:
                    pts.append(cur)
                out.extend(pts)
        return out


# ---- 采样：贴图与拉正 ------------------------------------------------------

def _bilinear(src, sw, sh, sx, sy):
    """src 是 bytes 的 RGBA。返回 (r,g,b,a)。"""
    x0 = int(math.floor(sx))
    y0 = int(math.floor(sy))
    if x0 < 0:
        x0 = 0
    elif x0 > sw - 2:
        x0 = max(0, sw - 2)
    if y0 < 0:
        y0 = 0
    elif y0 > sh - 2:
        y0 = max(0, sh - 2)
    fx = sx - x0
    fy = sy - y0
    o00 = (y0 * sw + x0) * 4
    o10 = o00 + 4
    o01 = o00 + sw * 4
    o11 = o01 + 4
    w00 = (1.0 - fx) * (1.0 - fy)
    w10 = fx * (1.0 - fy)
    w01 = (1.0 - fx) * fy
    w11 = fx * fy
    return (
        src[o00] * w00 + src[o10] * w10 + src[o01] * w01 + src[o11] * w11,
        src[o00 + 1] * w00 + src[o10 + 1] * w10 + src[o01 + 1] * w01 + src[o11 + 1] * w11,
        src[o00 + 2] * w00 + src[o10 + 2] * w10 + src[o01 + 2] * w01 + src[o11 + 2] * w11,
        src[o00 + 3] * w00 + src[o10 + 3] * w10 + src[o01 + 3] * w01 + src[o11 + 3] * w11,
    )


def _poly_dir(poly):
    """凸多边形是逆时针还是顺时针（同号叉积判据的符号）。"""
    if poly is None:
        return 1.0
    a = 0.0
    for i in range(4):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % 4]
        a += ax * by - bx * ay
    return 1.0 if a > 0 else -1.0


def _in_poly(poly, pdir, x, y):
    for i in range(4):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % 4]
        z = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
        if z * pdir < -1e-7:
            return False
    return True


def _bbox(corners, w, h):
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    x0 = max(0, int(math.floor(min(xs))) - 1)
    y0 = max(0, int(math.floor(min(ys))) - 1)
    x1 = min(w, int(math.ceil(max(xs))) + 2)
    y1 = min(h, int(math.ceil(max(ys))) + 2)
    return x0, y0, x1, y1


def paste_into(dst, w, h, src, sw, sh, corners, mix=True, progress=None):
    """把 src 整幅透视贴到 corners 上，返回新的 RGBA bytes（对 dst 做**拷贝**后改）。

    「整幅」= src 四角 ↔ corners 四角。反解每个目标像素落在 src 的哪儿，
    落在源图外面就不动 dst。mix=True 时按源的 alpha 混合。
    """
    if sw < 2 or sh < 2:
        raise ValueError("source too small")
    H = homography(((0.0, 0.0), (float(sw), 0.0),
                    (float(sw), float(sh)), (0.0, float(sh))), corners)
    Hi = invert_h(H)
    out = bytearray(dst)
    x0, y0, x1, y1 = _bbox(corners, w, h)
    if x1 <= x0 or y1 <= y0:
        return bytes(out)
    if have_numpy():
        _paste_np(out, w, h, src, sw, sh, Hi, x0, y0, x1, y1, mix, progress)
    else:
        _paste_py(out, w, h, src, sw, sh, Hi, x0, y0, x1, y1, mix, progress)
    return bytes(out)


def _paste_py(out, w, h, src, sw, sh, Hi, x0, y0, x1, y1, mix, progress,
              bounds=None, poly=None):
    h0, h1, h2, h3, h4, h5, h6, h7 = Hi
    pdir = _poly_dir(poly)
    # bounds 把「落在源图哪儿才算数」限制成一个子窗口。多面片贴图时用：
    # 少了它，每块面片都会顺着 v 方向溢出自己的四边形，盖到邻面上。
    smin, tmin, smax, tmax = bounds or (0.0, 0.0, sw - 1.0, sh - 1.0)
    rows = float(max(1, y1 - y0))
    for y in range(y0, y1):
        base = y * w * 4
        for x in range(x0, x1):
            den = h6 * x + h7 * y + 1.0
            if den <= W_EPS:
                continue
            sx = (h0 * x + h1 * y + h2) / den
            sy = (h3 * x + h4 * y + h5) / den
            if sx < smin or sx > smax or sy < tmin or sy > tmax:
                continue
            if poly is not None and not _in_poly(poly, pdir, x, y):
                continue
            r, g, b, a = _bilinear(src, sw, sh, sx, sy)
            if a <= 0.5:
                continue
            o = base + x * 4
            if mix:
                k = a / 255.0
                out[o] = int(r * k + out[o] * (1.0 - k))
                out[o + 1] = int(g * k + out[o + 1] * (1.0 - k))
                out[o + 2] = int(b * k + out[o + 2] * (1.0 - k))
                out[o + 3] = max(out[o + 3], int(a))
            else:
                out[o] = int(r)
                out[o + 1] = int(g)
                out[o + 2] = int(b)
                out[o + 3] = int(a)
        if progress:
            progress((y - y0) / rows)


def _paste_np(out, w, h, src, sw, sh, Hi, x0, y0, x1, y1, mix, progress,
              arr=None, bounds=None, poly=None, sarr=None):
    np = _np
    pdir = _poly_dir(poly)
    h0, h1, h2, h3, h4, h5, h6, h7 = Hi
    smin, tmin, smax, tmax = bounds or (0.0, 0.0, sw - 1.0, sh - 1.0)
    if sarr is None:
        sarr = np.frombuffer(src, dtype=np.uint8).reshape(sh, sw, 4).astype(np.float32)
    # frombuffer 出来的是只读视图，必须 copy 一份才能就地写
    dst_arr = arr
    if dst_arr is None:
        dst_arr = np.array(np.frombuffer(bytes(out), dtype=np.uint8)).reshape(h, w, 4)
    xs = np.arange(x0, x1, dtype=np.float64)
    chunk = 256
    rows = float(max(1, y1 - y0))
    for ya in range(y0, y1, chunk):
        yb = min(y1, ya + chunk)
        ys = np.arange(ya, yb, dtype=np.float64)[:, None]
        X = xs[None, :]
        den = h6 * X + h7 * ys + 1.0
        good = den > W_EPS
        safe = np.where(good, den, 1.0)
        sx = (h0 * X + h1 * ys + h2) / safe
        sy = (h3 * X + h4 * ys + h5) / safe
        good &= ((sx >= smin) & (sx <= smax)
                 & (sy >= tmin) & (sy <= tmax))
        for k in range(4 if poly is not None else 0):
            ax, ay = poly[k]
            bx, by = poly[(k + 1) % 4]
            zz = (bx - ax) * (ys - ay) - (by - ay) * (X - ax)
            good &= (zz * pdir) >= -1e-7
        xi = np.floor(sx).astype(np.int32)
        yi = np.floor(sy).astype(np.int32)
        np.clip(xi, 0, max(0, sw - 2), out=xi)
        np.clip(yi, 0, max(0, sh - 2), out=yi)
        fx = sx - xi                       # 保持 float64：float32 的权重
        fy = sy - yi                       # 会跟纯 Python 差 1~2 个色阶
        v00 = sarr[yi, xi]
        v10 = sarr[yi, xi + 1]
        v01 = sarr[yi + 1, xi]
        v11 = sarr[yi + 1, xi + 1]
        w00 = ((1.0 - fx) * (1.0 - fy))[:, :, None]
        w10 = (fx * (1.0 - fy))[:, :, None]
        w01 = ((1.0 - fx) * fy)[:, :, None]
        w11 = (fx * fy)[:, :, None]
        col = v00 * w00 + v10 * w10 + v01 * w01 + v11 * w11
        a = col[:, :, 3]
        if not mix:
            block = dst_arr[ya:yb, x0:x1]
            m3 = good[:, :, None]
            out_col = np.where(m3, np.clip(col, 0, 255).astype(np.uint8), block)
            dst_arr[ya:yb, x0:x1] = out_col
        else:
            m = good & (a > 0.5)
            k = (a / 255.0)[:, :, None]
            block = dst_arr[ya:yb, x0:x1].astype(np.float32)
            blended = col * k + block * (1.0 - k)
            blended[:, :, 3] = np.maximum(block[:, :, 3], a)
            m4 = m[:, :, None]
            dst_arr[ya:yb, x0:x1] = np.where(
                m4, np.clip(blended, 0, 255).astype(np.uint8), block.astype(np.uint8))
        if progress:
            progress((yb - y0) / rows)
    if arr is None:
        out[:] = dst_arr.tobytes()


def paste_many(dst, w, h, src, sw, sh, mappings, mix=True, progress=None):
    """一次把好几块四边形贴到同一张 dst 上（后面的盖前面的）。

    mappings 每项是 (Hi, x0, y0, x1, y1[, bounds[, poly]])：图像 → 源坐标的
    逆单应、包围盒，可选 bounds=(s0,t0,s1,t1) 限定只看源图的这一块，
    可选 poly 给出要裁剪的凸四边形。多面片贴图时两个都要给：bounds 挡住
    沿 v 方向的溢出，poly 挡住「逆单应越过无穷远线」之后在包围盒另一角
    冒出来的零星像素。
    顺着贴多重面的贴图要共用一份像素数组，逐块贴会每次拷贝整幅图。
    """
    out = bytearray(dst)
    if not mappings:
        return bytes(out)
    rows_total = float(sum(max(0, m[4] - m[2]) for m in mappings)) or 1.0
    arr = None
    sarr = None
    if have_numpy():
        arr = _np.array(_np.frombuffer(bytes(out), dtype=_np.uint8)
                        ).reshape(h, w, 4)
        # 源图转一次 float32 就够：每个面片各转一遍等于白烧 17 MB × 面数
        sarr = _np.frombuffer(src, dtype=_np.uint8).reshape(sh, sw, 4).astype(
            _np.float32)
    done = 0.0
    for m in mappings:
        Hi, x0, y0, x1, y1 = m[:5]
        bounds = m[5] if len(m) > 5 else None
        poly = m[6] if len(m) > 6 else None
        if x1 <= x0 or y1 <= y0:
            continue
        base, span = done, float(max(1, y1 - y0))

        def _cb(frac, base=base, span=span):
            if progress:
                progress((base + frac * span) / rows_total)

        if arr is not None:
            _paste_np(out, w, h, src, sw, sh, Hi, x0, y0, x1, y1, mix, _cb,
                      arr=arr, bounds=bounds, poly=poly, sarr=sarr)
        else:
            _paste_py(out, w, h, src, sw, sh, Hi, x0, y0, x1, y1, mix, _cb,
                      bounds=bounds, poly=poly)
        done += span
    if arr is not None:
        out[:] = arr.tobytes()
    return bytes(out)


def rectify_size(corners):
    """拉正后的矩形尺寸：上/下边平均做宽，左/右边平均做高。"""
    a = math.hypot(corners[1][0] - corners[0][0], corners[1][1] - corners[0][1])
    b = math.hypot(corners[2][0] - corners[3][0], corners[2][1] - corners[3][1])
    c = math.hypot(corners[3][0] - corners[0][0], corners[3][1] - corners[0][1])
    d = math.hypot(corners[2][0] - corners[1][0], corners[2][1] - corners[1][1])
    return max(2, int(round((a + b) * 0.5))), max(2, int(round((c + d) * 0.5)))


def rectify(src, sw, sh, corners, out_w, out_h, progress=None):
    """把 corners 里那块画面逆透视拉成 out_w×out_h 的矩形。返回 RGBA bytes。

    和 paste_into 正好互逆：那边是「源图四角 → corners」，
    这边是「corners → 输出矩形」。
    """
    if out_w < 2 or out_h < 2:
        raise ValueError("output too small")
    H = homography(UNIT4, corners)
    out = bytearray(out_w * out_h * 4)
    if have_numpy():
        _rectify_np(out, out_w, out_h, src, sw, sh, H, progress)
    else:
        _rectify_py(out, out_w, out_h, src, sw, sh, H, progress)
    return bytes(out)


def _rectify_py(out, ow, oh, src, sw, sh, H, progress):
    h0, h1, h2, h3, h4, h5, h6, h7 = H
    smax, tmax = sw - 1.0, sh - 1.0
    for y in range(oh):
        t = (y + 0.5) / oh
        base = y * ow * 4
        for x in range(ow):
            s = (x + 0.5) / ow
            den = h6 * s + h7 * t + 1.0
            if den <= W_EPS:
                continue
            sx = (h0 * s + h1 * t + h2) / den
            sy = (h3 * s + h4 * t + h5) / den
            if sx < 0.0 or sx > smax or sy < 0.0 or sy > tmax:
                continue
            r, g, b, a = _bilinear(src, sw, sh, sx, sy)
            o = base + x * 4
            out[o] = int(r)
            out[o + 1] = int(g)
            out[o + 2] = int(b)
            out[o + 3] = int(a)
        if progress:
            progress((y + 1) / float(oh))


def _rectify_np(out, ow, oh, src, sw, sh, H, progress):
    np = _np
    h0, h1, h2, h3, h4, h5, h6, h7 = H
    sarr = np.frombuffer(src, dtype=np.uint8).reshape(sh, sw, 4).astype(np.float32)
    oarr = np.array(np.frombuffer(bytes(out), dtype=np.uint8)).reshape(oh, ow, 4)
    smax, tmax = sw - 1.0, sh - 1.0
    ss = (np.arange(ow, dtype=np.float64) + 0.5) / ow
    chunk = 256
    for ya in range(0, oh, chunk):
        yb = min(oh, ya + chunk)
        ts = ((np.arange(ya, yb, dtype=np.float64) + 0.5) / oh)[:, None]
        S = ss[None, :]
        den = h6 * S + h7 * ts + 1.0
        good = den > W_EPS
        safe = np.where(good, den, 1.0)
        sx = (h0 * S + h1 * ts + h2) / safe
        sy = (h3 * S + h4 * ts + h5) / safe
        good &= (sx >= 0.0) & (sx <= smax) & (sy >= 0.0) & (sy <= tmax)
        xi = np.clip(np.floor(sx).astype(np.int32), 0, max(0, sw - 2))
        yi = np.clip(np.floor(sy).astype(np.int32), 0, max(0, sh - 2))
        fx = sx - xi                       # 保持 float64：float32 的权重
        fy = sy - yi                       # 会跟纯 Python 差 1~2 个色阶
        v00 = sarr[yi, xi]
        v10 = sarr[yi, xi + 1]
        v01 = sarr[yi + 1, xi]
        v11 = sarr[yi + 1, xi + 1]
        col = (v00 * ((1.0 - fx) * (1.0 - fy))[:, :, None]
               + v10 * (fx * (1.0 - fy))[:, :, None]
               + v01 * ((1.0 - fx) * fy)[:, :, None]
               + v11 * (fx * fy)[:, :, None])
        m4 = good[:, :, None]
        oarr[ya:yb, :, :] = np.where(m4, np.clip(col, 0, 255).astype(np.uint8), 0)
        if progress:
            progress((yb) / float(oh))
    out[:] = oarr.tobytes()


# ---- 序列化 ----------------------------------------------------------------

def format_plane_string(planes):
    """Planes → "x0,y0,x1,y1,x2,y2,x3,y3 | …"（两位小数）。"""
    parts = []
    for p in planes:
        parts.append(",".join("%.2f,%.2f" % (c[0], c[1]) for c in p.corners))
    return " | ".join(parts)


def parse_plane_string(text, w=0, h=0, clamp=True):
    """反过来。一段 4 组坐标算一个平面：写成 8 个数就够，写 2 个也认（按比例补）。
    解析不出来就返回空列表——不会抛，调用方好退回到默认平面。
    """
    out = []
    for raw in (text or "").replace("\n", "|").split("|"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            vals = [float(v) for v in raw.replace(";", ",")
                    .replace(",", " ").split()]
        except ValueError:
            continue
        if len(vals) >= 8:
            pts = [[vals[i], vals[i + 1]] for i in range(0, 8, 2)]
        elif len(vals) >= 6:            # 只给了 3 角：第四角补成平行四边形
            pts = [[vals[0], vals[1]], [vals[2], vals[3]], [vals[4], vals[5]],
                   [vals[0] + vals[4] - vals[2], vals[1] + vals[5] - vals[3]]]
        else:
            continue
        if clamp and w > 0 and h > 0:
            for p in pts:
                p[0] = min(max(p[0], 0.0), float(w) - 1.0)
                p[1] = min(max(p[1], 0.0), float(h) - 1.0)
        try:
            out.append(Plane(pts))
        except Exception:
            continue
    return out


def default_quad(w, h):
    """没有给平面时的默认四边形。

    刻意带一点**俯视透视**（上边窄、下边宽，左右也不平行）：一个轴对齐
    的矩形两组边各自平行，压根没有消失点——用户一打开就看不出这是
    「消失点」工具，网格也是死板的方块。这一组参数实测三个消失点都在，
    垂直方向的落在画面内（640, 695），拖边延伸出去立刻就是一面墙。
    """
    if w < 8 or h < 8:
        return Plane([(0, 0), (w - 1, 0), (w - 1, h - 1), (0, h - 1)])
    return Plane([(0.28 * w, 0.28 * h), (0.72 * w, 0.25 * h),
                  (0.86 * w, 0.80 * h), (0.14 * w, 0.78 * h)])


def plane_summary(planes, w=0, h=0):
    """对话框底部那行小字。"""
    info = {"count": len(planes), "valid": 0, "vanish": None,
            "area": 0.0, "rectified": None}
    for p in planes:
        if p.is_valid():
            info["valid"] += 1
            info["area"] += quad_area(p.corners)
    if planes:
        p = planes[0]
        Vu, Vv = p.vanish_uv()
        Vw = p.vanish_w(w, h) if w and h else None
        info["vanish"] = (Vu, Vv, Vw)
        info["rectified"] = rectify_size(p.corners)
    return info
