#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 参数对话框 / parameter dialogs
 ---------------------------------------------------------------------------
 purpose   给插件在 run() 里弹一个「参数框」。
           GIMP 3 **不会**自动为插件生成参数对话框——哪怕所有参数都注册好了、
           过程也挂在菜单上。插件的 run() 里必须自己
           `GimpUi.ProcedureDialog.new(procedure, config, 标题)` 再 `run()`。
           不写这几行，点菜单就是「用默认值直接跑」，参数框永远不出现；
           用户会以为插件根本没有可调参数（更糟：像 ai-inpaint 这种默认值
           不可用的，直接报错「提示词是空的」）。
 usage     from lb_dialog import run_dialog
           if not run_dialog(procedure, run_mode, config):
               return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

from gi.repository import Gimp

_ui_ready = False


def _ui_init(name):
    """GimpUi 只需要初始化一次；重复调用是幂等的。"""
    global _ui_ready
    if _ui_ready:
        return
    import gi
    gi.require_version('GimpUi', '3.0')
    from gi.repository import GimpUi
    GimpUi.init(name)
    _ui_ready = True


def has_arguments(config):
    """有没有值得问用户的参数。没有就别弹一个空框。"""
    try:
        return bool(list(config.list_properties()))
    except Exception:
        return True


def run_dialog(procedure, run_mode, config, title=None):
    """交互模式弹出参数框。

    返回 True  = 用户点了确定（或本来就该静默跑），继续执行；
    返回 False = 用户取消，调用方应返回 Gimp.PDBStatusType.CANCEL。

    三种模式的分工：
      INTERACTIVE     弹框；
      WITH_LAST_VALS  用上次的参数静默跑（「重复上次」就是这个模式），
                      再弹一次框是骚扰；
      NONINTERACTIVE  批处理，绝不能弹框。

    弹不出来时**不要**让插件失败——退回默认值继续跑，并打一条消息说明。
    宁可少一个框，也不能让插件整个不可用。
    """
    if run_mode != Gimp.RunMode.INTERACTIVE:
        return True
    if not has_arguments(config):
        return True

    try:
        import gi
        gi.require_version('GimpUi', '3.0')
        gi.require_version('Gtk', '3.0')
        from gi.repository import GimpUi

        _ui_init(procedure.get_name())
        if title is None:
            title = procedure.get_menu_label() or procedure.get_name()
            title = title.rstrip('…').rstrip('.').strip()
        # 标题是按 Pango 标记解析的：菜单名里带 & 时（"双曲线磨皮 (Dodge & Burn)"）
        # 不转义就会解析失败，标题退化成空或半截
        from gi.repository import GLib as _GLib
        title = _GLib.markup_escape_text(title)

        dialog = GimpUi.ProcedureDialog.new(procedure, config, title)
        try:
            # 让对话框贴着 GIMP 主窗口居中，别跑到屏幕角落去
            GimpUi.window_set_transient(dialog)
        except Exception:
            pass
        dialog.fill()
        accepted = bool(dialog.run())
        dialog.destroy()
        return accepted
    except Exception as exc:                          # 弹框失败不该毁掉插件
        Gimp.message("lb_dialog: %s" % exc)
        return True
