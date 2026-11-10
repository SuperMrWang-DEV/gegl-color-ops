#!/usr/bin/env python3
"""统一 13 个算子的文件头注释、include 块与展示名。

用法：
    python tools/normalize_headers.py            # 预览（不写盘）
    python tools/normalize_headers.py --write    # 实际写入

约定（改工程时请保持）：
  1. 文件头是 5+1 字段的注释盒：id / 菜单 / 作用 / 算法 / 类型 / 参考(可选) / 许可
  2. include 顺序固定：config.h -> gi18n-lib.h -> math.h -> string.h（按需）
  3. 行尾统一 LF
  4. "title" 与 "gimp:menu-label" 一律用 _() 包住，且标题以菜单名为前缀
"""
import glob
import os
import re
import sys

WIDTH = 78

# name: (gegl_id, menu_label, title, 作用, [算法行], 类型, 参考)
OPS = {
    "hue-saturation": (
        "lb:hue-saturation", "Hue/Saturation", "Hue/Saturation",
        "全局或按红/黄/绿/青/蓝/品红六个色相区间调整色相、饱和度、明度",
        ["RGB → HSL → 偏移 H/S/L → RGB；六区间按三角色相权重混合，",
         "overlap 控制区间互相渗透的宽度；无彩像素跳过，避免灰阶染色"],
        "GeglOperationPointFilter（逐像素，可多线程分块）",
        "GIMP 内置「色相-饱和度」（HSL 空间重写）",
    ),
    "hsl-seven": (
        "lb:hsl-seven", "HSL 7 Bands", "HSL 7 Bands",
        "红/橙/黄/绿/青/蓝/紫七段色相各自调 H/S/L，ACR 风格",
        ["21 个滑块按色相段加权叠加，段间由 feather 平滑过渡；",
         "低于 min-saturation 的灰像素可选择跳过"],
        "GeglOperationPointFilter",
        "Camera Raw 的 HSL 面板",
    ),
    "channel-mixer-plus": (
        "lb:channel-mixer-plus", "Channel Mixer Plus", "Channel Mixer Plus",
        "PS 通道混合器：每路输出通道由 RGB 三源加权相加，并带通道偏移",
        ["3×3 混合矩阵 + 每通道 offset；monochrome 打开时改用单组系数转灰"],
        "GeglOperationPointFilter",
        "GEGL 官方 channel-mixer（补 RGB offset、去 preserve luminosity）",
    ),
    "channel-range-to-alpha": (
        "lb:channel-range-to-alpha", "Range → Alpha", "Channel Range to Alpha",
        "按通道数值区间（0–255）生成 alpha，实现「混合颜色带」式透明控制",
        ["选定 RGB / 亮度 / LAB L·A·B 通道，区间内不透明，",
         "区间外按 fuzziness 与 feather 平滑衰减"],
        "GeglOperationPointFilter",
        "Photoshop「混合颜色带」(Blend If)",
    ),
    "cmyk-primary-correction": (
        "lb:cmyk-primary-correction", "CMYK Primary", "CMYK Primary Correction",
        "PS 可选颜色：红/黄/绿/青/蓝/品红/白/中性/黑九组各自独立记忆 C/M/Y/K",
        ["RGB → CMYK；九组色域分别算权重，逐像素把九组偏移同时叠加，",
         "支持绝对 / 相对两种模式，灰阶不受影响"],
        "GeglOperationPointFilter",
        "Photoshop「可选颜色」(Selective Color)",
    ),
    "color-balance": (
        "lb:color-balance", "Color Balance", "Color Balance",
        "PS 色彩平衡：阴影 / 中间调 / 高光各自调 C-R、M-G、Y-B 三对色轴",
        ["在 8bit sRGB 伽马域反推 PS 曲线，两种模式：",
         "原版 = 三区间独立通道曲线；MATLAB 版 = 零和矩阵（保明度）",
         "输入须为伽马编码 sRGB，勿在前置节点用 linear-rgb"],
        "GeglOperationFilter",
        "zhuanlan.zhihu.com/p/679776283 、/p/59450298（PS 色彩平衡原理）",
    ),
    "colorize-hsl": (
        "lb:colorize-hsl", "Colorize", "Colorize",
        "单色罩染：替换色相与饱和度，保留画面原有明暗结构",
        ["三通道 Overlay 叠灰层调明度 → 取 HSL 的 L → 换 H/S → 回 RGB；",
         "输出的像素间差异只来自 L"],
        "GeglOperationFilter",
        "Photoshop「颜色」调整层 + Overlay 着色",
    ),
    "color-mask-select": (
        "lb:color-mask-select", "Mask by Color", "Color Mask Select",
        "PS 色彩范围：按指定色 + 容差 + 羽化生成蒙版，可红色叠加预览",
        ["九组预设色或图像取色 → 色距判定 → fuzziness / feather 生成 alpha"],
        "GeglOperationPointFilter",
        "Photoshop「色彩范围」(Color Range)",
    ),
    "lab-levels": (
        "lb:lab-levels", "LAB Levels", "LAB Levels",
        "LAB 三通道各自设输入 / 输出黑白场与伽马",
        ["L/a/b 分别做 levels 映射后合并，a/b 以 0.5 为中性轴"],
        "GeglOperationFilter",
        None,
    ),
    "exposure": (
        "lb:exposure", "Exposure", "Exposure",
        "PS 曝光：EV、偏移、伽马三段式调整",
        ["在 8bit sRGB 伽马域反推 PS 曝光层公式；",
         "输入须为伽马编码 sRGB，勿在前置节点用 linear-rgb"],
        "GeglOperationFilter",
        "Photoshop「曝光」调整层",
    ),
    "rgb-domain-grayscale": (
        "lb:rgb-domain-grayscale", "Grayscale", "Grayscale",
        "PS 黑白：六个色相滑块（红/黄/绿/青/蓝/品红）加权转灰，可着色",
        ["RGB 三通道按六色权重加权求和，-200~300 区间与 PS 界面对齐"],
        "GeglOperationPointFilter",
        "Photoshop「黑白」(Black & White)",
    ),
    "vibrance-hyper": (
        "lb:vibrance-hyper", "Vibrance", "Vibrance",
        "自然饱和度：优先提升低饱和区，保护高饱和与肤色",
        ["双曲函数给出自适应增益，再乘全局线性饱和度"],
        "GeglOperationPointFilter",
        None,
    ),
    "xyz-multiply": (
        "lb:xyz-multiply", "XYZ Multiply", "XYZ Multiply",
        "以参考色在 XYZ 域做正片叠底，白点可选 D50/D55/D65/D75",
        ["sRGB → XYZ 乘叠 → 回 sRGB，opacity 控制混合比例"],
        "GeglOperationPointFilter",
        "正片叠底 (Multiply) 的 XYZ 域实现",
    ),
}


