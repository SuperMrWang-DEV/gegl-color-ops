# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 图层样式 / layer styles — 数学核心
 ---------------------------------------------------------------------------
 purpose   把 PS 的图层样式（投影 / 内阴影 / 外发光 / 内发光 / 斜面和浮雕 /
           光泽 / 颜色叠加 / 渐变叠加 / 图案叠加 / 描边）算成**一组 RGBA 图层**，
           再由插件把它们按层次插进 GIMP。纯 numpy，不 import GIMP，
           所以 tests / 预览 / 应用跑的是同一份代码。

           为什么输出「一组图层」而不是一张烤好的图：
             投影和发光要躲在内容**下面**（半透明内容会透出阴影，这是 PS 的
             行为），内阴影/斜面/叠加要压在内容**上面**。一张图做不到这一点，
             除非先把内容和效果自己合成一遍——那样用户就再也改不动内容了。

 note      五个非踩不可的：
           1. **混合模式交给 GEGL 做，颜色不要预混**。每个效果层带自己的
              LayerMode（投影 MULTIPLY、发光 SCREEN…），GIMP 会拿它和真正的
              下方内容混合。数学层里 pre-blend 一次，GIMP 里再 blend 一次，
              半透明边会黑一圈。
           2. **alpha 是 sRGB 域里的直通值**。GIMP 的 "R'G'B'A u8" 就是这一套，
              不要往线性空间转：转了以后 SCREEN 发光的亮度对不上，中间调会发灰。
           3. **描边和斜面要的是「带符号距离」，不是模糊**。用 blur 逼近
              3 px 描边，宽度会随内容对比度变（软边 alpha 被模糊摊薄），
              同一个参数在两块内容上厚度不一样。
           4. **斜面的法线从平滑后的 alpha 求**。直接对硬 alpha 求梯度，
              边界只剩一个像素的斜坡，光照结果是一条 1 px 的黑线；
              先把 alpha 用 size/2 模糊一次，斜坡才有宽度。
           5. **「挖空」不能只靠层叠顺序**。投影层放在内容下面，天然被内容挡住，
              那就是 PS 的「浅挖空」；「深挖空 / 无」要用 alpha 蒙版显式挖。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import json
import math

try:
    import numpy as np
except Exception:                                   # 没有 numpy：只有调用时才报错
    np = None


class NoNumpy(RuntimeError):
    pass


def have_numpy():
    return np is not None


def _need_numpy():
    if np is None:
        raise NoNumpy(
            "Layer styles need numpy. Run tools/install_gimp_numpy.py once "
            "(it installs the MSYS2 build that this GIMP's Python can load), "
            "then restart GIMP.")


# ---- 常量表 ---------------------------------------------------------------

# 渲染顺序 = PS 面板从下往上的顺序。outside 的那两个要排在内容下面。
EFFECT_ORDER = ("drop-shadow", "outer-glow", "inner-shadow", "inner-glow",
                "stroke", "pattern-overlay", "gradient-overlay",
                "color-overlay", "satin", "bevel")

EFFECT_LABEL = {
    "drop-shadow": "Drop Shadow",
    "outer-glow": "Outer Glow",
    "inner-shadow": "Inner Shadow",
    "inner-glow": "Inner Glow",
    "stroke": "Stroke",
    "pattern-overlay": "Pattern Overlay",
    "gradient-overlay": "Gradient Overlay",
    "color-overlay": "Color Overlay",
    "satin": "Satin",
    "bevel": "Bevel and Emboss",
}

# 放在内容**下面**的效果。其余都在内容上面。
BELOW_CONTENT = ("drop-shadow", "outer-glow")

# PS 面板里从上往下的显示顺序（UI 用）
PANEL_ORDER = ("bevel", "satin", "color-overlay", "gradient-overlay",
               "pattern-overlay", "stroke", "inner-glow", "inner-shadow",
               "outer-glow", "drop-shadow")

# 混合模式：(id, 面板名, GIMP LayerMode id, 数学实现名)
MODES = (
    ("normal", "Normal", "NORMAL"),
    ("darken", "Darken", "DARKEN_ONLY"),
    ("multiply", "Multiply", "MULTIPLY"),
    ("colorburn", "Color Burn", "BURN"),
    ("linearburn", "Linear Burn", "LINEAR_BURN"),
    ("lighten", "Lighten", "LIGHTEN_ONLY"),
    ("screen", "Screen", "SCREEN"),
    ("colordodge", "Color Dodge", "DODGE"),
    ("lineardodge", "Linear Dodge (Add)", "LINEAR_DODGE"),
    ("overlay", "Overlay", "OVERLAY"),
    ("softlight", "Soft Light", "SOFTLIGHT"),
    ("hardlight", "Hard Light", "HARDLIGHT"),
    ("vividlight", "Vivid Light", "VIVID_LIGHT"),
    ("pinlight", "Pin Light", "PIN_LIGHT"),
    ("linearlight", "Linear Light", "LINEAR_LIGHT"),
    ("hardmix", "Hard Mix", "HARD_MIX"),
    ("difference", "Difference", "DIFFERENCE"),
    ("exclusion", "Exclusion", "EXCLUSION"),
    ("subtract", "Subtract", "SUBTRACT"),
    ("divide", "Divide", "DIVIDE"),
    ("hue", "Hue", "HUE"),
    ("saturation", "Saturation", "SATURATION"),
    ("color", "Color", "COLOR"),
    ("luminosity", "Luminosity", "VALUE"),
    ("darkercolor", "Darker Color", "LUMA_DARKEN_ONLY"),
    ("lightercolor", "Lighter Color", "LUMA_LIGHTEN_ONLY"),
)
MODE_IDS = tuple(m[0] for m in MODES)
MODE_LABEL = dict((m[0], m[1]) for m in MODES)
MODE_GIMP = dict((m[0], m[2]) for m in MODES)

CONTOURS = ("linear", "cone", "cone-inverted", "gauss", "ring", "ring-double",
            "hollow", "rolling-slope", "sawtooth", "sawtooth-double",
            "notched", "half-round")

BEVEL_STYLES = ("outer", "inner", "emboss", "pillow", "stroke")
BEVEL_METHODS = ("smooth", "chisel-hard", "chisel-soft")
GRADIENT_STYLES = ("linear", "radial", "angle", "reflected", "diamond")
GLOW_METHODS = ("softer", "precise")
STROKE_POS = ("outside", "inside", "center")
FILL_TYPES = ("color", "gradient", "pattern")
KNOCKOUTS = ("none", "shallow", "deep")

DEFAULT_GLOBAL_ANGLE = 120.0
DEFAULT_ALTITUDE = 30.0


# ---- 参数表 ---------------------------------------------------------------
# (键, 类型, 默认值, 下限, 上限, 面板标签)
#   bool / int / float / percent / color / choice
# 所有角度都是 PS 的约定：0 = 正右，逆时针为正（屏幕上 y 向下，所以算的时候取负）。

