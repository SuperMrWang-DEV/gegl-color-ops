# -*- coding: utf-8 -*-
"""把 ops/ 下的算子渲染成一套静态站点，输出到 docs/（带 .disabled 的标停用/废弃）。

设计上把 docs/ 当作纯产物：每次运行整个目录重建，样式源在 tools/site/。
所以改样式改 tools/site/style.css，别直接改 docs/assets/style.css。

算子页是**中英双语**的：中文正文来自 ops/<dir>/README.md，英文正文来自
tools/site/en/<dir>.md（front matter 给 name / blurb）。两套内容同时写进同一个
HTML，靠 <html data-lang> 决定显示哪一套，页头的 中文/EN 按钮切换并记住偏好
（localStorage + ?lang=en）。首页也是双语的；清单页、插件页、安装页只有中文，
不显示切换按钮。

plugins.html 只是十块方格（每个插件一块，链到 plugins/<slug>.html），
正文全在文章页里；数据与文案集中在 tools/plugin_docs.py，两边不会漂。
首页有八张 Shortcut 入口卡，feed.xml 里也有十条。

    python tools/site_build.py           # 生成 docs/
    python tools/site_build.py --serve   # 生成后起本地服务看效果

发布走 GitHub Pages：仓库 Settings → Pages → Deploy from a branch →
main /docs。docs/ 里放了 .nojekyll，免掉 Jekyll 预处理（它会吞掉下划线开头
的文件，也会把构建时间拖长）。
"""

import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plugin_docs as PD  # Shortcut 八节的正文，插件页与文章页共用
ROOT = os.path.dirname(HERE)
OPS = os.path.join(ROOT, "ops")
DIST = os.path.join(ROOT, "dist")
DOCS = os.path.join(ROOT, "docs")
SRC = os.path.join(HERE, "site")

sys.path.insert(0, HERE)
from md2html import convert, inline, plain     # noqa: E402
import set_menu_group as SMG                   # noqa: E402  分组只有这一处数据源

REPO = "https://github.com/SuperMrWang-DEV/gegl-color-ops"
SITE = "https://superMrwang-dev.github.io/gegl-color-ops"  # GitHub Pages
RAW = REPO + "/raw/main/dist/windows-x64"
LIN_RAW = REPO + "/raw/main/dist/linux-x64"

# 算子页的英文版按目录名放这里，每个文件开头一小段 front matter（name / blurb）。
# README 里那些 `## English` 是旧插件的安装说明，不是当前算法的翻译，不能用。
EN_DIR = os.path.join(SRC, "en")

GROUP_ZH = {
    "Levels": ("Levels", "色阶家族"),
    "Component": ("Component", "分量"),
    "Tone":  ("Tone",  "影调"),
    "Color": ("Color", "色彩"),
    "Blend": ("Blend", "混合与通道"),
    "Mask":  ("Mask",  "蒙版"),
}

GROUP_DESC = {
    "Levels": "色阶一个不落，全收在一级目录 Levels 里：基础色阶，以及 HSL / HSB / "
              "HSI / LCH / LAB / CMYK 六条分量色阶——同一个黑白场+伽马模型，换个色彩空间。",
    "Component": "把分量打包成一张数据图、再解回来：HSL / Lab / HSI 各自成对的 "
                 "dual + compose，加上灰度→分量的单通道编码。分量曲线插件就架在这组上。",
    "Tone":  "明暗与影调：曝光、亮度/对比度、阴影-高光、黑白转换。色阶都在上面的 Levels 组。",
    "Color": "调整颜色的方向与浓度：色相饱和度、色彩平衡、白平衡、自然饱和度、可选颜色、匹配颜色。",
    "Blend": "把两层或多路通道混起来：应用图像、计算、通道混合器、XYZ 正片叠底、颜色查找、灰度转分量。",
    "Mask":  "按颜色或数值区间取蒙版：色彩范围、通道区间到 alpha。",
}

GROUP_DESC_EN = {
    "Levels": "Every levels flavour in one top-level Levels submenu: basic Levels plus "
              "six component levels — HSL / HSB / HSI / LCh / Lab / CMYK. One "
              "black-point / white-point + gamma model, six colour spaces.",
    "Component": "Pack components into one data image and unpack it again: paired "
                 "dual + compose for HSL / Lab / HSI, plus the single-channel "
                 "gray-to-component. The component-curve plug-ins sit on top.",
    "Tone":  "Light and dark: exposure, brightness/contrast, shadows–highlights, "
             "black & white. The levels family lives in the Levels group above.",
    "Color": "Steer hue and intensity: hue/saturation, colour balance, white balance, "
             "vibrance, selective colour, match colour.",
    "Blend": "Mix two layers or several channels: apply image, calculations, channel "
             "mixer, XYZ multiply, colour lookup, gray to component.",
    "Mask":  "Build masks from colour ranges or value intervals: colour range, "
             "channel range to alpha.",
}

TYPE_ZH = {
    "PointFilter":    "逐像素",
    "Filter":         "整块区域",
    "PointComposer":  "双输入 · 逐像素",
    "Composer":       "双输入",
    "PointRender":    "生成器",
    "Render":         "生成器",
}

# 参数不放进卡片，但文章页顶部给一行元信息就够了
FIELD = re.compile(r"^ \* ([a-z]+)\s{2,}(.*)$")


# --------------------------------------------------------------------------
# 元数据：从每个 .c 的文件头注释盒里读，不另建清单
# --------------------------------------------------------------------------

def parse_header(c_path):
    txt = open(c_path, encoding="utf-8", errors="replace").read()
    m = re.search(r"/\* =+\n(.*?)\n \* =+ \*/", txt, re.S)
    if not m:
        return {}
    fields, cur = {}, None
    for line in m.group(1).split("\n"):
        mm = FIELD.match(line)
        if mm:
            cur = mm.group(1)
            fields[cur] = [mm.group(2).strip()]
        elif cur and line.startswith(" *"):
            body = line[3:].strip()
            if body and not body.startswith("---"):
                fields[cur].append(body)
    return {k: v for k, v in fields.items()}


def split_zh_en(lines):
    """注释盒每段都是先中文后英文，按「ASCII 占比 + 首字母大写」切一刀。

    中文行不含空格且非 ASCII 居多；英文行反过来。这个判定对仓库里 29 个
    算子逐个看过，没有误切。
    """
    zh, en = [], []
    for ln in lines:
        ascii_n = sum(1 for ch in ln if ord(ch) < 128)
        ratio = ascii_n / max(1, len(ln))
        if not en and zh and ratio > 0.7 and ln[:1].isupper():
            en.append(ln)
        elif en:
            en.append(ln)
        else:
            zh.append(ln)
    return "".join(x for x in zh), " ".join(en)


def short(text, n=58):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    # 英文（ASCII 为主）退回最后一个空格，别把单词切成两半；中文按字数断
    if cut.count(" ") >= 3 and sum(1 for ch in cut if ord(ch) < 128) / len(cut) > 0.7:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip("，。;；、, ") + "…"


def load_ops():
    ops = []
    by_dir = {}
    for op_dir in sorted(os.listdir(OPS)):
        d = os.path.join(OPS, op_dir)
        if not os.path.isdir(d):
            continue
        cs = [f for f in sorted(os.listdir(d)) if f.endswith(".c")]
        if not cs:
            continue
        head = parse_header(os.path.join(d, cs[0]))
        if not head.get("id"):
            print("!! %s 没有文件头注释盒，跳过" % op_dir)
            continue
        zh, en = split_zh_en(head.get("purpose", []))
        tm = re.search(r"GeglOperation(\w+)", " ".join(head.get("type", [])))
        op = {
            "dir": op_dir,
            "id": head["id"][0],
            "menu": head.get("menu", [op_dir])[0],
            "purpose_zh": zh,
            "purpose_html": inline(zh),
            "purpose_text": plain(zh),
            "purpose_en": en,
            "type": TYPE_ZH.get(tm.group(1) if tm else "", tm.group(1) if tm else "算子"),
            "disabled": os.path.exists(os.path.join(d, ".disabled")),
            "deprecated": is_deprecated(os.path.join(d, ".disabled")),
            "discouraged": os.path.exists(os.path.join(d, ".discouraged")),
            "readme": os.path.join(d, "README.md"),
            "assets": os.path.join(d, "assets"),
        }
        by_dir[op_dir] = op
        ops.append(op)

    for g, members in SMG.GROUPS.items():
        for k, m in enumerate(members):
            if m in by_dir:
                by_dir[m]["group"] = g
                by_dir[m]["order"] = k

    for op in ops:
        op.setdefault("group", "Blend")
        op.setdefault("order", 99)
        # 模块文件名不一定等于目录名：exposure / brightness-contrast 为了避开
        # GEGL 内置算子的 GType 撞名，源文件改成了 lb-*.c，产物也叫 lb-*.dll
        for cand in ("%s" % op["dir"], "lb-%s" % op["dir"]):
            if (os.path.exists(os.path.join(DIST, "windows-x64", cand + ".dll")) or
                os.path.exists(os.path.join(DIST, "linux-x64", cand + ".so"))):
                op["module"] = cand
                break
        else:
            op["module"] = op["dir"]
        # 两个平台各自单独判：某个模块只出了一端时，页面上就别给它挂死链
        op["has_dll"] = os.path.exists(
            os.path.join(DIST, "windows-x64", op["module"] + ".dll"))
        op["has_so"] = os.path.exists(
            os.path.join(DIST, "linux-x64", op["module"] + ".so"))

    order = {g: i for i, g in enumerate(SMG.GROUPS)}
    ops.sort(key=lambda o: (order.get(o["group"], 9), o["order"], o["menu"]))
    for k, op in enumerate(ops):
        op["idx"] = k
        op["prev"] = ops[k - 1] if k else None
        op["next"] = ops[k + 1] if k + 1 < len(ops) else None
    return ops


# --------------------------------------------------------------------------
# 模板
# --------------------------------------------------------------------------

def t(zh, en):
    """同一句的两种语言，页面上只显示一种（由 <html data-lang> 决定）。"""
    return '<span class="l-zh">%s</span><span class="l-en">%s</span>' % (zh, en)


def head_html(root="", bilingual=False):
    sw = ('  <div class="lang-sw" role="group" aria-label="语言 / Language">\n'
          '    <button type="button" data-set-lang="zh" aria-pressed="true">中文</button>\n'
          '    <button type="button" data-set-lang="en" aria-pressed="false">EN</button>\n'
          '  </div>\n') if bilingual else ""
    return """<header class="site-head">
  <a class="brand" href="{r}index.html"><span class="dot"></span>gegl-color-ops</a>
  <nav>
    <a href="{r}index.html#ops">{ops}</a>
    <a href="{r}plugins.html">{plug}</a>
    <a href="{r}guide.html">{install}</a>
    <a href="{r}index.html#download">{download}</a>
    <a class="ext" href="https://github.com/SuperMrWang-DEV/gegl-color-ops">GitHub</a>
  </nav>
{sw}</header>""".format(r=root, sw=sw,
                        ops=t("算子", "Operators"),
                        plug=t("插件", "Plug-ins"),
                        install=t("安装", "Install"),
                        download=t("下载", "Download"))


def foot_html(version, root=""):
    return """<footer class="site-foot">
  <div>
    <p><strong>gegl-color-ops</strong> · {tag}</p>
    <p class="muted">{note}</p>
  </div>
  <div class="foot-links">
    <a href="https://github.com/SuperMrWang-DEV/gegl-color-ops">{repo}</a>
    <a href="https://github.com/SuperMrWang-DEV/gegl-color-ops/issues">{issue}</a>
    <a href="{r}guide.html">{guide}</a>
    <span class="muted">{v}</span>
  </div>
</footer>""".format(
        r=root, v=version,
        tag=t("GIMP 3 的 GEGL 色彩算子集", "a GEGL colour operator set for GIMP 3"),
        note=t("源码与文档同仓库，GPL-3.0-or-later。算法按公开公式与可观察行为自行实现，"
               "非官方移植；与各商业软件厂商及 GIMP 官方均无隶属关系。",
               "Source and docs live in one repository, GPL-3.0-or-later. Most "
               "algorithms were matched to observed behaviour rather than ported "
               "from source; this project is not affiliated with any vendor or the GIMP team."),
        repo=t("仓库", "Repository"),
        issue=t("问题反馈", "Issues"),
        guide=t("安装指南", "Install guide"))


