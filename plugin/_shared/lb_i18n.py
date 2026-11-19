#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · Python 插件侧的多语言
 ---------------------------------------------------------------------------
 GIMP 3 的 Python 插件是独立进程，翻译不能用 C 侧那个 bindtextdomain 构造函数，
 而且 ``GLib.dgettext(None, ...)`` 查的是「进程默认域」—— 落到 gimp30-python
 自己的语言包里，会出现中文界面蹦出德文单词这种串味。

 这里改成用标准库 gettext 查我们自己的域（gegl-color-ops），目录按下面的顺序
 找，第一个命中的生效：

   1. $LB_LOCALEDIR                       开发 / 调试用的显式覆盖
   2. <本文件所在目录>/../locale          plugin/_shared/ 与 locale/ 并排（仓库布局）
   3. <本文件所在目录>/locale             安装后 locale 被复制进插件目录
   4. <GIMP 前缀>/share/locale            装到系统前缀时的常规布局

 取语言必须用 GLib.get_language_names()：Windows 上 locale 模块读的是系统区域
 设置，而 GIMP 界面语言是可以单独选的，两者经常不一致。

 找不到 .mo 不是错误：fallback 到恒等函数，_() 原样返回英文 msgid。
 ============================================================================"""

import os

try:
    import gettext as _gettext
except ImportError:                     # 极简构建里可能没有
    _gettext = None

DOMAIN = 'gegl-color-ops'
_HERE = os.path.dirname(os.path.abspath(__file__))


def _candidates():
    forced = os.environ.get('LB_LOCALEDIR')
    if forced and os.path.isdir(forced):
        return [forced]
    dirs = [
        os.path.normpath(os.path.join(_HERE, '..', 'locale')),
        os.path.join(_HERE, 'locale'),
        os.path.normpath(os.path.join(_HERE, '..', 'share', 'locale')),
    ]
    return [d for d in dirs if os.path.isdir(d)]


def _languages():
    try:
        import gi
        gi.require_version('GIMP', '3.0')
        from gi.repository import GLib
        names = GLib.get_language_names()
        if names:
            return list(names)
    except Exception:
        pass
    return None


def translator():
    """返回一个 msgid -> str 的函数。"""
    if _gettext is None:
        return lambda message: message
    langs = _languages()
    for localedir in _candidates():
        try:
            trans = _gettext.translation(DOMAIN, localedir,
                                         languages=langs, fallback=False)
            return trans.gettext
        except (OSError, FileNotFoundError):
            continue
    return lambda message: message


_ = translator()
_N_ = lambda message: message        # 只做标记，留给提取脚本
