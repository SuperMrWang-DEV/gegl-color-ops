#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 计算（GEGL 薄壳）
 ---------------------------------------------------------------------------
 purpose   把 PS「图像 → 计算」的结果落到选区 / Alpha 通道 / 灰度层 / 图层
           alpha。像素**全部**由 GEGL 算子 lb:calculations 算，本文件里没有
           第二份混合公式，只做三件事：
             1. 把「图像 + 图层 + 通道」读成画布对齐的 GEGL 缓冲；
             2. 搭 buffer-source × 2 → lb:calculations 的小图，blit 出结果；
             3. 把结果落到 PS 的四种 Result 上。
           算子里修好的透明像素处理、26 种混合模式、通道枚举顺序都会自动
           继承，不存在「插件和算子对不上」的问题。
 menu      颜色 → SuperMrWang → Calculations (GEGL)
 usage     交互模式弹对话框；批处理用注册的参数（见 do_create_procedure）。
 note      GEGL 算子只能输出像素，落成选区/通道是 GIMP 侧的事；反过来
           Gimp.DrawableFilter 又拒绝带 aux 的算子（"effects with an 'aux'
           pad cannot be applied non-destructively"），所以这里是手搭一个
           三节点的小图直接 blit，绕开两边。
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import array
import os
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GLib, GObject, Gegl
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


def _N_(message):
    return message


def _(message):
    return GLib.dgettext(None, message)


# ---- 只在算子参数表里出现的名字 --------------------------------------------
# 混合模式按 PS 对话框的顺序排（Darker Color 在 Linear Burn 后、Lighter
# Color 在 Linear Dodge 后），纯粹是显示用；真正传给算子的是 nick，所以
# 这里和算子内部枚举顺序不一致也不会错。
# Blend modes in Photoshop's dialog order. Only the display order; the op gets
# the nick string, so a different order inside the op is harmless.
BLENDS = [
    ("normal", _("Normal")), ("darken", _("Darken")),
    ("multiply", _("Multiply")), ("color-burn", _("Color Burn")),
    ("linear-burn", _("Linear Burn")), ("darker-color", _("Darker Color")),
    ("lighten", _("Lighten")), ("screen", _("Screen")),
    ("color-dodge", _("Color Dodge")),
    ("linear-dodge", _("Linear Dodge (Add)")),
    ("lighter-color", _("Lighter Color")), ("overlay", _("Overlay")),
    ("soft-light", _("Soft Light")), ("hard-light", _("Hard Light")),
    ("vivid-light", _("Vivid Light")), ("linear-light", _("Linear Light")),
    ("pin-light", _("Pin Light")), ("hard-mix", _("Hard Mix")),
    ("difference", _("Difference")), ("exclusion", _("Exclusion")),
    ("subtract", _("Subtract")), ("divide", _("Divide")),
    ("hue", _("Hue")), ("saturation", _("Saturation")),
    ("color", _("Color")), ("luminosity", _("Luminosity")),
]

# 下标就是 CH_* 编号 / indices double as the CH_* ids
CHANNELS = [("luma", _("Gray")), ("red", _("Red")), ("green", _("Green")),
            ("blue", _("Blue")), ("alpha", _("Alpha")),
            ("mask", _("Layer mask"))]
CH_LUMA, CH_RED, CH_GREEN, CH_BLUE, CH_ALPHA, CH_MASK = range(6)

RESULTS = [("selection", _("Selection")),
           ("new-channel", _("New alpha channel")),
           ("grey-layer", _("New grey layer")),
           ("layer-alpha", _("Layer alpha"))]
RES_SELECTION, RES_CHANNEL, RES_GREY, RES_ALPHA = range(4)

OP_NAME = "lb:calculations"
FMT = "R'G'B'A float"
# 与 common/blend.h 的 lb_luma 同一组系数（Rec.709），只用于「遮罩来自第三
# 张图」时读遮罩值——那是取通道，不是混合公式。
_LUMA = (0.2126, 0.7152, 0.0722)


# ---- GEGL 初始化 -----------------------------------------------------------
# GIMP 的插件进程虽然链接了 libgegl，但没有调用 gegl_init()：直接
# create_child 会崩（op factory 的 hash table 还是空指针）。这里补一次。
_gegl_ready = False


