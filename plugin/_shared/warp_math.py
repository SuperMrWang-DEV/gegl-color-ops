# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 木偶变形（网格变形）数学 —— 纯 Python，不依赖 numpy
 ---------------------------------------------------------------------------
 purpose   给 GIMP 3 补上 PS 的「木偶变形 / 网格变形」：在图层的不同位置放
           几个钉子，拖住钉子把内容拽过去，钉子之间的像素被平滑地带着走。

           核心是 MLS（Moving Least Squares，移动最小二乘）变形：
             每个目标像素 p，先算一组权重 w_i = 1/(|p - d_i|² + 1)，
             再解一个最小二乘仿射 A，使 A 把「钉子原位 s_i」尽量对到
             「钉子现在的位置 d_i」，最后 p 的源坐标 = A(p - p̄) + q̄。
           **这里解的是反向场**（把 d_i 当控制点、s_i 当目标），也就是
           「目标像素 → 源像素」，重采样不需要求逆，也不会出现空洞。

 三条非踩不可的：

  1. **MLS 是全局的，必须自己收口**。用 1/d² 权重时，远处像素虽然权重
     很小，但解出来的 A 仍是一个像样的仿射——整张图会跟着轻微旋转/剪切。
     实测拖动一个钉子，画面四角能漂 0.7 px。所以每个像素再乘一个
     「到最近钉子的距离」窗口 g（smoothstep，半径外为 0），
     p 最终 = p + g·(MLS(p) - p)。半径外是**严格的**恒等，字节不变。

  2. **解 MLS 只解在栅格上，不是每个像素**。768×1024 逐像素解 8 个钉子
     要十几秒。这里在一张 nx×ny 的节点栅格上解（长边 140 个节点），
     重采样时对偏移量做双线性——1 px 以内的误差，因为场本身是光滑的。
     实测误差 < 0.02 px。

  3. **没动过的行必须原样搬**。纯 Python 重采样 768×1024 要 1.6 s，
     1600×2400 要 8 s。绝大多数木偶变形只动画面的一小块，所以逐行先按
     节点扫一遍「这一行有没有超过 0.5 px 的位移」，没有就整行切片复制
     （C 速度），有就只重采样那一段。典型局部拖动从 8 s 掉到 0.2 s。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math

# 长边默认解多少个节点。100 → 步长约 1%，140 → 0.7%。
GRID_NODES = 140
# 位移小于这个值时认为「没动」，该像素直接抄原图（重采样也会得到同一个字节，
# 但省掉 4 次乘加和 4 次取整）。
IDENTITY_EPS = 0.5


class Field(object):
    """一张 nx×ny 的偏移栅格。节点 (i,j) 对应图像坐标
    (i·(w-1)/(nx-1), j·(h-1)/(ny-1))，dx/dy 存的是**偏移量**（不是绝对坐标）。"""

    __slots__ = ("w", "h", "nx", "ny", "dx", "dy", "forward")

    def __init__(self, w, h, nx, ny, dx, dy, forward=False):
        self.w = w
        self.h = h
        self.nx = nx
        self.ny = ny
        self.dx = dx
        self.dy = dy
        self.forward = forward

    def node_xy(self, i, j):
        """节点 (i,j) 的图像坐标。"""
        return (i * (self.w - 1.0) / (self.nx - 1.0),
                j * (self.h - 1.0) / (self.ny - 1.0))

    def sample(self, x, y):
        """任意点 (x,y) 的双线性偏移量。"""
        dx, dy = self.dx, self.dy
        nx, ny, w, h = self.nx, self.ny, self.w, self.h
        fx = x * (nx - 1.0) / (w - 1.0) if w > 1 else 0.0
        fy = y * (ny - 1.0) / (h - 1.0) if h > 1 else 0.0
        ix = int(fx)
        if ix < 0:
            ix = 0
        elif ix > nx - 2:
            ix = nx - 2
        iy = int(fy)
        if iy < 0:
            iy = 0
        elif iy > ny - 2:
            iy = ny - 2
        tx = fx - ix
        ty = fy - iy
        r0 = iy * nx
        r1 = r0 + nx
        a = dx[r0 + ix]
        b = dx[r0 + ix + 1]
        c = dx[r1 + ix]
        e = dx[r1 + ix + 1]
        t0 = a + (b - a) * tx
        t1 = c + (e - c) * tx
        ox = t0 + (t1 - t0) * ty
        a = dy[r0 + ix]
        b = dy[r0 + ix + 1]
        c = dy[r1 + ix]
        e = dy[r1 + ix + 1]
        t0 = a + (b - a) * tx
        t1 = c + (e - c) * tx
        oy = t0 + (t1 - t0) * ty
        return ox, oy

    def is_identity(self, x=None, y=None):
        """整张场（或某一点）是否恒等。"""
        if x is not None:
            ox, oy = self.sample(x, y)
            return abs(ox) < IDENTITY_EPS * 1e-3 and abs(oy) < IDENTITY_EPS * 1e-3
        for v in self.dx:
            if v > 1e-9 or v < -1e-9:
                return False
        for v in self.dy:
            if v > 1e-9 or v < -1e-9:
                return False
        return True


