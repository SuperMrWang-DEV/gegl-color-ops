# -*- coding: utf-8 -*-
"""回归：layer-to-mask 插件（任意图层 → 选区 / Alpha 通道）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_layer_to_mask.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gimp / Gegl 的 GI 绑定）。检查 11 件事：

1. 灰度图层 → 选区的值等于灰度值（128 → 128）；
2. 反相是 255 减去原值；
3. 比画布小、带偏移的图层只在自己位置生效，界外不选中；
4. 彩色图层的 Gray 走亮度（纯红 ≈ 54），不是 HSL 明度（那会是 130）；
5. R / G / B / Alpha 通道各自取对；
6. 图层 → 通道：值、名字、反相；
7. **有选区时转通道不被截断**（shadow merge 遵守选区的坑），且原选区被恢复；
8. 选区的四种组合方式（Replace / Add / Subtract / Intersect）。
"""
import os
import array
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl


def _find_repo():
    cands = []
    try:
        cands.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except NameError:
        pass
    cwd = os.getcwd()
    cands += [cwd, os.path.join(cwd, "SuperMrWang"),
              os.path.join(cwd, "..", "SuperMrWang")]
    for c in cands:
        if os.path.exists(os.path.join(c, "plugin", "layer-to-mask",
                                       "layer-to-mask.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


PLUG = os.path.join(_find_repo(), "plugin", "layer-to-mask", "layer-to-mask.py")
spec = importlib.util.spec_from_file_location("layer_to_mask", PLUG)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FAIL = []


def _pdb(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def check(label, got, want, tol=1):
    ok = all(abs(g - w) <= tol for g, w in zip(got, want))
    print("%-40s got=%-14s want=%-14s %s"
          % (label, " ".join("%.0f" % v for v in got),
             " ".join(str(v) for v in want), "OK" if ok else "FAIL"))
    if not ok:
        FAIL.append(label)


def mk_layer(img, name, w, h, rgba, ox=0, oy=0):
    lay = Gimp.Layer.new(img, name, w, h, Gimp.ImageType.RGBA_IMAGE, 100.0,
                         Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, -1)
    if ox or oy:
        lay.set_offsets(ox, oy)
    buf = array.array('f', bytes(w * h * 16))
    for i in range(w * h):
        for c in range(4):
            buf[i * 4 + c] = rgba[c] / 255.0
    r = Gegl.Rectangle.new(0, 0, w, h)
    sh = lay.get_shadow_buffer()
    sh.set(r, "R'G'B'A float", buf.tobytes())
    sh.flush()
    lay.merge_shadow(True)
    return lay


def selv(img, x, y):
    """选区在 (x,y) 的值，0..255 / selection value, 0..255"""
    return [round(img.get_selection().value(img, x, y))]


def chan_val(ch, x, y):
    raw = ch.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                              "Y' float", Gegl.AbyssPolicy.NONE)
    a = array.array('f')
    a.frombytes(bytes(bytearray(raw)))
    return [round(a[0] * 255)]


def new_image(w=8, h=8):
    return Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)


# ---- 1/2. 灰度 → 选区，反相 ------------------------------------------------
img = new_image()
lay = mk_layer(img, "grey128", 8, 8, (128, 128, 128, 255))
mod.layer_to_selection(img, lay)
check("灰度128 → 选区", selv(img, 4, 4), [128])

mod.layer_to_selection(img, lay, invert=True)
check("反相 → 127", selv(img, 4, 4), [127])

# ---- 3. 小图层 + 偏移 ------------------------------------------------------
img2 = new_image()
small = mk_layer(img2, "small", 4, 4, (255, 255, 255, 255), ox=2, oy=2)
mod.layer_to_selection(img2, small)
check("偏移图层 内 (3,3)", selv(img2, 3, 3), [255])
check("偏移图层 界外 (0,0)", selv(img2, 0, 0), [0])
check("偏移图层 右界 (6,6)", selv(img2, 6, 6), [0])

# ---- 4. 彩色图层的 Gray 走亮度（不是 HSL 明度） ----------------------------
img3 = new_image()
redlay = mk_layer(img3, "red", 8, 8, (255, 0, 0, 255))
mod.layer_to_selection(img3, redlay, channel=mod.CH_GRAY)
check("纯红 Gray=亮度(≈54)", selv(img3, 4, 4), [54], tol=4)

# ---- 5. 单通道取值 ---------------------------------------------------------
img4 = new_image()
c123 = mk_layer(img4, "c", 8, 8, (10, 20, 30, 128))
mod.layer_to_selection(img4, c123, channel=mod.CH_RED)
check("R 通道 = 10", selv(img4, 4, 4), [10])
mod.layer_to_selection(img4, c123, channel=mod.CH_GREEN)
check("G 通道 = 20", selv(img4, 4, 4), [20])
mod.layer_to_selection(img4, c123, channel=mod.CH_BLUE)
check("B 通道 = 30", selv(img4, 4, 4), [30])
mod.layer_to_selection(img4, c123, channel=mod.CH_ALPHA)
check("Alpha 通道 = 128", selv(img4, 4, 4), [128])

# ---- 6. 图层 → 通道：值 / 名字 / 反相 --------------------------------------
img5 = new_image()
g200 = mk_layer(img5, "grey200", 8, 8, (200, 200, 200, 255))
ch = mod.layer_to_channel(img5, g200)
check("通道值 = 200", chan_val(ch, 4, 4), [200])
check("通道名沿用图层名", [1 if ch.get_name() == "grey200" else 0], [1])

ch2 = mod.layer_to_channel(img5, g200, invert=True, name="inv")
check("通道反相 = 55", chan_val(ch2, 4, 4), [55])
check("通道自定义名", [1 if ch2.get_name() == "inv" else 0], [1])

# ---- 7. 有选区时转通道不被截断，且原选区恢复 -------------------------------
img6 = new_image()
white = mk_layer(img6, "white", 8, 8, (255, 255, 255, 255))
img6.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 2, 2)      # 只在左上角
ch3 = mod.layer_to_channel(img6, white)
check("通道·原点仍在", chan_val(ch3, 0, 0), [255])
check("通道·选区外也有内容", chan_val(ch3, 7, 7), [255])
check("转通道后原选区保留 (1,1)", selv(img6, 1, 1), [255])
check("转通道后原选区保留 (7,7)", selv(img6, 7, 7), [0])

# ---- 8. 四种组合方式 -------------------------------------------------------
img7 = new_image()
g100 = mk_layer(img7, "g100", 8, 8, (100, 100, 100, 255))
img7.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 4, 8)      # 左半
mod.layer_to_selection(img7, g100, operation=1)                 # Add
check("Add：选区外也进来了 (6,4)", selv(img7, 6, 4), [100])

img8 = new_image()
g100b = mk_layer(img8, "g100", 8, 8, (100, 100, 100, 255))
_pdb('gimp-selection-all', image=img8)
mod.layer_to_selection(img8, g100b, operation=2)                # Subtract
check("Subtract：255-100=155", selv(img8, 4, 4), [155])

img9 = new_image()
g100c = mk_layer(img9, "g100", 8, 8, (100, 100, 100, 255))
_pdb('gimp-selection-all', image=img9)
mod.layer_to_selection(img9, g100c, operation=3)                # Intersect
check("Intersect：min(255,100)=100", selv(img9, 4, 4), [100])

print("\n%s" % ("全部通过" if not FAIL else "失败：%s" % ", ".join(FAIL)))
