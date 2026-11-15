# -*- coding: utf-8 -*-
"""lb:ps-hue-saturation 的规范参考实现（Python）。

本文件是「用户给定代码」的**逐字转录**与**浮点升级版**两套对照，用于：

  1. 作为 C 算子的唯一规范（不再和 Photoshop 实测图对比）；
  2. 量化原代码里 8 位整数量化/int() 截断引入的误差；
  3. 给出 saturation=+100 除零点的数学极限值。

原代码的处理链（不含着色）：
    rgb --(screen/multiply 混合中性灰)--> rgb' --(转 HSL，取整)-->
    h 旋转 --(s 相对缩放)--> hsl_to_rgb (int 截断)

字面版函数名带 _lit，浮点版带 _f。两者数学一致，差别只在量化：

  字面版  h 量化到 1°、s/l 量化到 1%、输出 int() 截断（恒向零）
  浮点版  全程 0…1 / 0…360 浮点，输出四舍五入

    python tools/ref_ps_hue_sat.py        # 跑示例 + 量化误差统计
"""
import colorsys
import random

# ---------------------------------------------------------------- 字面转录

def hsl_to_rgb_lit(h, s, l):
    h = h / 360.0
    s = s / 100.0
    l = l / 100.0
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def rgb_to_hsl_lit(r, g, b):
    r = r / 255.0
    g = g / 255.0
    b = b / 255.0
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return int(h * 360), int(s * 100), int(l * 100)


def multiply_blend_rgb(r1, g1, b1, r2, g2, b2):
    r = int((r1 * r2) / 255)
    g = int((g1 * g2) / 255)
    b = int((b1 * b2) / 255)
    return r, g, b