def _ensure_gegl():
    global _gegl_ready
    if not _gegl_ready:
        Gegl.init()
        _gegl_ready = True


# ---- 通用小件 / small helpers ----------------------------------------------

def _offsets(drawable):
    try:
        _ok, ox, oy = drawable.get_offsets()
        return ox, oy
    except Exception:
        return 0, 0


def _size(drawable):
    try:
        return drawable.get_width(), drawable.get_height()
    except Exception:
        return 0, 0


def _all_layers(image):
    """展开图层组 / flatten layer groups into one list"""
    out = []

    def walk(items):
        for it in items:
            out.append(it)
            try:
                if isinstance(it, Gimp.GroupLayer):
                    walk(it.get_children())
            except Exception:
                pass

    walk(image.get_layers())
    return out


def resolve_image(current, index):
    if index < 0:
        return current
    images = Gimp.get_images()
    return images[index] if 0 <= index < len(images) else current


def resolve_layer(image, name):
    layers = _all_layers(image)
    if not layers:
        return None
    if not name:
        return layers[0]
    for lay in layers:
        if lay.get_name() == name:
            return lay
    return layers[0]


def _pick(nick, r, g, b, a):
    """按通道取一个标量；luma 用和算子相同的系数"""
    if nick == "red":
        return r
    if nick == "green":
        return g
    if nick == "blue":
        return b
    if nick == "alpha":
        return a
    return _LUMA[0] * r + _LUMA[1] * g + _LUMA[2] * b


def _source(layer, ch):
    """通道选「图层蒙版」时改读蒙版 drawable，并按亮度取。

    GEGL 算子只认图层的 RGB/alpha，蒙版是 GIMP 侧的独立 drawable，只能在
    读图阶段就解析掉。
    A layer mask is a separate drawable that the op knows nothing about, so it
    has to be resolved while reading."""
    if ch == CH_MASK:
        try:
            mask = layer.get_mask()
            if mask is not None:
                return mask, "luma"
        except Exception:
            pass
        return layer, "luma"
    return layer, CHANNELS[ch][0]


def _canvas_buffer(drawable, w, h):
    """把图层按**画布坐标**铺进一块 w×h 的 GEGL 缓冲，界外补 0。

    算子按同一坐标读 input 和 aux，所以两块缓冲必须先对齐到画布：图层比画
    布小或带偏移时，直接把图层自己的 buffer 喂进去会整体错位。补 0 对应 PS
    把缺的那块当黑色。
    Fill a canvas-sized buffer from a drawable, padding with 0 outside. Both
    inputs must be in canvas coordinates: a smaller or offset layer would
    otherwise line up wrong. 0 matches Photoshop treating missing data as
    black."""
    buf = Gegl.Buffer.new(FMT, 0, 0, w, h)
    ox, oy = _offsets(drawable)
    dw, dh = _size(drawable)
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(w, ox + dw), min(h, oy + dh)
    if x1 > x0 and y1 > y0:
        data = drawable.get_buffer().get(
            Gegl.Rectangle.new(x0 - ox, y0 - oy, x1 - x0, y1 - y0),
            1.0, FMT, Gegl.AbyssPolicy.NONE)
        buf.set(Gegl.Rectangle.new(x0, y0, x1 - x0, y1 - y0), FMT, data)
    return buf


def _buf_floats(buf, w, h):
    vals = array.array('f')
    vals.frombytes(buf.get(Gegl.Rectangle.new(0, 0, w, h), 1.0, FMT,
                           Gegl.AbyssPolicy.NONE))
    return vals


def _write(drawable, rect, floats):
    """经 shadow buffer 写回，产生一条可撤销记录。

    rect 是**图层本地坐标**（通常 (0, 0, 宽, 高)）：shadow buffer 的 extent
    同样是 0,0,宽,高，不含图层偏移；传画布坐标会让带偏移的图层整体错位。
    rect is LAYER-LOCAL: the shadow buffer's extent carries no layer offset."""
    r = Gegl.Rectangle.new(rect[0], rect[1], rect[2], rect[3])
    shadow = drawable.get_shadow_buffer()
    shadow.set(r, FMT, floats.tobytes())
    shadow.flush()          # 不 flush 的话 merge_shadow 读到空 backend
    drawable.merge_shadow(True)
    drawable.update(rect[0], rect[1], rect[2], rect[3])


