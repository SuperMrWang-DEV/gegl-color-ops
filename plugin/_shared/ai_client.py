#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · ComfyUI 客户端 —— 插件与回归脚本共用
 ---------------------------------------------------------------------------
 purpose   GIMP 插件（plugin/ai-inpaint）要跟本机 ComfyUI 说话：传一张带蒙版
           的图、等它重绘完、把结果取回来。这套 HTTP + PNG 的活儿放在这里，
           一是插件本身只剩「选区 ↔ 像素」的 GIMP 部分，二是
           tools/check_ai_inpaint.py 可以在没有 GIMP 的环境里（CI）直接测它。
           A minimal ComfyUI API client shared by the plug-in and the tests.

 约束       **只用标准库**。GIMP 3 内嵌的 Python 没有 requests / PIL / numpy，
           而 tools/ 下的回归脚本又跑在系统 Python 上，所以这里不能有任何
           第三方依赖：HTTP 用 urllib，PNG 用 zlib 手写。

 约定       ComfyUI 的 LoadImage 用 **alpha 倒推** mask（mask = 1 - alpha），
           所以「要重绘的地方」在 mask 图里必须是**透明**的。直接存一张白底
           黑区的灰度 PNG 是不行的——那会给出一张全 0 的 mask，跑完像素一点
           不动（2026-11-20 踩过）。mask_png() 负责把这件事包好。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import json
import os
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

# 默认服务地址；插件里还可以用环境变量盖掉（调试时换端口方便）
DEFAULT_SERVER = "http://127.0.0.1:8188"
ENV_SERVER = "LB_COMFY_URL"

# 「自动挑底模」时优先用这个（填 ComfyUI 里显示的完整文件名）。用户装了十来个
# 模型、又不想每次都去高级版下拉里选时，把它写进环境变量最省事。
ENV_CKPT = "LB_COMFY_CKPT"

# ComfyUI 的 VAE 是 8× 下采样：宽高不是 8 的倍数时 latent 会截断，
# 回来的图比请求的小一圈，贴回画布就错位。所有尺寸都对齐到这个数。
SIZE_ALIGN = 8

# ---- 底模家族 ---------------------------------------------------------------
# 不同家族的「舒适分辨率」差很多：SD1.5 在 512 最稳，喂 1024 会长出双头；
# SDXL 反过来，喂 512 出来的人脸全是糊的。裁切框必须缩放到这个尺寸附近再送，
# 回来再缩回原尺寸贴回——这是「换更大的模型」能不能用起来的关键。
#
# 名字里带 xl / sdxl 的按 SDXL 算。SD3 / Flux 走的是别的节点图，不在这个表里。
FAMILY_TARGET = {
    "sd15": 512,
    "sdxl": 1024,
    "flux": 1024,
}

# 缩放倍率的上下限：小选区放大太多会把周围上下文拉变形，大选区缩小太多
# 又会丢掉原图的边缘细节，所以两头都留个闸。
SCALE_MIN = 0.25
SCALE_MAX = 4.0

# 送进模型的工作画布，长宽比不许超过这个值。
# SD1.5 / SDXL 都只在自己训练过的比例（大致 1:2 ~ 2:1）附近画得对；超出就会
# 退化成「平涂海报 + 重复图形」——2026-11-23 实测：同一句 "sunglasses"，选区
# 是眼睛那条 1024×400（2.56:1），SDXL 交回一块绿色底 + 重复白色箭头（像路牌），
# 把画布补成 1024×512 就正常戴上眼镜了。所以超宽/超高一律先补，不硬送。
MAX_WORK_RATIO = 2.0


def is_flux_model(name):
    """Flux 系（含 4bit 量化）：文件名以 .gguf 结尾，或者带 flux 字样。

    Flux 和 SD 系的差别不只是画质——**加载方式都不一样**：主干走 UnetLoaderGGUF，
    文本编码器是 T5+CLIP-L 两个、还要一个单独的 ae 解码器，提示词也要过
    FluxGuidance。所以「是不是 flux」决定了整张节点图，不能只当成换个底模。
    """
    n = (name or "").lower()
    return n.endswith(".gguf") or "flux" in n


def detect_family(checkpoint):
    """按文件名猜底模家族：'sd15' / 'sdxl' / 'flux'。认不出来就当 SD1.5。"""
    name = (checkpoint or "").lower()
    if is_flux_model(name):
        return "flux"
    if "xl" in name or "sdxl" in name:
        return "sdxl"
    return "sd15"


def family_target(checkpoint):
    """这个底模的舒适长边（像素）。"""
    return FAMILY_TARGET.get(detect_family(checkpoint), 512)


def work_scale(w, h, target):
    """裁切框 → 送给模型时的缩放倍率（把长边对到 target）。

    限制在 [SCALE_MIN, SCALE_MAX]，两头都不至于把画面拉烂。
    """
    long_edge = max(int(w), int(h), 1)
    scale = float(target) / long_edge
    return max(SCALE_MIN, min(SCALE_MAX, scale))


# 每个家族的（短边下限, 长边上限）。只看长边是不够的：把 1024×400 的长边
# 对到 512 会得到 512×200 —— 短边远低于 512，SD1.5 在这么窄的画布上会退化
# 成一排排重复图形（2026-11-23 用户报的「平涂、重复图案」）。两头都要有闸。
FAMILY_SIDES = {
    "sd15": (512, 768),
    "sdxl": (768, 1024),
    # Flux 的原生分辨率是 1MP：短边 768 以下会糊、1024 以上 8 GB 卡会爆显存
    "flux": (768, 1024),
}


