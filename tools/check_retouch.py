# -*- coding: utf-8 -*-
"""回归：三个磨皮快捷方式（高低频 / 双曲线 / 中性灰）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_retouch.py').read())" --quit

必须跑在 GIMP 的 Python 里。检查：

A. 高低频
   A1 结构：组（穿透）+ 高频 / 低频两层，层序对；
   A2 滤镜：低频一条 gaussian-blur（std-dev = 半径），高频一条 high-pass
      （std-dev = 半径、contrast = 2）；
   A3 32 位浮点 / 8 位：两层合成 = 原图（恒等）；
   A4 低频确实变糊（方差下降），高频确实以 0.5 为中轴；
   A5 改半径（两层同步改）仍然恒等——非破坏；
   A6 隐藏原图层后自己还原；
   A7 带 alpha 的图：组蒙版保住透明度，恒等；
   A8 图层组输入被拒。

B. 双曲线
   B1 结构：两层，正常模式，各带一张黑蒙版；
   B2 滤镜：各一条 gimp:curves（值通道）；
   B3 恒等：浮点 0、8 位 0；
   B4 在提亮蒙版上涂白 → 该处 = 提亮曲线；压暗层未涂 → 不变；
   B5 在压暗蒙版上涂白 → 该处 = 压暗曲线；
   B6 图层组输入被拒。

C. 中性灰
   C1 结构：一层，柔光模式，尺寸与偏移跟原图层一致；
   C2 填充值 = 0.5（8 位图 128）；
   C2b 写完之后调过 update(0,0,W,H)——漏掉这一步，投影不失效，界面上
      这张灰层会显示成一块黑（导出却是对的）；
   C3 恒等：浮点 0、8 位 0；
   C4 涂白 → 变亮，涂黑 → 变暗；
   C5 带 alpha 的图：组蒙版，恒等；
   C6 图层组输入被拒。
"""
import os
import math
import array
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
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
        if os.path.exists(os.path.join(c, "plugin", "frequency-separation",
                                       "frequency-separation.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
FREQ = _load("freq_sep", os.path.join(REPO, "plugin", "frequency-separation",
                                      "frequency-separation.py"))
DODGE = _load("dodge_burn", os.path.join(REPO, "plugin", "dodge-burn",
                                         "dodge-burn.py"))
GREY = _load("neutral_grey", os.path.join(REPO, "plugin", "neutral-grey",
                                          "neutral-grey.py"))

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
# 类皮肤色 + 一层细噪点（高频）+ 缓慢的明暗过渡（低频）。噪点是确定性的，
# 每次跑出来的图完全一样。

W, H = 64, 64


def _photo_pixel(x, y):
    base = (0.62, 0.47, 0.40)
    # 低频：左上亮、右下暗
    tone = 0.10 * math.cos((x / W) * 2.0) + 0.10 * math.sin((y / H) * 1.5)
    # 高频：确定性的“毛孔”
    grain = 0.03 * math.sin(x * 2.3) * math.cos(y * 1.9)
    v = [c + tone + grain for c in base]
    return [min(1.0, max(0.0, c)) for c in v]


def make_image(float_prec=False, alpha_left=None, with_alpha=True,
               w=W, h=H):
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer_type = (Gimp.ImageType.RGBA_IMAGE if with_alpha
                  else Gimp.ImageType.RGB_IMAGE)
    base = Gimp.Layer.new(img, "base", w, h, layer_type, 100.0,
                          Gimp.LayerMode.NORMAL)
    img.insert_layer(base, None, 0)
    if float_prec:
        proc = Gimp.get_pdb().lookup_procedure('gimp-image-convert-precision')
        cfg = proc.create_config()
        cfg.set_property('image', img)
        cfg.set_property('precision', Gimp.Precision.FLOAT_NON_LINEAR)
        proc.run(cfg)
    px = array.array('f')
    for y in range(h):
        for x in range(w):
            r, g, b = _photo_pixel(x, y)
            a = alpha_left if (alpha_left is not None and x < w // 2) else 1.0
            px.extend([r, g, b, a])
    if with_alpha:
        base.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h),
                              "R'G'B'A float", px.tobytes())
    else:
        rgb = array.array('f')
        for i in range(0, len(px), 4):
            rgb.extend(px[i:i + 3])
        base.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h),
                              "R'G'B' float", rgb.tobytes())
    return img, base


