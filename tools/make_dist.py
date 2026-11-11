# -*- coding: utf-8 -*-
"""把 build/ 里编好的模块整理成可直接下载的 dist/ 目录。

    python tools/make_dist.py            # 复制 + 生成清单/校验和
    python tools/make_dist.py --check     # 只核对 dist/ 与 build/ 是否一致

dist/ 里只放"用户拿去就能用"的二进制：13 个 GEGL 模块（.dll / .so）。
带 .disabled 标记的算子（应用图像 / 计算）不参与，所以不会出现在包里。
"""
import hashlib
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")

# 平台目录名 -> 扩展名
PLATFORMS = [("windows-x64", "dll"), ("linux-x64", "so")]


def ops_meta():
    """从源码里读 id / 菜单名 / 标题；跳过 .disabled 的算子。"""
    meta = []
    for d in sorted(os.listdir(os.path.join(ROOT, "ops"))):
        opdir = os.path.join(ROOT, "ops", d)
        if not os.path.isdir(opdir) or os.path.exists(os.path.join(opdir, ".disabled")):
            continue
        srcs = [f for f in os.listdir(opdir) if f.endswith(".c")]
        if not srcs:
            continue
        text = open(os.path.join(opdir, srcs[0]), encoding="utf-8").read()
        op_id = re.search(r'"name",\s*"(lb:[^"]+)"', text)
        title = re.search(r'"title",\s*_?\("([^"]+)"\)', text)
        meta.append({
            "dir": d,
            "stem": os.path.splitext(srcs[0])[0],
            "id": op_id.group(1) if op_id else "",
            "title": title.group(1) if title else d,
        })
    return meta


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    check = "--check" in sys.argv
    meta = ops_meta()
    summary = []

    for plat, ext in PLATFORMS:
        out = os.path.join(DIST, plat)
        os.makedirs(out, exist_ok=True)
        built = sorted(f for f in os.listdir(BUILD) if f.endswith("." + ext))
        if check:
            have = sorted(f for f in os.listdir(out) if f.endswith("." + ext))
            if built != have:
                print("✗ %s 不一致：build=%d 个，dist=%d 个" % (plat, len(built), len(have)))
                print("  仅 build 有：%s" % (set(built) - set(have) or "无"))
                print("  仅 dist 有：%s" % (set(have) - set(built) or "无"))
                return 1
            print("OK %-12s %d 个，与 build/ 一致" % (plat, len(have)))
            continue
        for f in os.listdir(out):
            if f.endswith("." + ext):
                os.remove(os.path.join(out, f))
        for f in built:
            shutil.copy2(os.path.join(BUILD, f), os.path.join(out, f))
        summary.append((plat, len(built)))

    if check:
        return 0

    # ---- 清单 + 校验和 ----
    lines = ["platform,file,op_id,title,bytes,sha256"]
    sums = []
    for plat, ext in PLATFORMS:
        out = os.path.join(DIST, plat)
        for f in sorted(os.listdir(out)):
            if not f.endswith("." + ext):
                continue
            path = os.path.join(out, f)
            digest = sha256(path)
            stem = os.path.splitext(f)[0]
            op = next((m for m in meta if m["stem"] == stem or m["dir"] == stem), None)
            op_id = op["id"] if op else ""
            title = op["title"] if op else ""
            lines.append("%s,%s,%s,%s,%d,%s"
                         % (plat, f, op_id, title.replace(",", " "),
                            os.path.getsize(path), digest))
            sums.append("%s  %s/%s" % (digest, plat, f))
    open(os.path.join(DIST, "manifest.csv"), "w", encoding="utf-8", newline="\n").write(
        "\n".join(lines) + "\n")
    open(os.path.join(DIST, "SHA256SUMS.txt"), "w", encoding="utf-8", newline="\n").write(
        "\n".join(sums) + "\n")

    print("· dist/ 已更新")
    for plat, n in summary:
        print("  %-12s %2d 个模块" % (plat, n))
    print("  manifest.csv / SHA256SUMS.txt 已重新生成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