# 切换语言的脚本：head 里那段先跑，避免「先画中文再跳成英文」的闪烁；
# body 末尾那段接按钮、记偏好、同步地址栏。
LANG_HEAD_JS = """<script>
(function () {
  try {
    var q = new URLSearchParams(location.search).get("lang");
    var l = q || localStorage.getItem("gco-lang");
    if (l === "en") {
      document.documentElement.setAttribute("data-lang", "en");
      document.documentElement.lang = "en";
    }
  } catch (e) {}
})();
</script>"""

LANG_FOOT_JS = """<script>
(function () {
  var root = document.documentElement;
  var btns = document.querySelectorAll("[data-set-lang]");
  function apply(l) {
    if (l === "en") {
      root.setAttribute("data-lang", "en");
      root.lang = "en";
    } else {
      root.removeAttribute("data-lang");
      root.lang = "zh-CN";
    }
    for (var i = 0; i < btns.length; i++) {
      btns[i].setAttribute("aria-pressed",
        btns[i].getAttribute("data-set-lang") === l ? "true" : "false");
    }
    if (root.dataset.titleZh && root.dataset.titleEn) {
      document.title = l === "en" ? root.dataset.titleEn : root.dataset.titleZh;
    }
  }
  for (var i = 0; i < btns.length; i++) {
    btns[i].addEventListener("click", function () {
      var l = this.getAttribute("data-set-lang");
      try { localStorage.setItem("gco-lang", l); } catch (e) {}
      apply(l);
      try {
        var u = new URL(location.href);
        if (l === "en") u.searchParams.set("lang", "en");
        else u.searchParams.delete("lang");
        history.replaceState(null, "", u);
      } catch (e) {}
    });
  }
  apply(root.getAttribute("data-lang") === "en" ? "en" : "zh");
})();
</script>"""


# 文章页的公式与流程图：KaTeX 负责公式（auto-render 扫正文里的 $..$ / $$..$$），
# mermaid 负责流程图。CDN 加载，本机离线预览时公式退化为原文、图退化为代码块。
# mermaid 不开 startOnLoad：双语页另一套语言是 display:none，隐藏元素量不出
# 文字尺寸，必须等可见时再画（切换语言后对新露出来的图补一次）。
MATH_HEAD = """<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"></script>
<script>
window.addEventListener("DOMContentLoaded", function () {
  if (window.renderMathInElement) {
    renderMathInElement(document.body, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "$", right: "$", display: false }
      ],
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"]
    });
  }
  if (window.mermaid) {
    var dark = matchMedia("(prefers-color-scheme: dark)").matches;
    mermaid.initialize({
      startOnLoad: false,
      theme: dark ? "dark" : "neutral",
      themeVariables: { fontSize: "13.5px" },
      flowchart: { curve: "basis", padding: 10, nodeSpacing: 28, rankSpacing: 38 }
    });
    var timer = null;
    function paint() {
      var nodes = [].filter.call(document.querySelectorAll("pre.mermaid"), function (n) {
        return !n.dataset.processed && n.offsetParent !== null;
      });
      if (nodes.length) mermaid.run({ nodes: nodes });
    }
    paint();
    document.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("[data-set-lang]")) {
        clearTimeout(timer); timer = setTimeout(paint, 60);
      }
    });
  }
});
</script>"""


def page(title, body, root="", desc="", titles=None, math=False):
    """titles=(中文标题, English title)。给了就说明这页是双语的，带上切换按钮。"""
    bilingual = bool(titles)
    lang_head, lang_foot, lang_attrs = "", "", ""
    if bilingual:
        lang_head = LANG_HEAD_JS + "\n"
        lang_foot = "\n" + LANG_FOOT_JS
        lang_attrs = ' data-title-zh="%s" data-title-en="%s"' % (
            html.escape(titles[0]), html.escape(titles[1]))
    return """<!DOCTYPE html>
<html lang="zh-CN"{attrs}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="alternate" type="application/atom+xml" title="算子更新" href="{root}feed.xml">
{math_head}{lang_head}</head>
<body>
<a class="skip" href="#main">{skip}</a>
{head}
<main id="main">
{body}
</main>
{foot}{lang_foot}
</body>
</html>
""".format(title=html.escape(title), body=body, desc=html.escape(desc),
           root=root, head=head_html(root, bilingual), foot=foot_html(VERSION, root),
           attrs=lang_attrs, lang_head=lang_head, lang_foot=lang_foot,
           math_head=MATH_HEAD if math else "",
           skip=t("跳到正文", "Skip to content"))


VERSION = "dev"


def is_deprecated(mark):
    """`.disabled` 里标了 DEPRECATED 的是永久废弃，否则只是临时停用。"""
    if not os.path.exists(mark):
        return False
    try:
        with open(mark, encoding="utf-8", errors="replace") as fh:
            return "DEPRECATED" in fh.read(400).upper()
    except OSError:
        return False


def off_badge(op, temporary="停用", temporary_en="Temporarily disabled"):
    if not op.get("disabled"):
        return ""
    if op.get("deprecated"):
        return '<span class="badge off">%s</span>' % t("已废弃", "Retired")
    return '<span class="badge off">%s</span>' % t(temporary, temporary_en)


def warn_badge(op):
    """`docs` 层面的「不推荐」：算子照常编译发布，只是别拿它当首选。"""
    return '<span class="badge warn">%s</span>' % t("不推荐", "Not recommended") \
        if op.get("discouraged") else ""


def en_blurb(op, n=90):
    """卡片上的一句话：优先用 tools/site/en 里手写的 blurb（比文件头
    purpose 的英文更紧凑、且每篇都有），其次回退到文件头的英文行。"""
    e = load_en(op)
    txt = (e or {}).get("blurb") or op["purpose_en"]
    return short(txt, n) if txt else short(op["purpose_text"], n)


def card(op):
    badge = off_badge(op) + warn_badge(op)
    return """<a class="card" href="ops/{slug}.html">
  <div class="card-top">
    <span class="tag t-{g}">{tag}</span>
    <code>{oid}</code>
    {badge}
  </div>
  <h3>{menu}</h3>
  <p>{blurb}</p>
  <span class="more">{more}</span>
</a>""".format(slug=op["dir"], g=op["group"].lower(),
               tag=t(GROUP_ZH[op["group"]][1], GROUP_ZH[op["group"]][0]),
               oid=html.escape(op["id"]),
               badge=badge,
               menu=t(html.escape(op["menu"]), html.escape(en_name(op))),
               blurb=t(inline(short(op["purpose_text"])), inline(en_blurb(op))),
               more=t("读算法说明 →", "Read the notes →"))


def group_section(g, ops):
    members = [o for o in ops if o["group"] == g]
    if not members:
        return ""
    return """
<section class="group" id="g-{g}">
  <h3 class="group-title"><span class="tag t-{gl}">{tag}</span>
    <span class="group-en">{ge}</span><span class="count">{n}</span></h3>
  <p class="group-desc">{desc}</p>
  <div class="cards">
{cards}
  </div>
</section>""".format(g=g, gl=g.lower(),
                     tag=t(GROUP_ZH[g][1], GROUP_ZH[g][0]),
                     ge=t(GROUP_ZH[g][0], ""),
                     n=t("%d 个" % len(members), "%d" % len(members)),
                     desc=t(GROUP_DESC[g], GROUP_DESC_EN[g]),
                     cards="\n".join("    " + card(o) for o in members))


# --------------------------------------------------------------------------
# 页面
# --------------------------------------------------------------------------

