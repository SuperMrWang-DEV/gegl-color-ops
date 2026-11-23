#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 tools/check_cutout.py · 抠图插件的纯 Python 回归（不需要 GIMP、不需要显卡）
 ---------------------------------------------------------------------------
 测什么
   1. cutout_math：边缘种子点（数量、避开四角、不越界、小图不炸）、图层偏移
      换算、alpha→蒙版（残影闸）、蒙版统计、覆盖率、cover 缩放、背景三选一
   2. ai_client：抠图工作流只有三个节点、RMBG 的参数名一个不差（写错就静默
      取默认值，画出来是整张图）、background 固定 Alpha
   3. mock 端到端：上传 → RMBG → 取回，alpha 是不是「左背景/右主体」那个
      已知形状；模型名不在列表时退回第一个
   4. 节点包缺失时的错误文案：要能照着做（说清装哪个仓库），而不是把
      ComfyUI 的 node_errors 原样甩出来
   5. 插件源码静态约束：菜单挂在 SuperMrWang/Mask、背景层插在 pos+1（插到
      pos 会把照片盖住）、本地版必须反选、AI 版必须用 alpha 当蒙版

 跑法   python tools/check_cutout.py
 ==========================================================================="""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))
sys.path.insert(0, HERE)

import ai_client as AC  # noqa: E402
import cutout_math as CM  # noqa: E402
import mock_comfy  # noqa: E402

PLUG = os.path.join(ROOT, "plugin", "cutout", "cutout.py")

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

def test_seeds():
    section("1. 边缘种子点")
    seeds = CM.edge_seeds(1000, 800, per_edge=5)
    # 每条边 5 个 → 20 个；四个角不在里面
    ok("1000×800 撒 5 点/边 → 20 个种子", len(seeds) == 20, len(seeds))
    ok("全部落在画布内",
       all(0 <= x < 1000 and 0 <= y < 800 for x, y in seeds), seeds[:3])
    ok("避开四个角（inset≥2）",
       not any((x < 2 or x > 997 or y < 2 or y > 797) and
               (x < 2 or x > 997) and (y < 2 or y > 797) for x, y in seeds))
    ok("顶边点都在 y=2 上", sum(1 for x, y in seeds if y == 2) == 5,
       [y for x, y in seeds][:6])
    ok("左边点都在 x=2 上", sum(1 for x, y in seeds if x == 2) == 5)
    # 种子沿边均匀分布（不挤在角上）
    top = sorted(x for x, y in seeds if y == 2)
    gaps = [b - a for a, b in zip(top, top[1:])]
    ok("顶边种子间距均匀（最大/最小 < 1.3）",
       max(gaps) <= min(gaps) * 1.3, (min(gaps), max(gaps)))

    tiny = CM.edge_seeds(12, 9, per_edge=8)
    ok("小图不越界", all(0 <= x < 12 and 0 <= y < 9 for x, y in tiny), tiny)
    ok("小图去重后数量合理", 0 < len(tiny) <= 32, len(tiny))
    ok("per_edge=1 每边一个 → 4 个", len(CM.edge_seeds(200, 100, 1)) == 4,
       CM.edge_seeds(200, 100, 1))


def test_offset():
    section("2. 偏移与图层边界")
    seeds = CM.edge_seeds(1000, 800, 5)
    moved = CM.offset_seeds(seeds, 0, 0, 1000, 800)
    ok("偏移 0 时原样保留", moved == seeds, len(moved))
    # 图层只盖住画布左上角 300×200：只有落进去的种子留下
    small = CM.offset_seeds(seeds, 0, 0, 300, 200)
    ok("只保留落在图层内的种子", 0 < len(small) < 20, len(small))
    ok("换算成图层局部坐标",
       all(0 <= x < 300 and 0 <= y < 200 for x, y in small), small[:3])
    outside = CM.offset_seeds(seeds, 5000, 5000, 300, 200)
    ok("图层整个在画布外时退回图层自己的四边", len(outside) == 20, len(outside))


def test_alpha_mask():
    section("3. alpha → 蒙版")
    alpha = bytes([0, 1, 7, 8, 9, 60, 128, 254, 255])
    mask = CM.alpha_to_mask(alpha, floor=8)
    ok("低于 8 的残影压成 0", list(mask[:3]) == [0, 0, 0], list(mask[:3]))
    ok("8 及以上原样保留", list(mask[3:]) == [8, 9, 60, 128, 254, 255],
       list(mask[3:]))
    ok("floor=0 时一个字节都不改",
       CM.alpha_to_mask(alpha, floor=0) == alpha)
    ok("floor 超出范围被夹紧（不炸，只留纯白）",
       CM.alpha_to_mask(alpha, floor=999) == bytes([0] * 7 + [254, 255]))

    ratio, lo, hi = CM.mask_stats(bytes([0, 0, 255, 255]))
    ok("前景占比按 >127 算", near(ratio, 0.5), ratio)
    ok("mask_stats 的 min/max", (lo, hi) == (0, 255), (lo, hi))
    ok("空蒙版不炸", CM.mask_stats(b"") == (0.0, 0, 0))


def test_coverage():
    section("4. 覆盖率与 cover")
    ok("全选中 → 1.0", near(CM.coverage([255, 255, 255]), 1.0))
    ok("全没中 → 0.0", near(CM.coverage([0, 0, 0]), 0.0))
    ok("一半 → 0.5", near(CM.coverage([255, 0, 255, 0]), 0.5))
    ok("空采样 → 0.0（不除零）", CM.coverage([]) == 0.0)

    nw, nh, ox, oy = CM.fit_cover(1000, 500, 800, 800)
    ok("宽图 cover：高度对齐、左右居中裁掉",
       (nw, nh) == (1600, 800) and (ox, oy) == (-400, 0), (nw, nh, ox, oy))
    nw, nh, ox, oy = CM.fit_cover(500, 1000, 800, 800)
    ok("竖图 cover：宽度对齐、上下居中裁掉",
       (nw, nh) == (800, 1600) and (ox, oy) == (0, -400), (nw, nh, ox, oy))
    ok("同尺寸不动",
       CM.fit_cover(800, 800, 800, 800) == (800, 800, 0, 0))


def test_background():
    section("5. 背景三选一")
    ok("transparent 原样", CM.normalize_background("transparent") == "transparent")
    ok("colour 拼写也认", CM.normalize_background("colour") == "color")
    ok("white 当纯色", CM.normalize_background("white") == "color")
    ok("选了纯色但没给颜色 → 退回透明",
       CM.normalize_background("color", have_color=False) == "transparent")
    ok("选了图片但没给文件 → 退回透明",
       CM.normalize_background("image", have_image=False) == "transparent")
    ok("空值 → 透明", CM.normalize_background("") == "transparent")
    ok("choice 顺序固定为 透明/纯色/图片",
       CM.BACKGROUND_CHOICES == ("transparent", "color", "image"),
       CM.BACKGROUND_CHOICES)


# ---- 2. 工作流 ---------------------------------------------------------------

def test_workflow():
    section("6. 抠图工作流")
    wf = AC.build_cutout_workflow("src.png", model="RMBG-2.0", process_res=1024,
                                  refine_foreground=True)
    ok("只有三个节点（LoadImage/RMBG/SaveImage）", len(wf) == 3, sorted(wf))
    kinds = sorted(n["class_type"] for n in wf.values())
    ok("节点类型对得上",
       kinds == ["LoadImage", "RMBG", "SaveImage"], kinds)
    rm = wf["2"]["inputs"]
    ok("RMBG 接到 LoadImage 的 IMAGE 上", rm["image"] == ["1", 0], rm["image"])
    ok("background 固定 Alpha（不然回来的是带色底的图）",
       rm["background"] == "Alpha", rm.get("background"))
    ok("模型名透传", rm["model"] == "RMBG-2.0", rm.get("model"))
    ok("process_res 透传", rm["process_res"] == 1024, rm.get("process_res"))
    ok("refine_foreground 透传", rm["refine_foreground"] is True)
    ok("不主动卸载模型（下一次抠图更快）", rm["unload_model"] is False)
    ok("输出接到 SaveImage",
       wf["3"]["inputs"]["images"] == ["2", 0], wf["3"]["inputs"])


# ---- 3. mock 端到端 ---------------------------------------------------------

class _NoNodeClient(object):
    """只答 /upload 与 /prompt，没有 /object_info/RMBG 的假客户端。"""

    def _request(self, path, payload=None, timeout=None, raw=False):
        raise AC.ComfyError("404 not found: " + path)


def test_mock_roundtrip():
    section("7. mock 端到端")
    srv = mock_comfy.start_mock()
    try:
        client = AC.ComfyClient(srv.url, timeout=10)
        ok("mock 报告节点包在位", AC.cutout_available(client) is True)
        ok("mock 的模型列表有两个",
           AC.cutout_models(client) == ["RMBG-2.0", "INSPYRENET"],
           AC.cutout_models(client))

        w, h = 100, 60
        rgba = bytearray(w * h * 4)
        for i in range(w * h):
            rgba[i * 4:i * 4 + 4] = bytes((200, 120, 60, 255))
        blob, info = AC.cutout(client, AC.rgba_png(w, h, bytes(rgba)),
                               model="RMBG-2.0", process_res=512)
        dw, dh, dch, dpx = AC.decode_png(blob)
        ok("回来的尺寸与上传一致", (dw, dh) == (w, h), (dw, dh))
        ok("带 alpha（四通道）", dch == 4, dch)
        alpha = dpx[3::4]
        ok("左侧是背景（alpha=0）", alpha[0] == 0 and alpha[dw // 2 - 1] == 0,
           alpha[:4])
        ok("右侧是主体（alpha=255）", alpha[-1] == 255, alpha[-4:])
        ok("中间有一条过渡带", any(0 < a < 255 for a in alpha), "no ramp")
        ok("info 里记下用的模型", info["model"] == "RMBG-2.0", info)

        # 模型名写错 → 退回第一个，不报错
        _blob2, info2 = AC.cutout(client, AC.rgba_png(w, h, bytes(rgba)),
                                  model="no-such-model")
        ok("模型名对不上时安静退回第一个",
           info2["model"] == "RMBG-2.0", info2["model"])

        # 蒙版形状：与插件里 alpha_to_mask 的用法一致
        mask = CM.alpha_to_mask(alpha)
        ratio, _lo, hi = CM.mask_stats(mask)
        ok("蒙版前景占比接近 40%（0.6 之后才是不透明）",
           0.35 < ratio < 0.65, ratio)
        ok("蒙版最大值 255", hi == 255, hi)
    finally:
        srv.stop()


def test_missing_node():
    section("8. 节点包缺失")
    client = _NoNodeClient()
    ok("查不到节点 → cutout_models 返回空表",
       AC.cutout_models(client) == [])
    ok("cutout_available 为 False", AC.cutout_available(client) is False)
    try:
        AC.cutout(client, b"x", model="RMBG-2.0")
        ok("没有节点时应该报错", False, "no exception")
    except AC.ComfyError as exc:
        msg = str(exc)
        ok("报错说清要装 ComfyUI-RMBG", "ComfyUI-RMBG" in msg, msg[:80])
        ok("报错给了仓库地址", "github.com/1038lab" in msg, msg[:120])
        ok("报错给了一条退路（本地版）", "本地" in msg or "local" in msg.lower(),
           msg[-80:])


# ---- 4. 源码静态约束 ---------------------------------------------------------

def test_sources():
    section("9. 插件源码约束")
    src = open(PLUG, encoding="utf-8").read()
    ok("两个过程都在", "PROC_LOCAL" in src and "PROC_AI" in src)
    ok("菜单挂在 SuperMrWang/Mask 下",
       src.count('add_menu_path("<Image>/SuperMrWang/Mask")') == 2,
       src.count('add_menu_path("<Image>/SuperMrWang/Mask")'))
    ok("先 set_menu_label 再 add_menu_path（顺序反了菜单会消失）",
       src.index("set_menu_label") < src.index("add_menu_path"))
    ok("背景层插在 pos + 1（插 pos 会盖住照片）", "pos + 1" in src)
    ok("本地版会反选背景选区", "'gimp-selection-invert'" in src)
    ok("AI 版用返回的 alpha 当蒙版", "alpha_to_mask" in src)
    ok("临时蒙版图层用完删掉", "image.remove_layer(tmp)" in src)
    ok("AI 前会先确保 ComfyUI 在跑", "ensure_running" in src)
    ok("上传前把长边压到 MAX_UPLOAD_EDGE 以内", "MAX_UPLOAD_EDGE" in src)
    ok("__main__ 里没有裸 sys.argv（模块只 import 了 sys as _sys，"
       "拼错名字只会在 GIMP 真启动时炸）",
       not re.search(r"(?<![_\w])sys\.argv", src),
       re.findall(r".{0,12}sys\.argv", src))
    ok("add_color_argument 带 has_alpha=False（少一个参数会在注册时 TypeError，"
       "菜单直接消失）", "False, Gegl.Color.new" in src)
    ok("不许写死 ComfyUI 地址",
       not re.search(r"127\.0\.0\.1:8188", src), "hard-coded server")
    ok("拒绝图层组（没有自己的像素）", "is_group()" in src)


def main():
    test_seeds()
    test_offset()
    test_alpha_mask()
    test_coverage()
    test_background()
    test_workflow()
    test_mock_roundtrip()
    test_missing_node()
    test_sources()
    print("\n" + ("全部通过：%d 条断言" % PASS if not FAIL
                  else "失败 %d / %d：\n  " % (len(FAIL), len(FAIL) + PASS)
                  + "\n  ".join(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
