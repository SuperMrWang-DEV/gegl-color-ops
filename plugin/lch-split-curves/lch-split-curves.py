#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · LCh 分量分解 + 曲线 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   把当前图层拆成 LCh 三张分量层（Lightness / Chroma / Hue），每层挂
           一条可编辑的曲线，再用「颜色」组的三条 LCh 分量混合模式叠回去。
           恒等曲线时逐位还原原图——等于「在 CIE LCh 空间里调曲线」，而 LCh
           正是 GIMP 分量混合模式里唯一完整、且没有 legacy 包袱的一组。
           Split a layer into LCh component layers with per-component curves,
           stacked back through the LCh blend modes.

 menu      颜色 → SuperMrWang → Shortcut → LCh Split (Curves)
           图层右键 → SuperMrWang → Shortcut → LCh Split (Curves)

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              LCh split           组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 3 Lightness    分量层   模式 = LCh 明度
                ├─ 2 Chroma       分量层   模式 = LCh 彩度
                ├─ 1 Hue          分量层   模式 = LCh 色相   ← 垫底
                └─ 原图层（不动，可以隐藏）

           合成顺序是自下而上：色相层（等 L 等 C 的色相圆）先定 H，彩度层换 C
           （L、H 取自下层），明度层最后换 L。层序不能反——最底那张必须是
           「带真实色相的彩色」，因为它下面什么都没有；若最底是灰（C=0），
           上面两层换 C、换 H 时读到的都是 0，怎么换都还是灰。
           每层的滤镜栈（图层面板里从上往下读，实际执行顺序与之相反）：

              Hue        1 · extract  lch-h  → 2 · curve → 3 · encode
              Chroma     1 · extract  lch-c  → 2 · curve → 3 · encode
              Lightness  1 · extract  lab-l  → 2 · curve → 3 · encode

           编码那一步是本仓库的 GEGL 算子 lb:gray-to-component，一个滤镜搞定
           （旧版是 scale 加三条 gimp:curves）。没装这个算子时自动退回曲线，
           结果一样但少了算子的精确进制。

 note      三个分量的量程（实测标定，GIMP 3.2.8 / babl D50）：
             lab-l   L*/100            0…1
             lch-c   C*/200            0…0.656（sRGB 内）
             lch-h   h/360             0…1（度→归一）

           四条 LCh 混合模式的语义也用黑盒验证过（底图 L49.6 C29.6 H56.9）：

             LCh 色相      → LCh(L_base, C_base, H_src)
             LCh 彩度      → LCh(L_base, C_src,   H_base)
             LCh 明度      → LCh(L_src,   C_base, H_base)
             LCh 颜色      → LCh(L_base,  C_src,   H_src)

           所以本插件只要按「色相→彩度→明度」自下而上叠，三个分量就各归各位
           ——这也正是把原图层藏起来、三层自己还原的前提。

           编码路径（把「分量值」变成混合模式读得出来的颜色）：
             Lightness  Lab(100g, 0, 0)                    —— 直接就是 L*
             Chroma     Lab(70, C·cos30°, C·sin30°)，C = 200g
                        （LCh 彩度模式只读 C，方向无关紧要）
             Hue        Lab(70, 39.8·cos360g, 39.8·sin360g)
                        —— 等 L*、等 C* 的色相圆。色相混合模式对色相误差极
                        敏感（ΔH=0.5° 在 C*=90 时折合 9.6 码），所以彩度压到
                        39.8（L*=70 处整圈能容纳 41.9，取 0.95 倍留余量），
                        灵敏度低一个数量级。

           实测（见 tools/check_lch_split.py）：
             32 位浮点图，恒等曲线往返：≤ 0.02 码
             8 位图，恒等曲线往返：     ≤ 0.5 码
           旧版（三条曲线编码）是 0.03 / 0.5 码，算子版没有 256 点查表误差。

           注意事项：
           - 色相曲线必须是连续的（两端相等、中间不跳变）。要整体旋转色相
             请用 lb:hue-saturation；这条曲线适合「压缩/拉伸某段色相」。
           - 彩度与色相在近中性色上无意义（C≈0 时色相是噪声），但合成的结果
             不受影响：彩度层把 C 归零后，色相层读到的 C 也是 0。
           - 结果可能超出 sRGB 色域（浮点图里会保留负值/超 1），要落到 8 位
             就得裁切——这是分量混合模式本身的性质，不是插件的。
           - 8 位图像必须收进组里：三层直接合成到 8 位投影缓冲时会被逐层量化，
             色相偏到 11 码级（组内合成走浮点缓冲，只有 0.5 码）。所以 8 位图上
             group=False 会自动改成分组，并在提示里说明。
           - 图层自带的非破坏滤镜不会被复制（new_from_drawable 只取像素）。
           - 透明区域没问题：分量混合模式会沿用下层 alpha，不必加蒙版。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math