def build_index(ops, stats, version):
    n_live = sum(1 for o in ops if not o.get("deprecated"))
    n_dep = len(ops) - n_live
    dep_note = ('<span class="muted">%s</span>' %
                t("另有 %d 个已废弃，只作存档。" % n_dep,
                  "Plus %d retired, kept as an archive." % n_dep)) if n_dep else ""
    by_g = "\n".join(group_section(g, ops) for g in SMG.GROUPS)

    hero = """<section class="hero">
  <p class="eyebrow">GIMP 3.x · GEGL 0.4 · GPL-3.0</p>
  <h1><span class="l-zh">给 GIMP 3 的一整套<br><span class="grad">色彩算子</span></span><span class="l-en">A complete set of<br><span class="grad">colour operators</span> for GIMP 3</span></h1>
  <p class="lede"><span class="l-zh">{n} 个 <code>lb:</code> 前缀的 GEGL 算子，覆盖色阶、色彩平衡、自然饱和度、
     白平衡、通道混合、蒙版生成。每个都是单文件 C，装完即用，能当非破坏滤镜挂在图层上。</span><span class="l-en">{n} GEGL operators with the <code>lb:</code> prefix, covering levels, colour
     balance, vibrance, white balance, channel mixing and mask building. Each one is a
     single C file, works out of the box, and mounts on a layer as a non-destructive
     fx filter.</span>
     {dep}</p>
  <div class="cta">
    <a class="btn primary" href="#download"><span class="l-zh">下载 Windows 包</span><span class="l-en">Download the Windows bundle</span><span class="size">{size} MB</span></a>
    <a class="btn" href="#ops"><span class="l-zh">浏览 {n} 个算子</span><span class="l-en">Browse the {n} operators</span></a>
    <a class="btn ghost" href="guide.html"><span class="l-zh">怎么装</span><span class="l-en">How to install</span></a>
  </div>
  <ul class="facts">
    <li><b>{n}</b> <span class="l-zh">个算子</span><span class="l-en">operators</span></li>
    <li><b>5</b> <span class="l-zh">个分类</span><span class="l-en">categories</span></li>
    <li><b>0</b> <span class="l-zh">依赖 · 免编译包</span><span class="l-en">dependencies · prebuilt</span></li>
    <li><b>{files}</b> <span class="l-zh">个 Windows 模块已随仓库发布</span><span class="l-en">Windows modules shipped with the repo</span></li>
  </ul>
</section>""".format(n=n_live, dep=dep_note, size=stats["zip_mb"], files=stats["win_files"])

    steps = """<section class="steps" id="start">
  <h2><span class="l-zh">三分钟装上</span><span class="l-en">Set up in three minutes</span></h2>
  <ol class="step-list">
    <li>
      <h3><span class="l-zh">解开压缩包</span><span class="l-en">Unpack the archive</span></h3>
      <p><span class="l-zh">把 {files} 个 <code>.dll</code> 放进 GEGL 的用户插件目录，目录不存在就自己建一个：</span><span class="l-en">Drop the {files} <code>.dll</code> files into GEGL's user plug-in directory — create it if it doesn't exist:</span></p>
      <pre><code>%LOCALAPPDATA%\\gegl-0.4\\plug-ins</code></pre>
    </li>
    <li>
      <h3><span class="l-zh">重启 GIMP</span><span class="l-en">Restart GIMP</span></h3>
      <p><span class="l-zh">没有安装步骤，也没有注册表。GEGL 启动时扫描这个目录，GIMP 跟着加载。</span><span class="l-en">No installer, no registry. GEGL scans that directory at startup and GIMP picks the modules up.</span></p>
    </li>
    <li>
      <h3><span class="l-zh">在菜单里找</span><span class="l-en">Find them in the menu</span></h3>
      <p><span class="l-zh">滤镜位于 <code>图像 → 颜色 → SuperMrWang</code>：色阶家族收在一级目录
     <b>Levels</b> 子菜单里（Levels / LAB / HSL / HSB / LCH / CMYK / HSI），
     分量家族的 dual / compose 与 gray-to-component 收在一级目录 <b>Component</b> 里，
     其余按 Tone / Color / Blend / Mask 四组排开；
     也可以按 <code>/</code> 搜算子名直接调。</span><span class="l-en">The filters live under <code>Colors → SuperMrWang</code>: the levels family is
     grouped in a top-level <b>Levels</b> submenu (Levels / LAB / HSL / HSB / LCH /
     CMYK / HSI), the component family (dual / compose pairs and gray-to-component)
     in a top-level <b>Component</b> submenu, and the rest in four groups —
     Tone / Color / Blend / Mask. You can also press <code>/</code> and search by
     operator name.</span></p>
    </li>
  </ol>
</section>""".format(files=stats["win_files"])

    if stats.get("zip_linux_name"):
        _miss = stats.get("linux_missing") or []
        _miss_zh = ("　注意：component 家族那 %d 个模块（各空间的 dual / compose 与 "
                    "gray-to-component）还没出包，要用就 <code>./build.sh</code> 自编"
                    "（Windows 端齐全）。" % len(_miss)) if _miss else ""
        _miss_en = (" Note: the %d component modules (dual / compose for each "
                    "space, plus gray-to-component) are not in this bundle yet — "
                    "build them with <code>./build.sh</code> (the Windows bundle "
                    "has them all)." % len(_miss)) if _miss else ""
        lin_body = """<p><span class="l-zh">{lin} 个 <code>.so</code>（{lsize} MB）。解到
         <code>~/.local/share/gegl-0.4/plug-ins</code>，重启 GIMP 即可。{misszh}</span><span class="l-en">{lin} <code>.so</code> files ({lsize} MB). Unpack into
         <code>~/.local/share/gegl-0.4/plug-ins</code> and restart GIMP.{missen}</span></p>
      <a class="btn" href="download/{lzip}">gegl-color-ops-linux-x64.zip</a>
      <p class="muted small">{chk}<code>SHA256 {lsha}</code></p>""".format(
            lin=stats["linux_files"], lsize=stats["zip_linux_mb"],
            lzip=stats["zip_linux_name"], lsha=stats["zip_linux_sha"][:32] + "…",
            misszh=_miss_zh, missen=_miss_en,
            chk=t("校验：", "Checksum: "))
    else:
        lin_body = """<p><span class="l-zh">暂时没有预编译包，跑 <code>./build.sh</code> 自己编（需要 GEGL 开发头文件）。</span><span class="l-en">No prebuilt bundle yet — build your own with <code>./build.sh</code> (needs GEGL development headers).</span></p>
      <a class="btn" href="{repo}/tree/main/dist/linux-x64"><span class="l-zh">看 Linux 目录</span><span class="l-en">Browse the Linux directory</span></a>""".format(repo=REPO)

    download = """<section class="download" id="download">
  <h2><span class="l-zh">下载</span><span class="l-en">Download</span></h2>
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Windows x64</h3><span class="pill">{rec}</span></div>
      <p><span class="l-zh">{n} 个 <code>.dll</code>（{size} MB）。解到
         <code>%LOCALAPPDATA%\\gegl-0.4\\plug-ins</code>，重启 GIMP 即可。</span><span class="l-en">{n} <code>.dll</code> files ({size} MB). Unpack into
         <code>%LOCALAPPDATA%\\gegl-0.4\\plug-ins</code> and restart GIMP.</span></p>
      <a class="btn primary" href="download/{zip}">gegl-color-ops-windows-x64.zip</a>
      <p class="muted small">{chk}<code>SHA256 {sha}</code></p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Linux x86_64</h3></div>
      {lin_body}
    </div>
    <div class="dl">
      <div class="dl-head"><h3>{single}</h3></div>
      <p><span class="l-zh">只想试一个？每个算子的文章页底部有它自己的模块直链。模块之间
         互不依赖（只链接 GIMP 自带的 GEGL 与 babl），下一个就是完整的。
         也可以从仓库里挑：<code>dist/windows-x64/&lt;名字&gt;.dll</code>、
         <code>dist/linux-x64/&lt;名字&gt;.so</code>。</span><span class="l-en">Just one? Every operator page links its own module at the bottom.
         Modules never depend on each other here — only on the GEGL and babl that
         ship with GIMP — so one file is complete. Or pick from the repo:
         <code>dist/windows-x64/&lt;name&gt;.dll</code>,
         <code>dist/linux-x64/&lt;name&gt;.so</code>.</span></p>
      <a class="btn ghost" href="{repo}/tree/main/dist/windows-x64">{browse}</a>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>{pyplug}</h3><span class="pill">{pypill}</span></div>
      <p><span class="l-zh">Layer to Selection / Layer to Channel 以及 Shortcut 里那些一键效果，
         每个插件一个包，<b>插件用到的算子模块已经打在包里</b>，下一次就齐。
         <code>.py</code> 进 GIMP 的 plug-ins，附带的模块进 GEGL 的 plug-ins。</span><span class="l-en">Layer to Selection / Layer to Channel and the one-click effects under
         Shortcut: one zip each, and <b>the operator modules a plug-in needs are
         already inside</b>. The <code>.py</code> goes into GIMP's plug-ins, the
         bundled modules into GEGL's plug-ins.</span></p>
      <a class="btn ghost" href="plugins.html">{goplugins}</a>
    </div>
  </div>
  <p class="note"><span class="l-zh">装不上、菜单里看不到、和 GIMP 自带算子重名——都写在
     <a href="guide.html">安装指南</a> 的排错一节。源码编译走 <code>./build.sh</code> 或 meson，同样在那一页。</span><span class="l-en">Won't install, missing from the menu, name clashes with a built-in — the
     troubleshooting section of the <a href="guide.html">install guide</a> covers all of it.
     Building from source via <code>./build.sh</code> or meson is on the same page.</span></p>
</section>""".format(n=stats["win_files"], size=stats["zip_mb"], zip=stats["zip_name"],
                     sha=stats["zip_sha"][:32] + "…", lin_body=lin_body,
                     repo=REPO, chk=t("校验：", "Checksum: "),
                     rec=t("推荐", "Recommended"),
                     single=t("单个算子", "A single operator"),
                     browse=t("浏览模块列表", "Browse the module list"),
                     pyplug=t("Python 插件", "Python plug-ins"),
                     pypill=t(".py · 免编译", ".py · no build"),
                     goplugins=t("去插件页下载", "Get them on the plug-ins page"))

    about = """<section class="about">
  <h2><span class="l-zh">这些算子是怎么来的</span><span class="l-en">Where these operators come from</span></h2>  <p><span class="l-zh">多数是按黑盒标定做的：拿目标实现（多为常见修图软件的调整图层）做对照，逐档采样、
     拟合公式，再在 16 位精度上把残差压到几码以内——只看输入输出，不读对方的代码。
     少数是直接实现公开的数学定义（Lab / LCh / HSL 色阶就是换了个色彩空间做同一件事）。</span><span class="l-en">Most were built by black-box calibration: sample a reference implementation
     (usually a well-known photo editor's adjustment layers) step by step, fit the
     formula, then press the residual down to a few code values at 16-bit precision —
     inputs and outputs only, no source reading. A few implement published mathematical
     definitions directly (the Lab / LCh / HSL levels are the same model in a different
     colour space).</span></p>
  <p><span class="l-zh">所以每篇算法说明里都有误差表、以及「哪一段没能对上、偏差多大」。没有说成
     「完全一致」的地方，都是实测过确实对不上——例如色温 / 色调对角线上的硬裁切。</span><span class="l-en">That's why every algorithm note carries an error table plus a note on which
     part didn't match and by how much. Anything not described as identical was measured
     and genuinely doesn't match — the hard clipping along the colour temperature / tint
     diagonals, for example.</span></p>
  <p class="muted"><span class="l-zh">算法来源在文件头 <code>reference</code> 字段里逐条标注，源码与文档在同一个仓库。</span><span class="l-en">Sources are listed per operator in the <code>reference</code> field of each file
     header; source and docs share one repository.</span></p>
</section>"""

    legal = """<section class="about" id="legal">
  <h2><span class="l-zh">版权与商标</span><span class="l-en">Copyright &amp; trademarks</span></h2>
  <p><span class="l-zh">这里的算子都是自己写的：按公开的数学公式与可观察的行为实现，没有复制任何商业软件的
     源代码或二进制，没有反编译产物，也不调用任何厂商的专有接口或 SDK。</span><span class="l-en">Every operator here was written from scratch: implemented from published
     mathematics and observable behaviour, with no vendor source code or binaries
     copied, no decompilation, and no calls to proprietary interfaces or SDKs.</span></p>
  <p><span class="l-zh">菜单名、对话框标题、算子显示名与页面正文都是本项目自定表述（<code>lb:</code>
     命名空间），不使用任何厂商的 logo、图标或界面截图。仅对业界公开的格式与色空间规范
     沿用标准名称（如 <code>.cube</code> LUT、Adobe RGB），属于指示性引用，不表示与
     本项目存在隶属关系。站点截图是在 GIMP 里运行本项目算子的界面。</span><span class="l-en">Menu names, dialog titles, operator labels and page copy are this project's own
     wording (the <code>lb:</code> namespace); no vendor logo, icon or UI screenshot is
     used. Standard names of industry-published formats and colour spaces (such as
     <code>.cube</code> LUTs or Adobe RGB) are cited nominatively only and imply no
     affiliation. Site screenshots show this project's own operators running in GIMP.</span></p>
  <p class="muted"><span class="l-zh">所有代码均为原创，依据公开数学与可观察行为自行实现，不使用任何厂商专有接口或
     SDK；名称与文案为本项目自定表述，标准格式与色空间名称仅作指示性引用，不构成隶属关系。
     如认为此处有不当使用，请开 issue，核实后会调整措辞或移除相关内容。</span><span class="l-en">All code here is original, written from published mathematics and observable
     behaviour, with no vendor-specific interfaces or SDKs. Names and copy are this
     project's own; standard format and colour-space names are cited nominatively only.
     This project is not affiliated with, endorsed by, or authorised by any vendor.
     If you believe something here is misused, open an issue and it will be reworded
     or removed once verified.</span></p>
</section>"""

    body = hero + steps + """
<section class="ops" id="ops">
  <h2>{n}</h2>
  <p class="section-lede"><span class="l-zh">按「找算子时的念头」分了六组，和 GIMP 菜单里的分组一致——
     七个色阶收在 Levels 一级目录里，分量家族收在 Component 一级目录里。
     点任一算子进去看算法、参数与实测误差。</span><span class="l-en">Six groups organised by the question you ask when hunting for an operator,
     matching the GIMP menu grouping — the levels family and the component family
     each sit in their own top-level submenu. Open any operator for its algorithm,
     parameters and measured error.</span></p>
{by_g}
</section>""".format(n=t("%d 个算子" % n_live, "%d operators" % n_live), by_g=by_g) \
        + download + about + legal

    return page("gegl-color-ops · GIMP 3 色彩算子集", body,
                desc="%d 个 GEGL 色彩算子，供 GIMP 3 使用：色阶、色彩平衡、自然饱和度、"
                     "白平衡、通道混合、蒙版。免编译包直接下载。" % n_live,
                titles=("gegl-color-ops · GIMP 3 色彩算子集",
                        "gegl-color-ops · colour operators for GIMP 3"))


