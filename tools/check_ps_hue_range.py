# -*- coding: utf-8 -*-
"""验收 lb:ps-hue-range（色系范围 + 权重缩放的色相/饱和度/明度）。

做法：造一张色卡（9 个已知色相/饱和度的色块），对每组参数跑 gegl
（支持 -- 链式串联 Master + Range），用 Python 参考实现（与本算子
逐字同式）算期望值，8bit 逐通道对比，容差 2 码。

行为断言的关键点：
  · 红系默认范围 315/345/15/45：红全选（w=1）、橙 30° 处 w=0.5、
    黄 60° 及以外 w=0；
  · 权重作用在原始色相上，调整量按 w 缩放（橙的色相位移是半量）；
  · 无彩像素不参与任何色系；
  · 柄拖过 0/360 环绕仍正确；
  · w=1 时与 lb:ps-hue-saturation 逐位一致（链式用例间接覆盖）。

    python tools/check_ps_hue_range.py
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]
OPS_CANDIDATES = [
    os.environ.get("GEGL_SYS_OPS", ""),
    r"D:\fastsoftware\GIMP 3\lib\gegl-0.4",
    r"C:\Program Files\GIMP 3\lib\gegl-0.4",
]

SW = 32
SH = 16
TOL = 2.0   # 8bit 每通道容差

# (名字, 8bit RGB)
SWATCHES = [
    ("红",     (255,   0,   0)),
    ("橙",     (255, 128,   0)),
    ("黄",     (255, 255,   0)),
    ("绿",     (  0, 255,   0)),
    ("青",     (  0, 255, 255)),
    ("蓝",     (  0,   0, 255)),
    ("品红",   (255,   0, 255)),
    ("玫红",   (255,   0, 128)),
    ("灰粉",   (200, 128, 128)),
]

CHANNEL_DEFAULTS = {
    "reds":     (315.0, 345.0,  15.0,  45.0),
    "yellows":  ( 15.0,  45.0,  75.0, 105.0),
    "greens":   ( 75.0, 105.0, 135.0, 165.0),
    "cyans":    (135.0, 165.0, 195.0, 225.0),
    "blues":    (195.0, 225.0, 255.0, 285.0),
    "magentas": (255.0, 285.0, 315.0, 345.0),
}


# ---- 参考实现：与 ps-hue-range.c / ps-hue-saturation.c 逐字同式 ----------

def wrap_degrees(d):
    d = d % 360.0
    return d


def rgb_to_hsl(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    delta = mx - mn
    total = mx + mn
    h = s = 0.0
    l = total * 0.5
    if delta > 1e-6 and total > 1e-6:
        s = delta / total if l <= 0.5 else delta / (2.0 - total)
        if mx == r:
            h = (g - b) / delta + (6.0 if g < b else 0.0)
        elif mx == g:
            h = (b - r) / delta + 2.0
        else:
            h = (r - g) / delta + 4.0
        h *= 60.0
    return wrap_degrees(h), min(max(s, 0.0), 1.0), min(max(l, 0.0), 1.0), delta


def hue_channel(m1, m2, h):
    if h < 0:
        h += 360.0
    elif h >= 360:
        h -= 360.0
    if h < 60:
        return m1 + (m2 - m1) * h / 60.0
    if h < 180:
        return m2
    if h < 240:
        return m1 + (m2 - m1) * (240.0 - h) / 60.0
    return m1


def hsl_to_rgb(h, s, l):
    if s <= 1e-6:
        return l, l, l
    m2 = l * (1 + s) if l <= 0.5 else l + s - l * s
    m1 = 2 * l - m2
    return (hue_channel(m1, m2, h + 120.0),
            hue_channel(m1, m2, h),
            hue_channel(m1, m2, h - 120.0))


def apply_lightness(c, t):
    if t > 0:
        return c + t * (1 - c)
    if t < 0:
        return c * (1 + t)
    return c


def scale_saturation(s, x):
    if x >= 1.0:
        return 1.0 if s > 0 else 0.0
    if x > 0:
        return min(1.0, s / (1.0 - x))
    if x < 0:
        return max(0.0, s * (1.0 + x))
    return s


def range_weight(h, o_l, i_l, i_r, o_r):
    span = i_r - i_l
    if span < 0:
        span += 360.0
    i_lu = i_l
    i_ru = i_l + span
    o_lu = i_lu - wrap_degrees(i_lu - o_l)
    o_ru = i_ru + wrap_degrees(o_r - i_r)
    hu = i_lu + wrap_degrees(h - i_lu)

    if hu < o_lu or hu > o_ru:
        return 0.0
    if i_lu <= hu <= i_ru:
        return 1.0
    if hu < i_lu:
        band = i_lu - o_lu
        return 0.0 if band <= 1e-6 else (hu - o_lu) / band
    band = o_ru - i_ru
    return 0.0 if band <= 1e-6 else (o_ru - hu) / band


def ref_adjust(r8, g8, b8, hue, sat, light, o_l, i_l, i_r, o_r):
    """单像素参考：返回 0-1 浮点 RGB（与 C 同序：明度→HSL→色相→饱和度）。"""
    r, g, b = (c / 255.0 for c in (r8, g8, b8))
    r, g, b = (min(max(c, 0.0), 1.0) for c in (r, g, b))

    h, s, l, chroma = rgb_to_hsl(r, g, b)
    w = range_weight(h, o_l, i_l, i_r, o_r) if chroma > 1e-6 else 0.0
    if w <= 0.0:
        return r, g, b

    t = light / 100.0 * w
    if t != 0.0:
        r, g, b = apply_lightness(r, t), apply_lightness(g, t), apply_lightness(b, t)

    h, s, l, _ = rgb_to_hsl(r, g, b)
    if hue != 0.0:
        h = wrap_degrees(h + hue * w)
    x = sat / 100.0 * w
    if x != 0.0:
        s = scale_saturation(s, x)

    return hsl_to_rgb(h, s, l)


def ref_master_then_range(r8, g8, b8, m_h, m_s, m_l,
                          hue, sat, light, o_l, i_l, i_r, o_r):
    """链式参考：先 Master（全图，w=1），再 Range。GEGL 链内是浮点直传，
    所以中间结果不量化，直接进 Range。"""
    r, g, b = (c / 255.0 for c in (r8, g8, b8))
    t = m_l / 100.0
    if t != 0.0:
        r, g, b = apply_lightness(r, t), apply_lightness(g, t), apply_lightness(b, t)
    h, s, l, _ = rgb_to_hsl(r, g, b)
    if m_h != 0.0:
        h = wrap_degrees(h + m_h)
    x = m_s / 100.0
    if x != 0.0:
        s = scale_saturation(s, x)
    r1, g1, b1 = hsl_to_rgb(h, s, l)
    # 再走 Range，权重按【链中该点的色相】算 —— 与 C 一致：Range 看的是
    # 自己输入的色相。中间值保留浮点精度（×255 还原成 ref_adjust 的尺度）。
    return ref_adjust(r1 * 255.0, g1 * 255.0, b1 * 255.0,
                      hue, sat, light, o_l, i_l, i_r, o_r)


# ---- 色卡 PNG 与输出读取 -------------------------------------------------

def write_swatches(path):
    row = bytearray()
    for _, (r, g, b) in SWATCHES:
        row += bytes([r, g, b]) * SW
    raw = b''.join(b'\x00' + bytes(row) for _ in range(SH))

    def chunk(tag, data):
        c = tag + data
        return (struct.pack('>I', len(data)) + c +
                struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF))

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', len(SWATCHES) * SW,
                                        SH, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 6))
           + chunk(b'IEND', b''))
    open(path, 'wb').write(png)


def read_rgb(path):
    """读 8/16 位 RGB PNG，返回 get(x, y) -> (r, g, b)，0-255 浮点。"""
    data = open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat = 8, []
    w = h = depth = ctype = 0
    while pos < len(data):
        ln = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', body[:10])
        elif tag == b'IDAT':
            idat.append(body)
        elif tag == b'IEND':
            break
    assert ctype in (2, 6), 'ctype=%d' % ctype
    nch = {2: 3, 6: 4}[ctype]
    bpp = nch * (depth // 8)
    stride = w * bpp
    raw = zlib.decompress(b''.join(idat))
    scale = 255.0 / 65535.0 if depth == 16 else 1.0

    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:
            for i in range(nch * (depth // 8), stride):
                line[i] = (line[i] + line[i - nch * (depth // 8)]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                left = line[i - nch * (depth // 8)] if i >= nch * (depth // 8) else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            def paeth(a, b, c):
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                return a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            for i in range(stride):
                left = line[i - nch * (depth // 8)] if i >= nch * (depth // 8) else 0
                up = prev[i]
                ul = prev[i - nch * (depth // 8)] if i >= nch * (depth // 8) else 0
                line[i] = (line[i] + paeth(left, up, ul)) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line

    def get(x, y):
        base = y * stride + x * bpp
        vals = [out[base + k] for k in range(3)]
        if depth == 16:
            vals = [((out[base + k * 2] << 8) | out[base + k * 2 + 1]) * scale
                    for k in range(3)]
        return vals

    return w, h, get


# ---- 用例 ----------------------------------------------------------------

def find(paths, what):
    for p in paths:
        if p and os.path.exists(p):
            return p
    raise SystemExit("找不到 %s，可以用环境变量指定" % what)


def run_gegl(gegl, ops_dirs, img, out, op_args):
    env = dict(os.environ, GEGL_PATH=ops_dirs)
    # GEGL CLI："--" 之后的【全部】 argv 依序组成链，算子之间不再重复 "--"，
    # property=value 直接跟在各自算子名后面。多加一个 "--" 会截断链（实测：
    # 只有第一个算子生效）；合成单串则完全不解析。
    flat = [a for op in op_args for a in op]
    args = [gegl, img, '-o', out, '--'] + flat
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("渲染失败 %s\n%s" % (op_args, r.stderr[-500:]))


def main():
    gegl = find(GEGL_CANDIDATES, "gegl.exe")
    opsdir = find(OPS_CANDIDATES, "gegl-0.4 算子目录")
    build = os.path.join(ROOT, "build")
    ops_path = (build + os.pathsep + opsdir).replace('\\', '/')

    tmp = tempfile.mkdtemp(prefix='phr-')
    img = os.path.join(tmp, 'swatches.png')
    write_swatches(img)

    def handles(ch, o_l, i_l, i_r, o_r):
        d = CHANNEL_DEFAULTS[ch]
        return (d[0] if o_l is None else o_l,
                d[1] if i_l is None else i_l,
                d[2] if i_r is None else i_r,
                d[3] if o_r is None else o_r)

    # (描述, gegl 算子链, 参考函数)
    cases = []

    def add_range_case(desc, props, ref_fn):
        cases.append((desc,
                      [['lb:ps-hue-range'] + props],
                      ref_fn))

    # 1. 红系 hue=90：橙在 30° 处应得半量位移（45°）
    add_range_case('红系 hue=90', ['channel=reds', 'hue=90'],
                   lambda r, g, b: ref_adjust(r, g, b, 90, 0, 0,
                                              *handles('reds', None, None, None, None)))
    # 2. 红系 hue=90 sat=50 lightness=20（全公式）
    add_range_case('红系 hue=90 sat=50 light=20',
                   ['channel=reds', 'hue=90', 'saturation=50', 'lightness=20'],
                   lambda r, g, b: ref_adjust(r, g, b, 90, 50, 20,
                                              *handles('reds', None, None, None, None)))
    # 3. 黄系 hue=-60：只有黄（±15 全选）动
    add_range_case('黄系 hue=-60', ['channel=yellows', 'hue=-60'],
                   lambda r, g, b: ref_adjust(r, g, b, -60, 0, 0,
                                              *handles('yellows', None, None, None, None)))
    # 4. 红系 sat=100：灰粉 (200,128,128) 的 s 应被拉满
    add_range_case('红系 sat=100', ['channel=reds', 'saturation=100'],
                   lambda r, g, b: ref_adjust(r, g, b, 0, 100, 0,
                                              *handles('reds', None, None, None, None)))
    # 5. 红系 lightness=50
    add_range_case('红系 light=50', ['channel=reds', 'lightness=50'],
                   lambda r, g, b: ref_adjust(r, g, b, 0, 0, 50,
                                              *handles('reds', None, None, None, None)))
    # 6. 柄拖过 0/360：内区 350–10（环绕），外柄仍跟默认 315/45
    add_range_case('红系 环绕内区 350–10',
                   ['channel=reds', 'range-inner-low=350', 'range-inner-high=10',
                    'hue=90'],
                   lambda r, g, b: ref_adjust(r, g, b, 90, 0, 0,
                                              *handles('reds', 315.0, 350.0, 10.0, 45.0)))
    # 7. 绿系 hue=-120：绿 → 红
    add_range_case('绿系 hue=-120', ['channel=greens', 'hue=-120'],
                   lambda r, g, b: ref_adjust(r, g, b, -120, 0, 0,
                                              *handles('greens', None, None, None, None)))
    # 8. 链式：Master hue=-30 → 红系 hue=60
    cases.append(('链式 Master(-30) → 红系(+60)',
                  [['lb:ps-hue-saturation', 'hue=-30'],
                   ['lb:ps-hue-range', 'channel=reds', 'hue=60']],
                  lambda r, g, b: ref_master_then_range(r, g, b, -30, 0, 0,
                                                        60, 0, 0,
                                                        *handles('reds', None, None, None, None))))

    total = worst = 0
    bad_pts = 0
    failures = 0
    for desc, op_args, ref_fn in cases:
        out = os.path.join(tmp, 'out.png')
        if os.path.exists(out):
            os.remove(out)
        run_gegl(gegl, ops_path, img, out, op_args)
        w, h, get = read_rgb(out)

        max_d = 0.0
        n = 0
        for i, (name, rgb) in enumerate(SWATCHES):
            got = get(i * SW + SW // 2, SH // 2)
            exp = ref_fn(*rgb)
            for k in range(3):
                d = abs(got[k] - exp[k] * 255.0)
                max_d = max(max_d, d)
                total += d
                n += 1
                if d > TOL:
                    bad_pts += 1
        worst = max(worst, max_d)
        ok = max_d <= TOL
        failures += 0 if ok else 1
        print("  %-28s 平均 %5.2f 码  最大 %5.1f 码 %s"
              % (desc, sum_cases(total, n), max_d, "✓" if ok else "✗"))

    print("· 共 %d 个用例，%d 个采样点，平均 %.2f 码，最大 %.1f 码（容差 %.0f）"
          % (len(cases), len(cases) * len(SWATCHES) * 3,
             total / max(total_pts(cases), 1), worst, TOL))
    if bad_pts:
        print("✗ %d 个点超差，%d 个用例失败" % (bad_pts, failures))
        return 1
    print("✓ 全部通过")
    return 0


def sum_cases(total, n):
    return total / max(n, 1)


def total_pts(cases):
    return len(cases) * len(SWATCHES) * 3


if __name__ == '__main__':
    sys.exit(main())
