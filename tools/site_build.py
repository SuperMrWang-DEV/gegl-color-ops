# -*- coding: utf-8 -*-
"""把 ops/ 下的算子渲染成一套静态站点，输出到 docs/（带 .disabled 的标停用/废弃，
带 .wip 的标「施工中」：照常发布，但参数和输出还会变）。

设计上把 docs/ 当作纯产物：每次运行整个目录重建，样式源在 tools/site/。
所以改样式改 tools/site/style.css，别直接改 docs/assets/style.css。

算子页是**中英双语**的：中文正文来自 ops/<dir>/README.md，英文正文来自
tools/site/en/<dir>.md（front matter 给 name / blurb）。两套内容同时写进同一个
HTML，靠 <html data-lang> 决定显示哪一套，页头的 中文/EN 按钮切换并记住偏好
（localStorage + ?lang=en）。**index.html 是主页**：宽屏上一行两列，左边标题块、
右边算子与插件两张卡（各挂 Windows / Linux 整包），窄屏退回上下；长版（三步
安装、算法来源、版权）在 overview.html，页脚有入口。清单页、插件页、安装页
只有中文，不显示切换按钮。

plugins.html 是和算子清单同一套表格（三组，链到 plugins/<slug>.html），
正文全在文章页里；数据与文案集中在 tools/plugin_docs.py，两边不会漂。
feed.xml 里收了十一篇插件文章。

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
import plugin_docs as PD  # Retouch 八节的正文，插件页与文章页共用
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
# macOS 的 .dylib 由另一台机器推到 dist/mac 分支；合并进 main 之后这里的直链才有效
MAC_RAW = REPO + "/raw/main/dist/macos-arm64"

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
    "Sharpen": ("Sharpen", "锐化"),
    "Noise": ("Noise", "杂色"),
    "Distort": ("Distort", "扭曲"),
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
    "Sharpen": "把边缘加陡：PS「锐化 → USM 锐化」的等价物，外加可调的光晕抑制，"
               "硬边不再长出白边。",
    "Noise": "颗粒与瑕疵：添加杂色（可复现）、减少杂色（只磨平坦区）、"
             "蒙尘与划痕（孤立点用邻域中值换掉）。",
    "Distort": "按位移图重采样：一张 RGBA 图同时给 X/Y，单位可换成长边百分比，"
               "覆盖不到的区域原样输出。",
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
    "Sharpen": "Steepen edges: Photoshop's Unsharp Mask with an adjustable halo "
               "suppression, so hard edges stop growing white fringes.",
    "Noise": "Grain and blemishes: add noise (reproducible from a seed), reduce "
             "noise (flat areas only), dust & scratches (isolated specks replaced "
             "by the median of similar neighbours).",
    "Distort": "Resample through a displacement map: one RGBA image drives both "
               "axes, the unit can be a percentage of the long edge, and areas "
               "the map does not cover pass straight through.",
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


CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def split_zh_en(lines):
    """注释盒每段都是先中文后英文，在「第一行不含中文」处切一刀。

    早先按「ASCII 占比 > 0.7 且首字母大写」判定，遇到 `the classic editor …`
    这种小写开头的英文行就切不开，整段英文被并进中文串，页面上出现
    「…并带通道偏移the classic editor Channel Mixer…」这种中英粘连。
    改成看「有没有汉字」：中文行为了夹术语会带 ASCII，英文行则不该出现汉字，
    这个判据在 41 个算子上没有反例，也不依赖句中大小写。
    """
    zh, en = [], []
    for ln in lines:
        if not ln.strip():
            continue
        if not en:
            if zh and not CJK_RE.search(ln):
                en.append(ln)
            else:
                zh.append(ln)
        else:
            en.append(ln)
    return "".join(x for x in zh), " ".join(en)


EN_WORD_RE = re.compile(r"[A-Za-z]{3,}")


def strip_en_sections(md):
    """整节删掉「标题和正文都是英文」的章节。

    rgb-domain-grayscale 这类 README 是「英文正文 + 中文正文」前后两套，中文页会
    先读到一节英文的 Algorithm / Parameters / Notes。英文已经有 tools/site/en 的
    整页版本，中文页里这些节纯属重复，按标题块整段删掉（含标题本身）。

    判据：该标题到下一个同级/更高级标题之间的内容，除了代码块之外一个汉字都没有，
    并且英文词数 >= 12。带一点中文的节（哪怕只有标签）都原样保留。
    """
    lines = md.split("\n")
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            heads.append((i, len(m.group(1))))
    drop = [False] * len(lines)
    for k, (i, lvl) in enumerate(heads):
        end = len(lines)
        for j, lvl2 in heads[k + 1:]:
            if lvl2 <= lvl:
                end = j
                break
        block = "\n".join(lines[i:end])
        clean = re.sub(r"```.*?```", "", block, flags=re.S)
        if not CJK_RE.search(clean) and len(EN_WORD_RE.findall(clean)) >= 12:
            for t in range(i, end):
                drop[t] = True
    return re.sub(r"\n{3,}", "\n\n", "\n".join(
        ln for ln, d in zip(lines, drop) if not d))


def strip_en_blocks(md):
    """删掉中文正文里「整段纯英文」的副本。

    有一批 README 把中文段落紧跟一段英文翻译一起写（apply-image、calculations、
    color-balance、rgb-domain-grayscale 都是），GitHub 上读着没问题，但站点已经
    有 tools/site/en/<dir>.md 的整页英文版，中文页里再留一整段英文就是中英混排：
    读者在中文模式下滑到半页，会突然读到一段英文公式推导。

    只动普通段落：以 # | > ![ - * 1. ` < 开头的块（标题、表格、引用、图片、
    列表、代码、内嵌 HTML）一律原样保留，代码块在切分前就整体保护起来。
    """
    parts = re.split(r"(```.*?```)", md, flags=re.S)
    out = []
    for part in parts:
        if part.startswith("```"):
            out.append(part)
            continue
        chunks = re.split(r"(\n[ \t]*\n)", part)
        kept = []
        for c in chunks:
            st = c.strip()
            if st and not CJK_RE.search(st) and len(EN_WORD_RE.findall(st)) >= 8 \
                    and not re.match(r"^(#|\||>|!\[|[-*+]\s|\d+\.\s|`|<)", st) \
                    and not st.startswith("http"):
                kept.append("")
            else:
                kept.append(c)
        out.append("".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "".join(out))


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
            "wip": os.path.exists(os.path.join(d, ".wip")),
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
                os.path.exists(os.path.join(DIST, "linux-x64", cand + ".so")) or
                os.path.exists(os.path.join(DIST, "macos-arm64", cand + ".dylib"))):
                op["module"] = cand
                break
        else:
            op["module"] = op["dir"]
        # 两个平台各自单独判：某个模块只出了一端时，页面上就别给它挂死链
        op["has_dll"] = os.path.exists(
            os.path.join(DIST, "windows-x64", op["module"] + ".dll"))
        op["has_so"] = os.path.exists(
            os.path.join(DIST, "linux-x64", op["module"] + ".so"))
        op["has_dylib"] = os.path.exists(
            os.path.join(DIST, "macos-arm64", op["module"] + ".dylib"))

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
    <a href="{r}ops.html">{ops}</a>
    <a href="{r}plugins.html">{plug}</a>
    <a href="{r}blog.html">{blog}</a>
    <a href="{r}guide.html">{install}</a>
    <a href="{r}index.html#download">{download}</a>
    <a class="ext" href="https://github.com/SuperMrWang-DEV/gegl-color-ops">GitHub</a>
  </nav>
{sw}</header>""".format(r=root, sw=sw,
                        ops=t("算子", "Operators"),
                        plug=t("插件", "Plug-ins"),
                        blog=t("博客", "Blog"),
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
    <a href="{r}overview.html">{overview}</a>
    <a href="{r}overview.html#legal">{legal}</a>
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
        guide=t("安装指南", "Install guide"),
        overview=t("总览", "Overview"),
        legal=t("来源与版权", "Provenance"))


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
    // description / og 也跟着换：搜索结果、分享卡片用的是这一份
    var metas = document.querySelectorAll("meta[data-desc-zh]");
    for (var j = 0; j < metas.length; j++) {
      metas[j].setAttribute("content",
        l === "en" ? metas[j].getAttribute("data-desc-en")
                   : metas[j].getAttribute("data-desc-zh"));
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


def _css_version():
    """样式表加 ?v= 指纹：改了 CSS 之后浏览器不至于还拿缓存里的旧版。"""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "site", "style.css")
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:10]
    except Exception:
        return "1"


CSS_VER = _css_version()


def page(title, body, root="", desc="", titles=None, math=False, desc_en="",
         body_class=""):
    """titles=(中文标题, English title)。给了就说明这页是双语的，带上切换按钮。

    body_class 给 <body> 加类名。首页用 home、算子页用 article：宽屏时各自
    单独放开 --max（首页放版式，文章页放行宽并把右侧目录带回来贴着正文），
    其余清单页仍是 1120px 的长文行宽。
    """
    bilingual = bool(titles)
    lang_head, lang_foot, lang_attrs = "", "", ""
    if bilingual:
        lang_head = LANG_HEAD_JS + "\n"
        lang_foot = "\n" + LANG_FOOT_JS
        lang_attrs = ' data-title-zh="%s" data-title-en="%s"' % (
            html.escape(titles[0]), html.escape(titles[1]))
        if not desc_en:
            desc_en = desc
    return """<!DOCTYPE html>
<html lang="zh-CN"{attrs}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}" data-desc-zh="{desc}" data-desc-en="{desc_en}">
<meta property="og:title" content="{title}" data-title-zh="{title_zh}" data-title-en="{title_en}">
<meta property="og:description" content="{desc}" data-desc-zh="{desc}" data-desc-en="{desc_en}">
<link rel="stylesheet" href="{root}assets/style.css?v={cssver}">
<link rel="alternate" type="application/atom+xml" title="算子更新 / Operator feed" href="{root}feed.xml">
{math_head}{lang_head}</head>
<body{body_attr}>
<a class="skip" href="#main">{skip}</a>
{head}
<main id="main">
{body}
</main>
{foot}{lang_foot}
</body>
</html>
""".format(title=html.escape(title), body=body, desc=html.escape(desc),
           desc_en=html.escape(desc_en),
           title_zh=html.escape(titles[0] if bilingual else title),
           title_en=html.escape(titles[1] if bilingual else title),
           root=root, cssver=CSS_VER, head=head_html(root, bilingual),
           foot=foot_html(VERSION, root),
           attrs=lang_attrs, lang_head=lang_head, lang_foot=lang_foot,
           math_head=MATH_HEAD if math else "",
           skip=t("跳到正文", "Skip to content"),
           body_attr=(' class="%s"' % body_class) if body_class else "")


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


def _lab(zh, en, lang):
    """页头徽标在 `.l-zh` / `.l-en` 里面，再套一层 t() 就成了语言块嵌套。
    给了 lang 就只输出这一种；没给（卡片、清单表格这种整页双语的）才用 t()。"""
    if lang == "en":
        return en
    if lang == "zh":
        return zh
    return t(zh, en)


def off_badge(op, temporary="停用", temporary_en="Temporarily disabled", lang=None):
    if not op.get("disabled"):
        return ""
    if op.get("deprecated"):
        return '<span class="badge off">%s</span>' % _lab("已废弃", "Retired", lang)
    return '<span class="badge off">%s</span>' % _lab(temporary, temporary_en, lang)


def warn_badge(op, lang=None):
    """`docs` 层面的「不推荐」：算子照常编译发布，只是别拿它当首选。"""
    return '<span class="badge warn">%s</span>' % _lab("不推荐", "Not recommended", lang) \
        if op.get("discouraged") else ""


def wip_badge(op, lang=None):
    """「施工中」：算子能用、也照常发布，但参数和输出还会变，别写进批处理。"""
    return '<span class="badge wip">%s</span>' % _lab("施工中", "WIP", lang) \
        if op.get("wip") else ""


