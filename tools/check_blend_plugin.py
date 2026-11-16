# -*- coding: utf-8 -*-
"""回归：应用图像 / 计算 的 Python 插件在半尺寸、带偏移图层上的行为。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_blend_plugin.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gimp / Gegl 的 GI 绑定），用系统 Python 会
在 import gi 处失败。检查三件事：

1. read_rgba 收画布坐标、write_rgba 收图层本地坐标——两套口径不能串；
2. 源图层比目标小或者带偏移时，没盖到的像素原样保留（keep_uncovered）；
3. 计算结果写进图层 alpha 时，alpha 是「原 alpha × 灰度值」，不是原 alpha。

第 1、2 条以前都错：目标图层的输入按本地坐标去读（带偏移就整体错位），
界外还被当成透明黑参与混合。第 3 条以前写的是 alpha × 1，等于没写。
"""
import os
import array
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

def _find_repo():
    """定位仓库根目录：本文件被 GIMP 用 exec 读进来时 __file__ 指向 GIMP 自己
    的插件目录，不可靠，所以再拿当前工作目录兜一次。
    Locate the repo root. When GIMP execs this file, __file__ points at GIMP's
    own plug-in directory, so the working directory is used as a fallback."""
    cands = []
    try:
        cands.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except NameError:
        pass
    cwd = os.getcwd()
    cands += [cwd, os.path.join(cwd, "SuperMrWang"),
              os.path.join(cwd, "..", "SuperMrWang")]
    for c in cands:
        if os.path.exists(os.path.join(c, "plugin", "blend", "blend.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


PLUG = os.path.join(_find_repo(), "plugin", "blend", "blend.py")

spec = importlib.util.spec_from_file_location("blend_kernel_plugin", PLUG)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
import blend_kernel  # 由插件目录 import 进来 / imported from the plugin dir

FAIL = []


def check(label, got, want, tol=2):
    ok = all(abs(g - w) <= tol for g, w in zip(got, want))
    print("%-42s got=%-22s want=%-18s %s" %
          (label, " ".join("%.0f" % v for v in got[:4]),
           " ".join(str(v) for v in want), "OK" if ok else "FAIL"))
    if not ok:
        FAIL.append(label)


def fill(layer, rgba):
    w, h = layer.get_width(), layer.get_height()
    buf = array.array('f', bytes(w * h * 16))
    for i in range(w * h):
        for c in range(4):
            buf[i * 4 + c] = rgba[c] / 255.0
    mod.write_rgba(layer, (0, 0, w, h), buf)


def px(drawable, x, y):
    data = drawable.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                                     "R'G'B'A float", Gegl.AbyssPolicy.BLACK)
    a = array.array('f')
    a.frombytes(data)
    return [round(v * 255) for v in a]


# ---------------- 应用图像：源层更小 + 带偏移 ----------------
img = Gimp.Image.new(6, 6, Gimp.ImageBaseType.RGB)
tgt = Gimp.Layer.new(img, "T", 4, 4, Gimp.ImageType.RGBA_IMAGE, 100.0,
                     Gimp.LayerMode.NORMAL)
img.insert_layer(tgt, None, 0)
tgt.set_offsets(1, 1)
src = Gimp.Layer.new(img, "S", 2, 2, Gimp.ImageType.RGBA_IMAGE, 100.0,
                     Gimp.LayerMode.NORMAL)
img.insert_layer(src, None, 0)
src.set_offsets(2, 2)

fill(tgt, (10, 10, 128, 255))
fill(src, (200, 100, 50, 255))

p = dict(blend=blend_kernel.BLEND_INDEX['multiply'], opacity=100.0,
         tch=blend_kernel.CH_GRAY, sch=blend_kernel.CH_GRAY, src_layer=src,
         use_mask=False, mask_layer=None, mch=blend_kernel.CH_GRAY,
         inv_mask=False, keep_transp=False, result=0)
mod.run_apply_image(img, tgt, p)

# 图层本地坐标：目标层 4x4，画布偏移 (1,1)；源层覆盖画布 (2,2)-(3,3)
check("应用图像·覆盖处 正片叠底(Gray→RGB)", px(tgt, 1, 1), (5, 5, 59, 255))
check("应用图像·源层外原样（左上）", px(tgt, 0, 0), (10, 10, 128, 255))
check("应用图像·源层外原样（右下）", px(tgt, 3, 3), (10, 10, 128, 255))

# 单通道目标：只有 R 参与混合，且必须落在图层自己坐标系的 (0,0) = 画布 (1,1)
p2 = dict(p, tch=blend_kernel.CH_RED, sch=blend_kernel.CH_RED,
          blend=blend_kernel.BLEND_INDEX['multiply'])
fill(tgt, (10, 10, 128, 255))
mod.run_apply_image(img, tgt, p2)
check("应用图像·单通道 R（画布 2,2）", px(tgt, 1, 1), (8, 10, 128, 255))
check("应用图像·单通道 R（画布 1,1 不动）", px(tgt, 0, 0), (10, 10, 128, 255))

# 缩放/补偿值：加法 scale=2 → (A+B)/2。Gray 源取亮度压进每个通道
# （PS 行为）：luma(200,100,50)=117.65，r=g=(10+117.65)/2≈64，b=(128+117.65)/2≈123
p3 = dict(p, blend=blend_kernel.BLEND_INDEX['linear-dodge'],
          scale=2.0, offset=0.0)
fill(tgt, (10, 10, 128, 255))
mod.run_apply_image(img, tgt, p3)
check("应用图像·加法 缩放2 (A+B)/2", px(tgt, 1, 1), (64, 64, 123, 255))

# ---------------- 计算：写入图层 alpha（带偏移图层） ----------------
img2 = Gimp.Image.new(6, 6, Gimp.ImageBaseType.RGB)
lay = Gimp.Layer.new(img2, "A", 4, 4, Gimp.ImageType.RGBA_IMAGE, 100.0,
                     Gimp.LayerMode.NORMAL)
img2.insert_layer(lay, None, 0)
lay.set_offsets(1, 1)
src2 = Gimp.Layer.new(img2, "B", 4, 4, Gimp.ImageType.RGBA_IMAGE, 100.0,
                      Gimp.LayerMode.NORMAL)
img2.insert_layer(src2, None, 0)
src2.set_offsets(1, 1)
fill(lay, (200, 100, 50, 255))
fill(src2, (200, 100, 50, 255))

pc = dict(ch1=blend_kernel.CH_GRAY, inv1=False, s1_layer=lay,
          ch2=blend_kernel.CH_GRAY, inv2=False, s2_layer=src2,
          blend=blend_kernel.BLEND_INDEX['multiply'], opacity=100.0,
          use_mask=False, mask_layer=None, mch=blend_kernel.CH_GRAY,
          inv_mask=False, result=3)
mod.run_calculations(img2, lay, pc)

# 这里是「图层 alpha」结果：alpha 应该是两路灰度的乘积，且必须落在
# 图层自己的 4x4 上（以前把画布坐标写进本地缓冲区，带偏移就错位）
check("计算·图层 alpha 写在自己位置上", px(lay, 0, 0), (200, 100, 50, 54))
check("计算·图层 alpha 右下角", px(lay, 3, 3), (200, 100, 50, 54))

# ---------------- 计算：范围（整幅 / 仅选区）与「载入为选区」 ----------------
img3 = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
a3 = Gimp.Layer.new(img3, "A3", 8, 8, Gimp.ImageType.RGBA_IMAGE, 100.0,
                    Gimp.LayerMode.NORMAL)
img3.insert_layer(a3, None, 0)
b3 = Gimp.Layer.new(img3, "B3", 8, 8, Gimp.ImageType.RGBA_IMAGE, 100.0,
                    Gimp.LayerMode.NORMAL)
img3.insert_layer(b3, None, 0)
fill(a3, (100, 100, 100, 255))
fill(b3, (200, 200, 200, 255))

base = dict(ch1=blend_kernel.CH_GRAY, inv1=False, s1_layer=a3,
            ch2=blend_kernel.CH_GRAY, inv2=False, s2_layer=b3,
            blend=blend_kernel.BLEND_INDEX['normal'], opacity=100.0,
            use_mask=False, mask_layer=None, mch=blend_kernel.CH_GRAY,
            inv_mask=False)


def selv(image, x, y):
    """选区在 (x,y) 的值，0..255（Gimp.Selection.value 已经是 0..255 刻度，
    不是 0..1）/ selection value at a pixel; GIMP reports it on 0..255"""
    return [round(image.get_selection().value(image, x, y))]


# 1. 范围 = 仅选区：左半（选区内）有值，右半归零
img3.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 4, 8)
mod.run_calculations(img3, a3, dict(base, result=0, scope=1))
check("计算·仅选区 内=200", selv(img3, 1, 1), [200])
check("计算·仅选区 外=0", selv(img3, 6, 1), [0])

