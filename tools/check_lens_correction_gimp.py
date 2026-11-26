# -*- coding: utf-8 -*-
"""在真 GIMP 里跑「镜头校正」算子的回归（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_lens_correction_gimp.py').read())" --quit

纯数学那套（check_lens_correction.py）验的是公式；这里验的是**接线**：
算子能不能被 GIMP 挂成图层滤镜、参数回读对不对、恒等参数下是不是逐字节
没动、畸变的方向、自动缩放是不是真的兜住四角、暗角是不是只在半径外圈
起作用、色差是不是只挪红蓝、越界策略有没有生效、挂上滤镜之后原像素有没有
被偷偷改掉。

测试图是「R = B = 255·r」的径向渐变（r 以半对角线归一化，四角恰为 1），
所以读回来的红通道就是这个像素取到的源半径——畸变和色差都能直接量出来。
G 恒为 40，当「没被碰过」的哨兵。
"""

import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
REPO = ROOT

OP = "lb:lens-correction"
PLUGIN = os.path.join(REPO, "plugin", "lens-correction", "lens-correction.py")

PASS = 0
FAIL = []
SECTION = ""


def section(name):
    global SECTION
    SECTION = name
    print("\n" + name)


def check(label, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  %-52s %s" % (label, detail))
    else:
        FAIL.append("%s / %s（%s）" % (SECTION, label, detail))
        print("  FAIL %-47s %s" % (label, detail))


def make_radial(w=240, h=240):
    """R = B = 255·r，G = 40：读红通道即读半径。"""
    import math
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(img, "photo", w, h, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    cx, cy = w * 0.5, h * 0.5
    hd = 0.5 * math.sqrt(w * w + h * h)
    data = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            r = min(1.0, math.hypot(dx, dy) / hd)
            v = int(round(255.0 * r))
            o = (y * w + x) * 4
            data[o] = v
            data[o + 1] = 40
            data[o + 2] = v
            data[o + 3] = 255
    layer.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8",
                           bytes(data))
    layer.get_buffer().flush()
    return img, layer


def pixels(layer):
    w, h = layer.get_width(), layer.get_height()
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                 "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    return w, h, bytes(bytearray(raw))


def px(rgba, w, x, y):
    o = (y * w + x) * 4
    return tuple(rgba[o:o + 4])


DEFAULTS = {
    "k1": 0.0, "k2": 0.0, "auto-zoom": True, "zoom": 1.0,
    "vignette": 0.0, "vignette-midpoint": 0.55, "vignette-feather": 0.45,
    "ca-red": 0.0, "ca-blue": 0.0, "abyss": "clamp", "resampling": "nohalo",
}


def attach(layer, **params):
    """把算子挂成图层滤镜（不烘焙），返回滤镜句柄。"""
    filt = Gimp.DrawableFilter.new(layer, OP, "lens test")
    cfg = filt.get_config()
    for k, v in params.items():
        cfg.set_property(k.replace("_", "-"), v)
    filt.update()
    layer.append_filter(filt)
    return filt


def render(img, layer, **params):
    """新建图层副本 → 挂滤镜 → 烘焙 → 读像素（不动原图层）。"""
    filt = attach(layer, **params)
    try:
        layer.merge_filter(filt)
    except Exception:
        pass
    return pixels(layer)[2]


def fresh(**params):
    img, layer = make_radial()
    return img, layer, render(img, layer, **params)


def main():
    print("=" * 62)
    print("镜头校正 / Lens Correction · GIMP 内回归")
    print("=" * 62)

    # ---- 算子可用 ---------------------------------------------------------
    section("算子注册与滤镜挂载")
    img0, lay0 = make_radial()
    ok_attach = True
    err = ""
    try:
        f = attach(lay0, k1=0.1)
    except Exception as exc:            # 模块没装 / 名字写错
        ok_attach = False
        err = str(exc)
    check("lb:lens-correction 能挂成图层滤镜", ok_attach, err)
    if ok_attach:
        check("参数 k1 回读 = 0.1",
              abs(f.get_config().get_property("k1") - 0.1) < 1e-9,
              repr(f.get_config().get_property("k1")))
        check("参数 auto-zoom 回读为 True",
              bool(f.get_config().get_property("auto-zoom")) is True)
    img0.delete()

    # ---- 恒等 -------------------------------------------------------------
    section("恒等参数（k1=k2=0, 暗角 0, 色差 0）")
    img1, lay1 = make_radial()
    before = pixels(lay1)[2]
    after = render(img1, lay1, k1=0.0, k2=0.0)
    diff = sum(1 for a, b in zip(before, after) if a != b)
    check("逐字节等于原图", diff == 0, "%d 个字节不同" % diff)

    # 挂滤镜但不烘焙：原图层像素不许动
    section("非破坏：挂上滤镜，原像素不动")
    img2, lay2 = make_radial()
    keep = pixels(lay2)[2]
    filt2 = attach(lay2, k1=0.3, vignette=-50.0)
    still = pixels(lay2)[2]
    check("append_filter 之后原像素逐字节未改", keep == still)
    check("滤镜在栈上（可回读）",
          any(f.get_operation_name() == OP for f in lay2.get_filters()))
    img2.delete()

    # ---- 畸变方向 ---------------------------------------------------------
    section("畸变：k1 > 0 从更外面取样（画面收缩）")
    img3, lay3, out3 = fresh(k1=0.2, k2=0.0, auto_zoom=False,
                             resampling="bilinear")
    w3, h3, _ = pixels(lay3)
    # (205,120)：沿水平方向 r ≈ 0.504，期望源半径 0.504·(1+0.2·0.504²) ≈ 0.530
    got_r = px(out3, w3, 205, 120)[0]
    check("r≈0.5 处红通道升到 ~135（源半径 0.53）", abs(got_r - 135) <= 4,
          "got %d, want 135±4" % got_r)
    check("绿通道未被碰（仍是 40）", px(out3, w3, 205, 120)[1] == 40,
          str(px(out3, w3, 205, 120)))
    centre = px(out3, w3, 120, 120)
    check("中心不动", abs(centre[0] - 0) <= 1, str(centre))

    section("畸变：k1 < 0 从更里面取样（画面放大）")
    img4, lay4, out4 = fresh(k1=-0.2, k2=0.0, auto_zoom=False,
                             resampling="bilinear")
    w4 = pixels(lay4)[0]
    got_r2 = px(out4, w4, 205, 120)[0]
    check("同一位置红通道降到 ~123", abs(got_r2 - 123) <= 4,
          "got %d" % got_r2)

    # ---- 自动缩放 ---------------------------------------------------------
    section("自动缩放：角落不许露空")
    img5, lay5, out5 = fresh(k1=0.25, auto_zoom=True, abyss="transparent")
    w5, h5, _ = pixels(lay5)
    corners = [px(out5, w5, 1, 1), px(out5, w5, w5 - 2, 1),
               px(out5, w5, 1, h5 - 2), px(out5, w5, w5 - 2, h5 - 2)]
    check("四角 alpha 全是 255（没有透明缺口）",
          all(c[3] == 255 for c in corners), str(corners))

    img6, lay6, out6 = fresh(k1=0.25, auto_zoom=False, abyss="transparent")
    c6 = px(out6, w5, 1, 1)
    check("关掉自动缩放 + transparent：角落真的漏了（alpha 0）",
          c6[3] == 0, str(c6))

    img7, lay7, out7 = fresh(k1=0.25, auto_zoom=False, abyss="clamp")
    c7 = px(out7, w5, 1, 1)
    check("关掉自动缩放 + clamp：角落拉边而不是透明", c7[3] == 255, str(c7))

    # ---- 暗角 -------------------------------------------------------------
    section("暗角：只压外圈，中心不动")
    img8, lay8, out8 = fresh(vignette=-60.0, vignette_midpoint=0.4,
                             vignette_feather=0.4)
    w8, h8, _ = pixels(lay8)
    g_centre = px(out8, w8, 120, 120)[1]
    g_mid = px(out8, w8, 205, 120)[1]       # r ≈ 0.5
    g_corner = px(out8, w8, 1, 1)[1]        # r ≈ 1
    check("中心绿通道不变（仍是 40）", g_centre == 40, str(g_centre))
    check("r≈0.5 处轻微压暗（36–40）", 34 <= g_mid <= 40, str(g_mid))
    check("角落压到 4 成（≈16）", abs(g_corner - 16) <= 2, str(g_corner))

    img9, lay9, out9 = fresh(vignette=+60.0, vignette_midpoint=0.4,
                             vignette_feather=0.4)
    g_c9 = px(out9, w8, 1, 1)[1]
    check("正值提亮角落（≈64）", abs(g_c9 - 64) <= 3, str(g_c9))

    # ---- 色差 -------------------------------------------------------------
    section("横向色差：只挪红蓝，绿不动")
    img10, lay10, out10 = fresh(ca_red=20.0, ca_blue=-20.0,
                                auto_zoom=False, resampling="bilinear")
    w10, h10, _ = pixels(lay10)
    p = px(out10, w10, 20, 120)       # r ≈ 0.59
    base = px(before, 240, 20, 120)   # 原图同一点
    # 测试图 R=B=255·r：越靠外越亮。红 +20 向外取 → 更亮；蓝 -20 向内 → 更暗。
    check("红通道被往外推（变亮）", p[0] > base[0] + 4,
          "%d → %d" % (base[0], p[0]))
    check("蓝通道被往内拉（变暗）", p[2] < base[2] - 4,
          "%d → %d" % (base[2], p[2]))
    check("绿通道一动不动", p[1] == 40, str(p))

    # ---- 数值稳定 ---------------------------------------------------------
    section("极端参数不炸")
    img11, lay11, out11 = fresh(k1=0.5, k2=0.5, vignette=-100.0,
                                ca_red=20.0, ca_blue=-20.0)
    check("k1 与 k2 同时 0.5 也能出图", len(out11) == 240 * 240 * 4)
    img12, lay12, out12 = fresh(k1=0.0, k2=0.0, zoom=0.2)
    check("zoom 0.2 只缩不放（角落之外全是拉边）",
          len(out12) == 240 * 240 * 4)

    # ---- 性能 -------------------------------------------------------------
    section("性能（240×240，nohalo）")
    img13, lay13 = make_radial()
    t0 = time.time()
    render(img13, lay13, k1=0.1, vignette=-20.0, ca_red=1.0, ca_blue=-1.0)
    dt = time.time() - t0
    check("一次 240×240 全参数重采样 < 0.6 s", dt < 0.6, "%.3f s" % dt)

    # ---- 插件源码 ---------------------------------------------------------
    section("插件源码")
    if os.path.exists(PLUGIN):
        src = open(PLUGIN, encoding="utf-8").read()
        check("插件里引用了 lb:lens-correction", OP in src)
        check("插件有 build_dialog(", "build_dialog(" in src)
        check("插件有 show_dialog(", "show_dialog(" in src)
        check("输出三档（filter / replace / new）",
              all(t in src for t in ("filter", "replace", "new")))
        check("三个页签都在", all(("畸变" in src, "暗角" in src, "色差" in src)))
    else:
        check("插件文件存在", False, PLUGIN)

    for im in list(Gimp.get_images()):
        im.delete()

    print("\n" + "=" * 62)
    print("PASS %d   FAIL %d" % (PASS, len(FAIL)))
    for f in FAIL:
        print("  " + f)
    print("=" * 62)


main()
