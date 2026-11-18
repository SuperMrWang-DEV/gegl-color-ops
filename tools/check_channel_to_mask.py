# -*- coding: utf-8 -*-
"""回归：通道 → 图层蒙版 插件（plugin/channel-to-mask/channel-to-mask.py）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_channel_to_mask.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gimp 的 GI 绑定）。检查八件事：

1. 图层没有蒙版时按通道新建，黑白两半逐像素对上；
2. 中间灰走原生漂移（128 → 187.8），与原生两条链路的落点一致；
3. 已有蒙版时先丢旧再新建，结果与原生新建一致；
4. 反相把黑白对调；
5. 偏移的小图层：蒙版跟着图层尺寸走，取的是画布上同位置的值；
6. 原本有像素选区时会被通道内容替换，与原生两步操作一致；
7. 按「通道名」指定通道，而不是只认当前选中；
8. 一次处理多个选中图层。
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
        if os.path.exists(os.path.join(c, "plugin", "channel-to-mask",
                                       "channel-to-mask.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


PLUG = os.path.join(_find_repo(), "plugin", "channel-to-mask",
                    "channel-to-mask.py")

spec = importlib.util.spec_from_file_location("channel_to_mask_plugin", PLUG)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FAIL = []


def check(label, got, want):
    ok = got == want
    print("%-46s got=%-22s want=%-22s %s"
          % (label, got, want, "OK" if ok else "FAIL"))
    if not ok:
        FAIL.append(label)


def near(label, got, want, tol=1.0):
    ok = abs(float(got) - float(want)) <= tol
    print("%-46s got=%-22s want=%-22s %s"
          % (label, round(float(got), 2), want, "OK" if ok else "FAIL"))
    if not ok:
        FAIL.append(label)


def new_image(w=16, h=16):
    return Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)


def new_layer(image, name, w, h, ox=0, oy=0, rgba=(128, 128, 128, 255)):
    layer = Gimp.Layer.new(image, name, w, h, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, -1)
    if ox or oy:
        layer.set_offsets(ox, oy)
    fill(layer, w, h, rgba)
    return layer


def fill(drawable, w, h, rgba):
    """走 shadow buffer 写精确 8bit 值（Gegl.Color 是线性值，会偏）"""
    shadow = drawable.get_shadow_buffer()
    shadow.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8",
               bytes(rgba) * (w * h))
    shadow.flush()
    drawable.merge_shadow(True)


def new_channel(image, name, w, h, values):
    """values = 长度 w*h 的 0..255 字节序列"""
    c = Gegl.Color()
    c.set_rgba(0.5, 0.5, 1.0, 1.0)
    ch = Gimp.Channel.new(image, name, w, h, 100.0, c)
    image.insert_channel(ch, None, -1)
    # 直接在 buffer 上写：同一图里已经做过蒙版操作时，shadow 写法只会
    # 落到右半 tile，左半读回旧值（Gegl tile 复用的坑）。
    ch.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "Y' u8", bytes(values))
    ch.update(0, 0, w, h)
    return ch

def half(w, h, left=0, right=255):
    return [left if x < w // 2 else right for y in range(h) for x in range(w)]


def mask_px(mask, x, y):
    raw = mask.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                                "Y' float", Gegl.AbyssPolicy.NONE)
    data = array.array('f')
    data.frombytes(bytes(bytearray(raw)))
    return round(data[0] * 255, 1) if len(data) else float('nan')


def selection_none(image):
    proc = Gimp.get_pdb().lookup_procedure('gimp-selection-none')
    cfg = proc.create_config()
    cfg.set_property('image', image)
    proc.run(cfg)


# ---- 1+2. 新建蒙版、值正确、中间灰不变 --------------------------------------

img = new_image()
layer = new_layer(img, "base", 16, 16)
ch = new_channel(img, "src", 16, 16, half(16, 16))
img.set_selected_channels([ch])

mask = mod.channel_to_mask(img, layer, ch)
check("1 蒙版已挂上", layer.get_mask() is not None, True)
near("1 左半（通道 0 → 遮住）", mask_px(mask, 2, 8), 0)
near("1 右半（通道 255 → 露出）", mask_px(mask, 13, 8), 255)

img2 = new_image()
layer2 = new_layer(img2, "base", 16, 16)
ch2 = new_channel(img2, "grey", 16, 16, [128] * 256)
mask2 = mod.channel_to_mask(img2, layer2, ch2)
near("2 中间灰跟随原生：128 → 187.8", mask_px(mask2, 4, 4), 187.8, tol=0.3)

# ---- 3. 已有蒙版：覆盖内容、对象不换 ---------------------------------------

before = layer.get_mask()
ch3 = new_channel(img, "flat", 16, 16, [200] * 256)
mod.channel_to_mask(img, layer, ch3)
check("3 蒙版已重建（与原生新建同源）",
      layer.get_mask().get_id() != before.get_id(), True)
near("3 内容刷新为 200 的漂移值 229.1", mask_px(layer.get_mask(), 2, 8), 229.1,
     tol=0.5)

# ---- 4. 反相 ---------------------------------------------------------------

img4 = new_image()
layer4 = new_layer(img4, "base", 16, 16)
ch4 = new_channel(img4, "src", 16, 16, half(16, 16))
mask4 = mod.channel_to_mask(img4, layer4, ch4, invert=True)
near("4 反相后左半 = 255", mask_px(mask4, 2, 8), 255)
near("4 反相后右半 = 0", mask_px(mask4, 13, 8), 0)

# ---- 5. 偏移的小图层 -------------------------------------------------------

img5 = new_image()
small = new_layer(img5, "small", 8, 8, ox=4, oy=4)
ch5 = new_channel(img5, "src", 16, 16, half(16, 16))
mask5 = mod.channel_to_mask(img5, small, ch5)
check("5 蒙版尺寸跟随图层", (mask5.get_width(), mask5.get_height()), (8, 8))
near("5 蒙版左缘 = 画布 x=4 的通道值 0", mask_px(mask5, 0, 0), 0)
near("5 蒙版右缘 = 画布 x=11 的通道值 255", mask_px(mask5, 7, 0), 255)

# ---- 6. 有选区也不被裁 -----------------------------------------------------

img6 = new_image()
layer6 = new_layer(img6, "base", 16, 16)
ch6 = new_channel(img6, "src", 16, 16, half(16, 16))
img6.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 16, 8)   # 只选中上半
mod.channel_to_mask(img6, layer6, ch6)
near("6 选区外（下半）同样写满", mask_px(layer6.get_mask(), 2, 12), 0)
near("6 选区外（下半右）同样写满", mask_px(layer6.get_mask(), 13, 12), 255)
near("6 选区被通道内容替换（原生一致）", mask_px(img6.get_selection(), 2, 2), 0)
near("6 选区另一半", mask_px(img6.get_selection(), 13, 2), 255)
selection_none(img6)

# ---- 7+8. 按名字指定通道、多个图层一次处理 ---------------------------------

img7 = new_image()
a = new_layer(img7, "a", 16, 16)
b = new_layer(img7, "b", 16, 16)
new_channel(img7, "noise", 16, 16, [77] * 256)
by_name = new_channel(img7, "picked", 16, 16, half(16, 16))
found = mod.pick_channel(img7, "picked")
check("7 按名字找到通道", found.get_id(), by_name.get_id())

for lay in (a, b):
    mod.channel_to_mask(img7, lay, found)
near("8 图层 a 挂上了", mask_px(a.get_mask(), 13, 8), 255)
near("8 图层 b 挂上了", mask_px(b.get_mask(), 13, 8), 255)

# ---- 9. 取源兜底：从通道面板右键进来时，通道以 drawable 形式传进来 ----------

img9 = new_image()
layer9 = new_layer(img9, "l", 16, 16)
ctx = new_channel(img9, "ctx", 16, 16, half(16, 16))
img9.set_selected_layers([layer9])       # 新建通道会自动成为选中项，这里还原
check("9 前置：通道未选中", bool(img9.get_selected_channels()), False)
check("9 上下文通道被取到", mod.pick_channel(img9, "", [ctx]).get_id(),
      ctx.get_id())

img10 = new_image()
layer10 = new_layer(img10, "l", 16, 16)
new_channel(img10, "only", 16, 16, half(16, 16))
img10.set_selected_layers([layer10])
check("10 唯一通道兜底", mod.pick_channel(img10, "").get_name(), "only")
check("10 目标图层兜底（图里只有一层）",
      [x.get_name() for x in mod.resolve_layers(img10, [])], ["l"])

# ---- 收尾 ------------------------------------------------------------------

print("")
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), ", ".join(FAIL)))
else:
    print("全部通过")