def wip_note(op, lang):
    """页头那条虚线提示。文案写在 `ops/<dir>/.wip` 里，`zh:` / `en:` 各一行；
    文件空着或没写前缀时回落一句通用的。"""
    if not op.get("wip"):
        return ""
    zh = en = ""
    try:
        with open(os.path.join(OPS, op["dir"], ".wip"), encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                low = s.lower()
                if low.startswith("zh:"):
                    zh = s[3:].strip()
                elif low.startswith("en:"):
                    en = s[3:].strip()
    except OSError:
        pass
    if not zh:
        zh = "这个算子的参数与输出还在收尾，版本之间可能变化。"
    if not en:
        en = "Parameters and output are still being wrapped up and may change between builds."
    return '\n  <p class="wip-note"><b>%s</b>　%s</p>' % (
        "Work in progress" if lang == "en" else "施工中",
        html.escape(en if lang == "en" else zh))


def en_blurb(op, n=90):
    """卡片上的一句话：优先用 tools/site/en 里手写的 blurb（比文件头
    purpose 的英文更紧凑、且每篇都有），其次回退到文件头的英文行。"""
    e = load_en(op)
    txt = (e or {}).get("blurb") or op["purpose_en"]
    return short(txt, n) if txt else short(op["purpose_text"], n)


def card(op):
    badge = off_badge(op) + warn_badge(op) + wip_badge(op)
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

def build_home(ops, stats, version, posts=None):
    """主页：两个方框 —— 算子一个、插件一个，各自带 Windows / Linux / macOS 整包。"""
    n_live = sum(1 for o in ops if not o.get("deprecated"))
    n_groups = len(SMG.GROUPS)
    n_plug = len(PLUGIN_SPECS)
    pb = stats.get("plugin_bundle") or {}
    pw, pl = pb.get("windows-x64") or {}, pb.get("linux-x64") or {}
    miss = stats.get("linux_missing") or []

    def dl(href, os_zh, os_en, meta_zh, meta_en, missing=False):
        return """<a class="dl-link{miss}" href="{href}">
        <span class="os">{os}</span>
        <span class="meta">{meta}</span>
        <span class="arrow" aria-hidden="true">↓</span>
      </a>""".format(href=href, miss=" is-missing" if missing else "",
                     os=t(os_zh, os_en), meta=t(meta_zh, meta_en))

    win_dl = dl("download/" + stats["zip_name"], "Windows x64", "Windows x64",
                "%d 个 .dll · %s MB" % (stats["win_files"], stats["zip_mb"]),
                "%d .dll · %s MB" % (stats["win_files"], stats["zip_mb"]))
    if stats.get("zip_linux_name"):
        lin_dl = dl("download/" + stats["zip_linux_name"], "Linux x86_64", "Linux x86_64",
                    "%d 个 .so · %s MB" % (stats["linux_files"], stats["zip_linux_mb"]),
                    "%d .so · %s MB" % (stats["linux_files"], stats["zip_linux_mb"]),
                    missing=bool(miss))
    else:
        lin_dl = dl("%s/tree/main/dist/linux-x64" % REPO, "Linux x86_64", "Linux x86_64",
                    "暂无预编译包，用 build.sh 自编", "no prebuilt yet — use build.sh")

    if stats.get("zip_mac_name"):
        mac_dl = dl("download/" + stats["zip_mac_name"], "macOS arm64", "macOS arm64",
                    "%d 个 .dylib · %s MB" % (stats["mac_files"], stats["zip_mac_mb"]),
                    "%d .dylib · %s MB" % (stats["mac_files"], stats["zip_mac_mb"]))
    else:
        # 还没合并 macOS 产物：指向 Actions，那里每次 push 都会编一份 artifact
        mac_dl = dl("%s/actions/workflows/build.yml" % REPO, "macOS arm64",
                    "macOS arm64",
                    "待合并 · 可从 Actions 下载",
                    "pending — grab it from Actions")

    pwin_dl = dl("download/" + pw["name"], "Windows x64", "Windows x64",
                 "%d 个 .py · %d 个模块 · %s MB" % (pw.get("py", n_plug), pw.get("mods", 0),
                                                 pw.get("mb", 0)),
                 "%d .py · %d modules · %s MB" % (pw.get("py", n_plug), pw.get("mods", 0),
                                                  pw.get("mb", 0))) if pw else ""
    plin_dl = dl("download/" + pl["name"], "Linux x86_64", "Linux x86_64",
                 "%d 个 .py · %d 个模块 · %s MB" % (pl.get("py", n_plug), pl.get("mods", 0),
                                                 pl.get("mb", 0)),
                 "%d .py · %d modules · %s MB" % (pl.get("py", n_plug), pl.get("mods", 0),
                                                  pl.get("mb", 0)),
                 missing=True) if pl else ""

    pm = pb.get("macos-arm64") or {}
    if pm:
        pmac_dl = dl("download/" + pm["name"], "macOS arm64", "macOS arm64",
                     "%d 个 .py · %d 个模块 · %s MB" % (pm.get("py", n_plug),
                                                     pm.get("mods", 0), pm.get("mb", 0)),
                     "%d .py · %d modules · %s MB" % (pm.get("py", n_plug),
                                                      pm.get("mods", 0), pm.get("mb", 0)))
    else:
        # 还没合并 macOS 产物时不能装作有包：给一条去 dist/mac 分支的路
        pmac_dl = dl("%s/actions/workflows/build.yml" % REPO, "macOS arm64",
                     "macOS arm64",
                     ".py 跨平台，模块等 Mac 产物",
                     "portable .py — modules pending")

    ops_miss = ""
    if miss:
        ops_miss = """<p class="door-note"><span class="l-zh">Linux 端少 %d 个分量模块（各空间的
      dual / compose 与 gray-to-component），要用就 <code>./build.sh</code> 自编；
      Windows 端 %d 个齐全。</span><span class="l-en">The Linux bundle is missing %d
      component modules (dual / compose for each space, plus gray-to-component) — build
      them with <code>./build.sh</code>. The Windows bundle has all %d.</span></p>""" % (
            len(miss), stats["win_files"], len(miss), stats["win_files"])

    plug_miss = ""
    if pl and pl.get("absent"):
        plug_miss = """<p class="door-note"><span class="l-zh">Linux 整包里没有那 %d 个分量模块，
      所以五个 <b>Split (Curves)</b> 插件要先自编再用；其余插件在 Linux 上装完即用。</span><span class="l-en">The Linux bundle leaves out those %d component
      modules, so the five <b>Split (Curves)</b> plug-ins need a local build first; every
      other plug-in works out of the box on Linux.</span></p>""" % (
            len(pl["absent"]), len(pl["absent"]))

    hero = """<section class="home-hero">
  <div class="home-glow" aria-hidden="true"></div>
  <p class="eyebrow">GIMP 3.x · GEGL 0.4 · GPL-3.0</p>
  <h1><span class="l-zh">GIMP 3 的 <span class="grad">GEGL 插件</span><br>两个包，一整套调色链</span><span class="l-en">The <span class="grad">GEGL plug-in set</span><br>for GIMP 3</span></h1>
  <p class="lede"><span class="l-zh">{n} 个 <code>lb:</code> 算子管算法，{p} 个 Python 插件管流程：
     把分量拆成层、把 alpha 画成曲线、把磨皮拆成高低频、把通道与蒙版互相倒。装完即用，
     全部能当非破坏滤镜挂在图层上，改参数不落像素。</span><span class="l-en">Two archives, the whole colour chain: {n} <code>lb:</code>
     GEGL operators for the maths, {p} Python plug-ins for the workflow: split a component into layers,
     draw alpha as a curve, separate skin into high and low frequency, flip channels and masks
     back and forth. Ready to use, all of it mounts as non-destructive filters.</span></p>
  <ul class="facts">
    <li><b>{n}</b> <span class="l-zh">个算子</span><span class="l-en">operators</span></li>
    <li><b>{p}</b> <span class="l-zh">个插件</span><span class="l-en">plug-ins</span></li>
    <li><b>{g}</b> <span class="l-zh">个分组</span><span class="l-en">groups</span></li>
    <li><b>0</b> <span class="l-zh">依赖 · 免编译</span><span class="l-en">deps · prebuilt</span></li>
  </ul>
</section>""".format(n=n_live, p=n_plug, g=n_groups)

    doors = """<section class="doors" id="download">
  <article class="door door-ops" id="ops">
    <p class="door-kicker">01 · OPERATORS</p>
    <h2><span class="l-zh">GEGL 算子</span><span class="l-en">GEGL operators</span></h2>
    <p class="door-lead"><span class="l-zh">{n} 个单文件 C 模块，一个模块一个滤镜。
     色阶、色彩平衡、自然饱和度、白平衡、通道混合、蒙版生成都在里面，按
     <b>Levels / Component / Tone / Color / Blend / Mask / Sharpen / Noise / Distort</b> 九组排在顶层菜单下。</span><span class="l-en">{n} single-file C modules, one filter each. Levels, colour balance,
     vibrance, white balance, channel mixing, mask building, sharpening, noise and
     displacement, arranged in nine groups —
     <b>Levels / Component / Tone / Color / Blend / Mask / Sharpen / Noise / Distort</b> —
     under one top-level menu.</span></p>
    <div class="door-meta">
      <span><b>{win}</b> <span class="l-zh">个 Windows 模块</span><span class="l-en">Windows modules</span></span>
      <span><b>{lin}</b> <span class="l-zh">个 Linux 模块</span><span class="l-en">Linux modules</span></span>
      <span><b>{mac}</b> <span class="l-zh">个 macOS 模块</span><span class="l-en">macOS modules</span></span>
      <span><b>{g}</b> <span class="l-zh">个分组</span><span class="l-en">groups</span></span>
    </div>
    <div class="door-dl">{win_dl}{lin_dl}{mac_dl}</div>
    {miss}
    <div class="door-foot">
      <a href="ops.html"><span class="l-zh">看全部 {n} 个算子</span><span class="l-en">Browse all {n}</span> <span aria-hidden="true">→</span></a>
      <a class="sub" href="overview.html#download"><span class="l-zh">单个模块</span><span class="l-en">One module at a time</span></a>
    </div>
  </article>

  <article class="door door-plug" id="plugins">
    <p class="door-kicker">02 · PLUG-INS</p>
    <h2><span class="l-zh">Python 插件</span><span class="l-en">Python plug-ins</span></h2>
    <p class="door-lead"><span class="l-zh">{p} 个 Python 插件，负责把算子串成流程：五个色彩空间的分量
     拆层加三条曲线、Alpha 曲线、高低频 / 双曲线 / 中性灰磨皮、图层转选区与转通道，
     还有通道 / 选区 / 蒙版 / 路径十二个方向的互转。每个插件内部要用的算子模块已经打在包里。</span><span class="l-en">{p} Python plug-ins that string the operators into a workflow: component
     split-and-curve in five colour spaces, alpha curves, frequency-separation / dodge &amp;
     burn / neutral-grey retouching, layer-to-selection and layer-to-channel, plus the
     twelve-way channel / selection / mask / path conversion. The operator modules each one
     needs are already inside.</span></p>
    <div class="door-meta">
      <span><b>{p}</b> <span class="l-zh">个 .py</span><span class="l-en">scripts</span></span>
      <span><b>3</b> <span class="l-zh">组磨皮</span><span class="l-en">retouching sets</span></span>
      <span><b>2</b> <span class="l-zh">处入口</span><span class="l-en">menu entries</span></span>
    </div>
    <div class="door-dl">{pwin_dl}{plin_dl}{pmac_dl}</div>
    {pmiss}
    <div class="door-foot">
      <a href="plugins.html"><span class="l-zh">看全部 {p} 个插件</span><span class="l-en">Browse all {p}</span> <span aria-hidden="true">→</span></a>
      <a class="sub" href="guide.html"><span class="l-zh">怎么装</span><span class="l-en">How to install</span></a>
    </div>
  </article>
</section>""".format(n=n_live, p=n_plug, g=n_groups,
                     win=stats["win_files"], lin=stats["linux_files"],
                     mac=stats["mac_files"],
                     win_dl=win_dl, lin_dl=lin_dl, mac_dl=mac_dl, miss=ops_miss,
                     pwin_dl=pwin_dl, plin_dl=plin_dl, pmac_dl=pmac_dl,
                     pmiss=plug_miss)

    quick = """<section class="quick">
  <h2><span class="l-zh">两个目录，三个动作</span><span class="l-en">Two directories, three moves</span></h2>
  <ol class="quick-list">
    <li>
      <h3><span class="l-zh">模块进 GEGL</span><span class="l-en">Modules into GEGL</span></h3>
      <p><span class="l-zh">解压后把 <code>.dll</code> / <code>.so</code> / <code>.dylib</code> 整个扔进 GEGL 的模块目录，<code>locale/</code> 也一起放（中文语言包，不放就只有英文）。</span><span class="l-en">Unpack and drop every <code>.dll</code> / <code>.so</code> / <code>.dylib</code> into GEGL's module directory — together with <code>locale/</code>, the Chinese catalogue.</span></p>
      <pre><code>Windows  %LOCALAPPDATA%\\gegl-0.4\\plug-ins
Linux    ~/.local/share/gegl-0.4/plug-ins
macOS    ~/Library/Application Support/gegl-0.4/plug-ins</code></pre>
    </li>
    <li>
      <h3><span class="l-zh">.py 进 GIMP</span><span class="l-en">Scripts into GIMP</span></h3>
      <p><span class="l-zh">插件包里的 <code>.py</code> 放进 GIMP 的插件目录，两处都要放，缺一个就报「找不到过程」；<code>_shared/</code> 与 <code>locale/</code> 跟 <code>.py</code> 放同一层。</span><span class="l-en">The plug-in bundle's <code>.py</code> files go into GIMP's plug-in directory. Both places — miss one and the procedure won't be found. Keep <code>_shared/</code> and <code>locale/</code> at that same level.</span></p>
      <pre><code>Windows  %APPDATA%\\GIMP\\3.x\\plug-ins
Linux    ~/.config/GIMP/3.x/plug-ins
macOS    ~/Library/Application Support/GIMP/3.x/plug-ins</code></pre>
    </li>
    <li>
      <h3><span class="l-zh">重启 GIMP</span><span class="l-en">Restart GIMP</span></h3>
      <p><span class="l-zh">完全退出再打开，菜单栏顶层就有 <b>SuperMrWang</b>（和「颜色」「图层」平级）。</span><span class="l-en">Quit completely and reopen: <b>SuperMrWang</b> is now a top-level menu, a sibling of Colors and Layer.</span></p>
    </li>
  </ol>
  <p class="note"><span class="l-zh">macOS 包是 <b>arm64</b>（Apple Silicon）的，Intel Mac 要
     <code>brew install gegl &amp;&amp; ./build.sh</code> 自编；Homebrew 版 GIMP 与官方版读同一个
     目录，GEGL 0.4.60+ 在 macOS 只认 <code>.dylib</code> 不认 <code>.so</code>。
     装不上、菜单里看不到、和 GIMP 自带算子重名——排错写在
     <a href="guide.html">安装指南</a>；算法来源、误差表与三轮安装说明在
     <a href="overview.html">完整总览</a>。</span><span class="l-en">The macOS bundle is <b>arm64</b> (Apple Silicon); on an Intel Mac build
     your own with <code>brew install gegl &amp;&amp; ./build.sh</code>. Homebrew and
     official GIMP read the same directory, and GEGL 0.4.60+ on macOS loads
     <code>.dylib</code>, never <code>.so</code>. Won't install, missing from the menu,
     name clashes — see the <a href="guide.html">install guide</a>. Algorithm
     provenance, error tables and the long version live in the
     <a href="overview.html">full overview</a>.</span></p>
</section>"""

    prov_short = """<section class="provenance home-prov" id="provenance">
  <div class="prov-head">
    <p class="eyebrow"><span class="l-zh">来源 · 版权 · 商标</span><span class="l-en">Provenance · copyright · trademarks</span></p>
    <h2><span class="l-zh">这些算子是怎么来的</span><span class="l-en">Where these operators come from</span></h2>
  </div>
  <div class="prov-grid">
    <article class="prov-card">
      <h3><span class="l-zh">黑盒标定 + 公开数学</span><span class="l-en">Black-box calibration, plus published maths</span></h3>
      <p><span class="l-zh">多数按目标实现逐档采样、拟合公式，在 16 位精度上把残差压到几码以内——只看输入输出，
         不读对方代码；少数直接实现公开的数学定义。每篇算法说明都带误差表，以及「哪一段没能对上、
         偏差多大」，没说成「完全一致」的地方都是实测确实对不上。</span><span class="l-en">Most are fitted against a reference implementation sample by sample, residual
         pressed to a few code values at 16-bit — inputs and outputs only, no source reading;
         a few implement published definitions directly. Every algorithm note carries an error
         table and says which part does not match, and by how much.</span></p>
    </article>
    <article class="prov-card">
      <h3><span class="l-zh">全部原创，无厂商代码</span><span class="l-en">Original code, no vendor material</span></h3>
      <p><span class="l-zh">没有复制任何商业软件的源代码或二进制，没有反编译产物，也不调用任何厂商的专有接口或 SDK；
         菜单名与文案为本项目自定表述（<code>lb:</code>），不使用任何厂商 logo、图标或界面截图。
         <code>.cube</code>、Adobe RGB 这类标准名称仅作指示性引用，不表示隶属关系。</span><span class="l-en">No vendor source code or binaries were copied, nothing was decompiled, and no
         proprietary interface or SDK is called; names and copy are this project's own
         (<code>lb:</code>). No vendor logo, icon or UI screenshot is used — standard names such
         as <code>.cube</code> or Adobe RGB are nominative references only.</span></p>
    </article>
  </div>
  <p class="prov-more"><a href="overview.html#legal"><span class="l-zh">完整说明（含商标声明与处理方式）</span><span class="l-en">The full statement, trademarks included</span> <span aria-hidden="true">→</span></a></p>
</section>"""

    # 首屏：文字通栏在上，两个方块（算子 / 插件）左右并排；1000 以下两张卡
    # 自动叠成上下。
    top = """<div class="home-top">
%s
%s
</div>""" % (hero, doors)

    cards = ""
    if posts:
        cards = "\n".join("""    <a class="teaser-card" href="blog/{slug}.html">
      <time datetime="{date}">{date_h}</time>
      <h3>{title}</h3>
      <p>{lede}</p>
    </a>""".format(slug=p["slug"], date=p["date"], date_h=p["date_h"],
                    title=t(html.escape(p["title_zh"]), html.escape(p["title_en"])),
                    lede=t(html.escape(p["lede_zh"]), html.escape(p["lede_en"])))
                        for p in posts[:3])
    blog_teaser = """<section class="blog-teaser">
  <div class="teaser-head">
    <p class="eyebrow">03 · NOTES</p>
    <h2><span class="l-zh">博客</span><span class="l-en">Blog</span></h2>
    <p class="teaser-sub"><span class="l-zh">算法背后的取舍，中英双版</span><span class="l-en">The trade-offs behind the maths, in both languages</span></p>
    <a class="teaser-all" href="blog.html"><span class="l-zh">全部 %d 篇</span><span class="l-en">All %d posts</span> <span aria-hidden="true">→</span></a>
  </div>
  <div class="teaser-grid">
%s
  </div>
</section>""" % (len(posts), len(posts), cards)

    return page("gegl-color-ops · GIMP 3 的 GEGL 算子与插件",
                top + quick + blog_teaser + prov_short, body_class="home",
                desc="GIMP 3 的 %d 个 GEGL 色彩算子 + %d 个 Python 插件，"
                     "Windows / Linux / macOS 整包直接下载。" % (n_live, n_plug),
                titles=("gegl-color-ops · GIMP 3 的 GEGL 算子与插件",
                        "gegl-color-ops · GEGL operators and plug-ins for GIMP 3"))


def build_overview(ops, stats, version):
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
    <a class="btn primary" href="#download"><span class="l-zh">下载预编译包</span><span class="l-en">Download a prebuilt bundle</span><span class="size">Win {size} MB</span></a>
    <a class="btn" href="#ops"><span class="l-zh">浏览 {n} 个算子</span><span class="l-en">Browse the {n} operators</span></a>
    <a class="btn ghost" href="guide.html"><span class="l-zh">怎么装</span><span class="l-en">How to install</span></a>
  </div>
  <ul class="facts">
    <li><b>{n}</b> <span class="l-zh">个算子</span><span class="l-en">operators</span></li>
    <li><b>6</b> <span class="l-zh">个分类</span><span class="l-en">categories</span></li>
    <li><b>0</b> <span class="l-zh">依赖 · 免编译包</span><span class="l-en">dependencies · prebuilt</span></li>
    <li><b>{files}</b> <span class="l-zh">个 Windows 模块已随仓库发布</span><span class="l-en">Windows modules shipped with the repo</span></li>
  </ul>
</section>""".format(n=n_live, dep=dep_note, size=stats["zip_mb"], files=stats["win_files"])

    steps = """<section class="steps" id="start">
  <h2><span class="l-zh">三分钟装上</span><span class="l-en">Set up in three minutes</span></h2>
  <ol class="step-list">
    <li>
      <h3><span class="l-zh">解开压缩包</span><span class="l-en">Unpack the archive</span></h3>
      <p><span class="l-zh">把包里的模块（Windows <code>.dll</code> / Linux <code>.so</code> / macOS <code>.dylib</code>）放进 GEGL 的用户插件目录，目录不存在就自己建一个：</span><span class="l-en">Drop the modules (Windows <code>.dll</code>, Linux <code>.so</code>, macOS <code>.dylib</code>) into GEGL's user plug-in directory — create it if it doesn't exist:</span></p>
      <pre><code>Windows  %LOCALAPPDATA%\\gegl-0.4\\plug-ins
Linux    ~/.local/share/gegl-0.4/plug-ins
macOS    ~/Library/Application Support/gegl-0.4/plug-ins</code></pre>
    </li>
    <li>
      <h3><span class="l-zh">重启 GIMP</span><span class="l-en">Restart GIMP</span></h3>
      <p><span class="l-zh">没有安装步骤，也没有注册表。GEGL 启动时扫描这个目录，GIMP 跟着加载。</span><span class="l-en">No installer, no registry. GEGL scans that directory at startup and GIMP picks the modules up.</span></p>
    </li>
    <li>
      <h3><span class="l-zh">在菜单里找</span><span class="l-en">Find them in the menu</span></h3>
      <p><span class="l-zh">菜单栏顶层就有 <code>SuperMrWang</code>（和「颜色」「图层」平级）：色阶家族收在一级目录
     <b>Levels</b> 子菜单里（Levels / LAB / HSL / HSB / LCH / CMYK / HSI），
     分量家族的 dual / compose 与 gray-to-component 收在一级目录 <b>Component</b> 里，
     其余按 Tone / Color / Blend / Mask / Sharpen / Noise / Distort 七组排开；
     也可以按 <code>/</code> 搜算子名直接调。</span><span class="l-en">The filters live in a top-level <code>SuperMrWang</code> menu: the levels family is
     grouped in a top-level <b>Levels</b> submenu (Levels / LAB / HSL / HSB / LCH /
     CMYK / HSI), the component family (dual / compose pairs and gray-to-component)
     in a top-level <b>Component</b> submenu, and the rest in seven groups —
     Tone / Color / Blend / Mask / Sharpen / Noise / Distort. You can also press
     <code>/</code> and search by operator name.</span></p>
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

    if stats.get("zip_mac_name"):
        mac_body = """<p><span class="l-zh">{mac} 个 <code>.dylib</code>（{msize} MB），Apple Silicon 专用。解到
         <code>~/Library/Application Support/gegl-0.4/plug-ins</code>，重启 GIMP 即可
         （GEGL 0.4.60+ 在 macOS 只认 <code>.dylib</code>，不是 <code>.so</code>）。</span><span class="l-en">{mac} <code>.dylib</code> files ({msize} MB), Apple Silicon only. Unpack into
         <code>~/Library/Application Support/gegl-0.4/plug-ins</code> and restart GIMP
         (GEGL 0.4.60+ on macOS loads <code>.dylib</code>, not <code>.so</code>).</span></p>
      <a class="btn" href="download/{mzip}">gegl-color-ops-macos-arm64.zip</a>
      <p class="muted small">{chk}<code>SHA256 {msha}</code></p>""".format(
            mac=stats["mac_files"], msize=stats["zip_mac_mb"],
            mzip=stats["zip_mac_name"], msha=stats["zip_mac_sha"][:32] + "…",
            chk=t("校验：", "Checksum: "))
    else:
        mac_body = """<p><span class="l-zh">预编译包还没合并进来。macOS 产物由一台 Apple Silicon 机器编译，
         跑 <code>./tools/dist_mac.sh</code> 后推到 <code>dist/mac</code> 分支；也可以自己
         <code>brew install gegl &amp;&amp; ./build.sh</code>。</span><span class="l-en">No bundle merged in yet. macOS builds come from a separate Apple Silicon
         machine: run <code>./tools/dist_mac.sh</code>, which pushes to the
         <code>dist/mac</code> branch. Or build your own with
         <code>brew install gegl &amp;&amp; ./build.sh</code>.</span></p>
      <a class="btn" href="{repo}/tree/dist/mac/dist/macos-arm64"><span class="l-zh">看 macOS 目录</span><span class="l-en">Browse the macOS directory</span></a>""".format(repo=REPO)

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
      <div class="dl-head"><h3>macOS arm64</h3></div>
      {mac_body}
    </div>
    <div class="dl">
      <div class="dl-head"><h3>{single}</h3></div>
      <p><span class="l-zh">只想试一个？每个算子的文章页底部有它自己的模块直链。模块之间
         互不依赖（只链接 GIMP 自带的 GEGL 与 babl），下一个就是完整的。
         也可以从仓库里挑：<code>dist/windows-x64/&lt;名字&gt;.dll</code>、
         <code>dist/linux-x64/&lt;名字&gt;.so</code>、
         <code>dist/macos-arm64/&lt;名字&gt;.dylib</code>。</span><span class="l-en">Just one? Every operator page links its own module at the bottom.
         Modules never depend on each other here — only on the GEGL and babl that
         ship with GIMP — so one file is complete. Or pick from the repo:
         <code>dist/windows-x64/&lt;name&gt;.dll</code>,
         <code>dist/linux-x64/&lt;name&gt;.so</code>,
         <code>dist/macos-arm64/&lt;name&gt;.dylib</code>.</span></p>
      <a class="btn ghost" href="{repo}/tree/main/dist/windows-x64">{browse}</a>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>{pyplug}</h3><span class="pill">{pypill}</span></div>
      <p><span class="l-zh">Layer to Selection / Layer to Channel 以及 Retouch 里那些一键效果，
         每个插件一个包，<b>插件用到的算子模块已经打在包里</b>，下一次就齐。
         <code>.py</code> 进 GIMP 的 plug-ins，附带的模块进 GEGL 的 plug-ins。</span><span class="l-en">Layer to Selection / Layer to Channel and the one-click effects under
         Retouch: one zip each, and <b>the operator modules a plug-in needs are
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
                     mac_body=mac_body,
                     repo=REPO, chk=t("校验：", "Checksum: "),
                     rec=t("推荐", "Recommended"),
                     single=t("单个算子", "A single operator"),
                     browse=t("浏览模块列表", "Browse the module list"),
                     pyplug=t("Python 插件", "Python plug-ins"),
                     pypill=t(".py · 免编译", ".py · no build"),
                     goplugins=t("去插件页下载", "Get them on the plug-ins page"))

    provenance = """<section class="provenance" id="legal">
  <div class="prov-head">
    <p class="eyebrow"><span class="l-zh">来源 · 版权 · 商标</span><span class="l-en">Provenance · copyright · trademarks</span></p>
    <h2><span class="l-zh">这些算子是怎么来的</span><span class="l-en">Where these operators come from</span></h2>
    <p class="section-lede"><span class="l-zh">每个算子都写清楚是标定来的还是按公开定义实现的，误差有多大；
       全部代码原创，不复制、不反编译、不调用厂商 SDK。</span><span class="l-en">Every operator says whether it was calibrated or implemented from a
       published definition, and how large the residual is; all code is original — nothing
       copied, nothing decompiled, no vendor SDK.</span></p>
  </div>

  <div class="prov-grid">
    <article class="prov-card" id="provenance">
      <h3><span class="l-zh">来源与标定方式</span><span class="l-en">Where the numbers come from</span></h3>
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
      <p><span class="l-zh">算法来源在文件头 <code>reference</code> 字段里逐条标注，源码与文档在同一个仓库。</span><span class="l-en">Sources are listed per operator in the <code>reference</code> field of each file
     header; source and docs share one repository.</span></p>
    </article>

    <article class="prov-card" id="trademarks">
      <h3><span class="l-zh">版权与商标</span><span class="l-en">Copyright &amp; trademarks</span></h3>
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
      <p class="prov-final"><span class="l-zh">所有代码均为原创，依据公开数学与可观察行为自行实现，不使用任何厂商专有接口或
     SDK；名称与文案为本项目自定表述，标准格式与色空间名称仅作指示性引用，不构成隶属关系。
     如认为此处有不当使用，请开 issue，核实后会调整措辞或移除相关内容。</span><span class="l-en">All code here is original, written from published mathematics and observable
     behaviour, with no vendor-specific interfaces or SDKs. Names and copy are this
     project's own; standard format and colour-space names are cited nominatively only.
     This project is not affiliated with, endorsed by, or authorised by any vendor.
     If you believe something here is misused, open an issue and it will be reworded
     or removed once verified.</span></p>
    </article>
  </div>
</section>"""

    body = hero + steps + """
<section class="ops" id="ops">
  <h2>{n}</h2>
  <p class="section-lede"><span class="l-zh">按「找算子时的念头」分了九组，和 GIMP 菜单里的分组一致——
     七个色阶收在 Levels 一级目录里，分量家族收在 Component 一级目录里，
     锐化 / 杂色 / 扭曲三组在 2026-11 补齐。
     点任一算子进去看算法、参数与实测误差。</span><span class="l-en">Nine groups organised by the question you ask when hunting for an operator,
     matching the GIMP menu grouping — the levels family and the component family
     each sit in their own top-level submenu, and Sharpen / Noise / Distort joined
     them in November 2026. Open any operator for its algorithm, parameters and
     measured error.</span></p>
{by_g}
</section>""".format(n=t("%d 个算子" % n_live, "%d operators" % n_live), by_g=by_g) \
        + download + provenance

    return page("gegl-color-ops · GIMP 3 色彩算子集", body,
                desc="%d 个 GEGL 色彩算子，供 GIMP 3 使用：色阶、色彩平衡、自然饱和度、"
                     "白平衡、通道混合、蒙版。免编译包直接下载。" % n_live,
                titles=("gegl-color-ops · GIMP 3 色彩算子集",
                        "gegl-color-ops · colour operators for GIMP 3"))


