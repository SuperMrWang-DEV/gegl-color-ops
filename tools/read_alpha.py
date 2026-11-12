# -*- coding: utf-8 -*-
"""读 8/16 位 RGBA PNG 的 alpha，返回 (w, h, get(x, y) -> 0…255)。

GEGL CLI 输出的 PNG 是 16 位，按 8 位读会把误差算成几十码（踩过这个坑），
所以 alpha 一律走这里，别用只认 RGB 的 read_png。
"""
import struct
import zlib


def read_alpha(path):
    data = open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a png: %s' % path
    pos, idat = 8, []
    w = h = depth = ctype = 0
    while pos < len(data):
        ln = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', body[:10])
            assert body[12] == 0, 'interlaced png unsupported'
        elif tag == b'IDAT':
            idat.append(body)
        elif tag == b'IEND':
            break
    assert ctype in (4, 6), '无 alpha 通道: %s (ctype=%d)' % (path, ctype)

    nch = {4: 2, 6: 4}[ctype]
    bpp = nch * (depth // 8)
    stride = w * bpp
    raw = zlib.decompress(b''.join(idat))
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                if ft == 1:
                    line[i] = (line[i] + a) & 0xFF
                elif ft == 2:
                    line[i] = (line[i] + b) & 0xFF
                elif ft == 3:
                    line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
                elif ft == 4:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line

    scale = 257.0 if depth == 16 else 1.0

    def get(x, y):
        i = y * stride + x * bpp + (bpp - 1 if depth == 8 else bpp - 2)
        v = out[i] if depth == 8 else struct.unpack('>H', out[i:i + 2])[0]
        return v / scale

    return w, h, get
