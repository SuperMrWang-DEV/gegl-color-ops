#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · AI 扩图（生成式扩展画布）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把画布往外扩一圈，让模型把空出来的地方画满——Photoshop 的
           Generative Expand 就是这件事。插件负责三件事：算扩多少、把原来
           那一块用边缘像素糊出去当起点、把「新画出来的部分」用羽化蒙版贴回
           来（原图区域一个像素都不动）。
           Grow the canvas, let a local ComfyUI paint the new band, and keep
           every original pixel untouched under a feathered mask.

 menu      SuperMrWang → AI → AI Expand (Outpaint)…

 usage     1. 打开图（多图层也行，取的是「可见合成」）；
           2. 选扩哪几边（四周/左右/上下/单边）和每边扩多少像素；
           3. 提示词描述**整张图应该是什么样**（不是只描述新区域）；
           4. 跑完画布变大，原图层不动，上面多一层带蒙版的「扩展」。

 requirements
           本机 ComfyUI + 一档底模（见 README）。扩图不新增任何节点，走的是
           和 AI 填充同一条 inpaint 管道，只是蒙版由画布边界算出来。

 note      四个坑（都已在代码里绕开）：
           1. **别送黑边**。新区域如果填纯黑，模型会把它当「一块不认识的深色
              区域」，连旁边的肤色一起压暗。用边缘像素复制（pad_edge_rgba）
              给它一个连续的起点，出来的光比才对。
           2. **蒙版要羽化**。硬边等于告诉模型「从这里开始是全新的」，它会
              沿着交界画一条笔直的边；羽化之后接缝才揉得进原来那层。
           3. **原图不能被重画**。蒙版在原图范围内是 0，贴回时那一圈被挡住，
              所以放大看也不会发现「原图被重采样过一遍」。
           4. **工作尺寸是硬上限**。扩完 1256×1632 的图送 SD1.5 只会按 768
              长边画，新长出来的那一圈回来要放大两三倍，必然是软的。想要
              清楚就用 Flux 或 SDXL，或者一次只扩一边、扩得少一点。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os
import sys
import tempfile

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject, Gio

from gi.repository import Gegl

try:
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
except Exception:                  # pragma: no cover
    Gtk = None

_here = os.path.dirname(os.path.abspath(__file__))
for _cand in (_here, os.path.join(_here, '_shared'),
              os.path.normpath(os.path.join(_here, '..', '_shared'))):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.append(_cand)

try:
    from lb_i18n import _          # noqa: F811
except Exception:
    def _(message):
        return GLib.dgettext(None, message)

import lb_dialog as _dialog
import comfy_ui as UI

try:
    import ai_client
except Exception as _exc:
    ai_client = None
    _AI_IMPORT_ERROR = _exc

try:
    import quality
except Exception:
    quality = None

try:
    import candidate_picker as _picker
except Exception:
    _picker = None

try:
    import mask_io as MI
except Exception:
    MI = None

PROC = "lb-plugin-ai-expand"
PROC_ADV = "lb-plugin-ai-expand-advanced"

DEFAULT_PROMPT = ("seamless continuation of the scene, matching the existing "
                  "lighting, perspective and texture")
DEFAULT_NEGATIVE = "text, watermark, border, frame, vignette"

RESULT_LAYER = "AI Expand"
MASK_CHANNEL = "AI Expand Mask"

AMOUNT_MIN = 16
AMOUNT_MAX = 4000
AMOUNT = 256
VARIATIONS = 2
VARIATIONS_MAX = 4
FEATHER = int(getattr(ai_client, "OUTPAINT_FEATHER", 24)) if ai_client else 24
SCORE_SIDE = 260
MAX_PIXELS = 40 * 1000 * 1000      # 扩完超过 4000 万像素就别硬来（内存 + 时间）

EDGES = [
    ("all", "All four sides", "四周"),
    ("horizontal", "Left and right", "左右"),
    ("vertical", "Top and bottom", "上下"),
    ("left", "Left only", "只左边"),
    ("right", "Right only", "只右边"),
    ("top", "Top only", "只上边"),
    ("bottom", "Bottom only", "只下边"),
]
EDGE_IDS = [e[0] for e in EDGES]


# ---- 小工具 -----------------------------------------------------------------