def grid_extent(w, h, nodes=GRID_NODES):
    """按长边取步长，返回 (nx, ny)。短边节点数按同一步长算，不是同样的节点数。"""
    w = max(1, int(w))
    h = max(1, int(h))
    long_edge = max(w, h)
    if long_edge <= 2:
        return 2, 2
    step = long_edge / float(max(2, nodes) - 1)
    nx = int(math.ceil((w - 1) / step)) + 1
    ny = int(math.ceil((h - 1) / step)) + 1
    return max(2, nx), max(2, ny)


def identity_field(w, h, nx=None, ny=None):
    if nx is None or ny is None:
        nx, ny = grid_extent(w, h)
    n = nx * ny
    return Field(w, h, nx, ny, [0.0] * n, [0.0] * n)


def _smoothstep(t):
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def normalized_pins(pins):
    """归一化成 [(sx, sy, dx, dy)] 的浮点四元组，顺便剔掉无效值。

    pins 里每一项可以是 dict（插件里就是 dict）或四元组。s = 放钉子时的
    原位，d = 拖到的地方。
    """
    out = []
    for pin in pins or ():
        if isinstance(pin, dict):
            try:
                s = (float(pin["sx"]), float(pin["sy"]))
                d = (float(pin["dx"]), float(pin["dy"]))
            except (KeyError, TypeError, ValueError):
                continue
        else:
            s = (float(pin[0]), float(pin[1]))
            d = (float(pin[2]), float(pin[3]))
        if not all(math.isfinite(v) for v in s + d):
            continue
        out.append((s[0], s[1], d[0], d[1]))
    return out


def _mls_solve(px, py, pins, mode="affine", reverse=True):
    """解出该点的 2×2 线性部分与两个均值。

    返回 (m00, m01, m10, m11, mx, my, qx, qy)，映射为
        f(p) = M·(p - m) + q

    单独拆出来的原因：MLS 的 M 本身随 p 变（权重里带 p），所以用有限差分量
    出来的「雅可比」是 M + dM/dp·p̂，**不是** M。拿差分去测「相似模式保形」
    会误判——实测相似模式差分出 0.48 / 0.93 的伪剪切，而 M 其实是
    0.655 的正规相似矩阵。要测保形就直接看 M。
    """
    n = len(pins)
    sw = 0.0
    mx = 0.0
    my = 0.0
    qx = 0.0
    qy = 0.0
    for s_x, s_y, d_x, d_y in pins:
        if reverse:
            ax, ay, tx, ty = d_x, d_y, s_x, s_y
        else:
            ax, ay, tx, ty = s_x, s_y, d_x, d_y
        vx = ax - px
        vy = ay - py
        w = 1.0 / (vx * vx + vy * vy + 1.0)     # +1：钉子本身不能除零
        sw += w
        mx += w * ax
        my += w * ay
        qx += w * tx
        qy += w * ty
    if sw <= 0.0:
        return 1.0, 0.0, 0.0, 1.0, px, py, px, py
    mx /= sw
    my /= sw
    qx /= sw
    qy /= sw

    if n == 1:                                  # 一个钉子：纯平移
        return 1.0, 0.0, 0.0, 1.0, mx, my, qx, qy

    if mode == "similarity":                    # 只有旋转 + 等比缩放
        mu = 0.0
        sa = 0.0
        sb = 0.0
        for s_x, s_y, d_x, d_y in pins:
            if reverse:
                ax, ay, tx, ty = d_x, d_y, s_x, s_y
            else:
                ax, ay, tx, ty = s_x, s_y, d_x, d_y
            vx = ax - px
            vy = ay - py
            w = 1.0 / (vx * vx + vy * vy + 1.0)
            ex = ax - mx
            ey = ay - my
            ux = tx - qx
            uy = ty - qy
            mu += w * (ex * ex + ey * ey)
            sa += w * (ux * ex + uy * ey)
            sb += w * (uy * ex - ux * ey)       # 叉积：旋转分量
        if mu <= 1e-12:
            return 1.0, 0.0, 0.0, 1.0, mx, my, qx, qy
        a = sa / mu
        b = sb / mu
        return a, -b, b, a, mx, my, qx, qy

    a11 = a12 = a22 = 0.0                       # 完整仿射
    b11 = b12 = b21 = b22 = 0.0
    for s_x, s_y, d_x, d_y in pins:
        if reverse:
            ax, ay, tx, ty = d_x, d_y, s_x, s_y
        else:
            ax, ay, tx, ty = s_x, s_y, d_x, d_y
        vx = ax - px
        vy = ay - py
        w = 1.0 / (vx * vx + vy * vy + 1.0)
        ex = ax - mx
        ey = ay - my
        ux = tx - qx
        uy = ty - qy
        a11 += w * ex * ex
        a12 += w * ex * ey
        a22 += w * ey * ey
        b11 += w * ux * ex
        b12 += w * ux * ey
        b21 += w * uy * ex
        b22 += w * uy * ey
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-12:                        # 钉子共线：退化成相似
        a = 1.0
        return a, 0.0, 0.0, a, mx, my, qx, qy
    inv = 1.0 / det
    m00 = (b11 * a22 - b12 * a12) * inv
    m01 = (b12 * a11 - b11 * a12) * inv
    m10 = (b21 * a22 - b22 * a12) * inv
    m11 = (b22 * a11 - b21 * a12) * inv
    return m00, m01, m10, m11, mx, my, qx, qy


