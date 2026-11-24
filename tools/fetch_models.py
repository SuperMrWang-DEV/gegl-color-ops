#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载更高质量的重绘 / 填充模型（旧入口，保留兼容）。

真正的盘点和下载都在 `tools/setup_comfy.py`：它认得三种 ComfyUI 布局、
会顺手装节点包和 pip 依赖、断点续传能跨镜像、装完还会重启并回读服务端。
这里只是把老命令翻译过去，老脚本和老文档不用改。

    python tools/fetch_models.py sdxl      → --only sdxl
    python tools/fetch_models.py flux      → --only flux
    python tools/fetch_models.py           → --only sdxl flux
    python tools/fetch_models.py --check   → 上面两个的体检

新用户直接用：

    python tools/setup_comfy.py            # 默认档：inpaint 两档 + 选区 + 抠图
    python tools/setup_comfy.py --check    # 只体检
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import setup_comfy as S                                     # noqa: E402

GROUPS = ("sdxl", "flux")
WITH_VALUE = ("--home", "--python", "--mirror")


def split_args(argv):
    """把「档位」和「带值的开关」分开。

    不能简单地把非 - 开头的都当档位：`--home D:\\ComfyUI` 里的路径也会被
    当成档位，然后报「未知档位 D:\\ComfyUI」——这是转发脚本最容易犯的错。
    """
    groups, passthrough, i = [], [], 0
    while i < len(argv):
        a = argv[i]
        if a in WITH_VALUE and i + 1 < len(argv):
            passthrough += [a, argv[i + 1]]
            i += 2
            continue
        if a.startswith("-"):
            passthrough.append(a)
        else:
            groups.append(a)
        i += 1
    return groups, passthrough


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    picked, passthrough = split_args(argv)
    unknown = [a for a in picked if a not in GROUPS]
    if unknown:
        print("未知档位：%s（可选 %s；想看全部用 setup_comfy.py --check）"
              % (" ".join(unknown), " / ".join(GROUPS)))
        return 2
    fwd = ["--only", " ".join(picked or GROUPS)] + passthrough
    return S.main(fwd)


if __name__ == "__main__":
    sys.exit(main())
