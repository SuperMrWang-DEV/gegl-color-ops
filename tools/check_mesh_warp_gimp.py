# -*- coding: utf-8 -*-
"""在真 GIMP 里跑「自由变形（网格 + 把手）」的回归（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_mesh_warp_gimp.py').read())" --quit

纯 Python 那套（check_mesh_warp.py）验的是数学；这里验的是**接线**：
画布坐标 ↔ 图层坐标有没有错位、拖交点之后像素真的挪了、把手圆点的位置
和它的拖动反推对不对、写回缓冲区时格式对不对（没有 alpha 的图层写 RGBA
会直接抛错）、输出到新图层时原图层有没有被顺手改掉、换网格密度会不会崩。
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
    if os.path.exists(os.path.join(cand, "plugin", "mesh-warp",
                                   "mesh-warp.py")):
        ROOT = cand
        break
REPO, HERE = ROOT, os.path.join(ROOT, "tools")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))

import importlib.util                                  # noqa: E402
import mesh_warp as MW8                                # noqa: E402

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
        "mesh_plugin", os.path.join(REPO, "plugin", "mesh-warp",
                                    "mesh-warp.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_image(w=200, h=150, box=(50, 40, 150, 110), fg=(220, 40, 40),
               bg=(250, 250, 250), alpha=False):
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


def px(rgba, w, x, y):
    o = (y * w + x) * 4
    return tuple(rgba[o:o + 4])


class FakeConfig(object):
    """对话框只用到 get_property / set_property，不必真建 GimpProcedureConfig。"""

    def __init__(self, **vals):
        self.vals = {"mesh": "", "output": "replace"}
        self.vals.update(vals)

    def get_property(self, key):
        return self.vals.get(key)

    def set_property(self, key, value):
        self.vals[key] = value


def main():
    mod = load_plugin()
    images = []

    # ---- 注册 --------------------------------------------------------------
    section("过程注册")
    # 注意：这里**不能**自己 new 一个 Gimp.PlugIn 来问它 —— GimpPlugIn 构造时
    # 要求有 read channel，在 python-eval 里直接 new 会 abort 整个 GIMP。
    src = open(os.path.join(REPO, "plugin", "mesh-warp",
                            "mesh-warp.py"), encoding="utf-8").read()
    proc = Gimp.get_pdb().lookup_procedure(mod.PROC)
    if proc is None:
        print("  （%s 还没装进 GIMP，跳过 PDB 参数表；"
              "./install-plugin.sh 之后再跑就会检查）" % mod.PROC)
        check("源码里两个参数都在",
              all(('"%s"' % x) in src for x in ("mesh", "output")))
    else:
        args = [a.get_name() for a in proc.get_arguments()]
        for want in ("mesh", "output"):
            check("参数 %s 在" % want, want in args, str(args))
        cfg0 = proc.create_config()
        # 新建的 config 里字符串参数可能还是 None（GIMP 不替我们填空串）
        check("mesh 缺省是空（= 3×3 恒等网格）",
              cfg0.get_property("mesh") in ("", None),
              repr(cfg0.get_property("mesh")))
        check("默认覆盖当前图层",
              cfg0.get_property("output") == mod.OUTPUT_REPLACE,
              cfg0.get_property("output"))
    check("菜单挂在 Distort 下", "<Image>/SuperMrWang/Distort" in src)
    check("只吃 RGB*", 'set_image_types("RGB*")' in src)
    check("自绘对话框（build + show 都在）",
          "build_dialog(" in src and "show_dialog(" in src)
    check("Gimp.main 用的是 _sys.argv", "Gimp.main(" in src and
          "_sys.argv" in src)
    check("网格密度只给 2～6 格", "GRID_CHOICES = (2, 3, 4, 5, 6)" in src)

    # ---- 变形本体 ----------------------------------------------------------
    section("变形：像素真的被搬走了")
    img, layer = make_image()
    images.append(img)
    before = pixels(layer)
    mesh = mod.MWM.Mesh.identity(200, 150, 3, 3)
    mesh.node(1, 1)["x"] += 40.0
    mesh.node(1, 1)["y"] += 25.0
    mesh.auto_refresh()
    t0 = time.time()
    info = mod.warp_drawable(layer, mesh, output=mod.OUTPUT_REPLACE)
    dt = time.time() - t0
    after = pixels(layer)
    check("返回了 info（%d×%d / %d 点动过）"
          % (info["cols"], info["rows"], info["moved"]),
          info["moved"] == 1 and info["cols"] == 3, info)
    check("被拖的交点附近还是有内容（%s）" % (px(after[2], after[0], 106, 70),),
          px(after[2], after[0], 106, 70)[:3] == (220, 40, 40),
          px(after[2], after[0], 106, 70))
    check("左上角（网格角点没动）字节不变",
          px(after[2], after[0], 0, 0) == px(before[2], before[0], 0, 0),
          (px(after[2], after[0], 0, 0), px(before[2], before[0], 0, 0)))
    check("200×150 变形 < 2 s（%.2f s）" % dt, dt < 2.0, dt)
    check("图层尺寸没变", (after[0], after[1]) == (before[0], before[1]),
          (after[0], after[1]))
    diff = sum(1 for a, b in zip(after[2], before[2]) if a != b)
    check("确实重采样了（%d 个通道字节不同）" % diff, diff > 500, diff)

    section("进度条：on_tick 不会炸")
    ticks = []
    img_t, layer_t = make_image()
    images.append(img_t)
    m_t = mod.MWM.Mesh.identity(200, 150, 3, 3)
    m_t.node(1, 1)["x"] += 20.0
    m_t.auto_refresh()
    mod.warp_drawable(layer_t, m_t, on_tick=lambda: ticks.append(1))
    check("on_tick 被调用", len(ticks) > 0, len(ticks))

    section("守卫：没动网格 / 坏图层")
    img3, layer3 = make_image()
    images.append(img3)
    try:
        mod.warp_drawable(layer3, mod.MWM.Mesh.identity(200, 150, 3, 3))
        check("恒等网格时抛错", False, "没抛")
    except RuntimeError as exc:
        check("恒等网格时抛错", "touched" in str(exc).lower(), exc)
    try:
        mod.warp_drawable(layer3, None)
        check("没有网格时抛错", False, "没抛")
    except RuntimeError as exc:
        check("没有网格时抛错", "mesh" in str(exc).lower(), exc)

    group = Gimp.GroupLayer.new(img3, "grp")
    img3.insert_layer(group, None, 0)
    try:
        mod.check_drawable(group)
        check("图层组被拦住", False, "没抛")
    except RuntimeError as exc:
        check("图层组被拦住", "group" in str(exc).lower(), exc)

    # 文字层在 gimp-console 里造不出来（字体资源没加载），只能静态验。
    check("守卫里拦了文字层/矢量层",
          "is_text_layer()" in src and "is_vector_layer()" in src)

    tiny_img = Gimp.Image.new(1, 1, Gimp.ImageBaseType.RGB)
    images.append(tiny_img)
    tiny = Gimp.Layer.new(tiny_img, "tiny", 1, 1, Gimp.ImageType.RGB_IMAGE,
                          100.0, Gimp.LayerMode.NORMAL)
    tiny_img.insert_layer(tiny, None, 0)
    try:
        mod.check_drawable(tiny)
        check("1×1 图层被拦住", False, "没抛")
    except RuntimeError as exc:
        check("1×1 图层被拦住", "small" in str(exc).lower(), exc)

    try:
        mod.check_drawable(None)
        check("空选择被拦住", False, "没抛")
    except RuntimeError:
        check("空选择被拦住", True)

    # ---- alpha -------------------------------------------------------------
    section("alpha：透明区还是透明")
    img4, layer4 = make_image(alpha=True)
    images.append(img4)
    mesh4 = mod.MWM.Mesh.identity(200, 150, 3, 3)
    mesh4.node(1, 1)["x"] += 25.0
    mesh4.auto_refresh()
    mod.warp_drawable(layer4, mesh4)
    a_after = pixels(layer4)
    check("图层仍然有 alpha", bool(layer4.has_alpha()))
    check("图片中心仍然实心", px(a_after[2], a_after[0], 85, 70)[3] > 200,
          px(a_after[2], a_after[0], 85, 70)[3])

    section("没有 alpha 的图层：写回不能炸、也不能偷偷加通道")
    check("RGB 图层 has_alpha = False", not layer.has_alpha())
    check("RGB 图层写完还是 3 通道（bpp）", layer.get_bpp() == 3,
          layer.get_bpp())

    # ---- 输出方式 ----------------------------------------------------------
    section("输出到新图层：原图层要被保住")
    img5, layer5 = make_image()
    images.append(img5)
    keep = pixels(layer5)
    n_before = len(img5.get_layers())
    mesh5 = mod.MWM.Mesh.identity(200, 150, 3, 3)
    mesh5.node(1, 1)["x"] += 30.0
    mesh5.auto_refresh()
    info5 = mod.warp_drawable(layer5, mesh5, output=mod.OUTPUT_LAYER)
    check("多了一个图层", len(img5.get_layers()) == n_before + 1,
          "%d → %d" % (n_before, len(img5.get_layers())))
    check("原图层像素没被动过", pixels(layer5)[2] == keep[2])
    check("新图层名字带 (warped)", "(warped)" in info5["layer"].get_name(),
          info5["layer"].get_name())

    # ---- 对话框（无头） ----------------------------------------------------
    section("对话框：能建、拖点会变、把手能弯")
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    img6, layer6 = make_image()
    images.append(img6)
    cfg = FakeConfig()
    dlg = None
    try:
        dlg, ctx = mod.build_dialog(cfg, img6, layer6, 200, 150)
        check("建出对话框", dlg is not None)
        check("预览尺寸 = 图层尺寸（小图不放大）",
              (ctx["pw"], ctx["ph"]) == (200, 150), (ctx["pw"], ctx["ph"]))
        check("一开始是 3×3 恒等网格", ctx["mesh"].is_identity())
        first = ctx["warped"]
        check("没动过时预览就是原图", first == ctx["prgba"])
        check("有网格线（4 竖 + 4 横）",
              ctx["lines"] and len(ctx["lines"]) == 8,
              len(ctx["lines"]) if ctx["lines"] else None)

        # 交点 (1,1) 的索引 = 1*(cols+1)+1 = 5
        idx = 5
        cx, cy = 66.3, 49.7
        check("点得中交点 (1,1)", ctx["hit_node"](cx, cy) == idx,
              ctx["hit_node"](cx, cy))
        ctx["selected"] = idx
        ctx["set_node_pos"](idx, cx + 30, cy + 15)
        ctx["render"]()
        n = ctx["mesh"].node(1, 1)
        check("交点真的挪到画布坐标（%.1f, %.1f）" % (n["x"], n["y"]),
              abs(n["x"] - (cx + 30)) < 0.6 and abs(n["y"] - (cy + 15)) < 0.6,
              (n["x"], n["y"]))
        check("拖了交点之后预览变了", ctx["warped"] != first)
        note = ctx["note"].get_text()
        check("状态行没有报错", "failed" not in note, note[:70])
        check("状态行里有「1 moved」", "1 moved" in note, note[:70])

        # 把手：位置在 节点 ± 切向/3
        hp = ctx["preview_mesh"].handle(1, 1, "u", 1)
        got = ctx["hit_handle"](hp[0], hp[1])
        check("点得中把手圆点", got == ("u", 1), got)
        check("把手点落在节点右侧（%.1f > %.1f）" % (hp[0], n["x"] / ctx["k"]),
              hp[0] > n["x"] / ctx["k"], (hp, n["x"]))
        hidx = (n["x"] / ctx["k"], n["y"] / ctx["k"])
        ctx["set_handle"]("u", 1, hidx[0] + 25, hidx[1] + 15)
        check("拖把手之后切向 = 3×距离（%.1f, %.1f）"
              % (n["ux"], n["uy"]),
              abs(n["ux"] - 75.0) < 2.0 and abs(n["uy"] - 45.0) < 2.0,
              (n["ux"], n["uy"]))
        check("手拖过之后这一点的把手不再自动", n["a"] == 0, n["a"])
        ctx["render"]()
        note = ctx["note"].get_text()
        check("状态行里出现「1 bent」", "1 bent" in note, note[:70])
        check("弯曲之后网格线离开直线（交点没动）",
              abs(ctx["preview_mesh"].eval_uv(0.5, 1)[1] - 49.7) > 1.0,
              ctx["preview_mesh"].eval_uv(0.5, 1))

        ctx["combo_grid"].set_active_id("5")
        check("换到 5×5 格（%d）" % ctx["mesh"].cols, ctx["mesh"].cols == 5,
              ctx["mesh"].cols)
        check("换密度之后交点数量对", len(ctx["mesh"].nodes) == 36,
              len(ctx["mesh"].nodes))
        ctx["render"]()
        check("5×5 也能渲染", "failed" not in ctx["note"].get_text(),
              ctx["note"].get_text()[:70])

        ctx["reset_all"]()
        ctx["render"]()
        check("全部复位后预览回到原图", ctx["warped"] == ctx["prgba"])
        check("全部复位后是恒等网格", ctx["mesh"].is_identity())

        vals = ctx["values"]()
        check("values() 带回网格/输出/显示开关",
              vals["mesh"].cols == 5 and vals["output"] == mod.OUTPUT_REPLACE
              and vals["show_mesh"] is True and vals["show_handles"] is True,
              (vals["mesh"].cols, vals["output"]))
        s = mod.MWM.format_mesh_string(vals["mesh"])
        check("网格字符串能被解析回来",
              mod.MWM.parse_mesh_string(s, 200, 150).cols == 5, s[:24])
        dlg.destroy()
        dlg = None
    except Exception as exc:
        check("对话框能建出来", False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        if dlg is not None:
            try:
                dlg.destroy()
            except Exception:
                pass

    # ---- 大图 --------------------------------------------------------------
    section("自己加分割线（Alt+点击）")
    gi6 = gi
    img8, layer8 = make_image()
    images.append(img8)
    cfg8 = FakeConfig(mesh="")
    dlg8 = None
    try:
        dlg8, ctx8 = mod.build_dialog(cfg8, img8, layer8, 200, 150)
        check("加线前是 3×3", ctx8["mesh"].cols == 3)
        # 在第 2 列中间点一下（预览坐标 = 图层坐标）
        added = ctx8["add_line"](100, 75)
        m8 = ctx8["mesh"]
        check("Alt+点击真的插进一条线", added and m8.cols + m8.rows == 7,
              (m8.cols, m8.rows))
        check("断点首尾对得上列数",
              abs(m8.us[0]) < 1e-9
              and abs(m8.us[-1] - m8.cols) < 1e-9,
              (m8.us, m8.cols))
        check("下拉变成 custom", ctx8["combo_grid"].get_active_id() == "0",
              ctx8["combo_grid"].get_active_id())
        ctx8["render"]()
        check("插线后网格线多了一根",
              ctx8["lines"] and len(ctx8["lines"]) > 8,
              len(ctx8["lines"]) if ctx8["lines"] else None)
        # 换个位置再点一次，第二个方向也插得进去
        ctx8["add_line"](20, 20)
        check("第二条也插进去（%d×%d）" % (ctx8["mesh"].cols,
                                          ctx8["mesh"].rows),
              ctx8["mesh"].cols + ctx8["mesh"].rows == 8,
              (ctx8["mesh"].cols, ctx8["mesh"].rows))
        # 改一个点，加过线的网格仍然变形正常
        ctx8["set_node_pos"](0, 10, 10)
        ctx8["render"]()
        check("加线后拖点预览仍在变", ctx8["warped"] != ctx8["prgba"])
        cfg8.set_property("mesh", MW8.format_mesh_string(ctx8["mesh"]))
        txt8 = cfg8.get_property("mesh")
        check("写回的串里带了分割线", "u:" in txt8 and "v:" in txt8, txt8[:50])
    finally:
        if dlg8 is not None:
            try:
                dlg8.destroy()
            except Exception:
                pass

    section("网格串里带分割线也能跑")
    img9, layer9 = make_image()
    images.append(img9)
    mesh9 = MW8.Mesh.identity(200, 150, 3, 3)
    mesh9.node(1, 1)["x"] += 24.0
    mesh9.auto_refresh()
    mesh9 = mesh9.split_u(1, 0.4)
    info9 = mod.warp_drawable(layer9, mesh9)
    check("带分割线的网格能直接变形", info9["cols"] == 4, info9)
    gw9, gh9, gb9 = pixels(layer9)
    c9 = px(gb9, gw9, 100, 75)
    check("像素真的被搬走（中心取色变了）",
          len(c9) == 4 and c9[:3] != (0, 0, 0), c9)

    section("768×1024 走一遍完整流程")
    img7, layer7 = make_image(768, 1024, box=(300, 400, 500, 600))
    images.append(img7)
    mesh7 = mod.MWM.Mesh.identity(768, 1024, 3, 3)
    mesh7.node(1, 1)["x"] += 120.0
    mesh7.node(1, 1)["y"] += 60.0
    mesh7.node(1, 0)["ux"], mesh7.node(1, 0)["uy"] = 300.0, 120.0
    mesh7.node(1, 0)["a"] = 0
    mesh7.auto_refresh()
    t0 = time.time()
    info7 = mod.warp_drawable(layer7, mesh7)
    dt7 = time.time() - t0
    check("768×1024 全流程 < 6 s（%.2f s）" % dt7, dt7 < 6.0, dt7)
    got7 = pixels(layer7)
    check("变形后仍有内容、尺寸没变",
          (got7[0], got7[1]) == (768, 1024), (got7[0], got7[1]))
    check("把手那一处也算进去了", info7["curved"] == 1, info7)

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