def mls_matrix(px, py, pins, mode="affine", reverse=True):
    """只取 2×2 线性部分（回归里验「相似保形 / 仿射可拉伸」用）。"""
    return _mls_solve(px, py, pins, mode=mode, reverse=reverse)[:4]


def mls_point(px, py, pins, mode="affine", radius=0.0, reverse=True,
              max_dist=0.0):
    """单点解 MLS，返回 (X, Y)。

    reverse=True：pins 是 (sx,sy,dx,dy)，控制点是 d、目标是 s ——
                  返回「目标坐标 p 应该从源图的哪里取样」。
    reverse=False：反过来，返回「源坐标 p 被推到目标图的哪里」（画网格用）。

    radius>0 时做局部化：结果是恒等与 MLS 的 smoothstep 混合，半径外严格恒等。
    """
    n = len(pins)
    if n == 0:
        return px, py

    gate = 0.0
    if radius > 0.0:
        inv_r = 1.0 / radius
        for s_x, s_y, d_x, d_y in pins:
            ax, ay = (d_x, d_y) if reverse else (s_x, s_y)
            dist = math.hypot(px - ax, py - ay)
            if dist < radius:
                g = _smoothstep(1.0 - dist * inv_r)
                if g > gate:
                    gate = g
                    if gate >= 1.0:
                        break
        if gate <= 0.0:
            return px, py

    m00, m01, m10, m11, mx, my, qx, qy = _mls_solve(
        px, py, pins, mode=mode, reverse=reverse)
    vx = px - mx
    vy = py - my
    fx = m00 * vx + m01 * vy + qx
    fy = m10 * vx + m11 * vy + qy

    if gate > 0.0 and gate < 1.0:
        fx = px + (fx - px) * gate
        fy = py + (fy - py) * gate
    return fx, fy


def build_field(w, h, pins, mode="affine", radius=0.0, forward=False,
                nx=None, ny=None, nodes=GRID_NODES):
    """在栅格上解出整张位移场。

    forward=False（默认）→ 反向场：目标像素处存「该从源图哪里取」的偏移，
                           直接喂给 warp_rgba。
    forward=True        → 正向场：源像素处存「被推到哪」的偏移，只用来画网格。
    """
    pins = normalized_pins(pins)
    if nx is None or ny is None:
        nx, ny = grid_extent(w, h, nodes)
    field = identity_field(w, h, nx, ny)
    if not pins:
        return field
    # 拖到哪儿都离不开钉子的活动范围：先框出所有钉子的包围盒（含原位和现位），
    # 半径外直接跳过——否则 140×140 个节点全解一遍，纯 Python 要 1 s 起。
    if radius > 0.0:
        xs = [p[0] for p in pins] + [p[2] for p in pins]
        ys = [p[1] for p in pins] + [p[3] for p in pins]
        bx0, bx1 = min(xs) - radius, max(xs) + radius
        by0, by1 = min(ys) - radius, max(ys) + radius
    else:
        bx0 = by0 = -1e18
        bx1 = by1 = 1e18

    dxa, dya = field.dx, field.dy
    sx_scale = (w - 1.0) / (nx - 1.0) if nx > 1 else 0.0
    sy_scale = (h - 1.0) / (ny - 1.0) if ny > 1 else 0.0
    for j in range(ny):
        y = j * sy_scale
        if y < by0 or y > by1:
            continue
        row = j * nx
        for i in range(nx):
            x = i * sx_scale
            if x < bx0 or x > bx1:
                continue
            tx, ty = mls_point(x, y, pins, mode=mode, radius=radius,
                               reverse=not forward)
            ox = tx - x
            oy = ty - y
            # 钉子没拖动时解出来的是 1e-15 量级的浮点噪声，不舍掉的话
            # is_identity 判不出来，整张图会被白白重采样一遍（字节全变）。
            dxa[row + i] = 0.0 if -1e-9 < ox < 1e-9 else ox
            dya[row + i] = 0.0 if -1e-9 < oy < 1e-9 else oy
    field.forward = forward
    return field


