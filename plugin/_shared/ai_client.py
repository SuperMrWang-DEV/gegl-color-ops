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


def detect_family(checkpoint):
    """按文件名猜底模家族：'sd15' 或 'sdxl'。认不出来就当 SD1.5。"""
    name = (checkpoint or "").lower()
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
    """PNG → (width, height, channels, bytes)。只支持 8 位、非隔行。

    支持 colour type 0/2/4/6（灰 / RGB / 灰+A / RGBA）与全部五种行过滤。
    调色板（type 3）和 16 位不要，ComfyUI 出来的图不会是这两种。
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
    if depth != 8:
        raise ComfyError("只支持 8 位 PNG，这张是 %s 位" % depth)
    if interlace:
        raise ComfyError("不支持隔行 PNG")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise ComfyError("不支持的 PNG colour type: %s" % ctype)

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise ComfyError("PNG 数据解压失败: %s" % exc)

    stride = width * channels
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
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xff
        elif ftype == 2:                                 # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xff
        elif ftype == 3:                                 # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xff
        elif ftype == 4:                                 # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xff
        elif ftype != 0:
            raise ComfyError("未知的 PNG 行过滤类型: %s" % ftype)
        out[y * stride:(y + 1) * stride] = line
        prev = line
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

    def first_checkpoint(self):
        """自动挑一个底模：**优先普通底模**，跳过 inpaint 专用模型。

        9 通道的 inpaint 底模（sd-v1.5-inpainting 那一类）在 ComfyUI 的
        VAEEncodeForInpaint 工作流下不认提示词：实测只把蒙版区抹平，画不出你要
        的东西，边界还留一圈淡影（2026-11-20）。它们的文件名都带 "inpaint"，
        所以按名字让开；真的只剩 inpaint 模型时也不拦着。
        Prefer a plain checkpoint: 9-channel inpaint models ignore the prompt
        on the VAEEncodeForInpaint path.
        """
        names = self.checkpoints()
        if not names:
            raise ComfyError(
                "ComfyUI 里没有可用的底模（checkpoints 目录是空的）。\n"
                "把 SD1.5 的 .safetensors 放进 D:\\ComfyUI\\ComfyUI\\models\\"
                "checkpoints\\ 后重启服务。")
        plain = [n for n in names if "inpaint" not in n.lower()]
        return (plain or names)[0]

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
def build_inpaint_workflow(checkpoint, image_name, mask_name, prompt,
                           negative="", steps=25, cfg=7.5, seed=0, denoise=1.0,
                           sampler="dpmpp_2m", scheduler="karras",
                           grow_mask_by=8, prefix="lb-ai-inpaint"):
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "3": {"class_type": "LoadImage", "inputs": {"image": mask_name}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative or "", "clip": ["1", 1]}},
        "6": {"class_type": "VAEEncodeForInpaint",
              "inputs": {"pixels": ["2", 0], "vae": ["1", 2], "mask": ["3", 1],
                         "grow_mask_by": int(grow_mask_by)}},
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


def inpaint(client, image_png, mask_png_bytes, prompt, negative="",
            checkpoint="", steps=25, cfg=7.5, seed=0, denoise=1.0,
            grow_mask_by=8, sampler="dpmpp_2m", scheduler="karras",
            timeout=600.0, prefix="lb-ai-inpaint", on_tick=None):
    """一整套「传图 → 排队 → 等 → 取回」；返回 (png_bytes, info)。

    image_png / mask_png_bytes 都是 PNG 字节，尺寸必须一致（调用方保证）。
    """
    t0 = time.time()
    src_name, _ = client.upload_image("lb-inpaint-src.png", image_png)
    msk_name, _ = client.upload_image("lb-inpaint-mask.png", mask_png_bytes)
    ckpt = checkpoint or client.first_checkpoint()

    wf = build_inpaint_workflow(ckpt, src_name, msk_name, prompt,
                               negative=negative, steps=steps, cfg=cfg,
                               seed=seed, denoise=denoise, sampler=sampler,
                               scheduler=scheduler, grow_mask_by=grow_mask_by,
                               prefix=prefix)
    pid = client.queue(wf)
    entry = client.wait(pid, timeout=timeout, on_tick=on_tick)
    img = first_image(entry)
    blob = client.download(img.get("filename", ""),
                           img.get("subfolder", ""),
                           img.get("type", "output"))
    return blob, {"prompt_id": pid, "checkpoint": ckpt,
                  "seconds": round(time.time() - t0, 2),
                  "filename": img.get("filename", "")}


def random_seed():
    """seed < 0 时用这个；取时间戳而不是 random，方便在日志里回溯。"""
    return int(time.time() * 1000) % (2 ** 32)
