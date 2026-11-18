# -*- coding: utf-8 -*-
"""回归：图层 → 分通道 插件（plugin/split-channels/split-channels.py）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_split_channels.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gimp 的 GI 绑定）。检查九件事：

1. RGB 图层拆出 R / G / B / Alpha 四条，名字 = 「图层名 + 后缀」；
2. 每条通道的值与源通道逐项一致（不是互相错位一格）；
3. 默认把源图层隐藏；
4. include_alpha=False 时只出三条；
5. 不带 alpha 的图层不出 Alpha 通道；
6. 灰度图只出 Gray（RGB 三路本来就相同），带透明才加 Alpha；
7. 偏移的小图层：通道是画布大小，图层外区域为 0、矩形内为源值；
8. 当前有选区时通道依然完整（选区被挂起）；
9. prefix 生效，重名通道自动加序号。
"""
import os
import array
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl


def _find_repo():
    cands = []
    try:
        cands.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except NameError:
        pass
    cwd = os.getcwd()
    cands += [cwd, os.path.join(cwd, "SuperMrWang"),
              os.path.join(cwd, "..", "SuperMrWang")]
    for c in cands:
        if os.path.exists(os.path.join(c, "plugin", "split-channels",
                                       "split-channels.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


PLUG = os.path.join(_find_repo(), "plugin", "split-channels", "split-channels.py")

spec = importlib.util.spec_from_file_location("split_channels_plugin", PLUG)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FAIL = []


def check(label, got, want):
    ok = got == want
    print("%-46s got=%-22s want=%-22s %s"
          % (label, got, want, "OK" if ok else "FAIL"))
    if not ok:
        FAIL.append(label)


def near(label, got, want, tol=1.5):
    ok = abs(float(got) - float(want)) <= tol
    print("%-46s got=%-22s want=%-22s %s"
          % (label, round(float(got), 2), want, "OK" if ok else "FAIL"))
    if not ok:
        FAIL.append(label)


def new_layer(image, name, w, h, ox=0, oy=0, rgba=None, image_type=None):
    it = image_type or Gimp.ImageType.RGBA_IMAGE
    layer = Gimp.Layer.new(image, name, w, h, it, 100.0, Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, -1)
    if ox or oy:
        layer.set_offsets(ox, oy)
    if rgba is not None:
        c = Gegl.Color()
        c.set_rgba(*rgba)
        Gimp.context_set_foreground(c)
        layer.fill(Gimp.FillType.FOREGROUND)
    return layer


def chan_of(image, name):
    for c in image.get_channels():
        if c.get_name() == name:
            return c
    return None


def drawable_mean(drawable, channel=0):
    proc = Gimp.get_pdb().lookup_procedure('gimp-drawable-histogram')
    cfg = proc.create_config()
    cfg.set_property('drawable', drawable)
    cfg.set_property('channel', channel)     # 0=VALUE 1=RED 2=GREEN 3=BLUE 4=ALPHA
    cfg.set_property('start-range', 0.0)
    cfg.set_property('end-range', 1.0)
    return proc.run(cfg).index(1)          # [0]=status, 均值在 1（0..255）


def chan_pixel(ch, x, y):
    """通道单像素（0..1）/ one pixel of a channel"""
    raw = ch.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                              "Y' float", Gegl.AbyssPolicy.NONE)
    data = array.array('f')
    data.frombytes(bytes(bytearray(raw)))
    return data[0] if len(data) else float('nan')


# ---- 1+2+3. RGB 四通道、值正确、源层隐藏 ------------------------------------

img = Gimp.Image.new(24, 18, Gimp.ImageBaseType.RGB)
lay = new_layer(img, 'photo', 24, 18, rgba=(1.0, 0.5, 0.0, 1.0))
created = mod.split_channels(img, lay)

check("RGB 拆出通道数", len(created), 4)
check("通道名 R", chan_of(img, 'photo R') is not None, True)
check("通道名 G", chan_of(img, 'photo G') is not None, True)
check("通道名 B", chan_of(img, 'photo B') is not None, True)
check("通道名 Alpha", chan_of(img, 'photo Alpha') is not None, True)

# 通道是 24×18 的画布大小
ch_r = chan_of(img, 'photo R')
check("通道尺寸 = 画布", (ch_r.get_width(), ch_r.get_height()), (24, 18))

# R/G/B 分别对应源图层的 R/G/B —— 索引错位一位就会全错，所以拿源图层
# 同通道的直方图均值做基准，而不是写死数值（Gegl.Color 是线性值，填充到
# sRGB 图像后要过 gamma，写死的期望值会和实际显示对不上）。
near("R 通道均值 = 源层 R", drawable_mean(chan_of(img, 'photo R')), drawable_mean(lay, 1))
near("G 通道均值 = 源层 G", drawable_mean(chan_of(img, 'photo G')), drawable_mean(lay, 2))
near("B 通道均值 = 源层 B", drawable_mean(chan_of(img, 'photo B')), drawable_mean(lay, 3))
near("Alpha 通道均值 = 源层 Alpha", drawable_mean(chan_of(img, 'photo Alpha')), drawable_mean(lay, 4))

# 再确认三路本来就互不相同，上面的比较才有区分度
check("三个源通道均值互不相同",
      len({round(drawable_mean(lay, i), 1) for i in (1, 2, 3)}), 3)

check("源图层被隐藏", lay.get_visible(), False)
check("新通道默认不叠到画布", ch_r.get_visible(), False)

# ---- 4. include_alpha=False 只出三条 ----------------------------------------

img2 = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
lay2 = new_layer(img2, 'three', 8, 8, rgba=(0.2, 0.4, 0.6, 1.0))
created2 = mod.split_channels(img2, lay2, include_alpha=False)
check("关掉 Alpha 后通道数", len(created2), 3)
check("关掉 Alpha 后无 Alpha 通道", chan_of(img2, 'three Alpha'), None)

# ---- 5. 不带 alpha 的图层不出 Alpha -----------------------------------------

img3 = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
lay3 = new_layer(img3, 'flat', 8, 8, rgba=(0.0, 1.0, 0.0, 1.0),
                 image_type=Gimp.ImageType.RGB_IMAGE)
mod._pdb('gimp-layer-flatten', layer=lay3)      # GIMP 3 新图层默认带 alpha
check("无 alpha 图层 has_alpha", lay3.has_alpha(), False)
created3 = mod.split_channels(img3, lay3)
check("无 alpha 图层通道数", len(created3), 3)

# ---- 6. 灰度图只出 Gray（+Alpha） -------------------------------------------

img4 = Gimp.Image.new(8, 8, Gimp.ImageBaseType.GRAY)
lay4 = new_layer(img4, 'grey', 8, 8, rgba=(0.25, 0.25, 0.25, 1.0),
                 image_type=Gimp.ImageType.GRAY_IMAGE)
created4 = mod.split_channels(img4, lay4)
check("灰度图通道数（无 alpha）", len(created4), 1)
check("灰度图通道名", created4[0].get_name(), 'grey Gray')
near("灰度通道均值 = 源层", drawable_mean(created4[0]), drawable_mean(lay4))

img5 = Gimp.Image.new(8, 8, Gimp.ImageBaseType.GRAY)
lay5 = new_layer(img5, 'greyA', 8, 8, rgba=(0.25, 0.25, 0.25, 0.5),
                 image_type=Gimp.ImageType.GRAYA_IMAGE)
created5 = mod.split_channels(img5, lay5)
check("灰度+alpha 通道数", len(created5), 2)
check("灰度+alpha 通道名", [c.get_name() for c in created5],
      ['greyA Gray', 'greyA Alpha'])

# ---- 7. 偏移小图层：铺满画布、外部为 0 --------------------------------------

img6 = Gimp.Image.new(16, 16, Gimp.ImageBaseType.RGB)
lay6 = new_layer(img6, 'small', 6, 6, ox=3, oy=4, rgba=(1.0, 1.0, 1.0, 1.0))
mod.split_channels(img6, lay6)
ch6 = chan_of(img6, 'small R')
check("偏移图层通道尺寸 = 画布",
      (ch6.get_width(), ch6.get_height()), (16, 16))
near("图层矩形内 (3,4)", chan_pixel(ch6, 3, 4), 1.0, 0.01)
near("图层矩形内 (8,9)", chan_pixel(ch6, 8, 9), 1.0, 0.01)
near("图层矩形外 (0,0)", chan_pixel(ch6, 0, 0), 0.0, 0.01)
near("图层矩形外 (9,4)", chan_pixel(ch6, 9, 4), 0.0, 0.01)

# ---- 8. 有选区时通道依然完整 ------------------------------------------------

img7 = Gimp.Image.new(16, 16, Gimp.ImageBaseType.RGB)
lay7 = new_layer(img7, 'sel', 16, 16, rgba=(1.0, 1.0, 1.0, 1.0))
mod._pdb('gimp-image-select-rectangle', image=img7,
         operation=Gimp.ChannelOps.REPLACE, x=0, y=0, width=4, height=4)
mod.split_channels(img7, lay7)
near("有选区时通道仍全白（选区被挂起）",
     drawable_mean(chan_of(img7, 'sel R')), 255)
check("选区在拆分后被还原", bool(img7.get_selection().bounds(img7)[1]), True)

# ---- 9. prefix 与重名序号 ---------------------------------------------------

img8 = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
lay8 = new_layer(img8, 'orig', 8, 8, rgba=(0.0, 0.0, 1.0, 1.0))
mod.split_channels(img8, lay8, prefix='卷1')
check("prefix 生效", chan_of(img8, '卷1 B') is not None, True)

lay9 = new_layer(img8, 'again', 8, 8, rgba=(0.0, 0.0, 1.0, 1.0))
mod.split_channels(img8, lay9, prefix='卷1')
check("重名自动加序号", chan_of(img8, '卷1 B 2') is not None, True)

# ---- 汇总 -------------------------------------------------------------------

print("")
if FAIL:
    print("✗ %d 项失败：%s" % (len(FAIL), "；".join(FAIL)))
else:
    print("✓ 全部通过")
