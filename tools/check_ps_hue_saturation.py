# -*- coding: utf-8 -*-
"""验收 lb:ps-hue-saturation：与规范参考（tools/ref_ps_hue_sat.py 浮点版）逐像素对拍。

    python tools/check_ps_hue_saturation.py        # 默认 4096 色 × 27 组参数
    python tools/check_ps_hue_saturation.py 512    # 抽少量颜色

判定标准：单通道绝对偏差 ≤1 码（8 位刻度）。这一码只有一个来源 —— 8 位
PNG 的输出量化，与算法无关；任何 >1 码的偏差都说明实现和公式不一致。
原代码自带的 h/s/l 取整会把偏差抬到最大 9 码，本算子不做那层取整。
"""
import os
import random
import struct
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ref_ps_hue_sat import ref_float

TMP = os.path.join(os.path.dirname(HERE), "build", "hs-check")
GEGL = os.environ.get("GEGL", r"D:/fastsoftware/GIMP 3/bin/gegl.exe")
SYS_OPS = r"D:/fastsoftware/GIMP 3/lib/gegl-0.4"

# 覆盖两端与中段：0 / ±10 / ±40 / ±100 与色相 ±180
COMBOS = [
    (0, 0, 0), (0, 0, 60), (0, 0, -60), (0, 0, 100), (0, 0, -100),
    (0, 40, 0), (0, 100, 0), (0, -40, 0), (0, -100, 0), (0, 90, 20), (0, -90, -20),
    (28, 0, 0), (-28, 0, 0), (120, 0, 0), (180, 0, 0), (-180, 0, 0),
    (28, 50, 0), (28, -50, 0), (90, 30, 40), (-90, -30, -40),
    (0, 50, 50), (0, -50, -50), (0, 50, -50), (0, -50, 50),
    (180, 100, 100), (45, 25, 25), (15, -75, 35),
]


def write_png(path, rgb, w, h):
    raw = b"".join(b"\x00" + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def read_png(path):
    """返回 (w, h, depth, ctype, bytes[rows])，只处理本项目用到的 8/16 位。"""
    data = open(path, "rb").read()
    i, idat, w, h, depth, ctype = 8, b"", 0, 0, 0, 0
    while i < len(data):
        ln = struct.unpack(">I", data[i:i + 4])[0]
        tag = data[i + 4:i + 8]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", data[i + 8:i + 18])
        elif tag == b"IDAT":
            idat += data[i + 8:i + 8 + ln]
        i += 12 + ln
    raw = zlib.decompress(idat)
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    bpp = ch * (depth // 8)
    stride = w * bpp
    out, prev, pos = [], bytearray(stride), 0
    for _ in range(h):
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ft == 1:
                line[x] = (line[x] + a) & 0xFF
            elif ft == 2:
                line[x] = (line[x] + b) & 0xFF
            elif ft == 3:
                line[x] = (line[x] + (a + b) // 2) & 0xFF
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        out.append(bytes(line))
        prev = line
    return w, h, depth, ctype, out


def render(src, dst, hue, sat, light):
    env = dict(os.environ)
    env["GEGL_PATH"] = ";".join(
        [os.path.join(os.path.dirname(HERE), "build"), SYS_OPS])
    cmd = [GEGL, src, "-o", dst, "--", "lb:ps-hue-saturation",
           "hue=%d" % hue, "saturation=%d" % sat, "lightness=%d" % light]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("gegl 渲染失败 %s\n%s\n%s" % (cmd, r.stdout, r.stderr))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4096
    os.makedirs(TMP, exist_ok=True)
    random.seed(20261115)
    colors = [(random.randrange(256), random.randrange(256), random.randrange(256))
              for _ in range(n)]
    # 补几个角点：纯黑/白/灰/三原色
    colors[:8] = [(0, 0, 0), (255, 255, 255), (128, 128, 128), (255, 0, 0),
                  (0, 255, 0), (0, 0, 255), (0, 0, 0), (1, 1, 1)]
    w = 64
    h = (n + w - 1) // w
    flat = b"".join(bytes(c) for c in colors)
    flat += bytes(w * h * 3 - len(flat))
    src = os.path.join(TMP, "src.png")
    write_png(src, flat, w, h)

    worst_all = 0
    for (hue, sat, light) in COMBOS:
        dst = os.path.join(TMP, "out.png")
        render(src, dst, hue, sat, light)
        ow, oh, depth, ctype, rows = read_png(dst)
        assert (ow, oh) == (w, h), "尺寸不一致"
        step = 3 * (depth // 8)
        nch = {2: 3, 6: 4}[ctype] * (depth // 8)   # 输出是 16 位 RGBA
        diffs, moved = [], 0.0
        for y in range(h):
            row = rows[y]
            for x in range(w):
                idx = y * w + x
                if idx >= n:
                    break
                if depth == 16:
                    got = [(row[x * nch + k * 2] * 256 + row[x * nch + k * 2 + 1]) / 257.0
                           for k in range(3)]
                else:
                    got = [float(row[x * nch + k]) for k in range(3)]
                # 与输入的平均差：证明算子真的动了像素，不是把原图读回来
                moved += sum(abs(g - c) for g, c in zip(got, colors[idx])) / 3.0
                exp = ref_float(*colors[idx], hue=hue, sat=sat, light=light)
                diffs.append(max(abs(g - e) for g, e in zip(got, exp)))
        diffs.sort()
        mx = diffs[-1]
        worst_all = max(worst_all, mx)
        print("  h=%4d s=%4d l=%4d   max=%.3f  p99=%.3f  median=%.3f  Δin=%6.1f"
              % (hue, sat, light, mx, diffs[int(len(diffs) * 0.99)],
                 diffs[len(diffs) // 2], moved / min(n, w * h)))

    print("\n全部 %d 组 × %d 色：最大偏差 %.2f 码（门槛 1.0）"
          % (len(COMBOS), n, worst_all))
    if worst_all > 1.0001:
        raise SystemExit("✗ 与参考公式不一致")
    print("✓ 与参考公式一致")


if __name__ == "__main__":
    main()
