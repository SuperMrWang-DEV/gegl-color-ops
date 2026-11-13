# -*- coding: utf-8 -*-
"""lb:gray-to-component 端到端回归，在 GIMP 的 python-fu 里跑：

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \\
        --batch-interpreter=python-fu-eval \\
        -b "exec(open(r'<repo>/tools/check_gray_to_component.py').read())" --quit

两层验证：

A. 编码公式精确性：灰度斜坡喂算子，Lab 域模式（lightness / lch-hue /
   lch-chroma）直读 Lab 输出与公式对拍；RGB 域模式（hue / saturation /
   rgb 三通道）读回 RGB 与 Python 镜像的 HSL/HSV 公式对拍。

B. 恒等往返（金标准，与 hsl-cal 校准同一方法）：探针图分解出分量灰度 →
   算子编码成彩色层 → GIMP 分量混合模式（Hue / Saturation / LCh
   Lightness / LCh Hue / LCh Chroma）还原 → 与原图逐像素比对，误差
   ≤2/255 说明「分解范围 ↔ 编码映射 ↔ 混合模式读取」三层对应关系成立；
   RGB 三通道层用 Lighten 叠合还原。
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


# ---- Python 镜像公式 -----------------------------------------------------

def hsl_to_rgb(h, s, l):
    return colorsys.hls_to_rgb(h % 1.0, l, s)


def hsv_to_rgb(h, s, v):
    return colorsys.hsv_to_rgb(h % 1.0, s, v)


def lab_for_mode(mode, g, sat_hue=0.0, lch_l=54.0, lch_c=30.0, lch_h=30.0,
                 chroma_scale=100.0):
    if mode == "lightness":
        return (g * 100.0, 0.0, 0.0)
    if mode == "lch-hue":
        hr = math.radians(g * 360.0)
        return (lch_l, lch_c * math.cos(hr), lch_c * math.sin(hr))
    if mode == "lch-chroma":
        hr = math.radians(lch_h)
        return (lch_l, g * chroma_scale * math.cos(hr),
                g * chroma_scale * math.sin(hr))
    raise ValueError(mode)


def rgb_for_mode(mode, g, sat_hue=0.0):
    if mode == "hue":
        return hsl_to_rgb(g, 1.0, 0.5)
    if mode == "saturation":
        return hsv_to_rgb(sat_hue / 360.0, g, 1.0)
    if mode == "red":
        return (g, 0.0, 0.0)
    if mode == "green":
        return (0.0, g, 0.0)
    if mode == "blue":
        return (0.0, 0.0, g)
    raise ValueError(mode)


# =========================================================================
# A. 编码公式精确性
# =========================================================================
print("== A. 编码公式 ==", flush=True)

RAMP = [i / 16.0 for i in range(17)]
W, H = len(RAMP), 1

for mode in ("lightness", "lch-hue", "lch-chroma"):
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

for mode in ("hue", "saturation", "red", "green", "blue"):
    for sat_hue in ([0.0, 210.0] if mode == "saturation" else [0.0]):
        rgb = read_fmt(run_op(RAMP, W, H, mode=mode, sat_hue=sat_hue),
                       FMT_RGB, W, H)
        worst = 0.0
        for i, g in enumerate(RAMP):
            want = rgb_for_mode(mode, g, sat_hue)
            worst = max(worst, max(abs(rgb[i][c] - want[c]) for c in range(3)))
        label = mode if mode != "saturation" else "saturation(h=%.0f°)" % sat_hue
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

# 透明像素：alpha=0 原样透传（输出保持全透明）
out = run_op([0.5, 0.5], 2, 1, mode="hue")
buf = make_gray_buf([0.5, 0.5], [1.0, 0.0], 2, 1)
root = Gegl.Node.new()
src = root.create_child("gegl:buffer-source")
src.set_property("buffer", buf)
op = root.create_child("lb:gray-to-component")
op.set_property("mode", "hue")
src.connect_to("output", op, "input")
o2 = Gegl.Buffer.new(FMT_LAB, 0, 0, 2, 1)
op.blit_buffer(o2, Gegl.Rectangle.new(0, 0, 2, 1), 0, Gegl.AbyssPolicy.NONE)
lab = read_fmt(o2, FMT_LAB, 2, 1)
report("透明像素 alpha 原样透传",
       abs(lab[0][3] - 1.0) < 1e-6 and lab[1][3] < 1e-6,
       "alpha=%s" % [round(p[3], 3) for p in lab])

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
tmp = Gegl.Buffer.new(FMT_RGB, 0, 0, PW, PH)
flat = array.array('f')
for p in probe_rgb:
    flat.extend([p[0], p[1], p[2], 1.0])
tmp.set(Gegl.Rectangle.new(0, 0, PW, PH), FMT_RGB, flat.tobytes())
lab_probe = read_fmt(tmp, FMT_LAB, PW, PH)
lch_probe = read_fmt(tmp, FMT_LCH, PW, PH)


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


def write_layer(lay, pixels):
    a = array.array('f')
    for p in pixels:
        a.extend([p[0], p[1], p[2], p[3] if len(p) > 3 else 1.0])
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, PW, PH), FMT_RGB,
                         a.tobytes())


def enc_layer(mode, grays, **props):
    """跑算子并读回 RGB，作为混合层像素"""
    out = run_op(grays, PW, PH, mode=mode, **props)
    return read_fmt(out, FMT_RGB, PW, PH)


def roundtrip(label, blend_modes):
    """blend_modes: [(mode_name, layer_pixels)]，自下而上叠在探针上"""
    img = new_image(PW, PH)
    base = Gimp.Layer.new(img, "probe", PW, PH, Gimp.ImageType.RGBA_IMAGE,
                          100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(base, None, 0)
    write_layer(base, probe_rgb)

    for mode_name, px in blend_modes:
        lay = Gimp.Layer.new(img, mode_name, PW, PH,
                             Gimp.ImageType.RGBA_IMAGE, 100.0,
                             Gimp.LayerMode.NORMAL)
        img.insert_layer(lay, None, 0)
        write_layer(lay, px)
        lay.set_mode(getattr(Gimp.LayerMode, mode_name))
        lay.set_opacity(100.0)

    res = img.flatten()
    got = read_fmt(res.get_buffer(), FMT_RGB, PW, PH)

    errs = []
    for i, p in enumerate(got):
        pr = PROBE[i]
        errs.append(max(abs(p[c] * 255.0 - pr[c]) for c in range(3)))
    worst = max(errs)
    report_val(label, worst, TOL_RT,
               "最差像素 #%d %s" % (errs.index(worst), PROBE[errs.index(worst)]))
    img.delete()
    return worst


# 分量灰度（分解语义：hue=HSL h，saturation=HSV s，lightness=CIE L，LCh 同）
grays = {}
grays["hue"] = [colorsys.rgb_to_hls(*p)[0] for p in probe_rgb]
grays["saturation"] = [colorsys.rgb_to_hsv(*p)[1] for p in probe_rgb]
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
roundtrip("lightness → LCh Lightness 模式",
          [("LCH_LIGHTNESS", enc_layer("lightness", grays["lightness"]))])
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
sub_px = enc_layer("lch-chroma", sub_grays)
img = new_image(len(sub), PH)
base = Gimp.Layer.new(img, "probe", len(sub), PH, Gimp.ImageType.RGBA_IMAGE,
                      100.0, Gimp.LayerMode.NORMAL)
img.insert_layer(base, None, 0)
_a = array.array('f')
for i in sub:
    _a.extend([probe_rgb[i][0], probe_rgb[i][1], probe_rgb[i][2], 1.0])
base.get_buffer().set(Gegl.Rectangle.new(0, 0, len(sub), PH), FMT_RGB,
                      _a.tobytes())
lay = Gimp.Layer.new(img, "enc", len(sub), PH, Gimp.ImageType.RGBA_IMAGE,
                     100.0, Gimp.LayerMode.NORMAL)
img.insert_layer(lay, None, 0)
_a = array.array('f')
for p in sub_px:
    _a.extend([p[0], p[1], p[2], 1.0])
lay.get_buffer().set(Gegl.Rectangle.new(0, 0, len(sub), PH), FMT_RGB,
                     _a.tobytes())
lay.set_mode(Gimp.LayerMode.LCH_CHROMA)
res = img.flatten()
flat = array.array('f')
flat.frombytes(res.get_buffer().get(Gegl.Rectangle.new(0, 0, len(sub), PH),
                                    1.0, FMT_RGB, Gegl.AbyssPolicy.NONE))
errs = []
for k, i in enumerate(sub):
    errs.append(max(abs(flat[k * 4 + c] * 255.0 - PROBE[i][c])
                    for c in range(3)))
report_val("lch-chroma → LCh Chroma 模式（默认量程 100，C≤100 探针）",
           max(errs), TOL_RT)
img.delete()

roundtrip("red/green/blue → Lighten 叠合",
          [("LIGHTEN_ONLY", enc_layer("blue", grays["blue"])),
           ("LIGHTEN_ONLY", enc_layer("green", grays["green"])),
           ("LIGHTEN_ONLY", enc_layer("red", grays["red"]))])

# 组合语义：色相层 + 饱和度层一起还原（Hue→Saturation 链）
roundtrip("hue + saturation 串联还原",
          [("HSV_HUE", enc_layer("hue", grays["hue"])),
           ("HSV_SATURATION", enc_layer("saturation", grays["saturation"]))])

print("\n结果: %d/%d 通过" % (PASS, PASS + FAIL), flush=True)
if FAIL:
    print("有 %d 项失败" % FAIL, flush=True)
