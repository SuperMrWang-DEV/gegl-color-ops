#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 tools/check_retouch_ai.py · 三支「AI 预修」磨皮插件的回归（不需要 GIMP）
 ---------------------------------------------------------------------------
 测什么
   1. retouch_math 的数学：亮度、盒式模糊、差值 → 蒙版 / 灰层，以及灰层
      代回柔光公式能不能把原图推回参考图（这是中性灰那支的全部正确性）
   2. ai_client 的整图工作流：节点表、参数透传、mock 端到端（img2img 只有
      一张 LoadImage，mock 原样返回）
   3. 三支插件的源码静态约束：过程名 / 菜单路径 / 下拉参数 / 提示词默认值
      必须英文 / 不许写死 ComfyUI 地址 / 不许绕过 retouch_prep 直接调 ai_client

 跑法   python tools/check_retouch_ai.py
 ==========================================================================="""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))
sys.path.insert(0, HERE)

import ai_client  # noqa: E402
import mock_comfy  # noqa: E402
import retouch_math as RM  # noqa: E402

PASS = 0
FAIL = []
SECTION = ""


def section(name):
    global SECTION
    SECTION = name
    print("\n" + name)


def ok(label, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append("%s / %s（%s）" % (SECTION, label, detail))
        print("  FAIL %s  %s" % (label, detail))


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ---- 1. 数学 -----------------------------------------------------------------

def test_luma():
    section("1. 亮度")
    # 纯红：Rec.709 权重下 0.2126，不是 0.299
    rgba = bytes((255, 0, 0, 255)) * 4
    lum = RM.luma(rgba)
    ok("纯红亮度 = 0.2126", near(lum[0], 0.2126, 1e-4), lum[0])
    gray = bytes((128, 128, 128, 255)) * 2
    ok("灰 128 → 约 0.502", near(RM.luma(gray)[0], 128 / 255.0, 1e-4),
       RM.luma(gray)[0])
    ok("luma_from_rgb 与 luma 同值",
       near(RM.luma_from_rgb(bytes((10, 20, 30)) * 2, 2)[1],
            RM.luma(bytes((10, 20, 30, 255)) * 2)[1], 1e-6))


def test_blur():
    section("2. 盒式模糊")
    w = h = 8
    vals = [0.0] * (w * h)
    vals[4 * w + 4] = 1.0                    # 中心一个亮点
    out = RM.box_blur(vals, w, h, radius=1, passes=1)
    ok("像素总数不变", len(out) == len(vals), len(out))
    ok("峰值被摊平", out[4 * w + 4] < 1.0, out[4 * w + 4])
    ok("邻域被抬起", out[4 * w + 5] > 0.0, out[4 * w + 5])
    ok("能量守恒（边界夹取会略多，误差 1%）",
       near(sum(out), sum(vals), 0.01 * sum(vals) + 1e-9), (sum(out), sum(vals)))
    flat = RM.box_blur([0.5] * (w * h), w, h, radius=3, passes=3)
    ok("常数场不变", all(near(v, 0.5, 1e-9) for v in flat), flat[0])
    ok("radius=0 原样返回", RM.box_blur(vals, w, h, 0, 3) == vals)


def test_masks():
    section("3. 差值 → 双曲线蒙版")
    base = [0.5] * 100
    delta = [0.0] * 100
    delta[10] = 0.06        # 该提亮
    delta[20] = -0.06       # 该压暗
    dodge, burn = RM.dodge_burn_masks(base, delta, amount=0.12, strength=0.7)
    ok("亮的差值进提亮蒙版", dodge[10] > 0 and burn[10] == 0,
       (dodge[10], burn[10]))
    ok("暗的差值进压暗蒙版", burn[20] > 0 and dodge[20] == 0,
       (dodge[20], burn[20]))
    ok("没差值的像素不涂", dodge[30] == 0 and burn[30] == 0)
    # 需要的浓度 = delta / (amount·4x(1−x))，x=0.5 时斜率=amount
    want = int(round(0.06 / 0.12 * 0.7 * 255))
    ok("浓度按曲线斜率算（0.5 处 ≈ %d）" % want, near(dodge[10], want, 2),
       dodge[10])
    ok("预修比例线性生效",
       RM.dodge_burn_masks(base, delta, 0.12, 0.35)[0][10] < dodge[10])
    ok("死区内不涂", RM.dodge_burn_masks(base, [0.001] * 100, 0.12, 1.0)[0][0] == 0)
    # 暗部同一个差值需要更浓的蒙版（曲线两端斜率为 0）
    dark = [0.08] * 4
    d2 = [0.06, 0.06, 0.06, 0.06]
    m_dark = RM.dodge_burn_masks(dark, d2, 0.12, 1.0)[0][0]
    m_mid = RM.dodge_burn_masks([0.5] * 4, d2, 0.12, 1.0)[0][0]
    ok("暗部比中灰更需要浓蒙版", m_dark >= m_mid, (m_dark, m_mid))
    ok("蒙版被夹在 0…255", 0 <= m_dark <= 255 and 0 <= m_mid <= 255)


def test_grey():
    section("4. 差值 → 中性灰层（柔光反解）")
    cases = [(0.30, 0.05), (0.50, 0.08), (0.50, -0.08), (0.72, -0.05),
             (0.12, 0.04), (0.88, -0.03)]
    for x, d in cases:
        g = RM.grey_for_delta([x], [d], strength=1.0)[0] / 255.0
        back = RM.soft_light(x, g)
        ok("柔光往返 x=%.2f d=%+.2f" % (x, d), near(back, x + d, 0.004),
           "%.4f vs %.4f (g=%.3f)" % (back, x + d, g))
    ok("零差值 → 128", RM.grey_for_delta([0.4], [0.0], 1.0)[0] == 128)
    half = RM.grey_for_delta([0.5], [0.08], 0.5)[0]
    full = RM.grey_for_delta([0.5], [0.08], 1.0)[0]
    ok("预修比例 0.5 落在 128 与全量之间", 128 < half < full, (half, full))
    ok("灰层被夹在 0…255",
       all(0 <= v <= 255 for v in RM.grey_for_delta([0.0, 0.5, 1.0],
                                                   [0.5, -0.5, 0.5], 1.0)))


def test_blend():
    section("5. 选区混合")
    base = bytes((10, 10, 10, 255)) * 4
    ref = bytes((200, 200, 200, 255)) * 4
    out = RM.blend_rgba(base, ref, [0.0, 0.5, 1.0, 0.0])
    ok("alpha=0 保持原样", out[0] == 10, out[0])
    ok("alpha=0.5 取中", 100 <= out[4] <= 110, out[4])
    ok("alpha=1 全换成参考", out[8] == 200, out[8])
    ok("alpha 长度覆盖整层", out[12] == 10, out[12])
    out2 = RM.blend_rgba(base, ref, [0.0] * 4)
    ok("全 0 → 逐字节等于原图", out2 == base)
    ok("alpha_from_gray 归一化",
       RM.alpha_from_gray(bytes([0, 51, 255]))[1] == 0.2)


# ---- 2. img2img 工作流 -------------------------------------------------------

def test_workflow():
    section("6. img2img 工作流")
    wf = ai_client.build_img2img_workflow(
        "m.safetensors", "src.png", "clean skin", negative="acne",
        steps=17, cfg=6.5, seed=42, denoise=0.31)
    kinds = sorted(n["class_type"] for n in wf.values())
    ok("节点表齐", kinds == sorted([
        "CheckpointLoaderSimple", "LoadImage", "CLIPTextEncode",
        "CLIPTextEncode", "VAEEncode", "KSampler", "VAEDecode", "SaveImage"]),
       kinds)
    ok("只有一张 LoadImage（和 inpaint 的区别）",
       kinds.count("LoadImage") == 1, kinds.count("LoadImage"))
    ok("没有蒙版节点", not any("Mask" in k for k in kinds), kinds)
    ks = [n for n in wf.values() if n["class_type"] == "KSampler"][0]["inputs"]
    ok("denoise 透传", near(ks["denoise"], 0.31, 1e-9), ks["denoise"])
    ok("steps / cfg / seed 透传",
       ks["steps"] == 17 and near(ks["cfg"], 6.5) and ks["seed"] == 42, ks)
    enc = [n for n in wf.values() if n["class_type"] == "VAEEncode"][0]["inputs"]
    ok("VAEEncode 接原图 latent", enc["pixels"] == ["2", 0], enc)
    pos = [n for n in wf.values() if n["class_type"] == "CLIPTextEncode"]
    ok("正负提示词分开", {p["inputs"]["text"] for p in pos} ==
       {"clean skin", "acne"}, [p["inputs"]["text"] for p in pos])


def test_mock_roundtrip():
    section("7. img2img 走 mock 端到端")
    rgba = bytearray()
    for y in range(16):
        for x in range(16):
            rgba += bytes((x * 16 % 256, y * 16 % 256, 64, 255))
    rgba = bytes(rgba)
    png = ai_client.encode_png(16, 16, rgba, channels=4)
    srv = mock_comfy.start_mock()
    try:
        cli = ai_client.ComfyClient(srv.url, timeout=10)
        blob, info = ai_client.img2img(cli, png, "clean skin", denoise=0.3,
                                      checkpoint=mock_comfy.CHECKPOINT,
                                      steps=4)
        ok("拿到结果图", bool(blob), len(blob or b""))
        w, h, ch, pix = ai_client.decode_png(blob)
        ok("尺寸一致", (w, h) == (16, 16), (w, h))
        ok("img2img 在 mock 里原样返回（denoise=0 语义）",
           bytes(pix) == rgba, "前 4 字节 %s" % (bytes(pix[:4]),))
        ok("info 带秒数与底模",
           "seconds" in info and info.get("checkpoint") == mock_comfy.CHECKPOINT,
           info)
        # mock 收到的工作流里必须有 VAEEncode 与 denoise
        pid = info["prompt_id"]
        wf = srv.state.prompts[pid]
        ks = [n for n in wf.values() if n["class_type"] == "KSampler"][0]["inputs"]
        ok("mock 收到的 denoise = 0.3", near(ks["denoise"], 0.3), ks["denoise"])
    finally:
        srv.stop()


# ---- 3. 插件源码静态检查 -----------------------------------------------------

PLUGINS = [
    ("ai-frequency-separation", "lb-plugin-ai-frequency-separation"),
    ("ai-dodge-burn", "lb-plugin-ai-dodge-burn"),
    ("ai-neutral-grey", "lb-plugin-ai-neutral-grey"),
]


def test_sources():
    section("8. 三支插件源码")
    for dirname, proc in PLUGINS:
        path = os.path.join(ROOT, "plugin", dirname, dirname + ".py")
        ok("%s 存在" % dirname, os.path.exists(path), path)
        src = open(path, encoding="utf-8").read()
        ok("%s 过程名" % dirname, "'" + proc + "'" in src, proc)
        ok("%s 两个菜单入口" % dirname,
           src.count('add_menu_path("<Image>/SuperMrWang/Retouch")') == 1 and
           src.count('add_menu_path("<Layers>/SuperMrWang/Retouch")') == 1)
        ok("%s 用 Choice 做参考来源" % dirname, "Gimp.Choice.new()" in src)
        ok("%s 有 local 兜底" % dirname, '"local"' in src)
        ok("%s 不直接 import ai_client" % dirname, "import ai_client" not in src)
        # 提示词参数必须默认空：预填一句通用文案，用户点确定就得到一块
        # 跟画面无关的东西（2026-11-21 在 ai-inpaint 上踩过一次）
        ok("%s 提示词默认空" % dirname,
           re.search(r'"prompt".*?DEFAULT|"prompt".*?\n.*?\n.*?"",\s*GObject', src, re.S)
           is not None or src.count('"", GObject.ParamFlags.READWRITE') >= 2)
        # 地址默认必须是空串（走 $LB_COMFY_URL / 内置默认），不是写死一个 IP
        ok("%s ComfyUI 地址默认空" % dirname,
           re.search(r'"server",\s*_\([^)]*\),\s*_\([^)]*\),\s*""', src, re.S)
           is not None, "找不到 server 参数或默认值不是空串")
        ok("%s 走 retouch_prep.prepare" % dirname, "RP.prepare(" in src)
        ok("%s 结尾 Gimp.main" % dirname, "Gimp.main(" in src)
        ok("%s i18n 域正确" % dirname, "'gegl-color-ops'" in src)

    # retouch_prep 自己的约束
    prep = open(os.path.join(ROOT, "plugin", "_shared", "retouch_prep.py"),
                encoding="utf-8").read()
    ok("prep 提示词是英文", "clean natural skin" in prep)
    ok("prep 有 AI 失败退回本地的分支", "fallback" in prep and "local_reference" in prep)
    ok("prep 工作尺寸上限 512", "WORK_MAX = 512" in prep)
    ok("prep 尊重选区", "use_selection" in prep and "blend_rgba" in prep)


def test_prep_constants():
    """retouch_prep 依赖 gi，跑不了就只读源码里的常量——别为了测试去装 GIMP。"""
    section("9. 预修参数默认值")
    src = open(os.path.join(ROOT, "plugin", "_shared", "retouch_prep.py"),
               encoding="utf-8").read()
    m = re.search(r"DEFAULT_PROMPT = \((.*?)\)\n", src, re.S)
    prompt = " ".join(re.findall(r'"([^"]*)"', m.group(1))) if m else ""
    n = re.search(r"DEFAULT_NEGATIVE = \((.*?)\)\n", src, re.S)
    negative = " ".join(re.findall(r'"([^"]*)"', n.group(1))) if n else ""
    ok("默认提示词是英文", prompt.isascii() and "clean" in prompt, prompt[:40])
    ok("默认提示词不推塑料感", "plastic" not in prompt, prompt[:40])
    ok("负面词里有 blemishes", "blemishes" in negative, negative[:40])
    ok("denoise 默认 0.35", "denoise=0.35" in src)
    ok("有中文提示词翻译的入口", "prompt_tools.to_english" in src)
    ok("翻不出来时退回默认值", "DEFAULT_PROMPT" in src.split("def resolve_prompt")[1][:600])


def main():
    test_luma()
    test_blur()
    test_masks()
    test_grey()
    test_blend()
    test_workflow()
    test_mock_roundtrip()
    test_sources()
    test_prep_constants()
    print("\n" + ("全部通过：%d 条断言" % PASS if not FAIL
                  else "失败 %d / %d：\n  " % (len(FAIL), len(FAIL) + PASS)
                  + "\n  ".join(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
