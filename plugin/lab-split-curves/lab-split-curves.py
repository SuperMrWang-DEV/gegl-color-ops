#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · Lab 分量分解 + 曲线 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   在 CIE Lab 空间里调曲线。GIMP 有 LCh 的三条分量混合模式和 HSV
           的三条，却没有 Lab 的——因为 Lab 的 a/b 是直角坐标，不是「色相 +
           彩度」那种可以直接搬的模式分量。本插件用两个适配算子把 Lab 接到
           LCh 明度 + 正常模式上，做到与直接改 Lab 完全等价：恒等曲线时逐像素
           还原原图，调 a 曲线就只动 a，调 L 曲线就只动 L。
           Curve Lab itself, adapting it onto GIMP's LCh lightness mode.

 menu      颜色 → SuperMrWang → Shortcut → Lab Split (Curves)
           图层右键 → SuperMrWang → Shortcut → Lab Split (Curves)

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              Lab split           组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 2 · L            模式 = LCh 明度   ← 只替换 L*
                ├─ 1 · a / b        模式 = 正常       ← 一条算子链算出完整 Lab 色
                └─ 原图层（不动，可以隐藏）

 note      为什么是两层，不是三层：GIMP 有「LCh 彩度」「LCh 色相」两条模式，
           而 LCh 正是 Lab 的极坐标形式，看起来 a/b 可以拆成 C/h 两层搞定——
           但每层的曲线只看得到自己那一个分量。要让 a 曲线和 b 曲线各自独立地
           映射，必须先把 (a, b) 两个值同时拿到手，再一起换算成 (C, h)；而
           「LCh 彩度」层手上只有一个标量 C，它没法知道 b 变成了多少。
           所以 a 与 b 必须挤进同一张数据图（R=a、G=b），两条曲线各挂一个
           通道，再由 lb:lab-compose 联合还原成颜色——这一层算出来的本来就是
           完整颜色（含 L），于是第三层不需要了；它上面只留一层「LCh 明度」
           模式，把 L* 换成曲线后的值。

           对比一下硬凑三层的代价：Lab 的 L* 恰好就是 LCh 的 L*（同一个量，
           babl 里就是同一个通道），所以 L 层与 LCh 明度模式逐位对齐，零误差；
           而 a/b 若想改用 LCh 彩度/色相模式，C 与 h 是 (a,b) 的二元函数，
           两条一维曲线表达不了。

           每层的滤镜栈（图层面板里从上往下读是 2 → 1，执行顺序相反）：

             a/b 层   1 · decompose   lb:lab-dual     原图 → (R=a, G=b, B=L)
                      2 · a curve     gimp:curves     通道 = R（红）
                      3 · b curve     gimp:curves     通道 = G（绿）
                      4 · compose     lb:lab-compose  (a,b,L) → 真实 Lab 色

             L 层     1 · lightness   gegl:component-extract  component=lab-l
                      2 · L curve     gimp:curves     通道 = 值
                      3 · encode      lb:gray-to-component  mode=lightness

           量程（babl 口径，D50 白点，与 GIMP 的 Lab 空间一致）：
             a / b    (a + 128) / 255      0…1，中性灰 a=b=0 → 0.502
             L        L* / 100             0…1

           实测（GIMP 3.2.8，见 tools/check_lab_split.py）：
             32 位浮点图，恒等曲线往返：   最大 0.03 码
             8 位图，恒等曲线往返：        ≤ 1 码
             隐藏原图层后两层自己还原：     与可见时同值

           注意事项：
           - a 曲线挂在**红**通道、b 曲线挂在**绿**通道。在图层属性的滤镜里
             改曲线时记得选对通道；选「值」会把两条数据一起改掉。
           - 中性灰上 a、b 是 0（数据图里 0.502），把 a 曲线在 0.5 附近往上抬
             就是往洋红推、往下压是往绿推；b 曲线同理（上=黄，下=蓝）。
           - 这套精确适配依赖 lb:lab-dual 与 lb:lab-compose 两个算子；缺了
             它们就没有等价回退（a/b 是二元映射，一维曲线凑不出来），插件会
             直接报错。
           - 图层自带的非破坏滤镜不会被复制（new_from_drawable 只取像素）。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math
import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject


def _(message):
    return GLib.dgettext(None, message)


def _identity(t):
    return t


# 精确适配用的两个算子（本仓库 ops/lab-dual、ops/lab-compose）
DUAL_OP = "lb:lab-dual"
COMPOSE_OP = "lb:lab-compose"
GTC_OP = "lb:gray-to-component"