def _pdb(name, **props):
    """按名调用 PDB；失败时抛异常（proc.run 不抛，只看第 0 位）。"""
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    if res.index(0) != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if len(res) > 1 else None
        raise RuntimeError("%s: %s" % (name, getattr(err, "message", err)))
    return res


def read_region(layer, x, y, w, h):
    """读图层的一块，返回 RGBA 8 位紧排字节。"""
    rect = Gegl.Rectangle.new(x, y, w, h)
    raw = layer.get_buffer().get(rect, 1.0, "R'G'B'A u8",
                                 Gegl.AbyssPolicy.NONE)
    data = bytes(bytearray(raw))
    if len(data) != w * h * 4:
        raise RuntimeError(_("Failed to read layer pixels: expected %d bytes, "
                             "got %d") % (w * h * 4, len(data)))
    return data


def _scale_rgba(data, w, h, nw, nh):
    """RGBA 缩放到 nw×nh（交给 GIMP 的重采样，Python 不做插值）。"""
    if (w, h) == (nw, nh):
        return data
    tmp = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    try:
        layer = Gimp.Layer.new(tmp, "lb-scale", w, h, Gimp.ImageType.RGBA_IMAGE,
                               100.0, Gimp.LayerMode.NORMAL)
        tmp.insert_layer(layer, None, 0)
        shadow = layer.get_shadow_buffer()
        shadow.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", data)
        shadow.flush()
        layer.merge_shadow(True)
        _pdb('gimp-layer-scale', layer=layer,
             **{'new-width': int(nw), 'new-height': int(nh),
                'local-origin': False})
        return read_region(layer, 0, 0, nw, nh)
    finally:
        tmp.delete()


def _scale_gray(data, w, h, nw, nh):
    if (w, h) == (nw, nh):
        return data
    rgba = bytearray(w * h * 4)
    rgba[0::4] = data
    rgba[1::4] = data
    rgba[2::4] = data
    rgba[3::4] = b"\xff" * (w * h)
    return bytes(_scale_rgba(bytes(rgba), w, h, nw, nh)[0::4])


# ---- 扩多少 -----------------------------------------------------------------

def plan_edges(edges, amount):
    """把「扩哪几边 + 每边多少像素」翻成 (left, top, right, bottom)。

    单独拎出来是因为这是唯一有语义判断的地方：选「左右」时上下必须是 0，
    否则画布会长高，用户会以为插件自己乱动。
    """
    amt = max(0, int(round(float(amount))))
    e = (edges or "all").strip().lower()
    if e not in EDGE_IDS:
        e = "all"
    if amt == 0:
        return 0, 0, 0, 0
    left = amt if e in ("all", "horizontal", "left") else 0
    right = amt if e in ("all", "horizontal", "right") else 0
    top = amt if e in ("all", "vertical", "top") else 0
    bottom = amt if e in ("all", "vertical", "bottom") else 0
    return left, top, right, bottom


# ---- 打分（和 AI 填充同一套尺子） -------------------------------------------

def rank_candidates(original, mask, cands, w, h):
    """给候选打分，返回 (order, scores)。原图 / 蒙版 / 候选都在同一坐标系。"""
    if quality is None or len(cands) < 2:
        return list(range(len(cands))), []
    sc = float(SCORE_SIDE) / max(1, max(w, h))
    sw = max(8, int(round(w * sc)))
    sh = max(8, int(round(h * sc)))
    base = quality.Buffer(sw, sh, _scale_rgba(original, w, h, sw, sh), 4)
    small = _scale_gray(mask, w, h, sw, sh)
    bufs = [quality.Buffer(sw, sh, _scale_rgba(c, w, h, sw, sh), 4) for c in cands]
    # removal=False：扩图是「往里加东西」，判据和插入一致（别按抹除那套算）
    return quality.rank(base, bufs, small, False), \
        quality.scores_of(base, bufs, small, False)


def write_region(layer, w, h, data):
    """把整块 RGBA 8 位像素写回图层（走 shadow buffer，比建选区快）。"""
    shadow = layer.get_shadow_buffer()
    shadow.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", data)
    shadow.flush()
    layer.merge_shadow(True)


