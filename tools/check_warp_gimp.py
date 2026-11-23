# -*- coding: utf-8 -*-
"""在真 GIMP 里跑「木偶变形」的回归（--batch 加载本文件）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_warp_gimp.py').read())" --quit

纯 Python 那套（check_warp.py）验的是数学；这里验的是**接线**：
钉子的图层坐标 ↔ 预览坐标有没有错位、变形真的落在像素上、写回缓冲区时
格式对不对（没有 alpha 的图层写 RGBA 会直接抛错）、半径外的像素是不是一个
字节都没动、输出到新图层时原图层有没有被顺手改掉。
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
    if os.path.exists(os.path.join(cand, "plugin", "puppet-warp",
                                   "puppet-warp.py")):
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
        "warp_plugin", os.path.join(REPO, "plugin", "puppet-warp",
                                    "puppet-warp.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pdb(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    class FakeConfig(object):
        """对话框只用到 get_property，不必真的去建 GimpProcedureConfig。"""

        def __init__(self, **vals):
            self.vals = {"pins": "", "mode": mod.MODE_SIMILARITY,
                         "radius": 30.0, "output": mod.OUTPUT_REPLACE}
            self.vals.update(vals)

        def get_property(self, key):
            return self.vals.get(key)

    cfg = FakeConfig()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def make_image(w=200, h=150, box=(50, 40, 150, 110), fg=(220, 40, 40),
               bg=(250, 250, 250), alpha=False, alpha_box=None):
    """白底 + 中间一块红方块。alpha=True 时切成 RGBA，alpha_box 之外全透明。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    itype = Gimp.ImageType.RGBA_IMAGE if alpha else Gimp.ImageType.RGB_IMAGE
    layer = Gimp.Layer.new(img, "photo", w, h, itype, 100.0,
                           Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    bpp = 4 if alpha else 3
    data = bytearray(w * h * bpp)
    ax1, ay1, ax2, ay2 = alpha_box or (0, 0, w, h)
    x1, y1, x2, y2 = box
    for y in range(h):
        for x in range(w):
            o = (y * w + x) * bpp
            inside = x1 <= x < x2 and y1 <= y < y2
            data[o:o + 3] = bytes(fg if inside else bg)
            if alpha:
                data[o + 3] = 255 if (ax1 <= x < ax2 and ay1 <= y < ay2) else 0
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


def main():
    mod = load_plugin()
    images = []

    # ---- 注册 --------------------------------------------------------------
    section("过程注册")
    # 注意：这里**不能**自己 new 一个 Gimp.PlugIn 来问它 —— GimpPlugIn 构造时
    # 要求有 read channel，在 python-eval 里直接 new 会 abort 整个 GIMP。
    # 所以只查 PDB（也就是「真的装进 GIMP 并且被加载过」），没装就明说跳过。
    proc = Gimp.get_pdb().lookup_procedure(mod.PROC)
    src = open(os.path.join(REPO, "plugin", "puppet-warp",
                            "puppet-warp.py"), encoding="utf-8").read()
    if proc is None:
        print("  （%s 还没装进 GIMP，跳过 PDB 参数表；"
              "./install-plugin.sh 之后再跑就会检查）" % mod.PROC)
        check("源码里四个参数都在",
              all(('"%s"' % x) in src for x in
                  ("pins", "mode", "radius", "output")))
    else:
        args = [a.get_name() for a in proc.get_arguments()]
        for want in ("pins", "mode", "radius", "output"):
            check("参数 %s 在" % want, want in args, str(args))
        cfg0 = proc.create_config()
        check("默认变形方式是相似（保形）",
              cfg0.get_property("mode") == mod.MODE_SIMILARITY,
              cfg0.get_property("mode"))
        check("默认半径 30%", abs(cfg0.get_property("radius") - 30.0) < 0.01,
              cfg0.get_property("radius"))
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

    # ---- 变形本体 ----------------------------------------------------------
    section("变形：像素真的被搬走了")
    img, layer = make_image()
    images.append(img)
    before = pixels(layer)
    t0 = time.time()
    info = mod.warp_drawable(
        layer, [{"sx": 100, "sy": 75, "dx": 140, "dy": 75}],
        mode="similarity", radius=0.9, output=mod.OUTPUT_REPLACE)
    dt = time.time() - t0
    after = pixels(layer)
    check("返回了 info（%d 钉子 / 最大位移 %.0f px）"
          % (info["count"], info["max_shift"]),
          info["count"] == 1 and abs(info["max_shift"] - 40.0) < 0.01, info)
    check("方块中心搬到了新位置", px(after[2], after[0], 130, 75)[:3] ==
          (220, 40, 40), px(after[2], after[0], 130, 75))
    check("旧位置不再是方块", px(after[2], after[0], 60, 75)[:3] != (220, 40, 40),
          px(after[2], after[0], 60, 75))
    check("200×150 变形 < 2 s（%.2f s）" % dt, dt < 2.0, dt)
    check("图层尺寸没变", (after[0], after[1]) == (before[0], before[1]),
          (after[0], after[1]))

    # 进度条那一路：Gimp.progress_pulse 不收参数，而 warp_rgba 每行会调
    # progress(0..1)，直接传进去会 TypeError。插件里必须包一层。
    ticks = []
    img_t, layer_t = make_image()
    images.append(img_t)
    mod.warp_drawable(layer_t, [{"sx": 100, "sy": 75, "dx": 120, "dy": 75}],
                      mode="affine", radius=0.6,
                      on_tick=lambda: ticks.append(1))
    check("on_tick 被调用（进度条不会炸）", len(ticks) > 0, len(ticks))

    section("半径外一个字节都不动")
    img2, layer2 = make_image()
    images.append(img2)
    ref = pixels(layer2)
    mod.warp_drawable(layer2, [{"sx": 100, "sy": 75, "dx": 125, "dy": 75}],
                      mode="affine", radius=0.15, output=mod.OUTPUT_REPLACE)
    got = pixels(layer2)
    check("右下角（圈外）字节完全一致",
          px(got[2], got[0], 192, 142) == px(ref[2], ref[0], 192, 142),
          (px(got[2], got[0], 192, 142), px(ref[2], ref[0], 192, 142)))
    diff = sum(1 for a, b in zip(got[2], ref[2]) if a != b)
    check("圈内有变化（%d 个通道字节不同）" % diff, diff > 40, diff)
    # 圈外逐像素验收（+2 px 余量留给双线性取样的邻域）
    outside = 0
    leaked = 0
    for yy in range(got[1]):
        for xx in range(got[0]):
            if math.hypot(xx - 125.0, yy - 75.0) > 0.15 * 200 + 2:
                outside += 1
                if px(got[2], got[0], xx, yy) != px(ref[2], ref[0], xx, yy):
                    leaked += 1
    check("半径外 %d 个像素一字节没动" % outside, leaked == 0,
          "%d 个漏了" % leaked)

    section("守卫：没钉子 / 没拖动 / 坏图层")
    img3, layer3 = make_image()
    images.append(img3)
    try:
        mod.warp_drawable(layer3, [], radius=0.3)
        check("没钉子时抛错", False, "没抛")
    except RuntimeError as exc:
        check("没钉子时抛错", "pin" in str(exc).lower(), exc)
    try:
        mod.warp_drawable(layer3, [{"sx": 50, "sy": 50, "dx": 50, "dy": 50}],
                          radius=0.3)
        check("钉子没拖动时抛错", False, "没抛")
    except RuntimeError as exc:
        check("钉子没拖动时抛错", "dragged" in str(exc).lower(), exc)

    group = Gimp.GroupLayer.new(img3, "grp")
    img3.insert_layer(group, None, 0)
    try:
        mod.check_drawable(group)
        check("图层组被拦住", False, "没抛")
    except RuntimeError as exc:
        check("图层组被拦住", "group" in str(exc).lower(), exc)

    # 文字层在 gimp-console 里造不出来（字体资源没加载，font 要 GimpFont 对象），
    # 所以这条只能静态验：守卫里必须同时拦文字层和矢量层。
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
    section("alpha：透明区还是透明，形状不丢")
    img4, layer4 = make_image(alpha=True, alpha_box=(50, 40, 150, 110))
    images.append(img4)
    a_before = pixels(layer4)
    mod.warp_drawable(layer4, [{"sx": 100, "sy": 75, "dx": 120, "dy": 75}],
                      mode="similarity", radius=0.5,
                      output=mod.OUTPUT_REPLACE)
    a_after = pixels(layer4)
    check("图层仍然有 alpha", bool(layer4.has_alpha()))
    check("变形后新位置的 alpha 还是实心",
          px(a_after[2], a_after[0], 110, 75)[3] > 200,
          px(a_after[2], a_after[0], 110, 75)[3])
    check("画布角落仍然是透明的",
          px(a_after[2], a_after[0], 5, 5)[3] == 0,
          px(a_after[2], a_after[0], 5, 5)[3])

    section("没有 alpha 的图层：写回不能炸、也不能偷偷加通道")
    check("RGB 图层 has_alpha = False", not layer2.has_alpha())
    check("RGB 图层写完还是 3 通道（bpp）", layer2.get_bpp() == 3,
          layer2.get_bpp())
    check("RGB 图层写完仍无 alpha", not layer2.has_alpha())

    # ---- 输出方式 ----------------------------------------------------------
    section("输出到新图层：原图层要被保住")
    img5, layer5 = make_image()
    images.append(img5)
    keep = pixels(layer5)
    n_before = len(img5.get_layers())
    info5 = mod.warp_drawable(
        layer5, [{"sx": 100, "sy": 75, "dx": 130, "dy": 75}],
        mode="affine", radius=0.8, output=mod.OUTPUT_LAYER)
    check("多了一个图层", len(img5.get_layers()) == n_before + 1,
          "%d → %d" % (n_before, len(img5.get_layers())))
    check("原图层像素没被动过", pixels(layer5)[2] == keep[2])
    check("新图层名字带 (warped)", "(warped)" in info5["layer"].get_name(),
          info5["layer"].get_name())
    check("新图层里有搬过去的方块",
          px(pixels(info5["layer"])[2], 200, 120, 75)[:3] == (220, 40, 40),
          px(pixels(info5["layer"])[2], 200, 120, 75))

    # ---- 对话框（无头） ----------------------------------------------------
    section("对话框：能建、能预览、拖钉子会变")
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    img6, layer6 = make_image()
    images.append(img6)
    class FakeConfig(object):
        """对话框只用到 get_property，不必真的去建 GimpProcedureConfig。"""

        def __init__(self, **vals):
            self.vals = {"pins": "", "mode": mod.MODE_SIMILARITY,
                         "radius": 30.0, "output": mod.OUTPUT_REPLACE}
            self.vals.update(vals)

        def get_property(self, key):
            return self.vals.get(key)

    cfg = FakeConfig()
    try:
        dlg, ctx = mod.build_dialog(cfg, img6, layer6, 200, 150)
        check("建出对话框", dlg is not None)
        check("预览尺寸 = 图层尺寸（小图不放大）",
              (ctx["pw"], ctx["ph"]) == (200, 150), (ctx["pw"], ctx["ph"]))
        check("一开始没有钉子", ctx["pins"] == [])
        first = ctx["warped"]
        check("没钉子时预览就是原图", first == ctx["prgba"])

        ctx["pins"].append({"sx": 100.0, "sy": 75.0, "dx": 130.0, "dy": 75.0})
        ctx["render"]()
        check("拖了钉子之后预览变了", ctx["warped"] != first)
        note = ctx["note"].get_text()
        check("状态行没有报错", "failed" not in note, note[:70])
        check("状态行里有钉子数", "1" in note, note[:70])
        check("开网格时有网格线", ctx["mesh"] and len(ctx["mesh"]) == 22,
              len(ctx["mesh"]) if ctx["mesh"] else None)

        ctx["pins_mesh"].set_active(False)
        ctx["render"]()
        check("关网格后没有网格线", not ctx["mesh"])

        # 反复改半径/模式：每一次都必须能渲出来
        ok_all = True
        for radius in (5, 40, 100):
            ctx["s_radius"].set_value(radius)
            ctx["render"]()
            if "failed" in ctx["note"].get_text():
                ok_all = False
        check("半径 5/40/100 都能渲染", ok_all)
        ctx["combo_mode"].set_active_id(mod.MODE_AFFINE)
        ctx["render"]()
        check("切到仿射也能渲染", "failed" not in ctx["note"].get_text(),
              ctx["note"].get_text()[:70])

        vals = ctx["values"]()
        check("values() 带回钉子/模式/半径/输出",
              len(vals["pins"]) == 1 and vals["mode"] == mod.MODE_AFFINE
              and vals["radius"] == 100.0 and vals["output"] == mod.OUTPUT_REPLACE,
              vals)
        check("钉子字符串能被 format 出来",
              "100.00,75.00,130.00,75.00" in mod.WM.format_pin_string(
                  vals["pins"]))
        dlg.destroy()
    except Exception as exc:
        check("对话框能建出来", False, "%s: %s" % (type(exc).__name__, exc))

    # ---- 大图 --------------------------------------------------------------
    section("768×1024 走一遍完整流程")
    img7, layer7 = make_image(768, 1024, box=(300, 400, 500, 600))
    images.append(img7)
    t0 = time.time()
    info7 = mod.warp_drawable(
        layer7, [{"sx": 400, "sy": 500, "dx": 460, "dy": 540},
                 {"sx": 380, "sy": 460, "dx": 410, "dy": 470}],
        mode="similarity", radius=0.25, output=mod.OUTPUT_REPLACE)
    dt = time.time() - t0
    check("768×1024 全流程 < 6 s（%.2f s）" % dt, dt < 6.0, dt)
    got7 = pixels(layer7)
    check("两个钉子都算进去了", info7["count"] == 2 and info7["moved"] == 2,
          info7)

    # ---- ARAP --------------------------------------------------------------
    section("ARAP：真 GIMP 里能变形、对话框能切")
    if mod.arap_ok():
        img8, layer8 = make_image(240, 180, box=(80, 50, 160, 130))
        images.append(img8)
        ref8 = pixels(layer8)
        mod.warp_drawable(layer8, [{"sx": 120, "sy": 90, "dx": 148, "dy": 96}],
                          mode=mod.MODE_ARAP, output=mod.OUTPUT_REPLACE)
        got8 = pixels(layer8)
        ndiff = sum(1 for a, b in zip(got8[2], ref8[2]) if a != b)
        check("ARAP 真的搬了像素（%d 个通道字节）" % ndiff, ndiff > 300, ndiff)
        check("ARAP 左下角（远离钉子）没动",
              px(got8[2], got8[0], 3, got8[1] - 3) ==
              px(ref8[2], ref8[0], 3, ref8[1] - 3),
              (px(got8[2], got8[0], 3, got8[1] - 3),
               px(ref8[2], ref8[0], 3, ref8[1] - 3)))

        dlg8, ctx8 = mod.build_dialog(FakeConfig(mode=mod.MODE_ARAP),
                                      img8, layer8, 240, 180)
        check("对话框认 ARAP 这一档",
              ctx8["combo_mode"].get_active_id() == mod.MODE_ARAP,
              ctx8["combo_mode"].get_active_id())
        check("ARAP 时 Falloff 滑杆灰掉", not ctx8["s_radius"].get_sensitive())
        ctx8["pins"].append({"sx": 120.0, "sy": 90.0, "dx": 148.0, "dy": 96.0})
        ctx8["render"]()
        note8 = ctx8["note"].get_text()
        check("ARAP 预览没报错", "fail" not in note8.lower(), note8)
        check("状态行说明 falloff 不参与", "falloff not used" in note8, note8)
        ctx8["combo_mode"].set_active_id(mod.MODE_SIMILARITY)
        check("切回相似档滑杆恢复", ctx8["s_radius"].get_sensitive())
    else:
        print("  （numpy 没装，ARAP 不可用，跳过）")

    # ---- 非破坏 ------------------------------------------------------------
    section("非破坏：钉子挂在滤镜上，像素不动")
    imgf, layerf = make_image()
    images.append(imgf)
    beforef = pixels(layerf)
    pins_f = [{"sx": 100, "sy": 75, "dx": 140, "dy": 75}]
    filt, tgt = mod.apply_filter(layerf, pins_f, mode=mod.MODE_SIMILARITY,
                                 radius=90.0)
    check("挂完滤镜像素一个字节都没动", beforef == pixels(layerf))
    f_list = tgt.get_filters() if hasattr(tgt, 'get_filters') else []
    check("图层上多了一条 lb:puppet-warp",
          len(f_list) == 1 and
          f_list[0].get_operation_name() == mod.FILTER_OP,
          [x.get_operation_name() for x in f_list])
    st = mod.load_filter_state(tgt)
    check("重跑时能把钉子读回来",
          bool(st) and st['pins'].startswith("100.00,75.00"), st)
    check("模式与范围也读回来",
          bool(st) and st['mode'] == mod.MODE_SIMILARITY and
          abs(st['radius'] - 90.0) < 0.01, st)
    mod.apply_filter(tgt, [{"sx": 100, "sy": 75, "dx": 150, "dy": 75}],
                     mode=mod.MODE_SIMILARITY, radius=90.0)
    check("再应用一次是更新同一条，不叠加",
          len(tgt.get_filters()) == 1, len(tgt.get_filters()))

    # 滤镜渲染出来要和破坏性那条路对得上
    img9, layer9 = make_image()
    images.append(img9)
    mod.warp_drawable(layer9, [{"sx": 100, "sy": 75, "dx": 150, "dy": 75}],
                      mode=mod.MODE_SIMILARITY, radius=0.9,
                      output=mod.OUTPUT_REPLACE)
    ref9 = pixels(layer9)
    try:
        tgt.merge_filters()
        got9 = pixels(tgt)
        nd = sum(1 for a, b in zip(got9[2], ref9[2]) if a != b)
        big = sum(1 for a, b in zip(got9[2], ref9[2]) if abs(a - b) > 6)
        mx = max(abs(a - b) for a, b in zip(got9[2], ref9[2]))
        check("滤镜渲染 == 破坏性结果（%d 字节不同 / %d 超 6 级 / 最大 %d）"
              % (nd, big, mx), big == 0 and mx <= 6, (nd, big, mx))
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
