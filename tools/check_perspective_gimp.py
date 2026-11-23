# -*- coding: utf-8 -*-
"""在真 GIMP 里跑「消失点（透视平面）」的回归（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_perspective_gimp.py').read())" --quit

纯 Python 那套（check_perspective.py）验的是数学；这里验的是**接线**：
画布坐标 ↔ 图层坐标有没有错位、贴图有没有真的透视变形、平面外的像素
是不是一个没动、没有 alpha 的图层写回会不会炸、拉正出来的新图层尺寸
对不对、对话框里建平面/拖角/延伸有没有写进对的坐标、退化四边形会不会
被拦下。
"""

import math
import os
import sys
import time

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
for cand in (ROOT, os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))):
    if os.path.exists(os.path.join(cand, "plugin", "vanishing-point",
                                   "vanishing-point.py")):
        ROOT = cand
        break
REPO, HERE = ROOT, os.path.join(ROOT, "tools")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))

import importlib.util                                  # noqa: E402

PASS = 0
FAIL = []
SECTION = ""


def section(name):
    global SECTION
    SECTION = name
    print("\n" + name)


def check(label, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  %-52s %s" % (label, detail))
    else:
        FAIL.append("%s / %s（%s）" % (SECTION, label, detail))
        print("  FAIL %-47s %s" % (label, detail))


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "vp_plugin", os.path.join(REPO, "plugin", "vanishing-point",
                                  "vanishing-point.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_image(w=200, h=150, box=(50, 40, 150, 110), fg=(220, 40, 40),
               bg=(250, 250, 250), alpha=False, grid=0):
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    itype = Gimp.ImageType.RGBA_IMAGE if alpha else Gimp.ImageType.RGB_IMAGE
    layer = Gimp.Layer.new(img, "photo", w, h, itype, 100.0,
                           Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    bpp = 4 if alpha else 3
    data = bytearray(w * h * bpp)
    x1, y1, x2, y2 = box
    for y in range(h):
        for x in range(w):
            o = (y * w + x) * bpp
            inside = x1 <= x < x2 and y1 <= y < y2
            if grid and (x % grid == 0 or y % grid == 0):
                data[o:o + 3] = bytes((20, 20, 20))
            else:
                data[o:o + 3] = bytes(fg if inside else bg)
            if alpha:
                data[o + 3] = 255
    fmt = "R'G'B'A u8" if alpha else "R'G'B' u8"
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), fmt, bytes(data))
    buf.flush()
    return img, layer


def pixels(layer):
    w, h = layer.get_width(), layer.get_height()
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0,
                                 "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    return w, h, bytes(bytearray(raw))


def layer_at(img, i):
    """取第 i 层。有的 GIMP 版本把层列表再包一层元组。"""
    lay = img.get_layers()
    if isinstance(lay, tuple) and len(lay) == 1 and isinstance(lay[0], tuple):
        lay = lay[0]
    return lay[i]


def px(rgba, w, x, y):
    o = (y * w + x) * 4
    return tuple(rgba[o:o + 4])


class FakeConfig(object):
    def __init__(self, **vals):
        self.vals = {"planes": "", "mode": "paste", "along": "w",
                     "output": "replace", "stairs": ""}
        self.vals.update(vals)

    def get_property(self, key):
        return self.vals.get(key)

    def set_property(self, key, value):
        self.vals[key] = value


