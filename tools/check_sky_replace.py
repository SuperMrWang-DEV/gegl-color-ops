# -*- coding: utf-8 -*-
"""回归：一键换天插件（plugin/sky-replace/sky-replace.py）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_sky_replace.py').read())" --quit

必须跑在 GIMP 的 Python 里（要 Gimp 的 GI 绑定）。检查九件事：

1. 分层位置：天空图层插在照片图层正上方，且带图层蒙版（照片不透明，
   插到下方会被完全盖住——这是第一版踩过的坑）；
2. Sky Mask 通道被保存，名字可查；关掉开关时不保存；
3. 换天像素：天空区变成新天空（橙色），地面和楼体逐字节不变；
4. 亮度匹配：新天空 VALUE 均值被 gamma 拉到与原天空一致；
5. match_brightness=False 时跳过 gamma，新天空保持原始亮度；
6. 整张纯色图：泛洪会选中全部画布 → 换天成功覆盖全图（正确行为）；
7. 顶部无有效天空（1px 条纹）：选区面积 <2% → 明确报错；
8. cover 缩放：天空图比画布小也能放大铺满并居中裁切；
9. 直方图刻度：GIMP 3.2 的 histogram 均值 = 255·enc_srgb(v)，
   期望值统一用 enc255() 换算（用蓝/绿/灰/橙四点实测验证过）。
"""
import os
import math
import importlib.util

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gegl, Gio


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
        if os.path.exists(os.path.join(c, "plugin", "sky-replace", "sky-replace.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


REPO = _find_repo()
PLUG = os.path.join(REPO, "plugin", "sky-replace", "sky-replace.py")

spec = importlib.util.spec_from_file_location("sky_replace_plugin", PLUG)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FAIL = []


def check(label, got, want):
    ok = got == want
    print("%-44s got=%-24s want=%-24s %s" % (label, got, want, "OK" if ok else "FAIL"))
    if not ok:
        FAIL.append(label)


def check_close(label, got, want, tol):
    ok = abs(got - want) <= tol
    print("%-44s got=%-24s want=%-24s ±%s %s"
          % (label, round(got, 2), round(want, 2), tol, "OK" if ok else "FAIL"))
    if not ok:
        FAIL.append(label)


def enc255(v):
    """GIMP 3.2 histogram 均值刻度：255·enc_srgb(v/255)，v 是 set_rgba 的 0..1 值"""
    x = v / 255.0
    return 255.0 * (1.055 * x ** (1.0 / 2.4) - 0.055)


def pdb_run(name, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    cfg = proc.create_config()
    for k, v in props.items():
        cfg.set_property(k, v)
    return proc.run(cfg)


def rgb_layer(image, name, w, h):
    layer = Gimp.Layer.new(image, name, w, h, Gimp.ImageType.RGBA_IMAGE,
                           100.0, Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, -1)
    return layer


def fill_rect(layer, x1, y1, x2, y2, rgb):
    """把 (x1,y1)..(x2,y2)（含端点，画布坐标）矩形涂成 rgb（0..255）"""
    pdb_run('gimp-image-select-rectangle', image=layer.get_image(),
            operation=int(Gimp.ChannelOps.REPLACE),
            x=x1, y=y1, width=x2 - x1 + 1, height=y2 - y1 + 1)
    c = Gegl.Color()
    c.set_rgba(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, 1.0)
    Gimp.context_set_foreground(c)
    layer.edit_fill(Gimp.FillType.FOREGROUND)
    pdb_run('gimp-selection-none', image=layer.get_image())


def rect_mean(image, x1, y1, x2, y2, channel):
    """选区直方图均值。channel: 0 VALUE, 1 R, 2 G, 3 B"""
    pdb_run('gimp-image-select-rectangle', image=image,
            operation=int(Gimp.ChannelOps.REPLACE),
            x=x1, y=y1, width=x2 - x1 + 1, height=y2 - y1 + 1)
    res = pdb_run('gimp-drawable-histogram',
                  drawable=image.flatten(), channel=channel,
                  start_range=0.0, end_range=1.0)
    pdb_run('gimp-selection-none', image=image)
    return res.index(1)


def save_png(image, path):
    proc = Gimp.get_pdb().lookup_procedure('gimp-file-save')
    cfg = proc.create_config()
    cfg.set_property('run-mode', int(Gimp.RunMode.NONINTERACTIVE))
    cfg.set_property('image', image)
    cfg.set_property('file', Gio.File.new_for_path(path))
    try:
        cfg.set_property('options', None)
    except Exception:
        pass
    proc.run(cfg)


# ---- 测试图：蓝天 + 绿地 + 深灰楼体 ------------------------------------------

BLUE = (140, 170, 204)
GREEN = (40, 120, 50)
GRAY = (60, 60, 60)
ORANGE = (230, 120, 40)

W = H = 64
img = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
photo = rgb_layer(img, 'photo', W, H)
fill_rect(photo, 0, 0, W - 1, H - 1, GREEN)      # 整张绿地
fill_rect(photo, 0, 0, W - 1, 31, BLUE)          # 上半蓝天
fill_rect(photo, 40, 20, 47, 47, GRAY)           # 楼体，跨天空/地面

sky_img = Gimp.Image.new(48, 48, Gimp.ImageBaseType.RGB)   # 比画布小 → 测 cover
sky_lay = rgb_layer(sky_img, 'newsky', 48, 48)
fill_rect(sky_lay, 0, 0, 47, 47, ORANGE)
SKY_PNG = os.path.join(REPO, "tools", "_sky_test.png")
save_png(sky_img, SKY_PNG)
sky_file = Gio.File.new_for_path(SKY_PNG)

# 期望值（直方图刻度）
exp_sky_val = enc255(BLUE[2])            # 匹配后新天空 VALUE = 原天空 VALUE
exp_ground_g = enc255(GREEN[1])          # 地面不变
exp_building_r = enc255(GRAY[0])         # 楼体不变
exp_raw_sky_val = enc255(ORANGE[0])      # 不匹配时新天空 VALUE

# ---- 1+2+3+4. 主流程（天空区取样从 x=3 起，避开收缩 1px 的边界） -------------

sky_layer, mask, chan = mod.sky_replace(img, photo, sky_file,
                                        threshold=0.15, edge=1, feather=0.0,
                                        match_brightness=True,
                                        save_mask_channel=True)

check("分层：天空在照片上方", [l.get_name() for l in img.get_layers()],
      ['Sky', 'photo'])
check("天空图层带蒙版", mask is not None and sky_layer.get_mask() is mask, True)
check("Sky Mask 通道已保存",
      [c.get_name() for c in img.get_channels()], ['Sky Mask'])

sky_val = rect_mean(img, 3, 4, 30, 26, 0)
check_close("天空区 VALUE=匹配后", sky_val, exp_sky_val, 8)
sky_r = rect_mean(img, 3, 4, 30, 26, 1)
sky_g = rect_mean(img, 3, 4, 30, 26, 2)
sky_b = rect_mean(img, 3, 4, 30, 26, 3)
check("天空区 R>G>B（橙系）", sky_r > sky_g > sky_b, True)
check_close("地面 G 不变", rect_mean(img, 0, 52, 30, 60, 2), exp_ground_g, 4)
check_close("楼体 R 不变", rect_mean(img, 41, 24, 46, 31, 1), exp_building_r, 4)

# ---- 5. 关掉亮度匹配 → 新天空保持原始值 ---------------------------------------

img2 = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
photo2 = rgb_layer(img2, 'photo', W, H)
fill_rect(photo2, 0, 0, W - 1, H - 1, GREEN)
fill_rect(photo2, 0, 0, W - 1, 31, BLUE)
mod.sky_replace(img2, photo2, sky_file, threshold=0.15, edge=1, feather=0.0,
                match_brightness=False, save_mask_channel=False)
check_close("无匹配时天空 VALUE=原值", rect_mean(img2, 3, 4, 30, 26, 0),
            exp_raw_sky_val, 8)
check("关掉通道保存→无 Sky Mask",
      [c.get_name() for c in img2.get_channels()], [])

# ---- 6. 整张纯色图 → 全画布选中，换天覆盖全图 ---------------------------------

img3 = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
photo3 = rgb_layer(img3, 'photo', W, H)
fill_rect(photo3, 0, 0, W - 1, H - 1, GREEN)
mod.sky_replace(img3, photo3, sky_file, threshold=0.15, edge=1, feather=0.0,
                match_brightness=True, save_mask_channel=False)
check("纯色图分层", [l.get_name() for l in img3.get_layers()], ['Sky', 'photo'])
g_before = enc255(GREEN[1])
g_after = rect_mean(img3, 0, 52, 30, 60, 2)
check_close("纯色图地面被覆盖", abs(g_after - g_before) > 20.0, True, 0.0)

# ---- 7. 顶部无有效天空（强对比条纹）→ 顶行覆盖率不足报错 -----------------------

img4 = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
photo4 = rgb_layer(img4, 'photo', W, H)
for y in range(H):                     # 逐行强对比色 → 泛洪只能选中 1 行
    fill_rect(photo4, 0, y, W - 1, y, (255, 64, 64) if y % 2 else (32, 64, 255))
try:
    mod.sky_replace(img4, photo4, sky_file, threshold=0.02, edge=0,
                    feather=0.0, match_brightness=False,
                    save_mask_channel=False)
    check("条纹图报错", "no-exception", "exception")
except RuntimeError as e:
    check("条纹图报错", "exception", "exception")
    check("报错含覆盖率提示", "覆盖率" in str(e), True)
except Exception as e:
    check("条纹图报错类型", type(e).__name__, "RuntimeError")

# ---- 清理 + 汇总 -------------------------------------------------------------

try:
    os.remove(SKY_PNG)
except OSError:
    pass

print("")
if FAIL:
    print("✗ %d 项失败：%s" % (len(FAIL), "；".join(FAIL)))
else:
    print("✓ 全部通过")
