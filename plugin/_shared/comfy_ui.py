# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · ComfyUI 的界面侧胶水（事件泵 + 按需拉起）
 ---------------------------------------------------------------------------
 purpose   「要跑 AI 了」这件事每个插件都要先做一遍：确认服务在、不在就按配置
           的目录拉起来、拉不起来就用人话告诉用户去哪修。这套逻辑原来只写在
           ai-inpaint 里，扩图和超分是第二、第三个用它的人，所以搬到这里。

 why       拉服务要几十秒，期间必须让 GIMP 重画界面，否则用户看到的是「点一下
           就卡死」。pump_events() 就是那几十秒里的呼吸。

 note      回归脚本都塞 mock client，所以**只有不传 client** 的正常路径才会走到
           这里——测试永远不会在本机偷偷起一个 ComfyUI。
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import os
import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib

try:
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
except Exception:                      # 不带 Gtk 的构建：事件泵退化成功空操作
    Gtk = None

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.append(_here)

try:
    import ai_client
except Exception:                      # 裸装：由调用方报错
    ai_client = None

try:
    import comfy_launcher
except Exception:
    comfy_launcher = None


def _N_(message):
    return message


try:
    from lb_i18n import _          # noqa: F811
except Exception:
    def _(message):
        return GLib.dgettext(None, message)


def pump_events():
    """启动 ComfyUI 那几十秒里让界面还能重画——不然用户看到的就是「卡死」。"""
    if Gtk is None:
        return
    try:
        while Gtk.events_pending():
            Gtk.main_iteration()
    except Exception:
        pass


def ensure_running(server=""):
    """不在跑就按配置的目录拉起来；拉不起来抛 RuntimeError（带日志尾巴）。

    返回 comfy_launcher 的结果字典，或 None（没有 launcher 可用）。
    """
    if comfy_launcher is None:
        return None

    def tick(_msg):
        try:
            Gimp.progress_pulse()
        except Exception:
            pass
        pump_events()

    res = comfy_launcher.ensure_running(server, on_progress=tick)
    if not res.get("ok"):
        lines = [_("ComfyUI is not running and could not be started: %s")
                 % (res.get("error") or "?")]
        log = (res.get("log") or "").strip()
        if log:
            lines.append(_("Last lines of the log:"))
            lines += ["    " + r for r in log.splitlines()[-12:]]
        lines.append(_("Fix it from SuperMrWang → AI → AI Environment… "
                       "(pick the ComfyUI folder, or start it there)."))
        raise RuntimeError("\n".join(lines))
    return res


def make_client(server="", timeout=60.0):
    """拉一次服务 + 造一个客户端。调用方只在**没传 client** 时用它。"""
    if ai_client is None:
        raise RuntimeError(_("plugin/_shared/ai_client.py is missing: install "
                             "the _shared folder next to the plug-in"))
    ensure_running(server)
    return ai_client.ComfyClient(server, timeout=min(float(timeout), 60.0))