def build_ops_index(ops, version):
    n_live = sum(1 for o in ops if not o.get("deprecated"))
    n_dep = len(ops) - n_live
    rows = []
    for g in SMG.GROUPS:
        members = [o for o in ops if o["group"] == g]
        if not members:
            continue
        rows.append('<h2 id="g-%s"><span class="tag t-%s">%s</span> %s</h2>'
                    % (g, g.lower(), GROUP_ZH[g][1], GROUP_DESC[g]))
        rows.append('<div class="table-wrap"><table class="op-table">')
        rows.append("<thead><tr><th>菜单名</th><th>GEGL id</th><th>类型</th>"
                    "<th>做什么</th></tr></thead><tbody>")
        for o in members:
            off = (" " + off_badge(o) + warn_badge(o)) if (o["disabled"] or o["discouraged"]) else ""
            rows.append('<tr><td><a href="ops/%s.html"><b>%s</b></a>%s</td>'
                        '<td><code>%s</code></td><td class="nowrap">%s</td><td>%s</td></tr>'
                        % (o["dir"], html.escape(o["menu"]), off, html.escape(o["id"]),
                           html.escape(o["type"]), inline(short(o["purpose_zh"], 70))))
        rows.append("</tbody></table></div>")

    body = """<section class="page-head">
  <p class="eyebrow"><a href="index.html">首页</a> / 算子清单</p>
  <h1>{n} 个算子</h1>
  <p class="lede">按 GIMP 菜单里的分组排列。点名字进算法说明。{dep}</p>
</section>
<section class="prose wide">
{rows}
</section>""".format(n=n_live, rows="\n".join(rows),
                   dep=("其中 %d 个已废弃，只作存档、不提供下载。" % n_dep) if n_dep else "")
    return page("算子清单 · gegl-color-ops", body, desc="全部算子的清单与一句话说明")


def split_legacy_intro(md):
    """把 README 里的「旧版插件文档」切出来。

    ops/ 下有九个 README 还带着最初作为独立插件时的说明：编译命令按旧目录结构写、
    菜单路径带 WB 后缀、全文没有一句算法。这些内容与现在的算子对不上，直接铺在
    页面上只会误导。切出来单放进 <details> 折叠，正文只留当前说明。

    旧文档的边界很规整：正文是 `## English` → `## 中文` 这一段双语安装说明；
    它前面紧邻的「本文件是该滤镜的原始说明文档」提示与 `# GEGL_GIMP_PLUGIN_*`
    标题也算旧文档。有些 README（xyz-multiply / hsl-seven）在提示之后还写了当前
    实现说明，所以不能简单地「从文件头切到文件尾」。

    返回 (正文 md, 旧文档 md 或 None)。
    """
    m_en = re.search(r"^##\s+English\s*$", md, re.M)
    if not m_en:
        return md, None

    # 起点：English 之前紧邻的一串「提示 / GEGL_GIMP_PLUGIN 标题 / 图片 / 分隔线」
    # 算旧文档；遇到别的行（正文、其它引用块、代码块）就停 —— hsl-seven 的
    # 实现说明、xyz-multiply 的整段当前文档都紧在 English 前面，不能一起折叠。
    _LEAD = (r"(?:[ \t]*\n"
             r"|!\[[^\]]*\]\([^)]*\)[ \t]*\n"
             r"|#\s+GEGL_GIMP_PLUGIN_[^\n]*\n"
             r"|---[ \t]*\n"
             r"|>\s*本文件是该滤镜的(?:原始)?说明文档[^\n]*\n(?:>[^\n]*\n)*)*")
    m_lead = re.search(r"(?:\A|\n)(" + _LEAD + r")\Z", md[:m_en.start()])
    start = len(md[:m_en.start()]) if not m_lead else m_en.start() - len(m_lead.group(1))

    # 终点：《## 中文》那一节的末尾（其后第一个二级标题，或文件结束）
    base = m_en.end()
    zh = re.search(r"^##\s+中文\s*$", md[base:], re.M)
    if zh:
        base += zh.end()
    nxt = re.search(r"^##\s+", md[base:], re.M)
    end = base + nxt.start() if nxt else len(md)

    # 只有真的是旧插件文档才折成「原始介绍」；有的 README 的 English 段是当前
    # 说明的正经翻译（color-balance 的英文里还带着算法），那该走 en-block，
    # 不能贴上「已过时」的标签。判据：旧文档是「English + 中文」双语的安装说明。
    region = md[m_en.start():end]
    lead = md[start:m_en.start()]
    if not (re.search(r"^##\s+中文\s*$", region, re.M) and
            ("build_linux.sh" in region or "How to Open the Plugin" in region)):
        return md, None

    legacy = md[start:end]
    tail = re.sub(r"\A\s*---[ \t]*\n", "", md[end:])
    head = md[:start]
    legacy = re.sub(r"\n+---[ \t]*\s*$", "", legacy.rstrip("\n")).strip("\n")

    return (head + "\n\n" + tail).strip("\n"), (legacy or None)


_EN_CACHE = {}


def _cap(s):
    """英文 blurb 原稿多以「the classic editor's …」开头，单独当 lede / 卡片文案时
    需要句首大写；只动第一个字母，中英文都安全。"""
    return (s[:1].upper() + s[1:]) if s[:1].islower() else s


def load_en(op):
    """读 tools/site/en/<dir>.md：front matter 给 name / blurb，其后是正文 md。

    英文版按整页切换，所以单独放文件，而不是塞进 README —— README 是给仓库读者
    看的双语安装说明，跟这里的「当前算法说明」不是一回事。
    """
    d = op["dir"]
    if d in _EN_CACHE:
        return _EN_CACHE[d]
    p = os.path.join(EN_DIR, d + ".md")
    ent = None
    if os.path.exists(p):
        txt = open(p, encoding="utf-8").read().replace("\r\n", "\n")
        meta, body = {}, txt
        m = re.match(r"\A---\n(.*?)\n---\n", txt, re.S)
        if m:
            for line in m.group(1).split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = txt[m.end():]
        ent = {"name": meta.get("name") or op["menu"],
               "blurb": _cap(meta.get("blurb") or ""),
               "md": body.strip("\n")}
    _EN_CACHE[d] = ent
    return ent


def en_name(op):
    e = load_en(op)
    return e["name"] if e else op["menu"]


def split_legacy_bilingual(md):
    """旧文档是「## English … ## 中文 …」双语的，按语言切成两份各自折叠。"""
    m = re.search(r"^##\s+中文\s*$", md, re.M)
    if not m:
        return md.strip("\n"), ""
    en = md[:m.start()]
    zh = md[m.end():]
    en = re.sub(r"^##\s+English\s*$\n?", "", en, flags=re.M)
    # 开头那两行中文提示（「构建命令按旧目录结构书写」）只对中文读者有意义
    en = re.sub(r"^>[^\n]*\n", "", en, flags=re.M)
    return zh.strip("\n"), en.strip("\n")


TYPE_EN = {
    "逐像素": "per-pixel",
    "整块区域": "area",
    "双输入 · 逐像素": "two inputs · per-pixel",
    "双输入": "two inputs",
    "生成器": "generator",
}


def download_html(op, lang):
    en = lang == "en"
    if op.get("deprecated"):
        if en:
            return """<div class="op-dl">
  <div>
    <h3>Retired — no download</h3>
    <p>This operator is no longer compiled or shipped. For per-channel grading use
       the <a href="hsl-levels.html">HSL</a>, <a href="hsb-levels.html">HSB</a>,
       <a href="lch-levels.html">LCh</a>, <a href="cmyk-levels.html">CMYK</a> and
       <a href="hsi-levels.html">HSI</a> levels instead — one step, no
       decompose-then-encode round trip. The source stays in
       <code>ops/gray-to-component/</code>; the reason is in the
       <code>.disabled</code> file there.</p>
  </div>
</div>"""
        return """<div class="op-dl">
  <div>
    <h3>已废弃，不提供下载</h3>
    <p>这个算子不再编译，也不再进安装包。分量调色改用
       <a href="hsl-levels.html">HSL</a>、<a href="hsb-levels.html">HSB</a>、
       <a href="lch-levels.html">LCh</a>、<a href="cmyk-levels.html">CMYK</a>、
       <a href="hsi-levels.html">HSI</a> 色阶，一步调完，不用先分解再编码。
       源码仍保留在仓库 <code>ops/gray-to-component/</code>，废弃原因见那里的
       <code>.disabled</code>。</p>
  </div>
</div>"""

    f = op["module"]
    lines, btns = [], []
    if op["has_dll"]:
        if en:
            lines.append('Windows module <code>%s.dll</code>, drop it into '
                         '<code>%%LOCALAPPDATA%%\\gegl-0.4\\plug-ins</code>' % f)
        else:
            lines.append('Windows 模块 <code>%s.dll</code>，放进 '
                         '<code>%%LOCALAPPDATA%%\\gegl-0.4\\plug-ins</code>' % f)
        btns.append('<a class="btn" href="%s/%s.dll">%s %s.dll'
                    '<span class="size">Windows x64</span></a>'
                    % (RAW, f, "Download" if en else "下载", f))
    if op["has_so"]:
        if en:
            lines.append('Linux module <code>%s.so</code>, drop it into '
                         '<code>~/.local/share/gegl-0.4/plug-ins</code>' % f)
        else:
            lines.append('Linux 模块 <code>%s.so</code>，放进 '
                         '<code>~/.local/share/gegl-0.4/plug-ins</code>' % f)
        btns.append('<a class="btn ghost" href="%s/%s.so">%s %s.so'
                    '<span class="size">Linux x86_64</span></a>'
                    % (LIN_RAW, f, "Download" if en else "下载", f))
    if not lines:
        lines.append('This module is not in the prebuilt bundle yet — build it with '
                     '<code>./build.sh</code>' if en else
                     '这一版还没把这个模块打进预编译包，可以 <code>./build.sh</code> 自己编一个')
    if en:
        head = "Just this one"
        tail = ('%s, then restart GIMP. Every module here is a standalone GEGL '
                'module: it links only against the GEGL and babl that ship with '
                'GIMP, never against another module of this project, so one '
                'download is all it needs. The full bundle is on the '
                '<a href="../index.html#download">download page</a>.') % "; ".join(lines)
    else:
        head = "只要这一个"
        tail = ('%s，然后重启 GIMP。这里的每个模块都是独立的 GEGL 模块，只链接 GIMP '
                '自带的 GEGL 与 babl，不依赖本项目里的其它模块——下这一个就够用，'
                '不会缺东西。要一次装齐，用'
                '<a href="../index.html#download">整包</a>。') % "；".join(lines)
    return """<div class="op-dl">
  <div>
    <h3>%s</h3>
    <p>%s</p>
  </div>
  <div class="btns">%s</div>
</div>""" % (head, tail, "".join(btns))


def pager_html(op, lang):
    en = lang == "en"
    nav = ['<nav class="pager">']
    if op["prev"]:
        nav.append('<a class="prev" href="%s.html"><span>%s</span>%s</a>'
                   % (op["prev"]["dir"], "Previous" if en else "上一个",
                      html.escape(en_name(op["prev"]) if en else op["prev"]["menu"])))
    else:
        nav.append("<span></span>")
    if op["next"]:
        nav.append('<a class="next" href="%s.html"><span>%s</span>%s</a>'
                   % (op["next"]["dir"], "Next" if en else "下一个",
                      html.escape(en_name(op["next"]) if en else op["next"]["menu"])))
    nav.append("</nav>")
    return "".join(nav)


