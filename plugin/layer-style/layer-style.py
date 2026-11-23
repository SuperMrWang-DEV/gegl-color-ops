#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 图层样式（投影 / 发光 / 斜面 / 描边 / 叠加）—— GIMP 3 插件
 ---------------------------------------------------------------------------
 purpose   把 PS 的「图层 → 图层样式」搬过来：一块面板上十个效果，
           每个有自己的混合模式、颜色、角度、距离、大小、等高线，
           改一个参数预览立刻跟着动，确定后生成一组**可编辑的图层**。

           和 PS 的区别（先说清楚，免得以为坏了）：
             · GIMP 没有「样式挂在图层上」这回事，所以结果是一组真图层，
               放在一个叫「X (layer style)」的组里，原图层在组内居中：
               投影/外发光在它下面，内阴影/内发光/描边/叠加/斜面在它上面。
             · 再调参数就重跑一遍（旧的效果层会被替换，原图层不动）。
             · 没做：纹理、3D 材质、自定义等高线编辑、下一图层的混合颜色带。

 menu      SuperMrWang → Layer → 图层样式…

 usage     选一个像素图层 → 菜单 → 左边勾选效果 → 右边调参数 → 应用。

 note      四个非踩不可的：
           1. **像素参数在预览里要乘 k**。预览图是可缩放过的（长边 560），
              而「距离 5 px / 大小 8 px」是文档像素。不缩放的话预览里的投影
              比真正应用时大两倍，用户会以为确定以后「变小了」。
           2. **效果层的 offset 必须跟原图层一致**。图层可能只有画布的一小块，
              读出来的 RGBA 是图层局部坐标；新建的效果层不设 offset 就会贴到
              画布左上角，效果整个错位——看起来像「投影没跟着内容走」。
           3. **重跑时必须先把旧的效果层删掉**。只往上加的话，同一组里会堆出
              十套投影，而且旧层还带着旧参数，用户永远调不干净。
           4. **样式得自己记**。GIMP 没有「样式挂在图层上」，所以整份 JSON 要
              挂成寄生数据（parasite，跟着 XCF 存）。不记的话：再打开对话框
              只看到默认值，PS 那种「拷贝图层样式 → 粘到另一个图层」也就无从
              谈起。对话框底下那条「Style code」就是把这份 JSON 交给人复制。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os as _os
import sys as _sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject, Gegl

_here = _os.path.dirname(_os.path.abspath(__file__))
for _cand in (_os.path.join(_here, '_shared'),
              _os.path.normpath(_os.path.join(_here, '..', '_shared'))):
    if _os.path.isdir(_cand) and _cand not in _sys.path:
        _sys.path.append(_cand)

try:
    from lb_i18n import _          # noqa: F811
except Exception:                  # helper 不在：保持可用，只是不翻译
    def _(message):
        return GLib.dgettext(None, message)

import layer_style as LS                # noqa: E402
import mask_io as MI                    # noqa: E402

PROC = 'lb-plugin-layer-style'
GROUP_SUFFIX = " (layer style)"
# 预览长边。560 时 420×320 的图一次 render 约 60~100 ms，拖滑杆跟得上手。
PREVIEW_EDGE = 560


# ---- 从 GIMP 取渐变 / 图案 -------------------------------------------------

def _pick_colors(res):
    """GI 返回值里挖出 [Gimp.Color] / [[r,g,b]] 列表（各版本返回形状不一样）。"""
    if isinstance(res, (list, tuple)):
        if res and hasattr(res[0], "get_rgba"):
            return list(res)
        for part in res:
            got = _pick_colors(part)
            if got:
                return got
    return None


def gradient_stops(gradient=None, n=32):
    """当前渐变的色标表 [(pos, (r,g,b)), …]。取不到就 None。"""
    try:
        grad = gradient or Gimp.context_get_gradient()
    except Exception:
        return None
    if grad is None:
        return None
    colors = None
    for fname in ("get_uniform_samples", "get_samples"):
        fn = getattr(grad, fname, None)
        if fn is None:
            continue
        try:
            colors = _pick_colors(fn(n))
        except Exception:
            colors = None
        if colors:
            break
    if not colors:
        return None
    stops = []
    last = max(1, len(colors) - 1)
    for i, col in enumerate(colors):
        try:
            rgba = col.get_rgba()
            stops.append((i / float(last), (rgba[0], rgba[1], rgba[2])))
        except Exception:
            try:
                stops.append((i / float(last), (col[0], col[1], col[2])))
            except Exception:
                continue
    return stops or None


