# -*- coding: utf-8 -*-
"""把 ops/ 下的算子渲染成一套静态站点，输出到 docs/（带 .disabled 的标停用/废弃）。

设计上把 docs/ 当作纯产物：每次运行整个目录重建，样式源在 tools/site/。
所以改样式改 tools/site/style.css，别直接改 docs/assets/style.css。

算子页是**中英双语**的：中文正文来自 ops/<dir>/README.md，英文正文来自
tools/site/en/<dir>.md（front matter 给 name / blurb）。两套内容同时写进同一个
HTML，靠 <html data-lang> 决定显示哪一套，页头的 中文/EN 按钮切换并记住偏好
（localStorage + ?lang=en）。首页也是双语的；清单页、插件页、安装页只有中文，
不显示切换按钮。

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
ROOT = os.path.dirname(HERE)
OPS = os.path.join(ROOT, "ops")
DIST = os.path.join(ROOT, "dist")
DOCS = os.path.join(ROOT, "docs")
SRC = os.path.join(HERE, "site")

sys.path.insert(0, HERE)
from md2html import convert, inline, plain     # noqa: E402
import set_menu_group as SMG                   # noqa: E402  分组只有这一处数据源

REPO = "https://github.com/SuperMrWang-DEV/gegl-color-ops"
RAW = REPO + "/raw/main/dist/windows-x64"
LIN_RAW = REPO + "/raw/main/dist/linux-x64"

# 算子页的英文版按目录名放这里，每个文件开头一小段 front matter（name / blurb）。
# README 里那些 `## English` 是旧插件的安装说明，不是当前算法的翻译，不能用。
EN_DIR = os.path.join(SRC, "en")

GROUP_ZH = {
    "Levels": ("Levels", "色阶家族"),
    "Tone":  ("Tone",  "影调"),
    "Color": ("Color", "色彩"),
    "Blend": ("Blend", "混合与通道"),
    "Mask":  ("Mask",  "蒙版"),
}

GROUP_DESC = {
    "Levels": "色阶一个不落，全收在一级目录 Levels 里：基础色阶，以及 HSL / HSB / "
              "HSI / LCH / LAB / CMYK 六条分量色阶——同一个黑白场+伽马模型，换个色彩空间。",
    "Tone":  "明暗与影调：曝光、亮度/对比度、阴影-高光、黑白转换。色阶都在上面的 Levels 组。",
    "Color": "调整颜色的方向与浓度：色相饱和度、色彩平衡、白平衡、自然饱和度、可选颜色、匹配颜色。",
    "Blend": "把两层或多路通道混起来：应用图像、计算、通道混合器、XYZ 正片叠底、颜色查找、灰度转分量。",
    "Mask":  "按颜色或数值区间取蒙版：色彩范围、通道区间到 alpha。",
}

GROUP_DESC_EN = {
    "Levels": "Every levels flavour in one top-level Levels submenu: basic Levels plus "
              "six component levels — HSL / HSB / HSI / LCh / Lab / CMYK. One "
              "black-point / white-point + gamma model, six colour spaces.",
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
     其余按 Tone / Color / Blend / Mask 四组排开；
     也可以按 <code>/</code> 搜算子名直接调。</span><span class="l-en">The filters live under <code>Colors → SuperMrWang</code>: the levels family is
     grouped in a top-level <b>Levels</b> submenu (Levels / LAB / HSL / HSB / LCH /
     CMYK / HSI), the rest are laid out in four groups — Tone / Color / Blend / Mask.
     You can also press <code>/</code> and search by operator name.</span></p>
    </li>
  </ol>
</section>""".format(files=stats["win_files"])

    if stats.get("zip_linux_name"):
        lin_body = """<p><span class="l-zh">{lin} 个 <code>.so</code>（{lsize} MB）。解到
         <code>~/.local/share/gegl-0.4/plug-ins</code>，重启 GIMP 即可。</span><span class="l-en">{lin} <code>.so</code> files ({lsize} MB). Unpack into
         <code>~/.local/share/gegl-0.4/plug-ins</code> and restart GIMP.</span></p>
      <a class="btn" href="download/{lzip}">gegl-color-ops-linux-x64.zip</a>
      <p class="muted small">{chk}<code>SHA256 {lsha}</code></p>""".format(
            lin=stats["linux_files"], lsize=stats["zip_linux_mb"],
            lzip=stats["zip_linux_name"], lsha=stats["zip_linux_sha"][:32] + "…",
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
      <p><span class="l-zh">只想试一个？每个算子的文章页底部有它自己的模块直链，
         或者从仓库里挑：<code>dist/windows-x64/&lt;名字&gt;.dll</code>、
         <code>dist/linux-x64/&lt;名字&gt;.so</code>。</span><span class="l-en">Just one? Every operator page links its own module at the bottom,
         or pick from the repo: <code>dist/windows-x64/&lt;name&gt;.dll</code>,
         <code>dist/linux-x64/&lt;name&gt;.so</code>.</span></p>
      <a class="btn ghost" href="{repo}/tree/main/dist/windows-x64">{browse}</a>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>{pyplug}</h3><span class="pill">{pypill}</span></div>
      <p><span class="l-zh">Layer to Selection / Layer to Channel：右键任意图层，一键转成选区
         或 Alpha 通道。每个插件一个包，放进 GIMP 的 plug-ins 目录。</span><span class="l-en">Layer to Selection / Layer to Channel: right-click any layer to turn it
         into a selection or an alpha channel in one click. One zip per plug-in,
         drop it into GIMP's plug-ins directory.</span></p>
      <a class="btn ghost" href="plugins.html#download">{goplugins}</a>
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
  <h2><span class="l-zh">这些算子是怎么来的</span><span class="l-en">Where these operators come from</span></h2>
  <p><span class="l-zh">多数是按黑盒标定做的：拿目标实现（多为常见修图软件的调整图层）做对照，逐档采样、
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
  <p class="section-lede"><span class="l-zh">按「找算子时的念头」分了五组，和 GIMP 菜单里的分组一致——
     七个色阶收在 Levels 一级目录里。点任一算子进去看算法、参数与实测误差。</span><span class="l-en">Five groups organised by the question you ask when hunting for an operator,
     matching the GIMP menu grouping — the levels family sits in one top-level Levels
     submenu. Open any operator for its algorithm, parameters and measured error.</span></p>
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
        tail = ('%s, then restart GIMP. The full bundle is on the '
                '<a href="../index.html#download">download page</a>.') % "; ".join(lines)
    else:
        head = "只要这一个"
        tail = ('%s，然后重启 GIMP。整包在 '
                '<a href="../index.html#download">下载页</a>。') % "；".join(lines)
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
    <li>Windows x64 用现成的 <code>.dll</code>，Linux x86_64 用 <code>.so</code>；
        两端都有预编译包，{n} 个模块齐全。</li>
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
     HSB / LCH / CMYK / HSI Levels）收在 <b>Levels</b> 子菜单里，分量曲线那几个
     一键插件收在 <b>Shortcut</b> 子菜单里，其余分
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

  <h2 id="faq">常见问题</h2>
  <h3>和 经典图像编辑器 的调整图层结果一致吗？</h3>
  <p>多数算子的目标是「肉眼与 8 位输出一致」。实测残差写在每篇算法说明里，
     通常是中位 0–4 码；有明确对不上的段落时也会说明（例如 经典图像编辑器 在个别对角线上的硬裁切）。</p>
  <h3>为什么叫 <code>lb:</code> 前缀？</h3>
  <p>GEGL 的 id 必须唯一。前缀避免和 GIMP 自带算子撞名——撞了会静默加载失败，
     所以这个工程里所有 id 和 GType 名都带前缀。</p>
  <h3>会进 GIMP 官方仓库吗？</h3>
  <p>不会。这是独立的第三方算子集，按 GPL-3.0 发布，自己装进用户插件目录即可。</p>
</article>""".format(repo=REPO, n=stats["win_files"])

    return page("安装与排错 · gegl-color-ops", body,
                desc="GIMP 3 GEGL 算子安装、验证与排错")


def build_plugin_zips(out_dir):
    """每个 Python 插件打一个包，与 dll/so 的免编译包同一套路。
    sky-replace 源码保留但带 .disabled，暂不发布。"""
    specs = [
        dict(key="selection",
             name="gegl-color-ops-plugin-layer-to-selection.zip",
             src_dir=os.path.join(ROOT, "plugin", "layer-to-selection"),
             py="layer-to-selection.py", menu="Layer to Selection",
             menus="    图层右键 → SuperMrWang → Layer to Selection\n"
                   "    选择 → SuperMrWang → Layer to Selection",
             desc="Layer to Selection：右键任意图层，把它转成当前选区"
                  "（Gray/R/G/B/Alpha、四种组合方式、可反相）。",
             pdb="lb-plugin-layer-to-selection(image, layer, channel, invert, operation)"),
        dict(key="channel",
             name="gegl-color-ops-plugin-layer-to-channel.zip",
             src_dir=os.path.join(ROOT, "plugin", "layer-to-channel"),
             py="layer-to-channel.py", menu="Layer to Channel",
             menus="    图层右键 → SuperMrWang → Layer to Channel\n"
                   "    选择 → SuperMrWang → Layer to Channel",
             desc="Layer to Channel：右键任意图层，把它变成一条新的 Alpha 通道"
                  "（恒为灰度：彩色图层先按亮度转灰度，再把灰度值写进通道）。",
             pdb="lb-plugin-layer-to-channel(image, layer, invert, name)"),
        dict(key="hsv",
             name="gegl-color-ops-plugin-hsv-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "hsv-split-curves"),
             py="hsv-split-curves.py", menu="HSV Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → HSV Split (Curves)\n"
                   "    图层右键 → SuperMrWang → Shortcut → HSV Split (Curves)",
             desc="HSV Split (Curves)：把一个图层拆成 H / S / V 三张分量层，每层挂"
                  "一条可编辑曲线，再用 HSV 色相/饱和度/明度三条混合模式叠回去。"
                  "恒等曲线时逐位还原原图。",
             pdb="lb-plugin-hsv-split-curves(image, drawable, group)"),
        dict(key="lch",
             name="gegl-color-ops-plugin-lch-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "lch-split-curves"),
             py="lch-split-curves.py", menu="LCh Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → LCh Split (Curves)\n"
                   "    图层右键 → SuperMrWang → Shortcut → LCh Split (Curves)",
             desc="LCh Split (Curves)：把一个图层拆成 L / C / h 三张分量层，每层挂"
                  "一条可编辑曲线，再用 LCh 明度/彩度/色相三条混合模式叠回去。"
                  "恒等曲线时还原原图。",
             pdb="lb-plugin-lch-split-curves(image, drawable, group)"),
        dict(key="hsl",
             name="gegl-color-ops-plugin-hsl-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "hsl-split-curves"),
             py="hsl-split-curves.py", menu="HSL Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → HSL Split (Curves)\n"
                   "    图层右键 → SuperMrWang → Shortcut → HSL Split (Curves)",
             desc="HSL Split (Curves)：在 HSL 空间里调曲线。GIMP 没有 HSL 分量混合"
                  "模式，插件用 lb:hsl-dual / lb:hsl-compose 把 HSL 精确接到 HSV 上："
                  "S 与 L 合进一张数据图（红=饱和度、绿=明度），色相单独一层。"
                  "恒等曲线时精确还原，调哪条就只动哪个 HSL 分量。",
             pdb="lb-plugin-hsl-split-curves(image, drawable, group)"),
        dict(key="lab",
             name="gegl-color-ops-plugin-lab-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "lab-split-curves"),
             py="lab-split-curves.py", menu="Lab Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → Lab Split (Curves)\n"
                   "    图层右键 → SuperMrWang → Shortcut → Lab Split (Curves)",
             desc="Lab Split (Curves)：在 CIE Lab 空间里调曲线。GIMP 没有 a/b 分量"
                  "混合模式，插件用 lb:lab-dual / lb:lab-compose 把 a 与 b 合进一张"
                  "数据图（红=a、绿=b）联合还原，L* 交给 LCh 明度模式（两者同一个"
                  "量，逐位精确）。恒等曲线时精确还原，调哪条就只动哪个 Lab 分量。",
             pdb="lb-plugin-lab-split-curves(image, drawable, group)"),
        dict(key="hsi",
             name="gegl-color-ops-plugin-hsi-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "hsi-split-curves"),
             py="hsi-split-curves.py", menu="HSI Split (Curves)",
             menus="    颜色 → SuperMrWang → Shortcut → HSI Split (Curves)\n"
                   "    图层右键 → SuperMrWang → Shortcut → HSI Split (Curves)",
             desc="HSI Split (Curves)：在 HSI 空间里调曲线。HSI 的 I 是 (R+G+B)/3，"
                  "GIMP 的六条分量模式一条也对不上；插件用 lb:hsi-dual / "
                  "lb:hsi-compose 把 S、I、色相挤进一张数据图（红=S、绿=I、蓝=H/360），"
                  "三条曲线各管一个分量。恒等曲线时精确还原。",
             pdb="lb-plugin-hsi-split-curves(image, drawable, group)"),
        dict(key="frequency",
             name="gegl-color-ops-plugin-frequency-separation.zip",
             src_dir=os.path.join(ROOT, "plugin", "frequency-separation"),
             py="frequency-separation.py", menu="高低频磨皮 (Frequency Separation)",
             menus="    颜色 → SuperMrWang → Shortcut → 高低频磨皮\n"
                   "    图层右键 → SuperMrWang → Shortcut → 高低频磨皮",
             desc="高低频磨皮：一次生成低频（高斯模糊，管影调与颜色）与高频"
                  "（颗粒合并 + 高通，管细节与质感）两层，恒等时合成就是原图。"
                  "在低频层抹平色块、在高频层修细节，互不干扰。",
             pdb="lb-plugin-frequency-separation(image, drawable, radius, group)"),
        dict(key="dodge",
             name="gegl-color-ops-plugin-dodge-burn.zip",
             src_dir=os.path.join(ROOT, "plugin", "dodge-burn"),
             py="dodge-burn.py", menu="双曲线磨皮 (Dodge & Burn)",
             menus="    颜色 → SuperMrWang → Shortcut → 双曲线磨皮\n"
                   "    图层右键 → SuperMrWang → Shortcut → 双曲线磨皮",
             desc="双曲线磨皮：生成提亮、压暗两条曲线层，蒙版全黑。用白色柔边"
                  "画笔在蒙版上涂抹，涂到哪里就提亮/压暗到哪里，没涂的地方与"
                  "原图逐像素相同。",
             pdb="lb-plugin-dodge-burn(image, drawable, amount, group)"),
        dict(key="grey",
             name="gegl-color-ops-plugin-neutral-grey.zip",
             src_dir=os.path.join(ROOT, "plugin", "neutral-grey"),
             py="neutral-grey.py", menu="中性灰磨皮 (Neutral Grey)",
             menus="    颜色 → SuperMrWang → Shortcut → 中性灰磨皮\n"
                   "    图层右键 → SuperMrWang → Shortcut → 中性灰磨皮",
             desc="中性灰磨皮：加一张 50% 灰的柔光层，恒等时与原图逐像素相同。"
                  "白色画笔提亮、黑色画笔压暗，反复涂抹把皮肤推平。",
             pdb="lb-plugin-neutral-grey(image, drawable, group)"),
    ]
    zips = {}
    for sp in specs:
        readme = """gegl-color-ops · {py}（GIMP 3 Python 插件）
=====================================================

{desc}

安装：把这个 .py 放进 GIMP 的用户插件目录（目录不存在就新建）：
    Windows:  %APPDATA%\\GIMP\\3.x\\plug-ins\\
    Linux:    ~/.config/GIMP/3.x/plug-ins/
    macOS:    ~/Library/Application Support/GIMP/3.x/plug-ins/

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
            _zip_add_text(z, "安装说明.txt", readme)
        zips[sp["key"]] = {"name": sp["name"], "sha": _sha256_file(path),
                           "kb": round(os.path.getsize(path) / 1024, 1)}
    return zips


def build_plugins(version, stats=None):
    # 与首页同一套框：facts 条、卡片、dl 盒、note 提示框、step-list、参数表、按钮。
    z = stats.get("plugin_zips", {}) if stats else {}

    def dl_box(key, title, blurb):
        d = z.get(key)
        if not d:
            return ""
        return """
    <div class="dl primary-dl">
      <div class="dl-head"><h3>{title}</h3><span class="pill">.py · 免编译</span></div>
      <p>{blurb}</p>
      <a class="btn primary" href="download/{name}">下载 {name}</a>
      <p class="muted small">{kb} KB · 校验：<code>SHA256 {sha}</code></p>
    </div>""".format(title=title, blurb=blurb, name=d["name"], kb=d["kb"],
                    sha=d["sha"][:32] + "…")

    cards = """
<div class="cards cards-10">
  <a class="card" href="#layer-to-selection">
    <div class="card-top"><span class="tag t-mask">选区</span><code>layer-to-selection</code></div>
    <h3>Layer to Selection</h3>
    <p>右键点哪个图层，就把哪个图层转成当前选区——Gray / R / G / B / Alpha、
       四种组合方式、可反相。</p>
    <span class="more">看细节与下载 →</span>
  </a>
  <a class="card" href="#layer-to-channel">
    <div class="card-top"><span class="tag t-mask">通道</span><code>layer-to-channel</code></div>
    <h3>Layer to Channel</h3>
    <p>右键点哪个图层，就把哪个图层变成一条新的 Alpha 通道——恒为灰度，
       黑 = 不选中、白 = 完全选中。</p>
    <span class="more">看细节与下载 →</span>
  </a>
  <a class="card" href="#hsv-split">
    <div class="card-top"><span class="tag t-color">曲线</span><code>hsv-split-curves</code></div>
    <h3>HSV Split (Curves)</h3>
    <p>拆成 H / S / V 三张分量层，每层一条原生曲线，用 HSV 三条分量模式叠回去。
       恒等曲线逐位还原——等于在 HSV 里调曲线。</p>
    <span class="more">看细节与下载 →</span>
  </a>
  <a class="card" href="#lch-split">
    <div class="card-top"><span class="tag t-color">曲线</span><code>lch-split-curves</code></div>
    <h3>LCh Split (Curves)</h3>
    <p>同上，但换成 CIE LCh 三个分量（明度 / 彩度 / 色相）——感知均匀，
       做亮度与彩度分级比 HSV 稳。</p>
    <span class="more">看细节与下载 →</span>
  </a>
  <a class="card" href="#hsl-split">
    <div class="card-top"><span class="tag t-color">曲线</span><code>hsl-split-curves</code></div>
    <h3>HSL Split (Curves)</h3>
    <p>GIMP 没有 HSL 分量模式，这个插件把 HSL 精确接到 HSV 上：
       S 与 L 合一层、色相一层，调哪条只动哪个分量。</p>
    <span class="more">看细节与下载 →</span>
  </a>
  <a class="card" href="#lab-split">
    <div class="card-top"><span class="tag t-blend">曲线</span><code>lab-split-curves</code></div>
    <h3>Lab Split (Curves)</h3>
    <p>a 与 b 合进一张数据图（红=a、绿=b），L* 用 LCh 明度模式——同一个量，
       逐位精确。调 a 只动 a，调 b 只动 b。</p>
    <span class="more">看细节与下载 →</span>
  </a>
  <a class="card" href="#hsi-split">
    <div class="card-top"><span class="tag t-color">曲线</span><code>hsi-split-curves</code></div>
    <h3>HSI Split (Curves)</h3>
    <p>I 是 (R+G+B)/3，没有分量模式可借，三个分量合进一层：红=S、绿=I、蓝=色相。
       一层三条曲线，互不串门。</p>
    <span class="more">看细节与下载 →</span>
  </a>
  <a class="card" href="#retouch">
    <div class="card-top"><span class="tag t-tone">磨皮</span><code>frequency-separation</code></div>
    <h3>高低频磨皮</h3>
    <p>一次建好低频（模糊，管影调）与高频（颗粒合并，管细节）两层，
       叠起来就是原图。半径决定分界。</p>
    <span class="more">看细节与下载 →</span>
  </a>
  <a class="card" href="#retouch">
    <div class="card-top"><span class="tag t-tone">磨皮</span><code>dodge-burn</code></div>
    <h3>双曲线磨皮</h3>
    <p>提亮 / 压暗两条曲线层，蒙版全黑。白色画笔涂哪儿，哪儿就亮或暗，
       没涂的地方一码不动。</p>
    <span class="more">看细节与下载 →</span>
  </a>
  <a class="card" href="#retouch">
    <div class="card-top"><span class="tag t-tone">磨皮</span><code>neutral-grey</code></div>
    <h3>中性灰磨皮</h3>
    <p>一张 50% 灰的柔光层，柔光在 0.5 处是恒等映射：白笔提亮、黑笔压暗，
       原图像素一个没动。</p>
    <span class="more">看细节与下载 →</span>
  </a>
</div>"""

    sel_boxes = """
  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>通道</h3></div>
      <p>可选 <b>Gray（亮度）/ R / G / B / Alpha</b>——彩色图层选 Gray 时按亮度算，
         不是 HSL 明度（纯红 ≈ 54/255，而不是 130）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>组合方式</h3></div>
      <p><b>替换 / 加 / 减 / 交</b>，与 GIMP 选区菜单一致；可反相
         （选暗部而不是亮部）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>偏移图层</h3></div>
      <p>图层比画布小、带偏移也没问题：只在自己位置生效，界外不选中。</p>
    </div>
  </div>"""

    chn_boxes = """
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>恒为灰度</h3><span class="pill">语义明确</span></div>
      <p>彩色图层先按亮度转成灰度，黑白图层原样——然后把这些<b>灰度值写进通道</b>
         （黑 = 不选中、白 = 完全选中、中间灰 = 部分选中）。没有「取 R 通道」
         这类选项——要的就是明暗，不给单色通道捣乱的机会。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>通道名与反相</h3></div>
      <p>可反相、可自定义通道名（默认沿用图层名），建好后状态栏会提示通道名。
         想把它变回选区：在「通道」面板右键该通道 → <b>通道到选区</b>
         （GIMP 原生）。</p>
    </div>
  </div>
  <p class="note"><b>彩色图层的 Gray 是亮度，不是 HSL 明度</b>：纯红 ≈ 54/255，
     而不是 HSL 明度的 130——和你在 PS 里按亮度去色的结果一致。
     实现上走临时副本去色（GIMP 3.2 的 LUMA 模式），用完即删，活动图层还原。</p>"""

    split_boxes = """
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">穿透组</span></div>
      <pre><code>HSV split        组 · 穿透（带 alpha 时组上还有蒙版）
  ├─ 3 · Value      模式 HSV 明度
  ├─ 2 · Saturation 模式 HSV 饱和度
  ├─ 1 · Hue        模式 HSV 色相   ← 垫底
  └─ 原图层（不动，可以隐藏）</code></pre>
      <p>每层三条滤镜：<code>extract</code>（抽分量）→ <code>curve</code>
         （<b>你调的那条</b>）→ <code>encode</code>（一个 <code>lb:gray-to-component</code>
         滤镜，把灰度编码成携带该分量的彩色）。</p>
      <p><b>层序不能反：</b>分量混合模式只替换一个分量，另外两个从下行读。最底层
         必须自带真实色相（全饱和色环），所以 Hue 垫底、Value 在顶。反过来的话
         最底是灰，上面两层读到 S=0，怎么换都是灰——<b>把原图层一隐藏就整幅崩掉</b>。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么是在做曲线</h3></div>
      <p>恒等曲线时三层合成回来<b>逐位还原</b>原图，所以改一条曲线就等于
         「在 HSV 空间里曲那一个分量」。GIMP 内置曲线只能选
         R/G/B/Alpha——H、S、LCh 这些分量它读不到，这正是缺口。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测精度</h3></div>
      <p>32 位浮点与 8 位图的恒等往返都是 <b>0.5 码</b>；真实 512×512 图逐像素
         比对最大 <b>1 码</b>，仅 0.335% 的通道值有差异。剩下的误差是 8 位量化，
         编码本身没有查表误差——旧版三条曲线才有 256 点 LUT。</p>
      <p>把<b>原图层隐藏掉</b>，三层自己叠出来还是 <b>0.5 码</b>；半透明区域的
         透明度由组蒙版保住（三层必须不透明，否则混合模式会按 alpha 做 lerp）。</p>
    </div>
  </div>"""

    lch_boxes = """
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>量程是标定出来的</h3><span class="pill">D50</span></div>
      <p><code>component-extract</code> 报的不是原始单位：<code>lab-l</code> = L/100、
         <code>lch-h</code> = h/360，而 <code>lch-c</code> = <b>C/200</b>（sRGB 内只到
         0.656）。编码时算子按 <code>chroma-scale = 200</code> 把灰度乘回真实 C*，
         所以彩度层不用再插一条 scale 曲线——曲线的 0.656 处就是 sRGB 最大彩度
         （纯蓝 131.21）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>编码路径的坑</h3></div>
      <p>色相模式对色相误差极其敏感：ΔH=0.5° 在 C*=90 时就是 9.6 个码值。
         所以色相编码不用全饱和色轮，而用<b>等 L 等 C 的色相圆</b>
         （L*=70、C*=39.8）——角度严格线性，插值误差从 0.22° 降到 0.002°。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测精度</h3></div>
      <p>浮点恒等往返 ≤ <b>0.02 码</b>，8 位 ≤ <b>0.5 码</b>，真实照片 512×512
         最大 <b>0.03 码</b>（超过 1.5 码的像素 <b>0 个</b>）。8 位图会被自动收进组里：
         不分组时逐层量化会让色相偏到 11 码级。</p>
    </div>
  </div>
  <p class="note"><b>选 LCh 还是 HSV</b>：HSV 的 V/S 是相对量，调 S 会随 V 变；
     LCh 的 L/C 是感知均匀的绝对量，做亮度、彩度分级更稳。论完整度也是 LCh 更高
     ——GIMP 的 HSV 组里那个「HSL 颜色」其实混了模型，而 LCh 组 H/C/L/Color 四项
     齐全，另有一个 Luminance。</p>"""

    hsl_boxes = """
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">两层</span></div>
      <pre><code>HSL split        组 · 穿透（带 alpha 时组上还有蒙版）
  ├─ 2 · Hue        模式 HSV 色相   ← 只替换色相
  ├─ 1 · S / L      模式 正常       ← 一条算子链算完整 HSL 色
  └─ 原图层（不动，可以隐藏）</code></pre>
      <p><b>S 曲线挂红通道、L 曲线挂绿通道</b>，色相曲线在 Hue 层。把 Hue 层关掉、
         只留 S/L 层，看到的就是「原色相 + 调过的 S/L」——很好用的中间状态。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么只有两层</h3></div>
      <p>HSL 的 S 与 L 是<b>耦合</b>的：<code>C = (1−|2L−1|)·S</code>、
         <code>V = L + C/2</code>、<code>S_hsv = C/V</code>。要精确换回 HSV 的
         S/V，编码器必须同时读到两者，而每层的曲线只看得到自己那一个分量——
         两个独立的 1D 曲线表达不了二元映射。所以 S 与 L 合进一张数据图
         （R=S、G=L），由 <code>lb:hsl-compose</code> 联合还原；算出来的已经是
         完整颜色，第三层就多余了。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>硬凑三层的代价</h3></div>
      <p>把 HSL 的 L 直接当 V 用：S=0.25 偏 <b>25 码</b>、S=1 偏 <b>64 码</b>
         （差的正好是 C/2）；再加一条按「典型 S」校准的曲线，实际 S 一变就偏到
         <b>77 码</b>；S、L 一起调最坏 <b>102 码</b>。</p>
    </div>
  </div>
  <p class="note">适配算子内部用 babl 的 <code>HSLA float</code> 做转换，与 GIMP
     自己的 HSL（<code>component-extract</code> 的 <code>hsl-s</code> /
     <code>hsl-l</code>）同一口径，所以往返没有查表误差：浮点 <b>0.00001 码</b>、
     8 位 <b>0.002 码</b>。改 S 曲线后结果的 HSL 饱和度 = f(原 S)，明度与色相
     误差 <b>0.0001 码</b>。依赖 <code>lb:hsl-dual</code> /
     <code>lb:hsl-compose</code> 两个算子，缺了没有一维回退，插件会直接报错。</p>"""

    lab_boxes = """
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">两层</span></div>
      <pre><code>Lab split        组 · 穿透（带 alpha 时组上还有蒙版）
  ├─ 2 · L          模式 LCh 明度   ← 只替换 L*
  ├─ 1 · a / b      模式 正常       ← 一条算子链算完整 Lab 色
  └─ 原图层（不动，可以隐藏）</code></pre>
      <p><b>a 曲线挂红通道、b 曲线挂绿通道</b>，L 曲线在 L 层（值通道）。数据图里
         中性灰落在 0.502，所以 a 曲线在 0.5 附近往上抬就是往洋红推、往下压是往
         绿推；b 曲线同理（上=黄、下=蓝）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么 a/b 必须合一层</h3></div>
      <p>a、b 是<b>直角坐标</b>，GIMP 没有「a」「b」分量模式。LCh 的 C/h 是它们的
         极坐标形式，但每层的曲线只看得到自己那一个标量：<code>C</code> 那一层
         不知道 b 变成了多少，所以两条独立的一维曲线拼不出 (a,b) 的二元映射。
         合进一张数据图后由 <code>lb:lab-compose</code> 一起读，就精确了。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>L* 为什么可以借 LCh 明度</h3></div>
      <p>Lab 的 L* 与 LCh 的 L* <b>是同一个量</b>（babl 里就是同一个通道），所以
         「LCh 明度」模式换 L* 是逐位精确的，不是近似。整条链的误差只剩浮点
         舍入：<b>0.010 码</b>（8 位 <b>0.499 码</b>）。</p>
    </div>
  </div>
  <p class="note">量程按 babl 的 <code>CIE Lab float</code>（D50 白点，与 GIMP 的 Lab
     空间同口径）：<code>a' = (a*+128)/255</code>、<code>L' = L*/100</code>。
     改 a 曲线后结果落在「a* 换了、b* 与 L* 都没动」的 Lab 点上，误差
     <b>0.0026 码</b>。超 sRGB 色域的 Lab 点会被裁——那是色域的事实。
     依赖 <code>lb:lab-dual</code> / <code>lb:lab-compose</code> 两个算子，
     缺了没有一维回退，插件会直接报错。</p>"""

    hsi_boxes = """
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">一层</span></div>
      <pre><code>HSI split          组 · 穿透（带 alpha 时组上还有蒙版）
  └─ 1 · HSI S/I/H   模式 正常   ← 一条算子链算完整 HSI 色
  └─ 原图层（不动，可以隐藏）</code></pre>
      <p>滤镜栈：<code>decompose</code>（lb:hsi-dual）→ <b>S 曲线（红）</b> →
         <b>I 曲线（绿）</b> → <b>H 曲线（蓝）</b> → <code>compose</code>
         （lb:hsi-compose）。三层分量各占一个通道，互不串门。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么只有一层</h3></div>
      <p>HSL 能拆两层、Lab 能拆两层，是因为各有一个分量借得到现成模式
         （HSL 色相 ≡ HSV 色相；Lab 的 L* ≡ LCh 的 L*）。HSI 一个都没有：
         <code>I=(R+G+B)/3</code> 不是 V 也不是 L。更麻烦的是色相——就算接到
         「HSV 色相」模式，那一步保留的是 HSV 的 S/V，<b>HSI 的 I 会被带走
         0.085（约 22 码）</b>。所以三个分量只能一起算。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>两种色相角不是一回事</h3></div>
      <p>HSI 的色相是余弦定义（等亮度平面里的真实夹角），HSV 的是六边形投影上的
         参数角；两者只在 0°/30°/60° 重合，中间最多差 <b>1.117°</b>。数据图里存
         的是 HSI 的角度，<code>lb:hsi-compose</code> 也按 HSI 的余弦式逆变换，
         所以全程不需要换算，往返 <b>0.0001 码</b>。</p>
    </div>
  </div>
  <p class="note">平均强度 I 比 HSV 的 max 更接近感知亮度，这也是 HSI 常见于图像
     分析与曝光校正的原因。S、I 推到极端时逆变换会出 sRGB 色域（HSI 的色域是
     六边形棱锥，不是立方体），出界部分按 0/1 裁掉。依赖 <code>lb:hsi-dual</code> /
     <code>lb:hsi-compose</code> 两个算子，缺了没有回退，插件会直接报错。</p>"""

    retouch_boxes = """
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>三个磨皮各自建什么</h3><span class="pill">一键</span></div>
      <pre><code>高低频磨皮               组 · 穿透
  ├─ 2 · 高频（细节）     颗粒合并 + 高通
  ├─ 1 · 低频（影调）     正常 + 高斯模糊
  └─ 原图层

双曲线磨皮
  ├─ 2 · 压暗（黑蒙版）   曲线下压
  ├─ 1 · 提亮（黑蒙版）   曲线上提
  └─ 原图层

中性灰磨皮
  └─ 1 · 中性灰           柔光 · 整层 128 灰</code></pre>
      <p>三个都是「先摆好、再涂」：刚建出来时结果与原图一致，之后靠改模糊半径、
         涂蒙版、涂灰层来修，原图层一直不动。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>恒等是怎么保证的</h3></div>
      <p>高低频：高频层是 <code>H = 0.5 + (原图 − 低频)</code>，颗粒合并算的是
         <code>H + L − 0.5</code>，偏移正好抵消。双曲线：两张蒙版全黑，两层
         在合成里根本不参与，误差 0。中性灰：柔光在 0.5 处是恒等映射，实测
         8 位图也是 0 码。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>怎么用</h3></div>
      <p><b>高低频</b>：低频层抹平色块、高频层修毛孔与痘印，半径决定分界。
         <b>双曲线</b>：点中蒙版，白色柔边画笔 10–20%，涂提亮层变亮、涂压暗层
         变暗。<b>中性灰</b>：直接在这层上涂，白色提亮、黑色压暗，涂过头用
         <code>#808080</code> 盖回去。</p>
    </div>
  </div>
  <p class="note">实测（GIMP 3.2.8，<code>tools/check_retouch.py</code>，52 项）：
     高低频合成与原图差 ≤1.5 码——<code>gegl:high-pass</code> 内部有约 1 码的
     定点偏移，与半径无关；双曲线与中性灰都是 0 码。带 alpha 的图自动分组，
     透明度交给组蒙版，隐藏原图层后 alpha 零误差。</p>"""

    download = """<section class="download" id="download">
  <h2>下载</h2>
  <div class="dl-grid">
{sel_box}
{chn_box}
{hsv_box}
{lch_box}
{hsl_box}
{lab_box}
{hsi_box}
{freq_box}
{dodge_box}
{grey_box}
  </div>
  <p class="note">和 <code>.dll</code> / <code>.so</code> 一个思路：免编译、解压即用。
     区别只是 Python 插件放进 <b>GIMP</b> 的用户插件目录
     （<code>%APPDATA%\\GIMP\\3.x\\plug-ins</code> 或
     <code>~/.config/GIMP/3.x/plug-ins</code>），不是 GEGL 的；
     包里的「安装说明.txt」写得很全。十个都装也行，分量曲线与磨皮都在同一个
     <b>Shortcut</b> 子菜单里。</p>
</section>""".format(sel_box=dl_box("selection", "Layer to Selection",
                                    "右键任意图层，把它转成当前选区"
                                    "（Gray/R/G/B/Alpha、四种组合方式、可反相）。"),
                     chn_box=dl_box("channel", "Layer to Channel",
                                    "右键任意图层，把它变成一条新的 Alpha 通道"
                                    "（恒为灰度，可反相、可自定义通道名）。"),
                     hsv_box=dl_box("hsv", "HSV Split (Curves)",
                                    "拆成 H / S / V 三张分量层，每层一条原生曲线，"
                                    "用 HSV 三条分量模式叠回去；恒等曲线逐位还原。"),
                     lch_box=dl_box("lch", "LCh Split (Curves)",
                                    "拆成 L / C / h 三张分量层，每层一条原生曲线，"
                                    "用 LCh 三条分量模式叠回去；恒等曲线还原原图。"),
                     hsl_box=dl_box("hsl", "HSL Split (Curves)",
                                    "在 HSL 空间里调曲线：S 与 L 合一层（红=饱和度、"
                                    "绿=明度）、色相一层；恒等曲线精确还原。"),
                     lab_box=dl_box("lab", "Lab Split (Curves)",
                                    "在 CIE Lab 空间里调曲线：a 与 b 合一层（红=a、"
                                    "绿=b）、L* 一层走 LCh 明度；恒等曲线精确还原。"),
                     hsi_box=dl_box("hsi", "HSI Split (Curves)",
                                    "在 HSI 空间里调曲线：红=饱和度、绿=强度、"
                                    "蓝=色相，三条曲线各管一个分量；恒等曲线精确还原。"),
                     freq_box=dl_box("frequency", "高低频磨皮",
                                     "一次建好低频（模糊）与高频（颗粒合并）两层，"
                                     "叠起来就是原图；半径决定频率分界。"),
                     dodge_box=dl_box("dodge", "双曲线磨皮",
                                      "提亮 / 压暗两条曲线层，蒙版全黑；白色画笔"
                                      "涂到哪里就亮/暗到哪里，没涂的地方不动。"),
                     grey_box=dl_box("grey", "中性灰磨皮",
                                     "一张 50% 灰的柔光层，恒等时与原图逐像素相同；"
                                     "白笔提亮、黑笔压暗。"))

    install = """<section class="steps" id="install">
  <h2>三步装上</h2>
  <ol class="step-list">
    <li>
      <h3>拿代码</h3>
      <pre><code>git clone {repo}.git
cd gegl-color-ops</code></pre>
    </li>
    <li>
      <h3>拷进 GIMP 插件目录</h3>
      <p>一条脚本把 <code>plugin/</code> 下的 <code>.py</code> 全部拷进 GIMP 的
         plug-ins 目录（Windows / Linux 通用；带 <code>.disabled</code> 标记的
         插件会跳过）：</p>
      <pre><code>bash install-plugin.sh</code></pre>
      <p>或者直接用上面下载区的十个 <code>.zip</code>，把 <code>.py</code>
         解进同一个目录（每个插件一个子目录也行，GIMP 会扫描下去）。</p>
    </li>
    <li>
      <h3>重启 GIMP，找菜单</h3>
      <p><b>颜色 → SuperMrWang</b> 下是 Apply Image / Calculations，分量曲线
         收在 <b>Shortcut</b> 子菜单里（HSV / LCh / HSL / Lab / HSI Split
         (Curves)）与三个磨皮；<b>图层右键 → SuperMrWang</b> 下十个都在，分量曲线
         与磨皮同样在 <b>Shortcut</b> 里；<b>选择 → SuperMrWang</b> 下是 Layer to Selection /
         Channel（不依赖右键、方便写脚本）。</p>
    </li>
  </ol>
</section>""".format(repo=REPO)

    pdb_table = """<div class="table-wrap"><table>
  <thead><tr><th>PDB 过程</th><th>参数</th><th>用途</th></tr></thead>
  <tbody>
    <tr><td><code>lb-plugin-layer-to-selection</code></td>
        <td><code>channel</code> / <code>invert</code> / <code>operation</code></td>
        <td>图层 → 选区</td></tr>
    <tr><td><code>lb-plugin-layer-to-channel</code></td>
        <td><code>invert</code> / <code>name</code></td>
        <td>图层 → 灰度 Alpha 通道</td></tr>
    <tr><td><code>lb-plugin-hsv-split-curves</code></td>
        <td><code>group</code></td>
        <td>图层 → H/S/V 三层分量曲线</td></tr>
    <tr><td><code>lb-plugin-lch-split-curves</code></td>
        <td><code>group</code></td>
        <td>图层 → L/C/h 三层分量曲线</td></tr>
    <tr><td><code>lb-plugin-hsl-split-curves</code></td>
        <td><code>group</code></td>
        <td>图层 → S/L 层 + Hue 层（HSL 精确适配）</td></tr>
    <tr><td><code>lb-plugin-lab-split-curves</code></td>
        <td><code>group</code></td>
        <td>图层 → a/b 层 + L* 层（Lab 精确适配）</td></tr>
    <tr><td><code>lb-plugin-hsi-split-curves</code></td>
        <td><code>group</code></td>
        <td>图层 → 一层三联曲线（S / I / H）</td></tr>
    <tr><td><code>lb-plugin-frequency-separation</code></td>
        <td><code>radius</code> / <code>group</code></td>
        <td>图层 → 低频 + 高频两层（磨皮）</td></tr>
    <tr><td><code>lb-plugin-dodge-burn</code></td>
        <td><code>amount</code> / <code>group</code></td>
        <td>图层 → 提亮 / 压暗两层（黑蒙版）</td></tr>
    <tr><td><code>lb-plugin-neutral-grey</code></td>
        <td><code>group</code></td>
        <td>图层 → 50% 灰柔光层（磨皮）</td></tr>
  </tbody>
</table></div>"""

    body = """<section class="page-head">
  <p class="eyebrow"><a href="index.html">首页</a> / Python 插件</p>
  <h1>十个 Python 插件</h1>
  <p class="lede">两件事原生 GIMP 做不顺：<b>灰度图变不成能用的东西</b>（复制图层 →
     新建通道 → 粘贴 → 蒙版转选区，四步），以及<b>曲线选不到分量</b>（只有
     R/G/B/Alpha，没有 H、S、LCh）。前两个插件把转换压成一次右键；其余五个把图层
     拆成分量层各挂一条原生曲线，恒等时精确还原——所以调曲线就等于在那个色彩空间
     里调那一维。HSV 与 LCh 各拆三层，HSL 与 Lab 因为有一对分量耦合、拆成两层，
     HSI 三个分量都借不到模式、干脆合成一层（见下文）。另外三个把磨皮要手动摆的
     那一整套图层结构（低频/高频、提亮/压暗、中性灰）一次建好。</p>
  <p class="lede">分量曲线五个和磨皮三个都收在菜单的 <b>Shortcut</b> 子菜单里
     （<code>颜色 → SuperMrWang → Shortcut</code>，图层右键同理）：它们本来就是
     「一次点击替代一串手工步骤」的东西，以后这类一键操作也往这个子菜单里放。</p>
  <div class="cta">
    <a class="btn primary" href="#download">下载插件包</a>
    <a class="btn" href="#install">三步装上</a>
    <a class="btn ghost" href="https://github.com/SuperMrWang-DEV/gegl-color-ops/tree/main/plugin">看插件源码</a>
  </div>
  <ul class="facts">
    <li><b>10</b> 个插件</li>
    <li><b>10</b> 个 PDB 过程</li>
    <li><b>253</b> 条回归断言</li>
    <li><b>0</b> 编译 · 纯 Python</li>
  </ul>
</section>
<section class="prose wide">
{cards}

  <section class="group" id="layer-to-selection">
    <h3 class="group-title"><span class="tag t-mask">选区</span>
      <span class="group-en">Layer to Selection</span><span class="count">一键转选区</span></h3>
    <p class="group-desc">把点击的图层变成当前选区。GEGL 算子跑完留下的灰度图，
       一步就能接着用——当蒙版用（选区）的场合就归它。</p>
{sel_boxes}
  </section>

  <section class="group" id="layer-to-channel">
    <h3 class="group-title"><span class="tag t-mask">通道</span>
      <span class="group-en">Layer to Channel</span><span class="count">一键转通道</span></h3>
    <p class="group-desc">把点击的图层变成一条新的 Alpha 通道，留档复用——
       后续用通道到选区、或拿通道当图层蒙版都行。</p>
{chn_boxes}
  </section>

  <section class="group" id="hsv-split">
    <h3 class="group-title"><span class="tag t-color">曲线</span>
      <span class="group-en">HSV Split</span><span class="count">H / S / V</span></h3>
    <p class="group-desc">GIMP 的曲线只能选 R / G / B / Alpha——想单独曲「色相」或
       「饱和度」没有入口。这个插件把图层拆成三张分量层、每层给一条曲线，
       再按 HSV 分量模式叠回去：恒等时逐位还原，所以改曲线就等于曲那个分量。</p>
{split_boxes}
  </section>

  <section class="group" id="lch-split">
    <h3 class="group-title"><span class="tag t-blend">曲线</span>
      <span class="group-en">LCh Split</span><span class="count">L / C / h</span></h3>
    <p class="group-desc">同样的思路换到 CIE LCh：明度、彩度、色相三条曲线。
       LCh 是「颜色」组里唯一完整、且没有 legacy 包袱的一组分量模式，
       感知均匀，做明暗与彩度分级比 HSV 稳。</p>
{lch_boxes}
  </section>

  <section class="group" id="hsl-split">
    <h3 class="group-title"><span class="tag t-color">曲线</span>
      <span class="group-en">HSL Split</span><span class="count">H / S / L</span></h3>
    <p class="group-desc">GIMP 给 HSV 和 LCh 都配了分量混合模式，唯独 HSL 没有。
       这个插件不是拿 HSV 去近似 HSL，而是把两者<b>精确</b>换算：色相本来就是
       同一个函数，S 与 L 则合进一张数据图，由算子联合还原。恒等时精确还原原图，
       调哪条曲线就只动那个 HSL 分量。</p>
{hsl_boxes}
  </section>

  <section class="group" id="lab-split">
    <h3 class="group-title"><span class="tag t-blend">曲线</span>
      <span class="group-en">Lab Split</span><span class="count">L / a / b</span></h3>
    <p class="group-desc">Lab 的 <code>a</code>、<code>b</code> 是直角坐标，GIMP 一条
       分量模式也对不上；<code>L*</code> 倒是能借 LCh 明度（同一个量）。所以这个
       插件把 a 与 b 合进一张数据图联合还原，L* 单独一层——恒等时精确还原原图，
       调 a 只动 a、调 b 只动 b。</p>
{lab_boxes}
  </section>

  <section class="group" id="hsi-split">
    <h3 class="group-title"><span class="tag t-color">曲线</span>
      <span class="group-en">HSI Split</span><span class="count">H / S / I</span></h3>
    <p class="group-desc">HSI 的 I 是 (R+G+B)/3，色相又用余弦定义——GIMP 的六条分量
       模式一条也对不上，连「借 HSV 色相换角」都会把 I 带走 22 码。于是三个分量
       合进同一层：红=S、绿=I、蓝=色相，三条曲线各管一个分量。</p>
{hsi_boxes}
  </section>

  <section class="group" id="retouch">
    <h3 class="group-title"><span class="tag t-tone">磨皮</span>
      <span class="group-en">Retouch Shortcuts</span><span class="count">3 个</span></h3>
    <p class="group-desc">磨皮本来要手动建层、挂滤镜、加蒙版、填灰，一套下来七八步。
       这三个把整套结构一次摆好，且摆好那一刻结果与原图完全一致——修不修、修多少
       都由你后面的笔画决定，原图层始终不动。</p>
{retouch_boxes}
  </section>

{download}

{install}

  <h2 id="script">脚本调用</h2>
  <p>十个动作都是标准 PDB 过程，脚本里直接调（参数留空走默认值）：</p>
{pdb_table}
  <p class="note">实现：转换类直接读图层像素（array 的 C 级切片，100 万像素约 4 毫秒），
     不走复制粘贴；灰度内容走零拷贝快路径，彩色图层才临时复制一份做去色。
     有活动选区时写通道会先把选区挂起再恢复——GIMP 的 shadow 合并遵守选区，
     不挂起的话通道会被截成选区那一块。图层组没有自己的像素，会明确报错提示
     先合并组。与 <code>plugin/gray-mask</code> 的分工：gray-mask 走复制/粘贴，
     会带上图层蒙版等<b>显示效果</b>；这两个插件读<b>原始像素</b>、更快。
     分量曲线类用 <code>gegl:component-extract</code> 抽分量、
     <code>gimp:curves</code> 当可调曲线，编码交给本仓库的
     <code>lb:gray-to-component</code>——没装这个算子时自动退回三条曲线，
     所以只装 Python 插件也能跑。HSL 版例外：它靠 <code>lb:hsl-dual</code> +
     <code>lb:hsl-compose</code> 把 S/L 联合还原（二维映射没有一维替代），
     缺这两个算子会直接报错，而不是给一个偏几十码的近似。Lab 版与 HSI 版同理：
     前者靠 <code>lb:lab-dual</code> + <code>lb:lab-compose</code>，后者靠
     <code>lb:hsi-dual</code> + <code>lb:hsi-compose</code>。</p>
  <h2 id="tests">回归</h2>
  <p><code>tools/check_layer_to_mask.py</code>，23 条断言跑在 gimp-console 的
     python-fu-eval 里：灰度值、反相、偏移图层、彩色亮度、四个单通道、
     通道值/名字/反相、彩色转通道=亮度、选区不被截断、四种组合方式。</p>
  <p>分量曲线另有五个脚本：<code>check_hsv_split.py</code>（24 条）、
     <code>check_lch_split.py</code>（35 条）、<code>check_hsl_split.py</code>
     （28 条）、<code>check_lab_split.py</code>（38 条）与
     <code>check_hsi_split.py</code>（37 条）——结构、滤镜栈顺序、浮点与 8 位
     恒等往返、曲线与直接改分量的数学期望对照、alpha 穿透、不分组、非法输入、
     编码路径量程。全部跑在真实的 GIMP 3.2 里，不是 mock。
     编码算子自己还有 <code>check_gray_to_component.py</code>（39 条），
     九个混合模式的恒等往返全在 2 码以内。三个磨皮在
     <code>check_retouch.py</code>（52 条）里：结构、滤镜参数、浮点与 8 位恒等、
     低频真变糊、高频真在中轴、改半径仍恒等、隐藏原图层自足、半透明图的
     alpha、以及「涂白/涂黑确实生效」。</p>
</section>""".format(cards=cards, sel_boxes=sel_boxes, chn_boxes=chn_boxes,
                   split_boxes=split_boxes, lch_boxes=lch_boxes,
                   hsl_boxes=hsl_boxes, lab_boxes=lab_boxes,
                   hsi_boxes=hsi_boxes, retouch_boxes=retouch_boxes,
                   download=download, install=install, pdb_table=pdb_table)
    return page("Python 插件 · gegl-color-ops", body,
                desc="GIMP 3 Python 插件下载：图层转选区 / Alpha 通道，"
                     "HSV / LCh / HSL / Lab / HSI 分量分层 + 曲线，"
                     "高低频 / 双曲线 / 中性灰磨皮——免编译，解压即用")


def build_feed(ops, version):
    """一个极简 Atom，方便订阅「最近加了什么算子」。GitHub Pages 不需要后端。"""
    entries = []
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
  <title>gegl-color-ops · 算子</title>
  <link href="{site}"/>
  <updated>2026-11-15T00:00:00Z</updated>
  <id>tag:github.com,2026:gegl-color-ops</id>
{entries}
</feed>""".format(site=REPO, entries="\n".join(entries))


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
    return {"win_files": len(dlls), "dlls": dlls, "win_dir": win,
            "linux_files": len(sos), "sos": sos, "linux_dir": lin}


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
    for key in ("selection", "channel"):
        d = stats.get("plugin_zips", {}).get(key)
        if d:
            print("           docs/download/%s（Python 插件）" % d["name"])

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