def build_article(op, version):
    md = open(op["readme"], encoding="utf-8").read()
    md, legacy_md = split_legacy_intro(md)
    # 去掉 README 自带的标题和「本文件是说明文档」的提示，页面头部自己给。
    # 这两样有时夹在当前说明前面（hsl-seven），所以按行清，不限定在文件头。
    md = re.sub(r"^>\s*本文件是该滤镜的(?:原始)?说明文档[^\n]*\n"
                r"(?:>\s*统一构建方式[^\n]*\n)?\s*", "", md, flags=re.M)
    md = re.sub(r"^#\s+GEGL_GIMP_PLUGIN_[^\n]*\n+", "", md, flags=re.M)
    md = re.sub(r"\A\s*#\s+[^\n]*\n+", "", md)
    md = re.sub(r"\A\s*!\[[^\]]*\]\([^)]*\)\s*\n+", "", md)

    # README 里的图片都写 `assets/xxx.png`；图片实际被拷到 assets/ops/<dir>/ 下，
    # 所以先把 assets/ 前缀去掉，再让转换器统一加前缀
    md = re.sub(r"\]\(assets/", "](", md)
    img_prefix = "../assets/ops/%s/" % op["dir"]

    # 老做法是把 README 末尾的 `## English` 折成一个 <details>；现在英文版是整页
    # 切换的，内容统一在 tools/site/en/<dir>.md。这里只摘掉那一段英文，后面若还有
    # 别的二级标题（color-balance 的「参考 / References」）要留着。
    m = re.search(r"^##\s+English\s*$", md, re.M)
    if m:
        nxt = re.search(r"^##\s+", md[m.end():], re.M)
        cut_end = m.end() + nxt.start() if nxt else len(md)
        md = md[:m.start()] + md[cut_end:]

    body_html, toc = convert(md, image_prefix=img_prefix,
                             link_base=REPO + "/blob/main/")
    body_html = body_html.replace('src="assets/', 'src="%s' % img_prefix)

    en = load_en(op)
    if en:
        en_html, en_toc = convert(en["md"], image_prefix=img_prefix,
                                  link_base=REPO + "/blob/main/")
        en_html = en_html.replace('src="assets/', 'src="%s' % img_prefix)
    else:
        en_html, en_toc = "", []

    legacy_zh, legacy_en = (None, None)
    if legacy_md:
        legacy_zh, legacy_en = split_legacy_bilingual(legacy_md)

    def legacy_details(lang):
        src = legacy_zh if lang == "zh" else legacy_en
        if not src:
            return ""
        # 旧文档里的图片也写 `assets/xxx.png`，和正文一样先剥前缀，否则
        # image_prefix 会拼成 assets/ops/<dir>/assets/xxx.png（死链）。
        src = re.sub(r"\]\(assets/", "](", src)
        h, _ = convert(src, image_prefix=img_prefix,
                       link_base=REPO + "/blob/main/")
        h = h.replace('src="assets/', 'src="%s' % img_prefix)
        summary = ('原始介绍<span class="muted">（这个滤镜作为独立插件时的旧文档：'
                   '编译命令按旧目录结构书写，菜单路径也已改名；算法说明以本页上方为准）'
                   '</span>' if lang == "zh" else
                   'Original plugin docs<span class="muted"> — written when this was a '
                   'standalone plug-in: the build commands assume the old directory '
                   'layout and the menu paths have changed. The algorithm notes above '
                   'supersede it.</span>')
        return ('<details class="legacy-intro"><summary>%s</summary>%s</details>'
                % (summary, h))

    def toc_block(items, lang):
        if not items:
            return ""
        lis = "\n".join('<li class="l%d"><a href="#%s">%s</a></li>'
                        % (lv, anc, html.escape(tl)) for lv, anc, tl in items)
        return """<aside class="toc">
  <p class="toc-title">%s</p>
  <ul>%s</ul>
</aside>""" % ("On this page" if lang == "en" else "本页目录", lis)

    def head_block(lang):
        en_ = lang == "en"
        meta = """<div class="meta">
    <code>%s</code>
    <span class="tag t-%s">%s</span>
    <span>%s</span>%s
  </div>""" % (html.escape(op["id"]), op["group"].lower(),
              GROUP_ZH[op["group"]][0 if en_ else 1],
              TYPE_EN.get(op["type"], op["type"]) if en_ else html.escape(op["type"]),
              badges)
        if en_:
            eyebrow = ('<a href="../index.html">Home</a> / <a href="../ops.html">'
                       'Operators</a> / %s' % GROUP_ZH[op["group"]][0])
            name, blurb = en["name"], en.get("blurb") or ""
        else:
            eyebrow = ('<a href="../index.html">首页</a> / <a href="../ops.html">算子</a> / '
                       '%s' % GROUP_ZH[op["group"]][1])
            name, blurb = op["menu"], op["purpose_html"]
        return """<section class="page-head">
  <p class="eyebrow">%s</p>
  <h1>%s</h1>
  %s%s
  <p class="lede">%s</p>
</section>""" % (eyebrow, html.escape(name), meta,
                warn_en if en_ else warn_zh, blurb)

    def one_lang(lang):
        en_ = lang == "en"
        art = (en_html if en_ else body_html) + download_html(op, lang) \
            + pager_html(op, lang) + legacy_details(lang)
        return """%s<div class="article-layout">
  <article class="prose">
%s
  </article>
  %s
</div>""" % (head_block(lang), art, toc_block(en_toc if en_ else toc, lang))

    off = (" " + off_badge(op, "临时停用", "Temporarily disabled") + warn_badge(op)) \
        if (op["disabled"] or op["discouraged"]) else ""
    badges = off

    if op.get("deprecated"):
        warn_zh = ('\n  <p class="dep-note"><b>已废弃</b>　本算子不再编译、不进安装包，'
                   '本页仅作存档。现在每个色彩模式都有自己的分量色阶，不需要「灰度 → '
                   '彩色编码 → 混合模式」这套三步走。</p>')
        warn_en = ('\n  <p class="dep-note"><b>Retired</b> — no longer built or shipped; '
                   'this page is an archive. Every colour model now has its own component '
                   'levels, so the old decompose → colour-encode → blend-mode route is '
                   'obsolete.</p>')
    elif op.get("discouraged"):
        warn_zh = ('\n  <p class="slow-note"><b>不推荐日常使用</b>　邻域双边加 4 次高斯，'
                   '半径 30 时每像素约 1.4 µs：2048×1536 默认参数净耗时 0.7 s、含解码 '
                   '2.1 s，在 GIMP 里拖一次滑杆就重算一遍整图。整体明暗改用 '
                   '<a href="levels.html">色阶</a> / <a href="lab-levels.html">LAB 色阶</a>；'
                   '确实需要「周围亮就少提」的局部行为再回来用它，半径压到 10–15 会快很多。'
                   '详见 <code>ops/shadows-highlights/.discouraged</code>。</p>')
        warn_en = ('\n  <p class="slow-note"><b>Not recommended for daily use</b> — '
                   'bilateral over four Gaussian passes costs about 1.4 µs per pixel at '
                   'radius 30: 0.7 s for a 2048×1536 image at defaults, 2.1 s including '
                   'decode, and every slider drag in GIMP recomputes the whole image. For '
                   'overall brightness use <a href="levels.html">Levels</a> / '
                   '<a href="lab-levels.html">LAB Levels</a>; come back here only when you '
                   'need the local “lift less where the surroundings are bright” '
                   'behaviour, and drop the radius to 10–15 for a big speedup. See '
                   '<code>ops/shadows-highlights/.discouraged</code>.</p>')
    else:
        warn_zh = warn_en = ""

    if en:
        body = ('<div class="l-zh">%s</div>\n<div class="l-en">%s</div>'
                % (one_lang("zh"), one_lang("en")))
        titles = ("%s · gegl-color-ops" % op["menu"],
                  "%s · gegl-color-ops" % en["name"])
    else:
        body = one_lang("zh")
        titles = None

    title = "%s · %s" % (op["menu"], "gegl-color-ops")
    return page(title, body, root="../", desc=op["purpose_text"][:120], titles=titles,
                math=True)


def build_guide(version, stats):
    body = """<section class="page-head">
  <p class="eyebrow"><a href="index.html">首页</a> / 安装</p>
  <h1>安装与排错</h1>
  <p class="lede">没有安装程序，也没有注册表：把模块文件放进 GEGL 的插件目录，重启 GIMP 就完事。</p>
</section>
<article class="prose wide">
  <h2 id="req">环境要求</h2>
  <ul>
    <li><b>GIMP 3.x</b>（3.0 / 3.2 实测），自带 GEGL 0.4。</li>
    <li>Windows x64 用现成的 <code>.dll</code>，Linux x86_64 用 <code>.so</code>。
        Windows 包 <b>{n} 个模块齐全</b>；Linux 包目前 {l} 个，{lm}。</li>
    <li>不需要 Python 运行时——算子是 C 编译的 GEGL 模块。</li>
  </ul>

  <h2 id="install">安装</h2>
  <p>把压缩包解开，把里面的模块文件（<code>.dll</code> / <code>.so</code>）全部放进
     用户插件目录（目录不存在就新建）：</p>
  <div class="table-wrap"><table>
    <thead><tr><th>系统</th><th>目录</th></tr></thead>
    <tbody>
      <tr><td>Windows</td><td><code>%LOCALAPPDATA%\\gegl-0.4\\plug-ins</code></td></tr>
      <tr><td>Linux</td><td><code>~/.local/share/gegl-0.4/plug-ins</code></td></tr>
      <tr><td>macOS</td><td><code>~/Library/Application Support/gegl-0.4/plug-ins</code></td></tr>
    </tbody>
  </table></div>
  <p>然后<b>完全退出 GIMP 再打开</b>（不是关窗口）。模块只在启动时扫描一次。</p>
  <p>确认加载成功，可以在命令行问 GEGL：</p>
  <pre><code>gegl --info lb:hsl-levels</code></pre>
  <p>能打印出参数表就说明注册上了。GIMP 自带的 <code>gegl</code> 在安装目录的
     <code>bin/</code> 里，Windows 上通常是 <code>C:\\Program Files\\GIMP 3\\bin\\gegl.exe</code>。</p>

  <h2 id="use">怎么用</h2>
  <p>菜单在 <code>图像 → 颜色 → SuperMrWang</code>：色阶家族（Levels / LAB / HSL /
     HSB / LCH / CMYK / HSI Levels）收在 <b>Levels</b> 子菜单里，分量家族
     （HSL / Lab / HSI 的 dual + compose 与 gray-to-component）收在 <b>Component</b>
     子菜单里，分量曲线那几个一键插件收在 <b>Shortcut</b> 子菜单里，其余分
     Tone / Color / Blend / Mask 四组。也可以在 <code>/</code>（搜索动作）里直接输算子名。</p>
  <p>绝大多数算子是 <b>Point</b> 或 <b>Filter</b> 类型，GIMP 会把它们当非破坏性 fx
     挂在图层上——参数随时能改，原像素不动。双输入算子（应用图像 / 计算）目前只能合并应用。</p>

  <h2 id="build">自己编（可选）</h2>
  <p>需要 GIMP 3 自带的 GEGL 开发头文件与 gcc（Windows 上 MSYS2 的 mingw64 工具链即可）：</p>
  <pre><code>git clone {repo}.git
cd gegl-color-ops
./build.sh              # 产物在 build/
./install.sh --verify   # 顺带拷进插件目录并逐个验证注册</code></pre>
  <p>Linux / macOS 也可以用 meson：</p>
  <pre><code>export PKG_CONFIG_PATH="/path/to/gimp/lib/pkgconfig"
meson setup build-meson &amp;&amp; ninja -C build-meson</code></pre>

  <h2 id="trouble">排错</h2>
  <h3>菜单里看不到</h3>
  <ul>
    <li>路径对不对：必须是 <code>gegl-0.4/plug-ins</code>，不是 GIMP 的 <code>plug-ins</code>。</li>
    <li>有没有重启：GIMP 启动后才扫描，热拷进去不生效。</li>
    <li>位数/依赖：用 GIMP 自带的那份 GEGL 运行时，别混用系统里另一套 GEGL。</li>
    <li>用 <code>gegl --info lb:xxx</code> 单独验：命令行能看到、GIMP 看不到，通常是 GIMP 版本太旧。</li>
  </ul>
  <h3>同一个算子出现两次 / 报重复注册</h3>
  <p>插件目录里同时存在旧文件名的模块（早期是 12 个独立仓库，文件名不一样）。
     删掉旧名字的 <code>.dll</code> 即可，详见仓库 <code>README.md</code> 的「与旧布局的对应关系」。</p>
  <h3>打开旧图提示未知参数</h3>
  <p>算子升级时偶尔会删掉合并过的参数，旧 XCF 里存的值会丢。加载只警告、不报错，
     但要重新调一次。升级前建议先另存一份。</p>

  <h2 id="code">精度里的「码」是什么</h2>
  <p>算子页和插件页里到处写着「恒等往返 0.0002 码」「残差 0.30 码」——<b>1 码就是 8 位
     图上的一个台阶</b>：0–255 共 256 级，相邻两级之间的差就是 1 码，等于
     <b>1/255 ≈ 0.392%</b>。所以「0.0002 码」的意思是：结果的编码值比原图最多差
     0.0002 个台阶，也就是 RGB 128 变成 128.0002。</p>
  <p>为什么用这把尺子：浮点误差本身没有直观意义（1e-7 是好是坏取决于位深和做过多少次
     运算），换成「折算成 8 位输出会差几级」之后，所有空间、所有位深都可以横向比，
     而且直接对上肉眼的分辨极限。</p>
  <div class="table-wrap"><table>
    <thead><tr><th>数值</th><th>意味着什么</th></tr></thead>
    <tbody>
      <tr><td><b>0.0002 码</b></td><td>1 码的 1/5000，浮点上的一次干净往返</td></tr>
      <tr><td><b>0.0053 码</b></td><td>1 码的 1/190，多层编码累积后的量级，仍不可见</td></tr>
      <tr><td><b>0.49 码</b></td><td>8 位量化本身的下限——任何一次输出 8 位图都躲不掉</td></tr>
      <tr><td><b>1 码</b></td><td>肉眼几乎不可见，并排才勉强看出</td></tr>
      <tr><td><b>3–4 码</b></td><td>开始能看出差异，渐变面上可能看到色带边界</td></tr>
      <tr><td><b>8 码以上</b></td><td>明显偏色或偏亮</td></tr>
    </tbody>
  </table></div>
  <p><b>它衡量的是「输出会不会变」，不是「人眼觉不觉得变」。</b>这里取的是 sRGB 编码值
     （R′G′B′）的最大绝对差——最坏的那个像素、最坏的那个通道，不是平均值。编码空间
     不是感知均匀的：暗部的 1 码比亮部的 1 码更扎眼，要讨论「看起来差多少」得换到
     Lab 里算 ΔE。所以同一份结果，码数是工程判据，ΔE 才是观感判据。</p>
  <p>顺带一提：小于 0.5 码的差异在 8 位图上落不到不同像素上去（四舍五入会抹平它），
     只会在浮点工程图、或者连续叠加几十次同类运算时慢慢显形。这就是为什么插件页里
     会同时给「32 位浮点」和「8 位」两组数字。</p>

  <h2 id="faq">常见问题</h2>
  <h3>和 经典图像编辑器 的调整图层结果一致吗？</h3>
  <p>多数算子的目标是「肉眼与 8 位输出一致」。实测残差写在每篇算法说明里，
     通常是中位 0–4 码；有明确对不上的段落时也会说明（例如 经典图像编辑器 在个别对角线上的硬裁切）。</p>
  <h3>为什么叫 <code>lb:</code> 前缀？</h3>
  <p>GEGL 的 id 必须唯一。前缀避免和 GIMP 自带算子撞名——撞了会静默加载失败，
     所以这个工程里所有 id 和 GType 名都带前缀。</p>
  <h3>会进 GIMP 官方仓库吗？</h3>
  <p>不会。这是独立的第三方算子集，按 GPL-3.0 发布，自己装进用户插件目录即可。</p>
</article>""".format(
        repo=REPO, n=stats["win_files"], l=stats["linux_files"],
        lm=("component 家族那 %d 个模块（hsv / hsl / lab / lch / hsi 各自的 dual 与 "
            "compose，再加 gray-to-component）还没出包，可以 <code>./build.sh</code> "
            "自己编" % len(stats["linux_missing"])
            if stats["linux_missing"] else "与 Windows 一致"))

    return page("安装与排错 · gegl-color-ops", body,
                desc="GIMP 3 GEGL 算子安装、验证与排错")


