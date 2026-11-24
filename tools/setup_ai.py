#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键装本机 ComfyUI，给 plugin/ai-inpaint 用。

只用标准库（目标是「用户机器上什么都没装」也能跑）：它自己下载一个嵌入式
Python，再用那个 Python 去装 torch 和 ComfyUI，完全不碰系统环境。

    python tools/setup_ai.py                 # 装到 %USERPROFILE%\\SuperMrWang-AI
    python tools/setup_ai.py --dir D:\\lb-ai  # 换目录
    python tools/setup_ai.py --model sdxl    # 底模换成 SDXL（1024²，约 6.9 GB）
    python tools/setup_ai.py --cpu           # 没有 N 卡：装 CPU 版（能跑，很慢）
    python tools/setup_ai.py --verify        # 只体检已装好的环境

为什么不是「下载一个 zip 解压完事」：ComfyUI 依赖 torch 的 CUDA 轮子
（~2.5 GB）和一份底模（2~7 GB），打进包里既过不了分发许可，也没人愿意下
一个 10 GB 的安装包。所以这里是「下载器 + 无人值守安装」。
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

# ---- 常量 -------------------------------------------------------------------

PY_VER = "3.12.8"
PY_EMBED_URL = ("https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip"
                % (PY_VER, PY_VER))
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# GitHub 直连在国内常年不通，按顺序试；200 才算数（有的代理会返回 403 页面）
COMFY_SOURCES = [
    "https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip",
    "https://ghproxy.net/https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip",
    "https://gh-proxy.com/https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip",
]
GITHUB_PROXY_PREFIXES = ["", "https://ghproxy.net/", "https://gh-proxy.com/"]

MODELS = {
    # 512² 一块，5 秒一张，小面积够用；体积也最小
    "sd15": {
        "name": "v1-5-pruned-emaonly-fp16.safetensors",
        "urls": [
            "https://hf-mirror.com/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly-fp16.safetensors",
            "https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly-fp16.safetensors",
        ],
        "bytes": 2132696762,
        "note": "SD1.5 fp16",
    },
    # 1024²，细节明显好一档，8 GB 显存能跑（实测 14~19 秒）
    "sdxl": {
        "name": "sd_xl_base_1.0.safetensors",
        "urls": [
            "https://hf-mirror.com/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
            "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
        ],
        "bytes": 6938078334,
        "note": "SDXL base 1.0",
    },
}

MIN_FREE_GB = 16          # Python + torch + ComfyUI + 一份底模，松一点
TORCH_INDEX = {
    "cu128": "https://download.pytorch.org/whl/cu128",
    "cpu": "https://download.pytorch.org/whl/cpu",
}

# 装完 ComfyUI 之后要不要顺手把插件要的 AI 资产也下齐（转发给 setup_comfy.py）。
# 默认只下「能填充」那一档：一张 4.3 GB 的 SD1.5-inpaint。SDXL / 按名称选区 /
# 抠图加起来再多 7.7 GB，让用户自己决定什么时候补。
ASSET_TIERS = ("none", "min", "std", "full")

# 普通 PyPI 包走国内镜像：直连 pypi.org 在多数国内网络下是几十 KB/s，
# 32 个依赖能装半小时。CUDA 轮子例外——torch 的 cu128 轮子只有官方源有。
PYPI_MIRROR = os.environ.get("LB_PYPI_MIRROR",
                             "https://pypi.tuna.tsinghua.edu.cn/simple")

# ComfyUI 的 requirements.txt 里带的 torch 版本号和我们装的 CUDA 轮子对不上，
# 必须整行剔掉；但**只剔这三行**——之前用 grep -v "^torch" 顺手把 torchsde
# 也删了，结果缺依赖跑不起来。
TORCH_REQ = re.compile(r"^(torch|torchvision|torchaudio)\b", re.I)


# ---- 输出 -------------------------------------------------------------------

def say(msg):
    print(msg, flush=True)


def step(n, total, msg):
    say("\n[%d/%d] %s" % (n, total, msg))


def warn(msg):
    say("  ! " + msg)


def die(msg):
    say("\n安装失败：" + msg)
    sys.exit(1)


# ---- 下载 -------------------------------------------------------------------

def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0