def build_ops_index(ops, version):
    """算子清单：整页双语，表格每个单元格都过 t()。

    这页此前只有中文，EN 模式下点「Operators」会掉进一页纯中文还没有切换按钮，
    是整站语言切换最大的一个断点。
    """
    n_live = sum(1 for o in ops if not o.get("deprecated"))
    n_dep = len(ops) - n_live
    rows = []
    for g in SMG.GROUPS:
        members = [o for o in ops if o["group"] == g]
        if not members:
            continue
        # 分组说明原先整个塞在 <h2> 里，标题被撑成两行大字，读起来像口号；
        # 标题只留标签，说明单独一行。
        rows.append('<h2 id="g-%s"><span class="tag t-%s">%s</span></h2>'
                    % (g, g.lower(), t(GROUP_ZH[g][1], GROUP_ZH[g][0])))
        rows.append('<p class="group-desc">%s</p>'
                    % t(GROUP_DESC[g], GROUP_DESC_EN[g]))
        rows.append('<div class="table-wrap"><table class="op-table">')
        rows.append("<thead><tr><th>%s</th><th>GEGL id</th><th>%s</th>"
                    "<th>%s</th></tr></thead><tbody>"
                    % (t("菜单名", "Menu name"), t("类型", "Type"),
                       t("做什么", "What it does")))
        for o in members:
            off = (" " + off_badge(o) + warn_badge(o) + wip_badge(o)) \
                if (o["disabled"] or o["discouraged"] or o["wip"]) else ""
            rows.append('<tr><td><a href="ops/%s.html"><b>%s</b></a>%s</td>'
                        '<td><code>%s</code></td><td class="nowrap">%s</td><td>%s</td></tr>'
                        % (o["dir"],
                           t(html.escape(o["menu"]), html.escape(en_name(o))),
                           off, html.escape(o["id"]),
                           t(html.escape(o["type"]),
                             html.escape(TYPE_EN.get(o["type"], o["type"]))),
                           t(inline(short(o["purpose_zh"], 70)),
                             inline(short(en_blurb(o), 70)))))
        rows.append("</tbody></table></div>")

    dep_zh = ("其中 %d 个已废弃，只作存档、不提供下载。" % n_dep) if n_dep else ""
    dep_en = ("%d of them are retired: archive only, no download." % n_dep) if n_dep else ""
    body = """<section class="page-head">
  <p class="eyebrow"><a href="index.html">{home}</a> / {ops}</p>
  <h1>{n}</h1>
  <p class="lede">{lede}{dep}</p>
</section>
<section class="prose wide">
{rows}
</section>""".format(home=t("首页", "Home"), ops=t("算子清单", "Operators"),
                       n=t("%d 个算子" % n_live, "%d operators" % n_live),
                       lede=t("按 GIMP 菜单里的分组排列。点名字进算法说明。",
                              "Grouped the way the GIMP menu is. Open a name for the "
                              "algorithm notes."),
                       dep=t(dep_zh, dep_en) if (dep_zh or dep_en) else "",
                       rows="\n".join(rows))
    return page("算子清单 · gegl-color-ops", body,
                desc="全部算子的清单与一句话说明",
                titles=("算子清单 · gegl-color-ops", "Operators · gegl-color-ops"),
                desc_en="Every operator with a one-line description: levels, component "
                        "pairs, tone, colour, blend and mask.")


def split_legacy_intro(md):
    """把 README 里的「旧版插件文档」切出来。

    ops/ 下有九个 README 还带着最初作为独立插件时的说明：编译命令按旧目录结构写、
    菜单路径带 WB 后缀、全文没有一句算法。这些内容与现在的算子对不上，直接铺在
    页面上只会误导。切出来单放进 <details> 折叠，正文只留当前说明。

    旧文档的边界很规整：正文是 `## English` → `## 中文` 这一段双语安装说明；
    它前面紧邻的「本文件是该滤镜的原始说明文档」提示与 `# GEGL_GIMP_PLUGIN_*`
    标题也算旧文档。有些 README（xyz-multiply / hsl-bands）在提示之后还写了当前
    实现说明，所以不能简单地「从文件头切到文件尾」。

    返回 (正文 md, 旧文档 md 或 None)。
    """
    m_en = re.search(r"^##\s+English\s*$", md, re.M)
    if not m_en:
        return md, None

    # 起点：English 之前紧邻的一串「提示 / GEGL_GIMP_PLUGIN 标题 / 图片 / 分隔线」
    # 算旧文档；遇到别的行（正文、其它引用块、代码块）就停 —— hsl-bands 的
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
    if op["has_dylib"]:
        if en:
            lines.append('macOS module <code>%s.dylib</code>, drop it into '
                         '<code>~/Library/Application Support/gegl-0.4/plug-ins</code>' % f)
        else:
            lines.append('macOS 模块 <code>%s.dylib</code>，放进 '
                         '<code>~/Library/Application Support/gegl-0.4/plug-ins</code>' % f)
        btns.append('<a class="btn ghost" href="%s/%s.dylib">%s %s.dylib'
                    '<span class="size">macOS arm64</span></a>'
                    % (MAC_RAW, f, "Download" if en else "下载", f))
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
    en = load_en(op)
    md, legacy_md = split_legacy_intro(md)
    if en:
        md = strip_en_sections(md)
        md = strip_en_blocks(md)
    # 去掉 README 自带的标题和「本文件是说明文档」的提示，页面头部自己给。
    # 这两样有时夹在当前说明前面（hsl-bands），所以按行清，不限定在文件头。
    md = re.sub(r"^>\s*本文件是该滤镜的(?:原始)?说明文档[^\n]*\n"
                r"(?:>\s*统一构建方式[^\n]*\n)?\s*", "", md, flags=re.M)
    md = re.sub(r"^#\s+GEGL_GIMP_PLUGIN_[^\n]*\n+", "", md, flags=re.M)
    md = re.sub(r"\A\s*#\s+[^\n]*\n+", "", md)
    md = re.sub(r"\A\s*!\[[^\]]*\]\([^)]*\)\s*\n+", "", md)
    # 「不推荐使用」的提示由模板在页头渲染，正文开头的同一条 blockquote 去掉，别重复
    md = re.sub(r"\A\s*>\s*\*\*不推荐[^\n]*\n(?:>[^\n]*\n)*\s*", "", md)

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
        badges = (off_badge(op, "临时停用", "Temporarily disabled", lang)
                  + warn_badge(op, lang) + wip_badge(op, lang)) \
            if (op["disabled"] or op["discouraged"] or op["wip"]) else ""
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
  %s%s%s
  <p class="lede">%s</p>
</section>""" % (eyebrow, html.escape(name), meta, wip_note(op, lang),
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
                math=True, body_class="article")


# --------------------------------------------------------------------------
# 博客：正文是长文，不放 README —— README 是算子参考，博客讲的是「为什么」
# 中文源在 tools/site/blog/<slug>.md，英文源在 tools/site/en/blog/<slug>.md，
# 两边同名，front matter 给 title / date / lede / tags。
# --------------------------------------------------------------------------

BLOG_DIR = os.path.join(SRC, "blog")
BLOG_EN_DIR = os.path.join(EN_DIR, "blog")


def _front_matter(path):
    txt = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    meta, body = {}, txt
    m = re.match(r"\A---\n(.*?)\n---\n", txt, re.S)
    if m:
        for line in m.group(1).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
        body = txt[m.end():]
    return meta, body.strip("\n")


def _read_minutes(md):
    """粗估阅读时间：中文按 420 字/分，英文单词按 220 词/分。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", md))
    words = len(re.findall(r"[A-Za-z][A-Za-z'-]+", md)) / 2.2
    return max(1, int(round(cjk / 420.0 + words / 220.0)))


