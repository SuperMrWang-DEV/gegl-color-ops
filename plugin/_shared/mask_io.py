# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 蒙版读写 / mask plumbing for GIMP
 ---------------------------------------------------------------------------
 purpose   选区 ↔ 蒙版字节流 的往返，全在 C 里做缩放，Python 只搬一次字节。
           两条容易踩的规矩：

           1. **通道读出来是线性的**。`gimp-selection-save` 得到的通道用
              "Y u8" 读，值是线性亮度；而选区值（Selection.value）和图层
              alpha 都是 sRGB 编码过的。实测：通道写 128 → 选区读回 188。
              不转换，精修后蒙版的中间调会整体下压，50% 等值线跟着漂。
           2. **写回选区走「临时图层 alpha」而不是通道**。图层 alpha 是直通
              的 0..255，没有 gamma 这回事；`gimp-image-select-item` 对图层
              取的就是 alpha。这样读一次转一次、写一次不转，方向不会搞反。
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

from gi.repository import Gimp, Gegl, GLib

import refine_math as RM

try:
    from lb_i18n import _
except Exception:                       # 单独的 helper 不在：保持可用，只是不翻译
    def _(message):
        return GLib.dgettext(None, message)

# 只认这两个通道名：抠图插件写的，和本插件写的。
MASK_CHANNELS = ("Refined Mask", "Cutout Mask")


def _pdb(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def pdb(name, **props):
    """对外暴露的 PDB 调用（同 _pdb，只是不带下划线）。"""
    return _pdb(name, **props)


def has_selection(image):
    sel = image.get_selection()
    if sel is None:
        return False
    ok, non_empty, x1, y1, x2, y2 = sel.bounds(image)
    return bool(non_empty) and x2 > x1 and y2 > y1


def find_mask_channel(image):
    """找抠图/精修留下的蒙版通道。没有就 None。"""
    try:
        for ch in image.get_channels():
            if ch.get_name() in MASK_CHANNELS:
                return ch
    except Exception:
        pass
    return None


def read_channel(channel, long_edge=0):
    """通道 → (w, h, 蒙版字节)。long_edge>0 时缩到那个长边（C 的 layer-scale）。

    通道里的值是线性的，这里用 LUT 转成「选区值」那一套（0..255 直通），
    后续所有数学都在这个域里做，写回时不再转换。
    """
    w, h = channel.get_width(), channel.get_height()
    rect = Gegl.Rectangle.new(0, 0, w, h)
    raw = channel.get_buffer().get(rect, 1.0, "Y u8", Gegl.AbyssPolicy.NONE)
    data = bytes(bytearray(raw)).translate(RM.linear_to_srgb_lut())
    if long_edge and max(w, h) > long_edge:
        tw, th, data = scale_mask(data, w, h,
                                  *fit_size(w, h, long_edge))
        w, h = tw, th
    return w, h, data


def fit_size(w, h, long_edge):
    scale = float(long_edge) / max(w, h, 1)
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def _scratch_image(w, h):
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(img, "lb-mask", w, h, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    return img, layer


def _write_gray(layer, w, h, mask):
    """把 0..255 写进图层的 RGB（alpha 全不透明），走 R'G'B' 这个 gamma 域。"""
    n = w * h
    if len(mask) != n:
        raise RuntimeError(_("Mask size mismatch: %d values for %d")
                           % (len(mask), n))
    data = bytearray(n * 4)
    data[0::4] = mask
    data[1::4] = mask
    data[2::4] = mask
    data[3::4] = b"\xff" * n
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", bytes(data))
    buf.flush()


def scale_mask(mask, w, h, tw, th):
    """把蒙版缩放到 tw×th。缩放交给 GIMP（C），Python 不做插值。"""
    if (w, h) == (tw, th):
        return w, h, bytes(mask)
    img, layer = _scratch_image(w, h)
    try:
        _write_gray(layer, w, h, mask)
        _pdb('gimp-layer-scale', layer=layer, new_width=tw, new_height=th,
             local_origin=False)
        raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, tw, th), 1.0,
                                     "R'G'B' u8", Gegl.AbyssPolicy.NONE)
        data = bytes(bytearray(raw))
    finally:
        img.delete()
    return tw, th, data[0::3]