def read(layer, w=W, h=H):
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


def rendered(img, layer):
    """只显示这一层后渲染——get_buffer() 拿到的是未过滤镜的原始像素。"""
    states = []
    for l in img.get_layers():
        states.append((l, l.get_visible()))
        if l.is_group():
            for k in l.get_children():
                states.append((k, k.get_visible()))
    for l in img.get_layers():
        if l.is_group():
            l.set_visible(True)
            for k in l.get_children():
                k.set_visible(k is layer)
        else:
            l.set_visible(l is layer)
    d = flatten(img)
    for l, v in states:
        l.set_visible(v)
    return d


def worst_rgb(a, b):
    return max(abs(a[i] - b[i]) for i in range(len(a)) if i % 4 != 3)


def worst_alpha(a, b):
    return max(abs(a[i] - b[i]) for i in range(3, len(a), 4))


def grad_energy(px, w=W, h=H):
    """平均相邻像素差——衡量「有多糊」比方差可靠（方差会被低频影调主导）。"""
    total = 0.0
    n = 0
    for y in range(h - 1):
        for x in range(w - 1):
            i = (y * w + x) * 4
            total += abs(px[i] - px[i + 4]) + abs(px[i] - px[i + w * 4])
            n += 2
    return total / n


def layer_variance(px, step=4):
    vals = [px[i] for i in range(0, len(px), step * 4)]
    mean = sum(vals) / len(vals)
    return sum((v - mean) ** 2 for v in vals) / len(vals)


def paint_mask(mask, rect_px, value):
    """把蒙版某个矩形涂成 value（0…1）。"""
    x, y, w, h = rect_px
    px = array.array('f', [value] * (w * h))
    mask.get_buffer().set(Gegl.Rectangle.new(x, y, w, h), "Y float",
                          px.tobytes())


def mask_mean(mask, w=W, h=H):
    raw = mask.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                "Y float", Gegl.AbyssPolicy.NONE)
    d = array.array('f')
    d.frombytes(bytes(bytearray(raw)))
    return sum(d) / len(d)


def filters_of(layer):
    return [f.get_operation_name() for f in layer.get_filters()][::-1]


def curve_obj(layer, label):
    """取某条 gimp:curves 的曲线对象（SMOOTH 曲线没有采样表，只能读控制点）。

    滤镜名走 _()，随界面语言变，所以 label 可以给多个候选（英文 / 中文）。
    """
    labels = (label,) if isinstance(label, str) else tuple(label)
    f = [f for f in layer.get_filters() if f.get_name() in labels][0]
    return f.get_config().get_property("curve")


def is_smooth(curve):
    return int(curve.get_curve_type()) == int(Gimp.CurveType.SMOOTH)


def points_of(curve):
    return [(round(curve.get_point(i).x, 4), round(curve.get_point(i).y, 4))
            for i in range(curve.get_n_points())]


print("================ A. 高低频 / frequency separation ================")
print("== A1 结构 / structure")
img, base = make_image()
FREQ.separate(img, base, 6.0, True)
group = img.get_layers()[0]
check(group.is_group(), "顶层是图层组")
check(group.get_mode() == Gimp.LayerMode.PASS_THROUGH, "组是穿透混合")
kids = group.get_children()
# 层名走 _()，随界面语言变；英文与中文两套都算通过
FREQ_NAMES = (
    ["2 · High frequency (detail)", "1 · Low frequency (tone)"],
    ["2 · 高频（细节）", "1 · 低频（影调）"],
)
check([k.get_name() for k in kids] in FREQ_NAMES,
      "层序：高频在上、低频在下", [k.get_name() for k in kids])
