# -*- coding: utf-8 -*-
"""在真 GIMP 里跑「把滤镜栈烘成 3D LUT」的回归（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_export_lut_gimp.py').read())" --quit

验的是接线，不是数学：
· 单位图的布局对不对（宽 size²、高 size、红最快）
· 恒等栈烘出来是不是恒等（最容易错、又最容易被忽略的一条）
· LUT 采样与「真的把颜色过一遍滤镜」差多少（三线性插值的固有误差）
· .cube 的表头、条目数、小数位、顺序
· 空间算子（USM / 变形 / 降噪）会不会被点名
· 烘焙过程有没有偷偷改原图、有没有把 8bit 量化带进结果
· 拿 lb:color-lookup 把 .cube 贴回图里，与直接过滤镜差几个码
"""

import os
import random
import struct
import sys
import tempfile

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
for cand in (ROOT, os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))):
    if os.path.exists(os.path.join(cand, "plugin", "_shared", "lut_bake.py")):
        ROOT = cand
        break
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import lut_bake as LB                                            # noqa: E402

PASS = 0
FAIL = []
SECTION = ""
TMP = tempfile.mkdtemp(prefix="lb_lut_")


def section(name):
    global SECTION
    SECTION = name
    print("\n" + name)


def ok(cond, what, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok   %s" % what)
    else:
        FAIL.append("[%s] %s %s" % (SECTION, what, detail))
        print("  FAIL %s %s" % (what, detail))


def near(a, b, tol, what):
    ok(abs(a - b) <= tol, what, "(%.6f vs %.6f)" % (a, b))


# --------------------------------------------------------------- 造图 / 过栈

def new_image(w=64, h=64, colors=None):
    img = Gimp.Image.new_with_precision(w, h, Gimp.ImageBaseType.RGB,
                                        Gimp.Precision.U8_PERCEPTUAL)
    lay = Gimp.Layer.new(img, "t", w, h, Gimp.ImageType.RGBA_IMAGE, 100.0,
                         Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    px = []
    if colors:
        for r, g, b in colors:
            px.extend((r, g, b, 1.0))
    else:
        for y in range(h):
            for x in range(w):
                px.extend((x / (w - 1.0), y / (h - 1.0),
                           ((x + y) % 16) / 15.0, 1.0))
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A float",
                         struct.pack('<%df' % len(px), *px))
    img.set_selected_layers([lay])
    return img, lay


def add_filters(layer, ops):
    for op, props in ops:
        f = Gimp.DrawableFilter.new(layer, op, op)
        cfg = f.get_config()
        for k, v in props.items():
            try:
                cfg.set_property(k, v)
            except Exception as exc:
                raise RuntimeError("设不上 %s.%s: %s" % (op, k, exc))
        layer.append_filter(f)


def read_rgb(layer, w, h):
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                 "R'G'B'A float", Gegl.AbyssPolicy.NONE)
    px = struct.unpack('<%df' % (w * h * 4), raw)
    return [(px[i * 4], px[i * 4 + 1], px[i * 4 + 2]) for i in range(w * h)]


def apply_stack(colors, ops):
    """把 colors 直接过一遍 ops，当 LUT 的参考答案。

    merge 要从栈底开始（get_filters() 给的是栈顶在前），否则整条链跑反。
    """
    img, lay = new_image(len(colors), 1, colors)
    add_filters(lay, ops)
    for f in reversed(list(lay.get_filters())):
        lay.merge_filter(f)
    out = read_rgb(lay, len(colors), 1)
    img.delete()
    return out


def lut_sample(values, size, rgb):
    """三线性采样，与 lb:color-lookup 的默认插值一致。"""
    def axis(v):
        t = max(0.0, min(1.0, v)) * (size - 1)
        i = int(t)
        if i >= size - 1:
            return size - 2, 1.0
        return i, t - i
    ri, rf = axis(rgb[0])
    gi, gf = axis(rgb[1])
    bi, bf = axis(rgb[2])
    out = [0.0, 0.0, 0.0]
    for db in (0, 1):
        wb = bf if db else 1 - bf
        for dg in (0, 1):
            wg = gf if dg else 1 - gf
            for dr in (0, 1):
                wr = rf if dr else 1 - rf
                idx = ((bi + db) * size + (gi + dg)) * size + (ri + dr)
                c = values[idx]
                w = wr * wg * wb
                for k in range(3):
                    out[k] += c[k] * w
    return out


# 三滤镜串联：亮度对比度 → 色相饱和度 → Lab 色阶（L 输出白点压低）
OPS3 = [("gimp:brightness-contrast", {"brightness": 0.08, "contrast": 0.12}),
        ("gimp:hue-saturation", {"hue": 25.0, "saturation": 0.15,
                                 "lightness": 0.05}),
        ("lb:lab-levels", {"L-out-white": 88.0})]

# --------------------------------------------------------------------- 用例

