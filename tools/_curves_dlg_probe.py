# -*- coding: utf-8 -*-
"""复现「曲线对话框只有一个空壳」：量一下正文在 show_all 前后的可见状态。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/_curves_dlg_probe.py').read())" --quit

结论（2026-11-24）：GTK3 控件默认不可见，`dlg.run()` 只 show 对话框自身。
build 完不 show_all，正文 outer/左边的预览/右边的曲线画布 get_visible() 全是
False，窗口缩到只剩按钮条 —— 用户看到的就是「一个小对话框」。
"""
import os
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, Gio, Gtk, GLib

ROOT = os.environ.get("LB_REPO") or \
    r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))
sys.path.insert(0, os.path.join(ROOT, "plugin", "curves"))


def pump(n=6):
    ctx = GLib.MainContext.default()
    for _ in range(n):
        while ctx.pending():
            ctx.iteration(False)


def load_mod():
    import importlib.util
    p = os.path.join(ROOT, "plugin", "curves", "curves.py")
    spec = importlib.util.spec_from_file_location("lb_curves_probe", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    mod = load_mod()
    card = os.path.join(ROOT, "tools", "_testcard.png")
    img = Gimp.Image.new(960, 640, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(card))
    img.insert_layer(layer, None, 0)

    class Cfg(object):
        def get_property(self, _n):
            return None

    dlg, ctx = mod.build_dialog(None, Cfg(), img, layer, "lab")
    body = dlg.get_content_area().get_children()[0]
    print("build 之后   body.get_visible() =", body.get_visible())
    print("             garea.get_visible() =", ctx["garea"].get_visible())
    print("             对话框 preferred =", dlg.get_preferred_width(),
          dlg.get_preferred_height())

    dlg.show_all()
    pump()
    print("show_all 之后 body.get_visible() =", body.get_visible())
    print("             garea.get_visible() =", ctx["garea"].get_visible(),
          " realized =", ctx["garea"].get_realized(),
          " 分配 =", ctx["garea"].get_allocated_width(),
          "x", ctx["garea"].get_allocated_height())
    ok = (body.get_visible() and ctx["garea"].get_visible()
          and ctx["garea"].get_allocated_width() > 0)
    dlg.destroy()
    img.delete()
    print("RESULT", "PASS" if ok else "FAIL")
    if not ok:
        raise SystemExit(1)


main()
