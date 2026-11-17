#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · Lab 分量分解 + 曲线 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   在 CIELAB 空间里调曲线。L* 是感知明度，a 是绿–品红轴，b 是蓝–黄轴；
           「黄了压 b、偏绿推 a」比在 RGB 里拉曲线直观得多。本插件把三个分量
           打包进一张数据图，三条曲线各管一个，再一起解回真实颜色。
           Curve CIELAB itself: one data layer (R = a, G = b, B = L*) with
           three curves. Identity curves reproduce the image exactly.

 menu      颜色 → SuperMrWang → Shortcut → Lab Split (Curves)
           图层右键 → SuperMrWang → Shortcut → Lab Split (Curves)

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              Lab split       组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 1 · Lab a/b/L   正常模式   ← 一条算子链算出完整 Lab 色
                └─ 原图层（不动，可以隐藏）

 note      和 HSI 那个插件同一个骨架：三个分量挤进一张数据图，一次算完再还原。
           旧版是两层：a/b 联合层用正常模式，L* 单独一层借 LCh 明度模式（L* 那个
           通道在两种空间里是同一个量）。现在 L* 也进 compose，一层就够——
           少一层的意义不只是省一个图，还少了「L 层用混合模式、ab 层用普通模式」
           这种两套语义并存的地方。

           滤镜栈（图层面板里从上往下读，执行顺序相反）：

             1 · decompose   lb:lab-dual   原图 → (R=a, G=b, B=L*/100)
             2 · a curve     gimp:curves     通道 = R（红）
             3 · b curve     gimp:curves     通道 = G（绿）
             4 · L curve     gimp:curves     通道 = B（蓝）
             5 · compose     lb:lab-compose   (a,b,L*) → 真实颜色

           量程：
             a, b  -128…+127  → (a+128)/255
             L*     0…100      → /100

           实测（GIMP 3.2.8，见 tools/check_lab_split.py）：
             32 位浮点图，恒等曲线往返：   最大 0.02 码
             8 位图，恒等曲线往返：        ≤ 0.5 码
             隐藏原图层后自己还原：         与可见时同值
             只改 a 曲线时 b、L* 的偏差：    < 0.02 码

           注意事项：
           - 三条曲线分别挂在**红 / 绿 / 蓝**通道上：a 在红、b 在绿、L* 在蓝。
             在图层属性的滤镜里改曲线时记得选对通道；选「值」会把三条数据
             一起改掉。
           - 色相曲线必须是连续的（两端相等、中间不跳变）。整体旋转色相请用
             lb:hue-saturation；这条曲线适合「压缩 / 拉伸某段色相」。
- a、b 是直角坐标：调 a 会连带改彩度与色相（这正是「整体偏绿」该有的
             行为）。要彩度、色相各自单独动，用 LCh 那个插件。
           - 分量推到头会出 sRGB 色域，8 位图按 0/1 裁切。
           - 这套精确适配依赖 lb:lab-dual 与 lb:lab-compose 两个算子；缺了它们就没有
             等价回退，插件会直接报错。
           - 图层自带的非破坏滤镜不会被复制（new_from_drawable 只取像素）。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

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


# ---- 滤镜栈 / the filter stack ---------------------------------------------

def _append_curve(layer, label, fn, channel):
    """在图层上追加一条 gimp:curves（通道级一维映射）。

    trc 钉成 NON_LINEAR：曲线在编码值上生效，与分量语义一致。
    Append one channel curve, pinned to encoded (NON_LINEAR) values."""
    filt = Gimp.DrawableFilter.new(layer, "gimp:curves", label)
    cfg = filt.get_config()
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.FREE)
    n = curve.get_n_samples()
    for i in range(n):
        x = i / float(n - 1)
        curve.set_sample(x, min(1.0, max(0.0, fn(x))))
    cfg.set_property("curve", curve)
    cfg.set_property("channel", channel)
    cfg.set_property("trc", Gimp.TRCType.NON_LINEAR)
    filt.update()
    layer.append_filter(filt)
    return filt


def _simple_filter(layer, op, label):
    """挂一个不需要曲线的算子滤镜（lb:lab-dual / lb:lab-compose 这类）。"""
    filt = Gimp.DrawableFilter.new(layer, op, label)
    filt.update()
    layer.append_filter(filt)
    return filt


def _require_adapter_ops(layer):
    """确认两个适配算子可用。"""
    missing = []
    for op in (DUAL_OP, COMPOSE_OP):
        try:
            Gimp.DrawableFilter.new(layer, op, "probe")
        except Exception:
            missing.append(op)
    if missing:
        raise RuntimeError(
            _("缺少适配算子：%s。它们是 Lab 精确适配的必需组件（三个分量必须"
              "在同一张数据图里一起算）。请先安装本仓库的 GEGL 算子 lab-dual / "
              "lab-compose（./install.sh），重启 GIMP 再试。") % ", ".join(missing))


def _link_alpha_mask(image, base, host):
    """把原图层的 alpha 变成整组的蒙版。

    分量层必须不透明（半透明层的混合会按 alpha 做 lerp），透明度交给组蒙版。
    Mask the group with the source alpha; the data layer stays opaque."""
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
    """把图层换成一张「a / b / L* 三联曲线」的 Lab 层。

    返回那张层；make_group 时返回包住它的组。原图层不动，把它隐藏掉这一层
    自己就能还原。
    Replace the layer with one Lab data layer carrying three curves; it
    reproduces the original on its own, with the source hidden."""
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

        layer = Gimp.Layer.new_from_drawable(base, image)
        layer.set_name(_("1 · Lab a/b/L"))
        layer.set_mode(Gimp.LayerMode.NORMAL)
        image.insert_layer(layer, host, 0)

        _simple_filter(layer, DUAL_OP, _("1 · decompose"))
        _append_curve(layer, _("2 · a curve"), _identity, Gimp.HistogramChannel.RED)
        _append_curve(layer, _("3 · b curve"), _identity, Gimp.HistogramChannel.GREEN)
        _append_curve(layer, _("4 · L curve"), _identity, Gimp.HistogramChannel.BLUE)
        _simple_filter(layer, COMPOSE_OP, _("5 · compose"))

        _link_alpha_mask(image, base, host)

        try:
            image.set_selected_layers([host or layer])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    try:
        msg = _("Lab 层已建立：%s。a 曲线在「2 · a curve」（红通道）、b 曲线在「3 · b curve」（绿通道）、L 曲线在「4 · L curve」（蓝通道）。 原图层可以隐藏，这一层自己就能还原。") \
              % (host.get_name() if host else layer.get_name())
        if auto_group:
            msg += _("\n（这张图带透明，已自动分组：透明度靠组蒙版保住。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or layer


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
            _("在 CIELAB 里调曲线：生成一张三联数据图（红通道 = a、绿通道 = b、蓝通道 = L*），三条曲线各管一个分量。恒等曲线时精确还原原图。"),
            _("Curve CIELAB itself. One data layer (R = a, G = b, B = L*) with three curves; identity curves reproduce the image exactly. Needs lb:lab-dual and lb:lab-compose."), name)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把这一层放进一个「Lab split」穿透组里；关掉就直接叠在原图层上方"),
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