def pattern_unit(image, pattern=None, max_size=192):
    """把当前图案铺到临时图层上读回像素 → (ph, pw, 4) float 单元。"""
    try:
        pat = pattern or Gimp.context_get_pattern()
    except Exception:
        return None
    if pat is None:
        return None
    # GIMP 3 的 Gimp.Pattern 没有 get_width()，尺寸只能问 PDB：
    # gimp-pattern-get-info → (status, width, height, bpp)
    try:
        info = MI.pdb('gimp-pattern-get-info', pattern=pat)
        pw, ph = int(info.index(1)), int(info.index(2))
    except Exception:
        return None
    if pw < 1 or ph < 1:
        return None
    scale = min(1.0, float(max_size) / max(pw, ph))
    tw, th = max(1, int(round(pw * scale))), max(1, int(round(ph * scale)))
    tmp = Gimp.Layer.new(image, "lb-pattern", tw, th,
                         Gimp.ImageType.RGBA_IMAGE, 100.0,
                         Gimp.LayerMode.NORMAL)
    image.insert_layer(tmp, None, 0)
    try:
        try:
            Gimp.context_set_pattern(pat)
        except Exception:
            pass
        MI.pdb('gimp-drawable-edit-fill', drawable=tmp,
               **{"fill-type": int(Gimp.FillType.PATTERN)})
        if (tw, th) != (pw, ph):
            MI.pdb('gimp-layer-scale', layer=tmp, new_width=tw,
                   new_height=th, local_origin=False)
        raw = tmp.get_buffer().get(Gegl.Rectangle.new(0, 0, tw, th), 1.0,
                                   "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
        data = bytes(bytearray(raw))
    except Exception:
        return None
    finally:
        image.remove_layer(tmp)
    import numpy
    arr = numpy.frombuffer(data, dtype=numpy.uint8, count=tw * th * 4)
    return (arr.reshape(th, tw, 4).astype(numpy.float32) / 255.0)


def collect_assets(image, need_gradient=False, need_pattern=False):
    """把渐变采样 / 图案单元备好（没用到的不去碰 GIMP，省得拖慢）。"""
    assets = {}
    if need_gradient:
        stops = gradient_stops()
        if stops:
            assets["gradient"] = LS.gradient_lut(stops)
    if need_pattern:
        unit = pattern_unit(image)
        if unit is not None:
            assets["pattern"] = unit
    return assets


# ---- 写入 GIMP -------------------------------------------------------------

def _layer_mode(mode_id):
    """本地混合模式 id → Gimp.LayerMode。**优先 *_LEGACY**。

    GIMP 3 默认的模式在**线性光**里算（50% 的 204 叠在 51 上是 153 而不是
    128），PS 是在 sRGB 值上算的。layer_style.render 已经把混合算进颜色里，
    这里挂 NORMAL 也必须是 legacy 版，否则柔边和中间调整个发亮。
    """
    gid = LS.MODE_GIMP.get(mode_id or "normal") or "NORMAL"
    for name in (gid + "_LEGACY", gid, gid + "_MODE"):
        value = getattr(Gimp.LayerMode, name, None)
        if value is not None:
            return value
    return Gimp.LayerMode.NORMAL


def layer_offsets(item):
    """GIMP 3 的 get_offsets() 返回 (ok, x, y)，不是 (x, y)。

    直接拿下标 0/1 会得到 (True, 0) —— 于是每个效果层都被搬到 (1, 0)，
    整份样式斜着一像素，怎么看怎么"差一点"。
    """
    try:
        got = item.get_offsets()
    except Exception:
        return (0, 0)
    if isinstance(got, (tuple, list)):
        if len(got) >= 3 and isinstance(got[0], bool):
            return (int(got[1]), int(got[2]))
        if len(got) >= 2:
            return (int(got[0]), int(got[1]))
    return (0, 0)


def _write_layer(image, layer, w, h, data, offset, mode, opacity):
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", data)
    buf.flush()
    try:
        layer.set_offsets(int(offset[0]), int(offset[1]))
    except Exception:
        pass
    try:
        layer.set_mode(_layer_mode(mode))
    except Exception:
        pass
    try:
        layer.set_opacity(float(opacity) * 100.0)
    except Exception:
        pass


def _find_style_group(drawable):
    """原图层已经在某个「(layer style)」组里 → 返回那个组。"""
    try:
        parent = drawable.get_parent()
    except Exception:
        return None
    if parent is None or not parent.is_group():
        return None
    if (parent.get_name() or "").endswith(GROUP_SUFFIX):
        return parent
    return None


# ---- 样式跟着图层走：寄生数据 ---------------------------------------------
# GIMP 没有「样式挂在图层上」这回事，但 XCF 能存任意寄生数据（parasite）。
# 把整份样式 JSON 挂到组和原图层上，于是：
#   · 关掉 GIMP 再打开，点这个图层的图层样式，看到的是上次那一套，不是默认值；
#   · 「复制到别的图层」真正可用 —— 不然打开对话框只有默认参数，复制的
#     永远是默认样式，等于没做。
STYLE_PARASITE = "supermrwang-layer-style"

# Gimp.Parasite.new 的 flags 是整数：1 = PERSISTENT，2 = UNDOABLE。
# PERSISTENT 才会跟着 XCF 一起存，少这一位就是「关了 GIMP 就丢」。
_PARASITE_FLAGS = 1 | 2


def _read_style_code(item):
    """从图层/组上读回样式代码字符串；没有就 None。"""
    if item is None:
        return None
    try:
        par = Gimp.Item.get_parasite(item, STYLE_PARASITE)
    except Exception:
        return None
    if par is None:
        return None
    try:
        return bytes(par.get_data()).decode("utf-8", "replace")
    except Exception:
        return None


def remember_style(item, style):
    """把样式写成寄生数据。返回是否成功（失败不影响出图，所以不抛）。"""
    if item is None:
        return False
    try:
        code = LS.format_style(style).encode("utf-8")
        Gimp.Item.attach_parasite(
            item, Gimp.Parasite.new(STYLE_PARASITE, _PARASITE_FLAGS, code))
        return True
    except Exception:
        return False


def recover_style(drawable):
    """这个图层上一次用的样式：先看它自己，再看它所在的样式组。

    返回 style dict 或 None。代码坏掉就当没有（不能因为一段残留数据
    让「打开对话框」整个失败）。
    """
    cands = [drawable]
    group = _find_style_group(drawable)
    if group is not None:
        cands.insert(0, group)
    try:
        parent = drawable.get_parent()
        if parent is not None and parent not in cands:
            cands.append(parent)
    except Exception:
        pass
    for item in cands:
        code = _read_style_code(item)
        if not code:
            continue
        try:
            st, _warn = LS.read_style_code(code)
        except LS.StyleCodeError:
            continue
        return st
    return None


def apply_style(image, drawable, style, assets=None):
    """渲染样式并写成图层组。返回 info 字典。"""
    if not LS.have_numpy():
        LS._need_numpy()
    w, h = drawable.get_width(), drawable.get_height()
    t0 = time.time()
    _pw, _ph, rgba = MI.read_drawable_rgba(drawable, max(w, h))
    if (_pw, _ph) != (w, h):
        raise RuntimeError(_("Read the layer at the wrong size: %d×%d, "
                             "expected %d×%d") % (_pw, _ph, w, h))
    if assets is None:
        assets = collect_assets(image)
    plan = LS.render_bytes(rgba, w, h, style, assets,
                           progress=Gimp.progress_pulse)
    if not plan["layers"]:
        raise RuntimeError(_("No effect is turned on — tick at least one on "
                             "the left before applying."))

    offset = layer_offsets(drawable)

    try:
        image.undo_group_start()
    except Exception:
        pass
    try:
        group = _find_style_group(drawable)
        if group is not None:
            # 重跑：组里除原图层以外全删掉（旧效果层带着旧参数，
            # 留着的话用户永远调不干净）
            for child in list(group.get_children()):
                if child is not drawable:
                    image.remove_layer(child)
        else:
            parent = drawable.get_parent()
            try:
                pos = image.get_item_position(drawable)
            except Exception:
                pos = 0
            group = Gimp.GroupLayer.new(
                image, (drawable.get_name() or "") + GROUP_SUFFIX)
            image.insert_layer(group, parent, pos)
            image.reorder_item(drawable, group, 0)

        below = [l for l in plan["layers"] if l["role"] == "below"]
        above = [l for l in plan["layers"] if l["role"] == "above"]
        made = []
        # 位置参数是「从组顶数」。below 逐个插到原图层**正下方**，
        # above 插到原图层**正上方**：后插的在上面，正好等于渲染顺序。
        for lyr in below:
            node = Gimp.Layer.new(image, lyr["name"], w, h,
                                  Gimp.ImageType.RGBA_IMAGE, 100.0,
                                  Gimp.LayerMode.NORMAL)
            at = image.get_item_position(drawable) + 1
            image.insert_layer(node, group, at)
            _write_layer(image, node, w, h, lyr["bytes"], offset,
                         lyr["mode"], lyr["opacity"])
            made.append(node)
        for lyr in above:
            node = Gimp.Layer.new(image, lyr["name"], w, h,
                                  Gimp.ImageType.RGBA_IMAGE, 100.0,
                                  Gimp.LayerMode.NORMAL)
            # 插到组顶：后插的在上面，正好等于渲染顺序（内阴影先、斜面最后）
            image.insert_layer(node, group, 0)
            _write_layer(image, node, w, h, lyr["bytes"], offset,
                         lyr["mode"], lyr["opacity"])
            made.append(node)

        # 样式存到组和原图层上（跟着 XCF 走）：再点这个图层就是上次那一套，
        # 「复制样式到别的图层」也才有东西可复制。放在 undo 组里，
        # 于是「撤销」会连样式一起退回去，不会留下对不上的参数。
        remember_style(group, style)
        remember_style(drawable, style)
    finally:
        try:
            image.undo_group_end()
        except Exception:
            pass

    info = LS.summary(plan)
    info.update({"seconds": time.time() - t0, "size": (w, h),
                 "group": group,
                 "effects": [n for n in LS.enabled_effects(style)]})
    return info


# ---- 对话框 ----------------------------------------------------------------

def _fmt_size(w, h):
    return "%d×%d" % (w, h)


def _spec_info(item):
    kind = item[1]
    info = {"key": item[0], "kind": kind, "default": item[2]}
    if kind == "choice":
        info["options"] = item[3]
        info["label"] = item[4]
    else:
        info["lo"], info["hi"] = item[3], item[4]
        info["label"] = item[5]
    return info


def _checker(cr, w, h, size=10):
    cr.set_source_rgb(0.82, 0.82, 0.82)
    cr.paint()
    cr.set_source_rgb(0.70, 0.70, 0.70)
    y = 0
    row = 0
    while y < h:
        x = 0 if row % 2 == 0 else size
        while x < w:
            cr.rectangle(x, y, min(size, w - x), min(size, h - y))
            x += size * 2
        y += size
        row += 1
    cr.fill()


def _pixbuf(rgba, w, h):
    from gi.repository import GdkPixbuf
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(bytes(rgba)), GdkPixbuf.Colorspace.RGB, True, 8,
        w, h, w * 4)


