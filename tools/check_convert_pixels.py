#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""严格比对：十二个方向，整幅逐像素，原生 vs 插件。

check_convert.py 用三点采样判定；这里换成 0–255 全幅渐变、把整幅平面读出来
逐像素比（4096 像素 × 12 向 × 2 档精度），要求偏差恰好为 0。

跑法 / run:
    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \\
        --batch-interpreter=python-fu-eval \\
        -b "exec(open(r'tools/check_convert_pixels.py').read())" --quit
"""
import array
import importlib.util
import os

import gi

gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

def _find_repo():
    cwd = os.getcwd()
    for c in (cwd, os.path.join(cwd, "SuperMrWang"),
              os.path.join(cwd, "..", "SuperMrWang")):
        if os.path.exists(os.path.join(c, "plugin", "convert", "convert.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


ROOT = _find_repo()
SPEC = importlib.util.spec_from_file_location(
    "convert_plugin", os.path.join(ROOT, "plugin", "convert", "convert.py"))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

W, H = 256, 16
RAMP = list(range(W))                      # 覆盖 0..255 全部取值
COLS = RAMP * H

_rows = {"ok": 0, "bad": 0}


def pdb(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def new_doc(precision=None):
    img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    if precision is not None:
        img.convert_precision(precision)
    layer = Gimp.Layer.new(img, "layer", W, H, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, -1)
    return img, layer


def set_plane(drawable, values):
    data = bytes(max(0, min(255, int(round(v)))) for v in values)
    drawable.get_buffer().set(Gegl.Rectangle.new(0, 0, W, H), "Y' u8", data)
    drawable.update(0, 0, W, H)


def _srgb_to_linear(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def set_sel(img, values):
    linear = array.array('f', (_srgb_to_linear(v) for v in values))
    sel = img.get_selection()
    sel.all(img)
    shadow = sel.get_shadow_buffer()
    shadow.set(Gegl.Rectangle.new(0, 0, W, H), "Y float", linear.tobytes())
    shadow.flush()
    sel.merge_shadow(True)
    sel.update(0, 0, W, H)


def make_channel(img):
    colour = Gegl.Color()
    colour.set_rgba(1.0, 1.0, 1.0, 1.0)
    ch = Gimp.Channel.new(img, "ramp", W, H, 100.0, colour)
    img.insert_channel(ch, None, -1)
    set_plane(ch, COLS)
    return ch


def make_mask(img, layer):
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, COLS)
    return m


def plane(item):
    raw = item.get_buffer().get(Gegl.Rectangle.new(0, 0, W, H), 1.0,
                                "Y' float", Gegl.AbyssPolicy.NONE)
    a = array.array('f')
    a.frombytes(bytes(bytearray(raw)))
    return a


def compare(tag, a, b, tol):
    diff = [abs(x - y) for x, y in zip(a, b)]
    worst = max(diff) * 255 if diff else 0.0
    n = sum(1 for d in diff if d * 255 > tol)
    ok = n == 0 and len(a) == len(b)
    _rows["ok" if ok else "bad"] += 1
    print("  %-4s %-30s 像素=%d 差异=%d 最大偏差=%.3f/255" %
          ("ok" if ok else "FAIL", tag, len(a), n, worst))
    return ok


def sel2path(img, layer):
    """在当前选区上跑原生 To Path，不改选区。"""
    before = set(p.get_id() for p in img.get_paths())
    proc = Gimp.get_pdb().lookup_procedure('plug-in-sel2path')
    cfg = proc.create_config()
    cfg.set_property('image', img)
    cfg.set_core_object_array('drawables', [layer])
    proc.run(cfg)
    return [p for p in img.get_paths() if p.get_id() not in before][0]


def seed_path(img, layer, x=64, w=128):
    img.select_rectangle(Gimp.ChannelOps.REPLACE, x, 0, w, H)
    return sel2path(img, layer)


def raster_path(img, path):
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=path)
    return img.get_selection()


def native_sel2path(img, layer):
    return sel2path(img, layer)


def run_suite(precision, tol):
    name = "u8 非线性（默认）" if precision is None else "32 位线性"
    print("\n== %s ==" % name)

    # 1 通道 → 选区
    img, layer = new_doc(precision)
    ch = make_channel(img)
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=ch)
    nat = plane(img.get_selection())
    img.delete()
    img, layer = new_doc(precision)
    ch = make_channel(img)
    mod.channel_to_selection(img, [ch])
    compare("通道 → 选区", nat, plane(img.get_selection()), tol)
    img.delete()

    # 2 选区 → 通道
    img, layer = new_doc(precision)
    set_sel(img, COLS)
    nat = plane(pdb('gimp-selection-save', image=img).index(1))
    img.delete()
    img, layer = new_doc(precision)
    set_sel(img, COLS)
    mod.selection_to_channel(img)
    compare("选区 → 通道", nat, plane(img.get_channels()[0]), tol)
    img.delete()

    # 3 选区 → 蒙版
    img, layer = new_doc(precision)
    set_sel(img, COLS)
    m = layer.create_mask(Gimp.AddMaskType.SELECTION)
    layer.add_mask(m)
    nat = plane(m)
    img.delete()
    img, layer = new_doc(precision)
    set_sel(img, COLS)
    mod.selection_to_mask(img, [layer])
    compare("选区 → 蒙版", nat, plane(layer.get_mask()), tol)
    img.delete()

    # 4 通道 → 蒙版（原生两步）
    img, layer = new_doc(precision)
    ch = make_channel(img)
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=ch)
    m = layer.create_mask(Gimp.AddMaskType.SELECTION)
    layer.add_mask(m)
    nat = plane(m)
    img.delete()
    img, layer = new_doc(precision)
    ch = make_channel(img)
    mod.channel_to_mask(img, [ch, layer])
    compare("通道 → 蒙版", nat, plane(layer.get_mask()), tol)
    img.delete()

    # 5 蒙版 → 选区
    img, layer = new_doc(precision)
    make_mask(img, layer)
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=layer.get_mask())
    nat = plane(img.get_selection())
    img.delete()
    img, layer = new_doc(precision)
    make_mask(img, layer)
    mod.mask_to_selection(img, [layer])
    compare("蒙版 → 选区", nat, plane(img.get_selection()), tol)
    img.delete()

    # 6 蒙版 → 通道（原生两步）
    img, layer = new_doc(precision)
    make_mask(img, layer)
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=layer.get_mask())
    nat = plane(pdb('gimp-selection-save', image=img).index(1))
    img.delete()
    img, layer = new_doc(precision)
    make_mask(img, layer)
    mod.mask_to_channel(img, [layer])
    compare("蒙版 → 通道", nat, plane(img.get_channels()[0]), tol)
    img.delete()

    # 7 路径 → 选区
    img, layer = new_doc(precision)
    path = seed_path(img, layer)
    nat = plane(raster_path(img, path))
    img.delete()
    img, layer = new_doc(precision)
    path = seed_path(img, layer)
    mod.path_to_selection(img, [path])
    compare("路径 → 选区", nat, plane(img.get_selection()), tol)
    img.delete()

    # 8 选区 → 路径（两边都栅格化回选区比）
    img, layer = new_doc(precision)
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 64, 0, 128, H)
    nat = plane(raster_path(img, native_sel2path(img, layer)))
    img.delete()
    img, layer = new_doc(precision)
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 64, 0, 128, H)
    ours = mod.selection_to_path(img, [layer])
    compare("选区 → 路径", nat, plane(raster_path(img, ours)), tol)
    img.delete()

    # 9 路径 → 通道
    img, layer = new_doc(precision)
    path = seed_path(img, layer)
    raster_path(img, path)
    nat = plane(pdb('gimp-selection-save', image=img).index(1))
    img.delete()
    img, layer = new_doc(precision)
    path = seed_path(img, layer)
    mod.path_to_channel(img, [path])
    compare("路径 → 通道", nat, plane(img.get_channels()[0]), tol)
    img.delete()

    # 10 通道 → 路径（原生两步）
    img, layer = new_doc(precision)
    ch = make_channel(img)
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=ch)
    nat = plane(raster_path(img, native_sel2path(img, layer)))
    img.delete()
    img, layer = new_doc(precision)
    ch = make_channel(img)
    ours = mod.channel_to_path(img, [ch, layer])[1]
    compare("通道 → 路径", nat, plane(raster_path(img, ours)), tol)
    img.delete()

    # 11 路径 → 蒙版
    img, layer = new_doc(precision)
    path = seed_path(img, layer)
    raster_path(img, path)
    m = layer.create_mask(Gimp.AddMaskType.SELECTION)
    layer.add_mask(m)
    nat = plane(m)
    img.delete()
    img, layer = new_doc(precision)
    path = seed_path(img, layer)
    mod.path_to_mask(img, [path, layer])
    compare("路径 → 蒙版", nat, plane(layer.get_mask()), tol)
    img.delete()

    # 12 蒙版 → 路径（原生两步）
    img, layer = new_doc(precision)
    make_mask(img, layer)
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=layer.get_mask())
    nat = plane(raster_path(img, native_sel2path(img, layer)))
    img.delete()
    img, layer = new_doc(precision)
    make_mask(img, layer)
    ours = mod.mask_to_path(img, [layer])[1]
    compare("蒙版 → 路径", nat, plane(raster_path(img, ours)), tol)
    img.delete()


run_suite(None, 0.4)                      # u8：允许 8 位量化后的半档
run_suite(Gimp.Precision.U32_LINEAR, 0.05)  # 线性：几乎不该有偏差

print("\n通过 %d 项，失败 %d 项" % (_rows["ok"], _rows["bad"]))
