# -*- coding: utf-8 -*-
"""在真 GIMP 里跑「图层样式」的回归（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_layer_style_gimp.py').read())" --quit

纯 Python 那套（check_layer_style.py）验的是渲染数学；这里验的是**接线**：
组有没有建对、原图层有没有留在组里、效果层在它上面还是下面、混合模式有没有
真的设进 GIMP、图层的 offset 有没有跟着走（不然效果整体错位）、重跑会不会
在同一个组里堆出两套效果、预览画布会不会真的动。
"""

import importlib.util
import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
for cand in (ROOT, os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))):
    if os.path.exists(os.path.join(cand, "plugin", "layer-style",
                                   "layer-style.py")):
        ROOT = cand
        break
REPO, HERE = ROOT, os.path.join(ROOT, "tools")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))

import numpy as np                                    # noqa: E402
import layer_style as LS                              # noqa: E402

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
        print("  %-54s %s" % (label, detail))
    else:
        FAIL.append("%s / %s（%s）" % (SECTION, label, detail))
        print("  FAIL %-49s %s" % (label, detail))


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "layer_style_plugin", os.path.join(REPO, "plugin", "layer-style",
                                           "layer-style.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_image(w=240, h=180, box=(60, 50, 180, 140), fg=(70, 120, 210),
               alpha=False, offset=(0, 0)):
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    itype = Gimp.ImageType.RGBA_IMAGE if alpha else Gimp.ImageType.RGB_IMAGE
    layer = Gimp.Layer.new(img, "photo", w, h, itype, 100.0,
                           Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    bpp = 4 if alpha else 3
    data = bytearray(w * h * bpp)
    x1, y1, x2, y2 = box
    for y in range(h):
        for x in range(w):
            o = (y * w + x) * bpp
            inside = x1 <= x < x2 and y1 <= y < y2
            data[o:o + 3] = bytes(fg if inside else (0, 0, 0))
            if alpha:
                data[o + 3] = 255 if inside else 0
    fmt = "R'G'B'A u8" if alpha else "R'G'B' u8"
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), fmt, bytes(data))
    buf.flush()
    if alpha:
        try:
            layer.set_offsets(offset[0], offset[1])
        except Exception:
            pass
    return img, layer


def pixels(layer):
    w, h = layer.get_width(), layer.get_height()
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                 "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    return w, h, bytes(bytearray(raw))


def px(rgba, w, x, y):
    o = (y * w + x) * 4
    return tuple(rgba[o:o + 4])


class FakeConfig(object):
    def __init__(self, **vals):
        self.vals = {"style": ""}
        self.vals.update(vals)

    def get_property(self, key):
        return self.vals.get(key)

    def set_property(self, key, value):
        self.vals[key] = value


def only(style, *names):
    for key in style["effects"]:
        style["effects"][key]["enabled"] = key in names
    return style


def names_of(group):
    return [c.get_name() for c in group.get_children()]


