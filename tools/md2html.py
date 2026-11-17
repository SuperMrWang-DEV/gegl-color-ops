# -*- coding: utf-8 -*-
"""把工程里的 README 转成 HTML 片段，给 docs/ 站点用。

只覆盖仓库里实际用到的语法：标题、段落、GFM 表格、围栏代码块、有序/无序
列表（含两级缩进）、引用、分隔线、行内代码、粗斜体、删除线、图片、链接、
裸 URL。不追求 CommonMark 全兼容 —— 装 markdown 库要联网，这台机器 pip
取不到源，仓库也一直保持「工具只用标准库」的习惯。

    from md2html import convert
    html, toc = convert(text, image_prefix="../assets/ops/x/")

`toc` 是 [(level, anchor, 标题文本)]，给右侧目录用。

公式与流程图（页面靠 KaTeX / mermaid 渲染，转换器只负责把原文原样放进
占位元素）：

- `$...$` 行内公式、`$$...$$` 独立成段的显示公式 → `.math` / `.math-display`；
- ` ```math ` 围栏 → `.math-display`（适合写多行的推导）；
- ` ```mermaid ` 围栏 → `<pre class="mermaid">`，由 mermaid 渲染成图。
  公式原文只做 HTML 转义，不进任何 markdown 行内规则 —— 否则 `*` `_` 会把
  LaTeX 搅碎。
"""

import html as _html
import re

# ---- 行内 -----------------------------------------------------------------

_PLACE = "\x00%d\x00"          # 行内元素的占位符，最后一步统一还原


def _esc(t):
    return _html.escape(t, quote=False)


def _slug(title, used):
    """锚点：ASCII 转小写连字符；中日韩直接保留（URL 里会被百分号编码，
    浏览器和 static server 都认）。重名加序号。"""
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "", title).strip().lower()
    s = re.sub(r"[\s_]+", "-", s) or "sec"
    base, n = s, 2
    while s in used:
        s = "%s-%d" % (base, n)
        n += 1
    used.add(s)
    return s


def _inline(text, link_base=None, image_prefix=None):
    store = []

    def keep(fragment):
        store.append(fragment)
        return _PLACE % (len(store) - 1)

    # 1. 行内代码先摘出来，里面的 * _ [ ] 都不该再被解析
    text = re.sub(r"`([^`]+)`", lambda m: keep("<code>%s</code>" % _esc(m.group(1))), text)

    # 2. 图片，必须在链接之前（![..](..) 也匹配 [..](..)）
    def img(m):
        alt, src, title = m.group(1), m.group(2), m.group(3)
        if image_prefix and not re.match(r"(?:[a-z]+:|/|#)", src):
            src = image_prefix + re.sub(r"^\./", "", src)
        t = ' title="%s"' % _esc(title) if title else ""
        return keep('<img src="%s" alt="%s"%s>' % (_esc(src), _esc(alt), t))

    text = re.sub(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"([^\"]*)\")?\s*\)", img, text)

    # 3. 链接。相对路径指到 GitHub 上的文件（README 里会互相引用 .h / .md）
    def link(m):
        label, href = m.group(1), m.group(2).strip()
        if link_base and not re.match(r"(?:[a-z]+:|/|#)", href):
            href = link_base + re.sub(r"^\.\.?/", "", href)
        ext = ' target="_blank" rel="noopener"' if href.startswith("http") else ""
        return keep('<a href="%s"%s>%s</a>' % (_esc(href), ext, label))

    text = re.sub(r"\[([^\]]+)\]\(\s*([^)]+?)\s*\)", link, text)

    # 4. 裸 URL（引用来源那几行常直接贴链接）
    text = re.sub(r"(?<![\"'>=])(https?://[^\s<>\u4e00-\u9fff]+)",
                  lambda m: keep('<a href="%s" target="_blank" rel="noopener">%s</a>'
                                 % (_esc(m.group(1)), _esc(m.group(1)))), text)

    # 5. 强调。下划线不做（文件名 a_b 太多），只认 ** 和 ~~
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", text)

    for k, frag in enumerate(store):
        text = text.replace(_PLACE % k, frag)

    return text


