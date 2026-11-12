# -*- coding: utf-8 -*-
"""数值回归：双输入算子（应用图像 / 计算）。

    python tools/check_blend.py

gegl 命令行只支持单输入，所以这里调用 build.sh 顺带编译出来的
build/auxrun 建图（input + aux 各接一张图）。每个用例的期望值都按 PS
的公式手算，容差 2/255（8bit 存储往返的量化误差）。

    python tools/check_blend.py -v     # 连通过项也打出来
"""
import os
import struct
import subprocess
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, "build", "blend-check")
RUNNER = os.path.join(ROOT, "build", "auxrun.exe")
SYS_OPS = r"D:/fastsoftware/GIMP 3/lib/gegl-0.4"
GIMP_BIN = r"D:/fastsoftware/GIMP 3/bin"


def write_png(path, rgba, w=4, h=4):
    """rgba 长度 3 时自动补不透明 alpha，统一写 RGBA。"""
    if len(rgba) == 3:
        rgba = tuple(rgba) + (255,)
    write_png_pixels(path, [rgba] * (w * h), w, h)


def write_png_pixels(path, pixels, w=4, h=4):
    """pixels 是 w*h 个 (r,g,b,a)，用来做「逐像素不同 alpha」的源层。"""
    px = b"".join(bytes(p) for p in pixels)
    raw = b"".join(b"\x00" + px[y * w * 4:(y + 1) * w * 4] for y in range(h))
    ctype = 6

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9))
                + chunk(b"IEND", b""))


def read_pixel(path, px=0, py=0):
    """返回 ((r,g,b[,a]), 位深)。结果可能是 8 或 16 位。"""
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
    pos = 0
    line = bytearray(stride)
    for y in range(h):
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
        if y == py:
            break

    off = px * bpp
    px_v = list(line[off:off + bpp])
    if depth == 16:
        return [px_v[k * 2] * 256 + px_v[k * 2 + 1] for k in range(ch)], 16
    return list(px_v), 8


def to8(values, depth):
    return [v * 255.0 / 65535.0 if depth == 16 else v for v in values]


def run(dst, op, src, aux, **params):
    env = dict(os.environ)
    env["GEGL_PATH"] = ((os.environ.get("OPS_DIR") or os.path.join(ROOT, "build"))
                        + ";" + SYS_OPS)
    env["PATH"] = GIMP_BIN + ";" + env.get("PATH", "")
    cmd = [RUNNER, dst, op, src, aux]
    cmd += ["%s=%s" % (k.replace("_", "-"), v) for k, v in params.items()]
    r = subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    if not os.path.exists(dst):
        sys.exit("✗ %s 渲染失败：\n%s" % (op, r.stdout.decode("utf-8", "replace")))


GRAY_IN = (128, 128, 128)
GRAY_AUX = (200, 200, 200)

