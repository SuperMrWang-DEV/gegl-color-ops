# -*- coding: utf-8 -*-
"""数值回归：确认算子确实跑在「感知（伽马）域」，而不是线性光。

    python tools/check_gamma_domain.py

对纯色小图跑单算子，把结果和 PS 的期望值比对。早期版本把输入钉成
`RGBA float`（线性光），黑白会把纯红算成 170 而不是 102，曝光 +1EV 只到
148 而不是 176 —— 这个脚本就是防止那次回退。
"""
import os
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, "build", "gamma-check")
GEGL = os.environ.get("GEGL", r"D:/fastsoftware/GIMP 3/bin/gegl.exe")
SYS_OPS = r"D:/fastsoftware/GIMP 3/lib/gegl-0.4"


def write_png(path, rgb, w=4, h=4):
    raw = (b"\x00" + bytes(rgb) * w) * h

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9))
                + chunk(b"IEND", b""))


def read_pixels(path):
    """返回 (w, h, [[r,g,b], ...] 8bit, depth)。

    必须逐行全读：曾经只查首像素，漏掉过「无 alpha 图按 3 通道步长走 4 通道
    缓冲」的错位 bug —— 首像素永远是对的，往后累积偏移才是马赛克。
    """
    data = open(path, "rb").read()
    i, idat = 8, b""
    w = h = depth = ctype = 0
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
    bpp_ch = depth // 8
    bpp = ch * bpp_ch
    stride = w * bpp

    prev = bytearray(stride)
    pos = 0
    rows = []
    for _y in range(h):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ftype == 1:
                line[x] = (line[x] + a) & 0xFF
            elif ftype == 2:
                line[x] = (line[x] + b) & 0xFF
            elif ftype == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 0xFF
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 0xFF
        prev = line
        if depth == 16:
            rows.append([line[k * 2] * 256 + line[k * 2 + 1] for k in range(w * ch)])
        else:
            rows.append(list(line))
    return w, h, rows, depth


def to8(values, depth):
    return [v * 255.0 / 65535.0 if depth == 16 else v for v in values]


def run(op, src, dst, **params):
    env = dict(os.environ)
    env["GEGL_PATH"] = (os.environ.get("OPS_DIR") or
                        os.path.join(ROOT, "build")) + ";" + SYS_OPS
    cmd = [GEGL, src, "-o", dst, "--", op]
    cmd += ["%s=%s" % (k.replace("_", "-"), v) for k, v in params.items()]
    r = subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    if not os.path.exists(dst):
        sys.exit("✗ %s 渲染失败：\n%s" % (op, r.stdout.decode("utf-8", "replace")))
    return r


CASES = [
    # (说明, 算子, 输入色, 参数, 期望 8bit R 值, 容差)
    ("黑白：纯红 red=40 yellow=60 → 40%",
     "lb:rgb-domain-grayscale", (255, 0, 0),
     dict(red=40, yellow=60, green=40, cyan=60, blue=20, magenta=80), 102, 2),
    ("曝光：中灰 +1.0 EV → 一档",
     "lb:exposure", (128, 128, 128), dict(exposure=1.0), 176, 3),
    ("色相/饱和度：零参数恒等",
     "lb:hue-saturation", (200, 120, 60), dict(), 200, 2),
    ("自然饱和度：零参数恒等",
     "lb:vibrance-hyper", (200, 120, 60), dict(), 200, 2),
    # 通道混合器专测「无 alpha 图」：输入是 3 通道 PNG，若 process 按 3 个 float
    # 步长走 4 通道缓冲，首像素对、往后逐像素错位，整图呈马赛克。
    ("通道混合器：无 alpha 恒等",
     "lb:channel-mixer-plus", (200, 120, 60), dict(), 200, 2),
    ("通道混合器：R←G 互换",
     "lb:channel-mixer-plus", (200, 120, 60),
     dict(rr_gain=0, rg_gain=1, gr_gain=1, gg_gain=0), 120, 2),
    ("通道混合器：单色 0.3/0.6/0.1",
     "lb:channel-mixer-plus", (200, 120, 60),
     dict(monochrome=1, mono_r=0.3, mono_g=0.6, mono_b=0.1), 138, 2),
]


def main():
    if not os.path.exists(GEGL):
        sys.exit("✗ 找不到 gegl 可执行文件：%s（可用 GEGL 环境变量指定）" % GEGL)
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)

    bad = 0
    print("%-34s %-8s %-8s %s" % ("用例", "最差", "期望", "结果"))
    for i, (label, op, rgb, params, expect, tol) in enumerate(CASES):
        src = os.path.join(TMP, "in%d.png" % i)
        dst = os.path.join(TMP, "out%d.png" % i)
        write_png(src, rgb)
        run(op, src, dst, **params)
        w, h, rows, depth = read_pixels(dst)
        # 逐像素核对，不能用首像素（错位 bug 的首像素永远是对的）
        worst, worst_xy = None, None
        ch = len(rows[0]) // w if w else 0
        for y in range(h):
            for x in range(w):
                r = to8([rows[y][x * ch]], depth)[0]
                if worst is None or abs(r - expect) > abs(worst - expect):
                    worst, worst_xy = r, (x, y)
        ok = abs(worst - expect) <= tol
        bad += 0 if ok else 1
        print("%-34s %-8.0f %-8d %s%s"
              % (label, worst, expect, "OK" if ok else "FAIL",
                 "" if ok else "  @%s" % (worst_xy,)))

    print("\n%d/%d 通过" % (len(CASES) - bad, len(CASES)))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
