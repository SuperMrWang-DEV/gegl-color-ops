# -*- coding: utf-8 -*-
"""自绘对话框那几支的截图（参数框不是 GimpUi 自动生成的）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/make_plugin_shots_custom.py').read())" --quit

这些插件的 `build_dialog()` 各自签名不同，只能逐个适配。做法都一样：
拿测试卡建 image + layer，调 build_dialog 拿到 (dlg, ctx)，show_all 之后
用 cairo 把整棵控件树 draw 进 ImageSurface（toplevel 塞不进 OffscreenWindow）。

输出 docs/assets/plugins/<slug>/dialog.png，并合并进 site/plugin_shots.json。
"""
import importlib.util
import json
import locale
import os
import sys
import time

for _loc in ("Chinese_China.936", "zh_CN.UTF-8", "zh_CN"):
    try:
        locale.setlocale(locale.LC_ALL, _loc)
        break
    except locale.Error:
        continue

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, Gio, Gtk

ROOT = os.environ.get("LB_REPO") or \
    r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
# 图源放 tools/site 下：docs/ 每次构建都会被整体清空重写，
# 直接写进 docs/assets/plugins 会被下一次 site_build 删掉。
OUTDIR = os.path.join(ROOT, "tools", "site", "plugin-shots")
JSDIR = os.path.join(ROOT, "tools", "site")
TITLE_H = 34
CARD = os.path.join(ROOT, "tools", "_testcard.png")

sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))
for _d in ("layer-style", "puppet-warp", "mesh-warp", "vanishing-point",
           "refine-mask", "curves", "color-range"):
    sys.path.insert(0, os.path.join(ROOT, "plugin", _d))


class Cfg(object):
    """只提供 get_property：自绘对话框建 UI 时读的默认值全是 None/空。"""

    def __init__(self, **kw):
        self.kw = kw

    def get_property(self, name):
        return self.kw.get(name)

    def set_property(self, name, value):
        self.kw[name] = value


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pump(rounds=30, delay=0.02):
    for _ in range(rounds):
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(delay)


def draw_title(cr, text, w, sub=""):
    cr.select_font_face("Microsoft YaHei", 0, 1)
    cr.set_font_size(14)
    cr.set_source_rgb(0.09, 0.09, 0.11)
    cr.move_to(14, 22)
    cr.show_text(text)
    if sub:
        cr.select_font_face("Microsoft YaHei", 0, 0)
        cr.set_font_size(11)
        cr.set_source_rgb(0.55, 0.55, 0.58)
        ext = cr.text_extents(text)
        cr.move_to(14 + ext.width + 12, 22)
        cr.show_text(sub)
    cr.set_source_rgb(0.85, 0.85, 0.87)
    cr.set_line_width(1)
    cr.move_to(0, TITLE_H - 0.5)
    cr.line_to(w, TITLE_H - 0.5)
    cr.stroke()


def save_dialog(dlg, slug, tzh, ten, extra_pump=20):
    import cairo
    dlg.show_all()
    pump(extra_pump)
    w = dlg.get_allocated_width()
    h = dlg.get_allocated_height()
    if w < 200 or h < 100:
        nw = max(dlg.get_preferred_width())
        nh = max(dlg.get_preferred_height())
        dlg.resize(nw, nh)
        pump(12)
        w = max(w, dlg.get_allocated_width(), nw)
        h = max(h, dlg.get_allocated_height(), nh)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h + TITLE_H)
    cr = cairo.Context(surface)
    cr.set_source_rgb(0.965, 0.965, 0.973)
    cr.paint()
    draw_title(cr, tzh, w, ten)
    cr.translate(0, TITLE_H)
    dlg.draw(cr)
    cr.identity_matrix()
    d = os.path.join(OUTDIR, slug)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "dialog.png")
    surface.write_to_png(path)
    dlg.destroy()
    pump(3)
    return path, w, h + TITLE_H


def make_image():
    img = Gimp.Image.new(960, 640, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(CARD))
    img.insert_layer(layer, None, 0)
    return img, layer


