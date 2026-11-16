# -*- coding: utf-8 -*-
"""把 ops/ 下的算子渲染成一套静态站点，输出到 docs/（带 .disabled 的标停用/废弃）。

设计上把 docs/ 当作纯产物：每次运行整个目录重建，样式源在 tools/site/。
所以改样式改 tools/site/style.css，别直接改 docs/assets/style.css。

算子页是**中英双语**的：中文正文来自 ops/<dir>/README.md，英文正文来自
tools/site/en/<dir>.md（front matter 给 name / blurb）。两套内容同时写进同一个
HTML，靠 <html data-lang> 决定显示哪一套，页头的 中文/EN 按钮切换并记住偏好
（localStorage + ?lang=en）。首页、清单页、安装页只有中文，不显示切换按钮。

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
    "Tone":  ("Tone",  "影调与色阶"),
    "Color": ("Color", "色彩"),
    "Blend": ("Blend", "混合与通道"),
    "Mask":  ("Mask",  "蒙版"),
}

GROUP_DESC = {
    "Tone":  "先把明暗和分量拉开：色阶、曝光、对比、阴影高光。包括 HSL / HSB / LCH / CMYK / HSI 五条分量色阶。",
    "Color": "调整颜色的方向与浓度：色相饱和度、色彩平衡、白平衡、自然饱和度、可选颜色、匹配颜色。",
    "Blend": "把两层或多路通道混起来：应用图像、计算、通道混合器、XYZ 正片叠底、颜色查找、灰度转分量。",
    "Mask":  "按颜色或数值区间取蒙版：色彩范围、通道区间到 alpha。",
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
    return text if len(text) <= n else text[:n].rstrip("，。;；、 ") + "…"


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


def page(title, body, root="", desc="", titles=None):
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
{lang_head}</head>
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


def card(op):
    badge = off_badge(op) + warn_badge(op)
    return """<a class="card" href="ops/{slug}.html">
  <div class="card-top">
    <span class="tag t-{g}">{gz}</span>
    <code>{oid}</code>
    {badge}
  </div>
  <h3>{menu}</h3>
  <p>{blurb}</p>
  <span class="more">读算法说明 →</span>
</a>""".format(slug=op["dir"], g=op["group"].lower(),
               gz=GROUP_ZH[op["group"]][1], oid=html.escape(op["id"]),
               badge=badge, menu=html.escape(op["menu"]),
               blurb=inline(short(op["purpose_text"])))


def group_section(g, ops):
    members = [o for o in ops if o["group"] == g]
    if not members:
        return ""
    return """
<section class="group" id="g-{g}">
  <h3 class="group-title"><span class="tag t-{gl}">{gz}</span>
    <span class="group-en">{ge}</span><span class="count">{n} 个</span></h3>
  <p class="group-desc">{desc}</p>
  <div class="cards">
{cards}
  </div>
</section>""".format(g=g, gl=g.lower(), gz=GROUP_ZH[g][1], ge=GROUP_ZH[g][0],
                     n=len(members), desc=GROUP_DESC[g],
                     cards="\n".join("    " + card(o) for o in members))


# --------------------------------------------------------------------------
# 页面
# --------------------------------------------------------------------------

def build_index(ops, stats, version):
    n_live = sum(1 for o in ops if not o.get("deprecated"))
    n_dep = len(ops) - n_live
    dep_note = ('<span class="muted">另有 %d 个已废弃，只作存档。</span>' % n_dep) if n_dep else ""
    by_g = "\n".join(group_section(g, ops) for g in SMG.GROUPS)

    hero = """<section class="hero">
  <p class="eyebrow">GIMP 3.x · GEGL 0.4 · GPL-3.0</p>
  <h1>给 GIMP 3 的一整套<br><span class="grad">色彩算子</span></h1>
  <p class="lede">{n} 个 <code>lb:</code> 前缀的 GEGL 算子，覆盖色阶、色彩平衡、自然饱和度、
     白平衡、通道混合、蒙版生成。每个都是单文件 C，装完即用，能当非破坏滤镜挂在图层上。
     {dep}</p>
  <div class="cta">
    <a class="btn primary" href="#download">下载 Windows 包<span class="size">{size} MB</span></a>
    <a class="btn" href="#ops">浏览 {n} 个算子</a>
    <a class="btn ghost" href="guide.html">怎么装</a>
  </div>
  <ul class="facts">
    <li><b>{n}</b> 个算子</li>
    <li><b>4</b> 个分类</li>
    <li><b>0</b> 依赖 · 免编译包</li>
    <li><b>{files}</b> 个 Windows 模块已随仓库发布</li>
  </ul>
