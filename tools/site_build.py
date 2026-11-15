# -*- coding: utf-8 -*-
"""把 ops/ 下的算子渲染成一套静态站点，输出到 docs/（带 .disabled 的标停用/废弃）。

设计上把 docs/ 当作纯产物：每次运行整个目录重建，样式源在 tools/site/。
所以改样式改 tools/site/style.css，别直接改 docs/assets/style.css。

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

def head_html(root=""):
    return """<header class="site-head">
  <a class="brand" href="{r}index.html"><span class="dot"></span>gegl-color-ops</a>
  <nav>
    <a href="{r}index.html#ops">算子</a>
    <a href="{r}guide.html">安装</a>
    <a href="{r}index.html#download">下载</a>
    <a class="ext" href="https://github.com/SuperMrWang-DEV/gegl-color-ops">GitHub</a>
  </nav>
</header>""".replace("{r}", root)


def foot_html(version, root=""):
    return """<footer class="site-foot">
  <div>
    <p><strong>gegl-color-ops</strong> · GIMP 3 的 GEGL 色彩算子集</p>
    <p class="muted">源码与文档同仓库，GPL-3.0-or-later。算法多由实测逆向，非官方移植；
       与 Adobe、GIMP 官方均无隶属关系。</p>
  </div>
  <div class="foot-links">
    <a href="https://github.com/SuperMrWang-DEV/gegl-color-ops">仓库</a>
    <a href="https://github.com/SuperMrWang-DEV/gegl-color-ops/issues">问题反馈</a>
    <a href="{r}guide.html">安装指南</a>
    <span class="muted">{v}</span>
  </div>
</footer>""".format(r=root, v=version)


def page(title, body, root="", desc=""):
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="alternate" type="application/atom+xml" title="算子更新" href="{root}feed.xml">
</head>
<body>
<a class="skip" href="#main">跳到正文</a>
{head}
<main id="main">
{body}
</main>
{foot}
</body>
</html>
""".format(title=html.escape(title), body=body, desc=html.escape(desc),
           root=root, head=head_html(root), foot=foot_html(VERSION, root))


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


def off_badge(op, temporary="停用"):
    if not op.get("disabled"):
        return ""
    return '<span class="badge off">%s</span>' % (
        "已废弃" if op.get("deprecated") else temporary)


def warn_badge(op):
    """`docs` 层面的「不推荐」：算子照常编译发布，只是别拿它当首选。"""
    return '<span class="badge warn">不推荐</span>' if op.get("discouraged") else ""


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
  <p>多数按实测逆向：拿目标实现（多为 Photoshop 的调整图层）做对照，逐档采样、
     拟合公式，再在 16 位精度上把残差压到几码以内。少数是直接实现公开的数学定义
     （Lab / LCh / HSL 色阶就是换了个色彩空间做同一件事）。</p>
  <p>所以每篇算法说明里都有误差表、以及「哪一段没能复刻、偏差多大」。没有说成
     「完全一致」的地方，都是实测过确实对不上——例如 PS 在色温 / 色调对角线上的硬裁切。</p>
  <p class="muted">算法来源在文件头 <code>reference</code> 字段里逐条标注，源码与文档在同一个仓库。</p>
</section>"""

    body = hero + steps + """
<section class="ops" id="ops">
  <h2>{n} 个算子</h2>
  <p class="section-lede">按「找算子时的念头」分了四组，和 GIMP 菜单里的分组一致。
     点任一算子进去看算法、参数与实测误差。</p>
{by_g}
</section>""".format(n=n_live, by_g=by_g) + download + about

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

    # 有一半 README 末尾挂一整段英文翻译，直接铺开会把页面拉长一倍。
    # 折进 <details>：默认收着，想看再展开，也不进右侧目录。
    m = re.search(r"^##\s+English\s*$", md, re.M)
    en_md = md[m.end():] if m else None
    if m:
        md = md[:m.start()]

    body_html, toc = convert(
        md,
        image_prefix=img_prefix,
        link_base=REPO + "/blob/main/",
    )

    if en_md:
        en_html, _ = convert(en_md, image_prefix=img_prefix,
                             link_base=REPO + "/blob/main/")
        body_html += ('<details class="en-block"><summary>English version'
                      '<span class="muted">（同一份说明的英文版）</span></summary>%s</details>'
                      % en_html)
    if legacy_md:
        legacy_html, _ = convert(legacy_md, image_prefix=img_prefix,
                                 link_base=REPO + "/blob/main/")
        body_html += ('<details class="legacy-intro"><summary>原始介绍'
                      '<span class="muted">（这个滤镜作为独立插件时的旧文档：'
                      '编译命令按旧目录结构书写，菜单路径也已改名；算法说明以本页'
                      '上方为准）</span></summary>%s</details>' % legacy_html)
    # README 里偶尔直接写 <img src="assets/...">（原始 HTML 直通），一并补前缀
    body_html = body_html.replace('src="assets/', 'src="%s' % img_prefix)

    toc_html = ""
    if toc:
        items = "\n".join(
            '<li class="l%d"><a href="#%s">%s</a></li>' % (lv, anc, html.escape(t))
            for lv, anc, t in toc)
        toc_html = """<aside class="toc">
  <p class="toc-title">本页目录</p>
  <ul>%s</ul>
