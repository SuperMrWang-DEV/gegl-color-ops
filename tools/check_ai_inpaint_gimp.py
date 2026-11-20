# -*- coding: utf-8 -*-
"""回归：AI 局部重绘插件在真 GIMP 里的行为（用 mock 服务，不需要显卡）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_ai_inpaint_gimp.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gimp / Gegl 的 GI 绑定）。这里只测插件自己那
一半——选区怎么变蒙版、裁切框怎么对齐、结果怎么贴回去：

1. 传给 ComfyUI 的蒙版是「选区内 = 白 = 要重绘」，且读的是**可见合成**（图层
   带偏移、比画布小时，界外取到的是下面的图层，不是黑色）；
2. 贴回来的图层尺寸/偏移与裁切框一致，选区内换成新像素、选区外一个像素不动；
3. 图层蒙版取的是羽化过的「AI Mask」通道，keep-mask=False 时通道收走；
4. 没选区、提示词为空这两种误用要给得出人话。
"""
import os
import sys
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl


def _find_repo():
    """定位仓库根目录：本文件被 GIMP 用 exec 读进来时 __file__ 不可靠。"""
    cands = []
    try:
        cands.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except NameError:
        pass
    cwd = os.getcwd()
    cands += [cwd, os.path.join(cwd, "SuperMrWang"),
              os.path.join(cwd, "..", "SuperMrWang")]
    for c in cands:
        if os.path.exists(os.path.join(c, "plugin", "ai-inpaint",
                                       "ai-inpaint.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


ROOT = _find_repo()
PLUG = os.path.join(ROOT, "plugin", "ai-inpaint", "ai-inpaint.py")
# 被 GIMP exec 进来时没有 __file__，sys.path 里也没有 tools/，手动补上
sys.path.insert(0, os.path.join(ROOT, "tools"))

spec = importlib.util.spec_from_file_location("ai_inpaint_plugin", PLUG)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

import ai_client                                     # noqa: E402  (插件已把它挂上)
import mock_comfy                                     # noqa: E402

FAIL = []


def check(label, cond, detail=""):
    print("%-46s %-34s %s" % (label, detail, "OK" if cond else "FAIL"))
    if not cond:
        FAIL.append(label)


def px(drawable, x, y):
    """图层本地坐标的 RGBA（8 位）。"""
    raw = drawable.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                                    "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    b = bytes(bytearray(raw))
    return tuple(b[:4])


def new_image(w, h, rgb, alpha=255):
    """一张纯色底图。用 GEGL shadow buffer 直接灌色，比 PDB 的 fill 少绕一层。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(img, "bg", w, h, Gimp.ImageType.RGBA_IMAGE, 100.0,
                           Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    solid = (bytes((rgb[0], rgb[1], rgb[2], alpha)) * (w * h))
    shadow = layer.get_shadow_buffer()
    shadow.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", solid)
    shadow.flush()
    layer.merge_shadow(True)
    img.set_selected_layers([layer])
    return img, layer


# ---------------- 1. 正常流程：选区居中，选区内换新像素 ----------------
srv = mock_comfy.start_mock()
try:
    # 画布比选区大不少，裁切框（选区 + 一圈上下文）才会小于画布——只有这时
    # 「贴回位置」这条断言才有意义
    W, H = 200, 160
    img, layer = new_image(W, H, (200, 180, 160))
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 80, 60, 40, 30)

    client = ai_client.ComfyClient(srv.url, timeout=10, poll=0.05)
    out, info = mod.ai_inpaint(img, layer, "a red apple", negative="blurry",
                               client=client, grow=0, feather=0, steps=8,
                               timeout=30)

    check("返回了新图层", out is not None and out.get_name() == "AI Inpaint",
          out.get_name() if out else "None")
    check("图层挂了蒙版", out.get_mask() is not None)
    check("画布尺寸不变", (img.get_width(), img.get_height()) == (W, H),
          "%dx%d" % (img.get_width(), img.get_height()))
    x, y, w, h = info["rect"]
    check("裁切框对齐 8", w % 8 == 0 and h % 8 == 0, "%dx%d@%d,%d" % (w, h, x, y))
    check("贴回位置＝裁切框原点", out.get_offsets()[1:] == (x, y),
          str(out.get_offsets()[1:]))
    check("贴回尺寸＝裁切框", (out.get_width(), out.get_height()) == (w, h),
          "%dx%d" % (out.get_width(), out.get_height()))

    # 图层本地坐标：选区左上角 (80,60) 相对裁切框
    lx, ly = 80 - x, 60 - y
    check("选区内＝重绘色", px(out, lx + 8, ly + 8)[:3] == mock_comfy.FILL_RGB,
          str(px(out, lx + 8, ly + 8)))
    check("选区外＝原像素", px(out, 2, 2)[:3] == (200, 180, 160),
          str(px(out, 2, 2)))
    check("圆角外角（框内选区外）也原样",
          px(out, w - 3, h - 3)[:3] == (200, 180, 160),
          str(px(out, w - 3, h - 3)))

    names = [c.get_name() for c in img.get_channels()]
    check("留下了 AI Mask 通道", "AI Mask" in names, str(names))

    # 蒙版是羽化过的选区：选区中心 255，角落 0（这里 feather=0，所以是硬边）
    mask = out.get_mask()
    center = mask.get_buffer().get(
        Gegl.Rectangle.new(lx + 8, ly + 8, 1, 1), 1.0, "Y u8",
        Gegl.AbyssPolicy.NONE)
    check("蒙版中心=255", bytes(bytearray(center))[0] > 250,
          str(bytes(bytearray(center))[0]))
    corner = mask.get_buffer().get(Gegl.Rectangle.new(1, 1, 1, 1), 1.0, "Y u8",
                                   Gegl.AbyssPolicy.NONE)
    check("蒙版角落=0", bytes(bytearray(corner))[0] < 5,
          str(bytes(bytearray(corner))[0]))

    # ---------------- 2. keep_mask=False 收走通道 ----------------
    img2, l2 = new_image(64, 48, (120, 140, 180))
    img2.select_rectangle(Gimp.ChannelOps.REPLACE, 16, 16, 16, 16)
    mod.ai_inpaint(img2, l2, "x", client=client, grow=0, feather=0, steps=4,
                   timeout=30, keep_mask=False)
    check("keep_mask=False 不留通道", not img2.get_channels(),
          str([c.get_name() for c in img2.get_channels()]))

    # ---------------- 3. 图层比画布小 + 带偏移：读的是可见合成 ----------------
    img3, bg3 = new_image(200, 160, (10, 10, 10))
    small = Gimp.Layer.new(img3, "small", 60, 50, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img3.insert_layer(small, None, 0)
    small.set_offsets(70, 55)
    solid = bytes((200, 100, 50, 255)) * (60 * 50)
    shadow = small.get_shadow_buffer()
    shadow.set(Gegl.Rectangle.new(0, 0, 60, 50), "R'G'B'A u8", solid)
    shadow.flush()
    small.merge_shadow(True)
    img3.set_selected_layers([small])
    img3.select_rectangle(Gimp.ChannelOps.REPLACE, 80, 65, 20, 20)
    out3, info3 = mod.ai_inpaint(img3, small, "x", client=client, grow=0,
                                 feather=0, steps=4, timeout=30)
    x3, y3, w3, h3 = info3["rect"]
    check("小图层场景：裁切框小于画布", (w3, h3) != (200, 160), "%dx%d" % (w3, h3))
    got = px(out3, 90 - x3, 75 - y3)[:3]
    check("小图层场景：选区内仍是重绘色", got == mock_comfy.FILL_RGB, str(got))
    check("小图层场景：贴回偏移正确", out3.get_offsets()[1:] == (x3, y3),
          str(out3.get_offsets()[1:]))
    # 小图层没盖到的地方（裁切框左上角）应当取到下面的背景层，而不是黑
    got_bg = px(out3, 1, 1)[:3]
    check("合成取到的是背景图层（不是黑）", got_bg == (10, 10, 10), str(got_bg))
    check("小图层内部原像素也在", px(out3, 72 - x3, 57 - y3)[:3] == (200, 100, 50),
          str(px(out3, 72 - x3, 57 - y3)))

    # ---------------- 4. 误用 ----------------
    img4, l4 = new_image(32, 32, (100, 100, 100))
    img4.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 0, 0)   # 清掉选区
    try:
        mod.ai_inpaint(img4, l4, "x", client=client)
        check("没有选区 → 报错", False, "居然跑通了")
    except RuntimeError as exc:
        # 文案跟界面语言走（英文 msgid + zh 译文），断言只看关键词
        msg = str(exc).lower()
        check("没有选区 → 报错", "selection" in msg or "选区" in msg, msg[:28])

    img4.select_rectangle(Gimp.ChannelOps.REPLACE, 4, 4, 8, 8)
    try:
        mod.ai_inpaint(img4, l4, "   ", client=client)
        check("提示词为空 → 报错", False, "居然跑通了")
    except RuntimeError as exc:
        msg = str(exc).lower()
        check("提示词为空 → 报错", "prompt" in msg or "提示词" in msg, msg[:28])
        # 报错要说清「写结果，不是写要删的东西」，否则用户下次还是这么填
        check("空提示词的报错教了怎么写",
              "result" in msg or "结果" in msg, msg[:40])

    # 中文提示词必须拦下来：SD1.5/SDXL 的文本编码器只认英文，中文等于噪声。
    # 这是「画出来跟图完全不搭」的头号原因，静默送下去只会让用户以为模型不行。
    for bad in ("把瓶子去掉", "空桌子", "かわいい"):
        try:
            mod.ai_inpaint(img4, l4, bad, client=client)
            check("中文/日文提示词 → 报错（%s）" % bad, False, "居然跑通了")
        except RuntimeError as exc:
            msg = str(exc).lower()
            check("中文/日文提示词 → 报错（%s）" % bad,
                  "english" in msg or "英文" in msg, msg[:30])

    # 反过来：正常英文不能误伤（含全角标点以外的 ASCII 标点、数字、连字符）
    try:
        check("英文提示词不被误拦",
              mod._check_prompt("Empty wooden table, 35mm, soft-daylight") != "")
    except Exception as exc:
        check("英文提示词不被误拦", False, str(exc)[:40])

    # 默认值必须是空：预填一句通用文案，点确定的人就会得到一块无关的色块
    check("DEFAULT_PROMPT 为空（不预填内容）", mod.DEFAULT_PROMPT == "",
          repr(mod.DEFAULT_PROMPT))

    # GIMP 会把没删掉的图像当成「插件漏出来的」报到日志里，收尾清干净
    for im in (img, img2, img3, img4):
        im.delete()
finally:
    srv.stop()

print("\n%s" % ("全部通过" if not FAIL else "失败：%s" % ", ".join(FAIL)))
