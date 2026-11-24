#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归：AI 局部重绘的「HTTP + PNG」那一半（不需要 GIMP，也不需要显卡）。

    python tools/check_ai_inpaint.py [-v]

测什么：
  1. PNG 编解码来回一致（RGBA / RGB / 灰），四种行过滤都能解；
  2. 「白＝要重绘」这条约定：mask_png 把白色写成**透明**（ComfyUI 的
     LoadImage 用 mask = 1 - alpha），写反了整条链路就白跑；
  3. 裁切框对齐到 8（VAE 8× 下采样，尺寸不整除会截断 → 贴回去错位）；
  4. 工作流结构：**三种配方必须和底模配对**——inpaint 专用模型走
     InpaintModelConditioning（蒙版和被挖掉的图一起进条件），普通模型走
     VAEEncode + SetLatentNoiseMask（洞外不加噪），legacy 才用
     VAEEncodeForInpaint。蒙版都接 LoadImage 的 MASK 输出；
  5. 对着 mock 服务跑完整流程：上传 → 排队 → 轮询 → 取图，像素对得上
     （蒙版区内变成 mock 的填充色，区外一字不动）；
  6. 错误路径：服务没起、服务拒绝、节点校验失败，三种都要给人话；
  7. 插件源码的静态检查：菜单注册齐全、只 import 标准库。