</aside>""" % items

    off = (" " + off_badge(op, "临时停用") + warn_badge(op)) \
        if (op["disabled"] or op["discouraged"]) else ""
    meta = """<div class="meta">
    <code>{oid}</code>
    <span class="tag t-{g}">{gz}</span>
    <span>{typ}</span>{off}
  </div>""".format(oid=html.escape(op["id"]), g=op["group"].lower(),
                   gz=GROUP_ZH[op["group"]][1], typ=html.escape(op["type"]), off=off)

    nav = ['<nav class="pager">']
    if op["prev"]:
        nav.append('<a class="prev" href="%s.html"><span>上一个</span>%s</a>'
                   % (op["prev"]["dir"], html.escape(op["prev"]["menu"])))
    else:
        nav.append("<span></span>")
    if op["next"]:
        nav.append('<a class="next" href="%s.html"><span>下一个</span>%s</a>'
                   % (op["next"]["dir"], html.escape(op["next"]["menu"])))
    nav.append("</nav>")
    nav = "".join(nav)

    if op.get("deprecated"):
        dl = """<div class="op-dl">
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
    else:
        f = op["module"]
        lines, btns = [], []
        if op["has_dll"]:
            lines.append('Windows 模块 <code>%s.dll</code>，放进 '
                         '<code>%%LOCALAPPDATA%%\\gegl-0.4\\plug-ins</code>' % f)
            btns.append('<a class="btn" href="%s/%s.dll">下载 %s.dll'
                        '<span class="size">Windows x64</span></a>' % (RAW, f, f))
        if op["has_so"]:
            lines.append('Linux 模块 <code>%s.so</code>，放进 '
                         '<code>~/.local/share/gegl-0.4/plug-ins</code>' % f)
            btns.append('<a class="btn ghost" href="%s/%s.so">下载 %s.so'
                        '<span class="size">Linux x86_64</span></a>' % (LIN_RAW, f, f))
        if not lines:
            lines.append('这一版还没把这个模块打进预编译包，'
                         '可以 <code>./build.sh</code> 自己编一个')
        dl = """<div class="op-dl">
  <div>
    <h3>只要这一个</h3>
    <p>%s，然后重启 GIMP。整包在 <a href="../index.html#download">下载页</a>。</p>
  </div>
  <div class="btns">%s</div>
</div>""" % ("；".join(lines), "".join(btns))

    warn = ""
    if op.get("deprecated"):
        warn = ('\n  <p class="dep-note"><b>已废弃</b>　本算子不再编译、不进安装包，'
                '本页仅作存档。现在每个色彩模式都有自己的分量色阶，不需要「灰度 → '
                '彩色编码 → 混合模式」这套三步走。</p>')
    elif op.get("discouraged"):
        warn = ('\n  <p class="slow-note"><b>不推荐日常使用</b>　邻域双边加 4 次高斯，'
                '半径 30 时每像素约 1.4 µs：2048×1536 默认参数净耗时 0.7 s、含解码 '
                '2.1 s，在 GIMP 里拖一次滑杆就重算一遍整图。整体明暗改用 '
                '<a href="levels.html">色阶</a> / <a href="lab-levels.html">LAB 色阶</a>；'
                '确实需要「周围亮就少提」的局部行为再回来用它，半径压到 10–15 会快很多。'
                '详见 <code>ops/shadows-highlights/.discouraged</code>。</p>')

    body = """<section class="page-head">
  <p class="eyebrow"><a href="../index.html">首页</a> / <a href="../ops.html">算子</a> /
     {gz}</p>
  <h1>{menu}</h1>
  {meta}{warn}
  <p class="lede">{blurb}</p>
</section>
<div class="article-layout">
  <article class="prose">
{html}
    {dl}
    {nav}
  </article>
  {toc}
</div>""".format(gz=GROUP_ZH[op["group"]][1], menu=html.escape(op["menu"]), meta=meta,
                 blurb=op["purpose_html"], html=body_html, dl=dl, nav=nav,
                 warn=warn, toc=toc_html)

    title = "%s · %s" % (op["menu"], "gegl-color-ops")
    return page(title, body, root="../", desc=op["purpose_text"][:120])


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
  <h3>和 Photoshop 的调整图层结果一致吗？</h3>
  <p>多数算子的目标是「肉眼与 8 位输出一致」。实测残差写在每篇算法说明里，
     通常是中位 0–4 码；有明确对不上的段落时也会说明（例如 PS 在个别对角线上的硬裁切）。</p>
  <h3>为什么叫 <code>lb:</code> 前缀？</h3>
  <p>GEGL 的 id 必须唯一。前缀避免和 GIMP 自带算子撞名——撞了会静默加载失败，
     所以这个工程里所有 id 和 GType 名都带前缀。</p>
  <h3>会进 GIMP 官方仓库吗？</h3>
  <p>不会。这是独立的第三方算子集，按 GPL-3.0 发布，自己装进用户插件目录即可。</p>
</article>""".format(repo=REPO, n=stats["win_files"])

    return page("安装与排错 · gegl-color-ops", body,
                desc="GIMP 3 GEGL 算子安装、验证与排错")


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

    # 样式与静态资源
    for f in os.listdir(SRC):
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
          % (4, len(ops),
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
