# -*- coding: utf-8 -*-
"""回归：hsv-split-curves 插件（HSV 空间调曲线，走适配算子 lb:hsv-dual / lb:hsv-compose）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_hsv_split.py').read())" --quit

必须跑在 GIMP 的 Python 里。检查 9 件事：

1. 生成结构：组 + 一层三联数据层，正常模式；
2. 滤镜条数与执行顺序（decompose / 三条曲线 / compose 共 5 条），三条曲线
   分别挂在红 / 绿 / 蓝通道上；
3. 32 位浮点图：恒等曲线往返 ≈ 0；
4. 8 位图：恒等往返 ≤ 1.5 码；
5. 改 2 · S curve 曲线后，结果的 饱和度 = f(原 饱和度)，另外两个分量不动；
6. 改 3 · V curve 曲线后同理；
7. 改 4 · H curve 曲线后同理；
8. 隐藏原图层后这一层自己还原（RGB + alpha，组蒙版）；
9. 不收组（无 alpha）、图层组输入被拒、带 alpha 自动分组。

断言只在「目标颜色落在 sRGB 色域内」的像素上做：分量推到极端会出色域，
出界部分必然被裁——那是色域的事实，不是误差。
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
        if os.path.exists(os.path.join(c, "plugin", "hsv-split-curves", "hsv-split-curves.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
MOD = _load("hsv_split_curves", os.path.join(REPO, "plugin", "hsv-split-curves", "hsv-split-curves.py"))

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


def ci_close(a, b, tol, label):
    """圆周量（色相）的差。"""
    d = abs(a - b) % 1.0
    close(min(d, 1.0 - d), 0.0, tol, label)


# ---- HSV 参考实现（与 babl 同一套定义，独立于被测插件） -----------------

def rgb2hsv(rgb):
    r, g, b = rgb
    mx, mn = max(rgb), min(rgb)
    v = mx
    d = mx - mn
    s = 0.0 if mx <= 1e-9 else d / mx
    if d <= 1e-9:
        h = 0.0
    elif mx == r:
        h = 60.0 * (((g - b) / d) % 6.0)
    elif mx == g:
        h = 60.0 * ((b - r) / d + 2.0)
    else:
        h = 60.0 * ((r - g) / d + 4.0)
    return h % 360.0, s, v


def hsv2rgb(h, s, v):
    c = v * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = v - c
    if h < 60.0:
        r, g, b = c, x, 0.0
    elif h < 120.0:
        r, g, b = x, c, 0.0
    elif h < 180.0:
        r, g, b = 0.0, c, x
    elif h < 240.0:
        r, g, b = 0.0, x, c
    elif h < 300.0:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return r + m, g + m, b + m


def to_space(rgb):
    return rgb2hsv(rgb)


def from_space(c):
    return hsv2rgb(c[0], c[1], c[2])


HUE_INDEX = 0


def norm(v, index=0):
    """分量 → 数据图里的编码值（0…1）。"""
    return v / 360.0 if index == HUE_INDEX else v


def denorm(x, index=0):
    return x * 360.0 if index == HUE_INDEX else x


# ---- 测试图 / test raster ---------------------------------------------------
# 三维都铺开：r 横、g 纵、b 斜纹，色相 / 彩度 / 明度都能覆盖到。

def make_image(w=48, h=48, float_prec=False, alpha_left=None,
               with_alpha=True):
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
            # 避开 0 / 1 与近黑：Lab / LCh 在暗部对 RGB 的舍入极其敏感，
            # 那不是插件误差，是色彩空间的条件数。
            r = 0.15 + 0.70 * x / float(w - 1)
            g = 0.15 + 0.70 * y / float(h - 1)
            b = 0.20 + 0.60 * ((x * 7 + y * 11) % w) / float(w - 1)
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
    """改那一条曲线（按滤镜名找）。"""
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
top = MOD.split_hsv(img, base, make_group=True)
group = img.get_layers()[0]
check(group.is_group(), "顶层是图层组")
check(group.get_mode() == Gimp.LayerMode.PASS_THROUGH, "组是穿透混合")
kids = group.get_children()
check([k.get_name() for k in kids] == ["1 · HSV S/V/H"],
      "组里只有一层三联数据层", [k.get_name() for k in kids])
check([k.get_mode() for k in kids] == [Gimp.LayerMode.NORMAL],
      "数据层是正常模式")
check(top is group, "返回值是组")

print("== 2. 滤镜栈 / filter stack")
layer = kids[0]
check(len(layer.get_filters()) == 5, "5 条滤镜", len(layer.get_filters()))
names = [f.get_name() for f in layer.get_filters()][::-1]
check(names == ["1 · decompose", "2 · S curve", "3 · V curve", "4 · H curve", "5 · compose"],
      "decompose → 2 · S curve → 3 · V curve → 4 · H curve → compose", names)
ops = [f.get_operation_name() for f in layer.get_filters()][::-1]
check(ops[0] == "lb:hsv-dual" and ops[4] == "lb:hsv-compose",
      "用的是 lb:hsv-dual / lb:hsv-compose", ops)
chans = [f.get_config().get_property("channel")
         for f in layer.get_filters()
         if f.get_operation_name() == "gimp:curves"][::-1]
check(chans == [Gimp.HistogramChannel.RED, Gimp.HistogramChannel.GREEN,
                Gimp.HistogramChannel.BLUE],
      "三条曲线分别挂红 / 绿 / 蓝通道", chans)

# ---- 3/4. 恒等往返 ----------------------------------------------------------

print("== 3. 浮点恒等往返 / float identity")
imgf, basef, reff = make_image(float_prec=True)
MOD.split_hsv(imgf, basef)
close(max_diff(reff, flatten(imgf)) * 255.0, 0.0, 0.05,
      "浮点恒等往返 ≤ 0.05 码")

print("== 4. 8 位恒等往返 / 8-bit identity")
img8, base8, ref8 = make_image()
MOD.split_hsv(img8, base8)
close(max_diff(ref8, flatten(img8)) * 255.0, 0.0, 1.5,
      "8 位恒等往返 ≤ 1.5 码")


# ---- 5/6/7. 改曲线 == 只改那个分量 ------------------------------------------

def effect(label, curve, channel, fn, index, circular=False):
    """改一条曲线，断言结果就是「只把该分量换成 f(原值)」的那个颜色。

    index：0/1/2 = 该分量在 HSV 三元组里的位置。
    """
    img, base, ref = make_image(float_prec=True)
    MOD.split_hsv(img, base)
    layer = img.get_layers()[0].get_children()[0]
    check(set_curve(layer, curve, fn, channel), "改 %s" % curve)
    got = flatten(img)
    worst = 0.0
    worst_other = 0.0
    tested = 0
    for i in range(0, len(ref), 4):
        rgb0 = (ref[i], ref[i + 1], ref[i + 2])
        # 近中性色与近黑的色相 / 彩度没有意义，跳过。
        if max(rgb0) - min(rgb0) < 0.10 or max(rgb0) < 0.12:
            continue
        c0 = to_space(rgb0)
        want = list(c0)
        want[index] = denorm(fn(norm(c0[index], index)), index)
        target = from_space(want)
        if min(target) < -0.002 or max(target) > 1.002:
            continue
        tested += 1
        g0 = to_space((got[i], got[i + 1], got[i + 2]))
        if circular:
            d = abs(norm(g0[index], index) - norm(want[index], index)) % 1.0
            worst = max(worst, min(d, 1.0 - d))
        else:
            worst = max(worst,
                        abs(norm(g0[index], index) - norm(want[index], index)))
        for k in range(3):
            if k == index:
                continue
            worst_other = max(worst_other,
                              abs(norm(g0[k], k) - norm(c0[k], k)))
    check(tested > 30, "%s：色域内的点够多" % label, tested)
    close(worst, 0.0, 1.5 / 255.0 if not circular else 0.35 / 360.0,
          "%s：目标分量对得上" % label)
    close(worst_other, 0.0, 1.5 / 255.0,
          "%s：另外两个分量没被碰" % label)


print("== 5. 2 · S curve 曲线 = 只改 饱和度 / first curve")
fn1 = lambda t: 0.10 + t * 0.85
effect("2 · S curve", "2 · S curve", Gimp.HistogramChannel.RED, fn1, 1, False)

print("== 6. 3 · V curve 曲线 = 只改 明度 / second curve")
fn2 = lambda t: 0.05 + t * 0.90
effect("3 · V curve", "3 · V curve", Gimp.HistogramChannel.GREEN, fn2, 2, False)

print("== 7. 4 · H curve 曲线 = 只改 色相 / third curve")
fn3 = lambda t: 0.02 + t * 0.95
effect("4 · H curve", "4 · H curve", Gimp.HistogramChannel.BLUE, fn3, 0, True)

# ---- 8. alpha / 自足 --------------------------------------------------------

print("== 8. 透明区域 / alpha passes through")
imga, basea, refa = make_image(alpha_left=0.4)
MOD.split_hsv(imga, basea)
check(imga.get_layers()[0].get_mask() is not None, "组上挂了 alpha 蒙版")
# 数据层本身是不透明的（透明度靠组蒙版），原图一起显示时 alpha 会叠加，
# 所以验 alpha 之前先把原图关掉——插件提示里也是这么说的。
basea.set_visible(False)
gota = flatten(imga)
close(max_diff(refa, gota, (3,)), 0.0, 2.0 / 255.0,
      "alpha 逐位保留（组蒙版）")
close(gota[(imga.get_width() // 4) * 4 + 3], 0.4, 1.5 / 255.0,
      "左半 alpha 仍是 0.4")

print("== 8b. 隐藏原图层后自足 / hide the source")
imgh, baseh, refh = make_image(alpha_left=0.4)
MOD.split_hsv(imgh, baseh)
baseh.set_visible(False)
close(max_diff(refh, flatten(imgh)) * 255.0, 0.0, 1.5,
      "原图层隐藏后仍能还原 RGB（≤1.5 码）")

# ---- 9. 不收组 / 非法输入 ---------------------------------------------------

print("== 9. 不收组 / no group")
imgn, basen, refn = make_image(with_alpha=False)
MOD.split_hsv(imgn, basen, make_group=False)
check(not imgn.get_layers()[0].is_group(), "顶层不是组")
check(len(imgn.get_layers()) == 2, "原图 + 一层", len(imgn.get_layers()))
close(max_diff(refn, flatten(imgn)) * 255.0, 0.0, 1.5, "不分组也逐位还原")

imgz, basez, _ = make_image(alpha_left=0.5)
MOD.split_hsv(imgz, basez, make_group=False)
check(imgz.get_layers()[0].is_group(), "带 alpha 不分组 → 自动分组")
check(imgz.get_layers()[0].get_mask() is not None, "自动分组也挂了 alpha 蒙版")

print("== 10. 非法输入 / invalid input")
imgg = Gimp.Image.new(16, 16, Gimp.ImageBaseType.RGB)
grp2 = Gimp.GroupLayer.new(imgg, "g")
imgg.insert_layer(grp2, None, 0)
try:
    MOD.split_hsv(imgg, grp2)
    check(False, "图层组应该被拒绝")
except RuntimeError:
    check(True, "图层组被拒绝")

print()
if FAILS:
    raise SystemExit("%d/%d 项失败: %s" % (len(FAILS), CHECKS[0], FAILS))
print("全部 %d 项通过 / %d checks passed" % (CHECKS[0], CHECKS[0]))