import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject

from gi.repository import Gegl


def _N_(message):
    return message


def _(message):
    return GLib.dgettext(None, message)


# ---- 颜色数学 / colour maths ------------------------------------------------
# 全部按 babl 的口径：sRGB 编码值 ↔ 线性 → XYZ(D65) → Bradford 适配到 D50
# → CIE Lab(D50)。component-extract 与 LCh 混合模式用的就是这一套。
# Everything follows babl: encoded sRGB -> linear -> XYZ(D65) -> Bradford D50
# -> CIE Lab(D50), which is exactly what component-extract reports.

_DELTA = 6.0 / 29.0
_DELTA3 = _DELTA ** 3
_D50 = (0.96422, 1.0, 0.82521)

_SRGB_TO_XYZ = ((0.4124564, 0.3575761, 0.1804375),
                (0.2126729, 0.7151522, 0.0721750),
                (0.0193339, 0.1191920, 0.9503041))
_XYZ_TO_SRGB = ((3.2404542, -1.5371385, -0.4985314),
                (-0.9692660, 1.8760108, 0.0415560),
                (0.0556434, -0.2040259, 1.0572252))
# Bradford D65 → D50
_D65_TO_D50 = ((1.0478112, 0.0228866, -0.0501270),
               (0.0295424, 0.9904844, -0.0170491),
               (-0.0092345, 0.0150436, 0.7521316))
# Bradford D50 → D65
_D50_TO_D65 = ((0.9555766, -0.0230393, 0.0631636),
               (-0.0282895, 1.0099416, 0.0210077),
               (0.0122982, -0.0204830, 1.3299098))


def _srgb_to_linear(c):
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c):
    if c <= 0.0031308:
        return c * 12.92
    return 1.055 * c ** (1.0 / 2.4) - 0.055


def _f(t):
    if t > _DELTA3:
        return t ** (1.0 / 3.0)
    return t / (3.0 * _DELTA * _DELTA) + 4.0 / 29.0


def _f_inv(t):
    if t > _DELTA:
        return t ** 3
    return 3.0 * _DELTA * _DELTA * (t - 4.0 / 29.0)


def _mul(m, v):
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def rgb_to_lch(rgb):
    """编码 sRGB → (L*, C*, h°)，白点 D50（babl 口径）。"""
    lin = tuple(_srgb_to_linear(c) for c in rgb)
    xyz = _mul(_SRGB_TO_XYZ, lin)
    xyz = _mul(_D65_TO_D50, xyz)
    fx, fy, fz = (_f(xyz[i] / _D50[i]) for i in range(3))
    light = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return (light, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360.0)


def lch_to_rgb(light, chroma, hue):
    """(L*, C*, h°) → 编码 sRGB；不做色域裁切（可能出负值/超 1）。"""
    hr = math.radians(hue)
    a, b = chroma * math.cos(hr), chroma * math.sin(hr)
    fy = (light + 16.0) / 116.0
    fx, fz = fy + a / 500.0, fy - b / 200.0
    xyz = (_D50[0] * _f_inv(fx), _D50[1] * _f_inv(fy), _D50[2] * _f_inv(fz))
    xyz = _mul(_D50_TO_D65, xyz)
    return tuple(_linear_to_srgb(c) for c in _mul(_XYZ_TO_SRGB, xyz))


# ---- 编码路径 / encoding paths ---------------------------------------------
# sRGB 色域内彩度上限：纯蓝的 C*≈131.21（36³ 网格搜索的最大值）。
MAX_CHROMA = 131.21
# extract 输出的 lch-c 是 C/200，乘这个系数把「sRGB 最大彩度」拉到 1.0。
CHROMA_SCALE = 200.0 / MAX_CHROMA

_N = 256   # 与 gimp:curves 的采样数一致，查表点正好落在曲线采样点上


def _gray_for_l(light):
    """L* → 编码值灰（三通道相同）。"""
    if light > 8.0:
        y = ((light + 16.0) / 116.0) ** 3
    else:
        y = light / (3.0 * _DELTA * _DELTA * 116.0)
    return min(1.0, max(0.0, _linear_to_srgb(y)))


