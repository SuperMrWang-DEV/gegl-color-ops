#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · HSI 分量分解 + 曲线 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   在 HSI 空间里调曲线。HSI 的 I 是 (R+G+B)/3——比 HSV 的 max 更接近
           感知亮度，图像分析和曝光校正里常用；但 GIMP 既没有 HSI 空间也没有
           HSI 分量混合模式，本插件用两个适配算子把三个分量挤进一张数据图联合
           计算，做到与直接改 HSI 完全等价：恒等曲线逐像素还原原图，调哪条
           曲线就只动那个分量。
           Curve HSI itself, by computing all three components in one data
           image (GIMP has no HSI component blend modes).

 menu      颜色 → SuperMrWang → Shortcut → HSI Split (Curves) · single
           图层右键 → SuperMrWang → Shortcut → HSI Split (Curves) · single

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              HSI split              组，穿透混合（带 alpha 时组上还有一张蒙版）
                ├─ 1 · HSI S/I/H     正常模式   ← 一条算子链算出完整 HSI 色
                └─ 原图层（不动，可以隐藏）

 note      这个插件只有 single 一种模式。HSL / Lab / HSV / LCh 都另有 multi
           模式（拆成两张或三张分量层，靠分量混合模式叠回去），HSI 做不出来：
           那四家至少有一个分量能借到现成的分量混合模式（HSV、LCh 三个都有；
           HSL 的色相 ≡ HSV 的色相；Lab 的 L* ≡ LCh 的 L*），HSI 一个都借不到：

             I = (R+G+B)/3        对上 HSV 的 V=max？不对。
             S = 1 − min/I        对上 HSL 的 S = (max−min)/(1−|2L−1|)？不对。
             H = 余弦角            对上 HSV 的参数角？最多差 1.117°。

           更麻烦的是色相：就算把色相层接到「HSV 色相」模式上，换角时它保留
           的是 HSV 的 S、V，而 HSI 的 S、I 会跟着变——实测换一条色相曲线，
           I 被带走 0.08（约 20 码）。所以色相也只能在数据图里改，三个分量
           由 lb:hsi-compose 一起重算。代价是少了一层可单独关闭的开关，换来
           的是「三个分量互相不串」——这才是这个插件想要的。

           滤镜栈（图层面板里从上往下读，执行顺序相反）：

             1 · decompose   lb:hsi-dual     原图 → (R=S, G=I, B=H/360)
             2 · S curve     gimp:curves     通道 = R（红）
             3 · I curve     gimp:curves     通道 = G（绿）
             4 · H curve     gimp:curves     通道 = B（蓝）
             5 · compose     lb:hsi-compose  (S,I,H) → 真实 HSI 色

           量程（与 lb:hsi-levels 同一份实现，见 common/color-levels.h）：
             S    1 − min/I                0…1
             I    (R+G+B)/3                0…1
             H    余弦定义 / 360           0…1

           实测（GIMP 3.2.8，见 tools/check_hsi_split.py）：
             32 位浮点图，恒等曲线往返：   最大 0.02 码
             8 位图，恒等曲线往返：        ≤ 0.5 码
             隐藏原图层后自己还原：         与可见时同值

           注意事项：
           - 三条曲线分别挂在**红 / 绿 / 蓝**通道上：S 在红、I 在绿、H 在蓝。
             在图层属性的滤镜里改曲线时记得选对通道；选「值」会把三条数据
             一起改掉。
           - 色相曲线必须是连续的（两端相等、中间不跳变）。整体旋转色相请用
             lb:hue-saturation。
           - S、I 推到极端时逆变换会出 sRGB 色域（HSI 的色域是六边形棱锥，
             不是立方体），出界部分按 0/1 裁掉——这是 HSI 本身的性质。
           - 这套精确适配依赖 lb:hsi-dual 与 lb:hsi-compose 两个算子；缺了
             它们就没有等价回退，插件会直接报错。
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


# 精确适配用的两个算子（本仓库 ops/hsi-dual、ops/hsi-compose）
DUAL_OP = "lb:hsi-dual"
COMPOSE_OP = "lb:hsi-compose"


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
    """挂一个不需要曲线的算子滤镜（lb:hsi-dual / lb:hsi-compose 这类）。"""
    filt = Gimp.DrawableFilter.new(layer, op, label)
    filt.update()
    layer.append_filter(filt)
    return filt


