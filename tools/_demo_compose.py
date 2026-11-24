# -*- coding: utf-8 -*-
"""把演示结果拼成前后对比图：左原图 / 右结果，同一缩放比例。

    gimp-console-3.2.exe -i -c -d -f --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/_demo_compose.py', encoding='utf-8').read())" --quit
"""

import os

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gio, Gegl

OUTDIR = r"D:/ComfyUI/test-out"
MAXDIM = 720
GAP = 12

try:
    Gimp.context_set_background(Gegl.Color.new("#111114"))
    BG = Gimp.FillType.BACKGROUND
except Exception:
    BG = Gimp.FillType.WHITE


def png_size(path):
    with open(path, "rb") as fh:
        head = fh.read(33)
    return (int.from_bytes(head[16:20], "big"),
            int.from_bytes(head[20:24], "big"))


def save(img, name):
    out = os.path.join(OUTDIR, name)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(out), None)
    print("  已导出", out)
    return out


def panel(path, crop=None, out_w=None, out_h=None):
    """裁剪 crop 并缩放到 out_w×out_h，返回临时 PNG 路径。

    没有 crop 时直接返回原路径 —— 缩放由 compose() 里的 layer.scale 做，
    别在 1×1 画布上 flatten 再放大，那样只会得到一块纯色。
    """
    if crop is None:
        return path
    cx, cy, cw, ch = crop
    path_c = os.path.join(OUTDIR, "_panel-%d.png" % panel.n)
    panel.n += 1
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                         Gio.File.new_for_path(path))
    img.resize(cw, ch, -cx, -cy)   # 负偏移 = 把画布原点挪到 (cx,cy)
    img.flatten()
    if out_w and out_h:
        img.scale(int(out_w), int(out_h))
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img,
                   Gio.File.new_for_path(path_c), None)
    img.delete()
    return path_c


panel.n = 0


def compose(panels, name):
    """panels: [(path, crop, out_w, out_h)]，同一比例，顶部对齐。"""
    built = [(panel(p, c, w, h), (w, h)) for (p, c, w, h) in panels]
    W = sum(w for _, (w, _) in built) + GAP * (len(built) - 1)
    H = max(h for _, (_, h) in built)
    canvas = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    base = Gimp.Layer.new(canvas, "bg", W, H, Gimp.ImageType.RGB_IMAGE, 100,
                          Gimp.LayerMode.NORMAL)
    canvas.insert_layer(base, None, 0)
    try:
        base.fill(BG)
    except Exception:
        pass
    x = 0
    for path, (w, h) in built:
        layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, canvas,
                                     Gio.File.new_for_path(path))
        canvas.insert_layer(layer, None, 0)
        if (layer.get_width(), layer.get_height()) != (w, h):
            layer.scale(w, h, False)
        layer.set_offsets(x, 0)
        x += w + GAP
    out = save(canvas, "cmp-%s.png" % name)
    canvas.delete()
    return out


def scaled(w, h, maxdim=MAXDIM):
    s = float(maxdim) / max(w, h)
    return max(1, int(round(w * s))), max(1, int(round(h * s)))


SRC = r"D:/ComfyUI/ComfyUI/input/lb-img2img-src.png"

jobs = [("expand-h", "expand-h"), ("expand-v", "expand-v"),
        ("expand-all", "expand-all"), ("upscale-2x", "upscale-2x"),
        ("expand-all-f72", "expand-all-f72"),
        ("expand-all-hard", "expand-all-hard"),
        ("expand-h-hard", "expand-h-hard"),
        ("expand-v-hard", "expand-v-hard"),
        ("expand-all-hard2", "expand-all-hard2")]
for out_tag, res in jobs:
    stem = res.replace("-f72", "")
    before = SRC if not stem.startswith("upscale") else \
        os.path.join(OUTDIR, "demo-%s-src.png" % stem)
    after = os.path.join(OUTDIR, "demo-%s.png" % res)
    if not os.path.exists(after):
        print("跳过（缺文件）", after)
        continue
    bw, bh = png_size(before)
    aw, ah = png_size(after)
    s = float(MAXDIM) / max(bh, ah, bw, aw)
    compose([(before, None, int(bw * s), int(bh * s)),
             (after, None, int(aw * s), int(ah * s))], out_tag)

# 100% 局部对比由 _demo_up_crop.py 单独生成，别在这里覆盖它
print("拼图结束")