# ---- 核心：跑一趟算子 / one pass through the operation ---------------------

def _run(inb, auxb, w, h, ch1, inv1, ch2, inv2, blend, opacity,
         mask_on, mask_ch, inv_mask, out_mode):
    """搭一张三节点的小图，返回 w*h*4 的浮点结果。

    GEGL 算子拿不到选区/通道，反过来 Gimp.DrawableFilter 又拒绝带 aux 的算
    子，所以只能自己接 buffer-source → lb:calculations → blit_buffer。
    Three nodes: two buffer sources into the op, then blit the output out.
    Gimp.DrawableFilter refuses aux-padded effects, hence the hand-built
    graph."""
    _ensure_gegl()
    root = Gegl.Node.new()
    s1 = root.create_child("gegl:buffer-source")
    s2 = root.create_child("gegl:buffer-source")
    op = root.create_child(OP_NAME)

    s1.set_property("buffer", inb)
    s2.set_property("buffer", auxb)

    op.set_enum_as_string("source1-channel", ch1)
    op.set_enum_as_string("source2-channel", ch2)
    op.set_enum_as_string("blend-mode", blend)
    op.set_enum_as_string("output-mode", out_mode)
    if mask_on:
        op.set_enum_as_string("mask-channel", mask_ch)
    op.set_property("invert-source1", bool(inv1))
    op.set_property("invert-source2", bool(inv2))
    op.set_property("mask-enabled", bool(mask_on))
    op.set_property("invert-mask", bool(inv_mask))
    op.set_property("opacity", float(opacity))

    s1.connect_to("output", op, "input")
    s2.connect_to("output", op, "aux")

    out = Gegl.Buffer.new(FMT, 0, 0, w, h)
    op.blit_buffer(out, Gegl.Rectangle.new(0, 0, w, h), 0,
                   Gegl.AbyssPolicy.NONE)
    return _buf_floats(out, w, h)


def calculate(w, h, p):
    """p: dict(ch1, inv1, s1_layer, ch2, inv2, s2_layer, blend, opacity,
               use_mask, mask_layer, mch, inv_mask, result)

    返回 w*h*4 的灰度浮点数据（落成什么由 land() 决定）。"""
    _ensure_gegl()          # 必须先于任何 Gegl.Buffer.new
    if p['s1_layer'] is None or p['s2_layer'] is None:
        raise RuntimeError(_("Both sources need a layer"))

    d1, c1 = _source(p['s1_layer'], p['ch1'])
    d2, c2 = _source(p['s2_layer'], p['ch2'])
    inb = _canvas_buffer(d1, w, h)
    auxb = _canvas_buffer(d2, w, h)

    # 通道/选区要靠 alpha 值说话（GIMP 读哪个分量都成立），灰度层要 alpha=1
    out_mode = "mask-gray" if p['result'] == RES_GREY else "mask-alpha"

    # 遮罩恰好也取自源 2 的某个通道时，一条图就能算完（算子自带 mask 参数）
    inline = (p['use_mask'] and p['mask_layer'] is p['s2_layer']
              and p['mch'] != CH_MASK)

    if not p['use_mask'] or inline:
        return _run(inb, auxb, w, h, c1, p['inv1'], c2, p['inv2'], p['blend'],
                    p['opacity'], inline, CHANNELS[p['mch']][0],
                    p['inv_mask'], out_mode)

    # 遮罩来自第三张图：算两趟再线性插值。算式和算子里的一样
    #   out = v1 + (blended - v1) × mask × opacity
    # 两趟都带着源 2 的 alpha 覆盖率，而覆盖率是线性因子，插值后再乘等价。
    # Mask from a third image: two passes and a lerp, same formula as lb_mix.
    full = _run(inb, auxb, w, h, c1, p['inv1'], c2, p['inv2'], p['blend'],
                100.0, False, "luma", False, out_mode)
    base = _run(inb, auxb, w, h, c1, p['inv1'], c2, p['inv2'], p['blend'],
                0.0, False, "luma", False, out_mode)

    md, mc = _source(p['mask_layer'], p['mch'])
    mask = _buf_floats(_canvas_buffer(md, w, h), w, h)
    k0 = p['opacity'] / 100.0
    for i in range(w * h):
        j = i * 4
        k = _pick(mc, mask[j], mask[j + 1], mask[j + 2], mask[j + 3])
        if p['inv_mask']:
            k = 1.0 - k
        k *= k0
        for c in range(4):
            base[j + c] += (full[j + c] - base[j + c]) * k
    return base


