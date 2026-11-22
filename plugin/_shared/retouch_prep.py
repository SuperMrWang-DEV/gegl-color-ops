#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 磨皮预修的 GIMP 胶水层
 ---------------------------------------------------------------------------
 干什么   三个「AI 预修」磨皮插件共用这一套：读图层像素 → 弄一张「参考图」
          （AI 整图低重绘，或本地降采样模糊）→ 在 512 长边的工作尺寸上算
          参考与原图的亮度差 → 交给 retouch_math 出蒙版/灰层。

 为什么参考图要缩到 512 再算   蒙版和灰层都是低频的东西，512 上算完再放大
           回去，边缘反而更顺；而在 4000×6000 上跑盒式模糊，Python 要几十秒。
           AI 那一路也一样：底模本来就只吃 512/1024，喂大了它也是缩。

 两条路怎么选   插件参数里的 source：
             "ai"    → ComfyUI 整图重绘（denoise 默认 0.35），语义上知道
                       「这是皮肤」，痘印和眼睛下方阴影不会一视同仁；
             "local" → 降采样再放大当低通参考，毫秒级、零依赖。
           "ai" 连不上 ComfyUI 时自动退回 local，并把原因写进 notes——不静默，
           也不让一次点击变成报错弹窗。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

import ai_client
import retouch_math as rm

try:
    from lb_i18n import _
except Exception:                       # helper 不在：保持可用，只是不翻译
    def _(message):
        return message

try:
    import prompt_tools
except Exception:
    prompt_tools = None


# 工作尺寸的长边。512 足够描述「哪块皮肤该提亮」这类低频信息，放大回去也不糊。
WORK_MAX = 512

# 预修用的默认提示词。要英文：SD 的文本编码器只认英文。
# 关键词是「clean / even / natural」而不是「beautiful / flawless」——后者会把
# 皮肤推向塑料感，磨皮插件要的是能继续加工的底子。
DEFAULT_PROMPT = ("clean natural skin, even tone, smooth texture, fine pores, "
                  "keep facial features and expression, photorealistic, sharp focus")
DEFAULT_NEGATIVE = ("blemishes, acne, blotches, plastic skin, waxy, over-smoothed, "
                    "blurry, deformed, watermark, text")


# ---- PDB 小工具 -------------------------------------------------------------

def _pdb(name, **props):
    """按名调用 PDB 过程，状态不是 SUCCESS 就抛。

    proc.run() 不抛异常，失败只写在返回值第 0 位——不看就静默失败。
    """
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    status = res.index(0)
    if status != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if len(res) > 1 else None
        raise RuntimeError("%s: %s" % (name, getattr(err, "message", err)))
    return res


# ---- 像素读写 ---------------------------------------------------------------

def layer_pixels(layer):
    """整层像素，RGBA 8 位紧排（0,0 起算，与图层自身的局部坐标一致）。"""
    w, h = layer.get_width(), layer.get_height()
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                 "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    data = bytes(bytearray(raw))
    if len(data) != w * h * 4:
        raise RuntimeError(_("Could not read the layer: expected %d bytes, got %d")
                           % (w * h * 4, len(data)))
    return w, h, data


def write_layer_pixels(layer, data):
    """把一整层 RGBA 写回图层（尺寸必须一致）。"""
    w, h = layer.get_width(), layer.get_height()
    if len(data) != w * h * 4:
        raise RuntimeError(_("Pixel buffer size does not match the layer"))
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", data)
    buf.flush()
    layer.update(0, 0, w, h)


def write_mask_pixels(mask, w, h, data):
    """把 8 位灰度写进图层蒙版。

    蒙版通道的格式随 GIMP 版本可能是 Y u8 或 R'G'B'A u8，先试单通道，
    失败再把同一份灰度铺成 RGB——蒙版只看亮度，铺开结果一样。
    """
    if len(data) != w * h:
        raise RuntimeError(_("Mask buffer size does not match the layer"))
    buf = mask.get_buffer()
    rect = Gegl.Rectangle.new(0, 0, w, h)
    try:
        buf.set(rect, "Y u8", bytes(data))
    except Exception:
        rgba = bytearray(w * h * 4)
        rgba[0::4] = data
        rgba[1::4] = data
        rgba[2::4] = data
        rgba[3::4] = b"\xff" * (w * h)
        buf.set(rect, "R'G'B'A u8", bytes(rgba))
    buf.flush()
    try:
        mask.update(0, 0, w, h)
    except Exception:
        pass


