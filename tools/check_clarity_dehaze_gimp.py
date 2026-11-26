# -*- coding: utf-8 -*-
"""在真 GIMP 里跑「清晰度 / 去朦胧」算子的回归（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_clarity_dehaze_gimp.py').read())" --quit

验的是接线与语义，不是公式推导：

- 两个都为 0 时逐字节恒等，挂滤镜不烘焙时原图层一个字节不动；
- 清晰度只动中频：纯色图不动，正弦条纹的对比上升/下降，硬边不产生
  大过冲（tanh 压幅在起作用），保护越强过冲越小；
- 中间调权重：同样幅度的条纹，中间调增益大于暗部增益；
- 去朦胧用合成雾图 I = J·t + A·(1−t) 反解，恢复后与 J 的平均差明显小于
  处理前；纯雾图（I ≡ A）不爆；负强度等于加雾；
- 饱和补偿只扩色度；
- 极端参数不产生 NaN、不整幅黑白；
- 性能：1600×2400 的三条路径 + 恒等快路径。
"""

import math
import os
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
REPO = ROOT

OP = "lb:clarity-dehaze"
PLUGIN = os.path.join(REPO, "plugin", "clarity-dehaze", "clarity-dehaze.py")

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


# ---- 造图 ---------------------------------------------------------------

