#!/usr/bin/env python3
"""翻译目录的提取、编译与校验。

本工程用 gettext 做多语言，域名是 ``gegl-color-ops``（见 common/config.h）。
按约定 msgid 一律写英文，中文等译文放在 po/<lang>.po 里 —— 缺译时用户看到英文，
不会看到半截中文。

用法::

    python tools/i18n.py extract        # 扫源码，刷新 po/gegl-color-ops.pot
    python tools/i18n.py build          # 每个 po/*.po 编成 locale/<lang>/LC_MESSAGES/*.mo
    python tools/i18n.py check          # 校验（msgid 必须是英文、无重复、无空译）

``build`` 自带纯 Python 的 .mo 写入器，不依赖 msgfmt（CI 与 Windows 上都不必装
gettext 工具链）；装了 msgfmt 也只是多一层保险，用不到。
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import struct
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAIN = "gegl-color-ops"
POT = os.path.join(ROOT, "po", DOMAIN + ".pot")
PO_DIR = os.path.join(ROOT, "po")
LOCALE_DIR = os.path.join(ROOT, "locale")

HEADER = """\
# {domain} translation template.
# 由 tools/i18n.py extract 生成，不要手改。
msgid ""
msgstr ""
"Project-Id-Version: {domain}\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"X-Source-Language: en\\n"
"""

# _("...")、_N_("...")，允许相邻字面量拼接（"a" "b"）
CALL_RE = re.compile(r'\b_?N?_\s*\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)', re.S)
LIT_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')

# enum_value (ID, "nick", "Label" [, "blurb"])：标签本身不带 _()，但 GEGL 在
# enum_end 里会拿它去 dgettext(GETTEXT_PACKAGE)，所以也要进目录。取调用里最后
# 一个字面量作为标签。
ENUM_VALUE_RE = re.compile(r'\benum_value\s*\(((?:[^()"]|"(?:[^"\\]|\\.)*")*)\)', re.S)


def unescape(text: str) -> str:
    return (text.replace("\\n", "\n").replace("\\t", "\t")
            .replace('\\"', '"').replace("\\\\", "\\"))


def escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\t", "\\t"))


def sources() -> list[str]:
    files = sorted(glob.glob(os.path.join(ROOT, "ops", "*", "*.c")))
    files += sorted(glob.glob(os.path.join(ROOT, "plugin", "*", "*.py")))
    files += sorted(glob.glob(os.path.join(ROOT, "plugin", "_shared", "*.py")))
    return files


def collect() -> "OrderedDict[str, list[str]]":
    """msgid -> 出处列表。按首次出现顺序，去重。"""
    found: "OrderedDict[str, list[str]]" = OrderedDict()
    for path in sources():
        with open(path, encoding="utf-8", errors="surrogateescape") as fh:
            src = fh.read()
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")

        def add(msgid: str, pos: int) -> None:
            if not msgid.strip():
                return
            refs = found.setdefault(msgid, [])
            ref = f"{rel}:{src.count(chr(10), 0, pos) + 1}"
            if ref not in refs:
                refs.append(ref)

        for match in CALL_RE.finditer(src):
            pieces = LIT_RE.findall(match.group(1))
            if pieces:
                add(unescape("".join(pieces)), match.start())

        if path.endswith(".c"):
            for match in ENUM_VALUE_RE.finditer(src):
                pieces = LIT_RE.findall(match.group(1))
                if len(pieces) >= 2:
                    add(unescape(pieces[-1]), match.start())
    return found


def write_pot(entries: "OrderedDict[str, list[str]]") -> None:
    os.makedirs(PO_DIR, exist_ok=True)
    out = [HEADER.format(domain=DOMAIN).rstrip("\n"), ""]
    for msgid, refs in entries.items():
        for ref in refs:
            out.append(f"#: {ref}")
        out.append(f'msgid "{escape(msgid)}"')
        out.append('msgstr ""')
        out.append("")
    with open(POT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out))
    print(f"✓ {os.path.relpath(POT, ROOT)}：{len(entries)} 条")


def parse_po(path: str) -> "OrderedDict[str, str]":
    """极简 .po 解析：只取 msgid/msgstr，支持多行与注释。"""
    entries: "OrderedDict[str, str]" = OrderedDict()
    cur_id: list[str] | None = None
    cur_str: list[str] | None = None
    field = None

    def flush() -> None:
        if cur_id is not None and cur_str is not None:
            msgid = unescape("".join(cur_id))
            if msgid:
                entries[msgid] = unescape("".join(cur_str))

    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
                flush()
                cur_id = cur_str = None
                field = None
                continue
            if line.startswith("#"):
                continue
            if line.startswith("msgid "):
                if cur_id is not None and cur_str is not None:
                    flush()
                cur_id, cur_str, field = [LIT_RE.findall(line)[0]], [""], "id"
                continue
            if line.startswith("msgstr "):
                cur_str = [LIT_RE.findall(line)[0]] if LIT_RE.findall(line) else [""]
                field = "str"
                continue
            if line.startswith('"'):
                lit = LIT_RE.findall(line)
                if not lit:
                    continue
                if field == "id":
                    cur_id.append(lit[0])
                elif field == "str":
                    cur_str.append(lit[0])
    flush()
    return entries


def write_mo(path: str, entries: dict[str, str]) -> None:
    """最小可用的 .mo 写入器（等价 msgfmt，不带 fuzzy/context）。"""
    items = sorted((k.encode("utf-8"), v.encode("utf-8"))
                   for k, v in entries.items() if v)
    items.insert(0, (b"", b"Content-Type: text/plain; charset=UTF-8\n"))

    count = len(items)
    key_off = 7 * 4 + 16 * count           # 头 28 字节 + 两张索引表
    keys = b""
    offsets = []
    for key, _ in items:
        offsets.append((len(keys), len(key)))
        keys += key + b"\0"
    val_base = key_off + len(keys)
    vals = b""
    voffsets = []
    for _, val in items:
        voffsets.append((len(vals), len(val)))
        vals += val + b"\0"

    out = struct.pack("<7I", 0x950412DE, 0, count, 7 * 4,
                      7 * 4 + 8 * count, 0, 0)
    for off, size in offsets:
        out += struct.pack("<2I", size, key_off + off)
    for off, size in voffsets:
        out += struct.pack("<2I", size, val_base + off)
    out += keys + vals

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(out)


def build() -> int:
    pfiles = sorted(glob.glob(os.path.join(PO_DIR, "*.po")))
    if not pfiles:
        print("✗ po/ 下没有 .po 文件")
        return 1
    total = 0
    for path in pfiles:
        lang = os.path.splitext(os.path.basename(path))[0]
        entries = parse_po(path)
        target = os.path.join(LOCALE_DIR, lang, "LC_MESSAGES", DOMAIN + ".mo")
        write_mo(target, entries)
        translated = sum(1 for k, v in entries.items() if v)
        total += translated
        print(f"✓ {lang}: {translated}/{len(entries)} 条 -> "
              f"{os.path.relpath(target, ROOT)}")
    return 0


def check() -> int:
    entries = collect()
    problems = 0
    cjk = re.compile(r"[\u4e00-\u9fff]")
    chinese_ids = [m for m in entries if cjk.search(m)]
    if chinese_ids:
        problems += len(chinese_ids)
        print(f"✗ {len(chinese_ids)} 条 msgid 里还有中文（本工程约定 msgid 为英文）：")
        for msgid in chinese_ids[:10]:
            print(f"    {entries[msgid][0]}  {msgid[:60]}")
        if len(chinese_ids) > 10:
            print(f"    … 还有 {len(chinese_ids) - 10} 条")

    for path in sorted(glob.glob(os.path.join(PO_DIR, "*.po"))):
        lang = os.path.splitext(os.path.basename(path))[0]
        po = parse_po(path)
        missing = [m for m in entries if m not in po]
        empty = [m for m in po if m in entries and not po[m]]
        stale = [m for m in po if m not in entries]
        if missing:
            # 缺译是允许的（回落到英文 msgid），只提示不判失败
            print(f"· {lang}: {len(missing)} 条尚无译文（显示英文原文）")
        if empty:
            print(f"✗ {lang}: {len(empty)} 条 msgstr 为空")
            problems += len(empty)
        if stale:
            print(f"· {lang}: {len(stale)} 条 msgid 在源码里已不存在（可删除）")

    # msgid 与 msgstr 的 printf 占位符数量必须一致，否则运行时会 TypeError
    spec = re.compile(r"%(?:\d+\$)?[-+ 0#]*\d*(?:\.\d+)?[sdifguxX%](?![A-Za-z])")
    for path in sorted(glob.glob(os.path.join(PO_DIR, "*.po"))):
        lang = os.path.splitext(os.path.basename(path))[0]
        po = parse_po(path)
        for msgid, msgstr in po.items():
            if not msgstr:
                continue
            a = len(spec.findall(msgid))
            b = len(spec.findall(msgstr))
            if a != b:
                print(f"✗ {lang}: 占位符数量不一致（{a} vs {b}）：{msgid[:60]}")
                problems += 1

    if not problems:
        print(f"✓ {len(entries)} 条 msgid，检查通过")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["extract", "build", "check"])
    args = ap.parse_args(argv)

    if args.action == "extract":
        write_pot(collect())
        return 0
    if args.action == "build":
        return build()
    return check()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