def work_size(w, h, checkpoint, max_upscale=4.0):
    """裁切框 → (工作宽, 工作高, 倍率)：短边抬到家族下限，长边压到上限。

    规则同 openfill 的 working_size：长边超上限就整体缩小；否则短边不足
    下限就整体放大（最多 max_upscale 倍），放大后长边顶到上限再退回按长边
    缩。两边都对齐到 SIZE_ALIGN，返回的倍率按实际像素算。
    """
    w, h = max(1, int(w)), max(1, int(h))
    fam = detect_family(checkpoint)
    min_side, max_side = FAMILY_SIDES.get(fam, FAMILY_SIDES["sd15"])
    longer, shorter = max(w, h), min(w, h)
    scale = 1.0
    if longer > max_side:
        scale = max_side / float(longer)
    elif shorter < min_side:
        scale = min(float(max_upscale), min_side / float(shorter))
        if longer * scale > max_side:
            scale = max_side / float(longer)
    ww = max(SIZE_ALIGN, int(round(w * scale)) // SIZE_ALIGN * SIZE_ALIGN)
    hh = max(SIZE_ALIGN, int(round(h * scale)) // SIZE_ALIGN * SIZE_ALIGN)
    return ww, hh, (ww / float(w) if w else 1.0)


# 工作缩放的最低倍率：低于它，宁肯把上下文收窄（少看一点周围），也不把
# 原图细节缩没。openfill 用 0.6 / 0.75，同一套数。
MIN_WORK_SCALE = {"sd15": 0.6, "sdxl": 0.75, "flux": 0.75}


def fit_context(sel, ctx, checkpoint, canvas_w, canvas_h, min_margin=64):
    """上下文太大、缩放会低于 MIN_WORK_SCALE 时，把它收窄到选区周围。

    sel / ctx 都是 (x1, y1, x2, y2)。返回**不比原上下文大**的新上下文，且
    一定完整包住选区（留 min_margin 边距）。选区本身就比上限还大时收不动，
    原样返回——那种情况得靠分块生成，不是收边距能解决的。
    """
    x1, y1, x2, y2 = [int(v) for v in ctx]
    sx1, sy1, sx2, sy2 = [int(v) for v in sel]
    fam = detect_family(checkpoint)
    max_side = FAMILY_SIDES.get(fam, FAMILY_SIDES["sd15"])[1]
    limit = int(max_side / MIN_WORK_SCALE.get(fam, 0.6))
    cw, ch = x2 - x1, y2 - y1
    if max(cw, ch) <= limit:
        return (x1, y1, x2, y2)
    sw, sh = max(1, sx2 - sx1), max(1, sy2 - sy1)
    if max(sw, sh) + 2 * min_margin > limit:
        return (x1, y1, x2, y2)          # 选区自己就超了，收不动
    want_w = min(cw, max(sw + 2 * min_margin, limit))
    want_h = min(ch, max(sh + 2 * min_margin, limit))
    # 以选区中心取框，再夹回画布内，最后确保仍包住选区
    cx, cy = (sx1 + sx2) // 2, (sy1 + sy2) // 2
    nx1 = max(0, min(canvas_w - want_w, cx - want_w // 2))
    ny1 = max(0, min(canvas_h - want_h, cy - want_h // 2))
    nx2, ny2 = nx1 + want_w, ny1 + want_h
    nx1 = min(nx1, max(0, sx1 - min_margin // 2))
    ny1 = min(ny1, max(0, sy1 - min_margin // 2))
    nx2 = max(nx2, min(canvas_w, sx2 + min_margin // 2))
    ny2 = max(ny2, min(canvas_h, sy2 + min_margin // 2))
    return (nx1, ny1, min(canvas_w, nx2), min(canvas_h, ny2))


def checkpoint_note(name):
    """给下拉框用的短标注：家族 + 舒适分辨率；inpaint 专用模型单独点出来。

    2026-11-24 改：inpaint 专用模型以前被标成「不认提示词，别选」——那是因为
    当时配的是 VAEEncodeForInpaint（把洞填成灰色，等于没告诉模型洞里原来是什么）。
    配上 InpaintModelConditioning 之后，它们才是填得最准的一档，所以现在标「推荐」。
    普通模型还能用（noise 配方，洞外不动），但细结构附近容易留白痕。
    """
    name = name or ""
    if is_flux_model(name):
        return "%s（Flux · 质量最好，慢）" % name
    if is_inpaint_checkpoint(name):
        return "%s（inpaint 专用 · 推荐）" % name
    fam = detect_family(name)
    return "%s（%s · %d · 非 inpaint，细结构易留痕）" % (
        name, "SDXL" if fam == "sdxl" else "SD1.5",
        FAMILY_TARGET.get(fam, 512))


class ComfyError(RuntimeError):
    """连不上 / 工作流报错 / 超时，统一一类；文案直接拿来给用户看。"""


# ---- PNG 编码 ---------------------------------------------------------------
# GIMP 内嵌 Python 没有 PIL，而我们要交出去的只有「一张 RGBA」和「一张带
# alpha 的蒙版」，所以手写一个只写不压缩花样的编码器就够：8 位、逐行 filter 0。
# 解码器是给回归脚本和 mock 服务用的（同样不依赖 PIL）。

def _png_chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload +
            struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff))


_PNG_COLOR_TYPE = {1: 0, 3: 2, 4: 6}          # 通道数 → PNG colour type


def encode_png(width, height, data, channels=4, level=6):
    """8 位紧排像素 → PNG 字节流。channels: 4=RGBA / 3=RGB / 1=Gray。

    data 必须是 width*height*channels 字节，行序自上而下（GEGL buffer 的顺序
    本来就是这个，不用翻转）。
    """
    if width <= 0 or height <= 0:
        raise ComfyError("PNG 尺寸非法: %dx%d" % (width, height))
    stride = width * channels
    if len(data) != stride * height:
        raise ComfyError("像素长度不对: %d != %d×%d×%d"
                         % (len(data), width, height, channels))
    ctype = _PNG_COLOR_TYPE.get(channels)
    if ctype is None:
        raise ComfyError("不支持的通道数: %d" % channels)

    raw = bytearray()
    view = memoryview(bytes(data))
    for y in range(height):
        raw.append(0)                      # filter type 0 (None)
        raw += view[y * stride:(y + 1) * stride]

    ihdr = struct.pack(">IIBBBBB", width, height, 8, ctype, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" +
            _png_chunk(b"IHDR", ihdr) +
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), level)) +
            _png_chunk(b"IEND", b""))


def rgba_png(width, height, rgba):
    """RGBA8 → PNG（源图用）。"""
    return encode_png(width, height, rgba, 4)


def gray_png(width, height, gray):
    """灰度 8 位 → PNG（人眼查看用；传给 ComfyUI 当 mask 请用 mask_png）。"""
    return encode_png(width, height, gray, 1)


def mask_png(width, height, gray):
    """「白=要重绘」的灰度数组 → ComfyUI 认的 mask PNG。

    ComfyUI 的 LoadImage 拿 alpha 反推 mask（mask = 1 - alpha），所以白色区域
    必须写成**透明**：RGB 全 255 只为了肉眼能看清，真正起作用的是 A=255-gray。
    Turn a white-is-inpaint grayscale mask into the RGBA form ComfyUI expects
    (LoadImage derives MASK from alpha, inverted).
    """
    return rgba_png(width, height, invert_alpha(width, height, gray))


def invert_alpha(width, height, gray):
    """灰度数组 → RGBA：RGB=255，A=255-gray。"""
    if len(gray) != width * height:
        raise ComfyError("蒙版长度不对: %d != %d×%d" % (len(gray), width, height))
    out = bytearray(width * height * 4)
    out[0::4] = b"\xff" * (width * height)
    out[1::4] = b"\xff" * (width * height)
    out[2::4] = b"\xff" * (width * height)
    out[3::4] = bytes(255 - v for v in gray)
    return bytes(out)


def decode_png(blob):
    """PNG → (width, height, channels, bytes)。支持 8/16 位、非隔行。

    支持 colour type 0/2/4/6（灰 / RGB / 灰+A / RGBA）与全部五种行过滤。
    16 位取**高字节**压成 8 位——GEGL 的 png-save 默认写 16 位，回归里要读它
    的输出跟 ctypes 预览逐像素对比，所以这条路得通。
    调色板（type 3）不支持。
    """
    if not blob or blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ComfyError("不是 PNG 数据（前 8 字节不对）")
    pos, idat = 8, bytearray()
    width = height = depth = ctype = None
    interlace = 0
    while pos + 8 <= len(blob):
        length = struct.unpack(">I", blob[pos:pos + 4])[0]
        tag = blob[pos + 4:pos + 8]
        payload = blob[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, depth, ctype, _comp, _filt, interlace = \
                struct.unpack(">IIBBBBB", payload)
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
    if width is None:
        raise ComfyError("PNG 缺 IHDR")
    if depth not in (8, 16):
        raise ComfyError("只支持 8/16 位 PNG，这张是 %s 位" % depth)
    if interlace:
        raise ComfyError("不支持隔行 PNG")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise ComfyError("不支持的 PNG colour type: %s" % ctype)

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise ComfyError("PNG 数据解压失败: %s" % exc)

    bpp = channels * (depth // 8)      # 每像素字节数（反 filter 的步长）
    stride = width * bpp
    out = bytearray(stride * height)
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        if p + 1 + stride > len(raw):
            raise ComfyError("PNG 数据不完整（第 %d 行就断了）" % y)
        ftype = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ftype == 1:                                   # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xff
        elif ftype == 2:                                 # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xff
        elif ftype == 3:                                 # Average
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xff
        elif ftype == 4:                                 # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xff
        elif ftype != 0:
            raise ComfyError("未知的 PNG 行过滤类型: %s" % ftype)
        out[y * stride:(y + 1) * stride] = line
        prev = line

    if depth == 16:
        # 每通道取高字节（>>8），也就是 16 位 → 8 位
        narrow = bytearray(width * channels * height)
        for y in range(height):
            for x in range(width * channels):
                narrow[y * width * channels + x] = \
                    out[y * stride + x * 2]          # 大端：高字节在前
        out = narrow
    return width, height, channels, bytes(out)


# ---- 尺寸对齐 ---------------------------------------------------------------

def _split_growth(need, room_a, room_b):
    """把 need 像素尽量均分到 a、b 两侧，返回 (da, db, 没地方放的余量)。

    先各给一半，一侧不够就借另一侧的，两边都满了才把余量吐回来（调用方
    用补边把余量吃掉）。
    """
    need = max(0, int(need))
    room_a = max(0, int(room_a))
    room_b = max(0, int(room_b))
    da = min(room_a, need // 2)
    db = min(room_b, need - da)
    left = need - da - db
    if left:
        extra = min(room_a - da, left)
        da += extra
        left -= extra
    return da, db, left


def plan_canvas_rect(x, y, w, h, canvas_w, canvas_h,
                     max_ratio=MAX_WORK_RATIO, align=SIZE_ALIGN):
    """把裁切框补成「长宽比 ≤ max_ratio」的工作画布。

    返回 (x, y, w, h, pad_left, pad_top, pad_right, pad_bottom)。其中
    (x, y, w, h) 是**工作画布**，可能超出图像边界；pad_* 是超出/额外部分的
    像素数，这些位置用边缘像素复制补齐（只给模型当上下文看，贴回时会被蒙版
    挡住，所以假一点也不露出来）。

    why: SD 系列只在自己训练过的比例附近才画得对。1024×400（2.56:1）这种
    超宽条送进去，SDXL 会退化成「平涂海报 + 重复图形」——实测同样一句
    "sunglasses"，2.56:1 出来是一块绿色底配重复白色箭头，2:1 就正常戴上了
    眼镜。这不是提示词的问题，是画幅的问题。
    """
    x, y, w, h = int(x), int(y), int(w), int(h)
    pad_l = pad_t = pad_r = pad_b = 0
    if w <= 0 or h <= 0 or max_ratio <= 0:
        return x, y, w, h, 0, 0, 0, 0

    if w / float(h) > max_ratio:                    # 太宽 → 加高
        need = int(-(-w // max_ratio)) - h          # ceil
        if need > 0:
            da, db, left = _split_growth(need, y, canvas_h - (y + h))
            y -= da
            h += da + db
            if left:                                # 画布上下都到边了 → 补边
                pad_t = left // 2
                pad_b = left - pad_t
                y -= pad_t
                h += left
    elif h / float(w) > max_ratio:                  # 太高 → 加宽
        need = int(-(-h // max_ratio)) - w
        if need > 0:
            da, db, left = _split_growth(need, x, canvas_w - (x + w))
            x -= da
            w += da + db
            if left:
                pad_l = left // 2
                pad_r = left - pad_l
                x -= pad_l
                w += left

    # 顺手对齐 8：多出来的补在右下。补边区反正被蒙版挡住，不需要真实像素
    if align > 1:
        ew, eh = (-w) % align, (-h) % align
        w += ew
        pad_r += ew
        h += eh
        pad_b += eh
    return x, y, w, h, pad_l, pad_t, pad_r, pad_b


def pad_edge_rgba(data, w, h, left=0, top=0, right=0, bottom=0):
    """RGBA 8 位紧排像素 → 用边缘像素复制补齐到 (w+left+right, h+top+bottom)。

    返回 (nw, nh, bytes)。补边比黑边好得多：黑边对模型来说是「一块不认识的
    深色区域」，会把周围的肤色也带暗。
    """
    left, top, right, bottom = (max(0, int(v)) for v in (left, top, right, bottom))
    if not (left or top or right or bottom):
        return w, h, data
    nw, nh = w + left + right, h + top + bottom
    rows = []
    for yy in range(h):
        row = data[yy * w * 4:(yy + 1) * w * 4]
        rows.append(row[:4] * left + row + row[-4:] * right)
    if not rows:                                    # 空裁剪：只能给个中性色
        return nw, nh, b"\x80" * (nw * nh * 4)
    body = b"".join(rows)
    return nw, nh, rows[0] * top + body + rows[-1] * bottom


def pad_gray(data, w, h, left=0, top=0, right=0, bottom=0, fill=0):
    """8 位灰度 → 补齐到 (nw, nh)，补出来的地方默认填 0（＝不重绘）。"""
    left, top, right, bottom = (max(0, int(v)) for v in (left, top, right, bottom))
    if not (left or top or right or bottom):
        return w, h, data
    nw, nh = w + left + right, h + top + bottom
    f = bytes([int(fill) & 0xff])
    band = f * nw
    out = bytearray(band * top)
    side_l, side_r = f * left, f * right
    for yy in range(h):
        out += side_l + data[yy * w:(yy + 1) * w] + side_r
    out += band * bottom
    return nw, nh, bytes(out)


def align_rect(x, y, w, h, canvas_w, canvas_h, align=SIZE_ALIGN):
    """把矩形向外扩到 align 的整数倍，并夹在画布内。

    先扩左上再扩右下；贴边时从另一侧借空间，实在借不到就保持（小图比对齐
    重要，ComfyUI 那边会自己截断，回来再 scale 一次也能对上）。
    """
    if align <= 1:
        return x, y, w, h
    x1, y1 = x, y
    x2, y2 = x + w, y + h
    # 左上向外（不越过 0）
    while x1 % align and x1 > 0:
        x1 -= 1
    while y1 % align and y1 > 0:
        y1 -= 1
    # 右下向外（不越过画布）
    while x2 % align and x2 < canvas_w:
        x2 += 1
    while y2 % align and y2 < canvas_h:
        y2 += 1
    # 画布本身就整除不了时，往回缩一点，保证尺寸是倍数
    while (x2 - x1) % align and x2 - 1 > x1:
        x2 -= 1
    while (y2 - y1) % align and y2 - 1 > y1:
        y2 -= 1
    return x1, y1, x2 - x1, y2 - y1


# ---- HTTP 客户端 ------------------------------------------------------------

def normalize_server(server):
    """补协议、去尾斜杠。空值 → 环境变量 → 默认 127.0.0.1:8188。"""
    s = (server or os.environ.get(ENV_SERVER) or DEFAULT_SERVER).strip()
    if not s:
        s = DEFAULT_SERVER
    if "://" not in s:
        s = "http://" + s
    return s.rstrip("/")


class ComfyClient(object):
    """ComfyUI 的 HTTP 接口（/system_stats、/object_info、/upload/image、
    /prompt、/history、/view）。所有失败都翻成 ComfyError，带人话说明。"""

    def __init__(self, server=None, timeout=30.0, poll=0.4, log=None):
        self.server = normalize_server(server)
        self.timeout = float(timeout)
        self.poll = float(poll)
        self.log = log or (lambda msg: None)
        self.client_id = uuid.uuid4().hex

    # ---- 底层 ----
    def _request(self, path, payload=None, timeout=None, raw=False):
        url = self.server + path
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)
        tmo = self.timeout if timeout is None else timeout
        try:
            with urllib.request.urlopen(req, timeout=tmo) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            raise ComfyError(_describe_http_error(self.server, path, exc.code, body))
        except urllib.error.URLError as exc:
            raise ComfyError(_conn_message(self.server, exc))
        except OSError as exc:                     # 超时（socket.timeout 也走这里）
            raise ComfyError("等 ComfyUI 响应超时（%s，%.0f 秒）：%s"
                             % (path, tmo, exc))
        return body if raw else _loads(body, path)

    def _upload(self, filename, blob, timeout=None):
        boundary = "----lbcomfy" + uuid.uuid4().hex
        parts = [
            ("--%s\r\nContent-Disposition: form-data; name=\"image\"; "
             "filename=\"%s\"\r\nContent-Type: image/png\r\n\r\n"
             % (boundary, filename)).encode("utf-8"),
            blob,
            ("\r\n--%s\r\nContent-Disposition: form-data; name=\"overwrite\""
             "\r\n\r\ntrue\r\n--%s--\r\n" % (boundary, boundary)).encode("utf-8"),
        ]
        req = urllib.request.Request(
            self.server + "/upload/image", data=b"".join(parts),
            headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return _loads(resp.read(), "/upload/image")
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            raise ComfyError(_describe_http_error(self.server, "/upload/image",
                                                  exc.code, body))
        except (urllib.error.URLError, OSError) as exc:
            raise ComfyError(_conn_message(self.server, exc))

    # ---- 查询 ----
    def stats(self):
        """探活。拿不到就抛 ComfyError（调用方用 probe() 拿布尔值）。"""
        return self._request("/system_stats", timeout=min(self.timeout, 10.0))

    def probe(self):
        """不抛异常的健康检查：{"ok": bool, "version": str, "error": str}"""
        try:
            data = self.stats()
        except ComfyError as exc:
            return {"ok": False, "version": "", "error": str(exc)}
        sysinfo = (data.get("system") or {}) if isinstance(data, dict) else {}
        return {"ok": True,
                "version": str(sysinfo.get("comfyui_version") or ""),
                "error": ""}

    def checkpoints(self):
        """服务上有哪些底模。ComfyUI 不同版本这里结构略有差别，取不到就空表。"""
        data = self._request("/object_info/CheckpointLoaderSimple")
        try:
            spec = data["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"]
            names = spec[0] if isinstance(spec, list) and spec else spec
            return [str(n) for n in names]
        except (KeyError, IndexError, TypeError):
            return []

    def models(self, timeout=6.0):
        """下拉框用的模型总表：SD 系（checkpoints）+ Flux 系（diffusion_models）。

        两边加载方式完全不同（见 build_flux_inpaint_workflow），但对用户来说都只是
        「选一个模型」，所以合成一张表；inpaint() 按名字自己分派。Flux 排在前面
        ——它质量最好，装了就是拿来用的；不方便的是慢（8 GB 卡 1~3 分钟）
        和要独占一份 T5，用户自己会权衡。
        """
        names = []
        try:
            names = self.checkpoints()
        except ComfyError:
            names = []
        flux = [n for n in flux_unets(self, timeout=timeout)
                if is_flux_model(n)]
        return flux + [n for n in names if n not in flux]

    def first_checkpoint(self):
        """自动挑一个底模：环境变量 > **优先 inpaint 专用底模**。

        2026-11-24 改：以前反过来（优先普通底模），理由是「9 通道的 inpaint
        底模在 VAEEncodeForInpaint 下不认提示词，只把蒙版区抹平」。那个观察没错，
        但结论错在归因——抹平是因为 VAEEncodeForInpaint 把洞填成灰色、把
        「洞里原来是什么」也丢了，不是因为模型不行。换成 InpaintModelConditioning
        之后，inpaint 底模能顺着眉毛的方向把断口接上；普通底模（sd_xl_base）
        在同一条路径上会把眉毛画成丝状、留几道白痕。

        所以现在优先 inpaint 模型，配 condition 配方（见 build_inpaint_workflow）。
        环境变量 LB_COMFY_CKPT 仍然可以点名要哪个。
        """
        names = self.checkpoints()
        if not names:
            raise ComfyError(
                "ComfyUI 里没有可用的底模（checkpoints 目录是空的）。\n"
                "把 SD1.5 的 .safetensors 放进 D:\\ComfyUI\\ComfyUI\\models\\"
                "checkpoints\\ 后重启服务。")
        want = (os.environ.get(ENV_CKPT) or "").strip()
        if want:
            for n in names:
                if n == want or os.path.basename(n) == os.path.basename(want):
                    return n
        special = [n for n in names if is_inpaint_checkpoint(n)]
        # inpaint 专用模型里再按家族排一次：SDXL inpaint 的细节和语义理解明显
        # 强过 SD1.5 inpaint（2026-11-24 在空房间地板上画猫，SD1.5 出得来形体
        # 但正面像糊的，SDXL 一档能画出毛色分层和眼神）。SD1.5 仍然排在普通
        # 底模前面——至少它见过「洞」。
        if special:
            special.sort(key=lambda n: 0 if detect_family(n) == "sdxl" else 1)
            return special[0]
        return names[0]

    # ---- 主要动作 ----
    def upload_image(self, filename, png_bytes):
        """上传一张 PNG 到 input 目录，返回服务端的文件名（重名时会被改写）。"""
        res = self._upload(filename, png_bytes)
        name = (res.get("name") if isinstance(res, dict) else "") or filename
        return name, res

    def queue(self, workflow, client_id=None):
        res = self._request("/prompt", {"prompt": workflow,
                                        "client_id": client_id or self.client_id})
        pid = (res or {}).get("prompt_id")
        if not pid:
            raise ComfyError("ComfyUI 拒绝了这次任务：%s"
                             % json.dumps(res, ensure_ascii=False)[:400])
        return pid

    def history(self, prompt_id):
        data = self._request("/history/" + prompt_id)
        if not isinstance(data, dict):
            return None
        return data.get(prompt_id)

    def wait(self, prompt_id, timeout=600.0, on_tick=None):
        """轮询 /history 直到这一单结束，返回它的 history 条目。"""
        deadline = time.time() + float(timeout)
        while True:
            entry = self.history(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ComfyError("ComfyUI 执行出错：%s"
                                     % _status_error(status))
                if status.get("completed", True):
                    return entry
            if time.time() > deadline:
                raise ComfyError("等了 %.0f 秒 ComfyUI 还没跑完（任务 %s）："
                                 "图太大或步数太多，调小 steps / 缩小选区再试。"
                                 % (timeout, prompt_id))
            if on_tick:
                on_tick()
            time.sleep(self.poll)

    def download(self, filename, subfolder="", folder_type="output"):
        query = urllib.parse.urlencode({"filename": filename,
                                        "subfolder": subfolder or "",
                                        "type": folder_type or "output"})
        return self._request("/view?" + query, raw=True)

    def interrupt(self):
        try:
            self._request("/interrupt", {})
        except ComfyError:
            pass


# ---- 错误文案 ---------------------------------------------------------------

def _conn_message(server, exc):
    """连不上 ComfyUI 时给用户看的完整提示。

    只写「连不上」没有用：最常见的是服务没开，其次是显卡被 Windows 停用了
    （设备管理器里 Code 43，ComfyUI 会在 import 阶段就崩，窗口一闪就关）。
    这两件事的处理办法完全不同，所以分条写出来。
    """
    return ("连不上 ComfyUI（%s）：%s\n"
            "  · 服务没开：双击 ComfyUI 目录里的 start-comfyui.bat，等窗口里出现\n"
            "    \"To see the GUI go to\" 之后再重跑本插件。\n"
            "  · 窗口一闪就关：多半是显卡被 Windows 停用了（设备管理器里 Code 43）。\n"
            "    新版 start-comfyui.bat 探测到没有显卡会自动改用 CPU 启动，\n"
            "    慢一些，但参考图照样能生成。\n"
            "  · 没装过：先跑 tools\\setup-ai.bat（一键装，约 5 GB 下载）。\n"
            "  最后确认浏览器能打开 %s/system_stats。"
            % (server, getattr(exc, "reason", exc), server))


def _loads(body, path):
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    try:
        return json.loads(text)
    except ValueError:
        raise ComfyError("ComfyUI 返回的不是 JSON（%s）：%s" % (path, text[:300]))


def _describe_http_error(server, path, code, body):
    detail = ""
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        data = None
    if isinstance(data, dict):
        parts = []
        if data.get("error"):
            err = data["error"]
            parts.append(err.get("message") if isinstance(err, dict) else str(err))
        for node, info in (data.get("node_errors") or {}).items():
            for e in (info.get("errors") or []):
                parts.append("[%s] %s" % (node, e.get("message") or e))
        detail = "；".join(p for p in parts if p) or \
            json.dumps(data, ensure_ascii=False)[:300]
    if not detail:
        detail = (body or b"").decode("utf-8", "replace")[:300]
    hint = ""
    if code in (502, 503, 504):
        hint = "（服务在但没准备好，确认 ComfyUI 控制台已经打印出 Starting server）"
    return "ComfyUI 返回 HTTP %s（%s%s）：%s%s" % (code, server, path, detail, hint)


def _status_error(status):
    for msg in reversed(status.get("messages") or []):
        if isinstance(msg, (list, tuple)) and len(msg) >= 2 and msg[0] == "execution_error":
            info = msg[1] or {}
            return "%s: %s" % (info.get("node_type") or info.get("node_id"),
                               info.get("exception_message") or "")
    return "见 ComfyUI 控制台"


# ---- 工作流 -----------------------------------------------------------------

# 局部重绘用的固定图：CheckpointLoaderSimple → 两张 LoadImage →
# VAEEncodeForInpaint → KSampler → VAEDecode → SaveImage。
#
# 为什么不用 9 通道的 inpaint 专用底模（sd-v1.5-inpainting.ckpt）：在 ComfyUI
# v0.46 上实测 InpaintModelConditioning 不生效（开关 noise_mask 都不改像素），
# VAEEncode 只会吐一团糊；普通 SD1.5 + VAEEncodeForInpaint 才是能用的路。
def is_inpaint_checkpoint(name):
    """底模是不是 inpaint 专用（UNet 9 通道，训练时见过「洞」）。

    文件名里带 inpaint 的都算：sd-v1.5-inpainting、*-inpaint、xxl-inpainting……
    这类模型**必须**配 InpaintModelConditioning（或旧式 VAEEncodeForInpaint），
    普通模型配它们那两种都会把 mask 通道丢掉。
    """
    return "inpaint" in (name or "").lower()


# ---- Flux Fill（4bit 量化） -------------------------------------------------
# Flux 不是「换个底模」，是另一张图：主干要 UnetLoaderGGUF（普通 CheckpointLoader
# 读不了 .gguf），文本编码器拆成 T5-XXL + CLIP-L 两个，解码要单独的 ae，
# 提示词的强度由 FluxGuidance 那个旋钮管（不是 cfg）。所以只要底模是 flux，
# 整张节点图换掉，别想着在 SD 的图上打个补丁。
FLUX_UNET_NODE = "UnetLoaderGGUF"
FLUX_DUAL_NODE = "DualCLIPLoader"
FLUX_GUIDANCE = 30.0
FLUX_STEPS = 20


def _object_info(client, node, timeout=6.0):
    """探一个节点的 /object_info；节点没注册（没装 GGUF 扩展）就给空表。

    故意吞掉所有异常：这个函数在「列出模型」这种不该失败的地方用，节点不存在、
    服务没起、mock 客户端没有 _request —— 都等价于「没有这个节点」。
    """
    try:
        return client._request("/object_info/" + node, timeout=timeout) or {}
    except Exception:
        return {}


def flux_unets(client, timeout=6.0):
    """服务上 UnetLoaderGGUF 能看到的模型（= diffusion_models/unet 目录里的）。"""
    return _combo_values(_object_info(client, FLUX_UNET_NODE, timeout),
                         FLUX_UNET_NODE, "unet_name")


def _pick(names, *hints, prefer=()):
    """在候选里按关键词挑一个：先满足 all(h in name)，再看 prefer 加分。

    prefer 里越靠前权重越高；名字**完全等于**某个 prefer 时直接胜出——否则
    「ae.safetensors」会被「flux_ae.safetensors」这种同样带 ae 的抢走。
    """
    best, best_score = "", -1
    for n in names:
        low = n.lower().replace("\\", "/")
        if hints and not all(h in low for h in hints):
            continue
        score = 0
        for i, k in enumerate(prefer):
            # k 也要转小写：prefer 里写的是给人看的文件名（4x-UltraSharp.pth），
            # 而 low 已经全小写了，不统一就永远比不中（2026-11-24 实测）。
            k = k.lower()
            if low.rsplit("/", 1)[-1] == k:
                score += 100
            elif k in low:
                score += len(prefer) - i
        if score > best_score:
            best, best_score = n, score
    return best


def flux_assets(client, unet="", timeout=8.0):
    """凑齐 Flux 跑一次要的四样东西：主干 / T5 / CLIP-L / VAE。

    挑不到的照着名字报缺什么，别让用户对着一句 KeyError 猜。
    """
    unets = flux_unets(client, timeout=timeout)
    if not unets:
        raise ComfyError(
            "ComfyUI 里没有 Flux 主干（UnetLoaderGGUF 的列表是空的）。\n"
            "确认 custom_nodes/ComfyUI-GGUF 已装好、模型放在 "
            "models/diffusion_models\\ 下，然后重启 ComfyUI。")
    unet = unet or _pick(unets, "flux", prefer=("fill", "q4"))
    if not unet:
        unet = _pick(unets, prefer=("fill",))

    def combo(node, key):
        return _combo_values(_object_info(client, node, timeout), node, key)

    # DualCLIPLoader 的两个下拉共用一个候选池（目录相同），但 ComfyUI 只把
    # 全部文件名挂在 clip_name1 上；顺手把 clip_name2 也取来并一次，谁列在哪
    # 都能挑到。
    clips = combo(FLUX_DUAL_NODE, "clip_name1")
    for extra in combo(FLUX_DUAL_NODE, "clip_name2"):
        if extra not in clips:
            clips.append(extra)
    t5 = _pick(clips, "t5", prefer=("xxl", "fp8"))
    clip_l = _pick(clips, "clip_l") or _pick(clips, "clip-l")
    vae_name = _pick(combo("VAELoader", "vae_name"), "ae",
                     prefer=("ae.safetensors",))
    missing = []
    if not unet:
        missing.append("主干 flux*.gguf（models/diffusion_models）")
    if not t5:
        missing.append("t5xxl_fp8_e4m3fn.safetensors（models/text_encoders）")
    if not clip_l:
        missing.append("clip_l.safetensors（models/text_encoders）")
    if not vae_name:
        missing.append("ae.safetensors（models/vae）")
    if missing:
        raise ComfyError("Flux 缺文件：" + "；".join(missing) +
                         "。可以跑 tools/fetch_models.py flux 自动下。")
    return {"unet": unet, "t5": t5, "clip_l": clip_l, "vae": vae_name}


def build_flux_inpaint_workflow(assets, image_name, mask_name, prompt,
                                negative="", steps=FLUX_STEPS, seed=0,
                                guidance=FLUX_GUIDANCE, prefix="lb-ai-inpaint",
                                batch=1):
    """Flux Fill 的填充图：UnetLoaderGGUF + DualCLIPLoader + InpaintModelConditioning。

    cfg 固定 1.0 —— Flux 是蒸馏模型，cfg>1 会把画面往「过饱和 + 硬边」推；
    提示词强度改用 FluxGuidance（默认 30，高了更像提示词、低了更随原图）。
    sampler 用 euler + simple，这是 Flux 的常规搭配。
    """
    wf = {
        "10": {"class_type": FLUX_UNET_NODE,
               "inputs": {"unet_name": assets["unet"]}},
        "11": {"class_type": FLUX_DUAL_NODE,
               "inputs": {"clip_name1": assets["t5"],
                          "clip_name2": assets["clip_l"], "type": "flux"}},
        "12": {"class_type": "VAELoader",
               "inputs": {"vae_name": assets["vae"]}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "3": {"class_type": "LoadImage", "inputs": {"image": mask_name}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["11", 0]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative or "", "clip": ["11", 0]}},
        "13": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["4", 0],
                          "guidance": float(guidance)}},
        "6": {"class_type": "InpaintModelConditioning",
              "inputs": {"positive": ["13", 0], "negative": ["5", 0],
                         "vae": ["12", 0], "pixels": ["2", 0],
                         "mask": ["3", 1], "noise_mask": True}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["10", 0], "positive": ["6", 0],
                         "negative": ["6", 1], "latent_image": ["6", 2],
                         "seed": int(seed), "steps": int(steps), "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1.0}},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["7", 0], "vae": ["12", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }
    batch = max(1, int(batch))
    if batch > 1:
        wf["14"] = {"class_type": "RepeatLatentBatch",
                    "inputs": {"samples": ["6", 2], "amount": batch}}
        wf["7"]["inputs"]["latent_image"] = ["14", 0]
    return wf


def build_inpaint_workflow(checkpoint, image_name, mask_name, prompt,
                           negative="", steps=25, cfg=7.5, seed=0, denoise=1.0,
                           sampler="dpmpp_2m", scheduler="karras",
                           grow_mask_by=8, prefix="lb-ai-inpaint", batch=1,
                           variant="auto"):
    """inpaint 工作流。batch > 1 时用 RepeatLatentBatch 让一次采样出多张。

    一次出多张而不是排 N 单：模型只加载一次、两张共享同一段文本编码，
    而且同一个 prompt_id 就能把 N 张一起取回（见 all_images）。

    **三种配方，必须和底模配对**（2026-11-24 实测，同一块额头、同一张蒙版）：

      variant="condition"  inpaint 专用底模 + InpaintModelConditioning
          蒙版和被挖掉的图一起进条件（9 通道），模型知道哪里是洞、洞外长什么样。
          实测：眉毛能顺着原方向接上去，没有白痕。**这是唯一"对"的配法。**

      variant="noise"      普通底模 + VAEEncode + SetLatentNoiseMask
          洞外一个字节都不加噪。比 VAEEncodeForInpaint 稳，但模型仍然没见过洞，
          细结构（眉毛、发丝、栏杆）附近还会留白痕。

      variant="legacy"     旧的 VAEEncodeForInpaint + denoise 1.0
          通用底模下会「乱画」：把 260×100 的一块额头重绘出丝状眉毛和几道白痕，
          边界一条直线（实测）。留着只为了能退回旧行为做对比。

    为什么以前反着配：9 通道模型配 VAEEncodeForInpaint 时只把蒙版区抹平、
    不认提示词，于是当时的结论是「inpaint 模型不能用」。真正的原因是条件给错了
    ——VAEEncodeForInpaint 是给 inpaint 模型用的老式编码，但它把洞填成灰色，
    等于把「洞里原来是什么」也一起丢了。InpaintModelConditioning 保留 masked
    image，才是这些模型训练时见过的输入。
    """
    if variant in (None, "auto", ""):
        variant = "condition" if is_inpaint_checkpoint(checkpoint) else "noise"

    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "3": {"class_type": "LoadImage", "inputs": {"image": mask_name}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative or "", "clip": ["1", 1]}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0],
                         "negative": ["5", 0], "latent_image": ["6", 0],
                         "seed": int(seed), "steps": int(steps),
                         "cfg": float(cfg), "sampler_name": sampler,
                         "scheduler": scheduler, "denoise": float(denoise)}},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["7", 0], "vae": ["1", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }

    if variant == "legacy":
        wf["6"] = {"class_type": "VAEEncodeForInpaint",
                   "inputs": {"pixels": ["2", 0], "vae": ["1", 2],
                              "mask": ["3", 1],
                              "grow_mask_by": int(grow_mask_by)}}
        latent_src = ["6", 0]
    elif variant == "condition":
        # 三个输出：positive / negative / latent。latent 已经带了 masked image，
        # 所以 KSampler 直接吃它，别再套一层 SetLatentNoiseMask。
        wf["6"] = {"class_type": "InpaintModelConditioning",
                   "inputs": {"positive": ["4", 0], "negative": ["5", 0],
                              "vae": ["1", 2], "pixels": ["2", 0],
                              "mask": ["3", 1], "noise_mask": True}}
        wf["7"]["inputs"]["positive"] = ["6", 0]
        wf["7"]["inputs"]["negative"] = ["6", 1]
        latent_src = ["6", 2]
    else:                                   # noise
        wf["6"] = {"class_type": "VAEEncode",
                   "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}}
        wf["10"] = {"class_type": "SetLatentNoiseMask",
                    "inputs": {"samples": ["6", 0], "mask": ["3", 1]}}
        latent_src = ["10", 0]

    wf["7"]["inputs"]["latent_image"] = latent_src

    batch = max(1, int(batch))
    if batch > 1:
        wf["11"] = {"class_type": "RepeatLatentBatch",
                    "inputs": {"samples": latent_src, "amount": batch}}
        wf["7"]["inputs"]["latent_image"] = ["11", 0]
    return wf


# 整图重绘（img2img）用的固定图：CheckpointLoaderSimple → LoadImage → VAEEncode
# → KSampler → VAEDecode → SaveImage。
#
# 和下面的 inpaint 工作流的区别只有一处：没有蒙版，latent 直接来自整张图，
# denoise 决定「保留多少原图」。磨皮预修要的正是这个——低 denoise（0.3–0.4）
# 把皮肤往干净里推，同时保住五官和轮廓；用 inpaint 那条路（全白蒙版）会把
# 整个 latent 清空，出来的是另一张脸。
def build_img2img_workflow(checkpoint, image_name, prompt, negative="",
                           steps=25, cfg=7.5, seed=0, denoise=0.35,
                           sampler="dpmpp_2m", scheduler="karras",
                           prefix="lb-ai-img2img"):
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative or "", "clip": ["1", 1]}},
        "6": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0],
                         "negative": ["5", 0], "latent_image": ["6", 0],
                         "seed": int(seed), "steps": int(steps),
                         "cfg": float(cfg), "sampler_name": sampler,
                         "scheduler": scheduler, "denoise": float(denoise)}},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["7", 0], "vae": ["1", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }


def img2img(client, image_png, prompt, negative="", checkpoint="", steps=25,
            cfg=7.5, seed=0, denoise=0.35, sampler="dpmpp_2m",
            scheduler="karras", timeout=600.0, prefix="lb-ai-img2img",
            on_tick=None):
    """整图低重绘：传图 → 排队 → 等 → 取回；返回 (png_bytes, info)。

    denoise 是这条路上唯一真正要紧的参数：0.2 只是轻微去噪，0.5 以上就开始
    换脸。磨皮预修默认 0.35。
    """
    t0 = time.time()
    src_name, _ = client.upload_image("lb-img2img-src.png", image_png)
    ckpt = checkpoint or client.first_checkpoint()

    wf = build_img2img_workflow(ckpt, src_name, prompt, negative=negative,
                                steps=steps, cfg=cfg, seed=seed,
                                denoise=denoise, sampler=sampler,
                                scheduler=scheduler, prefix=prefix)
    pid = client.queue(wf)
    entry = client.wait(pid, timeout=timeout, on_tick=on_tick)
    img = first_image(entry)
    blob = client.download(img.get("filename", ""),
                           img.get("subfolder", ""),
                           img.get("type", "output"))
    return blob, {"prompt_id": pid, "checkpoint": ckpt,
                  "seconds": round(time.time() - t0, 2),
                  "filename": img.get("filename", "")}


def first_image(entry):
    """从 history 条目里挑第一张 output 图（{filename, subfolder, type}）。"""
    for _node, out in (entry.get("outputs") or {}).items():
        for img in (out.get("images") or []):
            if (img.get("type") or "output") == "output":
                return img
    raise ComfyError("ComfyUI 跑完了却没有产出图片（工作流里少了 SaveImage？）")


def all_images(entry):
    """history 条目里这一单产出的**全部** output 图（batch > 1 时有多张）。"""
    images = []
    for _node, out in (entry.get("outputs") or {}).items():
        for img in (out.get("images") or []):
            if (img.get("type") or "output") == "output":
                images.append(img)
    if not images:
        raise ComfyError("ComfyUI 跑完了却没有产出图片（工作流里少了 SaveImage？）")
    return images


def inpaint(client, image_png, mask_png_bytes, prompt, negative="",
            checkpoint="", steps=25, cfg=7.5, seed=0, denoise=1.0,
            grow_mask_by=8, sampler="dpmpp_2m", scheduler="karras",
            timeout=600.0, prefix="lb-ai-inpaint", on_tick=None, batch=1,
            variant="auto"):
    """一整套「传图 → 排队 → 等 → 取回」；返回 ([png_bytes, …], info)。

    image_png / mask_png_bytes 都是 PNG 字节，尺寸必须一致（调用方保证）。
    batch > 1 时一次出多张候选，由调用方挑（见 quality.rank）。
    variant 见 build_inpaint_workflow：auto 会按底模自己配对。
    """
    t0 = time.time()
    src_name, _ = client.upload_image("lb-inpaint-src.png", image_png)
    msk_name, _ = client.upload_image("lb-inpaint-mask.png", mask_png_bytes)
    ckpt = checkpoint or client.first_checkpoint()
    recipe = variant
    if recipe in (None, "auto", ""):
        if is_flux_model(ckpt):
            recipe = "flux"
        else:
            recipe = "condition" if is_inpaint_checkpoint(ckpt) else "noise"

    if recipe == "flux":
        # Flux 的四个文件要先凑齐（主干 / T5 / CLIP-L / ae），缺哪个当场点名。
        assets = flux_assets(client, ckpt)
        wf = build_flux_inpaint_workflow(assets, src_name, msk_name, prompt,
                                         negative=negative, steps=steps,
                                         seed=seed, prefix=prefix,
                                         batch=batch)
    else:
        wf = build_inpaint_workflow(ckpt, src_name, msk_name, prompt,
                                    negative=negative, steps=steps, cfg=cfg,
                                    seed=seed, denoise=denoise, sampler=sampler,
                                    scheduler=scheduler,
                                    grow_mask_by=grow_mask_by,
                                    prefix=prefix, batch=batch, variant=recipe)
    pid = client.queue(wf)
    entry = client.wait(pid, timeout=timeout, on_tick=on_tick)
    images = all_images(entry)
    blobs = [client.download(img.get("filename", ""),
                             img.get("subfolder", ""),
                             img.get("type", "output"))
             for img in images]
    return blobs, {"prompt_id": pid, "checkpoint": ckpt,
                   "seconds": round(time.time() - t0, 2),
                   "filename": images[0].get("filename", ""),
                   "count": len(blobs), "variant": recipe}


def random_seed():
    """seed < 0 时用这个；取时间戳而不是 random，方便在日志里回溯。"""
    return int(time.time() * 1000) % (2 ** 32)


# ---- 抠图 / 移除背景 --------------------------------------------------------
# 走 ComfyUI-RMBG 这个自定义节点包（custom_nodes/ComfyUI-RMBG）。它把
# BiRefNet / InSPyReNet / BEN 这些「前景分割」模型包成几个节点，节点 id 是
# RMBG，输出 (IMAGE, MASK, MASK_IMAGE)。我们只要第一路 IMAGE 里的 alpha：
# 那是最贴近原图的软边（MASK 那一路经过尺寸对齐，边缘会硬一点）。
#
# 为什么要单独查节点在不在：节点包不在时 /prompt 只会回一句
# "Cannot execute because node RMBG does not exist"，用户根本不知道该装什么。
# 这里先问 /object_info/RMBG，没有就抛一条能照着做的错。
CUTOUT_NODE = "RMBG"
CUTOUT_MODELS = ("RMBG-2.0", "INSPYRENET", "BEN", "BEN2")
CUTOUT_PREFIX = "lb-cutout"

# 节点把四个模型摆在同一个下拉里，但它们**不等价**（2026-11-23 在本机逐个实测，
# 见 tools/check_cutout_models.py）：
#   RMBG-2.0    开箱即用。BiRefNet，发丝/毛绒最干净，权重 844 MB，默认选它。
#   INSPYRENET  要 Python 包 transparent-background（连带 onnxruntime）。没装时
#               节点直接抛 "No module named 'transparent_background'"——实测必炸。
#   BEN         自带 model.py + BEN_Base.pth（实测 1.08 GB）。
#   BEN2        自带 BEN2.py + BEN2_Base.pth（实测 1.08 GB），批量推理更快。
# 后两个不是「不能用」，是「第一次要等下载」。真正的坑在于下载那几分钟里
# ComfyUI 一行日志都不打，插件就在那转圈，用户只能以为卡死了。所以下面
# 准备了一张权重表，把超时翻成「正在下 X MB，再等等」。
CUTOUT_WEIGHT_MB = {
    "RMBG-2.0": 844,
    "INSPYRENET": 350,
    "BEN": 1080,
    "BEN2": 1080,
}
# 默认模型的优先级：先挑真的能跑的，再考虑效果。
CUTOUT_PREFERRED = ("RMBG-2.0", "BEN2", "BEN", "INSPYRENET")


def build_cutout_workflow(image_name, model="RMBG-2.0", sensitivity=1.0,
                          process_res=1024, mask_blur=0, mask_offset=0,
                          refine_foreground=True, prefix=CUTOUT_PREFIX):
    """LoadImage → RMBG → SaveImage，只有三个节点。

    background 固定 "Alpha"：要的是透明底，不是它自带的换色。
    refine_foreground 默认开——它就是「前景颜色估计」，把边缘半透明像素的
    颜色按邻近前景重算，能明显压掉白边/绿边（绿幕照片尤其明显）。
    """
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": CUTOUT_NODE,
              "inputs": {"image": ["1", 0], "model": model,
                         "sensitivity": float(sensitivity),
                         "process_res": int(process_res),
                         "mask_blur": int(mask_blur),
                         "mask_offset": int(mask_offset),
                         "invert_output": False,
                         "refine_foreground": bool(refine_foreground),
                         "unload_model": False,
                         "background": "Alpha"}},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": prefix}},
    }


def _input_names(object_info, node_id):
    """从 /object_info 的一条里抠出某个输入的可选值（list 或 dict 两种形态）。"""
    try:
        spec = object_info[node_id]["input"]
        for group in ("required", "optional"):
            item = (spec.get(group) or {}).get("model") or \
                   (spec.get(group) or {}).get("ckpt_name")
            if not item:
                continue
            values = item[0] if isinstance(item, (list, tuple)) and item else item
            if isinstance(values, (list, tuple)):
                return [str(v) for v in values]
    except (KeyError, TypeError, AttributeError, IndexError):
        pass
    return []


def cutout_models(client, timeout=2.0):
    """服务上可用哪些抠图模型；节点包没装就空表（不抛）。"""
    try:
        info = client._request("/object_info/" + CUTOUT_NODE, timeout=timeout)
    except ComfyError:
        return []
    return _input_names(info, CUTOUT_NODE)


def cutout_available(client, timeout=2.0):
    """节点包在不在。插件注册菜单时用它决定「模型」是下拉还是文本框。"""
    return bool(cutout_models(client, timeout=timeout))


def preferred_model(models, want=""):
    """挑一个默认模型：want 命中就用它，否则按「能用优先」的顺序挑。"""
    names = [str(m) for m in (models or [])]
    want = (want or "").strip()
    if want and want in names:
        return want
    for cand in CUTOUT_PREFERRED:
        if cand in names:
            return cand
    return names[0] if names else ""


def explain_cutout_error(message, model="", elapsed=None):
    """把 ComfyUI 回的抠图错误翻成「缺什么、怎么补」。

    认不出来就原样返回——宁可给用户看原文，也不要编一句对的废话。
    """
    text = str(message or "")
    low = text.lower()
    tips = []

    if "transparent_background" in low:
        tips.append(
            "INSPYRENET 要 Python 包 transparent-background（它自己还要 "
            "onnxruntime），当前这个 ComfyUI 环境里没装：\n"
            "    <ComfyUI>\\py312\\python.exe -m pip install "
            "transparent-background onnxruntime\n"
            "装完重启 ComfyUI。副作用是这个包会把 opencv-python-headless 和 "
            "protobuf 一起升上去，别的节点若依赖旧版可能受影响；只求稳就用 "
            "RMBG-2.0（开箱即用，效果也最好）。")
    else:
        mod = re.search(r"no module named '([\w.\-]+)'", low)
        if mod:
            tips.append("这个模型缺 Python 包 %s：\n    <ComfyUI>\\py312\\python.exe "
                        "-m pip install %s\n装完重启 ComfyUI。"
                        % (mod.group(1), mod.group(1).split(".")[0]))

    timed_out = ("还没跑完" in text) or ("timed out" in low) or ("timeout" in low)
    if timed_out:
        mb = CUTOUT_WEIGHT_MB.get(model, 0)
        if mb:
            tips.append(
                "%s 第一次用要先下约 %d MB 权重。下载阶段 ComfyUI 窗口里只会"
                "多出几行 Downloading…，进度条是不动的，插件这边只能干等。\n"
                "  先去看一眼 ComfyUI 窗口：还在 Downloading 就多等几分钟，"
                "权重落盘后再跑是秒出；下不动就查网络/镜像"
                "（start-comfyui.bat 里设了 HF_ENDPOINT=https://hf-mirror.com）。"
                % (model, mb))
        tips.append("不想等就换 RMBG-2.0 —— 它不需要额外下载。")
    elif any(k in low for k in ("connection", "name or service", "ssl",
                                "download", "404", "resolve")):
        tips.append("权重下载失败：确认能访问 hf-mirror.com。"
                    "ComfyUI 的启动脚本里已经设了 HF_ENDPOINT，"
                    "如果是手动起的服务，要自己先 set 这个变量。")

    if not tips:
        return text
    return text + "\n\n" + "\n".join(tips)


def cutout(client, image_png, model="", sensitivity=1.0, process_res=1024,
           mask_blur=0, mask_offset=0, refine_foreground=True,
           timeout=600.0, on_tick=None):
    """传图 → RMBG → 取回带 alpha 的 RGBA。返回 (png_bytes, info)。

    调用方（插件）负责先把图缩到长边 ≤ 2048 再传：RMBG 内部按 process_res
    缩放，24MP 的原始图进去只会白白多占一份内存。
    """
    t0 = time.time()
    models = cutout_models(client, timeout=3.0)
    if not models:
        raise ComfyError(
            "ComfyUI 里没有 RMBG 节点。抠图需要 ComfyUI-RMBG 这个自定义节点包：\n"
            "  1. 打开 ComfyUI 的 custom_nodes 目录；\n"
            "  2. git clone https://github.com/1038lab/ComfyUI-RMBG\n"
            "  3. 重启 ComfyUI（会自动下载 RMBG-2.0 模型，约 900 MB）\n"
            "装好后这个菜单就能用了；本地抠图那条路不需要它。")
    want = (model or "").strip()
    fallback_from = ""
    if want and want not in models:
        fallback_from = want          # 名字对不上就退回推荐的，不报错
        want = ""
    model = preferred_model(models, want)

    src_name, _ = client.upload_image("lb-cutout-src.png", image_png)
    wf = build_cutout_workflow(src_name, model=model, sensitivity=sensitivity,
                               process_res=process_res, mask_blur=mask_blur,
                               mask_offset=mask_offset,
                               refine_foreground=refine_foreground)
    pid = client.queue(wf)
    try:
        entry = client.wait(pid, timeout=timeout, on_tick=on_tick)
    except ComfyError as exc:
        # 报错原文对用户没用（"No module named ..." / "等了 600 秒还没跑完"），
        # 在这里补上「缺什么、怎么补」，插件那边就能原样弹出来。
        raise ComfyError(explain_cutout_error(str(exc), model,
                                              time.time() - t0)) from None
    img = first_image(entry)
    blob = client.download(img.get("filename", ""), img.get("subfolder", ""),
                           img.get("type", "output"))
    return blob, {"prompt_id": pid, "model": model,
                  "fallback_from": fallback_from,
                  "seconds": round(time.time() - t0, 2),
                  "filename": img.get("filename", "")}


# ---- 按名称自动选区（SAM2 + GroundingDINO）---------------------------------
# 还是 ComfyUI-RMBG 这个节点包，只不过用的是里面的 SAM2Segment：文字描述 →
# GroundingDINO 找出候选框 → SAM2 按框切出蒙版。这样「把耳朵选中」不用手描，
# 写一句 "ear" 就行。
#
# 和抠图的区别：抠图给的是「整个前景」，这个给的是「你点名的那个东西」，
# 而且能给出多块（比如两只眼睛）。蒙版直接转成 GIMP 选区，后面的填充/
# 调色/局部模糊都能接着用。
SEG_NODE = "SAM2Segment"
SEG_MASK_NODE = "MaskToImage"
SEG_PREFIX = "lb-ai-seg"
SEG_DINO = "GroundingDINO_SwinT_OGC (694MB)"
SEG_MODELS = ("sam2.1_hiera_tiny", "sam2.1_hiera_small",
              "sam2.1_hiera_base_plus", "sam2.1_hiera_large")
SEG_DEFAULT_THRESHOLD = 0.30


def build_segment_workflow(image_name, prompt, sam2_model=SEG_MODELS[0],
                           dino_model=SEG_DINO,
                           threshold=SEG_DEFAULT_THRESHOLD, mask_offset=0,
                           prefix=SEG_PREFIX):
    """LoadImage → SAM2Segment → MaskToImage → SaveImage。

    只取 SAM2Segment 的**第 2 路**（MASK，0..1 浮点），过 MaskToImage 变成
    IMAGE 存盘——第 1 路是「抠出来的前景」，第 3 路是带背景色的预览图，
    对我们都没用。
    mask_offset 是节点的「膨胀/收缩」，正数往外出：给填充留一圈余量时有用。
    threshold 越低框越多（0.30 对小东西比默认 0.35 稳一点）。
    """
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": SEG_NODE,
              "inputs": {"image": ["1", 0], "prompt": prompt,
                         "sam2_model": sam2_model, "dino_model": dino_model,
                         "device": "Auto",
                         "threshold": float(threshold),
                         "mask_offset": int(mask_offset),
                         "invert_output": False, "unload_model": False,
                         "background": "Alpha"}},
        "3": {"class_type": SEG_MASK_NODE, "inputs": {"mask": ["2", 1]}},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": prefix}},
    }


def _combo_values(object_info, node_id, key):
    """从 /object_info 里抠某个下拉的候选值。

    三种写法都见过（同一台机器上并存，因为节点包各写各的）：
      ["a.safetensors", "b.safetensors"]        ← 老写法，直接就是列表
      [["a", "b"], {"tooltip": "..."}]          ← 列表 + 选项字典
      ["COMBO", {"options": ["a", "b"]}]        ← 新写法（ComfyUI 2025 起）
    只认第一种的话，UpscaleModelLoader 会在真机上一直返回空表——mock 里是
    老写法，测试看不出来（2026-11-24 实测）。
    """
    try:
        spec = object_info[node_id]["input"]
        for group in ("required", "optional"):
            item = (spec.get(group) or {}).get(key)
            if not isinstance(item, (list, tuple)) or not item:
                continue
            values = item[0]
            if isinstance(values, str) and values.upper() == "COMBO":
                opts = item[1] if len(item) > 1 else {}
                values = (opts or {}).get("options") if isinstance(opts, dict) \
                    else None
            if isinstance(values, (list, tuple)):
                return [str(v) for v in values]
            if isinstance(values, dict):
                return [str(v) for v in values]
    except (KeyError, TypeError, AttributeError, IndexError):
        pass
    return []


def segment_models(client, timeout=2.0):
    """服务上 SAM2Segment 支持的模型档位；节点没注册就空表（不抛）。"""
    try:
        info = client._request("/object_info/" + SEG_NODE, timeout=timeout)
    except ComfyError:
        return []
    return _combo_values(info, SEG_NODE, "sam2_model")


def segment_available(client, timeout=2.0):
    """SAM2Segment 这个节点在不在（决定菜单里显不显示「按名称选区」）。"""
    return bool(segment_models(client, timeout=timeout))


def explain_segment_error(message):
    """把 SAM2 / GroundingDINO 的报错翻成「缺什么、装什么」。

    这一段最容易踩的坑是**权重走 huggingface.co 直连**：节点自己会下载，
    但国内直连是 0 字节卡死（不是慢，是不动），看起来像「ComfyUI 卡住了」。
    所以除了缺 Python 包，还要把「权重放哪」写清楚。
    """
    text = str(message or "")
    low = text.lower()
    tips = []
    mod = re.search(r"no module named '([\w.\-]+)'", low)
    if mod:
        pkg = mod.group(1).split(".")[0]
        alias = {"groundingdino": "groundingdino-py", "hydra": "hydra-core",
                 "omegaconf": "omegaconf", "addict": "addict",
                 "supervision": "supervision", "iopath": "iopath"}
        tips.append("缺 Python 包 %s：\n    <ComfyUI>\\py312\\python.exe -m pip "
                    "install %s\n装完**重启 ComfyUI**（节点是启动时注册的）。"
                    % (pkg, alias.get(pkg, pkg)))
    if "download" in low or "http" in low or "0 字节" in text:
        tips.append(
            "SAM2 / GroundingDINO 的权重是它们自己从 huggingface.co 下的，"
            "国内直连会卡在 0 字节。手动放到这两个目录即可（文件名必须一致）：\n"
            "    models\\sam2\\sam2.1_hiera_tiny-fp16.safetensors   (~78 MB)\n"
            "    models\\grounding-dino\\groundingdino_swint_ogc.safetensors"
            "   (~700 MB)\n"
            "    models\\grounding-dino\\GroundingDINO_SwinT_OGC.cfg.py")
    timed_out = ("还没跑完" in text) or ("timed out" in low) or ("timeout" in low)
    if timed_out and not tips:
        tips.append("这次是等超时。首次运行要先加载 GroundingDINO(≈1.5 GB 显存)"
                    "+ SAM2，头一次会慢一些；再跑一次通常就快了。")
    if not tips:
        return text
    return text + "\n\n" + "\n\n".join(tips)


def segment(client, image_png, prompt, sam2_model="", dino_model="",
            threshold=SEG_DEFAULT_THRESHOLD, mask_offset=0,
            timeout=300.0, on_tick=None):
    """传图 → 按名称切出蒙版 → 取回。返回 (w, h, gray_bytes, info)。

    gray_bytes 是单通道蒙版（255 = 选中的对象），尺寸和送进去的图一致——
    调用方负责再缩放回画布（mask_io.selection_from_mask 会做）。
    一个对象都没找到时 gray 全 0，info["empty"] 为 True，不抛异常：这是
    正常结果（名字写错了、图里没有），让插件去提示比抛错友好。
    """
    t0 = time.time()
    models = segment_models(client, timeout=3.0)
    if not models:
        raise ComfyError(
            "ComfyUI 里没有 SAM2Segment 节点。按名称选区需要 ComfyUI-RMBG "
            "节点包（0.40 以上版本才有 SAM2 这部分）：\n"
            "  1. 打开 ComfyUI 的 custom_nodes 目录；\n"
            "  2. git clone https://github.com/1038lab/ComfyUI-RMBG\n"
            "  3. <ComfyUI>\\py312\\python.exe -m pip install groundingdino-py "
            "hydra-core omegaconf iopath\n"
            "  4. 把 SAM2 / GroundingDINO 权重放进 models\\sam2 与 "
            "models\\grounding-dino\n"
            "  5. 重启 ComfyUI\n"
            "（只想要抠图的话不需要这些，抠图那条路早就在跑。）")
    want = (sam2_model or "").strip()
    if want not in models:
        want = SEG_MODELS[0] if SEG_MODELS[0] in models else models[0]

    src_name, _ = client.upload_image("lb-ai-seg-src.png", image_png)
    wf = build_segment_workflow(src_name, prompt, sam2_model=want,
                               dino_model=dino_model or SEG_DINO,
                               threshold=threshold, mask_offset=mask_offset)
    pid = client.queue(wf)
    try:
        entry = client.wait(pid, timeout=timeout, on_tick=on_tick)
    except ComfyError as exc:
        raise ComfyError(explain_segment_error(str(exc))) from None
    img = first_image(entry)
    blob = client.download(img.get("filename", ""), img.get("subfolder", ""),
                           img.get("type", "output"))
    w, h, ch, data = decode_png(blob)
    gray = data[0::ch] if ch > 1 else data          # MaskToImage 存的是灰度 RGB
    hit = sum(1 for v in gray[::7] if v > 127) * 7
    info = {"prompt_id": pid, "model": want,
            "seconds": round(time.time() - t0, 2),
            "filename": img.get("filename", ""),
            "cover": round(hit / float(max(1, w * h)), 4),
            "empty": hit < 32}
    return w, h, gray, info



# ---- 扩图 / outpaint --------------------------------------------------------
# 扩图和「局部重绘」是同一台机器：把画布往外扩一圈，让扩出来的那一圈当蒙版，
# 模型把空出来的地方画满。区别只在**谁决定蒙版**——重绘是用户画的选区，扩图
# 是画布边界。所以这里不新增工作流，只负责算对两样东西：补边后的图、蒙版。

OUTPAINT_PROMPT = ("seamless continuation of the scene, matching the existing "
                   "lighting, perspective and texture")
OUTPAINT_FEATHER = 24        # 新旧交界处羽化的半宽（px）
OUTPAINT_GROW = 24           # 硬蒙版往原图里多吃多少（给模型留过渡空间）


def expand_mask(w, h, left, top, right, bottom, feather=OUTPAINT_FEATHER):
    """**给 GIMP 图层蒙版**的软蒙版：返回 (nw, nh, gray)。

    原图之外 255，原图之内 0，交界处一段斜坡。这张只用来在 GIMP 里把候选
    图层贴回原图，**不要**拿去喂模型——喂模型请用 expand_model_mask()。

    为什么不是全图 255：那样原图也会被重画，等于整张重新生成——用户要的是
    「往外长」，不是「换一张」。

    实现按 x / y 两个方向分别算一维斜坡再取 max：矩形是轴对齐的，这样每个像
    素都只用一次比较，1 Mpx 的图也不用 Python 逐点算距离。
    """
    left, top, right, bottom = (max(0, int(v)) for v in (left, top, right, bottom))
    feather = max(1, int(feather))
    nw, nh = w + left + right, h + top + bottom
    if not (left or top or right or bottom):
        return nw, nh, bytes(nw * nh)

    span = 2.0 * feather

    def level(d):
        """带符号距离 → 0..255；0 是交界，正值往外、负值往原图里。"""
        v = 0.5 + d / span
        return 0 if v <= 0.0 else (255 if v >= 1.0 else int(round(v * 255)))

    def side_ramps(pos, size, before, after):
        """某一个轴上「两侧各自往外」的浓度。

        **没有扩的那一侧必须给 0**：早期版本把「到原图边界的距离」当成浓度，
        于是上下不扩图时，原图最上一行也会被判成 50% 要重绘——等于整张图都被
        轻轻重画了一遍（实测把干净的背景糊了一层）。
        """
        best = 0
        if before > 0:                       # 交界在 pos = before
            v = level(before - pos)
            if v > best:
                best = v
        if after > 0:                        # 交界在 pos = size - after
            v = level(pos - (size - after) + 1)
            if v > best:
                best = v
        return best

    xs = bytes(side_ramps(x, nw, left, right) for x in range(nw))
    out = bytearray()
    full = b"\xff" * nw
    for y in range(nh):
        vy = side_ramps(y, nh, top, bottom)
        if vy >= 255:
            out += full
        elif vy == 0:
            out += xs
        elif not any(xs):
            out += bytes([vy]) * nw
        else:                                   # 羽化带：逐像素取 max
            out += bytes([max(a, vy) for a in xs])
    return nw, nh, bytes(out)


def expand_model_mask(iw, ih, left, top, right, bottom, ww=None, hh=None,
                      grow=OUTPAINT_GROW):
    """**给采样器**的硬蒙版：255 = 重绘，0 = 保留。返回 (ww, hh, bytes)。

    只给 0/255，一点斜坡都不给，而且往原图里多吃 grow px。

    为什么必须硬边：ComfyUI 那条 inpaint 工作流的终点是 VAEDecode → SaveImage，
    **没有合成节点**，返回的是模型对整幅画布的重绘。给它一张 50% 的软蒙版，
    模型看到的是一个「半褪色」的区域，会顺手把它重建（提亮、补纹理），而这段
    重绘正好落在羽化带里；GIMP 再按同一条斜坡贴回去，交界处就浮出一圈亮边
    （实测平墙面上偏亮 4~8 级，一眼就能看出是个矩形）。硬边之后模型只在真的
    空白区作画，原图那块几乎原样吐回来，色差只剩模型本身的整体漂移。
    斜坡仍然要，但只由 GIMP 的图层蒙版做——一次混合，不会有脊线。

    往原图里多吃 grow 的原因：硬边界会让模型在交界内侧留一条「不敢碰」的窄带，
    多吃一点正好把这条窄带盖掉，斜坡混合时才没有缝可对。

    尺寸直接按 ww/hh 用比例算，不走 GIMP 缩放——二值蒙版过一遍双三次就又是
    灰的了，等于白做。
    """
    iw, ih = max(1, int(iw)), max(1, int(ih))
    left, top, right, bottom = (max(0, int(v)) for v in (left, top, right, bottom))
    nw, nh = iw + left + right, ih + top + bottom
    ww = nw if ww is None else max(1, int(ww))
    hh = nh if hh is None else max(1, int(hh))
    sx, sy = ww / float(nw), hh / float(nh)

    # 只有真的往外扩过的那一侧才有交界，没扩的方向不能顺手多吃。
    # 夹到原图 1/4：小图配大 grow 会把整张原图都判成重绘区（等于换一张）。
    gx = min(max(0, int(grow)), max(1, iw // 4))
    gy = min(max(0, int(grow)), max(1, ih // 4))
    gl = gx if left else 0
    gr = gx if right else 0
    gt = gy if top else 0
    gb = gy if bottom else 0
    x0 = min(ww, max(0, int(round((left + gl) * sx))))
    x1 = min(ww, max(x0, int(round((left + iw - gr) * sx))))
    y0 = min(hh, max(0, int(round((top + gt) * sy))))
    y1 = min(hh, max(y0, int(round((top + ih - gb) * sy))))

    full = b"\xff" * ww
    inner = b"\xff" * x0 + b"\x00" * (x1 - x0) + b"\xff" * (ww - x1)
    return ww, hh, full * y0 + inner * (y1 - y0) + full * (hh - y1)


def expand_canvas(data, w, h, left, top, right, bottom):
    """RGBA 原图 → 补边后的 RGBA（用边缘像素复制，不是黑边）。

    黑边对模型来说是「一块不认识的深色区域」，会把扩出来的地方整体压暗；
    边缘复制至少给了它一个连续的起点。返回 (nw, nh, bytes)。
    """
    return pad_edge_rgba(data, w, h, left, top, right, bottom)


# ---- 超分 / upscale ---------------------------------------------------------
# GIMP 自己的缩放是插值：放大只会变糊，不会变清楚。ComfyUI 这边是 ESRGAN 一类
# 的放大网络，靠 64 MB 的权重就能把 1024 边长放到 4096。节点是 ComfyUI 自带
# 的（UpscaleModelLoader / ImageUpscaleWithModel），不用装任何扩展。

UPSCALE_LOADER = "UpscaleModelLoader"
UPSCALE_NODE = "ImageUpscaleWithModel"
SCALE_NODE = "ImageScale"
UPSCALE_PREFER = ("4x-UltraSharp.pth", "4x-UltraSharp", "RealESRGAN_x4plus.pth")
UPSCALE_NATIVE = 4.0        # ESRGAN 系列基本都是 4 倍；模型自己决定，这里只做默认


def upscale_models(client, timeout=2.0):
    """服务上 UpscaleModelLoader 能看到的模型（= models/upscale_models 里的）。"""
    return _combo_values(_object_info(client, UPSCALE_LOADER, timeout),
                         UPSCALE_LOADER, "model_name")


def preferred_upscale(models, want=""):
    """挑一个放大模型：认 prefer 里的名字，其次任何带 4x/esrgan 的。"""
    want = (want or "").strip()
    if want and want in models:
        return want
    if want:                                   # 用户填了但没装：交给上层报错
        return want
    # 关键词放在 prefer 尾部：它们只是「加分项」，不该盖过精确文件名。
    # _pick 在没有一个命中时会返回第一个候选，所以兜底还得再判一次。
    best = _pick(models, prefer=UPSCALE_PREFER + ("4x", "esrgan", "ultrasharp"))
    if best:
        return best
    best = _pick(models, "4x") or _pick(models, "esrgan") or _pick(models, "swinir")
    return best or (models[0] if models else "")


def build_upscale_workflow(model, image_name, target_w=0, target_h=0,
                           prefix="lb-ai-upscale", method="lanczos"):
    """LoadImage → UpscaleModelLoader → ImageUpscaleWithModel → [ImageScale] → SaveImage。

    target_w/h 给了就再插一步 ImageScale 缩到精确尺寸：4x 权重只能出 4 倍，
    用户要 2 倍时（4000×3000 的图 4 倍就是 16000，GIMP 里根本拖不动）先放大
    再 lanczos 缩一半，比直接 2 倍插值清楚。
    """
    wf = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": UPSCALE_LOADER,
              "inputs": {"model_name": model}},
        "3": {"class_type": UPSCALE_NODE,
              "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
    }
    last = "3"
    if target_w and target_h:
        wf["4"] = {"class_type": SCALE_NODE,
                   "inputs": {"image": ["3", 0], "upscale_method": method,
                              "width": int(target_w), "height": int(target_h),
                              "crop": "disabled"}}
        last = "4"
    wf[str(int(last) + 1)] = {"class_type": "SaveImage",
                              "inputs": {"images": [last, 0],
                                         "filename_prefix": prefix}}
    return wf


def explain_upscale_error(message, models=()):
    """把「节点不存在 / 模型列表空的」翻成下一步该干什么。"""
    text = str(message or "")
    if "UpscaleModelLoader" in text or "not found" in text.lower() \
            or "does not exist" in text.lower():
        return (str(message) + "\n\n"
                "超分用的是 ComfyUI 自带节点，报这个多半是 ComfyUI 版本太老："
                "确认它至少是 2024 年之后的版本（有 UpscaleModelLoader）。")
    if not models:
        return (str(message) + "\n\n"
                "models\\upscale_models\\ 里没有放大模型。装一个 4x-UltraSharp"
                "（64 MB）即可：\n"
                "  SuperMrWang → AI → AI Environment… → 勾上「超分权重」那一档，"
                "或者直接跑 tools/setup_comfy.py --with upscale")
    return str(message)


def upscale(client, image_png, model="", factor=UPSCALE_NATIVE,
            target=(0, 0), timeout=300.0, prefix="lb-ai-upscale", on_tick=None):
    """整张图过一遍放大网络；返回 (png_bytes, info)。

    factor 只用来算 target：给了 target（精确像素）就以 target 为准。
    """
    t0 = time.time()
    models = upscale_models(client, timeout=3.0)
    want = preferred_upscale(models, model)
    if not want:
        raise ComfyError(explain_upscale_error(
            "ComfyUI 里没有可用的放大模型（UpscaleModelLoader 的列表是空的）。",
            models))
    src_name, _ = client.upload_image("lb-upscale-src.png", image_png)
    tw, th = (int(target[0]), int(target[1])) if target else (0, 0)
    wf = build_upscale_workflow(want, src_name, target_w=tw, target_h=th,
                                prefix=prefix)
    pid = client.queue(wf)
    try:
        entry = client.wait(pid, timeout=timeout, on_tick=on_tick)
    except ComfyError as exc:
        raise ComfyError(explain_upscale_error(str(exc), models)) from None
    img = first_image(entry)
    blob = client.download(img.get("filename", ""), img.get("subfolder", ""),
                           img.get("type", "output"))
    w, h, _ch, _px = decode_png(blob)
    info = {"prompt_id": pid, "model": want, "scale": float(factor),
            "width": w, "height": h,
            "seconds": round(time.time() - t0, 2),
            "filename": img.get("filename", "")}
    return blob, info
