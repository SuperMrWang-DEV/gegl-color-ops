# -*- coding: utf-8 -*-
"""在真 GIMP 里跑抠图插件的回归（--batch 加载本文件）。

    gimp-console-3.2 -i -d -f --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_cutout_gimp.py').read())" --quit

测的是「蒙版真的落在像素上」这件事：临时图层缩放、select-item、图层蒙版、
背景层位置。这些在纯 Python 里测不到——写错一个参数，GIMP 不会报错，
只会给你一张全白或全黑的蒙版。
"""

import os
import sys
import tempfile

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl, Gio

ROOT = "C:/Users/Administrator/WorkBuddy/2026-11-10-21-12-59/SuperMrWang"
for cand in (ROOT, os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))):
    if os.path.exists(os.path.join(cand, "plugin", "cutout", "cutout.py")):
        ROOT = cand
        break
REPO, HERE = ROOT, os.path.join(ROOT, "tools")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "plugin", "_shared"))

import importlib.util

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
        "cutout_plugin", os.path.join(REPO, "plugin", "cutout", "cutout.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_image(w=400, h=300, fg=(220, 40, 40), bg=(250, 250, 250),
               box=(100, 60, 300, 240)):
    """白底 + 中间一块红方块：本地泛洪该把白底吃掉、留下红块。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(img, "photo", w, h, Gimp.ImageType.RGB_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    data = bytearray(w * h * 3)
    x1, y1, x2, y2 = box
    for y in range(h):
        for x in range(w):
            inside = x1 <= x < x2 and y1 <= y < y2
            c = fg if inside else bg
            o = (y * w + x) * 3
            data[o:o + 3] = bytes(c)
    layer.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B' u8",
                           bytes(data))
    layer.get_buffer().flush()
    return img, layer


def mask_at(layer, x, y):
    mask = layer.get_mask()
    if mask is None:
        return -1
    raw = mask.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                                "Y u8", Gegl.AbyssPolicy.NONE)
    return raw[0]


def mask_rect(layer, x, y, w, h):
    mask = layer.get_mask()
    if mask is None:
        return b""
    raw = mask.get_buffer().get(Gegl.Rectangle.new(x, y, w, h), 1.0,
                                "Y u8", Gegl.AbyssPolicy.NONE)
    return bytes(bytearray(raw))


def has_channel(img, name):
    for ch in img.get_channels():
        if ch.get_name() == name:
            return True
    return False


def layer_names(img):
    return [x.get_name() for x in img.get_layers()]


def main():
    mod = load_plugin()
    section("0. 加载")
    check("插件导入成功", mod is not None and mod.PROC_LOCAL.startswith("lb-"))
    check("两个过程名都有（本地 / AI）",
          mod.PROC_LOCAL and mod.PROC_AI and mod.PROC_LOCAL != mod.PROC_AI)


    images = []

    # ---- 1. 本地版：无选区，四边泛洪 ----
    section("1. 本地抠图（四边泛洪）")
    img, layer = make_image()
    images.append(img)
    out, info = mod.cutout_local(img, layer, threshold=0.05, shrink=0,
                                 feather=0.0, background="transparent")
    ok_mask = layer.get_mask() is not None
    check("图层拿到了蒙版", ok_mask)
    if ok_mask:
        inside = mask_rect(layer, 120, 80, 160, 140)
        check("主体内部全不透明", all(v > 250 for v in inside),
              "min=%s" % (min(inside) if inside else "?"))
        check("四角透明",
              all(mask_at(layer, x, y) == 0
                  for x, y in ((2, 2), (397, 2), (2, 297), (397, 297))),
              [mask_at(layer, x, y) for x, y in ((2, 2), (397, 2))])
        mask_size = layer.get_mask().get_width(), layer.get_mask().get_height()
        check("蒙版尺寸等于图层尺寸", mask_size == (400, 300), mask_size)
    check("存下了 Cutout Mask 通道", has_channel(img, "Cutout Mask"))
    check("背景=透明时不多加图层", len(img.get_layers()) == 1,
          layer_names(img))
    check("info 里记的次数是泛洪", info["used_selection"] is False, info)
    check("泛洪覆盖率被记下来", 0.5 < (info["border_coverage"] or 0) <= 1.0,
          info["border_coverage"])

    # ---- 2. 本地版：有选区 → 只收边 ----
    section("2. 本地抠图（已有选区）")
    img2, layer2 = make_image()
    images.append(img2)
    Gimp.get_pdb().lookup_procedure("gimp-image-select-rectangle").run(
        _cfg("gimp-image-select-rectangle", image=img2,
             operation=int(Gimp.ChannelOps.REPLACE), x=150, y=100,
             width=100, height=100))
    out2, info2 = mod.cutout_local(img2, layer2, shrink=0, feather=0.0)
    check("用了已有选区", info2["used_selection"] is True, info2)
    check("选区中心不透明", mask_at(layer2, 200, 150) > 250,
          mask_at(layer2, 200, 150))
    check("选区外透明", mask_at(layer2, 20, 20) == 0, mask_at(layer2, 20, 20))

    # ---- 3. 输出背景：纯色 ----
    section("3. 输出背景")
    img3, layer3 = make_image()
    images.append(img3)
    mod.cutout_local(img3, layer3, threshold=0.05, shrink=0, feather=0.0,
                     background="color", color=Gegl.Color.new("#00ff00"))
    names = layer_names(img3)
    check("多了一层背景层", len(names) == 2, names)
    check("背景层在照片下面",
          names.index("Background") > names.index("photo"), names)
    bg = [x for x in img3.get_layers() if x.get_name() == "Background"][0]
    px = bg.get_buffer().get(Gegl.Rectangle.new(5, 5, 1, 1), 1.0,
                             "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    check("背景色填对了（绿）", list(px[:3]) == [0, 255, 0], list(px[:3]))
    check("背景层盖满画布",
          (bg.get_width(), bg.get_height()) == (400, 300),
          (bg.get_width(), bg.get_height()))

    # ---- 4. 输出背景：图片（cover） ----
    section("4. 背景图 cover")
    img4, layer4 = make_image()
    images.append(img4)
    tmp_png = os.path.join(tempfile.mkdtemp(prefix="lb-cutout-"), "bg.png")
    import ai_client as AC
    sw, sh = 200, 100
    pixels = bytearray(sw * sh * 4)
    for i in range(sw * sh):
        pixels[i * 4:i * 4 + 4] = bytes((10, 20, 200, 255))
    with open(tmp_png, "wb") as fh:
        fh.write(AC.rgba_png(sw, sh, bytes(pixels)))
    mod.cutout_local(img4, layer4, threshold=0.05, shrink=0, feather=0.0,
                     background="image",
                     bgfile=Gio.File.new_for_path(tmp_png))
    names = layer_names(img4)
    check("背景图被加进来了", "Background" in names, names)
    bg4 = [x for x in img4.get_layers() if x.get_name() == "Background"]
    if bg4:
        bg4 = bg4[0]
        # 200×100 铺满 400×300：取较大的系数 3 → 600×300，左右各裁 100
        check("cover 后盖满画布（600×300）",
              (bg4.get_width(), bg4.get_height()) == (600, 300),
              (bg4.get_width(), bg4.get_height()))
        check("居中裁切：offset_x = -100, offset_y = 0",
              (bg4.get_offsets()[1], bg4.get_offsets()[2]) == (-100, 0),
              bg4.get_offsets())
        check("背景图在照片下面", names.index("Background") > names.index("photo"))

    # ---- 5. AI 版：走 mock ComfyUI ----
    section("5. AI 抠图（mock）")
    import mock_comfy
    srv = mock_comfy.start_mock()
    try:
        client = AC.ComfyClient(srv.url, timeout=10)
        img5, layer5 = make_image()
        images.append(img5)
        out5, info5 = mod.cutout_ai(img5, layer5, client=client,
                                    model="RMBG-2.0", resolution=512,
                                    shrink=0, feather=0.0,
                                    background="transparent")
        check("AI 版拿到了蒙版", layer5.get_mask() is not None)
        if layer5.get_mask() is not None:
            left = mask_rect(layer5, 0, 10, 100, 20)
            right = mask_rect(layer5, 300, 10, 100, 20)
            check("左侧（mock 判成背景）透明", max(left) == 0, max(left))
            check("右侧（mock 判成主体）不透明", min(right) > 250, min(right))
        check("记录了模型与前景占比",
              info5["model"] == "RMBG-2.0" and 0.2 < info5["foreground"] < 0.8,
              (info5["model"], info5["foreground"]))
        check("AI 版也存了 Cutout Mask 通道", has_channel(img5, "Cutout Mask"))
        check("AI 版没有留下临时图层", len(img5.get_layers()) == 1,
              layer_names(img5))
    finally:
        srv.stop()

    # ---- 6. 失败路径 ----
    section("6. 失败路径")
    img6, layer6 = make_image(bg=(250, 250, 250), box=(0, 0, 400, 300))
    images.append(img6)
    try:
        mod.cutout_local(img6, layer6, threshold=0.02, shrink=0, feather=0.0)
        check("整张都是一个色时应该报错", False, "no exception")
    except RuntimeError as exc:
        msg = str(exc)
        check("报错提示调阈值或换 AI 版",
              "threshold" in msg.lower() and "AI" in msg, msg[:80])
    check("失败后没有留下蒙版", layer6.get_mask() is None)
    sel6 = img6.get_selection()
    ok_bounds = sel6.bounds(img6) if sel6 is not None else None
    check("失败后也把选区清干净了",
          sel6 is None or not ok_bounds[1], ok_bounds)

    # ---- 7. run() 这一层：参数名和转发对不对 ----
    section("7. 过程 run() 的胶水")
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

    img7, layer7 = make_image()
    images.append(img7)
    st, _err = mod.CutoutPlugin.run(
        object(), _FakeProc(mod.PROC_LOCAL), Gimp.RunMode.NONINTERACTIVE,
        img7, [layer7],
        _FakeCfg({"threshold": 0.05, "seeds": 5, "use-selection": False,
                  "shrink": 0, "feather": 0.0, "keep-mask": True,
                  "background": "color", "color": Gegl.Color.new("#ffffff"),
                  "bg-file": None}), None)
    check("本地版 run() 能跑通（参数名没写错）",
          st == Gimp.PDBStatusType.SUCCESS, st)
    check("run() 之后蒙版和背景都在",
          layer7.get_mask() is not None and len(img7.get_layers()) == 2,
          layer_names(img7))

    # AI 版：把 cutout_ai 换成假的，只验 run() 的取参与返回
    seen = []
    orig_ai = mod.cutout_ai
    def fake_ai(image, drawable, **kw):
        seen.append(kw)
        return drawable, {"model": "RMBG-2.0", "seconds": 1.0,
                          "foreground": 0.5, "background": "transparent"}
    mod.cutout_ai = fake_ai
    try:
        img8, layer8 = make_image()
        images.append(img8)
        st8, _e8 = mod.CutoutPlugin.run(
            object(), _FakeProc(mod.PROC_AI), Gimp.RunMode.NONINTERACTIVE,
            img8, [layer8],
            _FakeCfg({"model": "RMBG-2.0", "resolution": 1024,
                      "sensitivity": 1.0, "refine": True, "shrink": 1,
                      "feather": 1.5, "background": "transparent",
                      "color": None, "bg-file": None, "keep-mask": True}),
            None)
        check("AI 版 run() 能跑通", st8 == Gimp.PDBStatusType.SUCCESS, st8)
        check("run() 把 resolution 递给实现",
              seen and seen[0].get("resolution") == 1024, seen[:1])
        check("run() 把背景参数递给实现",
              seen and seen[0].get("background") == "transparent", seen[:1])
    finally:
        mod.cutout_ai = orig_ai

    for im in images:
        im.delete()

    print("\n" + ("全部通过（%d 条断言）" % PASS if not FAIL
                  else "失败 %d / %d：%s"
                  % (len(FAIL), PASS + len(FAIL), ", ".join(FAIL))))


def _cfg(proc_name, **props):
    proc = Gimp.get_pdb().lookup_procedure(proc_name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return cfg


main()
