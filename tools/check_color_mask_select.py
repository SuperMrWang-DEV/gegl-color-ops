# -*- coding: utf-8 -*-
"""验收 lb:color-mask-select 的色调模式（高光 / 阴影 / 中间调）。

这两条曲线不是推出来的，是拿 经典图像编辑器 2025「色彩范围」实测标定的
（见 ../clrr-cal：40 组参数跑出蒙版，拟合出「阈值 + 容差 → 亮度响应」）。

做法：造一张 256 px 的纯灰斜坡（第 x 列的亮度就是 x），让算子跑一遍，
把 alpha 与 ../clrr-cal/ps_color_range_ref.json 的记录逐点比。
参考表不在仓库里时（CI）自动跳过，退出码 0。

    python tools/check_color_mask_select.py
    python tools/check_color_mask_select.py -v      # 打印每个用例
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(os.path.dirname(ROOT), "clrr-cal", "ps_color_range_ref.json")

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

# 经典图像编辑器 的响应用解析式只能逼近：曲线中段能对到 1 码内，两端尾巴（alpha < 20）
# 差到 30 码左右，肉眼看就是「几乎不选」和「选了一点」。所以卡两档：
TOL = 34.0       # 单点最大偏差（0–255 码）
TOL_AVG = 4.0    # 全表平均偏差


def find(paths, what):
    for p in paths:
        if p and os.path.exists(p):
            return p
    raise SystemExit("找不到 %s，可以用环境变量指定" % what)


def write_ramp(path, width=256, height=8):
    """纯灰斜坡：第 x 列 = x，无 ICC（GEGL 按 sRGB 解释）。"""
    row = bytes([c for x in range(width) for c in (x, x, x)])
    raw = b''.join(b'\x00' + row for _ in range(height))

    def chunk(tag, data):
        c = tag + data
        return (struct.pack('>I', len(data)) + c +
                struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF))

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 6))
           + chunk(b'IEND', b''))
    open(path, 'wb').write(png)


def main():
    verbose = '-v' in sys.argv
    if not os.path.exists(REF):
        print("· 没有色彩范围标定数据（%s），跳过" % os.path.relpath(REF, ROOT))
        return 0

    gegl = find(GEGL_CANDIDATES, "gegl.exe")
    ops = find(OPS_CANDIDATES, "GIMP 的 gegl-0.4 算子目录")
    build = os.path.join(ROOT, "build")
    env = dict(os.environ,
               GEGL_PATH=(build + ';' + ops).replace('\\', '/'))

    ref = json.load(open(REF, encoding='utf-8'))
    tmp = tempfile.mkdtemp(prefix='cms-')
    ramp = os.path.join(tmp, 'ramp.png')
    write_ramp(ramp)

    if verbose:
        print("· gegl  =", gegl)
        print("· 参考  = %d 个用例（经典图像编辑器 2025 实测）" % len(ref['cases']))

    total = 0.0
    n = 0
    worst = (0.0, None)
    bad = 0

    for case in ref['cases']:
        out = os.path.join(tmp, 'out.png')
        if os.path.exists(out):
            os.remove(out)
        args = [gegl, ramp, '-o', out, '--', 'lb:color-mask-select',
                'mask-mode=%s' % case['mode'],
                'fuzziness=%d' % (case['fz'] * 2)]
        if case['mode'] == 'black':
            args.append('shadows-limit=%d' % case['limit'])
        elif case['mode'] == 'white':
            args.append('highlights-limit=%d' % case['limit'])
        else:
            args.append('midtone-low=%d' % case['limit'])
            args.append('midtone-high=%d' % case['limit2'])

        r = subprocess.run(args, capture_output=True, text=True, env=env)
        if r.returncode != 0 or not os.path.exists(out):
            print("✗ 渲染失败 %s\n%s" % (case, r.stderr[-300:]))
            return 1

        w, h, get = read_alpha(out)
        errs = []
        for L, want in case['samples']:
            err = abs(get(L, 0) - want)
            errs.append(err)
            total += err
            n += 1
            if err > worst[0]:
                worst = (err, '%s limit=%d fz=%d L=%d' %
                         (case['mode'], case['limit'], case['fz'], L))
            if err > TOL:
                bad += 1
        if verbose:
            label = ('中间调 %d–%d' % (case['limit'], case['limit2'])
                     if case['mode'] == 'gray' else
                     ('阴影 %d' % case['limit'] if case['mode'] == 'black'
                      else '高光 %d' % case['limit']))
            print("  %-14s 容差 %3d  平均 %5.2f 码  最大 %5.1f 码"
                  % (label, case['fz'], sum(errs) / len(errs), max(errs)))

    avg = total / max(n, 1)
    print("· 色调曲线对 参考图像编辑器：%d 个采样点，平均 %.2f 码，最大 %.1f 码（%s）"
          % (n, avg, worst[0], worst[1]))
    if bad or avg > TOL_AVG:
        print("✗ %d 个点超出 %.0f 码，平均 %.2f 码（限 %.1f）"
              % (bad, TOL, avg, TOL_AVG))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
