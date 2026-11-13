# -*- coding: utf-8 -*-
"""lb:gray-to-component 端到端回归，在 GIMP 的 python-fu 里跑：

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \\
        --batch-interpreter=python-fu-eval \\
        -b "exec(open(r'<repo>/tools/check_gray_to_component.py').read())" --quit

两层验证：

A. 编码公式精确性：灰度斜坡喂算子，Lab 域模式（lightness / luminance /
   lch-hue / lch-color / lch-chroma）直读 Lab 输出与公式对拍；RGB 域模式
   （hue / color / saturation / value / rgb 三通道）读回 RGB 与 Python 镜像
   的 HSL/HSV 公式对拍。

B. 恒等往返（金标准，与 hsl-cal 校准同一方法）：探针图分解出分量灰度 →
   算子编码成彩色层 → GIMP 颜色组混合模式（Hue / Saturation / Color /
   Value / LCh Hue / LCh Chroma / LCh Color / LCh Lightness / Luminance）
   还原 → 与原图逐像素比对，误差 ≤2/255 说明「分解范围 ↔ 编码映射 ↔
   混合模式读取」三层对应关系成立；RGB 三通道层用 Lighten 叠合还原。

   颜色组里 Color / Value / LCh Color 这类「只读一个分量」的模式各配一套
   探针：Color 需要底层饱和度等于 color-sat 的探针，LCh Color 需要底层
   色度等于 lch-c 的探针，否则不构成恒等条件。
"""

import array
import colorsys
import math
import os
import sys

import gi

gi.require_version('Gegl', '0.4')
gi.require_version('Gimp', '3.0')
from gi.repository import Gegl, Gimp

Gegl.init()

FMT_RGB = "R'G'B'A float"
FMT_LAB = "CIE Lab alpha float"
FMT_LCH = "CIE LCH(ab) alpha float"
FMT_GRAY = "YA float"

PASS = 0
FAIL = 0

TOL_EXACT = 1e-4     # Lab 域直写：只有 float32 舍入
TOL_RGB = 3e-3       # RGB 域经 babl 往返
TOL_RT = 2.0         # 恒等往返，按 0-255 计