check(kids[0].get_mode() == Gimp.LayerMode.GRAIN_MERGE, "高频层用颗粒合并")
check(kids[1].get_mode() == Gimp.LayerMode.NORMAL, "低频层用正常混合")
check(sorted(l.get_name() for l in img.get_layers()) in
      (sorted(["Frequency Separation", "base"]),
       sorted(["高低频磨皮", "base"])), "原图与组并列")

print("== A2 滤镜 / filters")
check(filters_of(kids[1])[-1] == "gegl:gaussian-blur", "低频层挂高斯模糊",
      filters_of(kids[1]))
blur_cfg = kids[1].get_filters()[0].get_config()
close(blur_cfg.get_property("std-dev-x"), 6.0, 1e-6, "模糊半径 = 6")
check(filters_of(kids[0])[-1] == "gegl:high-pass", "高频层挂高通",
      filters_of(kids[0]))
hp_cfg = kids[0].get_filters()[0].get_config()
close(hp_cfg.get_property("std-dev"), 6.0, 1e-6, "高通半径 = 6")
close(hp_cfg.get_property("contrast"), 2.0, 1e-6, "高通 contrast = 2")

print("== A2b 曲线类型 / curve type")
for k in kids:
    cur = curve_obj(k, "0 · alpha")
    check(is_smooth(cur), "%s：0 · alpha 是平滑曲线（SMOOTH）" % k.get_name(),
          int(cur.get_curve_type()))
    check(cur.get_n_points() == 3, "%s：三个控制点" % k.get_name(),
          cur.get_n_points())
    check(points_of(cur) == [(0.0, 1.0), (0.502, 1.0), (1.0, 1.0)],
          "%s：三点全在顶（alpha 拉满）" % k.get_name(), points_of(cur))

print("== A3 恒等 / identity")
ref = read(base)
close(worst_rgb(ref, flatten(img)), 0.0, 1.5 / 255.0,
      "32 位浮点：合成 = 原图（≤1.5 码，高通算子的定点偏差）")
img.delete()

img, base = make_image()
FREQ.separate(img, base, 6.0, True)
ref = read(base)
close(worst_rgb(ref, flatten(img)), 0.0, 1.5 / 255.0,
      "8 位：合成 = 原图（≤1.5 码）")

print("== A4 低频真的糊、高频真的在中轴 / layers behave")
group = img.get_layers()[0]
high, low = group.get_children()
lo = rendered(img, low)
hi = rendered(img, high)
check(grad_energy(lo) < grad_energy(ref) * 0.6,
      "低频层相邻像素差明显变小（确实模糊了）",
      "%.6f vs %.6f" % (grad_energy(lo), grad_energy(ref)))
check(0.0 < layer_variance(hi) < 0.02,
      "高频层是低幅度的细节图（有细节但不糊成一片）",
      "%.6f vs 原图 %.6f" % (layer_variance(hi), layer_variance(ref)))
mean_hi = sum(hi[0::4]) / (W * H)
close(mean_hi, 0.5, 0.02, "高频层以中灰 0.5 为中轴")

print("== A5 改半径仍然恒等（非破坏）/ radius is live")
for f in low.get_filters():
    if f.get_operation_name() != "gegl:gaussian-blur":
        continue
    f.get_config().set_property("std-dev-x", 14.0)
    f.get_config().set_property("std-dev-y", 14.0)
    f.update()
for f in high.get_filters():
    if f.get_operation_name() != "gegl:high-pass":
        continue
    f.get_config().set_property("std-dev", 14.0)
    f.update()
close(worst_rgb(ref, flatten(img)), 0.0, 1.5 / 255.0,
      "半径 6 → 14 之后仍然合成 = 原图")

print("== A6 隐藏原图层 / source hidden")
base.set_visible(False)
close(worst_rgb(ref, flatten(img)), 0.0, 1.5 / 255.0,
      "隐藏原图层，两层自己还原")
img.delete()

print("== A7 带 alpha / alpha images")
img, base = make_image(alpha_left=0.5)
FREQ.separate(img, base, 6.0, True)
ref = read(base)
# 恒等要按实际用法看：原图层藏着，两层自己还原。
base.set_visible(False)
got = flatten(img)
close(worst_rgb(ref, got), 0.0, 1.5 / 255.0,
      "半透明图（隐藏原图层）：RGB 恒等")
