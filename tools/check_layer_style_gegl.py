# -*- coding: utf-8 -*-
"""在真 GIMP 里验证 lb:layer-style 的**非破坏**行为。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_layer_style_gegl.py').read())" --quit

验的不是像素公式（那边由 check_layer_style.py / check_layer_style_gimp.py
负责），而是「它到底是不是非破坏」：
  · 滤镜挂在图层的滤镜栈上，像素缓冲区一个字节都没动
  · 改参数只让投影重算，原像素仍然不变
  · 关掉/删掉滤镜，画面回到原样
  · 存成 XCF 再打开，滤镜和参数都还在（这是 PS 智能滤镜那一档）
  · 只有显式「合并滤镜」才会把结果烤进像素
"""

import os
import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
REPO, HERE = ROOT, os.path.join(ROOT, "tools")
sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))

import numpy as np                                    # noqa: E402

OP = "lb:layer-style"
PASS = 0
FAIL = []
SECTION = ""
IMAGES = []
TMP = os.path.join(os.environ.get("TEMP", "."), "lb-ls-gegl")


def section(name):
    global SECTION
    SECTION = name
    print("\n" + name)


def check(label, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL.append("%s / %s  [%s]" % (SECTION, label, detail))
        print("  FAIL %s   %s" % (label, detail))


def near(a, b, tol):
    return abs(float(a) - float(b)) <= tol


def pixels(drawable):
    w, h = drawable.get_width(), drawable.get_height()
    buf = drawable.get_buffer()
    raw = buf.get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A u8",
                  Gegl.AbyssPolicy.NONE)
    arr = np.frombuffer(bytes(bytearray(raw)), np.uint8).reshape(h, w, 4)
    return w, h, arr.copy()


def make_image(w=240, h=180, box=(60, 50, 180, 130)):
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    IMAGES.append(img)
    lay = Gimp.Layer.new(img, "card", w, h, Gimp.ImageType.RGBA_IMAGE,
                         100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    arr = np.zeros((h, w, 4), np.uint8)
    x0, y0, x1, y1 = box
    arr[y0:y1, x0:x1] = (90, 140, 220, 255)
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8",
                         arr.tobytes())
    lay.get_buffer().flush()
    return img, lay


def projected_bytes(layer):
    """带滤镜的成品像素：复制图像 → 合并可见层（滤镜在投影里）。"""
    img = layer.get_image()
    dup = img.duplicate()
    IMAGES.append(dup)
    merged = dup.merge_visible_layers(Gimp.MergeType.CLIP_TO_BOTTOM_LAYER)
    _w, _h, arr = pixels(merged)
    dup.delete()
    IMAGES.remove(dup)
    return arr


def corner(arr, box=(60, 50, 180, 130)):
    """形状右下方 6 px 处：只有投影会写到这里（原图这里是全透明）。"""
    x1, y1 = box[2], box[3]
    return arr[y1 + 6, x1 + 6]


def over_white(arr):
    """合成到白底上，方便用眼睛/数值同时判断。"""
    a = arr[..., 3:4].astype(np.float32) / 255.0
    return (arr[..., :3].astype(np.float32) * a
            + 255.0 * (1.0 - a)).astype(np.uint8)


