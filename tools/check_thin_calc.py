#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计算薄壳（plugin/lb-calculations）端到端验证。

在 GIMP 的 python-fu 里跑，直接 import 插件模块、调用真实的
run_calculations，再做逐像素比对：

    export GEGL_PATH="<repo>/build;D:/fastsoftware/GIMP 3/lib/gegl-0.4"
    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_thin_calc.py').read())" --quit

期望值都是按 lb:calculations 的公式手算的（Rec.709 亮度，8bit 伽马域）：
    v1 = luma(128,128,128) = 0.5020
    v2 = luma(200,100,50)  = 0.4612
    multiply = v1*v2       = 0.2315 -> 59 码
"""

import array
import importlib.util
import os
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl

REL = os.path.join('plugin', 'lb-calculations', 'lb-calculations.py')


def _find_root():
    """GIMP 的 exec(open(...)) 里 __file__ 不可靠，用 cwd 兜底"""
    here = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    for cand in (here, os.path.dirname(here), os.getcwd()):
        if os.path.exists(os.path.join(cand, REL)):
            return cand
    raise RuntimeError("找不到 %s（请在仓库根目录运行）" % REL)


ROOT = _find_root()
MOD_PATH = os.path.join(ROOT, REL)

spec = importlib.util.spec_from_file_location("lbcalc", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
FMT = mod.FMT

W = H = 8
PASS, FAIL = 0, 0


def report(name, got, want, tol=2):
    global PASS, FAIL
    ok = all(abs(g - w) <= tol for g, w in zip(got, want))
    PASS += 1 if ok else 0
    FAIL += 0 if ok else 1
    print("  %-46s %-22s %-22s %s"
          % (name, got, want, "OK" if ok else "FAIL"), flush=True)


def make_layer(image, name, rgb, alpha=1.0, hole=None):
    lay = Gimp.Layer.new(image, name, W, H, Gimp.ImageType.RGBA_IMAGE, 100.0,
                         Gimp.LayerMode.NORMAL)
    image.insert_layer(lay, None, -1)
    vals = array.array('f')
    for y in range(H):
        for x in range(W):
            a = 0.0 if (hole and (x, y) == hole) else alpha
            vals.extend([rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, a])
    mod._write(lay, (0, 0, W, H), vals)
    return lay


def named(image, label):
    """按名字找图层（插入位置 -1 的具体含义随上下文变，不靠下标）"""
    for lay in image.get_layers():
        if lay.get_name() == label:
            return lay
    return image.get_layers()[0]


def px(drawable, x=0, y=0):
    data = drawable.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0, FMT,
                                     Gegl.AbyssPolicy.NONE)
    v = array.array('f')
    v.frombytes(data)
    return [round(t * 255) for t in v[:4]]


def px_y(drawable, x=0, y=0):
    """选区/蒙版是单通道 Y float，用 RGBA 读会被 babl 转成别处去"""
    data = drawable.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                                     "Y float", Gegl.AbyssPolicy.NONE)
    v = array.array('f')
    v.frombytes(data)
    return [round(t * 255) for t in v[:1]]


def params(**kw):
    p = dict(ch1=mod.CH_LUMA, inv1=False, s1_layer=None,
             ch2=mod.CH_LUMA, inv2=False, s2_layer=None,
             blend="multiply", opacity=100.0,
             use_mask=False, mask_layer=None, mch=mod.CH_LUMA,
             inv_mask=False, result=mod.RES_GREY)
    p.update(kw)
    return p


def fresh(hole=None):
    """新图像：A 灰 128，B (200,100,50)（可留一个透明洞），M 灰 64"""
    img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    a = make_layer(img, "A", (128, 128, 128))
    b = make_layer(img, "B", (200, 100, 50), hole=hole)
    m = make_layer(img, "M", (64, 64, 64))
    return img, a, b, m


print("计算薄壳 · 端到端", flush=True)
print("  v1=0.5020  v2=0.4612  multiply=0.2315 -> 59 码", flush=True)

# ---- 1. 无遮罩，multiply ---------------------------------------------------
img, a, b, m = fresh()
mod.run_calculations(img, a, params(s1_layer=a, s2_layer=b))
grey_layer = named(img, "Calculations")
report("无遮罩 multiply", px(grey_layer)[:3], [59, 59, 59])

# ---- 2. 遮罩取源 2 自身通道（算子自带 mask 参数，一趟） ---------------------
img, a, b, m = fresh()
mod.run_calculations(img, a, params(s1_layer=a, s2_layer=b, use_mask=True,
                                    mask_layer=b, mch=mod.CH_LUMA))
# out = 0.5020 + (0.2315-0.5020)*0.4612 = 0.3772 -> 96
report("遮罩=源2亮度（一趟）", px(named(img, "Calculations"))[:3], [96, 96, 96])

# ---- 3. 遮罩取第三张图（两趟 + 插值） --------------------------------------
img, a, b, m = fresh()
mod.run_calculations(img, a, params(s1_layer=a, s2_layer=b, use_mask=True,
                                    mask_layer=m, mch=mod.CH_LUMA))
# out = 0.5020 + (0.2315-0.5020)*(64/255=0.2510) = 0.4341 -> 111
report("遮罩=第三层灰64（两趟）", px(named(img, "Calculations"))[:3], [111, 111, 111])

# ---- 4. 源 2 的透明洞不参与，蒙版为 0 --------------------------------------
img, a, b, m = fresh(hole=(3, 3))
mod.run_calculations(img, a, params(s1_layer=a, s2_layer=b))
gl = named(img, "Calculations")
report("源2透明洞 -> 蒙版 0", px(gl, 3, 3)[:3], [0, 0, 0])
report("源2其余像素照常", px(gl, 4, 4)[:3], [59, 59, 59])

# ---- 5. 落成选区 -----------------------------------------------------------
img, a, b, m = fresh()
mod.run_calculations(img, a, params(s1_layer=a, s2_layer=b,
                                    result=mod.RES_SELECTION))
sel = img.get_selection()
report("选区（灰度即选中度）", px_y(sel), [59])
print("  选区存在:", sel is not None, " 通道数:", len(img.get_channels()), flush=True)

# ---- 6. 落成 Alpha 通道 ----------------------------------------------------
img, a, b, m = fresh()
mod.run_calculations(img, a, params(s1_layer=a, s2_layer=b,
                                    result=mod.RES_CHANNEL))
chs = img.get_channels()
print("  通道数:", len(chs), flush=True)
if chs:
    report("Alpha 通道内容", px(chs[0])[:3], [59, 59, 59])

# ---- 7. 落成图层 alpha -----------------------------------------------------
img, a, b, m = fresh()
mod.run_calculations(img, a, params(s1_layer=a, s2_layer=b,
                                    result=mod.RES_ALPHA))
# A 原本 alpha=1，乘上蒙版 0.2315 -> 59；RGB 保持 128
report("图层 alpha = 1 x 0.2315", px(a), [128, 128, 128, 59])

# ---- 8. 单通道 / 反相 ------------------------------------------------------
img, a, b, m = fresh()
mod.run_calculations(img, a, params(s1_layer=a, s2_layer=b,
                                    ch1=mod.CH_RED, ch2=mod.CH_RED,
                                    inv2=True))
# v1=0.5020, v2=1-0.5020=0.4980（B 的 R=200/255=0.784 反相后 0.216）
# 取红通道：v1=0.502, v2=0.784 -> 反相 0.216 -> 0.1084 -> 28
report("单通道 Red + 反相源 2", px(named(img, "Calculations"))[:3], [28, 28, 28])

# 不要 sys.exit：python-fu-eval 里那会直接把插件进程干掉
print("\n结果: %d/%d 通过%s" % (PASS, PASS + FAIL,
                              "" if FAIL == 0 else "（%d 项失败）" % FAIL),
      flush=True)