close(worst_alpha(ref, got), 0.0, 1.0 / 255.0,
      "半透明图（隐藏原图层）：alpha 零误差")
img.delete()

print("== A8 图层组输入被拒 / reject groups")
img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
grp = Gimp.GroupLayer.new(img, "g")
img.insert_layer(grp, None, 0)
try:
    FREQ.separate(img, grp, 6.0, True)
    check(False, "图层组应被拒绝")
except RuntimeError:
    check(True, "图层组被拒绝")
img.delete()

print("================ B. 双曲线 / dodge & burn ================")
print("== B1 结构 / structure")
img, base = make_image()
DODGE.dodge_burn(img, base, 0.12, True)
group = img.get_layers()[0]
check(group.is_group(), "顶层是图层组")
kids = group.get_children()
DODGE_NAMES = (
    ["2 · Burn (black mask)", "1 · Dodge (black mask)"],
    ["2 · 压暗（黑蒙版）", "1 · 提亮（黑蒙版）"],
)
check([k.get_name() for k in kids] in DODGE_NAMES,
      "层序：压暗在上、提亮在下", [k.get_name() for k in kids])
check(all(k.get_mode() == Gimp.LayerMode.NORMAL for k in kids), "两层都是正常模式")
check(all(k.get_mask() is not None for k in kids), "两层各带一张蒙版")
close(mask_mean(kids[0].get_mask()), 0.0, 0.5 / 255.0, "压暗层蒙版全黑")
close(mask_mean(kids[1].get_mask()), 0.0, 0.5 / 255.0, "提亮层蒙版全黑")

print("== B2 滤镜 / filters")
check(filters_of(kids[1])[-1] == "gimp:curves", "提亮层挂曲线", filters_of(kids[1]))
check(filters_of(kids[0])[-1] == "gimp:curves", "压暗层挂曲线", filters_of(kids[0]))
chan = kids[1].get_filters()[0].get_config().get_property("channel")
check(chan == Gimp.HistogramChannel.VALUE, "曲线挂在值通道", chan)

print("== B2b 曲线类型 / curve type")
for k, label in ((kids[1], ("1 · Dodge curve", "1 · 提亮曲线")),
                 (kids[0], ("2 · Burn curve", "2 · 压暗曲线"))):
    cur = curve_obj(k, label)
    check(is_smooth(cur), "%s 是平滑曲线（SMOOTH）" % (label[0] if isinstance(label, tuple) else label),
          int(cur.get_curve_type()))
    check(cur.get_n_points() == 5, "%s：五个控制点" % (label[0] if isinstance(label, tuple) else label), cur.get_n_points())
    pts = points_of(cur)
    check(pts[0] == (0.0, 0.0) and pts[-1] == (1.0, 1.0),
          "%s：两端不动（0,0）(1,1)" % (label[0] if isinstance(label, tuple) else label), pts)
    if k is kids[1]:
        check(pts[2][1] > 0.5, "提亮曲线中段高于 0.5", pts[2])
    else:
        check(pts[2][1] < 0.5, "压暗曲线中段低于 0.5", pts[2])
    alpha = curve_obj(k, "0 · alpha")
    check(is_smooth(alpha) and alpha.get_n_points() == 3,
          "%s 的 0 · alpha 也是平滑三点" % k.get_name())

print("== B3 恒等 / identity")
ref = read(base)
close(worst_rgb(ref, flatten(img)), 0.0, 0.5 / 255.0, "32 位浮点：恒等（≤0.5 码）")
img.delete()

img, base = make_image()
DODGE.dodge_burn(img, base, 0.12, True)
ref = read(base)
close(worst_rgb(ref, flatten(img)), 0.0, 0.5 / 255.0, "8 位：恒等（≤0.5 码）")

