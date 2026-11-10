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


def read_first_pixel(path):
    """返回首个像素的 8bit RGB（结果可能是 8 或 16 位，统一归一到 0..255）。"""
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
    stride = w * ch * bpp_ch

    # 逐行反滤波（GEGL 存盘时常用 Paeth），只需要首行但整行都要还原
    prev = bytearray(stride)
    pos = 0
    line = bytearray(stride)
    for _y in range(h):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        for x in range(stride):
            a = line[x - ch * bpp_ch] if x >= ch * bpp_ch else 0
            b = prev[x]
            c = prev[x - ch * bpp_ch] if x >= ch * bpp_ch else 0
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
        break

    px = list(line[:ch * bpp_ch])
    if depth == 16:
        return [px[k * 2] * 256 + px[k * 2 + 1] for k in range(ch)], 16
    return list(px), 8


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
    # (说明, 算子, 输入色, 参数, 期望 8bit 值, 容差)
    ("黑白：纯红 red=40 yellow=60 → 40%",
     "lb:rgb-domain-grayscale", (255, 0, 0),
     dict(red=40, yellow=60, green=40, cyan=60, blue=20, magenta=80), 102, 2),
    ("曝光：中灰 +1.0 EV → 一档",
     "lb:exposure", (128, 128, 128), dict(exposure=1.0), 176, 3),
    ("色相/饱和度：零参数恒等",
     "lb:hue-saturation", (200, 120, 60), dict(), 200, 2),
    ("自然饱和度：零参数恒等",
     "lb:vibrance-hyper", (200, 120, 60), dict(), 200, 2),
]


def main():
    if not os.path.exists(GEGL):
        sys.exit("✗ 找不到 gegl 可执行文件：%s（可用 GEGL 环境变量指定）" % GEGL)
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)

    bad = 0
    print("%-34s %-8s %-8s %s" % ("用例", "实测", "期望", "结果"))
    for i, (label, op, rgb, params, expect, tol) in enumerate(CASES):
        src = os.path.join(TMP, "in%d.png" % i)
        dst = os.path.join(TMP, "out%d.png" % i)
        write_png(src, rgb)
        run(op, src, dst, **params)
        px, depth = read_first_pixel(dst)
        got = to8(px, depth)[0]
        ok = abs(got - expect) <= tol
        bad += 0 if ok else 1
        print("%-34s %-8.0f %-8d %s" % (label, got, expect, "OK" if ok else "FAIL"))

    print("\n%d/%d 通过" % (len(CASES) - bad, len(CASES)))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
