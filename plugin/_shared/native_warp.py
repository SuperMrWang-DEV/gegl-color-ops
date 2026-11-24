#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctypes 直调 GEGL 算子的「预览渲染」入口。

为什么要这一层：交互时每拖一下都要出一帧预览。走原来的路——GEGL 建 buffer、
babl 转格式、整块取回，再在 Python/numpy 里重采样——480×360 实测 84～97 ms
（解场 47 + 重采样 37），拖动明显掉帧。

GEGL 算子的 .dll 里已经有一整套数学，这里让算子额外导出一个纯 C 函数
（`mw_render_rgba_u8` / `pw_render_rgba_u8`），Python 用 ctypes 把像素指针传进去，
结果写回一块 bytearray。实测 **9 ms**，快 9～10 倍，而且和最终烘焙走的是
同一份 mw_field_for / mw_sample —— 预览和结果不会不一致。

加载失败（别的机器没有 .dll、依赖解析不到）时 render() 返回 None，调用方
回退到原来的 numpy 路径，不会崩。
"""

import ctypes
import os
import time

_CACHE = {}


def _dll_dirs():
    """GIMP 的 dll 都在 bin/lib；Python 3.8+ 在 Windows 上不再从 PATH 解析依赖。"""
    dirs = []
    for base in (os.environ.get("GIMP_DIR"), r"D:\fastsoftware\GIMP 3"):
        if not base:
            continue
        for sub in ("bin", "lib"):
            d = os.path.join(base, sub)
            if os.path.isdir(d) and d not in dirs:
                dirs.append(d)
    return dirs


def _candidates(name):
    """去哪找算子 .dll。**已安装的那份优先**——GIMP 烘焙用的就是它，
    预览必须和烘焙同一份代码，否则「预览等于结果」这句承诺就废了。
    仓库 build/ 只作开发时的兜底。"""
    out = []
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    out.append(os.path.join(local, "gegl-0.4", "plug-ins", name + ".dll"))
    for d in _dll_dirs():
        out.append(os.path.join(d, "gegl-0.4", name + ".dll"))
    here = os.path.dirname(os.path.abspath(__file__))
    out.append(os.path.join(os.path.dirname(os.path.dirname(here)), "build",
                            name + ".dll"))
    return out


class NativePreview(object):
    """一个算子的预览入口。第一次用时才加载 .dll。"""

    def __init__(self, name):
        self.name = name
        self.entry = name.replace("-warp", "") + "_render_rgba_u8"
        # 名字对不上就用拼接结果；mesh-warp → mw_render_rgba_u8
        self.entry = {"mesh-warp": "mw_render_rgba_u8",
                      "puppet-warp": "pw_render_rgba_u8"}.get(
                          name, self.entry)
        self.lib = None
        self.path = ""
        self.error = ""
        self.seconds = 0.0
        self.calls = 0

    # -- 加载 ---------------------------------------------------------------
    def load(self):
        if self.lib is not None or self.error:
            return self.lib
        for d in _dll_dirs():
            try:
                os.add_dll_directory(d)
            except Exception:
                pass
        for path in _candidates(self.name):
            if not os.path.exists(path):
                continue
            lib = None
            try:
                lib = ctypes.CDLL(path)
            except OSError:
                try:
                    # 退路：老式搜索路径（依赖在 PATH 里时可用）
                    lib = ctypes.CDLL(path, winmode=0)
                except OSError as exc:
                    self.error = "%s: %s" % (path, exc)
                    continue
            try:
                fn = getattr(lib, self.entry)
            except AttributeError:
                self.error = "%s 里没有 %s（算子版本太旧？）" % (path, self.entry)
                continue
            # 两个算子的签名不一样：puppet 还要 mode 和 radius
            if self.name == "puppet-warp":
                fn.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_char_p, ctypes.c_char_p,
                               ctypes.c_double, ctypes.c_char_p]
            else:
                fn.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_char_p, ctypes.c_char_p]
            fn.restype = ctypes.c_int
            self.lib = lib
            self.fn = fn
            self.path = path
            self.error = ""
            return lib
        if not self.error:
            self.error = "没找到 %s.dll" % self.name
        return None

    @property
    def available(self):
        return self.load() is not None

    # -- 用 -----------------------------------------------------------------
    def render(self, key, rgba, w, h, mode="similarity", radius=30.0):
        """返回变形后的 u8 RGBA bytes；不可用或失败时返回 None。

        key 是 mesh 串（mesh-warp）或 pins 串（puppet-warp）。
        """
        if not self.load():
            return None
        if not rgba or len(rgba) != w * h * 4:
            return None
        src = rgba if isinstance(rgba, bytes) else bytes(rgba)
        dst = ctypes.create_string_buffer(w * h * 4)
        kb = (key or "").encode("utf-8")
        t0 = time.time()
        if self.name == "puppet-warp":
            ok = self.fn(src, w, h, kb, mode.encode("utf-8"), float(radius),
                         ctypes.cast(dst, ctypes.c_char_p))
        else:
            ok = self.fn(src, w, h, kb, ctypes.cast(dst, ctypes.c_char_p))
        self.seconds = time.time() - t0
        self.calls += 1
        if not ok:
            return None
        return dst.raw

    def identity(self, mesh_text, w, h):
        """场是不是恒等（全 0）。None = 判断不了。"""
        if not self.load():
            return None
        fn = getattr(self.lib, self.entry.replace("_render_rgba_u8",
                                                  "_field_is_identity"),
                     None)
        if fn is None:
            return None
        fn.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        fn.restype = ctypes.c_int
        r = fn((mesh_text or "").encode("utf-8"), w, h)
        return None if r < 0 else bool(r)


_MESH = NativePreview("mesh-warp")
_PUPPET = NativePreview("puppet-warp")


def mesh_preview():
    return _MESH


def puppet_preview():
    return _PUPPET
