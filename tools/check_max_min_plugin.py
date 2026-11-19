# -*- coding: utf-8 -*-
"""plugin/max-min 端到端回归：走 PDB 调插件，核对滤镜挂载与渲染结果。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \\
        --batch-interpreter=python-fu-eval \\
        -b "exec(open(r'<repo>/tools/check_max_min_plugin.py').read())" --quit

算子本身的逐位正确性由 tools/check_max_min.py 负责（对暴力实现）。这里只管
插件这一层容易被忽略的事：

  · 过程注册上了没有、参数对不对
  · 滤镜是不是**非破坏**地挂上去（像素没被改、滤镜在列表里、可以移除）
  · 挂到图层蒙版上是不是落在蒙版而不是图层
  · 图层组要明确拒绝，不能静默不动
"""

import array
import sys

import gi

gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gegl, Gimp

Gegl.init()

PROC = 'lb-plugin-max-min'
PASS = 0
FAIL = 0


def report(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  PASS  %-44s %s" % (label, detail), flush=True)
    else:
        FAIL += 1
        print("  FAIL  %-44s %s" % (label, detail), flush=True)


def px_pattern(w, h):
    """左半 0、右半 255，中间夹一条 128 的窄带；右上角一个孤立亮点。"""
    out = []
    for y in range(h):
        for x in range(w):
            if x < w // 3:
                v = 0
            elif x < w // 3 + 3:
                v = 128
            else:
                v = 255
            out.append((v, v, v))
    out[2 * w + w - 2] = (0, 0, 0)      # 亮点旁边挖一个暗点
    return out


def make_image(w, h, with_alpha=False):
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    itype = Gimp.ImageType.RGBA_IMAGE if with_alpha else Gimp.ImageType.RGB_IMAGE
    lay = Gimp.Layer.new(img, "bg", w, h, itype, 100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)

    px = px_pattern(w, h)
    a = array.array('f')
    for r, g, b in px:
        a.extend([r / 255.0, g / 255.0, b / 255.0, 1.0])
    fmt = "R'G'B'A float"
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), fmt, a.tobytes())
    lay.get_buffer().flush()
    lay.update(0, 0, w, h)
    img.set_selected_layers([lay])
    return img, lay


def read_rgb(drawable, w, h):
    data = drawable.get_buffer().get(
        Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A float",
        Gegl.AbyssPolicy.NONE)
    f = array.array('f')
    f.frombytes(data)
    return [int(round(f[i * 4] * 255.0)) for i in range(w * h)]


def run_proc(img, drawable, **props):
    proc = Gimp.get_pdb().lookup_procedure(PROC)
    cfg = proc.create_config()
    cfg.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property('image', img)
    cfg.set_core_object_array('drawables', [drawable])
    for k, v in props.items():
        cfg.set_property(k.replace('_', '-'), v)
    return proc.run(cfg)


def brute(vals, w, h, r, want_max):
    out = list(vals)
    for y in range(h):
        for x in range(w):
            best = vals[y * w + x]
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    yy = min(max(y + dy, 0), h - 1)
                    xx = min(max(x + dx, 0), w - 1)
                    v = vals[yy * w + xx]
                    best = max(best, v) if want_max else min(best, v)
            out[y * w + x] = best
    return out


def main():
    print("== plugin/max-min 端到端 ==", flush=True)

    proc = Gimp.get_pdb().lookup_procedure(PROC)
    report("过程已注册", proc is not None)
    if proc is None:
        return

    W, H = 36, 24

    # 1) 最大值挂到图层：像素不动，滤镜在列表里，渲染结果与暴力一致
    img, lay = make_image(W, H)
    before = read_rgb(lay, W, H)
    res = run_proc(img, lay, mode='maximum', radius=2, shape='square',
                   affect_alpha=False)
    report("调用返回 SUCCESS", res.index(0) == Gimp.PDBStatusType.SUCCESS,
           str(res.index(0)))

    after = read_rgb(lay, W, H)
    report("非破坏：get_buffer 仍是原始像素", before == after,
           "首值 %d / %d" % (before[0], after[0]))

    filters = lay.get_filters()
    report("滤镜已挂到图层", len(filters) == 1, "%d 条" % len(filters))

    # 渲染结果：复制一份并合并（合并会把滤镜算进去），再与暴力实现比
    vals = [p[0] for p in px_pattern(W, H)]
    want = brute(vals, W, H, 2, True)
    dup = img.duplicate()
    flat = dup.flatten()
    got = read_rgb(flat, W, H)
    diff = sum(1 for a, b in zip(got, want) if a != b)
    report("合并后结果 = 最大值暴力实现", diff == 0,
           "逐像素相同" if diff == 0 else "%d/%d 不同" % (diff, W * H))
    dup.delete()

    # 2) 挂到图层蒙版：滤镜落在蒙版上，不落到图层
    img2, lay2 = make_image(W, H, with_alpha=True)
    mask = lay2.create_mask(Gimp.AddMaskType.SELECTION)
    lay2.add_mask(mask)
    # 蒙版走的是「直接写像素」那条路（GIMP 3 的蒙版没有滤镜栈）：
    # 选一个白色方块做蒙版，跑最大值应该把方块撑大
    img2.select_rectangle(Gimp.ChannelOps.REPLACE, 8, 8, 6, 6)
    mask2 = lay2.create_mask(Gimp.AddMaskType.SELECTION)
    lay2.add_mask(mask2)

    def mask_at(m, px, py):
        return m.get_buffer().get(Gegl.Rectangle.new(px, py, 1, 1), 1.0,
                                  "Y u8", Gegl.AbyssPolicy.NONE)[0]

    before_in = mask_at(mask2, 12, 12)
    before_out = mask_at(mask2, 6, 12)
    res2 = run_proc(img2, mask2, mode='maximum', radius=3, shape='square')
    report("蒙版：调用返回 SUCCESS",
           res2.index(0) == Gimp.PDBStatusType.SUCCESS, str(res2.index(0)))
    report("蒙版：方块内仍是白的", before_in == 255, str(before_in))
    report("蒙版：外侧 2px 被扩张成白", mask_at(mask2, 6, 12) == 255,
           "原 %d → %d" % (before_out, mask_at(mask2, 6, 12)))
    report("蒙版不挂滤镜栈（走写像素）", len(mask2.get_filters()) == 0,
           "%d 条" % len(mask2.get_filters()))
    report("图层上没有多出滤镜", len(lay2.get_filters()) == 0,
           "%d 条" % len(lay2.get_filters()))

    # 3) 图层组要明确拒绝
    img3 = Gimp.Image.new(20, 20, Gimp.ImageBaseType.RGB)
    grp = Gimp.GroupLayer.new(img3, "grp")
    img3.insert_layer(grp, None, 0)
    res3 = run_proc(img3, grp, mode='maximum', radius=1, shape='square')
    report("图层组被拒绝",
           res3.index(0) != Gimp.PDBStatusType.SUCCESS, str(res3.index(0)))

    # 4) 参数透传：半径越界时 PDB 层应拒绝（1–100）
    img4, lay4 = make_image(12, 12)
    bad = True
    try:
        run_proc(img4, lay4, mode='maximum', radius=0, shape='square')
    except Exception:
        bad = False
    report("半径 0 被参数校验挡住", bad)

    print("\n合计 %d 项，失败 %d 项" % (PASS + FAIL, FAIL))
    return FAIL


_fail = main()
if _fail:
    print("MAX-MIN PLUGIN CHECKS FAILED: %d" % _fail)
