# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 木偶变形的 ARAP 解算器 —— 需要 numpy
 ---------------------------------------------------------------------------
 purpose   给「木偶变形」提供第三种模式：ARAP（As-Rigid-As-Possible）。
           MLS 的仿射解在**大角度**旋转/弯曲时会把内容压扁（最小二乘只能
           全局拟合一个仿射），PS 的木偶变形之所以能拧胳膊，是因为它在网格上
           解 ARAP：每个顶点只允许「刚体变换 + 极小残差」。

           这里解的是标准 ARAP 能量：
             E(X) = Σ_i Σ_{j∈N(i)} w_ij |(x_i - x_j) - R_i (v_i - v_j)|²
           交替做两件事直到收敛：
             局部  R_i = argmax tr(R_i S_i),  S_i = Σ_j w_ij (v_i-v_j)(x_i-x_j)^T
             全局  Σ_j w_ij (x_i - x_j) = Σ_j (w_ij/2)(R_i+R_j)(v_i-v_j)

 四个实现要点（都为了「能真的用」）：

  1. **2×2 的 R 用闭式解，不做 SVD**。tr(R S) = cosθ·(S00+S11) +
     sinθ·(S01-S10)，直接 atan2 出角度，比批量 SVD 快一个量级。

  2. **法方程预分解**。钉子原地不动、只拖动目标时，左端矩阵不变，
     `inv` 只算一次（V≈1700 时 ~70 ms），之后每次迭代只是一次
     (V,V)@(V,2) 的乘法（~2 ms）。拖钉子的预览就是靠这个做到实时的。

  3. **钉子用硬约束（Dirichlet），不是软约束**。这一条最容易写错：
     把约束以「大权重」加进 Laplacian（软约束）看着更简单，但钉子的合力
     不为零，而 L 的零空间是常数向量，系统就把整张网格抬成一个均匀平移
     ——实测整幅画面平移到钉子位移，一个顶点都不形变。改成「钉子覆盖的
     4 个顶点直接固定」，远处严格不动，解才是调和的形变。

  4. **只对自由顶点做分解**。约束顶点集合 C 由钉子的原位决定，拖动时不变，
     所以 L_FF 的逆可以缓存；每次迭代只是 (F,F)@(F,2) 的乘法。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math

try:
    import numpy as np
except Exception:           # 没 numpy 时整支 ARAP 不可用（MLS 仍然可用）
    np = None

# ARAP 网格沿长边取多少格。比 MLS 的场栅格粗：ARAP 的解本身就光滑，
# 48 已经能跟上手指，再密就只是让 inv 变贵。
ARAP_NODES = 48
DAMPING = 1.0e-6
# 位置锚定（弱弹簧，把每个顶点拉回原位）。ARAP 的能量只看边长，
# 「整张网格刚体转过去」是零能量解——只有一个钉子时，解会变成整个画面
# 跟着旋转/平移（实测中位位移 44 px，几乎全图都在动）。
# 加一个 0.06 的锚定（网格边权是 1）就能让远处老实待着：
# 远处不动时弹簧不受力，所以不干扰形变，只在「被带着走」的时候收口。
ANCHOR_WEIGHT = 0.06
MAX_ITERS = 12
TOLERANCE = 0.02            # px，顶点位移变化小于它就算收敛

# 最近一次预分解的结果。拖同一个钉子的目标是最高频的调用，
# 命中缓存就只有矩阵乘法。
_CACHE = {}
_CACHE_LIMIT = 3


def available():
    return np is not None


def _grid_extent(w, h, nodes):
    w = max(1, int(w))
    h = max(1, int(h))
    long_edge = max(w, h)
    if long_edge <= 2:
        return 2, 2
    step = long_edge / float(max(2, nodes) - 1)
    nx = int(math.ceil((w - 1) / step)) + 1
    ny = int(math.ceil((h - 1) / step)) + 1
    return max(2, nx), max(2, ny)


