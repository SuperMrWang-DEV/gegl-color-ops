#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 抠图用的纯数学 —— 插件与回归脚本共用
 ---------------------------------------------------------------------------
 干什么   两件不需要 GIMP 的事，单独拎出来好测：
             1. **边缘种子点**：本地抠图从四条边往里泛洪，种子放哪儿决定了
                「背景能不能被选中」——四个角最容易落在主体的阴影里，所以
                要避开；每条边要撒够点，纯色背景一次就中，渐变背景靠多点补；
             2. **AI 蒙版的后处理**：RMBG 回来的是 alpha（主体不透明度），
                低于阈值的残影要压成 0（否则背景会留一层灰雾），其余保留
                软边——抠头发全靠这一层半透明。
           再加上背景图 cover 缩放、蒙版统计这些零碎。

 为什么单独一个模块   插件里那半要真 GIMP，CI 上跑不了；这几条是纯算术，
           有 bug 时（比如种子全落在角上、cover 算反）在这里就能红灯。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""


def edge_seeds(width, height, per_edge=5, inset=2):
    """沿四条边均匀撒种子点（画布坐标）。

    避开四角的理由：商品的影子、人的头发常常压在角上，从角上起泛洪会直接
    把一块主体当背景吃掉。inset 默认 2px 已经躲开最外圈的抗锯齿像素——那是
    半透明的，颜色和背景不完全一样，容易泛洪失败。
    """
    w, h = int(width), int(height)
    n = max(1, int(per_edge))
    pad = max(1, min(int(inset), max(1, min(w, h) // 4)))
    seeds = []
    # 水平方向（顶边、底边）
    span = max(1, w - 2 * pad)
    for i in range(n):
        x = pad + int((i + 0.5) * span / n)
        x = min(max(x, pad), w - 1 - pad)
        seeds.append((x, pad))
        seeds.append((x, h - 1 - pad))
    # 垂直方向（左边、右边），跳过已经撒过的角
    span = max(1, h - 2 * pad)
    for i in range(n):
        y = pad + int((i + 0.5) * span / n)
        y = min(max(y, pad), h - 1 - pad)
        seeds.append((pad, y))
        seeds.append((w - 1 - pad, y))
    # 去重（小图时不同 i 可能落到同一个像素）
    out, seen = [], set()
    for p in seeds:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def offset_seeds(seeds, dx, dy, width, height):
    """把画布坐标的种子挪进某个 drawable 的局部坐标，并夹在图层范围内。

    图层常比画布小、还带偏移：直接拿画布坐标去调 select-contiguous-color
    会点在图层外面，那种点选出来是空的（GIMP 不报错，只是什么都不选），
    于是「背景选区为空」的报错显得莫名其妙。
    """
    out = []
    for x, y in seeds:
        lx = int(round(x - dx))
        ly = int(round(y - dy))
        if 0 <= lx < int(width) and 0 <= ly < int(height):
            out.append((lx, ly))
    if not out and int(width) > 0 and int(height) > 0:
        # 一个都没落进去（图层跑到画布外面）：退回图层自己的四条边
        out = edge_seeds(width, height)
    return out


def alpha_to_mask(alpha, floor=8):
    """RMBG 的 alpha → 蒙版字节串（255=主体）。

    floor 是「残影闸」：RMBG 对背景常常给 1~15 的 alpha，而不是干净的 0。
    直接拿去当蒙版的话，透明背景导出后在深色底上会看到一层灰雾；压到 0 就
    干净了。阈值压低到 8 是为了不伤头发——发丝的 alpha 一般在 40 以上。
    """
    floor = max(0, min(254, int(floor)))
    if floor <= 0:
        return bytes(alpha)
    table = bytes(0 if v < floor else v for v in range(256))
    return bytes(alpha).translate(table)


def mask_stats(mask):
    """(前景占比 0..1, 最小 alpha, 最大 alpha)。回归和提示文案都用它。"""
    if not mask:
        return 0.0, 0, 0
    total = len(mask)
    lit = 0
    lo, hi = 255, 0
    for v in mask:
        if v > 127:
            lit += 1
        if v < lo:
            lo = v
        if v > hi:
            hi = v
    return lit / float(total), lo, hi


def coverage(samples, threshold=127):
    """一组选区采样值里「被选中」的比例。用来判断泛洪到底选没选到背景。"""
    if not samples:
        return 0.0
    hit = sum(1 for v in samples if v > threshold)
    return hit / float(len(samples))


def fit_cover(src_w, src_h, dst_w, dst_h):
    """背景图按 cover 缩放：返回 (新宽, 新高, 偏移 x, 偏移 y)。

    取宽高比里较大的那个缩放系数，等比放大到盖满画布，多出来的居中裁掉。
    和 CSS 的 background-size: cover 一致——用户选一张背景图时想的是「铺满」，
    不是「留两条黑边」。
    """
    src_w, src_h = max(1, int(src_w)), max(1, int(src_h))
    dst_w, dst_h = max(1, int(dst_w)), max(1, int(dst_h))
    s = max(dst_w / float(src_w), dst_h / float(src_h))
    nw = max(dst_w, int(round(src_w * s)))
    nh = max(dst_h, int(round(src_h * s)))
    return nw, nh, (dst_w - nw) // 2, (dst_h - nh) // 2


def normalize_background(kind, have_color=True, have_image=True):
    """把「输出背景」收成三选一：transparent / color / image。

    参数是字符串（PDB 的 choice 传进来就是字符串），这里统一小写并兜底：
    选了 color 但颜色是空、或选了 image 却没有文件，就退回 transparent，
    而不是抛异常——抠图本身已经做完了，不该因为背景参数让整件事失败。
    """
    kind = (kind or "").strip().lower()
    if kind in ("color", "colour", "solid", "white"):
        return "color" if have_color else "transparent"
    if kind in ("image", "picture", "file"):
        return "image" if have_image else "transparent"
    return "transparent"


# PDB 里 choice 的取值顺序（下拉框显示的就是这个顺序）
BACKGROUND_CHOICES = ("transparent", "color", "image")
