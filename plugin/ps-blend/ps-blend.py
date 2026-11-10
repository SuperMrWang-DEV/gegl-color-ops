#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · PS 应用图像 / 计算 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   复刻 Photoshop「图像 → 应用图像」与「图像 → 计算」的完整工作流：
           源可以是任意打开图像的任意图层/通道，遮罩可指向第三张图，计算
           的结果可以直接变成选区或新建 Alpha 通道——这些是 GEGL 算子
           （lb:apply-image / lb:calculations）做不了的部分。
           Pixel math lives in psblend.py（优先 psblend_core.dll 加速，公式
           与 GEGL 算子共用 common/blend.h，两边结果一致）。
 menu      颜色 → SuperMrWang → Apply Image PS / Calculations PS
 usage     交互模式弹自定义对话框；批处理用注册的参数（见 do_create_procedure）。
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import array
import os
import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject, Gio, Gegl
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import psblend


def _N_(message):
    return message


def _(message):
    return GLib.dgettext(None, message)


# ---- 通用小件 / small helpers ----------------------------------------------

def _offsets(drawable):
    """图层/蒙版的画布偏移 / drawable offsets in canvas coordinates"""
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
    """index<0 = 当前图像，否则取打开图像列表的第 index 张"""
    if index < 0:
        return current
    images = Gimp.get_images()
    return images[index] if 0 <= index < len(images) else current


def resolve_layer(image, name):
    """按名字找图层；空名取第一层 / find a layer by name, empty = first"""
    layers = _all_layers(image)
    if not layers:
        return None
    if not name:
        return layers[0]
    for lay in layers:
        if lay.get_name() == name:
            return lay
    return layers[0]


def source_drawable(layer, channel):
    """通道 = 图层蒙版时返回蒙版 drawable / the mask channel reads the mask"""
    if channel == psblend.CH_MASK:
        try:
            mask = layer.get_mask()
            if mask is not None:
                return mask, psblend.CH_GRAY
        except Exception:
            pass
    return layer, channel


def read_rgba(drawable, rect):
    """读一块 RGBA 浮点数据；rect 为画布坐标 (x, y, w, h)，界外补 0。

    Reads RGBA floats for a canvas-coordinate rect; out-of-bounds reads 0,
    mirroring Photoshop pressing missing data as black. """
    x, y, w, h = rect
    out = array.array('f', bytes(w * h * 16))
    ox, oy = _offsets(drawable)
    dw, dh = _size(drawable)
    lx, ly = x - ox, y - oy                    # drawable 本地坐标 / local coords
    x0, y0 = max(lx, 0), max(ly, 0)
    x1, y1 = min(lx + w, dw), min(ly + h, dh)
    if x1 <= x0 or y1 <= y0:
        return out

    r = Gegl.Rectangle.new(x0, y0, x1 - x0, y1 - y0)
    data = drawable.get_buffer().get(r, 1.0, "R'G'B'A float",
                                     Gegl.AbyssPolicy.BLACK)
    src = array.array('f')
    src.frombytes(data)
    sw = x1 - x0

    # 逐行拷进全幅缓冲 / blit row by row into the full-size buffer
    dst_stride = w * 4
    src_stride = sw * 4
    for row in range(y1 - y0):
        d0 = ((y0 - ly + row) * dst_stride + (x0 - lx) * 4)
        s0 = row * src_stride
        out[d0:d0 + src_stride] = src[s0:s0 + src_stride]
    return out


def write_rgba(drawable, rect, floats):
    """把结果经 shadow buffer 写回，产生一条可撤销的记录"""
    r = Gegl.Rectangle.new(rect[0], rect[1], rect[2], rect[3])
    shadow = drawable.get_shadow_buffer()
    shadow.set(r, "R'G'B'A float", floats.tobytes())
    # 不 flush 的话 merge_shadow 读到的还是空 backend（GIMP 3 的坑）
    # Without flush, merge_shadow still sees an empty backend (GIMP 3 trap)
    shadow.flush()
    drawable.merge_shadow(True)
    drawable.update(rect[0], rect[1], rect[2], rect[3])


