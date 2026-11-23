#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 抠图模型体检 —— 哪个「去除背景」模型真的能跑
 ---------------------------------------------------------------------------
 purpose   ComfyUI-RMBG 的 RMBG 节点把四个模型列在同一个下拉里，但它们并不
           等价：INSPYRENET 依赖 Python 包 transparent_background（要 onnxruntime），
           BEN / BEN2 要额外下 400 MB 权重且依赖各自的 model.py。节点定义里
           看不到这些差别，用户点到才报错。这个脚本把每个模型真跑一次，
           失败时打印 ComfyUI 回的原话，并给出「缺什么」。

 用法      python tools/check_cutout_models.py
           python tools/check_cutout_models.py --models RMBG-2.0,BEN2
           python tools/check_cutout_models.py --server http://127.0.0.1:8188

 退出码    0 = 至少一个可用；2 = 一个都跑不通（跟 check_* 系列惯例一致）
 ==========================================================================="""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import ai_client  # noqa: E402


def probe_image(width=384, height=512):
    """画一张「渐变背景 + 中央椭圆前景」的测试图。

    不用照片：这里只判断模型能不能跑通、有没有返回 alpha，吃不到真实照片
    也没关系，反而少一份版权麻烦。椭圆足够让分割模型找到主体。
    """
    px = bytearray(width * height * 4)
    cx, cy = width * 0.5, height * 0.55
    rx, ry = width * 0.30, height * 0.34
    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 4
            # 背景：上浅蓝下浅灰的竖直渐变
            b = int(200 + 40 * y / height)
            px[i] = 210
            px[i + 1] = 225
            px[i + 2] = min(255, b)
            px[i + 3] = 255
            # 前景：暖色椭圆
            nx, ny = (x - cx) / rx, (y - cy) / ry
            if nx * nx + ny * ny <= 1.0:
                px[i] = 205
                px[i + 1] = 120
                px[i + 2] = 70
    return ai_client.rgba_png(width, height, bytes(px))


def main(argv=None):
    ap = argparse.ArgumentParser(description="逐个试 ComfyUI-RMBG 的抠图模型")
    ap.add_argument("--server", default=None, help="ComfyUI 地址")
    ap.add_argument("--models", default="", help="逗号分隔；默认试节点里列出的全部")
    ap.add_argument("--timeout", type=float, default=1200.0,
                    help="单个模型的等待上限（首次会下载权重，给足）")
    args = ap.parse_args(argv)

    client = ai_client.ComfyClient(args.server, timeout=20.0)
    if not client.probe():
        print("连不上 ComfyUI：%s" % client.server)
        print("先启动服务（start-comfyui.bat），等服务打印出 GUI 地址再跑。")
        return 2

    listed = ai_client.cutout_models(client, timeout=5.0)
    if not listed:
        print("ComfyUI 里没有 RMBG 节点 —— 抠图需要 ComfyUI-RMBG 节点包。")
        return 2

    models = [m.strip() for m in args.models.split(",") if m.strip()] or listed
    unknown = [m for m in models if m not in listed]
    if unknown:
        print("节点里没有这些模型名：%s" % ", ".join(unknown))
        print("节点实际列出：%s" % ", ".join(listed))
        models = [m for m in models if m in listed]
        if not models:
            return 2

    png = probe_image()
    print("服务 %s，节点列出 %d 个模型：%s"
          % (client.server, len(listed), ", ".join(listed)))
    print("-" * 68)

    ok, bad = [], []
    for name in models:
        t0 = time.time()
        sys.stdout.write("%-12s … " % name)
        sys.stdout.flush()
        try:
            blob, info = ai_client.cutout(client, png, model=name,
                                          timeout=args.timeout)
        except Exception as exc:                      # noqa: BLE001
            bad.append((name, str(exc)))
            print("失败（%.1f 秒）" % (time.time() - t0))
            for line in str(exc).splitlines()[:6]:
                print("    " + line)
            continue
        if not blob:
            bad.append((name, "没有取回图像"))
            print("失败（空图）")
            continue
        ok.append((name, len(blob), time.time() - t0))
        print("可用（%.1f 秒，%d 字节）" % (time.time() - t0, len(blob)))

    print("-" * 68)
    print("可用 %d / %d：%s" % (len(ok), len(models),
                              ", ".join(n for n, _, _ in ok) or "无"))
    if bad:
        print("不可用：%s" % ", ".join(n for n, _ in bad))
        for name, msg in bad:
            hint = _hint(msg)
            if hint:
                print("  · %s：%s" % (name, hint))
    return 0 if ok else 2


def _hint(msg):
    """按错误原文给出「缺什么」——比让用户自己读 traceback 有用。"""
    low = msg.lower()
    if "transparent_background" in low:
        return ("缺 Python 包 transparent_background（还要 onnxruntime）。"
                "跑 tools/install-cutout-deps.bat，或\n"
                "    <ComfyUI>/py312/python.exe -m pip install "
                "transparent-background onnxruntime")
    if "no module named 'timm'" in low:
        return "缺 timm：<ComfyUI>/py312/python.exe -m pip install timm"
    if "download" in low or "connection" in low or "name or service" in low:
        return "权重下载失败，检查网络 / HF 镜像（HF_ENDPOINT）"
    if "out of memory" in low or "cuda out of memory" in low:
        return "显存不够，把 process_res 降到 768 再试"
    return ""


if __name__ == "__main__":
    sys.exit(main())
