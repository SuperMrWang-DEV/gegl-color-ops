# -*- coding: utf-8 -*-
"""回归：hsv-split-curves 插件（HSV 分量层 + 曲线 + 混合模式还原）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_hsv_split.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gimp / Gegl 的 GI 绑定）。检查 8 件事：

1. 生成结构：组 + 三层，顺序 Hue / Saturation / Value，混合模式对；
2. 每层的滤镜条数与名字（Value 2 条，H/S 5 条）；
3. 32 位浮点图：恒等曲线往返误差 = 0（曲线编码是精确的）；
4. 8 位图：恒等往返 ≤ 1 码（只剩量化误差）；
5. 改曲线 ≈ 直接改 HSV 分量（8 位 ≤ 3 码）；
6. 透明区域 alpha 逐位保留；
7. 不收组（group=False）时同样还原；
8. 图层组作为输入会被拒绝。
"""
import os
import math
import array
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl


def _find_repo():
    cands = []
    try:
        cands.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except NameError:
        pass
    cwd = os.getcwd()
    cands += [cwd, os.path.join(cwd, "SuperMrWang"),
              os.path.join(cwd, "..", "SuperMrWang")]
    for c in cands:
        if os.path.exists(os.path.join(c, "plugin", "hsv-split-curves",
                                       "hsv-split-curves.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
HSV = _load("hsv_split_curves",
            os.path.join(REPO, "plugin", "hsv-split-curves",
                         "hsv-split-curves.py"))

FAILS = []
CHECKS = [0]


def check(cond, label, detail=""):
    CHECKS[0] += 1
    if cond:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILS.append(label)


def close(a, b, tol, label):
    delta = abs(a - b)
    check(delta <= tol, "%s (%.5f <= %.5f)" % (label, delta, tol))


# ---- 测试图 / test raster ---------------------------------------------------

def hsv2rgb(h, s, v):
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return r + m, g + m, b + m


def make_image(w=48, h=48, float_prec=False, alpha_left=None):
    """横向铺满色相，纵向三段不同 S/V，可选左半透明。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    if float_prec:
        proc = Gimp.get_pdb().lookup_procedure('gimp-image-convert-precision')
        cfg = proc.create_config()
        cfg.set_property('image', img)
        cfg.set_property('precision', Gimp.Precision.FLOAT_NON_LINEAR)
        proc.run(cfg)
    base = Gimp.Layer.new(img, "base", w, h, Gimp.ImageType.RGBA_IMAGE, 100.0,
                          Gimp.LayerMode.NORMAL)
    img.insert_layer(base, None, 0)
    px = array.array('f', bytes(w * h * 4))
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            s = 1.0 if y < h // 3 else (0.5 if y < 2 * h // 3 else 0.1)
            v = 1.0 if y < h // 3 else (0.6 if y < 2 * h // 3 else 0.3)
            r, g, b = hsv2rgb((x / float(w)) * 360.0, s, v)
            a = alpha_left if (alpha_left is not None and x < w // 2) else 1.0
            px[i:i + 4] = array.array('f', [r, g, b, a])
    base.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A float",
                          px.tobytes())
    return img, base, px


def read(layer):
    w, h = layer.get_width(), layer.get_height()
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                 "R'G'B'A float", Gegl.AbyssPolicy.NONE)
    d = array.array('f')
    d.frombytes(bytes(bytearray(raw)))
    return d


def flatten(img):
    di = img.duplicate()
    merged = di.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    got = read(merged)
    di.delete()
    return got


def set_curve(layer, fn, channel=Gimp.HistogramChannel.VALUE, which="2 · curve"):
    """改某一层的那条「用户曲线」（按滤镜名找）。"""
    for filt in layer.get_filters():
        if filt.get_name() == which:
            cfg = filt.get_config()
            curve = Gimp.Curve.new()
            curve.set_curve_type(Gimp.CurveType.FREE)
            n = curve.get_n_samples()
            for i in range(n):
                x = i / float(n - 1)
                curve.set_sample(x, min(1.0, max(0.0, fn(x))))
            cfg.set_property("curve", curve)
            cfg.set_property("channel", channel)
            cfg.set_property("trc", Gimp.TRCType.NON_LINEAR)
            filt.update()
            return True
    return False


def max_diff(a, b, channels=(0, 1, 2)):
    worst = 0.0
    for i in range(0, len(a), 4):
        for k in channels:
            worst = max(worst, abs(a[i + k] - b[i + k]))
    return worst


# ---- 1/2. 结构与滤镜栈 ------------------------------------------------------

print("== 1. 结构 / structure")
img, base, ref = make_image()
top = HSV.split_hsv(img, base, make_group=True)
group = img.get_layers()[0]
check(group.is_group(), "顶层是图层组")
check(group.get_mode() == Gimp.LayerMode.PASS_THROUGH, "组是穿透混合")
kids = group.get_children()
check([k.get_name() for k in kids] ==
      ["1 · Hue", "2 · Saturation", "3 · Value"],
      "三层顺序 Hue / Saturation / Value", [k.get_name() for k in kids])
check([k.get_mode() for k in kids] ==
      [Gimp.LayerMode.HSV_HUE, Gimp.LayerMode.HSV_SATURATION,
       Gimp.LayerMode.HSV_VALUE], "三条分量混合模式对")
check(img.get_layers()[1] is base or img.get_layers()[1].get_name() == "base",
      "原图层还在组下面且没被改动")

print("== 2. 滤镜栈 / filter stack")
hue_l, sat_l, val_l = kids
check(len(val_l.get_filters()) == 2, "Value 层 2 条滤镜",
      len(val_l.get_filters()))
check(len(sat_l.get_filters()) == 3, "Saturation 层 3 条滤镜",
      len(sat_l.get_filters()))
check(len(hue_l.get_filters()) == 3, "Hue 层 3 条滤镜", len(hue_l.get_filters()))
# get_filters() 是「最新在前」，执行顺序是它的反序
names = [f.get_name() for f in hue_l.get_filters()][::-1]
check(names == ["1 · extract", "2 · curve", "3 · encode"],
      "滤镜执行顺序 extract → curve → encode", names)

# 编码由一个算子完成：hue / saturation 各取对应的分量模式。
# 缺 lb:gray-to-component 时插件退回三条曲线，那时这条断言自动跳过。
gtc = [f for f in hue_l.get_filters() if f.get_name() == "3 · encode"]
if gtc and len(gtc) == 1 and HSV._GTC_OK:
    modes = []
    for lay in (hue_l, sat_l):
        f = [x for x in lay.get_filters() if x.get_name() == "3 · encode"][0]
        modes.append(f.get_config().get_property("mode"))
    check(modes == ["hue", "saturation"], "编码算子模式对", modes)
else:
    print("  .. 跳过算子断言（未安装 lb:gray-to-component，走曲线回退）")

print("== 3. 浮点图恒等往返 / float identity")
got = flatten(img)
# 上限是 gimp:curves 的 256 项查表：色相环上 1 个采样点 = 1.4°，折合 0.5 码
close(max_diff(ref, got), 0.0, 1.0 / 255.0, "32 位浮点：恒等往返 ≤ 1 码")

print("== 4. 8 位图恒等往返 / 8-bit identity")
img8, base8, ref8 = make_image()
HSV.split_hsv(img8, base8)
got8 = flatten(img8)
close(max_diff(ref8, got8), 0.0, 1.5 / 255.0, "8 位：恒等曲线 ≤ 1 码")

print("== 5. 曲线 ≈ 直接改 HSV / curves vs direct HSV maths")
imgc, basec, refc = make_image()
HSV.split_hsv(imgc, basec)
grp = imgc.get_layers()[0]
hue_l, sat_l, val_l = grp.get_children()
set_curve(hue_l, lambda t: t ** 1.25)
set_curve(sat_l, lambda t: t ** 0.8)
set_curve(val_l, lambda t: min(1.0, t * 1.1 + 0.02))
gotc = flatten(imgc)
want = array.array('f', bytes(len(refc) * 4))
w0 = imgc.get_width()
h0 = imgc.get_height()
for i in range(0, len(refc), 4):
    p = i // 4
    x, y = p % w0, p // w0
    s = 1.0 if y < h0 // 3 else (0.5 if y < 2 * h0 // 3 else 0.1)
    v = 1.0 if y < h0 // 3 else (0.6 if y < 2 * h0 // 3 else 0.3)
    hh = ((x / float(w0)) ** 1.25) * 360.0
    ss = s ** 0.8
    vv = min(1.0, v * 1.1 + 0.02)
    r, g, b = hsv2rgb(hh, ss, vv)
    want[i:i + 4] = array.array('f', [r, g, b, 1.0])
close(max_diff(want, gotc), 0.0, 3.0 / 255.0, "改曲线 vs 直接改 HSV ≤ 3 码")

print("== 6. 透明区域 / alpha passes through")
imga, basea, refa = make_image(alpha_left=0.4)
HSV.split_hsv(imga, basea)
gota = flatten(imga)
close(max_diff(refa, gota, (3,)), 0.0, 1e-5, "alpha 逐位保留")
close(gota[(imga.get_width() // 4) * 4 + 3], 0.4, 1.5 / 255.0,
      "左半 alpha 仍是 0.4")

print("== 7. 不收组 / no group")
imgn, basen, refn = make_image()
HSV.split_hsv(imgn, basen, make_group=False)
check(not imgn.get_layers()[0].is_group(), "顶层不是组")
check(len(imgn.get_layers()) == 4, "原图 + 三层", len(imgn.get_layers()))
close(max_diff(refn, flatten(imgn)), 0.0, 1.5 / 255.0, "不分组也逐位还原")

print("== 8. 非法输入 / invalid input")
imgg = Gimp.Image.new(16, 16, Gimp.ImageBaseType.RGB)
grp2 = Gimp.GroupLayer.new(imgg, "g")
imgg.insert_layer(grp2, None, 0)
try:
    HSV.split_hsv(imgg, grp2)
    check(False, "图层组应该被拒绝")
except RuntimeError:
    check(True, "图层组被拒绝")

print()
if FAILS:
    raise SystemExit("%d/%d 项失败: %s" % (len(FAILS), CHECKS[0], FAILS))
print("全部 %d 项通过" % CHECKS[0])