def _render_inline(raw, link_base, image_prefix=None):
    """先转义（保留已生成的标签），再交给 _inline 处理标记。"""
    store = []
    def keep(fragment):
        store.append(fragment)
        return "\x01%d\x01" % (len(store) - 1)

    frag = raw
    # 把行内代码的原始内容先护住，免得被转义后又当标记解析
    codes = []
    def hold(m):
        codes.append(m.group(1))
        return "\x02%d\x02" % (len(codes) - 1)
    frag = re.sub(r"`([^`]+)`", hold, frag)

    # LaTeX 公式也先护住：$..$ 与 $$..$$，内容不允许以空白开头/结尾，
    # 避免把「价格 $5 和 $6」这类文本误判成公式。
    maths = []
    def hold_math(m):
        maths.append(m.group(0))     # 连定界符一起留下，auto-render 要靠它认公式
        return "\x03%d\x03" % (len(maths) - 1)
    frag = re.sub(r"\$\$([^$\n]+?)\$\$", hold_math, frag)
    frag = re.sub(r"\$(?![\s$])([^$\n]+?)(?<![\s$])\$", hold_math, frag)

    frag = _esc(frag)
    frag = _inline(frag, link_base, image_prefix)

    # 还原行内代码（内容单独转义）
    for i, code in enumerate(codes):
        frag = frag.replace("\x02%d\x02" % i, '<code>%s</code>' % _esc(code))
    # 还原公式：只转义 HTML，不进任何 markdown 规则，KaTeX 拿到的就是原文
    for i, tex in enumerate(maths):
        frag = frag.replace("\x03%d\x03" % i,
                            '<span class="math">%s</span>' % _esc(tex))
    return frag


# ---- 块级 -----------------------------------------------------------------

FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+#-]*)\s*$")
HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
HR = re.compile(r"^\s*(?:\*\s*){3,}$|^\s*(?:-\s*){3,}$|^\s*(?:_\s*){3,}$")
LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells, cur, esc = [], "", False
    for ch in s:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
    cells.append(cur.strip())
    return cells


def _table(lines, i, link_base, image_prefix):
    head = _split_row(lines[i])
    aligns = []
    for c in _split_row(lines[i + 1]):
        c = c.strip()
        if c.startswith(":") and c.endswith(":"):
            aligns.append("center")
        elif c.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("")
    i += 2
    body = []
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        body.append(_split_row(lines[i]))
        i += 1

    out = ['<div class="table-wrap"><table>', "<thead><tr>"]
    for k, c in enumerate(head):
        a = ' style="text-align:%s"' % aligns[k] if k < len(aligns) and aligns[k] else ""
        out.append("<th%s>%s</th>" % (a, _render_inline(c, link_base, image_prefix)))
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>")
        for k, c in enumerate(row):
            a = ' style="text-align:%s"' % aligns[k] if k < len(aligns) and aligns[k] else ""
            out.append("<td%s>%s</td>" % (a, _render_inline(c, link_base, image_prefix)))
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out), i


def _list(lines, i, link_base, image_prefix):
    """返回 (html, next_i)。按缩进递归，支持两级以上。"""
    first = LIST.match(lines[i])
    indent = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    items, i = [], i
    while i < len(lines):
        m = LIST.match(lines[i])
        if not m or len(m.group(1)) != indent or m.group(2)[0].isdigit() != ordered:
            break
        raw = [m.group(3)]
        blocks = []

        def flush_raw():
            # 续行要和首行拼成一段再渲染，否则行内标记跨行时会漏（`**粗体`
            # 折到下一行就匹配不上了）
            if raw:
                blocks.append(_render_inline(" ".join(x.strip() for x in raw),
                                             link_base, image_prefix))
                del raw[:]

        i += 1
        # 子项 / 续行：缩进更深的算这个 item 的一部分
        while i < len(lines):
            if not lines[i].strip():
                # 空行后若紧跟更深的列表项，仍属于本 item
                if i + 1 < len(lines) and LIST.match(lines[i + 1]) and \
                   len(LIST.match(lines[i + 1]).group(1)) > indent:
                    i += 1
                    continue
                break
            n = LIST.match(lines[i])
            if n and len(n.group(1)) > indent:
                flush_raw()
                sub, i = _list(lines, i, link_base, image_prefix)
                blocks.append(sub)
                continue
            if not n and len(lines[i]) - len(lines[i].lstrip()) > indent:
                raw.append(lines[i].strip())
                i += 1
                continue
            break
        flush_raw()
        items.append("<li>%s</li>" % "".join(blocks))
    tag = "ol" if ordered else "ul"
    return "<%s>%s</%s>" % (tag, "".join(items), tag), i