def new_grey_layer(image, rect, floats, name):
    """新建一个灰度图层承载蒙版结果 / put a mask result on a new layer"""
    lay = Gimp.Layer.new(image, name, rect[2], rect[3],
                         Gimp.ImageType.RGBA_IMAGE, 100.0,
                         Gimp.LayerMode.NORMAL)
    lay.set_offsets(rect[0], rect[1])
    lay.fill(Gimp.FillType.TRANSPARENT)
    image.insert_layer(lay, None, -1)
    write_rgba(lay, (0, 0, rect[2], rect[3]), floats)
    return lay


def grey_to_channel(image, rect, floats, name):
    """把灰度结果放进一个 Alpha 通道 / store a grey result in a channel"""
    color = Gegl.Color.new("black")
    # 通道/选区按画布对齐（画布原点恒为 0,0），与 PS 一致
    # Channels align to the canvas, whose origin is always 0,0, like PS
    ch = Gimp.Channel.new(image, name, rect[2], rect[3], 100.0, color)
    image.insert_channel(ch, None, -1)
    write_rgba(ch, (0, 0, rect[2], rect[3]), floats)
    return ch


# ---- 应用图像执行 / Apply Image engine --------------------------------------

def run_apply_image(image, drawable, p):
    """p: dict(blend, opacity, tch, sch, src_layer, use_mask, mask_layer,
               mch, inv_mask, keep_transp, result)"""
    ox, oy = _offsets(drawable)
    w, h = drawable.get_width(), drawable.get_height()
    rect = (ox, oy, w, h)                    # 画布坐标 / canvas coords

    src = p['src_layer']
    if src is None:
        raise RuntimeError(_("No source layer"))

    sdrawable, sch = source_drawable(src, p['sch'])
    inb = read_rgba(drawable, (0, 0, w, h))
    aux = read_rgba(sdrawable, rect)
    mdrawable = mch = None
    if p['use_mask']:
        mdrawable, mch = source_drawable(p['mask_layer'], p['mch'])
        mask = read_rgba(mdrawable, rect)
    else:
        mask = None

    out = psblend.apply_image(inb, aux, mask, w * h,
                              p['blend'], p['tch'], sch,
                              p['opacity'] / 100.0,
                              1 if p['use_mask'] else 0,
                              1 if p['inv_mask'] else 0,
                              1 if p['keep_transp'] else 0,
                              1 if p['result'] == 1 else 0)

    image.undo_group_start()
    if p['result'] == 0:
        write_rgba(drawable, (0, 0, w, h), out)
    else:
        new_grey_layer(image, rect, out, _("Apply Image"))
    image.undo_group_end()
    Gimp.displays_flush()


# ---- 计算执行 / Calculations engine -----------------------------------------

def run_calculations(image, drawable, p):
    """p: dict(ch1, inv1, s1_layer, ch2, inv2, s2_layer, blend, opacity,
               use_mask, mask_layer, mch, inv_mask, result)"""
    iw, ih = image.get_width(), image.get_height()
    rect = (0, 0, iw, ih)                    # 通道/选区按画布对齐，与 PS 一致

    d1, c1 = source_drawable(p['s1_layer'], p['ch1'])
    d2, c2 = source_drawable(p['s2_layer'], p['ch2'])
    b1 = read_rgba(d1, rect)
    b2 = read_rgba(d2, rect)
    if p['use_mask']:
        md, mc = source_drawable(p['mask_layer'], p['mch'])
        mask = read_rgba(md, rect)
    else:
        mask = None

    grey = psblend.calculations(b1, b2, mask, iw * ih,
                                c1, 1 if p['inv1'] else 0,
                                c2, 1 if p['inv2'] else 0,
                                p['blend'], p['opacity'] / 100.0,
                                1 if p['use_mask'] else 0,
                                1 if p['inv_mask'] else 0)

    image.undo_group_start()
    result = p['result']
    if result == 0:                          # 选区 / selection
        ch = grey_to_channel(image, rect, grey, _("Calculations"))
        image.select_item(Gimp.ChannelOps.REPLACE, ch)
        image.remove_channel(ch)
    elif result == 1:                        # 新建 Alpha 通道 / new channel
        grey_to_channel(image, rect, grey, _("Calculations"))
    elif result == 2:                        # 新建灰度图层 / grey layer
        new_grey_layer(image, rect, grey, _("Calculations"))
    else:                                    # 写入图层 alpha / into layer alpha
        n = iw * ih
        for i in range(n):
            grey[i * 4 + 0] = b1[i * 4 + 0]
            grey[i * 4 + 1] = b1[i * 4 + 1]
            grey[i * 4 + 2] = b1[i * 4 + 2]
            grey[i * 4 + 3] = b1[i * 4 + 3] * grey[i * 4 + 3]
        write_rgba(drawable, rect, grey)
    image.undo_group_end()
    Gimp.displays_flush()


