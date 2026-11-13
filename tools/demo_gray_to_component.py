# -*- coding: utf-8 -*-
"""lb:gray-to-component 演示图：同一张灰度渐变，各模式各自的编码输出。

在 GIMP 控制台跑（需要 GEGL 里的 lb 算子）：

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \\
        --batch-interpreter=python-fu-eval \\
        -b "exec(open(r'<repo>/tools/demo_gray_to_component.py').read())" --quit

产物：build/demo-gtc/raw/*.png + build/demo-gtc/sheet.png（拼图）
"""

import array
import os
import struct
import zlib

import gi

gi.require_version('Gegl', '0.4')
from gi.repository import Gegl

Gegl.init()

FMT_RGB = "R'G'B'A float"
FMT_LAB = "CIE Lab alpha float"
FMT_GRAY = "YA float"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) \
    if '__file__' in globals() else os.getcwd()
for cand in (ROOT, os.path.dirname(ROOT), os.getcwd()):
    if os.path.exists(os.path.join(cand, 'ops', 'gray-to-component')):
        ROOT = cand
        break

OUT = os.path.join(ROOT, 'build', 'demo-gtc')
RAW = os.path.join(OUT, 'raw')
os.makedirs(RAW, exist_ok=True)

W, H = 512, 56


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b""))


def encode(mode, width, height, **props):
    """灰度水平渐变 → 算子 → RGB 像素（0-255）"""
    n = width * height
    grays = [(x / (width - 1.0)) for _y in range(height) for x in range(width)]
    a = array.array('f')
    for g in grays:
        a.extend([g, 1.0])
    gbuf = Gegl.Buffer.new(FMT_GRAY, 0, 0, width, height)
    gbuf.set(Gegl.Rectangle.new(0, 0, width, height), FMT_GRAY, a.tobytes())

    root = Gegl.Node.new()
    src = root.create_child("gegl:buffer-source")
    src.set_property("buffer", gbuf)
    op = root.create_child("lb:gray-to-component")
    op.set_property("mode", mode)
    for k, v in props.items():
        op.set_property(k.replace('_', '-'), v)
    src.connect_to("output", op, "input")

    out = Gegl.Buffer.new(FMT_LAB, 0, 0, width, height)
    op.blit_buffer(out, Gegl.Rectangle.new(0, 0, width, height), 0,
                   Gegl.AbyssPolicy.NONE)

    data = out.get(Gegl.Rectangle.new(0, 0, width, height), 1.0, FMT_RGB,
                   Gegl.AbyssPolicy.NONE)
    f = array.array('f')
    f.frombytes(data)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            i = (y * width + x) * 4
            row += bytes(int(min(max(f[i + c], 0.0), 1.0) * 255 + 0.5)
                         for c in range(3))
        rows.append(row)
    return rows


CASES = [
    ("01 hue", "hue", {}),
    ("02 saturation red", "saturation", {}),
    ("03 saturation cyan", "saturation", {"sat_hue": 210.0}),
    ("04 color sat100", "color", {}),
    ("05 color sat45", "color", {"color_sat": 45.0}),
    ("06 value", "value", {}),
    ("07 lightness cie-l", "lightness", {}),
    ("08 red channel", "red", {}),
    ("09 green channel", "green", {}),
    ("10 blue channel", "blue", {}),
    ("11 lch hue", "lch-hue", {}),
    ("12 lch chroma", "lch-chroma", {}),
]
# 未单列的两种：luminance 与 lightness、lch-color 与 lch-hue 的输出逐字节
# 相同（见 tools/check_gray_to_component.py 的 A 段），画出来是重复图

paths = []
for name, mode, props in CASES:
    rows = encode(mode, W, H, **props)
    p = os.path.join(RAW, name + ".png")
    write_png(p, W, H, rows)
    paths.append(p)
    print("  ✓ %s (%s)" % (os.path.basename(p), mode), flush=True)

print("产物目录: %s" % OUT, flush=True)
print("拼图: python tools/contact_sheet.py build/demo-gtc/sheet.png "
      "build/demo-gtc/raw/*.png --cols 1", flush=True)
