# -*- coding: utf-8 -*-
"""生成测试图：色相扫掠 + 4 档饱和度带 + 灰阶带 + 明度带。
用法: python tools/make_test_image.py [输出路径]   默认 build/smoke-input.png
"""
import zlib, struct, colorsys, os, sys

W, H = 600, 400

def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b""))

def hls(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return (int(r * 255 + .5), int(g * 255 + .5), int(b * 255 + .5))

rows = []
for y in range(H):
    row = bytearray()
    for x in range(W):
        if y < 240:                      # 色相 0-360，四档 HSL 饱和度，L 固定 0.5
            sat = [1.0, 0.65, 0.30, 0.08][y // 60]
            c = hls(x / W, 0.5, sat)
        elif y < 300:                    # 灰阶带（检验灰阶不被染色）
            g = int(255 * x / (W - 1)); c = (g, g, g)
        else:                            # 固定色相 30°，明度带
            c = hls(30 / 360, 0.12 + 0.76 * x / (W - 1), 0.9)
        row += bytes(c)
    rows.append(row)

out = sys.argv[1] if len(sys.argv) > 1 else "build/smoke-input.png"
write_png(out, W, H, rows)
print("wrote", out, f"{W}x{H}")