def fetch(url, dest, expect_bytes=None, retries=2, label=None):
    """带进度和续传的下载；失败换下一个源由调用方负责。"""
    label = label or os.path.basename(dest)
    tmp = dest + ".part"
    for attempt in range(retries + 1):
        have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        if expect_bytes and have >= expect_bytes:
            os.replace(tmp, dest)
            return dest
        req = urllib.request.Request(url, headers={"User-Agent": "SuperMrWang-setup"})
        if have:
            req.add_header("Range", "bytes=%d-" % have)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or 0) + have
                mode = "ab" if have and resp.status == 206 else "wb"
                if mode == "wb":
                    have = 0
                t0, last = time.time(), 0.0
                with open(tmp, mode) as fh:
                    while True:
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        fh.write(chunk)
                        have += len(chunk)
                        now = time.time()
                        if now - last > 0.4:      # 每 0.4 秒刷一次进度
                            last = now
                            pct = ("%5.1f%%" % (have * 100.0 / total)) if total else "  --  "
                            speed = have / max(now - t0, 0.001) / 1048576.0
                            sys.stdout.write("\r  %s  %s / %s  %5.1f MB/s" % (
                                pct, human(have),
                                human(total) if total else "?", speed))
                            sys.stdout.flush()
            sys.stdout.write("\r  %s  %s / %s  完成\n" % (
                "100.0%", human(have), human(expect_bytes or have)))
            sys.stdout.flush()
            if expect_bytes and have < expect_bytes:
                raise IOError("下到的比预期小：%d < %d" % (have, expect_bytes))
            os.replace(tmp, dest)
            return dest
        except Exception as exc:                                  # noqa: BLE001
            sys.stdout.write("\n")
            if attempt >= retries:
                raise
            warn("%s 第 %d 次失败（%s），续传重试" % (label, attempt + 1, exc))
    return dest


def fetch_first(urls, dest, expect_bytes=None, label=None):
    last = None
    for i, url in enumerate(urls):
        try:
            return fetch(url, dest, expect_bytes=expect_bytes, label=label)
        except Exception as exc:                                  # noqa: BLE001
            last = exc
            if i + 1 < len(urls):
                warn("%s 源不通（%s），换下一个" % (host_of(url), exc))
    raise IOError("所有下载源都失败：%s" % last)


def host_of(url):
    return re.sub(r"^https?://([^/]+).*$", r"\1", url)


# ---- 环境检查 ---------------------------------------------------------------

