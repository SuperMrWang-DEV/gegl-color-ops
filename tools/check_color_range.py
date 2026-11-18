# -*- coding: utf-8 -*-
"""回归：color-range 插件（色彩范围的定制对话框）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_color_range.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gtk + DrawableFilter）。检查这些事：

1. 十个模式各自的默认值：高光 192、阴影 64、中间调 64/192、色系没有限值键；
2. 公共参数默认：容差 50、羽化 10、最低彩度 0、不反相、红色叠加默认开；
3. 对话框能建起来（GTK 初始化后构造，不显示），每个模式 collect() 出来的
   mask_mode 与默认值都对；
4. 切模式不串值：改高光那根杆，切到阴影再切回来，改动还在；
5. 默认参数写进滤镜配置后，cfg 里读回来的值与预期一致；
6. apply_once 真的合并：图层上不留滤镜，RGB 一个码不动（红色没被烤进去）；
7. 高光模式：纯亮端 alpha = 1、纯暗端 alpha ≈ 0；阴影模式正好相反；
8. 没有 alpha 的图层会被补上 alpha；
9. 图层组被拒绝。
"""
import array
import importlib.util
import os

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, Gegl, Gtk

CHECKS = [0]
FAILS = []


def check(cond, label, detail=None):
    CHECKS[0] += 1
    if cond:
        print("  ok   %s" % label)
    else:
        FAILS.append(label)
        print("  FAIL %s%s" % (label, ("  (%s)" % detail) if detail else ""))


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
        if os.path.exists(os.path.join(c, "plugin", "color-range",
                                       "color-range.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
CR = _load("color_range", os.path.join(REPO, "plugin", "color-range",
                                       "color-range.py"))

W = 33


def make_image(with_alpha=True):
    """33×1 的灰阶斜坡：第 i 个像素 = i/(W-1)，浮点精度。"""
    img = Gimp.Image.new(W, 1, Gimp.ImageBaseType.RGB)
    proc = Gimp.get_pdb().lookup_procedure('gimp-image-convert-precision')
    cfg = proc.create_config()
    cfg.set_property('image', img)
    cfg.set_property('precision', Gimp.Precision.FLOAT_NON_LINEAR)
    proc.run(cfg)
    itype = Gimp.ImageType.RGBA_IMAGE if with_alpha else Gimp.ImageType.RGB_IMAGE
    lay = Gimp.Layer.new(img, "t", W, 1, itype, 100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    px = array.array('f', bytes(W * 4))
    for i in range(W):
        x = i / float(W - 1)
        px[i * 4:i * 4 + 4] = array.array('f', [x, x, x, 1.0])
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, W, 1), "R'G'B'A float",
                         px.tobytes())
    return img, lay


def flatten(lay):
    img = lay.get_image()
    di = img.duplicate()
    merged = di.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    raw = merged.get_buffer().get(Gegl.Rectangle.new(0, 0, W, 1), 1.0,
                                  "R'G'B'A float", Gegl.AbyssPolicy.NONE)
    out = array.array('f')
    out.frombytes(bytes(bytearray(raw)))
    di.delete()
    return out


def make_filter(lay):
    f = Gimp.DrawableFilter.new(lay, "lb:color-mask-select", "t")
    lay.append_filter(f)
    return f


# ---- 1–2. 默认值表 ----------------------------------------------------------

print("· 默认值")
COLOR_MODES = ('red', 'yellow', 'green', 'cyan', 'blue', 'magenta')
for mode in COLOR_MODES + ('custom',):
    p = CR.defaults_for(mode)
    check('highlights_limit' not in p and 'shadows_limit' not in p
          and 'midtone_low' not in p,
          "%s 不带限值键（范围是色相环）" % mode)

p = CR.defaults_for('white')
check(p.get('highlights_limit') == 192, "高光默认范围 = 192",
      str(p.get('highlights_limit')))
p = CR.defaults_for('black')
check(p.get('shadows_limit') == 64, "阴影默认范围 = 64",
      str(p.get('shadows_limit')))
p = CR.defaults_for('gray')
check(p.get('midtone_low') == 64 and p.get('midtone_high') == 192,
      "中间调默认 64 / 192",
      "%s / %s" % (p.get('midtone_low'), p.get('midtone_high')))
p = CR.defaults_for('red')
check(p['fuzziness'] == 50 and p['feather'] == 10 and p['saturation_min'] == 0,
      "公共默认：容差 50 / 羽化 10 / 最低彩度 0")
check(p['invert'] is False and p['preview_red_mask'] is True,
      "反相默认关、红色叠加默认开")

# ---- 3–5. 对话框（不显示） --------------------------------------------------

print("· 对话框")
ok, _argv = Gtk.init_check()
check(bool(ok), "GTK 能初始化")
img, lay = make_image()
filt = make_filter(lay)
dlg = CR.ColorRangeDialog(img, lay, filt)
check(dlg is not None, "对话框构造成功")

for mode in ('red', 'white', 'black', 'gray', 'custom'):
    dlg.combo.set_active_id(mode)
    got = dlg.collect()
    check(got['mask_mode'] == mode, "%s 的 mask_mode 传对" % mode)
    want = CR.defaults_for(mode)
    same = all(abs(float(got[k]) - float(want[k])) < 1e-6
               for k in ('fuzziness', 'feather')
               if k in want)
    for k in ('highlights_limit', 'shadows_limit', 'midtone_low', 'midtone_high'):
        if k in want:
            same = same and abs(got[k] - want[k]) < 1e-6
    check(same, "%s 的参数从自己的默认值起步" % mode)

area = CR._mode_kind('red')
check(area == 'chroma' and CR._mode_kind('white') == 'white'
      and CR._mode_kind('gray') == 'gray' and CR._mode_kind('custom') == 'custom',
      "模式 → 控件组映射")

# 切模式不串值
dlg.combo.set_active_id('white')
dlg.state['white']['highlights_limit'].set_value(210)
dlg.combo.set_active_id('black')
dlg.combo.set_active_id('white')
check(abs(dlg.state['white']['highlights_limit'].get_value() - 210) < 1e-6,
      "切走再切回，高光范围保留改动（210）",
      str(dlg.state['white']['highlights_limit'].get_value()))
dlg.destroy()

# 配置写进滤镜后读回来
CR.push_config(filt, CR.defaults_for('white'))
cfg = filt.get_config()
check(cfg.get_property('mask-mode') == 'white', "cfg 的 mask-mode = white")
check(int(cfg.get_property('highlights-limit')) == 192,
      "cfg 的 highlights-limit = 192",
      str(cfg.get_property('highlights-limit')))
check(abs(cfg.get_property('fuzziness') - 50.0) < 1e-6,
      "cfg 的 fuzziness = 50")
filt.delete()
img.delete()

# ---- 6–7. 一次性应用 --------------------------------------------------------

print("· 一次性应用")
for mode, want_left, want_right in (('white', 0.0, 1.0), ('black', 1.0, 0.0)):
    img, lay = make_image()
    CR.apply_once(img, lay, CR.defaults_for(mode))
    px = flatten(lay)
    check(len(lay.get_filters()) == 0, "%s：合并后不留滤镜" % mode,
          str(len(lay.get_filters())))
    rgb_same = max(abs(px[i * 4 + c] - i / float(W - 1))
                   for i in range(W) for c in range(3))
    check(rgb_same < 1e-6, "%s：RGB 一个码不动（红色没烤进去）" % mode,
          "%.6f" % rgb_same)
    left = px[3]
    right = px[(W - 1) * 4 + 3]
    check(abs(left - want_left) < 0.02, "%s：暗端 alpha ≈ %.0f" % (mode, want_left),
          "%.4f" % left)
    check(abs(right - want_right) < 0.02, "%s：亮端 alpha ≈ %.0f" % (mode, want_right),
          "%.4f" % right)
    img.delete()

# ---- 8–9. 边界 --------------------------------------------------------------

print("· 边界")
img, lay = make_image(with_alpha=False)
check(not lay.has_alpha(), "起始图层没有 alpha")
CR.apply_once(img, lay, CR.defaults_for('white'))
check(lay.has_alpha(), "应用后补上了 alpha")
img.delete()

img = Gimp.Image.new(16, 16, Gimp.ImageBaseType.RGB)
grp = Gimp.GroupLayer.new(img, "g")
img.insert_layer(grp, None, 0)
try:
    CR.apply_once(img, grp, CR.defaults_for('white'))
    check(False, "图层组被拒绝")
except Exception:
    check(True, "图层组被拒绝")
img.delete()

print()
if FAILS:
    print("失败 %d / %d 项：%s" % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
else:
    print("全部 %d 项通过 / %d checks passed" % (CHECKS[0], CHECKS[0]))
