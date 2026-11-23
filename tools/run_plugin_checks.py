#!/usr/bin/env python3
"""跑一遍 Python 插件的回归，并把「断言条数」记成机器可读的文件。

站点上那个「N 条回归断言」原先是在 tools/site_build.py 里手写的，改测试时
十有八九忘了改（2026-11-19 写 503，11-23 加了 168 条却还是 503，靠人肉想起来
改成 671）。现在改成：这个脚本真实跑一遍，把每条套件的条数写进
tools/plugin_assertions.json，站点构建时读那个文件求和。数字骗不了人，也不会
忘。

用法：
    python tools/run_plugin_checks.py            # 跑全套，重写 json
    python tools/run_plugin_checks.py --check    # 只核对 json 是否过期（构建时用）
    python tools/run_plugin_checks.py --print    # 只打印当前 json 里的总数

套件分两种：纯 Python（直接跑）和 GIMP 内（要真 GIMP，用 gimp-console 加载
脚本）。GIMP 的位置按 LB_GIMP 环境变量、PATH、常见安装路径依次找。

为什么单个套件失败就整体不写：一个套件挂了就没有可信条数，写进去只会让站点上
的数字比实际小，而没人会发现少了一个。
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tools", "plugin_assertions.json")

# (名字, 跑法, 脚本)。名字只用于报错和 json 的键，取脚本名去掉 .py。
SUITES = [
    ("check_ai_inpaint", "python"),
    ("check_retouch_ai", "python"),
    ("check_plugin_dialogs", "gimp"),
    ("check_retouch", "gimp"),
    ("check_observe", "gimp"),
    ("check_luminosity_mask", "gimp"),
    ("check_convert", "gimp"),
    ("check_ai_inpaint_gimp", "gimp"),
    ("check_retouch_ai_gimp", "gimp"),
]

# (正则, 语义)。语义有两种：'pass/total' 两个数都要对上，'pass/fail' 只要求
# 失败数为 0。各脚本的收尾提示是历史包袱，与其统一改一堆脚本，不如在这里认。
COUNT_RE = [
    (re.compile(r"(\d+)/(\d+)\s*通过"), "pass/total"),      # 「168/168 通过」
    (re.compile(r"通过\s*(\d+)\s*项，失败\s*(\d+)\s*项"), "pass/fail"),
    (re.compile(r"（(\d+)\s*条断言）"), "one"),              # check_plugin_dialogs
    (re.compile(r"：(\d+)\s*条断言"), "one"),                # check_retouch_ai
    (re.compile(r"全部通过：(\d+)\s*项检查"), "one"),         # check_retouch
]


def script_path(name):
    return os.path.join(ROOT, "tools", name + ".py")


def find_gimp():
    """定位 gimp-console。返回 None 表示这台机器上没装（那就只跑纯 Python 套件）。"""
    env = os.environ.get("LB_GIMP")
    if env and os.path.exists(env):
        return env
    for exe in ("gimp-console-3.2.exe", "gimp-console-3.0.exe",
                "gimp-console-3", "gimp-console"):
        hit = shutil.which(exe)
        if hit:
            return hit
    for base in ("C:/Program Files/GIMP 3/bin", "C:/Program Files/GIMP 2.99/bin",
                 "D:/fastsoftware/GIMP 3/bin", "/usr/bin", "/usr/local/bin",
                 "/Applications/GIMP-3.app/Contents/MacOS"):
        for exe in ("gimp-console-3.2.exe", "gimp-console-3.0.exe",
                    "gimp-console-3", "gimp-console"):
            p = os.path.join(base, exe)
            if os.path.exists(p):
                return p
    return None


def run_suite(name, kind, gimp):
    path = script_path(name)
    if kind == "python":
        cmd = [sys.executable, path]
    elif kind == "gimp":
        if not gimp:
            return None, "这台机器上找不到 gimp-console（设 LB_GIMP 指过去）"
        # 用 exec 加载而不是 -b "python-fu-eval" 的引号拼接：路径里有空格，
        # 在 Windows 上多层引号极易被吃掉。
        cmd = [gimp, "-i", "-c", "-d", "-f", "--batch-interpreter=python-fu-eval",
               "-b", "exec(open(r'%s').read())" % path.replace("\\", "/"), "--quit"]
    else:
        raise ValueError(kind)

    t0 = time.time()
    try:
        # GIMP 收尾时偶尔不肯退，超时直接判失败：宁可报错也不要一个来历不明的数。
        proc = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=900)
    except subprocess.TimeoutExpired:
        return None, "超时（>900 s）"
    out = proc.stdout.decode("utf-8", "replace")
    dt = time.time() - t0

    if proc.returncode != 0:
        tail = "\n".join(out.strip().splitlines()[-6:])
        return None, "退出码 %d，最后几行：\n%s" % (proc.returncode, tail)

    for pat, kind in COUNT_RE:
        m = pat.search(out)
        if not m:
            continue
        if kind == "one":
            return int(m.group(1)), "%.0f s" % dt
        first, second = int(m.group(1)), int(m.group(2))
        if kind == "pass/fail":
            if second:
                tail = "\n".join(out.strip().splitlines()[-6:])
                return None, "失败了 %d 条：\n%s" % (second, tail)
            return first, "%.0f s" % dt
        if first != second:
            tail = "\n".join(out.strip().splitlines()[-6:])
            return None, "只过了 %d/%d：\n%s" % (first, second, tail)
        return second, "%.0f s" % dt

    tail = "\n".join(out.strip().splitlines()[-6:])
    return None, "输出里找不到断言条数（脚本改了收尾提示？）：\n%s" % tail


def collect(gimp):
    counts, times, bad = {}, {}, []
    for name, kind in SUITES:
        sys.stdout.write("· %-24s " % name)
        sys.stdout.flush()
        n, note = run_suite(name, kind, gimp)
        if n is None:
            print("失败 —— %s" % note)
            bad.append((name, note))
        else:
            print("%d 条（%s）" % (n, note))
            counts[name] = n
            times[name] = note
    return counts, times, bad


def write_json(counts):
    data = {
        "note": "由 tools/run_plugin_checks.py 生成，勿手改。站点构建读 total。",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "suites": counts,
        "total": sum(counts.values()),
    }
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return data


def read_json():
    if not os.path.exists(OUT):
        return None
    with io.open(OUT, encoding="utf-8") as f:
        return json.load(f)


def stale_reason(data):
    """json 是否可信：脚本比 json 新、或套件清单对不上，都算过期。

    只比 mtime：`git checkout` 出来的旧脚本 mtime 会变新，那也只是多提示一次，
    不会骗人。反过来漏提示就会让站点显示一个早就作废的数字。
    """
    if data is None:
        return "还没生成（先跑 python tools/run_plugin_checks.py）"
    if sorted(data.get("suites", {})) != sorted(n for n, _ in SUITES):
        return "套件清单变了（json 里的键和 SUITES 对不上）"
    gen = os.path.getmtime(OUT)
    newer = [n for n, _ in SUITES if os.path.getmtime(script_path(n)) > gen]
    if newer:
        return "这些脚本比统计新：%s" % ", ".join(newer)
    return ""


def main():
    args = set(sys.argv[1:])
    data = read_json()
    if "--print" in args:
        print(data["total"] if data else 0)
        return 0
    if "--check" in args:
        why = stale_reason(data)
        if why:
            print("✗ 断言统计过期：%s" % why)
            return 1
        print("· 断言统计是最新的：%d 条（%s）"
              % (data["total"], ", ".join("%s %d" % (k, v)
                                          for k, v in data["suites"].items())))
        return 0

    gimp = find_gimp()
    print("· GIMP: %s" % (gimp or "没找到（跳过 GIMP 内的那几条）"))
    counts, _times, bad = collect(gimp)
    if bad:
        print("\n✗ %d 条套件没跑成，json 不写（免得站点上的数字悄悄变小）："
              % len(bad))
        for name, note in bad:
            print("    %s: %s" % (name, note.replace("\n", "\n      ")))
        return 1
    d = write_json(counts)
    print("\n· 合计 %d 条断言，已写入 %s"
          % (d["total"], os.path.relpath(OUT, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