# ---- 落地 / landing --------------------------------------------------------

def _new_channel(image, w, h, floats, name):
    """新建 Alpha 通道 / new alpha channel"""
    ch = Gimp.Channel.new(image, name, w, h, 100.0, Gegl.Color.new("black"))
    image.insert_channel(ch, None, -1)
    _write(ch, (0, 0, w, h), floats)
    return ch


def _new_grey_layer(image, w, h, floats, name):
    """新建灰度图层 / new grey layer"""
    lay = Gimp.Layer.new(image, name, w, h, Gimp.ImageType.RGBA_IMAGE, 100.0,
                         Gimp.LayerMode.NORMAL)
    lay.fill(Gimp.FillType.TRANSPARENT)
    image.insert_layer(lay, None, -1)
    _write(lay, (0, 0, w, h), floats)
    return lay


def _into_layer_alpha(drawable, grey, iw, ih):
    """把灰度乘进现用图层的 alpha / multiply the grey into layer alpha"""
    ox, oy = _offsets(drawable)
    dw, dh = _size(drawable)
    local = array.array('f')
    local.frombytes(drawable.get_buffer().get(
        Gegl.Rectangle.new(0, 0, dw, dh), 1.0, FMT, Gegl.AbyssPolicy.NONE))
    x0 = max(0, -ox)
    x1 = min(dw, iw - ox)
    for row in range(dh):
        cy = oy + row
        if cy < 0 or cy >= ih or x1 <= x0:
            continue
        for col in range(x0, x1):
            g = grey[(cy * iw + ox + col) * 4]
            local[(row * dw + col) * 4 + 3] *= g
    _write(drawable, (0, 0, dw, dh), local)


def land(image, drawable, grey, p):
    w, h = image.get_width(), image.get_height()
    result = p['result']
    if result == RES_SELECTION:
        ch = _new_channel(image, w, h, grey, _("Calculations"))
        image.select_item(Gimp.ChannelOps.REPLACE, ch)
        image.remove_channel(ch)
    elif result == RES_CHANNEL:
        _new_channel(image, w, h, grey, _("Calculations"))
    elif result == RES_GREY:
        _new_grey_layer(image, w, h, grey, _("Calculations"))
    else:
        _into_layer_alpha(drawable, grey, w, h)


def run_calculations(image, drawable, p):
    w, h = image.get_width(), image.get_height()
    grey = calculate(w, h, p)
    image.undo_group_start()
    try:
        land(image, drawable, grey, p)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()


# ---- 对话框 / dialogs -------------------------------------------------------

class _Picker:
    """图像 + 图层 + 通道 三联选择 / image, layer and channel pickers"""

    def __init__(self, grid, row, label, current_image):
        self.images = list(Gimp.get_images())
        if current_image not in self.images:
            self.images.insert(0, current_image)

        lbl = Gtk.Label.new(label)
        lbl.set_halign(Gtk.Align.START)
        grid.attach(lbl, 0, row, 1, 1)

        self.img_c = Gtk.ComboBoxText.new()
        for im in self.images:
            try:
                name = im.get_file().get_basename()
            except Exception:
                name = "image-%d" % im.get_id()
            self.img_c.append_text(name)
        self.img_c.set_active(0)
        self.img_c.connect('changed', self._on_image)
        grid.attach(self.img_c, 1, row, 1, 1)

        self.lay_c = Gtk.ComboBoxText.new()
        grid.attach(self.lay_c, 2, row, 1, 1)

        self.chan_c = Gtk.ComboBoxText.new()
        for _nick, lab in CHANNELS:
            self.chan_c.append_text(lab)
        self.chan_c.set_active(0)
        grid.attach(self.chan_c, 3, row, 1, 1)

        self._on_image(self.img_c)

    def _on_image(self, _combo):
        idx = self.img_c.get_active()
        self.layers = _all_layers(self.images[idx]) if idx >= 0 else []
        self.lay_c.get_model().clear()
        for lay in self.layers:
            self.lay_c.append_text(lay.get_name())
        self.lay_c.set_active(0 if self.layers else -1)

    def get(self):
        idx = self.img_c.get_active()
        image = self.images[idx] if idx >= 0 else None
        lidx = self.lay_c.get_active()
        layer = self.layers[lidx] if 0 <= lidx < len(self.layers) else None
        return image, layer, self.chan_c.get_active()