def _b_for_chroma(chroma):
    """在黑→蓝直线上反解：C*(0,0,b) = chroma。C(b) 单调，二分即可。"""
    lo, hi = 0.0, 1.0
    for _ in range(36):
        mid = (lo + hi) * 0.5
        if rgb_to_lch((0.0, 0.0, mid))[1] < chroma:
            lo = mid
        else:
            hi = mid
    return (lo + hi) * 0.5


# 色相编码用的「等 L 等 C 色相圆」：L*=70、C*=39.8。这两个数是量出来的——
# 在 sRGB 里，L*=70 处整圈色相都能容纳的最大彩度是 41.9（85 个 L 值里最大），
# 取 0.95 倍留余量，保证 256 个采样点全部落在色域内。
#
# 为什么不用「全饱和色轮」：色相混合模式对色相误差极其敏感——ΔH=0.5° 在
# C*=90 时就折合 9.6 个码值。全饱和路径在 a*b* 平面上曲率大，256 点线性
# 插值本身就有 0.22° 误差（≈4 码）；等 L 等 C 的圆在极坐标下角度严格线性，
# 实测插值误差 0.002°，彩度又只有 40，灵敏度低一个数量级。
_HUE_L = 70.0
_HUE_C = 39.8


def _sample(fn):
    return [fn(i / float(_N - 1)) for i in range(_N)]


def _clamped(rgb):
    return tuple(min(1.0, max(0.0, c)) for c in rgb)


_HUE_PATH = _sample(lambda t: _clamped(lch_to_rgb(_HUE_L, _HUE_C, 360.0 * t)))
_CHROMA_PATH = _sample(lambda t: (0.0, 0.0, _b_for_chroma(t * MAX_CHROMA)))
_LIGHT_PATH = _sample(lambda t: (_gray_for_l(100.0 * t),) * 3)


def _channel(path, k):
    """把预计算路径的某个通道包成 gimp:curves 能用的 f(t)。"""
    def fn(t):
        x = min(1.0, max(0.0, t)) * (_N - 1)
        i = int(x)
        if i >= _N - 1:
            return path[-1][k]
        w = x - i
        return path[i][k] * (1.0 - w) + path[i + 1][k] * w
    return fn


HUE_ENCODE = tuple(_channel(_HUE_PATH, k) for k in range(3))
CHROMA_ENCODE = tuple(_channel(_CHROMA_PATH, k) for k in range(3))
LIGHT_ENCODE = _channel(_LIGHT_PATH, 0)


def _identity(t):
    return t


def _chroma_scale(t):
    """extract 的 lch-c（C/200）→ 0…1（1.0 = sRGB 最大彩度）。"""
    return min(1.0, t * CHROMA_SCALE)


# ---- 滤镜栈 / the filter stack ---------------------------------------------

def _append_curve(layer, label, fn, channel=None):
    """在图层上追加一条 gimp:curves（一维映射）。

    channel 传 None 表示「值」通道（作用于 RGB 三通道，给灰度层用）。
    trc 必须钉成 NON_LINEAR：曲线要在编码值上生效，才和分量语义一致。
    Append one curve. channel=None means the VALUE channel, which applies the
    same mapping to all three channels. trc is pinned to NON_LINEAR."""
    filt = Gimp.DrawableFilter.new(layer, "gimp:curves", label)
    cfg = filt.get_config()
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.FREE)
    n = curve.get_n_samples()
    for i in range(n):
        x = i / float(n - 1)
        curve.set_sample(x, min(1.0, max(0.0, fn(x))))
    cfg.set_property("curve", curve)
    cfg.set_property("channel",
                     channel if channel is not None else Gimp.HistogramChannel.VALUE)
    cfg.set_property("trc", Gimp.TRCType.NON_LINEAR)
    filt.update()
    layer.append_filter(filt)
    return filt