# (说明, 算子, 输入, aux, 参数, 期望 RGB(A), 容差)
CASES = [
    ("应用图像 · 正常", "lb:apply-image", GRAY_IN, GRAY_AUX,
     dict(blend_mode="normal"), (200, 200, 200), 2),
    ("应用图像 · 正片叠底 128×200", "lb:apply-image", GRAY_IN, GRAY_AUX,
     dict(blend_mode="multiply"), (100, 100, 100), 2),
    ("应用图像 · 滤色", "lb:apply-image", GRAY_IN, GRAY_AUX,
     dict(blend_mode="screen"), (228, 228, 228), 2),
    ("应用图像 · 不透明度 50%", "lb:apply-image", GRAY_IN, GRAY_AUX,
     dict(blend_mode="normal", opacity=50), (164, 164, 164), 2),
    ("应用图像 · 遮罩取 aux 亮度", "lb:apply-image", GRAY_IN, GRAY_AUX,
     dict(blend_mode="normal", mask_enabled="true", mask_channel="luma"),
     (185, 185, 185), 2),
    ("应用图像 · 反相遮罩", "lb:apply-image", GRAY_IN, GRAY_AUX,
     dict(blend_mode="normal", mask_enabled="true", mask_channel="luma",
          invert_mask="true"), (144, 144, 144), 2),
    ("应用图像 · 只改红通道", "lb:apply-image", (200, 100, 50), GRAY_IN,
     dict(blend_mode="multiply", target_channel="red", source_channel="red"),
     (100, 100, 50), 2),
    ("应用图像 · 深色（整像素取 aux）", "lb:apply-image", (200, 100, 50),
     (100, 100, 100), dict(blend_mode="darker-color"), (100, 100, 100), 2),
    ("应用图像 · 变暗（逐通道，对照）", "lb:apply-image", (200, 100, 50),
     (100, 100, 100), dict(blend_mode="darken"), (100, 100, 50), 2),
    ("应用图像 · 色相（取 aux 色相）", "lb:apply-image", (255, 0, 0),
     (0, 0, 255), dict(blend_mode="hue"), (0, 0, 255), 2),
    ("应用图像 · 饱和度（aux 无饱和）", "lb:apply-image", (255, 0, 0),
     GRAY_IN, dict(blend_mode="saturation"), (255, 255, 255), 2),
    ("应用图像 · 明度（取 aux 明度）", "lb:apply-image", (255, 0, 0),
     GRAY_IN, dict(blend_mode="luminosity"), (128, 0, 0), 2),
    ("应用图像 · 保留透明（alpha=0 不动）", "lb:apply-image",
     (128, 128, 128, 0), (200, 200, 200, 255),
     dict(blend_mode="normal", preserve_transparency="true"),
     (128, 128, 128, 0), 2),

    ("计算 · 正片叠底出灰", "lb:calculations", GRAY_IN, GRAY_AUX,
     dict(blend_mode="multiply", output_mode="mask-gray"),
     (100, 100, 100, 255), 2),
    ("计算 · 正常 + 反相源 2", "lb:calculations", GRAY_IN, GRAY_AUX,
     dict(blend_mode="normal", invert_source2="true",
          output_mode="mask-gray"), (55, 55, 55, 255), 2),
    ("计算 · alpha 蒙版模式", "lb:calculations", GRAY_IN, GRAY_AUX,
     dict(blend_mode="multiply", output_mode="mask-alpha"),
     (100, 100, 100, 100), 2),

    # 通道枚举曾经整体错一位：默认 Luminance 实际读成蓝通道。灰像素取哪个
    # 通道都一样，所以上面三个用例全绿也发现不了，这里必须用彩色像素。
    # The channel enum used to be off by one: the default Luminance read the
    # blue channel. Grey pixels hide that, hence the colour cases below.
    ("计算 · 默认通道是亮度非蓝", "lb:calculations", (10, 10, 128), (200, 100, 50),
     dict(blend_mode="multiply"),
     (9, 9, 9, 255), 2),
    ("计算 · 通道 Red 取 R", "lb:calculations", (10, 10, 128), (200, 100, 50),
     dict(blend_mode="difference", source1_channel="red",
          source2_channel="red"), (190, 190, 190, 255), 2),
    ("计算 · 通道 Blue 取 B", "lb:calculations", (10, 10, 128), (200, 100, 50),
     dict(blend_mode="difference", source1_channel="blue",
          source2_channel="blue"), (78, 78, 78, 255), 2),
    ("计算 · 通道 Alpha", "lb:calculations", (10, 10, 128, 200),
     (200, 100, 50, 100), dict(blend_mode="difference",
                               source1_channel="alpha",
                               source2_channel="alpha"), (100, 100, 100, 255), 2),
]