def _require_adapter_ops(layer):
    """确认两个适配算子可用。

    没有它们就没有等价回退：I、S 在 GIMP 的分量模式里都不存在。
    The adapter pair is mandatory; no component mode carries I."""
    missing = []
    for op in (DUAL_OP, COMPOSE_OP):
        try:
            Gimp.DrawableFilter.new(layer, op, "probe")
        except Exception:
            missing.append(op)
    if missing:
        raise RuntimeError(
            _("缺少适配算子：%s。它们是 HSI 精确适配的必需组件（I 与 S 在 GIMP "
              "的分量混合模式里都没有对应项，只能联合计算）。请先安装本仓库的 "
              "GEGL 算子的 hsi-dual / hsi-compose（./install.sh），重启 GIMP "
              "再试。") % ", ".join(missing))


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

def split_hsi(image, base, make_group=True):
    """把图层换成一张「S/I/H 三联曲线」的 HSI 层。

    返回那张层；make_group 时返回包住它的组。原图层不动，把它隐藏掉这一层
    自己就能还原。
    Replace the layer with one HSI data layer carrying three curves; it
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
            host = Gimp.GroupLayer.new(image, _("HSI split"))
            host.set_mode(Gimp.LayerMode.PASS_THROUGH)
            image.insert_layer(host, parent, position)

        layer = Gimp.Layer.new_from_drawable(base, image)
        layer.set_name(_("1 · HSI S/I/H"))
        layer.set_mode(Gimp.LayerMode.NORMAL)
        image.insert_layer(layer, host, 0)

        _simple_filter(layer, DUAL_OP, _("1 · decompose"))
        _append_curve(layer, _("2 · S curve"), _identity,
                      Gimp.HistogramChannel.RED)
        _append_curve(layer, _("3 · I curve"), _identity,
                      Gimp.HistogramChannel.GREEN)
        _append_curve(layer, _("4 · H curve"), _identity,
                      Gimp.HistogramChannel.BLUE)
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
        msg = _("HSI 层已建立：%s。S 曲线在「2 · S curve」（红通道）、"
                "I 曲线在「3 · I curve」（绿通道）、色相曲线在「4 · H curve」"
                "（蓝通道）。原图层可以隐藏，这一层自己就能还原。") \
              % (host.get_name() if host else layer.get_name())
        if auto_group:
            msg += _("\n（这张图带透明，已自动分组：透明度靠组蒙版保住。）")
        Gimp.message(msg)
    except Exception:
        pass
    return host or layer


# ---- 程序包装 / procedure wrapper ------------------------------------------

class HsiSplitPlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gimp30-python', None

    def do_query_procedures(self):
        return ['lb-plugin-hsi-split-curves']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        procedure.set_menu_label(_("HSI Split (Curves) · single"))
        procedure.add_menu_path("<Image>/Colors/SuperMrWang/Shortcut")
        procedure.add_menu_path("<Layers>/SuperMrWang/Shortcut")

        procedure.set_documentation(
            _("在 HSI 空间里调曲线：生成一张三联数据图（红通道 = 饱和度、"
              "绿通道 = 强度、蓝通道 = 色相），三条曲线各管一个分量。恒等曲线"
              "时精确还原原图，调哪条曲线就只动那个 HSI 分量。"),
            _("Curve HSI itself. One data layer (R = saturation, G = intensity, "
              "B = hue/360) with three curves; identity curves reproduce the "
              "image exactly. Needs lb:hsi-dual and lb:hsi-compose."), name)
        procedure.add_boolean_argument(
            "group", _("收进图层组"),
            _("把这一层放进一个「HSI split」穿透组里；关掉就直接叠在原图层上方"),
            True, GObject.ParamFlags.READWRITE)
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None or not drawables:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("No image or no layer selected")))
        try:
            split_hsi(image, drawables[0], config.get_property('group'))
            return procedure.new_return_values(
                Gimp.PDBStatusType.SUCCESS, GLib.Error())
        except Exception as exc:
            Gimp.message("hsi-split-curves: %s" % exc)
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(exc)))


if __name__ == '__main__':
    Gimp.main(HsiSplitPlugin.__gtype__, sys.argv)