def box(op_id, label, action, algo, otype, ref):
    lines = []
    lines.append("/* " + "=" * (WIDTH - 3))
    lines.append(" * SuperMrWang · GEGL Operation")
    lines.append(" * " + "-" * (WIDTH - 3))
    lines.append(f" * id     : {op_id}")
    lines.append(f" * 菜单   : {label}")
    lines.append(f" * 作用   : {action}")
    for i, a in enumerate(algo):
        lines.append(f" * {'算法   : ' if i == 0 else '         '}{a}")
    lines.append(f" * 类型   : {otype}")
    if ref:
        lines.append(f" * 参考   : {ref}")
    lines.append(" * 许可   : GPL-3.0-or-later，见工程根目录 LICENSE")
    lines.append(" * " + "=" * (WIDTH - 6) + " */")
    return "\n".join(lines)


KEYS = ("name", "title", "categories", "description",
        "gimp:menu-path", "gimp:menu-label")


def align_set_keys(src):
    """把 class_set_keys 的键值列对齐（最长的键是 gimp:menu-label）。"""
    start = src.index("gegl_operation_class_set_keys")
    end = src.index("NULL);", start)
    block = src[start:end]
    lines = block.split("\n")

    key_re = re.compile(r'^(\s*)"(' + "|".join(re.escape(k) for k in KEYS) + r')",[ \t]*(.+)$')
    base = None
    for ln in lines[1:]:
        m = key_re.match(ln)
        if m:
            base = len(m.group(1))
            break
    if base is None:
        return src

    width = max(len(f'"{k}",') for k in KEYS)      # 17
    val_col = base + width + 1
    out = []
    for ln in lines:
        m = key_re.match(ln)
        if m:
            out.append(" " * base + f'"{m.group(2)}",'.ljust(width) + " " + m.group(3))
        elif re.match(r"^\s*\"", ln):               # 字符串续行
            out.append(" " * (val_col + 2) + ln.strip())
        else:
            out.append(ln)
    new_block = "\n".join(out)
    return src[:start] + new_block + src[end:]