def clean_up(original, mask, layer, w, h, seed, seam_band=24):
    """对选中的那张做两级修补，返回做了什么（和 AI 填充同一套）。

    扩图比局部重绘更怕接缝：新画的那条带子和原图是两个采样出来的，亮度/色温
    差一点，交界处就是一条笔直的浅色竖线（实测 SDXL 在平墙上非常明显）。
    接缝补偿只加低频色差、不动生成的细节；颗粒匹配让新带子的噪点和原图一致。
    """
    if quality is None:
        return {}
    done = {}
    px = read_region(layer, 0, 0, w, h)
    try:
        field = quality.seam_field(w, h, original, px, mask, 4, band=seam_band)
        if field is not None:
            biggest = max(max(abs(v) for v in cell) for cell in field.offsets)
            px = quality.apply_seam_field(px, w, h, 4, field)
            write_region(layer, w, h, px)
            done["seam"] = round(biggest, 1)
    except Exception as exc:
        done["seam_error"] = str(exc)
    try:
        ring = quality.noise_sigma(w, h, original, 4, mask, inside=False, step=3)
        if ring >= 1.0:
            inside = quality.noise_sigma(w, h, px, 4, mask, inside=True, step=3)
            add = quality.grain_to_add(ring, inside)
            if add > 0:
                px = quality.add_grain(px, 4, add, seed=int(seed) & 0xFFFF)
                write_region(layer, w, h, px)
                done["grain"] = round(add, 2)
        done["grain_ring"] = round(ring, 2)
    except Exception as exc:
        done["grain_error"] = str(exc)
    return done


# ---- 主流程 -----------------------------------------------------------------

