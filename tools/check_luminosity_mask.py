# -*- coding: utf-8 -*-
"""回归：明度蒙版（七条通道，一键生成）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_luminosity_mask.py').read())" --quit
"""
import os
import array
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
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
        if os.path.exists(os.path.join(c, "plugin", "luminosity-mask",
                                       "luminosity-mask.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = _find_repo()
LM = _load("lmask", os.path.join(REPO, "plugin", "luminosity-mask",
                                 "luminosity-mask.py"))

FAILS = []
CHECKS = [0]


def check(cond, label, detail=""):
    CHECKS[0] += 1
    if cond:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILS.append(label)


W = H = 32


def make_image(with_alpha=True, group=False):
    """左黑右白的水平渐变：每一列一个确定的亮度值，映射表对错一眼能验出来。"""
    img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
    lt = Gimp.ImageType.RGBA_IMAGE if with_alpha else Gimp.ImageType.RGB_IMAGE
    lay = Gimp.Layer.new(img, "base", W, H, lt, 100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    px = array.array('f')
    for y in range(H):
        for x in range(W):
            v = x / float(W - 1)
            px.extend([v, v, v, 1.0])
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, W, H),
                         "R'G'B'A float", px.tobytes())
    return img, lay


def channel_data(ch):
    w, h = ch.get_width(), ch.get_height()
    raw = ch.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "Y u8",
                              Gegl.AbyssPolicy.NONE)
    return w, h, bytes(bytearray(raw))


def find(image, needle):
    for ch in image.get_channels():
        if needle in ch.get_name():
            return ch
    return None


# ---- [1] 映射表本身（纯 Python，不依赖 GIMP 画布） -------------------------

print("== [1] 映射表 / the look-up tables")
masks = LM.build_masks()
check(len(masks) == 7, "七条", len(masks))

names = [n for n, _t in masks]
check(len(set(names)) == 7, "名字互不重复", names)
for kw in ("Lights 1", "Lights 2", "Lights 3",
           "Darks 1", "Darks 2", "Darks 3", "Midtones"):
    check(any(kw in n for n in names), "有 %s" % kw)

tables = dict(masks)
lights1 = tables[LM._("Lights 1 (> %d)") % LM.T1]
lights3 = tables[LM._("Lights 3 (> %d)") % LM.T3]
darks1 = tables[LM._("Darks 1 (< %d)") % LM.T3]
darks3 = tables[LM._("Darks 3 (< %d)") % LM.T1]

check(lights1[0] == 0, "亮部 1：纯黑处为 0", lights1[0])
check(lights1[LM.T1] == 0, "亮部 1：阈值处仍为 0", lights1[LM.T1])
check(lights1[255] == 255, "亮部 1：纯白处为 255", lights1[255])
check(lights1[LM.T1 + 1] > 0, "亮部 1：刚过阈值就开始亮", lights1[LM.T1 + 1])

check(lights3[LM.T3] == 0, "亮部 3：192 处为 0", lights3[LM.T3])
check(lights1[LM.T3 - 1] > 0,
      "亮部 1：191 处已经亮起来（覆盖范围更宽）", lights1[LM.T3 - 1])
check(lights3[200] < lights1[200],
      "亮部 3：200 处比亮部 1 暗（只挑最亮的那截）",
      (lights3[200], lights1[200]))

check(all(lights1[v] >= lights3[v] for v in range(256)),
      "亮部 1 处处不弱于亮部 3（更宽）")
check(all(a + b == 255 for a, b in zip(lights3, darks1)),
      "暗部 1 正好是亮部 3 的反相（同一阈值）")
check(all(a + b == 255 for a, b in zip(lights1, darks3)),
      "暗部 3 正好是亮部 1 的反相（同一阈值）")

mid = tables[LM._("Midtones (%d–%d)") % (LM.T1, LM.T3)]
check(mid[0] == 0, "中间调：最暗处为 0", mid[0])
check(mid[255] == 0, "中间调：最亮处为 0", mid[255])
check(max(mid) == 255, "中间调：峰值归一化到 255", max(mid))
peak = mid.index(255)
check(LM.T1 <= peak <= LM.T3, "中间调：峰值落在两阈值之间", peak)
check(mid[LM.T1] == 0, "中间调：下阈值处仍为 0", mid[LM.T1])
check(mid[LM.T3] == 255, "中间调：峰值正好落在上阈值", mid[LM.T3])
check(mid[LM.T3 + 1] < 255, "中间调：过了上阈值开始下降", mid[LM.T3 + 1])

