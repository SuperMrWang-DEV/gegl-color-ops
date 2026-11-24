#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 曲线数学（Python 侧）/ curve maths, Python side
 ---------------------------------------------------------------------------
 purpose   曲线对话框要画出「和算子实际算出来一模一样的曲线」，所以这里按
           common/curve.h 逐个函数复刻一遍：同样的 Fritsch–Carlson 切线
           限制、同样的 LUT 长度、同样的端点补齐规则。
           The dialog has to draw exactly the curve the operator computes, so
           every rule from common/curve.h is mirrored here: the same
           Fritsch–Carlson tangent limiting, the same LUT length, the same
           rule for filling in the ends.

           两边是同算法的两份实现，不是一份实现的两个包装。tools/check_curves.py
           里有一组对拍：把同一串控制点喂给 C 算子（gegl 跑一遍）和这里的
           lut()，逐点比，差超过 1 码就算回归失败。改任何一侧都必须同时改另一侧。
           These are two implementations of one algorithm, not two wrappers
           around one. check_curves.py cross-checks them point by point.

 尺度      全部归一化到 0…1。物理量与归一化之间的换算由调用方负责（算子里
           是 L 0…100 / C 0…132 / h 0…360；babl 的 HSVA 与 CMYKA 本身就是
           0…1）。
           Everything is normalised to 0…1; the operator maps physical ranges.
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ============================================================================"""

MAX_POINTS = 32
LUT_N = 1024

# 分量定义：名字 → (是否环形, 默认曲线)
# 环形的默认是「水平中线」（0.5 = 不偏），普通分量默认是对角线
SPACES = {
    'lab':  {'op': 'lb:lab-curves',  'title': 'LAB Curves',
             'parts': [('L', False), ('a', False), ('b', False)]},
    'lch':  {'op': 'lb:lch-curves',  'title': 'LCh Curves',
             'parts': [('L', False), ('C', False), ('h', True)]},
    'hsv':  {'op': 'lb:hsv-curves',  'title': 'HSV Curves',
             'parts': [('H', True), ('S', False), ('V', False)]},
    'cmyk': {'op': 'lb:cmyk-curves', 'title': 'CMYK Curves',
             'parts': [('C', False), ('M', False), ('Y', False), ('K', False)]},
}


def default_points(ring):
    """环形分量的恒等是一条 y=0.5 的水平线；普通分量是对角线。"""
    if ring:
        return [(0.0, 0.5), (1.0, 0.5)]
    return [(0.0, 0.0), (1.0, 1.0)]


def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _hermite(x, x0, x1, y0, y1, m0, m1):
    h = x1 - x0
    if h <= 0:
        return y1
    t = (x - x0) / h
    t2 = t * t
    t3 = t2 * t
    return ((2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * h * m0 +
            (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * h * m1)


def build(points):
    """控制点 → LUT。points 会自动排序、去重（同 x 留后一个）、补端点。

    返回 (lut, identity)。identity 的含义和 C 侧一致：普通分量表示 y==x，
    环形分量表示全程 0.5（零偏移）。
    """
    pts = [(float(x), _clamp01(float(y))) for x, y in points if x is not None]
    pts.sort(key=lambda p: p[0])

    # 同 x 只留最后一个：x 重复会让段长为 0，切线与 LUT 都没定义
    dedup = []
    for x, y in pts:
        if dedup and abs(x - dedup[-1][0]) < 1e-9:
            dedup[-1] = (x, y)
        else:
            dedup.append((x, y))
    pts = dedup[:MAX_POINTS]

    if len(pts) < 2:
        pts = default_points(False)
        return [i / (LUT_N - 1) for i in range(LUT_N)], True

    # 端点补齐：首点不在 0 就补 (0,0)，末点不在 1 就补 (1,1)
    if pts[0][0] > 1e-9 and len(pts) < MAX_POINTS:
        pts.insert(0, (0.0, 0.0))
    if pts[-1][0] < 1.0 - 1e-9 and len(pts) < MAX_POINTS:
        pts.append((1.0, 1.0))

    # 对角线 → 恒等快路径
    if all(abs(y - x) < 1e-9 for x, y in pts):
        return [i / (LUT_N - 1) for i in range(LUT_N)], True

    n = len(pts)
    d = []
    for i in range(n - 1):
        h = pts[i + 1][0] - pts[i][0]
        d.append((pts[i + 1][1] - pts[i][1]) / h if h > 1e-12 else 0.0)

    m = [0.0] * n
    m[0] = d[0]
    m[n - 1] = d[n - 2]
    for i in range(1, n - 1):
        m[i] = 0.5 * (d[i - 1] + d[i])

    # Fritsch–Carlson 限制：切线对夹进半径 3·|割线| 的圆
    for i in range(n - 1):
        if abs(d[i]) < 1e-12:
            m[i] = m[i + 1] = 0.0
            continue
        a = m[i] / d[i]
        b = m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9.0:
            t = 3.0 / (s ** 0.5)
            m[i] = t * a * d[i]
            m[i + 1] = t * b * d[i]

    lut = []
    seg = 0
    for i in range(LUT_N):
        v = i / (LUT_N - 1)
        while seg < n - 2 and v > pts[seg + 1][0]:
            seg += 1
        lut.append(_clamp01(_hermite(v, pts[seg][0], pts[seg + 1][0],
                                     pts[seg][1], pts[seg + 1][1],
                                     m[seg], m[seg + 1])))

    lut[0] = _clamp01(pts[0][1])
    lut[-1] = _clamp01(pts[-1][1])
    return lut, False


def sample(lut, v):
    """按 LUT 线性插值，v 归一到 0…1。"""
    v = _clamp01(v)
    t = v * (LUT_N - 1)
    i = int(t)
    if i >= LUT_N - 1:
        return lut[LUT_N - 1]
    f = t - i
    return lut[i] * (1.0 - f) + lut[i + 1] * f


def sample_offset(lut, v):
    """环形分量的偏移采样：偏移量夹 ±0.5 后按模 1 折回。"""
    d = sample(lut, v) - 0.5
    d = -0.5 if d < -0.5 else (0.5 if d > 0.5 else d)
    v += d
    if v < 0.0:
        v += 1.0
    elif v >= 1.0:
        v -= 1.0
    return v


def format_points(points):
    """控制点列表 → 算子认的串："0,0 0.25,0.22 1,1"。"""
    return " ".join("%.5f,%.5f" % (x, y) for x, y in points)


def parse_points(text):
    """算子认的串 → 控制点列表。坏 token 跳过，与 C 侧一致。"""
    out = []
    for tok in (text or "").replace("\t", " ").split():
        if "," not in tok:
            continue
        a, b = tok.split(",", 1)
        try:
            x, y = float(a), float(b)
        except ValueError:
            continue
        out.append((_clamp01(x), _clamp01(y)))
    out.sort(key=lambda p: p[0])
    return out


def format_set(curves):
    """{分量名: [点]} → 整串："L ...|a ...|b ..."。"""
    return "|".join("%s %s" % (name, format_points(pts))
                    for name, pts in curves.items() if pts)


def parse_set(space, text):
    """整串 → {分量名: [点]}，缺的分量给默认曲线。"""
    parts = [n for n, _ring in SPACES[space]['parts']]
    rings = dict(SPACES[space]['parts'])
    got = {}
    order = []
    for i, seg in enumerate((text or "").split("|")):
        seg = seg.strip()
        if not seg:
            continue
        head, _, body = seg.partition(" ")
        if "," in head:                    # 没有名字，整段都是点
            name, body = (parts[i] if i < len(parts) else parts[0]), seg
        elif head in parts:
            name = head
        else:
            name = parts[i] if i < len(parts) else parts[0]
        got[name] = parse_points(body)
        order.append(name)

    out = {}
    for name in parts:
        out[name] = got.get(name) or default_points(rings[name])
    return out