def build_plugin_zips(out_dir):
    """每个 Python 插件打一个包，与 dll/so 的免编译包同一套路。
    sky-replace 源码保留但带 .disabled，暂不发布。"""
    specs = [
        dict(key="selection", ops=[],
             name="gegl-color-ops-plugin-layer-to-selection.zip",
             src_dir=os.path.join(ROOT, "plugin", "layer-to-selection"),
             py="layer-to-selection.py", menu="Layer to Selection",
             menus="    图层右键 → SuperMrWang → Layer to Selection\n"
                   "    选择 → SuperMrWang → Layer to Selection",
             desc="Layer to Selection：右键任意图层，把它转成当前选区"
                  "（Gray/R/G/B/Alpha、四种组合方式、可反相）。",
             pdb="lb-plugin-layer-to-selection(image, layer, channel, invert, operation)"),
        dict(key="channel", ops=[],
             name="gegl-color-ops-plugin-layer-to-channel.zip",
             src_dir=os.path.join(ROOT, "plugin", "layer-to-channel"),
             py="layer-to-channel.py", menu="Layer to Channel",
             menus="    图层右键 → SuperMrWang → Layer to Channel\n"
                   "    选择 → SuperMrWang → Layer to Channel",
             desc="Layer to Channel：右键任意图层，把它变成一条新的 Alpha 通道"
                  "（恒为灰度：彩色图层先按亮度转灰度，再把灰度值写进通道）。",
             pdb="lb-plugin-layer-to-channel(image, layer, invert, name)"),
        dict(key="hsv", ops=["hsv-dual", "hsv-compose"],
             name="gegl-color-ops-plugin-hsv-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "hsv-split-curves"),
             py="hsv-split-curves.py", menu="HSV Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → HSV Split (Curves) · single\n"
                   "    颜色 → SuperMrWang → Shortcut → HSV Split (Curves) · multi\n"
                   "    图层右键 → SuperMrWang → Shortcut → 同上两条",
             desc="HSV Split (Curves)：在 HSV 空间里调曲线。一张数据图同时携带"
                  "S、V、H（红=S、绿=V、蓝=H/360），三条曲线各管一个分量，再由"
                  "lb:hsv-compose 一起算回颜色。恒等曲线时逐像素还原原图。",
             pdb="lb-plugin-hsv-split-curves(image, drawables, group)\n"
                 "lb-plugin-hsv-split-curves-multi(image, drawables, group)"),
        dict(key="lch", ops=["lch-dual", "lch-compose"],
             name="gegl-color-ops-plugin-lch-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "lch-split-curves"),
             py="lch-split-curves.py", menu="LCh Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → LCh Split (Curves) · single\n"
                   "    颜色 → SuperMrWang → Shortcut → LCh Split (Curves) · multi\n"
                   "    图层右键 → SuperMrWang → Shortcut → 同上两条",
             desc="LCh Split (Curves)：在 CIE LCh 里调曲线。一张数据图同时携带"
                  "L*、C*、h（红=L/100、绿=C/140、蓝=h/360），三条曲线各管一个"
                  "分量。极坐标，所以调彩度不动色相、调色相不动彩度。",
             pdb="lb-plugin-lch-split-curves(image, drawables, group)\n"
                 "lb-plugin-lch-split-curves-multi(image, drawables, group)"),
        dict(key="hsl", ops=["hsl-dual", "hsl-compose"],
             name="gegl-color-ops-plugin-hsl-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "hsl-split-curves"),
             py="hsl-split-curves.py", menu="HSL Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → HSL Split (Curves) · single\n"
                   "    颜色 → SuperMrWang → Shortcut → HSL Split (Curves) · multi\n"
                   "    图层右键 → SuperMrWang → Shortcut → 同上两条",
             desc="HSL Split (Curves)：在 HSL 空间里调曲线。GIMP 没有 HSL 分量混合"
                  "模式，插件用 lb:hsl-dual / lb:hsl-compose 把 S、L、H 打包进一张"
                  "数据图（红=S、绿=L、蓝=H/360），三条曲线各管一个分量。"
                  "恒等曲线时逐像素还原原图。",
             pdb="lb-plugin-hsl-split-curves(image, drawables, group)\n"
                 "lb-plugin-hsl-split-curves-multi(image, drawables, group)"),
        dict(key="lab", ops=["lab-dual", "lab-compose"],
             name="gegl-color-ops-plugin-lab-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "lab-split-curves"),
             py="lab-split-curves.py", menu="Lab Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → Lab Split (Curves) · single\n"
                   "    颜色 → SuperMrWang → Shortcut → Lab Split (Curves) · multi\n"
                   "    图层右键 → SuperMrWang → Shortcut → 同上两条",
             desc="Lab Split (Curves)：在 CIE Lab 空间里调曲线。一张数据图同时携带"
                  "a、b、L*（红=a、绿=b、蓝=L*/100），三条曲线各管一个分量，再由"
                  "lb:lab-compose 一起算回颜色。恒等曲线时逐像素还原原图。",
             pdb="lb-plugin-lab-split-curves(image, drawables, group)\n"
                 "lb-plugin-lab-split-curves-multi(image, drawables, group)"),
        dict(key="hsi", ops=["hsi-dual", "hsi-compose"],
             name="gegl-color-ops-plugin-hsi-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "hsi-split-curves"),
             py="hsi-split-curves.py", menu="HSI Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → HSI Split (Curves) · single\n"
                   "    图层右键 → SuperMrWang → Shortcut → HSI Split (Curves)",
             desc="HSI Split (Curves)：在 HSI 空间里调曲线。HSI 的 I 是 (R+G+B)/3，"
                  "GIMP 的六条分量模式一条也对不上；插件用 lb:hsi-dual / "
                  "lb:hsi-compose 把 S、I、色相挤进一张数据图（红=S、绿=I、蓝=H/360），"
                  "三条曲线各管一个分量。恒等曲线时精确还原。",
             pdb="lb-plugin-hsi-split-curves(image, drawables, group)"),
        dict(key="frequency", ops=[],
             name="gegl-color-ops-plugin-frequency-separation.zip",
             src_dir=os.path.join(ROOT, "plugin", "frequency-separation"),
             py="frequency-separation.py", menu="高低频磨皮 (Frequency Separation)",
             menus="    颜色 → SuperMrWang → Shortcut → 高低频磨皮\n"
                   "    图层右键 → SuperMrWang → Shortcut → 高低频磨皮",
             desc="高低频磨皮：一次生成低频（高斯模糊，管影调与颜色）与高频"
                  "（颗粒合并 + 高通，管细节与质感）两层，恒等时合成就是原图。"
                  "在低频层抹平色块、在高频层修细节，互不干扰。",
             pdb="lb-plugin-frequency-separation(image, drawables, radius, group)"),
        dict(key="dodge", ops=[],
             name="gegl-color-ops-plugin-dodge-burn.zip",
             src_dir=os.path.join(ROOT, "plugin", "dodge-burn"),
             py="dodge-burn.py", menu="双曲线磨皮 (Dodge & Burn)",
             menus="    颜色 → SuperMrWang → Shortcut → 双曲线磨皮\n"
                   "    图层右键 → SuperMrWang → Shortcut → 双曲线磨皮",
             desc="双曲线磨皮：生成提亮、压暗两条曲线层，蒙版全黑。用白色柔边"
                  "画笔在蒙版上涂抹，涂到哪里就提亮/压暗到哪里，没涂的地方与"
                  "原图逐像素相同。",
             pdb="lb-plugin-dodge-burn(image, drawables, amount, group)"),
        dict(key="grey", ops=[],
             name="gegl-color-ops-plugin-neutral-grey.zip",
             src_dir=os.path.join(ROOT, "plugin", "neutral-grey"),
             py="neutral-grey.py", menu="中性灰磨皮 (Neutral Grey)",
             menus="    颜色 → SuperMrWang → Shortcut → 中性灰磨皮\n"
                   "    图层右键 → SuperMrWang → Shortcut → 中性灰磨皮",
             desc="中性灰磨皮：加一张 50% 灰的柔光层，恒等时与原图逐像素相同。"
                  "白色画笔提亮、黑色画笔压暗，反复涂抹把皮肤推平。",
             pdb="lb-plugin-neutral-grey(image, drawables, group)"),
        dict(key="alpha-curves", ops=["channel-range-to-alpha"],
             name="gegl-color-ops-plugin-alpha-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "alpha-curves"),
             py="alpha-curves.py", menu="Alpha Curves（透明通道曲线）",
             menus="    颜色 → SuperMrWang → Mask → Alpha Curves\n"
                   "    图层右键 → SuperMrWang → Shortcut → Alpha Curves",
             desc="Alpha Curves：先把选定颜色通道写进 alpha，再接一条可以随便"
                  "画的曲线（gimp:curves，通道 = Alpha）。两条都是非破坏滤镜，"
                  "梯形、S 形、任意起伏都行。",
             pdb="lb-plugin-alpha-curves(image, drawables, channel, shape)"),
    ]
    zips = {}
    win_src = os.path.join(ROOT, "dist", "windows-x64")
    lin_src = os.path.join(ROOT, "dist", "linux-x64")
    for sp in specs:
        ops = sp.get("ops") or []
        win_dll = [m + ".dll" for m in ops
                   if os.path.exists(os.path.join(win_src, m + ".dll"))]
        lin_so = [m + ".so" for m in ops
                  if os.path.exists(os.path.join(lin_src, m + ".so"))]
        absent = sorted({
            m + ext for m in ops
            for ext, got in ((".dll", m + ".dll" in win_dll),
                             (".so", m + ".so" in lin_so))
            if not got})

        if ops:
            listing = ["    modules-windows-x64/%s" % f for f in win_dll]
            listing += ["    modules-linux-x64/%s" % f for f in lin_so]
            extra = ""
            if absent:
                extra = ("\n注意：Linux 端的 %s 还没进预编译包，这个包里不含。\n"
                         "要用 Linux 就 ./build.sh 自己编一份，Windows 端这里是齐的。\n"
                         % "、".join(absent))
            lin_hint = ("\uff08Linux \u7528 modules-linux-x64 \u91cc\u7684 .so\uff09"
                        if lin_so else "")
            readme = """gegl-color-ops · {py}（GIMP 3 Python 插件）
=====================================================

{desc}

包里有两个东西，要分别放进两个不同的目录——少一个插件就跑不起来：

  1) {py}  →  GIMP 的插件目录
        Windows:  %APPDATA%\\GIMP\\3.x\\plug-ins\\
        Linux:    ~/.config/GIMP/3.x/plug-ins/
        macOS:    ~/Library/Application Support/GIMP/3.x/plug-ins/

  2) modules-windows-x64 里的 .dll{lin_hint}
     →  GEGL 的模块目录（注意不是上面那个）
        Windows:  %LOCALAPPDATA%\\gegl-0.4\\plug-ins
        Linux:    ~/.local/share/gegl-0.4/plug-ins
        macOS:    ~/Library/Application Support/gegl-0.4/plug-ins

  两处都放好之后，完全退出 GIMP 再打开（不是关窗口）。两个目录都只在启动时扫描。

包里附带的模块（{py} 的内部依赖，不用另外去下载）：
{listing}
{extra}
菜单位置：
{menus}

批处理 / 脚本调用（PDB 过程）：
    {pdb}

源码与算法说明：{repo}

GPL-3.0-or-later
""".format(py=sp["py"], desc=sp["desc"], menus=sp["menus"], pdb=sp["pdb"],
           repo=REPO, listing="\n".join(listing), extra=extra,
           lin_hint=lin_hint)
        else:
            readme = """gegl-color-ops · {py}（GIMP 3 Python 插件）
=====================================================

{desc}

安装：把这个 .py 放进 GIMP 的用户插件目录（目录不存在就新建）：
    Windows:  %APPDATA%\\GIMP\\3.x\\plug-ins\\
    Linux:    ~/.config/GIMP/3.x/plug-ins/
    macOS:    ~/Library/Application Support/GIMP/3.x/plug-ins/

这个插件不需要任何额外的算子模块，装这一个文件就够。

然后完全退出 GIMP 再打开。菜单位置：
{menus}

批处理 / 脚本调用（PDB 过程）：
    {pdb}

源码与算法说明：{repo}

GPL-3.0-or-later
""".format(py=sp["py"], desc=sp["desc"], menus=sp["menus"],
           pdb=sp["pdb"], repo=REPO)
        path = os.path.join(out_dir, sp["name"])
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            _zip_add_file(z, os.path.join(sp["src_dir"], sp["py"]), sp["py"])
            for f in win_dll:
                _zip_add_file(z, os.path.join(win_src, f),
                              "modules-windows-x64/" + f)
            for f in lin_so:
                _zip_add_file(z, os.path.join(lin_src, f),
                              "modules-linux-x64/" + f)
            _zip_add_text(z, "安装说明.txt", readme)
        zips[sp["key"]] = {"name": sp["name"], "sha": _sha256_file(path),
                           "kb": round(os.path.getsize(path) / 1024, 1),
                           "win_mods": win_dll, "lin_mods": lin_so,
                           "absent": absent}
    return zips