# ---- [2] 真画布：通道生成 ---------------------------------------------------

print("== [2] 生成通道 / the channels")
img, base = make_image()
before_layers = len(img.get_layers())
base_before = channel_data(base)[2]

made = LM.create_masks(img, base)
check(len(made) == 7, "返回七条通道", len(made))
check(len(img.get_channels()) == 7, "图里正好七条通道",
      len(img.get_channels()))

prefix = LM.channel_prefix()
check(all(ch.get_name().startswith(prefix) for ch in img.get_channels()),
      "全部带统一前缀", [c.get_name() for c in img.get_channels()])
check(len(set(ch.get_name() for ch in img.get_channels())) == 7,
      "通道名互不重复")

check(len(img.get_layers()) == before_layers,
      "没有残留探针图层", len(img.get_layers()))
check(channel_data(base)[2] == base_before, "原图层像素逐位不变")

for ch in img.get_channels():
    check(ch.get_bpp() == 1, "通道是单通道灰度：%s" % ch.get_name(),
          ch.get_bpp())

# ---- [3] 内容：渐变图上的实际取值 -------------------------------------------

print("== [3] 内容 / what the channels hold")
l1 = find(img, LM.channel_prefix() + LM._("Lights 1 (> %d)") % LM.T1)
l3 = find(img, LM.channel_prefix() + LM._("Lights 3 (> %d)") % LM.T3)
d1 = find(img, LM.channel_prefix() + LM._("Darks 1 (< %d)") % LM.T3)
mid_ch = find(img, LM.channel_prefix() + LM._("Midtones (%d–%d)") % (LM.T1, LM.T3))
check(l1 is not None and l3 is not None and d1 is not None
      and mid_ch is not None, "四类通道都找得到")

w, h, data = channel_data(l1)
left = data[16 * w + 0]          # x=0，纯黑一列
right = data[16 * w + (w - 1)]   # x=31，纯白一列
check(left == 0, "亮部 1 左侧（黑）为 0", left)
check(right == 255, "亮部 1 右侧（白）为 255", right)

_, _, d1data = channel_data(d1)
check(d1data[16 * w + 0] == 255, "暗部 1 左侧（黑）为 255", d1data[16 * w + 0])
check(d1data[16 * w + (w - 1)] == 0, "暗部 1 右侧（白）为 0",
      d1data[16 * w + (w - 1)])

# 覆盖范围要看「非零」的像素数，不是「等于 255」的：线性拉伸下只要碰到纯白
# 都是 255，两者在最后一列上一样多，区别在左边那段渐进变亮有多宽。
_, _, l3data = channel_data(l3)
cov1 = sum(1 for b in data if b > 0)
cov3 = sum(1 for b in l3data if b > 0)
check(cov1 > cov3, "亮部 1 覆盖的范围比亮部 3 宽", (cov1, cov3))
check(cov3 > 0, "亮部 3 仍覆盖到高光区", cov3)

img.delete()

# ---- [4] 重跑幂等 / 图层组被拒 ---------------------------------------------

print("== [4] 幂等与拒绝 / rerun and rejection")
img, base = make_image()
LM.create_masks(img, base)
LM.create_masks(img, base)
check(len(img.get_channels()) == 7, "重跑两次仍只有七条（先删旧批）",
      len(img.get_channels()))
img.delete()

img, base = make_image()
grp = Gimp.GroupLayer.new(img, "g")
img.insert_layer(grp, None, 0)
try:
    LM.create_masks(img, grp)
    check(False, "图层组应被拒绝")
except RuntimeError:
    check(True, "图层组被拒绝")
check(len(img.get_channels()) == 0, "被拒时没有留下半成品通道")
img.delete()

# ---- [5] 无 alpha 的图也走得通 ---------------------------------------------

print("== [5] 无 alpha / no alpha")
img, base = make_image(with_alpha=False)
made = LM.create_masks(img, base)
check(len(made) == 7, "无 alpha 图也生成七条", len(made))
_, _, d = channel_data(find(img, LM.channel_prefix() +
                            LM._("Lights 1 (> %d)") % LM.T1))
check(d[16 * w + (w - 1)] == 255, "无 alpha 图右侧仍为 255",
      d[16 * w + (w - 1)])
img.delete()

# ---- 收尾 -------------------------------------------------------------------

print("-" * 46)
if FAILS:
    print("失败 %d 项 / %d：" % (len(FAILS), CHECKS[0]))
    for f in FAILS:
        print("  -", f)
else:
    print("全部通过：%d 项检查" % CHECKS[0])