def screen_blend_rgb(r1, g1, b1, r2, g2, b2):
    r = 255 - ((255 - r1) * (255 - r2) // 255)
    g = 255 - ((255 - g1) * (255 - g2) // 255)
    b = 255 - ((255 - b1) * (255 - b2) // 255)
    return r, g, b


def grayscale_percent(percent):
    return 255 * percent / 100, 255 * percent / 100, 255 * percent / 100


def get_new_rgb(r, g, b, lightness_percent):
    if lightness_percent > 0:
        gr, gg, gb = grayscale_percent(lightness_percent)
        return screen_blend_rgb(r, g, b, gr, gg, gb)
    else:
        gr, gg, gb = grayscale_percent(100 + lightness_percent)
        return multiply_blend_rgb(r, g, b, gr, gg, gb)


def adjust_hsl_lit(r, g, b, hue_adjust, saturation_percent):
    h, s, l = rgb_to_hsl_lit(r, g, b)
    h = (h + hue_adjust) % 360
    if saturation_percent >= 0:
        s = s / (1 - abs(saturation_percent) / 100.0)
    else:
        s = s * (1 - abs(saturation_percent) / 100.0)
    s = max(0, min(100, s))
    return hsl_to_rgb_lit(h, s, l)


def ref_literal(r, g, b, hue=0, sat=0, light=0):
    """原样调用：先明度混合，再色相/饱和度。sat=+100 会与原代码一致地抛
    ZeroDivisionError —— 这是原代码的真实行为，不在此掩盖。"""
    r2, g2, b2 = get_new_rgb(r, g, b, light)
    return adjust_hsl_lit(r2, g2, b2, hue, sat)


# ---------------------------------------------------------------- 浮点版

def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _rgb_to_hsl_f(r, g, b):
    h, l, s = colorsys.rgb_to_hls(_clamp01(r), _clamp01(g), _clamp01(b))
    return (h * 360.0) % 360.0, _clamp01(s), _clamp01(l)


def _hsl_to_rgb_f(h, s, l):
    return colorsys.hls_to_rgb((h % 360.0) / 360.0, _clamp01(l), _clamp01(s))


def _apply_light_f(c, t):
    """与中性灰做 screen(t>0) / multiply(t<0)，代数化简后就是个 lerp。"""
    if t > 0.0:
        return c + t * (1.0 - c)
    if t < 0.0:
        return c * (1.0 + t)
    return c


def _scale_sat_f(s, x):
    """x=+1 时原式 s/(1-1) 除零；数学极限是 +inf 再被 clamp 到 1。
    故 x>=1 直接返回满饱和（s=0 仍是 0）。"""
    if x >= 1.0:
        return 1.0 if s > 0.0 else 0.0
    if x > 0.0:
        return min(1.0, s / (1.0 - x))
    if x < 0.0:
        return max(0.0, s * (1.0 + x))
    return s


def ref_float(r, g, b, hue=0.0, sat=0.0, light=0.0):
    """r,g,b 为 0…255；返回 0…255 浮点（未取整，便于算码差）。"""
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    t = light / 100.0
    r, g, b = _apply_light_f(r, t), _apply_light_f(g, t), _apply_light_f(b, t)
    h, s, l = _rgb_to_hsl_f(r, g, b)
    h = (h + hue) % 360.0
    s = _scale_sat_f(s, sat / 100.0)
    r, g, b = _hsl_to_rgb_f(h, s, l)
    return r * 255.0, g * 255.0, b * 255.0


# ---------------------------------------------------------------- 统计

def _codes(v):
    return tuple(int(round(x)) for x in v)


def report(n=20000, seed=7):
    random.seed(seed)
    worst, hist = 0, {}
    fails = 0
    for _ in range(n):
        r, g, b = (random.randrange(256) for _ in range(3))
        hue = random.choice([0, -28, 28, 90, -150])
        sat = random.choice([0, 10, 25, 50, -25, -50, -80])
        light = random.choice([0, 10, 25, 60, -20, -60])
        lit = ref_literal(r, g, b, hue, sat, light)
        flt = _codes(ref_float(r, g, b, hue, sat, light))
        d = max(abs(a - c) for a, c in zip(lit, flt))
        hist[d] = hist.get(d, 0) + 1
        worst = max(worst, d)
        fails += 1 if d else 0
    print("样本 %d，字面版 vs 浮点版，单位=8 位码" % n)
    for k in sorted(hist):
        print("  差 %d 码: %5d 次 (%.1f%%)" % (k, hist[k], 100.0 * hist[k] / n))
    print("  最大 %d 码，不一致比例 %.1f%%" % (worst, 100.0 * fails / n))


# ------------------------------------------------ 量化误差来源拆解

def _variant(r, g, b, hue, sat, light, q_h=False, q_sl=False, trunc=False):
    """q_h: h 取整到 1°；q_sl: s/l 取整到 1%；trunc: 输出 int() 截断。"""
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    t = light / 100.0
    r, g, b = _apply_light_f(r, t), _apply_light_f(g, t), _apply_light_f(b, t)
    h, s, l = _rgb_to_hsl_f(r, g, b)
    if q_h:
        h = float(int(h))
    if q_sl:
        s = int(s * 100) / 100.0
        l = int(l * 100) / 100.0
    h = (h + hue) % 360.0
    if q_h:
        h = float(int(h))
    s = _scale_sat_f(s, sat / 100.0)
    r, g, b = _hsl_to_rgb_f(h, s, l)
    out = [r * 255.0, g * 255.0, b * 255.0]
    return [int(x) for x in out] if trunc else [int(round(x)) for x in out]


def breakdown(n=8000, seed=11):
    """逐项打开量化，看清哪一处吃掉了精度。"""
    rows = [("—（全浮点基准）", {}),
            ("h 取整 1°", dict(q_h=True)),
            ("s/l 取整 1%", dict(q_sl=True)),
            ("输出 int() 截断", dict(trunc=True)),
            ("h + s/l", dict(q_h=True, q_sl=True)),
            ("全部（= 原代码）", dict(q_h=True, q_sl=True, trunc=True))]
    random.seed(seed)
    samples = []
    for _ in range(n):
        samples.append((random.randrange(256), random.randrange(256),
                        random.randrange(256),
                        random.choice([0, -28, 28, 90, -150]),
                        random.choice([0, 10, 25, 50, -25, -50, -80]),
                        random.choice([0, 10, 25, 60, -20, -60])))
    print("\n量化项对结果的贡献（相对全浮点，单位=8 位码）：")
    for label, kw in rows:
        ds, signed = [], 0.0
        for (r, g, b, hue, sat, light) in samples:
            a = _variant(r, g, b, hue, sat, light)
            c = _variant(r, g, b, hue, sat, light, **kw)
            d = [y - x for x, y in zip(a, c)]
            ds.extend(d)
            signed += sum(d)
        ds_abs = sorted(abs(x) for x in ds)
        print("  %-18s max=%2d  p99=%2d  median=%.1f  平均偏 %+.2f"
              % (label, ds_abs[-1], ds_abs[int(len(ds_abs) * 0.99)],
                 ds_abs[len(ds_abs) // 2], signed / len(ds)))


if __name__ == "__main__":
    print("示例 r,g,b=100,30,10 light=+60:",
          ref_literal(100, 30, 10, 0, 0, 60),
          "(浮点", [round(x, 2) for x in ref_float(100, 30, 10, 0, 0, 60)], ")")
    print("示例 sat=-40:",
          ref_literal(100, 30, 10, 0, -40, 0),
          "  sat=+40:",
          ref_literal(100, 30, 10, 0, 40, 0))
    report()
    breakdown()