def build_dialog(config, image, drawable, w, h):
    """建出对话框，返回 (dlg, ctx)。**故意不 run()**：无头回归可以直接调
    ctx["render"]() / ctx["set"]() 验证「改了参数预览真的变了」。"""
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk

    style = LS.parse_style(config.get_property('style') or "")
    pw, ph, prgba = MI.read_drawable_rgba(drawable, PREVIEW_EDGE)
    k = float(w) / max(pw, 1)

    dlg = Gtk.Dialog.new()
    dlg.set_title(_("Layer Style"))
    dlg.set_default_size(1080, 720)
    dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dlg.add_button(_("Apply"), Gtk.ResponseType.OK)
    try:
        dlg.set_response_sensitive(Gtk.ResponseType.OK, True)
    except Exception:
        pass

    outer = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
    outer.set_border_width(8)
    dlg.get_content_area().pack_start(outer, True, True, 0)

    body = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
    outer.pack_start(body, True, True, 0)

    # ---- 左：效果列表
    left = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
    left.set_size_request(196, -1)
    body.pack_start(left, False, False, 0)
    left.pack_start(Gtk.Label.new(_("Effects")), False, False, 0)
    listbox = Gtk.ListBox.new()
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    scroll = Gtk.ScrolledWindow.new(None, None)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.add(listbox)
    left.pack_start(scroll, True, True, 0)

    # ---- 中：预览
    mid = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
    body.pack_start(mid, True, True, 0)
    area = Gtk.DrawingArea.new()
    area.set_size_request(420, 340)
    mid.pack_start(area, True, True, 0)
    note = Gtk.Label.new("")
    note.set_xalign(0.0)
    note.set_line_wrap(True)
    mid.pack_start(note, False, False, 0)

    # ---- 右：参数
    right = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
    right.set_size_request(330, -1)
    body.pack_start(right, False, False, 0)
    stack = Gtk.Stack.new()
    stack.set_transition_type(Gtk.StackTransitionType.NONE)
    rscroll = Gtk.ScrolledWindow.new(None, None)
    rscroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    rscroll.add(stack)
    right.pack_start(rscroll, True, True, 0)

    ctx = {"style": style, "k": k, "assets": {}, "pixbuf": None,
           "id": 0, "page": "blend", "preview_w": pw, "preview_h": ph,
           "preview_rgba": prgba, "controls": {}, "drawable": drawable,
           "quiet": False}

    # ---- 样式代码：复制到另一个图层 / 从代码粘回来 ------------------------
    # GIMP 里样式不是图层的一个属性，PS 那种「右键 → 拷贝图层样式」没有对应
    # 的宿主功能，所以跨图层复制就靠这一份 JSON：复制出去，到另一个图层的
    # 对话框里粘回来。同一份字符串也正是 PDB 的 style 参数，脚本能直接回放。
    exp = Gtk.Expander.new(_("Style code — copy this style to another layer"))
    outer.pack_start(exp, False, False, 0)
    cwrap = Gtk.Box.new(Gtk.Orientation.VERTICAL, 4)
    cwrap.set_border_width(6)
    exp.add(cwrap)

    cbar = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 6)
    cwrap.pack_start(cbar, False, False, 0)
    b_copy = Gtk.Button.new_with_label(_("Copy code"))
    b_paste = Gtk.Button.new_with_label(_("Paste and load"))
    b_load = Gtk.Button.new_with_label(_("Load this code"))
    for _b in (b_copy, b_paste, b_load):
        cbar.pack_start(_b, False, False, 0)
    chint = Gtk.Label.new(_("Sizes are document pixels — pasting onto a "
                            "different-sized layer keeps them as they are."))
    chint.set_xalign(0.0)
    chint.set_line_wrap(True)
    cbar.pack_start(chint, True, True, 0)

    tview = Gtk.TextView.new()
    tview.set_monospace(True)
    tview.set_wrap_mode(Gtk.WrapMode.CHAR)
    buf = tview.get_buffer()
    cscroll = Gtk.ScrolledWindow.new(None, None)
    cscroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    cscroll.set_size_request(-1, 104)
    cscroll.add(tview)
    cwrap.pack_start(cscroll, False, False, 0)

    cstate = Gtk.Label.new("")
    cstate.set_xalign(0.0)
    cstate.set_line_wrap(True)
    cwrap.pack_start(cstate, False, False, 0)

    cflag = {"sync": False, "edited": False}

    def say(msg):
        cstate.set_text(msg)

    def code_text():
        return LS.pretty_style(ctx["style"])

    def box_text():
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

    def set_code(text):
        # set_text 会触发 "changed"：用 sync 标记区分「程序写的」和「人手改的」，
        # 否则每次预览刷新都会被当成用户编辑，自动同步就再也不生效了
        cflag["sync"] = True
        buf.set_text(text)
        cflag["sync"] = False
        cflag["edited"] = False

    def on_code_changed(_b):
        if cflag["sync"]:
            return
        cflag["edited"] = True
        say(_("Edited — press “Load this code” to use these values."))

    def sync_widgets():
        """把 ctx["style"] 的当前值写回所有控件（粘贴之后要看得见）。"""
        ctx["quiet"] = True
        try:
            for name, store in ctx["controls"].items():
                specs = LS.BLEND_SPECS if name == "blend" else LS.SPECS[name]
                src = (ctx["style"]["blend"] if name == "blend"
                       else ctx["style"]["effects"][name])
                for item in specs:
                    info = _spec_info(item)
                    key = info["key"]
                    if key in store:
                        _set_widget(Gtk, info["kind"], store[key],
                                    src.get(key, info["default"]))
            for name, row in rowmap.items():
                if name == "blend":
                    continue
                child = row.get_child()
                if child is not None and hasattr(child, "set_active"):
                    child.set_active(
                        bool(ctx["style"]["effects"][name].get("enabled")))
        finally:
            ctx["quiet"] = False

    def load_code(text=None):
        txt = box_text() if text is None else text
        try:
            st, warns = LS.read_style_code(txt)
        except LS.StyleCodeError as exc:
            say(_("That is not a style code: %s") % exc)
            return False
        LS.adopt_style(ctx["style"], st)
        sync_widgets()
        set_code(code_text())
        changed()
        msg = _("Loaded — %d effect(s) on.")
        msg = msg % len(LS.enabled_effects(ctx["style"]))
        if warns:
            msg += " " + "; ".join(warns[:3])
            if len(warns) > 3:
                msg += " …"
        say(msg)
        return True

    def copy_code(_b=None):
        # 用户手动改过就以框里为准：他改的可能正是想带走的那一版
        text = box_text() if cflag["edited"] else code_text()
        if text != box_text():
            set_code(text)
        try:
            from gi.repository import Gdk
            clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clip.set_text(text, -1)
            clip.store()
            say(_("Copied %d characters. Open the other layer's dialog, "
                  "paste into this box and press “Load this code”.")
                % len(text))
        except Exception as exc:
            # 没有剪贴板（无头、Wayland 没起来）也别让人复制不了：
            # 全选交给 Ctrl+C
            buf.select_range(buf.get_start_iter(), buf.get_end_iter())
            say(_("The clipboard refused (%s); the code is selected — "
                  "press Ctrl+C.") % exc)
        return text

    def on_paste(_b=None):
        try:
            from gi.repository import Gdk
            text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        except Exception as exc:
            say(_("Could not read the clipboard: %s") % exc)
            return False
        if not text or not text.strip():
            say(_("The clipboard is empty."))
            return False
        set_code(text)
        return load_code(text)

    b_copy.connect("clicked", copy_code)
    b_paste.connect("clicked", on_paste)
    b_load.connect("clicked", lambda _b: load_code())
    buf.connect("changed", on_code_changed)

    def need_assets():
        want = set()
        for name in LS.enabled_effects(ctx["style"]):
            eff = ctx["style"]["effects"][name]
            if name == "gradient-overlay":
                want.add("gradient")
            elif name == "pattern-overlay":
                want.add("pattern")
            elif name == "stroke":
                if eff.get("fill") == "gradient":
                    want.add("gradient")
                elif eff.get("fill") == "pattern":
                    want.add("pattern")
            if eff.get("gradient"):
                want.add("gradient")
        missing = want - set(ctx["assets"])
        if missing:
            got = collect_assets(image, "gradient" in missing,
                                 "pattern" in missing)
            for key in list(missing):
                ctx["assets"].setdefault(key, got.get(key))

    def render():
        try:
            need_assets()
            scaled = LS.scale_style(ctx["style"], k)
            plan = LS.render(prgba, pw, ph, scaled, ctx["assets"])
            out = LS.preview(plan, pw, ph)
            ctx["pixbuf"] = _pixbuf(LS.to_bytes(out), pw, ph)
            st = LS.style_stats(ctx["style"])
            note.set_text(_("%d effect(s) on · preview %s (full size %s)")
                          % (st["enabled"], _fmt_size(pw, ph),
                             _fmt_size(w, h)))
        except Exception as exc:
            ctx["pixbuf"] = None
            note.set_text("layer-style: %s" % exc)
        area.queue_draw()

    def schedule(delay=90):
        if ctx["id"]:
            GLib.source_remove(ctx["id"])
        ctx["id"] = GLib.timeout_add(delay, _tick)

    def _tick():
        ctx["id"] = 0
        render()
        return False

    def changed():
        schedule()
        # 代码框跟着参数走；用户手动改过就先别覆盖（他可能正要粘出去）
        if not cflag["edited"]:
            set_code(code_text())

    # ---- 控件生成
    def add_page(name, specs, values, title):
        page = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
        page.set_border_width(6)
        head = Gtk.Label.new()
        head.set_markup("<b>%s</b>" % GLib.markup_escape_text(title))
        head.set_xalign(0.0)
        page.pack_start(head, False, False, 0)
        grid = Gtk.Grid.new()
        grid.set_row_spacing(4)
        grid.set_column_spacing(8)
        page.pack_start(grid, False, False, 0)
        store = {}
        for row, item in enumerate(specs):
            info = _spec_info(item)
            key, kind = info["key"], info["kind"]
            label = Gtk.Label.new(_(info["label"]))
            label.set_xalign(0.0)
            grid.attach(label, 0, row, 1, 1)
            widget = _build_widget(Gtk, info, values.get(key, info["default"]))
            widget.set_hexpand(True)
            grid.attach(widget, 1, row, 1, 1)
            store[key] = widget

            def on_change(_w, key=key, kind=kind):
                if ctx["quiet"]:            # 载入代码时在批量写控件，别回头改数据
                    return
                values[key] = _read_widget(Gtk, kind, store[key])
                ctx["style"]["effects"].setdefault(name, {})
                ctx["style"]["effects"][name][key] = values[key]
                changed()

            _connect(Gtk, kind, widget, on_change)
        stack.add_named(page, name)
        ctx["controls"][name] = store

    # 混合选项页（作用于原图层，不是效果层）
    blend_page = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
    blend_page.set_border_width(6)
    bhead = Gtk.Label.new()
    bhead.set_markup("<b>%s</b>" % GLib.markup_escape_text(
        _("Blend Options")))
    bhead.set_xalign(0.0)
    blend_page.pack_start(bhead, False, False, 0)
    bgrid = Gtk.Grid.new()
    bgrid.set_row_spacing(4)
    bgrid.set_column_spacing(8)
    blend_page.pack_start(bgrid, False, False, 0)
    bstore = {}
    for row, item in enumerate(LS.BLEND_SPECS):
        info = _spec_info(item)
        key, kind = info["key"], info["kind"]
        lbl = Gtk.Label.new(_(info["label"]))
        lbl.set_xalign(0.0)
        bgrid.attach(lbl, 0, row, 1, 1)
        widget = _build_widget(Gtk, info, ctx["style"]["blend"].get(
            key, info["default"]))
        widget.set_hexpand(True)
        bgrid.attach(widget, 1, row, 1, 1)
        bstore[key] = widget

        def on_blend(_w, key=key, kind=kind):
            if ctx["quiet"]:
                return
            ctx["style"]["blend"][key] = _read_widget(Gtk, kind, bstore[key])
            changed()

        _connect(Gtk, kind, widget, on_blend)
    stack.add_named(blend_page, "blend")
    ctx["controls"]["blend"] = bstore

    for name in LS.PANEL_ORDER:
        add_page(name, LS.SPECS[name], ctx["style"]["effects"][name],
                 LS.EFFECT_LABEL[name])

    # ---- 列表行
    rowmap = {}
    blend_row = Gtk.ListBoxRow.new()
    bc = Gtk.CheckButton.new_with_label(_("Blend Options"))
    bc.set_active(True)
    bc.set_inconsistent(False)
    blend_row.add(bc)
    listbox.add(blend_row)
    rowmap["blend"] = blend_row

    def on_toggle(btn, name):
        if ctx["quiet"]:
            return
        ctx["style"]["effects"][name]["enabled"] = bool(btn.get_active())
        changed()

    for name in LS.PANEL_ORDER:
        row = Gtk.ListBoxRow.new()
        cb = Gtk.CheckButton.new_with_label(_(LS.EFFECT_LABEL[name]))
        cb.set_active(bool(ctx["style"]["effects"][name].get("enabled")))
        cb.connect("toggled", on_toggle, name)
        row.add(cb)
        listbox.add(row)
        rowmap[name] = row

    def on_row(_lb, row):
        if row is None:
            return
        for name, r in rowmap.items():
            if r is row:
                ctx["page"] = name
                stack.set_visible_child_name(name)
                return

    listbox.connect("row-selected", on_row)

    def draw(_area, cr):
        aw = area.get_allocated_width()
        ah = area.get_allocated_height()
        _checker(cr, aw, ah)
        pb = ctx["pixbuf"]
        if pb is None:
            return False
        pw_, ph_ = pb.get_width(), pb.get_height()
        sc = min(1.0, float(aw) / max(1, pw_), float(ah) / max(1, ph_))
        dx = (aw - pw_ * sc) * 0.5
        dy = (ah - ph_ * sc) * 0.5
        cr.save()
        cr.translate(dx, dy)
        cr.scale(sc, sc)
        from gi.repository import Gdk
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.paint()
        cr.restore()
        return False

    area.connect("draw", draw)
    ctx["render"] = render
    ctx["schedule"] = schedule
    ctx["set_page"] = lambda name: (listbox.select_row(rowmap[name]))
    ctx["values"] = lambda: ctx["style"]
    ctx["on_toggle"] = on_toggle
    ctx["rowmap"] = rowmap
    ctx["changed"] = changed
    ctx["style_code"] = code_text
    ctx["load_code"] = load_code
    ctx["copy_code"] = copy_code
    ctx["code_box"] = tview
    ctx["box_text"] = box_text
    ctx["code_panel"] = cwrap
    listbox.select_row(blend_row)
    render()
    outer.show_all()
    # show_all 会把折叠面板里的东西也 show 出来（set_expanded(False) 对已经
    # 处于折叠状态的 expander 会直接 early-return，光靠它收不起来），
    # 所以显式把面板 hide 掉：默认不占高度，点标题才展开。
    exp.set_expanded(False)
    cwrap.hide()
    set_code(code_text())
    return dlg, ctx


