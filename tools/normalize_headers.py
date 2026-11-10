#!/usr/bin/env python3
"""统一 13 个算子的文件头注释、include 块与展示名。

用法：
    python tools/normalize_headers.py            # 预览（不写盘）
    python tools/normalize_headers.py --write    # 实际写入

约定（改工程时请保持）：
  1. 文件头是 6 字段的中英双语注释盒：
     id / menu / purpose / algorithm / type / reference(可选) / license
     每个字段先中文、后英文，英文另起一行，全部折行到 78 列以内
  2. include 顺序固定：config.h -> gi18n-lib.h -> math.h -> string.h（按需）
  3. 行尾统一 LF
  4. "title" 与 "gimp:menu-label" 一律用 _() 包住，且标题以菜单名为前缀
  5. 展示名不得与 GIMP/GEGL 自带算子重名（见 README「命名与代码风格约定」）
"""
import glob
import os
import re
import sys

WIDTH = 78

# 每个算子一条：id / 菜单名 / 标题 / 作用 / 算法 / 类型 / 参考，作用与算法中英各一份。
# 展示名一律避开 GIMP/GEGL 自带算子名（Exposure / Vibrance / Grayscale 已被占用）。
OPS = {
    "hue-saturation": dict(
        id="lb:hue-saturation", label="Hue/Saturation", title="Hue/Saturation",
        purpose_zh="全局或按红/黄/绿/青/蓝/品红六个色相区间调整色相、饱和度、明度",
        purpose_en="Adjust hue, saturation and lightness globally, or inside six hue "
                   "ranges (red, yellow, green, cyan, blue, magenta).",
        algo_zh="RGB → HSL → 偏移 H/S/L → RGB；六区间按三角色相权重混合，overlap 控制区间"
                "互相渗透的宽度；无彩像素跳过，避免灰阶染色",
        algo_en="RGB -> HSL, add the H/S/L offsets, back to RGB. The six ranges are "
                "blended with triangular hue weights, and 'overlap' sets how far each "
                "range bleeds into its neighbours. Achromatic pixels are skipped so "
                "greys are never tinted.",
        type="GeglOperationPointFilter（逐像素 / per-pixel）",
        ref_zh="GIMP 内置「色相-饱和度」（HSL 空间重写）",
        ref_en="GIMP Hue-Saturation dialog, reimplemented in HSL space",
    ),
    "hsl-seven": dict(
        id="lb:hsl-seven", label="HSL 7 Bands", title="HSL 7 Bands",
        purpose_zh="红/橙/黄/绿/青/蓝/紫七段色相各自调 H/S/L，ACR 风格",
        purpose_en="Seven hue bands (red, orange, yellow, green, cyan, blue, purple), "
                   "each with its own H/S/L shift, Camera Raw style.",
        algo_zh="21 个滑块按色相段加权叠加，段间由 feather 平滑过渡；低于 min-saturation "
                "的灰像素可选择跳过",
        algo_en="The 21 sliders are weighted by hue band and summed, with 'feather' "
                "cross-fading adjacent bands. Pixels below 'min-saturation' can be "
                "skipped.",
        type="GeglOperationPointFilter（逐像素 / per-pixel）",
        ref_zh="Camera Raw 的 HSL 面板",
        ref_en="Adobe Camera Raw HSL panel",
    ),
    "channel-mixer-plus": dict(
        id="lb:channel-mixer-plus", label="Channel Mixer Plus",
        title="Channel Mixer Plus",
        purpose_zh="PS 通道混合器：每路输出通道由 RGB 三源加权相加，并带通道偏移",
        purpose_en="PS Channel Mixer: every output channel is a weighted sum of R/G/B, "
                   "plus a constant offset per channel.",
        algo_zh="3×3 混合矩阵 + 每通道 offset；monochrome 打开时改用单组系数转灰",
        algo_en="A 3x3 mixing matrix plus one offset per channel; with 'monochrome' a "
                "single set of coefficients produces grey.",
        type="GeglOperationPointFilter（逐像素 / per-pixel）",
        ref_zh="GEGL 官方 channel-mixer（补 RGB offset、去 preserve luminosity）",
        ref_en="GEGL core channel-mixer, with per-channel offsets added and "
               "keep-luminosity dropped",
    ),
    "channel-range-to-alpha": dict(
        id="lb:channel-range-to-alpha", label="Range → Alpha",
        title="Channel Range to Alpha",
        purpose_zh="按通道数值区间（0–255）生成 alpha，实现「混合颜色带」式透明控制",
        purpose_en="Build alpha from a numeric range (0-255) of one channel, i.e. "
                   "Blend-If style transparency.",
        algo_zh="选定 RGB / 亮度 / LAB L·A·B 通道，区间内不透明，区间外按 fuzziness 与 "
                "feather 平滑衰减",
        algo_en="Pick an RGB, luminance or LAB L/a/b channel. Values inside the range "
                "stay opaque, values outside fade out by 'fuzziness' and 'feather'.",
        type="GeglOperationPointFilter（逐像素 / per-pixel）",
        ref_zh="Photoshop「混合颜色带」(Blend If)",
        ref_en="Photoshop Blend If",
    ),
    "cmyk-primary-correction": dict(
        id="lb:cmyk-primary-correction", label="CMYK Primary",
        title="CMYK Primary Correction",
        purpose_zh="PS 可选颜色：红/黄/绿/青/蓝/品红/白/中性/黑九组各自独立记忆 C/M/Y/K",
        purpose_en="PS Selective Color: nine ranges (red, yellow, green, cyan, blue, "
                   "magenta, white, neutral, black), each keeping its own C/M/Y/K "
                   "values.",
        algo_zh="RGB → CMYK；九组色域分别算权重，逐像素把九组偏移同时叠加，支持绝对 / "
                "相对两种模式，灰阶不受影响",
        algo_en="RGB -> CMYK. All nine ranges are weighted per pixel and their offsets "
                "are summed simultaneously; absolute and relative modes are supported "
                "and greys are left untouched.",
        type="GeglOperationPointFilter（逐像素 / per-pixel）",
        ref_zh="Photoshop「可选颜色」(Selective Color)",
        ref_en="Photoshop Selective Color",
    ),
    "color-balance": dict(
        id="lb:color-balance", label="Color Balance", title="Color Balance",
        purpose_zh="PS 色彩平衡：阴影 / 中间调 / 高光各自调 C-R、M-G、Y-B 三对色轴",
        purpose_en="PS Color Balance: shadow, midtone and highlight each carry three "
                   "axis pairs (C-R, M-G, Y-B).",
        algo_zh="在 8bit sRGB 伽马域反推 PS 曲线，两种模式：原版 = 三区间独立通道曲线；"
                "MATLAB 版 = 零和矩阵（保明度）。输入须为伽马编码 sRGB，勿在前置节点用 "
                "linear-rgb",
        algo_en="Reverse-engineered PS curves in 8-bit sRGB gamma space, two modes: "
                "original = independent per-region channel curves, MATLAB = zero-sum "
                "matrix that preserves luminosity. Feed gamma-encoded sRGB; do not "
                "insert linear-rgb before this op.",
        type="GeglOperationFilter（需整块区域 / whole-region）",
        ref_zh=["色彩平衡调整图层的本质-背后的数学原理（王先生的副业）",
                "https://zhuanlan.zhihu.com/p/679776283",
                "Photoshop 中的色彩平衡调整图层的原理分析（章佳杰）",
                "https://zhuanlan.zhihu.com/p/59450298"],
        ref_en=["The math behind the Color Balance layer / Wang's side project",
                "https://zhuanlan.zhihu.com/p/679776283",
                "How the Photoshop Color Balance layer really works / Zhang Jiajie",
                "https://zhuanlan.zhihu.com/p/59450298"],
    ),
    "colorize-hsl": dict(
        id="lb:colorize-hsl", label="Colorize", title="Colorize",
        purpose_zh="单色罩染：替换色相与饱和度，保留画面原有明暗结构",
        purpose_en="Monochrome tint: substitute hue and saturation while keeping the "
                   "original luminance structure.",
        algo_zh="三通道 Overlay 叠灰层调明度 → 取 HSL 的 L → 换 H/S → 回 RGB；输出的像素"
                "间差异只来自 L",
        algo_en="Overlay every channel with a grey layer to shape lightness, take L "
                "from HSL, substitute H/S, convert back to RGB. The output varies "
                "between pixels only in L.",
        type="GeglOperationFilter（需整块区域 / whole-region）",
        ref_zh="Photoshop「颜色」调整层 + Overlay 着色",
        ref_en="Photoshop Color fill layer over an Overlay-blended grey",
    ),
    "color-mask-select": dict(
        id="lb:color-mask-select", label="Mask by Color", title="Color Mask Select",
        purpose_zh="PS 色彩范围：按指定色 + 容差 + 羽化生成蒙版，可红色叠加预览",
        purpose_en="PS Color Range: build a mask from a picked colour, a fuzziness "
                   "radius and feathering, with an optional red overlay preview.",
        algo_zh="九组预设色或图像取色 → 色距判定 → fuzziness / feather 生成 alpha",
        algo_en="Nine preset colours or a colour sampled from the image -> distance "
                "test -> alpha from 'fuzziness' and 'feather'.",
        type="GeglOperationPointFilter（逐像素 / per-pixel）",
        ref_zh="Photoshop「色彩范围」(Color Range)",
        ref_en="Photoshop Color Range",
    ),
    "lab-levels": dict(
        id="lb:lab-levels", label="LAB Levels", title="LAB Levels",
        purpose_zh="LAB 三通道各自设输入 / 输出黑白场与伽马",
        purpose_en="Independent input/output black-white points and gamma for each "
                   "LAB channel.",
        algo_zh="L/a/b 分别做 levels 映射后合并，a/b 以 0.5 为中性轴",
        algo_en="Levels are applied per L/a/b channel and then merged; a and b use 0.5 "
                "as the neutral axis.",
        type="GeglOperationFilter（需整块区域 / whole-region）",
        ref_zh=None, ref_en=None,
    ),
    "exposure": dict(
        id="lb:exposure", label="Exposure EV", title="Exposure EV",
        purpose_zh="PS 曝光：EV、偏移、伽马三段式调整（按 EV 计曝光档位）",
        purpose_en="PS Exposure: EV, offset and gamma in three stages, measured in "
                   "exposure stops.",
        algo_zh="在 8bit sRGB 伽马域反推 PS 曝光层公式；输入须为伽马编码 sRGB，勿在前置"
                "节点用 linear-rgb",
        algo_en="Reverse-engineered from the PS Exposure layer in 8-bit sRGB gamma "
                "space. Feed gamma-encoded sRGB; do not insert linear-rgb before this "
                "op.",
        type="GeglOperationFilter（需整块区域 / whole-region）",
        ref_zh="Photoshop「曝光」调整层",
        ref_en="Photoshop Exposure adjustment layer",
    ),
    "rgb-domain-grayscale": dict(
        id="lb:rgb-domain-grayscale", label="Black & White", title="Black & White",
        purpose_zh="PS 黑白：六个色相滑块（红/黄/绿/青/蓝/品红）加权转灰，可着色",
        purpose_en="PS Black & White: six hue sliders (red, yellow, green, cyan, blue, "
                   "magenta) weight the grey conversion, with optional tinting.",
        algo_zh="RGB 三通道按六色权重加权求和，-200~300 区间与 PS 界面对齐",
        algo_en="The three RGB channels are summed with six hue weights; the -200..300 "
                "slider range matches the PS dialog.",
        type="GeglOperationPointFilter（逐像素 / per-pixel）",
        ref_zh="Photoshop「黑白」(Black & White)",
        ref_en="Photoshop Black & White",
    ),
    "vibrance-hyper": dict(
        id="lb:vibrance-hyper", label="Natural Saturation",
        title="Natural Saturation",
        purpose_zh="自然饱和度：提升低饱和区，抑制高饱和与肤色，不破坏色相",
        purpose_en="Natural saturation: lift muted colours while holding back highly "
                   "saturated ones and skin tones, without moving hue.",
        algo_zh="LAB 下按源图色度 C* 取双曲增益，叠加肤色色相窗；色度沿固定色相放大后按"
                "色域二分收敛，避免裁剪扭色",
        algo_en="In LAB a hyperbolic gain is driven by the source chroma C*, gated by a "
                "skin-hue window. Chroma grows along a fixed hue and is bisected back "
                "into gamut instead of being clipped.",
        type="GeglOperationPointFilter（逐像素 / per-pixel）",
        ref_zh="Adobe Camera Raw / Photoshop 的 Vibrance",
        ref_en="Adobe Camera Raw / Photoshop Vibrance",
    ),
    "xyz-multiply": dict(
        id="lb:xyz-multiply", label="XYZ Multiply", title="XYZ Multiply",
        purpose_zh="以参考色在 XYZ 域做正片叠底，白点可选 D50/D55/D65/D75",
        purpose_en="Multiply blend against a reference colour in XYZ space; the white "
                   "point can be D50/D55/D65/D75.",
        algo_zh="sRGB → XYZ 乘叠 → 回 sRGB，opacity 控制混合比例",
        algo_en="sRGB -> XYZ, multiply, back to sRGB; 'opacity' sets the blend amount.",
        type="GeglOperationPointFilter（逐像素 / per-pixel）",
        ref_zh="正片叠底 (Multiply) 的 XYZ 域实现",
        ref_en="Multiply blend, implemented in XYZ space",
    ),
}