def gpu_info():
    """返回 (名字, 显存 MiB, 驱动版本)；没 N 卡返回 None。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        for cand in (r"C:\Windows\System32\nvidia-smi.exe",
                     r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
            if os.path.exists(cand):
                exe = cand
                break
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20).stdout.strip()
        if not out:
            return None
        first = out.splitlines()[0]
        name, mem, drv = [p.strip() for p in first.split(",")[:3]]
        return name, int(float(mem)), drv
    except Exception:                                             # noqa: BLE001
        return None


def free_gb(path):
    try:
        target = path
        while target and not os.path.exists(target):
            parent = os.path.dirname(target)
            if parent == target:
                break
            target = parent
        return shutil.disk_usage(target or ".").free / (1024.0 ** 3)
    except Exception:                                             # noqa: BLE001
        return 0.0


# ---- 各步骤 -----------------------------------------------------------------

def ensure_python(root):
    """目标目录里的嵌入式 Python；已有就直接复用（换底模时不用重装）。"""
    py = os.path.join(root, "py", "python.exe")
    if os.path.exists(py):
        ver = subprocess.run([py, "-c", "import sys;print(sys.version.split()[0])"],
                             capture_output=True, text=True).stdout.strip()
        say("  已有 Python %s，复用" % ver)
        return py

    say("  下载嵌入式 Python %s（约 11 MB）" % PY_VER)
    zpath = os.path.join(root, "python-embed.zip")
    fetch(PY_EMBED_URL, zpath, label="python-embed.zip")
    py_dir = os.path.join(root, "py")
    os.makedirs(py_dir, exist_ok=True)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(py_dir)
    os.remove(zpath)

    # embeddable 默认不认 site-packages、也不跑 site.py，必须改 ._pth。
    # 少这一步 → pip 装完 import 不到任何东西。
    for fn in os.listdir(py_dir):
        if fn.endswith("._pth"):
            pth = os.path.join(py_dir, fn)
            lines = ["python312.zip", ".", "Lib\\site-packages", "import site"]
            with open(pth, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            break
    os.makedirs(os.path.join(py_dir, "Lib", "site-packages"), exist_ok=True)
    return py


def ensure_pip(root, py):
    res = subprocess.run([py, "-m", "pip", "--version"], capture_output=True, text=True)
    if res.returncode == 0:
        say("  已有 pip，复用")
        return
    say("  装 pip（bootstrap.pypa.io）")
    gp = os.path.join(root, "get-pip.py")
    fetch(GET_PIP_URL, gp, label="get-pip.py")
    cmd = [py, gp, "--no-warn-script-location", "--no-cache-dir"]
    if PYPI_MIRROR:
        cmd += ["--index-url", PYPI_MIRROR]
    subprocess.run(cmd, check=True, cwd=root)
    os.remove(gp)


def pip(py, *args, cwd=None, check=True, index=None):
    cmd = [py, "-m", "pip", "install", "--disable-pip-version-check"]
    if index:
        cmd += ["--index-url", index]
    elif PYPI_MIRROR:
        cmd += ["-i", PYPI_MIRROR]
    cmd += list(args)
    return subprocess.run(cmd, cwd=cwd, check=check)


def ensure_comfyui(root, py):
    comfy = os.path.join(root, "ComfyUI")
    if os.path.exists(os.path.join(comfy, "main.py")):
        say("  ComfyUI 已在 %s，复用" % comfy)
        return comfy

    say("  下载 ComfyUI 源码（约 8 MB）")
    zpath = os.path.join(root, "comfyui.zip")
    fetch_first(COMFY_SOURCES, zpath, label="ComfyUI-master.zip")
    tmpdir = os.path.join(root, "_unzip")
    if os.path.isdir(tmpdir):
        shutil.rmtree(tmpdir, ignore_errors=True)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(tmpdir)
    inner = [d for d in os.listdir(tmpdir) if os.path.isdir(os.path.join(tmpdir, d))]
    if len(inner) != 1:
        die("ComfyUI 压缩包结构不对：%s" % inner)
    shutil.move(os.path.join(tmpdir, inner[0]), comfy)
    shutil.rmtree(tmpdir, ignore_errors=True)
    os.remove(zpath)
    return comfy


def install_torch(py, variant):
    index = TORCH_INDEX[variant]
    # 先问一句已装了什么：换底模/重跑时不该把 2.5 GB 再下一遍
    probe = subprocess.run([py, "-c", "import torch;print(torch.__version__)"],
                           capture_output=True, text=True)
    if probe.returncode == 0:
        cur = probe.stdout.strip()
        want_cuda = variant == "cu128" and "+cu" in cur
        want_cpu = variant == "cpu" and "+cu" not in cur
        if want_cuda or want_cpu:
            say("  已有 torch %s，跳过（要重装就先删掉 py 目录）" % cur)
            return
        warn("已有 torch %s 但和 %s 不符，重装" % (cur, variant))
    say("  下载 torch %s（约 2.5 GB，最慢的一步）" % variant)
    pip(py, "--no-cache-dir", "torch", "torchvision", "torchaudio", index=index)


def install_requirements(py, comfy):
    req = os.path.join(comfy, "requirements.txt")
    if not os.path.exists(req):
        warn("没有 requirements.txt，跳过")
        return
    keep, dropped = [], []
    with open(req, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                keep.append(line.rstrip())
                continue
            if TORCH_REQ.match(s):
                dropped.append(s)
                continue
            keep.append(s)
    say("  装 ComfyUI 依赖（剔除 %d 行 torch：%s）" % (len(dropped), ", ".join(dropped)))
    tmp = os.path.join(comfy, "requirements.setup.txt")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(keep) + "\n")
    try:
        pip(py, "--no-cache-dir", "-r", tmp)
    finally:
        os.remove(tmp)


def install_model(comfy, key):
    spec = MODELS[key]
    dest = os.path.join(comfy, "models", "checkpoints", spec["name"])
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) >= spec["bytes"]:
        say("  已有 %s，跳过" % spec["name"])
        return dest
    say("  下载底模 %s（%s，约 %.1f GB）"
        % (spec["note"], spec["name"], spec["bytes"] / (1024.0 ** 3)))
    fetch_first(spec["urls"], dest, expect_bytes=spec["bytes"],
                label=spec["name"])
    return dest


def write_launcher(root, variant):
    """写一个「双击就能起」的启动器。

    两件事必须做对，否则用户看到的就是「窗口一闪就关」：

    1. **没有显卡时自动加 --cpu**。torch 在 import 阶段就会因为
       `torch.cuda.current_device()` 抛 RuntimeError: No CUDA GPUs are
       available，ComfyUI 根本走不到起服务那一步。显卡被 Windows 停用
       （设备管理器里 Code 43）时也长这样，用户完全看不出是自己显卡的问题。
    2. **bat 里一个中文都不放**。cmd 在 chcp 65001 下是按字节偏移回读批处理
       文件的，中文行会漂移：实测 `for /f` 之后的行会被截断成
       “'xx' 不是内部或外部命令”，连 `goto` 标签之后的行也会被吞掉。
       所以中文提示一律写进 launcher.md，需要时用 `type` 原样打出来——
       `type` 只搬字节，不解析。

    CPU 版和 GPU 版只差一行探测：CPU 版直接 `set EXTRA=--cpu`。
    """
    bat = os.path.join(root, "start-comfyui.bat")
    port = 8188
    probe = ("set EXTRA=\n"
             '"%~dp0py\\python.exe" -c "import torch,sys;'
             'sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>nul\n'
             "if errorlevel 1 set EXTRA=--cpu")
    if variant == "cpu":
        probe = "set EXTRA=--cpu"

    body = """@echo off
