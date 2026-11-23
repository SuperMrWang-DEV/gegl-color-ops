#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 观察层 —— GIMP 3 Python 插件
 ---------------------------------------------------------------------------
 purpose   修图时用来「看清问题」的一次性图层：点一下菜单，上面就多一层
           已经调好的观察效果，看完隐藏或删掉即可，原图层一个像素都不动。
           六种观察层，各一个菜单项，零参数、不弹框。
           Throw-away inspection layers for retouching: one click, the effect
           is already dialled in, hide or delete it when you are done. The
           original pixels are never touched.

 menu      SuperMrWang → Observe → 黑白 / 陡峭曲线 / 波浪曲线 / 饱和度 / 阈值 / 海报化
           图层右键 → SuperMrWang → Observe → 同上

 usage     选中一个栅格图层 → 菜单项。生成的结构（自上而下）：

              观察 · 黑白              副本 + gimp:desaturate（明度）
              原图层                   不动

           六种各看什么：

             黑白      去色成灰。看明暗结构、脏点、凹凸、色块之间的明度差。
                       皮肤问题一大半在这一层就能看见。
             陡峭曲线  S 曲线把中间调斜率拉陡。细微的色斑、肤色不均被放大成
                       明显的斑，是中性灰 / 双曲线的标准搭档。
             波浪曲线  曲线做成上下摆动的波浪。连续的色阶差被反复翻折，
                       断层、色带、渐变里的台阶会露出牙齿一样的纹路。
             饱和度    饱和度 +100。看色偏、泛红、色块边界；皮肤该均匀的地方
                       一泛红就跳出来。
             阈值      压成纯黑白两色。灰尘、痘印、小污点只剩形状，最狠的一层。
             海报化    压成 4 级色阶。比阈值温和，保留一点结构，适合看
                       大面积的色块边界和过渡是否干净。

 note      为什么是「副本 + 图层滤镜」而不是「调整图层」：GIMP 3 的
           DrawableFilter 挂在副本上，参数随时能改（右键副本 → 滤镜），删掉
           图层就全没了，源图从头到尾没被写过。副本意味着大图会多占一份
           内存，但观察层本来用完就删。

           曲线用 PERCEPTUAL 通道：屏幕上看到的就是图里算的。用线性会按
           物理光强算，中间调被抬亮，判断明暗会偏。

           黑白用 LUMINANCE（递归亮度）而不是 LIGHTNESS：前者按人眼对
           R/G/B 的敏感度加权，红绿两块在 LIGHTNESS 下亮度相同、在
           LUMINANCE 下能分开——挑色斑要看的就是后者。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GLib, GObject, Gegl


# 多语言：查自己的域（gegl-color-ops），语言取自 GIMP 界面设置。
import os as _os
import sys as _sys

_here = _os.path.dirname(_os.path.abspath(__file__))
for _cand in (_os.path.join(_here, '_shared'),
              _os.path.normpath(_os.path.join(_here, '..', '_shared'))):
    if _os.path.isdir(_cand) and _cand not in _sys.path:
        _sys.path.append(_cand)
try:
    from lb_i18n import _          # noqa: F811
except Exception:                  # helper 不在：保持可用，只是不翻译
    def _(message):
        return GLib.dgettext(None, message)

import lb_dialog as _dialog


DESATURATE_OP = "gimp:desaturate"
CURVES_OP = "gimp:curves"
HS_OP = "gimp:hue-saturation"
THRESHOLD_OP = "gimp:threshold"
POSTERIZE_OP = "gimp:posterize"

# 图层名前缀走翻译：中文界面下应该是「观察 · 陡峭曲线」而不是英文混中文。
# 不在模块级调用 _()：那时候 i18n 域未必已经装好。
def observe_name(label):
    return _("Observe · %s") % label


# ---- 公共小工具 / helpers ---------------------------------------------------

def _item_position(image, item, fallback=0):
    try:
        proc = Gimp.get_pdb().lookup_procedure('gimp-image-get-item-position')
        cfg = proc.create_config()
        cfg.set_property('image', image)
        cfg.set_property('item', item)
        return proc.run(cfg).index(1)
    except Exception:
        return fallback


def _append_filter(layer, op, name):
    """新建一个图层滤镜挂上去（不碰像素）。"""
    filt = Gimp.DrawableFilter.new(layer, op, name)
    if filt is None:
        raise RuntimeError(_("This GIMP build has no \"%s\" filter.") % op)
    return filt


def _curve_filter(layer, points, name):
    """按给定控制点建一条 VALUE 通道的曲线（PERCEPTUAL）。

    点必须按 x 递增、x 不重复；0 和 1 由调用方给全（曲线两端不透传），
    否则中间调会被整体压偏。
    """
    filt = _append_filter(layer, CURVES_OP, name)
    cfg = filt.get_config()
    curve = Gimp.Curve.new()
    curve.set_curve_type(Gimp.CurveType.SMOOTH)
    for x, y in points:
        curve.add_point(float(x), float(y))
    cfg.set_property("curve", curve)
    cfg.set_property("channel", Gimp.HistogramChannel.VALUE)
    cfg.set_property("trc", Gimp.TRCType.PERCEPTUAL)
    filt.update()
    layer.append_filter(filt)
    return filt