def _build_widget(Gtk, info, value):
    kind = info["kind"]
    if kind == "bool":
        w = Gtk.CheckButton.new()
        w.set_active(bool(value))
        return w
    if kind == "color":
        from gi.repository import Gdk
        w = Gtk.ColorButton.new()
        col = Gdk.RGBA()
        try:
            col.red, col.green, col.blue, col.alpha = (
                float(value[0]), float(value[1]), float(value[2]), 1.0)
        except Exception:
            col.red, col.green, col.blue, col.alpha = 0.0, 0.0, 0.0, 1.0
        w.set_rgba(col)
        return w
    if kind == "choice":
        w = Gtk.ComboBoxText.new()
        opts = info.get("options") or ()
        ids = []
        for opt in opts:
            if isinstance(opt, (tuple, list)):
                oid, olabel = opt[0], opt[1]
            else:
                oid, olabel = opt, opt
            w.append(oid, _(olabel))
            ids.append(oid)
        w.set_active_id(str(value))
        if w.get_active_id() is None and ids:
            w.set_active_id(ids[0])
        return w
    adj = Gtk.Adjustment.new(
        float(value if value is not None else info["default"]),
        float(info["lo"] if info["lo"] is not None else 0),
        float(info["hi"] if info["hi"] is not None else 100),
        1.0, 10.0, 0.0)
    w = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, adj)
    w.set_draw_value(True)
    w.set_value_pos(Gtk.PositionType.RIGHT)
    w.set_digits(0 if kind in ("percent", "int") else 1)
    w.set_size_request(150, -1)
    return w