SPECS = {
    "drop-shadow": (
        ("mode", "choice", "multiply", MODES, "Blend mode"),
        ("color", "color", (0, 0, 0), None, None, "Color"),
        ("opacity", "percent", 75, 0, 100, "Opacity"),
        ("angle", "float", 120.0, -180.0, 180.0, "Angle"),
        ("use_global", "bool", True, None, None, "Use global light"),
        ("distance", "float", 5.0, 0.0, 300.0, "Distance"),
        ("spread", "percent", 0, 0, 100, "Spread"),
        ("size", "float", 5.0, 0.0, 250.0, "Size"),
        ("contour", "choice", "linear", CONTOURS, "Contour"),
        ("noise", "percent", 0, 0, 100, "Noise"),
        ("knockout", "choice", "shallow", KNOCKOUTS, "Knockout"),
    ),
    "inner-shadow": (
        ("mode", "choice", "multiply", MODES, "Blend mode"),
        ("color", "color", (0, 0, 0), None, None, "Color"),
        ("opacity", "percent", 75, 0, 100, "Opacity"),
        ("angle", "float", 120.0, -180.0, 180.0, "Angle"),
        ("use_global", "bool", True, None, None, "Use global light"),
        ("distance", "float", 5.0, 0.0, 300.0, "Distance"),
        ("choke", "percent", 0, 0, 100, "Choke"),
        ("size", "float", 5.0, 0.0, 250.0, "Size"),
        ("contour", "choice", "linear", CONTOURS, "Contour"),
        ("noise", "percent", 0, 0, 100, "Noise"),
    ),
    "outer-glow": (
        ("mode", "choice", "screen", MODES, "Blend mode"),
        ("color", "color", (0.99, 0.98, 0.53), None, None, "Color"),
        ("opacity", "percent", 75, 0, 100, "Opacity"),
        ("method", "choice", "softer", GLOW_METHODS, "Technique"),
        ("spread", "percent", 0, 0, 100, "Spread"),
        ("size", "float", 8.0, 0.0, 250.0, "Size"),
        ("contour", "choice", "linear", CONTOURS, "Contour"),
        ("range", "percent", 50, 1, 100, "Range"),
        ("gradient", "bool", False, None, None, "Gradient fill"),
        ("noise", "percent", 0, 0, 100, "Noise"),
    ),
    "inner-glow": (
        ("mode", "choice", "screen", MODES, "Blend mode"),
        ("color", "color", (0.99, 0.98, 0.53), None, None, "Color"),
        ("opacity", "percent", 75, 0, 100, "Opacity"),
        ("method", "choice", "softer", GLOW_METHODS, "Technique"),
        ("source", "choice", "edge", (("edge", "Edge"), ("center", "Center")),
         "Source"),
        ("choke", "percent", 0, 0, 100, "Choke"),
        ("size", "float", 8.0, 0.0, 250.0, "Size"),
        ("contour", "choice", "linear", CONTOURS, "Contour"),
        ("range", "percent", 50, 1, 100, "Range"),
        ("gradient", "bool", False, None, None, "Gradient fill"),
        ("noise", "percent", 0, 0, 100, "Noise"),
    ),
    "bevel": (
        ("style", "choice", "inner", BEVEL_STYLES, "Style"),
        ("method", "choice", "smooth", BEVEL_METHODS, "Technique"),
        ("depth", "percent", 100, 1, 1000, "Depth"),
        ("direction", "choice", "up", (("up", "Up"), ("down", "Down")),
         "Direction"),
        ("size", "float", 5.0, 1.0, 250.0, "Size"),
        ("soften", "float", 0.0, 0.0, 40.0, "Soften"),
        ("angle", "float", 120.0, -180.0, 180.0, "Angle"),
        ("use_global", "bool", True, None, None, "Use global light"),
        ("altitude", "float", 30.0, 0.0, 90.0, "Altitude"),
        ("highlight_mode", "choice", "screen", MODES, "Highlight mode"),
        ("highlight_color", "color", (1, 1, 1), None, None, "Highlight color"),
        ("highlight_opacity", "percent", 75, 0, 100, "Highlight opacity"),
        ("shadow_mode", "choice", "multiply", MODES, "Shadow mode"),
        ("shadow_color", "color", (0, 0, 0), None, None, "Shadow color"),
        ("shadow_opacity", "percent", 75, 0, 100, "Shadow opacity"),
        ("stroke_size", "float", 3.0, 1.0, 100.0, "Stroke size (stroke style)"),
    ),
    "satin": (
        ("mode", "choice", "multiply", MODES, "Blend mode"),
        ("color", "color", (0, 0, 0), None, None, "Color"),
        ("opacity", "percent", 50, 0, 100, "Opacity"),
        ("angle", "float", 19.0, -180.0, 180.0, "Angle"),
        ("distance", "float", 11.0, 0.0, 300.0, "Distance"),
        ("size", "float", 14.0, 0.0, 250.0, "Size"),
        ("invert", "bool", False, None, None, "Invert"),
    ),
    "color-overlay": (
        ("mode", "choice", "normal", MODES, "Blend mode"),
        ("color", "color", (1, 0, 0), None, None, "Color"),
        ("opacity", "percent", 100, 0, 100, "Opacity"),
    ),
    "gradient-overlay": (
        ("mode", "choice", "normal", MODES, "Blend mode"),
        ("opacity", "percent", 100, 0, 100, "Opacity"),
        ("style", "choice", "linear", GRADIENT_STYLES, "Style"),
        ("angle", "float", 90.0, -180.0, 180.0, "Angle"),
        ("scale", "percent", 100, 1, 1000, "Scale"),
        ("reverse", "bool", False, None, None, "Reverse"),
        ("align", "bool", True, None, None, "Align with layer"),
    ),
    "pattern-overlay": (
        ("mode", "choice", "normal", MODES, "Blend mode"),
        ("opacity", "percent", 100, 0, 100, "Opacity"),
        ("scale", "percent", 100, 1, 1000, "Scale"),
        ("align", "bool", True, None, None, "Align with layer"),
    ),
    "stroke": (
        ("mode", "choice", "normal", MODES, "Blend mode"),
        ("opacity", "percent", 100, 0, 100, "Opacity"),
        ("size", "float", 3.0, 0.5, 200.0, "Size"),
        ("position", "choice", "outside", STROKE_POS, "Position"),
        ("fill", "choice", "color", FILL_TYPES, "Fill"),
        ("color", "color", (1, 0, 0), None, None, "Color"),
        ("gradient_style", "choice", "linear", GRADIENT_STYLES,
         "Gradient style"),
        ("gradient_angle", "float", 90.0, -180.0, 180.0, "Gradient angle"),
        ("pattern_scale", "percent", 100, 1, 1000, "Pattern scale"),
    ),
}

# 「混合选项」单独一张表：它作用于图层本身，不是效果层。
BLEND_SPECS = (
    ("fill_opacity", "percent", 100, 0, 100, "Fill opacity"),
    ("knockout", "choice", "none", KNOCKOUTS, "Knockout"),
    ("blend_if_source", "bool", False, None, None, "Blend if: this layer"),
    ("blend_if_lo", "percent", 0, 0, 100, "This layer: black"),
    ("blend_if_lo_split", "percent", 0, 0, 100, "  ↳ softness"),
    ("blend_if_hi", "percent", 100, 0, 100, "This layer: white"),
    ("blend_if_hi_split", "percent", 0, 0, 100, "  ↳ softness"),
)


def default_style():
    st = {"global_angle": DEFAULT_GLOBAL_ANGLE,
          "global_altitude": DEFAULT_ALTITUDE,
          "blend": {}, "effects": {}}
    for key, _kind, dflt, *_rest in BLEND_SPECS:
        st["blend"][key] = dflt
    st["blend"]["fill_opacity"] = 100
    st["blend"]["knockout"] = "none"
    for name in EFFECT_ORDER:
        eff = {}
        for key, kind, dflt, *_rest in SPECS[name]:
            eff[key] = dflt
        eff["enabled"] = False
        st["effects"][name] = eff
    # 默认打开投影，第一次点菜单就能看见东西
    st["effects"]["drop-shadow"]["enabled"] = True
    return st


def clone_style(st):
    return json.loads(json.dumps(st))


def format_style(st):
    """紧凑 JSON（脚本可读、可回放）。"""
    return json.dumps(st, sort_keys=True, separators=(",", ":"))


def pretty_style(st, indent=1):
    """给人看的同一份代码：换行缩进，方便选中复制、肉眼核对。

    JSON 里的空白不影响解析，所以这份也能直接当 `style` 参数喂回去。
    ensure_ascii 保持默认 True —— 全是 ASCII，粘到任何地方都不会被编码搞坏。
    """
    return json.dumps(st, sort_keys=True, indent=indent)


class StyleCodeError(ValueError):
    """粘进来的不是一份样式代码。"""


def _clamp(value, lo, hi):
    try:
        v = float(value)
    except Exception:
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    return v