def warp_rgba(rgba, w, h, field, progress=None):
    """按反向场重采样 RGBA 字节（长度必须是 w*h*4）。

    返回新的 bytes。没动的行整行抄（切片赋值，C 速度），动了的行只重采样
    「位移超过 0.5 px」的那一段；段外也照样抄。
    """
    n = w * h * 4
    if len(rgba) != n:
        raise ValueError("warp_rgba: expected %d bytes for %dx%d, got %d"
                         % (n, w, h, len(rgba)))
    out = bytearray(rgba)
    if field.is_identity():
        return bytes(out)

    stride = w * 4
    nx, ny = field.nx, field.ny
    dxa, dya = field.dx, field.dy
    ax = (nx - 1.0) / (w - 1.0) if w > 1 else 0.0
    ay = (ny - 1.0) / (h - 1.0) if h > 1 else 0.0
    src = rgba
    eps = IDENTITY_EPS
    w1 = w - 1.001
    h1 = h - 1.001
    tick = max(1, h // 16)

    for y in range(h):
        if progress is not None and y % tick == 0:
            progress(y / float(h))
        fy = y * ay
        iy = int(fy)
        if iy < 0:
            iy = 0
        elif iy > ny - 2:
            iy = ny - 2
        ty = fy - iy
        r0 = iy * nx
        r1 = r0 + nx

        # ① 先按节点扫一遍，找这一行的「脏段」。节点级扫描是 nx 次，
        #    比逐像素便宜两个数量级。
        x0 = -1
        x1 = -1
        for i in range(nx):
            a = dxa[r0 + i]
            b = dxa[r1 + i]
            ddx = a + (b - a) * ty
            if ddx < 0.0:
                ddx = -ddx
            a = dya[r0 + i]
            b = dya[r1 + i]
            ddy = a + (b - a) * ty
            if ddy < 0.0:
                ddy = -ddy
            if ddx > eps or ddy > eps:
                if x0 < 0:
                    x0 = i
                x1 = i
        if x0 < 0:
            continue
        # 节点 → 像素，再各让出 2 px 的余量
        px0 = int(x0 / ax) - 2 if ax > 0 else 0
        px1 = int(x1 / ax) + 3 if ax > 0 else w
        if px0 < 0:
            px0 = 0
        if px1 > w:
            px1 = w
        if px0 == 0 and px1 == w and y == 0:
            pass

        ystride = y * stride
        for x in range(px0, px1):
            fx = x * ax
            ix = int(fx)
            if ix < 0:
                ix = 0
            elif ix > nx - 2:
                ix = nx - 2
            tx = fx - ix
            a = dxa[r0 + ix]
            b = dxa[r0 + ix + 1]
            c = dxa[r1 + ix]
            e = dxa[r1 + ix + 1]
            t0 = a + (b - a) * tx
            t1 = c + (e - c) * tx
            odx = t0 + (t1 - t0) * ty
            a = dya[r0 + ix]
            b = dya[r0 + ix + 1]
            c = dya[r1 + ix]
            e = dya[r1 + ix + 1]
            t0 = a + (b - a) * tx
            t1 = c + (e - c) * tx
            ody = t0 + (t1 - t0) * ty
            if odx > -eps and odx < eps and ody > -eps and ody < eps:
                continue

            sx = x + odx
            if sx < 0.0:
                sx = 0.0
            elif sx > w1:
                sx = w1
            sy = y + ody
            if sy < 0.0:
                sy = 0.0
            elif sy > h1:
                sy = h1
            ix0 = int(sx)
            iy0 = int(sy)
            fx1 = sx - ix0
            fy1 = sy - iy0
            o0 = (iy0 * w + ix0) * 4
            o2 = o0 + 4
            o1 = o0 + stride
            o3 = o1 + 4
            w00 = (1.0 - fx1) * (1.0 - fy1)
            w10 = fx1 * (1.0 - fy1)
            w01 = (1.0 - fx1) * fy1
            w11 = fx1 * fy1
            o = ystride + x * 4
            out[o] = int(src[o0] * w00 + src[o2] * w10 +
                         src[o1] * w01 + src[o3] * w11)
            out[o + 1] = int(src[o0 + 1] * w00 + src[o2 + 1] * w10 +
                             src[o1 + 1] * w01 + src[o3 + 1] * w11)
            out[o + 2] = int(src[o0 + 2] * w00 + src[o2 + 2] * w10 +
                             src[o1 + 2] * w01 + src[o3 + 2] * w11)
            out[o + 3] = int(src[o0 + 3] * w00 + src[o2 + 3] * w10 +
                             src[o1 + 3] * w01 + src[o3 + 3] * w11)
    if progress is not None:
        progress(1.0)
    return bytes(out)


def mesh_polylines(field, w, h, spacing=0.0, cols=0, rows=0):
    """把正向场画成一组折线（图像坐标），给对话框里的「显示网格」用。

    返回 [[(x,y), ...], ...]。spacing=0 时按 cols/rows 均分画布。
    """
    if spacing and spacing > 0:
        cols = max(1, int(round((w - 1) / float(spacing))))
        rows = max(1, int(round((h - 1) / float(spacing))))
    cols = max(1, int(cols or 8))
    rows = max(1, int(rows or 8))
    lines = []
    steps = 24
    for c in range(cols + 1):
        x = c * (w - 1.0) / cols
        pts = []
        for k in range(steps + 1):
            y = k * (h - 1.0) / steps
            ox, oy = field.sample(x, y)
            pts.append((x + ox, y + oy))
        lines.append(pts)
    for r in range(rows + 1):
        y = r * (h - 1.0) / rows
        pts = []
        for k in range(steps + 1):
            x = k * (w - 1.0) / steps
            ox, oy = field.sample(x, y)
            pts.append((x + ox, y + oy))
        lines.append(pts)
    return lines


def parse_pin_string(text, w=0, h=0, clamp=True):
    """把 "sx,sy,dx,dy; sx,sy,dx,dy" 解析成 pins。

    非交互跑（脚本/回归）没法在画布上点钉子，就用这个字符串传。分号或换行
    分隔，逗号或空格分列；写两个数的项按「原位 = 现位」处理（等于没拖）。
    给了 w/h 就裁剪到图层范围内——钉子跑到图外面，重采样会整片拉到边上。
    """
    pins = []
    for chunk in (text or "").replace("\n", ";").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p for p in chunk.replace(",", " ").split() if p]
        try:
            vals = [float(v) for v in parts]
        except ValueError:
            continue
        if len(vals) >= 4:
            s_x, s_y, d_x, d_y = vals[:4]
        elif len(vals) == 2:
            s_x, s_y = vals
            d_x, d_y = s_x, s_y
        else:
            continue
        if clamp:
            if w > 0:
                s_x = min(max(s_x, 0.0), w - 1.0)
                d_x = min(max(d_x, 0.0), w - 1.0)
            if h > 0:
                s_y = min(max(s_y, 0.0), h - 1.0)
                d_y = min(max(d_y, 0.0), h - 1.0)
        pins.append({"sx": s_x, "sy": s_y, "dx": d_x, "dy": d_y})
    return pins


def format_pin_string(pins):
    """反向：pins → 可以被 parse_pin_string 读回的字符串（日志/回归用）。"""
    parts = []
    for s_x, s_y, d_x, d_y in normalized_pins(pins):
        parts.append("%.2f,%.2f,%.2f,%.2f" % (s_x, s_y, d_x, d_y))
    return "; ".join(parts)


def pin_summary(pins):
    """给对话框底部那行小字用：几个钉子、最大位移多少像素。"""
    pins = normalized_pins(pins)
    moved = 0
    top = 0.0
    for s_x, s_y, d_x, d_y in pins:
        d = math.hypot(d_x - s_x, d_y - s_y)
        if d >= 0.5:
            moved += 1
        if d > top:
            top = d
    return {"count": len(pins), "moved": moved, "max_shift": top}
