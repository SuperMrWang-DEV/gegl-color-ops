# -*- coding: utf-8 -*-
"""生成结果的质量评估与修补 / quality scoring and clean-up for AI fills

AI 重绘「看起来假」通常不是画错了，而是三件小事凑在一起：
  1. 一次只出一张，运气不好那张就是废的 —— 没有比较就没有挑选；
  2. 填充区和周围差半个色阶，在平滑的墙面/天空上勾出一圈淡框；
  3. 填充区太干净：照片有颗粒，生成区没有，像贴上去的贴纸。

这里做的正是这三件：`rank()` 给多张候选打分排序，`seam_field()` /
`apply_seam_field()` 只补低频色差（不动生成的细节），`noise_sigma()` /
`grain_to_add()` / `add_grain()` 把颗粒量补到和周围一致。

做法参考 hexsian/openfill 的 quality.py（上游 beckettharriman/openfill），
按我们的接口重写：这里只认「紧排 8 位 buffer」，不碰 GIMP —— 图像读写留在
插件里，纯数学放这儿，回归脚本才能在没有 GIMP 的机器上跑。

**全是纯 Python**：GIMP 自带的解释器没有 numpy，本模块在 768×1024 的上下文
上大约 1~3 s，相对几十秒的采样可以忽略。分析都在缩小图上做（长边 ≤256），
只有最后上色是原尺寸。
"""

import math
import random
from dataclasses import dataclass

INF = 1 << 20

# 带提示词的填充，如果「选区内的颜色」和「周围」几乎一样，说明模型什么都没画
# （或只画了极小一块）。低于这个距离就降权，让「真的画了东西」的那张胜出。
PROMPT_CONTENT = 0.35


@dataclass(frozen=True)
class Buffer:
    """8 位紧排像素。channels 为 3 或 4（第 4 通道是 alpha，打分时不看）。"""

    width: int
    height: int
    data: bytes
    channels: int = 4

    def luminance(self):
        c, d, n = self.channels, self.data, self.width * self.height
        if c < 3:
            return [d[i * c] / 255.0 for i in range(n)]
        return [(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) / 255.0
                for i in range(0, n * c, c)]

    def rgb(self, index):
        o = index * self.channels
        if self.channels < 3:
            v = self.data[o] / 255.0
            return v, v, v
        return (self.data[o] / 255.0, self.data[o + 1] / 255.0,
                self.data[o + 2] / 255.0)


@dataclass(frozen=True)
class Score:
    """各项都是「越小越好」的偏差量。`total` 是加权后的总罚分。"""

    seam: float        # 边缘梯度 / 边缘外侧梯度：>1 说明接缝比周围更「硬」
    lap_ratio: float   # 选区内拉普拉斯方差 / 周围：<1 偏糊，>1 偏碎
    frame: float       # 跨过边缘的颜色台阶（内侧一圈 vs 外侧一圈）
    colour: float      # 选区内 vs 周围环的颜色距离（均值 + 0.5×离散度）
    leak: float        # 选区外被改动量的均值：应该接近 0
    total: float       # 加权罚分，小的胜


def signed_distance(width, height, mask, threshold=128):
    """到选区边缘的棋盘距离：选区内 <= 0（边界上为 0），选区外 > 0。

    两个方向各做一次 chamfer 正反扫，这样「边上」和「边上第 k 圈」都能按
    距离取环带，不必真的去描边。
    """
    n = width * height
    inside = [mask[i] >= threshold for i in range(n)]

    def chamfer(seed):
        d = [0 if s else INF for s in seed]
        for y in range(height):
            row = y * width
            for x in range(width):
                i = row + x
                if d[i] == 0:
                    continue
                best = d[i]
                if x > 0:
                    best = min(best, d[i - 1] + 1)
                if y > 0:
                    best = min(best, d[i - width] + 1)
                    if x > 0:
                        best = min(best, d[i - width - 1] + 1)
                    if x < width - 1:
                        best = min(best, d[i - width + 1] + 1)
                d[i] = best
        for y in range(height - 1, -1, -1):
            row = y * width
            for x in range(width - 1, -1, -1):
                i = row + x
                best = d[i]
                if x < width - 1:
                    best = min(best, d[i + 1] + 1)
                if y < height - 1:
                    best = min(best, d[i + width] + 1)
                    if x < width - 1:
                        best = min(best, d[i + width + 1] + 1)
                    if x > 0:
                        best = min(best, d[i + width - 1] + 1)
                d[i] = best
        return d

    to_inside = chamfer(inside)
    to_outside = chamfer([not s for s in inside])
    return [to_inside[i] if not inside[i] else 1 - to_outside[i] for i in range(n)]