chcp 65001 >nul
title ComfyUI (SuperMrWang AI)
set HF_ENDPOINT=https://hf-mirror.com
set PYTHONIOENCODING=utf-8
cd /d "%%~dp0ComfyUI"
%s
echo.
echo   ComfyUI  http://127.0.0.1:%d   %%EXTRA%%
if exist "%%~dp0launcher.md" type "%%~dp0launcher.md"
echo.
echo   Keep this window open. Closing it stops the server.
echo.
"%%~dp0py\\python.exe" main.py --listen 127.0.0.1 --port %d --disable-auto-launch %%EXTRA%% %%*
echo.
echo   Server stopped.
pause
""" % (probe, port, port)
    with open(bat, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(body)

    note = os.path.join(root, "launcher.md")
    if variant == "cpu":
        text = (
            "  [CPU 版]\n"
            "  这套环境用 CPU 跑：一张 512 长边约 1-3 分钟，慢但不报错。\n")
    else:
        text = (
            "  [上面如果显示 --cpu]\n"
            "  PyTorch 没看到可用显卡，这次 ComfyUI 用 CPU 启动。\n"
            "  一张 512 长边约 1-3 分钟，慢一些，但参考图照样能生成。\n"
            "\n"
            "  [显卡没被认到怎么办]\n"
            "  设备管理器 → 显示适配器，看 NVIDIA 那张卡是不是标着 Code 43。\n"
            "  是的话：先重启；重启无效就重装 NVIDIA 驱动\n"
            "  （官网 Game Ready，安装时选「自定义 → 执行清洁安装」）。\n")
    with open(note, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(text)
    return bat


def asset_bytes(tier):
    """这一档 AI 资产大约要占多少字节（用来提前算磁盘够不够）。"""
    if tier == "none":
        return 0
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import setup_comfy as S
        assets, _groups = S.select_assets(tier)
        return sum(a["size"] for a in assets)
    except Exception:                                             # noqa: BLE001
        return {"min": 4 * 1 << 30, "std": 12 * 1 << 30,
                "full": 24 * 1 << 30}.get(tier, 0)


def install_assets(root, py, tier):
    """把资产下载转发给 setup_comfy.py（它才是唯一那份台账）。

    用 --no-restart：这个脚本最后自己会起一次服务做自检，两边抢 8188 端口
    就会互相踩。节点包需要重启才注册，所以自检那次启动正好把新节点带起来。
    """
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "setup_comfy.py")
    cmd = [sys.executable, script, "--home", root, "--python", py,
           "--tier", tier, "--no-restart"]
    say("  → %s" % " ".join(cmd[1:]))
    return subprocess.run(cmd).returncode == 0


def probe_server(url="http://127.0.0.1:8188", timeout=3.0):
    try:
        with urllib.request.urlopen(url + "/system_stats", timeout=timeout) as r:
            return r.status == 200
    except Exception:                                             # noqa: BLE001
        return False


def checkpoints(url="http://127.0.0.1:8188"):
    import json
    try:
        with urllib.request.urlopen(url + "/object_info/CheckpointLoaderSimple",
                                    timeout=8) as r:
            d = json.load(r)
        return list(d["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0])
    except Exception:                                             # noqa: BLE001
        return []


def verify(root, py, comfy, start_server=True):
    """装完的自检：能不能 import、服务能不能起、底模在不在。"""
    say("\n自检")
    ok = True
    for mod in ("torch", "numpy", "PIL", "safetensors", "aiohttp"):
        r = subprocess.run([py, "-c", "import %s;print(%s.__version__)" % (mod, mod)],
                           capture_output=True, text=True, cwd=comfy)
        if r.returncode == 0:
            say("  [ok] %s %s" % (mod, r.stdout.strip()))
        else:
            say("  [!!] %s 导入失败：%s" % (mod, r.stderr.strip().splitlines()[-1:]))
            ok = False

    r = subprocess.run([py, "-c", "import torch;print(torch.cuda.is_available(),"
                                  " torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"],
                       capture_output=True, text=True, cwd=comfy)
    say("  cuda: %s" % r.stdout.strip())

    if probe_server():
        say("  服务已在运行，直接查")
        ck = checkpoints()
        say("  底模：%s" % (", ".join(ck) or "（空）"))
        return ok and bool(ck)
    if not start_server:
        return ok

    say("  启动服务（约 15 秒）…")
    proc = subprocess.Popen([py, "main.py", "--listen", "127.0.0.1", "--port", "8188",
                             "--disable-auto-launch"], cwd=comfy,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            if probe_server(timeout=2):
                break
            if proc.poll() is not None:
                say("  [!!] 服务启动后退出了")
                return False
            time.sleep(1)
        else:
            say("  [!!] 30 秒内没起来（看 ComfyUI/comfyui.log 或手动跑 start-comfyui.bat）")
            return False
        ck = checkpoints()
        say("  [ok] 服务在线，底模：%s" % (", ".join(ck) or "（空）"))
        ok = ok and bool(ck)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return ok


# ---- 主流程 -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="一键装本机 ComfyUI（给 SuperMrWang 的 AI Inpaint 插件用）")
    ap.add_argument("--dir", default=os.path.join(os.path.expanduser("~"),
                                                  "SuperMrWang-AI"),
                    help="安装目录（默认 ~/SuperMrWang-AI）")
    ap.add_argument("--model", choices=sorted(MODELS), default="sdxl",
                    help="装哪个底模（默认 sdxl；sd15 体积小一半、速度约 3 倍）")
    ap.add_argument("--cpu", action="store_true", help="没有 N 卡时用")
    ap.add_argument("--no-model", action="store_true", help="先不下载底模")
    ap.add_argument("--assets", choices=ASSET_TIERS, default="min",
                    help="顺手下插件要的 AI 资产：min 只 SD1.5-inpaint（默认），"
                         "std 加 SDXL/选区/抠图，full 再加 Flux，none 不下")
    ap.add_argument("--verify", action="store_true", help="只体检，不装")
    args = ap.parse_args()

    # 有的 shell（含 Git Bash 调 cmd）会把引号当字面量传进来
    args.dir = args.dir.strip().strip('"').strip("'")
    root = os.path.abspath(os.path.expanduser(args.dir))
    os.makedirs(root, exist_ok=True)
    comfy = os.path.join(root, "ComfyUI")
    py = os.path.join(root, "py", "python.exe")

    say("SuperMrWang AI 环境安装")
    say("=" * 46)
    say("安装目录：%s" % root)

    if sys.version_info < (3, 8):
        die("需要 Python 3.8 或更高（当前 %s）。" % sys.version.split()[0])
    if platform.system() != "Windows":
        die("这个脚本只覆盖 Windows。Linux/macOS 上直接装 ComfyUI 更省事：\n"
            "  git clone https://github.com/comfyanonymous/ComfyUI\n"
            "  pip install -r requirements.txt && python main.py")

    if args.verify:
        if not os.path.exists(py):
            die("这里还没装过（找不到 %s）" % py)
        return 0 if verify(root, py, comfy) else 1

    # 1 硬件 / 2 Python / 3 pip / 4 ComfyUI / 5 底模 / 6 资产 / 7 启动脚本+自检
    do_assets = args.assets != "none"
    total = 7 if do_assets else 6

    # 1) 硬件
    step(1, total, "检查硬件")
    gpu = gpu_info()
    variant = "cpu"
    if gpu:
        name, mem, drv = gpu
        say("  显卡：%s / %d MB / 驱动 %s" % (name, mem, drv))
        variant = "cu128"
        if mem < 6000:
            warn("显存只有 %d MB：SDXL 会非常慢，建议 --model sd15" % mem)
        # 驱动太老会装完跑不起来，提前说清楚而不是等 torch 报错
        try:
            major = int(drv.split(".")[0])
            if major < 525:
                warn("驱动 %s 偏旧，CUDA 12.8 的轮子可能不被支持（建议 >= 570）" % drv)
        except (ValueError, IndexError):
            pass
    else:
        warn("没找到 NVIDIA 显卡——AI 功能只能走 CPU，一张 512² 要 1~3 分钟")
        if not args.cpu:
            die("如果确认就是这样，加 --cpu 重新运行。\n"
                "  其余 47 个算子不受影响，AI Inpaint 单独不可用而已。")

    need = MIN_FREE_GB if not args.no_model else 8
    extra = asset_bytes(args.assets)
    if extra:
        need += extra / (1024.0 ** 3)
    free = free_gb(root)
    say("  磁盘：%s 剩 %.1f GB（这一趟要 %.1f GB）"
        % (os.path.splitdrive(root)[0] or "?", free, need))
    if free < need:
        die("空间不够：要 %.0f GB，只剩 %.1f GB。\n"
            "  省一点可以加 --assets none（只装 ComfyUI，模型后用 "
            "tools/setup_comfy.py 补）" % (need, free))

    # 2) Python
    step(2, total, "准备独立 Python")
    py = ensure_python(root)

    # 3) pip
    step(3, total, "准备 pip")
    ensure_pip(root, py)

    # 4) ComfyUI 源码 + 依赖
    step(4, total, "装 ComfyUI")
    comfy = ensure_comfyui(root, py)
    install_torch(py, variant)
    install_requirements(py, comfy)

    # 5) 底模
    if args.no_model:
        step(5, total, "底模（跳过）")
        say("  之后手动放进 %s" % os.path.join(comfy, "models", "checkpoints"))
    else:
        step(5, total, "下载底模")
        install_model(comfy, args.model)

    # 6) 插件要的 AI 资产（inpaint 模型 / 选区 / 抠图 / 节点包）
    n = 6
    if do_assets:
        step(n, total, "下载插件要的 AI 资产（%s 档）" % args.assets)
        if not install_assets(root, py, args.assets):
            warn("资产没下全，之后可以重跑：python tools/setup_comfy.py "
                 "--home \"%s\" --tier %s" % (root, args.assets))
        n += 1

    # 7) 启动脚本 + 自检
    step(n, total, "写启动脚本并自检")
    bat = write_launcher(root, variant)
    say("  启动脚本：%s" % bat)
    good = verify(root, py, comfy)

    say("\n" + "=" * 46)
    if good:
        say("装好了。")
    else:
        say("装完了，但自检有问题（上面标 [!!] 的）。")
    say("")
    say("下一步：")
    say("  1. 双击 %s" % bat)
    say("  2. 在 GIMP 里跑 SuperMrWang -> AI -> AI Inpaint")
    say("     （插件用默认地址 http://127.0.0.1:8188 就会连上）")
    say("")
    if not do_assets:
        say("模型还没下。补的话跑一条命令：")
        say("  python tools/setup_comfy.py --home \"%s\" --tier std" % root)
    elif args.assets == "min":
        say("现在只有 SD1.5-inpaint。想要 SDXL / 按名称选区 / 抠图：")
        say("  python tools/setup_comfy.py --home \"%s\" --tier std" % root)
        say("想再要 Flux.1 Fill（质量上限，单张 1~3 分钟）：")
        say("  python tools/setup_comfy.py --home \"%s\" --tier full" % root)
    say("")
    say("换模型：把 .safetensors 丢进")
    say("  %s" % os.path.join(comfy, "models", "checkpoints"))
    say("重启服务即可；插件的 Checkpoint 留空会自动挑一个，")
    say("名字带 xl/sdxl 的自动按 1024 送图，其余按 512。")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