def _read_widget(Gtk, kind, widget):
    if kind == "bool":
        return bool(widget.get_active())
    if kind == "color":
        c = widget.get_rgba()
        return [float(c.red), float(c.green), float(c.blue)]
    if kind == "choice":
        return widget.get_active_id()
    v = float(widget.get_value())
    if kind in ("percent", "int"):
        return int(round(v))
    return round(v, 2)


def _set_widget(Gtk, kind, widget, value):
    """把值写回控件（粘贴代码之后用）。写不进去就保持原样，不抛。"""
    if kind == "bool":
        widget.set_active(bool(value))
        return
    if kind == "color":
        from gi.repository import Gdk
        col = Gdk.RGBA()
        try:
            col.red, col.green, col.blue = (
                float(value[0]), float(value[1]), float(value[2]))
        except Exception:
            col.red = col.green = col.blue = 0.0
        col.alpha = 1.0
        widget.set_rgba(col)
        return
    if kind == "choice":
        # set_active_id 对着不存在的 id 会返回 False 并保持原样
        widget.set_active_id(str(value))
        return
    try:
        widget.set_value(float(value))
    except Exception:
        pass


def _connect(Gtk, kind, widget, cb):
    if kind == "bool":
        widget.connect("toggled", cb)
    elif kind == "color":
        widget.connect("color-set", cb)
    elif kind == "choice":
        widget.connect("changed", cb)
    else:
        widget.connect("value-changed", cb)