section("1. 单位图布局")
W, H = LB.lattice_span(3)
ok((W, H) == (9, 3), "宽 size²、高 size", (W, H))
vals = LB.lattice_values(3)
ok(len(vals) == 3 ** 3 * 4, "节点数 27×4", len(vals))
near(vals[0], 0.0, 1e-9, "首节点 r=0")
near(vals[4], 0.5, 1e-9, "第二个节点 r 进一格（红最快）")
near(vals[4 * 3], 0.0, 1e-9, "第 4 个节点 r 回绕")
near(vals[4 * 3 + 1], 0.5, 1e-9, "第 4 个节点 g 进一格")
near(vals[4 * 26 + 2], 1.0, 1e-9, "末节点 b=1")
ok(all(abs(vals[i * 4 + 3] - 1.0) < 1e-9 for i in range(27)), "alpha 全 1")

section("2. 恒等栈烘出来必须还是恒等")
img, lay = new_image()
add_filters(lay, [("gimp:brightness-contrast",
                   {"brightness": 0.0, "contrast": 0.0})])
v, sp = LB.bake(img, lay, 9)
# 8bit 图层里格点本身被量化到 1/255，所以恒等也只能到 1 码以内
near(LB.identity_error(v, 9), 0.0, 1.0 / 255, "恒等栈最大误差 ≤ 1 码")
ok(sp == [], "没被误判成空间算子", sp)

section("3. 单滤镜：九个格点逐个对账")
img, lay = new_image()
add_filters(lay, [("gimp:brightness-contrast",
                   {"brightness": 0.2, "contrast": 0.0})])
v, _ = LB.bake(img, lay, 3)
grid = [(r / 2.0, g / 2.0, b / 2.0)
        for b in range(3) for g in range(3) for r in range(3)]
want = apply_stack(grid, [("gimp:brightness-contrast",
                           {"brightness": 0.2, "contrast": 0.0})])
worst3 = max(max(abs(a - b) for a, b in zip(g, w))
             for g, w in zip(v, want))
ok(worst3 <= 1.0 / 255, "九个格点都与直接过滤镜一致", "%.4f" % worst3)

section("4. 三滤镜串联：LUT 采样 vs 直接过栈")
img, lay = new_image()
add_filters(lay, OPS3)
v, sp = LB.bake(img, lay, 33)
ok(len(v) == 33 ** 3, "条目数 33³", len(v))
ok(sp == [], "三个算子都算逐像素", sp)

random.seed(7)
colors = [(random.random(), random.random(), random.random())
          for _ in range(40)]