# ---- 对话框 / dialogs -------------------------------------------------------

class _Picker:
    """图像 + 图层 + 通道 三联选择 / image, layer and channel pickers"""

    def __init__(self, grid, row, label, current_image, channels_with_mask):
        self.images = list(Gimp.get_images())
        if current_image not in self.images:
            self.images.insert(0, current_image)
        self.channels = list(channels_with_mask)

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
        for _nick, lab in self.channels:
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


def _add_check(grid, row, label, col=1):
    chk = Gtk.CheckButton.new_with_label(label)
    grid.attach(chk, col, row, 1, 1)
    return chk


def _add_spin(grid, row, label, lo, hi, val):
    lbl = Gtk.Label.new(label)
    lbl.set_halign(Gtk.Align.START)
    grid.attach(lbl, 0, row, 1, 1)
    adj = Gtk.Adjustment.new(val, lo, hi, 1.0, 10.0, 0.0)
    sp = Gtk.SpinButton.new(adj, 1.0, 0)
    grid.attach(sp, 1, row, 1, 1)
    return sp


def _mask_widgets(grid, row, title, current_image):
    use = _add_check(grid, row, title)
    use.set_halign(Gtk.Align.START)
    pick = _Picker(grid, row + 1, _("Mask source"), current_image,
                   psblend.CHANNELS)
    invert = _add_check(grid, row + 2, _("Invert mask"))
    invert.set_halign(Gtk.Align.START)
    return use, pick, invert


def _run_dialog(title, build, collect):
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
    widgets = build(grid)
    grid.show_all()
    resp = dlg.run()
    dlg.destroy()
    if resp != Gtk.ResponseType.OK:
        return None
    return collect(widgets)


# ---- 插件类 / the plug-in ---------------------------------------------------