def selection_from_mask(image, mask, mw, mh):
    """蒙版 → 画布上的选区（软边保留）。

    建一个 mw×mh 的临时图层（RGB=白、A=蒙版），插进**用户图像**后缩放到
    画布尺寸，再 gimp-image-select-item 取 alpha。缩放是 C 的；用完就删。
    """
    canvas_w, canvas_h = image.get_width(), image.get_height()
    n = mw * mh
    tmp = Gimp.Layer.new(image, "lb-refine-mask", mw, mh,
                         Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
    image.insert_layer(tmp, None, 0)
    try:
        data = bytearray(n * 4)
        data[0::4] = b"\xff" * n
        data[1::4] = b"\xff" * n
        data[2::4] = b"\xff" * n
        data[3::4] = bytes(mask)
        buf = tmp.get_buffer()
        buf.set(Gegl.Rectangle.new(0, 0, mw, mh), "R'G'B'A u8", bytes(data))
        buf.flush()
        if (mw, mh) != (canvas_w, canvas_h):
            _pdb('gimp-layer-scale', layer=tmp, new_width=canvas_w,
                 new_height=canvas_h, local_origin=False)
        _pdb('gimp-image-select-item', image=image,
             operation=int(Gimp.ChannelOps.REPLACE), item=tmp)
    finally:
        image.remove_layer(tmp)


def current_mask(image, long_edge=0):
    """当前要精修的蒙版：选区优先，其次蒙版通道。

    返回 (w, h, mask, source)，source 是 'selection' 或通道名；都没有就抛错。
    """
    if has_selection(image):
        channel = _pdb('gimp-selection-save', image=image).index(1)
        try:
            w, h, mask = read_channel(channel, long_edge)
        finally:
            image.remove_channel(channel)
        return w, h, mask, "selection"

    channel = find_mask_channel(image)
    if channel is not None:
        w, h, mask = read_channel(channel, long_edge)
        return w, h, mask, channel.get_name()

    raise RuntimeError(_(
        "There is no selection to refine. Make a selection first, or run "
        "Cut Out first (it leaves a \"Cutout Mask\" channel behind)."))


def read_drawable_rgba(drawable, long_edge, exact=None):
    """图层 → (w, h, RGBA)。超过 long_edge 就让 GIMP 缩（C 的 layer-scale）。

    和 AI 抠图那条路同一个套路：Python 里做双线性插值，4000×6000 要几十秒；
    临时图层 + gimp-layer-scale 是毫秒级。
    """
    w, h = drawable.get_width(), drawable.get_height()
    long_edge = max(32, int(long_edge))
    if exact and tuple(exact) != (w, h):
        tw, th = int(exact[0]), int(exact[1])
        image = drawable.get_image()
        tmp = drawable.copy()
        tmp.set_name("lb-refine-thumb")
        image.insert_layer(tmp, None, image.get_item_position(drawable))
        try:
            _pdb('gimp-layer-scale', layer=tmp, new_width=tw, new_height=th,
                 local_origin=False)
            raw = tmp.get_buffer().get(Gegl.Rectangle.new(0, 0, tw, th), 1.0,
                                       "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
            return tw, th, bytes(bytearray(raw))
        finally:
            image.remove_layer(tmp)
    if max(w, h) <= long_edge:
        rect = Gegl.Rectangle.new(0, 0, w, h)
        raw = drawable.get_buffer().get(rect, 1.0, "R'G'B'A u8",
                                        Gegl.AbyssPolicy.NONE)
        return w, h, bytes(bytearray(raw))
    tw, th = fit_size(w, h, long_edge)
    image = drawable.get_image()
    tmp = drawable.copy()
    tmp.set_name("lb-refine-thumb")
    image.insert_layer(tmp, None, image.get_item_position(drawable))
    try:
        _pdb('gimp-layer-scale', layer=tmp, new_width=tw, new_height=th,
             local_origin=False)
        raw = tmp.get_buffer().get(Gegl.Rectangle.new(0, 0, tw, th), 1.0,
                                   "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
        data = bytes(bytearray(raw))
    finally:
        image.remove_layer(tmp)
    if len(data) != tw * th * 4:
        raise RuntimeError(_("Failed to read the layer: expected %d bytes, "
                             "got %d") % (tw * th * 4, len(data)))
    return tw, th, data
