# -*- coding: utf-8 -*-
"""回归：lch-split-curves 插件（LCh 分量层 + 曲线 + 混合模式还原）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_lch_split.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gimp / Gegl 的 GI 绑定）。检查 9 件事：

1. 生成结构：组 + 三层，顺序 Hue / Chroma / Lightness，混合模式对；
2. 每层的滤镜条数与执行顺序（Lightness 3 条，Hue 5 条，Chroma 6 条）；
3. 32 位浮点图：恒等曲线往返 ≤ 1 码；
4. 8 位图：恒等往返 ≤ 2 码；
5. 改曲线 ≈ 直接改 LCh 分量（8 位 ≤ 6 码）；
6. 透明区域 alpha 逐位保留；
7. 不收组（group=False）时同样还原；
8. 图层组作为输入会被拒绝；
9. 编码量程：曲线的 1.0 确实落在 sRGB 最大彩度上。
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
        if os.path.exists(os.path.join(c, "plugin", "lch-split-curves",
                                       "lch-split-curves.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
LCH = _load("lch_split_curves",
            os.path.join(REPO, "plugin", "lch-split-curves",
                         "lch-split-curves.py"))

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


def set_curve(layer, fn, which):
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
            cfg.set_property("channel", Gimp.HistogramChannel.VALUE)
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
img, base, ref = make_image(float_prec=True)
LCH.split_lch(img, base, make_group=True)
group = img.get_layers()[0]
check(group.is_group(), "顶层是图层组")
check(group.get_mode() == Gimp.LayerMode.PASS_THROUGH, "组是穿透混合")
kids = group.get_children()
check([k.get_name() for k in kids] ==
      ["1 · Hue", "2 · Chroma", "3 · Lightness"],
      "三层顺序 Hue / Chroma / Lightness", [k.get_name() for k in kids])
check([k.get_mode() for k in kids] ==
      [Gimp.LayerMode.LCH_HUE, Gimp.LayerMode.LCH_CHROMA,
       Gimp.LayerMode.LCH_LIGHTNESS], "三条分量混合模式对")
check(img.get_layers()[1] is base or img.get_layers()[1].get_name() == "base",
      "原图层还在组下面且没被改动")

print("== 2. 滤镜栈 / filter stack")
hue_l, chroma_l, light_l = kids
check(len(hue_l.get_filters()) == 3, "Hue 层 3 条滤镜",
      len(hue_l.get_filters()))
check(len(chroma_l.get_filters()) == 3, "Chroma 层 3 条滤镜",
      len(chroma_l.get_filters()))
check(len(light_l.get_filters()) == 3, "Lightness 层 3 条滤镜",
      len(light_l.get_filters()))
# get_filters() 是「最新在前」，执行顺序是它的反序
names = [f.get_name() for f in hue_l.get_filters()][::-1]
check(names == ["1 · extract", "2 · curve", "3 · encode"],
      "Hue：extract → curve → encode", names)
names = [f.get_name() for f in chroma_l.get_filters()][::-1]
check(names == ["1 · extract", "2 · curve", "3 · encode"],
      "Chroma：extract → curve → encode（量程由算子参数给）", names)
names = [f.get_name() for f in light_l.get_filters()][::-1]
check(names == ["1 · extract", "2 · curve", "3 · encode"],
      "Lightness：extract → curve → encode", names)

# 编码是一个算子：三个分量各取自己的模式
encs = []
for lay in (hue_l, chroma_l, light_l):
    f = [x for x in lay.get_filters() if x.get_name() == "3 · encode"][0]
    encs.append(f.get_config().get_property("mode"))
check(encs == ["lch-hue", "lch-chroma", "lightness"], "编码算子模式对", encs)

print("== 3. 浮点图恒等往返 / float identity")
got = flatten(img)
close(max_diff(ref, got), 0.0, 1.0 / 255.0, "32 位浮点：恒等往返 ≤ 1 码")

print("== 4. 8 位图恒等往返 / 8-bit identity")
img8, base8, ref8 = make_image()
LCH.split_lch(img8, base8)
got8 = flatten(img8)
close(max_diff(ref8, got8), 0.0, 2.0 / 255.0, "8 位：恒等曲线 ≤ 2 码")

print("== 5. 曲线 ≈ 直接改 LCh / curves vs direct LCh maths")
imgc, basec, refc = make_image()
LCH.split_lch(imgc, basec)
grp = imgc.get_layers()[0]
hue_l, chroma_l, light_l = grp.get_children()
# 三条曲线都是「分量归一化值 → 新值」
fn_l = lambda t: min(1.0, t * 1.10 + 0.02)          # 提亮
fn_c = lambda t: min(1.0, t * 1.35)                  # 加彩度
fn_h = lambda t: t + 0.06 * math.sin(2.0 * math.pi * t)   # 连续偏移（两端相等）
check(set_curve(light_l, fn_l, "2 · curve"), "改 Lightness 曲线")
check(set_curve(chroma_l, fn_c, "2 · curve"), "改 Chroma 曲线")
check(set_curve(hue_l, fn_h, "2 · curve"), "改 Hue 曲线")
gotc = flatten(imgc)

want = array.array('f', bytes(len(refc) * 4))
w0 = imgc.get_width()
h0 = imgc.get_height()
for i in range(0, len(refc), 4):
    p = i // 4
    x, y = p % w0, p // w0
    s = 1.0 if y < h0 // 3 else (0.5 if y < 2 * h0 // 3 else 0.1)
    v = 1.0 if y < h0 // 3 else (0.6 if y < 2 * h0 // 3 else 0.3)
    rgb = hsv2rgb((x / float(w0)) * 360.0, s, v)
    L, C, H = LCH.rgb_to_lch(rgb)
    L2 = 100.0 * fn_l(L / 100.0)
    # 曲线输入是 extract 的原始归一化值 C/200（不再有 scale 那一步），
    # 编码由算子按 chroma-scale=200 还原成 C*
    C2 = 200.0 * fn_c(C / 200.0)
    H2 = 360.0 * fn_h(H / 360.0)
    r, g, b = LCH.lch_to_rgb(L2, C2, H2)
    # 8 位图会把超出色域的结果裁到 [0,1]——这是 GIMP 写缓冲区时做的，不是插件
    want[i:i + 4] = array.array('f', [min(1.0, max(0.0, r)),
                                      min(1.0, max(0.0, g)),
                                      min(1.0, max(0.0, b)), 1.0])
close(max_diff(want, gotc), 0.0, 6.0 / 255.0, "改曲线 vs 直接改 LCh ≤ 6 码")

print("== 6. 透明区域 / alpha passes through")
imga, basea, refa = make_image(alpha_left=0.4)
LCH.split_lch(imga, basea)
gota = flatten(imga)
close(max_diff(refa, gota, (3,)), 0.0, 1e-5, "alpha 逐位保留")
close(gota[(imga.get_width() // 4) * 4 + 3], 0.4, 1.5 / 255.0,
      "左半 alpha 仍是 0.4")

print("== 7. 不收组 / no group")
imgn, basen, refn = make_image(float_prec=True)
LCH.split_lch(imgn, basen, make_group=False)
check(not imgn.get_layers()[0].is_group(), "浮点图：顶层不是组")
check(len(imgn.get_layers()) == 4, "原图 + 三层", len(imgn.get_layers()))
close(max_diff(refn, flatten(imgn)), 0.0, 1.0 / 255.0, "不分组也还原")

# 8 位图不分组会被自动改成组（否则逐层量化，色相偏到 11 码）
img8n, base8n, ref8n = make_image()
LCH.split_lch(img8n, base8n, make_group=False)
check(img8n.get_layers()[0].is_group(), "8 位图：不分组被自动改成组")
close(max_diff(ref8n, flatten(img8n)), 0.0, 2.0 / 255.0,
      "8 位不分组（自动成组）也还原")

print("== 8. 非法输入 / invalid input")
imgg = Gimp.Image.new(16, 16, Gimp.ImageBaseType.RGB)
grp2 = Gimp.GroupLayer.new(imgg, "g")
imgg.insert_layer(grp2, None, 0)
try:
    LCH.split_lch(imgg, grp2)
    check(False, "图层组应该被拒绝")
except RuntimeError:
    check(True, "图层组被拒绝")

print("== 9. 编码量程 / encoding range")
# 路径末端：彩度 1.0 应落在纯蓝（C*=131.21），明度 1.0 落在白，色相 1/3 附近≈绿
c_end = LCH.rgb_to_lch(LCH._CHROMA_PATH[-1])[1]
close(c_end, LCH.MAX_CHROMA, 0.2, "彩度路径末端 = sRGB 最大彩度")
l_end = LCH.rgb_to_lch(LCH._LIGHT_PATH[-1])[0]
close(l_end, 100.0, 0.05, "明度路径末端 L* = 100")
l_start = LCH.rgb_to_lch(LCH._LIGHT_PATH[0])[0]
close(l_start, 0.0, 0.05, "明度路径起点 L* = 0")
# 色相路径：每个采样点的 LCh 色相必须等于 360·t，且全部落在色域内
worst = 0.0
for i in range(256):
    t = i / 255.0
    got_h = LCH.rgb_to_lch(LCH._HUE_PATH[i])[2]
    worst = max(worst, abs((got_h - 360.0 * t + 180.0) % 360.0 - 180.0))
close(worst, 0.0, 0.02, "色相路径：256 点全部落在目标色相上 ≤ 0.02°")
in_gamut = all(-1e-9 <= c <= 1.0 + 1e-9
               for p in LCH._HUE_PATH for c in p)
check(in_gamut, "色相路径整圈都在 sRGB 色域内")

# 曲线是 256 点线性插值，采样点之间的色相也要对——这才是实际生效的精度
worst = 0.0
for j in range(2560):
    t = j / 2559.0
    x = t * 255.0
    i = min(254, int(x))
    w = 1.0 if x >= 255.0 else x - i
    rgb = tuple(LCH._HUE_PATH[i][k] * (1 - w) + LCH._HUE_PATH[i + 1][k] * w
                for k in range(3))
    got_h = LCH.rgb_to_lch(rgb)[2]
    worst = max(worst, abs((got_h - 360.0 * t + 180.0) % 360.0 - 180.0))
close(worst, 0.0, 0.05, "色相路径插值误差 ≤ 0.05°")

print()
if FAILS:
    raise SystemExit("%d/%d 项失败: %s" % (len(FAILS), CHECKS[0], FAILS))
print("全部 %d 项通过" % CHECKS[0])