def read_selection(image, ox, oy, w, h):
    """按图层位置读当前选区；没有选区返回 None。"""
    try:
        sel = image.get_selection()
        if sel is None:
            return None
        # bounds() 返回 (has_selection_object, non_empty, x1, y1, x2, y2)：
        # 没有选区时第一项仍然是 True、第二项才是 False。只看第一项会把
        # 「没选区」当成「全选」，读出来一片黑，delta 立刻变成 0——所有预修
        # 静默失效（2026-11-22 就是这么踩的）。
        ok, non_empty, _x1, _y1, _x2, _y2 = sel.bounds(image)
        if not ok or not non_empty:
            return None
    except Exception:
        return None
    raw = sel.get_buffer().get(Gegl.Rectangle.new(ox, oy, w, h), 1.0,
                               "Y u8", Gegl.AbyssPolicy.NONE)
    data = bytes(bytearray(raw))
    if len(data) != w * h:
        return None
    return data


# ---- 缩放（借用 GIMP 的重采样，而不是 Python 逐像素插值） -------------------

def scale_rgba(data, w, h, nw, nh):
    if (w, h) == (nw, nh):
        return data
    tmp = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    try:
        layer = Gimp.Layer.new(tmp, "lb-prep-scale", w, h,
                               Gimp.ImageType.RGBA_IMAGE, 100.0,
                               Gimp.LayerMode.NORMAL)
        tmp.insert_layer(layer, None, 0)
        shadow = layer.get_shadow_buffer()
        shadow.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", data)
        shadow.flush()
        layer.merge_shadow(True)
        # PDB 的参数名是连字符（new-width）；写 new_width 只报 Calling error
        _pdb('gimp-layer-scale', layer=layer,
             **{'new-width': int(nw), 'new-height': int(nh),
                'local-origin': False})
        return layer_pixels(layer)[2]
    finally:
        tmp.delete()


def scale_gray(data, w, h, nw, nh):
    if (w, h) == (nw, nh):
        return bytes(data)
    rgba = bytearray(w * h * 4)
    rgba[0::4] = data
    rgba[1::4] = data
    rgba[2::4] = data
    rgba[3::4] = b"\xff" * (w * h)
    out = scale_rgba(bytes(rgba), w, h, nw, nh)
    return bytes(out[0::4])


def work_size(w, h, longest=WORK_MAX):
    """整层 → 工作尺寸（保持长宽比，长边不超过 longest）。"""
    long_edge = max(w, h)
    if long_edge <= longest:
        return w, h
    f = float(longest) / long_edge
    return max(1, int(round(w * f))), max(1, int(round(h * f)))


# ---- 参考图 -----------------------------------------------------------------

