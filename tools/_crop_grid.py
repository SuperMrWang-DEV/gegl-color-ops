#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时小工具：把几张图按同一块区域裁出来放大，拼成一排对比。

用法：python tools/_crop_grid.py out.png box=x,y,w,h scale in1.png in2.png ...
每张图下面写文件名（只显示 basename）。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugin", "_shared"))

import ai_client as A


def load(path):
    w, h, ch, data = A.decode_png(open(path, "rb").read())
    if ch == 4:
        rgba = data
    elif ch == 3:
        rgba = bytearray(w * h * 4)
        for i in range(w * h):
            rgba[i * 4:i * 4 + 3] = data[i * 3:i * 3 + 3]
            rgba[i * 4 + 3] = 255
        rgba = bytes(rgba)
    else:
        raise SystemExit("只接受 RGB/RGBA：" + path)
    return w, h, rgba


def crop(img, box):
    w, h, rgba = img
    x, y, cw, chh = box
    x, y = max(0, x), max(0, y)
    cw, chh = min(cw, w - x), min(chh, h - y)
    out = bytearray(cw * chh * 4)
    for r in range(chh):
        s = ((y + r) * w + x) * 4
        out[r * cw * 4:(r + 1) * cw * 4] = rgba[s:s + cw * 4]
    return cw, chh, bytes(out)


def scale_nn(img, k):
    w, h, rgba = img
    nw, nh = int(w * k), int(h * k)
    out = bytearray(nw * nh * 4)
    xs = [min(w - 1, int(c / k)) for c in range(nw)]
    for r in range(nh):
        srow = min(h - 1, int(r / k)) * w
        base = r * nw * 4
        for c in range(nw):
            s = (srow + xs[c]) * 4
            out[base + c * 4:base + c * 4 + 4] = rgba[s:s + 4]
    return nw, nh, bytes(out)


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    out_path = sys.argv[1]
    box = tuple(int(v) for v in sys.argv[2].split("=", 1)[1].split(","))
    k = float(sys.argv[3])
    paths = sys.argv[4:]

    tiles = []
    for p in paths:
        tiles.append((os.path.basename(p), scale_nn(crop(load(p), box), k)))
    tw, th = tiles[0][1][0], tiles[0][1][1]
    gap, pad, lab = 12, 10, 26
    cols = len(tiles)
    W = cols * tw + (cols - 1) * gap + pad * 2
    H = th + pad * 2 + lab
    canvas = bytearray(b"\x20\x22\x26\xff" * (W * H))

    def blit(src, sw, sh, ox, oy):
        for r in range(sh):
            d = ((oy + r) * W + ox) * 4
            canvas[d:d + sw * 4] = src[r * sw * 4:(r + 1) * sw * 4]

    for i, (_name, (w, h, rgba)) in enumerate(tiles):
        ox = pad + i * (tw + gap)
        blit(rgba, w, h, ox, pad + lab - 6)
    # 标签用极简 5x7 点阵画不出来，写不了字就留空条，靠顺序说明
    open(out_path, "wb").write(A.rgba_png(W, H, bytes(canvas)))
    print("图 %d×%d → %s" % (W, H, out_path))
    print("顺序：" + " | ".join(n for n, _ in tiles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
