#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装好「按名称自动选区」需要的东西（旧入口，保留兼容）。

真正干活的是 `tools/setup_comfy.py --only select`：它除了这三份权重，还会
装 ComfyUI-RMBG 节点包、补 groundingdino 那套 pip 依赖、写 BERT 补丁，
最后重启服务并回读 /object_info 确认 SAM2Segment 真的加载了。

    python tools/setup_comfy_sam2.py            → setup_comfy.py --only select
    python tools/setup_comfy_sam2.py --check    → 同上加 --check
    python tools/setup_comfy_sam2.py --home D:\\ComfyUI --python D:\\ComfyUI\\py312\\python.exe

为什么权重必须走脚本下：三份文件加起来 1.1 GB，其中 BERT 是一个目录里的五个
文件，靠手放到 `models/bert-base-uncased/` 很容易少一个；而且国内直连
huggingface.co 是 0 字节卡死，不是慢。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import setup_comfy as S                                     # noqa: E402


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fwd = ["--only", "select"]
    for flag in ("--check", "--no-restart", "--mirror"):
        if flag in argv:
            fwd.append(flag)
    for flag in ("--home", "--python"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv):
                fwd += [flag, argv[i + 1]]
    return S.main(fwd)


if __name__ == "__main__":
    sys.exit(main())