def _coerce(kind, value, default, lo, hi, options, label, warns):
    """按规格把一个值掰回合法范围。掰不动就退回默认值并记一条警告。"""
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        warns.append("bool expected for %s" % label)
        return default
    if kind == "color":
        try:
            seq = [float(x) for x in value][:3]
        except Exception:
            warns.append("colour expected for %s" % label)
            return default
        if len(seq) < 3 or any(x != x for x in seq):
            warns.append("colour expected for %s" % label)
            return default
        # 有人从别处抄 0–255 的写法：明显超过 1 就按 0–255 解读
        if max(seq) > 1.0001:
            seq = [x / 255.0 for x in seq]
            warns.append("%s looked like 0-255, divided by 255" % label)
        # 整数就写成整数：默认样式里是 [1,1,1]，往返一趟不该变成 [1.0,1.0,1.0]
        return [(int(x) if x % 1 == 0 else x)
                for x in (min(1.0, max(0.0, v)) for v in seq)]
    if kind == "choice":
        ids = []
        for opt in (options or ()):
            ids.append(opt[0] if isinstance(opt, (tuple, list)) else opt)
        if str(value) in ids:
            return str(value)
        warns.append("%s=%r not one of %s" % (label, value, "/".join(ids)))
        return default
    v = _clamp(value, lo, hi)
    if v is None:
        warns.append("number expected for %s" % label)
        return default
    if kind in ("percent", "int"):
        return int(round(v))
    # 原来是整数就写回整数：5 和 5.0 数值一样，但代码串要逐字节一致，
    # 否则「复制 → 粘贴」拿到的字符串跟原来的不一样，比对起来很别扭。
    if isinstance(value, int) and not isinstance(value, bool) and v == value:
        return int(v)
    return round(v, 4)


def read_style_code(text):
    """粘贴进来的代码 → (style, warnings)；不是代码就抛 StyleCodeError。

    比 parse_style 严格：parse_style 是「读不出来就给默认」，适合 PDB 参数；
    这里是用户主动粘了一坨东西，静默改成默认会让人以为粘贴成功了，所以
    必须报错。反过来，能读但超出范围的数字不报错——夹到边界并记一条警告，
    这样从旧版本或别的机器上拿来的代码仍然能用。
    """
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    text = (text or "").strip()
    if not text:
        raise StyleCodeError("empty")
    raw = text
    for _ in range(2):                     # 容忍被再编码过一次（""{...}""）
        if not isinstance(raw, str):
            break
        try:
            raw = json.loads(raw)
        except Exception as exc:
            raise StyleCodeError(str(exc))
    if not isinstance(raw, dict):
        raise StyleCodeError("expected a JSON object")
    if "effects" not in raw and "blend" not in raw:
        raise StyleCodeError("no \"effects\" / \"blend\" in it")

    st = default_style()
    # 从「全关」起步：代码里没提到的效果就别偷偷开一个默认投影，否则粘一份
    # 手写的三行代码上去，结果凭空多一个阴影，很莫名其妙。
    # 完整复制的代码里每个效果都带 enabled，所以这么改不影响它。
    for name in st["effects"]:
        st["effects"][name]["enabled"] = False
    warns = []
    for key in ("global_angle", "global_altitude"):
        if key in raw:
            v = _clamp(raw[key], -180.0, 180.0)
            if v is None:
                warns.append("number expected for %s" % key)
            else:
                st[key] = v

    blend_raw = raw.get("blend") or {}
    if not isinstance(blend_raw, dict):
        raise StyleCodeError("\"blend\" is not an object")
    effects_raw = raw.get("effects") or {}
    if not isinstance(effects_raw, dict):
        raise StyleCodeError("\"effects\" is not an object")

    for key, value in blend_raw.items():
        if key not in st["blend"]:
            warns.append("unknown blend key %r" % key)
            continue
        item = next((i for i in BLEND_SPECS if i[0] == key), None)
        if item is None:
            continue
        key, kind, dflt = item[0], item[1], item[2]
        if kind == "choice":               # ("x","choice",默认,选项,标签)
            options, lo, hi, label = item[3], None, None, item[4]
        else:                              # ("x",类型,默认,下界,上界,标签)
            options, lo, hi, label = None, item[3], item[4], item[5]
        st["blend"][key] = _coerce(kind, value, dflt, lo, hi, options,
                                   label, warns)

    for name, eff in effects_raw.items():
        if name not in st["effects"]:
            warns.append("unknown effect %r" % name)
            continue
        if not isinstance(eff, dict):
            warns.append("%s: expected an object" % name)
            continue
        for item in SPECS[name]:
            key, kind, dflt = item[0], item[1], item[2]
            if kind == "choice":
                lo = hi = None
                options = item[3]
                label = item[4]
            else:
                lo, hi = item[3], item[4]
                options = None
                label = item[5]
            if key in eff:
                st["effects"][name][key] = _coerce(
                    kind, eff[key], dflt, lo, hi, options,
                    "%s.%s" % (name, key), warns)
        if "enabled" in eff:
            st["effects"][name]["enabled"] = bool(eff["enabled"])
        elif eff:
            # 手写 / 手改的代码通常不写 enabled：给了参数就当要开，
            # 否则粘贴一份自己写的代码会得到一片空白，看不出为什么。
            st["effects"][name]["enabled"] = True
    return st, warns


def adopt_style(dest, src):
    """把 src 原地写进 dest，**保住 effects[name] 这个 dict 的身份**。

    对话框里每个参数页握着自己那一格 dict 的引用（改滑杆直接写进去），
    整个换掉 ctx["style"] 会让那些引用指向旧对象——页面从此改不动数据，
    预览也不再跟着动，而且看不出哪里错了。
    """
    if not isinstance(dest, dict) or not isinstance(src, dict):
        return dest
    for key in ("global_angle", "global_altitude"):
        if key in src:
            dest[key] = src[key]
    blend = dest.setdefault("blend", {})
    for key, value in (src.get("blend") or {}).items():
        blend[key] = value
    effects = dest.setdefault("effects", {})
    for name, eff in (src.get("effects") or {}).items():
        target = effects.setdefault(name, {})
        for key, value in eff.items():
            target[key] = value
    return dest


def parse_style(text):
    """从字符串读回样式。空串 / 坏串 → 默认样式（宁可少一个参数，不能炸）。"""
    st = default_style()
    if not text:
        return st
    try:
        raw = json.loads(text)
    except Exception:
        return st
    if not isinstance(raw, dict):
        return st
    for key in ("global_angle", "global_altitude"):
        if isinstance(raw.get(key), (int, float)):
            st[key] = float(raw[key])
    blend_raw = raw.get("blend") or {}
    if not isinstance(blend_raw, dict):
        raise StyleCodeError("\"blend\" is not an object")
    effects_raw = raw.get("effects") or {}
    if not isinstance(effects_raw, dict):
        raise StyleCodeError("\"effects\" is not an object")

    for key, value in blend_raw.items():
        if key in st["blend"]:
            st["blend"][key] = value
    for name, eff in effects_raw.items():
        if name not in st["effects"] or not isinstance(eff, dict):
            continue
        for key, value in eff.items():
            if key in st["effects"][name]:
                st["effects"][name][key] = value
    return st


def enabled_effects(st):
    return [n for n in EFFECT_ORDER
            if st["effects"].get(n, {}).get("enabled")]


# ---- 基础工具 -------------------------------------------------------------

def to_float(rgba, w, h):
    """u8 RGBA 字节 → (h, w, 4) float32，0..1（sRGB 直通值）。"""
    _need_numpy()
    a = np.frombuffer(rgba, dtype=np.uint8, count=w * h * 4)
    return (a.reshape(h, w, 4).astype(np.float32) / np.float32(255.0))


def to_bytes(arr):
    _need_numpy()
    a = np.clip(arr * np.float32(255.0) + np.float32(0.5), 0, 255)
    return a.astype(np.uint8).tobytes()


def _box(a, r, axis):
    if r < 1:
        return a
    m = np.moveaxis(a, axis, 0)
    n = m.shape[0]
    pad = ((r + 1, r),) + ((0, 0),) * (m.ndim - 1)
    p = np.pad(m, pad, mode="edge")
    cs = np.cumsum(p, axis=0, dtype=np.float32)
    cs = np.concatenate([np.zeros_like(cs[:1]), cs], axis=0)
    span = 2 * r + 1
    return np.moveaxis((cs[span:span + n] - cs[0:n]) / span, 0, axis)


