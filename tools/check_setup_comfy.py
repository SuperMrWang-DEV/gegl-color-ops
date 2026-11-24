#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 tools/check_setup_comfy.py · setup_comfy（AI 依赖安装器）的回归
 ---------------------------------------------------------------------------
 不需要 GIMP、不需要显卡、**不联网**：所有 HTTP 都打在本机的一个 stub 上。

 测什么
   1. 台账本身：每条都有 key/group/repo/name/dest/size，key 不重复，
      落点都在 models/ 下，档位只引用存在的组
   2. 档位展开：min ⊂ std ⊂ full、--only 只给那一组、给错组要报错
   3. 节点包联动：flux 要 GGUF、select/rmbg 要 RMBG、纯模型档不要节点
   4. 找 ComfyUI：外层目录 / 直接指源码 / 手填解释器 / 三种布局里
      **`py/python.exe`（setup_ai.py 装出来的那种）必须认**——之前漏了，
      插件会把这种环境判成「有 main.py 没解释器」，自动启动直接失效
   5. 下载引擎（真跑 HTTP）：整段下完、半截续传、镜像装傻回 200、
      同一源没进展就换源、尺寸对不上不许留成品、404 自动换仓库
   6. 体检输出：全齐 → 0，缺文件 → 1，找不到 ComfyUI → 2
   7. 管道被关掉（| head）不许抛 traceback

 跑法   python tools/check_setup_comfy.py
 ==========================================================================="""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import setup_comfy as S                                     # noqa: E402

PASS = 0
FAIL = []
SECTION = ""


def section(name):
    global SECTION
    SECTION = name
    print("\n" + name)


def ok(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL.append("%s / %s" % (SECTION, name))
        print("  ✗ %s%s" % (name, ("   → %s" % detail) if detail else ""))


# ---- stub HTTP：按路径后缀决定行为 ------------------------------------------

PAYLOAD = bytes(range(256)) * 40          # 10240 字节，够看续传
BEHAVIOR = "ok"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _plan(self):
        """返回 (start, end, honor_range, force_200)。"""
        ranges = self.headers.get("Range") or ""
        start = 0
        if ranges.startswith("bytes=") and BEHAVIOR != "norange":
            try:
                start = int(ranges[6:].split("-")[0])
            except ValueError:
                start = 0
        return start

    def do_GET(self):
        if "/boom/" in self.path:            # 这个仓库没有：模拟 404
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.endswith("empty.bin"):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        start = self._plan()
        body = PAYLOAD[start:]
        if BEHAVIOR == "short":              # 只给一半，且伪装成「完整响应」
            body = PAYLOAD[start:start + len(PAYLOAD) // 2]
        code = 206 if (start and BEHAVIOR != "norange") else 200
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def start_stub():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def mk_asset(tmp_src, name="x.bin", size=len(PAYLOAD), repos=("stub/repo",),
             group="sd15", dest=None):
    return {"key": name, "group": group, "repo": repos[0], "name": name,
            "dest": dest or ("models/%s" % name), "size": size,
            "why": "测试", "repos": list(repos)}


# ---- 1. 台账 -----------------------------------------------------------------

def test_table():
    section("1. 资产台账")
    keys = [a["key"] for a in S.ASSETS]
    ok("key 不重复", len(keys) == len(set(keys)), [k for k in keys
                                                 if keys.count(k) > 1])
    bad = [a["key"] for a in S.ASSETS
           if not (a.get("repo") and a.get("name") and a.get("dest")
                   and isinstance(a.get("size"), int) and a["size"] > 0)]
    ok("每条都有 repo/name/dest/正整数 size", not bad, bad)
    ok("落点都在 models/ 下",
       all(a["dest"].startswith("models/") for a in S.ASSETS),
       [a["dest"] for a in S.ASSETS if not a["dest"].startswith("models/")])
    ok("组名都在 GROUP_TITLE 里",
       all(a["group"] in S.GROUP_TITLE for a in S.ASSETS),
       sorted({a["group"] for a in S.ASSETS} - set(S.GROUP_TITLE)))
    bad_tier = [t for t, gs in S.TIERS.items()
                if any(g not in S.GROUP_TITLE for g in gs)]
    ok("档位只引用存在的组", not bad_tier, bad_tier)
    ok("repos 至少含主仓库",
       all(a["repos"] and a["repos"][0] == a["repo"] for a in S.ASSETS))
    urls = S.asset_urls(S.ASSETS[0], ["https://m1", "https://m2"])
    ok("URL = 镜像 × 仓库，且都是 https",
       len(urls) == 2 * len(S.ASSETS[0]["repos"]) and
       all(u.startswith("https://") and "/resolve/main/" in u for u in urls),
       urls)


def test_tiers():
    section("2. 档位展开")
    min_a, min_g = S.select_assets("min")
    std_a, std_g = S.select_assets("std")
    full_a, full_g = S.select_assets("full")
    ok("min ⊂ std ⊂ full",
       set(min_g) < set(std_g) < set(full_g), (min_g, std_g, full_g))
    ok("min = SD1.5 inpaint + 64 MB 的超分权重",
       {a["key"] for a in min_a} == {"sd15-inpaint", "upscale-4x"},
       [a["key"] for a in min_a])
    ok("超分权重在每个档位都在（它只有 64 MB，缺了插件就废一条）",
       all("upscale" in g for g in (min_g, std_g, full_g)), (min_g, std_g, full_g))
    ok("std 含 SDXL / 选区 / 抠图",
       {"sdxl", "select", "rmbg"} <= {a["group"] for a in std_a})
    ok("full 才含 flux", "flux" not in {a["group"] for a in std_a} and
       "flux" in {a["group"] for a in full_a})
    only, groups = S.select_assets("std", (), ["flux"])
    ok("--only flux 只给 4 个 flux 文件",
       groups == ["flux"] and len(only) == 4 and
       all(a["group"] == "flux" for a in only), len(only))
    only2, groups2 = S.select_assets("min", ["rmbg"], ())
    ok("--with rmbg 在档位上追加而不替换",
       "sd15" in groups2 and "rmbg" in groups2 and "sdxl" not in groups2,
       groups2)
    try:
        S.select_assets("std", (), ["nope"])
        ok("不认识的组要报错", False)
    except S.Abort as exc:
        ok("不认识的组要报错，并列出可选项",
           "nope" in str(exc) and "flux" in str(exc), str(exc)[:60])


def test_nodes():
    section("3. 节点包联动")
    ok("flux 要 ComfyUI-GGUF", S.needed_nodes(["flux"]) == ["gguf"],
       S.needed_nodes(["flux"]))
    ok("select 要 ComfyUI-RMBG（按名称选区借它的节点）",
       S.needed_nodes(["select"]) == ["rmbg"])
    ok("rmbg 也要 ComfyUI-RMBG", S.needed_nodes(["rmbg"]) == ["rmbg"])
    ok("只有模型、没有特殊功能时不要节点包",
       S.needed_nodes(["sd15", "sdxl"]) == [])
    ok("GGUF 的 pip 依赖里必须有 gguf",
       "gguf>=0.13.0" in S.NODES["gguf"]["pip"])
    ok("RMBG 不整体装 requirements（会拽 onnxruntime-gpu 好几个 GB）",
       "onnxruntime-gpu>=1.15.0" not in S.NODES["rmbg"]["pip"] and
       "groundingdino-py" in S.NODES["rmbg"]["pip"])


# ---- 4. 找 ComfyUI ----------------------------------------------------------

def fake_layout(root, python_rel="py/python.exe", outer=True):
    src = os.path.join(root, "ComfyUI") if outer else root
    os.makedirs(src, exist_ok=True)
    open(os.path.join(src, "main.py"), "w").close()
    os.makedirs(os.path.join(src, "models"), exist_ok=True)
    if python_rel:
        p = os.path.join(root, python_rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
    return src


def test_find():
    section("4. 找 ComfyUI / 找解释器")
    tmp = tempfile.mkdtemp(prefix="lb-setup-home-")
    try:
        # setup_ai.py 的布局：root/py/python.exe + root/ComfyUI/main.py
        a = os.path.join(tmp, "ai")
        src_a = fake_layout(a, "py/python.exe", outer=True)
        info = S.find_comfy(a)
        ok("认出 setup_ai.py 的布局（py/python.exe）",
           info["src"] == os.path.normpath(src_a) and
           info["python"].endswith(os.path.join("py", "python.exe")),
           info)
        # 直接指到源码目录
        b = os.path.join(tmp, "src")
        src_b = fake_layout(b, "python_embeded/python.exe", outer=False)
        info_b = S.find_comfy(b)
        ok("直接指到含 main.py 的源码目录也认",
           info_b["src"] == os.path.normpath(src_b) and
           info_b["python"].endswith("python_embeded" + os.sep + "python.exe"),
           info_b)
        # 手填解释器优先
        manual = os.path.join(tmp, "other", "python.exe")
        os.makedirs(os.path.dirname(manual), exist_ok=True)
        open(manual, "w").close()
        info_c = S.find_comfy(b, manual)
        ok("--python 手填的解释器优先", info_c["python"] == manual, info_c)
        # 只有 main.py，没有任何解释器
        d = os.path.join(tmp, "bare")
        fake_layout(d, "", outer=True)
        info_d = S.find_comfy(d)
        ok("有 main.py 没解释器时不瞎猜",
           info_d["src"] and not info_d["python"], info_d)
        ok("没解释器时给出的提示里带 --python", "--python" in
           S.python_hint(info_d["home"], info_d["src"]))
        # 不存在的路径不算布局；但 find_comfy 会接着猜常见位置（本机可能真有
        # ComfyUI），所以只要求「不崩、不把不存在的目录当 home」
        nope = os.path.join(tmp, "nope")
        ok("不存在的目录不当 home",
           not S._looks_like_home(nope) and S.find_comfy(nope)["home"] != nope)
        ok("返回值字段齐",
           set(S.find_comfy(nope)) == {"home", "src", "python", "source"})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- 5. 下载引擎 ------------------------------------------------------------

def test_download():
    section("5. 下载引擎（真跑 HTTP）")
    global BEHAVIOR
    srv, base = start_stub()
    tmp = tempfile.mkdtemp(prefix="lb-setup-dl-")
    try:
        # (1) 整段下完
        BEHAVIOR = "ok"
        a = mk_asset(tmp, "ok.bin")
        r = S.download(a, tmp, mirrors=[base], retries=2)
        p = os.path.join(tmp, "models", "ok.bin")
        ok("整段下载，落盘尺寸对", r == "ok" and os.path.getsize(p) == len(PAYLOAD))
        ok("成品字节一致", open(p, "rb").read() == PAYLOAD)
        ok("再跑一次判「已完整」", S.download(a, tmp, mirrors=[base]) == "skip")
        ok("没有留下 .part", not os.path.exists(p + ".part"))

        # (2) 半截续传：.part 已有前 1000 字节
        a2 = mk_asset(tmp, "resume.bin")
        p2 = os.path.join(tmp, "models", "resume.bin")
        os.makedirs(os.path.dirname(p2), exist_ok=True)
        with open(p2 + ".part", "wb") as fh:
            fh.write(PAYLOAD[:1000])
        S.download(a2, tmp, mirrors=[base], retries=2)
        ok("从 .part 续传（不是从头下）",
           open(p2, "rb").read() == PAYLOAD)

        # (3) 镜像装傻：收到 Range 却回 200 + 整个文件
        BEHAVIOR = "norange"
        a3 = mk_asset(tmp, "norange.bin")
        p3 = os.path.join(tmp, "models", "norange.bin")
        os.makedirs(os.path.dirname(p3), exist_ok=True)
        with open(p3 + ".part", "wb") as fh:
            fh.write(PAYLOAD[:500])
        S.download(a3, tmp, mirrors=[base], retries=2)
        ok("源不认 Range 时清空重写，不拼出重复内容",
           open(p3, "rb").read() == PAYLOAD, os.path.getsize(p3))
        BEHAVIOR = "ok"

        # (4) 尺寸始终对不上 → 必须报错，且不许留成品
        BEHAVIOR = "short"
        a4 = mk_asset(tmp, "short.bin")
        p4 = os.path.join(tmp, "models", "short.bin")
        try:
            S.download(a4, tmp, mirrors=[base], retries=1)
            ok("尺寸对不上要报错", False)
        except S.Abort as exc:
            ok("尺寸对不上要报错，并说清试过哪个源",
               "short.bin" in str(exc) and "只拿到" in str(exc), str(exc)[:80])
        ok("失败时不留成品（半截 .part 也清掉）",
           not os.path.exists(p4) and not os.path.exists(p4 + ".part"))
        BEHAVIOR = "ok"

        # (5) 一个字节都拿不到 → 不在同一个源上死磕
        a5 = mk_asset(tmp, "empty.bin")
        try:
            S.download(a5, tmp, mirrors=[base], retries=3)
            ok("空响应要报错", False)
        except S.Abort as exc:
            ok("空响应立刻换源/报错（不是重试到天荒地老）",
               "没有进展" in str(exc), str(exc)[:80])

        # (6) 第一个仓库 404 → 换下一个仓库
        a6 = mk_asset(tmp, "ok2.bin", repos=("stub/boom", "stub/good"))
        r6 = S.download(a6, tmp, mirrors=[base], retries=1)
        ok("主仓库 404 时自动换下一个仓库", r6 == "ok")
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


# ---- 6. 体检 -----------------------------------------------------------------

def test_check(tmp_root):
    section("6. 体检输出与退出码")
    src = fake_layout(tmp_root, "py/python.exe")
    tiny = [mk_asset(tmp_root, "tiny.bin", size=16),
            mk_asset(tmp_root, "huge.bin", size=32)]
    for a in tiny:
        a["dest"] = "models/" + a["name"]
    rows = S.report_rows(src, tiny, ["sd15"])
    ok("缺文件 → miss", [r["state"] for r in rows] == ["miss", "miss"])
    os.makedirs(os.path.join(src, "models"), exist_ok=True)
    with open(os.path.join(src, "models", "tiny.bin"), "wb") as fh:
        fh.write(b"x" * 16)
    with open(os.path.join(src, "models", "huge.bin"), "wb") as fh:
        fh.write(b"x" * 8)
    rows = S.report_rows(src, tiny, ["sd15"])
    ok("尺寸对 → ok，尺寸不对 → part",
       [r["state"] for r in rows] == ["ok", "part"],
       [r["state"] for r in rows])
    ok("human() 在 GB/MB/B 三档都对",
       S.human(3 * S.GB).endswith("GB") and S.human(5 * S.MB).endswith("MB")
       and S.human(99).endswith("B"))
    ok("port_owner() 返回 int（没监听就是 0）",
       isinstance(S.port_owner(free_port()), int))
    # 中文 Windows 上 tasklist/netstat/git 的输出是 GBK。用 text=True 会解码
    # 失败、stdout 变 None，上层只能看到「什么都没找到」。这里直接塞一段
    # GBK 字节进去，要求 run_tool 能解出来而不是崩。
    rc, out = S.run_tool([sys.executable, "-c",
                          "import sys;sys.stdout.buffer.write(b'\\xbb\\xd8\\xd7\\xdc')"])
    ok("run_tool 能在 GBK 输出上活下来（不炸、不丢内容）",
       rc == 0 and out.strip() != "", (rc, out[:20]))


def test_cli(tmp_root):
    section("7. 命令行")
    # 造一个「空的 ComfyUI」：这样体检一定报缺，也不会读到本机真实安装
    fake_layout(tmp_root, "py/python.exe")
    # 子进程的输出必须指定编码：Windows 上 stdout 被重定向时 Python 默认按
    # 本地代码页写（cp936），父进程按 utf-8 解就是 UnicodeDecodeError。
    env = dict(os.environ, LB_COMFY_CONFIG=os.path.join(tmp_root, "cfg.json"),
               PYTHONIOENCODING="utf-8")
    import subprocess

    def run(argv, timeout=300):
        return subprocess.run(argv, capture_output=True, text=True, env=env,
                              encoding="utf-8", errors="replace",
                              timeout=timeout)

    here = os.path.join(HERE, "setup_comfy.py")
    r = run([sys.executable, here, "--check", "--home", tmp_root])
    ok("--check 缺东西时退出码 1（不是崩）",
       r.returncode == 1 and "Traceback" not in (r.stderr or ""), r.returncode)
    ok("--check 会列出缺哪个文件", "sd-v1-5-inpainting.ckpt" in (r.stdout or ""))
    ok("--check 会说清还差多少",
       "还差" in (r.stdout or "") and "GB" in (r.stdout or ""),
       (r.stdout or "")[-200:])

    r2 = run([sys.executable, here, "--only", "nope", "--check"])
    ok("--only 给错组：退出码 1，且提示可选组",
       r2.returncode == 1 and "可选" in (r2.stdout or "") and
       "Traceback" not in (r2.stderr or ""), (r2.returncode,
                                              (r2.stdout or "")[:80]))

    # 输出被 `| head` 关掉：不许 traceback（Windows 上是 OSError 22）。
    # 不真去开 bash（有些机器 bash 指向 wsl），直接把管道关掉来模拟。
    proc = subprocess.Popen([sys.executable, here, "--check", "--home", tmp_root],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, text=True, encoding="utf-8",
                            errors="replace")
    proc.stdout.readline()
    proc.stdout.close()
    try:
        _, err = proc.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
    ok("输出被管道关掉时不抛异常",
       "Traceback" not in (err or "") and "Errno 22" not in (err or ""),
       (err or "").strip()[:120])

    # 兼容入口
    fm = os.path.join(HERE, "fetch_models.py")
    r4 = run([sys.executable, fm, "nope"])
    ok("fetch_models.py 报未知档位（退出码 2）",
       r4.returncode == 2 and "sdxl" in (r4.stdout or ""), r4.returncode)
    r5 = run([sys.executable, fm, "--check", "--home", tmp_root])
    ok("fetch_models.py --check 转发得到 --only",
       "SDXL" in (r5.stdout or "") and "Flux" in (r5.stdout or ""),
       (r5.stdout or "")[:80])


def test_restart_policy(tmp_root):
    """什么都没变就别重启（用户可能正连着用），变了才重启。"""
    section("8. 要不要重启")
    fake_layout(tmp_root, "py/python.exe")
    saved_assets, saved_nodes = S.ASSETS, S.NODES
    saved_online, saved_restart = S.server_online, S.restart_server
    calls = []
    try:
        tiny = mk_asset(tmp_root, "done.bin", size=4)
        os.makedirs(os.path.join(tmp_root, "ComfyUI", "models"), exist_ok=True)
        with open(os.path.join(tmp_root, "ComfyUI", "models", "done.bin"),
                  "wb") as fh:
            fh.write(b"abcd")
        S.ASSETS = [tiny]
        S.NODES = {}
        S.server_online = lambda url=None: True
        S.restart_server = lambda *a, **k: (calls.append(1), (True, "stub"))[1]
        args = S.build_parser().parse_args(["--only", "sd15", "--home", tmp_root])
        rc = S.run(args)
        ok("全都齐了、服务在线 → 不重启（退出码 0）",
           rc == 0 and not calls, (rc, len(calls)))

        # 故意让 shim 缺失：select 组 → 有变化 → 必须重启
        calls.clear()
        args2 = S.build_parser().parse_args(["--only", "select", "--home",
                                            tmp_root])
        S.ASSETS = [tiny]
        rc2 = S.run(args2)
        shim = os.path.join(tmp_root, "ComfyUI", "custom_nodes",
                            S.SHIM_DIR, "__init__.py")
        ok("补丁节点是新写的 → 要重启",
           rc2 == 0 and calls and os.path.isfile(shim), (rc2, len(calls)))
        ok("补丁代码里有 invert_attention_mask（transformers 5.x 那个坑）",
           "invert_attention_mask" in open(shim, encoding="utf-8").read())
        # 再跑一次：这次补丁已在，不该再重启
        calls.clear()
        rc3 = S.run(S.build_parser().parse_args(["--only", "select", "--home",
                                                tmp_root]))
        ok("第二次跑就不再重启（幂等）", rc3 == 0 and not calls, len(calls))
    finally:
        S.ASSETS, S.NODES = saved_assets, saved_nodes
        S.server_online, S.restart_server = saved_online, saved_restart


def main():
    tmp_root = tempfile.mkdtemp(prefix="lb-setup-cli-")
    rows_root = tempfile.mkdtemp(prefix="lb-setup-rows-")
    policy_root = tempfile.mkdtemp(prefix="lb-setup-policy-")
    try:
        test_table()
        test_tiers()
        test_nodes()
        test_find()
        test_download()
        test_check(rows_root)
        test_cli(tmp_root)
        test_restart_policy(policy_root)
    finally:
        for d in (tmp_root, rows_root, policy_root):
            shutil.rmtree(d, ignore_errors=True)

    print("\n" + "-" * 52)
    # 收尾格式要和 run_plugin_checks.COUNT_RE 对得上（「通过 N 项，失败 M 项」）
    print("通过 %d 项，失败 %d 项" % (PASS, len(FAIL)))
    for f in FAIL:
        print("  ✗", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