print("== B4/B5 涂蒙版生效 / painting the masks")
group = img.get_layers()[0]
dark, light = group.get_children()
# 左上 32×32 涂在提亮蒙版上
paint_mask(light.get_mask(), (0, 0, 32, 32), 1.0)
got = flatten(img)
i = (2 * W + 2) * 4
want = [min(1.0, max(0.0, ref[i + k] + 0.12 * 4.0
                        * ref[i + k] * (1.0 - ref[i + k]))) for k in range(3)]
check(all(abs(got[i + k] - want[k]) <= 1.5 / 255.0 for k in range(3)),
      "提亮蒙版涂白处 = 提亮曲线（≤1.5 码）",
      "%s vs %s" % ([round(got[i + k], 4) for k in range(3)],
                    [round(w, 4) for w in want]))
check(abs(got[i] - ref[i]) > 5.0 / 255.0, "提亮处确实变亮了",
      "%.4f -> %.4f" % (ref[i], got[i]))
j = (2 * W + 60) * 4          # 右侧未涂，应保持原样
close(abs(got[j] - ref[j]), 0.0, 1.5 / 255.0, "未涂的地方不动")

paint_mask(light.get_mask(), (0, 0, 32, 32), 0.0)   # 先擦掉提亮，单测压暗
paint_mask(dark.get_mask(), (0, 0, 32, 32), 1.0)
got = flatten(img)
want_dark = [min(1.0, max(0.0, ref[i + k] - 0.12 * 4.0
                             * ref[i + k] * (1.0 - ref[i + k]))) for k in range(3)]
check(all(abs(got[i + k] - want_dark[k]) <= 1.5 / 255.0 for k in range(3)),
      "压暗蒙版涂白处 = 压暗曲线（≤1.5 码）")
check(got[i] < ref[i] - 5.0 / 255.0, "压暗处确实变暗",
      "%.4f -> %.4f" % (ref[i], got[i]))
img.delete()

print("== B6 图层组输入被拒 / reject groups")
img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
grp = Gimp.GroupLayer.new(img, "g")
img.insert_layer(grp, None, 0)
try:
    DODGE.dodge_burn(img, grp, 0.12, True)
    check(False, "图层组应被拒绝")
except RuntimeError:
    check(True, "图层组被拒绝")
img.delete()

print("================ C. 中性灰 / neutral grey ================")
print("== C1/C2 结构与填充 / structure & fill")
img, base = make_image()
GREY.neutral_grey(img, base, True)
group = img.get_layers()[0]
check(group.is_group(), "顶层是图层组")
kids = group.get_children()
check(len(kids) == 1, "组里只有一层", [k.get_name() for k in kids])
grey = kids[0]
check(grey.get_mode() == Gimp.LayerMode.SOFTLIGHT, "灰层用柔光")
check((grey.get_width(), grey.get_height()) == (W, H), "尺寸跟原图层一致",
      (grey.get_width(), grey.get_height()))
check(grey.get_offsets()[1:] == base.get_offsets()[1:], "偏移跟原图层一致")
gv = read(grey)
close(gv[0], 0.5, 0.6 / 255.0, "填充值 = 0.5 编码灰（8 位图 128）")
img.delete()

print("== C2b 写完通知核心重绘 / invalidate the projection")
img, base = make_image()
calls = []
_orig_update = Gimp.Drawable.update


def _spy_update(self, x, y, w, h):
    calls.append((x, y, w, h))
    return _orig_update(self, x, y, w, h)


Gimp.Drawable.update = _spy_update
try:
    GREY.neutral_grey(img, base, True)
finally:
    Gimp.Drawable.update = _orig_update
# 只写私有 buffer 不 update，投影不失效：界面上这张灰层是黑的，导出却是
# 对的。必须看到一次覆盖整层的 update。
check((0, 0, W, H) in calls,
      "写灰层后 update(0, 0, W, H)（漏了界面上是黑块）", calls)

print("== C3 恒等 / identity")
ref = read(base)
close(worst_rgb(ref, flatten(img)), 0.0, 0.5 / 255.0, "32 位浮点：恒等（≤0.5 码）")
img.delete()