# ---- 颜色数学 / colour maths ------------------------------------------------
# 与 babl 同口径：sRGB 编码值 ↔ 线性 → XYZ(D65) → Bradford D50 → CIE Lab(D50)。
# component-extract 的 lab-l 与 LCh 明度混合模式用的就是这一套。
# Same pipeline as babl: encoded sRGB -> linear -> XYZ(D65) -> Bradford D50.

_DELTA = 6.0 / 29.0
_DELTA3 = _DELTA ** 3
_D50 = (0.96422, 1.0, 0.82521)

_SRGB_TO_XYZ = ((0.4124564, 0.3575761, 0.1804375),
                (0.2126729, 0.7151522, 0.0721750),
                (0.0193339, 0.1191920, 0.9503041))
_XYZ_TO_SRGB = ((3.2404542, -1.5371385, -0.4985314),
                (-0.9692660, 1.8760108, 0.0415560),
                (0.0556434, -0.2040259, 1.0572252))
_D65_TO_D50 = ((1.0478112, 0.0228866, -0.0501270),
               (0.0295424, 0.9904844, -0.0170491),
               (-0.0092345, 0.0150436, 0.7521316))
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


def rgb_to_lab(rgb):
    """编码 sRGB → (L*, a*, b*)，白点 D50。"""
    lin = tuple(_srgb_to_linear(c) for c in rgb)
    xyz = _mul(_D65_TO_D50, _mul(_SRGB_TO_XYZ, lin))
    fx, fy, fz = (_f(xyz[i] / _D50[i]) for i in range(3))
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def lab_to_rgb(light, a, b):
    """(L*, a*, b*) → 编码 sRGB；不裁色域（可能出负值/超 1）。"""
    fy = (light + 16.0) / 116.0
    fx, fz = fy + a / 500.0, fy - b / 200.0
    xyz = (_D50[0] * _f_inv(fx), _D50[1] * _f_inv(fy), _D50[2] * _f_inv(fz))
    xyz = _mul(_D50_TO_D65, xyz)
    return tuple(_linear_to_srgb(c) for c in _mul(_XYZ_TO_SRGB, xyz))


# ---- 明度编码（没有 gray-to-component 时的回退） ---------------------------
# L* → 编码值灰（三通道相同）。a=b=0 时 XYZ = (Xn, Y, Zn)，线性 sRGB 三分量
# 都等于 Y，所以一条一维映射就够。
# L* -> encoded grey; with a=b=0 all three linear channels equal Y.

_N = 256


def _gray_for_l(light):
    if light > 8.0:
        y = ((light + 16.0) / 116.0) ** 3
    else:
        y = light / (3.0 * _DELTA * _DELTA * 116.0)
    return min(1.0, max(0.0, _linear_to_srgb(y)))


_LIGHT_PATH = [_gray_for_l(100.0 * i / float(_N - 1)) for i in range(_N)]


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


LIGHT_ENCODE = _channel(_LIGHT_PATH, 0)


# ---- 滤镜栈 / the filter stack ---------------------------------------------

def _append_curve(layer, label, fn, channel=None):
    """在图层上追加一条 gimp:curves（一维映射）。

    channel=None 表示「值」通道（三通道同一映射，给灰度层用）。
    trc 钉成 NON_LINEAR：曲线在编码值上生效，与分量语义一致。
    Append one curve; channel=None means the VALUE channel."""
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
                     channel if channel is not None
                     else Gimp.HistogramChannel.VALUE)
    cfg.set_property("trc", Gimp.TRCType.NON_LINEAR)
    filt.update()
    layer.append_filter(filt)
    return filt


def _simple_filter(layer, op, label, props=None):
    """挂一个不需要曲线的算子滤镜（lb:lab-dual / lb:lab-compose 这类）。"""
    filt = Gimp.DrawableFilter.new(layer, op, label)
    if props:
        cfg = filt.get_config()
        for key, value in props.items():
            cfg.set_property(key, value)
    filt.update()
    layer.append_filter(filt)
    return filt


def _append_encoder(layer, label):
    """给明度灰度层挂编码：优先 lb:gray-to-component，缺算子时退回一条曲线。"""
    try:
        filt = Gimp.DrawableFilter.new(layer, GTC_OP, label)
        filt.get_config().set_property("mode", "lightness")
        filt.update()
        layer.append_filter(filt)
        return [filt]
    except Exception:
        return [_append_curve(layer, label, LIGHT_ENCODE)]


def _require_adapter_ops(layer):
    """确认两个适配算子可用。

    没有它们就没有等价回退：a/b 是二元映射，一维曲线表达不了。
    The adapter pair is mandatory; there is no curve-only fallback."""
    missing = []
    for op in (DUAL_OP, COMPOSE_OP):
        try:
            Gimp.DrawableFilter.new(layer, op, "probe")
        except Exception:
            missing.append(op)
    if missing:
        raise RuntimeError(
            _("缺少适配算子：%s。它们是 Lab 精确适配的必需组件（a 与 b 必须联合"
              "计算，无法用一维曲线代替）。请先安装本仓库的 GEGL 算子的 "
              "lab-dual / lab-compose（./install.sh），重启 GIMP 再试。")
            % ", ".join(missing))


