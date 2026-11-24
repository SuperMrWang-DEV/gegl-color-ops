#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：把 53 个算子的属性（名字/范围/默认值）抓成一行一条，方便配演示参数。

    python tools/_opinfo.py > tools/_opinfo.tsv

gegl.exe 的输出是 GBK 混 UTF-8（菜单标签有中文），一律按 replace 解。
"""
import glob
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = r"D:\fastsoftware\GIMP 3\bin\gegl.exe"

env = dict(os.environ)
env["GEGL_PATH"] = os.pathsep.join([
    os.path.join(ROOT, "build"),
    os.path.join(os.environ["LOCALAPPDATA"], "gegl-0.4", "plug-ins"),
    r"D:\fastsoftware\GIMP 3\lib\gegl-0.4",
])

rows = []
for d in sorted(glob.glob(os.path.join(ROOT, "ops", "*"))):
    if not os.path.isdir(d):
        continue
    name = os.path.basename(d)
    src = ""
    for p in glob.glob(os.path.join(d, "*.c")):
        src += open(p, encoding="utf-8", errors="ignore").read()
    m = re.search(r"\bid\s+(lb:[a-z0-9-]+)", src)
    if not m:
        rows.append((name, "NONE", ""))
        continue
    op = m.group(1)
    raw = subprocess.run([EXE, "--info", op], env=env,
                         capture_output=True, timeout=90).stdout
    out = raw.decode("utf-8", "replace")
    props = []
    tail = out.split("Properties:")[-1]
    for line in tail.splitlines():
        mm = re.match(r"^([a-z0-9-]+)\s+\[(\w+)\]\s+(.*)$", line)
        if not mm:
            continue
        pname, _ptype, desc = mm.groups()
        tag = pname
        rng = re.match(r"\s*\(([-0-9.]+)\s*~\s*([-0-9.]+)\)", desc)
        if rng:
            tag += "[%s~%s]" % rng.groups()
        dflt = re.search(r"\(default:\s*([^)]*)\)", desc)
        if dflt:
            tag += "=%s" % dflt.group(1).strip()[:12]
        props.append(tag)
    rows.append((name, op, " ".join(props)))

for r in rows:
    print("\t".join(r))
