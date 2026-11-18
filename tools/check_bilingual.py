# -*- coding: utf-8 -*-
"""扫描 docs/ 下所有页面，找中英文切换的破绽。

判据：
  A. 英文模式仍可见中文   —— 文本节点既不在 .l-en 里，也不在 .l-zh 里（或直接在 .l-zh 里却有 CJK）
  B. 中文模式仍可见英文长句 —— 无包裹的文本节点里出现 >=6 个连续英文单词（术语/品牌名之外）
  C. 双语段落条数不配对    —— 一个 .l-zh 找不到相邻的 .l-en
  D. 属性里的中文          —— alt / title / aria-label / placeholder 含 CJK（英文模式无法切换）
"""
import io, os, re, sys, html
from html.parser import HTMLParser

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
CJK = re.compile(r'[\u4e00-\u9fff]')
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{1,}")
SKIP_TAGS = {"script", "style", "code", "pre", "kbd", "samp"}
VOID = {"area","base","br","col","embed","hr","img","input","link","meta","param",
        "source","track","wbr"}


class Node:
    __slots__ = ("tag", "classes", "attrs", "children", "parent", "text")
    def __init__(self, tag, classes, attrs, parent):
        self.tag = tag; self.classes = classes; self.attrs = attrs
        self.children = []; self.parent = parent; self.text = ""


class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", set(), {}, None)
        self.cur = self.root
        self.texts = []   # (text, node, in_skip)
        self.attrs_all = []  # (tag, attr, value, node)
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        n = Node(tag, set((a.get("class") or "").split()), a, self.cur)
        self.cur.children.append(n)
        for k, v in attrs:
            if k in ("alt", "title", "aria-label", "placeholder", "content") and v:
                self.attrs_all.append((tag, k, v, n))
        if tag not in VOID:
            self.cur = n
    def handle_startendtag(self, tag, attrs):
        a = dict(attrs)
        n = Node(tag, set((a.get("class") or "").split()), a, self.cur)
        self.cur.children.append(n)
        for k, v in attrs:
            if k in ("alt", "title", "aria-label", "placeholder", "content") and v:
                self.attrs_all.append((tag, k, v, n))
    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent
    def handle_data(self, data):
        if not data.strip():
            return
        # 脚本、样式、代码块里的内容不随语言切换，也不算文案
        n = self.cur
        while n is not None:
            if n.tag in SKIP_TAGS:
                return
            n = n.parent
        self.texts.append((data, self.cur))


def ctx(node):
    """返回该节点所处的语言环境：'zh' / 'en' / 'both'。"""
    n = node
    langs = set()
    while n is not None:
        if "l-zh" in n.classes:
            langs.add("zh")
        if "l-en" in n.classes:
            langs.add("en")
        n = n.parent
    if langs == {"zh"}:
        return "zh"
    if langs == {"en"}:
        return "en"
    if langs == {"zh", "en"}:
        return "nested"
    return "both"


def visible_in(node, lang):
    """该文本在 lang 模式下是否可见。"""
    c = ctx(node)
    if c == "both":
        return True
    if c == "nested":
        return False   # 嵌套是生成器的 bug，单独报
    return c == lang


def main():
    pages = []
    for dirpath, _, files in os.walk(ROOT):
        for f in sorted(files):
            if f.endswith(".html"):
                pages.append(os.path.join(dirpath, f))
    pages.sort()

    problems = {}
    for path in pages:
        rel = os.path.relpath(path, os.path.dirname(ROOT)).replace("\\", "/")
        raw = io.open(path, encoding="utf-8").read()
        p = P(); p.feed(raw); p.close()

        zh_leak_en, en_leak_zh, nested, attr_issues = [], [], [], []
        n_zh = n_en = 0
        for txt, node in p.texts:
            s = txt.strip()
            if not s:
                continue
            c = ctx(node)
            if c == "zh": n_zh += 1
            if c == "en": n_en += 1
            if c == "nested":
                nested.append(s[:80]); continue
            # <title> 靠 data-title-en 在切语言时替换，静态文本是中文，属预期
            under_title = False
            q = node
            while q is not None:
                if q.tag == "title":
                    under_title = True; break
                q = q.parent
            if under_title:
                continue
            # 语言按钮上的「中文」本来就该用中文写，不是漏翻
            q = node
            in_sw = False
            while q is not None:
                if "lang-sw" in q.classes:
                    in_sw = True; break
                q = q.parent
            if in_sw:
                continue
            if s.startswith("$"):
                continue   # 公式两种语言共用
            if CJK.search(s) and visible_in(node, "en"):
                zh_leak_en.append(s[:100])
            if not CJK.search(s) and not s.startswith("$"):
                words = LATIN_WORD.findall(s)
                if len(words) >= 6 and visible_in(node, "zh"):
                    en_leak_zh.append(s[:100])

        for tag, k, v, node in p.attrs_all:
            if not CJK.search(v):
                continue
            c = ctx(node)
            if c not in ("both", "en"):
                continue
            # 已经备了英文副本的（meta data-desc-en、双语 aria-label/link title）不算
            if ("data-desc-en" in node.attrs or "data-title-en" in node.attrs
                    or " / " in v):
                continue
            attr_issues.append("%s[%s]=%s" % (tag, k, v[:70]))

        if zh_leak_en or en_leak_zh or nested or attr_issues or n_zh != n_en:
            problems[rel] = dict(zh_leak_en=zh_leak_en, en_leak_zh=en_leak_zh,
                                 nested=nested, attrs=attr_issues,
                                 n_zh=n_zh, n_en=n_en)

    print("扫描 %d 个页面，%d 个有问题\n" % (len(pages), len(problems)))
    for rel, d in problems.items():
        print("=" * 78)
        print(rel, "  (l-zh=%d, l-en=%d)" % (d["n_zh"], d["n_en"]))
        if d["zh_leak_en"]:
            print("  [EN 模式露出中文] %d 处" % len(d["zh_leak_en"]))
            for s in d["zh_leak_en"][:8]:
                print("     -", s)
        if d["en_leak_zh"]:
            print("  [ZH 模式露出英文长句] %d 处" % len(d["en_leak_zh"]))
            for s in d["en_leak_zh"][:6]:
                print("     -", s)
        if d["nested"]:
            print("  [zh/en 嵌套] %d 处" % len(d["nested"]))
            for s in d["nested"][:5]:
                print("     -", s)
        if d["attrs"]:
            print("  [属性含中文] %d 处" % len(d["attrs"]))
            for s in d["attrs"][:8]:
                print("     -", s)


if __name__ == "__main__":
    main()
