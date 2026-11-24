#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · ComfyUI 目录配置 + 自动启动 —— 插件与回归脚本共用
 ---------------------------------------------------------------------------
 purpose   用户机器上 ComfyUI 可能装在 D:\\ComfyUI、C:\\ComfyUI、某个便携
           包、或者自己 git clone 的目录里；也可能连启动脚本都没有，只有
           main.py + 一份嵌入式 Python。这一层做两件事：
             1. **记住用户手填的目录**（一个 JSON，插件界面上点「选择文件夹」
                就能存下来），下回不用再点；
             2. **连不上时把 ComfyUI 自己拉起来**——隐藏窗口、输出写日志、
                轮询 /system_stats 等它就绪，起不来就把日志尾几行原样带回去。
           Config file + hidden auto-start for a local ComfyUI.

 约束       **只用标准库**：GIMP 3 内嵌 Python 没有 requests，回归脚本又跑在
           系统 Python 上。HTTP 用 urllib，进程用 subprocess。

 为什么不用 start-comfyui.bat：那个 bat 是给人双击的（开控制台、末尾 pause），
           插件里调它必然会多一个关不掉的窗口。这里直接 python main.py 起，
           bat 只当成「有 bat 但没找到 python」时的最后退路。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import glob
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

# 配置文件路径可以盖掉（回归脚本用临时目录，绝不碰用户的真配置）
CONFIG_ENV = "LB_COMFY_CONFIG"
# 关掉自动启动（回归脚本用，也是「我不想让它自己起进程」的开关）
AUTOSTART_ENV = "LB_COMFY_AUTOSTART"
# 兼容老版本：只配了目录、没有配置文件的人
HOME_ENV = "LB_COMFY_HOME"
URL_ENV = "LB_COMFY_URL"

DEFAULT_SERVER = "http://127.0.0.1:8188"
START_TIMEOUT = 180.0      # 冷启动 + 加载底模，机械盘上两分钟也有过
PROBE_TIMEOUT = 2.5

_LOG_NAME = "comfyui.log"
_RUN_NAME = "comfyui-run.json"

_DEFAULTS = {
    "home": "",          # 用户手填的 ComfyUI 目录（可以是源码目录，也可以是包着 ComfyUI/ 的外层）
    "python": "",        # 手填的解释器；空 = 自动找
    "url": "",           # 空 = http://127.0.0.1:8188
    "auto_start": True,  # 连不上时自动拉起
    "extra_args": "",    # 追加给 main.py 的参数（比如 --lowvram）
}


# ---- 配置文件 ---------------------------------------------------------------

def config_dir():
    """配置放哪：%APPDATA%\\SuperMrWang（Windows）/ ~/.config/SuperMrWang。"""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
    return os.path.join(base, "SuperMrWang")


def config_path():
    override = (os.environ.get(CONFIG_ENV) or "").strip()
    if override:
        return os.path.abspath(override)
    return os.path.join(config_dir(), "comfyui.json")


def runtime_path():
    return os.path.join(os.path.dirname(config_path()), _RUN_NAME)


def default_log_path():
    return os.path.join(os.path.dirname(config_path()), _LOG_NAME)


def load():
    """读配置；文件坏了就当默认值（不抛异常，绝不因为一个坏 JSON 让插件罢工）。"""
    cfg = dict(_DEFAULTS)
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for key in _DEFAULTS:
                if key in data and data[key] is not None:
                    cfg[key] = data[key]
    except (OSError, ValueError):
        pass
    if not cfg.get("home"):
        # 老用户只设过环境变量：认下来，但写下一次就变成配置文件
        env = (os.environ.get(HOME_ENV) or "").strip().strip('"')
        if env:
            cfg["home"] = os.path.normpath(env)
    return cfg


def save(cfg):
    """原子写：先写 .tmp 再 replace，写到一半断电也不会留下半截 JSON。"""
    out = {}
    for key, default in _DEFAULTS.items():
        value = cfg.get(key, default)
        out[key] = default if value is None else value
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return out


