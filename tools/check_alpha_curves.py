# -*- coding: utf-8 -*-
"""回归：alpha-curves 插件（通道 → Alpha，再挂一条 alpha 曲线）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_alpha_curves.py').read())" --quit

必须跑在 GIMP 的 Python 里。检查这些事：

1. 图层上正好两条滤镜，名字与顺序（曲线在上、range 在下）；
2. 曲线滤镜的通道是 ALPHA、trc 是 NON_LINEAR；
3. range 滤镜的四个滑块是 0 / 255 / 255 / 255（斜坡拉满 = 直通）；
4. identity：alpha 正好等于所选通道值，RGB 一个码都不动；
5. band：梯形对得上（0 → 0、4% → 0.5、50% → 1、100% → 0）；
6. soft：单调、中段为 1；
7. 原图半透明时是「乘」而不是「替换」：alpha = 0.5 × 通道值；
8. 与 lb:channel-range-to-alpha（同样的梯形）逐像素一致；
9. channel = red 时 alpha 真的跟红通道走；
10. channel = alpha 时只挂一条曲线，identity 不改任何东西；
11. 无 alpha 的图层会自动加 alpha；图层组输入被拒；8 位图误差 ≤ 1 码。
"""
import array
import importlib.util
import os

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl

CHECKS = [0]
FAILS = []


def check(cond, label, detail=None):
    CHECKS[0] += 1
    if cond:
        print("  ok   %s" % label)
    else:
        FAILS.append(label)
        print("  FAIL %s%s" % (label, ("  (%s)" % detail) if detail else ""))


