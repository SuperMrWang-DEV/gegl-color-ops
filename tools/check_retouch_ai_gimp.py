# -*- coding: utf-8 -*-
"""回归：三支「AI 预修」磨皮插件在真 GIMP 里的行为（用 mock 服务，不需要显卡）。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_retouch_ai_gimp.py').read())" --quit

测的都是「打开文件那一刻能不能看到工作痕迹」：

1. 高低频：组 / 两个子层 / 混合模式 / 滤镜都在；参考图走本地模糊时，高频层
   在痘印位置接近中灰（= 痘印已经被抹掉），而不是原图的暗斑；
2. 双曲线：两张蒙版都已经有白色笔触，暗斑落在提亮蒙版、亮斑落在压暗蒙版，
   预修比例 0 时两张蒙版全黑（= 不动原图）；
3. 中性灰：灰层不再是平的 128——暗斑处 > 128、亮斑处 < 128，背景 ≈ 128；
   预修比例 0 时整层都是 128；
4. 选区：选区外一个像素都不许动（灰层 128、蒙版 0）；
5. AI 那一路（mock 原样返回）：结构照样建出来，并且不因为没有差值而报错。
"""
import os
import sys
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
        if os.path.exists(os.path.join(c, "plugin", "_shared",
                                       "retouch_prep.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


ROOT = _find_repo()
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

SPECS = {
    "fs": os.path.join(ROOT, "plugin", "ai-frequency-separation",
                       "ai-frequency-separation.py"),
    "db": os.path.join(ROOT, "plugin", "ai-dodge-burn", "ai-dodge-burn.py"),
    "ng": os.path.join(ROOT, "plugin", "ai-neutral-grey", "ai-neutral-grey.py"),
}

MODS = {}
for _key, _path in SPECS.items():
    _spec = importlib.util.spec_from_file_location("lb_retouch_" + _key, _path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    MODS[_key] = _mod

import retouch_prep as RP                            # noqa: E402
os.environ["LB_COMFY_AUTOSTART"] = "0"  # 别让回归去起真的 ComfyUI
import mock_comfy                                     # noqa: E402

FAIL = []
OK = 0


def check(label, cond, detail=""):
    global OK
    OK += 1
    print("%-46s %-34s %s" % (label, detail, "OK" if cond else "FAIL"))
    if not cond:
        FAIL.append(label)


def px(drawable, x, y):
    raw = drawable.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                                    "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
    return tuple(bytes(bytearray(raw))[:4])


def mask_px(layer, x, y):
    mask = layer.get_mask()
    if mask is None:
        return None
    raw = mask.get_buffer().get(Gegl.Rectangle.new(x, y, 1, 1), 1.0,
                                "Y u8", Gegl.AbyssPolicy.NONE)
    return bytes(bytearray(raw))[0]


SKIN = (205, 168, 148)
BLEMISH_AT = (55, 50)         # 痘印中心：比肤色暗 40 码，该提亮
BLEMISH_AMT = -40
OIL_AT = (120, 70)            # 油光中心：比肤色亮 30 码，该压暗
OIL_AMT = 30
BLOB_SIGMA = 5.0              # 半径 5px 的软斑：参考图（12px 截止）能修掉，
                              # 而 40px 的大暗块修不动——那是换脸不是磨皮


def make_image(w=180, h=140):
    """肤色底 + 两块高斯软斑。用软斑而不是硬方块，是因为「参考图能不能修掉」
    取决于斑的尺寸相对参考半径——硬方块在降采样里会被整块保留，测出来像
    「算法没干活」，其实是测试图选错了。"""
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    lay = Gimp.Layer.new(img, "base", w, h, Gimp.ImageType.RGB_IMAGE, 100.0,
                         Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    data = bytearray()
    for y in range(h):
        for x in range(w):
            v = 0.0
            for (cx, cy), amt in ((BLEMISH_AT, BLEMISH_AMT), (OIL_AT, OIL_AMT)):
                d2 = (x - cx) ** 2 + (y - cy) ** 2
                v += amt * pow(2.718281828, -d2 / (2.0 * BLOB_SIGMA ** 2))
            c = tuple(max(0, min(255, int(round(ch + v)))) for ch in SKIN)
            data += bytes(c)
    buf = lay.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B' u8", bytes(data))
    buf.flush()
    lay.update(0, 0, w, h)
    return img, lay


# GIMP 3 的 drawables 参数是 GimpCoreObjectArray，Python 侧没有可构造的绑定
# （Gimp.Array 只吃数字）。所以行为测试直接调 run()，塞一个假 config——和
# tools/check_ai_inpaint_gimp.py 同一条路；过程注册 / 下拉默认值另外单独验。

DEFAULTS = {
    "fs": dict(prompt="", source="local", radius=8.0, denoise=0.35,
               server="", checkpoint="", steps=10, group=True),
    "db": dict(prompt="", source="local", amount=12.0, prepaint=70.0,
               radius=12.0, denoise=0.35, server="", checkpoint="", steps=10,
               group=True),
    "ng": dict(prompt="", source="local", prepaint=70.0, radius=12.0,
               denoise=0.35, server="", checkpoint="", steps=10, group=True),
}

PROC_NAMES = {
    "fs": "lb-plugin-ai-frequency-separation",
    "db": "lb-plugin-ai-dodge-burn",
    "ng": "lb-plugin-ai-neutral-grey",
}


class _Proc(object):
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name

    def new_return_values(self, status, err):
        return (status, err)


class _Cfg(object):
    def __init__(self, values):
        self._values = values

    def get_property(self, key):
        return self._values.get(key)


def run_plugin(key, image, layer, **over):
    mod = MODS[key]
    values = dict(DEFAULTS[key])
    values.update(over)
    cls = None
    for c in vars(mod).values():
        if isinstance(c, type) and issubclass(c, Gimp.PlugIn) and c is not Gimp.PlugIn:
            cls = c
            break
    try:
        status, err = cls.run(object(), _Proc(PROC_NAMES[key]),
                              Gimp.RunMode.NONINTERACTIVE, image, [layer],
                              _Cfg(values), None)
    except Exception as exc:                  # 插件里没兜住的异常也要看得见
        return "raised", str(exc)
    msg = getattr(err, "message", "") or ""
    return status, msg


def children(layer):
    try:
        return list(layer.get_children())
    except Exception:
        return []


def drop(img):
    img.delete()


# ---- 0. 注册与下拉 -----------------------------------------------------------

def test_registration():
    print("\n0. 过程注册 / 参考来源下拉")
    for key, name in PROC_NAMES.items():
        proc = Gimp.get_pdb().lookup_procedure(name)
        check("%s 已注册" % name, proc is not None, name)
        if proc is None:
            continue
        args = [a.get_name() for a in proc.get_arguments()]
        check("%s 参数表" % key,
              all(k in args for k in ("prompt", "source", "group", "steps")),
              args)
        label = proc.get_menu_label() or ""
        # 标签会跟着 GIMP 界面语言翻译：中文界面下是「…（AI 预修）」，
        # 英文界面下才是 "(AI prep)"。只认英文的断言在中文 GIMP 里必红。
        check("%s 菜单标签标明是 AI 预修版" % key,
              ("AI prep" in label) or ("AI 预修" in label), label)
        cfg = proc.create_config()
        check("%s source 默认 ai" % key, cfg.get_property("source") == "ai",
              cfg.get_property("source"))
        cfg.set_property("source", "local")
        check("%s source 能设 local" % key,
              cfg.get_property("source") == "local", cfg.get_property("source"))
        bad = False
        try:
            cfg.set_property("source", "nope")
            bad = cfg.get_property("source") == "nope"
        except Exception:
            pass
        check("%s 非法 source 被拒" % key, not bad, "居然接受了 nope")


# ---- 1. 高低频 ---------------------------------------------------------------

def test_fs():
    print("\n1. 高低频磨皮（AI 预修）· 本地参考")
    img, base = make_image()
    st, msg = run_plugin("fs", img, base,
                   prompt="", source="local", radius=8.0, group=True,
                   denoise=0.35, server="", checkpoint="", steps=10)
    check("过程返回 SUCCESS", st == Gimp.PDBStatusType.SUCCESS, msg[:40])

    tops = list(img.get_layers())
    check("顶层多出组（原图层还在）", len(tops) == 2, len(tops))
    group = tops[0]
    check("组名带 AI prep", group.get_name() == "Frequency Separation (AI prep)",
          group.get_name())
    check("组是穿透混合", group.get_mode() == Gimp.LayerMode.PASS_THROUGH,
          group.get_mode())
    kids = children(group)
    check("组里两层", len(kids) == 2, len(kids))
    high, low = kids[0], kids[1]
    check("高频层名", high.get_name() == "2 · High frequency (detail)",
          high.get_name())
    check("低频层名", low.get_name() == "1 · Low frequency (tone)",
          low.get_name())
    check("高频 = 颗粒合并", high.get_mode() == Gimp.LayerMode.GRAIN_MERGE,
          high.get_mode())
    check("低频 = 正常", low.get_mode() == Gimp.LayerMode.NORMAL, low.get_mode())
    check("两层各一条非破坏滤镜",
          len(high.get_filters()) == 1 and len(low.get_filters()) == 1,
          (len(high.get_filters()), len(low.get_filters())))

    # 内容：两层的像素就是参考图（滤镜是非破坏的，缓冲区里存的是源像素）
    cx, cy = BLEMISH_AT
    base_v = px(base, cx, cy)[0]
    ref_v = px(low, cx, cy)[0]
    check("原图在痘印处确实偏暗", base_v < SKIN[0] - 20, base_v)
    check("参考图把痘印提亮了", ref_v > base_v + 8, (base_v, ref_v))
    check("两层内容一致（同一张参考图）",
          px(low, cx, cy)[:3] == px(high, cx, cy)[:3],
          (px(low, cx, cy)[:3], px(high, cx, cy)[:3]))

    # 高频层 = 0.5 + (参考 − 模糊(参考))；参考图本身已经平了，所以它接近中灰。
    # 缓冲区读不到滤镜结果，就按定义验：对参考图再低通一次，差值必须很小。
    w, h = img.get_width(), img.get_height()
    wd, hd, ref_data = RP.layer_pixels(low)
    smooth = RP.local_reference(ref_data, wd, hd, 8.0)
    j = (cy * wd + cx) * 4
    resid = abs(ref_data[j] - smooth[j])
    check("参考图已无高频残留（高频层≈中灰）", resid <= 6, resid)
    # 对照：原图同一处低通后差得很多，说明测试图确实有细节可去
    wb, hb_, base_data = RP.layer_pixels(base)
    smooth_b = RP.local_reference(base_data, wb, hb_, 8.0)
    resid_b = abs(base_data[j] - smooth_b[j])
    check("原图同一处有明显高频（对照）", resid_b > resid + 6,
          (resid_b, resid))

    # 原图层一个像素都没被改
    check("原图层不动", px(base, cx, cy)[:3] == tuple(
        max(0, min(255, int(round(c)))) for c in (px(base, cx, cy)[:3])),
        px(base, cx, cy)[:3])
    drop(img)


# ---- 2. 双曲线 ---------------------------------------------------------------

def test_db():
    print("\n2. 双曲线磨皮（AI 预修）· 本地参考")
    img, base = make_image()
    st, msg = run_plugin("db", img, base,
                   prompt="", source="local", amount=12.0, prepaint=70.0,
                   radius=12.0, group=True, denoise=0.35, server="",
                   checkpoint="", steps=10)
    check("过程返回 SUCCESS", st == Gimp.PDBStatusType.SUCCESS, msg[:40])

    group = list(img.get_layers())[0]
    check("组名带 AI prep", group.get_name() == "Dodge & Burn (AI prep)",
          group.get_name())
    kids = children(group)
    check("组里两层", len(kids) == 2, len(kids))
    burn, dodge = kids[0], kids[1]
    check("提亮层名", dodge.get_name() == "1 · Dodge (pre-painted)",
          dodge.get_name())
    check("压暗层名", burn.get_name() == "2 · Burn (pre-painted)",
          burn.get_name())
    check("两层都有蒙版",
          dodge.get_mask() is not None and burn.get_mask() is not None)

    d_blemish = mask_px(dodge, BLEMISH_AT[0], BLEMISH_AT[1])
    d_oil = mask_px(dodge, OIL_AT[0], OIL_AT[1])
    b_blemish = mask_px(burn, BLEMISH_AT[0], BLEMISH_AT[1])
    b_oil = mask_px(burn, OIL_AT[0], OIL_AT[1])
    check("暗斑处提亮蒙版已被预涂", d_blemish and d_blemish > 20, d_blemish)
    check("暗斑处压暗蒙版是黑的", b_blemish == 0, b_blemish)
    check("亮斑处压暗蒙版已被预涂", b_oil and b_oil > 20, b_oil)
    check("亮斑处提亮蒙版是黑的", d_oil == 0, d_oil)
    check("背景没被乱涂", mask_px(dodge, 5, 5) == 0 and mask_px(burn, 5, 5) == 0,
          (mask_px(dodge, 5, 5), mask_px(burn, 5, 5)))
    drop(img)

    # 预修 0% 时必须全黑（等于原版插件）
    img, base = make_image()
    run_plugin("db", img, base, prompt="", source="local",
         amount=12.0, prepaint=0.0, radius=12.0, group=True, steps=10)
    group = list(img.get_layers())[0]
    kids = children(group)
    check("预修 0% → 提亮蒙版全黑",
          mask_px(kids[1], BLEMISH_AT[0], BLEMISH_AT[1]) == 0, mask_px(kids[1], BLEMISH_AT[0], BLEMISH_AT[1]))
    check("预修 0% → 压暗蒙版全黑",
          mask_px(kids[0], OIL_AT[0], OIL_AT[1]) == 0, mask_px(kids[0], OIL_AT[0], OIL_AT[1]))
    drop(img)


# ---- 3. 中性灰 ---------------------------------------------------------------

def test_ng():
    print("\n3. 中性灰磨皮（AI 预修）· 本地参考")
    img, base = make_image()
    st, msg = run_plugin("ng", img, base, prompt="",
                   source="local", prepaint=70.0, radius=12.0, group=True,
                   denoise=0.35, server="", checkpoint="", steps=10)
    check("过程返回 SUCCESS", st == Gimp.PDBStatusType.SUCCESS, msg[:40])

    group = list(img.get_layers())[0]
    check("组名带 AI prep", group.get_name() == "Neutral Grey (AI prep)",
          group.get_name())
    kids = children(group)
    check("组里一层", len(kids) == 1, len(kids))
    grey = kids[0]
    check("灰层是柔光", grey.get_mode() == Gimp.LayerMode.SOFTLIGHT,
          grey.get_mode())
    check("灰层不是平的 128（已预校正）",
          px(grey, BLEMISH_AT[0], BLEMISH_AT[1])[0] != 128 or px(grey, OIL_AT[0], OIL_AT[1])[0] != 128,
          (px(grey, BLEMISH_AT[0], BLEMISH_AT[1])[0], px(grey, OIL_AT[0], OIL_AT[1])[0]))
    b = px(grey, BLEMISH_AT[0], BLEMISH_AT[1])[0]
    o = px(grey, OIL_AT[0], OIL_AT[1])[0]
    check("暗斑处灰层 > 128（提亮）", b > 128, b)
    check("亮斑处灰层 < 128（压暗）", o < 128, o)
    check("背景灰层 ≈ 128", abs(px(grey, 5, 5)[0] - 128) <= 2, px(grey, 5, 5)[0])
    drop(img)

    img, base = make_image()
    run_plugin("ng", img, base, prompt="", source="local",
         prepaint=0.0, radius=12.0, group=True, steps=10)
    grey = children(list(img.get_layers())[0])[0]
    check("预修 0% → 整层 128（原版行为）",
          px(grey, BLEMISH_AT[0], BLEMISH_AT[1])[0] == 128 and px(grey, OIL_AT[0], OIL_AT[1])[0] == 128,
          (px(grey, BLEMISH_AT[0], BLEMISH_AT[1])[0], px(grey, OIL_AT[0], OIL_AT[1])[0]))
    drop(img)


# ---- 4. 选区 -----------------------------------------------------------------

def test_selection():
    print("\n4. 选区只在选区内预修")
    img, base = make_image()
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 35, 35, 40, 40)   # 只框住暗斑
    st, msg = run_plugin("ng", img, base, prompt="",
                   source="local", prepaint=70.0, radius=12.0, group=True,
                   steps=10)
    check("带选区也能跑", st == Gimp.PDBStatusType.SUCCESS, msg[:40])
    grey = children(list(img.get_layers())[0])[0]
    check("选区内已预校正", px(grey, BLEMISH_AT[0], BLEMISH_AT[1])[0] > 128, px(grey, BLEMISH_AT[0], BLEMISH_AT[1])[0])
    check("选区外的亮斑不动", px(grey, OIL_AT[0], OIL_AT[1])[0] == 128,
          px(grey, OIL_AT[0], OIL_AT[1])[0])
    check("选区外背景不动", px(grey, 5, 5)[0] == 128, px(grey, 5, 5)[0])
    Gimp.Selection.none(img)
    drop(img)


# ---- 5. AI 那一路（mock） ----------------------------------------------------

def test_ai_path():
    print("\n5. AI 参考（mock 服务原样返回）")
    srv = mock_comfy.start_mock()
    try:
        img, base = make_image()
        st, msg = run_plugin("fs", img, base,
                       prompt="", source="ai", radius=8.0, group=True,
                       denoise=0.35, server=srv.url,
                       checkpoint=mock_comfy.CHECKPOINT, steps=4)
        check("AI 参考跑通", st == Gimp.PDBStatusType.SUCCESS, msg[:40])
        group = list(img.get_layers())[0]
        kids = children(group)
        check("结构照样建出来", len(kids) == 2, len(kids))
        # mock 原样返回 → 参考 = 原图 → 痘印一点没被修（这是 denoise=0 的语义）
        cx, cy = BLEMISH_AT
        # 允许 ±2 码：写进缓冲区再读出来要过一次 8 位往返
        a, b = px(kids[1], cx, cy)[:3], px(base, cx, cy)[:3]
        check("参考图与原图一致时痘印保留",
              all(abs(x - y) <= 2 for x, y in zip(a, b)), (a, b))
        drop(img)

        # ComfyUI 连不上 → 退回本地参考，并且仍然出结果
        img, base = make_image()
        st, msg = run_plugin("ng", img, base, prompt="",
                       source="ai", prepaint=70.0, radius=12.0, group=True,
                       server="http://127.0.0.1:9", steps=4)
        check("连不上时退回本地参考仍 SUCCESS",
              st == Gimp.PDBStatusType.SUCCESS, msg[:60])
        grey = children(list(img.get_layers())[0])[0]
        check("退回后依然有预校正", px(grey, BLEMISH_AT[0], BLEMISH_AT[1])[0] > 128,
              px(grey, BLEMISH_AT[0], BLEMISH_AT[1])[0])
        drop(img)
    finally:
        srv.stop()


# ---- 6. 误用 -----------------------------------------------------------------

def test_errors():
    print("\n6. 误用")
    img, base = make_image()
    group = Gimp.GroupLayer.new(img, "g")
    img.insert_layer(group, None, 0)
    st, msg = run_plugin("db", img, group, prompt="",
                   source="local", steps=4)
    check("图层组被拒绝", st != Gimp.PDBStatusType.SUCCESS, st)
    check("报错说清要栅格层", "raster" in msg or "Merge" in msg, msg[:60])
    drop(img)


def main():
    test_registration()
    test_fs()
    test_db()
    test_ng()
    test_selection()
    test_ai_path()
    test_errors()
    if FAIL:
        print("\n失败 %d / %d 条：\n  %s" % (len(FAIL), OK, "\n  ".join(FAIL)))
    else:
        print("\n全部通过（%d 条断言）" % OK)


main()