def main():
    mod = load_plugin()
    P = mod.PERSP
    images = []

    # ---- 注册 --------------------------------------------------------------
    section("过程注册")
    src = open(os.path.join(REPO, "plugin", "vanishing-point",
                            "vanishing-point.py"), encoding="utf-8").read()
    proc = Gimp.get_pdb().lookup_procedure(mod.PROC)
    if proc is None:
        print("  （%s 还没装进 GIMP，跳过 PDB 参数表；"
              "./install-plugin.sh 之后再跑就会检查）" % mod.PROC)
        check("源码里五个参数都在",
              all(('"%s"' % x) in src
                  for x in ("planes", "mode", "along", "output", "stairs")))
        check("源码里带上了 scene3d",
              ("import scene3d" in src) and ("stair_faces" in src))
    else:
        args = [a.get_name() for a in proc.get_arguments()]
        for want in ("planes", "mode", "along", "output", "stairs"):
            check("参数 %s 在" % want, want in args, str(args))
        cfg0 = proc.create_config()
        check("planes 缺省是空", cfg0.get_property("planes") in ("", None),
              repr(cfg0.get_property("planes")))
        check("mode 缺省是 paste", cfg0.get_property("mode") == "paste",
              cfg0.get_property("mode"))
    check("菜单挂在 SuperMrWang/Distort 下",
          "SuperMrWang/Distort" in src)

    # ---- 贴图：像素真的透视挪了，外面一个没动 ------------------------------
    section("透视贴图（真写回缓冲区）")
    img1, layer1 = make_image(200, 150, grid=25, alpha=False)
    images.append(img1)
    before = pixels(layer1)[2]
    # 梯形：上边比下边窄，明显带透视
    quad = [[60, 30], [150, 20], [180, 130], [30, 140]]
    plane = P.Plane(quad)
    check("平面有效", plane.is_valid())
    t0 = time.time()
    info1 = mod.apply_planes(layer1, [plane], mode=mod.MODE_PASTE,
                             output=mod.OUTPUT_REPLACE)
    dt1 = time.time() - t0
    after = pixels(layer1)[2]
    check("写回之后尺寸没变", (pixels(layer1)[0], pixels(layer1)[1]) == (200, 150))
    check("像素确实变了（不是空操作）", after != before)
    check("没有 alpha 的图层也能写回（3 通道不炸）", len(after) == 200 * 150 * 4)

    # 平面外取样：左上角离梯形很远，必须原样
    outside = [(3, 3), (196, 3), (3, 146), (196, 146), (100, 6)]
    keep = all(px(after, 200, x, y) == px(before, 200, x, y)
               for x, y in outside)
    check("平面外的角上像素一个字节都没动", keep,
          [(x, y, px(after, 200, x, y)) for x, y in outside if
           px(after, 200, x, y) != px(before, 200, x, y)])

    # 平面内：贴图把整幅按四角重采样，棋盘格必须被拧歪——数变了多少像素，
    # 不能是 0（空操作）也不能是全图（漏了范围限制）
    changed = 0
    for i in range(0, len(after), 4):
        if after[i:i + 3] != before[i:i + 3]:
            changed += 1
    total = 200 * 150
    check("变化的像素数合理（%d / %d）" % (changed, total),
          200 < changed < total * 0.75, changed)
    check("贴图 <.5 s（%.2f s）" % dt1, dt1 < 0.5, dt1)

    # ---- 输出到新图层 ------------------------------------------------------
    section("输出到新图层")
    img2, layer2 = make_image(160, 120, grid=20, alpha=True)
    images.append(img2)
    keep2 = pixels(layer2)[2]
    n0 = len(img2.get_layers())
    p2 = P.Plane([[40, 20], [130, 15], [150, 100], [20, 105]])
    info2 = mod.apply_planes(layer2, [p2], mode=mod.MODE_PASTE,
                             output=mod.OUTPUT_LAYER)
    check("图层数 +1", len(img2.get_layers()) == n0 + 1,
          "%d → %d" % (n0, len(img2.get_layers())))
    check("原图层像素没被动过", pixels(layer2)[2] == keep2)
    check("新图层名字带 (vanishing point)",
          "(vanishing point)" in info2["layer"].get_name(),
          info2["layer"].get_name())

    # ---- 拉正 --------------------------------------------------------------
    section("拉正")
    img3, layer3 = make_image(240, 180, grid=24, alpha=False)
    images.append(img3)
    p3 = P.Plane([[30, 40], [210, 25], [230, 150], [15, 165]])
    info3 = mod.apply_planes(layer3, [p3], mode=mod.MODE_RECTIFY)
    check("拉正建出了新图层", isinstance(info3["layer"], Gimp.Layer))
    ow, oh = info3["size"]
    check("新图层尺寸 = 平面边长估算（%d×%d）" % (ow, oh),
          (info3["layer"].get_width(), info3["layer"].get_height()) == (ow, oh),
          (info3["layer"].get_width(), info3["layer"].get_height()))
    check("拉正尺寸和平面尺寸同量级（不是 0 也不是原图）",
          100 < ow < 400 and 100 < oh < 400, (ow, oh))
    rw, rh, rdata = pixels(info3["layer"])
    nonblank = sum(1 for i in range(0, len(rdata), 4) if rdata[i + 3] > 0)
    check("拉正出来的图层不是全空", nonblank > rw * rh * 0.5,
          "%d/%d" % (nonblank, rw * rh))
    check("原图层还在（拉正是新增，不是替换）",
          len(img3.get_layers()) == 2, len(img3.get_layers()))

    # ---- 拦截退化输入 ------------------------------------------------------
    section("拦截退化输入")
    img4, layer4 = make_image(120, 90)
    images.append(img4)
    try:
        mod.apply_planes(layer4, [], mode=mod.MODE_PASTE)
        check("没有平面时报错", False)
    except RuntimeError as exc:
        check("没有平面时报错", "plane" in str(exc).lower(), str(exc))
    try:
        mod.apply_planes(layer4, [P.Plane([(10, 10), (12, 10), (12, 12),
                                           (10, 12)])], mode=mod.MODE_PASTE)
        check("太小的四边形被拦下", False)
    except RuntimeError as exc:
        check("太小的四边形被拦下", True, str(exc)[:40])
    try:
        mod.apply_planes(layer4, [P.Plane([(0, 0), (100, 0), (20, 30),
                                           (0, 100)])], mode=mod.MODE_PASTE)
        check("凹四边形被拦下", False)
    except RuntimeError as exc:
        check("凹四边形被拦下", True, str(exc)[:40])

    # ---- 对话框（无头） ----------------------------------------------------
    section("对话框：建平面、拖角、延伸")
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    img5, layer5 = make_image(1200, 900, grid=100)
    images.append(img5)
    cfg = FakeConfig()
    dlg = None
    try:
        dlg, ctx = mod.build_dialog(cfg, img5, layer5, 1200, 900)
        check("建出对话框", dlg is not None)
        check("预览被缩到 %d 长边" % mod.PREVIEW_EDGE,
              max(ctx["pw"], ctx["ph"]) == mod.PREVIEW_EDGE,
              (ctx["pw"], ctx["ph"]))
        k = ctx["k"]
        check("画布→图层倍率 k ≈ %.2f" % k, 2.0 < k < 2.2, k)
        check("一打开就有一个默认平面", len(ctx["planes"]) == 1)
        check("默认平面是有效凸四边形", ctx["planes"][0].is_valid())
        check("有透视网格线", len(ctx["lines"]) >= 8, len(ctx["lines"]))
        check("三个消失点都算出来了",
              ctx["vpoints"] and all(v is not None for v in ctx["vpoints"]),
              ctx["vpoints"])

        # 拖角：给的是画布坐标，写进平面必须是图层坐标
        p0 = ctx["planes"][0]
        cx0 = p0.corners[0][0] / k
        cy0 = p0.corners[0][1] / k
        check("角点命中（画布坐标）", ctx["hit_corner"](cx0, cy0) == 0,
              ctx["hit_corner"](cx0, cy0))
        ctx["set_corner"](0, cx0 + 20, cy0 + 10)
        check("set_corner 换算回图层坐标（+%.0f px）" % (20 * k),
              abs(p0.corners[0][0] - (cx0 + 20) * k) < 1.0
              and abs(p0.corners[0][1] - (cy0 + 10) * k) < 1.0,
              (p0.corners[0][0], p0.corners[0][1]))

        # 边中点 → 延伸出新平面
        n_before = len(ctx["planes"])
        mx, my = ctx["scale_plane"](ctx["planes"][0], 1.0 / k).edge_mid(1)
        side = ctx["hit_edge_mid"](mx, my)
        check("边中点命中（第 %d 条边）" % side, side == 1, side)
        base_before = ctx["planes"][0].copy()
        ctx["ext_src"] = (base_before, 1)
        ctx["extend_from"](1, mx + 60, my)
        check("延伸之后平面数不变（是改当前这块，不是再加一块）",
              len(ctx["planes"]) == n_before, len(ctx["planes"]))
        ext = ctx["planes"][0]
        check("延伸出来的平面仍是凸的有效四边形", ext.is_valid(),
              [tuple(round(v) for v in c) for c in ext.corners])
        same_a = abs(ext.corners[0][0] - base_before.corners[1][0]) < 1e-9 and \
            abs(ext.corners[0][1] - base_before.corners[1][1]) < 1e-9
        same_b = abs(ext.corners[1][0] - base_before.corners[2][0]) < 1e-9 and \
            abs(ext.corners[1][1] - base_before.corners[2][1]) < 1e-9
        check("延伸平面与原边严格共用两个角", same_a and same_b,
              (ext.corners[0], base_before.corners[1]))

        # 新建 / 删除
        n0 = len(ctx["planes"])
        ctx["new_plane"]()
        check("新建平面 +1", len(ctx["planes"]) == n0 + 1)
        ctx["del_plane"]()
        check("删除平面 -1", len(ctx["planes"]) == n0)

        # 空白处拖一个新矩形
        n0 = len(ctx["planes"])
        ctx["sel"] = -1
        idx = ctx["add_plane"](100, 100, 300, 260)
        check("拖出来的矩形成了新平面", idx >= 0 and len(ctx["planes"]) == n0 + 1)
        np_ = ctx["planes"][idx]
        check("新平面的角在图层坐标（不是画布坐标）",
              abs(np_.corners[0][0] - 100 * k) < 1.0, np_.corners[0])

        ctx["render"]()
        note = ctx["note"].get_text()
        check("状态行写得出东西", bool(note and len(note) > 5), note[:60])

        v = ctx["values"]()
        check("values() 带回所有平面和模式",
              len(v["planes"]) == len(ctx["planes"]) and v["mode"] == "paste")
    finally:
        if dlg is not None:
            if ctx["id"]:
                from gi.repository import GLib
                GLib.source_remove(ctx["id"])
            dlg.destroy()

    # ---- 台阶 --------------------------------------------------------------
    section("台阶（折面）")
    STAIR_QUAD = [(20, 30), (180, 20), (160, 130), (40, 140)]
    img7, layer7 = make_image(200, 150, grid=15)
    images.append(img7)
    before7 = pixels(layer7)[2]
    st = mod.S3D.parse_stair_string("2,5,0.12,0,0")
    check("参数串解析出 5 级台阶", st["on"] and st["steps"] == 5)
    info7 = mod.apply_planes(layer7, [P.Plane(STAIR_QUAD)], mode=mod.MODE_PASTE,
                             output=mod.OUTPUT_REPLACE, stairs=st)
    check("台阶跑通并回报面片数", bool(info7.get("stairs"))
          and info7["stairs"]["faces"] == 10, info7.get("stairs"))
    w7, h7, after7 = pixels(layer7)
    changed = sum(1 for i in range(0, len(after7), 4)
                  if after7[i:i + 3] != before7[i:i + 3])
    check("台阶真的改了像素（%d）" % changed, 400 < changed < 200 * 150 * 0.9,
          changed)
    check("台阶的总展开长 = 5×(run+rise)",
          abs(info7["stairs"]["total_v"] - 5 * (0.2 + 0.12)) < 1e-6,
          info7["stairs"]["total_v"])
    check("台阶高度 = 5×rise",
          abs(info7["stairs"]["height"] - 0.6) < 1e-9,
          info7["stairs"]["height"])

    # 新图层输出
    img8, layer8 = make_image(200, 150, grid=15)
    images.append(img8)
    before8 = pixels(layer8)
    info8 = mod.apply_planes(layer8, [P.Plane(STAIR_QUAD)], mode=mod.MODE_PASTE,
                             output=mod.OUTPUT_LAYER, stairs=st)
    check("台阶 + 新图层：多了一层", len(img8.get_layers()) == 2,
          len(img8.get_layers()))
    # 按名字找新层：这个 build 的 get_layers() 有时给 list 有时给 tuple，
    # 索引拿到的对象不一定稳，遍历最保险。
    made = None
    for lyr in img8.get_layers():
        if "(vanishing point)" in lyr.get_name():
            made = lyr
    check("台阶 + 新图层：新层按名字找得到", made is not None)
    check("台阶 + 新图层：原层不动",
          pixels(layer8)[2] == before8[2], "原层被改了")
    if made is not None:
        check("台阶 + 新图层：新层是折过的",
              pixels(made)[2] != before8[2], "新层和原层一样")

    # 关掉台阶时不该有台阶信息
    img9, layer9 = make_image(200, 150, grid=15)
    images.append(img9)
    info9 = mod.apply_planes(layer9, [P.Plane(STAIR_QUAD)], mode=mod.MODE_PASTE,
                             stairs=mod.S3D.parse_stair_string(""))
    check("空参数串 = 不折台阶", info9.get("stairs") is None)

    # 矩形（没有透视）要能退回近似而不是报错
    img10, layer10 = make_image(200, 150, grid=20)
    images.append(img10)
    info10 = mod.apply_planes(layer10, [P.Plane([(30, 30), (170, 30),
                                                 (170, 120), (30, 120)])],
                              mode=mod.MODE_PASTE,
                              stairs=mod.S3D.parse_stair_string("2,4,0.1,0,0"))
    check("无透视的矩形也能折（近似相机）",
          bool(info10.get("stairs"))
          and info10["stairs"]["cam"].approx is True,
          info10.get("stairs") and info10["stairs"]["cam"].approx)

    # ---- 序列化经 config 往返 ----------------------------------------------
    section("config 往返")
    img6, layer6 = make_image(200, 150, grid=25)
    images.append(img6)
    cfg = FakeConfig()
    dlg = None
    try:
        dlg, ctx = mod.build_dialog(cfg, img6, layer6, 200, 150)
        v = ctx["values"]()
        cfg.set_property("planes", mod.PERSP.format_plane_string(v["planes"]))
        cfg.set_property("mode", "rectify")
        cfg.set_property("along", "v")
        cfg.set_property("output", "new-layer")
        cfg.set_property("stairs", mod.S3D.format_stair_string(
            {"on": True, "edge": 1, "steps": 4, "rise": 0.09, "run": 0.05,
             "flip": True}))
    finally:
        if dlg is not None:
            dlg.destroy()
    parsed = mod.PERSP.parse_plane_string(cfg.get_property("planes"), 200, 150)
    check("平面串能解析回来", len(parsed) == 1, cfg.get_property("planes")[:60])
    back_st = mod.S3D.parse_stair_string(cfg.get_property("stairs"))
    check("台阶串经 config 往返",
          back_st["on"] and back_st["edge"] == 1 and back_st["steps"] == 4
          and abs(back_st["rise"] - 0.09) < 1e-6 and back_st["flip"] is True,
          cfg.get_property("stairs"))
    check("解析回来的平面有效", parsed and parsed[0].is_valid())
    info6 = mod.apply_planes(layer6, parsed, mode=cfg.get_property("mode"),
                             output=cfg.get_property("output"))
    check("用 config 里的值也能跑（模式=rectify）",
          info6["mode"] == "rectify" and info6["size"] != (200, 150),
          info6["size"])
    check("新图层已插入", len(img6.get_layers()) == 2, len(img6.get_layers()))

    for im in images:
        try:
            im.delete()
        except Exception:
            pass


main()

print("\n" + "=" * 62)
if FAIL:
    print("失败 %d 项 / 通过 %d 项" % (len(FAIL), PASS))
    for f in FAIL:
        print("  - %s" % f)
else:
    print("全部通过：%d 项检查" % PASS)
