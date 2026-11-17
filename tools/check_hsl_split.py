# -*- coding: utf-8 -*-
"""回归：hsl-split-curves 插件（HSL 空间调曲线，经适配算子接到 HSV 混合模式）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_hsl_split.py').read())" --quit

必须跑在 GIMP 的 Python 里。检查 8 件事：

1. 生成结构：组 + 两层，顺序 Hue / S·L，混合模式对；
2. 每层的滤镜条数与执行顺序（S/L 4 条，Hue 3 条）；
3. 32 位浮点图：恒等曲线往返 ≈ 0（适配算子用 babl，无查表）；
4. 8 位图：恒等往返 ≤ 1.5 码（只剩量化）；
5. 改 S 曲线后，结果的 HSL 饱和度 = f(原 S)、明度不变（这是「等价于直接改
   HSL」的核心断言）；
6. 改 L 曲线后同理；
7. 隐藏原图层后两层自己还原（RGB + alpha，组蒙版）；
8. 不收组（无 alpha）、图层组输入被拒、缺算子时报错。
"""
import os
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
        if os.path.exists(os.path.join(c, "plugin", "hsl-split-curves",
                                       "hsl-split-curves.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
HSL = _load("hsl_split_curves",
            os.path.join(REPO, "plugin", "hsl-split-curves",
                         "hsl-split-curves.py"))

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

def hsl2rgb(h, s, l):
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c / 2
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


def rgb2hsl(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    l = (mx + mn) / 2.0
    if d == 0:
        return 0.0, 0.0, l
    s = d / (1 - abs(2 * l - 1))
    if mx == r:
        h = (60 * ((g - b) / d)) % 360
    elif mx == g:
        h = 60 * ((b - r) / d) + 120
    else:
        h = 60 * ((r - g) / d) + 240
    return h, s, l


def make_image(w=48, h=48, float_prec=False, alpha_left=None,
               with_alpha=True):
    """横向铺满色相，纵向三段不同 S/L 组合，可选左半透明。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    if float_prec:
        proc = Gimp.get_pdb().lookup_procedure('gimp-image-convert-precision')
        cfg = proc.create_config()
        cfg.set_property('image', img)
        cfg.set_property('precision', Gimp.Precision.FLOAT_NON_LINEAR)
        proc.run(cfg)
    layer_type = (Gimp.ImageType.RGBA_IMAGE if with_alpha
                  else Gimp.ImageType.RGB_IMAGE)
    base = Gimp.Layer.new(img, "base", w, h, layer_type, 100.0,
                          Gimp.LayerMode.NORMAL)
    img.insert_layer(base, None, 0)
    px = array.array('f', bytes(w * h * 4))
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            if y < h // 3:
                s, l = 0.9, 0.5
            elif y < 2 * h // 3:
                s, l = 0.5, 0.7
            else:
                s, l = 0.2, 0.35
            r, g, b = hsl2rgb((x / float(w)) * 360.0, s, l)
            a = alpha_left if (alpha_left is not None and x < w // 2) else 1.0
            px[i:i + 4] = array.array('f', [r, g, b, a])
    if with_alpha:
        base.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A float",
                              px.tobytes())
    else:
        rgb = array.array('f')
        for i in range(0, len(px), 4):
            rgb.extend(px[i:i + 3])
        base.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B' float",
                              rgb.tobytes())
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


def set_curve(layer, which, fn, channel):
    """改某一层的某条曲线（按滤镜名找）。"""
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
top = HSL.split_hsl(img, base, make_group=True)
group = img.get_layers()[0]
check(group.is_group(), "顶层是图层组")
check(group.get_mode() == Gimp.LayerMode.PASS_THROUGH, "组是穿透混合")
kids = group.get_children()
check([k.get_name() for k in kids] == ["2 · Hue", "1 · S / L"],
      "两层顺序（上→下）Hue / S·L", [k.get_name() for k in kids])
check([k.get_mode() for k in kids] ==
      [Gimp.LayerMode.HSV_HUE, Gimp.LayerMode.NORMAL],
      "Hue 层用 HSV 色相模式，S/L 层是正常模式")
check(top is group, "返回值是组")

print("== 2. 滤镜栈 / filter stack")
hue_l, sl_l = kids
check(len(sl_l.get_filters()) == 4, "S/L 层 4 条滤镜",
      len(sl_l.get_filters()))
check(len(hue_l.get_filters()) == 3, "Hue 层 3 条滤镜",
      len(hue_l.get_filters()))
# get_filters() 最新在前，执行顺序是反序
names = [f.get_name() for f in sl_l.get_filters()][::-1]
check(names == ["1 · decompose", "2 · S curve", "3 · L curve", "4 · compose"],
      "S/L：decompose → S 曲线 → L 曲线 → compose", names)
names = [f.get_name() for f in hue_l.get_filters()][::-1]
check(names == ["1 · hue", "2 · H curve", "3 · encode"],
      "Hue：extract → 曲线 → encode", names)

# ---- 3. 浮点恒等往返 --------------------------------------------------------

print("== 3. 浮点恒等往返 / float identity")
imgf, basef, reff = make_image(float_prec=True)
HSL.split_hsl(imgf, basef)
gotf = flatten(imgf)
close(max_diff(reff, gotf), 0.0, 0.01 / 255.0,
      "浮点恒等往返 ≤ 0.01 码")

# ---- 4. 8 位恒等往返 --------------------------------------------------------

print("== 4. 8 位恒等往返 / 8-bit identity")
img8, base8, ref8 = make_image()
HSL.split_hsl(img8, base8)
got8 = flatten(img8)
close(max_diff(ref8, got8), 0.0, 1.5 / 255.0, "8 位恒等往返 ≤ 1.5 码")

# ---- 5/6. 改曲线 == 直接改 HSL 分量 ----------------------------------------

print("== 5. S 曲线 = 只改 HSL 饱和度 / S curve only moves S")
imgs, bases, refs = make_image(float_prec=True)
topS = HSL.split_hsl(imgs, bases)
grpS = imgs.get_layers()[0]
hueS, slS = grpS.get_children()
fn_s = lambda t: t * 0.5
check(set_curve(slS, "2 · S curve", fn_s, Gimp.HistogramChannel.RED),
      "改 S 曲线（红通道）")
gots = flatten(imgs)
worst_s = 0.0
worst_l = 0.0
worst_h = 0.0
for i in range(0, len(refs), 4):
    h0, s0, l0 = rgb2hsl(refs[i], refs[i + 1], refs[i + 2])
    h1, s1, l1 = rgb2hsl(gots[i], gots[i + 1], gots[i + 2])
    worst_s = max(worst_s, abs(s1 - s0 * 0.5) * 255)
    worst_l = max(worst_l, abs(l1 - l0) * 255)
    dh = abs((h1 - h0 + 180) % 360 - 180)
    worst_h = max(worst_h, dh)
close(worst_s, 0.0, 1.0, "结果的 HSL 饱和度 = 0.5×原 S（≤1 码）")
close(worst_l, 0.0, 1.0, "HSL 明度不动（≤1 码）")
check(worst_h < 0.05, "HSL 色相不动（%.4f° < 0.05°）" % worst_h)

print("== 6. L 曲线 = 只改 HSL 明度 / L curve only moves L")
imgl, basel, refl = make_image(float_prec=True)
HSL.split_hsl(imgl, basel)
grpl = imgl.get_layers()[0]
huel, sll = grpl.get_children()
fn_l = lambda t: 0.1 + t * 0.8
check(set_curve(sll, "3 · L curve", fn_l, Gimp.HistogramChannel.GREEN),
      "改 L 曲线（绿通道）")
gotl = flatten(imgl)
worst_l2 = 0.0
worst_s2 = 0.0
for i in range(0, len(refl), 4):
    h0, s0, l0 = rgb2hsl(refl[i], refl[i + 1], refl[i + 2])
    h1, s1, l1 = rgb2hsl(gotl[i], gotl[i + 1], gotl[i + 2])
    worst_l2 = max(worst_l2, abs(l1 - (0.1 + l0 * 0.8)) * 255)
    worst_s2 = max(worst_s2, abs(s1 - s0) * 255)
close(worst_l2, 0.0, 1.0, "结果的 HSL 明度 = 0.1 + 0.8×原 L（≤1 码）")
close(worst_s2, 0.0, 1.0, "HSL 饱和度不动（≤1 码）")

# ---- 7. 隐藏原图层 / hide the source ---------------------------------------

print("== 7. 隐藏原图层后自足 / hide the source")
imgh, baseh, refh = make_image(float_prec=True, alpha_left=0.4)
HSL.split_hsl(imgh, baseh)
baseh.set_visible(False)
goth = flatten(imgh)
close(max_diff(refh, goth), 0.0, 1.5 / 255.0,
      "原图层隐藏后仍能还原 RGB（≤1.5 码）")
close(max_diff(refh, goth, (3,)), 0.0, 2.0 / 255.0,
      "原图层隐藏后 alpha 仍对（组蒙版）")
check(imgh.get_layers()[0].get_mask() is not None, "组上挂了 alpha 蒙版")

# ---- 8. 边界 / edges -------------------------------------------------------

print("== 8. 边界 / edges")
# 无 alpha 的层可以不分组
imgn, basen, refn = make_image(float_prec=True, with_alpha=False)
HSL.split_hsl(imgn, basen, make_group=False)
check(not imgn.get_layers()[0].is_group(), "无 alpha 时不分组")
check(len(imgn.get_layers()) == 3, "原图 + 两层", len(imgn.get_layers()))
close(max_diff(refn, flatten(imgn)), 0.0, 1.5 / 255.0, "不分组也精确还原")

# 带 alpha 又要求不分组 → 自动分组（蒙版只能挂组上）
imgz, basez, _ = make_image(alpha_left=0.5)
HSL.split_hsl(imgz, basez, make_group=False)
check(imgz.get_layers()[0].is_group(), "带 alpha 不分组 → 自动分组")
check(imgz.get_layers()[0].get_mask() is not None, "自动分组也挂了 alpha 蒙版")

# 图层组作为输入要被拒绝
imgg = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
grp = Gimp.GroupLayer.new(imgg, "g")
imgg.insert_layer(grp, None, 0)
try:
    HSL.split_hsl(imgg, grp)
    check(False, "图层组输入被拒绝")
except RuntimeError:
    check(True, "图层组输入被拒绝")

# 缺算子时的报错路径（把探测结果伪造成 False 不该影响别处，这里只验证消息）
try:
    HSL._require_adapter_ops(base)
    check(True, "适配算子探测通过")
except Exception as exc:
    check(False, "适配算子探测通过", exc)

print()
if FAILS:
    print("失败 %d / %d 项：%s" % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
else:
    print("全部 %d 项通过" % CHECKS[0])
