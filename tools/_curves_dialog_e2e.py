# -*- coding: utf-8 -*-
"""端到端验：走插件真实的 `show_dialog()` 路径，看正文到底显示出来了没有。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/_curves_dialog_e2e.py').read())" --quit

和 `_curves_dlg_probe.py` 的区别：那个只看 build_dialog 之后手动 show_all 的效果，
这个把 build_dialog 换成捕获壳，然后**真的调 show_dialog**——内部 `dlg.run()`
会开嵌套主循环，超时回调正好落在里面，量到的就是用户点菜单那一刻的窗口状态。
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

OUT = os.path.join(ROOT, "outputs")
CAP = {}
RESULT = {"ok": False, "why": "超时回调没跑"}


def load_mod():
    import importlib.util
    p = os.path.join(ROOT, "plugin", "curves", "curves.py")
    spec = importlib.util.spec_from_file_location("lb_curves_e2e", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Cfg(object):
    def get_property(self, _n):
        return None

    def set_property(self, _n, _v):
        pass


def main():
    mod = load_mod()
    orig = mod.build_dialog

    def wrap(*a, **k):
        dlg, ctx = orig(*a, **k)
        CAP["dlg"], CAP["ctx"] = dlg, ctx
        return dlg, ctx

    mod.build_dialog = wrap

    def inspect():
        dlg, ctx = CAP["dlg"], CAP["ctx"]
        body = dlg.get_content_area().get_children()[0]
        garea = ctx["garea"]
        win = dlg.get_window()
        state = {
            "body_visible": body.get_visible(),
            "garea_visible": garea.get_visible(),
            "garea_alloc": (garea.get_allocated_width(),
                            garea.get_allocated_height()),
            "win": (win.get_width(), win.get_height()) if win else None,
            "pixbuf": ctx["pixbuf"] is not None,
        }
        print("窗口状态", state)
        RESULT["ok"] = (state["body_visible"] and state["garea_visible"]
                        and state["garea_alloc"][0] > 100
                        and state["win"] and state["win"][1] > 200)
        RESULT["why"] = "" if RESULT["ok"] else "正文没铺开"
        # 顺手存一张真正的窗口截图，肉眼再确认一次
        if win and state["win"][0] > 1:
            try:
                w, h = state["win"]
                pb = Gdk_pixbuf(win, w, h)
                os.makedirs(OUT, exist_ok=True)
                pb.savev(os.path.join(OUT, "curves-dialog-e2e.png"),
                         "png", [], [])
                print("saved", os.path.join(OUT, "curves-dialog-e2e.png"))
            except Exception as exc:
                print("截图失败（不影响判定）:", exc)
        dlg.response(Gtk.ResponseType.CANCEL)
        return False

    GLib.timeout_add(1200, inspect)

    card = os.path.join(ROOT, "tools", "_testcard.png")
    img = Gimp.Image.new(960, 640, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(card))
    img.insert_layer(layer, None, 0)
    called = mod.show_dialog(None, Cfg(), img, layer, "lab")
    img.delete()
    print("show_dialog 返回", called)
    print("RESULT", "PASS" if RESULT["ok"] else "FAIL", RESULT["why"])
    if not RESULT["ok"]:
        raise SystemExit(1)


def Gdk_pixbuf(win, w, h):
    from gi.repository import Gdk
    return Gdk.pixbuf_get_from_window(win, 0, 0, w, h)


main()
