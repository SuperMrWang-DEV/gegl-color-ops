# -*- coding: utf-8 -*-
"""把若干测试图拼成带标签的对照表（自包含：不依赖 PIL / ImageMagick）。
用法: python tools/contact_sheet.py out.png build/smoke/*.png [--cols 4] [--scale 2]
标签取图片文件名（大写，- 转空格）。
"""
import zlib, struct, os, sys

FONT = {
 'A':"01110/10001/10001/11111/10001/10001/10001", 'B':"11110/10001/11110/10001/10001/10001/11110",
 'C':"01110/10001/10000/10000/10000/10001/01110", 'D':"11110/10001/10001/10001/10001/10001/11110",
 'E':"11111/10000/11110/10000/10000/10000/11111", 'F':"11111/10000/11110/10000/10000/10000/10000",
 'G':"01110/10001/10000/10111/10001/10001/01111", 'H':"10001/10001/11111/10001/10001/10001/10001",
 'I':"11111/00100/00100/00100/00100/00100/11111", 'J':"00111/00010/00010/00010/10010/10010/01100",
 'K':"10001/10010/10100/11000/10100/10010/10001", 'L':"10000/10000/10000/10000/10000/10000/11111",
 'M':"10001/11011/10101/10101/10001/10001/10001", 'N':"10001/11001/10101/10011/10001/10001/10001",
 'O':"01110/10001/10001/10001/10001/10001/01110", 'P':"11110/10001/10001/11110/10000/10000/10000",
 'Q':"01110/10001/10001/10001/10101/10010/01101", 'R':"11110/10001/10001/11110/10100/10010/10001",
 'S':"01111/10000/10000/01110/00001/00001/11110", 'T':"11111/00100/00100/00100/00100/00100/00100",
 'U':"10001/10001/10001/10001/10001/10001/01110", 'V':"10001/10001/10001/10001/10001/01010/00100",
 'W':"10001/10001/10001/10101/10101/11011/10001", 'X':"10001/01010/00100/00100/00100/01010/10001",
 'Y':"10001/01010/00100/00100/00100/00100/00100", 'Z':"11111/00001/00010/00100/01000/10000/11111",
 '0':"01110/10001/10011/10101/11001/10001/01110", '1':"00100/01100/00100/00100/00100/00100/01110",
 '2':"01110/10001/00001/00110/01000/10000/11111", '3':"11110/00001/01110/00001/00001/10001/01110",
 '4':"00010/00110/01010/10010/11111/00010/00010", '5':"11111/10000/11110/00001/00001/10001/01110",
 '6':"01110/10000/11110/10001/10001/10001/01110", '7':"11111/00001/00010/00100/01000/01000/01000",
 '8':"01110/10001/01110/10001/10001/10001/01110", '9':"01110/10001/10001/01111/00001/00001/01110",
 '+':"00000/00100/00100/11111/00100/00100/00000", '-':"00000/00000/00000/11111/00000/00000/00000",
 '.':"00000/00000/00000/00000/00000/01100/01100", ' ':"00000/00000/00000/00000/00000/00000/00000",
}

def read_png(path):
    data = open(path, "rb").read()
    pos, idat, w, h, bd, ct = 8, b"", 0, 0, 0, 0
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos+4])[0]
        tag, body = data[pos+4:pos+8], data[pos+8:pos+8+ln]
        if tag == b"IHDR": w, h, bd, ct = struct.unpack(">IIBB", body[:10])
        elif tag == b"IDAT": idat += body
        pos += 12 + ln
    nch = 3 if ct == 2 else 4
    bps = bd // 8; bpp = nch * bps
    raw = zlib.decompress(idat); stride = w * bpp
    out, prev, p = [], bytearray(stride), 0
    for _ in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p+stride]); p += stride
        if f == 1:
            for i in range(bpp, stride): line[i] = (line[i] + line[i-bpp]) & 255
        elif f == 2:
            for i in range(stride): line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                b, c = prev[i], (prev[i-bpp] if i >= bpp else 0)
                pa, pb, pc = abs(b-c), abs(a-c), abs(a+b-2*c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        row = []
        for i in range(w):
            vals = []
            for k in range(nch):
                off = i*bpp + k*bps
                v = line[off] if bps == 1 else (line[off] << 8 | line[off+1])
                vals.append(v if bps == 1 else v * 255 // 65535)
            row.append(vals[:3] if len(vals) >= 3 else vals + [255]*(3-len(vals)))
        out.append(row); prev = line
    return w, h, out

def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

def draw_text(rows, x0, y0, s, scale=2, color=(20, 20, 20)):
    cx = x0
    for ch in s.upper():
        g = FONT.get(ch, FONT[' ']).split('/')
        for ry, line in enumerate(g):
            for rx, bit in enumerate(line):
                if bit == '1':
                    for dy in range(scale):
                        for dx in range(scale):
                            px, py = cx + rx*scale + dx, y0 + ry*scale + dy
                            if 0 <= py < len(rows) and 0 <= px*3 < len(rows[py]):
                                rows[py][px*3:px*3+3] = bytes(color)
        cx += 6 * scale

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    cols, scale = 4, 2
    for a in sys.argv[1:]:
        if a.startswith('--cols'):  cols = int(a.split('=')[-1] if '=' in a else 4)
        if a.startswith('--scale'): scale = int(a.split('=')[-1] if '=' in a else 2)
    if len(args) < 2:
        print(__doc__); return 1
    out, paths = args[0], args[1:]
    imgs = []
    for p in paths:
        w, h, im = read_png(p)
        small = [bytearray(b"".join(bytes(im[y*scale][x*scale]) for x in range(w//scale))) for y in range(h//scale)]
        label = os.path.basename(p)[:-4].upper().replace('-', ' ').replace('_', ' ')
        imgs.append((label, small, w//scale, h//scale))
    TW, TH = imgs[0][2], imgs[0][3]
    BAR, PAD = 18, 8
    nrows = (len(imgs) + cols - 1) // cols
    W = cols * (TW + PAD) + PAD
    H = nrows * (TH + BAR + PAD) + PAD
    sheet = [bytearray(bytes((250, 250, 250)) * W) for _ in range(H)]
    for idx, (label, small, tw, th) in enumerate(imgs):
        ox = PAD + (idx % cols) * (TW + PAD)
        oy = PAD + (idx // cols) * (TH + BAR + PAD)
        draw_text(sheet, ox, oy + 2, label)
        for y in range(min(th, TH)):
            sheet[oy + BAR + y][ox*3:(ox+tw)*3] = small[y]
    write_png(out, W, H, sheet)
    print("wrote", out, f"{W}x{H}  ({len(imgs)} 图)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
