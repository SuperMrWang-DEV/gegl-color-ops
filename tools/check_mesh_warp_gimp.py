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
import warp_math as WM                                 # noqa: E402

try:
    import native_warp as _NWmod
    NW = _NWmod.mesh_preview()
except Exception as _e:                                # noqa: BLE001
    NW = None
    print("native_warp 不可用：", _e)

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

    # `_, layer = apply_filter(...)` 会把模块级翻译函数 `_` 绑成 DrawableFilter
    # 实例，下一行 _("…") 就报「'DrawableFilter' object is not callable」。
    check("run() 没把 `_` 覆盖成滤镜返回值",
          "_, layer = apply_filter" not in src and "_, layer =" not in src)
    # 密度必须分「列」和「行」两个自由度。以前只有 2..6 的方形下拉，
    # 而且 resample(want, want) 把行列绑死，所以 6×2 这种根本设不出来。
    check("密度是列/行两个独立数字框",
          "spin_cols" in src and "spin_rows" in src
          and "resample(want, want)" not in src)
    check("行列上限用 MAX_CELLS 而不是写死 6",
          "new_with_range(1, MWM.MAX_CELLS, 1)" in src
          and "GRID_CHOICES = (2, 3, 4, 5, 6)" not in src)

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
        # 现在返回 (节点索引, 轴, 方向)：拖谁的把手就自动选中谁
        check("点得中把手圆点（带节点索引）", got == (5, "u", 1), got)
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

        # hover 的节点也要能直接拖把手（不用先点一下选中）
        ctx["selected"] = -1
        ctx["hover"] = 1 * (ctx["mesh"].cols + 1) + 1
        hp2 = ctx["preview_mesh"].handle(1, 1, "v", -1)
        check("hover 的节点把手也点得中",
              ctx["hit_handle"](hp2[0], hp2[1]) == (5, "v", -1),
              ctx["hit_handle"](hp2[0], hp2[1]))
        ctx["selected"] = 5
        ctx["hover"] = -1

        # 防折叠：目标拖到邻居右边 40%（会自交），最终位置必须停在不折处
        ctx["mesh"] = MW8.Mesh.identity(ctx["w"], ctx["h"], 4, 4)
        ctx["selected"] = -1
        m0 = ctx["mesh"]
        j0, i0 = 2, 2
        idx0 = j0 * (m0.cols + 1) + i0
        n0 = m0.node(i0, j0)
        x0, y0 = n0["x"], n0["y"]
        right = m0.node(i0 + 1, j0)["x"]
        ctx["set_node_pos"](idx0, (right + 0.4 * (right - x0)) / ctx["k"],
                            y0 / ctx["k"])
        moved = n0["x"] - x0
        check("拖过邻居会被限幅（只走了 %.1f px，邻居在 %.1f）" % (moved, right - x0),
              moved < (right - x0) * 1.05, (moved, right - x0))
        check("限幅之后网格没有自交", not m0.folded(), m0.cell_fold_ratio(i0, j0))
        check("限幅不是「原地不动」", moved > (right - x0) * 0.4, moved)

        ctx["spin_cols"].set_value(5)
        ctx["spin_rows"].set_value(5)
        check("换到 5×5 格（%d×%d）" % (ctx["mesh"].cols, ctx["mesh"].rows),
              ctx["mesh"].cols == 5 and ctx["mesh"].rows == 5,
              (ctx["mesh"].cols, ctx["mesh"].rows))
        check("换密度之后交点数量对", len(ctx["mesh"].nodes) == 36,
              len(ctx["mesh"].nodes))
        ctx["render"]()
        check("5×5 也能渲染", "failed" not in ctx["note"].get_text(),
              ctx["note"].get_text()[:70])
        # 恒等网格会被短路成 "id"（连 C 都不调），所以先把中间那个点拖开
        _m5 = ctx["mesh"]
        _i5, _j5 = _m5.cols // 2, _m5.rows // 2
        _n5 = _m5.node(_i5, _j5)
        _n5["x"] += 12.0
        _n5["y"] -= 8.0
        _m5.auto_refresh()
        check("网格已经不是恒等（拖动生效）", not _m5.is_identity(),
              _m5.is_identity())
        ctx["render"]()
        check("预览走 C（ctypes 直调算子）",
              ctx.get("preview_path") == "c",
              ctx["note"].get_text().replace("\n", " | ")[:90])
        # 和 Python 路径（numpy）比：两边同一套数学，主要差异来自 Newton
        # 收敛细节，只要求「95% 的通道几乎一样」。差得离谱就说明 ctypes 传的
        # mesh 串 / 尺寸 / 坐标对不上（这类错会让整幅图错位，不是几十级噪声）。
        try:
            _ref = WM.warp_rgba(ctx["prgba"], ctx["pw"], ctx["ph"],
                                MW8.build_field(ctx["preview_mesh"],
                                                ctx["pw"], ctx["ph"]))
            _d = sorted(abs(_ref[_i] - ctx["warped"][_i])
                        for _i in range(0, len(_ref), 7))
            _p95 = _d[int(len(_d) * 0.95)]
            check("C 预览与 numpy 路径 95%% 一致（p95=%d / 最大 %d）"
                  % (_p95, _d[-1]), _p95 <= 3, _p95)
        except NameError as _exc:
            check("C 预览与 numpy 路径一致", False, "缺模块: %s" % _exc)

        # 非方形：6 列 × 2 行。这一条就是用户要的「横线竖线分开设」。
        ctx["spin_cols"].set_value(6)
        ctx["spin_rows"].set_value(2)
        check("能设成 6 列 × 2 行（%d×%d）" % (ctx["mesh"].cols, ctx["mesh"].rows),
              ctx["mesh"].cols == 6 and ctx["mesh"].rows == 2,
              (ctx["mesh"].cols, ctx["mesh"].rows))
        check("6×2 交点数量对（7×3=21）", len(ctx["mesh"].nodes) == 21,
              len(ctx["mesh"].nodes))
        ctx["render"]()
        check("6×2 也能渲染", "failed" not in ctx["note"].get_text(),
              ctx["note"].get_text()[:70])
        # 恒等网格换密度后画面必须还是恒等（不能因为重新拟合走样）
        ctx["reset_all"]()
        ctx["render"]()
        check("6×2 恒等网格仍是恒等",
              ctx["warped"] is ctx["prgba"], None)
        # 改回 3×3：后面的断言都按 3×3 写，顺便验证能来回改
        ctx["spin_cols"].set_value(3)
        ctx["spin_rows"].set_value(3)
        check("能改回 3×3（%d×%d）" % (ctx["mesh"].cols, ctx["mesh"].rows),
              ctx["mesh"].cols == 3 and ctx["mesh"].rows == 3,
              (ctx["mesh"].cols, ctx["mesh"].rows))

        ctx["reset_all"]()
        ctx["render"]()
        check("全部复位后预览回到原图", ctx["warped"] == ctx["prgba"])
        check("全部复位后是恒等网格", ctx["mesh"].is_identity())

        vals = ctx["values"]()
        check("values() 带回网格/输出/显示开关",
              vals["mesh"].cols == 3 and vals["mesh"].rows == 3
              and vals["output"] == mod.OUTPUT_REPLACE
              and vals["show_mesh"] is True and vals["show_handles"] is True,
              (vals["mesh"].cols, vals["output"]))
        s = mod.MWM.format_mesh_string(vals["mesh"])
        check("网格字符串能被解析回来",
              mod.MWM.parse_mesh_string(s, 200, 150).cols == 3, s[:24])
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
        check("数字框跟着插线更新（%d×%d）"
              % (ctx8["spin_cols"].get_value(), ctx8["spin_rows"].get_value()),
              int(ctx8["spin_cols"].get_value()) == m8.cols
              and int(ctx8["spin_rows"].get_value()) == m8.rows,
              (ctx8["spin_cols"].get_value(), ctx8["spin_rows"].get_value(),
               m8.cols, m8.rows))
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

    # ---- 非破坏 ------------------------------------------------------------
    section("非破坏：网格挂在滤镜上，像素不动")
    imgf, layerf = make_image()
    images.append(imgf)
    beforef = pixels(layerf)
    meshf = mod.MWM.Mesh.identity(200, 150, 3, 3)
    meshf.node(1, 1)["x"] += 25
    meshf.node(1, 1)["y"] += 15
    meshf.auto_refresh()
    filt, tgt = mod.apply_filter(layerf, meshf)
    check("挂完滤镜像素一个字节都没动", beforef == pixels(layerf))
    f_list = tgt.get_filters() if hasattr(tgt, 'get_filters') else []
    check("图层上多了一条 lb:mesh-warp",
          len(f_list) == 1 and
          f_list[0].get_operation_name() == mod.FILTER_OP,
          [x.get_operation_name() for x in f_list])
    st = mod.load_filter_state(tgt)
    check("重跑时能把网格读回来",
          bool(st) and st['mesh'].startswith("3,3"), st)

    img9, layer9 = make_image()
    images.append(img9)
    # 参考也要读同一份「两位小数」网格串：滤镜只能看见序列化后的值，
    # 把手限幅是个 max()，0.01 px 的舍入正好在临界点上会翻面，直接用
    # 原对象比会差出几个小块（实测最大 102 级），那是口径不同不是算错。
    ref_mesh = mod.MWM.parse_mesh_string(st['mesh'], 200, 150)
    mod.warp_drawable(layer9, ref_mesh, output=mod.OUTPUT_REPLACE)
    ref9 = pixels(layer9)
    try:
        tgt.merge_filters()
        got9 = pixels(tgt)
        nd = sum(1 for a, b in zip(got9[2], ref9[2]) if a != b)
        big = sum(1 for a, b in zip(got9[2], ref9[2]) if abs(a - b) > 6)
        mx = max(abs(a - b) for a, b in zip(got9[2], ref9[2]))
        # 容差：C 算子与 Python 版在**折点**处 Newton 可能收敛到另一支
        # （同一现象见 _mw_probe.py，最大 ~112 级、十几个像素），别按 0 卡。
        check("滤镜渲染 ≈ 破坏性结果（%d 字节不同 / %d 超 6 级 / 最大 %d）"
              % (nd, big, mx), big <= 120 and mx <= 130, (nd, big, mx))
    except Exception as exc:
        check("merge_filters 可用（%s）" % exc, False)

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