</section>""".format(n=n_live, dep=dep_note, size=stats["zip_mb"], files=stats["win_files"])

    steps = """<section class="steps" id="start">
  <h2>三分钟装上</h2>
  <ol class="step-list">
    <li>
      <h3>解开压缩包</h3>
      <p>把 {files} 个 <code>.dll</code> 放进 GEGL 的用户插件目录，目录不存在就自己建一个：</p>
      <pre><code>%LOCALAPPDATA%\\gegl-0.4\\plug-ins</code></pre>
    </li>
    <li>
      <h3>重启 GIMP</h3>
      <p>没有安装步骤，也没有注册表。GEGL 启动时扫描这个目录，GIMP 跟着加载。</p>
    </li>
    <li>
      <h3>在菜单里找</h3>
      <p>滤镜位于 <code>图像 → 颜色 → SuperMrWang</code>，按四个分类排开；
         也可以按 <code>/</code> 搜算子名直接调。</p>
    </li>
  </ol>
</section>""".format(files=stats["win_files"])

    if stats.get("zip_linux_name"):
        lin_body = """<p>{lin} 个 <code>.so</code>（{lsize} MB）。解到
         <code>~/.local/share/gegl-0.4/plug-ins</code>，重启 GIMP 即可。</p>
      <a class="btn" href="download/{lzip}">下载 gegl-color-ops-linux-x64.zip</a>
      <p class="muted small">校验：<code>SHA256 {lsha}</code></p>""".format(
            lin=stats["linux_files"], lsize=stats["zip_linux_mb"],
            lzip=stats["zip_linux_name"], lsha=stats["zip_linux_sha"][:32] + "…")
    else:
        lin_body = """<p>暂时没有预编译包，跑 <code>./build.sh</code> 自己编（需要 GEGL 开发头文件）。</p>
      <a class="btn" href="{repo}/tree/main/dist/linux-x64">看 Linux 目录</a>""".format(repo=REPO)

    download = """<section class="download" id="download">
  <h2>下载</h2>
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Windows x64</h3><span class="pill">推荐</span></div>
      <p>{n} 个 <code>.dll</code>（{size} MB）。解到
         <code>%LOCALAPPDATA%\\gegl-0.4\\plug-ins</code>，重启 GIMP 即可。</p>
      <a class="btn primary" href="download/{zip}">下载 gegl-color-ops-windows-x64.zip</a>
      <p class="muted small">校验：<code>SHA256 {sha}</code></p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Linux x86_64</h3></div>
      {lin_body}
    </div>
    <div class="dl">
      <div class="dl-head"><h3>单个算子</h3></div>
      <p>只想试一个？每个算子的文章页底部有它自己的模块直链，
         或者从仓库里挑：<code>dist/windows-x64/&lt;名字&gt;.dll</code>、
         <code>dist/linux-x64/&lt;名字&gt;.so</code>。</p>
      <a class="btn ghost" href="{repo}/tree/main/dist/windows-x64">浏览模块列表</a>
    </div>
  </div>
  <p class="note">装不上、菜单里看不到、和 GIMP 自带算子重名——都写在
     <a href="guide.html">安装指南</a> 的排错一节。源码编译走 <code>./build.sh</code> 或 meson，同样在那一页。</p>
</section>""".format(n=stats["win_files"], size=stats["zip_mb"], zip=stats["zip_name"],
                   sha=stats["zip_sha"][:32] + "…", lin_body=lin_body,
                   repo=REPO)

    about = """<section class="about">
  <h2>这些算子是怎么来的</h2>
  <p>多数是按黑盒标定做的：拿目标实现（多为常见修图软件的调整图层）做对照，逐档采样、
     拟合公式，再在 16 位精度上把残差压到几码以内——只看输入输出，不读对方的代码。
     少数是直接实现公开的数学定义（Lab / LCh / HSL 色阶就是换了个色彩空间做同一件事）。</p>
  <p>所以每篇算法说明里都有误差表、以及「哪一段没能对上、偏差多大」。没有说成
     「完全一致」的地方，都是实测过确实对不上——例如色温 / 色调对角线上的硬裁切。</p>
  <p class="muted">算法来源在文件头 <code>reference</code> 字段里逐条标注，源码与文档在同一个仓库。</p>