def _pin_cells(pins, w, h, nx, ny):
    """把钉子原位换成「所属单元的 4 个顶点 + 双线性权重」。

    返回 (idx, wt)，形状 (K,4)。idx 是展平后的顶点号。
    """
    sx_scale = (nx - 1.0) / (w - 1.0) if w > 1 else 0.0
    sy_scale = (ny - 1.0) / (h - 1.0) if h > 1 else 0.0
    idx = np.empty((len(pins), 4), dtype=np.int64)
    wt = np.empty((len(pins), 4), dtype=np.float64)
    for k, (sx, sy, _dx, _dy) in enumerate(pins):
        fx = min(max(sx * sx_scale, 0.0), nx - 1.0)
        fy = min(max(sy * sy_scale, 0.0), ny - 1.0)
        i = min(int(fx), max(0, nx - 2))
        j = min(int(fy), max(0, ny - 2))
        tx = fx - i
        ty = fy - j
        idx[k] = (j * nx + i, j * nx + i + 1,
                  (j + 1) * nx + i, (j + 1) * nx + i + 1)
        wt[k] = ((1 - tx) * (1 - ty), tx * (1 - ty),
                 (1 - tx) * ty, tx * ty)
    return idx, wt


def _prepare(w, h, nx, ny, pins):
    """建网格 + 法方程 + 预分解。同样的钉子原位只做一次。"""
    n = nx * ny
    gx = np.arange(nx, dtype=np.float64) * ((w - 1.0) / (nx - 1.0))
    gy = np.arange(ny, dtype=np.float64) * ((h - 1.0) / (ny - 1.0))
    X, Y = np.meshgrid(gx, gy)
    v0 = np.stack([X.ravel(), Y.ravel()], axis=1)     # (V,2)

    # 边：水平 + 垂直 + 两条对角线（四边形网格，各向同性靠对角线补）
    a = np.arange(n)
    grid = a.reshape(ny, nx)
    ei = []
    ej = []
    ei.append(grid[:, :-1].ravel()); ej.append(grid[:, 1:].ravel())
    ei.append(grid[:-1, :].ravel()); ej.append(grid[1:, :].ravel())
    ei.append(grid[:-1, :-1].ravel()); ej.append(grid[1:, 1:].ravel())
    ei.append(grid[:-1, 1:].ravel()); ej.append(grid[1:, :-1].ravel())
    e_i = np.concatenate(ei)
    e_j = np.concatenate(ej)
    e_w = np.ones(e_i.shape[0], dtype=np.float64)
    # 对角线按 1/√2 加权：它们比轴对齐的边长，权重小一点更接近等方。
    n_axis = ei[0].shape[0] + ei[1].shape[0]
    e_w[n_axis:] = 1.0 / math.sqrt(2.0)

    L = np.zeros((n, n), dtype=np.float64)
    np.add.at(L, (e_i, e_i), e_w)
    np.add.at(L, (e_j, e_j), e_w)
    np.add.at(L, (e_i, e_j), -e_w)
    np.add.at(L, (e_j, e_i), -e_w)

    pin_idx, pin_wt = _pin_cells(pins, w, h, nx, ny)
    # 钉子覆盖的顶点固定住（Dirichlet），其余顶点自由。约束集只跟原位有关，
    # 拖动时不变，所以这一份分解可以一直复用。
    constrained = np.unique(pin_idx)
    free_mask = np.ones(n, dtype=bool)
    free_mask[constrained] = False
    free = np.nonzero(free_mask)[0]
    if free.shape[0] < 2:                       # 钉子占满整个网格，无解可解
        return None
    Lff = L[np.ix_(free, free)] + (DAMPING + ANCHOR_WEIGHT) * np.eye(free.shape[0])
    Lfc = L[np.ix_(free, constrained)]
    Minv = np.linalg.inv(Lff)
    return dict(w=w, h=h, nx=nx, ny=ny, v0=v0, e_i=e_i, e_j=e_j, e_w=e_w,
                pin_idx=pin_idx, pin_wt=pin_wt, free=free,
                constrained=constrained, Lfc=Lfc, Minv=Minv,
                anchor=ANCHOR_WEIGHT * v0[free])


def _rotations(S):
    """批量求 2D 旋转：R = argmax tr(R S)。

    tr(R(θ) S) = cosθ(S00+S11) + sinθ(S01-S10)，所以 θ = atan2(S01-S10, S00+S11)。
    比 np.linalg.svd 对 (V,2,2) 逐批分解快得多。
    """
    a = S[:, 0, 0] + S[:, 1, 1]
    b = S[:, 0, 1] - S[:, 1, 0]
    r = np.hypot(a, b)
    r = np.where(r < 1e-12, 1.0, r)
    cs = a / r
    sn = b / r
    R = np.empty_like(S)
    R[:, 0, 0] = cs
    R[:, 0, 1] = -sn
    R[:, 1, 0] = sn
    R[:, 1, 1] = cs
    return R