def new_image(data, w, h, name="photo"):
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(img, name, w, h, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    layer.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", data)
    layer.get_buffer().flush()
    return img, layer


def make_flat(w, h, v):
    return new_image(bytes([v, v, v, 255]) * (w * h), w, h)


def make_wave(w, h, period, amp, base=128, dark_base=None):
    """灰底 + 正弦条纹。dark_base 给定时下半幅改用那个底色（测中间调权重）。"""
    buf = bytearray(w * h * 4)
    for y in range(h):
        b = base if (dark_base is None or y < h // 2) else dark_base
        for x in range(w):
            v = b + amp * math.sin(2.0 * math.pi * x / period)
            v = int(max(0, min(255, round(v))))
            o = (y * w + x) * 4
            buf[o] = buf[o + 1] = buf[o + 2] = v
            buf[o + 3] = 255
    return new_image(bytes(buf), w, h)


def make_step(w, h, lo=40, hi=215):
    """竖硬边：左半 lo、右半 hi。边缘两侧的过冲直接量。"""
    buf = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            v = lo if x < w // 2 else hi
            o = (y * w + x) * 4
            buf[o] = buf[o + 1] = buf[o + 2] = v
            buf[o + 3] = 255
    return new_image(bytes(buf), w, h)


def make_hazy(w, h, t=0.5, air=216):
    """合成雾：I = J·t + A·(1−t)。J 是棋盘 + 彩色块，反解回来该接近 J。"""
    buf = bytearray(w * h * 4)
    sky = int(round(h * 0.2))
    for y in range(h):
        for x in range(w):
            if y < sky:
                # 天空：三通道都等于大气光。暗通道先验要求远景本身就是 A，
                # 否则最亮的 min(R,G,B) 落在彩色块上，A 会被估低。
                jr = jg = jb = air
            else:
                checker = 40 if ((x // 24) + (y // 24)) % 2 else 200
                jr = checker
                jg = 120 if x < w // 2 else 60
                jb = 100 if (y - sky) < (h - sky) // 2 else 170
            o = (y * w + x) * 4
            for i, j in enumerate((jr, jg, jb)):
                buf[o + i] = int(round(j * t + air * (1.0 - t)))
            buf[o + 3] = 255
    return new_image(bytes(buf), w, h)


def make_color(w, h):
    """左橙右蓝，两块都饱和；测饱和补偿看色度。"""
    buf = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            o = (y * w + x) * 4
            if x < w // 2:
                buf[o], buf[o + 1], buf[o + 2] = 200, 110, 60
            else:
                buf[o], buf[o + 1], buf[o + 2] = 60, 110, 200
            buf[o + 3] = 255
    return new_image(bytes(buf), w, h)


# ---- 读写 / 挂滤镜 ------------------------------------------------------

def pixels(layer):
    w, h = layer.get_width(), layer.get_height()
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                 "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    return w, h, bytes(bytearray(raw))


def attach(layer, **params):
    filt = Gimp.DrawableFilter.new(layer, OP, "cd test")
    cfg = filt.get_config()
    for k, v in params.items():
        cfg.set_property(k.replace("_", "-"), v)
    filt.update()
    layer.append_filter(filt)
    return filt


def run(layer, **params):
    """把 layer 的像素搬进一张全新图像，挂滤镜、烘焙、读回、删图。

    每个用例一张独立的图：在同一张图的同一图层上反复 merge_filter，GIMP
    3.2 会在退出时 double unref 已烘焙的滤镜对象（g_object_unref 断言 +
    gimp_object_get_memsize 连环报错，最后 abort）。lens 的回归是每节新建
    图像才没踩到，这里照做。
    """
    w0, h0, data = pixels(layer)
    img = Gimp.Image.new(w0, h0, Gimp.ImageBaseType.RGB)
    lay = Gimp.Layer.new(img, "run", w0, h0, Gimp.ImageType.RGBA_IMAGE,
                         100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, w0, h0), "R'G'B'A u8", data)
    lay.get_buffer().flush()
    filt = attach(lay, **params)
    lay.merge_filter(filt)
    w, h, out = pixels(lay)
    img.delete()
    return w, h, out


def luma(rgba, w, h, x, y):
    o = (y * w + x) * 4
    return 0.2126 * rgba[o] + 0.7152 * rgba[o + 1] + 0.0722 * rgba[o + 2]


def pstd(rgba, w, h, x0, x1, y0, y1):
    vals = [luma(rgba, w, h, x, y)
            for y in range(y0, y1)
            for x in range(x0, x1)]
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def pmean(rgba, w, h, x0, x1, y0, y1):
    vals = [luma(rgba, w, h, x, y)
            for y in range(y0, y1)
            for x in range(x0, x1)]
    return sum(vals) / len(vals)


def chroma(rgba, w, h, x0, x1, y0, y1):
    vals = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            o = (y * w + x) * 4
            vals.append(max(rgba[o:o + 3]) - min(rgba[o:o + 3]))
    return sum(vals) / len(vals)


def main():
    print("=" * 62)
    print("清晰度 / 去朦胧 · Clarity & Dehaze · GIMP 内回归")
    print("=" * 62)

    # ---- 注册 -------------------------------------------------------------
    section("算子注册与滤镜挂载")
    img0, lay0 = make_flat(64, 64, 128)
    ok, err = True, ""
    filt = None
    try:
        filt = attach(lay0, clarity=30.0)
    except Exception as exc:
        ok, err = False, str(exc)
    check("lb:clarity-dehaze 能挂成图层滤镜", ok, err)
    if ok:
        cfg = filt.get_config()
        check("参数 clarity 回读 = 30",
              abs(cfg.get_property("clarity") - 30.0) < 1e-9,
              repr(cfg.get_property("clarity")))
        check("参数 dehaze-keep 回读 = 0.95",
              abs(cfg.get_property("dehaze-keep") - 0.95) < 1e-9)
    img0.delete()

    # ---- 恒等 -------------------------------------------------------------
    section("恒等：两个强度都是 0")
    img1, lay1 = make_wave(160, 160, 24, 40)
    _, _, src = pixels(lay1)
    h1, w1, out1 = run(lay1, clarity=0.0, dehaze=0.0)
    check("输出尺寸不变", (w1, h1) == (160, 160), "%dx%d" % (w1, h1))
    check("输出与输入逐字节相同", out1 == src,
          "diff=%d" % sum(1 for a, b in zip(out1, src) if a != b))
    _, _, keep = pixels(lay1)
    check("烘焙副本后原图层未被改", keep == src)
    img1.delete()

    # ---- 清晰度 -----------------------------------------------------------
    section("清晰度：只推中频")
    img2, lay2 = make_wave(200, 200, 26, 34)
    _, _, base = pixels(lay2)
    s0 = pstd(base, 200, 200, 40, 160, 40, 160)
    _, _, up = run(lay2, clarity=80.0, clarity_radius=40)
    s_up = pstd(up, 200, 200, 40, 160, 40, 160)
    _, _, dn = run(lay2, clarity=-80.0, clarity_radius=40)
    s_dn = pstd(dn, 200, 200, 40, 160, 40, 160)
    check("clarity=+80 条纹对比上升", s_up > s0 * 1.3,
          "%.1f → %.1f" % (s0, s_up))
    check("clarity=−80 条纹对比下降", s_dn < s0 * 0.85,
          "%.1f → %.1f" % (s0, s_dn))
    img2.delete()

    img3, lay3 = make_flat(120, 120, 128)
    _, _, flat_out = run(lay3, clarity=100.0, clarity_radius=20)
    diff = max(abs(a - b) for a, b in zip(flat_out, pixels(lay3)[2]))
    check("纯色图不被清晰度改动（d=0）", diff <= 1, "max diff %d" % diff)
    img3.delete()

    section("清晰度：硬边缘不过冲")
    img4, lay4 = make_step(200, 200)
    _, _, st0 = pixels(lay4)
    edge_x = 100
    lo0 = luma(st0, 200, 200, edge_x - 20, 100)
    hi0 = luma(st0, 200, 200, edge_x + 20, 100)
    _, _, p035 = run(lay4, clarity=100.0, clarity_radius=30,
                     clarity_protect=0.35)
    _, _, p100 = run(lay4, clarity=100.0, clarity_radius=30,
                     clarity_protect=1.0)

    def over(rgba, x0, ref, step):
        return max(abs(luma(rgba, 200, 200, x0 + step * k, 100) - ref) / ref
                   for k in range(0, 3))

    o_lo = over(p035, edge_x - 1, lo0, -1)
    o_hi = over(p035, edge_x, hi0, +1)
    o_lo_1 = over(p100, edge_x - 1, lo0, -1)
    # 增益是乘性的，亮部的绝对过冲天然更大，所以判据用**相对**偏离
    check("保护 0.35 时暗侧相对过冲 < 0.35", o_lo < 0.35,
          "%.2f" % o_lo)
    check("保护 0.35 时亮侧相对过冲 < 0.35", o_hi < 0.35,
          "%.2f" % o_hi)
    check("保护 1.0 比 0.35 过冲更小", o_lo_1 < o_lo * 0.5,
          "%.3f vs %.3f" % (o_lo_1, o_lo))
    img4.delete()

    section("清晰度：中间调权重大于暗部")
    img5, lay5 = make_wave(200, 200, 26, 30, base=128, dark_base=30)
    _, _, b5 = pixels(lay5)
    mid0 = pstd(b5, 200, 200, 40, 160, 20, 80)
    dark0 = pstd(b5, 200, 200, 40, 160, 120, 180)
    _, _, o5 = run(lay5, clarity=100.0, clarity_radius=24)
    mid1 = pstd(o5, 200, 200, 40, 160, 20, 80)
    dark1 = pstd(o5, 200, 200, 40, 160, 120, 180)
    g_mid, g_dark = mid1 / max(mid0, 1e-6), dark1 / max(dark0, 1e-6)
    check("中间调增益大于暗部增益", g_mid > g_dark,
          "%.2fx vs %.2fx" % (g_mid, g_dark))
    img5.delete()

    # ---- 去朦胧 -----------------------------------------------------------
    section("去朦胧：合成雾图反解")
    img6, lay6 = make_hazy(180, 180, t=0.5, air=216)
    _, _, hazy = pixels(lay6)

    sky6 = int(round(180 * 0.2))

    def expect_j(x, y):
        if y < sky6:
            return (216, 216, 216)
        checker = 40 if ((x // 24) + (y // 24)) % 2 else 200
        return (checker,
                120 if x < 90 else 60,
                100 if (y - sky6) < (180 - sky6) // 2 else 170)

    _, _, rec = run(lay6, dehaze=100.0, dehaze_radius=15,
                    dehaze_keep=0.95)
    e_hazy = sum(abs(pixels(lay6)[2][(y * 180 + x) * 4 + c] - expect_j(x, y)[c])
                 for y in range(0, 180, 6) for x in range(0, 180, 6)
                 for c in range(3))
    e_rec = sum(abs(rec[(y * 180 + x) * 4 + c] - expect_j(x, y)[c])
                for y in range(0, 180, 6) for x in range(0, 180, 6)
                for c in range(3))
    n = 3 * len(range(0, 180, 6)) ** 2
    check("恢复后比原雾图更接近真实 J", e_rec < e_hazy * 0.5,
          "MAE %.1f → %.1f" % (e_hazy / n, e_rec / n))
    check("恢复后整体不再是一片灰（对比明显回升）",
          pstd(rec, 180, 180, 10, 170, 10, 170) >
          pstd(hazy, 180, 180, 10, 170, 10, 170) * 1.5,
          "%.1f → %.1f" % (pstd(hazy, 180, 180, 10, 170, 10, 170),
                           pstd(rec, 180, 180, 10, 170, 10, 170)))
    img6.delete()

    section("去朦胧：纯雾与反方向")
    img7, lay7 = make_flat(120, 120, 200)
    _, _, fog = run(lay7, dehaze=100.0, dehaze_radius=10,
                    dehaze_keep=0.95)
    check("纯雾图（I≡A）不爆，仍是原地亮度",
          abs(pmean(fog, 120, 120, 0, 120, 0, 120) - 200) < 3,
          "%.1f" % pmean(fog, 120, 120, 0, 120, 0, 120))
    img7.delete()

    img8, lay8 = make_hazy(140, 140, t=0.6, air=200)
    _, _, hz = pixels(lay8)
    _, _, more = run(lay8, dehaze=-80.0, dehaze_radius=12)
    check("dehaze=−80 等于加雾：对比下降",
          pstd(more, 140, 140, 10, 130, 10, 130) <
          pstd(hz, 140, 140, 10, 130, 10, 130) * 0.85,
          "%.1f → %.1f" % (pstd(hz, 140, 140, 10, 130, 10, 130),
                           pstd(more, 140, 140, 10, 130, 10, 130)))
    check("加雾后整体向大气光靠（更亮）",
          pmean(more, 140, 140, 0, 140, 0, 140) >
          pmean(hz, 140, 140, 0, 140, 0, 140),
          "%.1f → %.1f" % (pmean(hz, 140, 140, 0, 140, 0, 140),
                           pmean(more, 140, 140, 0, 140, 0, 140)))
    img8.delete()

    section("去朦胧：饱和补偿只扩色度")
    img9, lay9 = make_color(120, 120)
    _, _, c0 = pixels(lay9)
    _, _, c1 = run(lay9, dehaze=30.0, dehaze_radius=10,
                   dehaze_saturation=60.0)
    ch0 = chroma(c0, 120, 120, 10, 50, 40, 80)
    ch1 = chroma(c1, 120, 120, 10, 50, 40, 80)
    check("sat=+60 时色度上升", ch1 > ch0 * 1.1,
          "%.1f → %.1f" % (ch0, ch1))
    img9.delete()

    # ---- 极端参数 ---------------------------------------------------------
    section("极端参数")
    img10, lay10 = make_hazy(120, 120, t=0.45, air=210)
    _, _, ex = run(lay10, clarity=100.0, clarity_radius=4,
                   clarity_protect=0.0, dehaze=100.0, dehaze_radius=4,
                   dehaze_keep=1.0, dehaze_saturation=100.0)
    m = pmean(ex, 120, 120, 0, 120, 0, 120)
    check("极端参数下没有 NaN/负数", all(0 <= v <= 255 for v in ex))
    check("极端参数下不是整幅全黑/全白", 5 < m < 250, "均值 %.1f" % m)
    img10.delete()

    # ---- 性能 -------------------------------------------------------------
    section("性能 1600×2400")
    W, H = 1600, 2400
    big = bytes([126, 96, 72, 255]) * (W * H)
    img11, lay11 = new_image(big, W, H)
    t0 = time.time()
    run(lay11, clarity=0.0, dehaze=0.0)
    t_id = time.time() - t0
    t0 = time.time()
    run(lay11, clarity=40.0, clarity_radius=40)
    t_c = time.time() - t0
    t0 = time.time()
    run(lay11, dehaze=40.0, dehaze_radius=15)
    t_d = time.time() - t0
    t0 = time.time()
    run(lay11, clarity=40.0, clarity_radius=40, dehaze=40.0)
    t_b = time.time() - t0
    print("    恒等 %.2f s   清晰度 %.2f s   去朦胧 %.2f s   两者 %.2f s"
          % (t_id, t_c, t_d, t_b))
    check("恒等快路径 < 0.8 s（含图层复制）", t_id < 0.8, "%.2f s" % t_id)
    check("清晰度 < 4 s", t_c < 4.0, "%.2f s" % t_c)
    check("去朦胧 < 4 s", t_d < 4.0, "%.2f s" % t_d)
    img11.delete()

    # ---- 插件源码 ---------------------------------------------------------
    section("插件源码")
    if os.path.exists(PLUGIN):
        src = open(PLUGIN, encoding="utf-8").read()
        check("插件里引用了 lb:clarity-dehaze", OP in src)
        check("插件有 build_dialog(", "build_dialog(" in src)
        check("插件有 show_dialog(", "show_dialog(" in src)
        check("输出三档（filter / replace / new）",
              all(t in src for t in ("filter", "replace", "new")))
        check("清晰度与去朦胧两组参数都在",
              all(t in src for t in ("clarity", "dehaze")))
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