def close(got, want, tol, label):
    """以「码」为单位比较（1 码 = 1/255）。"""
    diff = abs(got - want) * 255.0
    check(diff <= tol, label, "got %.5f want %.5f diff %.5f 码"
          % (got, want, diff))


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
        if os.path.exists(os.path.join(c, "plugin", "alpha-curves",
                                       "alpha-curves.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
AC = _load("alpha_curves", os.path.join(REPO, "plugin", "alpha-curves",
                                        "alpha-curves.py"))

W = 33


def make_image(alpha0=1.0, rgb=None, with_alpha=True, float_prec=True):
    """33×1 的梯度图：默认 RGB 都是 x，alpha 固定。"""
    img = Gimp.Image.new(W, 1, Gimp.ImageBaseType.RGB)
    if float_prec:
        proc = Gimp.get_pdb().lookup_procedure('gimp-image-convert-precision')
        cfg = proc.create_config()
        cfg.set_property('image', img)
        cfg.set_property('precision', Gimp.Precision.FLOAT_NON_LINEAR)
        proc.run(cfg)
    itype = Gimp.ImageType.RGBA_IMAGE if with_alpha else Gimp.ImageType.RGB_IMAGE
    lay = Gimp.Layer.new(img, "t", W, 1, itype, 100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    px = array.array('f', bytes(W * 4))
    for i in range(W):
        x = i / float(W - 1)
        r, g, b = (x, x, x) if rgb is None else rgb(x)
        px[i * 4:i * 4 + 4] = array.array('f', [r, g, b, alpha0])
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, W, 1), "R'G'B'A float",
                         px.tobytes())
    return img, lay


def flatten(lay):
    """读投影（滤镜之后）的 RGBA。"""
    img = lay.get_image()
    di = img.duplicate()
    merged = di.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    raw = merged.get_buffer().get(Gegl.Rectangle.new(0, 0, W, 1), 1.0,
                                  "R'G'B'A float", Gegl.AbyssPolicy.NONE)
    out = array.array('f')
    out.frombytes(bytes(bytearray(raw)))
    di.delete()
    return out


def x_at(i):
    return i / float(W - 1)


def alpha_at(px, i):
    return px[i * 4 + 3]


print("\n== 1. 结构 ==")
img, lay = make_image()
AC.alpha_curves(img, lay, 'gray', 'identity')
names = [f.get_name() for f in lay.get_filters()]
check(len(names) == 2, "两条滤镜", names)
check(names[0].endswith("Alpha 曲线"), "第一条是 Alpha 曲线", names)
check(names[1].endswith("通道 → Alpha"), "第二条是通道 → Alpha", names)

curve_filt = lay.get_filters()[0]
range_filt = lay.get_filters()[1]
cfg = curve_filt.get_config()
check(cfg.get_property('channel') == Gimp.HistogramChannel.ALPHA,
      "曲线的通道 = ALPHA", cfg.get_property('channel'))
check(cfg.get_property('trc') == Gimp.TRCType.NON_LINEAR,
      "曲线的 trc = NON_LINEAR", cfg.get_property('trc'))
rcfg = range_filt.get_config()
sliders = [rcfg.get_property(k) for k in ('l1', 'l2', 'r1', 'r2')]
check(sliders == [0.0, 255.0, 255.0, 255.0],
      "range 四个滑块 0/255/255/255", sliders)

print("\n== 2. identity：alpha 就是通道值 ==")
got = flatten(lay)
for i in (0, 8, 16, 24, 32):
    close(alpha_at(got, i), x_at(i), 0.01,
          "alpha(%.3f) = %.3f" % (x_at(i), x_at(i)))
rgb_drift = max(abs(got[i * 4 + c] - i / float(W - 1))
                for i in range(W) for c in range(3))
close(rgb_drift, 0.0, 0.01, "RGB 一个码都没动")
img.delete()

print("\n== 3. band：梯形形状 ==")
img, lay = make_image()
AC.alpha_curves(img, lay, 'gray', 'band')
got = flatten(lay)
close(alpha_at(got, 0), 0.0, 0.5, "band：最暗处 = 0")
close(alpha_at(got, 1), x_at(1) / 0.08, 1.0, "band：x=%.3f 在 8%% 斜坡上" % x_at(1))
close(alpha_at(got, 16), 1.0, 0.01, "band：中间 = 1")
close(alpha_at(got, 31), 1.0 - (x_at(31) - 0.92) / 0.08, 1.0,
      "band：x=%.3f 在 92%% 斜坡上" % x_at(31))
close(alpha_at(got, 32), 0.0, 0.5, "band：最亮处 = 0")
img.delete()

print("\n== 4. soft：单调 + 中段为 1 ==")
img, lay = make_image()
AC.alpha_curves(img, lay, 'gray', 'soft')
got = flatten(lay)
vals = [alpha_at(got, i * 4) for i in range(9)]
check(all(vals[i] <= vals[i + 1] + 1e-4 for i in range(8)), "soft 单调不减", vals)
close(vals[0], 0.0, 0.5, "soft：最暗处 = 0")
close(vals[8], 1.0, 0.01, "soft：最亮处 = 1")
close(vals[4], 0.5, 1.0, "soft：中点为 0.5")
img.delete()

print("\n== 5. 半透明原图：乘，不是替换 ==")
img, lay = make_image(alpha0=0.5)
AC.alpha_curves(img, lay, 'gray', 'identity')
got = flatten(lay)
for i in (8, 16, 32):
    close(alpha_at(got, i), 0.5 * x_at(i), 0.02,
          "alpha(%.3f) = 0.5 × %.3f" % (x_at(i), x_at(i)))
img.delete()

print("\n== 6. 与 lb:channel-range-to-alpha 对得上 ==")
img, lay = make_image()
AC.alpha_curves(img, lay, 'gray', 'band')
got = flatten(lay)
img2, lay2 = make_image()
filt = Gimp.DrawableFilter.new(lay2, 'lb:channel-range-to-alpha', 'ref')
rc = filt.get_config()
rc.set_property('channel', 'gray')
rc.set_property('l1', 0.0)
rc.set_property('l2', 0.08 * 255.0)
rc.set_property('r1', 0.92 * 255.0)
rc.set_property('r2', 255.0)
filt.update()
lay2.append_filter(filt)
ref = flatten(lay2)
diff = max(abs(got[i * 4 + 3] - ref[i * 4 + 3]) for i in range(W))
close(diff, 0.0, 0.05, "曲线梯形 = 算子梯形")
img.delete()
img2.delete()

print("\n== 7. channel = red 时跟红通道走 ==")
img, lay = make_image(rgb=lambda x: (x, 0.2, 0.8))
AC.alpha_curves(img, lay, 'red', 'identity')
got = flatten(lay)
close(alpha_at(got, 10), x_at(10), 0.02,
      "alpha 跟 R 走（%.3f）" % x_at(10))
close(alpha_at(got, 29), x_at(29), 0.02,
      "alpha 跟 R 走（%.3f）" % x_at(29))
img.delete()

print("\n== 8. channel = alpha：只挂一条曲线 ==")
img, lay = make_image()
AC.alpha_curves(img, lay, 'alpha', 'auto')
names = [f.get_name() for f in lay.get_filters()]
check(len(names) == 1, "只挂一条滤镜", names)
got = flatten(lay)
close(alpha_at(got, 12), 1.0, 0.01, "identity：alpha 原样（原图不透明）")
img.delete()

print("\n== 9. 边界 ==")
img, lay = make_image(with_alpha=False)
AC.alpha_curves(img, lay, 'gray', 'identity')
check(lay.has_alpha(), "无 alpha 的图层自动加 alpha")
img.delete()

imgg = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
grp = Gimp.GroupLayer.new(imgg, "g")
imgg.insert_layer(grp, None, 0)
try:
    AC.alpha_curves(imgg, grp, 'gray', 'identity')
    check(False, "图层组输入被拒绝")
except RuntimeError:
    check(True, "图层组输入被拒绝")

img, lay = make_image(float_prec=False)
AC.alpha_curves(img, lay, 'gray', 'identity')
got = flatten(lay)
worst = max(abs(alpha_at(got, i * 4) - x_at(i * 4)) for i in range(9)) * 255.0
check(worst <= 1.0, "8 位图 identity ≤ 1 码", "%.3f 码" % worst)
img.delete()

print()
if FAILS:
    print("失败 %d / %d 项：%s" % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
else:
    print("全部 %d 项通过 / %d checks passed" % (CHECKS[0], CHECKS[0]))