# 尺寸 / 位置不匹配：源层比主图小、或者不在原点时，没盖到的像素必须原样
# 输出。之前 point composer 拿不到 aux 的 extent，界外被当成透明黑参与混
# 合——multiply 会把那里涂黑，normal 会把它擦成透明。
# (说明, 算子, 主图, 主图尺寸, aux, aux 尺寸, aux 偏移, 参数,
#  [(x, y, 期望 RGB), ...], 容差)
COVERAGE_CASES = [
    ("应用图像 · 源层比主图小", "lb:apply-image", (10, 10, 128), (4, 4),
     (200, 100, 50), (2, 2), (0, 0), dict(blend_mode="multiply"),
     [(0, 0, (8, 4, 25)), (1, 1, (8, 4, 25)),
      (2, 2, (10, 10, 128)), (3, 3, (10, 10, 128))], 2),
    ("应用图像 · 源层带偏移", "lb:apply-image", (10, 10, 128), (4, 4),
     (200, 100, 50), (2, 2), (1, 1), dict(blend_mode="normal"),
     [(0, 0, (10, 10, 128)), (1, 1, (200, 100, 50)),
      (2, 2, (200, 100, 50)), (3, 3, (10, 10, 128))], 2),
    ("应用图像 · 源层完全在界外", "lb:apply-image", (10, 10, 128), (4, 4),
     (200, 100, 50), (2, 2), (8, 8), dict(blend_mode="normal"),
     [(0, 0, (10, 10, 128)), (3, 3, (10, 10, 128))], 2),
]

# 源层的透明像素：extent 只说明「这块地方属于源层」，不说明「这块有像素」。
# 抠图 / 文字层的透明区 RGB 是 0，若照常参与 multiply 会把目标乘成纯黑——
# 表现为「相交区域里本不该动的地方也变了」。
# Transparent source pixels: the extent only says the area belongs to the
# source layer, not that it holds pixels. RGB 0 in a cut-out's holes would
# blacken the target under multiply.
# (说明, 主图, aux 逐像素, 尺寸, 参数, [(x, y, 期望 RGB), ...], 容差)
def _aux_with_hole():
    """4x4 源层，只有 (1,1) 有像素，其余 alpha=0（抠图 / 文字层的透明区）。"""
    px = [(0, 0, 0, 0)] * 16
    px[5] = (200, 100, 50, 255)
    return px


ALPHA_CASES = [
    ("应用图像 · 源层透明处不作用", "lb:apply-image", (10, 10, 128, 255),
     _aux_with_hole(), (4, 4), dict(blend_mode="normal"),
     [(1, 1, (200, 100, 50)), (0, 0, (10, 10, 128)),
      (2, 2, (10, 10, 128))], 2),
    ("应用图像 · 透明洞不被 multiply 涂黑", "lb:apply-image", (128, 128, 128, 255),
     _aux_with_hole(), (4, 4), dict(blend_mode="multiply"),
     [(1, 1, (100, 50, 25)), (0, 0, (128, 128, 128)),
      (2, 2, (128, 128, 128))], 2),
    ("应用图像 · 半透明源按覆盖率混合", "lb:apply-image", (128, 128, 128, 255),
     [(200, 100, 50, 128)] * 16, (4, 4), dict(blend_mode="normal"),
     [(0, 0, (164, 114, 89))], 2),

    # 计算输出的是蒙版，没有「原图」可保留：源 2 透明处直接给 0（不选中），
    # 半透明按覆盖率衰减。计算默认通道是 Luminance。
    # Calculations outputs a mask with no target to preserve, so source-2
    # holes come out 0 (not selected) and half-transparent pixels scale down.
    ("计算 · 源层透明处蒙版为 0", "lb:calculations", (128, 128, 128, 255),
     _aux_with_hole(), (4, 4), dict(blend_mode="multiply"),
     [(1, 1, (59, 59, 59)), (0, 0, (0, 0, 0)),
      (2, 2, (0, 0, 0))], 2),
    ("计算 · 半透明源按覆盖率衰减", "lb:calculations", (128, 128, 128, 255),
     [(200, 100, 50, 128)] * 16, (4, 4), dict(blend_mode="multiply"),
     [(0, 0, (30, 30, 30))], 2),
]


