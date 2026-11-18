#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原生路径 vs convert 插件：六向转换的数值对比（诊断脚本）。

跑法 / run:
    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'tools/compare_native.py').read())" --quit
"""

import array
import importlib.util
import os

import gi

gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

W = H = 16
RAMP = [0 if x < 6 else (128 if x < 11 else 255) for x in range(W)]
XS = [2, 8, 13]
WANT = [0.0, 128.0, 255.0]


def _find_repo():
    cands = [os.getcwd(), os.path.join(os.getcwd(), "SuperMrWang"),
             os.path.join(os.getcwd(), "..", "SuperMrWang")]
    for c in cands:
        if os.path.exists(os.path.join(c, "plugin", "convert", "convert.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


ROOT = _find_repo()
SPEC = importlib.util.spec_from_file_location(
    "convert_plugin", os.path.join(ROOT, "plugin", "convert", "convert.py"))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def pdb(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def new_doc():
    img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(img, "layer", W, H, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, -1)
    return img, layer


def set_plane(drawable, values):
    w, h = drawable.get_width(), drawable.get_height()
    data = bytes(max(0, min(255, int(round(v * 255)))) for v in values)
    drawable.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "Y' u8", data)
    drawable.update(0, 0, w, h)


def make_channel(img, values=None, name="ramp"):
    values = (RAMP * H) if values is None else values
    colour = Gegl.Color()
    colour.set_rgba(1.0, 1.0, 1.0, 1.0)
    ch = Gimp.Channel.new(img, name, W, H, 100.0, colour)
    img.insert_channel(ch, None, -1)
    set_plane(ch, [v / 255.0 for v in values])
    return ch


def _srgb_to_linear(v):
    if v <= 0.04045:
        return v / 12.92
    return ((v + 0.055) / 1.055) ** 2.4


def set_selection(img, values):
    values = values * H if len(values) == W else values
    linear = array.array('f', (_srgb_to_linear(v) for v in values))
    sel = img.get_selection()
    sel.all(img)
    shadow = sel.get_shadow_buffer()
    shadow.set(Gegl.Rectangle.new(0, 0, W, H), "Y float", linear.tobytes())
    shadow.flush()
    sel.merge_shadow(True)
    sel.update(0, 0, W, H)


def read_y(item, xs=None, y=8):
    out = []
    for x in (XS if xs is None else xs):
        raw = item.get_buffer().get(
            Gegl.Rectangle.new(x, y, 1, 1), 1.0, "Y' float",
            Gegl.AbyssPolicy.NONE)
        a = array.array('f')
        a.frombytes(bytes(bytearray(raw)))
        out.append(round(a[0] * 255, 1))
    return out


def line(tag, native, ours):
    print("  %-28s native=%-22s convert=%s" % (tag, native, ours))


def try_(fn):
    try:
        return fn()
    except Exception as exc:
        return "ERR:%s" % exc


def run():
    print("\n========== 原生 vs convert（源值 0 / 128 / 255）==========")

    # 1 通道 → 选区
    img, _ = new_doc()
    ch = make_channel(img)
    img.set_selected_channels([ch])
    nat = try_(lambda: (pdb('gimp-image-select-item', image=img,
                            operation=Gimp.ChannelOps.REPLACE, item=ch),
                        read_y(img.get_selection()))[1])
    img.delete()

    img, _ = new_doc()
    ch = make_channel(img)
    img.set_selected_channels([ch])
    mod.channel_to_selection(img)
    ours = read_y(img.get_selection())
    img.delete()
    line("通道 → 选区", nat, ours)

    # 2 选区 → 通道
    img, _ = new_doc()
    set_selection(img, [v / 255.0 for v in RAMP])
    nat = try_(lambda: read_y(img.get_channels()[0]
                              if img.get_channels() else
                              (pdb('gimp-selection-save', image=img),
                               img.get_channels()[0])[1]))
    img.delete()

    img, _ = new_doc()
    set_selection(img, [v / 255.0 for v in RAMP])
    ours = read_y(mod.selection_to_channel(img))
    img.delete()
    line("选区 → 通道", nat, ours)

    # 3 选区 → 蒙版
    img, layer = new_doc()
    set_selection(img, [v / 255.0 for v in RAMP])

    def nat_sel_mask():
        m = layer.create_mask(Gimp.AddMaskType.SELECTION)
        layer.add_mask(m)
        return read_y(m)
    nat = try_(nat_sel_mask)
    img.delete()

    img, layer = new_doc()
    set_selection(img, [v / 255.0 for v in RAMP])
    mod.selection_to_mask(img, [layer])
    ours = read_y(layer.get_mask())
    img.delete()
    line("选区 → 蒙版", nat, ours)

    # 4 通道 → 蒙版：原生没有直接入口，只能两步，见第 7 项

    # 5 蒙版 → 选区
    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, [v / 255.0 for v in RAMP] * H)
    nat = try_(lambda: (pdb('gimp-image-select-item', image=img,
                            operation=Gimp.ChannelOps.REPLACE, item=m),
                        read_y(img.get_selection()))[1])
    img.delete()

    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, [v / 255.0 for v in RAMP] * H)
    mod.mask_to_selection(img, [layer])
    ours = read_y(img.get_selection())
    img.delete()
    line("蒙版 → 选区", nat, ours)

    # 6 蒙版 → 通道（原生两步：蒙版→选区→通道）
    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, [v / 255.0 for v in RAMP] * H)

    def nat_mask_ch():
        pdb('gimp-image-select-item', image=img,
            operation=Gimp.ChannelOps.REPLACE, item=m)
        ch2 = pdb('gimp-selection-save', image=img).index(1)
        return read_y(ch2)
    nat = try_(nat_mask_ch)
    img.delete()

    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, [v / 255.0 for v in RAMP] * H)
    ours = read_y(mod.mask_to_channel(img, [layer]))
    img.delete()
    line("蒙版 → 通道（原生两步）", nat, ours)

    # 7 原生「通道 → 蒙版」只能绕两步：通道→选区→蒙版
    img, layer = new_doc()
    ch = make_channel(img)

    def nat_ch_mask_two_step():
        pdb('gimp-image-select-item', image=img,
            operation=Gimp.ChannelOps.REPLACE, item=ch)
        m2 = layer.create_mask(Gimp.AddMaskType.SELECTION)
        layer.add_mask(m2)
        return read_y(m2)
    nat = try_(nat_ch_mask_two_step)
    img.delete()

    img, layer = new_doc()
    ch = make_channel(img)
    img.set_selected_channels([ch])
    mod.channel_to_mask(img, [layer])
    ours = read_y(layer.get_mask())
    img.delete()
    line("通道 → 蒙版（原生两步）", nat, ours)

    # 8 原生往返：选区 → 通道 → 选区
    img, _ = new_doc()
    set_selection(img, [v / 255.0 for v in RAMP])

    def nat_roundtrip():
        ch3 = pdb('gimp-selection-save', image=img).index(1)
        pdb('gimp-image-select-item', image=img,
            operation=Gimp.ChannelOps.REPLACE, item=ch3)
        return read_y(img.get_selection())
    nat = try_(nat_roundtrip)
    img.delete()

    img, _ = new_doc()
    set_selection(img, [v / 255.0 for v in RAMP])
    ch3 = mod.selection_to_channel(img)
    img.set_selected_channels([ch3])
    mod.channel_to_selection(img)
    ours = read_y(img.get_selection())
    img.delete()
    line("选区→通道→选区（往返）", nat, ours)

    # 9 原生连续往返三次，看漂移累加
    img, _ = new_doc()
    set_selection(img, [v / 255.0 for v in RAMP])

    def nat_loops():
        vals = None
        for _i in range(3):
            ch4 = pdb('gimp-selection-save', image=img).index(1)
            pdb('gimp-image-select-item', image=img,
                operation=Gimp.ChannelOps.REPLACE, item=ch4)
            img.remove_channel(ch4)
            vals = read_y(img.get_selection())
        return vals
    nat = try_(nat_loops)
    img.delete()
    line("原生往返 ×3", nat, "—")

    print("\n目标期望（视觉灰）= %s\n" % WANT)


try:
    run()
except Exception:
    import traceback
    traceback.print_exc()
