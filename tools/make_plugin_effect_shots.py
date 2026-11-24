# -*- coding: utf-8 -*-
"""零参数插件（convert / luminosity / observe）的插图：原图 → 结果 对比条。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/make_plugin_effect_shots.py').read())" --quit

这三支点菜单直接跑，没有参数框（`run_dialog` 遇到零参数就不弹），所以
截对话框只能拿到一个纯按钮的空壳。改成和算子页一样的对比条：

  observe   → 顶部多一层去色副本，画面按明度看结构
  luminosity→ 生成一组明度蒙版，取其中一张（Lights 1）当结果
  convert   → 选区转通道，得到黑白通道

结果一律 950×323（两格 460×307），和 ops/*/assets/shot.png 同规格。
写到 tools/site/plugin-shots/<slug>/shot.png（docs/ 每次构建都会清空）。
"""
import importlib.util
import json
import locale
import os
import sys

for _loc in ("Chinese_China.936", "zh_CN.UTF-8", "zh_CN"):
    try:
        locale.setlocale(locale.LC_ALL, _loc)
        break
    except locale.Error:
        continue

import cairo
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, Gio

ROOT = os.environ.get("LB_REPO") or \
    r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
OUTDIR = os.path.join(ROOT, "tools", "site", "plugin-shots")
TMP = os.path.join(ROOT, "tools", "_shots")
CARD = os.path.join(ROOT, "tools", "_testcard.png")
CELL_W, CELL_H = 460, 307
GAP, PAD = 14, 8

sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))
for _d in ("observe", "luminosity-mask", "convert"):
    sys.path.insert(0, os.path.join(ROOT, "plugin", _d))


def load(name, sub):
    p = os.path.join(ROOT, "plugin", sub, "%s.py" % sub)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def new_image():
    img = Gimp.Image.new(960, 640, Gimp.ImageBaseType.RGB)
    layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, img,
                                 Gio.File.new_for_path(CARD))
    img.insert_layer(layer, None, 0)
    return img, layer


def write_rgba_png(rgba, w, h, path):
    buf = bytearray(w * h * 4)
    for i in range(w * h):
        r, g, b = rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2]
        o = i * 4
        buf[o], buf[o + 1], buf[o + 2], buf[o + 3] = b, g, r, 255
    surf = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, w, h)
    surf.write_to_png(path)


def write_gray_png(gray, w, h, path):
    buf = bytearray(w * h * 4)
    for i, v in enumerate(gray):
        o = i * 4
        buf[o] = buf[o + 1] = buf[o + 2] = v
        buf[o + 3] = 255
    surf = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, w, h)
    surf.write_to_png(path)


def draw_cell(cr, path, x, y):
    src = cairo.ImageSurface.create_from_png(path)
    sw, sh = src.get_width(), src.get_height()
    cr.save()
    cr.rectangle(x, y, CELL_W, CELL_H)
    cr.clip()
    cr.translate(x, y)
    cr.scale(float(CELL_W) / sw, float(CELL_H) / sh)
    cr.set_source_surface(src, 0, 0)
    cr.paint()
    cr.restore()


def tag(cr, x, y, text):
    cr.select_font_face("Microsoft YaHei", cairo.FONT_SLANT_NORMAL,
                        cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(11)
    ext = cr.text_extents(text)
    bw, bh = ext.width + 10, ext.height + 7
    cr.set_source_rgba(0, 0, 0, 0.55)
    cr.rectangle(x, y, bw, bh)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.move_to(x + 5, y + bh - 4)
    cr.show_text(text)


def compose(orig, res, out, bg=(0.09, 0.09, 0.11)):
    w = CELL_W * 2 + GAP + PAD * 2
    h = CELL_H + PAD * 2
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*bg)
    cr.paint()
    draw_cell(cr, orig, PAD, PAD)
    draw_cell(cr, res, PAD + CELL_W + GAP, PAD)
    tag(cr, PAD + 6, PAD + 6, "Original")
    tag(cr, PAD + CELL_W + GAP + 6, PAD + 6, "Result")
    surface.write_to_png(out)
    return w, h


def rgba_of(layer):
    import mask_io as MI
    return MI.read_drawable_rgba(layer, 100000)


def main():
    import mask_io as MI
    os.makedirs(TMP, exist_ok=True)
    obs_mod = load("lb_obs_eff", "observe")
    lum_mod = load("lb_lum_eff", "luminosity-mask")
    conv_mod = load("lb_conv_eff", "convert")

    meta = {}

    def emit(slug, tzh, ten, res_png, zh, en):
        d = os.path.join(OUTDIR, slug)
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "shot.png")
        w, h = compose(CARD, res_png, out)
        print("OK   %-14s %4dx%-4d" % (slug, w, h))
        meta[slug] = {"zh": zh, "en": en, "w": w, "h": h, "title": tzh, "kind": "effect"}

    # ---- observe：黑白观察层
    img, layer = new_image()
    lay = obs_mod.make_observer(img, layer, obs_mod.observe_grey, "Black & White")
    # get_buffer() 读的是图层源像素，不含未合并的滤镜；先合并再读
    try:
        for f in lay.get_filters():
            lay.merge_filter(f)
    except Exception as exc:
        print("merge_filter:", exc)
    rw, rh, rgba = rgba_of(lay)
    p = os.path.join(TMP, "observe.png")
    write_rgba_png(rgba, rw, rh, p)
    emit("observe", "观察层", "Observe", p,
         "顶部加一层去色副本，结构和脏点在纯明暗下最清楚",
         "a desaturated copy on top; structure and blemishes read as pure brightness")
    img.delete()

    # ---- luminosity：明度蒙版（取 Lights 1）
    img, layer = new_image()
    lum_mod.create_masks(img, layer)
    chan = None
    for c in img.get_channels():
        if "Lights 1" in c.get_name() or "亮部 1" in c.get_name():
            chan = c
            break
    if chan is None:
        chans = img.get_channels()
        chan = chans[0] if chans else None
    if chan is None:
        raise SystemExit("luminosity: 没有生成通道")
    cw, ch, gray = MI.read_channel(chan, 100000)
    p = os.path.join(TMP, "luminosity.png")
    write_gray_png(gray, cw, ch, p)
    emit("luminosity", "明度蒙版", "Luminosity Masks", p,
         "一次生成八条明度蒙版，这里显示其中的 Lights 1",
         "eight luminance masks in one go; Lights 1 is shown here")
    img.delete()

    # ---- convert：选区 → 通道
    img, layer = new_image()
    img.select_ellipse(Gimp.ChannelOps.REPLACE, 370, 120, 320, 380)
    chan = conv_mod.selection_to_channel(img)
    cw, ch, gray = MI.read_channel(chan, 100000)
    p = os.path.join(TMP, "convert.png")
    write_gray_png(gray, cw, ch, p)
    emit("convert", "转换", "Convert", p,
         "选区转通道：圆选区变成一条黑白通道",
         "selection to channel: the round selection becomes a black-and-white channel")
    img.delete()

    jp = os.path.join(ROOT, "tools", "site", "plugin_shots.json")
    old = {}
    if os.path.exists(jp):
        try:
            old = json.load(open(jp, encoding="utf-8"))
        except Exception:
            old = {}
    old.update(meta)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("\n对比条 %d 张" % len(meta))


main()