def report(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  ✓ %s" % label, flush=True)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (label, detail), flush=True)


def report_val(label, worst, tol, detail=""):
    report(label, worst <= tol,
           "最大偏差 %.4g > %.4g %s" % (worst, tol, detail))


# ---- 缓冲工具 ------------------------------------------------------------

def make_gray_buf(grays, alpha=None, w=None, h=None):
    """grays: [g 0..1]，alpha 默认全 1"""
    n = len(grays)
    w = w or n
    h = h or 1
    alpha = alpha or [1.0] * n
    a = array.array('f')
    for i in range(n):
        a.extend([grays[i], alpha[i]])
    buf = Gegl.Buffer.new(FMT_GRAY, 0, 0, w, h)
    buf.set(Gegl.Rectangle.new(0, 0, w, h), FMT_GRAY, a.tobytes())
    return buf


def read_fmt(buf, fmt, w, h):
    data = buf.get(Gegl.Rectangle.new(0, 0, w, h), 1.0, fmt,
                   Gegl.AbyssPolicy.NONE)
    flat = array.array('f')
    flat.frombytes(data)
    n = {FMT_RGB: 4, FMT_LAB: 4, FMT_LCH: 4, FMT_GRAY: 2}[fmt]
    return [tuple(flat[i * n:(i + 1) * n]) for i in range(w * h)]


def run_op(grays, w, h, **props):
    root = Gegl.Node.new()
    src = root.create_child("gegl:buffer-source")
    src.set_property("buffer", make_gray_buf(grays, None, w, h))
    op = root.create_child("lb:gray-to-component")
    for k, v in props.items():
        op.set_property(k.replace('_', '-'), v)
    src.connect_to("output", op, "input")
    out = Gegl.Buffer.new(FMT_LAB, 0, 0, w, h)
    op.blit_buffer(out, Gegl.Rectangle.new(0, 0, w, h), 0,
                   Gegl.AbyssPolicy.NONE)
    return out


def px_to_buf(pixels, fmt, w, h):
    """RGB 三元组 / 任意 fmt 分量 → Gegl 缓冲"""
    a = array.array('f')
    for p in pixels:
        q = list(p) + [1.0] * (4 - len(p))
        a.extend(q[:4])
    buf = Gegl.Buffer.new(fmt, 0, 0, w, h)
    buf.set(Gegl.Rectangle.new(0, 0, w, h), fmt, a.tobytes())
    return buf


# ---- Python 镜像公式 -----------------------------------------------------

def hsl_to_rgb(h, s, l):
    return colorsys.hls_to_rgb(h % 1.0, l, s)


def hsv_to_rgb(h, s, v):
    return colorsys.hsv_to_rgb(h % 1.0, s, v)


def lab_for_mode(mode, g, sat_hue=0.0, color_sat=100.0, lch_l=54.0,
                 lch_c=30.0, lch_h=30.0, chroma_scale=100.0):
    if mode == "lightness" or mode == "luminance":
        return (g * 100.0, 0.0, 0.0)
    if mode == "lch-hue" or mode == "lch-color":
        hr = math.radians(g * 360.0)
        return (lch_l, lch_c * math.cos(hr), lch_c * math.sin(hr))
    if mode == "lch-chroma":
        hr = math.radians(lch_h)
        return (lch_l, g * chroma_scale * math.cos(hr),
                g * chroma_scale * math.sin(hr))
    raise ValueError(mode)


def rgb_for_mode(mode, g, sat_hue=0.0, color_sat=100.0):
    if mode == "hue":
        return hsl_to_rgb(g, 1.0, 0.5)
    if mode == "color":
        return hsl_to_rgb(g, color_sat / 100.0, 0.5)
    if mode == "saturation":
        return hsv_to_rgb(sat_hue / 360.0, g, 1.0)
    if mode == "value":
        return (g, g, g)
    if mode == "red":
        return (g, 0.0, 0.0)
    if mode == "green":
        return (0.0, g, 0.0)
    if mode == "blue":
        return (0.0, 0.0, g)
    raise ValueError(mode)


LAB_MODES = ("lightness", "luminance", "lch-hue", "lch-color", "lch-chroma")
RGB_MODES = ("hue", "color", "saturation", "value", "red", "green", "blue")

# =========================================================================
# A. 编码公式精确性
# =========================================================================
print("== A. 编码公式 ==", flush=True)

RAMP = [i / 16.0 for i in range(17)]
W, H = len(RAMP), 1

for mode in LAB_MODES:
    # 每个模式跑默认参数 + 一组非默认参数（确认参数真的进了公式）
    for extra in ({}, {"lch_l": 70.0, "lch_c": 45.0, "lch_h": 120.0,
                   "chroma_scale": 132.0}):
        props = dict(mode=mode, **extra)
        lab = read_fmt(run_op(RAMP, W, H, **props), FMT_LAB, W, H)
        worst = 0.0
        for i, g in enumerate(RAMP):
            want = lab_for_mode(mode, g,
                                lch_l=extra.get("lch_l", 54.0),
                                lch_c=extra.get("lch_c", 30.0),
                                lch_h=extra.get("lch_h", 30.0),
                                chroma_scale=extra.get("chroma_scale", 100.0))
            worst = max(worst, max(abs(lab[i][c] - want[c]) for c in range(3)))
        report_val("%s 公式对拍%s" % (mode, "（非默认参数）" if extra else ""),
                   worst, TOL_EXACT)

for mode in RGB_MODES:
    variants = []
    if mode == "saturation":
        variants = [{"sat_hue": 0.0}, {"sat_hue": 210.0}]
    elif mode == "color":
        variants = [{"color_sat": 100.0}, {"color_sat": 40.0}]
    else:
        variants = [{}]
    for extra in variants:
        rgb = read_fmt(run_op(RAMP, W, H, mode=mode, **extra), FMT_RGB, W, H)
        worst = 0.0
        for i, g in enumerate(RAMP):
            want = rgb_for_mode(mode, g, extra.get("sat_hue", 0.0),
                                extra.get("color_sat", 100.0))
            worst = max(worst, max(abs(rgb[i][c] - want[c]) for c in range(3)))
        label = mode
        if extra:
            label += "(%s)" % ",".join("%s=%g" % (k, v)
                                       for k, v in extra.items())
        report_val("%s 公式对拍" % label, worst, TOL_RGB)

# 端点语义：hue 在 g=0/0.5/1 处给纯红/青/红，saturation 端点给出白/纯红
rgb = read_fmt(run_op([0.0, 0.5, 1.0], 3, 1, mode="hue"), FMT_RGB, 3, 1)
report("hue 端点：0=红、0.5=青、1=回红",
       abs(rgb[0][0] - 1) < 1e-3 and rgb[0][1] < 1e-3 and
       abs(rgb[1][0]) < 1e-3 and abs(rgb[1][1] - 1) < 1e-3,
       "got=%s" % [(round(p[0], 3), round(p[1], 3), round(p[2], 3))
                   for p in rgb])

rgb = read_fmt(run_op([0.0, 1.0], 2, 1, mode="saturation"), FMT_RGB, 2, 1)
report("saturation 端点：0=白、1=纯红",
       min(rgb[0][:3]) > 0.999 and rgb[1][0] > 0.999 and
       max(rgb[1][1:3]) < 1e-3,
       "got=%s" % [(round(p[0], 3), round(p[1], 3), round(p[2], 3))
                   for p in rgb])

rgb = read_fmt(run_op([0.0, 0.5, 1.0], 3, 1, mode="value"), FMT_RGB, 3, 1)
report("value 端点：0=黑、1=白、中性灰（RGB 三通道相等）",
       max(rgb[0][:3]) < 1e-3 and min(rgb[2][:3]) > 0.999 and
       abs(rgb[1][0] - rgb[1][1]) < 1e-4 and abs(rgb[1][1] - rgb[1][2]) < 1e-4,
       "got=%s" % [(round(p[0], 3), round(p[1], 3), round(p[2], 3))
                   for p in rgb])

# color 的饱和度参数：0% 时退化成中性灰（Color 模式只留底色明度）
rgb = read_fmt(run_op([0.25], 1, 1, mode="color", color_sat=0.0), FMT_RGB, 1, 1)
report("color(color-sat=0) 退化成中性灰",
       abs(rgb[0][0] - rgb[0][1]) < 1e-4 and abs(rgb[0][1] - rgb[0][2]) < 1e-4,
       "got=%s" % [round(v, 3) for v in rgb[0][:3]])

# 两组「同编码别名」：luminance 与 lightness、lch-color 与 lch-hue
lab_l = read_fmt(run_op(RAMP, W, H, mode="lightness"), FMT_LAB, W, H)
lab_y = read_fmt(run_op(RAMP, W, H, mode="luminance"), FMT_LAB, W, H)
report("luminance 与 lightness 输出逐分量相同（L 与 Y 单调对应）",
       max(abs(a[c] - b[c]) for a, b in zip(lab_l, lab_y) for c in range(3))
       < 1e-6)

lab_h = read_fmt(run_op(RAMP, W, H, mode="lch-hue"), FMT_LAB, W, H)
lab_c = read_fmt(run_op(RAMP, W, H, mode="lch-color"), FMT_LAB, W, H)
report("lch-color 与 lch-hue 输出逐分量相同（色度同由 lch-c 固定）",
       max(abs(a[c] - b[c]) for a, b in zip(lab_h, lab_c) for c in range(3))
       < 1e-6)

# 透明像素：alpha=0 原样透传（输出保持全透明）
#
# 用 32x8 的棋盘而非 2x1：GEGL 的 tile 是 128x64，小到不足一个 tile 的
# 缓冲在读回时偶尔会读到尚未初始化的 tile 尾巴（垃圾值随机为 1.0 或
# denormal），与算子行为无关。铺满整块 tile 后读数稳定。
AW, AH = 32, 8
a_gray, a_alpha = [], []
for y in range(AH):
    for x in range(AW):
        a_gray.append((x + y) / (AW + AH - 2.0))
        a_alpha.append(0.0 if (x + y) % 3 == 0 else 1.0)
abuf = Gegl.Buffer.new(FMT_GRAY, 0, 0, AW, AH)
arr = array.array('f')
for g, al in zip(a_gray, a_alpha):
    arr.extend([g, al])
abuf.set(Gegl.Rectangle.new(0, 0, AW, AH), FMT_GRAY, arr.tobytes())

root = Gegl.Node.new()
src = root.create_child("gegl:buffer-source")
src.set_property("buffer", abuf)
op = root.create_child("lb:gray-to-component")
op.set_property("mode", "hue")
src.connect_to("output", op, "input")
o2 = Gegl.Buffer.new(FMT_LAB, 0, 0, AW, AH)
op.blit_buffer(o2, Gegl.Rectangle.new(0, 0, AW, AH), 0, Gegl.AbyssPolicy.NONE)
lab = read_fmt(o2, FMT_LAB, AW, AH)
err_a = max(abs(lab[i][3] - a_alpha[i]) for i in range(AW * AH))
dark = [i for i in range(AW * AH) if a_alpha[i] == 0.0]
leak = max(max(abs(lab[i][c]) for c in range(3)) for i in dark)
report("透明像素 alpha 原样透传（%d/%d 透明）" % (len(dark), AW * AH),
       err_a < 1e-6 and leak < 1e-6,
       "alpha 偏差 %.3g / 透明像素残留 %.3g" % (err_a, leak))

# =========================================================================
# B. 恒等往返（金标准）
# =========================================================================
print("\n== B. 恒等往返 ==", flush=True)

PROBE = [
    (230, 30, 30), (230, 120, 30), (230, 210, 30), (150, 230, 30),
    (30, 230, 60), (30, 230, 180), (30, 180, 230), (30, 90, 230),
    (80, 30, 230), (180, 30, 230), (230, 30, 160), (230, 30, 80),
    (128, 128, 128), (200, 200, 200), (40, 40, 40), (255, 255, 255),
    (0, 0, 0), (120, 160, 110), (200, 170, 120), (90, 100, 140),
    (250, 245, 230), (20, 25, 35), (170, 60, 90), (60, 130, 90),
]
PW = len(PROBE)
PH = 1
probe_rgb = [(p[0] / 255.0, p[1] / 255.0, p[2] / 255.0) for p in PROBE]

# 用 babl 读探针的 Lab / LCH（分解灰度语义的来源，Python 不自实现转换）
lab_probe = read_fmt(px_to_buf(probe_rgb, FMT_RGB, PW, PH), FMT_LAB, PW, PH)
lch_probe = read_fmt(px_to_buf(probe_rgb, FMT_RGB, PW, PH), FMT_LCH, PW, PH)


def hsl_probe_set(hues, s, ls):
    """按 HSL 设计值造探针：返回 (0-255 三元组, RGB 浮点)"""
    px = [hsl_to_rgb(h, s, l) for h in hues for l in ls]
    return ([(round(p[0] * 255), round(p[1] * 255), round(p[2] * 255))
             for p in px], px)


def lch_probe_set(specs):
    """(L, C, h) 列表 → RGB 像素（走 babl，Python 不实现 LCh 转换）"""
    n = len(specs)
    buf = px_to_buf([(l, c, h, 1.0) for (l, c, h) in specs], FMT_LCH, n, 1)
    px = [p[:3] for p in read_fmt(buf, FMT_RGB, n, 1)]
    return ([(round(p[0] * 255), round(p[1] * 255), round(p[2] * 255))
             for p in px], px)


def new_image(w, h):
    """float32 图像：与 hsl-cal 校准环境一致（8-bit 会把 Lab/LCh 编码
    量化打碎，恒等往返必须在 float32 下测）。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    proc = Gimp.get_pdb().lookup_procedure('gimp-image-convert-precision')
    cfg = proc.create_config()
    cfg.set_property('image', img)
    cfg.set_property('precision', Gimp.Precision.FLOAT_NON_LINEAR)
    proc.run(cfg)
    return img


def write_layer(lay, pixels, w=PW, h=PH):
    a = array.array('f')
    for p in pixels:
        a.extend([p[0], p[1], p[2], p[3] if len(p) > 3 else 1.0])
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), FMT_RGB,
                         a.tobytes())


def enc_layer(mode, grays, width=PW, **props):
    """跑算子并读回 RGB，作为混合层像素"""
    out = run_op(grays, width, PH, mode=mode, **props)
    return read_fmt(out, FMT_RGB, width, PH)


def roundtrip(label, blend_modes, probes=None, base_px=None):
    """blend_modes: [(mode_name, layer_pixels)]，自下而上叠在探针上"""
    probes = probes if probes is not None else PROBE
    base_px = base_px if base_px is not None else probe_rgb
    n = len(base_px)

    img = new_image(n, PH)
    base = Gimp.Layer.new(img, "probe", n, PH, Gimp.ImageType.RGBA_IMAGE,
                          100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(base, None, 0)
    write_layer(base, base_px, n, PH)

    for mode_name, px in blend_modes:
        lay = Gimp.Layer.new(img, mode_name, n, PH,
                             Gimp.ImageType.RGBA_IMAGE, 100.0,
                             Gimp.LayerMode.NORMAL)
        img.insert_layer(lay, None, 0)
        write_layer(lay, px, n, PH)
        lay.set_mode(getattr(Gimp.LayerMode, mode_name))
        lay.set_opacity(100.0)

    res = img.flatten()
    got = read_fmt(res.get_buffer(), FMT_RGB, n, PH)

    errs = []
    for i, p in enumerate(got):
        pr = probes[i]
        errs.append(max(abs(p[c] * 255.0 - pr[c]) for c in range(3)))
    worst = max(errs)
    report_val(label, worst, TOL_RT,
               "最差像素 #%d %s" % (errs.index(worst), probes[errs.index(worst)]))
    img.delete()
    return worst


# 分量灰度（分解语义：hue=HSL h，saturation=HSV s，value=HSV V，
# lightness/luminance=CIE L，LCh 同）
grays = {}
grays["hue"] = [colorsys.rgb_to_hls(*p)[0] for p in probe_rgb]
grays["saturation"] = [colorsys.rgb_to_hsv(*p)[1] for p in probe_rgb]
grays["value"] = [colorsys.rgb_to_hsv(*p)[2] for p in probe_rgb]
grays["lightness"] = [min(max(lab_probe[i][0] / 100.0, 0.0), 1.0)
                      for i in range(PW)]
grays["lch-hue"] = [(lch_probe[i][2] % 360.0) / 360.0 for i in range(PW)]
grays["lch-chroma"] = [min(max(lch_probe[i][1] / 100.0, 0.0), 1.0)
                       for i in range(PW)]
grays["red"] = [p[0] for p in probe_rgb]
grays["green"] = [p[1] for p in probe_rgb]
grays["blue"] = [p[2] for p in probe_rgb]

roundtrip("hue → Hue 模式", [("HSV_HUE", enc_layer("hue", grays["hue"]))])
roundtrip("saturation → Saturation 模式",
          [("HSV_SATURATION", enc_layer("saturation", grays["saturation"]))])
roundtrip("value → Value 模式",
          [("HSV_VALUE", enc_layer("value", grays["value"]))])
roundtrip("lightness → LCh Lightness 模式",
          [("LCH_LIGHTNESS", enc_layer("lightness", grays["lightness"]))])
roundtrip("luminance → Luminance 模式",
          [("LUMINANCE", enc_layer("luminance", grays["lightness"]))])
roundtrip("lch-hue → LCh Hue 模式",
          [("LCH_HUE", enc_layer("lch-hue", grays["lch-hue"]))])

# lch-chroma：默认量程 100 对应 C∈[0,100]；sRGB 蓝/品红可超 100，需要把
# chroma_scale 调成与分解侧一致的满量程（此处 132 覆盖全部探针）——
# 关键是灰度必须是 C/132，否则编码出的色度就不是原值
CS = 132.0
grays_cs = [min(max(lch_probe[i][1] / CS, 0.0), 1.0) for i in range(PW)]
roundtrip("lch-chroma → LCh Chroma 模式（量程 132，覆盖全色域）",
          [("LCH_CHROMA",
            enc_layer("lch-chroma", grays_cs, chroma_scale=CS))])

# 默认量程 100：只对 C≤100 的探针成立，超出的部分按设计被裁掉
sub = [i for i in range(PW) if lch_probe[i][1] <= 100.0]
sub_grays = [grays["lch-chroma"][i] for i in sub]
sub_px = enc_layer("lch-chroma", sub_grays, width=len(sub))
roundtrip("lch-chroma → LCh Chroma 模式（默认量程 100，C≤100 探针）",
          [("LCH_CHROMA", sub_px)],
          probes=[PROBE[i] for i in sub],
          base_px=[probe_rgb[i] for i in sub])

roundtrip("red/green/blue → Lighten 叠合",
          [("LIGHTEN_ONLY", enc_layer("blue", grays["blue"])),
           ("LIGHTEN_ONLY", enc_layer("green", grays["green"])),
           ("LIGHTEN_ONLY", enc_layer("red", grays["red"]))])

# 组合语义：色相层 + 饱和度层一起还原（Hue→Saturation 链）
roundtrip("hue + saturation 串联还原",
          [("HSV_HUE", enc_layer("hue", grays["hue"])),
           ("HSV_SATURATION", enc_layer("saturation", grays["saturation"]))])

# ---- Color：只读 H+S、保留底色 L，所以恒等条件是「底层 S = color-sat」 ----
HUE12 = [i / 12.0 for i in range(12)]
probes_s1, px_s1 = hsl_probe_set(HUE12, 1.0, (0.5, 0.3, 0.7))
n_s1 = len(px_s1)
g_s1 = [colorsys.rgb_to_hls(*p)[0] for p in px_s1]
roundtrip("color(sat=100) → Color 模式（S=100% 探针）",
          [("HSL_COLOR", enc_layer("color", g_s1, width=n_s1,
                                   color_sat=100.0))],
          probes=probes_s1, base_px=px_s1)

probes_s6, px_s6 = hsl_probe_set(HUE12, 0.6, (0.5,))
n_s6 = len(px_s6)
g_s6 = [colorsys.rgb_to_hls(*p)[0] for p in px_s6]
roundtrip("color(sat=60) → Color 模式（S=60% 探针，验证饱和度参数）",
          [("HSL_COLOR", enc_layer("color", g_s6, width=n_s6,
                                   color_sat=60.0))],
          probes=probes_s6, base_px=px_s6)

# ---- LCh Color：只读 h+C、保留底色 L，恒等条件是「底层 C = lch-c」 ----
LCH_C = 30.0
specs = [(54.0, LCH_C, h) for h in range(0, 360, 30)]
probes_lc, px_lc = lch_probe_set(specs)
n_lc = len(px_lc)
g_lc = [s[2] / 360.0 for s in specs]
roundtrip("lch-color → LCh Color 模式（C=lch-c=30 探针）",
          [("LCH_COLOR", enc_layer("lch-color", g_lc, width=n_lc,
                                   lch_c=LCH_C))],
          probes=probes_lc, base_px=px_lc)

print("\n结果: %d/%d 通过" % (PASS, PASS + FAIL), flush=True)
if FAIL:
    print("有 %d 项失败" % FAIL, flush=True)