def load_posts():
    posts = []
    if not os.path.isdir(BLOG_DIR):
        return posts
    for f in sorted(os.listdir(BLOG_DIR)):
        if not f.endswith(".md"):
            continue
        slug = f[:-3]
        zh, zh_md = _front_matter(os.path.join(BLOG_DIR, f))
        en_path = os.path.join(BLOG_EN_DIR, f)
        en, en_md = (_front_matter(en_path) if os.path.exists(en_path)
                     else ({}, ""))
        date = zh.get("date") or "2026-11-01"
        posts.append({
            "slug": slug,
            "date": date,
            "date_h": date.replace("-", "."),
            "title_zh": zh.get("title") or slug,
            "title_en": en.get("title") or zh.get("title") or slug,
            "lede_zh": zh.get("lede") or "",
            "lede_en": en.get("lede") or zh.get("lede") or "",
            "tags_zh": [s.strip() for s in (zh.get("tags") or "").split(",") if s.strip()],
            "tags_en": [s.strip() for s in (en.get("tags") or zh.get("tags") or "").split(",") if s.strip()],
            "md_zh": zh_md,
            "md_en": en_md,
            "min_zh": _read_minutes(zh_md),
            "min_en": _read_minutes(en_md or zh_md),
        })
    posts.sort(key=lambda p: (p["date"], p["slug"]), reverse=True)
    return posts


def _post_tags(post, lang):
    names = post["tags_en"] if lang == "en" else post["tags_zh"]
    return "".join('<span class="tag">%s</span>' % html.escape(s) for s in names)


def build_post(post, prev=None, nxt=None):
    zh_html, zh_toc = convert(post["md_zh"])
    en_html, en_toc = (convert(post["md_en"]) if post["md_en"] else ("", []))

    def toc_block(items, lang):
        if not items:
            return ""
        lis = "\n".join('<li class="l%d"><a href="#%s">%s</a></li>'
                        % (lv, anc, html.escape(tl)) for lv, anc, tl in items)
        return """<aside class="toc">
  <p class="toc-title">%s</p>
  <ul>%s</ul>
</aside>""" % ("On this page" if lang == "en" else "本页目录", lis)

    def pager(lang):
        en_ = lang == "en"
        back = ('<a class="prev" href="../blog.html"><span>%s</span>%s</a>'
                % ("All posts" if en_ else "全部文章",
                   "Back to the blog" if en_ else "回到博客列表"))
        links = [back]
        if nxt:
            links.append('<a class="next" href="%s.html"><span>%s</span>%s</a>'
                         % (nxt["slug"], "Newer" if en_ else "较新",
                            html.escape(nxt["title_en"] if en_ else nxt["title_zh"])))
        return '<nav class="pager">%s</nav>' % "".join(links)

    def head_block(lang):
        en_ = lang == "en"
        title = post["title_en"] if en_ else post["title_zh"]
        lede = post["lede_en"] if en_ else post["lede_zh"]
        meta = """<div class="meta">
    <span class="post-date"><time datetime="%s">%s</time></span>
    <span>%s</span>%s
  </div>""" % (post["date"], post["date_h"],
              ("%d min read" % post["min_en"]) if en_ else
              ("约 %d 分钟" % post["min_zh"]),
              _post_tags(post, lang))
        eyebrow = ('<a href="../index.html">Home</a> / <a href="../blog.html">Blog</a>'
                   if en_ else
                   '<a href="../index.html">首页</a> / <a href="../blog.html">博客</a>')
        return """<section class="page-head">
  <p class="eyebrow">%s</p>
  <h1>%s</h1>
  %s
  <p class="lede">%s</p>
</section>""" % (eyebrow, html.escape(title), meta, lede)

    def one_lang(lang):
        en_ = lang == "en"
        art = (en_html if en_ else zh_html) + pager(lang)
        return """%s<div class="article-layout">
  <article class="prose">
%s
  </article>
  %s
</div>""" % (head_block(lang), art, toc_block(en_toc if en_ else zh_toc, lang))

    body = ('<div class="l-zh">%s</div>\n<div class="l-en">%s</div>'
            % (one_lang("zh"), one_lang("en")))
    return page("%s · 博客" % post["title_zh"], body, root="../",
                desc=post["lede_zh"][:140], desc_en=post["lede_en"][:160],
                titles=("%s · gegl-color-ops 博客" % post["title_zh"],
                        "%s · gegl-color-ops blog" % post["title_en"]),
                math=True, body_class="article")


def build_blog(posts):
    rows = []
    for p in posts:
        rows.append("""  <article class="post-row">
    <div class="post-when">
      <time datetime="{date}">{date_h}</time>
      <span class="muted">{mins}</span>
    </div>
    <div class="post-body">
      <h2><a href="blog/{slug}.html">{title}</a></h2>
      <p class="lede">{lede}</p>
      <div class="post-tags"><span class="l-zh">{tags_zh}</span><span class="l-en">{tags_en}</span></div>
    </div>
  </article>""".format(date=p["date"], date_h=p["date_h"],
                       mins=t("约 %d 分钟" % p["min_zh"], "%d min read" % p["min_en"]),
                       slug=p["slug"],
                       title=t(html.escape(p["title_zh"]), html.escape(p["title_en"])),
                       lede=t(p["lede_zh"], p["lede_en"]),
                       tags_zh=_post_tags(p, "zh"), tags_en=_post_tags(p, "en")))

    hero = """<section class="hero blog-hero">
  <p class="eyebrow">NOTES</p>
  <h1><span class="l-zh">写代码的时候<br><span class="grad">顺手想明白的事</span></span><span class="l-en">The things we had to<br><span class="grad">work out properly</span></span></h1>
  <p class="lede"><span class="l-zh">算子页讲的是「参数是什么、误差多大」，这里讲「为什么最后这么写」：
     一个滤镜在目标软件里为什么让人别扭、公式在哪一步失真、哪一处看着能用其实一直在
     偷偷改画布。每篇都对着仓库里的实现和自检脚本写。</span><span class="l-en">The operator pages say what the parameters are and how large the error is.
     These posts are about why the code ended up the way it did: what makes a filter awkward
     in the reference editor, where the formula loses fidelity, and which part only looks
     correct while quietly moving the canvas. Each one is written against the implementation
     and the self-check scripts in the repository.</span></p>
  <p class="blog-meta"><span class="l-zh">共 %d 篇 · 中英双版</span><span class="l-en">%d posts, both languages</span></p>
</section>""" % (len(posts), len(posts))

    listing = """<section class="post-list">
%s
</section>""" % ("\n".join(rows) if rows else
                  '<p class="muted">%s</p>' % t("还没有文章。", "No posts yet."))

    return page("博客 · gegl-color-ops",
                hero + listing, desc="GEGL 算子背后的算法笔记：置换、锐化、杂色。",
                desc_en="Notes on the algorithms behind the operators: displacement, "
                        "sharpening, noise.",
                titles=("博客 · gegl-color-ops", "Blog · gegl-color-ops"))