def _component_layer(image, base, title, component, mode, parent,
                     encode=None):
    """造一张分量层：extract → curve → encode，并挂好混合模式。

    extract 输出灰度、alpha 写成不透明；不用补蒙版——分量混合模式合成时沿用
    下层 alpha，透明区域照样透出去（实测逐位一致）。
    encode = dict(mode=…, props=…, value=…, rgb=…, scale=…)，由
    _append_encoder 解释；用不上算子时它会自己把 scale / 曲线补上。
    Build one component layer. No mask is needed: component modes inherit the
    backdrop alpha."""
    layer = Gimp.Layer.new_from_drawable(base, image)
    layer.set_name(title)
    layer.set_mode(mode)
    image.insert_layer(layer, parent, 0)

    filt = Gimp.DrawableFilter.new(
        layer, "gegl:component-extract", _("1 · extract"))
    cfg = filt.get_config()
    cfg.set_property("component", component)
    filt.update()
    layer.append_filter(filt)

    use_gtc = encode is not None and _gtc_available(layer)

    # 只有曲线回退路径需要那条固定的 scale，算子自己带量程参数
    has_scale = (encode is not None and encode.get("scale") is not None
                 and not use_gtc)
    if has_scale:
        _append_curve(layer, _("2 · scale (×1.52)"), encode["scale"])

    _append_curve(layer, _("3 · curve") if has_scale else _("2 · curve"),
                  _identity)

    if encode is not None:
        _append_encoder(layer, use_gtc,
                        _("4 · encode") if has_scale else _("3 · encode"),
                        encode)
    return layer


# ---- 编码器 / the encoder ---------------------------------------------------
# 优先用本仓库的 GEGL 算子 lb:gray-to-component：一个滤镜顶掉「scale + 三条
# 曲线」。它内部按 CIE Lab/LCh 的定义直接写 a*b*，没有 256 项查表的插值误差。
# The repo's own GEGL op replaces the scale curve plus three curve filters.

GTC_OP = "lb:gray-to-component"

_GTC_OK = None


def _gtc_available(layer):
    """能不能建出这个滤镜；结果缓存（GEGL 注册表进程内不变）。"""
    global _GTC_OK
    if _GTC_OK is None:
        try:
            Gimp.DrawableFilter.new(layer, GTC_OP, "probe").get_config()
            _GTC_OK = True
        except Exception:
            _GTC_OK = False
    return _GTC_OK


def _append_encoder(layer, use_gtc, label, encode):
    """挂编码：算子或曲线回退。"""
    if use_gtc:
        try:
            filt = Gimp.DrawableFilter.new(layer, GTC_OP, label)
            cfg = filt.get_config()
            cfg.set_property("mode", encode["mode"])
            for key, val in encode.get("props", {}).items():
                cfg.set_property(key, val)
            filt.update()
            layer.append_filter(filt)
            return
        except Exception:
            pass

    value = encode.get("value")
    if value is not None:
        _append_curve(layer, label, value)
        return
    for channel, fn in zip((Gimp.HistogramChannel.RED,
                            Gimp.HistogramChannel.GREEN,
                            Gimp.HistogramChannel.BLUE), encode["rgb"]):
        _append_curve(layer, label, fn, channel)


def _link_alpha_mask(image, base, host):
    """把原图层的 alpha 变成整组的蒙版。

    分量混合模式在源 alpha=1 时才是「纯替换」；若把 alpha 留在分量层上，GIMP
    会按 alpha 把结果与下层 lerp（实测半透明区偏 28 码）。所以三层一律不透明，
    alpha 交给组蒙版：颜色由三层算，透明度由原图给。
    Mask the group with the source alpha: the three component layers must stay
    opaque (a partly transparent blend layer lerps instead of replaces).
    Returns True when a mask was attached."""
    if host is None:
        return False
    try:
        if not base.has_alpha():
            return False
    except Exception:
        return False

    saved = None
    try:
        if not Gimp.Selection.is_empty(image):
            saved = Gimp.Selection.save(image)
    except Exception:
        saved = None

    try:
        image.select_item(Gimp.ChannelOps.REPLACE, base)
        mask = host.create_mask(Gimp.AddMaskType.SELECTION)
        if mask is None:
            return False
        host.add_mask(mask)
        return True
    except Exception:
        return False
    finally:
        try:
            if saved is not None:
                image.select_item(Gimp.ChannelOps.REPLACE, saved)
                image.remove_channel(saved)
            else:
                Gimp.Selection.none(image)
        except Exception:
            pass


def _item_position(image, item, fallback=0):
    try:
        proc = Gimp.get_pdb().lookup_procedure('gimp-image-get-item-position')
        cfg = proc.create_config()
        cfg.set_property('image', image)
        cfg.set_property('item', item)
        return proc.run(cfg).index(1)
    except Exception:
        return fallback


# ---- 动作 / the action ------------------------------------------------------