def _cache_key(w, h, nx, ny, pins):
    # 关键：只认钉子的**原位**。拖动时原位不变、只有目标变，
    # 左端矩阵不动，所以能直接复用分解结果。
    return (w, h, nx, ny) + tuple(
        (round(p[0], 4), round(p[1], 4)) for p in pins)


def solve(w, h, pins, nx=None, ny=None, nodes=ARAP_NODES, iters=MAX_ITERS):
    """解出每个网格顶点的位移。返回 (dx, dy) 两个 (V,) 数组，或 None。

    dx/dy 是「顶点被推到哪」的偏移，与 Field 的语义一致（正向场）。
    """
    if np is None or not pins:
        return None
    pins = [tuple(float(v) for v in p) for p in pins]
    if nx is None or ny is None:
        nx, ny = _grid_extent(w, h, nodes)

    key = _cache_key(w, h, nx, ny, pins)
    st = _CACHE.get(key)
    if st is None:
        st = _prepare(w, h, nx, ny, pins)
        if st is None:
            return None
        _CACHE[key] = st
        if len(_CACHE) > _CACHE_LIMIT:      # 别让 inv 结果无限攒内存
            for old in list(_CACHE)[:-_CACHE_LIMIT]:
                _CACHE.pop(old, None)

    v0 = st["v0"]
    n = v0.shape[0]
    e_i, e_j, e_w = st["e_i"], st["e_j"], st["e_w"]
    pin_idx, pin_wt = st["pin_idx"], st["pin_wt"]
    constrained, free = st["constrained"], st["free"]
    Lfc, Minv = st["Lfc"], st["Minv"]
    anchor = st["anchor"]          # 弱锚定的右端项，固定不变

    # 约束顶点的目标位置：所在单元的 4 个顶点各自平移 (d - s)。
    # 这样双线性插值出来的点正好落在 d 上，钉子严格跟手。
    acc = np.zeros((n, 2), dtype=np.float64)
    cnt = np.zeros(n, dtype=np.float64)
    for k, p in enumerate(pins):
        d = np.array((p[2] - p[0], p[3] - p[1]), dtype=np.float64)
        ix = pin_idx[k]
        acc[ix] += v0[ix] + d
        cnt[ix] += 1.0
    Xc = acc[constrained] / cnt[constrained][:, None]

    # 初值：约束顶点已到位、自由顶点仍在原位。这样第一轮局部步骤就能看到
    # 真实的形变，不会像「先整体平移」那样卡在退化点上。
    X = np.empty((n, 2), dtype=np.float64)
    X[constrained] = Xc
    X[free] = v0[free]

    e_rest = v0[e_i] - v0[e_j]          # 原位边向量，不随迭代变

    for _ in range(max(1, int(iters))):
        e_now = X[e_i] - X[e_j]
        # S_i = Σ_j w (v_i-v_j)(x_i-x_j)^T ；同一条边对 i、j 两端的贡献相同
        outer = e_rest[:, :, None] * e_now[:, None, :]
        S = np.zeros((n, 2, 2), dtype=np.float64)
        np.add.at(S, e_i, e_w[:, None, None] * outer)
        np.add.at(S, e_j, e_w[:, None, None] * outer)
        R = _rotations(S)

        b = np.zeros((n, 2), dtype=np.float64)
        Rm = 0.5 * (R[e_i] + R[e_j])                    # (E,2,2)
        rep = np.einsum('eij,ej->ei', Rm, e_rest)       # (E,2)
        contrib = e_w[:, None] * rep
        np.add.at(b, e_i, contrib)
        np.add.at(b, e_j, -contrib)

        XF = Minv.dot(b[free] - Lfc.dot(Xc) + anchor)
        delta = np.abs(XF - X[free]).max()
        X[free] = XF
        if delta < TOLERANCE:
            break

    return X[:, 0] - v0[:, 0], X[:, 1] - v0[:, 1]
