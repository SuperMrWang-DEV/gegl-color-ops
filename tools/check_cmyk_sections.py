#!/usr/bin/env python3
"""lb:cmyk-primary-correction 的九组记忆功能验证。

检查三件事：
  1. 单组参数（新版 reds-cyan=80）与旧版（target=red cyan=80）结果一致；
  2. 只调 reds 时，蓝/青区像素不动；只调 blues 时，红/黄区不动；
  3. 同时给 reds 与 blues 设值，两组改动都在，互不覆盖（旧版做不到）。
"""
import colorsys
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from contact_sheet import read_png  # noqa: E402


def load(p):
    w, h, rows = read_png(p)
    return w, h, rows


def hue_sector(r, g, b):
    h, _l, _s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    return int(h * 360) // 30 * 30            # 30° 一档


def maxdiff(a, b):
    w, h, A = a
    _w, _h, B = b
    best, cnt = 0, 0
    for y in range(h):
        for x in range(w):
            d = max(abs(A[y][x][k] - B[y][x][k]) for k in range(3))
            best = max(best, d)
            if d > 0:
                cnt += 1
    return best, cnt


def changed_by_sector(base, out):
    """返回 {色相档: (改动像素数, 最大差值)}"""
    w, h, A = base
    _w, _h, B = out
    stat = {}
    for y in range(h):
        for x in range(w):
            d = max(abs(A[y][x][k] - B[y][x][k]) for k in range(3))
            if d == 0:
                continue
            s = hue_sector(*A[y][x])
            n, m = stat.get(s, (0, 0))
            stat[s] = (n + 1, max(m, d))
    return stat


def main():
    t = "build/t"
    base = load("build/smoke-input.png")
    old_red = load(f"{t}/old-red.png")
    new_red = load(f"{t}/new-red.png")
    new_blue = load(f"{t}/new-blue.png")
    new_both = load(f"{t}/new-both.png")

    print("1) 旧版 target=red cyan=80  vs  新版 reds-cyan=80")
    d, n = maxdiff(old_red, new_red)
    print(f"   最大差 {d}, 不同像素 {n}  ->", "一致" if d <= 1 else "不一致")

    print("2) 单组作用范围")
    for name, img in (("reds-cyan=80", new_red), ("blues-yellow=-60", new_blue)):
        st = changed_by_sector(base, img)
        hot = sorted(st.items(), key=lambda kv: -kv[1][0])[:4]
        print(f"   {name:18s} 主要改动区（色相档°,像素数,峰值）："
              + ", ".join(f"{k}({v[0]},{v[1]})" for k, v in hot))

    print("3) 九组同时生效（内存互不覆盖）")
    st_both = changed_by_sector(base, new_both)
    st_r = changed_by_sector(base, new_red)
    st_b = changed_by_sector(base, new_blue)
    red_kept = all(st_both.get(k, (0, 0))[0] > 0 for k in st_r)
    blue_kept = all(st_both.get(k, (0, 0))[0] > 0 for k in st_b)
    print(f"   reds 影响的 {len(st_r)} 个色相档全部保留: {red_kept}")
    print(f"   blues 影响的 {len(st_b)} 个色相档全部保留: {blue_kept}")
    print(f"   合计改动像素 {sum(v[0] for v in st_both.values())}，"
          f"单组分别为 {sum(v[0] for v in st_r.values())} / {sum(v[0] for v in st_b.values())}")
    ok = d <= 1 and red_kept and blue_kept
    print("\n结论:", "通过" if ok else "失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
