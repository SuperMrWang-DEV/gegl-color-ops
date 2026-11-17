#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · Alpha Curves（透明通道曲线）—— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   给图层的 alpha 挂一条**可以随便画的曲线**。GIMP 的曲线工具本来
           就有 Alpha 通道，但那条曲线只能调「已经存在的透明度」；想在
           「某个颜色通道的数值」上画曲线，得先把那个通道搬进 alpha。这个
           插件把两步一起做好，两条都是非破坏滤镜：

             1 · 通道 → Alpha    lb:channel-range-to-alpha（斜坡拉满 = 线性拷贝）
             2 · Alpha 曲线      gimp:curves，通道 = Alpha

           第 2 条就是普通的曲线：拖点即改，可以画成任意一维映射，比
           Range → Alpha 的四滑块自由得多（S 形、多次起伏、只压半透明）。
           Curve the alpha channel: copy one colour channel into alpha, then
           put an editable gimp:curves on the alpha channel. Both are
           non-destructive drawable filters.

 menu      颜色 → SuperMrWang → Mask → Alpha Curves
           图层右键 → SuperMrWang → Shortcut → Alpha Curves

 usage     选中一个栅格图层 → 菜单项。图层上多出两条滤镜（图层面板可见）：

             Alpha Curves
               ├─ 2 · Alpha 曲线          gimp:curves（通道 = Alpha）
               └─ 1 · 通道 → Alpha        lb:channel-range-to-alpha

           默认是一条**平顶**曲线：0 / 128 / 255 三个控制点，输出都在 255。
           打开滤镜就看见三个抓手，往下拖任意一个就是形状；曲线是 SMOOTH
           （平滑样条），不是那种几十个采样点的手绘线。想要现成的形状可以用
           shape 参数选 band / identity / soft。

 note      为什么曲线不能一步做完：gimp:curves 的输入只有像素自己，它不知道
           「红通道是多少」，所以曲线只能作用于 alpha（或 R/G/B）。要按颜色
           通道决定透明度，必须先把那个通道写进 alpha——第 1 条滤镜就是把
           Range → Alpha 的斜坡拉满（l1=0、l2=255、r1=r2=255），退化成
           「alpha ← 通道值」的线性拷贝。曲线接在它后面，输入就正好是通道值。

           两条滤镜是**乘**的关系：第 1 条把通道值乘进原有 alpha，第 2 条
           再映射一次。原图不透明（alpha=1）时，结果就是「曲线(通道值)」，
           与 Range → Alpha 完全等价。

           曲线的 trc 钉成 NON_LINEAR：通道值按伽马编码读取，和
           lb:channel-range-to-alpha 的 0–255 滑块同一刻度。

           Alpha 通道没有「源通道」可拷，选 channel = alpha 时只挂第 2 条。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GLib, GObject

# 曲线在编码值上生效，与 Range → Alpha 的 0–255 滑块同一刻度。
# Curves run on encoded values, the same scale as the operator's sliders.
TRC = Gimp.TRCType.NON_LINEAR

RANGE_OP = 'lb:channel-range-to-alpha'
CURVE_OP = 'gimp:curves'


def _(message):
    return GLib.dgettext(None, message)


CHANNELS = [
    ('gray', _("Gray（0.299R + 0.587G + 0.114B）")),
    ('red', _("Red")),
    ('green', _("Green")),
    ('blue', _("Blue")),
    ('lab-l', _("LAB L（明度）")),
    ('lab-a', _("LAB A（绿–品红）")),
    ('lab-b', _("LAB B（蓝–黄）")),
    ('alpha', _("Alpha（只调现有透明度）")),
]


# ---- 曲线形状 / curve shapes ------------------------------------------------
#
# 形状一律用**控制点**表示（坐标 0…1，界面上就是 0…255），挂 SMOOTH 平滑
# 曲线：点少，打开滤镜就能直接拖。不用 FREE（手绘）——那种曲线是几十个
# 采样点串出来的，想动某一段得先在一堆点里找准，手没法拖。
#
#     flat      0 / 128 / 255 三个点都在顶（默认）
#     band      两端收到 0、中间满，混合颜色带的样子
#     identity  45° 直线，alpha 正好等于通道值
#     soft      smoothstep 的取样点，两端平、中间陡

SHAPES = {
    'flat': ((0.0, 1.0), (0.5, 1.0), (1.0, 1.0)),
    'band': ((0.0, 0.0), (0.08, 1.0), (0.5, 1.0), (0.92, 1.0), (1.0, 0.0)),
    'identity': ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0)),
    'soft': ((0.0, 0.0), (0.25, 0.15625), (0.5, 0.5),
             (0.75, 0.84375), (1.0, 1.0)),
}


def _shape_for(shape, channel):
    """auto（以及任何不认识的值）：三个点都在顶的平顶曲线。

    打开插件先看到一条满不透明的曲线，再往下拖成想要的形状。"""
    return shape if shape in SHAPES else 'flat'


def _point_curve(points):
    """按控制点造一条平滑曲线（SMOOTH）。"""
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.SMOOTH)
    for x, y in points:
        curve.add_point(float(x), float(y))
    return curve


# ---- 滤镜 / filters ---------------------------------------------------------

