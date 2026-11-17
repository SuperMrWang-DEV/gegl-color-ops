# -*- coding: utf-8 -*-
"""给所有算子设置 GIMP 菜单分组。

只改 C 源里的 `"gimp:menu-path"` 字符串，不动任何逻辑；op id 不变，所以
XCF 里已经用过的滤镜照旧能打开，变的只是菜单位置。

按字节替换（不经过文本解码），因为仓库里 LF / CRLF 两种行尾混用，用 sed
或按行重写会把行尾统一掉，diff 会炸。

    python tools/set_menu_group.py            # 写入
    python tools/set_menu_group.py --check    # 只报告现状，不写

分组调整就在 GROU经典图像编辑器 里挪名字，然后 ./build.sh + 重启 GIMP。
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OPS = os.path.join(ROOT, "ops")

BASE = "<Image>/Colors/SuperMrWang"

# 按「找算子时的念头」分组；组名会出现在 GIMP 的子菜单里。
# Levels 与 Component 是一级目录（各自的家族全在自己名下），其余四组平铺。
GROUPS = {
    "Levels": ["levels", "lab-levels", "hsl-levels", "hsb-levels", "lch-levels",
               "cmyk-levels", "hsi-levels"],
    # 分量：把几个分量打包成一张数据图、再解回来。dual 与 compose 成对使用，
    # gray-to-component 是单分量的编码器（HSV / LCh 的分量曲线插件用它）。
    "Component": ["hsl-dual", "hsl-compose", "hsv-dual", "hsv-compose",
                  "lab-dual", "lab-compose", "lch-dual", "lch-compose",
                  "hsi-dual", "hsi-compose", "gray-to-component"],
    "Tone":  ["exposure", "brightness-contrast",
              "shadows-highlights", "rgb-domain-grayscale"],
    "Color": ["hue-saturation", "hue-saturation-basic", "hsl-seven", "color-balance",
              "color-grading", "color-temperature-tint", "vibrance",
              "vibrance-hyper", "cmyk-primary-correction", "colorize-hsl",
              "hue-range-basic", "match-color"],
    "Blend": ["apply-image", "calculations", "channel-mixer-plus",
              "xyz-multiply", "color-lookup"],
    "Mask":  ["color-mask-select", "channel-range-to-alpha"],
}

# 匹配已有的 menu-path 值（带或不带分组后缀）
PATTERN = re.compile(rb'<Image>/Colors/SuperMrWang(?:/[A-Za-z]+)?')


def group_of(op_dir):
    for g, members in GROUPS.items():
        if op_dir in members:
            return g
    return None


def c_files(op_dir):
    d = os.path.join(OPS, op_dir)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".c")]


def main():
    check = "--check" in sys.argv
    known = {m for members in GROUPS.values() for m in members}
    seen, changed, missing = set(), [], []

    for op_dir in sorted(os.listdir(OPS)):
        if not os.path.isdir(os.path.join(OPS, op_dir)):
            continue
        want = group_of(op_dir)
        files = c_files(op_dir)
        if want is None:
            if any(PATTERN.search(open(f, "rb").read()) for f in files):
                missing.append(op_dir)
            continue

        seen.add(op_dir)
        target = ("%s/%s" % (BASE, want)).encode()

        for f in files:
            data = open(f, "rb").read()
            if not PATTERN.search(data):
                continue
            new = PATTERN.sub(target, data)
            if new != data:
                changed.append((op_dir, want))
                if not check:
                    open(f, "wb").write(new)

    for op_dir, want in changed:
        print("%-28s -> %s" % (op_dir, want))
    print("\n共 %d 个算子已分组，改动 %d 个文件" % (len(seen), len(changed)))
    if missing:
        print("!! 这些目录没有分组，被漏掉了：%s" % ", ".join(missing))
    if known - seen:
        print("!! 映射表里写了但目录不存在：%s" % ", ".join(sorted(known - seen)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