LABEL_W = 10          # 字段名列宽
CONTENT_W = WIDTH - 3 - LABEL_W - 1


def _wrap(text, width=CONTENT_W):
    """按显示宽度折行：拉丁词不断开，CJK 逐字可断，收尾标点跟随前一个词。"""
    raw = re.findall(r"-?[0-9][0-9A-Za-z_\-'./:+=%#]*"
                     r"|[A-Za-z0-9][A-Za-z0-9_\-'./:+=%#]*"
                     r"|'[^']*'|\s+|.", text)
    units = []
    for u in raw:                                   # 收尾标点并入前一个单元，避免行首标点
        if len(u) == 1 and u in ")]}>,.;:!?%，。；、：）」』" and units and not units[-1].isspace():
            units[-1] += u
            continue
        units.append(u)

    lines, cur, curw, gap = [], "", 0, False
    for u in units:
        if u.isspace():
            gap = True
            continue
        piece = (" " if gap and cur else "") + u
        if cur and curw + _w(piece) > width:
            lines.append(cur)
            cur, curw = u, _w(u)
        else:
            cur += piece
            curw += _w(piece)
        gap = False
    if cur:
        lines.append(cur)
    for i in range(len(lines) - 1, 0, -1):          # 兜底：标点仍落行首就挪回上一行
        while lines[i] and lines[i][0] in "，。；、：）」』！？%,.;:)]}":
            lines[i - 1] += lines[i][0]
            lines[i] = lines[i][1:]
    return [l.strip() for l in lines if l.strip()]