def main():
    Gtk.init([])
    img, layer = make_image()
    meta = {}

    def run(slug, tzh, ten, fn):
        try:
            dlg = fn()
            path, w, h = save_dialog(dlg, slug, tzh, ten)
            print("OK   %-22s %4dx%-4d" % (slug, w, h))
            return {"w": w, "h": h, "title": tzh}
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print("FAIL %-22s %s: %s" % (slug, type(exc).__name__, exc))
            return None

    def ls():
        m = load("lb_ls_shot", os.path.join(ROOT, "plugin", "layer-style",
                                            "layer-style.py"))
        return m.build_dialog(Cfg(), img, layer, 520, 347)[0]

    def warp():
        m = load("lb_warp_shot", os.path.join(ROOT, "plugin", "puppet-warp",
                                              "puppet-warp.py"))
        return m.build_dialog(Cfg(), img, layer, 560, 373)[0]

    def mesh():
        m = load("lb_mesh_shot", os.path.join(ROOT, "plugin", "mesh-warp",
                                              "mesh-warp.py"))
        return m.build_dialog(Cfg(), img, layer, 560, 373)[0]

    def vp():
        m = load("lb_vp_shot", os.path.join(ROOT, "plugin", "vanishing-point",
                                            "vanishing-point.py"))
        return m.build_dialog(Cfg(), img, layer, 560, 373)[0]

    def cr():
        m = load("lb_cr_shot", os.path.join(ROOT, "plugin", "color-range",
                                            "color-range.py"))
        filt = Gimp.DrawableFilter.new(layer, m.OP, "Color Range")
        return m.ColorRangeDialog(img, layer, filt)

    def refine():
        import mask_io as MI
        m = load("lb_refine_shot", os.path.join(ROOT, "plugin", "refine-mask",
                                                "refine-mask.py"))
        # 精修的对象是「选区/蒙版」，先圈一块再取蒙版
        img.select_ellipse(Gimp.ChannelOps.REPLACE, 370, 120, 320, 380)
        w, h, mask, _src = MI.current_mask(img, 0)
        cfg = Cfg(radius=2.0, smart=False, smooth=1.0, feather=1.5,
                  contrast=20.0, shift=-3.0, decontaminate=30.0,
                  output="mask", **{"work-size": 0})
        return m.build_dialog(cfg, img, layer, w, h, mask)[0]

    CASES = [
        ("layer-style", "图层样式", "Layer Style", ls,
         "左侧效果列表、右侧参数，实时预览", "effect list, parameters, live preview"),
        ("refine", "选择并遮住", "Select and Mask", refine,
         "左侧预览、右侧半径/平滑/羽化/去色边，边缘实时重算",
         "preview on the left; radius, smooth, feather and decontaminate on the right"),
        ("warp", "木偶变形", "Puppet Warp", warp,
         "钉住关节再拖动，右侧是吸附半径与网格密度",
         "pin the joints, drag to bend; snapping radius and mesh density"),
        ("mesh-warp", "自由变形", "Free Transform", mesh,
         "拖节点或它的把手，按 Bezier 面片弯曲",
         "drag a node or its handles to bend along Bezier patches"),
        ("vanishing-point", "消失点", "Vanishing Point", vp,
         "在画面上标一个透视平面，再贴图或拉正",
         "mark one perspective plane, then paste or rectify onto it"),
        ("color-range", "色彩范围", "Color Range", cr,
         "按颜色取样建选区，带红色叠加预览",
         "sample colours to build a selection, with a red overlay preview"),
    ]
    for slug, tzh, ten, fn, zh, en in CASES:
        m = run(slug, tzh, ten, fn)
        if m:
            m.update({"zh": zh, "en": en})
            meta[slug] = m

    jp = os.path.join(JSDIR, "plugin_shots.json")
    old = {}
    if os.path.exists(jp):
        try:
            old = json.load(open(jp, encoding="utf-8"))
        except Exception:
            old = {}
    old.update(meta)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=1, sort_keys=True)
    img.delete()
    print("\n自绘 %d 张" % len(meta))


main()
