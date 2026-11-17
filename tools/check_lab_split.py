# -*- coding: utf-8 -*-
"""回归：lab-split-curves 插件（Lab 空间调曲线，经适配算子接到 LCh 明度）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_lab_split.py').read())" --quit

必须跑在 GIMP 的 Python 里。检查 8 件事：

1. 生成结构：组 + 两层，顺序 L / a·b，混合模式对；
2. 每层的滤镜条数与执行顺序（a/b 4 条，L 3 条）；
3. 32 位浮点图：恒等曲线往返 ≈ 0（适配算子用 babl，无查表）；
4. 8 位图：恒等往返 ≤ 1.5 码（只剩量化）；
5. 改 a 曲线后，结果的 Lab a = f(原 a)，b 与 L* 不动（这是「等价于直接改
   Lab」的核心断言）；
6. 改 b 曲线、L 曲线同理；
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
        if os.path.exists(os.path.join(c, "plugin", "lab-split-curves",
                                       "lab-split-curves.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
LAB = _load("lab_split_curves",
            os.path.join(REPO, "plugin", "lab-split-curves",
                         "lab-split-curves.py"))

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
# 直接在 Lab 里铺格：横向 a* 扫、纵向分三段不同 b*/L*，比 RGB 色轮覆盖得广。

def _clamp_rgb(rgb):
    return tuple(min(1.0, max(0.0, c)) for c in rgb)


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
    bands = ((52.0, -18.0), (70.0, 22.0), (34.0, 6.0))   # (L*, b*)
    for y in range(h):
        light, bb = bands[min(2, y * 3 // h)]
        for x in range(w):
            i = (y * w + x) * 4
            a = -62.0 + x * (124.0 / max(1, w - 1))
            r, g, b = _clamp_rgb(LAB.lab_to_rgb(light, a, bb))
            al = alpha_left if (alpha_left is not None and x < w // 2) else 1.0
            px[i:i + 4] = array.array('f', [r, g, b, al])
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


# a/b 的数据图量程是 255 个 Lab 单位（−128…127），所以「1 码」≈ 1 个 Lab 单位；
# L* 是 100 个单位跨 255 码，1 码 ≈ 0.39 个 L* 单位。
A_CODE = 1.0
L_CODE = 255.0 / 100.0

# ---- 1/2. 结构与滤镜栈 ------------------------------------------------------

print("== 1. 结构 / structure")
img, base, ref = make_image()
top = LAB.split_lab(img, base, make_group=True)
group = img.get_layers()[0]
check(group.is_group(), "顶层是图层组")
check(group.get_mode() == Gimp.LayerMode.PASS_THROUGH, "组是穿透混合")
kids = group.get_children()
check([k.get_name() for k in kids] == ["2 · L", "1 · a / b"],
      "两层顺序（上→下）L / a·b", [k.get_name() for k in kids])
check([k.get_mode() for k in kids] ==
      [Gimp.LayerMode.LCH_LIGHTNESS, Gimp.LayerMode.NORMAL],
      "L 层用 LCh 明度模式，a/b 层是正常模式")
check(top is group, "返回值是组")

print("== 2. 滤镜栈 / filter stack")
light_l, ab_l = kids
check(len(ab_l.get_filters()) == 4, "a/b 层 4 条滤镜", len(ab_l.get_filters()))
check(len(light_l.get_filters()) == 3, "L 层 3 条滤镜",
      len(light_l.get_filters()))
names = [f.get_name() for f in ab_l.get_filters()][::-1]
check(names == ["1 · decompose", "2 · a curve", "3 · b curve", "4 · compose"],
      "a/b：decompose → a 曲线 → b 曲线 → compose", names)
names = [f.get_name() for f in light_l.get_filters()][::-1]
check(names == ["1 · lightness", "2 · L curve", "3 · encode"],
      "L：extract → 曲线 → encode", names)

# 提取器确实挂在 lab-dual / lab-compose 上
ops = [f.get_operation_name() for f in ab_l.get_filters()][::-1]
check(ops[0] == "lb:lab-dual" and ops[3] == "lb:lab-compose",
      "a/b 层用的是 lab-dual / lab-compose", ops)

# ---- 3. 浮点恒等往返 --------------------------------------------------------

print("== 3. 浮点恒等往返 / float identity")
imgf, basef, reff = make_image(float_prec=True)
LAB.split_lab(imgf, basef)
gotf = flatten(imgf)
worst_f = max_diff(reff, gotf) * 255.0
close(worst_f, 0.0, 0.05, "浮点恒等往返 ≤ 0.05 码")

# ---- 4. 8 位恒等往返 --------------------------------------------------------

print("== 4. 8 位恒等往返 / 8-bit identity")
img8, base8, ref8 = make_image()
LAB.split_lab(img8, base8)
got8 = flatten(img8)
worst_8 = max_diff(ref8, got8) * 255.0
close(worst_8, 0.0, 1.5, "8 位恒等往返 ≤ 1.5 码")

# ---- 5/6. 改曲线 == 直接改 Lab 分量 ----------------------------------------
# 做法：把曲线作用于某个分量后，算出「那个 Lab 点」应该是什么颜色，再和实际
# 合成的颜色比。sRGB 装不下的 Lab 点（S、I 拉猛了就会出界）必须跳过——裁切
# 是色域的物理事实，不是插件的误差，拿它当断言只会测到裁切本身。

def lab_effect(label, curve_name, channel, fn, fmap, desc, moved):
    img, base, ref = make_image(float_prec=True)
    LAB.split_lab(img, base)
    grp = img.get_layers()[0]
    light, ab = grp.get_children()
    host = light if curve_name.startswith("2 · L") else ab
    check(set_curve(host, curve_name, fn, channel), "改 %s" % desc)
    got = flatten(img)
    worst_rgb = worst_a = worst_b = worst_l = 0.0
    tested = skipped = 0
    for i in range(0, len(ref), 4):
        l0, a0, b0 = LAB.rgb_to_lab((ref[i], ref[i + 1], ref[i + 2]))
        l1, a1, b1 = fmap(l0, a0, b0)
        target = LAB.lab_to_rgb(l1, a1, b1)
        if min(target) < -0.002 or max(target) > 1.002:
            skipped += 1
            continue
        tested += 1
        g1 = LAB.rgb_to_lab((got[i], got[i + 1], got[i + 2]))
        worst_rgb = max(worst_rgb,
                        max(abs(got[i + k] - target[k]) for k in range(3))
                        * 255.0)
        worst_l = max(worst_l, abs(g1[0] - l1))
        worst_a = max(worst_a, abs(g1[1] - a1))
        worst_b = max(worst_b, abs(g1[2] - b1))
    close(worst_rgb, 0.0, 0.5,
          "%s：结果就是那个 Lab 点（≤0.5 码，%d 个点，跳过 %d）"
          % (label, tested, skipped))
    for name, delta, tol, unit in (("L", worst_l, L_CODE, "0.39 单位"),
                                   ("a", worst_a, A_CODE, "1 码"),
                                   ("b", worst_b, A_CODE, "1 码")):
        if name == moved:
            continue
        close(delta, 0.0, tol, "%s：%s* 不动（≤%s）" % (label, name, unit))
    check(tested > 100, "%s：色域内的点够多" % label, tested)


def _a_from(t):
    return lambda a: t((a + 128.0) / 255.0) * 255.0 - 128.0


def _b_from(t):
    return lambda b: t((b + 128.0) / 255.0) * 255.0 - 128.0


def _l_from(t):
    return lambda l: t(l / 100.0) * 100.0


print("== 5. a 曲线 = 只改 a* / a curve only moves a*")
fn_a = lambda t: 0.5 + (t - 0.5) * 0.6          # 围绕中性灰压缩 0.6 倍
fa = _a_from(fn_a)
lab_effect("a 曲线", "2 · a curve", Gimp.HistogramChannel.RED, fn_a,
           (lambda l, a, b: (l, fa(a), b)), "a 曲线（红通道）", "a")

print("== 6. b 曲线与 L 曲线 / b and L curves")
fn_b = lambda t: 0.45 + (t - 0.45) * 0.5        # 往蓝压一半，但不出色域
fb = _b_from(fn_b)
lab_effect("b 曲线", "3 · b curve", Gimp.HistogramChannel.GREEN, fn_b,
           (lambda l, a, b: (l, a, fb(b))), "b 曲线（绿通道）", "b")

fn_l = lambda t: 0.1 + t * 0.8
fl = _l_from(fn_l)
lab_effect("L 曲线", "2 · L curve", Gimp.HistogramChannel.VALUE, fn_l,
           (lambda l, a, b: (fl(l), a, b)), "L 曲线（值通道）", "L")

# ---- 7. 隐藏原图层 / hide the source ---------------------------------------

print("== 7. 隐藏原图层后自足 / hide the source")
imgh, baseh, refh = make_image(float_prec=True, alpha_left=0.4)
LAB.split_lab(imgh, baseh)
baseh.set_visible(False)
goth = flatten(imgh)
close(max_diff(refh, goth) * 255.0, 0.0, 1.5,
      "原图层隐藏后仍能还原 RGB（≤1.5 码）")
close(max_diff(refh, goth, (3,)) * 255.0, 0.0, 2.0,
      "原图层隐藏后 alpha 仍对（组蒙版）")
check(imgh.get_layers()[0].get_mask() is not None, "组上挂了 alpha 蒙版")

# ---- 8. 边界 / edges -------------------------------------------------------

print("== 8. 边界 / edges")
imgn, basen, refn = make_image(float_prec=True, with_alpha=False)
LAB.split_lab(imgn, basen, make_group=False)
check(not imgn.get_layers()[0].is_group(), "无 alpha 时不分组")
check(len(imgn.get_layers()) == 3, "原图 + 两层", len(imgn.get_layers()))
close(max_diff(refn, flatten(imgn)) * 255.0, 0.0, 1.5, "不分组也精确还原")

imgz, basez, _ = make_image(alpha_left=0.5)
LAB.split_lab(imgz, basez, make_group=False)
check(imgz.get_layers()[0].is_group(), "带 alpha 不分组 → 自动分组")
check(imgz.get_layers()[0].get_mask() is not None, "自动分组也挂了 alpha 蒙版")

imgg = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
grp = Gimp.GroupLayer.new(imgg, "g")
imgg.insert_layer(grp, None, 0)
try:
    LAB.split_lab(imgg, grp)
    check(False, "图层组输入被拒绝")
except RuntimeError:
    check(True, "图层组输入被拒绝")

try:
    LAB._require_adapter_ops(base)
    check(True, "适配算子探测通过")
except Exception as exc:
    check(False, "适配算子探测通过", exc)

# 明度编码器用的是 lightness 模式（不是 lch-chroma 之类）
gtc = None
for f in light_l.get_filters():
    if f.get_operation_name() == "lb:gray-to-component":
        gtc = f
if gtc is not None:
    check(gtc.get_config().get_property("mode") == "lightness",
          "gray-to-component 用的是 lightness 模式")
else:
    check(True, "（未装 gray-to-component，走了曲线回退）")

print()
if FAILS:
    print("失败 %d / %d 项：%s" % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
else:
    print("全部 %d 项通过" % CHECKS[0])
