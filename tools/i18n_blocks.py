#!/usr/bin/env python3
"""注释双语化工具：按「注释块」定位与替换，保证只动注释、不动代码。

用法：
    python tools/i18n_blocks.py scan  <算子名>            # 列出块号/行号/原文
    python tools/i18n_blocks.py apply <算子名> <map.json> # 按块号替换
    python tools/i18n_blocks.py check                     # 与 git HEAD 比，确认代码零改动
    python tools/i18n_blocks.py todo                       # 统计仍缺英文的注释块

注释风格约定（本工程统一）：
    单行：  /* 中文 / English */
    多行：  /* 中文...
             * English...
             */
替换文件格式（三种写法可混用）：
    {"0": {"zh": "中文", "en": "English"}}      # 自动排版：能一行就一行，否则折行
    {"1": {"div": "中文 / English"}}            # 段分隔线，dashes 由 normalize 补齐
    {"2": null}                                 # 删除该块（用于合并中英重复块）
块内缩进由脚本补，折行宽度按 78 列（CJK 记 2 列）计算。
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from normalize_headers import WIDTH, _divider, _wrap, _w   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def op_path(name):
    return os.path.join(ROOT, "ops", name, name + ".c")


def header_end(lines):
    """文件头注释盒之后的第一行（含 #include 之前）——头盒由 normalize_headers 管。"""
    for i, ln in enumerate(lines):
        if ln.startswith("#include"):
            # 往上找注释盒的结束行
            for j in range(i - 1, -1, -1):
                if lines[j].rstrip().endswith("*/"):
                    return j + 1
            return i
    return 0


def blocks(text):
    """扫描 C 注释块，返回 [(start, end, indent)]，行号 0 基。"""
    lines = text.split("\n")
    skip_until = header_end(lines)
    out, i = [], skip_until
    while i < len(lines):
        ln = lines[i]
        pos = ln.find("/*")
        if pos < 0:
            i += 1
            continue
        indent = len(ln) - len(ln.lstrip())
        if "*/" in ln[pos + 2:]:
            out.append((i, i, indent))
            i += 1
            continue
        j = i + 1
        while j < len(lines) and "*/" not in lines[j]:
            j += 1
        out.append((i, min(j, len(lines) - 1), indent))
        i = j + 1
    return out


def scan(name):
    path = op_path(name)
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    for n, (a, b, ind) in enumerate(blocks(text)):
        body = "\n".join(lines[a:b + 1])
        print(f"--- #{n}  行 {a+1}-{b+1}  缩进 {ind}")
        print(body)
    print(f"共 {len(blocks(text))} 个块")


def strip_comments(text):
    """去掉所有注释并压缩空白，用于确认代码本体未变。"""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':                      # 字符串字面量原样保留
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        else:
            out.append(c)
            i += 1
    # 比较时忽略所有空白：注释删除会改变空行数量，但必须保证代码字符逐一相同
    return re.sub(r"\s+", "", "".join(out))


def compose(zh, en, indent):
    """把中文段与英文段排成注释块：一行放得下就用单行，否则折行。"""
    budget = WIDTH - indent - 6
    lines = []
    for p in (zh if isinstance(zh, list) else [zh]):
        lines += _wrap(p, budget)
    for p in (en if isinstance(en, list) else [en]):
        lines += _wrap(p, budget)
    if len(lines) == 1:
        return [f"/* {lines[0]} */"]
    out = [f"/* {lines[0]}"]
    out += [f" * {l}" for l in lines[1:-1]]
    out.append(f" * {lines[-1]} */")
    return out


def render(value, indent):
    """JSON 里的值 -> 注释块各行（不含缩进）。"""
    if value is None:
        return []
    if isinstance(value, str):                       # 已经是排好的整块
        return value.split("\n")
    if "div" in value:
        if "lines" in value:                         # 带正文的段注释：首行不能自行闭合
            return ([_divider("", value["div"])[:-3].rstrip()]
                    + [f" * {l}" if l else " *" for l in value["lines"]]
                    + [" */"])
        return [_divider("", value["div"])]
    return compose(value["zh"], value["en"], indent)


def apply_map(name, map_path):
    path = op_path(name)
    text = open(path, encoding="utf-8").read()
    repl = json.load(open(map_path, encoding="utf-8"))
    lines = text.split("\n")
    bl = blocks(text)
    for key in sorted(repl, key=lambda k: int(k), reverse=True):   # 从后往前，行号不漂移
        idx = int(key)
        a, b, ind = bl[idx]
        value = repl[key]
        if isinstance(value, dict) and "tail" in value:            # 行尾注释：只改注释部分
            line = lines[a]
            cut = line.find("/*")
            lines[a] = line[:cut] + f"/* {value['tail']} */"
            continue
        new = render(value, ind)
        pad = " " * ind
        lines[a:b + 1] = [(pad + ln) if ln else "" for ln in new]
    new_text = "\n".join(lines)
    old_code, new_code = strip_comments(text), strip_comments(new_text)
    if old_code != new_code:
        print(f"  !! {name}: 代码本体被改动，已放弃写入")
        return False
    open(path, "w", encoding="utf-8", newline="\n").write(new_text)
    print(f"  写入 {name}: {len(repl)} 个块")
    return True


def check():
    ok = True
    for name in sorted(os.listdir(os.path.join(ROOT, "ops"))):
        path = op_path(name)
        if not os.path.exists(path):
            continue
        head = subprocess.run(["git", "show", f"HEAD:ops/{name}/{name}.c"],
                              cwd=ROOT, capture_output=True, text=True)
        if head.returncode:
            continue
        old, new = strip_comments(head.stdout), strip_comments(open(path, encoding="utf-8").read())
        if old != new:
            ok = False
            print(f"  !! {name} 代码有差异")
    print("代码本体检查：", "全部一致" if ok else "存在差异")
    return ok


def todo():
    """缺语言检测：块内既要有汉字，也要有 3 字符以上的英文单词才算双语。"""
    for name in sorted(os.listdir(os.path.join(ROOT, "ops"))):
        path = op_path(name)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        lines = text.split("\n")
        miss = []
        for n, (a, b, _) in enumerate(blocks(text)):
            body = " ".join(lines[a:b + 1])
            zh = re.search(r"[\u4e00-\u9fff]", body)
            en = re.search(r"[A-Za-z]{3,}", body)
            if not (zh and en):
                miss.append((n, "缺英文" if zh else "缺中文"))
        if miss:
            print(f"  {name:28s} {len(miss)} 个块: {miss[:6]}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "todo"
    if cmd == "scan":
        scan(sys.argv[2])
    elif cmd == "apply":
        apply_map(sys.argv[2], sys.argv[3])
    elif cmd == "check":
        check()
    else:
        todo()