def includes(body, name):
    """include 顺序固定：config.h -> gi18n-lib.h -> math.h -> string.h（按需）。"""
    out = ['#include "config.h"', "#include <glib/gi18n-lib.h>", "#include <math.h>"]
    if re.search(r"\b(memset|memcpy|memmove|memcmp|strlen|strcmp|strcpy)\s*\(", body):
        out.append("#include <string.h>")
    return "\n".join(out)


def _w(s):
    """显示宽度：CJK / 全角按 2 列算。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def _divider(indent, name, width=WIDTH):
    """生成统一的分隔注释：/* ---- 名称 ---------...---------- */"""
    lead, head, tail = "/* ---- ", " ", " */"
    fill = width - len(indent) - len(lead) - _w(name) - len(tail)
    if fill < 2:
        return f"{indent}{lead}{name}{tail}"
    return f"{indent}{lead}{name}{' '}{'-' * (fill - 1)}{tail}"


DIV_SLASH = re.compile(r'^(\s*)//\s*[=-]{3,}\s*(.+?)\s*[=-]{3,}\s*$')
DIV_BLOCK = re.compile(r'^(\s*)/\*[\s=-]{3,}(.+?)\s*[=-]{3,}\s*\*/\s*$')
LINE_SLASH = re.compile(r'^(\s*)//\s*(\S.*?)\s*$')


def normalize_comments(src):
    """统一注释分隔线为 /* ---- 名称 ---- */，并把整行 // 注释改为 /* */。"""
    out, in_block = [], False
    for line in src.split("\n"):
        if in_block:
            out.append(line)
            if "*/" in line:
                in_block = False
            continue

        m = DIV_SLASH.match(line) or DIV_BLOCK.match(line)
        if m:
            out.append(_divider(m.group(1), m.group(2)))
            continue

        m = LINE_SLASH.match(line)
        if m and "*/" not in m.group(2):
            out.append(f"{m.group(1)}/* {m.group(2)} */")
            continue

        out.append(line)
        if "/*" in line and line.rfind("/*") > line.rfind("*/"):
            in_block = True
    return "\n".join(out)


def rewrite(path, name):
    raw = open(path, "rb").read().decode("utf-8")
    src = raw.replace("\r\n", "\n")

    idx = src.index("#ifdef GEGL_PROPERTIES")
    body = src[idx:]

    op_id, label, title, action, algo, otype, ref = OPS[name]

    head = "\n".join([
        box(op_id, label, action, algo, otype, ref),
        "",
        includes(body, name),
        "",
        "",
    ])

    body = re.sub(r'^(\s*"title",\s*)(?:_\()?"[^"]*"\)?,',
                  lambda m: f'{m.group(1)}_("{title}"),', body, count=1, flags=re.M)
    body = re.sub(r'^(\s*"gimp:menu-label",\s*)(?:_\()?"[^"]*"\)?,',
                  lambda m: f'{m.group(1)}_("{label}"),', body, count=1, flags=re.M)
    # GEGL_OP_NAME 决定 GType 名，必须全局唯一 —— 统一加 lb_ 前缀，
    # 否则会与 GEGL 自带算子撞名（例如 core 的 "exposure"）。
    body = re.sub(r'(#define\s+GEGL_OP_NAME\s+)\w+',
                  lambda m: m.group(1) + "lb_" + name.replace("-", "_"), body, count=1)

    # 属性块起始统一：`#ifdef GEGL_PROPERTIES` 后空一行
    body = re.sub(r'^#ifdef GEGL_PROPERTIES\n(?!\n)', "#ifdef GEGL_PROPERTIES\n\n",
                  body, count=1, flags=re.M)

    body = align_set_keys(body)
    body = normalize_comments(body)

    return head + body


def main():
    write = "--write" in sys.argv
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    changed = 0
    for path in sorted(glob.glob(os.path.join(root, "ops", "*", "*.c"))):
        name = os.path.basename(os.path.dirname(path))
        if name not in OPS:
            print(f"跳过（无元数据）: {name}")
            continue
        new = rewrite(path, name)
        old = open(path, "rb").read().decode("utf-8").replace("\r\n", "\n")
        if new == old:
            print(f"  不变  {name}")
            continue
        changed += 1
        if write:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(new)
            print(f"  写入  {name}")
        else:
            print(f"  待改  {name}  (-{len(old.splitlines())} +{len(new.splitlines())} 行)")
    print(f"共 {changed} 个文件{'已更新' if write else '待更新'}（--write 落盘）")


if __name__ == "__main__":
    main()