def build_guide(version, stats):
    """安装与排错：整页双语。

    这页原来是纯中文硬编码，英文用户从下载页点「Install」会掉进一页中文。
    现在中英各一份正文，共用同一套 stats 数字。
    """
    n, l = stats["win_files"], stats["linux_files"]
    if stats["linux_missing"]:
        miss = len(stats["linux_missing"])
        lm_zh = ("component 家族那 %d 个模块（hsv / hsl / lab / lch / hsi 各自的 dual 与 "
                 "compose，再加 gray-to-component）还没出包，可以 <code>./build.sh</code> "
                 "自己编" % miss)
        lm_en = ("the %d modules of the component family (dual and compose for hsv / hsl / "
                 "lab / lch / hsi, plus gray-to-component) are not in the bundle yet — "
                 "build them with <code>./build.sh</code>" % miss)
    else:
        lm_zh = "与 Windows 一致"
        lm_en = "same as Windows"

    zh = """<section class="page-head">
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

  <h3>别忘了包里那个 <code>locale</code> 目录</h3>
  <p>下载包里除了模块，还有 <code>locale/zh_CN/LC_MESSAGES/gegl-color-ops.mo</code>——
     那就是中文语言包。解压时<b>连目录一起</b>放进 <code>gegl-0.4/plug-ins</code>，
     最终是 <code>plug-ins/locale/zh_CN/LC_MESSAGES/gegl-color-ops.mo</code>。
     漏了它不会报错：算子照常工作，只是菜单名和参数说明回落到英文。</p>
  <p>Python 插件包同理：GIMP 的插件目录里除了 <code>.py</code>，还要有
     <code>_shared/</code>（翻译取值模块）和 <code>locale/</code>（语言包），
     即 <code>plug-ins/_shared/lb_i18n.py</code> 与 <code>plug-ins/locale/</code>。</p>

  <h2 id="lang">界面语言</h2>
  <p>翻译跟着 <b>GIMP 的界面语言</b>走，不跟操作系统走：</p>
  <ul>
    <li><b>GIMP 3</b>：编辑 → 首选项 → 界面 → 语言，选「中文（简体）」，完全退出再打开。</li>
    <li>命令行验证：<code>LANG=en_US.UTF-8 gimp</code> 出英文、<code>LANG=zh_CN.UTF-8 gimp</code>
        出中文（Linux / macOS）；Windows 可以先 <code>set LANGUAGE=zh_CN</code> 再启动 GIMP。</li>
    <li>只想单独试一份语言包：<code>LB_LOCALEDIR=/path/to/locale gimp</code>。</li>
  </ul>
  <p>切完语言菜单名可能还停在旧语言：GIMP 把插件的菜单名缓存进 <code>pluginrc</code>，
     里面存的是<b>已经翻译好的字符串</b>，不带语言标记，所以切语言它不会自己失效。
     关掉 GIMP，删掉 <code>%APPDATA%\\GIMP\\3.x\\pluginrc</code>
     （Linux 是 <code>~/.config/GIMP/3.x/pluginrc</code>）再启动即可。
     算子那边不受影响——它们每次启动都重新取。</p>

  <h2 id="use">怎么用</h2>
  <p>菜单栏顶层多了 <code>SuperMrWang</code>（和「颜色」「图层」平级），算子按
     <b>Levels</b>（色阶家族）/ <b>Component</b>（dual + compose 与 gray-to-component）/
     <b>Tone</b> / <b>Color</b> / <b>Blend</b> / <b>Mask</b> 归组；Python 插件另占
     <b>Convert</b>（图层 → 选区 / 通道 / 拆分量）、<b>Mask</b>（Alpha Curves、Color Range）、
     <b>Blend</b>（应用图像、计算）、<b>Retouch</b>（五个分量曲线 + 三个磨皮）。
     图层右键菜单用同一套 Convert / Mask / Retouch，只列对单层能用的。
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
    <li><b>只看到一部分算子</b>：先数模块数——整包是 <b>47 个</b>。旧包只装 43 个，
        新加的锐化 / 杂色 / 置换就不在菜单里。重装一次整包，或源码目录里跑
        <code>./install.sh --no-build --verify</code>（装 <code>build/</code> 里现成的产物，
        再用 <code>gegl --info</code> 逐个确认注册）。</li>
    <li>位数/依赖：用 GIMP 自带的那份 GEGL 运行时，别混用系统里另一套 GEGL。</li>
    <li>用 <code>gegl --info lb:xxx</code> 单独验：命令行能看到、GIMP 看不到，通常是 GIMP 版本太旧。</li>
  </ul>
  <h3>同一个算子出现两次 / 报重复注册</h3>
  <p>插件目录里同时存在旧文件名的模块（早期是 12 个独立仓库，文件名不一样）。
     删掉旧名字的 <code>.dll</code> 即可，详见仓库 <code>README.md</code> 的「与旧布局的对应关系」。</p>
  <h3>打开旧图提示未知参数</h3>
  <p>算子升级时偶尔会删掉合并过的参数，旧 XCF 里存的值会丢。加载只警告、不报错，
     但要重新调一次。升级前建议先另存一份。</p>
  <h3>菜单和参数说明是英文的</h3>
  <ul>
    <li>语言包没放对：确认 <code>plug-ins/locale/zh_CN/LC_MESSAGES/gegl-color-ops.mo</code>
        在（算子和插件共用这一份）。</li>
    <li>GIMP 界面语言不是中文：翻译跟界面语言走，不是跟系统语言，见上面「界面语言」。</li>
    <li>插件菜单名没刷新：删掉 <code>pluginrc</code> 再启动，那里缓存了上一次的语言。</li>
  </ul>

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

  <h2 id="curves">曲线为什么全是「平滑」，而且不吃精度</h2>
  <p>插件里给你调的那几条曲线，一律是 GIMP 的 <b>SMOOTH</b>（平滑样条），控制点
     只有三到五个：<code>(0,0) (128,128) (255,255)</code> 这样的对角三点，或者
     提亮/压暗曲线的五个点。另一种写法 <b>FREE</b>「手绘」看着更自由，其实是把
     256 个采样点一个个塞进去：打开属性面板是一串密密麻麻的点，想动某一段得先在
     一堆点里找准是哪一个，手一拖整条线就歪。三个抓手没有这个问题。</p>
  <p>早先我以为「平滑必然要付精度代价」，实测下来这个结论是错的。<b>关键在于控制点
     落在哪</b>：曲线内部只认 0…255 的整数档，<code>x</code> 也一样。写
     <code>0.5</code> 表示 127.5/255，正好卡在两档中间，GIMP 会把它挪到某一侧，
     于是这条「对角直线」并不真的过对角——恒等状态下差半码，8 位图上还会把相邻两档
     并成一级（256 级只剩 217 级）。改成 <code>128/255</code>（踩在格点上）之后，
     恒等往返实测 <b>0.0002 码</b>、256 级一级不少，与铺满采样点的老写法完全一致。
     控制点仍然只有三个，照样拖得动。</p>
  <p>顺带解答一个常见的想法：<b>先铺 256 个采样点、再在面板里点「平滑」</b>行不行？
     行，结果也是 0 误差——因为 GIMP 转换时把控制点放在了 <code>32/255</code> 的
     格点上，等于它替你踩了格子。但它把 256 个点重新拟合成 <b>9 个</b>控制点，原来的
     采样表被丢掉，而且这一步不可逆：手绘时留的硬拐角会被磨圆，想找回原样只能重画。
     我们直接生成踩格点的三个点，省掉这一步，也不丢任何东西。</p>
  <p>两类曲线分得很清：给人调的走平滑样条；机器自己用的<b>编码表</b>（比如把
     L* 0–100 铺满灰阶、把色相 0–360° 缩进 0–255）仍然是采样点——它的形状是算
     出来的，不是画出来的，也不需要抓手。</p>
  <p>实测对照（同一张图、同样的恒等曲线，旧写法 FREE 256 点 vs 现写法 SMOOTH 三点）：</p>
  <div class="table-wrap"><table>
    <thead><tr><th>插件</th><th>FREE 256 点</th><th>SMOOTH 三点（踩格点）</th><th>8 位</th></tr></thead>
    <tbody>
      <tr><td>HSV</td><td>0.00015 码</td><td>0.00015 码</td><td>0.49 码</td></tr>
      <tr><td>HSL</td><td>0.00012 码</td><td>0.00012 码</td><td>0.49 码</td></tr>
      <tr><td>Lab</td><td>0.00243 码</td><td>0.00243 码</td><td>0.49 码</td></tr>
      <tr><td>LCh</td><td>0.00049 码</td><td>0.00049 码</td><td>0.49 码</td></tr>
      <tr><td>HSI</td><td>0.00014 码</td><td>0.00014 码</td><td>0.50 码</td></tr>
    </tbody>
  </table></div>
  <p>两列数字一模一样。8 位的 0.49 码是量化本身，跟曲线无关。</p>

  <h2 id="faq">常见问题</h2>
  <h3>和经典图像编辑器的调整图层结果一致吗？</h3>
  <p>多数算子的目标是「肉眼与 8 位输出一致」。实测残差写在每篇算法说明里，
     通常是中位 0–4 码；有明确对不上的段落时也会说明（例如 经典图像编辑器 在个别对角线上的硬裁切）。</p>
  <h3>为什么叫 <code>lb:</code> 前缀？</h3>
  <p>GEGL 的 id 必须唯一。前缀避免和 GIMP 自带算子撞名——撞了会静默加载失败，
     所以这个工程里所有 id 和 GType 名都带前缀。</p>
  <h3>会进 GIMP 官方仓库吗？</h3>
  <p>不会。这是独立的第三方算子集，按 GPL-3.0 发布，自己装进用户插件目录即可。</p>
</article>""".format(repo=REPO, n=n, l=l, lm=lm_zh)

    en = """<section class="page-head">
  <p class="eyebrow"><a href="index.html">Home</a> / Install</p>
  <h1>Install &amp; troubleshooting</h1>
  <p class="lede">No installer, no registry: drop the module files into GEGL's plug-in
     directory and restart GIMP. That is the whole procedure.</p>
</section>
<article class="prose wide">
  <h2 id="req">Requirements</h2>
  <ul>
    <li><b>GIMP 3.x</b> (tested on 3.0 and 3.2), which ships GEGL 0.4.</li>
    <li>Prebuilt <code>.dll</code> for Windows x64, <code>.so</code> for Linux x86_64.
        The Windows bundle has <b>all {n} modules</b>; the Linux bundle currently has
        {l} — {lm}.</li>
    <li>No Python runtime needed: the operators are GEGL modules compiled from C.</li>
  </ul>

  <h2 id="install">Installing</h2>
  <p>Unpack the archive and copy every module file (<code>.dll</code> / <code>.so</code>)
     into the user plug-in directory (create it if it does not exist):</p>
  <div class="table-wrap"><table>
    <thead><tr><th>System</th><th>Directory</th></tr></thead>
    <tbody>
      <tr><td>Windows</td><td><code>%LOCALAPPDATA%\\gegl-0.4\\plug-ins</code></td></tr>
      <tr><td>Linux</td><td><code>~/.local/share/gegl-0.4/plug-ins</code></td></tr>
      <tr><td>macOS</td><td><code>~/Library/Application Support/gegl-0.4/plug-ins</code></td></tr>
    </tbody>
  </table></div>
  <p>Then <b>quit GIMP completely and start it again</b> (closing the window is not
     enough). Directories are scanned once, at startup.</p>
  <p>To confirm the modules loaded, ask GEGL from a terminal:</p>
  <pre><code>gegl --info lb:hsl-levels</code></pre>
  <p>If it prints the property list, the operator is registered. GIMP's own
     <code>gegl</code> lives in the <code>bin/</code> folder of its install directory —
     on Windows usually <code>C:\\Program Files\\GIMP 3\\bin\\gegl.exe</code>.</p>

  <h3>Do not leave the <code>locale</code> folder behind</h3>
  <p>Besides the modules, the archive contains
     <code>locale/zh_CN/LC_MESSAGES/gegl-color-ops.mo</code> — the Chinese catalogue.
     Keep the directory when unpacking, so it ends up as
     <code>plug-ins/locale/zh_CN/LC_MESSAGES/gegl-color-ops.mo</code>. Nothing breaks
     if you drop it: the operators still work, the menu names and parameter blurbs just
     fall back to English.</p>
  <p>Same for the Python plug-in archives: next to the <code>.py</code> files GIMP's
     plug-in folder needs <code>_shared/</code> (the lookup helper) and
     <code>locale/</code> (the catalogue), i.e. <code>plug-ins/_shared/lb_i18n.py</code>
     and <code>plug-ins/locale/</code>.</p>

  <h2 id="lang">Interface language</h2>
  <p>The translation follows <b>GIMP's interface language</b>, not the operating
     system:</p>
  <ul>
    <li><b>GIMP 3</b>: Edit → Preferences → Interface → Language, pick Chinese
        (Simplified), quit completely and start again.</li>
    <li>From a terminal: <code>LANG=en_US.UTF-8 gimp</code> gives English and
        <code>LANG=zh_CN.UTF-8 gimp</code> Chinese (Linux / macOS). On Windows run
        <code>set LANGUAGE=zh_CN</code> before starting GIMP.</li>
    <li>To point at one specific catalogue directory:
        <code>LB_LOCALEDIR=/path/to/locale gimp</code>.</li>
  </ul>
  <p>Menu labels may stay in the old language after switching: GIMP caches plug-in menu
     names in <code>pluginrc</code> as <b>already-translated strings</b> with no language
     tag, so a language change does not invalidate them. Quit GIMP, delete
     <code>%APPDATA%\\GIMP\\3.x\\pluginrc</code> (Linux:
     <code>~/.config/GIMP/3.x/pluginrc</code>) and start it again. Operators are not
     affected — they resolve their strings on every start.</p>

  <h2 id="use">Using it</h2>
  <p>A top-level <code>SuperMrWang</code> menu appears next to Colors and Layers.
     Operators are grouped as <b>Levels</b> (the levels family), <b>Component</b>
     (dual + compose plus gray-to-component), <b>Tone</b>, <b>Color</b>, <b>Blend</b>
     and <b>Mask</b>; the Python plug-ins take <b>Convert</b> (layer → selection /
     channel, or one split into R/G/B/A), <b>Mask</b> (Alpha Curves, Color Range), <b>Blend</b> (Apply Image,
     Calculations) and <b>Retouch</b> (five component curves plus three retouching
     tools). The layer context menu uses the same Convert / Mask / Retouch split and
     only lists what works on a single layer. You can also type an operator name into
     the action search (<code>/</code>).</p>
  <p>Almost every operator is a <b>Point</b> or <b>Filter</b> op, so GIMP attaches it to
     the layer as a non-destructive fx — parameters stay editable and the pixels are not
     touched. The two-input operators (Apply Image and Calculations) can only be applied
     destructively for now.</p>

  <h2 id="build">Building from source (optional)</h2>
  <p>You need GIMP 3's GEGL development headers and gcc (MSYS2's mingw64 toolchain is
     enough on Windows):</p>
  <pre><code>git clone {repo}.git
cd gegl-color-ops
./build.sh              # output lands in build/
./install.sh --verify   # also copies everything into place and checks each op</code></pre>
  <p>Linux and macOS can use meson instead:</p>
  <pre><code>export PKG_CONFIG_PATH="/path/to/gimp/lib/pkgconfig"
meson setup build-meson &amp;&amp; ninja -C build-meson</code></pre>

  <h2 id="trouble">Troubleshooting</h2>
  <h3>Nothing shows up in the menu</h3>
  <ul>
    <li>Check the path: it must be <code>gegl-0.4/plug-ins</code>, not GIMP's own
        <code>plug-ins</code>.</li>
    <li>Did you restart? The scan happens at startup, so copying files in while GIMP
        runs does nothing.</li>
    <li>Architecture and dependencies: use the GEGL runtime that ships with GIMP, not a
        second GEGL from the system.</li>
    <li>Verify with <code>gegl --info lb:xxx</code>: visible on the command line but
        missing inside GIMP usually means the GIMP version is too old.</li>
  </ul>
  <h3>The same operator appears twice / duplicate registration errors</h3>
  <p>An old module with a different file name is still in the plug-in directory (early
     on these were 12 separate repositories with unrelated names). Delete the old
     <code>.dll</code>; the mapping is listed in the repository's <code>README.md</code>
     under "relationship to the old layout".</p>
  <h3>Opening an old image warns about unknown properties</h3>
  <p>Upgrades occasionally remove properties that were merged into others, and the values
     stored in old XCFs are then dropped. Loading only warns, never fails, but you have to
     set those parameters again. Save a copy before upgrading.</p>
  <h3>Menus and parameter blurbs are in English</h3>
  <ul>
    <li>The catalogue is not where it should be: check that
        <code>plug-ins/locale/zh_CN/LC_MESSAGES/gegl-color-ops.mo</code> exists (operators
        and plug-ins share that one file).</li>
    <li>GIMP's interface language is not Chinese: the translation follows the interface
        language, not the system locale — see "Interface language" above.</li>
    <li>Plug-in menu labels were not refreshed: delete <code>pluginrc</code> and start
        GIMP again, it still holds the previous language.</li>
  </ul>

  <h2 id="code">What a "code" is</h2>
  <p>The operator and plug-in pages keep quoting figures like "identity round trip 0.0002
     codes" or "residual 0.30 codes". <b>One code is one step on an 8-bit image</b>: 0–255
     is 256 levels, so the gap between neighbours is 1 code, or <b>1/255 ≈ 0.392%</b>.
     "0.0002 codes" therefore means the encoded result differs from the source by at most
     0.0002 of a step — RGB 128 comes back as 128.0002.</p>
  <p>Why that yardstick: floating-point error on its own says nothing (whether 1e-7 is
     good depends on bit depth and how many operations ran). Expressed as "how many 8-bit
     levels would this change", every colour space and bit depth becomes comparable, and
     the number lines up with what the eye can resolve.</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Value</th><th>What it means</th></tr></thead>
    <tbody>
      <tr><td><b>0.0002 codes</b></td><td>1/5000 of a step — a clean float round trip</td></tr>
      <tr><td><b>0.0053 codes</b></td><td>1/190 of a step — the scale after several encode passes, still invisible</td></tr>
      <tr><td><b>0.49 codes</b></td><td>the floor set by 8-bit quantisation; no 8-bit output escapes it</td></tr>
      <tr><td><b>1 code</b></td><td>barely visible, and only side by side</td></tr>
      <tr><td><b>3–4 codes</b></td><td>visible; banding may show on gradients</td></tr>
      <tr><td><b>8 codes and up</b></td><td>an obvious colour or brightness shift</td></tr>
    </tbody>
  </table></div>
  <p><b>It measures whether the output changed, not whether an eye would notice.</b> The
     figure is the maximum absolute difference in sRGB encoded values (R′G′B′) — the worst
     pixel, the worst channel, never an average. The encoding space is not perceptually
     uniform: one code in the shadows is more visible than one code in the highlights, so
     "how different does it look" has to be computed as ΔE in Lab. Codes are the
     engineering criterion; ΔE is the perceptual one.</p>
  <p>Worth adding: a difference below 0.5 codes cannot land on a different pixel in an
     8-bit image (rounding swallows it). It only shows up in float working images, or after
     stacking dozens of similar operations. That is why the plug-in pages quote both a
     32-bit float and an 8-bit number.</p>

  <h2 id="curves">Why the curves are all SMOOTH, and why that costs no precision</h2>
  <p>Every curve handed to you in the plug-ins is GIMP's <b>SMOOTH</b> spline with three to
     five control points: a diagonal of <code>(0,0) (128,128) (255,255)</code>, or the five
     points of a dodge/burn curve. The other form, <b>FREE</b> "hand-drawn", looks more
     flexible but is really 256 sample points pushed in one at a time: the property panel
     becomes a wall of dots, editing one segment means finding the right dot first, and one
     slip drags the whole line. Three handles do not have that problem.</p>
  <p>I used to assume "smoothing must cost precision". Measured, that is wrong. <b>What
     matters is where the control points sit</b>: the curve only knows integer levels
     0…255, and so does <code>x</code>. Writing <code>0.5</code> means 127.5/255, exactly
     between two levels; GIMP nudges it to one side, so the "diagonal" does not actually
     pass through the diagonal — the identity is half a code off, and in 8-bit two adjacent
     levels collapse into one (256 levels become 217). Put the point on
     <code>128/255</code> (on the grid) and the identity round trip measures <b>0.0002
     codes</b> with all 256 levels intact — identical to the old fully-sampled form, with
     three handles instead of 256 dots.</p>
  <p>And a common idea: <b>lay down 256 sample points, then hit "smooth" in the panel</b>?
     That works too, also with zero error — GIMP places the converted control points on the
     <code>32/255</code> grid for you. But it refits those 256 points into <b>9</b> control
     points and throws the original table away, irreversibly: hard corners you drew get
     rounded, and the only way back is to redraw. Generating the three on-grid points
     directly skips that step and loses nothing.</p>
  <p>The two kinds of curve are kept strictly apart: anything a person drags is a smooth
     spline; the <b>encoding tables</b> the machine uses for itself (L* 0–100 across the
     greyscale, hue 0–360° squeezed into 0–255) stay sampled — their shape is computed, not
     drawn, and they need no handles.</p>
  <p>Measured side by side (same image, same identity curve, old FREE 256 points vs the
     current SMOOTH three points):</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Plug-in</th><th>FREE, 256 points</th><th>SMOOTH, 3 points on grid</th><th>8-bit</th></tr></thead>
    <tbody>
      <tr><td>HSV</td><td>0.00015 codes</td><td>0.00015 codes</td><td>0.49 codes</td></tr>
      <tr><td>HSL</td><td>0.00012 codes</td><td>0.00012 codes</td><td>0.49 codes</td></tr>
      <tr><td>Lab</td><td>0.00243 codes</td><td>0.00243 codes</td><td>0.49 codes</td></tr>
      <tr><td>LCh</td><td>0.00049 codes</td><td>0.00049 codes</td><td>0.49 codes</td></tr>
      <tr><td>HSI</td><td>0.00014 codes</td><td>0.00014 codes</td><td>0.50 codes</td></tr>
    </tbody>
  </table></div>
  <p>The two columns are identical. The 0.49 codes in the 8-bit column is quantisation
     itself, unrelated to the curve.</p>

  <h2 id="faq">FAQ</h2>
  <h3>Do the results match the classic editor's adjustment layers?</h3>
  <p>Most operators aim for "the same 8-bit output, to the eye". The measured residual is
     quoted in every algorithm page, usually 0–4 codes at the median; where something
     genuinely differs, the page says so (for example the classic editor's hard clipping on
     a few diagonals).</p>
  <h3>Why the <code>lb:</code> prefix?</h3>
  <p>GEGL ids have to be unique. The prefix avoids colliding with GIMP's own operators —
     a collision fails silently at load time — so every id and GType name in this project
     carries it.</p>
  <h3>Will this go into GIMP's official repository?</h3>
  <p>No. It is an independent third-party operator set, released under GPL-3.0, installed
     into your own user plug-in directory.</p>
</article>""".format(repo=REPO, n=n, l=l, lm=lm_en)

    body = '<div class="l-zh">%s</div>\n<div class="l-en">%s</div>' % (zh, en)
    return page("安装与排错 · gegl-color-ops", body,
                desc="GIMP 3 GEGL 算子安装、验证与排错",
                titles=("安装与排错 · gegl-color-ops",
                        "Install & troubleshooting · gegl-color-ops"),
                desc_en="Installing, verifying and troubleshooting the GEGL operators "
                        "for GIMP 3.")