def main():
    verbose = "-v" in sys.argv
    if not os.path.exists(RUNNER):
        sys.exit("✗ 找不到 %s，先跑 ./build.sh" % RUNNER)

    os.makedirs(TMP, exist_ok=True)
    bad = 0

    print("%-38s %-18s %-18s %s" % ("用例", "实测", "期望", "结果"))
    for i, (label, op, cin, caux, params, expect, tol) in enumerate(CASES):
        src = os.path.join(TMP, "in%d.png" % i)
        aux = os.path.join(TMP, "aux%d.png" % i)
        dst = os.path.join(TMP, "out%d.png" % i)
        write_png(src, cin)
        write_png(aux, caux)
        if os.path.exists(dst):
            os.remove(dst)
        run(dst, op, src, aux, **params)

        px, depth = read_pixel(dst)
        got = to8(px, depth)
        n = min(len(got), len(expect))
        ok = all(abs(got[k] - expect[k]) <= tol for k in range(n))
        bad += 0 if ok else 1
        if ok and not verbose:
            continue
        print("%-38s %-18s %-18s %s" % (
            label,
            " ".join("%.0f" % v for v in got),
            " ".join(str(v) for v in expect),
            "OK" if ok else "FAIL"))

    ok_n = len(CASES) - bad

    # ---- 尺寸 / 位置覆盖 ----
    for i, (label, op, cin, csize, caux, asize, aoff, params, probes,
            tol) in enumerate(COVERAGE_CASES):
        src = os.path.join(TMP, "cin%d.png" % i)
        aux = os.path.join(TMP, "caux%d.png" % i)
        dst = os.path.join(TMP, "cout%d.png" % i)
        write_png(src, cin, csize[0], csize[1])
        write_png(aux, caux, asize[0], asize[1])
        if os.path.exists(dst):
            os.remove(dst)
        run(dst, op, src, aux, aux_x=aoff[0], aux_y=aoff[1], **params)

        ok = True
        shown = []
        for px, py, expect in probes:
            got = to8(*read_pixel(dst, px, py))
            n = min(len(got), len(expect))
            good = all(abs(got[k] - expect[k]) <= tol for k in range(n))
            ok = ok and good
            shown.append("%d,%d→%s%s" % (px, py,
                                         " ".join("%.0f" % v for v in got),
                                         "" if good else "✗"))
        bad += 0 if ok else 1
        if ok and not verbose:
            continue
        print("%-38s %-18s %-18s %s" % (label, "  ".join(shown), "", "OK" if ok else "FAIL"))

    ok_n = len(CASES) + len(COVERAGE_CASES) - bad

    # ---- 源层透明像素 ----
    for i, (label, op, cin, auxpx, size, params, probes,
            tol) in enumerate(ALPHA_CASES):
        src = os.path.join(TMP, "ain%d.png" % i)
        aux = os.path.join(TMP, "aaux%d.png" % i)
        dst = os.path.join(TMP, "aout%d.png" % i)
        write_png_pixels(src, [cin] * (size[0] * size[1]), size[0], size[1])
        write_png_pixels(aux, auxpx, size[0], size[1])
        if os.path.exists(dst):
            os.remove(dst)
        run(dst, op, src, aux, **params)

        ok = True
        shown = []
        for px_, py_, expect in probes:
            got = to8(*read_pixel(dst, px_, py_))
            n = min(len(got), len(expect))
            good = all(abs(got[k] - expect[k]) <= tol for k in range(n))
            ok = ok and good
            shown.append("%d,%d→%s%s" % (px_, py_,
                                         " ".join("%.0f" % v for v in got),
                                         "" if good else "✗"))
        bad += 0 if ok else 1
        if ok and not verbose:
            continue
        print("%-38s %-18s %-18s %s" % (label, "  ".join(shown), "", "OK" if ok else "FAIL"))

    ok_n = len(CASES) + len(COVERAGE_CASES) + len(ALPHA_CASES) - bad
    print("\n%d/%d 通过" % (ok_n, len(CASES) + len(COVERAGE_CASES) + len(ALPHA_CASES)))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