img, base = make_image()
GREY.neutral_grey(img, base, True)
ref = read(base)
close(worst_rgb(ref, flatten(img)), 0.0, 0.5 / 255.0, "8 位：恒等（≤0.5 码）")

print("== C4 涂白变亮、涂黑变暗 / painting the grey layer")
grey = img.get_layers()[0].get_children()[0]
rect = Gegl.Rectangle.new(0, 0, 16, 16)
px = array.array('f', [1.0, 1.0, 1.0, 1.0] * (16 * 16))
grey.get_buffer().set(rect, "R'G'B'A float", px.tobytes())
got = flatten(img)
i = (2 * W + 2) * 4
check(got[i] > ref[i] + 1.0 / 255.0, "涂白处变亮",
      "%.5f -> %.5f" % (ref[i], got[i]))
j = (40 * W + 40) * 4
close(abs(got[j] - ref[j]), 0.0, 1.0 / 255.0, "没涂的地方不动")

px = array.array('f', [0.0, 0.0, 0.0, 1.0] * (16 * 16))
grey.get_buffer().set(rect, "R'G'B'A float", px.tobytes())
got = flatten(img)
check(got[i] < ref[i] - 1.0 / 255.0, "涂黑处变暗",
      "%.5f -> %.5f" % (ref[i], got[i]))
img.delete()

print("== C5 带 alpha / alpha images")
img, base = make_image(alpha_left=0.5)
GREY.neutral_grey(img, base, True)
ref = read(base)
got = flatten(img)
close(worst_rgb(ref, got), 0.0, 1.0 / 255.0, "半透明图：RGB 恒等")
close(worst_alpha(ref, got), 0.0, 1.0 / 255.0, "半透明图：alpha 零误差")
img.delete()

print("== C6 图层组输入被拒 / reject groups")
img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
grp = Gimp.GroupLayer.new(img, "g")
img.insert_layer(grp, None, 0)
try:
    GREY.neutral_grey(img, grp, True)
    check(False, "图层组应被拒绝")
except RuntimeError:
    check(True, "图层组被拒绝")
img.delete()

# 无 alpha 的图（绝大多数照片）走的是另一支：灰层是 RGB_IMAGE，写的是
# "R'G'B' float"。这一支以前只改 get_buffer()，投影不失效，界面上直接是
# 一块黑——必须走 shadow buffer + merge_shadow。C1/C3 全用的带 alpha 的图，
# 一直没盖住这里。
print("== C7 无 alpha 的图 / images without alpha")
for fp in (False, True):
    img, base = make_image(float_prec=fp, with_alpha=False)
    GREY.neutral_grey(img, base, True)
    grey = img.get_layers()[0].get_children()[0]
    check(not grey.has_alpha(), "灰层无 alpha" , grey.has_alpha())
    close(read(grey)[0], 0.5, 1.0 / 255.0,
          "%s：灰层填 0.5" % ("浮点" if fp else "8 位"))
    ref = read(base)
    close(worst_rgb(ref, flatten(img)), 0.0, 0.5 / 255.0,
          "%s：无 alpha 图恒等（≤0.5 码）" % ("浮点" if fp else "8 位"))
    img.delete()

print("== C8 走 shadow buffer / merge_shadow")
img, base = make_image(with_alpha=False)
merged = []
_orig_ms = Gimp.Drawable.merge_shadow


def _spy_ms(self, undo):
    merged.append(bool(undo))
    return _orig_ms(self, undo)


Gimp.Drawable.merge_shadow = _spy_ms
try:
    GREY.neutral_grey(img, base, True)
finally:
    Gimp.Drawable.merge_shadow = _orig_ms
# 直接写 get_buffer() 不走 shadow：merge_shadow 一次都不会被调用，而投影
# 缓存却停在新图层的空内容上（黑块）。
check(merged == [True], "填灰层走 merge_shadow(True)", merged)
img.delete()

print("")
if FAILS:
    print("失败 %d 项 / %d checks failed: %s"
          % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
else:
    print("全部通过：%d 项检查 / all %d checks passed" % (CHECKS[0], CHECKS[0]))