def _add_combo(grid, row, label, entries, default=0):
    lbl = Gtk.Label.new(label)
    lbl.set_halign(Gtk.Align.START)
    grid.attach(lbl, 0, row, 1, 1)
    c = Gtk.ComboBoxText.new()
    for _nick, lab in entries:
        c.append_text(lab)
    c.set_active(default)
    grid.attach(c, 1, row, 1, 1)
    return c


def _add_check(grid, row, label):
    chk = Gtk.CheckButton.new_with_label(label)
    chk.set_halign(Gtk.Align.START)
    grid.attach(chk, 1, row, 1, 1)
    return chk


def _add_spin(grid, row, label, lo, hi, val):
    lbl = Gtk.Label.new(label)
    lbl.set_halign(Gtk.Align.START)
    grid.attach(lbl, 0, row, 1, 1)
    adj = Gtk.Adjustment.new(val, lo, hi, 1.0, 10.0, 0.0)
    sp = Gtk.SpinButton.new(adj, 1.0, 0)
    grid.attach(sp, 1, row, 1, 1)
    return sp


def _build(grid):
    image = _CURRENT['image']
    r = 0
    s1 = _Picker(grid, r, _("Source 1"), image); r += 1
    i1 = _add_check(grid, r, _("Invert source 1")); r += 1
    s2 = _Picker(grid, r, _("Source 2"), image); r += 1
    i2 = _add_check(grid, r, _("Invert source 2")); r += 1
    bl = _add_combo(grid, r, _("Blending"), BLENDS, 2); r += 1
    op = _add_spin(grid, r, _("Opacity"), 0, 100, 100); r += 1
    use = _add_check(grid, r, _("Mask")); r += 1
    pick = _Picker(grid, r, _("Mask source"), image); r += 1
    inv = _add_check(grid, r, _("Invert mask")); r += 1
    res = _add_combo(grid, r, _("Result"), RESULTS); r += 1
    return (s1, i1, s2, i2, bl, op, use, pick, inv, res)


def _collect(w):
    s1, i1, s2, i2, bl, op, use, pick, inv, res = w
    _im1, lay1, c1 = s1.get()
    _im2, lay2, c2 = s2.get()
    _im3, mlay, mc = pick.get()
    return dict(ch1=c1, inv1=i1.get_active(), s1_layer=lay1,
                ch2=c2, inv2=i2.get_active(), s2_layer=lay2,
                blend=BLENDS[bl.get_active()][0], opacity=op.get_value(),
                use_mask=use.get_active(), mask_layer=mlay, mch=mc,
                inv_mask=inv.get_active(), result=res.get_active())


def _run_dialog(title):
    dlg = Gtk.Dialog.new()
    dlg.set_title(title)
    dlg.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
    ok = dlg.add_button(_("_OK"), Gtk.ResponseType.OK)
    ok.grab_default()
    box = dlg.get_content_area()
    box.set_border_width(10)
    grid = Gtk.Grid.new()
    grid.set_column_spacing(8)
    grid.set_row_spacing(6)
    box.add(grid)
    widgets = _build(grid)
    grid.show_all()
    resp = dlg.run()
    dlg.destroy()
    if resp != Gtk.ResponseType.OK:
        return None
    return _collect(widgets)


_CURRENT = {'image': None}


# ---- 插件类 / the plug-in ---------------------------------------------------