def set_home(home, python="", **extra):
    """把「用户选的目录」写进配置。返回 (cfg, detect 结果)。"""
    cfg = load()
    cfg["home"] = os.path.normpath(os.path.expanduser(home.strip().strip('"'))) \
        if home else ""
    if python is not None:
        cfg["python"] = os.path.normpath(os.path.expanduser(python.strip())) \
            if python else ""
    for key, value in extra.items():
        if key in _DEFAULTS:
            cfg[key] = value
    cfg = save(cfg)
    return cfg, detect(cfg["home"], cfg)


def set_auto_start(flag):
    cfg = load()
    cfg["auto_start"] = bool(flag)
    return save(cfg)


# ---- 目录探测 ---------------------------------------------------------------

def guess_homes():
    """没配置时按顺序猜。只用于「第一次打开对话框」的建议，不写盘。"""
    out = []
    env = (os.environ.get(HOME_ENV) or "").strip().strip('"')
    if env:
        out.append(os.path.normpath(env))
    home = os.path.expanduser("~")
    out += [os.path.join(home, "SuperMrWang-AI"),
            os.path.join(home, "ComfyUI"),
            os.path.join(home, "Documents", "ComfyUI"),
            "C:/ComfyUI", "D:/ComfyUI", "E:/ComfyUI",
            "D:/ComfyUI/ComfyUI"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(os.path.join(local, "Programs", "ComfyUI"))
    seen, uniq = set(), []
    for p in out:
        key = os.path.normcase(os.path.normpath(p))
        if key not in seen:
            seen.add(key)
            uniq.append(os.path.normpath(p))
    return uniq


def configured_home(cfg=None):
    """**用户明确选过的**目录；没选过就是空串。

    自动启动只用这个——猜出来的目录可以用来「在对话框里提示你装在哪了」，
    但不能拿来起进程：猜错一次就是「用另一个 Python 起了别人的 ComfyUI」，
    报错还全是 ModuleNotFoundError，比不启动难查得多（2026-11-23 回归里踩到）。
    """
    cfg = cfg or load()
    home = (cfg.get("home") or "").strip()
    return os.path.normpath(home) if home and os.path.isdir(home) else ""


def resolve_home(cfg=None):
    """显示用：配置里的（存在才算）→ 猜出来的第一个像 ComfyUI 的。"""
    cfg = cfg or load()
    home = configured_home(cfg)
    if home:
        return home
    for cand in guess_homes():
        if os.path.isdir(cand):
            det = detect(cand, cfg)
            if det.get("main") or det.get("bat"):
                return cand
    return (cfg.get("home") or "").strip()


def _python_names():
    if os.name == "nt":
        return ["python.exe", os.path.join("python", "python.exe"),
                # tools/setup_ai.py 装出来的就是这个布局：root/py/python.exe
                # 少了这一条，「用它装的 ComfyUI」在插件里会被判成
                # 「找到 main.py 但没有解释器」，自动启动直接失效。
                os.path.join("py", "python.exe"),
                os.path.join("python_embeded", "python.exe"),
                os.path.join("venv", "Scripts", "python.exe"),
                os.path.join(".venv", "Scripts", "python.exe"),
                os.path.join("env", "Scripts", "python.exe")]
    return ["bin/python3", "bin/python", "python3",
            os.path.join("venv", "bin", "python3"),
            os.path.join(".venv", "bin", "python3")]


def find_python(home, src, cfg=None):
    """找一个能跑 torch 的解释器。

    优先级：配置里手填的 → ComfyUI 源码目录里自带的 → 外层目录里的
    py312 / python_embeded / venv（setup_ai.py 就装成 `py312 + ComfyUI/` 这种
    结构）→ 同级的 py3xx 目录。找 Python 3.13 之前那类「系统 python 没装
    torch」的坑不去猜——用户手填的那个永远优先。
    """
    cfg = cfg or {}
    manual = (cfg.get("python") or "").strip()
    if manual and os.path.isfile(manual):
        return manual

    dirs = []
    for d in (home, src, os.path.dirname(src or home)):
        if d and d not in dirs:
            dirs.append(d)
    rel = _python_names()
    for d in dirs:
        for name in rel:
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return os.path.normpath(cand)
    # py312 / py311 / Python312 这种目录名不固定，扫一层
    for d in dirs:
        for pat in ("py3*/python.exe", "Python3*/python.exe", "Python3*/*/python.exe"):
            for cand in sorted(glob.glob(os.path.join(d, pat)), reverse=True):
                if os.path.isfile(cand):
                    return os.path.normpath(cand)
    return ""


def detect(home, cfg=None):
    """看这个目录像不像能跑的 ComfyUI。

    返回 dict：home / source（含 main.py 的目录）/ main / python / bat /
    models / ok / note。ok 的意思是「能启动」，不是「一定装全了」——
    有没有底模要等连上服务才知道。
    """
    cfg = cfg if cfg is not None else load()
    res = {"home": home or "", "source": "", "main": "", "python": "",
           "bat": "", "models": "", "ok": False, "note": ""}
    if not home:
        res["note"] = "no folder configured"
        return res
    if not os.path.isdir(home):
        res["note"] = "folder not found"
        return res

    src = ""
    if os.path.isfile(os.path.join(home, "main.py")):
        src = home
    elif os.path.isfile(os.path.join(home, "ComfyUI", "main.py")):
        src = os.path.join(home, "ComfyUI")
    res["source"] = src
    if src:
        res["main"] = os.path.join(src, "main.py")
        res["models"] = os.path.join(src, "models", "checkpoints")

    for cand in (os.path.join(home, _start_bat_name()),
                 os.path.join(home, "ComfyUI", _start_bat_name()),
                 os.path.join(os.path.dirname(home), _start_bat_name())):
        if os.path.isfile(cand):
            res["bat"] = os.path.normpath(cand)
            break

    res["python"] = find_python(home, src, cfg)
    res["ok"] = bool(src and (res["python"] or res["bat"]))
    if not src and not res["bat"]:
        res["note"] = "no main.py found (pick the folder that contains main.py)"
    elif src and not res["python"] and not res["bat"]:
        res["note"] = ("found main.py but no python.exe — set the interpreter "
                       "or add a start script")
    return res


def _start_bat_name():
    return "start-comfyui.bat" if os.name == "nt" else "start-comfyui.sh"


# ---- 探活 -------------------------------------------------------------------

def normalize_server(server=""):
    s = (server or os.environ.get(URL_ENV) or load().get("url")
         or DEFAULT_SERVER).strip()
    if not s:
        s = DEFAULT_SERVER
    if "://" not in s:
        s = "http://" + s
    return s.rstrip("/")


def port_of(server):
    try:
        return int(server.rsplit(":", 1)[-1].split("/")[0])
    except (ValueError, IndexError):
        return 8188


def free_port():
    """拿一个当前空着的端口（回归脚本用；真机上没人调）。"""
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def probe(server="", timeout=PROBE_TIMEOUT):
    """GET /system_stats。不抛异常：{"ok", "version", "error"}。"""
    url = normalize_server(server) + "/system_stats"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.URLError as exc:
        return {"ok": False, "version": "", "error": str(getattr(exc, "reason", exc))}
    except OSError as exc:
        return {"ok": False, "version": "", "error": str(exc)}
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {"ok": False, "version": "", "error": "not a ComfyUI response"}
    system = (data.get("system") or {}) if isinstance(data, dict) else {}
    return {"ok": True, "version": str(system.get("comfyui_version") or ""),
            "error": ""}


def is_online(server=""):
    return probe(server, timeout=1.0)["ok"]


# ---- 启停 -------------------------------------------------------------------

def _env_for_child():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # 国内拉底模走镜像；用户自己设过就不动
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    return env


def _flags():
    if os.name == "nt":
        # CREATE_NO_WINDOW：不弹控制台；CREATE_NEW_PROCESS_GROUP：Ctrl+C 不串味
        return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    return 0


def launch(server="", extra=None, cfg=None):
    """把 ComfyUI 起起来（隐藏窗口，输出进日志）。返回 dict。

    cmd 里的参数刻意和 start-comfyui.bat 对齐：--listen 127.0.0.1 只让本机
    访问（不要暴露到局域网），--disable-auto-launch 免得它顺手开浏览器。
    """
    cfg = cfg or load()
    # 只认用户手选的目录：见 configured_home() 的注释
    home = configured_home(cfg)
    det = detect(home, cfg)
    if not det["ok"]:
        return {"ok": False, "pid": 0, "cmd": [], "log": "", "error":
                "ComfyUI folder not usable: %s (%s)"
                % (home or "?", det["note"] or "unknown")}

    srv = normalize_server(server or cfg.get("url") or DEFAULT_SERVER)
    port = port_of(srv)
    args = [str(a) for a in (extra or [])]
    if not args:
        raw = (cfg.get("extra_args") or "").strip()
        args = raw.split() if raw else []

    if det["main"] and det["python"]:
        cmd = [det["python"], "-u", det["main"],
               "--listen", "127.0.0.1", "--port", str(port),
               "--disable-auto-launch"] + args
        cwd = os.path.dirname(det["main"])
    else:
        bat = det["bat"]
        if os.name == "nt":
            cmd = ["cmd.exe", "/c", bat] + args
        else:
            cmd = ["/bin/sh", bat] + args
        cwd = os.path.dirname(bat)

    log_path = os.path.join(os.path.dirname(config_path()), _LOG_NAME)
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        logf = open(log_path, "a", encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "pid": 0, "cmd": cmd, "log": "",
                "error": "cannot open log file: %s" % exc}

    logf.write("\n===== %s  launch =====\n    %s\n"
               % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(cmd)))
    logf.flush()
    kwargs = {"cwd": cwd, "env": _env_for_child(), "stdin": subprocess.DEVNULL,
              "stdout": logf, "stderr": subprocess.STDOUT, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = _flags()
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except OSError as exc:
        logf.write("spawn failed: %s\n" % exc)
        logf.close()
        return {"ok": False, "pid": 0, "cmd": cmd, "log": log_path,
                "error": "cannot start ComfyUI: %s" % exc}
    finally:
        try:
            logf.close()          # 子进程已持有自己的句柄
        except OSError:
            pass

    _write_runtime({"pid": proc.pid, "started_at": time.time(),
                    "log": log_path, "cmd": cmd, "server": srv})
    return {"ok": True, "pid": proc.pid, "cmd": cmd, "log": log_path,
            "error": ""}


def _write_runtime(data):
    try:
        path = runtime_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def runtime():
    try:
        with open(runtime_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def pid_alive(pid):
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            # tasklist 的输出跟着系统代码页走（中文 Windows 是 GBK），按 utf-8
            # 解码会直接 UnicodeDecodeError——这里只要「输出里有没有这个 pid」，
            # 所以拿 bytes 比就行，别解码。
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                                 capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        return str(pid).encode("ascii") in (out.stdout or b"")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def tail(path="", lines=15):
    """日志尾几行。ComfyUI 起不来时，答案几乎总在这几行里。"""
    path = path or runtime().get("log") or default_log_path()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError:
        return ""
    rows = [r for r in data.splitlines() if r.strip()]
    return "\n".join(rows[-int(lines):])


def wait_ready(server="", timeout=START_TIMEOUT, pid=0, log_path="",
               interval=1.0):
    """轮询到 /system_stats 通为止；进程中途挂了就立刻返回，别干等。"""
    t0 = time.monotonic()
    last = ""
    while time.monotonic() - t0 < float(timeout):
        res = probe(server, timeout=2.0)
        if res["ok"]:
            return {"ok": True, "waited": time.monotonic() - t0,
                    "version": res["version"], "log": tail(log_path, 5)}
        last = res["error"]
        if pid and not pid_alive(pid):
            return {"ok": False, "waited": time.monotonic() - t0,
                    "error": "ComfyUI process exited during startup (%s)" % last,
                    "log": tail(log_path, 25), "exited": True}
        time.sleep(max(0.2, float(interval)))
    return {"ok": False, "waited": time.monotonic() - t0,
            "error": "ComfyUI did not answer within %.0f s" % float(timeout),
            "log": tail(log_path, 25)}


def ensure_running(server="", auto=None, timeout=None, on_progress=None):
    """**AI 操作前的一次性保险**：在线就返回，不在线且开了自动启动就拉起。

    返回 dict：ok / started / waited / version / error / log。
    绝不抛异常——调用方拿 ok 决定是继续跑还是走本地兜底。
    """
    srv = normalize_server(server)
    cfg = load()
    first = probe(srv, timeout=1.5)
    if first["ok"]:
        return {"ok": True, "started": False, "waited": 0.0,
                "version": first["version"], "error": "", "log": ""}

    auto = cfg.get("auto_start", True) if auto is None else bool(auto)
    if (os.environ.get(AUTOSTART_ENV) or "").strip().lower() in (
            "0", "off", "false", "no"):
        auto = False
    if not auto:
        return {"ok": False, "started": False, "error":
                "ComfyUI is not running and auto-start is off", "log": ""}

    home = configured_home(cfg)
    if not detect(home, cfg)["ok"]:
        guess = resolve_home(cfg)
        hint = ""
        if guess and guess != home:
            hint = (" Found a ComfyUI at %s — open AI Environment… and press "
                    "Choose folder… to confirm it." % guess)
        return {"ok": False, "started": False, "error":
                "ComfyUI is not running, and no usable ComfyUI folder is "
                "configured (%s). Use SuperMrWang → AI → AI Environment… to "
                "pick the folder.%s" % (home or "none", hint), "log": ""}

    if on_progress:
        on_progress("starting ComfyUI from %s …" % home)
    started = launch(srv, cfg=cfg)
    if not started["ok"]:
        return {"ok": False, "started": False, "error": started["error"],
                "log": tail(started.get("log", ""), 20)}

    ready = wait_ready(srv, timeout if timeout is not None else START_TIMEOUT,
                       pid=started["pid"], log_path=started["log"])
    if ready["ok"]:
        return {"ok": True, "started": True, "waited": ready["waited"],
                "version": ready.get("version", ""), "error": "",
                "log": ready.get("log", "")}

    # 显存/驱动那条路最容易踩：进程秒退、日志里有 "No CUDA GPUs" → 用 --cpu 再来一次。
    log = ready.get("log", "") or ""
    if ready.get("exited") and "cuda" in log.lower() and "--cpu" not in " ".join(started["cmd"]):
        if on_progress:
            on_progress("no CUDA device — retrying with --cpu …")
        started = launch(srv, extra=["--cpu"], cfg=cfg)
        if started["ok"]:
            ready = wait_ready(srv, timeout if timeout is not None else START_TIMEOUT,
                               pid=started["pid"], log_path=started["log"])
            if ready["ok"]:
                return {"ok": True, "started": True, "cpu": True,
                        "waited": ready["waited"], "version": ready.get("version", ""),
                        "error": "", "log": ready.get("log", "")}
    return {"ok": False, "started": True, "error": ready.get("error", ""),
            "log": ready.get("log", "")}


def stop():
    """停掉**我们自己起的**那个进程（不问系统里别的 ComfyUI）。"""
    run = runtime()
    pid = int(run.get("pid") or 0)
    if not pid_alive(pid):
        _write_runtime({})
        return {"ok": False, "error": "ComfyUI was not started by the plug-in "
                                      "(or already stopped)"}
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=20)
        else:
            os.kill(pid, 15)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}
    _write_runtime({})
    return {"ok": True, "error": ""}


def status(server=""):
    """对话框要的一屏状态。"""
    srv = normalize_server(server)
    cfg = load()
    home = resolve_home(cfg)
    det = detect(home, cfg)
    online = probe(srv, timeout=1.5)
    run = runtime()
    pid = int(run.get("pid") or 0)
    return {"server": srv, "online": online["ok"], "version": online["version"],
            "error": online["error"], "home": home, "detect": det,
            "auto_start": bool(cfg.get("auto_start", True)),
            "config": config_path(), "pid": pid if pid_alive(pid) else 0,
            "log": run.get("log") or default_log_path(),
            "tail": tail(run.get("log") or default_log_path(), 12) if not online["ok"] else ""}


if __name__ == "__main__":                       # 手工排查用
    st = status()
    print("config:", st["config"])
    print("server:", st["server"], "online:", st["online"], st["version"])
    print("home:", st["home"], "| detect:", st["detect"]["ok"], st["detect"]["main"],
          "|", st["detect"]["python"])
    print("auto_start:", st["auto_start"], "| pid:", st["pid"])
    if st["tail"]:
        print("--- log tail ---")
        print(st["tail"])
    if "--start" in sys.argv:
        res = ensure_running()
        print("ensure:", res)
