#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""六向转换的回归测试：**逐位对齐 GIMP 原生**。

跑法 / run:
    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'tools/check_convert.py').read())" --quit

判定方式：同一份源数据建两张图，一张只调原生 PDB（模拟用户手点菜单），
一张只调插件函数，然后比较读出的 Y' 值。相等即通过——插件是否「正确」
不由我们定义，由原生定义。

不要求插件已安装：直接从 plugin/convert/convert.py 加载模块调函数。
"""

import array
import importlib.util
import os

import gi

gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

ROOT = None


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
        if os.path.exists(os.path.join(c, "plugin", "convert", "convert.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


ROOT = _find_repo()
SPEC = importlib.util.spec_from_file_location(
    "convert_plugin", os.path.join(ROOT, "plugin", "convert", "convert.py"))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

W = H = 16
RAMP = [0 if x < 6 else (128 if x < 11 else 255) for x in range(W)]
XS = [2, 8, 13]
DRIFT_HI = [0.0, 187.8, 255.0]      # 原生通道 → 选区
DRIFT_LO = [0.0, 55.0, 255.0]       # 原生选区 → 通道
EXACT = [0.0, 128.0, 255.0]         # 选区 ↔ 蒙版

passed = 0
failed = 0


def check(label, got, want, tol=0.15):
    global passed, failed
    got, want = list(got), list(want)
    if any(isinstance(v, str) for v in got + want):
        ok = got == want
    else:
        ok = len(got) == len(want) and all(
            abs(a - b) <= tol for a, b in zip(got, want))
    if ok:
        passed += 1
        print("  ok   %-44s %s" % (label, got))
    else:
        failed += 1
        print("  FAIL %-44s got=%s want=%s" % (label, got, want))


def pdb(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def new_doc(w=W, h=H, ox=0, oy=0, precision=None):
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    if precision is not None:
        img.convert_precision(precision)
    layer = Gimp.Layer.new(img, "layer", w, h, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, -1)
    if ox or oy:
        layer.set_offsets(ox, oy)
    return img, layer


def set_plane(drawable, values):
    """按 Y' 值填满一个 drawable，用 u8 写保证数值精确。
    Fill a drawable with Y' values; writing u8 keeps the numbers exact."""
    w, h = drawable.get_width(), drawable.get_height()
    if len(values) == w:
        values = values * h
    if len(values) != w * h:
        raise ValueError("平面长度 %d != %d×%d" % (len(values), w, h))
    data = bytes(max(0, min(255, int(round(v)))) for v in values)
    # 直写 buffer：同一图里做过蒙版操作后，shadow 写法会只落到右半 tile。
    drawable.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "Y' u8", data)
    drawable.update(0, 0, w, h)


def _srgb_to_linear(v):
    if v <= 0.04045:
        return v / 12.92
    return ((v + 0.055) / 1.055) ** 2.4


def set_sel(img, values):
    """同 set_selection，但不依赖插件内部函数（插件已不再做空间换算）。"""
    w, h = img.get_width(), img.get_height()
    if len(values) == w:
        values = values * h
    linear = array.array('f', (_srgb_to_linear(v) for v in values))
    sel = img.get_selection()
    sel.all(img)
    shadow = sel.get_shadow_buffer()
    shadow.set(Gegl.Rectangle.new(0, 0, w, h), "Y float", linear.tobytes())
    shadow.flush()
    sel.merge_shadow(True)
    sel.update(0, 0, w, h)


def make_channel(img, name="ramp", values=None):
    values = RAMP * H if values is None else values
    colour = Gegl.Color()
    colour.set_rgba(1.0, 1.0, 1.0, 1.0)
    ch = Gimp.Channel.new(img, name, img.get_width(), img.get_height(),
                          100.0, colour)
    img.insert_channel(ch, None, -1)
    set_plane(ch, values)
    return ch


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


# ---- 原生参照：完全模拟用户手点菜单 ----------------------------------------

def native_channel_to_selection(img, ch):
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=ch)
    return img.get_selection()


def native_selection_to_channel(img):
    return pdb('gimp-selection-save', image=img).index(1)


def native_selection_to_mask(img, layer):
    m = layer.create_mask(Gimp.AddMaskType.SELECTION)
    layer.add_mask(m)
    return m