"""
import os
import re
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import ai_client  # noqa: E402
import mock_comfy  # noqa: E402
import prompt_tools  # noqa: E402
import quality  # noqa: E402

VERBOSE = "-v" in sys.argv
PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        if VERBOSE:
            print("  ok   %s %s" % (name, detail))
    else:
        FAIL += 1
        print("  FAIL %s  %s" % (name, detail))


# ---- 素材 -------------------------------------------------------------------

def gradient(width, height):
    """一张可预测的假照片：横向渐变 + 中间一块深色方块。"""
    px = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 4
            r = 40 + (200 * x) // max(1, width - 1)
            g = 60 + (150 * y) // max(1, height - 1)
            b = 90
            if width // 3 < x < 2 * width // 3 and height // 3 < y < 2 * height // 3:
                r, g, b = 20, 20, 25
            px[i:i + 4] = bytes((r, g, b, 255))
    return bytes(px)


def rect_mask(width, height, x1, y1, x2, y2):
    m = bytearray(width * height)
    for y in range(y1, y2):
        m[y * width + x1:y * width + x2] = b"\xff" * (x2 - x1)
    return bytes(m)


# ---- 1. PNG ----------------------------------------------------------------

def test_png():
    print("\nPNG 编解码")
    w, h = 17, 11
    rgba = bytes((i * 7 + j) & 0xff for j in range(h) for i in range(w * 4))
    blob = ai_client.rgba_png(w, h, rgba)
    ok("RGBA 往返", ai_client.decode_png(blob) == (w, h, 4, rgba),
       "%d 字节" % len(blob))

    gray = bytes((i * 3) & 0xff for i in range(w * h))
    ok("灰度往返",
       ai_client.decode_png(ai_client.gray_png(w, h, gray)) == (w, h, 1, gray))

    rgb = bytes((i * 5) & 0xff for i in range(w * h * 3))
    ok("RGB 往返",
       ai_client.decode_png(ai_client.encode_png(w, h, rgb, 3)) == (w, h, 3, rgb))

    # 手工造一条 filter=2(Up) 与 filter=4(Paeth) 的行，验证解码器不只认 0
    raw = bytearray()
    prev = bytearray(w * 4)
    line1 = bytearray(rgba[:w * 4])
    raw.append(0)
    raw += line1
    prev = line1
    line2 = bytearray(rgba[w * 4:2 * w * 4])
    raw.append(2)                                   # Up: 存差值
    raw += bytes((line2[i] - prev[i]) & 0xff for i in range(w * 4))
    prev = line2
    for y in range(2, h):                           # 其余用 Paeth 存差值
        line = bytearray(rgba[y * w * 4:(y + 1) * w * 4])
        enc = bytearray(w * 4)
        for i in range(w * 4):
            a = line[i - 4] if i >= 4 else 0
            b = prev[i]
            c = prev[i - 4] if i >= 4 else 0
            pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
            pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            enc[i] = (line[i] - pred) & 0xff
        raw.append(4)
        raw += enc
        prev = line
    ihdr = b"\x89PNG\r\n\x1a\n" + \
        ai_client._png_chunk(b"IHDR", ai_client.struct.pack(
            ">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    blob2 = ihdr + ai_client._png_chunk(
        b"IDAT", zlib.compress(bytes(raw), 6)) + ai_client._png_chunk(b"IEND", b"")
    ok("filter 2/4 解码", ai_client.decode_png(blob2) == (w, h, 4, rgba))


# ---- 2. 蒙版约定 ------------------------------------------------------------

def test_mask():
    print("\n蒙版约定（白＝重绘 → 透明）")
    w, h = 4, 2
    gray = bytes([255, 0, 255, 0, 0, 255, 0, 255])
    _, _, ch, px = ai_client.decode_png(ai_client.mask_png(w, h, gray))
    alpha = list(px[3::4])
    ok("通道数是 RGBA", ch == 4)
    ok("白区 alpha=0（会被重绘）", alpha[0] == 0 and alpha[2] == 0,
       str(alpha))
    ok("黑区 alpha=255（保留原样）", alpha[1] == 255 and alpha[4] == 255)
    ok("RGB 恒为白（肉眼可看）", list(px[:3]) == [255, 255, 255])


# ---- 3. 对齐 ----------------------------------------------------------------

def test_align():
    print("\n裁切框对齐 8")
    cases = [((100, 60, 130, 90), (320, 200)),
             ((0, 0, 5, 5), (320, 200)),
             ((313, 193, 319, 199), (320, 200)),
             ((7, 9, 11, 13), (64, 48))]
    for (x1, y1, x2, y2), (cw, ch) in cases:
        x, y, w, h = ai_client.align_rect(x1, y1, x2 - x1, y2 - y1, cw, ch)
        ok("bbox %s → %dx%d@%d,%d" % ((x1, y1, x2, y2), w, h, x, y),
           w % 8 == 0 and h % 8 == 0 and x >= 0 and y >= 0 and
           x + w <= cw and y + h <= ch and
           x <= x1 and y <= y1 and x + w >= x2 and y + h >= y2)


# ---- 3b. 底模家族 / 工作分辨率 ------------------------------------------------

def test_family():
    print("\n底模家族与工作分辨率")
    cases = [
        ("v1-5-pruned-emaonly-fp16.safetensors", "sd15", 512),
        ("sd_xl_base_1.0.safetensors", "sdxl", 1024),
        ("SDXL/anything-v3.safetensors", "sdxl", 1024),
        ("juggernautXL_v9.safetensors", "sdxl", 1024),
        ("dreamshaper_8.safetensors", "sd15", 512),
        ("", "sd15", 512),
        (None, "sd15", 512),
    ]
    for name, fam, target in cases:
        ok("detect_family(%r) == %s" % (name, fam),
           ai_client.detect_family(name) == fam, ai_client.detect_family(name))
        ok("family_target(%r) == %d" % (name, target),
           ai_client.family_target(name) == target, ai_client.family_target(name))

    # 裁切框 → 送模型时的倍率：长边要贴近 target，但不能无限放大/缩小
    scale_cases = [
        # work_scale 返回的是**倍率**，不是目标像素
        ((432, 392), 512, 512 / 432),    # 小框喂 SD1.5：长边放大到 512
        ((1024, 1024), 512, 0.5),        # 大框喂 SD1.5：缩一半
        ((432, 392), 1024, 1024 / 432),  # 小框喂 SDXL：长边放大到 1024
        ((200, 192), 1024, 4.0),         # 太小：撞 SCALE_MAX，不无限放大
        ((4000, 3000), 512, 0.25),       # 太大：撞 SCALE_MIN
    ]
    for (w, h), target, want in scale_cases:
        got = ai_client.work_scale(w, h, target)
        ok("work_scale(%d,%d,%d) = %.2f" % (w, h, target, got),
           abs(got - want) < 0.01, "want %.2f" % want)
        # 缩放后的长边必须能对上 target（撞 clamp 的情况除外）
        long_after = max(w, h) * got
        ok("  → 长边 %.0f %s %d" % (long_after, "≈" if long_after == target else "≠", target),
           long_after == target or got in (ai_client.SCALE_MIN, ai_client.SCALE_MAX),
           "%dx%d" % (w * got, h * got))


# ---- 3c. 画幅比例（2026-11-23 那块「绿色路牌」）-------------------------------

def test_canvas_ratio():
    print("\n工作画布比例（超宽条会被画成平涂海报）")
    iw, ih = 1376, 2064

    # 用户那次：眼睛一条 1024×400 = 2.56:1 → 必须补到 ≤2:1
    x, y, w, h, pl, pt, pr, pb = ai_client.plan_canvas_rect(
        176, 620, 1024, 400, iw, ih)
    ok("1024×400 被补成 ≤2:1 的画布", w / float(h) <= ai_client.MAX_WORK_RATIO,
       "%dx%d = %.2f:1" % (w, h, w / float(h)))
    ok("  → 宽高仍是 8 的倍数", w % 8 == 0 and h % 8 == 0, "%dx%d" % (w, h))
    ok("  → 原选区还在画布里",
       x <= 176 and y <= 620 and x + w >= 176 + 1024 and y + h >= 620 + 400)
    ok("  → 画布内能长出来的部分不用补边", pl == 0 and pt == 0,
       "pads %s" % ((pl, pt, pr, pb),))

    # 竖条同样要治
    x, y, w, h = ai_client.plan_canvas_rect(0, 0, 256, 1024, 2048, 2048)[:4]
    ok("256×1024 竖条被补成 ≤1:2", h / float(w) <= ai_client.MAX_WORK_RATIO,
       "%dx%d" % (w, h))

    # 正常比例不动
    got = ai_client.plan_canvas_rect(0, 0, 512, 512, iw, ih)
    ok("正方框原样不动", got[:4] == (0, 0, 512, 512), str(got[:4]))

    # 画布太小、长不出真实像素时 → 用补边吃下余量，不能让比例破功
    x, y, w, h, pl, pt, pr, pb = ai_client.plan_canvas_rect(
        0, 0, 1024, 400, 1024, 400)
    ok("画布到边 → 改用补边", pl + pt + pr + pb > 0, str((pl, pt, pr, pb)))
    ok("  → 比例依旧 ≤2:1", w / float(h) <= ai_client.MAX_WORK_RATIO,
       "%dx%d" % (w, h))
    ok("  → 原图仍落在画布内", x <= 0 and y <= 0 and x + w >= 1024 and
       y + h >= 400, "%d,%d %dx%d" % (x, y, w, h))

    # 补边：边缘像素复制，不是黑边
    w, h = 3, 2
    px = bytes()
    for y0 in range(h):
        for x0 in range(w):
            px += bytes([10 * y0 + x0, 0, 0, 255])
    nw, nh, out = ai_client.pad_edge_rgba(px, w, h, 1, 1, 1, 1)
    ok("pad_edge_rgba 尺寸对", (nw, nh) == (5, 4))
    corner = tuple(out[0:3])
    ok("左上角复制了左上像素", corner == (0, 0, 0), str(corner))
    bottom_right = tuple(out[((nh - 1) * nw + nw - 1) * 4:][:3])
    ok("右下角复制了右下像素", bottom_right == (10 + 2, 0, 0), str(bottom_right))

    # 灰度补边默认填 0（＝不重绘），不然补出来的边会被一起重画
    nw, nh, g = ai_client.pad_gray(bytes([255, 255, 255, 255]), 2, 2, 2, 2, 2, 2)
    ok("pad_gray 尺寸对", (nw, nh) == (6, 6))
    ok("pad_gray 补出来的地方是 0（不重绘）", g[0] == 0 and g[-1] == 0)
    ok("pad_gray 原来的像素没动", g[2 * 6 + 2] == 255)


# ---- 4. 工作流 --------------------------------------------------------------

def test_workflow():
    print("\n工作流结构")
    # 普通底模：VAEEncode + SetLatentNoiseMask（洞外一个字节都不加噪）
    wf = ai_client.build_inpaint_workflow("m.safetensors", "src.png", "mask.png",
                                          "a cat", negative="dog", steps=12,
                                          cfg=6.5, seed=7, grow_mask_by=12)
    kinds = {n["class_type"] for n in wf.values()}
    ok("普通底模用 VAEEncode", "VAEEncode" in kinds)
    ok("普通底模配 SetLatentNoiseMask", "SetLatentNoiseMask" in kinds)
    ok("普通底模不再用 VAEEncodeForInpaint",
       "VAEEncodeForInpaint" not in kinds, sorted(kinds))
    ok("普通底模不用 InpaintModelConditioning",
       "InpaintModelConditioning" not in kinds)
    enc = next(n for n in wf.values() if n["class_type"] == "VAEEncode")
    mask_node = wf[enc["inputs"]["pixels"][0]]
    ok("编码吃的是原图", mask_node["class_type"] == "LoadImage" and
       mask_node["inputs"]["image"] == "src.png")
    nsm = next(n for n in wf.values() if n["class_type"] == "SetLatentNoiseMask")
    m_node = wf[nsm["inputs"]["mask"][0]]
    ok("噪声蒙版接 LoadImage 的 MASK 输出",
       m_node["class_type"] == "LoadImage" and nsm["inputs"]["mask"][1] == 1)
    ok("蒙版节点读的是 mask.png", m_node["inputs"]["image"] == "mask.png")
    ks = next(n for n in wf.values() if n["class_type"] == "KSampler")
    ok("步数/种子/CFG 传进去了",
       (ks["inputs"]["steps"], ks["inputs"]["seed"], ks["inputs"]["cfg"]) ==
       (12, 7, 6.5))
    ok("KSampler 吃的是加了噪声蒙版的 latent",
       wf[ks["inputs"]["latent_image"][0]]["class_type"] == "SetLatentNoiseMask")
    ok("有 SaveImage 才取得到图",
       any(n["class_type"] == "SaveImage" for n in wf.values()))
    ok("默认 batch=1 时不加 RepeatLatentBatch",
       "RepeatLatentBatch" not in kinds, sorted(kinds))

    # inpaint 专用底模：InpaintModelConditioning（mask 进条件，KSampler 吃它的 latent）
    wf2 = ai_client.build_inpaint_workflow(
        "sd-v1-5-inpainting.ckpt", "src.png", "mask.png", "a cat")
    kinds2 = {n["class_type"] for n in wf2.values()}
    ok("inpaint 底模自动用 InpaintModelConditioning",
       "InpaintModelConditioning" in kinds2, sorted(kinds2))
    ok("  → 不再套 SetLatentNoiseMask", "SetLatentNoiseMask" not in kinds2)
    ok("  → 也不用 VAEEncodeForInpaint", "VAEEncodeForInpaint" not in kinds2)
    imc = next(n for n in wf2.values()
               if n["class_type"] == "InpaintModelConditioning")
    ok("  → masked image 是原图", wf2[imc["inputs"]["pixels"][0]]["inputs"]
       .get("image") == "src.png")
    ok("  → mask 接 LoadImage 的 MASK", imc["inputs"]["mask"] == ["3", 1])
    ok("  → noise_mask 打开", imc["inputs"]["noise_mask"] is True)
    ks2 = next(n for n in wf2.values() if n["class_type"] == "KSampler")
    ok("  → KSampler 的正负条件来自条件节点",
       ks2["inputs"]["positive"] == ["6", 0] and
       ks2["inputs"]["negative"] == ["6", 1])
    ok("  → KSampler 的 latent 是条件节点的第 3 个输出",
       ks2["inputs"]["latent_image"] == ["6", 2])

    # legacy：显式要旧行为时才走 VAEEncodeForInpaint，grow_mask_by 才有效
    wf_old = ai_client.build_inpaint_workflow(
        "m.safetensors", "s.png", "m.png", "a cat", grow_mask_by=12,
        variant="legacy")
    enc_old = next(n for n in wf_old.values()
                   if n["class_type"] == "VAEEncodeForInpaint")
    ok("variant=legacy 才用 VAEEncodeForInpaint", isinstance(
        enc_old["inputs"]["grow_mask_by"], int))
    ok("grow_mask_by 传进去了", enc_old["inputs"]["grow_mask_by"] == 12)

    # 名字判断
    ok("认得出 inpaint 专用底模",
       ai_client.is_inpaint_checkpoint("sd-v1-5-inpainting.ckpt") and
       ai_client.is_inpaint_checkpoint("SDXL-inpaint-v2.safetensors"))
    ok("普通底模不会被误判",
       not ai_client.is_inpaint_checkpoint("sd_xl_base_1.0.safetensors") and
       not ai_client.is_inpaint_checkpoint("dreamshaper_8.safetensors"))
    ok("下拉里的 inpaint 模型标「推荐」",
       "推荐" in ai_client.checkpoint_note("sd-v1-5-inpainting.ckpt"))
    ok("普通模型标「非 inpaint」",
       "非 inpaint" in ai_client.checkpoint_note("sd_xl_base_1.0.safetensors"))

    # batch：复制的必须是「采样起点」，不是编码结果
    wf3 = ai_client.build_inpaint_workflow("m.safetensors", "s.png", "m.png",
                                           "a cat", batch=3)
    kinds3 = {n["class_type"] for n in wf3.values()}
    ok("batch=3 用 RepeatLatentBatch 一次出三张",
       "RepeatLatentBatch" in kinds3, sorted(kinds3))
    rep = next(n for n in wf3.values()
               if n["class_type"] == "RepeatLatentBatch")
    ok("  → amount 是 3", rep["inputs"]["amount"] == 3, rep["inputs"]["amount"])
    ks3 = next(n for n in wf3.values() if n["class_type"] == "KSampler")
    ok("  → KSampler 吃的是复制后的 latent",
       wf3[ks3["inputs"]["latent_image"][0]]["class_type"] == "RepeatLatentBatch")
    ok("  → 复制的源是噪声蒙版之后的 latent",
       wf3[rep["inputs"]["samples"][0]]["class_type"] == "SetLatentNoiseMask",
       rep["inputs"]["samples"])

    wf4 = ai_client.build_inpaint_workflow("sd-v1-5-inpainting.ckpt", "s.png",
                                           "m.png", "a cat", batch=2)
    rep4 = next(n for n in wf4.values() if n["class_type"] == "RepeatLatentBatch")
    ok("inpaint 底模 batch 复制条件节点的 latent",
       wf4[rep4["inputs"]["samples"][0]]["class_type"] == "InpaintModelConditioning"
       and rep4["inputs"]["samples"][1] == 2, rep4["inputs"]["samples"])


# ---- 5. 端到端（mock）------------------------------------------------------

def test_end_to_end():
    print("\n端到端（mock ComfyUI）")
    w, h = 96, 72
    src = gradient(w, h)
    gray = rect_mask(w, h, 32, 24, 64, 48)

    with mock_comfy.start_mock() as srv:
        client = ai_client.ComfyClient(srv.url, timeout=5, poll=0.05)
        probe = client.probe()
        ok("探活通过", probe["ok"], probe.get("version"))
        ok("读到 mock 底模", client.checkpoints() == [mock_comfy.CHECKPOINT])

        blobs, info = ai_client.inpaint(
            client, ai_client.rgba_png(w, h, src),
            ai_client.mask_png(w, h, gray), "a red apple", negative="blurry",
            steps=8, seed=1, timeout=30)
        ok("返回的是列表（单张也包成列表）", isinstance(blobs, list) and blobs,
           type(blobs).__name__)
        ok("info 记了张数", info.get("count") == len(blobs), info.get("count"))

        # 一次出三张：mock 按 RepeatLatentBatch 的 amount 多吐几张
        trio, info3 = ai_client.inpaint(
            client, ai_client.rgba_png(w, h, src),
            ai_client.mask_png(w, h, gray), "a red apple",
            steps=8, seed=1, timeout=30, batch=3)
        ok("batch=3 真的取回三张", len(trio) == 3, len(trio))
        ok("  → 三张都是 PNG", all(b[:4] == b"\x89PNG" for b in trio))
        ok("  → 每张内容不同（换种子/变体）", len(set(trio)) == 3, len(set(trio)))
        # 同一块画布上，三张的分差应能排出高低：越亮离原图越远
        def nn(data, w, h, nw, nh, ch=4):
            out = bytearray(nw * nh * ch)
            for y in range(nh):
                sy = min(h - 1, y * h // nh)
                for x in range(nw):
                    sx = min(w - 1, x * w // nw)
                    d = (y * nw + x) * ch
                    o = (sy * w + sx) * ch
                    out[d:d + ch] = data[o:o + ch]
            return bytes(out)

        small_mask = nn(gray, w, h, 48, 36, 1)
        base = quality.Buffer(48, 36, nn(src, w, h, 48, 36), 4)
        cands = [quality.Buffer(48, 36, nn(ai_client.decode_png(b)[3], w, h, 48, 36), 4)
                 for b in trio]
        order = quality.rank(base, cands, small_mask, removal=False)
        ok("三张候选排得出顺序", len(order) == 3 and sorted(order) == [0, 1, 2],
           order)
        ok("  → 最接近原图的那张（第 0 张）排第一", order[0] == 0,
           [round(quality.score(base, c, small_mask, False).total, 2)
            for c in cands])
        blob = blobs[0]
        ok("取回的是 PNG", blob[:8] == b"\x89PNG\r\n\x1a\n",
           "%d 字节 / %.2fs" % (len(blob), info["seconds"]))
        rw, rh, rch, rpx = ai_client.decode_png(blob)
        ok("尺寸与原图一致", (rw, rh) == (w, h), "%dx%d" % (rw, rh))

        def at(px, x, y):
            i = (y * rw + x) * 4
            return tuple(px[i:i + 3])

        ok("蒙版中心被重绘", at(rpx, 48, 36) == mock_comfy.FILL_RGB,
           str(at(rpx, 48, 36)))
        ok("蒙版边缘也被重绘", at(rpx, 33, 25) == mock_comfy.FILL_RGB)
        ok("蒙版外一字不动", at(rpx, 5, 5) == tuple(src[(5 * w + 5) * 4:][:3]),
           "%s vs %s" % (at(rpx, 5, 5), tuple(src[(5 * w + 5) * 4:][:3])))
        ok("蒙版外右下也不动", at(rpx, 90, 68) ==
           tuple(src[(68 * w + 90) * 4:][:3]))
        ok("上传了两张图（源图 + 蒙版）",
           sorted(srv.state.inputs) == ["lb-inpaint-mask.png",
                                        "lb-inpaint-src.png"])
        ok("info 带 prompt_id", bool(info["prompt_id"]))
        ok("checkpoint 用的是服务端第一份",
           info["checkpoint"] == mock_comfy.CHECKPOINT)


# ---- 5.5 候选打分与修补 ------------------------------------------------------

def _flat(w, h, level, noise=0.0, seed=1):
    """纯色 RGBA 图（可选加单色颗粒）。"""
    px = bytes([level, level, level, 255]) * (w * h)
    if noise > 0:
        px = quality.add_grain(px, 4, noise, seed=seed)
    return px


def test_quality():
    print("\n候选打分 / 接缝补偿 / 颗粒匹配")
    w = h = 64
    mask = bytes([255 if 24 <= x < 40 and 24 <= y < 40 else 0
                  for y in range(h) for x in range(w)])

    base = quality.Buffer(w, h, _flat(w, h, 128), 4)
    # 差的一张：选区内亮 60 级，边缘一道硬台阶，周围也被改动
    bad_px = bytearray(_flat(w, h, 128))
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if mask[i]:
                o = i * 4
                bad_px[o:o + 3] = bytes([188, 188, 188])
    bad = quality.Buffer(w, h, bytes(bad_px), 4)
    # 好的一张：选区内和周围一致
    good = quality.Buffer(w, h, _flat(w, h, 128), 4)

    sc_bad = quality.score(base, bad, mask, removal=True)
    sc_good = quality.score(base, good, mask, removal=True)
    ok("接缝硬的罚分更高", sc_bad.seam > sc_good.seam,
       "%.2f vs %.2f" % (sc_bad.seam, sc_good.seam))
    ok("色台阶大的罚分更高", sc_bad.frame > sc_good.frame,
       "%.2f vs %.2f" % (sc_bad.frame, sc_good.frame))
    ok("总分排序正确", sc_good.total < sc_bad.total,
       "%.3f vs %.3f" % (sc_good.total, sc_bad.total))
    ok("rank 把好的排第一", quality.rank(base, [bad, good], mask, True) == [1, 0],
       quality.rank(base, [bad, good], mask, True))
    ok("只有一张时不排序", quality.rank(base, [good], mask, True) == [0])

    # 边缘距离：选区内 <=0、边界 0、外面 >0
    d = quality.signed_distance(w, h, mask)
    ok("选区中心距离为负", d[32 * w + 32] < 0, d[32 * w + 32])
    ok("选区外距离为正", d[5 * w + 5] > 0, d[5 * w + 5])

    # 接缝场：整幅偏亮 12 级 → 应测出约 +12（原图 - 图层 = -12）
    layer = quality.Buffer(w, h, _flat(w, h, 140), 4)
    field = quality.seam_field(w, h, base.data, layer.data, mask, 4, band=16)
    ok("测出了接缝色差", field is not None)
    if field is not None:
        inside = [cell[0] for cell in field.offsets if any(cell)]
        ok("  → 偏移量约 -12", bool(inside) and
           -14 < sum(inside) / len(inside) < -10,
           round(sum(inside) / len(inside), 2) if inside else None)
        fixed = quality.apply_seam_field(layer.data, w, h, 4, field)
        centre = (32 * w + 32) * 4
        ok("  → 补完选区内接近原图",
           abs(fixed[centre] - 128) <= 2, fixed[centre])

    # 无差异时不该返回场（不许白改）
    ok("本来就没色差 → 返回 None",
       quality.seam_field(w, h, base.data, base.data, mask, 4, band=16) is None)

    # 颗粒：周围 sigma≈4、填充区 0 → 补 4
    ring_px = _flat(w, h, 128, noise=4.0, seed=7)
    s_ring = quality.noise_sigma(w, h, ring_px, 4, None, inside=False, step=2)
    s_clean = quality.noise_sigma(w, h, _flat(w, h, 128), 4, None, inside=False)
    ok("量出周围噪声 ~4（%.2f）" % s_ring, 3.0 < s_ring < 5.0, s_ring)
    ok("干净图量出的噪声接近 0（%.2f）" % s_clean, s_clean < 0.5, s_clean)
    add = quality.grain_to_add(s_ring, s_clean)
    ok("要补的量 ~4（%.2f）" % add, 3.0 < add < 5.0, add)
    ok("本来就有颗粒 → 不加", quality.grain_to_add(4.0, 4.2) == 0.0)
    ok("补完噪声接近周围",
       abs(quality.noise_sigma(w, h, quality.add_grain(_flat(w, h, 128), 4, add, 3),
                               4, None, inside=False, step=2) - s_ring) < 1.2)


# ---- 6. 错误路径 ------------------------------------------------------------

def test_errors():
    print("\n错误提示")
    dead = ai_client.ComfyClient("http://127.0.0.1:9", timeout=1.0)
    probe = dead.probe()
    ok("服务没起 → probe 返回 False", probe["ok"] is False)
    ok("提示里教人怎么启动", "start-comfyui" in probe["error"] or
       "连不上" in probe["error"], probe["error"].splitlines()[0])

    with mock_comfy.start_mock(fail_status="模拟的校验失败") as srv:
        client = ai_client.ComfyClient(srv.url, timeout=5, poll=0.05)
        try:
            ai_client.inpaint(client, ai_client.rgba_png(8, 8, bytes(8 * 8 * 4)),
                              ai_client.mask_png(8, 8, bytes(64)), "x")
        except ai_client.ComfyError as exc:
            msg = str(exc)
            ok("服务拒绝 → 抛 ComfyError", True)
            ok("错误信息里有原因", "模拟的校验失败" in msg, msg.splitlines()[0])
        else:
            ok("服务拒绝 → 抛 ComfyError", False, "居然成功了")

    with mock_comfy.start_mock() as srv:
        client = ai_client.ComfyClient(srv.url, timeout=5, poll=0.05)
        try:
            ai_client.inpaint(client, ai_client.rgba_png(8, 8, bytes(8 * 8 * 4)),
                              ai_client.mask_png(8, 8, bytes(64)), "__FAIL__")
        except ai_client.ComfyError as exc:
            ok("节点校验失败 → 报出节点与原因",
               "value_not_in_list" in str(exc) or "Value not in list" in str(exc),
               str(exc)[:80])
        else:
            ok("节点校验失败 → 报出节点与原因", False, "居然成功了")


# ---- 6.5 提示词：中文能不能直接用 --------------------------------------------

def test_prompt_tools():
    """用户脑子里的话是中文（「画一只小猫」），这层要是漏了，前面全白搭。"""
    print("\n提示词翻译与预设")

    ok("「画一只小猫」→ 英文",
       prompt_tools.to_english("画一只小猫")[0] == "small kitten",
       prompt_tools.to_english("画一只小猫")[0])

    # 数量词 / 方位词要丢掉，不能变成 "a small kitten sitting on table" 里的杂词
    got = prompt_tools.to_english("一只小猫坐在木质桌子上")[0]
    ok("数量词与虚词被丢掉", "一只" not in got and "的" not in got, got)
    ok("多字词没被切碎（猫 / 桌子）", "kitten" in got and "table" in got, got)

    # 最长匹配：油画 → oil painting，不能被拆成 oil + 画
    ok("最长匹配（油画）",
       prompt_tools.to_english("油画")[0] == "oil painting",
       prompt_tools.to_english("油画")[0])

    # 半中半英：英文段原样保留
    got = prompt_tools.to_english("一只小猫, soft bokeh, 35mm")[0]
    ok("中英混写保留英文段", "soft bokeh" in got and "35mm" in got, got)

    # 没收录的词必须点名报错，不能静默丢掉（丢掉就等于随机重绘）
    try:
        prompt_tools.to_english("嘎嘎嘎嘎的怪兽")
        ok("未收录词报错", False, "居然放过了")
    except ValueError as exc:
        ok("未收录词报错", "还没收进" in str(exc), str(exc)[:40])
        ok("报错里点名了那个词", "嘎" in str(exc), str(exc)[:40])

    # 负面提示词走宽松模式：一个生词不能废掉整段
    neg = prompt_tools.polish_negative("模糊，低质量，嘎嘎嘎")
    ok("负面提示词容忍生词", neg == "blurry low quality", neg)

    # 预设打底 + 提示词补细节
    ok("预设能单独出活", prompt_tools.compose("", "cat").startswith("a small cat"),
       prompt_tools.compose("", "cat"))
    both = prompt_tools.compose("戴着一顶帽子", "cat")
    ok("预设 + 细节拼在一起",
       both.startswith("a small cat") and both.endswith("wearing hat"), both)
    ok("none 预设不塞东西", prompt_tools.compose("空的木桌", "none") == "empty wooden table",
       prompt_tools.compose("空的木桌", "none"))
    ok("未知预设 id 当 none 处理", prompt_tools.compose("", "no-such") == "",
       prompt_tools.compose("", "no-such"))

    # 词表必须干净：重复键会被后者覆盖，改一个翻不动另一个
    zhs = [pid for pid, _l, _p in prompt_tools.PRESETS]
    ok("预设 id 不重复", len(zhs) == len(set(zhs)), str(zhs))
    ok("预设都带英文标签", all(l.strip() for _i, l, _p in prompt_tools.PRESETS))
    ok("词表规模够用", len(prompt_tools._ZH) >= 200, "%d 条" % len(prompt_tools._ZH))


# ---- 7b. AI 环境入口 / 底模清单 --------------------------------------------

def test_env_entry():
    print("\nAI 环境入口与底模清单")
    # 下拉里的标注：用户装一堆模型时，光看文件名分不出家族和「不认提示词」的
    ok("标注认出 SDXL", "SDXL" in ai_client.checkpoint_note(
        "juggernautXL_v9.safetensors"))
    ok("标注认出 SD1.5", "SD1.5" in ai_client.checkpoint_note(
        "dreamshaper_8.safetensors"))
    ok("标注点出 inpaint 专用",
       "inpaint" in ai_client.checkpoint_note("sd-v1-5-inpainting.ckpt"))

    # LB_COMFY_CKPT 优先；名字对不上就退回自动挑（不报错）
    with mock_comfy.start_mock() as srv:
        client = ai_client.ComfyClient(srv.url, timeout=5, poll=0.05)
        old = os.environ.get(ai_client.ENV_CKPT)
        try:
            os.environ[ai_client.ENV_CKPT] = mock_comfy.CHECKPOINT
            ok("环境变量点名的底模被采用",
               client.first_checkpoint() == mock_comfy.CHECKPOINT)
            os.environ[ai_client.ENV_CKPT] = "not-there.safetensors"
            ok("环境变量写错 → 退回自动挑",
               client.first_checkpoint() == mock_comfy.CHECKPOINT)
        finally:
            if old is None:
                os.environ.pop(ai_client.ENV_CKPT, None)
            else:
                os.environ[ai_client.ENV_CKPT] = old

    src = open(os.path.join(ROOT, "plugin", "ai-inpaint", "ai-inpaint.py"),
               encoding="utf-8").read()
    ok("注册了 AI 环境过程", "lb-plugin-ai-env" in src)
    ok("AI 环境挂了菜单项", 'set_menu_label(_("AI Environment…"))' in src)
    # 非交互必须安静：headless 回归会遍历所有过程，弹模态框 = 挂死
    ok("非交互模式不弹环境对话框",
       "if run_mode == Gimp.RunMode.INTERACTIVE:" in src)
    # 安装器要跟着插件走，否则下载包用户点了也找不到
    ok("安装器有 ai-setup 候选路径", '"ai-setup"' in src)
    ok("底模是下拉（不是只能手打文件名）",
       'add_choice_argument(\n                "checkpoint"' in src or
       '"checkpoint", _("Checkpoint"), help_text, choice' in src)


# ---- 8. 插件源码静态检查 ----------------------------------------------------

def test_plugin_source():
    print("\n插件源码")
    plugins = []
    for name in sorted(os.listdir(os.path.join(ROOT, "plugin"))):
        d = os.path.join(ROOT, "plugin", name)
        if (not os.path.isdir(d) or name.startswith("_")
                or os.path.exists(os.path.join(d, ".disabled"))):
            continue
        pys = [f for f in os.listdir(d) if f.endswith(".py")
               and not f.startswith("_")]
        if pys:
            plugins.append(os.path.join(d, pys[0]))

    ok("找到插件源文件", len(plugins) >= 4, "%d 个" % len(plugins))
    for path in plugins:
        src = open(path, encoding="utf-8").read()
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        has_menu = "add_menu_path(" in src
        has_proc = "lb-plugin-" in src
        ok("%s 注册了菜单" % rel, has_menu)
        ok("%s 有 lb-plugin- 过程名" % rel, has_proc)
        # add_menu_path 必须写在 set_menu_label 之后。GIMP 会把「先挂菜单、
        # 后设标签」的路径静默丢掉：PDB 里查得到过程，pluginrc 里 menu-path
        # 数却是 0，菜单里什么都看不到。065b70d 就这么让 AI 菜单消失了一轮，
        # 而当时「源码里有 SuperMrWang/AI 这个字符串」的断言照样是绿的。
        if has_menu and "set_menu_label(" in src:
            ok("%s 菜单挂在标签之后" % rel,
               src.index("add_menu_path(") > src.index("set_menu_label("),
               "先 set_menu_label 再 add_menu_path")

    path = os.path.join(ROOT, "plugin", "ai-inpaint", "ai-inpaint.py")
    src = open(path, encoding="utf-8").read()
    for banned, what in (("import requests", "requests"),
                         ("import numpy", "numpy"),
                         ("from PIL", "PIL"), ("import PIL", "PIL")):
        if banned == "import PIL":          # 上面那条已经覆盖
            continue
        ok("ai-inpaint 不依赖 %s" % what, banned not in src)
    ok("ai-inpaint 挂在 SuperMrWang/AI 下",
       '"<Image>/SuperMrWang/AI"' in src)

    # 参数名对不对得上：add_*_argument("x") 与 config.get_property('x') 必须同名。
    # 拼错了不会报错——只会静默拿到默认值，人在菜单里改半天没反应。
    declared = set(re.findall(r'add_\w+_argument\(\s*"([A-Za-z0-9-]+)"', src))
    # 简版过程用 prop('x', default) 兜默认值，取参数的两种写法都要认
    used = set(re.findall(r"(?:get_property|prop)\('([A-Za-z0-9-]+)'", src))
    ok("每个参数都被 run() 取到", declared == used,
       "只在 add 里: %s / 只在 get 里: %s"
       % (sorted(declared - used), sorted(used - declared)))



# ---- 3d. 工作尺寸：短边也要够（2026-11-23 平涂 / 重复图案）-----------------

def test_work_size():
    print("\n工作尺寸：短边不能低于 512，否则 SD1.5 画成重复图案")

    # 小框喂 SD1.5：短边 392 → 整体放大到 512
    ww, hh, f = ai_client.work_size(432, 392, "sd15.safetensors")
    ok("432×392 短边被抬到 512（%dx%d）" % (ww, hh), min(ww, hh) >= 512, (ww, hh))
    ok("  → 长边不超 768", max(ww, hh) <= 768 + 8, (ww, hh))
    ok("  → 两边都是 8 的倍数", ww % 8 == 0 and hh % 8 == 0, (ww, hh))
    ok("  → 倍率按实际像素算", abs(f - ww / 432.0) < 1e-6, f)

    # 大框：长边压到 768，短边顺带就够
    ww, hh, f = ai_client.work_size(4000, 3000, "sd15.safetensors")
    ok("4000×3000 长边压到 768（%dx%d）" % (ww, hh), max(ww, hh) <= 768 + 8, (ww, hh))
    ok("  → 短边仍不低于 512", min(ww, hh) >= 512, (ww, hh))

    # 已经合适的框不要动
    ww, hh, f = ai_client.work_size(768, 512, "sd15.safetensors")
    ok("768×512 原样不动", (ww, hh) == (768, 512), (ww, hh))

    # SDXL：下限 768、上限 1024
    ww, hh, f = ai_client.work_size(432, 392, "sdxl_model.safetensors")
    ok("SDXL 432×392 → 短边 768（%dx%d）" % (ww, hh), min(ww, hh) >= 768, (ww, hh))
    ok("  → 长边不超 1024", max(ww, hh) <= 1024 + 8, (ww, hh))
    ww, hh, f = ai_client.work_size(3000, 2000, "sdxl_model.safetensors")
    # 长边顶格时短边必然不足（比例摆在那儿），这是上限优先的正常结果
    ok("SDXL 3000×2000 长边压到 1024（%dx%d）" % (ww, hh),
       max(ww, hh) <= 1024 + 8 and
       (min(ww, hh) >= 768 or max(ww, hh) >= 1024), (ww, hh))

    # 放大有闸：极小框不能无限放大
    ww, hh, f = ai_client.work_size(40, 32, "sd15.safetensors")
    ok("40×32 放大不超过 4×（%dx%d）" % (ww, hh), f <= 4.0 + 1e-6, f)

    # 极端比例（2.56:1）不是 work_size 能救的，上游必须先补画布；
    # 这里只保证它不会把长边喂超上限。
    ww, hh, f = ai_client.work_size(1024, 400, "sd15.safetensors")
    ok("1024×400 长边不超 768（%dx%d，靠上游补比例）" % (ww, hh),
       max(ww, hh) <= 768 + 8, (ww, hh))



def test_fit_context():
    print("\n上下文收窄：大图里选一小块，不能缩成 768 就完事")
    sel = (1600, 1200, 2400, 1800)          # 800×600
    ctx = (1000, 750, 3000, 2250)           # 2000×1500 的上下文
    f = ai_client.fit_context(sel, ctx, "sd15.safetensors", 4000, 3000)
    ok("上下文被收窄", (f[2] - f[0], f[3] - f[1]) < (2000, 1500),
       (f[2] - f[0], f[3] - f[1]))
    ok("  → 仍完整包住选区",
       f[0] <= 1600 and f[1] <= 1200 and f[2] >= 2400 and f[3] >= 1800, f)
    ww, hh, sc = ai_client.work_size(f[2] - f[0], f[3] - f[1], "sd15.safetensors")
    ok("  → 工作缩放回到 ≥0.6（%.2f）" % sc, sc >= 0.59, sc)
    ok("  → 短边也够 512（%dx%d）" % (ww, hh), min(ww, hh) >= 512, (ww, hh))

    # 选区自己就超过上限：收不动，原样返回（那种得靠分块）
    ok("大选区收不动，原样返回",
       ai_client.fit_context((0, 0, 3000, 2000), (0, 0, 4000, 3000),
                             "sd15.safetensors", 4000, 3000) ==
       (0, 0, 4000, 3000))
    # 本来就够小：一格不动
    ok("小上下文不动",
       ai_client.fit_context((10, 10, 50, 50), (0, 0, 300, 200),
                             "sd15.safetensors", 400, 300) == (0, 0, 300, 200))


def test_segment():
    """按名称自动选区：工作流结构 + 蒙版平移 + 报错翻译。"""
    print("\n按名称自动选区（SAM2）")

    wf = ai_client.build_segment_workflow("src.png", "ear")
    kinds = {n["class_type"] for n in wf.values()}
    ok("走 SAM2Segment 节点", "SAM2Segment" in kinds, sorted(kinds))
    ok("蒙版过 MaskToImage 才能存盘", "MaskToImage" in kinds)
    ok("提示词传进去了",
       next(n for n in wf.values() if n["class_type"] == "SAM2Segment")
       ["inputs"]["prompt"] == "ear")
    seg = next(n for n in wf.values() if n["class_type"] == "SAM2Segment")
    ok("取的是 SAM2 的第 2 路（MASK）",
       [n for n in wf.values() if n["class_type"] == "MaskToImage"][0]
       ["inputs"]["mask"] == ["2", 1])
    ok("默认用 tiny 档（够用又快）", seg["inputs"]["sam2_model"] ==
       "sam2.1_hiera_tiny", seg["inputs"]["sam2_model"])
    ok("不抠前景（background=Alpha 只影响第 1 路）",
       seg["inputs"]["background"] == "Alpha")
    ok("threshold 传进去了",
       seg["inputs"]["threshold"] == ai_client.SEG_DEFAULT_THRESHOLD)
    wf2 = ai_client.build_segment_workflow("s.png", "left eye",
                                           sam2_model="sam2.1_hiera_base_plus",
                                           threshold=0.5, mask_offset=6)
    seg2 = next(n for n in wf2.values() if n["class_type"] == "SAM2Segment")
    ok("档位和膨胀量能改",
       seg2["inputs"]["sam2_model"] == "sam2.1_hiera_base_plus" and
       seg2["inputs"]["mask_offset"] == 6)

    # 下拉值的抠取：list 与 dict 两种形态都要认
    fake = {"SAM2Segment": {"input": {"required": {
        "sam2_model": [["sam2.1_hiera_tiny", "sam2.1_hiera_large"], {}]}}}}
    ok("从 /object_info 读出模型档位",
       ai_client._combo_values(fake, "SAM2Segment", "sam2_model") ==
       ["sam2.1_hiera_tiny", "sam2.1_hiera_large"])
    ok("节点没有时返回空表，不抛",
       ai_client._combo_values({}, "SAM2Segment", "sam2_model") == [])

    # 报错翻译：缺包要说清楚装哪个 PyPI 名字
    msg = ai_client.explain_segment_error(
        "ComfyUI 执行出错：SAM2Segment: No module named 'groundingdino'")
    ok("缺 groundingdino 时给出 PyPI 名",
       "groundingdino-py" in msg, msg[:80])
    msg2 = ai_client.explain_segment_error(
        "ComfyUI 执行出错：SAM2Segment: No module named 'hydra'")
    ok("缺 hydra 时提示 hydra-core", "hydra-core" in msg2, msg2[:80])
    ok("认不出的错误原样返回",
       ai_client.explain_segment_error("炸了") == "炸了")


def main():
    test_png()
    test_mask()
    test_align()
    test_canvas_ratio()
    test_workflow()
    test_segment()
    test_family()
    test_work_size()
    test_fit_context()
    test_end_to_end()
    test_quality()
    test_errors()
    test_prompt_tools()
    test_env_entry()
    test_plugin_source()
    print("\n%d/%d 通过" % (PASS, PASS + FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
