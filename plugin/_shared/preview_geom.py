#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预览该开多大。

两个变形插件原来把预览写死成 480 / 520 长边。写死是有原因的：预览每拖一下
都要重算一帧，走 numpy 时 480×360 就要 84～97 ms，再大就拖不动了。代价是
对话框一开只有一小块，网格节点挤在一起，把手圆点指甲盖那么大——「预览太小」
说的就是这个。

自从预览改走 C（算子 .dll 里的 mw_render_rgba_u8，同尺寸 9 ms）这个前提就没了，
预览完全可以按屏幕给的余量开。所以尺寸改成算出来的：

    sw, sh = workarea()                    # 主屏可用区，扣掉任务栏
    box = (sw - PANEL_W, sh - PANEL_H)     # 扣掉右边参数栏、标题、按钮条
    fit_box(w, h, *box)                    # 等比塞进去，不放大

纯 Python 兜底（.dll 没装上、别的机器）时仍收回到 FALLBACK_EDGE，不然一帧
几百毫秒，比小更难受。

这个模块不碰 GIMP，只算数：拿不到 Gdk 时按 1920×1040 估。
"""

DEFAULT_WORKAREA = (1920, 1040)

# 对话框里除预览以外占掉的地方：右边参数栏 250 + 盒子间距/边框/窗口边 ≈ 330；
# 上下标题栏、按钮条、左边那行提示 ≈ 220。刻意留宽一点——算到「刚好塞满」
# 就会被窗口管理器顶出去，右下角的按钮就点不着了。
PANEL_W = 330
PANEL_H = 220

# 纯 Python 兜底时的预览长边（就是原来的 480 / 520 那档）
FALLBACK_EDGE = 520

# 再快也别超过这个像素数。ctypes 那条路每帧要把整块像素拷一份、再造一次
# GdkPixbuf，85 万像素大约 40～50 ms 一帧（480×360 是 7～9 ms），拖起来还
# 跟得上手；再多就开始发黏。想让预览更大就抬这个数，代价是拖动手感。
MAX_PIXELS = 850 * 1000

_cache = {}


def workarea():
    """主屏可用区（逻辑像素，已扣任务栏）。拿不到就退回 1920×1040。"""
    if "wa" in _cache:
        return _cache["wa"]
    wa = DEFAULT_WORKAREA
    try:
        import gi
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk
        disp = Gdk.Display.get_default()
        mon = None
        if disp is not None:
            mon = disp.get_primary_monitor() or disp.get_monitor(0)
        if mon is not None:
            a = mon.get_workarea()
            if a.width > 320 and a.height > 240:
                wa = (int(a.width), int(a.height))
    except Exception:
        pass
    _cache["wa"] = wa
    return wa


def fit_box(w, h, box_w, box_h):
    """等比缩进框里，**不放大**（小图放大会糊，而且没有信息量）。"""
    w, h = int(w), int(h)
    if w <= 0 or h <= 0:
        return max(1, w), max(1, h)
    s = min(1.0, float(box_w) / w, float(box_h) / h)
    if s >= 1.0:
        return w, h
    return max(1, int(round(w * s))), max(1, int(round(h * s)))


def preview_size(w, h, native=True, edge_cap=None):
    """图层 w×h → 预览该用多少像素。

    native  预览能走 C 那条快路时 True（放开尺寸），否则退回小尺寸。
    edge_cap 额外上限（长边），给确实慢的插件留的余地。
    """
    sw, sh = workarea()
    box_w = max(320, sw - PANEL_W)
    box_h = max(240, sh - PANEL_H)
    if not native:
        box_w = min(box_w, FALLBACK_EDGE)
        box_h = min(box_h, FALLBACK_EDGE)
    if edge_cap:
        box_w = min(box_w, int(edge_cap))
        box_h = min(box_h, int(edge_cap))
    tw, th = fit_box(w, h, box_w, box_h)
    px = tw * th
    if px > MAX_PIXELS:
        s = (float(MAX_PIXELS) / px) ** 0.5
        tw, th = max(1, int(tw * s)), max(1, int(th * s))
    return tw, th


def reset_cache():
    """测试用：换掉 workarea 之后让下次重算。"""
    _cache.clear()