# ---- 六种观察效果 / the six effects ----------------------------------------

def observe_grey(layer):
    """去色。LUMINANCE 而不是 LIGHTNESS（见文件头 note）。"""
    filt = _append_filter(layer, DESATURATE_OP, _("Desaturate"))
    cfg = filt.get_config()
    cfg.set_property("mode", Gimp.DesaturateMode.LUMINANCE)
    filt.update()
    layer.append_filter(filt)


# 陡峭曲线：中间调斜率抬到约 2.3 倍，两端各留一段缓冲。
# 别把陡峭度拉满：实测斜到 3 倍以上时，本身偏暗的图（夜景、深色界面截图）
# 会被压成一整块黑，观察层就白建了。2 倍出头足够把细微色斑拉成看得见的斑。
STEEP_POINTS = [(0.0, 0.0), (0.25, 0.09), (0.50, 0.50),
                (0.75, 0.91), (1.0, 1.0)]


def observe_steep(layer):
    return _curve_filter(layer, STEEP_POINTS, _("Steep curves"))


def _wave_points(waves=4, amp=0.22):
    """上下摆动的控制点：相邻点一高一低，SMOOTH 插值出来就是波浪。"""
    pts = [(0.0, 0.0), (1.0, 1.0)]
    n = waves * 2 + 1                      # 峰谷交替，两端各半个
    for i in range(1, n):
        x = i / float(n)
        pts.append((x, 0.5 + amp if i % 2 else 0.5 - amp))
    return sorted(pts)


def observe_wave(layer):
    """先去色再拉波浪。

    直接对彩色图拉波浪，等值线会带上各通道自己的色相（紫/绿/蓝环），信息量大
    但看着闹，判断「这块肤色不匀」反而更难。灰度等值线就是一张地形图，哪儿
    有坡一眼就看出来；要看色偏另点「饱和度观察层」。
    """
    observe_grey(layer)
    return _curve_filter(layer, _wave_points(), _("Wave curves"))


def observe_saturation(layer):
    """饱和度 +100（GEGL 这边是 -1…1）。"""
    filt = _append_filter(layer, HS_OP, _("Saturation +100"))
    cfg = filt.get_config()
    cfg.set_property("range", Gimp.HueRange.ALL)
    cfg.set_property("saturation", 1.0)
    filt.update()
    layer.append_filter(filt)


def _median_level(layer, fallback=0.5):
    """图层亮度的中位数（0…1），拿来做阈值。

    固定死在 0.5 是不行的：偏暗的图（夜景、深色截图、欠曝的照片）整张都在
    0.5 以下，阈值观察层会变成一块纯黑，什么都看不出来。按中位数切，黑白
    天然各占一半。
    gimp-drawable-histogram 的返回是 (status, mean, std_dev, median, …)，
    median 在 0…255 刻度上，不管图像精度是多少。
    """
    try:
        proc = Gimp.get_pdb().lookup_procedure('gimp-drawable-histogram')
        cfg = proc.create_config()
        cfg.set_property('drawable', layer)
        cfg.set_property('channel', Gimp.HistogramChannel.VALUE)
        cfg.set_property('start-range', 0.0)
        cfg.set_property('end-range', 1.0)
        median = float(proc.run(cfg).index(3))
        if median > 1.0:                 # 0…255 刻度
            median /= 255.0
        if 0.0 <= median <= 1.0:
            return median
    except Exception:
        pass
    return fallback


def observe_threshold(layer):
    """压成纯黑白：按中位数做一道硬阶梯。

    这里不用 gimp:threshold：它的 low/high 语义和界面上那两个滑块并不一致，
    实测 low == high 时（想切得干脆）整片变黑，区间收窄切点还会飘——都是
    除零和量化的坑。曲线做台阶是确定的：两个相隔一个码的点把中间调直接
    翻过去，切点就是中位数。
    """
    observe_grey(layer)                  # 先统一成灰：否则三通道各自过切点，
    m = _median_level(layer)             # 出来的二值图是彩色的
    eps = 1.0 / 255.0
    pts = [(0.0, 0.0),
           (max(0.0, m - eps), 0.0),
           (min(1.0, m + eps), 1.0),
           (1.0, 1.0)]
    out = []
    for x, y in pts:                     # 曲线要求 x 严格递增，边界处会重合
        if out and x <= out[-1][0]:
            continue
        out.append((x, y))
    if len(out) < 2:
        out = [(0.0, 0.0), (1.0, 1.0)]
    return _curve_filter(layer, out, _("Threshold"))


def observe_posterize(layer, levels=4):
    filt = _append_filter(layer, POSTERIZE_OP, _("Posterize"))
    cfg = filt.get_config()
    cfg.set_property("levels", int(levels))
    filt.update()
    layer.append_filter(filt)


# ---- 动作 / the action ------------------------------------------------------