def local_reference(data, w, h, radius=8.0):
    """降采样再放大 = 低通参考，毫秒级。

    这比真跑一遍高斯更贴近「拉向邻域平均」这件事本身：降采样的分辨率就是
    radius 对应的截止频率，放大用的是 GIMP 的 NoHalo，不会出块。
    """
    factor = max(2, int(round(max(2.0, float(radius)))))
    sw, sh = max(1, w // factor), max(1, h // factor)
    if (sw, sh) == (w, h):
        return data
    small = scale_rgba(data, w, h, sw, sh)
    return scale_rgba(small, sw, sh, w, h)


def resolve_prompt(prompt):
    """中文提示词 → 英文；翻不动的部分丢掉，空了就用默认值。"""
    text = (prompt or "").strip()
    if not text:
        return DEFAULT_PROMPT
    if prompt_tools is not None:
        try:
            en, _unknown = prompt_tools.to_english(text, strict=False)
            if en:
                return en
        except Exception:
            pass
    # 没词表或整句翻不出来：只有纯 ASCII 才敢直接送下去
    try:
        text.encode("ascii")
        return text
    except Exception:
        return DEFAULT_PROMPT


def ai_reference(data, w, h, server="", checkpoint="", prompt="",
                 negative="", steps=25, cfg=7.5, seed=-1, denoise=0.35,
                 timeout=600.0, client=None, on_tick=None):
    """把整层交给 ComfyUI 低重绘一遍，返回与图层同尺寸的 RGBA。

    client 参数是给回归脚本塞 mock 用的；正常留空，按 server 现建一个。
    """
    t0 = time.time()
    cli = client or ai_client.ComfyClient(server)
    ckpt = checkpoint or cli.first_checkpoint()
    target = ai_client.family_target(ckpt)
    scale = ai_client.work_scale(w, h, target)
    sw = max(8, int(round(w * scale)) // ai_client.SIZE_ALIGN * ai_client.SIZE_ALIGN)
    sh = max(8, int(round(h * scale)) // ai_client.SIZE_ALIGN * ai_client.SIZE_ALIGN)

    small = scale_rgba(data, w, h, sw, sh)
    src_png = ai_client.encode_png(sw, sh, small, channels=4)
    blob, info = ai_client.img2img(
        cli, src_png, resolve_prompt(prompt), negative=negative or DEFAULT_NEGATIVE,
        checkpoint=ckpt, steps=steps, cfg=cfg,
        seed=ai_client.random_seed() if seed is None or seed < 0 else seed,
        denoise=denoise, timeout=timeout, on_tick=on_tick,
        prefix="lb-retouch-ref")

    dw, dh, dch, dpix = ai_client.decode_png(blob)
    if dch == 4:
        rgba = bytes(dpix)
    else:
        out = bytearray(dw * dh * 4)
        out[0::4] = bytes(dpix[0::3])
        out[1::4] = bytes(dpix[1::3])
        out[2::4] = bytes(dpix[2::3])
        out[3::4] = b"\xff" * (dw * dh)
        rgba = bytes(out)
    if (dw, dh) != (w, h):
        rgba = scale_rgba(rgba, dw, dh, w, h)

    info = dict(info)
    info.update(seconds=round(time.time() - t0, 2), checkpoint=ckpt,
                work=(sw, sh), denoise=denoise)
    return rgba, info


# ---- 图层搭建小工具 ---------------------------------------------------------
# 这三支插件搭出来的结构必须和原版插件一模一样（组 / 混合模式 / 滤镜参数），
# 只是内容换成了参考图。共用的部分放这里，三份插件才不会各自漂。

def new_group(image, name, parent, position):
    host = Gimp.GroupLayer.new(image, name)
    host.set_mode(Gimp.LayerMode.PASS_THROUGH)
    image.insert_layer(host, parent, position)
    return host


def force_opaque(layer):
    """alpha 拉满：分组显隐只由组蒙版负责，避免混合模式按半透明插值。"""
    filt = Gimp.DrawableFilter.new(layer, "gimp:curves", _("0 · alpha"))
    cfg = filt.get_config()
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.SMOOTH)
    for x in (0.0, 128 / 255.0, 1.0):
        curve.add_point(x, 1.0)
    cfg.set_property("curve", curve)
    cfg.set_property("channel", Gimp.HistogramChannel.ALPHA)
    cfg.set_property("trc", Gimp.TRCType.LINEAR)
    filt.update()
    layer.append_filter(filt)
    return filt


def append_blur(layer, radius, label=None):
    filt = Gimp.DrawableFilter.new(layer, "gegl:gaussian-blur",
                                   label or _("Gaussian blur (low frequency)"))
    cfg = filt.get_config()
    cfg.set_property("std-dev-x", float(radius))
    cfg.set_property("std-dev-y", float(radius))
    filt.update()
    layer.append_filter(filt)
    return filt


def append_highpass(layer, radius, label=None):
    filt = Gimp.DrawableFilter.new(layer, "gegl:high-pass",
                                   label or _("High pass (high frequency)"))
    cfg = filt.get_config()
    cfg.set_property("std-dev", float(radius))
    # contrast 是「差值放大倍数的一半」，2 才输出完整的 (原图 − 模糊)
    cfg.set_property("contrast", 2.0)
    filt.update()
    layer.append_filter(filt)
    return filt


# 五个控制点：三点的样条画提亮/压暗那条抛物线会差 2.6 码，五点是 0.6 码。
CURVE_STEPS = (0.0, 64 / 255.0, 128 / 255.0, 192 / 255.0, 1.0)


def curve_fn(amount, sign):
    """x + sign·d·4x(1−x)：两端不动，中间鼓起/凹下。"""
    def fn(x):
        return min(1.0, max(0.0, x + sign * amount * 4.0 * x * (1.0 - x)))
    return fn


def append_curve(layer, label, fn):
    filt = Gimp.DrawableFilter.new(layer, "gimp:curves", label)
    cfg = filt.get_config()
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.SMOOTH)
    for x in CURVE_STEPS:
        curve.add_point(x, fn(x))
    cfg.set_property("curve", curve)
    cfg.set_property("channel", Gimp.HistogramChannel.VALUE)
    cfg.set_property("trc", Gimp.TRCType.NON_LINEAR)
    filt.update()
    layer.append_filter(filt)
    return filt


def link_alpha_mask(image, base, host):
    """原图层的 alpha → 整组的蒙版（组内各层保持不透明）。"""
    if host is None:
        return False
    try:
        if not base.has_alpha():
            return False
    except Exception:
        return False

    saved = None
    try:
        if not Gimp.Selection.is_empty(image):
            saved = Gimp.Selection.save(image)
    except Exception:
        saved = None

    try:
        image.select_item(Gimp.ChannelOps.REPLACE, base)
        mask = host.create_mask(Gimp.AddMaskType.SELECTION)
        if mask is None:
            return False
        host.add_mask(mask)
        return True
    except Exception:
        return False
    finally:
        try:
            if saved is not None:
                image.select_item(Gimp.ChannelOps.REPLACE, saved)
                image.remove_channel(saved)
            else:
                Gimp.Selection.none(image)
        except Exception:
            pass


def layer_from_pixels(image, name, w, h, data, parent, position, mode=None,
                      opaque=False):
    """按像素新建一层。opaque=True 时把 alpha 拉满——原图带透明通道时必须这样，
    否则混合模式会按半透明插值，边缘一圈颜色会和原图对不上。"""
    lay = Gimp.Layer.new(image, name, w, h, Gimp.ImageType.RGBA_IMAGE, 100.0,
                         mode or Gimp.LayerMode.NORMAL)
    image.insert_layer(lay, parent, position)
    write_layer_pixels(lay, data)
    if opaque:
        force_opaque(lay)
    return lay


def item_position(image, item, fallback=0):
    try:
        proc = Gimp.get_pdb().lookup_procedure('gimp-image-get-item-position')
        cfg = proc.create_config()
        cfg.set_property('image', image)
        cfg.set_property('item', item)
        return proc.run(cfg).index(1)
    except Exception:
        return fallback


def summarize(prep, extra=""):
    """给 Gimp.message 的一句话：这次用的是哪条路、花了多久。"""
    used = prep.get("source")
    if used == "ai":
        info = prep.get("info") or {}
        head = _("AI reference from ComfyUI (%s, denoise %s, %s s)") % (
            info.get("checkpoint", "?"), info.get("denoise", "?"),
            info.get("seconds", "?"))
    else:
        head = _("Local reference (no ComfyUI)")
    if prep.get("fallback"):
        head += _("\nComfyUI was not reachable, so the local reference was used instead: %s") % prep["fallback"]
    if "selection" in (prep.get("notes") or []):
        head += _("\nOnly the selection was pre-worked; everything outside it is untouched.")
    return head + ("\n" + extra if extra else "")


# ---- 一次准备好的全部材料 ---------------------------------------------------

def prepare(image, base, source="ai", radius=8.0, denoise=0.35, prompt="",
            negative="", server="", checkpoint="", steps=25, cfg=7.5, seed=-1,
            timeout=600.0, use_selection=True, client=None, on_tick=None):
    """读像素 → 参考图 → 工作尺寸上的亮度差。

    返回的 dict 里，三个插件各取所需：
        ref       整层尺寸的参考图 RGBA（高低频拿它当新的「原图」）
        base_luma 工作尺寸上的原图亮度
        delta     ref − base 的亮度差（正数该提亮，负数该压暗）
        notes     给用户看的说明（AI 退回本地、选区生效等）
    """
    w, h, data = layer_pixels(base)
    try:
        ok, ox, oy = base.get_offsets()
        if not ok:
            ox = oy = 0
    except Exception:
        ox, oy = 0, 0

    notes = []
    info = None
    fallback = ""
    used = source if source in ("ai", "local") else "local"

    if used == "ai":
        try:
            ref, info = ai_reference(data, w, h, server=server,
                                     checkpoint=checkpoint, prompt=prompt,
                                     negative=negative, steps=steps, cfg=cfg,
                                     seed=seed, denoise=denoise,
                                     timeout=timeout, client=client,
                                     on_tick=on_tick)
            notes.append("ai")
        except Exception as exc:
            used = "local"
            fallback = str(exc).split("\n")[0][:200]
            notes.append("fallback")
            ref = local_reference(data, w, h, radius)
    else:
        ref = local_reference(data, w, h, radius)
        notes.append("local")

    # 选区：参考图整层混合一次，选区外 alpha=0 就等于没改
    sel = read_selection(image, ox, oy, w, h) if use_selection else None
    if sel is not None:
        ref = rm.blend_rgba(data, ref, rm.alpha_from_gray(sel))
        notes.append("selection")

    ww, wh = work_size(w, h)
    if (ww, wh) != (w, h):
        base_small = scale_rgba(data, w, h, ww, wh)
        ref_small = scale_rgba(ref, w, h, ww, wh)
    else:
        base_small, ref_small = data, ref

    base_luma = rm.luma(base_small)
    delta = rm.diff(rm.luma(ref_small), base_luma)
    # 模糊差值：痘印是高频，参考图与它在像素上对不齐，不模糊的话蒙版会是
    # 一张麻点图，涂上去脏。半径 2、三遍够把 512 上的高频压平。
    delta = rm.box_blur(delta, ww, wh, radius=2, passes=3)

    return {"w": w, "h": h, "base": data, "ref": ref, "source": used,
            "notes": notes, "info": info, "fallback": fallback,
            "work_w": ww, "work_h": wh,
            "base_luma": base_luma, "delta": delta,
            "selection": sel, "radius": radius}