def split_lch(image, base, make_group=True):
    """把一个图层拆成 LCh 三张分量层 + 曲线，再用分量混合模式叠回去。

    自下而上是 色相 → 彩度 → 明度：色相层（等 L 等 C 的色相圆）垫底定 H，
    彩度层换掉 C（L、H 取自下层），明度层最后换 L。返回最上面那层
    （Lightness）；make_group 时返回包住三层的组。原图层不动，也不依赖它
    ——把原图层隐藏掉，这三层自己就能叠回原图。
    Split one layer into L/C/H curve layers that recombine to the original,
    even with the source layer hidden."""
    if base is None:
        raise RuntimeError(_("没有可以拆分的图层 / no layer to split"))
    if base.is_group():
        raise RuntimeError(
            _("图层组不能拆分：请先选一个栅格图层（右键 → 合并组）"
              " / a layer group has no pixels of its own"))

    parent = base.get_parent()
    position = _item_position(image, base)

    # 两种情况下必须分组，静默改掉：
    #  * 8 位图不分组时，三层是直接合成到 8 位投影缓冲上的，中间的量化会把色相
    #    吃掉（实测 32×32 色相图最大偏 11 码，分组时只有 0.5 码）；
    #  * 原图层带 alpha 时要靠组蒙版保住透明度，散层没有地方挂。
    auto_group = False
    if not make_group:
        try:
            needs = image.get_precision() == Gimp.Precision.U8_NON_LINEAR
            if not needs and base.has_alpha():
                needs = True
            if needs:
                make_group = True
                auto_group = True
        except Exception:
            pass

    image.undo_group_start()
    try:
        host = None
        if make_group:
            host = Gimp.GroupLayer.new(image, _("LCh split"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        # 自下而上造：Hue 最先插入（落到组的最底），Lightness 最后插到最上。
        # 顺序不能反：分量混合模式只替换一个分量，其余从下行读。最底那张必须
        # 是「等 L 等 C 的色相圆」（带真实色相），因为它下面什么都没有；若最底
        # 是 Lightness 的灰（C=0），上面两层换 C、换 H 时读到的都是 0，怎么换
        # 都是灰——把原图层藏起来就彻底还原不出来。
        hue = _component_layer(
            image, base, _("1 · Hue"), "lch-h",
            Gimp.LayerMode.LCH_HUE, host,
            encode=dict(mode="lch-hue",
                        props={"lch-l": _HUE_L, "lch-c": _HUE_C},
                        rgb=HUE_ENCODE))
        chroma = _component_layer(
            image, base, _("2 · Chroma"), "lch-c",
            Gimp.LayerMode.LCH_CHROMA, host,
            encode=dict(mode="lch-chroma",
                        props={"lch-l": _HUE_L, "chroma-scale": 200.0},
                        rgb=CHROMA_ENCODE, scale=_chroma_scale))
        light = _component_layer(
            image, base, _("3 · Lightness"), "lab-l",
            Gimp.LayerMode.LCH_LIGHTNESS, host,
            encode=dict(mode="lightness", value=LIGHT_ENCODE))

        _link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([host or light])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("LCh 分量层已建立：%s。改每层的「curve」就是调该分量的曲线；"
                "encode 别动。") % (host.get_name() if host else light.get_name())
        if auto_group:
            msg += _("\n（8 位图像必须放在组里：不分组会逐层量化，色相会偏几码。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or light


# ---- 程序包装 / procedure wrapper ------------------------------------------

class LchSplitPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-lch-split-curves']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("LCh Split (Curves)"))
        procedure.add_menu_path("<Image>/Colors/SuperMrWang/Shortcut")
        procedure.add_menu_path("<Layers>/SuperMrWang/Shortcut")

        procedure.set_documentation(
            _("把图层拆成 L / C / h 三张分量层，每层挂一条可编辑的曲线，再用"
              "「颜色」组的 LCh 明度 / 彩度 / 色相三条混合模式叠回去。恒等曲线"
              "时还原原图。"),
            _("Split into LCh component layers with per-component curves. The "
              "three layers recombine through the LCh blend modes, so editing a "
              "curve is exactly 'curve the L/C/h channel'."), name)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把三层放进一个「LCh split」穿透组里；关掉就直接叠在原图层上方"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        try:
            split_lch(image, drawables[0], config.get_property('group'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("lch-split-curves: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(LchSplitPlugin.__gtype__, sys.argv)
