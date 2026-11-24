#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给每个算子页生成一张「原图 / 结果」对比插图。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/make_op_shots.py').read())" --quit

    # 只跑某几个（调试）
    LB_ONLY=color-balance,vibrance ...

产物：ops/<dir>/assets/shot.png，以及 tools/site/shots.json（每张图的参数说明，
中英各一份，site_build 拿来当 figcaption —— 参数只在这里写一次）。

参数从 `gegl --info` 抓，量程以 ops/<dir>/README.md 的参数表为准。测试卡由
tools/make_test_card.py 生成，所有算子共用同一张，所以 53 张图横向可比。

跑完会打印结果与原图的平均差；低于 1.5 码说明这组参数基本没效果，要么参数
写错、要么该算子得换一种输入（多输入 / 带 alpha / 坐标串），需要单独处理。
"""
import json
import os
import subprocess

import cairo

ROOT = os.environ.get("LB_REPO") or \
    r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
GEGL = r"D:\fastsoftware\GIMP 3\bin\gegl.exe"
CARD = os.path.join(ROOT, "tools", "_testcard.png")
TMP = os.path.join(ROOT, "tools", "_shots")
MANIFEST = os.path.join(ROOT, "tools", "site", "shots.json")

CELL_W, CELL_H = 460, 307          # 每格 3:2，页面显示约 370 宽
GAP = 14
PAD = 8

# 细节类算子（锐化/降噪/噪点/去尘）在整图缩略上根本看不出来：4 px 的栅格
# 缩到一半就糊成灰块。这类给 crop 一个 1:1 的局部窗口，其余算子看整卡。
TEX = (500, 333, 460, 307)         # 1:1 窗口：苹果下半 + 木桌 + 灰阶右端 + 栅格与噪点


def _mesh_string(cols=3, rows=3, w=960, h=640, bulge=72.0):
    """3×3 均匀网格，把内侧四个交点往下拉，做出「向外鼓」的形变。

    格式：`cols,rows;x,y,ux,uy,vx,vy,auto;…`，切向给 0 让算子按邻居自动重算，
    值里不能有空格（GEGL CLI 按空格拆参数）。
    """
    cw, ch = w / float(cols), h / float(rows)
    parts = ["%d,%d" % (cols, rows)]
    for j in range(rows + 1):
        for i in range(cols + 1):
            x, y = i * cw, j * ch
            if 0 < i < cols and 0 < j < rows:
                y += bulge
            parts.append("%.1f,%.1f,0,0,0,0,1" % (x, y))
    return ";".join(parts)


# (目录, op, 参数, 中文说明, 英文说明, crop)
# 参数值全部落在 README 参数表的量程内，且要「一眼看得出来」。
CASES = [
    # ---- 明暗 / 对比 ----
    ("brightness-contrast", "lb:brightness-contrast",
     {"brightness": 30, "contrast": 28},
     "亮度 +30、对比 +28（新版曲线）",
     "Brightness +30, Contrast +28 (modern curve)", None),
    ("levels", "lb:levels",
     {"in-low": 22, "in-gamma": 1.2, "in-high": 232},
     "输入 22–232、中间调 gamma 1.2",
     "Input 22–232, midtone gamma 1.2", None),
    ("exposure", "lb:exposure",
     {"exposure": 0.8, "offset": 0.02},
     "曝光 +0.8 EV、偏移 +0.02（线性光里加）",
     "Exposure +0.8 EV, Offset +0.02 (added in linear light)", None),
    ("shadows-highlights", "lb:shadows-highlights",
     {"shadows-amount": 60, "highlights-amount": 45,
      "shadows-radius": 25, "highlights-radius": 25},
     "阴影 +60、高光 −45、半径 25",
     "Shadows +60, Highlights −45, radius 25", None),

    # ---- 整体色彩 ----
    ("color-balance", "lb:color-balance",
     {"midtone-cr": 35, "midtone-yb": -20, "preserve-luminosity": "true"},
     "中间调 青←→红 +35、黄←→蓝 −20，保留明度",
     "Midtone Cyan–Red +35, Yellow–Blue −20, preserve luminosity", None),
    ("color-temperature-tint", "lb:color-temperature-tint",
     {"temperature": 45, "tint": 12},
     "色温 +45（偏暖）、色调 +12（偏洋红）",
     "Temperature +45 (warmer), Tint +12 (magenta)", None),
    ("color-grading", "lb:color-grading",
     {"global-hue": 200, "global-sat": 25,
      "shadow-lum": -15, "high-lum": 10, "balance": -20},
     "全局色相 200°、饱和 +25；阴影压暗、高光提亮",
     "Global hue 200°, sat +25; shadows −15, highlights +10", None),
    ("vibrance", "lb:vibrance",
     {"vibrance": 85},
     "自然饱和度 +65（低饱和加得多、红色受保护）",
     "Vibrance +65 (low-saturation colours gain most, reds protected)", None),
    ("vibrance-hyper", "lb:vibrance-hyper",
     {"vibrance": 85, "saturation": 25},
     "自然饱和度 +70、饱和度 +15",
     "Vibrance +70, Saturation +15", None),
    ("hue-saturation", "lb:hue-saturation",
     {"hue": 25, "saturation": 30},
     "整体色相 +25°、饱和度 +30",
     "Hue +25°, Saturation +30 (whole image)", None),
    ("hue-saturation-basic", "lb:hue-saturation-basic",
     {"hue": 30, "saturation": 35},
     "整体色相 +30°、饱和度 +35",
     "Hue +30°, Saturation +35", None),
    ("colorize-hsl", "lb:colorize-hsl",
     {"hue": 35, "saturation": 45},
     "色相 35°、饱和 45%（单色调上色）",
     "Hue 35°, Saturation 45% (monochrome tint)", None),
    ("rgb-domain-grayscale", "lb:rgb-domain-grayscale",
     {"red": 120, "yellow": 90, "green": 40,
      "blue": 10, "cyan": 20, "magenta": 140},
     "按色系加权的黑白：红/洋红重、蓝轻",
     "Hue-weighted black & white: red/magenta heavy, blue light", None),
    ("channel-mixer-plus", "lb:channel-mixer-plus",
     {"rr-gain": 1.18, "rg-gain": 0.12, "gg-gain": 0.9,
      "bb-gain": 0.82, "gr-gain": 0.08},
     "输出 R 取 1.18R+0.12G、G 混 0.08R、B 压到 0.82",
     "R = 1.18R + 0.12G, G mixes 0.08R, B scaled to 0.82", None),
    ("xyz-multiply", "lb:xyz-multiply",
     {"overlay-color": "rgb(0.96,0.78,0.48)", "opacity": 0.85},
     "照片滤镜色 暖橙、密度 85%、保留明度",
     "Photo-filter colour warm orange, density 85%, preserve luminosity", None),

    # ---- 色阶家族 ----
    ("hsb-levels", "lb:hsb-levels",
     {"s-in-black": 12, "b-in-white": 240, "h-gamma": 1.3},
     "S 输入黑场 12、B 输入白场 240、H gamma 1.3",
     "S black point 12, B white point 240, H gamma 1.3", None),
    ("cmyk-levels", "lb:cmyk-levels",
     {"c-in-black": 45, "y-in-white": 190, "m-gamma": 1.3},
     "C 输入黑场 45、Y 输入白场 190、M gamma 1.3",
     "C black 45, Y white 190, M gamma 1.3", None),
    ("lab-levels", "lb:lab-levels",
     {"a-in-black": -20, "a-in-white": 100, "b-in-white": 95},
     "a 输入 −20–100、b 白场 95（暖调收窄）",
     "a input −20–100, b white point 95", None),
    ("lch-levels", "lb:lch-levels",
     {"c-in-white": 100, "l-in-black": 8, "h-gamma": 1.2},
     "C 白场 100、L 黑场 8、H gamma 1.2",
     "C white 100, L black 8, H gamma 1.2", None),

    # ---- 曲线家族 ----
    ("lab-curves", "lb:lab-curves",
     {"curves": "L 0,0 0.3,0.2 0.75,0.85 1,1|a 0,0 1,1|b 0,0 1,1"},
     "L 通道 S 形（0.3→0.2、0.75→0.85）",
     "S-curve on L (0.3→0.2, 0.75→0.85)", None),
    ("lch-curves", "lb:lch-curves",
     {"curves": "L 0,0 1,1|C 0,0 0.55,0.72 1,1|h 0,0.55 0.5,0.5 1,0.55"},
     "C 中段抬到 0.72、色相偏移曲线（红橙段 +18°）",
     "C lifted to 0.72 mid-range, hue offset curve (+18° on reds)", None),
    ("hsv-curves", "lb:hsv-curves",
     {"curves": "H 0,0.5 1,0.5|S 0,0 0.4,0.62 1,1|V 0,0 1,1"},
     "S 中段抬到 0.62（低饱和加得多）",
     "S raised to 0.62 in the low/mid range", None),
    ("cmyk-curves", "lb:cmyk-curves",
     {"curves": "C 0,0 1,1|M 0,0 1,1|Y 0,0 0.35,0.62 1,1|K 0,0 1,1"},
     "Y 中段下压到 0.35→0.62（褪黄）",
     "Y pushed down to 0.35→0.62 (less yellow)", None),

    # ---- 细节（1:1 局部）----
    ("unsharp-mask", "lb:unsharp-mask",
     {"radius": 2.5, "amount": 180, "threshold": 0},
     "半径 2.5、数量 180%、阈值 0",
     "Radius 2.5, Amount 180%, Threshold 0", TEX),
    ("reduce-noise", "lb:reduce-noise",
     {"strength": 85, "detail": 15, "radius": 3},
     "强度 85、保留细节 15、半径 3",
     "Strength 85, Preserve detail 15, Radius 3", TEX),
    ("add-noise", "lb:add-noise",
     {"amount": 45, "monochrome": "true", "seed": 7},
     "数量 45%、单色、种子 7",
     "Amount 45%, monochromatic, seed 7", TEX),
    ("dust-scratches", "lb:dust-scratches",
     {"radius": 4, "threshold": 60},
     "半径 4、阈值 60",
     "Radius 4, Threshold 60", TEX),
    # ---- 其它色彩模型的分量色阶 ----
    ("hsi-levels", "lb:hsi-levels",
     {"s-in-black": 15, "i-gamma": 1.25},
     "S 输入黑场 15、I gamma 1.25",
     "S black point 15, I gamma 1.25", None),
    ("hsl-levels", "lb:hsl-levels",
     {"s-in-black": 15, "l-gamma": 1.25},
     "S 输入黑场 15、L gamma 1.25",
     "S black point 15, L gamma 1.25", None),
    ("hue-range-basic", "lb:hue-range-basic",
     {"channel": "reds", "hue": -45, "saturation": 25, "lightness": 8},
     "锁定红色域：色相 −45°、饱和 +25、明度 +8",
     "Reds range: hue −45°, saturation +25, lightness +8", None),
    ("hsl-bands", "lb:hsl-bands",
     {"hue-feather": 30, "saturation-min": 8, "red-hue": -50, "red-sat": 35},
     "红域色相 −50°、饱和 +35；色相过渡 30°",
     "Reds: hue −50°, saturation +35; hue feather 30°", None),
    ("max-min", "lb:max-min",
     {"mode": "minimum", "shape": "round", "radius": 4},
     "最小值（腐蚀）、圆形、半径 4",
     "Minimum (erode), round, radius 4", None),
    ("color-mask-select", "lb:color-mask-select",
     {"mask-mode": "red", "fuzziness": 55},
     "红色域蒙版、容差 55",
     "Red range mask, fuzziness 55", None),
    # l1/l2/r1/r2 是 process 里 g_object_get 读的动态属性，gegl --info 不列它，
    # 但 CLI 能传；不传就是 0/0/0/0 —— 那才是「跑了等于没跑」的原因。
    ("channel-range-to-alpha", "lb:channel-range-to-alpha",
     {"channel": "lab-l", "l1": 0, "l2": 20, "r1": 140, "r2": 160},
     "LAB 亮度低于 20 或高于 140 的部分变透明",
     "LAB L below 20 or above 140 becomes transparent", None),
    ("cmyk-primary-correction", "lb:cmyk-primary-correction",
     {"reds-cyan": 50, "reds-magenta": -25, "blues-yellow": 40},
     "红往青 +50、减洋红 −25，蓝加黄 +40",
     "Reds +50 towards cyan, magenta −25, blues +40 towards yellow", None),
    # ---- 三联提取（dual）：把三个分量打包成一张数据图 ----
    ("hsi-dual", "lb:hsi-dual", {},
     "打包成数据图：R=饱和度、G=强度、B=色相/360",
     "Packed data image: R=S, G=I, B=H/360", None),
    ("hsl-dual", "lb:hsl-dual", {},
     "打包成数据图：R=饱和度、G=明度、B=色相/360",
     "Packed data image: R=S, G=L, B=H/360", None),
    ("hsv-dual", "lb:hsv-dual", {},
     "打包成数据图：R=饱和度、G=明度、B=色相/360",
     "Packed data image: R=S, G=V, B=H/360", None),
    ("lab-dual", "lb:lab-dual", {},
     "打包成数据图：R=a*、G=b*、B=L*",
     "Packed data image: R=a*, G=b*, B=L*", None),
    ("lch-dual", "lb:lch-dual", {},
     "打包成数据图：R=L/100、G=C/140、B=色相/360",
     "Packed data image: R=L/100, G=C/140, B=H/360", None),
    # ---- 合成（compose）：把数据图还原成颜色，单输入时用自身当三个分量 ----
    ("hsi-compose", "lb:hsi-compose", {},
     "把 (S, I, H/360) 数据图还原成颜色",
     "Turn the packed (S, I, H/360) data back into colour", None),
    ("hsl-compose", "lb:hsl-compose", {},
     "把 (S, L, H/360) 数据图还原成颜色",
     "Turn the packed (S, L, H/360) data back into colour", None),
    ("hsv-compose", "lb:hsv-compose", {},
     "把 (S, V, H/360) 数据图还原成颜色",
     "Turn the packed (S, V, H/360) data back into colour", None),
    ("lab-compose", "lb:lab-compose", {},
     "把 (a*, b*, L*) 数据图还原成颜色",
     "Turn the packed (a*, b*, L*) data back into colour", None),
    ("lch-compose", "lb:lch-compose", {},
     "把 (L, C, H/360) 数据图还原成颜色",
     "Turn the packed (L, C, H/360) data back into colour", None),
    ("cmyk-compose", "lb:cmyk-compose", {},
     "把 (C, M, Y, K) 数据图还原成颜色",
     "Turn the packed (C, M, Y, K) data back into colour", None),

    # ---- 双通道 / 多输入 ----
    ("calculations", "lb:calculations",
     {"source1-channel": "red", "source2-channel": "luma", "blend-mode": "multiply"},
     "红通道 × 亮度（正片叠底）",
     "Red channel × luminance (multiply)", None),
    ("apply-image", "lb:apply-image",
     {"blend-mode": "multiply"},
     "以正片叠底把自己的内容叠回自身",
     "Multiply blended onto itself", None),
    ("displace", "lb:displace",
     {"amount-x": 25, "amount-y": 15},
     "水平位移 25 px、垂直 15 px",
     "Displace 25 px horizontally, 15 px vertically", None),
    ("match-color", "lb:match-color",
     {"color-intensity": 60},
     "色彩强度 60%（与参考图匹配）",
     "Colour intensity 60% (match a reference)", None),
    ("layer-style", "lb:layer-style",
     {"shadow-distance": 24, "shadow-size": 34, "shadow-opacity": 90,
      "glow-on": "true", "glow-size": 26, "glow-opacity": 45},
     "投影 距离 18 / 大小 26 / 不透明度 85%，外加外发光",
     "Drop shadow 18/26/85% plus an outer glow", None),
    # ---- 变形 ----
    ("mesh-warp", "lb:mesh-warp",
     {"mesh": _mesh_string()},
     "3×3 网格，内侧交点下移 72 px（网格变形）",
     "3×3 mesh, inner handles pulled down 72 px", None),
    ("puppet-warp", "lb:puppet-warp",
     {"pins": "480,320,545,430", "mode": "similarity", "radius": 55},
     "一个钉子从 (480,320) 拖到 (545,430)，保形模式",
     "One pin dragged from (480,320) to (545,430), similarity mode", None),
    ("color-lookup", "lb:color-lookup",
     {"file": os.path.join(TMP, "warm.cube"), "strength": 1.0},
     "载入一张暖调 3D LUT、强度 100%",
     "Warm 3D LUT at full strength", None),
    ("gray-to-component", "lb:gray-to-component", {},
     "灰度图按默认映射编码成彩色分量",
     "Encode a greyscale image into colour components (default mapping)", None),
]


def env():
    e = dict(os.environ)
    e["GEGL_PATH"] = os.pathsep.join([
        os.path.join(ROOT, "build"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "gegl-0.4", "plug-ins"),
        r"D:\fastsoftware\GIMP 3\lib\gegl-0.4",
    ])
    return e


# 这些算子 gegl 命令行跑不出效果：输出带 alpha（-o 写 PNG 时把 alpha 丢了）
# 或者要多个输入 pad，只能在 GIMP 里用图层滤镜跑。
GIMP_OPS = set()

# 吃 alpha 的算子换成带透明边的测试卡，否则「投影/发光」没有地方落
ALPHA_CARD = os.path.join(ROOT, "tools", "_testcard_alpha.png")
ALPHA_OPS = {"layer-style"}


def render_via_gimp(op, props, out, src=None):
    import gi
    gi.require_version("Gimp", "3.0")
    from gi.repository import Gimp, Gio
    img = Gimp.Image.new(960, 640, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(src or CARD))
    img.insert_layer(layer, None, 0)
    if not layer.has_alpha():
        layer.add_alpha()
    filt = Gimp.DrawableFilter.new(layer, op, "shot")
    cfg = filt.get_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    filt.update()
    layer.append_filter(filt)
    layer.merge_filter(filt)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    img.delete()
    if not os.path.exists(out):
        raise RuntimeError("%s: GIMP 没写出 %s" % (op, out))
    return out


def render(op, props, out, src=None):
    cmd = [GEGL, src or CARD, "-o", out, "--", op]
    for k, v in props.items():
        cmd.append("%s=%s" % (k, v))
    r = subprocess.run(cmd, env=env(), capture_output=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("%s 失败：%s" % (
            op, (r.stderr or b"").decode("utf-8", "replace")[:400]))
    return out


def _as_argb(path):
    """统一成 ARGB32 再比：gegl 存出来的可能是 RGB24（无 alpha），
    字节布局和 stride 都不一样，直接按 4 字节索引会整幅错位。"""
    src = cairo.ImageSurface.create_from_png(path)
    if src.get_format() == cairo.FORMAT_ARGB32:
        return src
    w, h = src.get_width(), src.get_height()
    dst = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(dst)
    cr.set_source_surface(src, 0, 0)
    cr.paint()
    return dst


def mean_diff(a, b, crop=None):
    """两张同尺寸 PNG 的平均绝对差（0–255，抽样 1/16 像素）。

    细节类算子只看 crop 那一小块 —— 整幅里 90% 是光滑区域，降噪/去尘在整幅
    上的平均差必然被稀释到 1 码以下，用整幅判断会把有效参数误判成无效。
    """
    sa = _as_argb(a)
    sb = _as_argb(b)
    if (sa.get_width(), sa.get_height()) != (sb.get_width(), sb.get_height()):
        # 形态学算子会把边界扩出去（半径 4 → 968×648），缩回去再比
        w0, h0 = sa.get_width(), sa.get_height()
        scaled = cairo.ImageSurface(cairo.FORMAT_ARGB32, w0, h0)
        cr = cairo.Context(scaled)
        cr.scale(w0 / float(sb.get_width()), h0 / float(sb.get_height()))
        cr.set_source_surface(sb, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        sb = scaled
    da, db = sa.get_data(), sb.get_data()
    st = sa.get_stride()
    w, h = sa.get_width(), sa.get_height()
    if crop:
        cx, cy, cw, ch = crop
        xs = range(cx, min(cx + cw, w), 2)
        ys = range(cy, min(cy + ch, h), 2)
    else:
        xs = range(0, w, 4)
        ys = range(0, h, 4)
    tot = n = 0
    for y in ys:
        row = y * st
        for x in xs:
            o = row + x * 4
            # alpha 也要比：channel-range-to-alpha 这类只改 alpha 的算子，
            # 只看 RGB 会判成「毫无效果」
            tot += (abs(da[o] - db[o]) + abs(da[o + 1] - db[o + 1])
                    + abs(da[o + 2] - db[o + 2]) + abs(da[o + 3] - db[o + 3]))
            n += 4
    return tot / float(n) if n else 0.0


def _draw_image(cr, path, x, y, crop=None):
    """crop=None 时整卡按 3:2 居中填满；给了 crop 就按 1:1 贴进去。

    1:1 是关键：细节类算子的差别只有一两个码，任何缩放（哪怕是高质量插值）
    都会把差别吃平，看起来两格一样。
    """
    src = cairo.ImageSurface.create_from_png(path)
    sw, sh = src.get_width(), src.get_height()
    cr.save()
    cr.rectangle(x, y, CELL_W, CELL_H)
    cr.clip()
    if crop:
        cx, cy, cw, ch = crop
        scale = min(1.0, CELL_W / float(cw), CELL_H / float(ch))
        dw, dh = cw * scale, ch * scale
        cr.translate(x + (CELL_W - dw) / 2.0, y + (CELL_H - dh) / 2.0)
        cr.scale(scale, scale)
        cr.set_source_surface(src, -cx, -cy)
    else:
        scale = max(CELL_W / float(sw), CELL_H / float(sh))
        dw, dh = sw * scale, sh * scale
        cr.translate(x + (CELL_W - dw) / 2.0, y + (CELL_H - dh) / 2.0)
        cr.scale(scale, scale)
        cr.set_source_surface(src, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_NEAREST if crop else cairo.FILTER_GOOD)
    cr.paint()
    cr.restore()


def _tag(cr, x, y, text):
    cr.select_font_face("Microsoft YaHei", cairo.FONT_SLANT_NORMAL,
                        cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(11)
    ext = cr.text_extents(text)
    bw, bh = ext.width + 10, ext.height + 7
    cr.set_source_rgba(0, 0, 0, 0.55)
    cr.rectangle(x, y, bw, bh)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.move_to(x + 5, y + bh - 4)
    cr.show_text(text)


def compose(orig, res, out, crop=None, bg=(0.09, 0.09, 0.11)):
    """bg 默认深色；投影/发光这类要在浅底上看，否则黑阴影落在黑底上等于没有。"""
    w = CELL_W * 2 + GAP + PAD * 2
    h = CELL_H + PAD * 2
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*bg)
    cr.paint()
    _draw_image(cr, orig, PAD, PAD, crop)
    _draw_image(cr, res, PAD + CELL_W + GAP, PAD, crop)
    _tag(cr, PAD + 6, PAD + 6, "Original")
    _tag(cr, PAD + CELL_W + GAP + 6, PAD + 6, "Result")
    surface.write_to_png(out)
    return out


def main():
    only = [s.strip() for s in os.environ.get("LB_ONLY", "").split(",") if s.strip()]
    os.makedirs(TMP, exist_ok=True)
    manifest = {}
    if os.path.exists(MANIFEST):
        try:
            manifest = json.load(open(MANIFEST, encoding="utf-8"))
        except Exception:
            manifest = {}

    weak = []
    for d, op, props, zh, en, crop in CASES:
        if only and d not in only:
            continue
        res = os.path.join(TMP, "%s.png" % d)
        src = ALPHA_CARD if d in ALPHA_OPS else CARD
        try:
            if d in GIMP_OPS:
                if os.path.exists(res):
                    os.remove(res)
                render_via_gimp(op, props, res, src)
            else:
                render(op, props, res, src)
        except Exception as exc:
            print("%-22s FAIL %s" % (d, exc))
            weak.append(d)
            continue
        diff = mean_diff(src, res, crop)
        dst = os.path.join(ROOT, "ops", d, "assets")
        os.makedirs(dst, exist_ok=True)
        shot = os.path.join(dst, "shot.png")
        if diff < 0.8:
            # 跑出来和原图几乎一样就不放图：页面上摆一张「左右相同」的对比图
            # 比没有图更糟，读者会以为算子坏了
            if os.path.exists(shot):
                os.remove(shot)
            manifest.pop(d, None)
            weak.append(d)
            print("%-22s  平均差 %5.2f 码  <-- 没有效果，不放图" % (d, diff))
            continue
        bg = (0.95, 0.95, 0.96) if d in ALPHA_OPS else (0.09, 0.09, 0.11)
        out = compose(src, res, shot, crop, bg)
        size = os.path.getsize(out) / 1024.0
        print("%-22s %6.1f KB  平均差 %5.2f 码" % (d, size, diff))
        manifest[d] = {"zh": zh, "en": en}

    # 只留 CASES 里还认的条目（删掉的算子不该留在 json 里）
    known = set(c[0] for c in CASES)
    manifest = {k: v for k, v in manifest.items() if k in known}
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(manifest.items())), fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("manifest: %d 条" % len(manifest))
    if weak:
        print("需要复查：", ", ".join(weak))


main()
