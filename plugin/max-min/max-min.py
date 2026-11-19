#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 最大值 / 最小值 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   形态学的膨胀与腐蚀，也就是 Photoshop「滤镜 → 其它 → 最大值 /
           最小值」的等价物：每个像素取邻域内最大（最大值）或最小值
           （最小值）。最大值把亮区往外推、吞掉暗处的小点；最小值反过来
           收亮区、啃掉残留的白边。
           Morphological dilate / erode — Photoshop's Maximum / Minimum.

 menu      SuperMrWang → Mask → 最大值 / 最小值
           图层右键 → SuperMrWang → Mask → 最大值 / 最小值

 usage     选一个图层或图层蒙版，点菜单项，在对话框里选：

             模式      最大值（膨胀） / 最小值（腐蚀）
             半径      1–100 像素，r=1 即 3×3，边缘向外长一圈
             形状      方形（方窗） / 圆形（圆盘）
             影响 alpha 默认关：PS 同样不动图层透明度

           在图层上，结果是**非破坏**的：以 GEGL 滤镜的形式挂在图层上，在
           图层面板的滤镜列表里双击就能改参数、眼睛图标可以随时关掉。
           蒙版和通道没有滤镜栈（GIMP 3 实测：往蒙版 append 一条滤镜，API
           不报错但渲染不受影响），所以这两类目标是直接写像素，靠撤销退回。

 note      GIMP 3.2 已经不带这个功能了：gegl:dilate / gegl:erode 属于
           GEGL 的 workshop 算子，官方 Windows 构建没有编译进来，
           plug-in-dilate / plug-in-erode 也在 2.10 之后移除。所以这里用的是
           本项目自己的算子 lb:max-min（ops/max-min），不是转调原生。

           为什么不做色彩管理：PS 的这两个滤镜同样是直接对通道值取极值，
           不换算到线性光。跟着它的语义走，彩色图上才会得到一样的偏色。
           逐通道独立运算，所以红蓝交界处会出现 PS 上熟悉的那种紫边。

           单色蒙版 / 通道是这两个滤镜最合适的用法：蒙版只有一张灰度平面，
           取极值就是纯粹的「扩边 / 收边」，不会有任何偏色。

           性能：方窗可分离，3MP 图 r=1 与 r=100 都只要几十毫秒；圆盘
           不能分离，代价随半径线性增长（3MP、r=100 约 1.2 秒）。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import array
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GLib, GObject, Gegl

# 插件进程是独立的，不调用这一步的话创建 Gegl.Node 会直接段错误
# （在 python-eval 里跑同一段代码不会，所以很容易漏）。
Gegl.init()

OP = 'lb:max-min'


def _(message):
    return GLib.dgettext(None, message)


MODES = [
    ('maximum', _("最大值（膨胀：亮区外扩）")),
    ('minimum', _("最小值（腐蚀：亮区收缩）")),
]

SHAPES = [
    ('square', _("方形（(±r, ±r) 方窗）")),
    ('round', _("圆形（半径 r 的圆盘）")),
]


# ---- 动作 / the action ------------------------------------------------------

def _props(mode, radius, shape, affect_alpha):
    return {'mode': mode, 'radius': int(radius), 'shape': shape,
            'affect-alpha': bool(affect_alpha)}


def _apply_to_mask(drawable, props):
    """蒙版 / 通道：直接算完写回像素。

    GIMP 3 的滤镜栈只作用于图层：往蒙版上 append 一条滤镜，API 不报错，
    但 get_filters() 始终为空，渲染也不受影响（实测 3.2.8）。蒙版在 GIMP
    里本来就是「滤镜一挂即写死」的语义，所以这里老实走一遍临时 GEGL 图，
    结果写回缓冲。格式取 Y float，8 位蒙版往返仍是同一字节。
    Masks carry no filter stack in GIMP 3, so bake the result instead.
    """
    buf = drawable.get_buffer()
    w, h = drawable.get_width(), drawable.get_height()
    _, ox, oy = drawable.get_offsets()
    rect = Gegl.Rectangle.new(ox, oy, w, h)
    fmt = "Y float"

    src = Gegl.Buffer.new(fmt, ox, oy, w, h)
    src.set(rect, fmt, buf.get(rect, 1.0, fmt, Gegl.AbyssPolicy.NONE))

    root = Gegl.Node.new()
    node_src = root.create_child("gegl:buffer-source")
    node_src.set_property("buffer", src)
    node = root.create_child(OP)
    for k, v in props.items():
        node.set_property(k, v)
    node_src.connect_to("output", node, "input")

    out = Gegl.Buffer.new(fmt, ox, oy, w, h)
    node.blit_buffer(out, rect, 0, Gegl.AbyssPolicy.NONE)

    buf.set(rect, fmt, out.get(rect, 1.0, fmt, Gegl.AbyssPolicy.NONE))
    buf.flush()
    drawable.update(ox, oy, w, h)