def build_plugins(version, stats=None):
    """插件总览：和首页同一套「分组 + 方格」，只放入口不写正文。

    结构与算子页一样：分组标题带标签和数量，配一句 group-desc，下面是卡片；
    每个插件讲什么、怎么用、误差多少全在 plugins/<slug>.html 里，点开才看到。
    """
    def card(p):
        return """  <a class="card" href="plugins/{slug}.html">
    <div class="card-top"><span class="tag {cls}">{tag}</span></div>
    <h3>{title}</h3>
    <p>{brief}</p>
    <span class="more">读插件说明 →</span>
  </a>""".format(slug=p["slug"], cls=p["tag"][1], tag=p["tag"][0],
                 title=html.escape(p["title"]), brief=p["brief"])

    def group(key, tag, cls, desc, members):
        return """<section class="group" id="{key}">
  <h3 class="group-title"><span class="tag {cls}">{tag}</span>
    <span class="group-en">{en}</span><span class="count">{n} 个</span></h3>
  <p class="group-desc">{desc}</p>
  <div class="cards">
{cards}
  </div>
</section>""".format(key=key, tag=tag, cls=cls, en=key.capitalize(),
                     n=len(members),
                     desc=desc,
                     cards="\n".join(card(p) for p in members))

    shortcut = [p for p in PD.PAGES if p["area"].startswith("Shortcut")]
    convert = [p for p in PD.PAGES if p["area"] == "图层转换"]
    mask = [p for p in PD.PAGES if p["area"] == "Mask"]

    body = """<section class="page-head">
  <p class="eyebrow"><a href="index.html">首页</a> / Python 插件</p>
  <h1>11 个 Python 插件</h1>
  <p class="lede">免编译的 GIMP 3 插件，装进 <code>plug-ins</code> 目录、重启即用。
     两处入口：<b>图层右键 → SuperMrWang</b>（十一个都在）与
     <b>颜色 → SuperMrWang</b>。</p>
  <ul class="facts">
    <li><b>11</b> 个插件</li>
    <li><b>11</b> 个 PDB 过程</li>
    <li><b>290</b> 条回归断言</li>
    <li><b>0</b> 编译 · 纯 Python</li>
  </ul>
</section>

<div class="prose wide">
{shortcut}
{convert}
{mask}
  <p class="note">安装：<code>bash install-plugin.sh</code> 一次装齐，或从各自的页面
     单独下某一个 <code>.zip</code>；细节见 <a href="guide.html">安装指南</a>。</p>
</div>""".format(
        shortcut=group("shortcut", "Shortcut", "t-color",
                       "五个分量曲线、三个磨皮：把一串手工步骤压成一次点击。",
                       shortcut),
        convert=group("convert", "图层转换", "t-mask",
                      "算子跑完留下的灰度图，一步变成蒙版或选区存档。", convert),
        mask=group("mask", "Mask", "t-mask",
                   "透明度本身当曲线来画：按通道生成 alpha，形状随便画。", mask)
        if mask else "")

    return page("Python 插件 · gegl-color-ops", body,
                desc="GIMP 3 Python 插件：图层转选区 / Alpha 通道，"
                     "HSV / LCh / HSL / Lab / HSI 分量分层曲线，"
                     "高低频 / 双曲线 / 中性灰磨皮——免编译，解压即用")


def build_plugin_article(p, version, stats=None, prev=None, nxt=None):
    """每个插件一篇文章：页头 + 位置/PDB/依赖 + 正文 + 下载 + 翻页。

    十一个插件共用一套骨架，差异全在 plugin_docs.py 里。图层转换那两个不在
    Shortcut 菜单下，所以菜单块直接读 p["menus"]，不写死。
    """
    z = ((stats or {}).get("plugin_zips") or {}).get(p["key"])
    name = p["menu"].split("→")[-1].strip()

    if p["deps"]:
        dep_html = ('<p>%s</p>\n      <ul class="deps">%s</ul>'
                    % (p["deps_note"],
                       "".join("<li><code>%s</code></li>" % d for d in p["deps"])))
    else:
        dep_html = '<p>%s</p>' % p["deps_note"]

    dl = ""
    if z:
        mods = z.get("win_mods") or []
        absent = z.get("absent") or []
        if mods:
            pill = "含 %d 个模块 · 免编译" % len(mods)
            note = ("包里有一个 <code>.py</code>、%d 个算子模块和一份安装说明。"
                    "<b>算子依赖已经附在里面，不用另外去下。</b>"
                    "<code>.py</code> 进 GIMP 的 <code>plug-ins</code>，模块进 GEGL 的 "
                    "<code>gegl-0.4/plug-ins</code>——两个目录不一样，包内说明分步写了。"
                    % len(mods))
        else:
            pill = ".py · 免编译"
            note = ("包里只有一个 <code>.py</code> 和一份安装说明。解压到 GIMP 的 "
                    "<code>plug-ins</code> 目录（Windows "
                    "<code>%%APPDATA%%\\GIMP\\3.x\\plug-ins</code>，Linux "
                    "<code>~/.config/GIMP/3.x/plug-ins</code>），<b>重启 GIMP</b> 才注册。")
        if absent:
            note += (" Linux 端的 %s 还没进预编译包，要用 Linux 就 "
                     "<code>./build.sh</code> 自己编一份（Windows 端齐全）。"
                     % "、".join(absent))
        dl = """<section class="download" id="download">
  <h2>下载这一个</h2>
  <div class="dl primary-dl">
    <div class="dl-head"><h3>%s</h3><span class="pill">%s</span></div>
    <p>%s</p>
    <a class="btn primary" href="../download/%s">下载 %s</a>
    <p class="muted small">%s KB · 校验：<code>SHA256 %s…</code></p>
  </div>
</section>""" % (name, pill, note, z["name"], name, z["kb"], z["sha"][:32])

    def pager_link(q, label, cls):
        if not q:
            return ""
        return ('<a class="%s" href="%s.html"><span>%s</span>%s</a>'
                % (cls, q["slug"], label, q["title"]))

    pager = """<nav class="pager">
  <a href="../plugins.html"><span>回到</span>Python 插件总览</a>
  %s%s
</nav>""" % (pager_link(prev, "上一篇", "prev"), pager_link(nxt, "下一篇", "next"))

    menu_html = "".join("<li>%s</li>" % m for m in p["menus"])
    body = """<section class="page-head">
  <p class="eyebrow"><a href="../index.html">首页</a> / <a href="../plugins.html">插件</a>
    / %s</p>
  <h1>%s</h1>
  <div class="meta">
    <code>plugin/%s</code>
    <span class="tag %s">%s</span>
    <span>%s</span>
  </div>
  <p class="lede">%s</p>
</section>

<div class="prose wide">
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>菜单位置</h3><span class="pill">多条</span></div>
      <ul class="menu-list">%s</ul>
      <p>这几条是同一个动作，处理的是<b>当前选中的那一个图层</b>。图层组不行——
         组没有自己的像素，会直接报错并提示先合并。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>脚本调用</h3></div>
      <pre><code>%s</code></pre>
      <p>标准 PDB 过程，参数留空走默认值。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>依赖</h3></div>
      %s
    </div>
  </div>

%s

%s

<p class="note">文中「码」指 8 位图上的一个台阶：0–255 共 256 级，相邻两级的差就是
   1 码，等于 1/255 ≈ 0.392%%（也就是 RGB 128 与 129 之间的差）。各数量级的含义与
   「码为什么不是感知量」的说明见
   <a href="../guide.html#code">安装指南 · 精度里的「码」</a>。</p>

%s
</div>""" % (p["area"], p["title"], p["slug"], p["tag"][1], p["tag"][0],
             p["area"], p["lede"], menu_html, p["pdb"], dep_html,
             p["body"], dl, pager)

    return page("%s · Python 插件 · gegl-color-ops" % p["title"], body, root="../",
                desc=re.sub(r"<[^>]+>", "", p["lede"])[:120])


