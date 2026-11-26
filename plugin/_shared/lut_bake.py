#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 把图层滤镜栈烘成 3D LUT 的内核
 ---------------------------------------------------------------------------
 干什么：把「当前图层挂着的非破坏滤镜栈」当成一个颜色函数 f(r,g,b)，
 在 size³ 的格点上采样，写成 Adobe Cube（.cube）——之后就能给视频、
 给别的图、给 lb:color-lookup 用，不必再带着 GIMP 工程走。

 做法与两处公开实现一致：

   · RawTherapee 的 CubeLUT::createIdentityTempFile / saveAsCubeFile
     （PR #7676「Add .cube LUT support and HALD/.cube LUT export」）：
     先造一张「单位图」——宽 size²、高 size，像素 (x=g·size+r, y=b)
     编码输入色 (r,g,b)/(size-1)；把这张图送进整条处理管线；再把处理后的
     像素按 **红变化最快** 的顺序吐出成 .cube。
   · OpenColorIO 的 FileFormatIridasCube::bake()：
     表头 LUT_3D_SIZE + 6 位小数，条目顺序同样是 R 最快、B 最慢。

 这里复用了同一套布局，但「管线」换成 GIMP 的图层滤镜栈：复制一份图像 →
 把目标图层铺成单位图 → merge 掉它的每个 DrawableFilter → 读回像素。
 滤镜本身不动原图，所以烘完原图一个字节都没变。

 只有**逐像素**算子能被 LUT 完整表示。模糊、降噪、USM、置换、木偶/自由变形、
 图层样式、最大最小值这些要看邻居像素或随机数的算子，烘出来只是近似——
 SPATIAL_OPS 里列了名单，界面会提前警告，但不阻止（有时候近似也够用）。
 ============================================================================"""

import os
import struct

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl


# 依赖邻居像素 / 随机数 / 多输入统计的算子：LUT 表达不了，只能近似。
SPATIAL_OPS = {
    'shadows-highlights',   # 按邻域做边缘感知
    'unsharp-mask',
    'reduce-noise',
    'dust-scratches',
    'add-noise',            # 随机数：烘出来的噪声是固定的
    'displace',
    'puppet-warp',
    'mesh-warp',
    'layer-style',
    'max-min',              # 形态学膨胀/腐蚀
    'apply-image',          # 两输入
    'calculations',         # 两输入
    'match-color',          # 要统计另一张图
}

def short_op(name):
    """'lb:hsv-levels' -> 'hsv-levels'，用于比对 SPATIAL_OPS。"""
    return (name or '').split(':', 1)[-1]


def is_spatial(op_name):
    return short_op(op_name) in SPATIAL_OPS


def filter_names(layer):
    return [f.get_operation_name() for f in layer.get_filters()]


def spatial_filters(layer):
    return [n for n in filter_names(layer) if is_spatial(n)]


def lattice_span(size):
    """单位图的画布尺寸。宽 = size²，高 = size。"""
    return size * size, size


def lattice_values(size):
    """单位图的像素，RGBA float，行优先。

    顺序 intentionally 与 .cube 一致：y 走 b，x 走 g·size+r，
    所以线性遍历就是「红最快、蓝最慢」。
    """
    den = float(size - 1) if size > 1 else 1.0
    out = []
    for b in range(size):
        bv = b / den
        for g in range(size):
            gv = g / den
            for r in range(size):
                out.extend((r / den, gv, bv, 1.0))
    return out


def _find_layer(dup, image, layer):
    """在副本里找到与 layer 对应的那一层。

    先按顶层顺序对位（绝大多数情况够用）；对不上就按「同名同深度」找，
    再不行就要求调用方自己给。
    """
    src = image.get_layers()
    dst = dup.get_layers()
    if len(src) == len(dst):
        for a, b in zip(src, dst):
            if a.get_name() == b.get_name() and a.get_width() == b.get_width():
                if a.get_name() == layer.get_name():
                    return b
    for cand in dst:
        if cand.get_name() == layer.get_name():
            return cand
    return None


def bake(image, layer, size):
    """把 layer 的滤镜栈采成 size³ 的 LUT。

    返回 (values, spatial)：values 是长度 size³×3 的 float 列表（R 最快），
    已经 clamp 到 0…1；spatial 是被判定为「只能近似」的算子名。

    做法：复制整张图（滤镜随图层一起复制），只留目标层，铺上单位图，
    merge 掉滤镜，再读回来。副本用完即删，原图不动。
    """
    if size < 2:
        raise ValueError('LUT 尺寸至少要 2')
    filters = list(layer.get_filters())
    if not filters:
        raise RuntimeError('这个图层没有滤镜，没有可烘的东西')

    spatial = [f.get_operation_name() for f in filters if is_spatial(
        f.get_operation_name())]

    W, H = lattice_span(size)
    rect = Gegl.Rectangle.new(0, 0, W, H)
    dup = image.duplicate()
    try:
        target = _find_layer(dup, image, layer)
        if target is None:
            raise RuntimeError('副本里找不到对应图层，换一张图再试')

        # 只留这一层：别的图层会被 merge 进来，混色就不是纯函数了
        for other in list(dup.get_layers()):
            if other is not target:
                dup.remove_layer(other)

        # 图层蒙版会让滤镜只作用在一部分像素上，烘出来是错的
        if hasattr(target, 'get_mask') and target.get_mask() is not None:
            target.remove_mask()

        # 精度**不能动**。曾经为了躲开 8bit 量化把副本转成浮点，结果整条
        # 管线的语义变了：8bit 每一级都把结果 clamp 到 0…1，浮点不会，
        # 负的 a/b 会一路带到下一级，同一份栈能差出 0.8。原图层是什么精度，
        # 就按什么精度烘——那才是用户在屏幕上看到的那条管线。
        target.resize(W, H, 0, 0)
        flat = lattice_values(size)
        target.get_buffer().set(rect, "R'G'B'A float",
                                struct.pack('<%df' % len(flat), *flat))
        if hasattr(target, 'update'):        # 通知 GEGL 这块脏了，滤镜才会重算
            target.update(0, 0, W, H)

        # 顺序很关键：get_filters() 从**栈顶**往下给，而 GIMP 是先算栈底。
        # 照列表顺序 merge 等于把整条链倒着跑一遍（实测差 0.8 个色阶），
        # 所以必须 reversed。
        for f in reversed(list(target.get_filters())):
            target.merge_filter(f)

        raw = target.get_buffer().get(rect, 1.0, "R'G'B'A float",
                                      Gegl.AbyssPolicy.NONE)
        px = struct.unpack('<%df' % (W * H * 4), raw)
    finally:
        dup.delete()

    values = []
    clamp = lambda v: 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
    for i in range(0, len(px), 4):
        values.append((clamp(px[i]), clamp(px[i + 1]), clamp(px[i + 2])))
    return values, spatial


def write_cube(path, size, values, title='gegl-color-ops'):
    """写 Adobe Cube。表头与条目顺序照 Iridas 规范，数值固定 6 位小数。"""
    if len(values) != size ** 3:
        raise ValueError('条目数不对：%d != %d³' % (len(values), size))
    lines = [
        'TITLE "%s"' % title.replace('"', "'"),
        '',
        'LUT_3D_SIZE %d' % size,
        '',
        'DOMAIN_MIN 0.0 0.0 0.0',
        'DOMAIN_MAX 1.0 1.0 1.0',
        '',
    ]
    for r, g, b in values:
        lines.append('%.6f %.6f %.6f' % (r, g, b))
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines) + '\n')
    return path


def bake_to_cube(image, layer, path, size=33, title=None):
    values, spatial = bake(image, layer, size)
    if title is None:
        base = os.path.splitext(os.path.basename(path))[0]
        title = base or 'gegl-color-ops'
    write_cube(path, size, values, title)
    return spatial


def identity_error(values, size):
    """烘焙结果离单位映射有多远：逐格求最大通道误差。恒等栈应为 0。"""
    den = float(size - 1)
    worst = 0.0
    i = 0
    for b in range(size):
        for g in range(size):
            for r in range(size):
                want = (r / den, g / den, b / den)
                got = values[i]
                i += 1
                for a, c in zip(want, got):
                    worst = max(worst, abs(a - c))
    return worst