def _link_alpha_mask(image, base, host):
    """把原图层的 alpha 变成整组的蒙版。

    分量层必须不透明（半透明层的混合会按 alpha 做 lerp，实测偏 28 码），
    透明度交给组蒙版：颜色由图层算，透明度由原图给。
    Mask the group with the source alpha; component layers stay opaque."""
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

def split_lab(image, base, make_group=True):
    """把图层拆成「a/b 联合层 + L 层」，在 Lab 空间里调曲线。

    返回最上面那层（L）；make_group 时返回包住两层的组。原图层不动，把它
    隐藏掉这两层自己就能还原。
    Split into an a/b layer and an L layer that recombine exactly to the
    original, even with the source hidden."""
    if base is None:
        raise RuntimeError(_("没有可以拆分的图层 / no layer to split"))
    if base.is_group():
        raise RuntimeError(
            _("图层组不能拆分：请先选一个栅格图层（右键 → 合并组）"
              " / a layer group has no pixels of its own"))

    _require_adapter_ops(base)

    parent = base.get_parent()
    position = _item_position(image, base)

    # 带 alpha 的图层必须分组：透明度靠组蒙版保住，散层没有地方挂。
    auto_group = False
    if not make_group:
        try:
            if base.has_alpha():
                make_group = True
                auto_group = True
        except Exception:
            pass

    image.undo_group_start()
    try:
        host = None
        if make_group:
            host = Gimp.GroupLayer.new(image, _("Lab split"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        # 自下而上：a/b 层先插入（落最底，正常模式），L 层最后插到最上。
        ab = Gimp.Layer.new_from_drawable(base, image)
        ab.set_name(_("1 · a / b"))
        ab.set_mode(Gimp.LayerMode.NORMAL)
        image.insert_layer(ab, host, 0)

        _simple_filter(ab, DUAL_OP, _("1 · decompose"))
        _append_curve(ab, _("2 · a curve"), _identity,
                      Gimp.HistogramChannel.RED)
        _append_curve(ab, _("3 · b curve"), _identity,
                      Gimp.HistogramChannel.GREEN)
        _simple_filter(ab, COMPOSE_OP, _("4 · compose"))

        # L 层：只替换 L*，a 和 b 保留下面那层的。Lab 的 L* 就是 LCh 的 L*，
        # 所以 LCh 明度模式在这里是逐位精确的。
        light = Gimp.Layer.new_from_drawable(base, image)
        light.set_name(_("2 · L"))
        light.set_mode(Gimp.LayerMode.LCH_LIGHTNESS)
        image.insert_layer(light, host, 0)

        _simple_filter(light, "gegl:component-extract", _("1 · lightness"),
                       {"component": "lab-l"})
        _append_curve(light, _("2 · L curve"), _identity,
                      Gimp.HistogramChannel.VALUE)
        _append_encoder(light, _("3 · encode"))

        _link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([host or light])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("Lab 分量层已建立：%s。a 曲线在「2 · a curve」（红通道）、"
                "b 曲线在「3 · b curve」（绿通道）、明度曲线在 L 层的"
                "「2 · L curve」。原图层可以隐藏，这两层自己就能还原。") \
              % (host.get_name() if host else light.get_name())
        if auto_group:
            msg += _("\n（这张图带透明，已自动分组：透明度靠组蒙版保住。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or light


# ---- 程序包装 / procedure wrapper ------------------------------------------

class LabSplitPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-lab-split-curves']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("Lab Split (Curves)"))
        procedure.add_menu_path("<Image>/Colors/SuperMrWang/Shortcut")
        procedure.add_menu_path("<Layers>/SuperMrWang/Shortcut")

        procedure.set_documentation(
            _("在 CIE Lab 空间里调曲线：生成一个 a/b 联合层（红通道 = a、"
              "绿通道 = b）和一个只替换 L* 的 L 层。恒等曲线时精确还原原图，"
              "调哪条曲线就只动那个 Lab 分量。"),
            _("Curve Lab itself. An a/b layer (R = a, G = b) plus an L* layer "
              "on top; identity curves reproduce the image exactly. Needs "
              "lb:lab-dual and lb:lab-compose."), name)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把两层放进一个「Lab split」穿透组里；关掉就直接叠在原图层上方"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        try:
            split_lab(image, drawables[0], config.get_property('group'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("lab-split-curves: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(LabSplitPlugin.__gtype__, sys.argv)
