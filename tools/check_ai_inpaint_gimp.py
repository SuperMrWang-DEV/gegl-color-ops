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
OK = 0


def check(label, cond, detail=""):
    global OK
    OK += 1
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
    # 这一段的断言全是「贴回位置 / 尺寸 / 蒙版 / 原始像素」，所以关掉多候选
    # 与后处理：接缝补偿会把 mock 的固定填色往周围拉（那是另一条用例的事）。
    out, info = mod.ai_inpaint(img, layer, "a red apple", negative="blurry",
                               client=client, grow=0, feather=0, steps=8,
                               timeout=30, variations=1,
                               fix_seams=False, match_grain=False)

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

    # ---- 多候选：一次出三张，只留最好的可见 ------------------------------
    img3, layer3 = new_image(200, 160, (120, 150, 190))
    img3.select_rectangle(Gimp.ChannelOps.REPLACE, 70, 50, 60, 50)
    out3, info3 = mod.ai_inpaint(img3, layer3, "a red apple", client=client,
                                 grow=0, feather=0, steps=8, timeout=30,
                                 variations=3)
    check("一次出了 3 张", info3.get("variations") == 3, info3.get("variations"))
    ranked = [ly for ly in img3.get_layers()
              if ly.get_name().startswith("AI Inpaint ")]
    check("图上多了 3 个候选图层", len(ranked) == 3,
          [ly.get_name() for ly in ranked])
    check("只有一张可见", sum(1 for ly in ranked if ly.get_visible()) == 1,
          [(ly.get_name(), ly.get_visible()) for ly in ranked])
    best = (info3.get("order") or [0])[0]
    check("可见的是排第一那张",
          out3.get_visible() and out3.get_name().startswith(
              "AI Inpaint %d " % (best + 1)), out3.get_name())
    check("名字里带分数", "(" in out3.get_name(), out3.get_name())
    check("order 覆盖全部候选",
          sorted(info3.get("order") or []) == [0, 1, 2], info3.get("order"))

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

    # 中文提示词：常用词现在直接翻成英文（用户脑子里的话就是「画一只小猫」），
    # 翻不掉的词才报错点名——绝不能把半截中文静默送进模型（那等于随机重绘）。
    try:
        got = mod._check_prompt("画一只小猫")
        check("中文提示词被翻成英文", got == "small kitten", got)
    except Exception as exc:
        check("中文提示词被翻成英文", False, str(exc)[:40])

    try:
        mod._check_prompt("嘎嘎嘎的怪兽")
        check("翻不掉的中文 → 报错", False, "居然放过了")
    except RuntimeError as exc:
        check("翻不掉的中文 → 报错", "嘎" in str(exc) or "dictionary" in str(exc),
              str(exc)[:36])

    # 日文/韩文压根不在词表里，仍然要拦（真实原因是编码器不认，不是我们懒）
    for bad in ("かわいい", "귀여운"):
        try:
            mod._check_prompt(bad)
            check("日文/韩文提示词 → 报错（%s）" % bad, False, "居然跑通了")
        except RuntimeError as exc:
            check("日文/韩文提示词 → 报错（%s）" % bad,
                  "dictionary" in str(exc) or "英文" in str(exc), str(exc)[:30])

    # 预设：选了「小猫」，提示词可以只写细节，也可以完全空着
    got = mod._check_prompt("", "cat")
    check("预设能单独出提示词", got.startswith("a small cat"), got)
    got = mod._check_prompt("戴着一顶帽子", "cat")
    check("预设 + 中文细节", got.startswith("a small cat") and "hat" in got, got)
    try:
        mod._check_prompt("", "none")
        check("空提示词 + 无预设 → 报错", False, "居然跑通了")
    except RuntimeError as exc:
        check("空提示词 + 无预设 → 报错", "prompt" in str(exc).lower(), str(exc)[:28])

    # 反过来：正常英文不能误伤（含全角标点以外的 ASCII 标点、数字、连字符）
    try:
        check("英文提示词不被误拦",
              mod._check_prompt("Empty wooden table, 35mm, soft-daylight") != "")
    except Exception as exc:
        check("英文提示词不被误拦", False, str(exc)[:40])

    # 默认值必须是空：预填一句通用文案，点确定的人就会得到一块无关的色块
    check("DEFAULT_PROMPT 为空（不预填内容）", mod.DEFAULT_PROMPT == "",
          repr(mod.DEFAULT_PROMPT))

    # ---------------- erase 预设：把「这一格要留空」传到打分器 --------------
    # 抹除的候选判据和插入相反（填得平是好事）。判据开关由 preset 决定，
    # 别指望「提示词为空」——提示词是必填的，那条老路永远走不到。
    img5, l5 = new_image(200, 160, (150, 150, 150))
    img5.select_rectangle(Gimp.ChannelOps.REPLACE, 70, 50, 60, 50)
    _o5, info5 = mod.ai_inpaint(img5, l5, "empty grey wall", client=client,
                                grow=0, feather=0, steps=4, timeout=30,
                                variations=1, preset="erase")
    check("erase 预设 → 走抹除判据", info5.get("removal") is True,
          info5.get("removal"))

    img6, l6 = new_image(200, 160, (150, 150, 150))
    img6.select_rectangle(Gimp.ChannelOps.REPLACE, 70, 50, 60, 50)
    _o6, info6 = mod.ai_inpaint(img6, l6, "a red apple", client=client,
                                grow=0, feather=0, steps=4, timeout=30,
                                variations=1, preset="none")
    check("普通预设 → 不误判成抹除", info6.get("removal") is False,
          info6.get("removal"))

    # ---------------- 6. 候选挑选窗 ----------------
    # 多候选以前只是图层面板里几个隐藏图层（名字带罚分），不点眼睛看不见。
    # 现在给一个能点的窗口：缩略图并排、默认选中打分最优那张、确认后重排图层。
    picker = mod._picker
    check("挑选器模块加载上了", picker is not None)
    if picker is not None:
        check("GIMP 里能建 GTK 窗口（pycairo 在）", picker.available() is True)

        # 缩略图裁切：候选图层通常是「选区的好几倍高」，整块缩下去三张一模一样
        lw, lh = 744, 496
        box = picker._crop_box(lw, lh, (10, 376, 470, 120))
        check("裁切窗口存在", box is not None, str(box))
        if box:
            bx, by, bw, bh = box
            inside = (bx <= 10 and by <= 376 and bx + bw >= 480
                      and by + bh >= 496)
            check("裁切窗口包住整个选区", inside, "%s vs 选区 10,376,470,120" % (box,))
            check("裁切窗口不越出图层",
                  0 <= bx and 0 <= by and bx + bw <= lw and by + bh <= lh, str(box))
            check("裁切窗口比整层小（真的裁了）", bw * bh < lw * lh,
                  "%dx%d < %dx%d" % (bw, bh, lw, lh))
        check("整层就是选区时退回整层（不做无意义的裁切）",
              picker._crop_box(100, 100, (0, 0, 100, 100)) is None)
        check("没有选区信息就返回 None", picker._crop_box(100, 100, None) is None)
        check("零尺寸选区不炸", picker._crop_box(100, 100, (5, 5, 0, 0)) is None)
        # 选区贴在图层角上：窗口要被夹回图层内，而不是算出负坐标
        edge = picker._crop_box(300, 200, (0, 0, 20, 20))
        check("选区贴角时窗口不越界",
              edge is None or (edge[0] >= 0 and edge[1] >= 0
                               and edge[0] + edge[2] <= 300
                               and edge[1] + edge[3] <= 200), str(edge))

        # ---- 建窗：默认选中、点击切换、保留开关 ----
        img7 = Gimp.Image.new(160, 120, Gimp.ImageBaseType.RGB)
        cands7 = []
        for i, col in enumerate(((200, 60, 60), (60, 200, 60), (60, 60, 200))):
            lay = Gimp.Layer.new(img7, "cand%d" % i, 160, 120,
                                 Gimp.ImageType.RGBA_IMAGE, 100.0,
                                 Gimp.LayerMode.NORMAL)
            img7.insert_layer(lay, None, 0)
            shadow = lay.get_shadow_buffer()
            shadow.set(Gegl.Rectangle.new(0, 0, 160, 120), "R'G'B'A u8",
                       bytes((col[0], col[1], col[2], 255)) * (160 * 120))
            shadow.flush()
            lay.merge_shadow(True)
            cands7.append(lay)

        dlg, pctx = picker.build_dialog(cands7, [1, 0, 2], [1.20, 2.00, 3.00],
                                        focus=(40, 40, 60, 40))
        check("窗口建出来了（不 run）", dlg is not None)
        check("默认选中打分最优那张（order[0]）",
              pctx["values"]()["index"] == 1, str(pctx["values"]()))
        check("三个缩略图都画好了", len(pctx["areas"]) == 3, str(len(pctx["areas"])))
        check("默认保留其余候选", pctx["values"]()["keep_all"] is True)
        pctx["select"](2)
        check("点第三张就选中第三张", pctx["values"]()["index"] == 2,
              str(pctx["values"]()))
        pctx["select"](99)
        check("越界点击不改变选择", pctx["values"]()["index"] == 2,
              str(pctx["values"]()))
        pctx["select"](-5)
        check("负数下标不改变选择", pctx["values"]()["index"] == 2,
              str(pctx["values"]()))
        pctx["keep"].set_active(False)
        check("取消勾选 → 其余候选会被删",
              pctx["values"]()["keep_all"] is False, str(pctx["values"]()))
        labels = [lb.get_text() for lb in pctx["labels"]]
        check("标签写了序号", labels[0].startswith("#1"), str(labels))
        check("标签带分数", "2.00" in labels[0] or "1.20" in labels[0], str(labels))
        dlg.destroy()
        img7.delete()

    # ---- 用户挑了非最优那张：图层要按选择重排 / 删减 ----
    if picker is not None:
        orig_choose = picker.choose
        img8, l8 = new_image(200, 160, (150, 150, 150))
        img8.select_rectangle(Gimp.ChannelOps.REPLACE, 70, 50, 60, 50)
        try:
            picker.choose = lambda *a, **kw: {"index": 1, "keep_all": True}
            out8, info8 = mod.ai_inpaint(
                img8, l8, "a red apple", client=client, grow=0, feather=0,
                steps=4, timeout=30, variations=3, pick="auto",
                fix_seams=False, match_grain=False)
        finally:
            picker.choose = orig_choose
        kept = [it for it in img8.get_layers()
                if it.get_name().startswith("AI Inpaint")]
        check("保留其余候选：三张都在", len(kept) == 3, len(kept))
        check("可见的是用户选的那张", out8 is kept[1] and out8.get_visible(),
              out8.get_name())
        check("其余候选是隐藏的",
              not any(it.get_visible() for it in kept if it is not out8))
        check("picked 记下了是用户挑的",
              info8.get("picked", {}).get("by") == "user", str(info8.get("picked")))
        img8.delete()

        # 同一批候选，用户勾掉「保留其余」→ 只留一张，名字不带序号
        orig_choose = picker.choose
        img9, l9 = new_image(200, 160, (150, 150, 150))
        img9.select_rectangle(Gimp.ChannelOps.REPLACE, 70, 50, 60, 50)
        try:
            picker.choose = lambda *a, **kw: {"index": 2, "keep_all": False}
            out9, info9 = mod.ai_inpaint(
                img9, l9, "a red apple", client=client, grow=0, feather=0,
                steps=4, timeout=30, variations=3, pick="auto",
                fix_seams=False, match_grain=False)
        finally:
            picker.choose = orig_choose
        left = [it for it in img9.get_layers()
                if it.get_name().startswith("AI Inpaint")]
        check("不保留 → 只留一张", len(left) == 1, [it.get_name() for it in left])
        check("留下的是用户选的那张", out9 is left[0] and out9.get_visible())
        check("单张名字不带序号",
              left[0].get_name().startswith("AI Inpaint ("), left[0].get_name())
        check("picked 记下了索引", info9.get("picked", {}).get("index") == 2,
              str(info9.get("picked")))
        check("picked 记下了没保留", info9.get("picked", {}).get("kept_all") is False)
        img9.delete()

    # ---------------- 5. 两个入口的参数装配 ----------------
    # 简版只声明了 prompt / preset / negative，run() 里却要拼出完整参数表：
    # 少兜一个默认值就是 TypeError，用户看到的是「点菜单直接报错」。
    class _FakeProc(object):
        def __init__(self, name):
            self._name = name
        def get_name(self):
            return self._name
        def new_return_values(self, status, err):
            return (status, err)

    class _FakeCfg(object):
        def __init__(self, d):
            self._d = d
        def get_property(self, key):
            return self._d.get(key)

    def _wire(name, cfg_dict):
        seen = []

        def fake_inpaint(*a, **kw):
            seen.append((a, kw))
            return None, {}

        orig = mod.ai_inpaint
        mod.ai_inpaint = fake_inpaint
        try:
            status, _err = mod.AiInpaintPlugin.run(
                object(), _FakeProc(name), Gimp.RunMode.NONINTERACTIVE,
                object(), [object()], _FakeCfg(cfg_dict), None)
        finally:
            mod.ai_inpaint = orig
        return status, seen

    st, seen = _wire(mod.PROC_QUICK,
                     {"prompt": "一只小猫", "preset": "cat", "negative": None})
    check("简版能跑通（没声明的参数走默认值）",
          st == Gimp.PDBStatusType.SUCCESS and len(seen) == 1, str(st))
    if seen:
        args, kw = seen[0]
        check("简版把 prompt 原样递下去", args[2] == "一只小猫", repr(args[2]))
        check("简版把 preset 递给实现", kw.get("preset") == "cat", str(kw.get("preset")))
        check("简版 negative 空 → 空串（不是 None）", args[3] == "", repr(args[3]))
        check("简版 steps 默认 25", args[6] == 25, str(args[6]))
        check("简版 keep-mask 默认 True", args[14] is True, str(args[14]))
        check("简版 scale 默认 0", args[15] == 0.0, str(args[15]))
        # 批处理 / 重复上次绝不能弹挑选窗（弹了就是卡住的批处理任务）
        check("批处理不弹挑选窗", kw.get("pick") == "off", str(kw.get("pick")))

    st, seen = _wire(mod.PROC_ADVANCED,
                     {"prompt": "empty table", "preset": "none", "negative": "text",
                      "server": "http://x:1", "checkpoint": "m.ckpt", "steps": 9,
                      "cfg": 5.5, "seed": 42, "denoise": 0.6, "grow": 2,
                      "grow-mask-by": 4, "feather": 1.5, "timeout": 90,
                      "keep-mask": False, "scale": 1.0})
    check("高级版能跑通", st == Gimp.PDBStatusType.SUCCESS and len(seen) == 1, str(st))
    if seen:
        args, kw = seen[0]
        check("高级版读到了 steps", args[6] == 9, str(args[6]))
        check("高级版读到了 checkpoint", args[5] == "m.ckpt", str(args[5]))
        check("高级版读到了 seed", args[8] == 42, str(args[8]))
        check("高级版读到了 scale", args[15] == 1.0, str(args[15]))
        check("高级版 keep-mask=off 传下去", args[14] is False, str(args[14]))

    # 底模参数的形态取决于「注册那一刻 ComfyUI 在不在跑」：连得上就建成 Gimp.Choice
    # （乱写的名字会被拉回默认的 auto），连不上就退回文本框（原样收下，让用户手写
    # 文件名）。两种都是设计好的行为，所以这里按当时的状态分别验——否则同一份代码
    # 在有服务和没服务的机器上会一个绿一个红（2026-11-23 就撞上过）。
    proc = Gimp.get_pdb().lookup_procedure(mod.PROC_ADVANCED)
    if proc is not None:
        cfg = proc.create_config()
        default = cfg.get_property("checkpoint")
        cfg.set_property("checkpoint", "definitely-not-a-model.safetensors")
        got = cfg.get_property("checkpoint")
        online = bool(mod._available_checkpoints())
        if online:
            check("有底模时是下拉（乱写的名字被拒回默认值）", got == default,
                  "default=%r got=%r" % (default, got))
            check("有底模时默认值是 auto", default == mod.AUTO_CKPT, repr(default))
        else:
            check("没底模时退化成文本框（原样收下文件名）",
                  got == "definitely-not-a-model.safetensors",
                  "got=%r" % (got,))
            check("没底模时默认值为空", default in ("", None), repr(default))

        env_proc = Gimp.get_pdb().lookup_procedure(mod.PROC_ENV)
        check("注册了 AI 环境过程", env_proc is not None)

        # 「AI 环境」现在还要能**手选 ComfyUI 目录**并**自己起服务**：目录选择器
        # 和自动启动钩子只要缺一个，对话框里的按钮就是死的（点了没反应），
        # 而这类问题在 headless 里不弹窗、看不出来，所以在这里点名查。
        check("comfy_launcher 跟着插件加载上了", mod.comfy_launcher is not None)
        check("有目录选择器（Choose folder…）",
              callable(getattr(mod, "_pick_folder", None)))
        check("有解释器选择器（Choose python…）",
              callable(getattr(mod, "_pick_file", None)))
        check("有 AI 操作前的自动启动钩子",
              callable(getattr(mod, "_autostart_comfy", None)))
        check("Gtk 支持选目录的 FileChooserDialog",
              mod.Gtk is not None
              and hasattr(mod.Gtk, "FileChooserDialog")
              and hasattr(mod.Gtk.FileChooserAction, "SELECT_FOLDER"))

    # ---- 按名称自动选区（SAM2）：注册 + 蒙版平移 ----
    sel_proc = Gimp.get_pdb().lookup_procedure(mod.PROC_SELECT)
    check("注册了「按名称选区」过程", sel_proc is not None)
    if sel_proc is not None:
        scfg = sel_proc.create_config()
        names = {p.name for p in scfg.list_properties()}
        for key in ("object", "sam2-model", "threshold", "grow",
                    "shift-x", "shift-y", "server", "timeout"):
            check("  参数齐了：%s" % key, key in names, ",".join(sorted(names)))
        check("  默认不平移", scfg.get_property("shift-y") == 0)
        check("  默认阈值 0.30", abs(scfg.get_property("threshold") - 0.30) < 1e-9)
        try:
            mod.ai_select_object(img, img.get_layers()[0], "")
            check("空名字要报错（不能静默乱选）", False)
        except RuntimeError as exc:
            check("空名字要报错（不能静默乱选）", "Type what to select" in str(exc),
                  str(exc)[:60])

    # 蒙版平移：右移 / 下移 / 越界 / 零位移
    W, H = 4, 3
    base = bytes([1, 2, 3, 4,
                  5, 6, 7, 8,
                  9, 10, 11, 12])
    got = mod._shift_mask(base, W, H, 1, 0)
    check("平移 x=+1：整行右移、左边补 0",
          list(got) == [0, 1, 2, 3,
                        0, 5, 6, 7,
                        0, 9, 10, 11], list(got))
    got = mod._shift_mask(base, W, H, 0, 1)
    check("平移 y=+1：整行下移、最上面补 0",
          list(got) == [0, 0, 0, 0,
                        1, 2, 3, 4,
                        5, 6, 7, 8], list(got))
    got = mod._shift_mask(base, W, H, -1, 0)
    check("平移 x=-1：整行左移、右边补 0",
          list(got) == [2, 3, 4, 0,
                        6, 7, 8, 0,
                        10, 11, 12, 0], list(got))
    check("位移超过画布宽度就整块清空",
          set(mod._shift_mask(base, W, H, W + 1, 0)) == {0})
    check("零位移原样返回（省一次拷贝）",
          mod._shift_mask(base, W, H, 0, 0) is base)
    check("shift-x/y 是对话框参数（画布像素）",
          mod.ai_select_object.__defaults__ is not None)

    # ---- AI 扩图：真 GIMP 里长画布 + 蒙版 ----
    exp_path = os.path.join(ROOT, "plugin", "ai-outpaint", "ai-outpaint.py")
    espec = importlib.util.spec_from_file_location("ai_expand_plugin", exp_path)
    emod = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(emod)

    check("扩图：选「左右」时上下是 0", emod.plan_edges("horizontal", 100)
          == (100, 0, 100, 0), emod.plan_edges("horizontal", 100))
    check("扩图：选「上下」时左右是 0", emod.plan_edges("vertical", 64)
          == (0, 64, 0, 64), emod.plan_edges("vertical", 64))
    check("扩图：「四周」四条边都给", emod.plan_edges("all", 32)
          == (32, 32, 32, 32))
    check("扩图：不认识的边当 all", emod.plan_edges("sideways", 8)
          == (8, 8, 8, 8))
    check("扩图：0 像素 = 什么都不扩", emod.plan_edges("all", 0) == (0, 0, 0, 0))

    ex_img, ex_lay = new_image(60, 40, (210, 180, 150))
    corner = px(ex_lay, 0, 0)
    ex_info = emod.ai_expand(ex_img, ex_lay, "a calm sea, low horizon",
                           edges="left", amount=20, variations=1, pick="off",
                           client=client, timeout=30)
    check("扩图：画布宽 60 → 80", ex_img.get_width() == 80,
          ex_img.get_width())
    check("扩图：画布高没变", ex_img.get_height() == 40, ex_img.get_height())
    off = ex_lay.get_offsets()
    check("扩图：原图层整体右移 20 px", (off[1], off[2]) == (20, 0),
          (off[1], off[2]))
    check("扩图：原图左上角像素一个字节都没动", px(ex_lay, 0, 0) == corner,
          (px(ex_lay, 0, 0), corner))
    ex_top = ex_img.get_layers()[0]
    check("扩图：结果层铺满新画布",
          (ex_top.get_width(), ex_top.get_height()) == (80, 40),
          (ex_top.get_width(), ex_top.get_height()))
    check("扩图：结果层带图层蒙版（原图区域被挡住）",
          ex_top.get_mask() is not None)
    check("扩图：info 里记下了前后尺寸",
          ex_info["canvas"] == (80, 40) and ex_info["before"] == (60, 40),
          (ex_info["canvas"], ex_info["before"]))
    check("扩图：info 里记下了每边扩多少",
          ex_info["edges"] == (20, 0, 0, 0), ex_info["edges"])

    # 喂给采样器的蒙版必须是硬的。ComfyUI 那条工作流没有合成节点，软蒙版会让
    # 模型把交界当成半褪色区域重建，贴回去就是一圈亮边（2026-11-24 修）。
    mblob = srv.state.inputs.get("lb-inpaint-mask.png")
    if mblob:
        mw, mh, mch, mpix = ai_client.decode_png(mblob)
        alphas = set(mpix[3::mch])
        check("扩图：喂模型的蒙版是硬的（alpha 只有 0/255）",
              alphas <= {0, 255}, sorted(alphas)[:6])
        check("扩图：硬蒙版左侧仍是重绘区",
              mpix[(mh // 2) * mw * mch + 3] == 0,
              mpix[(mh // 2) * mw * mch + 3])
        check("扩图：硬蒙版不碰原图深处",
              mpix[((mh // 2) * mw + mw // 2) * mch + 3] == 255,
              mpix[((mh // 2) * mw + mw // 2) * mch + 3])
    else:
        check("扩图：mock 收到了蒙版上传", False, "state.inputs 里没有 mask")

    try:
        emod.ai_expand(ex_img, ex_lay, "x", edges="all", amount=0, client=client)
        check("扩图：0 像素要报错（不能静默跑一趟）", False)
    except RuntimeError as exc:
        check("扩图：0 像素要报错（不能静默跑一趟）",
              "Nothing to expand" in str(exc), str(exc)[:50])

    # ---- AI 超分：2 倍出层、偏移跟着放大 ----
    up_path = os.path.join(ROOT, "plugin", "ai-upscale", "ai-upscale.py")
    uspec = importlib.util.spec_from_file_location("ai_upscale_plugin", up_path)
    umod = importlib.util.module_from_spec(uspec)
    uspec.loader.exec_module(umod)

    check("超分：20×12 放 2 倍 = 40×24", umod.plan_target(20, 12, 2) == (40, 24))
    try:
        umod.plan_target(9000, 9000, 4)
        check("超分：像素爆掉要提前报错", False)
    except RuntimeError as exc:
        check("超分：像素爆掉要提前报错", "megapixels" in str(exc),
              str(exc)[:50])

    up_img, up_lay = new_image(24, 16, (120, 90, 60))
    up_lay.set_offsets(5, 7)
    up_layer, up_info = umod.ai_upscale(up_img, up_lay, factor=2, client=client,
                                      timeout=30)
    check("超分：新层是 48×32",
          (up_layer.get_width(), up_layer.get_height()) == (48, 32),
          (up_layer.get_width(), up_layer.get_height()))
    upo = up_layer.get_offsets()
    check("超分：偏移按倍率一起放大 (5,7) → (10,14)",
          (upo[1], upo[2]) == (10, 14), (upo[1], upo[2]))
    check("超分：原图层原样留着（放大是新建一层）",
          (up_lay.get_width(), up_lay.get_height()) == (24, 16))
    check("超分：新层在原图之上", up_img.get_item_position(up_layer) <
          up_img.get_item_position(up_lay),
          (up_img.get_item_position(up_layer), up_img.get_item_position(up_lay)))
    check("超分：info 记下了模型与倍率",
          up_info["factor"] == 2 and up_info["model"] == mock_comfy.UPSCALE_MODEL,
          (up_info["factor"], up_info["model"]))

    # 两个新过程都要注册进 PDB，否则菜单里点了没反应
    for proc_name, label in ((emod.PROC, "AI 扩图"), (umod.PROC, "AI 超分")):
        check("%s：注册进 PDB" % label,
              Gimp.get_pdb().lookup_procedure(proc_name) is not None, proc_name)

    # GIMP 会把没删掉的图像当成「插件漏出来的」报到日志里，收尾清干净。
    # 不按变量名逐个删：中途有用例复用了同名变量（img3 建过两次），漏掉的
    # 就是旧的那个——按「此刻还剩什么」删才收得干净。
    for im in list(Gimp.get_images()):
        im.delete()
finally:
    srv.stop()

print("\n%s" % ("全部通过（%d 条断言）" % OK if not FAIL
                    else "失败 %d / %d：%s" % (len(FAIL), OK, ", ".join(FAIL))))
