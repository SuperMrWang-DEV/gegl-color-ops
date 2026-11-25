"""旁白读音订正：喂给 TTS 的文本 ≠ 字幕文本。

微软中文 Neural 音色在这三类地方会念错，逐条在这里兜住：

1. 英文缩写夹在中文里会被"拼音化"（GEGL 念成"哥格勒"），逐字母写出才稳；
2. 点号、连字符被念成"点""杠"（GPL-3.0、build.sh），换成中文说法；
3. 多音字靠上下文猜，猜错就是错读（重采样 zhòng、栅格 shān、量程 liàng）。

字幕仍用 script.py 里的 narr 原文，这里只产出 spoken。
"""
import re

# 顺序有意义：长的、带标点的先替换，否则会被短规则先吃掉。
# 右列都经过 asr_check.py 回听确认（GIMP 原来念成"店普"，栅格念成 shān，
# 重采样念成 zhòng，都记在 README 的"念错清单"里）。
TERMS = [
    (r"GPL-3\.0", "G P L 三点零"),
    (r"build\.sh\s*", "build 脚本"),
    (r"install\.sh\s*", "install 脚本"),
    (r"ComfyUI", "Comfy U I"),
    (r"GEGL", "G E G L"),
    (r"\bgegl\b", "G E G L"),
    (r"GIMP", "金普"),          # 引擎按英文单词念，中文语境里像"店普"
    (r"LCh", "L C H"),
    (r"CMYK", "C M Y K"),
    (r"RGB", "R G B"),
    (r"USM", "U S M"),
    (r"MLS", "M L S"),
    (r"FFD", "F F D"),
    (r"RMBG", "R M B G"),
    (r"LUT", "L U T"),
    (r"\blb 前缀", "L B 前缀"),
    (r"\bLab\b", "拉布"),        # 行业读法 /læb/
    (r"\bC1\b", "C 一"),
]

# 多音字：只改读音，不动字幕。右列是读音明确的同义写法。
# （"栅格"念 shān、"只改"念 zhí、"整行"念 xíng 的几处，已经在 script.py
#  把原句换成"网格""仅改""整条"，不走这里。）
HOMOPHONE = [
    (r"重采样", "重新采样"),      # 重 zhòng → chóng
    (r"调色", "配色"),            # 调 diào → tiáo；稿子已统一改"配色"，这条是兜底
]

_RULES = [(re.compile(p), r) for p, r in TERMS + HOMOPHONE]


def spoken(text):
    """把旁白原文转成 TTS 友好写法。"""
    for pat, rep in _RULES:
        text = pat.sub(rep, text)
    return text


def diff_report(scenes):
    """列出哪些句子会被改写，方便人工复核。"""
    rows = []
    for sc in scenes:
        say = spoken(sc["narr"])
        if say != sc["narr"]:
            rows.append((sc["key"], sc["narr"], say))
    return rows


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from script import SCENES
    for key, src, say in diff_report(SCENES):
        print("-" * 70)
        print(key)
        print("  字幕:", src)
        print("  配音:", say)
