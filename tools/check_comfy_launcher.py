#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 tools/check_comfy_launcher.py · comfy_launcher 的回归（不需要 GIMP、不需要显卡）
 ---------------------------------------------------------------------------
 测什么
   1. 配置文件：路径可被 LB_COMFY_CONFIG 盖掉、save/load 往返、坏 JSON 不炸、
      set_home 规范化、auto_start 落盘
   2. 目录探测：外层目录（ComfyUI/main.py）、源码目录本身、py312 / venv /
      python_embeded 三种解释器摆放、有 main.py 没解释器、只有 bat
   3. 地址解析：补协议、去尾斜杠、环境变量、配置里的 url
   4. **真起进程**：临时目录里造一个 stub ComfyUI（标准库 http.server，
      只答 /system_stats），用系统 python 当「ComfyUI 的解释器」，
      跑 ensure_running → 在线 → 再调一次不重启 → stop() → 端口关掉
   5. 失败路径：auto_start 关掉时不动手；目录没配时给的是「去 AI 环境里选」
      而不是 traceback；进程秒退时把日志尾带回来

 为什么第 4 条要真起进程：只测「launch 返回了 pid」等于没测——参数拼错、
  工作目录不对、日志句柄没交接，全都只有在真进程活下来时才暴露。

 跑法   python tools/check_comfy_launcher.py
 ==========================================================================="""

import json
import os
import shutil
import socket
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

PASS = 0
FAIL = []
SECTION = ""

STUB = r'''
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = 8188
args = sys.argv[1:]
for i, a in enumerate(args):
    if a == "--port" and i + 1 < len(args):
        port = int(args[i + 1])

print("stub comfy listening on %d" % port, flush=True)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/system_stats"):
            body = json.dumps({"system": {"comfyui_version": "stub-1.0"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", port), H).serve_forever()
'''

# 立即退出、日志里带 CUDA 报错：ensure_running 应该把日志尾带回来
CRASH = r'''
import sys
print("RuntimeError: No CUDA GPUs are available", flush=True)
print("torch.cuda.is_available() is False", flush=True)
sys.exit(3)
'''

TMP = tempfile.mkdtemp(prefix="lb-launcher-test-")
CONFIG = os.path.join(TMP, "conf", "comfyui.json")


def section(name):
    global SECTION
    SECTION = name
    print("\n" + name)


def ok(label, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append("%s / %s（%s）" % (SECTION, label, detail))
        print("  FAIL %s  %s" % (label, detail))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def mk_tree(name, python_rel="py312/python.exe", main=STUB, bat=False):
    """造一个假的安装目录：<name>/ComfyUI/main.py + <name>/py312/python.exe。"""
    home = os.path.join(TMP, name)
    write(os.path.join(home, "ComfyUI", "main.py"), main)
    if python_rel:
        write(os.path.join(home, python_rel), "stub")
    if bat:
        write(os.path.join(home, "start-comfyui.bat"), "@echo off\r\n")
    return home


def port_open(port, timeout=1.0):
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def main():
    # 先把环境隔离干净：绝不读用户真配置，也绝不动用户真的 ComfyUI
    # run_plugin_checks 会给所有子进程设 LB_COMFY_AUTOSTART=0（免得别的套件
    # 真起服务）；这个套件要测的正是自动启动，所以先摘掉，后面再单独测开关。
    for key in ("LB_COMFY_HOME", "LB_COMFY_URL", "LB_COMFY_AUTOSTART"):
        os.environ.pop(key, None)
    os.environ["LB_COMFY_CONFIG"] = CONFIG

    import comfy_launcher as CL

    # ---- 1. 配置文件 ----
    section("1. 配置文件")
    ok("config_path 受 LB_COMFY_CONFIG 控制",
       CL.config_path() == os.path.abspath(CONFIG), CL.config_path())
    cfg = CL.load()
    ok("没文件时给默认值", cfg["home"] == "" and cfg["auto_start"] is True, cfg)
    cfg["home"] = "D:/somewhere"
    cfg["no_such_key"] = 1
    saved = CL.save(cfg)
    ok("save 丢掉未知键", "no_such_key" not in saved, saved)
    back = CL.load()
    ok("save/load 往返", back["home"] == "D:/somewhere", back["home"])
    with open(CONFIG, "w", encoding="utf-8") as fh:
        fh.write("{ this is not json")
    broken = CL.load()
    ok("坏 JSON 退回默认值、不抛异常",
       broken["home"] == "" and broken["auto_start"] is True, broken)
    ok("set_auto_start 落盘", CL.set_auto_start(False)["auto_start"] is False)
    CL.set_auto_start(True)
    ok("set_auto_start 能再打开", CL.load()["auto_start"] is True)

    # ---- 2. 目录探测 ----
    section("2. 目录探测")
    home = mk_tree("good")
    det = CL.detect(home)
    ok("外层目录：找到 main.py",
       det["ok"] and det["main"].endswith(os.path.join("ComfyUI", "main.py")),
       det)
    ok("外层目录：找到 py312 解释器",
       det["python"].endswith("python.exe") and "py312" in det["python"],
       det["python"])
    ok("模型目录指向 ComfyUI/models/checkpoints",
       det["models"].endswith(os.path.join("models", "checkpoints")), det["models"])

    src_home = os.path.join(home, "ComfyUI")
    det_src = CL.detect(src_home)
    ok("直接选源码目录也行",
       det_src["ok"] and det_src["source"] == os.path.normpath(src_home), det_src)

    bare = mk_tree("bare", python_rel="")
    det_bare = CL.detect(bare)
    ok("有 main.py 没解释器 → 不可启动",
       not det_bare["ok"] and "python" in det_bare["note"], det_bare)

    venv = mk_tree("venv", python_rel="venv/Scripts/python.exe")
    ok("venv/Scripts 里的解释器也认", CL.detect(venv)["ok"], CL.detect(venv))

    embed = mk_tree("embed", python_rel="python_embeded/python.exe")
    ok("python_embeded 里的解释器也认", CL.detect(embed)["ok"], CL.detect(embed))

    # tools/setup_ai.py 装出来的布局是 root/py/python.exe（目录就叫 py，
    # 不是 py312）。2026-11-24 之前这里没认，导致「用它装的 ComfyUI」在插件
    # 里被判定成有 main.py 没解释器，自动启动完全失效。
    pybare = mk_tree("pybare", python_rel="py/python.exe")
    ok("setup_ai.py 的 py/python.exe 也认", CL.detect(pybare)["ok"],
       CL.detect(pybare))

    batty = mk_tree("batty", python_rel="", bat=True)
    ok("没解释器但有 start-comfyui.bat → 可启动", CL.detect(batty)["ok"],
       CL.detect(batty))

    ok("目录不存在 → 不可启动且说清原因",
       not CL.detect(os.path.join(TMP, "nope"))["ok"],
       CL.detect(os.path.join(TMP, "nope")))
    ok("空配置 → 不可启动", not CL.detect("")["ok"])

    manual = mk_tree("manual")
    cfg2, det2 = CL.set_home(manual)
    ok("set_home 写进配置并能探测到", det2["ok"] and CL.load()["home"] ==
       os.path.normpath(manual), (cfg2, det2))
    cfg3, det3 = CL.set_home(manual, python=sys.executable)
    ok("手填解释器优先于自动探测", det3["python"] == os.path.normpath(sys.executable),
       det3["python"])

    # ---- 3. 地址解析 ----
    section("3. 地址解析")
    ok("缺协议自动补 http://",
       CL.normalize_server("127.0.0.1:9000") == "http://127.0.0.1:9000")
    ok("尾斜杠去掉",
       CL.normalize_server("http://127.0.0.1:8188/") == "http://127.0.0.1:8188")
    os.environ["LB_COMFY_URL"] = "http://127.0.0.1:7777"
    ok("环境变量 LB_COMFY_URL 生效", CL.normalize_server() == "http://127.0.0.1:7777")
    os.environ.pop("LB_COMFY_URL")
    CL.save({"url": "http://127.0.0.1:7001", "home": manual, "auto_start": True})
    ok("配置里的 url 生效", CL.normalize_server() == "http://127.0.0.1:7001")
    CL.save({"url": "", "home": manual, "auto_start": True})
    ok("都没配时回到 8188", CL.port_of(CL.normalize_server()) == 8188)
    ok("port_of 从 url 取端口", CL.port_of("http://127.0.0.1:1234") == 1234)

    # ---- 4. 真起进程 ----
    section("4. 真起进程（stub ComfyUI）")
    port = CL.free_port()
    server = "http://127.0.0.1:%d" % port
    ok("stub 启动前端口是空的", not port_open(port))
    cfg = CL.load()
    cfg["home"] = manual
    cfg["python"] = sys.executable
    cfg["url"] = server
    cfg["auto_start"] = True
    CL.save(cfg)

    t0 = time.time()
    res = CL.ensure_running(server, timeout=40)
    took = time.time() - t0
    ok("ensure_running 把 stub 拉起来了", res.get("ok"), res)
    ok("报告里 started=True", res.get("started") is True, res)
    ok("拿到版本号", res.get("version") == "stub-1.0", res.get("version"))
    ok("端口真的开了", port_open(port), port)
    ok("进程还活着", CL.pid_alive(CL.runtime().get("pid")), CL.runtime())
    log = res.get("log") or ""
    ok("日志里有 stub 的启动行",
       "stub comfy listening" in (log or CL.tail()), log[-300:])
    ok("启动耗时在超时之内", took < 40, took)

    again = CL.ensure_running(server, timeout=10)
    ok("已经在跑时不重复启动",
       again.get("ok") and again.get("started") is False, again)

    st = CL.status(server)
    ok("status 说在线", st["online"] and st["version"] == "stub-1.0", st["online"])
    ok("status 带配置路径与自动启动状态",
       st["config"] == CL.config_path() and st["auto_start"] is True, st)
    ok("status 认出 pid", st["pid"] > 0, st["pid"])
    ok("在线时不再贴日志尾", not st["tail"], st["tail"][:80])

    stop = CL.stop()
    ok("stop 报成功", stop["ok"], stop)
    deadline = time.time() + 8
    while time.time() < deadline and port_open(port, 0.3):
        time.sleep(0.2)
    ok("stop 之后端口关了", not port_open(port), port)
    ok("stop 之后 pid 不再存活", not CL.pid_alive(CL.runtime().get("pid")),
       CL.runtime())
    ok("再 stop 一次不炸（只说没得停）", CL.stop()["ok"] is False)

    # ---- 5. 失败路径 ----
    section("5. 失败路径")
    port2 = CL.free_port()
    server2 = "http://127.0.0.1:%d" % port2
    cfg = CL.load()
    cfg["auto_start"] = False
    cfg["url"] = server2
    CL.save(cfg)
    off = CL.ensure_running(server2, timeout=10)
    ok("auto_start 关掉时不动手",
       off.get("ok") is False and "auto-start is off" in (off.get("error") or ""),
       off)
    ok("关掉自动启动时端口一直是空的", not port_open(port2), port2)

    cfg["auto_start"] = True
    cfg["home"] = ""
    CL.save(cfg)
    os.environ["LB_COMFY_HOME"] = ""
    nohome = CL.ensure_running(server2, timeout=5, auto=True)
    ok("没配目录时提示去 AI 环境里选",
       "AI Environment" in (nohome.get("error") or ""), nohome)
    ok("没配目录时不假装启动成功", nohome.get("ok") is False, nohome)
    ok("没配目录时绝不去「猜」一个目录来启动（猜错会起错的 Python）",
       nohome.get("started") is False
       and not CL.pid_alive(CL.runtime().get("pid")), nohome)

    crash_home = mk_tree("crash", python_rel="py312/python.exe", main=CRASH)
    cfg = CL.load()
    cfg["home"] = crash_home
    cfg["python"] = sys.executable
    cfg["url"] = server2
    cfg["auto_start"] = True
    CL.save(cfg)
    crash = CL.ensure_running(server2, timeout=30)
    ok("进程秒退 → 返回失败", crash.get("ok") is False, crash)
    ok("失败原因写明进程退出了",
       "exited" in (crash.get("error") or "").lower(), crash.get("error"))
    ok("把日志尾带回来（能看出是 CUDA 问题）",
       "CUDA" in (crash.get("log") or ""), (crash.get("log") or "")[-200:])

    # LB_COMFY_AUTOSTART=0：回归脚本必须能关掉自动启动，否则「故意连空端口」
    # 的用例会真的拉起一个 ComfyUI（11-23 在磨皮回归里撞到过）。
    cfg = CL.load()
    cfg["home"] = manual
    cfg["auto_start"] = True
    cfg["url"] = server2
    CL.save(cfg)
    os.environ["LB_COMFY_AUTOSTART"] = "0"
    forced_off = CL.ensure_running(server2, timeout=5)
    ok("环境变量能强制关掉自动启动",
       forced_off.get("ok") is False
       and "auto-start is off" in (forced_off.get("error") or ""), forced_off)
    ok("强制关掉时不会真起进程", not port_open(port2), port2)
    os.environ.pop("LB_COMFY_AUTOSTART", None)

    launch_fail = CL.launch(server2)
    ok("launch 永远返回结构化结果（不抛异常）",
       isinstance(launch_fail, dict) and "ok" in launch_fail, launch_fail)

    print("\n" + ("全部通过：%d 条断言" % PASS if not FAIL
                  else "失败 %d / %d：\n  " % (len(FAIL), len(FAIL) + PASS)
                  + "\n  ".join(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        try:
            sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))
            import comfy_launcher
            comfy_launcher.stop()
        except Exception:
            pass
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
