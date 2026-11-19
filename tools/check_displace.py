# -*- coding: utf-8 -*-
"""数值回归：置换算子 lb:displace。

    python tools/check_displace.py

用 build/auxrun 建图（input + aux 各接一张图），逐像素核对「输出这个位置
取的是源图哪个位置」。

测试图每个像素的 R 编码列号、G 编码行号（10 + 60×坐标），所以从结果颜色
就能反推它抽的是哪个源像素；黑（0,0,0）表示采到了图外，用来区分「夹住
边缘」和「环绕」。

    python tools/check_displace.py -v     # 连通过项也打出来
"""
import os
import struct
import subprocess
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, "build", "displace-check")
RUNNER = os.path.join(ROOT, "build", "auxrun.exe")
SYS_OPS = r"D:/fastsoftware/GIMP 3/lib/gegl-0.4"
GIMP_BIN = r"D:/fastsoftware/GIMP 3/bin"

W = H = 4
STEP = 60
BASE = 10

VERBOSE = "-v" in sys.argv


def write_png(path, pixels, w, h):
    """pixels 是 w*h 个 (r,g,b,a)。"""
    px = b"".join(bytes(p) for p in pixels)
    raw = b"".join(b"\x00" + px[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9))
                + chunk(b"IEND", b""))


def read_all(path):
    """返回 (width, height, [(r,g,b,a), ...])，8bit 归一。"""
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
    bpp = ch * (depth // 8)
    stride = w * bpp

    prev = bytearray(stride)
    out = []
    pos = 0
    for _ in range(h):
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

        for k in range(w):
            vals = list(line[k * bpp:(k + 1) * bpp])
            if depth == 16:
                vals = [vals[j * 2] * 256 + vals[j * 2 + 1] for j in range(ch)]
                vals = [round(v * 255.0 / 65535.0) for v in vals]
            while len(vals) < 4:
                vals.append(255)
            out.append(tuple(vals[:4]))
    return w, h, out


def write_base(path):
    write_png(path, [(BASE + x * STEP, BASE + y * STEP, 0, 255)
                     for y in range(H) for x in range(W)], W, H)


def write_flat(path, v, a=255):
    write_png(path, [(v, v, v, a)] * (W * H), W, H)


def write_vec(path, rv, gv):
    write_png(path, [(rv, gv, 0, 255)] * (W * H), W, H)


def run(dst, src, aux, **params):
    env = dict(os.environ)
    env["GEGL_PATH"] = ((os.environ.get("OPS_DIR") or os.path.join(ROOT, "build"))
                        + ";" + SYS_OPS)
    env["PATH"] = GIMP_BIN + ";" + env.get("PATH", "")
    cmd = [RUNNER, dst, "lb:displace", src, aux]
    cmd += ["%s=%s" % (k.replace("_", "-"), v) for k, v in params.items()]
    r = subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    if not os.path.exists(dst):
        sys.exit("✗ 渲染失败：\n%s" % r.stdout.decode("utf-8", "replace"))


def decode(px):
    """把结果颜色还原成源坐标；越界（黑）返回 None。"""
    r, g = px[0], px[1]
    if r == 0 and g == 0:
        return None
    return (round((r - BASE) / float(STEP)), round((g - BASE) / float(STEP)))


def expect(dst, samples):
    """samples: {(x, y): (src_x, src_y) 或 None}。"""
    w, h, px = read_all(dst)
    if (w, h) != (W, H):
        return ["尺寸 %dx%d，期望 %dx%d" % (w, h, W, H)]
    bad = []
    for (x, y), want in samples.items():
        got = decode(px[y * w + x])
        if got != want:
            bad.append("(%d,%d) 取到 %s，期望 %s" % (x, y, got, want))
    return bad


CASES = []


def case(name, aux_file, params, samples):
    CASES.append((name, aux_file, params, samples))


def main():
    os.makedirs(TMP, exist_ok=True)
    base = os.path.join(TMP, "base.png")
    write_base(base)
    flat_black = os.path.join(TMP, "black.png")
    flat_white = os.path.join(TMP, "white.png")
    flat_grey = os.path.join(TMP, "grey.png")
    vec_xy = os.path.join(TMP, "vec.png")
    clear_white = os.path.join(TMP, "clear-white.png")
    write_flat(flat_black, 0)
    write_flat(flat_white, 255)
    write_flat(flat_grey, 128)
    write_flat(clear_white, 255, 0)   # 全透明但 RGB 为白
    write_vec(vec_xy, 255, 0)     # R=白 → +X，G=黑 → -Y

    # 黑图 = 负方向满量，白图 = 正方向满量，中灰 = 不动
    case("零位移恒等", flat_grey, dict(amount_x=1), {
        (x, y): (x, y) for y in range(H) for x in range(W)})
    case("黑图向左 1 像素（环绕）", flat_black,
         dict(amount_x=1, abyss="loop"), {(0, 0): (3, 0), (1, 2): (0, 2)})
    case("白图向右 1 像素（环绕）", flat_white,
         dict(amount_x=1, abyss="loop"), {(0, 0): (1, 0), (3, 1): (0, 1)})
    case("边缘改为夹住", flat_black,
         dict(amount_x=1, abyss="clamp"), {(0, 0): (0, 0), (1, 0): (0, 0)})
    case("矢量场 X 与 Y 独立", vec_xy,
         dict(amount_x=1, amount_y=1, abyss="loop"),
         {(0, 0): (1, 3), (2, 1): (3, 0)})
    case("单通道模式（只走 X）", flat_white,
         dict(map_mode="scalar", map_channel="red", amount_x=1, amount_y=1,
              abyss="clamp"), {(0, 0): (1, 1), (1, 1): (2, 2)})
    case("百分比单位（长边 4 → 1 像素）", flat_white,
         dict(units="percent", amount_x=25, abyss="clamp"),
         {(0, 0): (1, 0), (2, 2): (3, 2)})
    case("白场外推（3 倍位移）", flat_white,
         dict(amount_x=1, midpoint=0.25, white_point=0.5, abyss="clamp"),
         {(0, 0): (3, 0), (1, 1): (3, 1)})
    case("默认不乘 alpha（透明位移图仍然生效）", clear_white,
         dict(amount_x=1, abyss="clamp"), {(0, 0): (1, 0)})
    case("勾上 alpha 权重后透明区不动", clear_white,
         dict(amount_x=1, alpha_weight="true", abyss="clamp"),
         {(0, 0): (0, 0)})

    # 位移图比主图小、还带偏移：覆盖不到的像素必须原样，不能被硬移
    case("位移图只盖右半边", flat_black,
         dict(amount_x=1, abyss="loop", **{"aux-x": 2}),
         {(0, 0): (0, 0), (1, 1): (1, 1), (2, 0): (1, 0)})

    fails = 0
    for name, aux, params, samples in CASES:
        dst = os.path.join(TMP, "out.png")
        if os.path.exists(dst):
            os.remove(dst)
        run(dst, base, aux, **params)
        bad = expect(dst, samples)
        if bad:
            fails += 1
            print("FAIL  %s" % name)
            for b in bad:
                print("        " + b)
        elif VERBOSE:
            print("ok    %s" % name)

    total = len(CASES)
    print("\n%d/%d 通过" % (total - fails, total))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