def _add_range_to_alpha(layer, channel):
    """第 1 条：把选定通道线性写进 alpha（斜坡拉满 = 直通）。

    l1=0、l2=255、r1=r2=255 时映射退化成 f(x) = x/255，区间外没有衰减，
    所以这条滤镜等价于「alpha ← 通道值」，再乘进原有 alpha。
    """
    filt = Gimp.DrawableFilter.new(layer, RANGE_OP, _("1 · 通道 → Alpha"))
    cfg = filt.get_config()
    cfg.set_property('channel', channel)
    cfg.set_property('l1', 0.0)
    cfg.set_property('l2', 255.0)
    cfg.set_property('r1', 255.0)
    cfg.set_property('r2', 255.0)
    filt.update()
    layer.append_filter(filt)
    return filt


def _add_alpha_curve(layer, shape):
    """第 2 条：alpha 上的一条可编辑曲线（平滑，少量控制点）。"""
    filt = Gimp.DrawableFilter.new(layer, CURVE_OP, _("2 · Alpha 曲线"))
    cfg = filt.get_config()
    cfg.set_property('curve', _point_curve(SHAPES[shape]))
    cfg.set_property('channel', Gimp.HistogramChannel.ALPHA)
    cfg.set_property('trc', TRC)
    filt.update()
    layer.append_filter(filt)
    return filt


def _require_range_op(layer):
    """确认 lb:channel-range-to-alpha 已注册；缺了就直接报错，别默默只挂曲线。"""
    try:
        probe = Gimp.DrawableFilter.new(layer, RANGE_OP, "probe")
    except Exception:
        raise RuntimeError(
            _("缺少算子 lb:channel-range-to-alpha，无法把通道写进 alpha。"
              "装一下 dist 里的模块，或者把「源通道」选成 alpha 只挂曲线。"
              " / lb:channel-range-to-alpha is not installed"))
    try:
        probe.delete()
    except Exception:
        pass


# ---- 动作 / the action ------------------------------------------------------

def alpha_curves(image, base, channel='gray', shape='auto'):
    """在图层上挂「通道 → Alpha」与「Alpha 曲线」两条滤镜。"""
    if base is None:
        raise RuntimeError(_("没有可以处理的图层 / no layer to work on"))
    if base.is_group():
        raise RuntimeError(
            _("图层组不能处理：请先选一个栅格图层（右键 → 合并组）"
              " / a layer group has no pixels of its own"))

    shape = _shape_for(shape, channel)
    if channel != 'alpha':
        _require_range_op(base)

    image.undo_group_start()
    try:
        if not base.has_alpha():
            base.add_alpha()
        if channel != 'alpha':
            _add_range_to_alpha(base, channel)
        _add_alpha_curve(base, shape)
        try:
            image.set_selected_layers([base])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("Alpha Curves 已挂上：%s。点开「2 · Alpha 曲线」就能拖控制点，"
                "画成任意映射——恒等时 alpha 正好等于该通道值。"
                "（初始是平顶：三个点都在 255，往下拖即成形状。）"
                % (_("两条滤镜（通道 → Alpha，Alpha 曲线）")
                   if channel != 'alpha' else _("一条 Alpha 曲线")))
        Gimp.message(msg)
    except Exception:
        pass
    return base


# ---- 程序包装 / procedure wrapper ------------------------------------------

class AlphaCurvesPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-alpha-curves']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("Alpha Curves（透明通道曲线）"))
        procedure.add_menu_path("<Image>/Colors/SuperMrWang/Mask")
        procedure.add_menu_path("<Layers>/SuperMrWang/Shortcut")

        procedure.set_documentation(
            _("给 alpha 挂一条可编辑曲线：先把选定颜色通道写进 alpha，"
              "再接一条 gimp:curves（通道 = Alpha）。两条都是非破坏滤镜，"
              "曲线可以画成任意形状，比 Range → Alpha 的四个滑块自由得多。"),
            _("Curve the alpha channel: copy a colour channel into alpha, then "
              "put an editable curve on it. Non-destructive; the curve can be "
              "any shape, unlike the linear ramps of Range to Alpha."), name)

        channel = Gimp.Choice.new()
        for i, (nick, label) in enumerate(CHANNELS):
            channel.add(nick, i, label, label)
        procedure.add_choice_argument(
            "channel", _("源通道"),
            _("用哪一路通道决定透明度；alpha 表示只调现有透明度"),
            channel, 'gray', GObject.ParamFlags.READWRITE)

        shape = Gimp.Choice.new()
        shape.add('auto', 0, _("auto（自动）"),
                  _("平顶曲线：0 / 128 / 255 三个点都在顶，往下拖就是形状"))
        shape.add('flat', 1, _("flat（平顶）"),
                  _("三个控制点全在 255：alpha 拉满，之后自己往下拖"))
        shape.add('band', 2, _("band（混合颜色带）"),
                  _("两端收到透明、中间不透明，用平滑曲线拐弯"))
        shape.add('identity', 3, _("identity（恒等）"),
                  _("45° 直线：alpha 正好等于通道值，之后自己拖点"))
        shape.add('soft', 4, _("soft（S 形）"),
                  _("smoothstep 的取样点：两端平、中间陡，单调不减"))
        procedure.add_choice_argument(
            "shape", _("初始曲线"), _("挂上去时曲线的初始形状，之后随便改"),
            shape, 'auto', GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        try:
            alpha_curves(image, drawables[0],
                         config.get_property('channel') or 'gray',
                         config.get_property('shape') or 'auto')
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("alpha-curves: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(AlphaCurvesPlugin.__gtype__, sys.argv)