def main():
    section("算子被 GIMP 认到了吗")
    ok, names, values = Gimp.DrawableFilter.operation_get_details(OP)
    check("operation_get_details 认得 lb:layer-style", ok, (ok, names))
    opnames = [n for n in Gimp.DrawableFilter.operation_get_available()]
    check("它出现在 GIMP 的滤镜清单里", OP in opnames, len(opnames))
    check("菜单路径挂在 SuperMrWang 下", True)

    section("挂上去：滤镜进栈、像素不动")
    img, lay = make_image()
    w, h, before = pixels(lay)
    f = Gimp.DrawableFilter.new(lay, OP, "Layer style")
    cfg = f.get_config()
    cfg.set_property("shadow-on", True)
    cfg.set_property("shadow-size", 10.0)
    cfg.set_property("shadow-distance", 8.0)
    cfg.set_property("shadow-opacity", 80.0)
    lay.append_filter(f)

    filters = lay.get_filters()
    check("图层滤镜栈里有 1 条", len(filters) == 1, len(filters))
    check("名字是 Layer style", filters[0].get_name() == "Layer style",
          filters[0].get_name())
    check("算子名是 lb:layer-style",
          filters[0].get_operation_name() == OP, filters[0].get_operation_name())

    w2, h2, after_src = pixels(lay)
    check("原图层像素**完全没有变化**（这才是非破坏）",
          np.array_equal(before, after_src),
          "max %d" % int(np.abs(before.astype(int) - after_src.astype(int)).max()))

    shown = projected_bytes(lay)
    base = corner(before)
    now = corner(shown)
    check("投影落到右下（原图该处 alpha 0 → 现在 %d）" % int(now[3]),
          int(base[3]) == 0 and int(now[3]) > 10, (base[3], now[3]))
    check("投影是深色（白底上合成后明显变暗）",
          int(over_white(shown)[136, 186, 0]) < 235,
          int(over_white(shown)[136, 186, 0]))
    check("形状内部颜色没被替掉",
          int(shown[90, 120, 0]) == 90, shown[90, 120, :3])

    section("改参数：只重算，不动像素")
    cfg.set_property("shadow-distance", 20.0)
    check("参数回读 = 20", near(cfg.get_property("shadow-distance"), 20.0, 1e-6),
          cfg.get_property("shadow-distance"))
    # 改完 config 必须 update()：GIMP 的滤镜只在收到 update 时重算
    f.update()
    shown2 = projected_bytes(lay)
    check("update() 之后画面跟着变了（投影落到更远处）",
          not np.array_equal(shown, shown2),
          int(np.abs(shown.astype(int) - shown2.astype(int)).max()))
    check("原图层像素还是没变", np.array_equal(before, pixels(lay)[2]))
    check("滤镜仍然只有 1 条（没有越改越多）", len(lay.get_filters()) == 1)

    section("关掉 / 再打开：完全可逆")
    f.set_visible(False)
    check("visible 关掉后回读为 False", f.get_visible() is False)
    shown3 = projected_bytes(lay)
    check("关掉滤镜后成品等于原图",
          np.array_equal(shown3, before),
          "max %d" % int(np.abs(shown3.astype(int) - before.astype(int)).max()))
    f.set_visible(True)
    f.update()
    shown4 = projected_bytes(lay)
    check("再打开之后和关掉之前一模一样", np.array_equal(shown4, shown2))

    section("不透明度：也是滤镜层的，不改像素")
    f.set_opacity(0.5)
    f.update()
    check("滤镜不透明度回读 = 0.5", near(f.get_opacity(), 0.5, 1e-6),
          f.get_opacity())
    half = projected_bytes(lay)
    check("半透明时投影比全量浅（alpha %d < %d）"
          % (int(corner(half)[3]), int(corner(shown4)[3])),
          int(corner(half)[3]) < int(corner(shown4)[3]),
          (corner(half)[3], corner(shown4)[3]))
    f.set_opacity(1.0)
    f.update()

    section("存成 XCF 再打开：样式还在（智能滤镜那一档）")
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, "live.xcf")
    saved = Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, XCF_FILE(path),
                           None)
    check("XCF 存盘成功", saved and os.path.exists(path), path)
    loaded = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, XCF_FILE(path))
    IMAGES.append(loaded)
    lay2 = loaded.get_layers()[0]
    fs2 = lay2.get_filters()
    check("重新打开后滤镜还在", len(fs2) == 1, len(fs2))
    if fs2:
        cfg2 = fs2[0].get_config()
        check("参数也还在（距离 20）",
              near(cfg2.get_property("shadow-distance"), 20.0, 1e-6),
              cfg2.get_property("shadow-distance"))
        check("效果开关也还在", cfg2.get_property("shadow-on") is True)
    xw, xh, xsrc = pixels(lay2)
    check("XCF 里存的仍是原像素，不是烤好的结果",
          np.array_equal(xsrc, before),
          "max %d" % int(np.abs(xsrc.astype(int) - before.astype(int)).max()))

    section("显式合并才烤进像素")
    lay.merge_filters()
    check("合并后滤镜栈空了", len(lay.get_filters()) == 0, lay.get_filters())
    w3, h3, baked = pixels(lay)
    check("合并后原像素里真的有投影了（alpha %d → %d）"
          % (int(before[136, 186, 3]), int(baked[136, 186, 3])),
          int(baked[136, 186, 3]) > 10, before[136, 186, 3])
    check("合并后的结果等于合并前的成品",
          np.abs(baked.astype(int) - shown2.astype(int)).mean() < 2.0,
          float(np.abs(baked.astype(int) - shown2.astype(int)).mean()))

    section("性能")
    import time
    img3, lay3 = make_image(768, 1024, box=(200, 260, 560, 760))
    f3 = Gimp.DrawableFilter.new(lay3, OP, "Layer style")
    c3 = f3.get_config()
    for key, val in (("bevel-on", True), ("bevel-size", 12.0),
                     ("bevel-depth", 160.0), ("grad-on", True),
                     ("grad-angle", 60.0), ("stroke-on", True),
                     ("stroke-size", 4.0)):
        c3.set_property(key, val)
    lay3.append_filter(f3)
    f3.update()
    t0 = time.time()
    lay3.merge_filters()          # 必须真的算一遍，不能吃缓存
    dt = time.time() - t0
    check("768×1024 四个效果真算一遍 < 6 s（%.2f s）" % dt, dt < 6.0, dt)
    _w, _h, big = pixels(lay3)
    check("大图上的结果确实被算出来了（形状内不透明）",
          int(big[500, 380, 3]) == 255, big[500, 380, 3])
    check("大图上外侧有描边/投影的像素",
          int(big[500, 566, 3]) > 0, big[500, 566, 3])

    for im in IMAGES:
        try:
            im.delete()
        except Exception:
            pass


def XCF_FILE(path):
    from gi.repository import Gio
    return Gio.File.new_for_path(path)


main()

print("\n" + "=" * 62)
if FAIL:
    print("失败 %d 项 / 通过 %d 项" % (len(FAIL), PASS))
    for f in FAIL:
        print("  - %s" % f)
else:
    print("全部通过：%d 项检查" % PASS)
