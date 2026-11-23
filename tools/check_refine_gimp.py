# -*- coding: utf-8 -*-
"""在真 GIMP 里跑「选择并遮住」的回归（--batch 加载本文件）。

    gimp-console-3.2 -i -d -f --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_refine_gimp.py').read())" --quit

纯 Python 那套（check_refine.py）验的是数学；这里验的是**接线**：
选区 ↔ 通道的 gamma 转换对不对、缩放回画布有没有错位、蒙版真不真的落在
像素上、去色边有没有把颜色改回前景色。这些写错了 GIMP 一声不响，
只会给你一张全白或者糊掉的蒙版。
"""

import os
import sys

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
for cand in (ROOT, os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))):
    if os.path.exists(os.path.join(cand, "plugin", "refine-mask", "refine-mask.py")):
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
        "refine_plugin", os.path.join(REPO, "plugin", "refine-mask",
                                      "refine-mask.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pdb(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def make_image(w=200, h=150, fg=(220, 40, 40), bg=(250, 250, 250),
               box=(50, 40, 150, 110), soft=0):
    """白底 + 中间一块红方块。soft>0 时左右两侧做成混色渐变——
    真实照片的边缘本来就是「红混白」，去色边要修的就是这一圈。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(img, "photo", w, h, Gimp.ImageType.RGB_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    data = bytearray(w * h * 3)
    x1, y1, x2, y2 = box
    for y in range(h):
        for x in range(w):
            if soft and y1 <= y < y2 and (x1 - soft) <= x < (x1 + soft):
                t = (x - (x1 - soft)) / float(2 * soft)
                c = tuple(int(round(bg[i] + (fg[i] - bg[i]) * t))
                          for i in range(3))
            elif soft and y1 <= y < y2 and (x2 - soft) <= x < (x2 + soft):
                t = (x - (x2 - soft)) / float(2 * soft)
                c = tuple(int(round(fg[i] + (bg[i] - fg[i]) * t))
                          for i in range(3))
            else:
                c = fg if (x1 <= x < x2 and y1 <= y < y2) else bg
            o = (y * w + x) * 3
            data[o:o + 3] = bytes(c)
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B' u8", bytes(data))
    buf.flush()
    return img, layer


def select_box(img, x1, y1, x2, y2, feather=0.0):
    pdb('gimp-selection-none', image=img)
    pdb('gimp-image-select-rectangle', image=img,
        operation=int(Gimp.ChannelOps.REPLACE),
        x=x1, y=y1, width=x2 - x1, height=y2 - y1)
    if feather:
        pdb('gimp-selection-feather', image=img, radius=float(feather))


def sel_vals(img, pts):
    sel = img.get_selection()
    if sel is None:
        return [0] * len(pts)
    return [sel.value(img, x, y) for (x, y) in pts]


def layer_alpha_at(layer, x, y):
    raw = layer.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                                 "A u8", Gegl.AbyssPolicy.NONE)
    return bytes(bytearray(raw))[0]


def layer_rgb_at(layer, x, y):
    raw = layer.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                                 "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    return tuple(bytes(bytearray(raw))[:3])


def soft_count(mask):
    return sum(1 for v in mask if 0 < v < 255)


def main():
    mod = load_plugin()
    MI = mod.MI
    images = []

    # ---- 1. 选区 → 蒙版（gamma 转换） ----
    section("1. 选区 ↔ 蒙版 的往返")
    img, layer = make_image()
    images.append(img)
    select_box(img, 50, 40, 150, 110, feather=6.0)
    pts = [(40, 75), (50, 75), (48, 75), (60, 75), (100, 75), (152, 75), (170, 75)]
    before_sel = sel_vals(img, pts)
    w, h, mask, source = MI.current_mask(img, 0)
    check("读到的尺寸等于画布", (w, h) == (200, 150), (w, h))
    check("来源标成 selection", source == "selection", source)
    check("蒙版尺寸对", len(mask) == 200 * 150, len(mask))
    check("主体内是 255", mask[75 * 200 + 100] == 255, mask[75 * 200 + 100])
    check("主体外是 0", mask[75 * 200 + 5] == 0, mask[75 * 200 + 5])
    # 这就是 gamma 那条：通道读回来是线性的，不转的话这里的软边会整体偏暗
    got = [mask[y * 200 + x] for (x, y) in pts]
    diffs = [abs(a - b) for a, b in zip(got, before_sel)]
    check("软边与选区值一致（通道是线性的，必须转）", max(diffs) <= 3,
          list(zip(got, before_sel)))
    check("软边确实存在（不是全 0/255）", soft_count(mask) > 50,
          soft_count(mask))

    # ---- 2. 全零参数 = 恒等 ----
    section("2. 全零参数应当什么都不改")
    info = mod.refine_selection(img, layer, radius=0, smooth=0, feather=0,
                                contrast=0, shift=0, decontaminate=0,
                                output=mod.OUTPUT_SELECTION, work_size=0)
    after_sel = sel_vals(img, pts)
    check("选区值没变（±2）",
          max(abs(a - b) for a, b in zip(after_sel, before_sel)) <= 2,
          list(zip(after_sel, before_sel)))
    check("info 报告的是同一张蒙版",
          info["before"]["soft"] == info["after"]["soft"], info["after"])

    # ---- 3. 对比度 / 移动边缘 ----
    section("3. 对比度与移动边缘")
    img3, layer3 = make_image()
    images.append(img3)
    select_box(img3, 50, 40, 150, 110, feather=8.0)
    mod.refine_selection(img3, layer3, smooth=0, feather=0, contrast=0,
                         shift=0, output=mod.OUTPUT_SELECTION, work_size=0)
    _w, _h, soft0, _s = MI.current_mask(img3, 0)
    mod.refine_selection(img3, layer3, smooth=0, feather=0, contrast=100,
                         shift=0, output=mod.OUTPUT_SELECTION, work_size=0)
    _w, _h, soft1, _s = MI.current_mask(img3, 0)
    check("对比度 100 把软边压窄", soft_count(soft1) < soft_count(soft0),
          (soft_count(soft0), soft_count(soft1)))

    img3b, layer3b = make_image()
    images.append(img3b)
    select_box(img3b, 50, 40, 150, 110, feather=4.0)
    _w, _h, base_mask, _s = MI.current_mask(img3b, 0)
    base_area = sum(1 for v in base_mask if v > 127)
    mod.refine_selection(img3b, layer3b, smooth=0, feather=0, contrast=0,
                         shift=40, output=mod.OUTPUT_SELECTION, work_size=0)
    _w, _h, grown, _s = MI.current_mask(img3b, 0)
    grown_area = sum(1 for v in grown if v > 127)
    check("移动边缘 +40 让选区变大", grown_area > base_area,
          (base_area, grown_area))

    # ---- 4. 三种输出 ----
    section("4. 输出：图层蒙版 / 新图层 / 通道")
    img4, layer4 = make_image()
    images.append(img4)
    select_box(img4, 50, 40, 150, 110, feather=4.0)
    mod.refine_selection(img4, layer4, smooth=1, feather=1, contrast=20,
                         output=mod.OUTPUT_MASK, work_size=0)
    check("图层蒙版挂上了", layer4.get_mask() is not None)
    if layer4.get_mask() is not None:
        check("蒙版尺寸等于图层",
              (layer4.get_mask().get_width(), layer4.get_mask().get_height())
              == (200, 150))
        raw = layer4.get_mask().get_buffer().get(
            Gegl.Rectangle.new(100, 75, 1, 1), 1.0, "Y u8", Gegl.AbyssPolicy.NONE)
        check("蒙版主体处是白的", bytes(bytearray(raw))[0] > 240,
              bytes(bytearray(raw))[0])
    check("加完蒙版把选区清掉了", MI.has_selection(img4) is False)

    img5, layer5 = make_image()
    images.append(img5)
    select_box(img5, 50, 40, 150, 110, feather=4.0)
    n_before = len(img5.get_layers())
    info5 = mod.refine_selection(img5, layer5, smooth=1, feather=1,
                                 contrast=20, output=mod.OUTPUT_LAYER,
                                 work_size=0)
    check("多了一层", len(img5.get_layers()) == n_before + 1,
          len(img5.get_layers()))
    new_layer = info5.get("layer")
    check("返回了新图层对象", new_layer is not None)
    if new_layer is not None:
        check("主体处不透明", layer_alpha_at(new_layer, 100, 75) == 255,
              layer_alpha_at(new_layer, 100, 75))
        check("背景处透明", layer_alpha_at(new_layer, 5, 5) == 0,
              layer_alpha_at(new_layer, 5, 5))
        check("新图层在照片上面",
              img5.get_item_position(new_layer) < img5.get_item_position(layer5),
              (img5.get_item_position(new_layer),
               img5.get_item_position(layer5)))

    img6, layer6 = make_image()
    images.append(img6)
    select_box(img6, 50, 40, 150, 110, feather=4.0)
    mod.refine_selection(img6, layer6, smooth=1, feather=1, contrast=20,
                         output=mod.OUTPUT_CHANNEL, work_size=0)
    names = [c.get_name() for c in img6.get_channels()]
    check("写了 Refined Mask 通道", "Refined Mask" in names, names)
    check("通道输出后选区还在", MI.has_selection(img6) is True)
    pdb('gimp-selection-none', image=img6)
    check("清掉选区后，通道能被 current_mask 认出来（下次还能接着修）",
          MI.current_mask(img6, 0)[3] == "Refined Mask",
          MI.current_mask(img6, 0)[3])

    # ---- 5. 去色边 ----
    section("5. 去色边（边缘像素要回到前景色）")
    img7, layer7 = make_image(fg=(220, 40, 40), bg=(250, 250, 250), soft=4)
    images.append(img7)
    # 硬选区 + 羽化 → 边界上有一圈「红混白」的浅红像素
    select_box(img7, 50, 40, 150, 110, feather=5.0)
    mod.refine_selection(img7, layer7, smooth=0, feather=0, contrast=0,
                         shift=0, decontaminate=0, output=mod.OUTPUT_LAYER,
                         work_size=0)
    plain = img7.get_layers()[0]
    edge_plain = layer_rgb_at(plain, 49, 75)
    check("羽化边上确实是浅红（绿通道被白底抬起来了）",
          edge_plain[1] > 90, edge_plain)

    img8, layer8 = make_image(fg=(220, 40, 40), bg=(250, 250, 250), soft=4)
    images.append(img8)
    select_box(img8, 50, 40, 150, 110, feather=5.0)
    info8 = mod.refine_selection(img8, layer8, smooth=0, feather=0,
                                 contrast=0, shift=0, decontaminate=100,
                                 output=mod.OUTPUT_LAYER, work_size=0)
    check("报告处理了边缘像素", (info8.get("decontaminated") or 0) > 0,
          info8.get("decontaminated"))
    fixed = img8.get_layers()[0]
    edge_fixed = layer_rgb_at(fixed, 49, 75)
    check("边缘像素被拉回前景红（绿通道降下来）",
          edge_fixed[1] < edge_plain[1] - 20, (edge_plain, edge_fixed))
    check("主体内部不受影响",
          abs(layer_rgb_at(fixed, 100, 75)[1] - 40) <= 2,
          layer_rgb_at(fixed, 100, 75))
    check("背景不受影响",
          abs(layer_rgb_at(fixed, 5, 5)[0] - 250) <= 2,
          layer_rgb_at(fixed, 5, 5))

    # ---- 6. 工作尺寸缩放 ----
    section("6. 工作尺寸（蒙版缩放回画布）")
    img9, layer9 = make_image(400, 300, box=(100, 60, 300, 240))
    images.append(img9)
    select_box(img9, 100, 60, 300, 240, feather=3.0)
    info9 = mod.refine_selection(img9, layer9, smooth=1, feather=1,
                                 contrast=20, output=mod.OUTPUT_SELECTION,
                                 work_size=100)
    check("工作尺寸按长边缩到 100", info9["work"] == (100, 75), info9["work"])
    sel = sel_vals(img9, [(200, 150), (20, 20)])
    check("缩放回画布后主体内仍然是实心", sel[0] > 240, sel[0])
    check("缩放回画布后背景仍然是空", sel[1] < 10, sel[1])
    scan = sel_vals(img9, [(x, 150) for x in range(88, 116)])
    cross = next((88 + i for i, v in enumerate(scan) if v >= 128), None)
    check("边界位置没跑（100±6）", cross is not None and abs(cross - 100) <= 6,
          cross)

    # ---- 7. 没有选区也没有通道 ----
    section("7. 没有蒙版来源时的提示")
    img10, layer10 = make_image()
    images.append(img10)
    pdb('gimp-selection-none', image=img10)
    try:
        MI.current_mask(img10, 0)
        check("应当报错", False)
    except RuntimeError as exc:
        check("报错说要先做选区", "Make a selection" in str(exc)
              or "selection" in str(exc), str(exc)[:70])

    # ---- 8. run() 胶水 ----
    section("8. 过程 run() 的取参与返回")
    class _FakeProc(object):
        def __init__(self, name):
            self._name = name
        def get_name(self):
            return self._name
        def new_return_values(self, status, err):
            return (status, err)

    class _FakeCfg(object):
        def __init__(self, d):
            self._d = d
        def get_property(self, key):
            return self._d.get(key)

    img11, layer11 = make_image()
    images.append(img11)
    select_box(img11, 50, 40, 150, 110, feather=4.0)
    cfg = _FakeCfg({"radius": 0.0, "smart": True, "smooth": 1.0, "feather": 1.0,
                    "contrast": 20.0, "shift": 0.0, "decontaminate": 0.0,
                    "output": mod.OUTPUT_MASK, "work-size": 0})
    st, _err = mod.RefineMaskPlugin.run(
        object(), _FakeProc(mod.PROC), Gimp.RunMode.NONINTERACTIVE,
        img11, [layer11], cfg, None)
    check("run() 能跑通（参数名没写错）", st == Gimp.PDBStatusType.SUCCESS, st)
    check("run() 之后蒙版挂上了", layer11.get_mask() is not None)

    # ---- 9. 过程注册 ----
    section("9. 注册")
    proc = Gimp.get_pdb().lookup_procedure(mod.PROC)
    check("过程注册在 PDB 里（装进 GIMP 后会出现在菜单）", proc is not None,
          mod.PROC)
    if proc is not None:
        cfg2 = proc.create_config()
        names = [p.name for p in cfg2.list_properties()]
        for key in ("radius", "smart", "smooth", "feather", "contrast",
                    "shift", "decontaminate", "output", "work-size"):
            check("参数 %s 存在" % key, key in names, names)

    # ---- 9b. 两个守卫 ----
    section("9b. 守卫：已有蒙版 / 图层组")
    img13, layer13 = make_image()
    images.append(img13)
    select_box(img13, 50, 40, 150, 110, feather=4.0)
    mod.refine_selection(img13, layer13, smooth=0, feather=0, contrast=0,
                         output=mod.OUTPUT_MASK, work_size=0)
    select_box(img13, 50, 40, 150, 110, feather=4.0)   # 上一轮把选区清掉了
    try:
        mod.refine_selection(img13, layer13, smooth=0, feather=0, contrast=0,
                             output=mod.OUTPUT_MASK, work_size=0)
        check("已有蒙版时不默默覆盖", False)
    except RuntimeError as exc:
        check("已有蒙版时明确报错（不悄悄覆盖旧蒙版）",
              "already has a mask" in str(exc), str(exc)[:60])
    check("报错之后旧蒙版还在", layer13.get_mask() is not None)

    # ---- 10. 对话框与实时预览 ----
    section("10. 对话框与实时预览（不弹窗，直接建 + 渲染）")

    class _Cfg(object):
        def __init__(self, d=None):
            self.d = dict(d or {})
        def get_property(self, key):
            return self.d.get(key)
        def set_property(self, key, value):
            self.d[key] = value

    img12, layer12 = make_image(300, 240, soft=4, box=(80, 50, 220, 190))
    images.append(img12)
    select_box(img12, 80, 50, 220, 190, feather=6.0)
    w12, h12, mask12, _s12 = MI.current_mask(img12, 0)
    try:
        dlg, ctx = mod.build_dialog(_Cfg({"radius": 0.0, "smart": True,
                                          "smooth": 1.0, "feather": 1.0,
                                          "contrast": 10.0, "shift": 0.0,
                                          "decontaminate": 0.0,
                                          "output": mod.OUTPUT_MASK}),
                                    img12, layer12, w12, h12, mask12)
        check("对话框能建出来", dlg is not None)
        check("预览有像素",
              ctx["preview"].get_pixbuf() is not None
              and ctx["preview"].get_pixbuf().get_width() > 0,
              ctx["preview"].get_pixbuf().get_width()
              if ctx["preview"].get_pixbuf() else None)
        check("状态行报的是预览而不是错误",
              "Preview" in ctx["note"].get_text(), ctx["note"].get_text()[:60])
        first = ctx["preview"].get_pixbuf().get_pixels()

        # 拖滑杆（羽化 1 → 12），重渲染，像素必须变
        ctx["scales"][2].set_value(12.0)
        ctx["render"]()
        check("改羽化后预览重算了",
              ctx["preview"].get_pixbuf().get_pixels() != first)
        check("重算没有报错", "failed" not in ctx["note"].get_text(),
              ctx["note"].get_text()[:60])

        # 切到红蒙版看片方式
        ctx["buttons"]["red"].set_active(True)
        ctx["render"]()
        check("红蒙版模式也能渲染",
              "failed" not in ctx["note"].get_text(),
              ctx["note"].get_text()[:60])
        dlg.destroy()
    except Exception as exc:
        check("对话框能建出来", False, "%s: %s" % (type(exc).__name__, exc))

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
