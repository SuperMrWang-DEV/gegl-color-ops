#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：ctypes 直调 mesh-warp.dll 的预览接口，和 numpy 路径比速度/一致性。

用户问「那三个仓库效率更高一筹，可以模仿吗」。她们的做法是把预览渲染放进
C（mesh_preview_render / pw_render_preview），Python 只用 ctypes 传指针。
这里验证我们能不能照着做：同一个 mw_render_rgba 和 GEGL 滤镜共用 field。
"""

import ctypes
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import mesh_warp as MWM
import warp_math as WM

GIMP = r"D:\fastsoftware\GIMP 3"
for d in (os.path.join(GIMP, "bin"), os.path.join(GIMP, "lib")):
    if os.path.isdir(d):
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

W, H = 480, 360


def load():
    for cand in (os.path.join(ROOT, "build", "mesh-warp.dll"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""),
                              "gegl-0.4", "plug-ins", "mesh-warp.dll")):
        if os.path.exists(cand):
            try:
                lib = ctypes.CDLL(cand)
            except OSError:
                # Python 3.8+ 默认不从 PATH 解析依赖；GIMP 的 dll 都在 bin/lib
                lib = ctypes.CDLL(cand, winmode=0)
            fp = ctypes.POINTER(ctypes.c_float)
            lib.mw_render_rgba.argtypes = [fp, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_char_p, fp]
            lib.mw_render_rgba.restype = ctypes.c_int
            lib.mw_field_is_identity.argtypes = [ctypes.c_char_p,
                                                 ctypes.c_int, ctypes.c_int]
            lib.mw_field_is_identity.restype = ctypes.c_int
            return lib, cand
    return None, None


def main():
    lib, path = load()
    if lib is None:
        print("找不到 mesh-warp.dll")
        return 1
    print("加载：", path)

    # 平滑渐变（随机噪声对「采样位置差 0.5 px」过敏，比不出真实一致性）
    u8 = bytes(
        int(255 * (0.5 + 0.4 * ((x * 3 + y * 5) % 256) / 255.0))
        for y in range(H) for x in range(W) for _ in range(4))
    # C 侧吃 RGBA float 0..1（与 GEGL 的 R'G'B'A float 一致）
    src = (ctypes.c_float * (W * H * 4))(*[v / 255.0 for v in u8])
    dst = (ctypes.c_float * (W * H * 4))()

    m = MWM.Mesh.identity(W, H, 4, 4)
    n = m.node(2, 2)
    n["x"] += 45.0
    n["y"] -= 35.0
    m.auto_refresh()
    mesh = MWM.format_mesh_string(m).encode()

    # ---- C ----
    t = time.time()
    ok = lib.mw_render_rgba(src, W, H, mesh, dst)
    tc = (time.time() - t) * 1000.0
    print("C   ：ok=%d  %.1f ms" % (ok, tc))

    # 再来一次（field 缓存命中？网格串没变，应该命中）
    t = time.time()
    lib.mw_render_rgba(src, W, H, mesh, dst)
    tc2 = (time.time() - t) * 1000.0
    print("C 二次：%.1f ms" % tc2)

    iso = lib.mw_field_is_identity(mesh, W, H)
    ident_mesh = MWM.format_mesh_string(MWM.Mesh.identity(W, H, 4, 4)).encode()
    print("is_identity(变形) =", iso, "/ is_identity(恒等) =",
          lib.mw_field_is_identity(ident_mesh, W, H))

    # ---- numpy（现役预览路径，吃 u8 RGBA） ----
    t = time.time()
    field = MWM.build_field(m, W, H)
    out = WM.warp_rgba(u8, W, H, field)
    tn = (time.time() - t) * 1000.0
    print("numpy：%.1f ms" % tn)

    # ---- 一致性：C 的 float 结果换算回 u8 比 ----
    diffs = []
    worst_at = 0
    for i in range(len(u8)):
        cv = int(round(dst[i] * 255.0))
        d = abs(cv - out[i])
        diffs.append(d)
        if d > diffs[worst_at]:
            worst_at = i
    diffs.sort()
    n = len(diffs)
    print("像素差 u8：中位 %d / p99 %d / 最大 %d（最大处 idx=%d px=%d,%d ch=%d）"
          % (diffs[n // 2], diffs[int(n * 0.99)], diffs[-1],
             worst_at, (worst_at // 4) % W, (worst_at // 4) // W, worst_at % 4))
    big = sum(1 for d in diffs if d > 8)
    print("差 >8 的通道数：%d / %d（%.2f%%）" % (big, n, 100.0 * big / n))
    print("加速：%.1f×" % (tn / tc if tc > 0 else 0))
    return 0


def gegl_pair():
    """C 预览 vs GEGL 烘焙（gegl CLI 跑同一个算子）—— 预览等于结果的唯一证明。"""
    import subprocess
    import ai_client as AC
    import _mesh_handle_probe as P

    m = MWM.Mesh.identity(P.W, P.H, 3, 3)
    n = m.node(1, 1)
    n["x"] += 40.0
    n["y"] -= 25.0
    m.auto_refresh()
    dst = P.run("nativecmp", m)
    if dst is None:
        print("gegl 没跑成")
        return

    lib, _p = None, None
    lib, path = load()
    u8 = open(os.path.join(P.OUT, "_mh_src.png"), "rb").read()
    w, h, ch, px = AC.decode_png(u8)
    print("源图 %dx%d ch=%d" % (w, h, ch))

    out = None
    buf = ctypes.create_string_buffer(w * h * 4)
    fn = getattr(lib, "mw_render_rgba_u8")
    fn.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                   ctypes.c_char_p, ctypes.c_char_p]
    fn.restype = ctypes.c_int
    ok = fn(bytes(px), w, h, MWM.format_mesh_string(m).encode(),
            ctypes.cast(buf, ctypes.c_char_p))
    print("ctypes ok=", ok)

    w2, h2, _c2, px2 = AC.decode_png(open(dst, "rb").read())
    diffs = []
    for y in range(min(h, h2)):
        for x in range(min(w, w2)):
            i = (y * w + x) * 4
            j = (y * w2 + x) * 4
            for c in range(4):
                diffs.append(abs(buf.raw[i + c] - px2[j + c]))
    diffs.sort()
    n_ = len(diffs)
    big = sum(1 for d in diffs if d > 1)
    print("预览(C) vs 烘焙(GEGL)：中位 %d / p99 %d / 最大 %d / 差>1 的通道 %.3f%%"
          % (diffs[n_ // 2], diffs[int(n_ * 0.99)], diffs[-1],
             100.0 * big / n_))


if __name__ == "__main__":
    if "--gegl" in sys.argv:
        gegl_pair()
    else:
        sys.exit(main())