</section>"""

    legal = """<section class="about" id="legal">
  <h2>版权与商标</h2>
  <p>这里的算子都是自己写的：按公开的数学公式与可观察的行为实现，没有复制任何商业软件的
     源代码或二进制，没有反编译产物，也不调用任何厂商的专有接口或 SDK。</p>
  <p>菜单名、对话框标题、算子显示名与页面正文都是本项目自定表述（<code>lb:</code>
     命名空间），不使用任何厂商的 logo、图标或界面截图。仅对业界公开的格式与色空间规范
     沿用标准名称（如 <code>.cube</code> LUT、Adobe RGB），属于指示性引用，不表示与
     本项目存在隶属关系。站点截图是在 GIMP 里运行本项目算子的界面。</p>
  <p class="muted">All code here is original, written from published mathematics and observable
     behaviour, with no vendor-specific interfaces or SDKs. Names and copy are this project's
     own; standard format and colour-space names are cited nominatively only. This project
     is not affiliated with, endorsed by, or authorised by any vendor.
     如认为此处有不当使用，请开 issue，核实后会调整措辞或移除相关内容。</p>
</section>"""

    body = hero + steps + """
<section class="ops" id="ops">
  <h2>{n} 个算子</h2>
  <p class="section-lede">按「找算子时的念头」分了四组，和 GIMP 菜单里的分组一致。
     点任一算子进去看算法、参数与实测误差。</p>
{by_g}
</section>""".format(n=n_live, by_g=by_g) + download + about + legal

    return page("gegl-color-ops · GIMP 3 色彩算子集", body,
                desc="%d 个 GEGL 色彩算子，供 GIMP 3 使用：色阶、色彩平衡、自然饱和度、"
                     "白平衡、通道混合、蒙版。免编译包直接下载。" % n_live)


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
               "blurb": meta.get("blurb") or "",
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
    return page(title, body, root="../", desc=op["purpose_text"][:120], titles=titles)


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
  <p>菜单在 <code>图像 → 颜色 → SuperMrWang</code>，下面分四组：Tone / Color / Blend / Mask。
     也可以在 <code>/</code>（搜索动作）里直接输算子名。</p>
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


def build_plugins(version):
    # 与首页同一套框：facts 条、卡片、dl 盒、note 提示框、step-list、参数表、按钮。
    cards = """
<div class="cards">
  <a class="card" href="#sky">
    <div class="card-top"><span class="tag t-color">换天</span><code>sky-replace</code></div>
    <h3>Sky Replace · 一键换天</h3>
    <p>选中照片 + 指定天空图，一次点击完成分割、合成、亮度匹配——经典泛洪算法，无需 AI 模型。</p>
    <span class="more">看参数与细节 →</span>
  </a>
  <a class="card" href="#layer-to-mask">
    <div class="card-top"><span class="tag t-mask">蒙版</span><code>layer-to-mask</code></div>
    <h3>Layer to Selection / Channel</h3>
    <p>右键点哪个图层，就把哪个图层转成选区或 Alpha 通道——算子跑完留下的灰度图，一步接着用。</p>
    <span class="more">看参数与细节 →</span>
  </a>