# 2. 范围 = 整幅：选区外同样有值（旧行为不变）
mod.run_calculations(img3, a3, dict(base, result=0, scope=0))
check("计算·整幅 外也有值", selv(img3, 6, 1), [200])

# 3. 结果 = 灰度图层 + 同时载入为选区：图层留档，选区也拿到同一份灰度
img3.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 4, 8)
mod.run_calculations(img3, a3, dict(base, result=2, scope=1,
                                    load_selection=True))
names = [l.get_name() for l in img3.get_layers()]
check("计算·灰度图层已建", [1 if "Calculations" in names else 0], [1])
check("计算·同时载入选区 内=200", selv(img3, 1, 1), [200])
check("计算·同时载入选区 外=0", selv(img3, 6, 1), [0])

# 4. 结果 = 图层 alpha + 同时载入：选区必须是计算结果，不是被改回原图的 RGB
fill(a3, (100, 100, 100, 255))
mod.run_calculations(img3, a3, dict(base, result=3, scope=0,
                                    load_selection=True))
check("计算·alpha+载入选区 值=灰度", selv(img3, 1, 1), [200])
check("计算·alpha 已写入", [px(a3, 1, 1)[3]], [200])

print("\n%s" % ("全部通过" if not FAIL else "失败：%s" % ", ".join(FAIL)))
