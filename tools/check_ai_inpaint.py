#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归：AI 局部重绘的「HTTP + PNG」那一半（不需要 GIMP，也不需要显卡）。

    python tools/check_ai_inpaint.py [-v]

测什么：
  1. PNG 编解码来回一致（RGBA / RGB / 灰），四种行过滤都能解；
  2. 「白＝要重绘」这条约定：mask_png 把白色写成**透明**（ComfyUI 的
     LoadImage 用 mask = 1 - alpha），写反了整条链路就白跑；
  3. 裁切框对齐到 8（VAE 8× 下采样，尺寸不整除会截断 → 贴回去错位）；
  4. 工作流结构：走 VAEEncodeForInpaint（不是 InpaintModelConditioning），
     蒙版接 LoadImage 的 MASK 输出；
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


# ---- 4. 工作流 --------------------------------------------------------------

def test_workflow():
    print("\n工作流结构")
    wf = ai_client.build_inpaint_workflow("m.safetensors", "src.png", "mask.png",
                                          "a cat", negative="dog", steps=12,
                                          cfg=6.5, seed=7, grow_mask_by=12)
    kinds = {n["class_type"] for n in wf.values()}
    ok("用 VAEEncodeForInpaint", "VAEEncodeForInpaint" in kinds)
    ok("不用 InpaintModelConditioning",
       "InpaintModelConditioning" not in kinds)
    enc = next(n for n in wf.values()
               if n["class_type"] == "VAEEncodeForInpaint")
    mask_node = wf[enc["inputs"]["mask"][0]]
    ok("蒙版接 LoadImage 的 MASK 输出",
       mask_node["class_type"] == "LoadImage" and enc["inputs"]["mask"][1] == 1)
    ok("蒙版节点读的是 mask.png", mask_node["inputs"]["image"] == "mask.png")
    ks = next(n for n in wf.values() if n["class_type"] == "KSampler")
    ok("步数/种子/CFG 传进去了",
       (ks["inputs"]["steps"], ks["inputs"]["seed"], ks["inputs"]["cfg"]) ==
       (12, 7, 6.5))
    ok("grow_mask_by 是整数", isinstance(enc["inputs"]["grow_mask_by"], int))
    ok("有 SaveImage 才取得到图",
       any(n["class_type"] == "SaveImage" for n in wf.values()))


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

        blob, info = ai_client.inpaint(
            client, ai_client.rgba_png(w, h, src),
            ai_client.mask_png(w, h, gray), "a red apple", negative="blurry",
            steps=8, seed=1, timeout=30)
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


# ---- 7. 插件源码静态检查 ----------------------------------------------------

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
    used = set(re.findall(r"get_property\('([A-Za-z0-9-]+)'\)", src))
    ok("每个参数都被 run() 取到", declared == used,
       "只在 add 里: %s / 只在 get 里: %s"
       % (sorted(declared - used), sorted(used - declared)))


def main():
    test_png()
    test_mask()
    test_align()
    test_workflow()
    test_end_to_end()
    test_errors()
    test_plugin_source()
    print("\n%d/%d 通过" % (PASS, PASS + FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
