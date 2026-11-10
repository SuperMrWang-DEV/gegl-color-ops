"""对比 lb:vibrance-hyper 旧版 / 新版蒙版在同样参数下的行为。

旧版用公式复现（含逐通道硬裁剪），新版走真实算子渲染。
关注三项：C* 增幅、色相偏移 Δh、裁剪前后出界通道数。
"""
import math, os, struct, subprocess, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from contact_sheet import read_png             # noqa: E402

GEGL = "gegl"


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(v for px in r for v in px) for r in rows)

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def s2l(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb2lab(r, g, b):
    x = r * .4124564 + g * .3575761 + b * .1804375
    y = r * .2126729 + g * .7151522 + b * .0721750
    z = r * .0193339 + g * .1191920 + b * .9503041
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x / .95047), f(y), f(z / 1.08883)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lab2rgb(L, a, b):
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    inv = lambda t: t ** 3 if t > 0.206893 else (t - 16 / 116) / 7.787
    x, y, z = inv(fx) * .95047, inv(fy), inv(fz) * 1.08883
    return (x * 3.2404542 + y * -1.5371385 + z * -0.4985314,
            x * -0.9692660 + y * 1.8760108 + z * 0.0415560,
            x * 0.0556434 + y * -0.2040259 + z * 1.0572252)


def old_pixel(r, g, b, vib, atten=2.0):
    """旧版：无肤色窗、chroma 后算、硬裁剪。"""
    L, a, bb = rgb2lab(r, g, b)
    chroma = math.hypot(a, bb)
    w = 1.0 / (1.0 + atten * chroma / 50.0)
    scale = 1.0 + (vib / 50.0) * w
    na, nb = a * scale, bb * scale
    out = [min(1.0, max(0.0, v)) for v in lab2rgb(L, na, nb)]
    oog = sum(1 for v in lab2rgb(L, na, nb) if v < -1e-4 or v > 1 + 1e-4)
    return out, oog


COLORS = [
    ("肤色 亮",   (235, 190, 170)),
    ("肤色 中",   (200, 150, 120)),
    ("肤色 暗",   (120, 80, 60)),
    ("饱和 红",   (230, 30, 40)),
    ("饱和 绿",   (30, 200, 60)),
    ("饱和 蓝",   (40, 70, 220)),
    ("青",        (0, 180, 210)),
    ("品红",      (220, 40, 180)),
    ("深饱和蓝",  (0, 0, 120)),
    ("中性灰",    (128, 128, 128)),
]

W = H = 40
rows = [[(0, 0, 0)] * (W * len(COLORS)) for _ in range(H)]
for i, (_, c) in enumerate(COLORS):
    for y in range(H):
        for x in range(W * i, W * (i + 1)):
            rows[y][x] = c

os.makedirs("build/diag", exist_ok=True)
in_p = "build/diag/in.png"
write_png(in_p, W * len(COLORS), H, rows)

for vib in (50, 100):
    subprocess.run([GEGL, in_p, "-o", f"build/diag/new-v{vib}.png", "--",
                    "lb:vibrance-hyper", f"vibrance={vib}"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

_, _, src = read_png(in_p)

for vib in (50, 100):
    _, _, new = read_png(f"build/diag/new-v{vib}.png")
    print(f"\n=== vibrance=+{vib}   旧版 vs 新版")
    print(f"  {'色块':<9}{'C*原':>6} | {'旧C*':>6}{'倍':>5}{'Δh':>6}{'出界':>4}"
          f" | {'新C*':>6}{'倍':>5}{'Δh':>6}")
    for i, (name, _) in enumerate(COLORS):
        x, y = W * i + W // 2, H // 2
        r0, g0, b0 = (s2l(v) for v in src[y][x][:3])
        L0, a0, bb0 = rgb2lab(r0, g0, b0)
        c0 = math.hypot(a0, bb0)
        h0 = math.degrees(math.atan2(bb0, a0)) % 360

        oc, oog = old_pixel(r0, g0, b0, vib)
        Lo, ao, bo = rgb2lab(*oc)
        co = math.hypot(ao, bo)
        ho = math.degrees(math.atan2(bo, ao)) % 360
        dho = (ho - h0 + 180) % 360 - 180

        rn, gn, bn = (s2l(v) for v in new[y][x][:3])
        Ln, an, bnn = rgb2lab(rn, gn, bn)
        cn = math.hypot(an, bnn)
        hn = math.degrees(math.atan2(bnn, an)) % 360
        dhn = (hn - h0 + 180) % 360 - 180

        print(f"  {name:<9}{c0:6.1f} | {co:6.1f}{co/max(c0,1e-6):5.2f}{dho:6.1f}{oog:>4}"
              f" | {cn:6.1f}{cn/max(c0,1e-6):5.2f}{dhn:6.1f}")

print("\n=== 恒等检查（vibrance=0 应逐像素不变）")
subprocess.run([GEGL, in_p, "-o", "build/diag/id.png", "--", "lb:vibrance-hyper"],
               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
_, _, idp = read_png("build/diag/id.png")
diff = max(abs(a - b) for row_a, row_b in zip(src, idp) for pa, pb in zip(row_a, row_b)
           for a, b in zip(pa, pb))
print(f"  最大差异 = {diff}")