def make_observer(image, base, build, layer_name):
    """复制 base，挂上观察滤镜，插在 base 正上方，选中它。

    build(layer) 只负责往副本上挂滤镜——副本已经和 base 同尺寸、同偏移、
    同蒙版，不需要再对齐。
    """
    if base is None:
        raise RuntimeError(_("Nothing to observe: no layer."))
    if base.is_group():
        raise RuntimeError(
            _("A layer group has no pixels of its own; pick a raster layer "
              "(right-click the group, then Merge Group)."))

    parent = base.get_parent()
    position = _item_position(image, base)

    image.undo_group_start()
    try:
        lay = base.copy()
        if lay is None:
            raise RuntimeError(_("Could not copy the layer."))
        lay.set_name(layer_name)
        image.insert_layer(lay, parent, position)
        build(lay)
        try:
            image.set_selected_layers([lay])
        except Exception:
            pass
    finally:
        image.undo_group_end()

    Gimp.displays_flush()
    return lay


# ---- 菜单表 / the menu table ------------------------------------------------
# (procedure 尾名, 菜单标签, 图层名前缀, 动作, 英文说明, 中文说明)
#
# 说明写成 msgid 英文、中文进 po，和其他插件一个口径。

OBSERVERS = [
    ("grey", "Black & White", "Black & White", observe_grey,
     "Black & White: a desaturated copy on top (Luminance). Structure, "
     "blemishes and uneven tone show up as pure brightness differences.",
     "黑白观察层：顶部加一份去色副本（明度加权）。结构、脏点、肤色不匀在"
     "纯明暗下最清楚。"),
    ("steep", "Steep Curves", "Steep curves", observe_steep,
     "Steep Curves: an S-curve copy on top. Doubles the midtone slope so "
     "faint blotches and uneven skin turn into obvious patches.",
     "陡峭曲线观察层：顶部加一份 S 曲线副本。中间调斜率加倍，细微色斑、"
     "肤色不匀被放大成明显的斑。"),
    ("wave", "Wave Curves", "Wave curves", observe_wave,
     "Wave Curves: a zigzag curve copy on top. Gradual gradients fold back "
     "and forth, so banding and broken tone steps show as a sawtooth.",
     "波浪曲线观察层：顶部加一份锯齿曲线副本。渐变的连续色阶被反复翻折，"
     "色带、断层会露出锯齿状纹路。"),
    ("saturation", "Saturation +100", "Saturation +100", observe_saturation,
     "Saturation +100: a fully saturated copy on top. Redness, colour casts "
     "and the edges of colour patches jump out.",
     "饱和度观察层：顶部加一份饱和度 +100 的副本。泛红、色偏、色块边界"
     "一眼就跳出来。"),
    ("threshold", "Threshold", "Threshold", observe_threshold,
     "Threshold: a pure black-and-white copy on top. Dust, acne and small "
     "specks keep only their shape — the harshest of the six.",
     "阈值观察层：顶部加一份纯黑白副本。灰尘、痘印、小污点只剩形状，"
     "六种里最狠的一层。"),
    ("posterize", "Posterize (4 levels)", "Posterize", observe_posterize,
     "Posterize: a copy quantised to 4 levels on top. Gentler than Threshold; "
     "good for checking patch boundaries and whether a gradient is clean.",
     "海报化观察层：顶部加一份压到 4 级色阶的副本。比阈值温和，保留一点"
     "结构，适合看色块边界和渐变是否干净。"),
]

BY_KEY = dict((o[0], o) for o in OBSERVERS)
PROC_PREFIX = 'lb-plugin-observe-'


class ObservePlugin(Gimp.PlugIn):

    def do_set_i18n(self, procname):
        return True, 'gegl-color-ops', None

    def do_query_procedures(self):
        return [PROC_PREFIX + o[0] for o in OBSERVERS]

    def do_create_procedure(self, name):
        key = name[len(PROC_PREFIX):]
        _key, label, _lname, _build, doc_en, doc_zh = BY_KEY[key]

        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("RGB*, GRAY*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES)
        procedure.set_attribution("SuperMrWang", "SuperMrWang", "2026")

        # 零参数：点了就建，不弹对话框（观察层要的是一秒钟看到结果）。
        # No arguments: the menu item runs straight away.
        procedure.set_documentation(doc_en, doc_zh, name)
        procedure.set_menu_label(_(label))
        procedure.add_menu_path("<Image>/SuperMrWang/Observe")
        procedure.add_menu_path("<Layers>/SuperMrWang/Observe")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, data):
        if image is None:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(_("No image")))
        if len(drawables) != 1:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(_("Select exactly one layer.")))
        if not _dialog.run_dialog(procedure, run_mode, config):
            return procedure.new_return_values(
                Gimp.PDBStatusType.CANCEL, None)

        key = procedure.get_name()[len(PROC_PREFIX):]
        _key, _label, lname, build, _en, _zh = BY_KEY[key]
        try:
            lay = make_observer(image, drawables[0], build, observe_name(_(lname)))
        except RuntimeError as exc:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(str(exc)))
        Gimp.message(_("Added \"%s\": hide or delete it when you are done — "
                       "the layer underneath was not touched.") % lay.get_name())
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


if __name__ == '__main__':
    Gimp.main(ObservePlugin.__gtype__, sys.argv)