def inline(text):
    """只走行内规则（粗体、代码、链接），给「一行摘要」这类场景用。"""
    return _render_inline(text, None, None)


def plain(text):
    """去掉行内标记，得到纯文本（meta description 不能带标签）。"""
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text


def convert(text, image_prefix=None, link_base=None):
    """md 文本 → (html, toc)。image_prefix 加在相对图片路径前；
    link_base 加在相对链接前（默认指到 GitHub 仓库根）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    lines = text.split("\n")
    out, toc, used = [], [], set()
    i, n = 0, len(lines)
    para = []

    def flush():
        if para:
            # 整段就是一个 $$...$$ 显示公式 → 单独的块，别塞进 <p> 里
            joined = " ".join(para)
            m = re.match(r"^\$\$(.+?)\$\$$", joined, re.S)
            if m:
                out.append('<div class="math-display">$$%s$$</div>'
                           % _esc(m.group(1).strip()))
                para.clear()
                return
            out.append("<p>%s</p>" % _render_inline(" ".join(para), link_base, image_prefix))
            para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush()
            i += 1
            continue

        m = FENCE.match(line)
        if m:
            flush()
            fence, lang = m.group(1), m.group(2)
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith(fence):
                buf.append(lines[i])
                i += 1
            i += 1
            if lang == "mermaid":
                # mermaid 读 textContent 渲染；转义即可，不要碰里面的任何字符
                out.append('<pre class="mermaid">%s</pre>' % _esc("\n".join(buf)))
                continue
            if lang == "math":
                # 内容不含定界符，包上 $$ 让 auto-render 按显示模式处理
                out.append('<div class="math-display">$$%s$$</div>'
                           % _esc("\n".join(buf).strip()))
                continue
            cls = ' class="language-%s"' % lang if lang else ""
            out.append("<pre><code%s>%s</code></pre>" % (cls, _esc("\n".join(buf))))
            continue

        m = HEAD.match(line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2)
            anchor = _slug(re.sub(r"[`*_]", "", title), used) if level >= 2 else ""
            if level in (2, 3):
                toc.append((level, anchor, re.sub(r"[`*_]", "", title)))
            attr = ' id="%s"' % anchor if anchor else ""
            out.append("<h%d%s>%s</h%d>" % (level, attr,
                                            _render_inline(title, link_base, image_prefix), level))
            i += 1
            continue

        if HR.match(line):
            flush()
            out.append("<hr>")
            i += 1
            continue

        if stripped.startswith(">"):
            flush()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>%s</blockquote>"
                       % convert("\n".join(buf), image_prefix, link_base)[0])
            continue

        if "|" in line and i + 1 < n and TABLE_SEP.match(lines[i + 1]):
            flush()
            frag, i = _table(lines, i, link_base, image_prefix)
            out.append(frag)
            continue

        if LIST.match(line):
            flush()
            frag, i = _list(lines, i, link_base, image_prefix)
            out.append(frag)
            continue

        if stripped.startswith("<"):
            # 允许少量原始 HTML 直通（README 里偶尔嵌 <details>）
            flush()
            out.append(line)
            i += 1
            continue

        para.append(stripped)
        i += 1

    flush()
    return "\n".join(out), toc


if __name__ == "__main__":
    import sys
    src = open(sys.argv[1], encoding="utf-8").read()
    print(convert(src)[0])