# 每个 Python 插件：一个 .py 加上它内部依赖的算子模块。清单放在模块级，
# 是因为主页的「插件整包」也要用它，不能再抄一遍。
# sky-replace 源码保留但带 .disabled，暂不发布。
PLUGIN_SPECS = [
        dict(key="selection", ops=[],
             name="gegl-color-ops-plugin-layer-to-selection.zip",
             src_dir=os.path.join(ROOT, "plugin", "layer-to-selection"),
             py="layer-to-selection.py", menu="Layer to Selection",
             menus="    图层右键 → SuperMrWang → Convert → Layer to Selection\n"
                   "    SuperMrWang → Convert → Layer to Selection",
             desc="Layer to Selection：右键任意图层，把它转成当前选区"
                  "（Gray/R/G/B/Alpha、四种组合方式、可反相）。",
             pdb="lb-plugin-layer-to-selection(image, layer, channel, invert, operation)"),
        dict(key="channel", ops=[],
             name="gegl-color-ops-plugin-layer-to-channel.zip",
             src_dir=os.path.join(ROOT, "plugin", "layer-to-channel"),
             py="layer-to-channel.py", menu="Layer to Channel",
             menus="    图层右键 → SuperMrWang → Convert → Layer to Channel\n"
                   "    SuperMrWang → Convert → Layer to Channel",
             desc="Layer to Channel：右键任意图层，把它变成一条新的 Alpha 通道"
                  "（恒为灰度：彩色图层先按亮度转灰度，再把灰度值写进通道）。",
             pdb="lb-plugin-layer-to-channel(image, layer, invert, name)"),
        dict(key="split", ops=[],
             name="gegl-color-ops-plugin-split-channels.zip",
             src_dir=os.path.join(ROOT, "plugin", "split-channels"),
             py="split-channels.py", menu="Split Channels",
             menus="    图层右键 → SuperMrWang → Convert → Split Channels\n"
                   "    SuperMrWang → Convert → Split Channels",
             desc="Split Channels：右键任意图层，一次拆出 R / G / B / Alpha 四条"
                  "通道（灰度图只出 Gray），原图层自动隐藏留作对照，通道恒为画布"
                  "大小、偏移图层界外补黑。",
             pdb="lb-plugin-split-channels(image, layer, include-alpha, hide-source, prefix)"),
        dict(key="hsv", ops=["hsv-dual", "hsv-compose"],
             name="gegl-color-ops-plugin-hsv-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "hsv-split-curves"),
             py="hsv-split-curves.py", menu="HSV Split (Curves)",
             menus="    SuperMrWang → Retouch → HSV Split (Curves) · single\n"
                   "    SuperMrWang → Retouch → HSV Split (Curves) · multi\n"
                   "    图层右键 → SuperMrWang → Retouch → 同上两条",
             desc="HSV Split (Curves)：在 HSV 空间里调曲线。一张数据图同时携带"
                  "S、V、H（红=S、绿=V、蓝=H/360），三条曲线各管一个分量，再由"
                  "lb:hsv-compose 一起算回颜色。恒等曲线时逐像素还原原图。",
             pdb="lb-plugin-hsv-split-curves(image, drawables, group)\n"
                 "lb-plugin-hsv-split-curves-multi(image, drawables, group)"),
        dict(key="lch", ops=["lch-dual", "lch-compose"],
             name="gegl-color-ops-plugin-lch-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "lch-split-curves"),
             py="lch-split-curves.py", menu="LCh Split (Curves)",
             menus="    SuperMrWang → Retouch → LCh Split (Curves) · single\n"
                   "    SuperMrWang → Retouch → LCh Split (Curves) · multi\n"
                   "    图层右键 → SuperMrWang → Retouch → 同上两条",
             desc="LCh Split (Curves)：在 CIE LCh 里调曲线。一张数据图同时携带"
                  "L*、C*、h（红=L/100、绿=C/140、蓝=h/360），三条曲线各管一个"
                  "分量。极坐标，所以调彩度不动色相、调色相不动彩度。",
             pdb="lb-plugin-lch-split-curves(image, drawables, group)\n"
                 "lb-plugin-lch-split-curves-multi(image, drawables, group)"),
        dict(key="hsl", ops=["hsl-dual", "hsl-compose"],
             name="gegl-color-ops-plugin-hsl-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "hsl-split-curves"),
             py="hsl-split-curves.py", menu="HSL Split (Curves)",
             menus="    SuperMrWang → Retouch → HSL Split (Curves) · single\n"
                   "    SuperMrWang → Retouch → HSL Split (Curves) · multi\n"
                   "    图层右键 → SuperMrWang → Retouch → 同上两条",
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
             menus="    SuperMrWang → Retouch → Lab Split (Curves) · single\n"
                   "    SuperMrWang → Retouch → Lab Split (Curves) · multi\n"
                   "    图层右键 → SuperMrWang → Retouch → 同上两条",
             desc="Lab Split (Curves)：在 CIE Lab 空间里调曲线。一张数据图同时携带"
                  "a、b、L*（红=a、绿=b、蓝=L*/100），三条曲线各管一个分量，再由"
                  "lb:lab-compose 一起算回颜色。恒等曲线时逐像素还原原图。",
             pdb="lb-plugin-lab-split-curves(image, drawables, group)\n"
                 "lb-plugin-lab-split-curves-multi(image, drawables, group)"),
        dict(key="hsi", ops=["hsi-dual", "hsi-compose"],
             name="gegl-color-ops-plugin-hsi-split-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "hsi-split-curves"),
             py="hsi-split-curves.py", menu="HSI Split (Curves)",
             menus="    SuperMrWang → Retouch → HSI Split (Curves) · single\n"
                   "    图层右键 → SuperMrWang → Retouch → HSI Split (Curves)",
             desc="HSI Split (Curves)：在 HSI 空间里调曲线。HSI 的 I 是 (R+G+B)/3，"
                  "GIMP 的六条分量模式一条也对不上；插件用 lb:hsi-dual / "
                  "lb:hsi-compose 把 S、I、色相挤进一张数据图（红=S、绿=I、蓝=H/360），"
                  "三条曲线各管一个分量。恒等曲线时精确还原。",
             pdb="lb-plugin-hsi-split-curves(image, drawables, group)"),
        dict(key="frequency", ops=[],
             name="gegl-color-ops-plugin-frequency-separation.zip",
             src_dir=os.path.join(ROOT, "plugin", "frequency-separation"),
             py="frequency-separation.py", menu="高低频磨皮 (Frequency Separation)",
             menus="    SuperMrWang → Retouch → 高低频磨皮\n"
                   "    图层右键 → SuperMrWang → Retouch → 高低频磨皮",
             desc="高低频磨皮：一次生成低频（高斯模糊，管影调与颜色）与高频"
                  "（颗粒合并 + 高通，管细节与质感）两层，恒等时合成就是原图。"
                  "在低频层抹平色块、在高频层修细节，互不干扰。",
             pdb="lb-plugin-frequency-separation(image, drawables, radius, group)"),
        dict(key="dodge", ops=[],
             name="gegl-color-ops-plugin-dodge-burn.zip",
             src_dir=os.path.join(ROOT, "plugin", "dodge-burn"),
             py="dodge-burn.py", menu="双曲线磨皮 (Dodge & Burn)",
             menus="    SuperMrWang → Retouch → 双曲线磨皮\n"
                   "    图层右键 → SuperMrWang → Retouch → 双曲线磨皮",
             desc="双曲线磨皮：生成提亮、压暗两条曲线层，蒙版全黑。用白色柔边"
                  "画笔在蒙版上涂抹，涂到哪里就提亮/压暗到哪里，没涂的地方与"
                  "原图逐像素相同。",
             pdb="lb-plugin-dodge-burn(image, drawables, amount, group)"),
        dict(key="grey", ops=[],
             name="gegl-color-ops-plugin-neutral-grey.zip",
             src_dir=os.path.join(ROOT, "plugin", "neutral-grey"),
             py="neutral-grey.py", menu="中性灰磨皮 (Neutral Grey)",
             menus="    SuperMrWang → Retouch → 中性灰磨皮\n"
                   "    图层右键 → SuperMrWang → Retouch → 中性灰磨皮",
             desc="中性灰磨皮：加一张 50% 灰的柔光层，恒等时与原图逐像素相同。"
                  "白色画笔提亮、黑色画笔压暗，反复涂抹把皮肤推平。",
             pdb="lb-plugin-neutral-grey(image, drawables, group)"),
        dict(key="ai-frequency", ops=[],
             name="gegl-color-ops-plugin-ai-frequency-separation.zip",
             src_dir=os.path.join(ROOT, "plugin", "ai-frequency-separation"),
             py="ai-frequency-separation.py",
             menu="高低频磨皮（AI 预修）(Frequency Separation, AI prep)",
             menus="    SuperMrWang → Retouch → 高低频磨皮（AI 预修）\n"
                   "    图层右键 → SuperMrWang → Retouch → 高低频磨皮（AI 预修）",
             desc="高低频磨皮（AI 预修）：结构和原版一样，但两层的内容是一张已经"
                  "修过一遍的参考图（ComfyUI 低重绘，或本地降采样低通），合成结果"
                  "就是那张参考图——打开文件时色块已铺平、痘印已淡掉。",
             shared=["retouch_prep.py", "retouch_math.py", "ai_client.py",
                     "prompt_tools.py"],
             pdb="lb-plugin-ai-frequency-separation(image, drawables, prompt, source, "
                 "radius, denoise, server, checkpoint, steps, group)"),
        dict(key="ai-dodge", ops=[],
             name="gegl-color-ops-plugin-ai-dodge-burn.zip",
             src_dir=os.path.join(ROOT, "plugin", "ai-dodge-burn"),
             py="ai-dodge-burn.py",
             menu="双曲线磨皮（AI 预修）(Dodge & Burn, AI prep)",
             menus="    SuperMrWang → Retouch → 双曲线磨皮（AI 预修）\n"
                   "    图层右键 → SuperMrWang → Retouch → 双曲线磨皮（AI 预修）",
             desc="双曲线磨皮（AI 预修）：提亮 / 压暗两条曲线的蒙版按「参考图与原图"
                  "的亮度差」预先涂好七成，浓度按每个像素自己的亮度反算。打开就能"
                  "接着补几笔。",
             shared=["retouch_prep.py", "retouch_math.py", "ai_client.py",
                     "prompt_tools.py"],
             pdb="lb-plugin-ai-dodge-burn(image, drawables, prompt, source, amount, "
                 "prepaint, radius, denoise, server, checkpoint, steps, group)"),
        dict(key="ai-grey", ops=[],
             name="gegl-color-ops-plugin-ai-neutral-grey.zip",
             src_dir=os.path.join(ROOT, "plugin", "ai-neutral-grey"),
             py="ai-neutral-grey.py",
             menu="中性灰磨皮（AI 预修）(Neutral Grey, AI prep)",
             menus="    SuperMrWang → Retouch → 中性灰磨皮（AI 预修）\n"
                   "    图层右键 → SuperMrWang → Retouch → 中性灰磨皮（AI 预修）",
             desc="中性灰磨皮（AI 预修）：那张 50% 灰的柔光层不再是平的 128——按参考图"
                  "反解出每个像素该有的灰度，已做一轮中性灰。白笔继续提亮、黑笔压暗、"
                  "#808080 擦回去。",
             shared=["retouch_prep.py", "retouch_math.py", "ai_client.py",
                     "prompt_tools.py"],
             pdb="lb-plugin-ai-neutral-grey(image, drawables, prompt, source, prepaint, "
                 "radius, denoise, server, checkpoint, steps, group)"),
        dict(key="alpha-curves", ops=["channel-range-to-alpha"],
             name="gegl-color-ops-plugin-alpha-curves.zip",
             src_dir=os.path.join(ROOT, "plugin", "alpha-curves"),
             py="alpha-curves.py", menu="Alpha Curves（透明通道曲线）",
             menus="    SuperMrWang → Mask → Alpha Curves\n"
                   "    图层右键 → SuperMrWang → Retouch → Alpha Curves",
             desc="Alpha Curves：先把选定颜色通道写进 alpha，再接一条可以随便"
                  "画的曲线（gimp:curves，通道 = Alpha）。两条都是非破坏滤镜，"
                  "梯形、S 形、任意起伏都行。",
             pdb="lb-plugin-alpha-curves(image, drawables, channel, shape)"),
        dict(key="color-range", ops=["color-mask-select"],
             name="gegl-color-ops-plugin-color-range.zip",
             src_dir=os.path.join(ROOT, "plugin", "color-range"),
             py="color-range.py", menu="Color Range（色彩范围）",
             menus="    SuperMrWang → Mask → Color Range\n"
                   "    图层右键 → SuperMrWang → Color Range",
             desc="Color Range：色彩范围的定制对话框。选哪种颜色就只显示那种颜色"
                  "的参数，高光 192 / 阴影 64 / 中间调 64–192 各自归位；"
                  "红色叠加实时预览，确定后蒙版写进 alpha。",
             pdb="lb-plugin-color-range(image, drawables)"),
        dict(key="channel-to-mask", ops=[],
             name="gegl-color-ops-plugin-channel-to-mask.zip",
             src_dir=os.path.join(ROOT, "plugin", "channel-to-mask"),
             py="channel-to-mask.py", menu="Channel to Mask（通道转图层蒙版）",
             menus="    SuperMrWang → Mask → Channel to Mask...\n"
                   "    图层右键 → SuperMrWang → Mask → Channel to Mask...",
             desc="Channel to Mask：把通道面板里选中的那条通道，挂成所选图层的"
                  "图层蒙版。多选图层一次挂齐，可反相；已有蒙版则覆盖内容，"
                  "再跑一次就是刷新。与 Layer to Channel 互为反向操作。",
             pdb="lb-plugin-channel-to-mask(image, drawables, channel-name, invert)"),
        dict(key="convert", ops=[],
             name="gegl-color-ops-plugin-convert.zip",
             src_dir=os.path.join(ROOT, "plugin", "convert"),
             py="convert.py", menu="Convert（通道 / 选区 / 蒙版 / 路径 十二向转换）",
             menus="    SuperMrWang → Convert → 十二项，通道 / 选区 / 蒙版 / 路径两两互转\n"
                   "    图层右键 / 通道右键 / 路径右键 → SuperMrWang → Convert",
             desc="Convert：通道、选区、蒙版、路径四者两两互转，十二个方向各一个菜单项，"
                  "零参数、点一下直接执行。源全从上下文取：通道 / 路径面板选中那条、"
                  "当前选区、当前图层的蒙版。原生缺的「蒙版 → 通道」「通道 / 蒙版 ↔ 路径」"
                  "也补成一步；路径只管几何，位图进路径按 50% 等值线取轮廓。",
             pdb="lb-plugin-conv-* 十二个过程，全部零参数"),
        dict(key="max-min", ops=["max-min"],
             name="gegl-color-ops-plugin-max-min.zip",
             src_dir=os.path.join(ROOT, "plugin", "max-min"),
             py="max-min.py", menu="最大值 / 最小值（Maximum / Minimum）",
             menus="    SuperMrWang → Mask → 最大值 / 最小值\n"
                   "    图层右键 → SuperMrWang → Mask → 最大值 / 最小值",
             desc="最大 / 最小值：形态学的膨胀与腐蚀，Photoshop「最大值 / 最小值」"
                  "滤镜的等价物。最大值扩边、去暗点；最小值收边、去亮点。"
                  "半径 1–100、方形或圆盘可选，alpha 默认不动。图层上是非破坏滤镜，"
                  "蒙版和通道直接写像素。",
             pdb="lb-plugin-max-min(image, drawables, mode, radius, shape, affect-alpha)"),
]


def build_plugin_zips(out_dir):
    """每个 Python 插件打一个包，与 dll/so 的免编译包同一套路。"""
    specs = PLUGIN_SPECS
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

包里有三样东西，要分两个目录放——少一样插件就跑不起来：

  1) {py}  →  GIMP 的插件目录
        Windows:  %APPDATA%\\GIMP\\3.x\\plug-ins\\
        Linux:    ~/.config/GIMP/3.x/plug-ins/
        macOS:    ~/Library/Application Support/GIMP/3.x/plug-ins/

  2) modules-windows-x64 里的 .dll{lin_hint}
     →  GEGL 的模块目录（注意不是上面那个）
        Windows:  %LOCALAPPDATA%\\gegl-0.4\\plug-ins
        Linux:    ~/.local/share/gegl-0.4/plug-ins
        macOS:    ~/Library/Application Support/gegl-0.4/plug-ins

  3) _shared\\ 和 locale\\  →  跟着 {py} 放同一个插件目录，不要丢
        Windows:  %APPDATA%\\GIMP\\3.x\\plug-ins\\_shared\\
                  %APPDATA%\\GIMP\\3.x\\plug-ins\\locale\\
        Linux:    ~/.config/GIMP/3.x/plug-ins/_shared/
                  ~/.config/GIMP/3.x/plug-ins/locale/
        macOS:    ~/Library/Application Support/GIMP/3.x/plug-ins/_shared/

     _shared\\lb_i18n.py 是翻译的取值模块，locale\\ 下是中文语言包。少这两个
     插件仍能跑，但界面文案只能是英文——插件的 import 会失败并静默回退。
     {py} 放子目录也行（plug-ins\\{stem}\\{py}），只要 _shared\\ 和 locale\\
     还在 plug-ins\\ 这一层。

  三处都放好之后，完全退出 GIMP 再打开（不是关窗口）。这些目录都只在启动时扫描。

  这个包还带了插件自己要 import 的共享模块（一起放进 plug-ins\\_shared\\）：
{shared_list}

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
           stem=os.path.splitext(sp["py"])[0],
           shared_list="\n".join("    _shared/" + f for f in ["lb_i18n.py"] +
                                  (sp.get("shared") or [])),
           lin_hint=lin_hint)
        else:
            readme = """gegl-color-ops · {py}（GIMP 3 Python 插件）
=====================================================

{desc}

安装：把这个 .py 放进 GIMP 的用户插件目录（目录不存在就新建）：
    Windows:  %APPDATA%\\GIMP\\3.x\\plug-ins\\
    Linux:    ~/.config/GIMP/3.x/plug-ins/
    macOS:    ~/Library/Application Support/GIMP/3.x/plug-ins/

这个插件不需要任何额外的算子模块，但**翻译要跟着走**：把包里的 _shared\\
和 locale\\ 也放进同一个插件目录（成为 plug-ins\\_shared\\、plug-ins\\locale\\）。
少了它们插件照常能跑，只是界面文案回落到英文。

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
            # 这几支插件除了 lb_i18n，还要 retouch_prep / ai_client 这些共享模块；
            # 不一起打进去，用户解压出来点菜单只会得到一个 ImportError
            for shared_py in (sp.get("shared") or []):
                _zip_add_file(z, os.path.join(ROOT, "plugin", "_shared", shared_py),
                              "_shared/" + shared_py)
            for f in win_dll:
                _zip_add_file(z, os.path.join(win_src, f),
                              "modules-windows-x64/" + f)
            for f in lin_so:
                _zip_add_file(z, os.path.join(lin_src, f),
                              "modules-linux-x64/" + f)
            _zip_add_i18n(z, "")
            _zip_add_text(z, "安装说明.txt", readme)
        zips[sp["key"]] = {"name": sp["name"], "sha": _sha256_file(path),
                           "kb": round(os.path.getsize(path) / 1024, 1),
                           "win_mods": win_dll, "lin_mods": lin_so,
                           "absent": absent}
    return zips


def build_plugin_bundle(out_dir):
    """插件整包：全部 .py 一次装齐，外加它们内部依赖的模块，每个平台一个。
    .py 是纯 Python、跨平台通用，所以各包里的 plugins/ 完全一样，只有
    modules-* 目录不同。macOS 那份要等 dist/macos-arm64/ 里有 .dylib 才出——
    那目录由另一台 Apple Silicon 机器推 dist/mac 分支，没合进来就整个跳过。"""
    need = sorted({m for sp in PLUGIN_SPECS for m in (sp.get("ops") or [])})
    ext_of = {"windows-x64": "dll", "linux-x64": "so", "macos-arm64": "dylib"}
    src_of = {plat: os.path.join(ROOT, "dist", plat) for plat in ext_of}
    mods_of = {
        plat: [m + "." + ext for m in need
               if os.path.exists(os.path.join(src_of[plat], m + "." + ext))]
        for plat, ext in ext_of.items()
    }
    # macOS 还没合进来就丢掉整个条目，别在下载页挂一个 0 模块的空包
    if not mods_of["macos-arm64"]:
        del mods_of["macos-arm64"]
        del src_of["macos-arm64"]
    absent_of = {plat: [m for m in need if m + "." + ext_of[plat] not in mods]
                 for plat, mods in mods_of.items()}

    out = {}
    for plat, mods in mods_of.items():
        miss = absent_of[plat]
        miss_note = ""
        if miss and plat == "linux-x64":
            miss_note = (
                "\n注意：%d 个分量模块（各色空间的 dual / compose）还没进预编译包，\n"
                "这个包里不含：\n    %s\n"
                "受影响的是五个 * Split (Curves) 插件；其余插件在 Linux 上开箱可用。\n"
                "要用它们，在源码目录跑 ./build.sh 自己编一份（Windows 端是齐的）。\n"
                % (len(miss), "、".join(miss)))
        elif miss:
            miss_note = (
                "\n注意：本机 dist/macos-arm64/ 里还缺 %d 个分量模块，这个包里不含：\n"
                "    %s\n五个 * Split (Curves) 插件需要它们，其余插件不受影响。\n"
                % (len(miss), "、".join(miss)))
        if plat == "windows-x64":
            gimp_dir = "%APPDATA%\\GIMP\\3.x\\plug-ins\\"
            gegl_dir = "%LOCALAPPDATA%\\gegl-0.4\\plug-ins"
        elif plat == "macos-arm64":
            # macOS 的 GIMP 3 用 Application Support；GEGL 的模块目录也是同一层
            gimp_dir = "~/Library/Application Support/GIMP/3.x/plug-ins/"
            gegl_dir = "~/Library/Application Support/gegl-0.4/plug-ins"
        else:
            gimp_dir = "~/.config/GIMP/3.x/plug-ins/"
            gegl_dir = "~/.local/share/gegl-0.4/plug-ins"
        readme = """gegl-color-ops · Python 插件整包（{plat}）
