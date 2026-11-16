# -*- coding: utf-8 -*-
"""验收 lb:color-mask-select 自定颜色模式（CIELAB ΔE + kL=2 匹配）。

关键性质（目标色 = 纯红，羽化 0，实测标定的 ΔE94(kL=2) 排序）：
  · 距离排序：{红, 暗红, 橙红} ≈ ΔE<50 < {粉} ≈ ΔE 50–60
    < {近黑, 灰, 白, 蓝} > 100——低彩度和无关色被感知距离合理排后；
  · 容差 100（ΔE 50 窗）：红 / 暗红 / 橙红全选，粉掉出窗外——
    旧 RGB 距离做不到：把灰/近黑也判得很近；
  · 容差 140（ΔE 70 窗）：粉也入选，无关色仍不选；
  · 容差 60（ΔE 30 窗）：只剩纯红 / 橙红；
  · 容差 200：按设计全选。
退出码非 0 即失败。

    python tools/check_color_mask_custom.py
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, HERE)
from read_alpha import read_alpha      # noqa: E402

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

# 色卡：8bit sRGB。目标色 = 纯红。
SWATCHES = [
    ("红",       (255,   0,   0)),
    ("暗红",     (128,   0,   0)),
    ("粉",       (255, 128, 128)),
    ("橙红",     (255,  64,   0)),
    ("近黑",     ( 16,   0,   0)),
    ("灰",       (128, 128, 128)),
    ("白",       (255, 255, 255)),
    ("蓝",       (  0,   0, 255)),
]
SW = 32   # 每个色块宽
SH = 16   # 高

FUZZINESS = 100        # w = 0.5，即 ΔE 50 容差窗
FUZZINESS_WIDE = 140   # w = 0.7，即 ΔE 70 容差窗
FUZZINESS_TIGHT = 60   # w = 0.3，即 ΔE 30 容差窗
FEATHER = 0


def find(paths, what):
    for p in paths:
        if p and os.path.exists(p):
            return p
    raise SystemExit("找不到 %s，可以用环境变量指定" % what)


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


def run_case(gegl, ops, build, env, tmp, fuzziness):
    img = os.path.join(tmp, 'swatches.png')
    out = os.path.join(tmp, 'out-%d.png' % fuzziness)
    write_swatches(img)

    args = [gegl, img, '-o', out, '--', 'lb:color-mask-select',
            'mask-mode=custom',
            'custom-color=rgba(1.0, 0.0, 0.0, 1.0)',
            'fuzziness=%d' % fuzziness,
            'feather=%d' % FEATHER]
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    if r.returncode != 0 or not os.path.exists(out):
        print("✗ 渲染失败\n%s" % r.stderr[-500:])
        return None

    w, h, get = read_alpha(out)
    return [get(i * SW + SW // 2, SH // 2)
            for i in range(len(SWATCHES))]


def main():
    gegl = find(GEGL_CANDIDATES, "gegl.exe")
    ops = find(OPS_CANDIDATES, "GIMP 的 gegl-0.4 算子目录")
    build = os.path.join(ROOT, "build")
    env = dict(os.environ,
               GEGL_PATH=(build + ';' + ops).replace('\\', '/'))

    tmp = tempfile.mkdtemp(prefix='cmc-')
    a = run_case(gegl, ops, build, env, tmp, FUZZINESS)
    aw = run_case(gegl, ops, build, env, tmp, FUZZINESS_WIDE)
    b = run_case(gegl, ops, build, env, tmp, FUZZINESS_TIGHT)
    if a is None or aw is None or b is None:
        return 1

    names = [n for n, _ in SWATCHES]
    for label, vals in (("容差 %d" % FUZZINESS, a),
                        ("容差 %d" % FUZZINESS_WIDE, aw),
                        ("容差 %d" % FUZZINESS_TIGHT, b)):
        print("  %s：" % label)
        for n, v in zip(names, vals):
            print("    %-4s alpha = %3d" % (n, v))

    red, dark, pink, orange, nearblk, gray, white, blue = a
    redw, darkw, pinkw, orangew, nearblkw, grayw, whitew, bluew = aw
    red2, dark2, pink2, orange2 = b[:4]

    checks = [
        ("大窗：纯红全选",            red    >= 240),
        ("大窗：暗红同族全选",        dark   >= 200),
        ("大窗：橙红全选",            orange >= 240),
        ("大窗：粉掉出窗外（低彩度排后）", pink <= 20),
        ("大窗：近黑几乎不选",        nearblk <= 20),
        ("大窗：灰几乎不选",          gray   <= 20),
        ("大窗：白几乎不选",          white  <= 20),
        ("大窗：蓝完全不选",          blue   <= 10),
        ("宽窗：粉也入选",            pinkw  >= 200),
        ("宽窗：红/暗红/橙红仍全选",  min(redw, darkw, orangew) >= 200),
        ("宽窗：无关色仍不选",        max(nearblkw, grayw, whitew, bluew) <= 20),
        ("小窗：纯红仍全选",          red2   >= 240),
        ("小窗：橙红仍全选",          orange2 >= 240),
        ("小窗：暗红掉出窗外",        dark2  <= 20),
        ("小窗：粉掉出窗外",          pink2  <= 20),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    if bad:
        print("✗ %d 条性质不成立" % len(bad))
        return 1
    print("· 自定颜色 ΔE 匹配行为验收通过")
    return 0


if __name__ == '__main__':
    sys.exit(main())