def ai_expand(image, drawable, prompt, negative=DEFAULT_NEGATIVE, edges="all",
              amount=AMOUNT, variations=VARIATIONS, pick="off", checkpoint="",
              steps=25, cfg=7.5, seed=-1, feather=FEATHER, timeout=600.0,
              server="", client=None, on_tick=None, variant="auto"):
    """扩图主流程。返回 info（画布前后尺寸、每边扩了多少、耗时、用了哪个底模）。

    client 只为回归存在：塞了 mock 就不去拉真服务。
    """
    if ai_client is None:
        raise RuntimeError(_("plugin/_shared/ai_client.py is missing: install "
                             "the _shared folder next to the plug-in"))
    if MI is None:
        raise RuntimeError(_("plugin/_shared/mask_io.py is missing: install "
                             "the _shared folder next to the plug-in"))
    prompt = (prompt or "").strip() or DEFAULT_PROMPT
    left, top, right, bottom = plan_edges(edges, amount)
    if not (left or top or right or bottom):
        raise RuntimeError(_("Nothing to expand: set \"How much\" to at least "
                             "%d pixels") % AMOUNT_MIN)

    iw, ih = image.get_width(), image.get_height()
    nw, nh = iw + left + right, ih + top + bottom
    if nw * nh > MAX_PIXELS:
        raise RuntimeError(
            _("The result would be %(w)d×%(h)d (%(mp).1f megapixels). That is "
              "too big for one pass — expand less, or do it in two runs.")
            % {"w": nw, "h": nh, "mp": nw * nh / 1e6})

    # 1) 原图整块读出来（多图层时取可见合成，扩的是「用户看到的那张」）
    flat = Gimp.Layer.new_from_visible(image, image, "lb-expand-src")
    try:
        src = read_region(flat, 0, 0, iw, ih)
    finally:
        flat.delete()

    # 2) 补边 + 蒙版都算好，再动 GIMP（动完画布用户就回不去了）
    ew, eh, ext = ai_client.expand_canvas(src, iw, ih, left, top, right, bottom)
    mw, mh, mask = ai_client.expand_mask(iw, ih, left, top, right, bottom,
                                         feather=feather)
    if (ew, eh) != (mw, mh):
        raise RuntimeError(_("Internal error: canvas %(a)s vs mask %(b)s")
                           % {"a": (ew, eh), "b": (mw, mh)})

    Gimp.progress_init(_("AI Expand"))
    if client is None:
        client = UI.make_client(server, timeout=timeout)
    checkpoint = checkpoint or _client_first_checkpoint(client)
    ww, hh, _fac = ai_client.work_size(ew, eh, checkpoint)
    src_work = _scale_rgba(ext, ew, eh, ww, hh)
    mask_work = _scale_gray(mask, ew, eh, ww, hh)

    seed = ai_client.random_seed() if int(seed) < 0 else int(seed)
    batch = max(1, min(VARIATIONS_MAX, int(variations or 1)))
    blobs, info = ai_client.inpaint(
        client,
        ai_client.rgba_png(ww, hh, src_work),
        ai_client.mask_png(ww, hh, mask_work),
        prompt, negative=negative or "", checkpoint=checkpoint,
        steps=int(steps), cfg=float(cfg), seed=seed, denoise=1.0,
        timeout=float(timeout), on_tick=on_tick or Gimp.progress_pulse,
        batch=batch, variant=variant, prefix="lb-ai-expand")

    # 3) 候选先落到临时文件（GIMP 自己解 PNG，比手写解码靠谱），读成像素再排
    tmpdir = tempfile.mkdtemp(prefix="lb-expand-")
    paths, layers, px = [], [], []
    image.undo_group_start()
    try:
        _pdb('gimp-image-resize', image=image, new_width=nw, new_height=nh,
             offx=left, offy=top)
        for index, blob in enumerate(blobs):
            path = os.path.join(tmpdir, "expand-%d.png" % index)
            with open(path, "wb") as fh:
                fh.write(blob)
            paths.append(path)
            layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image,
                                         Gio.File.new_for_path(path))
            image.insert_layer(layer, None, 0)
            if (layer.get_width(), layer.get_height()) != (nw, nh):
                _pdb('gimp-layer-scale', layer=layer,
                     **{'new-width': nw, 'new-height': nh,
                        'local-origin': False})
            layer.set_offsets(0, 0)
            layers.append(layer)
            px.append(read_region(layer, 0, 0, nw, nh))

        order, scores = rank_candidates(ext, mask, px, nw, nh)
        chosen, picked_by, keep_all = order[0], "auto", True

        if pick == "auto" and _picker is not None and len(layers) > 1:
            try:
                ans = _picker.choose(layers, order, scores,
                                     focus=(0, 0, nw, nh),
                                     note=_("The band outside the old canvas "
                                            "is what changes."))
                if ans:
                    chosen = int(ans.get("index", chosen))
                    keep_all = bool(ans.get("keep_all", True))
                    picked_by = "user"
            except Exception:              # 弹窗失败不该丢掉已经跑完的结果
                pass

        # 4) 胜出的那张先补接缝与颗粒，再挂蒙版
        cleanup = clean_up(ext, mask, layers[chosen], nw, nh, seed,
                           seam_band=max(12, int(feather)))

        # 5) 蒙版：把扩出来的那一圈变成选区，再做成图层蒙版
        #    selection_from_mask 给的斜坡就是羽化本身，不要再 feather 一次——
        #    再羽化会把边界往原图里推，原图的边缘会被重采样。
        MI.selection_from_mask(image, mask, mw, mh)
        mask_channel = _pdb('gimp-selection-save', image=image).index(1)
        mask_channel.set_name(MASK_CHANNEL)
        image.select_item(Gimp.ChannelOps.REPLACE, mask_channel)

        for i, layer in enumerate(layers):
            layer.set_visible(i == chosen)
            layer.add_mask(layer.create_mask(Gimp.AddMaskType.SELECTION))
            if len(layers) > 1:
                layer.set_name("%s %d (%s)" % (
                    RESULT_LAYER, i + 1,
                    "%.2f" % scores[i].total if scores else "?"))
            else:
                layer.set_name(RESULT_LAYER)

        if not keep_all and len(layers) > 1:
            for i, layer in enumerate(layers):
                if i != chosen:
                    image.remove_layer(layer)
            layers = [layers[chosen]]
            chosen = 0
        image.undo_group_end()
    except Exception:
        try:
            image.undo_group_end()
        except Exception:
            pass
        raise
    finally:
        for path in paths:
            try:
                os.unlink(path)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass

    info.update({"canvas": (nw, nh), "before": (iw, ih),
                 "edges": (left, top, right, bottom),
                 "drawn": len(layers),
                 "order": order,
                 "scores": [round(sc.total, 3) for sc in scores],
                 "cleanup": cleanup,
                 "picked": {"by": picked_by, "index": chosen,
                            "kept_all": keep_all},
                 "variations": len(layers)})
    return info


# ---- 参数与注册 -------------------------------------------------------------

