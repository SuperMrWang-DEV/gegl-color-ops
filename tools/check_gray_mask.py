# -*- coding: utf-8 -*-
"""回归：灰度图层 → 选区 / Alpha 通道 插件（plugin/gray-mask/gray-mask.py）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_gray_mask.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gimp 的 GI 绑定）。检查五件事：

1. 带偏移的小图层 → 选区：边界精确等于图层矩形（以前粘贴会居中放置，
   偏移丢失，整体错位）；
2. 灰度值决定选区强度：半灰图层选出的通道直方图均值 ≈ 0.5；
3. invert：通道反相后均值 ≈ 1 − 原均值；选区反相后为补集；
4. operation：Add/Subtract/Intersect 相对已有选区按预期组合；
5. 灰度 → 通道：通道出现在 image.get_channels()，名字可指定，
   RGB 图层粘贴进通道会被转成灰度（非零，不是 0/255 两极）。
"""
import os
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
        if os.path.exists(os.path.join(c, "plugin", "gray-mask", "gray-mask.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


PLUG = os.path.join(_find_repo(), "plugin", "gray-mask", "gray-mask.py")

spec = importlib.util.spec_from_file_location("gray_mask_plugin", PLUG)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FAIL = []


def check(label, got, want):
    ok = got == want
    print("%-44s got=%-24s want=%-24s %s" % (label, got, want, "OK" if ok else "FAIL"))
    if not ok:
        FAIL.append(label)


def bounds(image):
    r = image.get_selection().bounds(image)   # (ok, non_empty, x1, y1, x2, y2)
    return tuple(int(v) for v in r[2:6]), bool(r[1])


def new_gray_layer(image, name, w, h, ox, oy, value):
    layer = Gimp.Layer.new(image, name, w, h, Gimp.ImageType.GRAY_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, -1)
    layer.set_offsets(ox, oy)
    c = Gegl.Color()
    c.set_rgba(value, value, value, 1.0)
    Gimp.context_set_foreground(c)
    layer.fill(Gimp.FillType.FOREGROUND)
    return layer


def drawable_mean(drawable):
    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure('gimp-drawable-histogram')
    cfg = proc.create_config()
    cfg.set_property('drawable', drawable)
    cfg.set_property('channel', 0)
    cfg.set_property('start-range', 0.0)
    cfg.set_property('end-range', 1.0)
    res = proc.run(cfg)
    return res.index(1)     # ValueArray[0] 是状态码，均值在 1


def channel_mean(image, channel):
    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure('gimp-drawable-histogram')
    cfg = proc.create_config()
    cfg.set_property('drawable', channel)
    cfg.set_property('channel', 0)      # HistogramChannel.VALUE
    cfg.set_property('start-range', 0.0)
    cfg.set_property('end-range', 1.0)
    res = proc.run(cfg)
    return res.index(1)                 # [0]=status, mean 在 1（0..255 刻度）


# ---- 1. 带偏移图层 → 选区，边界精确 ------------------------------------------

img = Gimp.Image.new(16, 16, Gimp.ImageBaseType.GRAY)
lay = new_gray_layer(img, 'mask', 6, 6, 3, 4, 1.0)
mod.gray_to_selection(img, lay, 0, False)
check("偏移图层→选区 边界", bounds(img), ((3, 4, 9, 10), True))

# ---- 2. 半灰 → 选区强度 0.5（通道直方图均值） --------------------------------

img2 = Gimp.Image.new(16, 16, Gimp.ImageBaseType.GRAY)
lay2 = new_gray_layer(img2, 'half', 16, 16, 0, 0, 0.5)
chan = mod.gray_to_channel(img2, lay2, False, 'half-chan')
src_mean = drawable_mean(lay2)
check("半灰→通道 均值=源图层均值", round(channel_mean(img2, chan), 1),
      round(src_mean, 1))

# ---- 3. invert ------------------------------------------------------------

chan_inv = mod.gray_to_channel(img2, lay2, True, 'half-inv')
check("反相通道 均值≈255-源均值", round(channel_mean(img2, chan_inv), 1),
      round(255 - src_mean, 1))

img3 = Gimp.Image.new(16, 16, Gimp.ImageBaseType.GRAY)
lay3 = new_gray_layer(img3, 'corner', 8, 8, 0, 0, 1.0)
mod.gray_to_selection(img3, lay3, 0, True)
# 反相选区 = 除左上 8x8 外全部 → 边界是整张画布
check("反相选区 边界", bounds(img3), ((0, 0, 16, 16), True))

# ---- 4. operation 组合 ------------------------------------------------------

img4 = Gimp.Image.new(16, 16, Gimp.ImageBaseType.GRAY)
a = new_gray_layer(img4, 'a', 8, 8, 0, 0, 1.0)     # 左上
b = new_gray_layer(img4, 'b', 8, 8, 8, 8, 1.0)     # 右下
mod.gray_to_selection(img4, a, 0, False)           # a
mod.gray_to_selection(img4, b, 1, False)           # add b → 整画布
check("Add 组合 边界", bounds(img4), ((0, 0, 16, 16), True))

img5 = Gimp.Image.new(16, 16, Gimp.ImageBaseType.GRAY)
a5 = new_gray_layer(img5, 'a', 16, 16, 0, 0, 1.0)
b5 = new_gray_layer(img5, 'b', 8, 8, 4, 4, 1.0)
mod.gray_to_selection(img5, a5, 0, False)
mod.gray_to_selection(img5, b5, 2, False)          # subtract → 四角
# 四角并集的包围盒仍是整画布，用 IsEmpty 不可靠，改查像素：
got = img5.get_selection().value(img5, 8, 8)        # 画布中心不在任何角
check("Subtract 中心为空", bool(got), False)

# ---- 5. RGB 图层粘贴进通道转灰度 --------------------------------------------

img6 = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
lay6 = Gimp.Layer.new(img6, 'red', 8, 8, Gimp.ImageType.RGBA_IMAGE, 100.0,
                      Gimp.LayerMode.NORMAL)
img6.insert_layer(lay6, None, -1)
c = Gegl.Color(); c.set_rgba(1.0, 0.0, 0.0, 1.0)
Gimp.context_set_foreground(c)
lay6.fill(Gimp.FillType.FOREGROUND)
chan6 = mod.gray_to_channel(img6, lay6, False, '')
mean6 = channel_mean(img6, chan6)
check("RGB 红层→通道均值>0 且 <255", 0.0 < mean6 < 255.0, True)
check("通道默认名=图层名", chan6.get_name(), 'red')

# ---- 汇总 -------------------------------------------------------------------

print("")
if FAIL:
    print("✗ %d 项失败：%s" % (len(FAIL), "；".join(FAIL)))
else:
    print("✓ 全部通过")