def _grad_lap(lum, width, height):
    grad = [0.0] * (width * height)
    lap = [0.0] * (width * height)
    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            i = row + x
            up, dn, lf, rt = lum[i - width], lum[i + width], lum[i - 1], lum[i + 1]
            grad[i] = math.hypot(rt - lf, dn - up) / 2.0
            lap[i] = up + dn + lf + rt - 4.0 * lum[i]
    return grad, lap


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _var(values):
    if not values:
        return 0.0
    m = _mean(values)
    return sum((v - m) ** 2 for v in values) / len(values)


def _colour_stats(buf, indices):
    if not indices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    chans = list(zip(*(buf.rgb(i) for i in indices)))
    means = tuple(_mean(list(c)) for c in chans)
    spreads = tuple(math.sqrt(_var(list(c))) for c in chans)
    return means, spreads


def score(original, candidate, mask, removal, distance=None):
    """给一张候选打分。original / candidate 是同一块上下文的 8 位 buffer。

    original 是「填之前」的原图（用来量选区外有没有被改动、周围是什么颜色），
    candidate 是生成结果。mask 每像素一字节，选区内 255。
    """
    w, h = candidate.width, candidate.height
    if (original.width, original.height) != (w, h):
        raise ValueError("original and candidate differ in size")
    d = distance if distance is not None else signed_distance(w, h, mask)
    lum = candidate.luminance()
    grad, lap = _grad_lap(lum, w, h)
    interior = [y * w + x for y in range(1, h - 1) for x in range(1, w - 1)]
    edge = [i for i in interior if -1 <= d[i] <= 1]
    beside = [i for i in interior if 3 <= abs(d[i]) <= 8]
    inner = [i for i in interior if d[i] <= -2]
    ring = [i for i in interior if 2 <= d[i] <= 10]
    band_in = [i for i in interior if -4 <= d[i] <= -1]
    band_out = [i for i in interior if 2 <= d[i] <= 5]

    seam = 1.0
    if edge and beside:
        seam = (_mean([grad[i] for i in edge])
                / max(1e-6, _mean([grad[i] for i in beside])))
    lap_ratio = 1.0
    if inner and ring:
        lap_ratio = (_var([lap[i] for i in inner])
                     / max(1e-9, _var([lap[i] for i in ring])))
    m_in, _ = _colour_stats(candidate, band_in)
    m_out, _ = _colour_stats(candidate, band_out)
    frame = math.sqrt(sum((a - b) ** 2 for a, b in zip(m_in, m_out)))
    whole_in, s_in = _colour_stats(candidate, inner)
    m_ring, s_ring = _colour_stats(original, ring)
    colour = (math.sqrt(sum((a - b) ** 2 for a, b in zip(whole_in, m_ring)))
              + 0.5 * math.sqrt(sum((a - b) ** 2 for a, b in zip(s_in, s_ring))))
    outside = [i for i in interior if d[i] >= 2]
    leak = 0.0
    if outside:
        leak = _mean([abs(a - b) for i in outside
                      for a, b in zip(candidate.rgb(i), original.rgb(i))])

    penalty = 2.0 * max(0.0, seam - 1.0)          # 接缝比周围更硬
    penalty += 0.6 * max(0.0, -math.log(max(lap_ratio, 1e-6)))   # 比周围糊
    if removal:
        # 移除物体：选区内比周围更「碎」说明模型自己编了个新东西出来
        penalty += 0.6 * max(0.0, math.log(max(lap_ratio, 1e-6) / 1.5))
        penalty += 3.0 * colour
    else:
        # 带提示词：几乎和周围一样 = 什么都没画
        penalty += 3.0 * max(0.0, PROMPT_CONTENT - colour)
    penalty += 6.0 * frame + 8.0 * leak
    return Score(seam, lap_ratio, frame, colour, leak, penalty)


def rank(original, candidates, mask, removal):
    """候选项下标，最好的在前；分数相同时保持原顺序（稳定）。"""
    if len(candidates) < 2:
        return list(range(len(candidates)))
    d = signed_distance(original.width, original.height, mask)
    totals = [score(original, c, mask, removal, d).total for c in candidates]
    return sorted(range(len(candidates)), key=lambda i: (totals[i], i))


def scores_of(original, candidates, mask, removal):
    """与 rank() 同一套计算，但把每张的 Score 都返回（给日志/回归用）。"""
    if not candidates:
        return []
    d = signed_distance(original.width, original.height, mask)
    return [score(original, c, mask, removal, d) for c in candidates]


# --------------------------------------------------------------- 颗粒 / grain

# 纯高斯噪声 s 时，「像素减四邻均值」这个残差的标准差是 s * sqrt(1.25)；
# 反过来量噪声要除掉这个增益（用中位数绝对偏差，抗纹理）。
_RESIDUAL_GAIN = math.sqrt(1.25)
# 邻域亮度极差不超过这么多级才算「平坦」——只有平坦处量的才是噪声，不是纹理。
FLAT_RANGE = 24


