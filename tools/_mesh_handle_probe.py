#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：C 算子（lb:mesh-warp）在「手拖把手」的情况下到底怎么变形。

问题背景：用户反馈「拖节点只能平移，拐不出弯」。数学层的 eval_uv 能拐弯
（probe 里已验证），但 C 算子对把手（a=0 的 ux/uy）是否照做，需要像素级证据。
跑出四张图，人眼对比。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))
sys.path.insert(0, HERE)

import ai_client as AC          # noqa: E402
import mesh_warp as MWM         # noqa: E402

OUT = os.path.join(ROOT, "build")
W = H = 300
COLS = ROWS = 3


def field_png():
    """白底 + 每 30 px 一条浅灰线 + 中心十字：线弯没弯一眼能看出。"""
    px = bytearray(W * H * 4)
    for y in range(H):
        for x in range(W):
            i = (y * W + x) * 4
            v = 255
            if x % 30 == 0 or y % 30 == 0:
                v = 205
            if abs(x - W // 2) <= 1 or abs(y - H // 2) <= 1:
                v = 60
            px[i] = px[i + 1] = px[i + 2] = v
            px[i + 3] = 255
    return AC.rgba_png(W, H, bytes(px))


def find_gegl():
    for p in (r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
              r"C:\Program Files\GIMP 3\bin\gegl.exe"):
        if os.path.exists(p):
            return p
    raise SystemExit("gegl.exe 不在预期位置")


def run(name, mesh):
    src = os.path.join(OUT, "_mh_src.png")
    dst = os.path.join(OUT, "_mh_%s.png" % name)
    if not os.path.exists(src):
        open(src, "wb").write(field_png())
    env = dict(os.environ)
    # 与 tools/check_*_ps.py 同一套：GIMP 的 lib/gegl-0.4 放自带算子，
    # 用户目录放我们装进去的算子。只剩自己的 build 会找不到 gegl:nop。
    exe = find_gegl()
    lib = os.path.join(os.path.dirname(os.path.dirname(exe)), "lib", "gegl-0.4")
    user = os.path.join(os.environ.get("LOCALAPPDATA", ""), "gegl-0.4", "plug-ins")
    env["GEGL_PATH"] = os.pathsep.join([os.path.join(ROOT, "build"), user, lib])
    cmd = [find_gegl(), src, "-o", dst, "--", "lb:mesh-warp",
           "mesh=" + MWM.format_mesh_string(mesh)]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0 or os.path.exists(dst) is False:
        print("FAIL", name, r.stderr[-400:])
        return None
    print("ok", name, os.path.getsize(dst))
    return dst


def base():
    return MWM.Mesh.identity(W, H, COLS, ROWS)


def main():
    os.makedirs(OUT, exist_ok=True)

    run("identity", base())

    # A. 只拖节点：自动把手，形状应该是「整块跟着挪，附近平滑」
    a = base()
    n = a.node(1, 1)
    n["x"], n["y"] = W * 0.75, H * 0.25
    a.auto_refresh()
    run("node-only", a)

    # B. 节点不动，只把 (1,1) 的 U 把手转 90°（朝上）—— 这就是「拐弯」
    b = base()
    n = b.node(1, 1)
    n["ux"], n["uy"] = 0.0, 100.0
    n["a"] = 0
    run("bend-u90", b)

    # C. 同上，但转角更狠：把手朝右上、长度 1.5 格
    c = base()
    n = c.node(1, 1)
    n["ux"], n["uy"] = 106.0, 106.0
    n["a"] = 0
    run("bend-diag", c)

    # D. 拖节点 + 同时转把手（PS 里做「拉出一只耳朵」的动作）
    d = base()
    n = d.node(1, 1)
    n["x"], n["y"] = W * 0.62, H * 0.38
    n["ux"], n["uy"] = 0.0, 120.0
    n["a"] = 0
    d.auto_refresh()
    # auto_refresh 会跳过 a=0 的节点，但 v 向还是自动的，够了
    run("node+bend", d)


if __name__ == "__main__":
    main()