class CalcGegl(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-calc-gegl']

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(_("No image")))

        _CURRENT['image'] = image
        if run_mode == Gimp.RunMode.INTERACTIVE:
            params = _run_dialog(_("Calculations (GEGL)"))
            if params is None:
                return procedure.new_return_values(
                    Gimp.PDBStatusType.CANCEL, GLib.Error())
        else:
            i1 = resolve_image(image, config.get_property('source1-image'))
            l1 = resolve_layer(i1, config.get_property('source1-layer'))
            i2 = resolve_image(image, config.get_property('source2-image'))
            l2 = resolve_layer(i2, config.get_property('source2-layer'))
            im = resolve_image(image, config.get_property('mask-image'))
            ml = resolve_layer(im, config.get_property('mask-layer'))
            params = dict(
                ch1=config.get_property('source1-channel'),
                inv1=config.get_property('invert-source1'),
                s1_layer=l1,
                ch2=config.get_property('source2-channel'),
                inv2=config.get_property('invert-source2'),
                s2_layer=l2,
                blend=BLENDS[config.get_property('blend')][0],
                opacity=config.get_property('opacity'),
                use_mask=config.get_property('use-mask'),
                mask_layer=ml,
                mch=config.get_property('mask-channel'),
                inv_mask=config.get_property('invert-mask'),
                result=config.get_property('result'))

        Gimp.context_push()
        try:
            run_calculations(image, drawables[0], params)
            status, error = Gimp.PDBStatusType.SUCCESS, GLib.Error()
        except Exception as exc:
            Gimp.message("lb-calc-gegl: %s" % exc)
            status, error = Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc))
        Gimp.context_pop()
        return procedure.new_return_values(status, error)

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        procedure.set_documentation(
            _("PS Calculations, pixel math from lb:calculations: blend two "
              "channels into a selection, channel, grey layer or layer alpha"),
            _("Same result targets as Photoshop's Image > Calculations, but "
              "the pixels come from the GEGL operation."), name)
        procedure.set_menu_label(_("Calculations (GEGL)..."))
        procedure.add_menu_path("<Image>/Colors/SuperMrWang")

        for prefix, label in (("source1", _("Source 1")),
                              ("source2", _("Source 2"))):
            procedure.add_int_argument(
                "%s-channel" % prefix, _("%s channel") % label,
                _("0 Gray, 1 R, 2 G, 3 B, 4 Alpha, 5 mask"),
                0, 5, 0, GObject.ParamFlags.READWRITE)
            procedure.add_boolean_argument(
                "invert-%s" % prefix, _("Invert %s") % label,
                _("Invert this channel first"), False,
                GObject.ParamFlags.READWRITE)
            procedure.add_int_argument(
                "%s-image" % prefix, _("%s image") % label,
                _("-1 = this image"), -1, 1024, -1,
                GObject.ParamFlags.READWRITE)
            procedure.add_string_argument(
                "%s-layer" % prefix, _("%s layer") % label,
                _("Layer name; empty = first layer"), "",
                GObject.ParamFlags.READWRITE)
        procedure.add_int_argument("blend", _("Blend mode"),
                                   _("0 = Normal .. 25 = Luminosity (PS order)"),
                                   0, 25, 2, GObject.ParamFlags.READWRITE)
        procedure.add_double_argument("opacity", _("Opacity"),
                                      _("Blend strength"), 0.0, 100.0, 100.0,
                                      GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument("use-mask", _("Use mask"),
                                       _("Limit the effect with a mask"),
                                       False, GObject.ParamFlags.READWRITE)
        procedure.add_int_argument("mask-image", _("Mask image"),
                                   _("-1 = this image"),
                                   -1, 1024, -1, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument("mask-layer", _("Mask layer"),
                                      _("Layer name; empty = first layer"),
                                      "", GObject.ParamFlags.READWRITE)
        procedure.add_int_argument("mask-channel", _("Mask channel"),
                                   _("0 Gray .. 5 layer mask"),
                                   0, 5, 0, GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument("invert-mask", _("Invert mask"),
                                       _("Use the inverted mask"),
                                       False, GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "result", _("Result"),
            _("0 selection, 1 new channel, 2 grey layer, 3 layer alpha"),
            0, 3, 0, GObject.ParamFlags.READWRITE)
        return procedure


if __name__ == '__main__':
    Gimp.main(CalcGegl.__gtype__, sys.argv)