def main():
    mod = load_plugin()
    images = []

    section("投影：组、层次、混合模式、offset")
    img, layer = make_image(alpha=True)
    images.append(img)
    st = only(LS.default_style(), "drop-shadow")
    info = mod.apply_style(img, layer, st)
    check("建出样式组", info["group"] is not None)
    check("组名带后缀", info["group"].get_name().endswith(mod.GROUP_SUFFIX),
          info["group"].get_name())
    check("组里 2 层（原图层 + 投影）", info["group"].get_children().__len__() == 2,
          names_of(info["group"]))
    kids = info["group"].get_children()
    check("原图层在组里", any(c is layer for c in kids))
    check("投影在原图层**下面**", kids[-1].get_name() == "Drop Shadow",
          [c.get_name() for c in kids])
    check("投影是 RGBA 层、带 alpha", kids[-1].has_alpha())
    check("效果层挂的是 NORMAL_LEGACY（sRGB over，不是线性光）",
          kids[-1].get_mode() == Gimp.LayerMode.NORMAL_LEGACY,
          kids[-1].get_mode())
    check("投影层 offset 跟原图层一致",
          mod.layer_offsets(kids[-1]) == mod.layer_offsets(layer),
          (mod.layer_offsets(kids[-1]), mod.layer_offsets(layer)))
    w, h, sb = pixels(kids[-1])
    # 角度 120° / 距离 5 → 阴影落在右下方
    _, _, left_top = pixels(layer)
    check("投影的 alpha 只出现在右下侧",
          px(sb, w, 62, 52)[3] < 40 and px(sb, w, 182, 142)[3] > 0,
          (px(sb, w, 62, 52)[3], px(sb, w, 182, 142)[3]))
    check("投影颜色偏暗", px(sb, w, 175, 135)[0] < 120, px(sb, w, 175, 135))

    section("重跑：旧效果层要被换掉，不能叠加")
    before = len(names_of(info["group"]))
    st2 = only(LS.default_style(), "drop-shadow", "outer-glow")
    info2 = mod.apply_style(img, layer, st2)
    check("还是同一个组", info2["group"] is info["group"])
    check("层数变成 3（不是 4）", len(names_of(info2["group"])) == 3,
          names_of(info2["group"]))
    check("层数不是简单累加", len(names_of(info2["group"])) != before + 2)
    check("外发光在投影上面、原图层下面",
          names_of(info2["group"])[-1] == "Drop Shadow"
          and names_of(info2["group"])[-2] == "Outer Glow",
          names_of(info2["group"]))

    section("内部效果在内容之上")
    img3, layer3 = make_image(alpha=True, fg=(200, 200, 200))
    images.append(img3)
    st3 = only(LS.default_style(), "inner-shadow", "color-overlay")
    info3 = mod.apply_style(img3, layer3, st3)
    order3 = names_of(info3["group"])
    check("组里 3 层", len(order3) == 3, order3)
    check("原图层在最下面", order3[-1] == "photo", order3)
    check("颜色叠加压在内阴影上面", order3[0] == "Color Overlay", order3)
    ov = info3["group"].get_children()[0]
    w3, h3, ob = pixels(ov)
    check("颜色叠加是纯色 + 内部 alpha",
          px(ob, w3, 100, 90)[:3] == (255, 0, 0)
          and px(ob, w3, 20, 20)[3] == 0, (px(ob, w3, 100, 90),
                                           px(ob, w3, 20, 20)))

    section("描边：内 / 外 / 居中")
    for pos, marker in (("outside", (57, 95)), ("inside", (63, 95)),
                        ("center", (60, 95))):
        img4, layer4 = make_image(alpha=True)
        images.append(img4)
        st4 = only(LS.default_style(), "stroke")
        st4["effects"]["stroke"].update({"position": pos, "size": 6.0,
                                         "color": [1, 0, 0]})
        mod.apply_style(img4, layer4, st4)
        grp = layer4.get_parent()
        stl = [c for c in grp.get_children()
               if c.get_name() == "Stroke"][0]
        w4, h4, b4 = pixels(stl)
        got = px(b4, w4, marker[0], marker[1])
        check("描边（%s）红且不透明" % pos, got[0] > 180 and got[3] > 160, got)
    img5, layer5 = make_image(alpha=True)
    images.append(img5)
    st5 = only(LS.default_style(), "stroke")
    st5["effects"]["stroke"].update({"position": "outside", "size": 6.0})
    mod.apply_style(img5, layer5, st5)
    stl5 = [c for c in layer5.get_parent().get_children()
            if c.get_name() == "Stroke"][0]
    w5, h5, b5 = pixels(stl5)
    check("外描边不越界到内容里", px(b5, w5, 120, 95)[3] == 0,
          px(b5, w5, 120, 95))

    section("斜面和浮雕：两层 + 混合模式")
    img6, layer6 = make_image(alpha=True, fg=(150, 150, 150))
    images.append(img6)
    st6 = only(LS.default_style(), "bevel")
    info6 = mod.apply_style(img6, layer6, st6)
    kids6 = info6["group"].get_children()
    check("组里 3 层（阴影 + 高光 + 原图层）", len(kids6) == 3,
          [c.get_name() for c in kids6])
    modes = set(int(c.get_mode()) for c in kids6[:2])
    check("两片都是 NORMAL_LEGACY（混合已在数学层预混）",
          modes == {int(Gimp.LayerMode.NORMAL_LEGACY)}, modes)
    check("高光层在最上面", kids6[0].get_name().endswith("(highlight)"),
          kids6[0].get_name())

    section("预览对话框（不 run，直接驱动）")
    img7, layer7 = make_image(alpha=True)
    images.append(img7)
    cfg = FakeConfig()
    dlg, ctx = mod.build_dialog(cfg, img7, layer7, 240, 180)
    check("建出对话框", dlg is not None)
    check("预览图尺寸 = 长边 560 缩放后的尺寸",
          (ctx["preview_w"], ctx["preview_h"]) == (240, 180),
          (ctx["preview_w"], ctx["preview_h"]))
    check("首帧算出 pixbuf", ctx["pixbuf"] is not None)
    first = bytes(ctx["pixbuf"].get_pixels()) if ctx["pixbuf"] else b""
    ctx["style"]["effects"]["drop-shadow"]["distance"] = 40
    ctx["render"]()
    second = bytes(ctx["pixbuf"].get_pixels()) if ctx["pixbuf"] else b""
    check("改距离之后预览真的变了", first and first != second,
          "%d vs %d" % (len(first), len(second)))
    ctx["style"]["effects"]["bevel"]["enabled"] = True
    ctx["render"]()
    check("开斜面之后也没炸", ctx["pixbuf"] is not None)
    ctx["set_page"]("bevel")
    check("切到斜面页", ctx["page"] == "bevel", ctx["page"])
    check("每个效果页都建了控件",
          set(LS.PANEL_ORDER) <= set(ctx["controls"].keys()),
          len(ctx["controls"]))
    if ctx["id"]:
        from gi.repository import GLib
        GLib.source_remove(ctx["id"])
    dlg.destroy()

    section("色板 / 图案取用不炸")
    stops = mod.gradient_stops()
    check("渐变能取到色标或安全返回 None",
          stops is None or len(stops) >= 2, len(stops or []))
    unit = mod.pattern_unit(img7)
    check("图案能取到单元或安全返回 None",
          unit is None or (unit.ndim == 3 and unit.shape[2] == 4),
          None if unit is None else unit.shape)
    assets = mod.collect_assets(img7, True, True)
    check("资产字典可用", isinstance(assets, dict), list(assets.keys()))

    section("图层 offset 跟着走")
    img8, layer8 = make_image(alpha=True, offset=(40, 30))
    images.append(img8)
    st8 = only(LS.default_style(), "drop-shadow")
    info8 = mod.apply_style(img8, layer8, st8)
    kid8 = info8["group"].get_children()[-1]
    check("投影层 offset = 原图层的 offset",
          mod.layer_offsets(kid8) == (40, 30), mod.layer_offsets(kid8))

    section("复制样式：寄生数据 + 代码框")
    img8, layer8 = make_image(120, 90, box=(20, 20, 100, 70), alpha=True)
    images.append(img8)
    st8 = only(LS.default_style(), "drop-shadow", "inner-shadow", "stroke")
    st8["effects"]["drop-shadow"]["distance"] = 11
    st8["effects"]["stroke"]["position"] = "inside"
    info8 = mod.apply_style(img8, layer8, st8)
    back8 = mod.recover_style(layer8)
    check("重开对话框能读回上次的样式（不是默认值）",
          back8 is not None
          and LS.format_style(back8) == LS.format_style(st8),
          None if back8 is None else "ok")
    check("组上挂着这份样式", mod._read_style_code(info8["group"]) is not None)
    check("图层自己也挂着（被拖出组也还在）",
          mod._read_style_code(layer8) is not None)
    img_bare, layer_bare = make_image(40, 40)
    images.append(img_bare)
    check("没挂过的图层读回来是 None",
          mod.recover_style(layer_bare) is None)

    # 真正的「拷贝图层样式 → 粘到另一个图层」
    img9, layer9 = make_image(120, 90, box=(25, 25, 105, 75), alpha=True)
    images.append(img9)
    code8 = LS.format_style(mod.recover_style(layer8))
    st_copy, _warn8 = LS.read_style_code(code8)
    mod.apply_style(img9, layer9, st_copy)
    names8 = [c.get_name() for c in info8["group"].get_children()]
    names9 = [c.get_name() for c in layer9.get_parent().get_children()]
    check("粘过去之后层序与层名完全一致", names8 == names9, names9)
    check("新图层也记住了这份样式",
          LS.format_style(mod.recover_style(layer9)) == code8)

    section("对话框里的代码框（复制 / 粘贴自己来）")
    img10, layer10 = make_image(240, 180, box=(60, 50, 180, 120), alpha=True)
    images.append(img10)
    cfg10 = FakeConfig()
    dlg10, ctx10 = mod.build_dialog(cfg10, img10, layer10, 240, 180)
    code10 = ctx10["style_code"]()
    check("代码框里是一份能读回来的代码",
          LS.format_style(LS.read_style_code(code10)[0])
          == LS.format_style(ctx10["style"]))
    check("框里的文本就是那份代码", ctx10["box_text"]().strip() == code10.strip(),
          "%d 字符" % len(code10))
    check("代码面板默认收起（对话框高度不变）",
          ctx10["code_panel"].get_visible() is False)
    ctx10["changed"]()
    ctx10["style"]["effects"]["drop-shadow"]["distance"] = 33
    ctx10["changed"]()
    check("参数一改，代码串跟着变",
          '"distance": 33' in ctx10["box_text"]())

    before10 = bytes(ctx10["pixbuf"].get_pixels()) if ctx10["pixbuf"] else b""
    st_new = only(LS.default_style(), "outer-glow", "bevel")
    st_new["effects"]["bevel"].update({"size": 17.0, "style": "pillow"})
    st_new["effects"]["outer-glow"]["size"] = 12.0
    loaded = ctx10["load_code"](LS.pretty_style(st_new))
    check("粘贴另一份代码 → 载入成功", loaded is True)
    check("载入后样式等于粘进来的那份",
          LS.format_style(ctx10["style"]) == LS.format_style(st_new))
    check("载入后滑杆跟着变（斜面大小 17）",
          abs(ctx10["controls"]["bevel"]["size"].get_value() - 17.0) < 0.01,
          ctx10["controls"]["bevel"]["size"].get_value())
    check("载入后下拉跟着变（枕状浮雕）",
          ctx10["controls"]["bevel"]["style"].get_active_id() == "pillow",
          ctx10["controls"]["bevel"]["style"].get_active_id())
    check("载入后勾选框跟着变（斜面开、投影关）",
          ctx10["rowmap"]["bevel"].get_child().get_active()
          and not ctx10["rowmap"]["drop-shadow"].get_child().get_active())
    check("载入后代码框换成新代码",
          '"size": 17' in ctx10["box_text"]())
    ctx10["render"]()
    after10 = bytes(ctx10["pixbuf"].get_pixels()) if ctx10["pixbuf"] else b""
    check("载入后预览真的重画了", before10 and before10 != after10,
          "%d vs %d" % (len(before10), len(after10)))

    before_style = LS.format_style(ctx10["style"])
    check("乱粘一坨 → 返回 False",
          ctx10["load_code"]("hello world") is False)
    check("乱粘之后样式没被改坏",
          LS.format_style(ctx10["style"]) == before_style)

    copied = ctx10["copy_code"]()
    check("复制出来的就是当前这份（剪贴板不行就退回全选）",
          LS.format_style(LS.read_style_code(copied)[0]) == before_style)
    check("复制的内容还能再粘回去", ctx10["load_code"](copied) is True)

    if ctx10["id"]:
        from gi.repository import GLib as _GLib
        _GLib.source_remove(ctx10["id"])
    dlg10.destroy()

    section("GIMP 真的按混合模式合成了吗（数学 vs GEGL）")
    img10, layer10 = make_image(240, 180, box=(60, 50, 180, 120),
                                fg=(90, 140, 220), alpha=True)
    images.append(img10)
    st10 = only(LS.default_style(), "drop-shadow", "inner-shadow",
                "color-overlay")
    st10["effects"]["color-overlay"].update({"color": [1.0, 0.4, 0.0],
                                             "opacity": 60})
    pw10, ph10, pb10 = pixels(layer10)
    plan10 = LS.render(pb10, pw10, ph10, st10)
    expect = LS.preview(plan10, pw10, ph10)
    mod.apply_style(img10, layer10, st10)
    dup = img10.duplicate()
    merged = dup.merge_visible_layers(Gimp.MergeType.CLIP_TO_BOTTOM_LAYER)
    mw, mh, mbytes = pixels(merged)
    got = LS.to_float(mbytes, mw, mh)
    diff = np.abs(got - expect)
    # 只在两边都实心的像素上比：透明区的 alpha 舍入会让 RGB 无意义
    mask = (expect[..., 3] > 0.9) & (got[..., 3] > 0.9)
    worst = float(diff[..., :3][mask].max()) if mask.any() else 1.0
    mean = float(diff[..., :3][mask].mean()) if mask.any() else 1.0
    check("实心区最大色差 ≤ 6/255（%.1f）" % (worst * 255), worst <= 6 / 255.0,
          worst * 255)
    check("实心区平均色差 ≤ 1.5/255（%.2f）" % (mean * 255),
          mean <= 1.5 / 255.0, mean * 255)
    dup.delete()

    section("大图性能")
    img9, layer9 = make_image(768, 1024, box=(150, 200, 620, 820), alpha=True)
    images.append(img9)
    st9 = only(LS.default_style(), "drop-shadow", "outer-glow",
               "inner-shadow", "bevel", "gradient-overlay", "stroke")
    t0 = time.time()
    mod.apply_style(img9, layer9, st9)
    dt = time.time() - t0
    check("768×1024 六个效果 < 12 s（%.2f s）" % dt, dt < 12.0, dt)
    check("六个效果都进了组",
          len(layer9.get_parent().get_children()) >= 7,
          len(layer9.get_parent().get_children()))

    for im in images:
        try:
            im.delete()
        except Exception:
            pass


main()

print("\n" + "=" * 62)
if FAIL:
    print("失败 %d 项 / 通过 %d 项" % (len(FAIL), PASS))
    for f in FAIL:
        print("  - %s" % f)
else:
    print("全部通过：%d 项检查" % PASS)
