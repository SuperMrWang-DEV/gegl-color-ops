#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图层样式：数学层回归（不需要 GIMP）。

跑法：python tools/check_layer_style.py

这里验的是 _shared/layer_style.py 的**语义**：
  · 距离变换必须是「精确 N 像素」——描边宽度不能随内容软硬变；
  · 投影的位移量必须真的等于 distance（角度往下是 +y）；
  · 混合模式的公式必须是 PS/GEGL 那一套（Multiply/Screen/Overlay…）；
  · 描边的外/内/居中必须落在边界的正确一侧，宽度线性可测；
  · 斜面的高光必须在光源那一侧，方向反过来要整片翻转；
  · 没启用的效果不能产出图层，启用的必须按 PS 的层序出现；
  · 预览缩放只动像素量、不动百分比（不然预览和应用是两套参数）。
这些错了不会报错，只会给你一张「看着差一点」的图。
"""

import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import numpy as np                                          # noqa: E402
import layer_style as LS                                    # noqa: E402

PASS = 0
FAIL = []


def ok(label, cond, detail=None):
    global PASS
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL.append("%s %s" % (label, detail if detail is not None else ""))
        print("  FAIL %s   %s" % (label, detail if detail is not None else ""))


def section(name):
    print("\n" + name)


def near(a, b, tol):
    return abs(float(a) - float(b)) <= tol


def make(w, h, box, fuzz=0.0):
    """纯色方块（alpha=1）在透明底上，返回 u8 RGBA bytes。"""
    arr = np.zeros((h, w, 4), dtype=np.float32)
    x1, y1, x2, y2 = box
    arr[y1:y2, x1:x2, :3] = 0.5
    arr[y1:y2, x1:x2, 3] = 1.0
    if fuzz > 0:
        arr[y1:y2, x1:x2, 3] = np.clip(
            arr[y1:y2, x1:x2, 3] * (1 - fuzz) +
            np.random.RandomState(7).rand(y2 - y1, x2 - x1) * fuzz, 0, 1)
    return LS.to_bytes(arr)


def style(**kw):
    st = LS.default_style()
    for key in st["effects"]:
        st["effects"][key]["enabled"] = False
    for name, vals in kw.items():
        st["effects"][name.replace("_", "-")].update(vals)
        st["effects"][name.replace("_", "-")]["enabled"] = True
    return st


W, H = 160, 120
BOX = (50, 40, 110, 80)


def render(**kw):
    st = style(**kw)
    return LS.render(make(W, H, BOX), W, H, st)


def layer_of(plan, name):
    for lyr in plan["layers"]:
        if lyr["name"].startswith(name):
            return lyr
    return None


def alpha_of(lyr):
    return lyr["rgba"][..., 3]


# ---- 基础 -----------------------------------------------------------------

section("基础：字节往返 / 模糊 / 平移")
raw = make(W, H, BOX)
back = LS.to_bytes(LS.to_float(raw, W, H))
ok("u8 → float → u8 逐字节一致", back == raw, len(back))
a = np.ones((32, 32), dtype=np.float32)
ok("模糊纯色场仍是 1（边缘也复制而不是补零）",
   near(LS.gaussian(a, 3.0).min(), 1.0, 1e-5), LS.gaussian(a, 3.0).min())
ramp = np.zeros((16, 16), dtype=np.float32)
ramp[8:, :] = 1.0
sh = LS.shift2(ramp, 0, 4)
ok("平移 4 行：原第 8 行挪到第 12 行", sh[12, 0] > 0.99 and sh[11, 0] < 0.01,
   (sh[11, 0], sh[12, 0]))
ok("平移出界补 0（不是环绕）", LS.shift2(ramp, 0, 20).max() == 0.0)
ok("sigma=0 是恒等", np.array_equal(LS.gaussian(ramp, 0), ramp))
plateau = np.full((24, 24), 0.4, dtype=np.float32)
ok("模糊不动内部平台（只软边）",
   near(float(LS.gaussian(plateau, 3.0)[12, 12]), 0.4, 1e-5),
   LS.gaussian(plateau, 3.0)[12, 12])

# ---- 距离变换 -------------------------------------------------------------

section("带符号距离：描边/斜面的地基")
m = np.zeros((81, 81), dtype=np.float32)
m[30:51, 30:51] = 1.0                               # 21×21 方块，中心 (40,40)
sd = LS.signed_distance(m, 60.0)
ok("方块中心到最近外部像素的距离 = 11（半宽 10 + 1）",
   near(sd[40, 40], 11.0, 0.001), sd[40, 40])
ok("最外圈内容像素距离 = 1", near(sd[30, 40], 1.0, 0.001), sd[30, 40])
ok("外侧 5 px 处 = -5", near(sd[40, 25], -5.0, 0.001), sd[40, 25])
ok("对角内容像素 (30,30) → 1", near(sd[30, 30], 1.0, 0.001), sd[30, 30])
ok("对角外侧 (25,25) 的距离 = 5√2", near(sd[25, 25], -5 * math.sqrt(2), 0.02),
   sd[25, 25])
edt = LS._edt(m > 0.5, 60.0)
ok("EDT：内容内为 0", edt[40, 40] == 0.0)
ok("EDT 截断到 max_d", LS._edt(m > 0.5, 3.0).max() <= 3.0,
   LS._edt(m > 0.5, 3.0).max())
ok("全空 mask 不炸", float(LS.signed_distance(np.zeros((8, 8), np.float32),
                                            10.0).max()) == -10.0)

# ---- 曲线 / 等高线 --------------------------------------------------------

section("扩展曲线与等高线")
x = np.linspace(0, 1, 101, dtype=np.float32)
sp = LS.spread_curve(x, 0.5)
ok("扩展把 0.5 钉住", near(sp[50], 0.5, 1e-6), sp[50])
ok("扩展让斜坡变陡", (sp[60] - sp[40]) > (x[60] - x[40]))
ok("扩展 0 是恒等", np.allclose(LS.spread_curve(x, 0.0), x))
ok("扩展 100% 变硬边", np.all((sp := LS.spread_curve(x, 1.0)) <= 1e-6) or
   (LS.spread_curve(x, 1.0).max() > 0.99))
lut = LS.contour_lut("linear")
ok("linear 等高线是恒等", near(lut[128], 128 / 255.0, 0.01), lut[128])
ok("等高线表长 256",
   all(LS.contour_lut(k).shape[0] == 256 for k in LS.CONTOURS))
ok("cone 在中间最高",
   float(LS.contour_lut("cone")[128]) > float(LS.contour_lut("cone")[10]))
ok("所有等高线端点都被夹到 0/1",
   all(0.0 <= float(LS.contour_lut(k)[0]) <= 1.0 for k in LS.CONTOURS))

# ---- 渐变场 ---------------------------------------------------------------

section("渐变场")
g = LS.gradient_field(40, 40, "linear", 90.0, 1.0, False)
ok("angle=90：底行为 0、顶行为 1", near(g[39, 20], 0.0, 0.05)
   and near(g[0, 20], 1.0, 0.05), (g[39, 20], g[0, 20]))
g0 = LS.gradient_field(40, 40, "linear", 0.0, 1.0, False)
ok("angle=0：左 0 右 1", near(g0[20, 0], 0.0, 0.05)
   and near(g0[20, 39], 1.0, 0.05), (g0[20, 0], g0[20, 39]))
ok("reverse 反转", near(float(
    LS.gradient_field(40, 40, "linear", 90.0, 1.0, True)[0, 20]), 0.0, 0.05))
rad = LS.gradient_field(41, 41, "radial", 0.0, 1.0, False)
ok("径向：中心最小、角落最大", rad[20, 20] < rad[0, 0], (rad[20, 20], rad[0, 0]))
dia = LS.gradient_field(41, 41, "diamond", 0.0, 1.0, False)
ok("菱形：中心最小", dia[20, 20] < dia[0, 20] and dia[20, 20] < dia[0, 0],
   (dia[20, 20], dia[0, 20], dia[0, 0]))
sc = LS.gradient_field(40, 40, "linear", 90.0, 2.0, False)
ok("scale 200% 把渐变拉长（顶行只到 0.75）", near(sc[0, 20], 0.75, 0.06),
   sc[0, 20])
lstops = LS.gradient_lut([(0.0, (1, 0, 0)), (1.0, (0, 0, 1))])
ok("色标表首尾正确", near(lstops[0, 0], 1.0, 0.01)
   and near(lstops[-1, 2], 1.0, 0.01))
unit = np.zeros((4, 4, 4), dtype=np.float32)
unit[..., 0] = 1.0
unit[0, 0, 1] = 1.0
pf = LS.pattern_field(unit, 10, 10, 1.0)
ok("图案按单元平铺（周期 4）", near(pf[0, 0, 1], 1.0, 1e-6)
   and near(pf[4, 4, 1], 1.0, 1e-6) and near(pf[1, 1, 1], 0.0, 1e-6))
ok("图案缩放 2× 周期变 8", near(LS.pattern_field(unit, 16, 16, 2.0)[8, 8, 1],
                              1.0, 1e-6))

# ---- 混合模式 -------------------------------------------------------------

section("混合模式公式")
cb = np.array([0.2, 0.5, 0.8], dtype=np.float32)
cs = np.array([0.6, 0.4, 0.3], dtype=np.float32)


def bmode(name, base=(0.2, 0.5, 0.8), src=(0.6, 0.4, 0.3)):
    return LS.blend_rgb(np.array(base, np.float32),
                        np.array(src, np.float32), name)


ok("normal = 源", np.allclose(bmode("normal"), cs))
ok("multiply = a×b", np.allclose(bmode("multiply"), cb * cs))
ok("screen = 1-(1-a)(1-b)", np.allclose(bmode("screen"),
                                         1 - (1 - cb) * (1 - cs)))
ok("darken = min", np.allclose(bmode("darken"), np.minimum(cb, cs)))
ok("lighten = max", np.allclose(bmode("lighten"), np.maximum(cb, cs)))
ok("difference = |a-b|", np.allclose(bmode("difference"), np.abs(cb - cs)))
ok("exclusion 公式", np.allclose(bmode("exclusion"),
                                 cb + cs - 2 * cb * cs))
ok("lineardodge = a+b 夹紧", np.allclose(bmode("lineardodge"),
                                         np.clip(cb + cs, 0, 1)))
ok("linearburn = a+b-1 夹紧", np.allclose(bmode("linearburn"),
                                          np.clip(cb + cs - 1, 0, 1)))
ok("subtract = a-b 夹紧", np.allclose(bmode("subtract"),
                                      np.clip(cb - cs, 0, 1)))
ok("overlay：暗底 2ab、亮底 1-2(1-a)(1-b)",
   near(float(bmode("overlay")[0]), 2 * 0.2 * 0.6, 1e-5)
   and near(float(bmode("overlay")[2]), 1 - 2 * 0.2 * 0.7, 1e-5),
   bmode("overlay"))
ok("hardlight 是 overlay 的源底互换",
   np.allclose(bmode("hardlight"), LS.blend_rgb(cs, cb, "overlay")))
ok("multiply 输出被夹在 0..1", 0 <= float(bmode("multiply").min())
   and float(bmode("multiply").max()) <= 1.0)
cb1 = np.array([[0.3, 0.5, 0.7]], dtype=np.float32)
cs1 = np.array([[0.5, 0.5, 0.5]], dtype=np.float32)
ok("hue 模式保留底色的亮度", near(
    float(LS._lum(LS.blend_rgb(cb1, cs1, "hue")[0])), float(LS._lum(cb1)[0]),
    0.02))
ok("luminosity 只借亮度", near(
    float(LS._lum(LS.blend_rgb(cb1, cs1, "luminosity")[0])),
    float(LS._lum(cs1)[0]), 0.02))
ok("colorburn 源为 0 → 0", float(bmode("colorburn", src=(0.0, 0.0, 0.0))[0])
   == 0.0)
ok("colordodge 源为 1 → 1", float(bmode("colordodge",
                                        src=(1.0, 1.0, 1.0))[0]) == 1.0)

section("合成：W3C / GEGL 通用公式")
dst = np.zeros((2, 2, 4), dtype=np.float32)
dst[..., 3] = 1.0
dst[..., :3] = 0.2
src = np.zeros((2, 2, 4), dtype=np.float32)
src[..., 3] = 0.5
src[..., :3] = 0.8
out = LS.composite_one(dst, src, "normal", 1.0)
ok("50% 正常叠在实底上：值居中", near(out[0, 0, 0], 0.5, 1e-6), out[0, 0, 0])
ok("叠加后 alpha 仍是 1", near(out[0, 0, 3], 1.0, 1e-6))
out2 = LS.composite_one(dst, src, "normal", 0.5)
ok("效果不透明度 50% 再减半", near(out2[0, 0, 0], 0.35, 1e-6), out2[0, 0, 0])
tr = np.zeros((1, 1, 4), dtype=np.float32)
ok("叠到全透明上 = 源本身", near(LS.composite_one(tr, src, "normal")[0, 0, 0],
                                 0.8, 1e-5))

# ---- 投影 -----------------------------------------------------------------

section("投影：位移 / 不透明度 / 挖空")
plan = render(drop_shadow={"distance": 10.0, "size": 0.0, "spread": 0,
                           "opacity": 100, "angle": 120.0})
lyr = plan["layers"][0]
al = alpha_of(lyr)
ys, xs = np.mgrid[0:H, 0:W]
tot = al.sum()
cx = (al * xs).sum() / tot
cy = (al * ys).sum() / tot
# PS 的「角度」是光源方向：120° = 光从左上来，阴影投向右下
want_dx = -10 * math.cos(math.radians(120))
want_dy = 10 * math.sin(math.radians(120))
ok("阴影重心按角度 120° 位移（x %.1f / 期望 %.1f）" % (cx, 80 + want_dx),
   near(cx, 80 + want_dx, 0.6), cx)
ok("角度 120° 时阴影落到下方（y %.1f / 期望 %.1f）" % (cy, 60 + want_dy),
   near(cy, 60 + want_dy, 0.6), cy)
ok("size=0 时不模糊（alpha 只有 0/1）",
   set(np.unique(np.round(al, 3))) <= {0.0, 1.0})
ok("投影颜色 = 参数颜色",
   tuple(np.round(lyr["rgba"][45, 75, :3], 3)) == (0.0, 0.0, 0.0))
ok("默认混合模式是 multiply", lyr["style_mode"] == "multiply")
ok("交给 GIMP 的层一律 normal（混合已预混）", lyr["mode"] == "normal")
ok("投影在内容下面", lyr["role"] == "below")
plan = render(drop_shadow={"distance": 10.0, "size": 0.0, "opacity": 40})
ok("不透明度 40% → alpha 0.4",
   near(float(alpha_of(plan["layers"][0]).max()), 0.4, 0.01),
   alpha_of(plan["layers"][0]).max())
plan = render(drop_shadow={"distance": 0.0, "size": 6.0})
al = alpha_of(plan["layers"][0])
ok("size=6 时边界有半透明过渡",
   ((al > 0.05) & (al < 0.95)).sum() > 100, ((al > 0.05) & (al < 0.95)).sum())
plan = render(drop_shadow={"distance": 10.0, "size": 0.0, "knockout": "deep"})
al = alpha_of(plan["layers"][0])
ok("深挖空：内容区域内 alpha = 0", al[55:65, 80:90].max() < 1e-6,
   al[55:65, 80:90].max())
ok("深挖空：内容外仍有阴影", al[85:90, 100:110].max() > 0.5)
plan = render(drop_shadow={"distance": 0, "size": 8, "spread": 0})
soft = alpha_of(plan["layers"][0])
plan = render(drop_shadow={"distance": 0, "size": 8, "spread": 100})
hard = alpha_of(plan["layers"][0])
ok("扩展 100% 比扩展 0 的边缘更硬",
   ((hard > 0.05) & (hard < 0.95)).sum() < ((soft > 0.05) & (soft < 0.95)).sum(),
   (((soft > 0.05) & (soft < 0.95)).sum(),
    ((hard > 0.05) & (hard < 0.95)).sum()))

# ---- 内阴影 / 发光 --------------------------------------------------------

section("内阴影：只在内容内部")
plan = render(inner_shadow={"distance": 6.0, "size": 4.0})
al = alpha_of(plan["layers"][0])
ok("内容外 alpha = 0", al[:, :40].max() < 1e-6 and al[0:30, :].max() < 1e-6,
   al[:, :40].max())
ok("内阴影聚在左上内缘（左上 > 右下）",
   float(al[44:56, 52:70].mean()) > float(al[66:78, 92:108].mean()),
   (float(al[44:56, 52:70].mean()), float(al[66:78, 92:108].mean())))
ok("内部中心没被压到", al[60, 80] < 0.05, al[60, 80])
ok("内阴影在上面", plan["layers"][0]["role"] == "above")

section("外发光 / 内发光")
plan = render(outer_glow={"size": 8.0, "spread": 0, "opacity": 100})
al = alpha_of(plan["layers"][0])
ok("外发光在内容外部亮", al[36, 80] > 0.05, al[36, 80])
ok("外发光压在内容下面（内部靠层叠遮住）",
   plan["layers"][0]["role"] == "below")
ok("外发光默认 screen",
   plan["layers"][0]["style_mode"] == "screen")
plan = render(inner_glow={"size": 8.0, "source": "edge", "opacity": 100})
edge = alpha_of(plan["layers"][0])
plan = render(inner_glow={"size": 8.0, "source": "center", "opacity": 100})
center = alpha_of(plan["layers"][0])
ok("内发光（边缘）：贴边亮、中心暗", edge[42, 55] > edge[60, 80],
   (edge[42, 55], edge[60, 80]))
ok("内发光（居中）：中心比边缘亮", center[60, 80] > center[42, 55],
   (center[60, 80], center[42, 55]))
ok("两种源给出不同的图", not np.allclose(edge, center))

# ---- 斜面 -----------------------------------------------------------------

section("斜面和浮雕")
plan = render(bevel={"size": 8.0, "depth": 100, "angle": 120.0})
ok("斜面出两片（阴影 + 高光）", len(plan["layers"]) == 2,
   [l["name"] for l in plan["layers"]])
sh_l = plan["layers"][0]
hi_l = plan["layers"][1]
ok("阴影片 multiply / 高光片 screen",
   sh_l["style_mode"] == "multiply" and hi_l["style_mode"] == "screen",
   (sh_l["style_mode"], hi_l["style_mode"]))
ok("两片交给 GIMP 时都是 normal", sh_l["mode"] == "normal"
   and hi_l["mode"] == "normal")
hi = alpha_of(hi_l)
sh = alpha_of(sh_l)
ok("角度 120°：上边缘内侧有高光", hi[44, 80] > 0.1, hi[44, 80])
ok("角度 120°：下边缘内侧有阴影", sh[78, 80] > 0.1, sh[78, 80])
ok("高光与阴影不在同一侧", hi[78, 80] < hi[44, 80],
   (hi[78, 80], hi[44, 80]))
plan_d = render(bevel={"size": 8.0, "direction": "down"})
hi_d = alpha_of(plan_d["layers"][1])
ok("方向反了之后高光换到另一侧", hi_d[78, 80] > hi_d[44, 80],
   (hi_d[78, 80], hi_d[44, 80]))
for sty in LS.BEVEL_STYLES:
    pl = render(bevel={"size": 8.0, "style": sty})
    ok("斜面样式 %s 能出图且有 alpha" % sty,
       len(pl["layers"]) == 2 and float(alpha_of(pl["layers"][1]).max()) > 0.01,
       float(alpha_of(pl["layers"][1]).max()))
plan_o = render(bevel={"size": 8.0, "style": "outer"})
al_o = alpha_of(plan_o["layers"][1])
ok("外斜面的高光贴在外侧", al_o[38, 80] > 0.02, al_o[38, 80])
plan_s = render(bevel={"size": 8.0, "style": "stroke", "stroke_size": 4.0})
ok("描边浮雕的 alpha 是一圈窄带",
   0 < float(alpha_of(plan_s["layers"][1]).max()) < 1.0)

# ---- 光泽 / 叠加 / 描边 ---------------------------------------------------

section("光泽")
plan = render(satin={"distance": 8.0, "size": 10.0, "opacity": 100})
a_sat = alpha_of(plan["layers"][0])
plan_inv = render(satin={"distance": 8.0, "size": 10.0, "opacity": 100,
                         "invert": True})
a_inv = alpha_of(plan_inv["layers"][0])
ok("光泽在内容内部", a_sat[:, :40].max() < 1e-6)
ok("反相后是另一张图（不是同一张）",
   float(np.abs(a_sat - a_inv).max()) > 0.1,
   float(np.abs(a_sat - a_inv).max()))

section("颜色 / 渐变 / 图案叠加")
plan = render(color_overlay={"color": [1.0, 0.0, 0.0], "opacity": 100})
lyr = plan["layers"][0]
ok("颜色叠加：RGB 是纯红", tuple(np.round(lyr["rgba"][60, 80, :3], 3))
   == (1.0, 0.0, 0.0), lyr["rgba"][60, 80, :3])
ok("颜色叠加：alpha = 内容 alpha",
   near(float(alpha_of(lyr)[60, 80]), 1.0, 1e-6)
   and float(alpha_of(lyr)[10, 10]) == 0.0)
plan = render(color_overlay={"opacity": 50})
ok("不透明度 50% → alpha 0.5",
   near(float(alpha_of(plan["layers"][0])[60, 80]), 0.5, 0.01))
assets = {"gradient": LS.gradient_lut([(0.0, (1, 0, 0)),
                                       (1.0, (0, 0, 1))])}
st = style(gradient_overlay={"angle": 90.0, "scale": 100, "opacity": 100})
plan = LS.render(make(W, H, BOX), W, H, st, assets)
rgb = plan["layers"][0]["rgba"]
ok("渐变叠加：顶行偏蓝、底行偏红",
   rgb[42, 80, 2] > rgb[42, 80, 0] and rgb[77, 80, 0] > rgb[77, 80, 2],
   (rgb[42, 80, :3], rgb[77, 80, :3]))
st = style(gradient_overlay={"angle": 90.0, "reverse": True})
plan = LS.render(make(W, H, BOX), W, H, st, assets)
rgb_r = plan["layers"][0]["rgba"]
ok("渐变叠加 reverse 反转", rgb_r[42, 80, 0] > rgb_r[77, 80, 0],
   (rgb_r[42, 80, 0], rgb_r[77, 80, 0]))
unit2 = np.zeros((4, 4, 4), dtype=np.float32)
unit2[..., 0] = 1.0
unit2[0:2, :, 1] = 1.0
st = style(pattern_overlay={"scale": 100, "opacity": 100})
plan = LS.render(make(W, H, BOX), W, H, st, {"pattern": unit2})
rgb = plan["layers"][0]["rgba"]
ok("图案叠加按单元平铺（第 0/4 行同色）",
   near(rgb[40, 50, 1], rgb[44, 50, 1], 1e-5),
   (rgb[40, 50, 1], rgb[44, 50, 1]))

section("描边：位置与宽度")
def stroke_width(pos, size, at=80):
    st = style(stroke={"size": size, "position": pos, "color": [1, 0, 0],
                       "opacity": 100})
    plan = LS.render(make(W, H, BOX), W, H, st)
    al = alpha_of(plan["layers"][0])
    row = al[60, :]
    xs = np.where(row > 0.5)[0]
    return xs.min(), xs.max(), al


lo, hi_i, al_o = stroke_width("outside", 6)
ok("外描边从内容左边界（x=50）外 6 px 起", lo == 45, lo)
ok("外描边不进内容", al_o[60, 80] < 1e-6)
lo, hi_i, al_i = stroke_width("inside", 6)
ok("内描边从 x=50 起", lo == 50, lo)
ok("内描边只贴边、不填满", al_i[60, 53] > 0.5 and al_i[60, 80] < 1e-6,
   (al_i[60, 53], al_i[60, 80]))
lo, hi_i, al_c = stroke_width("center", 6)
ok("居中描边跨边界（外 3 / 内 3）", lo == 48 and al_c[60, 51] > 0.5, lo)
lo1, _, _ = stroke_width("outside", 3)
lo2, _, _ = stroke_width("outside", 9)
ok("外描边宽度线性（3 px → 起点 48，9 px → 起点 42）",
   lo1 == 48 and lo2 == 42, (lo1, lo2))
st = style(stroke={"size": 5, "position": "outside", "fill": "gradient"})
plan = LS.render(make(W, H, BOX), W, H, st, assets)
ok("描边可以用渐变填充",
   len(np.unique(np.round(plan["layers"][0]["rgba"][..., 0], 2))) > 3)

# ---- 混合选项 -------------------------------------------------------------

section("混合选项：混合颜色带")
dark = np.zeros((H, W, 4), dtype=np.float32)
dark[..., :3] = 0.05
dark[20:60, 30:90, 3] = 1.0
bright = np.zeros((H, W, 4), dtype=np.float32)
bright[..., :3] = 0.9
bright[20:60, 30:90, 3] = 1.0
st = style(color_overlay={"color": [1, 1, 0]})
st["blend"].update({"blend_if_source": True, "blend_if_lo": 30})
plan = LS.render(LS.to_bytes(dark), W, H, st)
ok("混合颜色带：暗像素被抬掉（alpha 变 0）",
   float(alpha_of(plan["layers"][0]).max()) < 0.05,
   float(alpha_of(plan["layers"][0]).max()))
plan = LS.render(LS.to_bytes(bright), W, H, st)
ok("混合颜色带：亮像素不受影响",
   float(alpha_of(plan["layers"][0]).max()) > 0.9)

# ---- 整体流程 -------------------------------------------------------------

section("样式栈：层序 / 启用状态")
st = style(drop_shadow={}, inner_shadow={}, color_overlay={}, bevel={},
           stroke={})
plan = LS.render(make(W, H, BOX), W, H, st)
names = [l["name"] for l in plan["layers"]]
ok("层序 = PS 的渲染顺序（投影最先、斜面最后）",
   names[0] == "Drop Shadow" and names[-1] == "Bevel and Emboss (highlight)",
   names)
ok("below 的只有投影和外发光",
   [l["name"] for l in plan["layers"] if l["role"] == "below"]
   == ["Drop Shadow"], [l["name"] for l in plan["layers"]
                        if l["role"] == "below"])
st = style(outer_glow={})
plan = LS.render(make(W, H, BOX), W, H, st)
ok("只开外发光时只出一层", len(plan["layers"]) == 1)
st = LS.default_style()
for k in st["effects"]:
    st["effects"][k]["enabled"] = False
plan = LS.render(make(W, H, BOX), W, H, st)
ok("全关时不出层", len(plan["layers"]) == 0)
ok("默认样式里投影是开的",
   LS.default_style()["effects"]["drop-shadow"]["enabled"])
ok("enabled_effects 按渲染顺序返回",
   LS.enabled_effects(style(stroke={}, drop_shadow={}))
   == ["drop-shadow", "stroke"])

section("序列化 / 预览缩放")
st = style(drop_shadow={"distance": 12.0, "size": 9.0},
           stroke={"size": 4.0, "position": "inside"})
text = LS.format_style(st)
back = LS.parse_style(text)
ok("样式串往返一致", LS.format_style(back) == text)
ok("空串退回默认样式", LS.parse_style("")["effects"]["drop-shadow"]["enabled"])
ok("坏串不炸", isinstance(LS.parse_style("{oops"), dict))
k = 0.5
sc = LS.scale_style(st, k)
ok("scale_style 把像素参数乘 k",
   near(sc["effects"]["drop-shadow"]["distance"], 6.0, 1e-6), 
   sc["effects"]["drop-shadow"]["distance"])
ok("scale_style 不动百分比",
   sc["effects"]["drop-shadow"]["opacity"]
   == st["effects"]["drop-shadow"]["opacity"])
ok("scale_style 不动描边位置这类枚举",
   sc["effects"]["stroke"]["position"] == "inside")
ok("scale_style 不动原样式",
   near(st["effects"]["drop-shadow"]["size"], 9.0, 1e-6))

plan = LS.render(make(W, H, BOX), W, H, style(drop_shadow={},
                                              color_overlay={"opacity": 100}))
out = LS.preview(plan, W, H)
ok("preview 输出尺寸正确", out.shape == (H, W, 4), out.shape)
ok("preview 里颜色叠加盖住了内容",
   out[60, 80, 0] > 0.9 and out[60, 80, 1] < 0.2, out[60, 80, :3])
flat = LS.flatten_onto(out, (1.0, 1.0, 1.0))
ok("flatten 之后没有 alpha 残留", flat.shape == (H, W, 3))
ok("summay 能列出层名", LS.summary(plan)["layers"] == len(plan["layers"]))

section("健壮性：坏参数不毁整份样式")
st = style(color_overlay={})
st["effects"]["stroke"] = {"enabled": True, "size": "not-a-number"}
plan = LS.render(make(W, H, BOX), W, H, st)
ok("坏效果被跳过、其余照出",
   len(plan["layers"]) == 1 and len(plan["notes"]) >= 1,
   (len(plan["layers"]), plan["notes"]))
ok("ROLE 常量覆盖两个 below",
   set(LS.BELOW_CONTENT) == {"drop-shadow", "outer-glow"})
ok("混合模式表能映射到 GIMP id",
   all(LS.MODE_GIMP[m[0]].isupper() for m in LS.MODES))
ok("每个效果都有参数表",
   set(LS.SPECS.keys()) == set(LS.EFFECT_ORDER), set(LS.SPECS.keys()))
ok("面板顺序覆盖所有效果",
   set(LS.PANEL_ORDER) == set(LS.EFFECT_ORDER))

section("性能（768×1024，六个效果）")
big = make(768, 1024, (150, 200, 620, 820))
st = style(drop_shadow={}, outer_glow={}, inner_shadow={}, bevel={},
           gradient_overlay={}, stroke={})
t0 = time.time()
plan = LS.render(big, 768, 1024, st, assets)
dt = time.time() - t0
ok("768×1024 六个效果 < 4 s（%.2f s）" % dt, dt < 4.0, dt)
ok("全部产出了图层", len(plan["layers"]) == 7, len(plan["layers"]))


section("复制样式：代码串进、代码串出")
st_a = style(drop_shadow={"distance": 9, "size": 7, "angle": 135.0},
             inner_shadow={"choke": 20},
             stroke={"size": 2.5, "position": "inside"})
code = LS.format_style(st_a)
again, warns = LS.read_style_code(code)
ok("复制 → 粘贴，逐字节还原（%d 字符）" % len(code),
   LS.format_style(again) == code)
ok("读回时没有警告", not warns, warns)
ok("pretty 版本（换行缩进）读回来还是同一份",
   LS.format_style(LS.read_style_code(LS.pretty_style(st_a))[0]) == code)
ok("代码串全是 ASCII（粘到哪儿都不会被编码弄坏）",
   all(ord(c) < 128 for c in LS.pretty_style(st_a)))
ok("套了一层引号（json.dumps 过两次）也能读",
   LS.format_style(LS.read_style_code(json.dumps(code))[0]) == code)

src = make(W, H, BOX)
pa = LS.render(src, W, H, st_a, assets)
pb = LS.render(src, W, H, again, assets)
ok("粘过去渲染出来的像素完全一致",
   len(pa["layers"]) == len(pb["layers"])
   and all((la["rgba"] == lb["rgba"]).all()
           for la, lb in zip(pa["layers"], pb["layers"])),
   (len(pa["layers"]), len(pb["layers"])))

for bad in ("", "   ", "hello", "[1,2]", '{"a":1}', '{"effects":5}'):
    try:
        LS.read_style_code(bad)
        ok("坏代码要报错：%r" % bad, False)
    except LS.StyleCodeError:
        ok("坏代码报错：%r" % bad, True)

st_c, warns_c = LS.read_style_code(
    '{"effects":{"drop-shadow":{"distance":9999,"size":-5,'
    '"contour":"nope"},"nope":{}}}')
ok("越界距离夹到上限 300", float(st_c["effects"]["drop-shadow"]["distance"]) == 300.0,
   st_c["effects"]["drop-shadow"]["distance"])
ok("负数大小夹到 0", float(st_c["effects"]["drop-shadow"]["size"]) == 0.0,
   st_c["effects"]["drop-shadow"]["size"])
ok("不认识的等高线退回 linear",
   st_c["effects"]["drop-shadow"]["contour"] == "linear")
ok("不认识的效果被忽略、但留一条警告",
   any("nope" in w for w in warns_c), warns_c)

st_d, _w = LS.read_style_code(
    '{"effects":{"color-overlay":{"color":[255,128,0],"enabled":true}}}')
ok("0–255 写法的颜色自动除以 255",
   near(st_d["effects"]["color-overlay"]["color"][0], 1.0, 1e-6)
   and near(st_d["effects"]["color-overlay"]["color"][1], 128 / 255.0, 1e-6),
   st_d["effects"]["color-overlay"]["color"])

st_e, _w = LS.read_style_code('{"effects":{"satin":{"size":22}}}')
ok("只给一个参数，其余保持默认",
   float(st_e["effects"]["satin"]["size"]) == 22.0
   and st_e["effects"]["satin"]["distance"]
   == LS.default_style()["effects"]["satin"]["distance"],
   (st_e["effects"]["satin"]["size"], st_e["effects"]["satin"]["distance"]))
ok("手写代码没写 enabled 也当成要开",
   st_e["effects"]["satin"]["enabled"] is True)
ok("没提到的效果保持关闭",
   st_e["effects"]["drop-shadow"]["enabled"] is False)

dest = LS.default_style()
ref = dest["effects"]["bevel"]
LS.adopt_style(dest, st_a)
ok("adopt 之后参数页握着的还是同一个 dict（否则滑杆再也改不动数据）",
   ref is dest["effects"]["bevel"])
ok("adopt 之后内容等于源", LS.format_style(dest) == code)
st_f = LS.default_style()
st_f["global_angle"] = 45.0
LS.adopt_style(dest, st_f)
ok("全局光也一起带过去", near(dest["global_angle"], 45.0, 1e-9),
   dest["global_angle"])

print("\n" + "=" * 62)
if FAIL:
    print("失败 %d 项 / 通过 %d 项" % (len(FAIL), PASS))
    for f in FAIL:
        print("  - %s" % f)
    sys.exit(1)
else:
    print("全部通过：%d 项检查" % PASS)