def _add_edges_argument(procedure):
    try:
        choice = Gimp.Choice.new()
        for idx, (eid, label, _zh) in enumerate(EDGES):
            choice.add(eid, idx, _(label), "")
        procedure.add_choice_argument(
            "edges", _("Which sides to grow"),
            _("All four / left and right / top and bottom / a single side. "
              "The band that gets painted is exactly this ring."),
            choice, "all", GObject.ParamFlags.READWRITE)
    except Exception:
        procedure.add_string_argument(
            "edges", _("Which sides to grow (all / horizontal / vertical / "
                       "left / right / top / bottom)"),
            _("Leave empty for all"), "all", GObject.ParamFlags.READWRITE)


AUTO_CKPT = "auto"


def _available_checkpoints(timeout=1.5):
    """注册菜单时问一次 ComfyUI 有哪些底模；连不上就空表（绝不拖慢启动）。"""
    if ai_client is None:
        return []
    try:
        return ai_client.ComfyClient(timeout=timeout).models()
    except Exception:
        return []


def _add_checkpoint_argument(procedure):
    help_text = _("Automatic prefers the best model you have (SDXL, then "
                  "Flux): outpaint paints a whole band, and the 512-class "
                  "models lose the texture there.")
    names = _available_checkpoints()
    if names:
        try:
            choice = Gimp.Choice.new()
            choice.add(AUTO_CKPT, 0, _("Automatic (recommended)"),
                       _("SDXL / Flux first — outpaint needs the detail"))
            for idx, name in enumerate(names, 1):
                choice.add(name, idx, ai_client.checkpoint_note(name),
                           _("From this ComfyUI installation"))
            procedure.add_choice_argument(
                "checkpoint", _("Checkpoint"), help_text, choice, AUTO_CKPT,
                GObject.ParamFlags.READWRITE)
            return
        except Exception:
            pass
    procedure.add_string_argument(
        "checkpoint", _("Checkpoint"), help_text, "",
        GObject.ParamFlags.READWRITE)


def _client_first_checkpoint(client):
    """扩图优先挑 SDXL / Flux：整条新边都要它画，SD1.5 那档回来是软的。

    名字要按**实际文件名**认：`sd_xl_base_1.0_inpainting_0.1.safetensors` 里
    没有 "sdxl" 这个连写，只查 "sdxl" 会一个都匹配不到，然后退到 Flux——
    实测就这么在「本以为跑 SDXL」的探针里跑了 154 秒 Flux。
    """
    try:
        names = client.models()
    except Exception:
        names = []
    families = (("sdxl", "sd_xl"), ("flux", "flux1"))
    # 先找「这一族里带 inpaint 的那份」：sd_xl_base 和 sd_xl_base_inpainting
    # 都装的时候，按字母序第一个是 base，用它扩图边缘会接不上。
    for want in families:
        for name in names:
            low = name.lower()
            if any(k in low for k in want) and "inpaint" in low:
                return name
    for want in families:
        for name in names:
            if any(k in name.lower() for k in want):
                return name
    return client.first_checkpoint()


class AiExpandPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC, PROC_ADV]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.add_string_argument(
            "prompt", _("Prompt — what the finished picture should be"),
            _("Describe the WHOLE picture, not just the new band: \"a quiet "
              "beach at sunset, wet sand, distant cliffs\". The model cannot "
              "see what is outside the canvas, so this is where you say it."),
            DEFAULT_PROMPT, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument(
            "negative", _("Negative prompt"),
            _("What must not appear — borders, frames and watermarks are "
              "already in the default"),
            DEFAULT_NEGATIVE, GObject.ParamFlags.READWRITE)
        _add_edges_argument(procedure)
        procedure.add_int_argument(
            "amount", _("How much (pixels per side)"),
            _("Pixels added on every chosen side. 256 is a good start for a "
              "portrait; 512+ for a wide scene."),
            AMOUNT_MIN, AMOUNT_MAX, AMOUNT, GObject.ParamFlags.READWRITE)
        procedure.add_int_argument(
            "variations", _("Variations — how many to draw"),
            _("2 or 3 is worth it: the band either continues the scene or it "
              "does not, and that is easy to see side by side."),
            1, VARIATIONS_MAX, VARIATIONS, GObject.ParamFlags.READWRITE)
        procedure.add_boolean_argument(
            "pick", _("Pick from candidates"),
            _("Show the candidates side by side when more than one is drawn. "
              "Batch runs never open the window."),
            True, GObject.ParamFlags.READWRITE)

        if name == PROC_ADV:
            procedure.add_string_argument(
                "server", _("ComfyUI address"),
                _("Empty = $LB_COMFY_URL, else http://127.0.0.1:8188"),
                "", GObject.ParamFlags.READWRITE)
            _add_checkpoint_argument(procedure)
            procedure.add_int_argument(
                "steps", _("Steps"), _("Sampling steps"),
                1, 150, 25, GObject.ParamFlags.READWRITE)
            procedure.add_double_argument(
                "cfg", _("CFG"), _("Prompt guidance strength"),
                1.0, 20.0, 7.5, GObject.ParamFlags.READWRITE)
            procedure.add_int_argument(
                "seed", _("Seed"), _("Random seed; -1 picks a new one each run"),
                -1, 2 ** 31 - 1, -1, GObject.ParamFlags.READWRITE)
            procedure.add_int_argument(
                "feather", _("Seam feather"),
                _("Softness of the join, in pixels. 24 is invisible on most "
                  "textures; go smaller on crisp edges, larger on gradients."),
                0, 200, FEATHER, GObject.ParamFlags.READWRITE)
            procedure.add_int_argument(
                "timeout", _("Timeout (s)"),
                _("How long to wait for the sampler"),
                30, 3600, 600, GObject.ParamFlags.READWRITE)
            procedure.set_menu_label(_("AI Expand (Outpaint, Advanced)…"))
            procedure.set_documentation(
                _("AI Expand (Advanced): server, checkpoint, seed, feather"),
                _("Same as AI Expand but exposes the server, the checkpoint "
                  "dropdown, steps/CFG/seed, the seam feather and the timeout."),
                name)
        else:
            procedure.set_menu_label(_("AI Expand (Outpaint)…"))
            procedure.set_documentation(
                _("AI Expand: grow the canvas, let AI paint the new band"),
                _("Grow the canvas by N pixels on the chosen sides and paint "
                  "the new band with ComfyUI. The original pixels stay "
                  "untouched under a feathered mask."),
                name)
        # 顺序很重要：先 set_menu_label 再 add_menu_path，否则 GIMP 会把菜单
        # 路径丢掉（见 ai-inpaint 里的同一条注释）。
        procedure.add_menu_path("<Image>/SuperMrWang/AI")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if run_mode == Gimp.RunMode.INTERACTIVE:
            if not _dialog.run_dialog(procedure, run_mode, config):
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL,
                                                   GLib.Error())
        name = procedure.get_name()
        adv = name == PROC_ADV

        def prop(key, default=None):
            val = config.get_property(key)
            return default if val is None else val

        drawable = drawables[0] if drawables else image.get_active_drawable()
        if drawable is None:
            raise RuntimeError(_("This image has no drawable to expand"))

        # 只有交互运行才弹挑选窗：批处理等鼠标 = 卡死
        pick = "auto" if (run_mode == Gimp.RunMode.INTERACTIVE and
                          bool(prop("pick", True))) else "off"
        info = ai_expand(
            image, drawable,
            prompt=prop("prompt", ""), negative=prop("negative", ""),
            edges=prop("edges", "all"), amount=prop("amount", AMOUNT),
            variations=prop("variations", VARIATIONS), pick=pick,
            checkpoint=prop("checkpoint", "") if adv else "",
            steps=prop("steps", 25) if adv else 25,
            cfg=prop("cfg", 7.5) if adv else 7.5,
            seed=prop("seed", -1) if adv else -1,
            feather=prop("feather", FEATHER) if adv else FEATHER,
            timeout=prop("timeout", 600) if adv else 600,
            server=prop("server", "") if adv else "")
        image.set_dirty(True)
        try:
            Gimp.message(_("AI Expand: %(w)d×%(h)d → grew %(g)s px, %(n)d "
                           "candidate(s) in %(s).1f s")
                         % {"w": info["canvas"][0], "h": info["canvas"][1],
                            "g": "/".join(str(v) for v in info["edges"]),
                            "n": info["drawn"], "s": info["seconds"]})
        except Exception:                  # 状态栏失败不该算任务失败
            pass
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS,
                                           GLib.Error())


if __name__ == "__main__":
    Gimp.main(AiExpandPlugin.__gtype__, sys.argv)