colors += [(0, 0, 0), (1, 1, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
ref = apply_stack(colors, OPS3)

# 先看格点本身：格点上不该有插值误差，只有 1 码取整
nodes = [(i / 32.0, j / 32.0, k / 32.0)
         for i, j, k in [(0, 0, 0), (8, 8, 8), (16, 4, 24), (32, 32, 32),
                         (2, 30, 1), (24, 0, 12)]]
nref = apply_stack(nodes, OPS3)
node_err = max(max(abs(a - b) for a, b in zip(lut_sample(v, 33, c), w))
               for c, w in zip(nodes, nref))
ok(node_err <= 1.5 / 255, "33³ 的格点位置逐点吻合 ≤ 1.5 码", "%.4f" % node_err)

worst, at = 0.0, None
for c, want in zip(colors, ref):
    got = lut_sample(v, 33, c)
    d = max(abs(a - b) for a, b in zip(got, want))
    if d > worst:
        worst, at = d, c
ok(worst <= 0.05, "任意色最大差 ≤ 0.05（三线性固有误差）",
   "%.4f @ %s" % (worst, at))
print("       格点 %.4f，格间 %.4f（格间限差来自阶调曲线在近黑处的折点）"
      % (node_err, worst))

section("5. .cube 格式")
p = os.path.join(TMP, "t.cube")
LB.write_cube(p, 33, v, "check")
txt = open(p, encoding="utf-8").read().splitlines()
ok(txt[0].startswith('TITLE "'), "首行 TITLE", txt[0])
ok("LUT_3D_SIZE 33" in txt, "有 LUT_3D_SIZE 33")
ok("DOMAIN_MIN 0.0 0.0 0.0" in txt, "有 DOMAIN_MIN")
ok("DOMAIN_MAX 1.0 1.0 1.0" in txt, "有 DOMAIN_MAX")
body = [l for l in txt if l and not l[0].isalpha() and l[0] != "#"]
ok(len(body) == 33 ** 3, "条目 33³", len(body))
ok(all(len(x.split()[0].split(".")[1]) == 6 for x in body[:80]), "固定 6 位小数")
ok(all(0.0 <= float(q) <= 1.0 for x in body for q in x.split()), "值都在 0…1")
try:
    LB.write_cube(os.path.join(TMP, "bad.cube"), 33, v[:-1])
    ok(False, "条目数不对要报错")
except ValueError:
    ok(True, "条目数不对要报错")

section("6. 空间算子会被点名")
img, lay = new_image()
add_filters(lay, [("gimp:brightness-contrast", {"brightness": 0.1}),
                  ("lb:unsharp-mask", {"radius": 5.0, "amount": 0.5})])
v, sp = LB.bake(img, lay, 9)
ok(len(sp) == 1 and 'unsharp' in sp[0], "认出 unsharp-mask", sp)

section("7. 空栈要报错")
img, lay = new_image()
try:
    LB.bake(img, lay, 9)
    ok(False, "空栈要报错")
except RuntimeError:
    ok(True, "空栈要报错")

section("8. 烘焙不动原图")
img, lay = new_image()
add_filters(lay, [("gimp:brightness-contrast", {"brightness": 0.2})])
before = lay.get_buffer().get(Gegl.Rectangle.new(0, 0, 64, 64), 1.0,
                              "R'G'B'A float", Gegl.AbyssPolicy.NONE)
LB.bake(img, lay, 9)
after = lay.get_buffer().get(Gegl.Rectangle.new(0, 0, 64, 64), 1.0,
                             "R'G'B'A float", Gegl.AbyssPolicy.NONE)
ok(before == after, "像素逐字节相同")
ok(len(lay.get_filters()) == 1, "滤镜还挂在原图层上")
ok(img.get_precision().value_nick == 'u8-perceptual', "原图精度没被改")

section("9. 精度跟着图层走")
img, lay = new_image()
add_filters(lay, [("gimp:brightness-contrast", {"brightness": 0.2})])
v, _ = LB.bake(img, lay, 17)
w8 = apply_stack([(i / 16.0, i / 16.0, i / 16.0) for i in range(5)],
                 [("gimp:brightness-contrast", {"brightness": 0.2})])
e8 = max(max(abs(a - b) for a, b in zip(v[(i * 17 + i) * 17 + i], w))
         for i, w in zip(range(5), w8))
ok(e8 <= 1.5 / 255, "8bit 图层与直接过栈一致", "%.4f" % e8)

imgf = Gimp.Image.new_with_precision(64, 64, Gimp.ImageBaseType.RGB,
                                     Gimp.Precision.FLOAT_PERCEPTUAL)
layf = Gimp.Layer.new(imgf, "f", 64, 64, Gimp.ImageType.RGBA_IMAGE, 100.0,
                      Gimp.LayerMode.NORMAL)
imgf.insert_layer(layf, None, 0)
px = []
for y in range(64):
    for x in range(64):
        px.extend((x / 63.0, y / 63.0, 0.5, 1.0))
layf.get_buffer().set(Gegl.Rectangle.new(0, 0, 64, 64), "R'G'B'A float",
                      struct.pack('<%df' % len(px), *px))
add_filters(layf, [("gimp:brightness-contrast", {"brightness": 0.2})])
vf, _ = LB.bake(imgf, layf, 17)
wf = apply_stack([(i / 16.0, i / 16.0, i / 16.0) for i in range(5)],
                 [("gimp:brightness-contrast", {"brightness": 0.2})])
ef = max(max(abs(a - b) for a, b in zip(vf[(i * 17 + i) * 17 + i], w))
         for i, w in zip(range(5), wf))
ok(ef <= 1.5 / 255, "浮点图层也与直接过栈一致", "%.4f" % ef)
ok(imgf.get_precision().value_nick == 'float-perceptual', "浮点图精度没被改")

section("10. 贴回图里：lb:color-lookup vs 直接过滤镜")
img, lay = new_image()
add_filters(lay, OPS3)
v, _ = LB.bake(img, lay, 33)
cube = os.path.join(TMP, "rt.cube")
LB.write_cube(cube, 33, v, "rt")

img3, lay3 = new_image(len(colors), 1, colors)
add_filters(lay3, [("lb:color-lookup", {"file": cube, "strength": 1.0})])
for f in list(lay3.get_filters()):
    lay3.merge_filter(f)
got = read_rgb(lay3, len(colors), 1)

# 一路是「算子查表」，一路是「脚本里自己三线性算」，两者应当只差取整
by_lut = max(max(abs(a - b) for a, b in zip(g, lut_sample(v, 33, c)))
             for g, c in zip(got, colors))
ok(by_lut <= 2.0 / 255, "color-lookup 与本地三线性 ≤ 2 码", "%.4f" % by_lut)
worst2 = 0.0
for g, want in zip(got, ref):
    worst2 = max(worst2, max(abs(a - b) for a, b in zip(g, want)))
ok(worst2 <= 0.05, "贴回后与直接过滤镜 ≤ 0.05（同一份插值误差）",
   "%.4f" % worst2)
print("       查表 vs 直算 %.4f，贴回 vs 直滤镜 %.4f" % (by_lut, worst2))

# --------------------------------------------------------------------- 收尾
for _img in list(Gimp.get_images()):
    _img.delete()

print("\n" + "=" * 60)
print("PASS %d   FAIL %d" % (PASS, len(FAIL)))
for f in FAIL:
    print("  " + f)
print("=" * 60)