def box(op):
    out = ["/* " + "=" * (WIDTH - 3),
           " * SuperMrWang · GEGL 算子 / GEGL Operation",
           " * " + "-" * (WIDTH - 3)]

    def field(label, value):
        paras = []
        for v in (value if isinstance(value, list) else [value]):
            paras.extend(v if isinstance(v, list) else [v])     # 参考可传多段（含 URL 单行）
        first = True
        for p in paras:
            for ln in _wrap(p):
                head = (" * " + label.ljust(LABEL_W) + " ") if first else (" * " + " " * LABEL_W + " ")
                out.append(head + ln)
                first = False

    field("id", op["id"])
    field("menu", op["label"])
    field("purpose", [op["purpose_zh"], op["purpose_en"]])
    field("algorithm", [op["algo_zh"], op["algo_en"]])
    field("type", op["type"])
    if op.get("ref_zh"):
        field("reference", [op["ref_zh"], op["ref_en"]])
    field("license", ["GPL-3.0-or-later，见工程根目录 LICENSE",
                      "GPL-3.0-or-later, see LICENSE at the project root"])
    out.append(" * " + "=" * (WIDTH - 6) + " */")
    return "\n".join(out)


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

    meta = OPS[name]
    title, label = meta["title"], meta["label"]

    head = "\n".join([
        box(meta),
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