def noise_sigma(width, height, data, channels, mask=None, inside=False, step=2):
    """平坦区的亮度噪声标准差（8 位级）。太少平坦像素时返回 0。"""
    c = channels
    residuals = []
    for y in range(1, height - 1, step):
        for x in range(1, width - 1, step):
            i = y * width + x
            if mask is not None and (mask[i] >= 128) != inside:
                continue

            def lum(j):
                o = j * c
                if c < 3:
                    return float(data[o])
                return 0.299 * data[o] + 0.587 * data[o + 1] + 0.114 * data[o + 2]

            v = lum(i)
            up, dn = lum(i - width), lum(i + width)
            lf, rt = lum(i - 1), lum(i + 1)
            if max(v, up, dn, lf, rt) - min(v, up, dn, lf, rt) > FLAT_RANGE:
                continue
            residuals.append(abs(v - (up + dn + lf + rt) / 4.0))
    if len(residuals) < 64:
        return 0.0
    residuals.sort()
    return 1.4826 * residuals[len(residuals) // 2] / _RESIDUAL_GAIN


def grain_to_add(ring_sigma, inside_sigma, minimum=1.0):
    """把 inside 的噪声补到 ring 的水平需要加多少（平方相加）。

    低于 minimum 级就当看不见，不加——免得把干净照片弄脏。
    """
    add = math.sqrt(max(0.0, ring_sigma * ring_sigma - inside_sigma * inside_sigma))
    return add if add >= minimum else 0.0


def _normal_quantile(p):
    """标准正态分布的分位数（Acklam 有理逼近），用来做查表噪声。"""
    a = (-39.69683028665376, 220.9460984245205, -275.9285104469687,
         138.3577518672690, -30.66479806614716, 2.506628277459239)
    b = (-54.47609879822406, 161.5858368580409, -155.6989798598866,
         66.80131188771972, -13.28068155288572)
    c = (-0.007784894002430293, -0.3223964580411365, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783)
    d = (0.007784695709041462, 0.3224671290700398, 2.445134137142996,
         3.754408661907416)
    low = 0.02425
    if p < low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q
                + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > 1.0 - low:
        return -_normal_quantile(1.0 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q \
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


def add_grain(data, channels, sigma, seed=0):
    """给颜色通道加单色高斯噪声（灰度抖动，alpha 不动）。

    R/G/B 加同一个偏移，所以颗粒没有彩色噪点；sigma <= 0 原样返回。
    """
    if sigma <= 0 or not data:
        return data
    n = len(data) // channels
    # 256 个分位数，按随机字节查表：一次 map 顶掉整行
    offsets = [round(sigma * _normal_quantile((k + 0.5) / 256.0)) for k in range(256)]
    table = bytes(max(0, min(255, v + offsets[k])) for v in range(256) for k in range(256))
    noise = random.Random(seed).randbytes(n)
    out = bytearray(data)
    colours = min(3, channels)
    for ch in range(colours):
        values = data[ch::channels]
        out[ch::channels] = bytes(
            map(table.__getitem__, map(int.__add__, map((256).__mul__, values), noise)))
    return bytes(out)


# ------------------------------------------------------------ 接缝场 / seam

# 量接缝时把上下文缩到长边 256：低频色差不需要原分辨率。
SEAM_SIDE = 256
SEAM_CELL = 8            # 分析图上每 8 像素一个偏移格
SEAM_MAX_OFFSET = 24     # 差得比这多的是内容差异，不是色偏，不动它
SEAM_MAX_SPREAD = 10     # 格内差异散布比这大的算纹理，跳过
SEAM_TABLE_OFFSET = 24   # apply 时单次最多加/减这么多级
SEAM_MIN_OFFSET = 1.5    # 小于这个级数肉眼看不见，白改


@dataclass(frozen=True)
class SeamField:
    """粗网格上的逐通道偏移；`block` 是一个格子在原图上的像素数。"""

    width: int
    height: int
    block: int
    offsets: tuple   # 每格一个 (dr, dg, db)


def _median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def seam_field(width, height, original, layer, mask, channels=4,
               band=24, side=SEAM_SIDE, max_offset=SEAM_MAX_OFFSET,
               max_spread=SEAM_MAX_SPREAD):
    """让 `layer` 在选区边缘「接上」`original` 的低频偏移，不需要修时返回 None。

    original / layer 是同一块上下文的 8 位紧排 buffer；mask 是选区。
    只在选区**外**的环带量差（那里图层本来就该等于原图），再把这个差用
    Shepard 插值摊到整个填充区上。所以生成的细节一点没动，只是整体挪了几个色阶。
    """
    step = max(1, int(math.ceil(max(width, height) / float(side))))
    sw, sh = len(range(0, width, step)), len(range(0, height, step))
    colours = min(3, channels)

    def small(data, ch):
        rows = []
        stride = width * ch
        for y in range(0, height, step):
            row = data[y * stride:(y + 1) * stride]
            rows.append([row[c::ch][::step] for c in range(ch)])
        return rows

    so, sl, sm = small(original, channels), small(layer, channels), small(mask, 1)
    flat_mask = b"".join(r[0] for r in sm)
    dist = signed_distance(sw, sh, flat_mask)
    reach = max(1, int(round(band / float(step))))

    cell = SEAM_CELL
    gw, gh = int(math.ceil(sw / float(cell))), int(math.ceil(sh / float(cell)))
    samples = {}
    for y in range(sh):
        o_row, l_row = so[y], sl[y]
        for x in range(sw):
            d = dist[y * sw + x]
            if not 1 <= d <= reach:
                continue
            key = (y // cell) * gw + x // cell
            per = samples.setdefault(key, [[] for _ in range(colours)])
            for c in range(colours):
                per[c].append(o_row[c][x] - l_row[c][x])

    known = []
    for key, per in samples.items():
        if len(per[0]) < 4:
            continue
        meds = tuple(_median(v) for v in per)
        spread = max(_median([abs(a - m) for a in v]) for v, m in zip(per, meds))
        if spread > max_spread or max(abs(m) for m in meds) > max_offset:
            continue
        known.append((key % gw + 0.5, key // gw + 0.5, meds))
    if not known:
        return None
    if max(max(abs(m) for m in k[2]) for k in known) < SEAM_MIN_OFFSET:
        return None

    # 图层在这些格子里是「可见」的（选区内 + 边缘外 reach 之内）；其余格偏移为 0
    shown = [False] * (gw * gh)
    for y in range(sh):
        for x in range(sw):
            if dist[y * sw + x] <= reach:
                shown[(y // cell) * gw + x // cell] = True
    offsets = []
    for gy in range(gh):
        for gx in range(gw):
            if not shown[gy * gw + gx]:
                offsets.append((0.0,) * colours)
                continue
            acc = [0.0] * colours
            total = 0.0
            exact = None
            for kx, ky, meds in known:
                d2 = (kx - gx - 0.5) ** 2 + (ky - gy - 0.5) ** 2
                if d2 < 1e-6:
                    exact = meds
                    break
                w = 1.0 / d2
                total += w
                for c in range(colours):
                    acc[c] += w * meds[c]
            offsets.append(tuple(exact) if exact else tuple(a / total for a in acc))
    return SeamField(gw, gh, step * cell, tuple(offsets))


def apply_seam_field(data, width, height, channels, field):
    """把接缝场的偏移加回颜色通道（格子之间双线性，alpha 不动）。"""
    colours = min(3, channels)
    block = field.block
    # 先把偏移算到 block/4 的细网格上，行内用查表平移：纯 Python 里这是
    # 「相邻格最多差一级」最省的做法，不会出现块状边界。
    fine = max(1, block // 4)
    fw, fh = int(math.ceil(width / float(fine))), int(math.ceil(height / float(fine)))
    span = 2 * SEAM_TABLE_OFFSET + 1
    table = bytes(max(0, min(255, v + k - SEAM_TABLE_OFFSET))
                  for v in range(256) for k in range(span))

    def at(gx, gy, c):
        gx = min(max(gx - 0.5, 0.0), field.width - 1.0)
        gy = min(max(gy - 0.5, 0.0), field.height - 1.0)
        x0, y0 = int(gx), int(gy)
        x1 = min(x0 + 1, field.width - 1)
        y1 = min(y0 + 1, field.height - 1)
        fx, fy = gx - x0, gy - y0
        o = field.offsets
        top = o[y0 * field.width + x0][c] * (1 - fx) + o[y0 * field.width + x1][c] * fx
        bottom = o[y1 * field.width + x0][c] * (1 - fx) + o[y1 * field.width + x1][c] * fx
        return top * (1 - fy) + bottom * fy

    out = bytearray(data)
    stride = width * channels
    for fy in range(fh):
        gy = (fy * fine + fine / 2.0) / block
        rows = range(fy * fine, min(height, (fy + 1) * fine))
        for c in range(colours):
            cells = [max(0, min(span - 1,
                                int(round(at((fx * fine + fine / 2.0) / block,
                                             gy, c))) + SEAM_TABLE_OFFSET))
                     for fx in range(fw)]
            if all(k == SEAM_TABLE_OFFSET for k in cells):
                continue
            line = b"".join(bytes((k,)) * fine for k in cells)[:width]
            for y in rows:
                start = y * stride + c
                values = data[start:start + stride:channels]
                out[start:start + stride:channels] = bytes(
                    map(table.__getitem__,
                        map(int.__add__, map(span.__mul__, values), line)))
    return bytes(out)