</div>"""

    sky_boxes = """
  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>分割</h3><span class="pill">经典算法</span></div>
      <p>从图像<b>顶边三个种子点</b>做泛洪选择，把连通的天空选出来（GIMP 3 的采样
         阈值/判据走 context，插件用 context_push/pop 包住，不污染你的设置）。
         蓝天、晴天照片效果最好。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>收边</h3></div>
      <p>选区按参数<b>收缩/羽化</b>：<code>edge</code> 正=收缩、负=扩张，默认收 1px
         收掉前景光晕。顶行天空覆盖率低于 60% 时直接报错提示，而不是静默输出一张坏结果。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>合成</h3></div>
      <p>天空图按 <b>cover 方式缩放、居中裁切</b>，插到照片图层<b>正上方</b>；
         再按两张天空区的直方图均值算 gamma，把新天空亮度拉到与原天空一致
         （可在对话框关掉）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>输出</h3></div>
      <p>选区转成天空图层的<b>图层蒙版</b>，前景自然露出。可勾选存一条
         <code>Sky Mask</code> 通道：对分割不满意时，用 <code>lb:color-mask-select</code>
         等蒙版算子手工精修，再重新生成选区合成。</p>
    </div>
  </div>
  <div class="table-wrap"><table>
    <thead><tr><th>参数</th><th>范围 / 默认</th><th>做什么</th></tr></thead>
    <tbody>
      <tr><td><code>sky-file</code></td><td>文件</td><td>替换用的天空图</td></tr>
      <tr><td><code>threshold</code></td><td>0 – 0.5</td><td>泛洪采样阈值</td></tr>
      <tr><td><code>edge</code></td><td>默认 1</td><td>选区收缩（正值）/ 扩张（负值）像素数</td></tr>
      <tr><td><code>feather</code></td><td>羽化半径</td><td>选区边缘羽化</td></tr>
      <tr><td><code>match-brightness</code></td><td>开</td><td>gamma 亮度匹配，把新天空拉到原天空亮度</td></tr>
      <tr><td><code>save-mask-channel</code></td><td>关</td><td>把分割蒙版存成 <code>Sky Mask</code> 通道，方便精修</td></tr>
    </tbody>
  </table></div>
  <p class="note">效果边界：泛洪只认<b>颜色连通</b>，不认语义。云层破碎、天空被树枝
     零碎切割、或前景顶边与天空颜色接近的照片，分割质量会下降——这类图建议勾上
     「存 Sky Mask 通道」，用蒙版算子精修后再合成。</p>"""

    ltm_boxes = """
  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Layer to Selection</h3><span class="pill">转选区</span></div>
      <p>把点击的图层变成当前选区：</p>
      <ul>
        <li><b>通道</b>：Gray（亮度）/ R / G / B / Alpha 任选；</li>
        <li><b>组合方式</b>：替换 / 加 / 减 / 交，与 GIMP 选区菜单一致；</li>
        <li>可反相（选暗部而不是亮部）；</li>
        <li>图层比画布小、带偏移也没问题：只在自己位置生效，界外不选中。</li>
      </ul>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Layer to Channel</h3><span class="pill">转通道</span></div>
      <p>把点击的图层变成一条新的 Alpha 通道，<b>恒为灰度</b>：</p>
      <ul>
        <li>彩色图层先按亮度转灰度、黑白图层原样，再把这些<b>灰度值写进通道</b>
            （黑 = 不选中、白 = 完全选中、中间灰 = 部分选中）；</li>
        <li>没有「取 R 通道」这类选项——要的就是明暗，不给单色通道捣乱的机会；</li>
        <li>可反相、可自定义通道名（默认沿用图层名），建好后状态栏提示通道名；</li>
        <li>想变回选区：通道面板右键该通道 → <b>通道到选区</b>（GIMP 原生）。</li>
      </ul>
    </div>
  </div>
  <p class="note"><b>彩色图层的 Gray 是亮度，不是 HSL 明度</b>：纯红 ≈ 54/255，
     而不是 HSL 明度的 130——和你在 PS 里按亮度去色的结果一致。
     实现上走临时副本去色（GIMP 3.2 的 LUMA 模式），用完即删，活动图层还原。</p>
  <p class="note">与 <code>plugin/gray-mask</code> 的分工：gray-mask 走复制/粘贴，会带上
     图层蒙版等<b>显示效果</b>；layer-to-mask 读<b>原始像素</b>、更快、支持任意通道。
     日常「灰度图 → 蒙版」优先用它。有活动选区时写通道会先把选区挂起再恢复——
     GIMP 的 shadow 合并遵守选区，不挂起的话通道会被截成选区那一块。</p>"""

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
         plug-ins 目录（Windows / Linux 通用）：</p>
      <pre><code>bash install-plugin.sh</code></pre>
    </li>
    <li>
      <h3>重启 GIMP，找菜单</h3>
      <p><b>Sky Replace</b>：<code>图层 → SuperMrWang → Sky Replace</code>；
         <b>Layer to Selection / Channel</b>：<code>图层右键 → SuperMrWang</code>，
         另有一份挂在 <code>选择 → SuperMrWang</code> 下（不依赖右键、方便写脚本）。</p>
    </li>
  </ol>
</section>""".format(repo=REPO)

    pdb_table = """<div class="table-wrap"><table>
  <thead><tr><th>PDB 过程</th><th>参数</th><th>用途</th></tr></thead>
  <tbody>
    <tr><td><code>lb-plugin-sky-replace</code></td>
        <td><code>sky-file</code> / <code>threshold</code> / <code>edge</code> /
            <code>feather</code> / <code>match-brightness</code> /
            <code>save-mask-channel</code></td>
        <td>批处理换天</td></tr>
    <tr><td><code>lb-plugin-layer-to-selection</code></td>
        <td><code>channel</code> / <code>invert</code> / 组合方式</td>
        <td>图层 → 选区</td></tr>
    <tr><td><code>lb-plugin-layer-to-channel</code></td>
        <td><code>invert</code> / <code>name</code></td>
        <td>图层 → 灰度 Alpha 通道</td></tr>
  </tbody>
</table></div>"""

    body = """<section class="page-head">
  <p class="eyebrow"><a href="index.html">首页</a> / Python 插件</p>
  <h1>两个 Python 插件</h1>
  <p class="lede">一键换天，以及「右键图层 → 转选区/通道」。GEGL 算子的产出常常是一张
     灰度蒙版，这两个插件把「蒙版 → 能用的东西」压成一次点击。</p>
  <div class="cta">
    <a class="btn primary" href="#install">三步装上</a>
    <a class="btn" href="#sky">换天参数</a>
    <a class="btn ghost" href="https://github.com/SuperMrWang-DEV/gegl-color-ops/tree/main/plugin">看插件源码</a>
  </div>
  <ul class="facts">
    <li><b>2</b> 个插件</li>
    <li><b>3</b> 个 PDB 过程</li>
    <li><b>36</b> 条回归断言</li>
    <li><b>0</b> 编译 · 纯 Python</li>
  </ul>
</section>
<section class="prose wide">
{cards}

  <section class="group" id="sky">
    <h3 class="group-title"><span class="tag t-color">换天</span>
      <span class="group-en">Sky Replace</span><span class="count">一键换天</span></h3>
    <p class="group-desc">选中照片图层 + 指定一张天空图，一次点击完成：泛洪分割 →
       收缩羽化 → 天空 cover 合成 → gamma 亮度匹配 → 图层蒙版。经典算法，
       不需要 AI 模型，蓝天 / 晴天照片效果最好。</p>
{sky_boxes}
  </section>

  <section class="group" id="layer-to-mask">
    <h3 class="group-title"><span class="tag t-mask">蒙版</span>
      <span class="group-en">Layer to Selection / Channel</span><span class="count">一键转选区 / 通道</span></h3>
    <p class="group-desc">这套 GEGL 算子（计算、色彩范围、通道区间到 alpha……）的产出
       常常是一张<b>灰度图</b>——它本身就是一张蒙版。原生流程要把它变成能用的东西得四步
       （复制图层 → 新建通道 → 粘贴 → 蒙版转选区），这两个动作把它压成<b>一次右键</b>，
       而且不要求图层是「纯灰度」。</p>
{ltm_boxes}
  </section>

{install}

  <h2 id="script">脚本调用</h2>
  <p>三个动作都是标准 PDB 过程，脚本里直接调（第二个参数列表可留空走默认值）：</p>
{pdb_table}
  <p class="note">实现：直接读图层像素（array 的 C 级切片，100 万像素约 4 毫秒），
     不走复制粘贴；灰度内容走零拷贝快路径，彩色图层才临时复制一份做去色。
     图层组没有自己的像素，会明确报错提示先合并组。</p>
  <h2 id="tests">回归</h2>
  <p>两套断言跑在 gimp-console 的 python-fu-eval 里：
     <code>tools/check_sky_replace.py</code>（13 条：分层、蒙版、合成像素、亮度匹配、
     开关行为、报错路径；直方图期望值按 255·enc_srgb(v) 刻度换算）与
     <code>tools/check_layer_to_mask.py</code>（23 条：灰度值、反相、偏移图层、
     彩色亮度、四个单通道、通道值/名字/反相、彩色转通道=亮度、选区不被截断、
     四种组合方式）。</p>
</section>""".format(cards=cards, sky_boxes=sky_boxes, ltm_boxes=ltm_boxes,
                   install=install, pdb_table=pdb_table)
    return page("Python 插件 · gegl-color-ops", body,
                desc="GIMP 3 Python 插件：Sky Replace 一键换天；Layer to Selection / "
                     "Channel 右键任意图层一键转选区或灰度 Alpha 通道")


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
            z.write(os.path.join(root_dir, f), f)
        z.writestr("安装说明.txt", readme)
        man = os.path.join(DIST, "manifest.csv")
        if os.path.exists(man):
            z.write(man, "manifest.csv")
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
        "plugins.html": build_plugins(version),
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
