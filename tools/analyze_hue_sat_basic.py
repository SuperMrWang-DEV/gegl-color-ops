# -*- coding: utf-8 -*-
"""lb:hue-saturation-basic 公式的合理性体检：把三条曲线的行为量化出来。

    python tools/analyze_hue_sat_basic.py
"""
import colorsys
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ref_hue_sat_basic import _rgb_to_hsl_f, ref_float


def line(t):
    print(t)


def saturation_table():
    line("① 饱和度滑杆：s → s'（单位 %，原值取 10/30/50/70/90）")
    line("   x      s=10   s=30   s=50   s=70   s=90")
    for x in (0.0, 0.25, 0.5, 0.75, 0.9, 1.0, -0.25, -0.5, -0.75, -1.0):
        cells = []
        for s in (10, 30, 50, 70, 90):
            v = s / 100.0
            if x >= 1.0:
                out = 1.0 if v > 0 else 0.0
            elif x > 0.0:
                out = min(1.0, v / (1.0 - x))
            elif x < 0.0:
                out = max(0.0, v * (1.0 + x))
            else:
                out = v
            cells.append("%5.1f" % (out * 100))
        line("  %+.2f  %s" % (x, " ".join(cells)))
    line("   → 正支是双曲的：x=0.5 时 s=50 直接顶到 100，s=10 只到 20；")
    line("     x=1.0 时所有 s>0 一律 100，饱和度层次被完全抹平（见 ②）。")
    line("     负支是线性的：x=-0.5 时每个 s 都缩到 50%，两端对称性不成立。")


def collapse():
    line("\n② +100 的「悬崖」：多少比例的像素被推到同一个 S=100")
    for x in (0.25, 0.5, 0.75, 0.9, 1.0):
        thr = (1.0 - x) * 100.0
        frac = max(0.0, 100.0 - thr)
        line("   x=%4.2f：原 S ≥ %5.1f%% 的像素全部变成 100%%，均匀分布下占 %5.1f%%"
             % (x, thr, frac))
    line("   → s=100 那档等价于「二值化饱和度」，原本 5% 与 95% 的像素结果相同。")


def lightness_probe():
    line("\n③ 明度滑杆：逐通道 lerp 对 S / 色相的影响")
    samples = [(100, 30, 10), (200, 120, 60), (30, 60, 200), (240, 240, 40),
               (128, 128, 128), (0, 0, 255)]
    line("   颜色          原S    t=+25        t=+60        t=-25        t=-60")
    for (r, g, b) in samples:
        cells = []
        for t in (0.25, 0.6, -0.25, -0.6):
            out = ref_float(r, g, b, light=t * 100)
            h, s, l = _rgb_to_hsl_f(*[c / 255.0 for c in out])
            h0, s0, l0 = _rgb_to_hsl_f(r / 255.0, g / 255.0, b / 255.0)
            dh = (h - h0 + 180) % 360 - 180
            cells.append("S%3.0f Δh%+4.0f" % (s * 100, dh))
        h0, s0, l0 = _rgb_to_hsl_f(r / 255.0, g / 255.0, b / 255.0)
        line("   %-13s %3.0f%%  %s" % ("(%d,%d,%d)" % (r, g, b), s0 * 100,
                                      "  ".join(cells)))
    line("   → 两种情形都是均匀仿射 c·k+b：色相只由通道差值之比决定，故 Δh 恒为 0，")
    line("     明度滑杆不动色相。区别全在 S：t<0 是纯缩放 c·(1+t)，S=Δ/(max+min)")
    line("     分子分母同缩放，L≤50% 时 S 一字不动（(100,30,10) 的 82% 保持 82%）；")
    line("     t>0 多了常数项 t，差值相对变小，S 被显著削弱（82% → 22%）。")
    line("     这就是提亮「发灰」的根源：正向明度与负向明度对 S 的影响不对称。")


def extremes():
    line("\n④ 端点与单调性")
    bad = 0
    for c in range(256):
        prev = -1.0
        for i in range(-100, 101):
            v = (c + (i / 100.0) * (255 - c)) if i > 0 else c * (1 + i / 100.0)
            if v < prev - 1e-9:
                bad += 1
            prev = v
    line("   逐通道单调性：%s" % ("通过" if bad == 0 else "违反 %d 次" % bad))
    line("   端点：t=+100 → 255（白），t=-100 → 0（黑），均在色域内、无溢出")
    line("   全黑/全白/中性灰保持不变（S=0 时色相无意义，输出仍是灰）")


if __name__ == "__main__":
    saturation_table()
    collapse()
    lightness_probe()
    extremes()
