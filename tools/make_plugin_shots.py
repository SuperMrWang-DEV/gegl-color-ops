# -*- coding: utf-8 -*-
"""把插件页要用的「真实参数对话框」截成 PNG。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/make_plugin_shots.py').read())" --quit

只做走 `GimpUi.ProcedureDialog` 自动参数框的那批（二十多个）。自绘对话框的
六支（curves / layer-style / refine / warp / mesh-warp / vanishing-point）
各自的 build_dialog 参数不同，在 make_plugin_shots_custom.py 里单独处理。

截图不靠窗口系统：Gtk.Dialog 是 toplevel，塞不进 OffscreenWindow，改用
cairo 直接把整棵控件树 draw 进 ImageSurface——标题栏（窗口管理器画的）没有，
所以顶上自己补一条标题带，和曲线那几张保持一致。

输出：
  docs/assets/plugins/<slug>/dialog.png
  tools/site/plugin_shots.json   {slug: {"zh": 参数说明, "en": ...}}
"""
import importlib.util
import json
import locale
import os
import sys
import time

# gimp-console 在 Windows 上不读 LANG，界面语言回落到英文；截图要的是中文
# 界面（真实用户在中文 GIMP 里看到的样子），直接把 C locale 换过去。
for _loc in ("Chinese_China.936", "zh_CN.UTF-8", "zh_CN"):
    try:
        locale.setlocale(locale.LC_ALL, _loc)
        break
    except locale.Error:
        continue

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, GimpUi, Gtk

ROOT = os.environ.get("LB_REPO") or \
    r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\SuperMrWang"
# 图源放 tools/site 下：docs/ 每次构建都会被整体清空重写，
# 直接写进 docs/assets/plugins 会被下一次 site_build 删掉。
OUTDIR = os.path.join(ROOT, "tools", "site", "plugin-shots")
JSDIR = os.path.join(ROOT, "tools", "site")
TITLE_H = 34

# slug -> (PDB 过程名, 中文标题, 英文标题, 中文说明, 英文说明)
CASES = [
    ("layer-to-selection", "lb-plugin-layer-to-selection",
     "图层转选区", "Layer to Selection",
     "目标类型、是否反相、是否隐藏源图层", "target, invert, hide the source layer"),
    ("layer-to-channel", "lb-plugin-layer-to-channel",
     "图层转通道", "Layer to Channel",
     "通道名、反相、是否保留源图层", "channel name, invert, keep the source"),
    ("split-channels", "lb-plugin-split-channels",
     "拆通道", "Split Channels",
     "拆成哪几个分量、是否带上 alpha、是否隐藏原图",
     "which components, keep alpha, hide the original"),
    ("hsv-split-curves", "lb-plugin-hsv-split-curves",
     "HSV 分通道曲线", "HSV Split Curves",
     "H / S / V 三条曲线、输出成组还是独立图层",
     "H / S / V curves, grouped or separate output"),
    ("lch-split-curves", "lb-plugin-lch-split-curves",
     "LCh 分通道曲线", "LCh Split Curves",
     "L / C / h 三条曲线，色相环按角度吸附",
     "L / C / h curves, hue snapping on the angle ring"),
    ("hsl-split-curves", "lb-plugin-hsl-split-curves",
     "HSL 分通道曲线", "HSL Split Curves",
     "H / S / L 三条曲线与合并方式", "H / S / L curves and the merge mode"),
    ("lab-split-curves", "lb-plugin-lab-split-curves",
     "Lab 分通道曲线", "Lab Split Curves",
     "L / a / b 三条曲线，a、b 带中性轴",
     "L / a / b curves, a and b centred on neutral"),
    ("hsi-split-curves", "lb-plugin-hsi-split-curves",
     "HSI 分通道曲线", "HSI Split Curves",
     "H / S / I 三条曲线，强度按亮度归一",
     "H / S / I curves, intensity normalised by luminance"),
    ("frequency-separation", "lb-plugin-frequency-separation",
     "双曲线磨皮（分频）", "Frequency Separation",
     "分离半径、低频/高频的曲线与混合量",
     "split radius, low/high-frequency curves, blend amount"),
    ("dodge-burn", "lb-plugin-dodge-burn",
     "双曲线磨皮（加亮加深）", "Dodge & Burn",
     "加亮/加深两条曲线、保护肤色、蒙版平滑",
     "dodge/burn curves, skin protection, mask smoothing"),
    ("neutral-grey", "lb-plugin-neutral-grey",
     "中性灰观察层", "Neutral Grey",
     "灰度值、混合模式、是否分组",
     "grey level, blend mode, group the result"),
    ("observe", "lb-plugin-observe",
     "观察层", "Observe",
     "观察方式（中性灰 / 黑白 / 高反差保留）与强度",
     "observe mode (neutral grey / mono / high-pass) and strength"),
    ("luminosity", "lb-plugin-luminosity-mask",
     "明度蒙版", "Luminosity Mask",
     "明度区间、羽化、反相", "luminance range, feather, invert"),
    ("ai-inpaint", "lb-plugin-ai-inpaint",
     "AI 消除 / 重绘", "AI Inpaint",
     "提示词、去噪强度、蒙版来源", "prompt, denoise strength, mask source"),
    ("ai-expand", "lb-plugin-ai-expand",
     "AI 扩图", "AI Expand",
     "扩展方向与像素、提示词、接缝处理",
     "direction and amount, prompt, seam handling"),
    ("ai-upscale", "lb-plugin-ai-upscale",
     "AI 放大", "AI Upscale",
     "放大倍数、模型、分块大小", "scale factor, model, tile size"),
    ("cutout", "lb-plugin-cutout-local",
     "抠图", "Cutout",
     "AI 还是本地泛洪、容差、输出为蒙版或 alpha",
     "AI or local flood, tolerance, mask or alpha output"),
    ("ai-frequency-separation", "lb-plugin-ai-frequency-separation",
     "AI 分频磨皮", "AI Frequency Separation",
     "AI 平滑半径、细节回填量", "AI smoothing radius, detail restore"),
    ("ai-dodge-burn", "lb-plugin-ai-dodge-burn",
     "AI 双曲线", "AI Dodge & Burn",
     "AI 生成明暗图、强度与肤色保护",
     "AI shading map, strength, skin protection"),
    ("ai-neutral-grey", "lb-plugin-ai-neutral-grey",
     "AI 中性灰", "AI Neutral Grey",
     "AI 分区、灰度层混合方式", "AI zones, grey layer blend mode"),
    ("alpha-curves", "lb-plugin-alpha-curves",
     "Alpha 曲线", "Alpha Curves",
     "alpha 通道的曲线与作用范围", "alpha curve and its range"),
    ("channel-to-mask", "lb-plugin-channel-to-mask",
     "通道转蒙版", "Channel to Mask",
     "取哪个通道、黑白点、是否反相",
     "which channel, black/white points, invert"),
    ("max-min", "lb-plugin-max-min",
     "最大值 / 最小值", "Maximum / Minimum",
     "半径、取最大还是最小、通道模式",
     "radius, maximum or minimum, channel mode"),
]