def show_dialog(procedure, config, image, drawable, w, h):
    """弹窗。True = 应用（样式已写回 config）。"""
    try:
        dlg, ctx = build_dialog(config, image, drawable, w, h)
        from gi.repository import Gtk
    except Exception as exc:
        Gimp.message(_("This build of GIMP has no GTK — nothing to click on. "
                       "(%s). Pass the style through the style argument "
                       "instead (a JSON string).") % exc)
        return False

    resp = dlg.run()
    if ctx["id"]:
        GLib.source_remove(ctx["id"])
    if resp != Gtk.ResponseType.OK:
        dlg.destroy()
        return False
    config.set_property("style", LS.format_style(ctx["style"]))
    dlg.destroy()
    return True


# ---- 过程注册 --------------------------------------------------------------

def check_drawable(drawable):
    if drawable is None:
        raise RuntimeError(_("Nothing is selected. Pick a pixel layer first."))
    if not drawable.is_layer():
        raise RuntimeError(_("That is not a layer. Select a pixel layer."))
    if drawable.is_group():
        raise RuntimeError(_(
            "That is a layer group. Pick a single layer inside it — a group "
            "has no pixels to draw a style from."))
    if drawable.get_width() < 2 or drawable.get_height() < 2:
        raise RuntimeError(_("The layer is %d×%d — too small for a style.")
                           % (drawable.get_width(), drawable.get_height()))


class LayerStylePlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label(_("Layer Style…"))
        procedure.set_documentation(
            _("Drop shadow, glows, bevel, satin, overlays and stroke — as a "
              "group of editable layers, with live preview"),
            _("Photoshop's layer styles: drop shadow, inner shadow, outer and "
              "inner glow, bevel and emboss (five styles), satin, colour / "
              "gradient / pattern overlay and stroke. Each one has its own "
              "blend mode, colour, angle, distance, size and contour. The "
              "result is a layer group holding the original layer plus one "
              "layer per effect, so nothing is baked into the pixels."),
            name)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")
        procedure.add_string_argument(
            "style", _("Style"),
            _("The whole style as a JSON string. The dialog's \"Style code\" "
              "box holds exactly this string — copy it from one layer and "
              "paste it into another layer's box (or pass it here from a "
              "script) to get the same style. Leave empty to use whatever "
              "style that layer was last given (it is stored in the XCF), or "
              "the defaults with the drop shadow on for a fresh layer."),
            "", GObject.ParamFlags.READWRITE)
        procedure.add_menu_path("<Image>/SuperMrWang/Layer")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        drawable = drawables[0]
        try:
            check_drawable(drawable)
            # 没有显式给样式 → 读回这个图层上次用的那一套（存在寄生数据里）。
            # 少了这一步，「复制样式到别的图层」打开对话框只会看到默认值，
            # 复制的永远不是原来那份 —— 功能表面上有，实际没用。
            if not (config.get_property('style') or "").strip():
                found = recover_style(drawable)
                if found is not None:
                    config.set_property('style', LS.format_style(found))
            if run_mode == Gimp.RunMode.INTERACTIVE:
                if not show_dialog(procedure, config, image, drawable,
                                   drawable.get_width(),
                                   drawable.get_height()):
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.CANCEL, None)
            style = LS.parse_style(config.get_property('style') or "")
            info = apply_style(image, drawable, style)
            Gimp.message(_("Layer style: %d layer(s) in \"%s\" · %s · %.1f s")
                         % (info["layers"], info["group"].get_name(),
                            _fmt_size(info["size"][0], info["size"][1]),
                            info["seconds"]))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("layer-style: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(LayerStylePlugin.__gtype__, _sys.argv)
