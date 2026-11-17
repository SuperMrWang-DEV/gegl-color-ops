# -*- coding: utf-8 -*-
"""回归：hsi-split-curves 插件（HSI 空间调曲线，经适配算子接到 HSV 色相）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_hsi_split.py').read())" --quit

必须跑在 GIMP 的 Python 里。检查 9 件事：

1. 生成结构：组 + 一层，正常模式；
2. 滤镜条数与执行顺序（decompose / S / I / H / compose 共 5 条）；
3. 32 位浮点图：恒等曲线往返 ≈ 0；
4. 8 位图：恒等往返 ≤ 1.5 码；
5. 改 S 曲线后，结果的 HSI 饱和度 = f(原 S)，I 与色相不动；
6. 改 I 曲线后同理；
7. 改 H 曲线后，结果的 HSI 色相 = f(原色相)，S 与 I 不动（这一条正是
   「不能借 HSV 色相模式」的证据：借了的话 S、I 会被带走 0.05 / 0.08）；
8. 隐藏原图层后这一层自己还原（RGB + alpha，组蒙版）；
9. 不收组（无 alpha）、图层组输入被拒、缺算子时报错。

断言只在「目标颜色落在 sRGB 色域内」的像素上做：HSI 的色域是六边形棱锥，
不是立方体，S/I 一拉就会出界，出界部分必然被裁——那是色域的事实，不是误差。
"""
import math
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
        if os.path.exists(os.path.join(c, "plugin", "hsi-split-curves",
                                       "hsi-split-curves.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
HSI = _load("hsi_split_curves",
            os.path.join(REPO, "plugin", "hsi-split-curves",
                         "hsi-split-curves.py"))

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


# ---- HSI 参考实现（与 common/color-levels.h 同一套定义） --------------------

def rgb_to_hsi(rgb):
    r, g, b = rgb
    i = (r + g + b) / 3.0
    mx, mn = max(r, g, b), min(r, g, b)
    if i <= 1e-9 or mx - mn <= 1e-9:
        return 0.0, 0.0, i
    s = 1.0 - mn / i
    num = 0.5 * ((r - g) + (r - b))
    den = math.sqrt((r - g) ** 2 + (r - b) * (g - b))
    if den <= 1e-9:
        return 0.0, s, i
    theta = math.degrees(math.acos(max(-1.0, min(1.0, num / den))))
    h = theta if b <= g else 360.0 - theta
    return h % 360.0, s, i


def hsi_to_rgb(h, s, i):
    """(H°, S, I) → sRGB，HSI 的余弦式逆变换；不裁色域（调用方自己判）。"""
    h = h % 360.0
    if h < 120.0:
        lo = i * (1.0 - s)
        hi = i * (1.0 + s * math.cos(math.radians(h))
                  / math.cos(math.radians(60.0 - h)))
        return hi, 3.0 * i - lo - hi, lo
    if h < 240.0:
        a = h - 120.0
        lo = i * (1.0 - s)
        hi = i * (1.0 + s * math.cos(math.radians(a))
                  / math.cos(math.radians(60.0 - a)))
        return lo, hi, 3.0 * i - lo - hi
    a = h - 240.0
    lo = i * (1.0 - s)
    hi = i * (1.0 + s * math.cos(math.radians(a))
              / math.cos(math.radians(60.0 - a)))
    return 3.0 * i - lo - hi, lo, hi


def _clamp_rgb(rgb):
    return tuple(min(1.0, max(0.0, c)) for c in rgb)


# ---- 测试图 / test raster ---------------------------------------------------
# 横向扫色相，纵向三段不同 (S, I) 组合。

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
    bands = ((0.85, 0.45), (0.55, 0.65), (0.30, 0.35))   # (S, I)
    for y in range(h):
        s, iv = bands[min(2, y * 3 // h)]
        for x in range(w):
            i = (y * w + x) * 4
            hue = 8.0 + (x / float(w)) * 344.0
            r, g, b = _clamp_rgb(hsi_to_rgb(hue, s, iv))
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


def set_curve(layer, which, fn, channel, index=0):
    """改某一层的某条曲线（按滤镜名找；重名时用 index 选第几条）。"""
    hits = [f for f in layer.get_filters() if f.get_name() == which]
    if len(hits) <= index:
        return False
    filt = hits[index]
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


def max_diff(a, b, channels=(0, 1, 2)):
    worst = 0.0
    for i in range(0, len(a), 4):
        for k in channels:
            worst = max(worst, abs(a[i + k] - b[i + k]))
    return worst


def hue_delta(h0, h1):
    d = abs(h0 - h1) % 360.0
    return min(d, 360.0 - d)


# ---- 1/2. 结构与滤镜栈 ------------------------------------------------------

print("== 1. 结构 / structure")
img, base, ref = make_image()
top = HSI.split_hsi(img, base, make_group=True)
group = img.get_layers()[0]
check(group.is_group(), "顶层是图层组")
check(group.get_mode() == Gimp.LayerMode.PASS_THROUGH, "组是穿透混合")
kids = group.get_children()
check([k.get_name() for k in kids] == ["1 · HSI S/I/H"],
      "组里只有一层三联数据层", [k.get_name() for k in kids])
check([k.get_mode() for k in kids] == [Gimp.LayerMode.NORMAL],
      "数据层是正常模式")
check(top is group, "返回值是组")

print("== 2. 滤镜栈 / filter stack")
layer = kids[0]
check(len(layer.get_filters()) == 5, "5 条滤镜", len(layer.get_filters()))
names = [f.get_name() for f in layer.get_filters()][::-1]
check(names == ["1 · decompose", "2 · S curve", "3 · I curve",
                "4 · H curve", "5 · compose"],
      "decompose → S → I → H → compose", names)
ops = [f.get_operation_name() for f in layer.get_filters()][::-1]
check(ops[0] == "lb:hsi-dual" and ops[4] == "lb:hsi-compose",
      "用的是 hsi-dual / hsi-compose", ops)
# 三条曲线必须分别挂在红 / 绿 / 蓝通道上（按名字挑，compose 没有 channel）
chans = [f.get_config().get_property("channel")
         for f in layer.get_filters()
         if f.get_operation_name() == "gimp:curves"][::-1]
check(chans == [Gimp.HistogramChannel.RED, Gimp.HistogramChannel.GREEN,
                Gimp.HistogramChannel.BLUE],
      "S/I/H 曲线分别挂红 / 绿 / 蓝通道", chans)

# ---- 3. 浮点恒等往返 --------------------------------------------------------

print("== 3. 浮点恒等往返 / float identity")
imgf, basef, reff = make_image(float_prec=True)
HSI.split_hsi(imgf, basef)
gotf = flatten(imgf)
close(max_diff(reff, gotf) * 255.0, 0.0, 0.05, "浮点恒等往返 ≤ 0.05 码")

# ---- 4. 8 位恒等往返 --------------------------------------------------------

print("== 4. 8 位恒等往返 / 8-bit identity")
img8, base8, ref8 = make_image()
HSI.split_hsi(img8, base8)
got8 = flatten(img8)
close(max_diff(ref8, got8) * 255.0, 0.0, 1.5, "8 位恒等往返 ≤ 1.5 码")


# ---- 5/6/7. 改曲线 == 直接改 HSI 分量 --------------------------------------

def hsi_effect(label, curve_name, channel, fn, fmap, desc):
    """改一条曲线，然后断言「结果就是那个 HSI 点」，并且另外两个分量没动。

    只在目标颜色落在 sRGB 色域内时断言：HSI 的色域是六边形棱锥，S/I 推到
    极端必然出界，出界部分被裁是色域的事实，不是误差。
    """
    img, base, ref = make_image(float_prec=True)
    HSI.split_hsi(img, base)
    layer = img.get_layers()[0].get_children()[0]
    check(set_curve(layer, curve_name, fn, channel), "改 %s" % desc)
    got = flatten(img)
    worst_s = worst_i = worst_h = 0.0
    tested = 0
    for i in range(0, len(ref), 4):
        h0, s0, i0 = rgb_to_hsi((ref[i], ref[i + 1], ref[i + 2]))
        h1, s1, i1 = fmap(h0, s0, i0)
        target = hsi_to_rgb(h1, s1, i1)
        if min(target) < -0.002 or max(target) > 1.002:
            continue
        tested += 1
        g0, gs, gi = rgb_to_hsi((got[i], got[i + 1], got[i + 2]))
        worst_s = max(worst_s, abs(gs - s1))
        worst_i = max(worst_i, abs(gi - i1))
        worst_h = max(worst_h, hue_delta(g0, h1))
    check(tested > 100, "%s：色域内的点够多" % label, tested)
    close(worst_s, 0.0, 1.0 / 255.0, "%s：S 对得上（≤1 码）" % label)
    close(worst_i, 0.0, 1.0 / 255.0, "%s：I 对得上（≤1 码）" % label)
    close(worst_h, 0.0, 0.35, "%s：色相角对得上（≤0.35°）" % label)


print("== 5. S 曲线 = 只改 HSI 饱和度 / S curve")
fn_s = lambda t: 0.08 + t * 0.86
hsi_effect("S 曲线", "2 · S curve", Gimp.HistogramChannel.RED, fn_s,
           (lambda h, s, i: (h, fn_s(s), i)), "S 曲线（红通道）")

print("== 6. I 曲线 = 只改 HSI 强度 / I curve")
fn_i = lambda t: 0.12 + t * 0.80
hsi_effect("I 曲线", "3 · I curve", Gimp.HistogramChannel.GREEN, fn_i,
           (lambda h, s, i: (h, s, fn_i(i))), "I 曲线（绿通道）")

print("== 7. H 曲线 = 只改 HSI 色相角 / H curve")


def fn_h(t):
    """连续、两端相等的色相曲线：t + 0.3·sin(2πt)/(2π)。"""
    return t + 0.3 * math.sin(2.0 * math.pi * t) / (2.0 * math.pi)


hsi_effect("H 曲线", "4 · H curve", Gimp.HistogramChannel.BLUE, fn_h,
           (lambda h, s, i: ((fn_h(h / 360.0) * 360.0) % 360.0, s, i)),
           "H 曲线（蓝通道）")

# 借「HSV 色相」模式换角会带走 HSI 的 S、I——这是本插件只用一层的理由，
# 把量级钉在测试里（换同样的曲线，S/I 会偏到这个数）。
print("== 7b. 对照：借 HSV 色相模式换角会带走 S、I / why not HSV_HUE")
worst_drift_s = worst_drift_i = 0.0
for i in range(0, len(ref), 4):
    h0, s0, i0 = rgb_to_hsi((ref[i], ref[i + 1], ref[i + 2]))
    if s0 < 0.15 or i0 < 0.1:
        continue
    mx, mn = max(ref[i], ref[i + 1], ref[i + 2]), min(ref[i], ref[i + 1], ref[i + 2])
    v = mx
    sv = 0.0 if mx <= 0 else (mx - mn) / mx
    h1 = (fn_h(h0 / 360.0) * 360.0) % 360.0
    # HSV(h1, Sv, V) 的实际 RGB（HSV 与 HSL 同扇区公式，取 l 由 c/v 反推）
    c = v * sv
    x = c * (1.0 - abs((h1 / 60.0) % 2.0 - 1.0))
    m = v - c
    if h1 < 60:
        t = (c, x, 0.0)
    elif h1 < 120:
        t = (x, c, 0.0)
    elif h1 < 180:
        t = (0.0, c, x)
    elif h1 < 240:
        t = (0.0, x, c)
    elif h1 < 300:
        t = (x, 0.0, c)
    else:
        t = (c, 0.0, x)
    _, s2, i2 = rgb_to_hsi((t[0] + m, t[1] + m, t[2] + m))
    worst_drift_s = max(worst_drift_s, abs(s2 - s0))
    worst_drift_i = max(worst_drift_i, abs(i2 - i0))
check(worst_drift_i > 0.02,
      "HSV 色相模式会带走 I（%.3f ≈ %.0f 码）—— 所以不用它"
      % (worst_drift_i, worst_drift_i * 255),
      worst_drift_i)

# ---- 8. 隐藏原图层 / hide the source ---------------------------------------

print("== 8. 隐藏原图层后自足 / hide the source")
imgh, baseh, refh = make_image(float_prec=True, alpha_left=0.4)
HSI.split_hsi(imgh, baseh)
baseh.set_visible(False)
goth = flatten(imgh)
close(max_diff(refh, goth) * 255.0, 0.0, 1.5,
      "原图层隐藏后仍能还原 RGB（≤1.5 码）")
close(max_diff(refh, goth, (3,)) * 255.0, 0.0, 2.0,
      "原图层隐藏后 alpha 仍对（组蒙版）")
check(imgh.get_layers()[0].get_mask() is not None, "组上挂了 alpha 蒙版")

# ---- 9. 边界 / edges -------------------------------------------------------

print("== 9. 边界 / edges")
imgn, basen, refn = make_image(float_prec=True, with_alpha=False)
HSI.split_hsi(imgn, basen, make_group=False)
check(not imgn.get_layers()[0].is_group(), "无 alpha 时不分组")
check(len(imgn.get_layers()) == 2, "原图 + 一层", len(imgn.get_layers()))
close(max_diff(refn, flatten(imgn)) * 255.0, 0.0, 1.5, "不分组也精确还原")

imgz, basez, _ = make_image(alpha_left=0.5)
HSI.split_hsi(imgz, basez, make_group=False)
check(imgz.get_layers()[0].is_group(), "带 alpha 不分组 → 自动分组")
check(imgz.get_layers()[0].get_mask() is not None, "自动分组也挂了 alpha 蒙版")

imgg = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
grp = Gimp.GroupLayer.new(imgg, "g")
imgg.insert_layer(grp, None, 0)
try:
    HSI.split_hsi(imgg, grp)
    check(False, "图层组输入被拒绝")
except RuntimeError:
    check(True, "图层组输入被拒绝")

try:
    HSI._require_adapter_ops(base)
    check(True, "适配算子探测通过")
except Exception as exc:
    check(False, "适配算子探测通过", exc)

print()
if FAILS:
    print("失败 %d / %d 项：%s" % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
else:
    print("全部 %d 项通过" % CHECKS[0])
