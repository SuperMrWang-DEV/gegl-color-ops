# -*- coding: utf-8 -*-
"""回归：观察层（六种，各一个菜单项，零参数直接执行）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_observe.py').read())" --quit
"""
import os
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
        if os.path.exists(os.path.join(c, "plugin", "observe", "observe.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
OBS = _load("observe", os.path.join(REPO, "plugin", "observe", "observe.py"))

FAILS = []
CHECKS = [0]


def check(cond, label, detail=""):
    CHECKS[0] += 1
    if cond:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILS.append(label)


W = H = 32


def make_image(with_alpha=True):
    """左暗右亮的渐变，中间压一块偏红的斑（观察层就是要把这种地方挑出来）。"""
    img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    lt = Gimp.ImageType.RGBA_IMAGE if with_alpha else Gimp.ImageType.RGB_IMAGE
    lay = Gimp.Layer.new(img, "base", W, H, lt, 100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    px = array.array('f')
    for y in range(H):
        for x in range(W):
            v = 0.15 + 0.70 * x / float(W - 1)
            r, g, b = v, v * 0.85, v * 0.70
            if 8 <= x < 20 and 8 <= y < 20:
                r, g, b = 0.88, 0.36, 0.30
            px.extend([r, g, b, 1.0])
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, W, H),
                         "R'G'B'A float", px.tobytes())
    return img, lay


def read(drawable):
    raw = drawable.get_buffer().get(Gegl.Rectangle.new(0, 0, W, H), 1.0,
                                    "R'G'B'A float", Gegl.AbyssPolicy.NONE)
    d = array.array('f')
    d.frombytes(bytes(bytearray(raw)))
    return d


def render_only(img, keep):
    """只显示 keep 这一层再合成——观察层的滤镜效果只在这里面才算得出来。"""
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
                k.set_visible(k is keep)
        else:
            l.set_visible(l is keep)
    di = img.duplicate()
    merged = di.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    got = read(merged)
    di.delete()
    for l, v in states:
        l.set_visible(v)
    return got


def px(d, x, y, c=0):
    return d[(y * W + x) * 4 + c]


def lum(d, x, y):
    i = (y * W + x) * 4
    return (d[i] + d[i + 1] + d[i + 2]) / 3.0


# ---- [1] 六支 procedure 都注册上 / all six registered ----------------------
print("== [1] 菜单项注册 / procedures")
pdb = Gimp.get_pdb()
missing = []
for key in ("grey", "steep", "wave", "saturation", "threshold", "posterize"):
    if pdb.lookup_procedure("lb-plugin-observe-" + key) is None:
        missing.append(key)
check(not missing, "六个 procedure 都注册了", missing)


# ---- [2] 公共行为：多一层、名字、位置、原层不动 ----------------------------
def run_one(key):
    _k, _label, lname, build, _en, _zh = OBS.BY_KEY[key]
    img, base = make_image()
    ref = read(base)
    lay = OBS.make_observer(img, base, build, OBS.observe_name(lname))
    layers = img.get_layers()
    check(len(layers) == 2, "[%s] 只多一层（副本）" % key,
          [l.get_name() for l in layers])
    check(layers[0].get_id() == lay.get_id(), "[%s] 观察层在最上面" % key)
    check(lay.get_name() == OBS.observe_name(lname), "[%s] 图层名带前缀" % key,
          lay.get_name())
    check(lay.get_mode() == Gimp.LayerMode.NORMAL, "[%s] 普通模式" % key)
    check((lay.get_width(), lay.get_height()) == (W, H), "[%s] 尺寸一致" % key)
    # 原图层必须一个字节都没动
    check(list(read(base)) == list(ref), "[%s] 原图层像素未变" % key)
    got = render_only(img, lay)
    return img, base, lay, got


print("== [2] 黑白 / desaturate")
img, base, lay, got = run_one("grey")
ops = [f.get_operation_name() for f in lay.get_filters()]
check(ops == [OBS.DESATURATE_OP], "挂了一条 gimp:desaturate", ops)
spread = max(abs(got[(y * W + x) * 4] - got[(y * W + x) * 4 + 1])
             for y in range(0, H, 4) for x in range(0, W, 4))
check(spread < 1e-4, "输出是三通道相等的灰", spread)
# 红斑处（原本 R 远大于 G）去色后应当明显暗于旁边同位置的渐变
check(lum(got, 12, 12) < lum(got, 24, 12) - 0.05, "色斑在明度上与亮部区分开",
      "%.3f vs %.3f" % (lum(got, 12, 12), lum(got, 24, 12)))
img.delete()

print("== [3] 陡峭曲线 / steep")
img, base, lay, got = run_one("steep")
ops = [f.get_operation_name() for f in lay.get_filters()]
check(ops == [OBS.CURVES_OP], "挂了一条 gimp:curves", ops)
st = read(base)
# 暗部更暗、亮部更亮：对比度是拉大的
d_dark = lum(got, 2, 2) - lum(st, 2, 2)
d_light = lum(got, 30, 2) - lum(st, 30, 2)
check(d_dark < -0.005, "暗部被压暗", "%.4f" % d_dark)
check(d_light > 0.005, "亮部被提亮", "%.4f" % d_light)
img.delete()

print("== [4] 波浪曲线 / wave")
img, base, lay, got = run_one("wave")
ops = [f.get_operation_name() for f in lay.get_filters()]
# get_filters() 是栈顶在前（后挂的排前面），所以只比集合，不比顺序
check(sorted(ops) == sorted([OBS.DESATURATE_OP, OBS.CURVES_OP]),
      "去色 + 曲线两条都挂上", ops)
spread = max(abs(got[(y * W + x) * 4] - got[(y * W + x) * 4 + 2])
             for y in range(0, H, 4) for x in range(0, W, 4))
check(spread < 1e-4, "等值线是灰的（不带通道色相）", spread)
# 波浪曲线把中间调反复翻折：同一列的灰阶不再是单调递增
seq = [lum(got, x, 2) for x in range(W)]
steps = [seq[i + 1] - seq[i] for i in range(len(seq) - 1)]
flip = sum(1 for i in range(len(steps) - 1)
           if steps[i] * steps[i + 1] < -1e-7)
check(flip >= 2, "渐变被翻折（出现反向台阶）", "flips=%d" % flip)
img.delete()

print("== [5] 饱和度 / saturation")
img, base, lay, got = run_one("saturation")
ops = [f.get_operation_name() for f in lay.get_filters()]
check(ops == [OBS.HS_OP], "挂了一条 gimp:hue-saturation", ops)
i = (12 * W + 12) * 4
spread = max(got[i:i + 3]) - min(got[i:i + 3])
check(spread > 0.30, "色斑的通道差被拉大", "%.3f" % spread)
img.delete()

print("== [6] 阈值 / threshold")
img, base, lay, got = run_one("threshold")
ops = [f.get_operation_name() for f in lay.get_filters()]
check(sorted(ops) == sorted([OBS.DESATURATE_OP, OBS.CURVES_OP]),
      "先去色 + 曲线硬阶梯（不是 gimp:threshold）", ops)
vals = set()
for y in range(0, H, 2):
    for x in range(0, W, 2):
        vals.add(round(lum(got, x, y), 3))
# 恰好等于切点的像素会落在阶梯上，8 位量化后能看到一个中间值（128 那一档）。
# 这是切点本身的归属问题，不是没二值化——留一个的余量。
odd = [v for v in vals if v not in (0.0, 1.0)]
check(len(odd) <= 1, "只输出两种值（至多一个切点像素）", sorted(vals)[:6])
check(0.0 in vals and 1.0 in vals, "黑白两边都有（不是整块黑或整块白）",
      sorted(vals)[:6])
img.delete()

print("== [6b] 偏暗的图也切得开 / dark image")
# 整张都在 0.05…0.45 之间（夜景、深色截图、欠曝）。阈值要是死在 0.5，这一层
# 就是一块纯黑，什么都看不见——中位数自适应才切得开。
img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
dark = Gimp.Layer.new(img, "dark", W, H, Gimp.ImageType.RGBA_IMAGE, 100.0,
                      Gimp.LayerMode.NORMAL)
img.insert_layer(dark, None, 0)
px = array.array('f')
for y in range(H):
    for x in range(W):
        v = 0.05 + 0.40 * x / float(W - 1)
        px.extend([v, v, v, 1.0])
dark.get_buffer().set(Gegl.Rectangle.new(0, 0, W, H),
                      "R'G'B'A float", px.tobytes())
lay = OBS.make_observer(img, dark, OBS.observe_threshold,
                        OBS.observe_name("Threshold"))
got = render_only(img, lay)
vals = set(round(lum(got, x, 2), 3) for x in range(0, W, 2))
odd = [v for v in vals if v not in (0.0, 1.0)]
check(len(odd) <= 1 and 0.0 in vals and 1.0 in vals,
      "暗图照样黑白各一半", sorted(vals))
img.delete()

print("== [7] 海报化 / posterize")
img, base, lay, got = run_one("posterize")
ops = [f.get_operation_name() for f in lay.get_filters()]
check(ops == [OBS.POSTERIZE_OP], "挂了一条 gimp:posterize", ops)
vals = set()
for y in range(0, H, 2):
    for x in range(0, W, 2):
        i = (y * W + x) * 4
        # 逐通道看：海报化是每个通道各自压级，取三通道平均会组合出更多的值
        # （0 / 1/3 / 2/3 / 1 平均后能出现 1/9 这种），不等于级数没生效。
        for c in range(3):
            vals.add(round(got[i + c], 3))
check(len(vals) <= 4, "每个通道的色阶数不超过 4", sorted(vals))
img.delete()

print("== [8] 无 alpha 的图 / no-alpha")
img, base = make_image(with_alpha=False)
lay = OBS.make_observer(img, base, OBS.observe_grey,
                        OBS.observe_name("Black & White"))
check(not lay.has_alpha(), "副本跟随原图层没有 alpha", lay.has_alpha())
got = render_only(img, lay)
check(abs(got[(4 * W + 4) * 4] - got[(4 * W + 4) * 4 + 1]) < 1e-4,
      "无 alpha 图也正确去色")
img.delete()

print("== [9] 图层组输入被拒 / reject groups")
img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
grp = Gimp.GroupLayer.new(img, "g")
img.insert_layer(grp, None, 0)
try:
    OBS.make_observer(img, grp, OBS.observe_grey, "x")
    check(False, "图层组应被拒绝")
except RuntimeError:
    check(True, "图层组被拒绝")
img.delete()

print("")
if FAILS:
    print("失败 %d 项 / %d checks failed: %s"
          % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
else:
    print("全部通过：%d 项检查 / all %d checks passed" % (CHECKS[0], CHECKS[0]))