def _apply_to_layer(drawable, props, label):
    """图层：挂一条非破坏滤镜，参数随时可改、可关掉。"""
    try:
        filt = Gimp.DrawableFilter.new(drawable, OP, label)
    except Exception:
        raise RuntimeError(
            _("缺少算子 lb:max-min，请先安装 dist 里的模块"
              " / lb:max-min is not installed"))
    cfg = filt.get_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    filt.update()
    drawable.append_filter(filt)
    return filt


def max_min(image, drawable, mode='maximum', radius=1, shape='square',
            affect_alpha=False):
    """图层挂滤镜；蒙版 / 通道直接写像素。"""
    if drawable is None:
        raise RuntimeError(_("没有可以处理的图层 / no drawable to work on"))
    if drawable.is_group():
        raise RuntimeError(
            _("图层组不能处理：请先选一个栅格图层或它的蒙版"
              " / a layer group has no pixels of its own"))

    props = _props(mode, radius, shape, affect_alpha)
    label = _("最大值") if mode == 'maximum' else _("最小值")
    is_layer = isinstance(drawable, Gimp.Layer)

    image.undo_group_start()
    try:
        if is_layer:
            filt = _apply_to_layer(drawable, props, label)
        else:
            filt = None
            _apply_to_mask(drawable, props)
        try:
            image.set_selected_layers([drawable])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        shape_txt = _("方形") if shape == 'square' else _("圆形")
        if is_layer:
            msg = _("已挂上「%s」：半径 %d、%s。这是非破坏滤镜——在图层面板"
                    "的滤镜列表里双击可以改参数，眼睛图标可以随时关掉。") % (
                        label, radius, shape_txt)
        else:
            msg = _("已对%s应用「%s」：半径 %d、%s。蒙版和通道不接受非破坏"
                    "滤镜，结果已写入像素（撤销可以退回）。") % (
                        _("蒙版") if isinstance(drawable, Gimp.LayerMask)
                        else _("通道"),
                        label, radius, shape_txt)
        Gimp.message(msg)
    except Exception:
        pass
    return filt


# ---- 程序包装 / procedure wrapper ------------------------------------------

class MaxMinPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-max-min']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("最大值 / 最小值 (Max / Min)"))
        procedure.add_menu_path("<Image>/SuperMrWang/Mask")
        procedure.add_menu_path("<Layers>/SuperMrWang/Mask")

        procedure.set_documentation(
            _("形态学的最大值（膨胀）与最小值（腐蚀）：每个像素取邻域内的"
              "最大 / 最小值。最大值扩边、去暗点；最小值收边、去亮点。"
              "以非破坏滤镜形式挂在图层或蒙版上，参数随时可改。"),
            _("Morphological maximum (dilate) and minimum (erode) over a "
              "square or round neighbourhood, attached as a non-destructive "
              "drawable filter."), name)

        mode = Gimp.Choice.new()
        for i, (nick, label) in enumerate(MODES):
            mode.add(nick, i, label, label)
        procedure.add_choice_argument(
            "mode", _("模式"), _("最大值＝膨胀，最小值＝腐蚀"),
            mode, 'maximum', GObject.ParamFlags.READWRITE)

        procedure.add_int_argument(
            "radius", _("半径"), _("邻域半径（像素）。r=1 即 3×3，边缘向外长一圈"),
            1, 100, 1, GObject.ParamFlags.READWRITE)

        shape = Gimp.Choice.new()
        for i, (nick, label) in enumerate(SHAPES):
            shape.add(nick, i, label, label)
        procedure.add_choice_argument(
            "shape", _("形状"), _("方形＝方窗；圆形＝圆盘（对应 PS 的方形度 / 圆度）"),
            shape, 'square', GObject.ParamFlags.READWRITE)

        procedure.add_boolean_argument(
            "affect_alpha", _("影响 alpha"),
            _("关掉时 alpha 原样保留（PS 同样不改图层透明度）"),
            False, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("请选择一个图层或其蒙版 / select a layer or a mask")))
        try:
            max_min(image, drawables[0],
                    config.get_property('mode') or 'maximum',
                    config.get_property('radius') or 1,
                    config.get_property('shape') or 'square',
                    config.get_property('affect_alpha'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("max-min: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(MaxMinPlugin.__gtype__, sys.argv)