def native_channel_to_mask(img, layer, ch):
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=ch)
    return native_selection_to_mask(img, layer)


def native_mask_to_selection(img, mask):
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=mask)
    return img.get_selection()


def native_mask_to_channel(img, mask):
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=mask)
    return pdb('gimp-selection-save', image=img).index(1)


def native_sel2path(img, layer):
    """原生「选择 → 路径」，只取它新造出来的那条。
    Native Select > To Path; returns the path it just created."""
    before = set(p.get_id() for p in img.get_paths())
    proc = Gimp.get_pdb().lookup_procedure('plug-in-sel2path')
    cfg = proc.create_config()
    cfg.set_property('image', img)
    cfg.set_core_object_array('drawables', [layer])
    proc.run(cfg)
    return [p for p in img.get_paths() if p.get_id() not in before]


def native_path_to_selection(img, path):
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=path)
    return img.get_selection()


def path_to_rect(img, layer, x, y, w, h):
    """用原生过程把矩形选区描成路径，当作各方向的源。
    Seed a path from a rectangular selection using the native tracer."""
    img.select_rectangle(Gimp.ChannelOps.REPLACE, x, y, w, h)
    return native_sel2path(img, layer)[0]


def run():
    print("\n[1] 通道 → 选区（原生：Y' 当线性直搬）")
    img, _ = new_doc()
    ch = make_channel(img)
    nat = read_y(native_channel_to_selection(img, ch))
    img.delete()
    img, _ = new_doc()
    ch = make_channel(img)
    img.set_selected_channels([ch])
    mod.channel_to_selection(img)
    ours = read_y(img.get_selection())
    img.delete()
    check("原生值就是 128 → 188", nat, DRIFT_HI)
    check("插件与原生逐位一致", ours, nat)

    print("\n[2] 选区 → 通道（原生：线性当 Y' 直搬）")
    img, _ = new_doc()
    set_sel(img, [v / 255.0 for v in RAMP])
    nat = read_y(native_selection_to_channel(img))
    img.delete()
    img, _ = new_doc()
    set_sel(img, [v / 255.0 for v in RAMP])
    dst = mod.selection_to_channel(img)
    ours = read_y(dst)
    check("原生值就是 128 → 55", nat, DRIFT_LO)
    check("插件与原生逐位一致", ours, nat)
    check("通道名", [dst.get_name()], ["Selection"])
    img.delete()

    print("\n[3] 选区 → 蒙版（原生：这一对会换算，不漂）")
    img, layer = new_doc()
    set_sel(img, [v / 255.0 for v in RAMP])
    nat = read_y(native_selection_to_mask(img, layer))
    img.delete()
    img, layer = new_doc()
    set_sel(img, [v / 255.0 for v in RAMP])
    mod.selection_to_mask(img, [layer])
    ours = read_y(layer.get_mask())
    check("原生值 128 不变", nat, EXACT)
    check("插件与原生逐位一致", ours, nat)
    img.delete()

    print("\n[4] 通道 → 蒙版（原生两步）")
    img, layer = new_doc()
    ch = make_channel(img)
    nat = read_y(native_channel_to_mask(img, layer, ch))
    img.delete()
    img, layer = new_doc()
    ch = make_channel(img)
    img.set_selected_channels([ch])
    mod.channel_to_mask(img, [layer])
    ours = read_y(layer.get_mask())
    check("原生两步 = 188", nat, DRIFT_HI)
    check("插件与原生逐位一致", ours, nat)
    img.delete()

    print("\n[5] 蒙版 → 选区")
    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, RAMP)
    nat = read_y(native_mask_to_selection(img, m))
    img.delete()
    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, RAMP)
    mod.mask_to_selection(img, [layer])
    ours = read_y(img.get_selection())
    check("原生值 128 不变", nat, EXACT)
    check("插件与原生逐位一致", ours, nat)
    img.delete()

    print("\n[6] 蒙版 → 通道（原生两步）")
    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, RAMP)
    nat = read_y(native_mask_to_channel(img, m))
    img.delete()
    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, RAMP)
    dst = mod.mask_to_channel(img, [layer])
    ours = read_y(dst)
    check("原生两步 = 55", nat, DRIFT_LO)
    check("插件与原生逐位一致", ours, nat)
    check("通道名带图层名", [dst.get_name()], ["layer Mask"])
    img.delete()

    print("\n[7] 32 位线性精度：原生不漂，插件必须也不漂")
    img, layer = new_doc(precision=Gimp.Precision.U32_LINEAR)
    ch = make_channel(img)
    nat = read_y(native_channel_to_selection(img, ch))
    img.delete()
    img, _ = new_doc(precision=Gimp.Precision.U32_LINEAR)
    ch = make_channel(img)
    img.set_selected_channels([ch])
    mod.channel_to_selection(img)
    ours = read_y(img.get_selection())
    img.delete()
    check("原生线性精度 ≈ 128", nat, EXACT, tol=1.0)
    check("插件与原生逐位一致", ours, nat)

    print("\n[8] 偏移图层：通道 → 蒙版")
    img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    small = Gimp.Layer.new(img, "small", 8, 8, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(small, None, -1)
    small.set_offsets(4, 4)
    ch = make_channel(img, "grad", [x * 8 for x in range(W)] * H)
    nat = read_y(native_channel_to_mask(img, small, ch), [0, 3, 7], 4)
    img.delete()
    img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    small = Gimp.Layer.new(img, "small", 8, 8, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(small, None, -1)
    small.set_offsets(4, 4)
    ch = make_channel(img, "grad", [x * 8 for x in range(W)] * H)
    img.set_selected_channels([ch])
    mod.channel_to_mask(img, [small])
    m = small.get_mask()
    ours = read_y(m, [0, 3, 7], 4)
    check("蒙版尺寸跟着图层", [m.get_width(), m.get_height()], [8.0, 8.0])
    check("插件与原生逐位一致", ours, nat)
    img.delete()

    print("\n[9] 多图层一次挂齐")
    img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    layers = []
    for i in range(3):
        lay = Gimp.Layer.new(img, "L%d" % i, W, H, Gimp.ImageType.RGBA_IMAGE,
                             100.0, Gimp.LayerMode.NORMAL)
        img.insert_layer(lay, None, 0)
        layers.append(lay)
    ch = make_channel(img)
    img.set_selected_channels([ch])
    mod.channel_to_mask(img, layers)
    check("三个图层都有蒙版",
          [lay.get_mask() is not None for lay in layers], [True] * 3)
    check("第三个图层的内容", read_y(layers[2].get_mask()), DRIFT_HI)
    img.delete()

    print("\n[10] 已有蒙版：重建后与原生新建一致")
    img, layer = new_doc()
    old = layer.create_mask(Gimp.AddMaskType.BLACK)     # 先挂一张全黑
    layer.add_mask(old)
    ch = make_channel(img)
    img.set_selected_channels([ch])
    mod.channel_to_mask(img, [layer])
    check("蒙版已换新", [layer.get_mask().get_id() != old.get_id()], [True])
    check("内容与原生一致", read_y(layer.get_mask()), DRIFT_HI)
    img.delete()

    print("\n[11] 无选区时 → 通道：按全选处理（原生补全选）")
    img, _ = new_doc()
    dst = mod.selection_to_channel(img)
    check("得到全白通道", read_y(dst), [255.0] * 3)
    img.delete()

    print("\n[12] 错误分支")
    img, layer = new_doc()
    try:
        mod.channel_to_selection(img)
        check("无通道应报错", ["没报错"], ["应报错"])
    except RuntimeError as exc:
        check("无通道报错信息", ["通道" in str(exc)], [True])
    try:
        mod.mask_to_selection(img, [layer])
        check("无蒙版应报错", ["没报错"], ["应报错"])
    except RuntimeError as exc:
        check("无蒙版报错信息", ["蒙版" in str(exc)], [True])
    grp = Gimp.GroupLayer.new(img, "grp")
    img.insert_layer(grp, None, 0)
    try:
        mod.selection_to_mask(img, [grp])
        check("图层组应报错", ["没报错"], ["应报错"])
    except RuntimeError as exc:
        check("图层组报错信息", ["图层组" in str(exc)], [True])
    img.delete()

    print("\n[13] 往返闭合（原生也闭合，插件跟随）")
    img, _ = new_doc()
    set_sel(img, [v / 255.0 for v in RAMP])
    ch = mod.selection_to_channel(img)
    img.set_selected_channels([ch])
    mod.channel_to_selection(img)
    check("选区 → 通道 → 选区", read_y(img.get_selection()), EXACT)
    img.delete()

    print("\n[14] 通道取源的三路兜底（通道面板右键 / 重复运行）")
    # 14a：通道以 drawable 形式传进来（通道面板右键），但没有「选中」状态
    img, layer = new_doc()
    ch = make_channel(img)
    img.set_selected_layers([layer])      # 新建通道会自动变成选中项，这里还原
    check("前置：图层是选中项、通道未选中",
          [len(img.get_selected_layers()), len(img.get_selected_channels())],
          [1, 0])
    mod.channel_to_selection(img, [ch])
    check("14a 上下文通道可作源", read_y(img.get_selection()), DRIFT_HI)
    img.delete()

    # 14b：什么都没传，图里只有一条通道 → 直接用它
    img, _ = new_doc()
    make_channel(img)
    mod.channel_to_selection(img)
    check("14b 唯一通道兜底", read_y(img.get_selection()), DRIFT_HI)
    img.delete()

    # 14c：通道面板右键 → 蒙版，目标图层靠「图里唯一一层」兜底
    img, layer = new_doc()
    ch = make_channel(img)
    mod.channel_to_mask(img, [ch])
    check("14c 通道右键能挂上蒙版", [layer.get_mask() is not None], [True])
    check("14c 蒙版内容与原生一致", read_y(layer.get_mask()), DRIFT_HI)
    img.delete()

    # 14d：多条通道且没选 → 报错里要把名字列出来
    img, layer = new_doc()
    make_channel(img, "alpha", RAMP * H)
    make_channel(img, "beta", [200] * (W * H))
    img.set_selected_layers([layer])      # 同上：清掉自动选中
    check("14d 前置：两条通道都没选中",
          [len(img.get_selected_channels())], [0])
    try:
        mod.channel_to_selection(img)
        check("14d 多通道未选中应报错", ["没报错"], ["应报错"])
    except RuntimeError as exc:
        check("14d 报错列出通道名", ["alpha" in str(exc) and "beta" in str(exc)],
              [True])
    img.delete()

    print("\n[15] 路径 → 选区（原生 select-item，一步）")
    img, layer = new_doc()
    path = path_to_rect(img, layer, 6, 0, 8, H)
    nat = read_y(native_path_to_selection(img, path))
    img.delete()
    img, layer = new_doc()
    path = path_to_rect(img, layer, 6, 0, 8, H)
    mod.path_to_selection(img, [path])
    ours = read_y(img.get_selection())
    check("矩形路径栅格化 = 硬边", nat, [0.0, 255.0, 255.0])
    check("插件与原生逐位一致", ours, nat)
    img.delete()

    print("\n[16] 选区 → 路径（原生 plug-in-sel2path）")
    img, layer = new_doc()
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 6, 0, 8, H)
    nat_path = native_sel2path(img, layer)[0]
    nat = read_y(native_path_to_selection(img, nat_path))
    img.delete()
    img, layer = new_doc()
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 6, 0, 8, H)
    ours_path = mod.selection_to_path(img, [layer])
    ours = read_y(native_path_to_selection(img, ours_path))
    check("描出来的路径栅格化回选区", ours, nat)
    check("路径名与原生一致", [ours_path.get_name()], [nat_path.get_name()])
    img.delete()

    print("\n[17] 羽化选区 → 路径：软边被压成 50% 等值线（原生也如此）")
    img, layer = new_doc()
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 3, 3, 5, 5)
    Gimp.Selection.feather(img, 2.0)
    nat_before = read_y(img.get_selection())
    nat_path = native_sel2path(img, layer)[0]
    nat = read_y(native_path_to_selection(img, nat_path))
    img.delete()
    img, layer = new_doc()
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 3, 3, 5, 5)
    Gimp.Selection.feather(img, 2.0)
    ours_path = mod.selection_to_path(img, [layer])
    ours = read_y(native_path_to_selection(img, ours_path))
    check("羽化边上原本是灰", [0.0 < nat_before[0] < 255.0], [True])
    check("过路径后只剩硬边", [ours[0] in (0.0, 255.0)], [True])
    check("插件与原生逐位一致", ours, nat)
    img.delete()

    print("\n[18] 通道 → 路径（原生两步：通道 → 选区 → 路径）")
    img, layer = new_doc()
    ch = make_channel(img)
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=ch)
    nat_path = native_sel2path(img, layer)[0]
    nat = read_y(native_path_to_selection(img, nat_path))
    img.delete()
    img, layer = new_doc()
    ch = make_channel(img)
    img.set_selected_layers([layer])
    img.set_selected_channels([ch])
    _src, ours_path = mod.channel_to_path(img, [layer])
    ours = read_y(native_path_to_selection(img, ours_path))
    check("插件与原生逐位一致", ours, nat)
    check("路径名带通道名", [ours_path.get_name()], ["Channel ramp"])
    img.delete()

    print("\n[19] 路径 → 通道 / 蒙版（路径栅格化后走原生落点）")
    img, layer = new_doc()
    path = path_to_rect(img, layer, 6, 0, 8, H)
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=path)
    nat_ch = read_y(pdb('gimp-selection-save', image=img).index(1))
    img.delete()
    img, layer = new_doc()
    path = path_to_rect(img, layer, 6, 0, 8, H)
    _src, ch = mod.path_to_channel(img, [path])
    ours = read_y(ch)
    check("路径 → 通道 = 硬边", ours, [0.0, 255.0, 255.0])
    check("插件与原生逐位一致", ours, nat_ch)
    mod.path_to_mask(img, [path])
    check("路径 → 蒙版同为硬边", read_y(layer.get_mask()), ours)
    img.delete()

    print("\n[20] 蒙版 → 路径（原生两步：蒙版 → 选区 → 路径）")
    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, RAMP)
    pdb('gimp-image-select-item', image=img,
        operation=Gimp.ChannelOps.REPLACE, item=m)
    nat_path = native_sel2path(img, layer)[0]
    nat = read_y(native_path_to_selection(img, nat_path))
    img.delete()
    img, layer = new_doc()
    m = layer.create_mask(Gimp.AddMaskType.WHITE)
    layer.add_mask(m)
    set_plane(m, RAMP)
    _src, ours_path = mod.mask_to_path(img, [layer])
    ours = read_y(native_path_to_selection(img, ours_path))
    check("插件与原生逐位一致", ours, nat)
    check("路径名带图层名", [ours_path.get_name()], ["layer Mask"])
    img.delete()

    print("\n[21] 重复运行不撞名，也不覆盖旧路径")
    img, layer = new_doc()
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 3, 3, 5, 5)
    p1 = mod.selection_to_path(img, [layer])
    p2 = mod.selection_to_path(img, [layer])
    check("第一条叫 Selection", [p1.get_name()], ["Selection"])
    check("第二条自动编号", [p2.get_name()], ["Selection 2"])
    check("两条路径都在", [len(img.get_paths())], [2])
    img.delete()

    print("\n[22] 路径取源兜底与错误分支")
    img, layer = new_doc()
    try:
        mod.path_to_selection(img)
        check("无路径应报错", ["没报错"], ["应报错"])
    except RuntimeError as exc:
        check("无路径报错信息", ["路径" in str(exc)], [True])

    # 两条路径时，认「路径面板里选中的那条」，谁选中就取谁
    # （GIMP 的路径选中项不会被清空，总有一条是选中状态）
    pa = path_to_rect(img, layer, 6, 0, 8, H)
    pb = path_to_rect(img, layer, 0, 0, 4, H)
    img.set_selected_paths([pa])
    mod.path_to_selection(img)
    check("取选中路径 A", tuple(Gimp.Selection.bounds(img))[4:6], (14, 16))
    img.set_selected_paths([pb])
    mod.path_to_selection(img)
    check("取选中路径 B", tuple(Gimp.Selection.bounds(img))[4:6], (4, 16))

    # 没有选区时 → 路径：明确拒绝，不偷偷描空路径
    pdb('gimp-selection-none', image=img)
    try:
        mod.selection_to_path(img, [layer])
        check("无选区应报错", ["没报错"], ["应报错"])
    except RuntimeError as exc:
        check("无选区报错信息", ["选区" in str(exc)], [True])
    img.delete()


try:
    run()
except Exception as exc:
    import traceback
    traceback.print_exc()
    failed += 1
    print("\n异常: %r" % exc)

print("\n" + "=" * 60)
print("通过 %d 项，失败 %d 项" % (passed, failed))
print("=" * 60)