=================================================

{py_n} 个 GIMP 3 Python 插件，加上它们内部依赖的 {mod_n} 个算子模块，
一次装齐，不用一个一个下。

两条路、两个目录——少放一边，插件会报「找不到过程」：

  1) plugins/ 里的**全部内容**  →  GIMP 的用户插件目录
        {gimp_dir}
     不只是 .py：_shared/ 和 locale/ 也要一起放进去
     （最终成为 plug-ins\\_shared\\lb_i18n.py 与 plug-ins\\locale\\zh_CN\\…）。
     _shared 是翻译取值模块，locale 是中文语言包；少了它们插件照常跑，
     但界面文案只能是英文。

  2) modules-{plat}/ 里的模块  →  GEGL 的模块目录（注意不是上面那个）
        {gegl_dir}

放好之后完全退出 GIMP 再打开（关窗口不算）。两个目录都只在启动时扫描。

菜单位置：菜单栏顶层的 SuperMrWang（和「颜色」「图层」平级）
    SuperMrWang → Retouch   五个分量曲线 + 高低频 / 双曲线 / 中性灰磨皮
    SuperMrWang → Mask       Alpha Curves
    SuperMrWang → Convert    Layer to Selection / Layer to Channel / Split Channels
    图层右键 → SuperMrWang   同上全部
{miss_note}
插件清单：
{listing}

源码与算法说明：{repo}

GPL-3.0-or-later
""".format(plat=plat, py_n=len(PLUGIN_SPECS), mod_n=len(mods),
           gimp_dir=gimp_dir, gegl_dir=gegl_dir, miss_note=miss_note,
           listing="\n".join("    %-28s %s" % (sp["py"], sp["menu"])
                             for sp in PLUGIN_SPECS),
           repo=REPO)
        name = "gegl-color-ops-plugins-%s.zip" % plat
        path = os.path.join(out_dir, name)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for sp in PLUGIN_SPECS:
                _zip_add_file(z, os.path.join(sp["src_dir"], sp["py"]),
                              "plugins/" + sp["py"])
            for f in mods:
                _zip_add_file(z, os.path.join(src_of[plat], f),
                              "modules-%s/%s" % (plat, f))
            _zip_add_i18n(z, "plugins/")
            # 插件要 import 的共享模块：整包里也必须有，否则「装了整包、点菜单
            # 报 ImportError」——AI 磨皮这三支就靠 retouch_prep / ai_client
            for shared_py in sorted({f for sp in PLUGIN_SPECS
                                     for f in (sp.get("shared") or [])}):
                _zip_add_file(z, os.path.join(ROOT, "plugin", "_shared", shared_py),
                              "plugins/_shared/" + shared_py)
            _zip_add_text(z, "安装说明.txt", readme)
        out[plat] = {"name": name, "sha": _sha256_file(path),
                     "mb": round(os.path.getsize(path) / (1024 * 1024), 1),
                     "mods": len(mods), "py": len(PLUGIN_SPECS),
                     "absent": miss}
    return out


def build_plugins(version, stats=None):
    """插件总览：和算子页同一套「分组标题 + 表格」，只放入口不写正文。

    早先是卡片方格，但插件页和算子页是同一类东西——都是「有哪些、各干什么」的
    清单，一个用表格一个用方格，来回切换时读法都要重新适应。统一成 op-table：
    菜单名 / PDB 过程 / 类型 / 一句话，点名字进详情页。
    """
    def row(p):
        # p["pdb"] 是多行签名（含参数），表格里只放过程名
        pdb_name = p["pdb"].split("(")[0].strip()
        return ('<tr><td><a href="plugins/%s.html"><b>%s</b></a></td>'
                '<td><code>%s</code></td><td class="nowrap">%s</td><td>%s</td></tr>'
                % (p["slug"],
                   t(html.escape(p["title"]),
                     html.escape(p.get("title_en") or p["title"])),
                   html.escape(pdb_name),
                   t(html.escape(p["tag"][0]),
                     html.escape(p.get("tag_en") or p["tag"][0])),
                   t(p["brief"], p.get("brief_en") or p["brief"])))

    def group(key, tag, cls, desc, members, tag_en=None, desc_en=None):
        rows = "\n".join(row(p) for p in members)
        return """<h2 id="g-{key}" class="plug-group"><span class="tag {cls}">{tag}</span>
    <span class="count">{n}</span></h2>
  <p class="group-desc">{desc}</p>
  <div class="table-wrap"><table class="op-table plug-table">
    <thead><tr><th>{th1}</th><th>PDB</th><th>{th3}</th><th>{th4}</th></tr></thead>
    <tbody>
    {rows}
    </tbody>
  </table></div>""".format(key=key, tag=t(tag, tag_en or key.capitalize()), cls=cls,
                             n=t("%d 个" % len(members), str(len(members))),
                             desc=t(desc, desc_en or desc),
                             th1=t("插件", "Plug-in"),
                             th3=t("类型", "Type"),
                             th4=t("做什么", "What it does"),
                             rows=rows)

    shortcut = [p for p in PD.PAGES if p["area"].startswith("Retouch")]
    convert = [p for p in PD.PAGES if p["area"] == "图层转换"]
    mask = [p for p in PD.PAGES if p["area"] == "Mask"]

    n_plug = len(PD.PAGES)
    body = """<section class="page-head">
  <p class="eyebrow"><a href="index.html">{home}</a> / {plugs}</p>
  <h1>{h1}</h1>
  <p class="lede">{lede}</p>
  <ul class="facts">
    <li>{f1}</li>
    <li>{f2}</li>
    <li>{f3}</li>
    <li>{f4}</li>
  </ul>
</section>

<div class="prose wide">
{shortcut}
{convert}
{mask}
  <p class="note">{note}</p>
</div>""".format(
        home=t("首页", "Home"), plugs=t("Python 插件", "Python plug-ins"),
        h1=t("%d 个 Python 插件" % n_plug, "%d Python plug-ins" % n_plug),
        lede=t("免编译的 GIMP 3 插件，装进 <code>plug-ins</code> 目录、重启即用。"
               "两处入口：菜单栏顶层的 <b>SuperMrWang</b>（全部都在），以及"
               "<b>图层右键 → SuperMrWang</b>。",
               "Compile-free GIMP 3 plug-ins: drop them into the <code>plug-ins</code> "
               "folder and restart. Two entry points: the top-level <b>SuperMrWang</b> "
               "menu (all of them) and <b>layer right-click → SuperMrWang</b>."),
        f1=t("<b>%d</b> 个插件" % n_plug, "<b>%d</b> plug-ins" % n_plug),
        f2=t("<b>%d</b> 个 PDB 过程" % n_plug, "<b>%d</b> PDB procedures" % n_plug),
        f3=t("<b>503</b> 条回归断言", "<b>503</b> regression assertions"),
        f4=t("<b>0</b> 编译 · 纯 Python", "<b>0</b> to compile · pure Python"),
        note=t("安装：<code>bash install-plugin.sh</code> 一次装齐，或从各自的页面"
               "单独下某一个 <code>.zip</code>；细节见 "
               "<a href=\"guide.html\">安装指南</a>。",
               "Install: <code>bash install-plugin.sh</code> puts them all in place, "
               "or download a single <code>.zip</code> from its own page — details in "
               "the <a href=\"guide.html\">install guide</a>."),
        shortcut=group("shortcut", "Retouch", "t-color",
                       "五条分量曲线、三个磨皮：把一串手工步骤压成一次点击。",
                       shortcut, tag_en="Retouch",
                       desc_en="Five component-curve plug-ins and three retouching "
                               "ones: a chain of manual steps collapsed into one click."),
        convert=group("convert", "图层转换", "t-mask",
                      "算子跑完留下的灰度图，一步变成蒙版或选区存档。", convert,
                      tag_en="Convert",
                      desc_en="Turns the greyscale an operator leaves behind into a "
                              "mask or a saved selection in one step."),
        mask=group("mask", "Mask", "t-mask",
                   "透明度本身当曲线来画：按通道生成 alpha，形状随便画。", mask,
                   tag_en="Mask",
                   desc_en="Alpha as a curve: generate coverage per channel, then "
                           "shape it freely.")
        if mask else "")

    return page("Python 插件 · gegl-color-ops", body,
                desc="GIMP 3 Python 插件：图层转选区 / Alpha 通道，"
                     "HSV / LCh / HSL / Lab / HSI 分量分层曲线，"
                     "高低频 / 双曲线 / 中性灰磨皮——免编译，解压即用",
                titles=("Python 插件 · gegl-color-ops", "Python plug-ins · gegl-color-ops"),
                desc_en="%d compile-free GIMP 3 plug-ins: layer to selection or "
                        "channel, HSV / LCh / HSL / Lab / HSI component curves, "
                        "frequency separation, dodge & burn, neutral grey." % n_plug)


# 有几个插件的全部价值在于「把原生操作收成一次点击」，不新增任何像素算法。
# 这些页面顶上要明说，免得读者以为里面藏着别的东西。
NATIVE_NOTE_ZH = """<p class="native-note"><b>只是原生方式的便捷实现</b>　这里没有新算法：
   像素结果全部出自 GIMP 自带的 PDB 过程，插件只负责把散在三处菜单、要跨三四步的动作
   收成一次点击，并保证与手点原生菜单得到的结果逐位相同。</p>"""
NATIVE_NOTE_EN = """<p class="native-note"><b>Only a convenience wrapper over native behaviour</b> —
   no new algorithms here: every pixel comes out of GIMP's own PDB procedures. The plug-in just
   folds a detour that lives in three different menus and takes three or four steps into a
   single click, and keeps the result bit-for-bit identical to doing it by hand.</p>"""


def _mark_plugin_sections(markup, lang):
    """给插件正文的每个 .dl 小节补锚点，并抽出标题给右侧目录。

    插件正文是手写的 HTML 片段，一个 .dl 就是一小节。与其逐页改标记，
    不如在拼页时统一加 id、顺便取出 h3 的纯文本。
    """
    items = []
    pat = re.compile(
        r'<div class="dl(?: primary-dl)?">(\s*<div class="dl-head"><h3>(.*?)</h3>)',
        re.S)

    def repl(m):
        sid = "%s-sec-%d" % (lang, len(items) + 1)
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        items.append((sid, title))
        return '<div class="dl" id="%s">%s' % (sid, m.group(1))

    return pat.sub(repl, markup), items


def build_plugin_article(p, version, stats=None, prev=None, nxt=None):
    """每个插件一篇文章：页头 + 位置/PDB/依赖 + 正文 + 下载 + 翻页。

    十一个插件共用一套骨架，差异全在 plugin_docs.py 里。图层转换那两个不在
    Retouch 菜单下，所以菜单块直接读 p["menus"]，不写死。
    """
    z = ((stats or {}).get("plugin_zips") or {}).get(p["key"])
    name = p["menu"].split("→")[-1].strip()
    name_en = p.get("title_en") or p["title"]

    def one_lang(lang):
        en_ = lang == "en"
        dn = (p.get("deps_note_en") if en_ else "") or p["deps_note"]
        if p["deps"]:
            dep_html = ('<p>%s</p>\n      <ul class="deps">%s</ul>'
                        % (dn, "".join("<li><code>%s</code></li>" % d for d in p["deps"])))
        else:
            dep_html = '<p>%s</p>' % dn

        menus = p["menus"]
        if en_:
            if p.get("menus_en"):
                # 有英文原文就直接用，别拿中文去替换（中文插件名替换不干净）
                menus = p["menus_en"]
            else:
                # 菜单条目里夹着中文：入口名、中文插件名、"同上两条"
                # 「通道右键 / 路径右键」是另外两个入口，图层转换那几条会用到
                menus = [m.replace("图层右键", "Layer right-click")
                          .replace("通道右键", "Channel right-click")
                          .replace("路径右键", "Path right-click")
                          .replace("同上两条", "same as the two above")
                          .replace("十二项，按目标命名", "twelve items, named by target")
                          .replace("十二项", "twelve items")
                          .replace("最大值 / 最小值", "Maximum / Minimum")
                          .replace(p["title"], p.get("title_en") or p["title"])
                         for m in menus]
        menu_html = "".join("<li>%s</li>" % m for m in menus)

        dl = ""
        if z:
            mods = z.get("win_mods") or []
            absent = z.get("absent") or []
            if mods:
                if en_:
                    pill = "%d modules included · no compile" % len(mods)
                    note = ("The archive holds one <code>.py</code>, %d operator modules, "
                            "an install note, plus <code>_shared/</code> and "
                            "<code>locale/</code>. <b>The operator dependencies are already "
                            "inside, nothing else to download.</b> The <code>.py</code> goes "
                            "into GIMP's <code>plug-ins</code>, the modules into GEGL's "
                            "<code>gegl-0.4/plug-ins</code> — two different directories, and "
                            "the note inside walks through both. Keep <code>_shared/</code> "
                            "and <code>locale/</code> next to the <code>.py</code> or the "
                            "menu labels stay English." % len(mods))
                else:
                    pill = "含 %d 个模块 · 免编译" % len(mods)
                    note = ("包里有一个 <code>.py</code>、%d 个算子模块和一份安装说明，"
                            "外加 <code>_shared/</code> 与 <code>locale/</code>。"
                            "<b>算子依赖已经附在里面，不用另外去下。</b>"
                            "<code>.py</code> 进 GIMP 的 <code>plug-ins</code>，模块进 GEGL 的 "
                            "<code>gegl-0.4/plug-ins</code>——两个目录不一样，包内说明分步写了。"
                            "<code>_shared/</code> 和 <code>locale/</code> 要跟 <code>.py</code> "
                            "放同一处，否则菜单文案只能是英文。"
                            % len(mods))
            else:
                if en_:
                    pill = ".py · no compile"
                    note = ("The archive holds a single <code>.py</code>, an install note and "
                            "the <code>_shared/</code> + <code>locale/</code> pair. Unpack all "
                            "of it into GIMP's <code>plug-ins</code> directory (Windows "
                            "<code>%%APPDATA%%\\GIMP\\3.x\\plug-ins</code>, Linux "
                            "<code>~/.config/GIMP/3.x/plug-ins</code>) and <b>restart GIMP</b> "
                            "for it to register. Without <code>_shared/</code> and "
                            "<code>locale/</code> it still runs, but only in English.")
                else:
                    pill = ".py · 免编译"
                    note = ("包里是一个 <code>.py</code>、一份安装说明，以及 "
                            "<code>_shared/</code> 与 <code>locale/</code>。整包解压到 GIMP 的 "
                            "<code>plug-ins</code> 目录（Windows "
                            "<code>%%APPDATA%%\\GIMP\\3.x\\plug-ins</code>，Linux "
                            "<code>~/.config/GIMP/3.x/plug-ins</code>），<b>重启 GIMP</b> 才注册。"
                            "少了 <code>_shared/</code> 和 <code>locale/</code> 也能跑，"
                            "但界面只有英文。")
            if absent:
                if en_:
                    note += (" The Linux side of %s is not in the prebuilt bundle yet; if you "
                             "need Linux, build it with <code>./build.sh</code> (Windows is "
                             "complete)." % ", ".join(absent))
                else:
                    note += (" Linux 端的 %s 还没进预编译包，要用 Linux 就 "
                             "<code>./build.sh</code> 自己编一份（Windows 端齐全）。"
                             % "、".join(absent))
            dl = """<section class="download" id="%s-download">
  <h2>%s</h2>
  <div class="dl primary-dl">
    <div class="dl-head"><h3>%s</h3><span class="pill">%s</span></div>
    <p>%s</p>
    <a class="btn primary" href="../download/%s">%s %s</a>
    <p class="muted small">%s KB · %s<code>SHA256 %s…</code></p>
  </div>