def pump(rounds=30, delay=0.02):
    for _ in range(rounds):
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(delay)



def draw_title(cr, text, w, sub=""):
    cr.select_font_face("Microsoft YaHei", 0, 1)
    cr.set_font_size(14)
    cr.set_source_rgb(0.09, 0.09, 0.11)
    cr.move_to(14, 22)
    cr.show_text(text)
    if sub:
        cr.select_font_face("Microsoft YaHei", 0, 0)
        cr.set_font_size(11)
        cr.set_source_rgb(0.55, 0.55, 0.58)
        ext = cr.text_extents(text)
        cr.move_to(14 + ext.width + 12, 22)
        cr.show_text(sub)
    cr.set_source_rgb(0.85, 0.85, 0.87)
    cr.set_line_width(1)
    cr.move_to(0, TITLE_H - 0.5)
    cr.line_to(w, TITLE_H - 0.5)
    cr.stroke()


def shoot(proc_name, title_zh, title_en, slug, limited=()):
    import cairo
    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure(proc_name)
    if proc is None:
        # observe 那支的过程名是 `lb-plugin-observe-<模式>`，按前缀找
        found = None
        for cand in ("%s-neutral-grey" % proc_name, "%s-mono" % proc_name,
                     "%s-high-pass" % proc_name, "%s-color" % proc_name):
            p = pdb.lookup_procedure(cand)
            if p is not None:
                found = p
                break
        proc = found
    if proc is None:
        return None, "PDB 里没有这个过程"

    cfg = proc.create_config()
    if not list(cfg.list_properties()):
        return None, "零参数（不弹参数框）"

    names = [x.name for x in cfg.list_properties()
             if x.name not in ("procedure", "run-mode", "image")]
    dlg = GimpUi.ProcedureDialog.new(proc, cfg, title_zh)
    GimpUi.window_set_transient(dlg)
    dlg.fill(names)
    dlg.show_all()
    pump(14)

    w = max(320, dlg.get_allocated_width() or 0)
    h = max(180, dlg.get_allocated_height() or 0)
    if w <= 320 or h <= 180:
        nw = max(dlg.get_preferred_width())
        nh = max(dlg.get_preferred_height())
        dlg.resize(nw, nh)
        pump(10)
        w = max(w, dlg.get_allocated_width(), nw)
        h = max(h, dlg.get_allocated_height(), nh)

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h + TITLE_H)
    cr = cairo.Context(surface)
    cr.set_source_rgb(0.965, 0.965, 0.973)
    cr.paint()
    draw_title(cr, title_zh, w, title_en)
    cr.translate(0, TITLE_H)
    dlg.draw(cr)
    cr.identity_matrix()

    d = os.path.join(OUTDIR, slug)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "dialog.png")
    surface.write_to_png(path)
    dlg.destroy()
    pump(4)
    return (path, w, h + TITLE_H), ""


def main():
    GimpUi.init("lb-plugin-shots")
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(JSDIR, exist_ok=True)
    meta = {}
    ok = fail = 0
    only = os.environ.get("LB_ONLY")
    cases = [c for c in CASES if not only or c[0] in only.split(",")]
    for slug, proc, tzh, ten, zh, en in cases:
        try:
            res, why = shoot(proc, tzh, ten, slug)
        except Exception as exc:
            res, why = None, "%s: %s" % (type(exc).__name__, exc)
        if res is None:
            print("SKIP %-26s %s" % (slug, why))
            fail += 1
            continue
        path, w, h = res
        meta[slug] = {"zh": zh, "en": en, "w": w, "h": h, "title": tzh}
        print("OK   %-26s %4dx%-4d %s" % (slug, w, h, os.path.basename(path)))
        ok += 1

    jp = os.path.join(JSDIR, "plugin_shots.json")
    old = {}
    if os.path.exists(jp):
        try:
            old = json.load(open(jp, encoding="utf-8"))
        except Exception:
            old = {}
    old.update(meta)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("\n完成 %d 张，跳过 %d 张 -> %s" % (ok, fail, jp))


main()