class PsBlend(Gimp.PlugIn):

    # -- Apply Image --

    def _ai_build(self, grid):
        image = self._image
        ch = [c for c in psblend.CHANNELS]           # 含图层蒙版选项
        tgt = [("rgb", _("RGB")), ("red", _("Red")), ("green", _("Green")),
               ("blue", _("Blue")), ("alpha", _("Alpha"))]

        r = 0
        src = _Picker(grid, r, _("Source"), image, ch); r += 1
        tc = _add_combo(grid, r, _("Target"), tgt); r += 1
        bl = _add_combo(grid, r, _("Blending"),
                        [(n, l) for n, l in psblend.BLENDS], 2); r += 1
        op = _add_spin(grid, r, _("Opacity"), 0, 100, 100); r += 1
        kt = _add_check(grid, r, _("Preserve transparency")); r += 1
        kt.set_halign(Gtk.Align.START)
        use, pick, inv = _mask_widgets(grid, r, _("Mask"), image); r += 4
        res = _add_combo(grid, r, _("Result"),
                         [(n, _(l)) for n, l in psblend.APPLY_RESULTS]); r += 1
        return (src, tc, bl, op, kt, use, pick, inv, res)

    def _ai_collect(self, w):
        src, tc, bl, op, kt, use, pick, inv, res = w
        _img, layer, sch = pick.get()
        return dict(blend=bl.get_active(), opacity=op.get_value(),
                    tch=tc.get_active(), sch=sch, src_layer=layer,
                    use_mask=use.get_active(), mask_layer=pick.get()[1],
                    mch=pick.get()[2], inv_mask=inv.get_active(),
                    keep_transp=kt.get_active(), result=res.get_active())

    # -- Calculations --

    def _calc_build(self, grid):
        image = self._image
        ch = [c for c in psblend.CHANNELS]
        results = [(n, _(l)) for n, l in psblend.CALC_RESULTS]

        r = 0
        s1 = _Picker(grid, r, _("Source 1"), image, ch); r += 1
        i1 = _add_check(grid, r, _("Invert source 1")); r += 1
        i1.set_halign(Gtk.Align.START)
        s2 = _Picker(grid, r, _("Source 2"), image, ch); r += 1
        i2 = _add_check(grid, r, _("Invert source 2")); r += 1
        i2.set_halign(Gtk.Align.START)
        bl = _add_combo(grid, r, _("Blending"),
                        [(n, l) for n, l in psblend.BLENDS], 2); r += 1
        op = _add_spin(grid, r, _("Opacity"), 0, 100, 100); r += 1
        use, pick, inv = _mask_widgets(grid, r, _("Mask"), image); r += 4
        res = _add_combo(grid, r, _("Result"), results); r += 1
        return (s1, i1, s2, i2, bl, op, use, pick, inv, res)

    def _calc_collect(self, w):
        s1, i1, s2, i2, bl, op, use, pick, inv, res = w
        _img, lay1, c1 = s1.get()
        _img2, lay2, c2 = s2.get()
        return dict(ch1=c1, inv1=i1.get_active(), s1_layer=lay1,
                    ch2=c2, inv2=i2.get_active(), s2_layer=lay2,
                    blend=bl.get_active(), opacity=op.get_value(),
                    use_mask=use.get_active(), mask_layer=pick.get()[1],
                    mch=pick.get()[2], inv_mask=inv.get_active(),
                    result=res.get_active())

    # -- 通用 run / common run --

    def _run_common(self, procedure, run_mode, image, drawable, config,
                    interactive_build, interactive_collect, engine,
                    noninteractive_params):
        if image is None:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(_("No image")))

        self._image = image
        params = None
        if run_mode == Gimp.RunMode.INTERACTIVE:
            params = _run_dialog(procedure.get_name(),
                                 interactive_build, interactive_collect)
            if params is None:
                return procedure.new_return_values(
                    Gimp.PDBStatusType.CANCEL, GLib.Error())
        else:
            params = noninteractive_params(config)

        Gimp.context_push()
        try:
            engine(image, drawable, params)
            status = Gimp.PDBStatusType.SUCCESS
            error = GLib.Error()
        except Exception as exc:             # 出错就报，不留半截结果
            Gimp.message("ps-blend: %s" % exc)
            status = Gimp.PDBStatusType.EXECUTION_ERROR
            error = GLib.Error(str(exc))
        Gimp.context_pop()
        return procedure.new_return_values(status, error)

    # -- procedures --

    def apply_image_run(self, procedure, run_mode, image, drawables, config,
                        data):
        def noninteractive(cfg):
            simg = resolve_image(image, cfg.get_property('source-image'))
            slay = resolve_layer(simg, cfg.get_property('source-layer'))
            mimg = resolve_image(image, cfg.get_property('mask-image'))
            mlay = resolve_layer(mimg, cfg.get_property('mask-layer'))
            return dict(blend=cfg.get_property('blend'),
                        opacity=cfg.get_property('opacity'),
                        tch=cfg.get_property('target-channel'),
                        sch=cfg.get_property('source-channel'),
                        src_layer=slay,
                        use_mask=cfg.get_property('use-mask'),
                        mask_layer=mlay,
                        mch=cfg.get_property('mask-channel'),
                        inv_mask=cfg.get_property('invert-mask'),
                        keep_transp=cfg.get_property('preserve-transparency'),
                        result=cfg.get_property('result'))

        return self._run_common(procedure, run_mode, image, drawables[0],
                                config, self._ai_build, self._ai_collect,
                                run_apply_image, noninteractive)

    def calculations_run(self, procedure, run_mode, image, drawables, config,
                         data):
        def noninteractive(cfg):
            i1 = resolve_image(image, cfg.get_property('source1-image'))
            l1 = resolve_layer(i1, cfg.get_property('source1-layer'))
            i2 = resolve_image(image, cfg.get_property('source2-image'))
            l2 = resolve_layer(i2, cfg.get_property('source2-layer'))
            mimg = resolve_image(image, cfg.get_property('mask-image'))
            mlay = resolve_layer(mimg, cfg.get_property('mask-layer'))
            return dict(ch1=cfg.get_property('source1-channel'),
                        inv1=cfg.get_property('invert-source1'),
                        s1_layer=l1,
                        ch2=cfg.get_property('source2-channel'),
                        inv2=cfg.get_property('invert-source2'),
                        s2_layer=l2,
                        blend=cfg.get_property('blend'),
                        opacity=cfg.get_property('opacity'),
                        use_mask=cfg.get_property('use-mask'),
                        mask_layer=mlay,
                        mch=cfg.get_property('mask-channel'),
                        inv_mask=cfg.get_property('invert-mask'),
                        result=cfg.get_property('result'))

        return self._run_common(procedure, run_mode, image, drawables[0],
                                config, self._calc_build, self._calc_collect,
                                run_calculations, noninteractive)

    # -- boilerplate --

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-apply-image', 'lb-plugin-calculations']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN,
            self.apply_image_run if name.endswith('apply-image')
            else self.calculations_run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        if name.endswith('apply-image'):
            procedure.set_documentation(
                _("PS Apply Image: blend a layer from any open image onto "
                  "this one, per channel, with mask and opacity"),
                _("Replicates Photoshop Image > Apply Image."), name)
            procedure.set_menu_label(_("Apply Image PS..."))
            procedure.add_menu_path("<Image>/Colors/SuperMrWang")

            procedure.add_int_argument("blend", _("Blend mode"),
                                       _("0 = Normal .. 25 = Luminosity (PS order)"),
                                       0, 25, 2, GObject.ParamFlags.READWRITE)
            procedure.add_double_argument("opacity", _("Opacity"),
                                          _("Blend strength"), 0.0, 100.0, 100.0,
                                          GObject.ParamFlags.READWRITE)
            procedure.add_int_argument("target-channel", _("Target channel"),
                                       _("0 RGB, 1 R, 2 G, 3 B, 4 Alpha"),
                                       0, 4, 0, GObject.ParamFlags.READWRITE)
            procedure.add_int_argument("source-channel", _("Source channel"),
                                       _("0 Gray, 1 R, 2 G, 3 B, 4 Alpha, 5 mask"),
                                       0, 5, 0, GObject.ParamFlags.READWRITE)
            procedure.add_int_argument("source-image", _("Source image"),
                                       _("-1 = this image, else index of open images"),
                                       -1, 1024, -1, GObject.ParamFlags.READWRITE)
            procedure.add_string_argument("source-layer", _("Source layer"),
                                          _("Layer name; empty = first layer"),
                                          "", GObject.ParamFlags.READWRITE)
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
            procedure.add_boolean_argument("preserve-transparency",
                                           _("Preserve transparency"),
                                           _("Leave transparent pixels alone"),
                                           False, GObject.ParamFlags.READWRITE)
            procedure.add_int_argument("result", _("Result"),
                                       _("0 composite, 1 new grey layer"),
                                       0, 1, 0, GObject.ParamFlags.READWRITE)
        else:
            procedure.set_documentation(
                _("PS Calculations: blend two channels from any open image "
                  "into a selection, channel, grey layer or layer alpha"),
                _("Replicates Photoshop Image > Calculations."), name)
            procedure.set_menu_label(_("Calculations PS..."))
            procedure.add_menu_path("<Image>/Colors/SuperMrWang")

            # Source 1 / Source 2 各一套：通道、反相、图像、图层
            # Source 1 / Source 2 each get channel, invert, image and layer
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
    Gimp.main(PsBlend.__gtype__, sys.argv)