</section>""" % (lang, "Download this one" if en_ else "下载这一个",
                name_en if en_ else name, pill, note, z["name"],
                "Download" if en_ else "下载", name_en if en_ else name,
                z["kb"], "checksum: " if en_ else "校验：", z["sha"][:32])

        def pager_link(q, label, cls):
            if not q:
                return ""
            return ('<a class="%s" href="%s.html"><span>%s</span>%s</a>'
                    % (cls, q["slug"], label,
                       q.get("title_en") or q["title"] if en_ else q["title"]))

        pager = """<nav class="pager">
  <a href="../plugins.html"><span>%s</span>%s</a>
  %s%s
</nav>""" % ("Back to" if en_ else "回到",
             "All plug-ins" if en_ else "Python 插件总览",
             pager_link(prev, "Previous" if en_ else "上一篇", "prev"),
             pager_link(nxt, "Next" if en_ else "下一篇", "next"))

        note_code = ("""<p class="note">In this article a "code" means one step on an 8-bit
   image: 0–255 is 256 levels, so the gap between neighbours is 1 code, or
   1/255 ≈ 0.392%% (the difference between RGB 128 and 129). For the order of magnitude
   of each figure, and why a code is not a perceptual quantity, see
   <a href="../guide.html#code">Install guide · what a code is</a>.</p>"""
                     if en_ else
                     """<p class="note">文中「码」指 8 位图上的一个台阶：0–255 共 256 级，
   相邻两级的差就是 1 码，等于 1/255 ≈ 0.392%%（也就是 RGB 128 与 129 之间的差）。
   各数量级的含义与「码为什么不是感知量」的说明见
   <a href="../guide.html#code">安装指南 · 精度里的「码」</a>。</p>""")

        native = NATIVE_NOTE_EN + "\n" if en_ else NATIVE_NOTE_ZH + "\n"
        if not p.get("native_only"):
            native = ""

        spec = """<dl class="spec" id="%s-overview">
  <dt>%s</dt>
  <dd><ul class="menu-list">%s</ul><p>%s</p></dd>
  <dt>%s</dt>
  <dd><code class="pdb">%s</code><p>%s</p></dd>
  <dt>%s</dt>
  <dd>%s</dd>
</dl>""" % (lang,
           "Menu location" if en_ else "菜单位置", menu_html,
           ("These are all the same action, applied to <b>the one layer you have "
            "selected</b>. Layer groups do not work — a group has no pixels of its own, "
            "so the plug-in stops with an explicit error and asks you to merge first."
            if en_ else
            "这几条是同一个动作，处理的是<b>当前选中的那一个图层</b>。图层组不行——"
            "组没有自己的像素，会直接报错并提示先合并。"),
           "Scripting" if en_ else "脚本调用", p["pdb"],
           "A standard PDB procedure; leave an argument empty to take its default."
           if en_ else "标准 PDB 过程，参数留空走默认值。",
           "Dependencies" if en_ else "依赖", dep_html)

        arts, secs = _mark_plugin_sections(
            spec + "\n" + ((p.get("body_en") or p["body"]) if en_ else p["body"]), lang)
        toc_li = "".join('<li><a href="#%s">%s</a></li>' % (i, html.escape(t))
                         for i, t in secs)

        return """<section class="page-head">
  <p class="eyebrow"><a href="../index.html">%s</a> /
    <a href="../plugins.html">%s</a> / %s</p>
  <h1>%s</h1>
  <div class="meta">
    <code>plugin/%s</code>
    <span class="tag %s">%s</span>
    <span>%s</span>
  </div>
  <p class="lede">%s</p>
</section>
%s<div class="article-layout">
  <article class="prose">
%s

%s

%s
  </article>
  <aside class="toc">
    <p class="toc-title">%s</p>
    <ul>
      <li><a href="#%s-overview">%s</a></li>
%s
      <li><a href="#%s-download">%s</a></li>
    </ul>
  </aside>
</div>""" % ("Home" if en_ else "首页",
             "Plug-ins" if en_ else "插件",
             (p.get("area_en") if en_ else p["area"]),
             html.escape(name_en if en_ else p["title"]),
             p["slug"], p["tag"][1],
             p.get("tag_en") if en_ else p["tag"][0],
             p.get("area_en") if en_ else p["area"],
             (p.get("lede_en") or p["lede"]) if en_ else p["lede"],
             native, arts, dl, note_code,
             "On this page" if en_ else "本页目录",
             lang, "Overview" if en_ else "概览", toc_li,
             lang, "Download" if en_ else "下载") + "\n" + pager

    body = ('<div class="l-zh">%s</div>\n<div class="l-en">%s</div>'
            % (one_lang("zh"), one_lang("en")))
    return page("%s · Python 插件 · gegl-color-ops" % p["title"], body, root="../",
                desc=re.sub(r"<[^>]+>", "", p["lede"])[:120],
                titles=("%s · Python 插件 · gegl-color-ops" % p["title"],
                        "%s · Python plug-ins · gegl-color-ops" % p["title"]),
                desc_en=re.sub(r"<[^>]+>", "", p.get("lede_en") or p["lede"])[:120])


def build_feed(ops, version, posts=None):
    """一个极简 Atom，方便订阅「最近加了什么」：博客长文 + 算子 + Retouch 八个插件。

    Retouch 那八条链到站点里的文章页（插件没有 README 可链），日期用加进来的
    那天，排在新加算子之后。博客排在最前，日期用各自的发布日期。
    """
    entries = []
    for p in (posts or [])[:6]:
        entries.append("""  <entry>
    <title>{title}</title>
    <link href="{site}/blog/{slug}.html"/>
    <id>tag:github.com,2026:post-{slug}</id>
    <updated>{date}T00:00:00Z</updated>
    <summary>{sum}</summary>
  </entry>""".format(title=html.escape("博客 · " + p["title_zh"]),
                     site=SITE, slug=p["slug"], date=p["date"],
                     sum=html.escape(p["lede_zh"][:200])))
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
    newest = posts[0]["date"] if posts else "2026-11-19"
    return """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>gegl-color-ops · 博客、算子与插件</title>
  <link href="{site}/"/>
  <updated>{newest}T00:00:00Z</updated>
  <id>tag:github.com,2026:gegl-color-ops</id>
{entries}
</feed>""".format(site=SITE, newest=newest, entries="\n".join(entries))


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
    # macOS：另一台机器推到 dist/mac 分支，合并进来后 dist/ 里才有，缺了不影响构建
    mac = os.path.join(DIST, "macos-arm64")
    dylibs = sorted(f for f in os.listdir(mac) if f.endswith(".dylib")) \
        if os.path.isdir(mac) else []
    return {"win_files": len(dlls), "dlls": dlls, "win_dir": win,
            "linux_files": len(sos), "sos": sos, "linux_dir": lin,
            "linux_missing": missing,
            "mac_files": len(dylibs), "dylibs": dylibs, "mac_dir": mac}


# 打包用固定时间戳：同一批文件重复打包应当得到同一个 zip，
# 否则每次重建 docs/ 都会因为 mtime 变化刷出一堆二进制改动。
ZIP_EPOCH = (2020, 1, 1, 0, 0, 0)



def _zip_add_i18n(z, prefix):
    """插件包必须带上翻译：插件里的 _() 来自 plugin/_shared/lb_i18n.py，
    少了它 import 就失败，整个插件不加载；.mo 缺了只是回落英文。"""
    src = os.path.join(ROOT, "plugin", "_shared", "lb_i18n.py")
    if os.path.exists(src):
        _zip_add_file(z, src, prefix + "_shared/lb_i18n.py")
    loc = os.path.join(ROOT, "locale")
    for lang in sorted(os.listdir(loc)) if os.path.isdir(loc) else []:
        mo = os.path.join(loc, lang, "LC_MESSAGES", "gegl-color-ops.mo")
        if os.path.exists(mo):
            _zip_add_file(z, mo, "%slocale/%s/LC_MESSAGES/gegl-color-ops.mo"
                          % (prefix, lang))

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
        # 算子名与参数说明走 gettext，翻译目录要和 .dll/.so 放在一起
        loc = os.path.join(ROOT, "locale")
        for lang in sorted(os.listdir(loc)) if os.path.isdir(loc) else []:
            mo = os.path.join(loc, lang, "LC_MESSAGES", "gegl-color-ops.mo")
            if os.path.exists(mo):
                _zip_add_file(z, mo, "locale/%s/LC_MESSAGES/gegl-color-ops.mo" % lang)
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

locale 目录也要一并放进去（放成 ...\\gegl-0.4\\plug-ins\\locale\\zh_CN\\LC_MESSAGES\\）：
不放的话算子名和参数说明全是英文——不是坏了，是找不到翻译就回落英文。

然后完全退出 GIMP 再打开。菜单位置：
    菜单栏顶层的 SuperMrWang（和「颜色」「图层」平级）

验证是否加载成功（gegl.exe 在 GIMP 安装目录的 bin 下，不在 PATH 里就用全路径）：
    gegl --info lb:hsl-levels

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

把这些 .so 全部放进（locale 目录一并放进去，算子名与参数说明才会显示中文）：
    ~/.local/share/gegl-0.4/plug-ins

（等价于 ./install.sh 在 Linux 下的默认目标目录。装到系统目录的话是
 /usr/lib/x86_64-linux-gnu/gegl-0.4，需要 sudo。）

然后完全退出 GIMP 再打开。菜单位置：
    菜单栏顶层的 SuperMrWang（和「颜色」「图层」平级）

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

    if stats["dylibs"]:
        mac_readme = """gegl-color-ops · macOS arm64 免编译包（Apple Silicon）
====================================================

把这些 .dylib 全部放进：
    ~/Library/Application Support/gegl-0.4/plug-ins

（Homebrew 装的 GIMP 用同一个目录；Intel Mac 不适用，这一包是 arm64 的。）

然后完全退出 GIMP 再打开。菜单位置：
    菜单栏顶层的 SuperMrWang（和「颜色」「图层」平级）

验证是否加载成功：
    gegl --info lb:hsl-levels

共 {n} 个模块，针对 libgegl-0.4 编译（GEGL 0.4.60+ 在 macOS 只认 .dylib）。
列表见同目录 manifest.csv，校验和见 SHA256SUMS.txt。
源码与算法说明：{repo}

GPL-3.0-or-later
""".format(n=len(stats["dylibs"]), repo=REPO)
        mname = "gegl-color-ops-macos-arm64.zip"
        mpath, msha, msize = _zip_one(out_dir, mname, stats["dylibs"],
                                      stats["mac_dir"], mac_readme)
        stats.update(zip_mac_name=mname, zip_mac_sha=msha, zip_mac_mb=msize)

    return path


def main():
    serve = "--serve" in sys.argv
    # --no-clean：不删 docs 直接覆盖。预览面板开着 docs 里的页面时，Windows
    # 上整个目录删不掉（trash 操作会被中止），这时用它重建。代价是已下线的
    # 页面会留在原地，收尾记得核对 git status 里有没有多余文件。
    no_clean = "--no-clean" in sys.argv
    stats = collect_stats()
    ops = load_ops()
    posts = load_posts()
    version = sh("git", "rev-parse", "--short", "HEAD") or "local"

    if os.path.isdir(DOCS) and not no_clean:
        try:
            shutil.rmtree(DOCS)
        except OSError as exc:
            # Windows 上删整个目录偶尔会被中止（有句柄的杀软、预览进程都会导致），
            # 与其整个构建崩掉，不如原地覆盖：新页面照写，下线的页面留在原地。
            print("· 清空 docs 失败（%s），改为原地覆盖；收尾请核对 git status 里"
                  "有没有已下线页面残留" % exc)
            no_clean = True
    os.makedirs(os.path.join(DOCS, "ops"), exist_ok=True)
    os.makedirs(os.path.join(DOCS, "assets"), exist_ok=True)
    os.makedirs(os.path.join(DOCS, "download"), exist_ok=True)

    build_zip(stats, os.path.join(DOCS, "download"))
    stats["plugin_zips"] = build_plugin_zips(os.path.join(DOCS, "download"))
    stats["plugin_bundle"] = build_plugin_bundle(os.path.join(DOCS, "download"))

    # 样式与静态资源（tools/site/en 是英文正文的源文件目录，不是要拷的资源）
    for f in os.listdir(SRC):
        if os.path.isfile(os.path.join(SRC, f)):
            shutil.copy2(os.path.join(SRC, f), os.path.join(DOCS, "assets", f))

    # 每个算子：文章页 + 截图
    for op in ops:
        if os.path.isdir(op["assets"]):
            dst = os.path.join(DOCS, "assets", "ops", op["dir"])
            shutil.copytree(op["assets"], dst, dirs_exist_ok=True)

    with open(os.path.join(DOCS, ".nojekyll"), "w"):
        pass

    globals()["VERSION"] = version

    pages = {
        "index.html": build_home(ops, stats, version, posts),
        "overview.html": build_overview(ops, stats, version),
        "ops.html": build_ops_index(ops, version),
        "plugins.html": build_plugins(version, stats),
        "blog.html": build_blog(posts),
        "guide.html": build_guide(version, stats),
        "feed.xml": build_feed(ops, version, posts),
    }
    for op in ops:
        pages["ops/%s.html" % op["dir"]] = build_article(op, version)

    # 博客长文：列表按日期倒序，翻页按同一顺序（较新 / 较旧）
    for i, post in enumerate(posts):
        pages["blog/%s.html" % post["slug"]] = build_post(
            post,
            nxt=posts[i - 1] if i else None,
            prev=posts[i + 1] if i + 1 < len(posts) else None)

    # Retouch 里每个组件一篇独立文章；翻页在八篇里循环。
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
    print("· docs/ 已生成：%d 个总览页、%d 篇算子文章、%d 篇博客，%d 个资源文件，"
          "共 %.1f MB（含下载包 %.1f MB）"
          % (7, len(ops), len(posts),
             sum(len(fs) for _, _, fs in os.walk(os.path.join(DOCS, "assets"))),
             total / 1048576, stats["zip_mb"]))
    print("· 分类：" + " / ".join("%s %d" % (GROUP_ZH[g][1],
                                            sum(1 for o in ops if o["group"] == g))
                                  for g in SMG.GROUPS))
    print("· 下载包：docs/download/%s（%d 个模块）" % (stats["zip_name"], stats["win_files"]))
    if stats.get("zip_linux_name"):
        print("           docs/download/%s（%d 个模块）"
              % (stats["zip_linux_name"], stats["linux_files"]))
    if stats.get("zip_mac_name"):
        print("           docs/download/%s（%d 个模块）"
              % (stats["zip_mac_name"], stats["mac_files"]))
    for d in (stats.get("plugin_zips") or {}).values():
        print("           docs/download/%s（GIMP 3 Python 插件）" % d["name"])
    for plat, d in (stats.get("plugin_bundle") or {}).items():
        print("           docs/download/%s（插件整包 %d 个 .py + %d 个模块）"
              % (d["name"], d["py"], d["mods"]))

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