def build_feed(ops, version):
    """一个极简 Atom，方便订阅「最近加了什么」：算子 + Shortcut 八个插件。

    Shortcut 那八条链到站点里的文章页（插件没有 README 可链），日期用加进来的
    那天，排在新加算子之后。
    """
    entries = []
    for sp in reversed(PD.PAGES):
        entries.append("""  <entry>
    <title>{title}</title>
    <link href="{site}/plugins/{slug}.html"/>
    <id>tag:github.com,2026:plugin-{slug}</id>
    <updated>2026-11-17T00:00:00Z</updated>
    <summary>{sum}</summary>
  </entry>""".format(title=html.escape("插件 · " + sp["title"]),
                     site=SITE, slug=sp["slug"],
                     sum=html.escape(re.sub(r"<[^>]+>", "", sp["lede"])[:200])))
    for op in reversed(ops):
        entries.append("""  <entry>
    <title>{menu}</title>
    <link href="{repo}/blob/main/ops/{dir}/README.md"/>
    <id>tag:github.com,2026:{oid}</id>
    <updated>2026-11-15T00:00:00Z</updated>
    <summary>{sum}</summary>
  </entry>""".format(menu=html.escape(op["menu"]), repo=REPO, dir=op["dir"],
                     oid=html.escape(op["id"]),
                     sum=html.escape(op["purpose_text"][:200])))
    return """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>gegl-color-ops · 算子与插件</title>
  <link href="{site}/"/>
  <updated>2026-11-17T00:00:00Z</updated>
  <id>tag:github.com,2026:gegl-color-ops</id>
{entries}
</feed>""".format(site=SITE, entries="\n".join(entries))


# --------------------------------------------------------------------------
# 产物
# --------------------------------------------------------------------------

def sh(*cmd):
    return subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True).stdout.strip()


def collect_stats():
    win = os.path.join(DIST, "windows-x64")
    dlls = sorted(f for f in os.listdir(win) if f.endswith(".dll")) if os.path.isdir(win) else []
    lin = os.path.join(DIST, "linux-x64")
    sos = sorted(f for f in os.listdir(lin) if f.endswith(".so")) if os.path.isdir(lin) else []
    missing = sorted({d[:-4] for d in dlls} - {s[:-3] for s in sos})
    return {"win_files": len(dlls), "dlls": dlls, "win_dir": win,
            "linux_files": len(sos), "sos": sos, "linux_dir": lin,
            "linux_missing": missing}


# 打包用固定时间戳：同一批文件重复打包应当得到同一个 zip，
# 否则每次重建 docs/ 都会因为 mtime 变化刷出一堆二进制改动。
ZIP_EPOCH = (2020, 1, 1, 0, 0, 0)


def _zip_add_file(z, path, arcname):
    info = zipfile.ZipInfo(arcname, date_time=ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with open(path, "rb") as f:
        z.writestr(info, f.read())


def _zip_add_text(z, arcname, text):
    info = zipfile.ZipInfo(arcname, date_time=ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    z.writestr(info, text.encode("utf-8"))


def _sha256_file(path):
    """自己算，不调 sha256sum：Windows 下 os.path.join 会拼出含反斜杠的路径，
    GNU coreutils 见到反斜杠会在整行前加一个 '\\' 做转义，split()[0] 就把这个
    反斜杠也算进摘要值里，页面上展示的校验和因此多一个字符、复制出来是错的。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip_one(out_dir, name, files, root_dir, readme):
    path = os.path.join(out_dir, name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            _zip_add_file(z, os.path.join(root_dir, f), f)
        _zip_add_text(z, "安装说明.txt", readme)
        man = os.path.join(DIST, "manifest.csv")
        if os.path.exists(man):
            _zip_add_file(z, man, "manifest.csv")
    sha = _sha256_file(path)
    size = round(os.path.getsize(path) / (1024 * 1024), 1)
    return path, sha, size


def build_zip(stats, out_dir):
    """两个平台各打一个包。Linux 包只在 dist/linux-x64 有产物时才生成。"""
    win_readme = """gegl-color-ops · Windows x64 免编译包
=====================================

把这些 .dll 全部放进：
    %LOCALAPPDATA%\\gegl-0.4\\plug-ins

然后完全退出 GIMP 再打开。菜单位置：
    图像 -> 颜色 -> SuperMrWang

验证是否加载成功（用 GIMP 自带的 gegl）：
    "C:////Program Files////GIMP 3////bin////gegl.exe" --info lb:hsl-levels

共 {n} 个模块。列表见同目录 manifest.csv，校验和见 SHA256SUMS.txt。
源码与算法说明：{repo}

GPL-3.0-or-later
""".format(n=len(stats["dlls"]), repo=REPO)
    name = "gegl-color-ops-windows-x64.zip"
    path, sha, size = _zip_one(out_dir, name, stats["dlls"], stats["win_dir"], win_readme)
    stats.update(zip_name=name, zip_sha=sha, zip_mb=size)

    if stats["sos"]:
        lin_readme = """gegl-color-ops · Linux x86_64 免编译包
======================================

把这些 .so 全部放进：
    ~/.local/share/gegl-0.4/plug-ins

（等价于 ./install.sh 在 Linux 下的默认目标目录。装到系统目录的话是
 /usr/lib/x86_64-linux-gnu/gegl-0.4，需要 sudo。）

然后完全退出 GIMP 再打开。菜单位置：
    图像 -> 颜色 -> SuperMrWang

验证是否加载成功：
    GEGL_PATH="$HOME/.local/share/gegl-0.4/plug-ins" gegl --info lb:hsl-levels

共 {n} 个模块，x86_64，针对 libgegl-0.4 编译（Ubuntu / Debian 系可直接用；
glibc 版本过旧或发行版差异较大时，建议用 ./build.sh 自己编一遍）。
列表见同目录 manifest.csv，校验和见 SHA256SUMS.txt。
源码与算法说明：{repo}

GPL-3.0-or-later
""".format(n=len(stats["sos"]), repo=REPO)
        lname = "gegl-color-ops-linux-x64.zip"
        lpath, lsha, lsize = _zip_one(out_dir, lname, stats["sos"], stats["linux_dir"], lin_readme)
        stats.update(zip_linux_name=lname, zip_linux_sha=lsha, zip_linux_mb=lsize)

    return path


def main():
    serve = "--serve" in sys.argv
    stats = collect_stats()
    ops = load_ops()
    version = sh("git", "rev-parse", "--short", "HEAD") or "local"

    if os.path.isdir(DOCS):
        shutil.rmtree(DOCS)
    os.makedirs(os.path.join(DOCS, "ops"))
    os.makedirs(os.path.join(DOCS, "assets"))
    os.makedirs(os.path.join(DOCS, "download"))

    build_zip(stats, os.path.join(DOCS, "download"))
    stats["plugin_zips"] = build_plugin_zips(os.path.join(DOCS, "download"))

    # 样式与静态资源（tools/site/en 是英文正文的源文件目录，不是要拷的资源）
    for f in os.listdir(SRC):
        if os.path.isfile(os.path.join(SRC, f)):
            shutil.copy2(os.path.join(SRC, f), os.path.join(DOCS, "assets", f))

    # 每个算子：文章页 + 截图
    for op in ops:
        if os.path.isdir(op["assets"]):
            dst = os.path.join(DOCS, "assets", "ops", op["dir"])
            shutil.copytree(op["assets"], dst)

    with open(os.path.join(DOCS, ".nojekyll"), "w"):
        pass

    globals()["VERSION"] = version

    pages = {
        "index.html": build_index(ops, stats, version),
        "ops.html": build_ops_index(ops, version),
        "plugins.html": build_plugins(version, stats),
        "guide.html": build_guide(version, stats),
        "feed.xml": build_feed(ops, version),
    }
    for op in ops:
        pages["ops/%s.html" % op["dir"]] = build_article(op, version)

    # Shortcut 里每个组件一篇独立文章；翻页在八篇里循环。
    for i, sp in enumerate(PD.PAGES):
        pages["plugins/%s.html" % sp["slug"]] = build_plugin_article(
            sp, version, stats,
            PD.PAGES[i - 1] if i else None,
            PD.PAGES[i + 1] if i + 1 < len(PD.PAGES) else None)

    for name, text in pages.items():
        path = os.path.join(DOCS, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(DOCS) for f in fs)
    print("· docs/ 已生成：%d 个总览页、%d 篇算子文章、%d 个资源文件，共 %.1f MB（含下载包 %.1f MB）"
          % (5, len(ops),
             sum(len(fs) for _, _, fs in os.walk(os.path.join(DOCS, "assets"))),
             total / 1048576, stats["zip_mb"]))
    print("· 分类：" + " / ".join("%s %d" % (GROUP_ZH[g][1],
                                            sum(1 for o in ops if o["group"] == g))
                                  for g in SMG.GROUPS))
    print("· 下载包：docs/download/%s（%d 个模块）" % (stats["zip_name"], stats["win_files"]))
    if stats.get("zip_linux_name"):
        print("           docs/download/%s（%d 个模块）"
              % (stats["zip_linux_name"], stats["linux_files"]))
    for d in (stats.get("plugin_zips") or {}).values():
        print("           docs/download/%s（GIMP 3 Python 插件）" % d["name"])

    # 构建后自检：站内相对链接必须都能落到文件上。缺图这类死链在浏览器里
    # 只是不显示，肉眼极容易漏过，所以构建时就报出来。
    link = re.compile(r'(?:href|src)="([^"#?]+)"')
    missing = []
    n_pages = 0
    for dp, _, fs in os.walk(DOCS):
        for f in fs:
            if not f.endswith(".html"):
                continue
            n_pages += 1
            page = os.path.join(dp, f)
            with open(page, encoding="utf-8") as fh:
                txt = fh.read()
            for url in link.findall(txt):
                if url.startswith(("http://", "https://", "mailto:", "data:", "//")):
                    continue
                if not os.path.exists(os.path.normpath(os.path.join(dp, url))):
                    missing.append("%s -> %s" % (os.path.relpath(page, DOCS), url))
    if missing:
        print("· 站内死链 %d 条 / %d broken local links：" % (len(missing), len(missing)))
        for m in missing[:20]:
            print("    " + m)
    else:
        print("· 站内链接自检通过：%d 个页面无死链 / %d pages, 0 broken links"
              % (n_pages, n_pages))

    if serve:
        import http.server
        import socketserver
        os.chdir(DOCS)
        with socketserver.TCPServer(("127.0.0.1", 8123), http.server.SimpleHTTPRequestHandler) as s:
            print("· http://127.0.0.1:8123/")
            s.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