def _gauss_radii(sigma, boxes=3):
    if sigma <= 0:
        return []
    ideal = math.sqrt((12.0 * sigma * sigma / boxes) + 1.0)
    wl = int(math.floor(ideal))
    if wl % 2 == 0:
        wl -= 1
    wl = max(1, wl)
    wu = wl + 2
    m_ideal = (12.0 * sigma * sigma - boxes * wl * wl - 4.0 * boxes * wl
               - 3.0 * boxes) / (-4.0 * wl - 4.0)
    m = max(0, min(boxes, int(round(m_ideal))))
    return [(s - 1) // 2 for s in ([wl] * m + [wu] * (boxes - m))]


def gaussian(a, sigma):
    """可分离高斯（三次盒式逼近）。边缘按复制，纯色图不会发黑。"""
    _need_numpy()
    if sigma <= 0:
        return a
    cur = a
    for r in _gauss_radii(sigma):
        if r >= 1:
            cur = _box(_box(cur, r, 0), r, 1)
    return cur


def shift2(a, dx, dy):
    """平移，出界补 0（PS 的偏移效果也是直接出界，不留边）。"""
    _need_numpy()
    ih, iw = a.shape[:2]
    dx, dy = int(round(dx)), int(round(dy))
    out = np.zeros_like(a)
    if abs(dx) >= iw or abs(dy) >= ih:
        return out
    # 正的 dy 往下挪：目标从 dy 行起，取源的第 0 行起
    ys, yd = (slice(0, ih - dy), slice(dy, None)) if dy >= 0 else \
             (slice(-dy, None), slice(0, ih + dy))
    xs, xd = (slice(0, iw - dx), slice(dx, None)) if dx >= 0 else \
             (slice(-dx, None), slice(0, iw + dx))
    out[yd, xd] = a[ys, xs]
    return out


def _edt(mask, max_d):
    """每个像素到最近 True 的欧氏距离，上限 max_d（超出记 max_d）。

    横向一次向量化到底（左右最近源索引），纵向按 ±k 行做下包络搜索。
    纯 blur 做不到「精确 N 像素」——软边 alpha 会被摊薄，同一个描边在
    两块内容上厚度不一样，所以这里老老实实算距离。
    """
    _need_numpy()
    h, w = mask.shape
    big = np.float32(1e12)
    idx = np.arange(w, dtype=np.float32)
    left = np.maximum.accumulate(np.where(mask, idx, np.float32(-1.0)), axis=1)
    right = np.where(mask, idx, np.float32(w + 1.0))
    right = np.minimum.accumulate(right[:, ::-1], axis=1)[:, ::-1]
    dl = np.where(left >= 0, idx - left, np.float32(w + 1.0))
    dr = np.where(right <= w, right - idx, np.float32(w + 1.0))
    V = np.minimum(dl * dl, dr * dr).astype(np.float32)
    D = V.copy()
    R = int(max(0, min(h - 1, math.ceil(max_d))))
    for k in range(1, R + 1):
        kk = np.float32(k * k)
        np.minimum(D[k:, :], V[:-k, :] + kk, out=D[k:, :])
        np.minimum(D[:-k, :], V[k:, :] + kk, out=D[:-k, :])
    return np.minimum(np.sqrt(D).astype(np.float32), np.float32(max_d))


def signed_distance(alpha, max_d):
    """带符号距离：内容内部为正、外部为负（阈值取 0.5，和 PS 一致）。"""
    m = alpha > 0.5
    if not m.any():
        return np.full(alpha.shape, -max_d, dtype=np.float32)
    if m.all():
        return np.full(alpha.shape, max_d, dtype=np.float32)
    d_out = _edt(m, max_d)                 # 内容内为 0
    d_in = _edt(~m, max_d)                 # 背景内为 0
    return np.where(m, d_in, -d_out).astype(np.float32)


def spread_curve(a, amount):
    """PS 的「扩展 / 收缩 / 阻塞」：把 50% 等值线钉住，斜率加大。

    amount 0..1。1 就是完全阈值化（硬边）。
    """
    if amount <= 0:
        return a
    thr = 0.5 * min(1.0, amount)
    # 斜率取「让 0.5 留在 0.5」的那一支：thr→0.5 时 k→∞，就是阈值化。
    k = 0.5 / max(1e-4, 0.5 - thr)
    return np.clip((a - thr) * k, 0.0, 1.0).astype(np.float32)


def contour_lut(kind="linear", n=256):
    """12 条 PS 预设等高线，返回长度 n 的 0..1 表。"""
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    if kind == "linear":
        v = t
    elif kind == "cone":
        v = 1.0 - np.abs(2.0 * t - 1.0)
    elif kind == "cone-inverted":
        v = np.abs(2.0 * t - 1.0)
    elif kind == "gauss":
        v = np.exp(-((t - 0.5) / 0.22) ** 2)
    elif kind == "ring":
        v = 1.0 - np.abs(np.sin(t * math.pi * 2.0))
    elif kind == "ring-double":
        v = np.abs(np.sin(t * math.pi * 2.0)) ** 0.6
    elif kind == "hollow":
        v = np.abs(2.0 * t - 1.0) ** 2.2
    elif kind == "rolling-slope":
        v = 0.5 - 0.5 * np.cos(t * math.pi * 2.0)
    elif kind == "sawtooth":
        v = np.abs(((t * 2.0) % 1.0) * 2.0 - 1.0)
    elif kind == "sawtooth-double":
        v = ((t * 3.0) % 1.0)
    elif kind == "notched":
        v = np.clip(1.0 - np.abs(2.0 * t - 1.0) * 3.0, 0.0, 1.0)
    elif kind == "half-round":
        v = np.sqrt(np.clip(1.0 - (t - 1.0) ** 2, 0.0, 1.0))
    else:
        v = t
    v = np.clip(v, 0.0, 1.0).astype(np.float32)
    v[0], v[-1] = 0.0, 1.0
    return v


def _apply_contour(a, kind, amount=1.0):
    lut = contour_lut(kind)
    n = lut.shape[0]
    pos = np.clip(a, 0.0, 1.0) * (n - 1)
    i0 = np.floor(pos).astype(np.int32)
    i0 = np.clip(i0, 0, n - 2)
    f = (pos - i0).astype(np.float32)
    mapped = lut[i0] * (1.0 - f) + lut[i0 + 1] * f
    if amount >= 0.999:
        return mapped
    return (a * (1.0 - amount) + mapped * amount).astype(np.float32)


def _noise(a, amount, seed=1234):
    """效果上的「杂色」：只调制 alpha，不碰颜色。amount 0..1。"""
    if amount <= 0:
        return a
    rs = np.random.RandomState(seed)
    n = rs.rand(*a.shape).astype(np.float32)
    # PS 的杂色是「加性抖动」，0..1 → 最多 ±50% 的密度起伏
    return np.clip(a * (1.0 - 0.5 * amount) + n * a * amount, 0.0, 1.0)


# ---- 渐变 / 图案 ----------------------------------------------------------

def gradient_lut(stops, n=256):
    """色标 → 长度 n 的 (r,g,b) 表。stops = [(pos, (r,g,b)), …]，pos 0..1。"""
    _need_numpy()
    if not stops:
        stops = [(0.0, (0.0, 0.0, 0.0)), (1.0, (1.0, 1.0, 1.0))]
    stops = sorted(stops, key=lambda s: s[0])
    t = np.linspace(0.0, 1.0, n)
    out = np.zeros((n, 3), dtype=np.float32)
    for ch in range(3):
        xs = np.array([s[0] for s in stops], dtype=np.float64)
        ys = np.array([s[1][ch] for s in stops], dtype=np.float64)
        out[:, ch] = np.interp(t, xs, ys)
    return out


def gradient_field(w, h, style="linear", angle=90.0, scale=1.0, reverse=False,
                   bbox=None):
    """渐变参数场 t(x,y) ∈ [0,1]。bbox = (x0, y0, x1, y1)（图层坐标）。"""
    _need_numpy()
    if bbox is None:
        bbox = (0.0, 0.0, float(w), float(h))
    x0, y0, x1, y1 = [float(v) for v in bbox]
    cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    ew, eh = max(1.0, x1 - x0), max(1.0, y1 - y0)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    sx = max(0.01, scale)
    dx = (xs - cx) / (ew * 0.5 * sx)
    dy = (ys - cy) / (eh * 0.5 * sx)
    a = math.radians(float(angle))
    ca, sa = math.cos(a), math.sin(a)
    # 屏幕 y 向下：角度 0° = 从左到右，90° = 从下到上（PS 的约定）。
    # 所以投到渐变轴上的坐标是 (dx·cos − dy·sin)。
    if style == "radial":
        t = np.sqrt(dx * dx + dy * dy) * 0.5
    elif style == "angle":
        t = (np.arctan2(dy, dx) / (2 * math.pi)) % 1.0
        t = (t + 0.5) % 1.0
    elif style == "reflected":
        # 对称：从中心向两侧各跑一遍 0→1
        u = (dx * ca - dy * sa) * 0.5
        t = np.abs(u) * 2.0
    elif style == "diamond":
        t = (np.abs(dx) + np.abs(dy)) * 0.5
    else:                                   # linear
        u = (dx * ca - dy * sa) * 0.5
        t = u + 0.5
    t = np.clip(t, 0.0, 1.0).astype(np.float32)
    if reverse:
        t = 1.0 - t
    return t


def pattern_field(unit, w, h, scale=1.0, bbox=None, offset=(0, 0)):
    """图案平铺 → (h,w,3) 颜色场。unit = (ph, pw, 3|4) float 数组。"""
    _need_numpy()
    if unit is None:
        return np.ones((h, w, 3), dtype=np.float32)
    ph, pw = unit.shape[0], unit.shape[1]
    s = max(0.01, float(scale))
    tw, th = max(1, int(round(pw * s))), max(1, int(round(ph * s)))
    # 先按整数缩放（最近邻）+ 平铺，够用且不引入插值开销
    reps = (h // th + 2, w // tw + 2)
    tile = unit
    if (tw, th) != (pw, ph):
        yi = (np.arange(th) * (ph / float(th))).astype(np.int32).clip(0, ph - 1)
        xi = (np.arange(tw) * (pw / float(tw))).astype(np.int32).clip(0, pw - 1)
        tile = unit[yi][:, xi]
    rgb = np.tile(tile[..., :3], (reps[0], reps[1], 1))
    oy = int(offset[1]) % th
    ox = int(offset[0]) % tw
    return rgb[oy:oy + h, ox:ox + w].astype(np.float32)


# ---- 混合模式 -------------------------------------------------------------

def _lum(c):
    return (c[..., 0] * 0.3 + c[..., 1] * 0.59 + c[..., 2] * 0.11)


def _clip_color(c):
    l = _lum(c)[..., None]
    n = c.min(axis=-1)[..., None]
    x = c.max(axis=-1)[..., None]
    c = np.where(n < 0, l + (c - l) * l / np.maximum(l - n, 1e-6), c)
    c = np.where(x > 1, l + (c - l) * (1 - l) / np.maximum(x - l, 1e-6), c)
    return np.clip(c, 0.0, 1.0)


def _set_lum(c, l):
    d = l - _lum(c)
    return _clip_color(c + d[..., None])


def _sat(c):
    return c.max(axis=-1) - c.min(axis=-1)


def _set_sat(c, s):
    mn = c.min(axis=-1)[..., None]
    mx = c.max(axis=-1)[..., None]
    rng = np.maximum(mx - mn, 1e-6)
    return np.clip((c - mn) * (s[..., None] / rng), 0.0, 1.0)


def blend_rgb(cb, cs, mode):
    """PS 的混合模式函数 B(cb, cs)，逐通道，数组友好。"""
    _need_numpy()
    cb = np.clip(cb, 0.0, 1.0).astype(np.float32)
    cs = np.clip(cs, 0.0, 1.0).astype(np.float32)
    if mode in (None, "", "normal"):
        return cs
    if mode == "darken":
        return np.minimum(cb, cs)
    if mode == "lighten":
        return np.maximum(cb, cs)
    if mode == "multiply":
        return cb * cs
    if mode == "screen":
        return 1.0 - (1.0 - cb) * (1.0 - cs)
    if mode == "colorburn":
        return np.where(cs <= 0.0, 0.0,
                        np.where(cb >= 1.0, 1.0,
                                 1.0 - np.minimum(1.0, (1.0 - cb) /
                                                  np.maximum(cs, 1e-6))))
    if mode == "linearburn":
        return np.clip(cb + cs - 1.0, 0.0, 1.0)
    if mode == "colordodge":
        return np.where(cs >= 1.0, 1.0,
                        np.where(cb <= 0.0, 0.0,
                                 np.minimum(1.0, cb / np.maximum(1.0 - cs,
                                                                 1e-6))))
    if mode == "lineardodge":
        return np.clip(cb + cs, 0.0, 1.0)
    if mode == "overlay":
        return np.where(cb <= 0.5, 2.0 * cb * cs,
                        1.0 - 2.0 * (1.0 - cb) * (1.0 - cs))
    if mode == "hardlight":
        return np.where(cs <= 0.5, 2.0 * cb * cs,
                        1.0 - 2.0 * (1.0 - cb) * (1.0 - cs))
    if mode == "softlight":
        d = np.where(cb <= 0.25,
                     ((16.0 * cb - 12.0) * cb + 4.0) * cb, np.sqrt(
                         np.maximum(cb, 0.0)))
        return np.where(cs <= 0.5, cb - (1.0 - 2.0 * cs) * cb * (1.0 - cb),
                        cb + (2.0 * cs - 1.0) * (d - cb))
    if mode == "vividlight":
        return np.where(cs <= 0.5,
                        np.clip(1.0 - (1.0 - cb) / np.maximum(2.0 * cs, 1e-6),
                                0.0, 1.0),
                        np.clip(cb / np.maximum(2.0 * (1.0 - cs), 1e-6),
                                0.0, 1.0))
    if mode == "pinlight":
        return np.where(cb > 2.0 * cs, 2.0 * cs,
                        np.where(cb < 2.0 * cs - 1.0, 2.0 * cs - 1.0, cb))
    if mode == "linearlight":
        return np.clip(cb + 2.0 * cs - 1.0, 0.0, 1.0)
    if mode == "hardmix":
        return np.where(cb + cs >= 1.0, 1.0, 0.0)
    if mode == "difference":
        return np.abs(cb - cs)
    if mode == "exclusion":
        return cb + cs - 2.0 * cb * cs
    if mode == "subtract":
        return np.clip(cb - cs, 0.0, 1.0)
    if mode == "divide":
        return np.where(cb >= 0.0, np.clip(
            cb / np.maximum(cs, 1e-4), 0.0, 1.0), cb)
    if mode == "hue":
        return _set_lum(_set_sat(cs, _sat(cb)), _lum(cb))
    if mode == "saturation":
        return _set_lum(_set_sat(cb, _sat(cs)), _lum(cb))
    if mode == "color":
        return _set_lum(cs, _lum(cb))
    if mode == "luminosity":
        return _set_lum(cb, _lum(cs))
    if mode == "darkercolor":
        return np.where((_lum(cs) < _lum(cb))[..., None], cs, cb)
    if mode == "lightercolor":
        return np.where((_lum(cs) > _lum(cb))[..., None], cs, cb)
    return cs


def composite_one(dst, src, mode="normal", opacity=1.0):
    """把 (h,w,4) 的 src 按混合模式叠到 dst 上（W3C / GEGL 的通用公式）。"""
    _need_numpy()
    if opacity <= 0:
        return dst
    sa = (src[..., 3:4] * float(opacity)).astype(np.float32)
    da = dst[..., 3:4]
    cb = dst[..., :3]
    cs = src[..., :3]
    blended = blend_rgb(cb, cs, mode)
    out_a = sa + da * (1.0 - sa)
    out_c = (sa * (1.0 - da) * cs + sa * da * blended
             + (1.0 - sa) * da * cb)
    safe = np.maximum(out_a, 1e-6)
    rgb = np.where(out_a > 1e-6, out_c / safe, cb)
    out = np.concatenate([rgb, out_a], axis=-1).astype(np.float32)
    return np.clip(out, 0.0, 1.0)


def preblend_layer(acc, src, mode):
    """把「效果层 + 混合模式」压成一层**等价的不透明度层**（NORMAL 就能叠）。

    为什么非要做这一步：GIMP 3 默认的混合模式是「非 legacy」的，它在
    **线性光**里做合成（实测 50% 的 204 叠在 51 上是 153 而不是 128）。
    PS 是在 sRGB 值上混合的。直接在 GIMP 里挂 MULTIPLY，边缘和中间调会
    跟 PS 差一截；而且 alpha 的 over 也在线性光里，柔边会发亮。

    所以混合在这里算完，交给 GIMP 的只剩 NORMAL_LEGACY（纯 sRGB over）。
    代价是效果层的颜色里带上了「下方是什么」的痕迹 —— 挪动它会跟着错，
    但图层样式本来就不是让你挪的。
    """
    _need_numpy()
    if mode in (None, "", "normal"):
        return src
    sa = src[..., 3:4]
    da = acc[..., 3:4]
    cs = src[..., :3]
    cb = acc[..., :3]
    blended = blend_rgb(cb, cs, mode)
    rgb = (1.0 - da) * cs + da * blended
    out = np.concatenate([rgb, sa], axis=-1)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def composite(layers, base=None, w=0, h=0):
    """layers: [{rgba(float), mode, opacity}]，从下往上。返回 (h,w,4)。"""
    _need_numpy()
    if base is None:
        base = np.zeros((h, w, 4), dtype=np.float32)
    cur = base
    for lyr in layers:
        cur = composite_one(cur, lyr["rgba"], lyr.get("mode", "normal"),
                            lyr.get("opacity", 1.0))
    return cur


# ---- 效果工厂 -------------------------------------------------------------

def _solid(rgb, alpha):
    """纯色 + alpha → (h,w,4)。rgb 可以是三元组或 (h,w,3)。"""
    _need_numpy()
    h, w = alpha.shape
    out = np.empty((h, w, 4), dtype=np.float32)
    if isinstance(rgb, tuple) or isinstance(rgb, list):
        out[..., 0] = rgb[0]
        out[..., 1] = rgb[1]
        out[..., 2] = rgb[2]
    else:
        out[..., :3] = rgb
    out[..., 3] = np.clip(alpha, 0.0, 1.0)
    return out


def _col(c):
    try:
        return (float(c[0]), float(c[1]), float(c[2]))
    except Exception:
        return (0.0, 0.0, 0.0)


def _offset(eff, st, toward_light=False):
    """PS 的「角度」是**光源方向**。

    投影往光源的反方向落（120° → 右下），内阴影和光泽往光源那一侧压
    （120° → 左上内缘）。两者差一个负号，搞错就是「阴影跑到上面去了」。
    """
    ang = (st["global_angle"] if eff.get("use_global", True)
           else eff.get("angle", DEFAULT_GLOBAL_ANGLE))
    a = math.radians(float(ang))
    d = float(eff.get("distance", 0.0))
    if toward_light:
        return d * math.cos(a), -d * math.sin(a)
    return -d * math.cos(a), d * math.sin(a)


def _bbox(alpha):
    _need_numpy()
    m = alpha > 0.002
    if not m.any():
        return None
    rows = np.where(m.any(axis=1))[0]
    cols = np.where(m.any(axis=0))[0]
    return (float(cols[0]), float(rows[0]),
            float(cols[-1] + 1), float(rows[-1] + 1))


def _op(eff, key="opacity"):
    return max(0.0, min(1.0, float(eff.get(key, 100)) / 100.0))


def _fill_rgb(eff, alpha, w, h, assets, color_key="color",
              style_key="gradient_style", angle_key="gradient_angle",
              scale_key=None, box=None, fill_key="fill"):
    """给描边/发光挑「颜色 / 渐变 / 图案」填充。返回 (h,w,3) 或三元组。

    发光的 sRGB 只有「单色 / 渐变」两档（没有 fill 字段，用 gradient 布尔）；
    描边有 fill 三选一。
    """
    _need_numpy()
    if fill_key in eff:
        kind = eff.get(fill_key, "color")
    else:
        kind = "gradient" if eff.get("gradient") else "color"
    if kind == "gradient":
        lut = assets.get("gradient")
        if lut is None:
            return _col(eff.get(color_key))
        sc = float(eff.get(scale_key, 100)) / 100.0 if scale_key else 1.0
        t = gradient_field(w, h, eff.get(style_key, "linear"),
                           eff.get(angle_key, 90.0), sc, False, box)
        idx = np.clip((t * (lut.shape[0] - 1)).astype(np.int32), 0,
                      lut.shape[0] - 1)
        return lut[idx]
    if kind == "pattern":
        unit = assets.get("pattern")
        if unit is None:
            return _col(eff.get(color_key))
        return pattern_field(unit, w, h,
                             float(eff.get("pattern_scale", 100)) / 100.0,
                             box, (int(box[0]), int(box[1])) if box else (0, 0))
    return _col(eff.get(color_key))


def effect_drop_shadow(alpha, eff, st, w, h, assets):
    a = alpha
    # 「扩展」必须在模糊**之后**：先扩展再模糊等于白扩展（模糊会把
    # 硬边重新摊软），PS 的滑杆也是拉模糊之后的密度。
    if eff.get("size", 0):
        a = gaussian(a, float(eff["size"]) * 0.5)
    if eff.get("spread", 0):
        a = spread_curve(a, float(eff["spread"]) / 100.0)
    if eff.get("contour", "linear") != "linear":
        a = _apply_contour(a, eff["contour"])
    a = _noise(a, float(eff.get("noise", 0)) / 100.0)
    dx, dy = _offset(eff, st)
    a = shift2(a, dx, dy)
    if eff.get("knockout") == "deep":
        # 深挖空：内容区域把阴影整块挖掉（浅挖空靠层叠顺序就够）
        a = a * (1.0 - alpha)
    return _solid(_col(eff.get("color")), a * _op(eff))


def effect_outer_glow(alpha, eff, st, w, h, assets):
    a = alpha
    amt = float(eff.get("spread", 0)) / 100.0
    if eff.get("size", 0):
        a = gaussian(a, float(eff["size"]) * 0.5)
    if eff.get("method") == "precise":
        a = spread_curve(a, max(amt, 0.6))       # 精确：模糊后把密度拉满
    elif amt > 0:
        a = spread_curve(a, amt)
    rng = max(0.01, float(eff.get("range", 50)) / 100.0)
    a = _apply_contour(a, eff.get("contour", "linear"), 1.0)
    a = np.clip(a * (1.0 / rng), 0.0, 1.0)
    a = _noise(a, float(eff.get("noise", 0)) / 100.0)
    rgb = _fill_rgb(eff, a, w, h, assets, box=_bbox(alpha))
    return _solid(rgb, a * _op(eff))


def effect_inner_shadow(alpha, eff, st, w, h, assets):
    inv = 1.0 - alpha
    a = gaussian(inv, float(eff.get("size", 0)) * 0.5) \
        if eff.get("size", 0) else inv
    if eff.get("choke", 0):
        a = spread_curve(a, float(eff["choke"]) / 100.0)
    a = _apply_contour(a, eff.get("contour", "linear"))
    a = _noise(a, float(eff.get("noise", 0)) / 100.0)
    # 偏移方向和投影**一样**（120° → 右下）：反相的 alpha 场往右下挪，
    # 左上那段「内容外面的 1」才会跑进左上内缘，阴影才在左上。
    dx, dy = _offset(eff, st)
    a = shift2(a, dx, dy) * alpha
    return _solid(_col(eff.get("color")), a * _op(eff))


def effect_inner_glow(alpha, eff, st, w, h, assets):
    inv = 1.0 - alpha
    if eff.get("size", 0):
        # 源=边缘时是「从边界向内衰减」，源=居中时是「从中心向外衰减」，
        # 同一个模糊场，取补即可
        inv = gaussian(inv, float(eff["size"]) * 0.5)
    if eff.get("choke", 0):
        inv = spread_curve(inv, float(eff["choke"]) / 100.0)
    if eff.get("method") == "precise":
        inv = spread_curve(inv, 0.5)
    a = inv if eff.get("source") == "edge" else (1.0 - inv)
    rng = max(0.01, float(eff.get("range", 50)) / 100.0)
    a = np.clip(_apply_contour(a, eff.get("contour", "linear")) / rng, 0.0, 1.0)
    a = _noise(a, float(eff.get("noise", 0)) / 100.0)
    a = a * alpha
    rgb = _fill_rgb(eff, a, w, h, assets, box=_bbox(alpha))
    return _solid(rgb, a * _op(eff))


def _profile(x, depth):
    """斜面横截面：0 平、1 顶。depth 越大越陡（PS 的「深度」）。"""
    x = np.clip(x, 0.0, 1.0)
    k = max(0.2, depth)
    return np.clip(1.0 - np.power(1.0 - x, 1.0 + k), 0.0, 1.0)


def _height_field(alpha, eff, w, h, assets):
    """斜面/浮雕的高度图 + 生效区域（两者都是 (h,w)）。"""
    size = max(0.5, float(eff.get("size", 5.0)))
    style = eff.get("style", "inner")
    depth = float(eff.get("depth", 100)) / 100.0
    smooth = gaussian(alpha, size * 0.5)
    if eff.get("method") == "chisel-hard":
        smooth = spread_curve(smooth, 0.45)
    elif eff.get("method") == "chisel-soft":
        smooth = spread_curve(smooth, 0.2)
    # inner：0 在边界、1 在内部（内侧斜坡的高度）
    inner = np.clip((smooth - 0.5) * 2.0, 0.0, 1.0)
    # outer_r：0 在边界、1 在远处（「内容外面」这块区域有多大）
    outer_r = np.clip((0.5 - smooth) * 2.0, 0.0, 1.0)
    # outer_h：1 在边界、0 在远处。外斜面是「内容外缘向外鼓起来」，
    # 所以高度贴着边界最高 —— 用 inner 那种形状当外斜面会变成一圈凹槽，
    # 高光会跑到背光那一侧（一开始就是这么错的）。
    outer_h = np.clip(smooth * 2.0, 0.0, 1.0)
    if style == "outer":
        hgt, region = _profile(outer_h, depth), outer_r
    elif style == "emboss":
        hgt = _profile(inner, depth) * 0.5 + _profile(outer_h, depth) * 0.5
        region = np.maximum(alpha, outer_r)
    elif style == "pillow":
        # 枕状浮雕 = 内斜面**反过来**：内部平台低、边界高，看起来像被压进背景
        hgt = (1.0 - _profile(inner, depth)).astype(np.float32)
        region = alpha
    elif style == "stroke":
        sw = max(0.5, float(eff.get("stroke_size", 3.0)))
        sd = signed_distance(alpha, sw + 2.0)
        band = np.clip(sw - np.abs(sd) + 0.5, 0.0, 1.0)
        hgt = _profile(np.clip(np.abs(sd) / sw, 0.0, 1.0), depth)
        region = band
    else:                                        # inner
        hgt, region = _profile(inner, depth), alpha
    if eff.get("soften", 0):
        hgt = gaussian(hgt, float(eff["soften"]) * 0.5)
    if eff.get("direction") == "down":
        hgt = 1.0 - hgt
    return hgt.astype(np.float32), region.astype(np.float32)


def effect_bevel(alpha, eff, st, w, h, assets):
    """返回两个图层：高光 + 阴影（PS 里也是两个独立的高光/阴影合成）。"""
    hgt, region = _height_field(alpha, eff, w, h, assets)
    gy, gx = np.gradient(hgt)
    depth = float(eff.get("depth", 100)) / 100.0
    k = 1.5 / max(0.15, depth)
    # 法线 z 取 1，xy 是高度梯度；图像 y 向下，所以法线的 y 分量不再取反，
    # 光照向量的 y 用 -sin（正角朝右上方）
    nx, ny, nz = -gx * k, -gy * k, np.ones_like(gx)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / ln, ny / ln, nz / ln
    ang = (st["global_angle"] if eff.get("use_global", True)
           else eff.get("angle", DEFAULT_GLOBAL_ANGLE))
    alt = float(eff.get("altitude", st.get("global_altitude", 30.0)))
    az, al = math.radians(float(ang)), math.radians(max(0.0, min(89.0, alt)))
    lx, ly, lz = math.cos(al) * math.cos(az), -math.cos(al) * math.sin(az), \
        math.sin(al)
    dot = nx * lx + ny * ly + nz * lz
    flat = lz
    gain = 6.0 / max(0.2, depth)
    hi = np.clip((dot - flat) * gain, 0.0, 1.0) * region * _op(
        eff, "highlight_opacity")
    lo = np.clip((flat - dot) * gain, 0.0, 1.0) * region * _op(
        eff, "shadow_opacity")
    hi_layer = _solid(_col(eff.get("highlight_color", (1, 1, 1))), hi)
    lo_layer = _solid(_col(eff.get("shadow_color", (0, 0, 0))), lo)
    # 先阴影后高光：高光最后叠上去，边缘才不会被压暗
    return [(lo_layer, eff.get("shadow_mode", "multiply")),
            (hi_layer, eff.get("highlight_mode", "screen"))]


def effect_satin(alpha, eff, st, w, h, assets):
    inv = 1.0 - alpha
    size = float(eff.get("size", 14.0))
    dx, dy = _offset(eff, {**{"global_angle": DEFAULT_GLOBAL_ANGLE},
                           **eff, "use_global": False})
    b1 = gaussian(inv, size * 0.5) if size > 0 else inv
    b2 = gaussian(shift2(inv, dx, dy), size * 0.5) if size > 0 \
        else shift2(inv, dx, dy)
    d = b1 - b2
    v = np.clip(0.5 + d * 2.0, 0.0, 1.0)
    if eff.get("invert"):
        a = np.clip((v - 0.5) * 2.0, 0.0, 1.0)
    else:
        a = np.clip((0.5 - v) * 2.0, 0.0, 1.0)
    return _solid(_col(eff.get("color")), a * alpha * _op(eff))


def effect_color_overlay(alpha, eff, st, w, h, assets):
    return _solid(_col(eff.get("color")), alpha * _op(eff))


def effect_gradient_overlay(alpha, eff, st, w, h, assets):
    lut = assets.get("gradient")
    box = _bbox(alpha) if eff.get("align", True) else None
    if lut is None:
        return _solid((0.0, 0.0, 0.0), alpha * _op(eff))
    t = gradient_field(w, h, eff.get("style", "linear"),
                       float(eff.get("angle", 90.0)),
                       float(eff.get("scale", 100)) / 100.0,
                       bool(eff.get("reverse")), box)
    idx = np.clip((t * (lut.shape[0] - 1)).astype(np.int32), 0,
                  lut.shape[0] - 1)
    return _solid(lut[idx], alpha * _op(eff))


def effect_pattern_overlay(alpha, eff, st, w, h, assets):
    unit = assets.get("pattern")
    if unit is None:
        return _solid((0.0, 0.0, 0.0), alpha * _op(eff))
    box = _bbox(alpha) if eff.get("align", True) else None
    rgb = pattern_field(unit, w, h, float(eff.get("scale", 100)) / 100.0,
                        box, (int(box[0]), int(box[1])) if box else (0, 0))
    return _solid(rgb, alpha * _op(eff))


def effect_stroke(alpha, eff, st, w, h, assets):
    size = max(0.5, float(eff.get("size", 3.0)))
    pos = eff.get("position", "outside")
    sd = signed_distance(alpha, size + 2.0)
    if pos == "inside":
        band = np.clip(np.minimum(size - sd, sd) + 0.5, 0.0, 1.0)
    elif pos == "center":
        band = np.clip(size * 0.5 - np.abs(sd) + 0.5, 0.0, 1.0)
    else:
        band = np.clip(np.minimum(sd + size, -sd) + 0.5, 0.0, 1.0)
    band = band.astype(np.float32)
    rgb = _fill_rgb(eff, band, w, h, assets, style_key="gradient_style",
                    angle_key="gradient_angle", scale_key=None,
                    box=_bbox(alpha))
    return _solid(rgb, band * _op(eff))


# 名称 → 生成器，返回 (rgba, mode) 或 [(rgba, mode), …]（斜面是两片）
GENERATORS = {
    "drop-shadow": effect_drop_shadow,
    "outer-glow": effect_outer_glow,
    "inner-shadow": effect_inner_shadow,
    "inner-glow": effect_inner_glow,
    "bevel": effect_bevel,
    "satin": effect_satin,
    "color-overlay": effect_color_overlay,
    "gradient-overlay": effect_gradient_overlay,
    "pattern-overlay": effect_pattern_overlay,
    "stroke": effect_stroke,
}


# ---- 主入口 ---------------------------------------------------------------

def blend_if_alpha(alpha, rgb, eff):
    """PS 的「混合颜色带：本图层」。按灰度把 alpha 在两端做斜坡。"""
    _need_numpy()
    if not eff.get("blend_if_source", False):
        return alpha
    lum = _lum(rgb)
    lo = float(eff.get("blend_if_lo", 0)) / 100.0
    lo_s = float(eff.get("blend_if_lo_split", 0)) / 100.0
    hi = float(eff.get("blend_if_hi", 100)) / 100.0
    hi_s = float(eff.get("blend_if_hi_split", 0)) / 100.0
    lo_end = max(lo, min(1.0, lo + lo_s))
    hi_start = min(hi, max(0.0, hi - hi_s))
    m = np.ones_like(lum)
    if lo_end > 0.0001:
        m = m * np.clip((lum - lo) / max(1e-4, lo_end - lo), 0.0, 1.0)
    if hi_start < 0.9999:
        m = m * np.clip((hi - lum) / max(1e-4, hi - hi_start), 0.0, 1.0)
    return (alpha * m).astype(np.float32)


def render(rgba, w, h, style, assets=None, progress=None, preblend=True):
    """样式 → 图层计划。

    返回 {"layers": [...], "notes": [...], "source": ..., "seconds": …}
    每个 layer: {"name", "effect", "rgba", "mode", "style_mode", "role"}
    role ∈ {"below", "above"}：below 要插到内容**下面**。
    preblend=True 时每个层的 mode 都是 normal（混合已经算进颜色里），
    原始混合模式留在 style_mode 里给界面看。
    """
    _need_numpy()
    import time
    t0 = time.time()
    assets = assets or {}
    st = style

    # 也接受已经是 (h,w,4) float 的数组：预览/测试里不必先转成字节再转回来
    if isinstance(rgba, np.ndarray):
        src = rgba.astype(np.float32, copy=True)
    else:
        src = to_float(rgba, w, h)
    alpha = src[..., 3].copy()
    alpha = blend_if_alpha(alpha, src[..., :3], st.get("blend") or {})

    layers = []
    notes = []
    acc = np.zeros((h, w, 4), dtype=np.float32)

    def emit(name):
        nonlocal acc
        eff = (st.get("effects") or {}).get(name) or {}
        if not eff.get("enabled"):
            return
        gen = GENERATORS[name]
        if progress:
            progress()
        try:
            out = gen(alpha, eff, st, w, h, assets)
        except NoNumpy:
            raise
        except Exception as exc:            # 单个效果算炸不该毁掉整份样式
            notes.append("%s: %s" % (name, exc))
            return
        pieces = out if isinstance(out, list) else [(out, eff.get("mode",
                                                                "normal"))]
        for idx, (rgba_f, mode) in enumerate(pieces):
            label = EFFECT_LABEL[name]
            if len(pieces) > 1:
                label += " (shadow)" if idx == 0 else " (highlight)"
            style_mode = mode or "normal"
            if preblend:
                body = preblend_layer(acc, rgba_f, style_mode)
                acc = composite_one(acc, body, "normal", 1.0)
            else:
                body = rgba_f
            layers.append({
                "name": label,
                "effect": name,
                "rgba": body,
                "mode": "normal" if preblend else style_mode,
                "style_mode": style_mode,
                "opacity": 1.0,
                "role": "below" if name in BELOW_CONTENT else "above",
            })

    below = [n for n in EFFECT_ORDER if n in BELOW_CONTENT]
    above = [n for n in EFFECT_ORDER if n not in BELOW_CONTENT]
    for name in below:
        emit(name)
    if preblend:
        acc = composite_one(acc, src, "normal", 1.0)
    for name in above:
        emit(name)
    return {"layers": layers, "notes": notes, "alpha": alpha,
            "size": (w, h), "seconds": time.time() - t0,
            "preblended": preblend,
            "source": src}


def render_bytes(rgba, w, h, style, assets=None, progress=None):
    """同 render，但把 float 数组换成 u8 字节（写图层用）。"""
    plan = render(rgba, w, h, style, assets, progress)
    for lyr in plan["layers"]:
        lyr["bytes"] = to_bytes(lyr.pop("rgba"))
    plan["source_bytes"] = to_bytes(plan.pop("source"))
    plan.pop("alpha", None)
    return plan


def preview(plan, w, h, background=(0.0, 0.0, 0.0, 0.0)):
    """把计划合成成一张 RGBA（预览用：内容 + 全部效果）。"""
    _need_numpy()
    src = plan["source"]
    below = [dict(rgba=l["rgba"], mode=l["mode"], opacity=l["opacity"])
             for l in plan["layers"] if l["role"] == "below"]
    above = [dict(rgba=l["rgba"], mode=l["mode"], opacity=l["opacity"])
             for l in plan["layers"] if l["role"] == "above"]
    base = np.zeros((h, w, 4), dtype=np.float32)
    base[..., :] = background
    out = composite(below, base, w, h)
    out = composite_one(out, src, "normal", 1.0)
    out = composite(above, out, w, h)
    return out


def flatten_onto(out, bg_rgb=(1.0, 1.0, 1.0)):
    """合成到不透明底色上，返回 (h,w,3) —— 预览面板要给它铺棋盘格时用。"""
    _need_numpy()
    a = out[..., 3:4]
    bg = np.array(bg_rgb, dtype=np.float32)
    return np.clip(out[..., :3] * a + bg * (1.0 - a), 0.0, 1.0)


def summary(plan):
    """给用户看的一句话。"""
    names = [l["name"] for l in plan["layers"]]
    return {"layers": len(names), "names": names,
            "seconds": plan.get("seconds", 0.0),
            "notes": plan.get("notes") or []}


# ---- 预览缩放 -------------------------------------------------------------

# 这些都是「像素」单位，预览图缩小了 k 倍就必须一起乘 k，
# 否则预览里的投影距离和模糊半径会比真正应用时大一圈（看着像两套参数）。
PIXEL_KEYS = ("distance", "size", "soften", "stroke_size")


def scale_style(st, k):
    """把样式里的像素级参数按 k 缩放（预览用）。"""
    if abs(k - 1.0) < 1e-6:
        return st
    out = clone_style(st)
    for name, eff in out["effects"].items():
        for key in PIXEL_KEYS:
            if key in eff and isinstance(eff[key], (int, float)):
                eff[key] = max(0.5, float(eff[key]) * k)
    return out


def style_stats(st):
    """面板摘要：启用了几个效果。"""
    on = [EFFECT_LABEL[n] for n in EFFECT_ORDER
          if (st.get("effects") or {}).get(n, {}).get("enabled")]
    return {"enabled": len(on), "names": on}

