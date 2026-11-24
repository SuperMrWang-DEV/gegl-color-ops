#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 tools/setup_comfy.py · 一条命令把插件要的 AI 依赖装齐（下载器 + 体检）
 ---------------------------------------------------------------------------
 为什么要有这个脚本
   用户「下载了插件」之后，真正卡住的从来不是插件本身，而是 ComfyUI 那一侧：
     · 不知道 ComfyUI 装在哪（便携包 / git clone / tools/setup_ai.py 装的，
       目录结构三种都不一样），也不知道该用它哪个 python.exe；
     · 模型要放五个不同目录，放错一个就是「界面上选不到」；
     · 6~7 GB 的文件断一次线就从头再来；
     · Flux 还要一个自定义节点包（ComfyUI-GGUF），「按名称选区」和「抠图」
       要 ComfyUI-RMBG，节点包不在时插件只会说「找不到」。
   这个脚本把这些全部收进一条命令里：**探测 → 补依赖 → 装节点包 → 下权重
   → 校验 → 重启并确认服务里真的看得见**。

 用法
   python tools/setup_comfy.py                # 默认 std 档（inpaint 两档 + 选区 + 抠图）
   python tools/setup_comfy.py --check        # 只体检：缺什么、多大、怎么补
   python tools/setup_comfy.py --tier min     # 最小：只 SD1.5-inpaint（4.3 GB）
   python tools/setup_comfy.py --tier full    # 再加 Flux.1 Fill（12 GB）
   python tools/setup_comfy.py --with flux    # 在默认档上追加某一组
   python tools/setup_comfy.py --only flux    # **只**下这一组（fetch_models.py 就是这么转发的）
   python tools/setup_comfy.py --home D:\\ComfyUI --python D:\\ComfyUI\\py312\\python.exe
   python tools/setup_comfy.py --install-comfyui   # 连 ComfyUI 都没有：先装再继续

 设计上的几条硬规矩（都是踩出来的）
   1. **只用标准库**。目标机器可能什么都没有；而且这个脚本要在 GIMP 的嵌入式
      Python 之外跑，不能假设 requests/tqdm 存在。
   2. **权重先写 .part 再改名**。半截文件和「已装好」的区别必须靠尺寸判断，
      不能让 ComfyUI 读到一半的 safetensors。
   3. **镜像可以换，字节必须对**。hf-mirror 和 huggingface.co 是同一份内容，
      所以换源不丢 .part；但只要落盘尺寸和台账对不上，就当这轮不算数。
   4. **节点包和它的 pip 依赖成对装**。装了 ComfyUI-GGUF 却没装 gguf，
      ComfyUI 启动时那个节点直接报错消失——比不装更难查。
   5. **装完必须重启，重启完必须回读**。/object_info 里看不见等于没装。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import argparse
import json
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHARED = os.path.join(ROOT, "plugin", "_shared")
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

try:                                    # 插件自带的 ComfyUI 探测（纯标准库）
    import comfy_launcher as launch
except Exception:                       # noqa: BLE001 —— 只用 tools/ 也要能跑
    launch = None

MB = 1024 * 1024
GB = 1024 * MB
UA = "SuperMrWang-setup/2.0"

DEFAULT_SERVER = "http://127.0.0.1:8188"
HF_MIRRORS = [m for m in (os.environ.get("LB_HF_MIRROR"), "https://hf-mirror.com",
                          "https://huggingface.co") if m]
PYPI_MIRROR = os.environ.get("LB_PYPI_MIRROR",
                             "https://pypi.tuna.tsinghua.edu.cn/simple")
PYPI_FALLBACK = "https://pypi.org/simple"

# GitHub 直连在国内常年不通；节点包走 zip 时按这个顺序试前缀
GH_PREFIXES = ["", "https://ghproxy.net/", "https://gh-proxy.com/",
               "https://ghfast.top/"]
DISK_HEADROOM = int(1.5 * GB)     # 下大文件时留一点余量，别把盘写满

# ---- 资产台账 ---------------------------------------------------------------
# 一条 = 一份要落盘的文件。字段：
#   key    台账里的唯一名（--only 也认它）
#   group  sd15 / sdxl / flux / select / rmbg，档位就是靠 group 拼的
#   repo   镜像上的 HF 仓库；repos 是「主仓库 404 时依次再试」
#   dest   相对 ComfyUI 源码目录的位置（就是 models/ 那一套）
#   size   期望字节数。**一定填**：尺寸是「装好了没」的唯一判据
#
# 2026-11-24 逐个 HEAD 验过，别凭印象改。

def _asset(key, group, repo, name, dest, size, why, repos=()):
    return {"key": key, "group": group, "repo": repo, "name": name,
            "dest": dest, "size": size, "why": why,
            "repos": list(repos) or [repo]}


ASSETS = [
    # —— 填充模型 ——
    _asset("sd15-inpaint", "sd15",
           "stable-diffusion-v1-5/stable-diffusion-inpainting",
           "sd-v1-5-inpainting.ckpt",
           "models/checkpoints/sd-v1-5-inpainting.ckpt", 4265437280,
           "9 通道 SD1.5 inpaint：能跑就够，慢机器/显存小也能用",
           repos=("stable-diffusion-v1-5/stable-diffusion-inpainting",
                  "sd-legacy/stable-diffusion-inpainting",
                  "runwayml/stable-diffusion-inpainting")),
    _asset("sdxl", "sdxl",
           "wangqyqq/sd_xl_base_1.0_inpainting_0.1.safetensors",
           "sd_xl_base_1.0_inpainting_0.1.safetensors",
           "models/checkpoints/sd_xl_base_1.0_inpainting_0.1.safetensors",
           6938069944,
           "9 通道 SDXL inpaint：插件「自动」优先挑这档，细节明显强过 SD1.5"),
    _asset("flux-unet", "flux", "YarvixPA/FLUX.1-Fill-dev-GGUF",
           "flux1-fill-dev-Q4_K_S.gguf",
           "models/diffusion_models/flux1-fill-dev-Q4_K_S.gguf", 6809920800,
           "Flux.1 Fill 主干（4bit）：质量上限那一档"),
    _asset("flux-t5", "flux", "comfyanonymous/flux_text_encoders",
           "t5xxl_fp8_e4m3fn.safetensors",
           "models/text_encoders/t5xxl_fp8_e4m3fn.safetensors", 4893934904,
           "Flux 的 T5-XXL 文本编码器（fp8，8 GB 卡只能用 fp8）"),
    _asset("flux-clip", "flux", "comfyanonymous/flux_text_encoders",
           "clip_l.safetensors",
           "models/text_encoders/clip_l.safetensors", 246144152,
           "Flux 的 CLIP-L 文本编码器"),
    # ae 必须绕开官方仓库：black-forest-labs/FLUX.1-* 要登录 + 接受许可，403。
    _asset("flux-ae", "flux", "camenduru/FLUX.1-dev", "ae.safetensors",
           "models/vae/ae.safetensors", 335304388,
           "Flux 的 ae 解码器（官方仓库 403，这份逐字节相同）",
           repos=("camenduru/FLUX.1-dev", "Comfy-Org/Lumina_Image_2.0_Repackaged")),
    # —— 按名称选区（SAM2Segment） ——
    _asset("sam2", "select", "1038lab/sam2",
           "sam2.1_hiera_tiny-fp16.safetensors",
           "models/sam2/sam2.1_hiera_tiny-fp16.safetensors", 77980668,
           "SAM2 tiny 权重：写个名词就出选区，一次 5~6 秒"),
    _asset("dino", "select", "1038lab/GroundingDINO",
           "groundingdino_swint_ogc.safetensors",
           "models/grounding-dino/groundingdino_swint_ogc.safetensors", 699587568,
           "GroundingDINO：把「一只猫」变成框，再交给 SAM2"),
    _asset("dino-cfg", "select", "1038lab/GroundingDINO",
           "GroundingDINO_SwinT_OGC.cfg.py",
           "models/grounding-dino/GroundingDINO_SwinT_OGC.cfg.py", 1006,
           "GroundingDINO 的模型配置（节点按路径读它）"),
    _asset("bert-model", "select", "bert-base-uncased", "model.safetensors",
           "models/bert-base-uncased/model.safetensors", 440449768,
           "GroundingDINO 的文本编码器（不在 HF 缓存里，节点要本地目录）"),
    _asset("bert-config", "select", "bert-base-uncased", "config.json",
           "models/bert-base-uncased/config.json", 570, "BERT 配置"),
    _asset("bert-vocab", "select", "bert-base-uncased", "vocab.txt",
           "models/bert-base-uncased/vocab.txt", 231508, "BERT 词表"),
    _asset("bert-tok", "select", "bert-base-uncased", "tokenizer.json",
           "models/bert-base-uncased/tokenizer.json", 466062, "BERT 分词器"),
    _asset("bert-tokcfg", "select", "bert-base-uncased", "tokenizer_config.json",
           "models/bert-base-uncased/tokenizer_config.json", 48, "BERT 分词器配置"),
    # —— 抠图（RMBG 节点：RMBG-2.0） ——
    _asset("rmbg-model", "rmbg", "1038lab/RMBG-2.0", "model.safetensors",
           "models/RMBG/RMBG-2.0/model.safetensors", 884878856,
           "RMBG-2.0 权重：发丝最干净的抠图档"),
    _asset("rmbg-config", "rmbg", "1038lab/RMBG-2.0", "config.json",
           "models/RMBG/RMBG-2.0/config.json", 405, "RMBG-2.0 配置"),
    _asset("rmbg-net", "rmbg", "1038lab/RMBG-2.0", "birefnet.py",
           "models/RMBG/RMBG-2.0/birefnet.py", 91320, "RMBG-2.0 网络结构（随仓库走）"),
    _asset("rmbg-arc", "rmbg", "1038lab/RMBG-2.0", "BiRefNet_config.py",
           "models/RMBG/RMBG-2.0/BiRefNet_config.py", 298, "RMBG-2.0 网络配置"),
]

# 档位 = 要哪些 group。min 只保证「能填充」，std 是日常，full 加质量上限。
TIERS = {
    "min": ["sd15"],
    "std": ["sd15", "sdxl", "select", "rmbg"],
    "full": ["sd15", "sdxl", "select", "rmbg", "flux"],
}
GROUP_TITLE = {
    "sd15": "SD1.5 inpaint（最小可用）",
    "sdxl": "SDXL inpaint（推荐）",
    "flux": "Flux.1 Fill（质量上限，慢）",
    "select": "按名称选区（SAM2 + GroundingDINO）",
    "rmbg": "抠图（RMBG-2.0）",
}
GROUP_BY_ASSET = {a["group"] for a in ASSETS}

# ---- 节点包 -----------------------------------------------------------------
# 节点包必须和它的 pip 依赖成对出现，否则 ComfyUI 启动时那个节点会静默加载失败。
NODES = {
    "gguf": {
        "dir": "ComfyUI-GGUF",
        "repo": "city96/ComfyUI-GGUF",
        "pip": ["gguf>=0.13.0", "sentencepiece", "protobuf"],
        "groups": ["flux"],
        "why": "Flux 主干是 .gguf，普通 CheckpointLoader 读不了",
        "probe": "UnetLoaderGGUF",
    },
    "rmbg": {
        "dir": "ComfyUI-RMBG",
        "repo": "1038lab/ComfyUI-RMBG",
        # 只装这个包**用得上的子集**：整份 requirements 里的 onnxruntime-gpu /
        # nobg / transparent-background 加起来好几个 GB，还会动 torch 的版本，
        # 而 SAM2Segment / RMBG 这两个节点根本不需要它们（节点包自己按文件
        # try/except 加载，缺依赖的节点跳过，不影响别的）。
        "pip": ["groundingdino-py", "hydra-core", "omegaconf", "iopath"],
        "groups": ["select", "rmbg"],
        "why": "按名称选区和抠图都借这个包的 SAM2Segment / RMBG 节点",
        "probe": "SAM2Segment",
    },
}

SHIM_DIR = "zz_bert_shim"
SHIM_CODE = '''# -*- coding: utf-8 -*-
"""给 transformers 5.x 补回 BertModel.invert_attention_mask（setup_comfy.py 生成）。

GroundingDINO 的 bertwarper.py 直接取 `bert_model.invert_attention_mask`，
transformers 5.0 把这个方法从 BertModel 上删了，于是 SAM2Segment 一跑就报
AttributeError。这里按 4.x 的原样实现补回去。不注册任何 ComfyUI 节点。
"""

import torch

try:
    from transformers.models.bert.modeling_bert import BertModel
except Exception:
    BertModel = None


def _invert_attention_mask(self, encoder_attention_mask):
    dtype = getattr(self, "dtype", torch.float32)
    if encoder_attention_mask.dim() == 3:
        ext = encoder_attention_mask[:, None, :, :]
    else:
        ext = encoder_attention_mask[:, None, None, :]
    ext = ext.to(dtype=dtype)
    return (1.0 - ext) * torch.finfo(dtype).min


if BertModel is not None and not hasattr(BertModel, "invert_attention_mask"):
    BertModel.invert_attention_mask = _invert_attention_mask
    print("[zz_bert_shim] BertModel.invert_attention_mask 已补回")

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
'''

# ---- 输出 -------------------------------------------------------------------

_TTY = sys.stdout.isatty()


def _bail():
    """stdout 被 `| head` 关掉：把 1 号描述符换成 devnull 再退出。

    只 raise SystemExit 不够——解释器退出时还会 flush 一次那根已经断掉的
    管道，于是多出一行 "Exception ignored ... OSError: [Errno 22]"。
    """
    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    except OSError:
        pass
    raise SystemExit(0)


def say(msg=""):
    """打印一行。**管道被关掉不算错误**。"""
    try:
        print(msg, flush=True)
    except (BrokenPipeError, OSError):
        _bail()


def _write(text):
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        _bail()


def human(n):
    if n >= GB:
        return "%.2f GB" % (n / GB)
    if n >= MB:
        return "%.0f MB" % (n / MB)
    return "%d B" % n


class Abort(Exception):
    """能说清原因、不需要 traceback 的失败。"""


# ---- 找 ComfyUI -------------------------------------------------------------

def _looks_like_home(path):
    """含 main.py 的目录，或者包着一层 ComfyUI/ 的外层目录，都算。"""
    return bool(path) and (
        os.path.isfile(os.path.join(path, "main.py")) or
        os.path.isfile(os.path.join(path, "ComfyUI", "main.py")))


def find_comfy(want_home="", want_python=""):
    """返回 dict(home, src, python, source)。

    home 是「用户填的那一层」（可能是外层目录），src 是含 main.py 的那一层，
    python 是那个环境自己的解释器（不能拿系统 python 去装包——装完 ComfyUI
    也 import 不到）。三种布局都要认：
        D:\\ComfyUI\\            ← 便携包（ComfyUI/ + python_embeded/）
        D:\\ComfyUI\\ComfyUI\\    ← 直接指到源码
        ~\\SuperMrWang-AI\\       ← tools/setup_ai.py 装的（py/ + ComfyUI/）
    """
    cands = []
    if want_home:
        cands.append(os.path.abspath(os.path.expanduser(want_home)))
    if launch is not None:
        cfg_home = launch.configured_home()
        if cfg_home:
            cands.append(cfg_home)
        cands += launch.guess_homes()
    else:
        cands += [os.path.join(os.path.expanduser("~"), "SuperMrWang-AI"),
                  os.path.join(os.path.expanduser("~"), "ComfyUI"),
                  "C:/ComfyUI", "D:/ComfyUI", "D:/ComfyUI/ComfyUI"]

    seen, uniq = set(), []
    for c in cands:
        if not c:
            continue
        key = os.path.normcase(os.path.normpath(c))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(os.path.normpath(c))

    for home in uniq:
        if not _looks_like_home(home):
            continue
        if launch is not None:
            det = launch.detect(home)
            src, python = det.get("source") or "", det.get("python") or ""
        else:
            src = home if os.path.isfile(os.path.join(home, "main.py")) \
                else os.path.join(home, "ComfyUI")
            python = ""
        if not src:
            continue
        python = want_python or python
        return {"home": home, "src": src, "python": python,
                "source": "参数" if want_home and home == os.path.abspath(
                    os.path.expanduser(want_home)) else "自动探测"}
    return {"home": "", "src": "", "python": "", "source": ""}


def python_hint(home, src):
    """找不到解释器时，把「该填哪个」直接列出来，别让用户猜。"""
    lines = ["在 %s 和它旁边找过：" % (home or src)]
    for pat in ("py/python.exe", "py312/python.exe", "python_embeded/python.exe",
                "venv/Scripts/python.exe", "python.exe"):
        lines.append("  · %s" % os.path.join(home or src, pat.replace("/", os.sep)))
    lines.append("用 --python 指一下（那个能 import torch 的 python.exe）。")
    return "\n".join(lines)


# ---- 下载 -------------------------------------------------------------------

def asset_urls(asset, mirrors=None):
    out = []
    for repo in asset["repos"]:
        for m in (mirrors or HF_MIRRORS):
            out.append("%s/%s/resolve/main/%s" % (m.rstrip("/"), repo,
                                                  asset["name"]))
    return out


def _fetch_stream(url, part, size):
    """跑一次 Range 下载。返回落盘后的字节数。

    只有 206 才允许追写；有的镜像对 Range 装傻回 200 + 整个文件，
    那时候必须清空重写，否则文件前面会多出一段。
    """
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if size and have > size:
        os.remove(part)
        have = 0
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if have:
        req.add_header("Range", "bytes=%d-" % have)
    with urllib.request.urlopen(req, timeout=60) as resp:
        code = getattr(resp, "status", 200)
        mode = "ab" if (have and code == 206) else "wb"
        if mode == "wb":
            have = 0
        total = size or 0
        t0 = time.time()
        done = have
        last = 0.0
        with open(part, mode) as fh:
            while True:
                chunk = resp.read(1 * MB)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last >= 0.35:
                    last = now
                    spd = (done - have) / max(now - t0, 0.001) / MB
                    if _TTY:
                        pct = ("%5.1f%%" % (done * 100.0 / total)) if total else "  --  "
                        _write("\r    %s  %s / %s  %5.1f MB/s   " % (
                            pct, human(done), human(total) if total else "?",
                            spd))
                    elif int(now - t0) % 20 == 0:
                        say("    %s / %s  %.1f MB/s" % (
                            human(done), human(total) if total else "?",
                            spd))
        if _TTY:
            _write("\n")
    return done


def download(asset, src, mirrors=None, retries=3, quiet_skip=True):
    """下一个资产。返回 'ok' / 'skip'；失败抛 Abort。

    断点续传靠 .part：换镜像不丢进度（几家镜像背后是同一份文件），
    但落盘尺寸对不上就不认——宁可重下，也不留一个半截的 safetensors。
    """
    dest = os.path.join(src, asset["dest"].replace("/", os.sep))
    size = asset["size"]
    if size and os.path.isfile(dest) and os.path.getsize(dest) == size:
        return "skip"
    if os.path.isfile(dest) and size and os.path.getsize(dest) != size:
        # 之前被截断/放错版本：留着只会一直判「坏」，直接清掉
        say("    ! %s 尺寸不对（%s / %s），删掉重下"
            % (asset["name"], human(os.path.getsize(dest)), human(size)))
        os.remove(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    if size and os.path.isfile(part) and os.path.getsize(part) == size:
        os.replace(part, dest)
        return "ok"

    say("  ↓ %s  %s" % (asset["name"], human(size)))
    say("    %s" % asset["why"])
    errors = []
    for url in asset_urls(asset, mirrors):
        if os.environ.get("LB_SETUP_TRACE"):
            say("    试 %s" % url)
        for attempt in range(1, retries + 1):
            before = os.path.getsize(part) if os.path.exists(part) else 0
            try:
                done = _fetch_stream(url, part, size)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403, 404):     # 源本身没有/要登录：换源
                    errors.append("%s → HTTP %d" % (url.rsplit("/", 2)[-2], exc.code))
                    break
                errors.append("%s → HTTP %d" % (url.rsplit("/", 2)[-2], exc.code))
                time.sleep(min(8, 2 ** attempt))
                continue
            except Exception as exc:                # noqa: BLE001 —— 网络类
                errors.append("%s → %s" % (url.rsplit("/", 2)[-2],
                                           type(exc).__name__))
                time.sleep(min(8, 2 ** attempt))
                continue
            got = os.path.getsize(part)
            if not size or got == size:
                os.replace(part, dest)
                say("    ✓ %s" % human(got))
                return "ok"
            if got <= before:
                # 这轮一个新字节都没拿到：这个源没用了，换下一个
                errors.append("%s → 没有进展（%s）" % (url.rsplit("/", 2)[-2],
                                                     human(got)))
                break
            errors.append("%s → 只拿到 %s / %s" % (url.rsplit("/", 2)[-2],
                                                  human(got), human(size)))
            time.sleep(1)
    if os.path.exists(part):
        try:                                        # 半截留着没意义（来源都不通）
            os.remove(part)
        except OSError:
            pass
    raise Abort("下载失败：%s\n    试过：%s" % (asset["name"],
                                              "；".join(errors[-4:])))


# ---- pip / 节点包 -----------------------------------------------------------

TORCH_REQ = re.compile(r"^(torch|torchvision|torchaudio)\b", re.I)


def py_probe(python, code):
    rc, out = run_tool([python, "-c", code], timeout=120)
    return rc == 0, out.strip()


def missing_pkgs(python, reqs):
    """在**目标解释器**里查（不是当前进程），只认模块名。

    pip 的包名和 import 名不是一回事（groundingdino-py → groundingdino），
    但这里几个包恰好只差下划线，所以按规范名转换就够；查不到就当成「都缺」，
    宁可多跑一次 pip install（幂等），也别漏装。
    """
    mods = []
    for r in reqs:
        name = re.split(r"[<>=!\[;]", r)[0].strip()
        if name:
            mods.append(name.replace("-", "_"))
    ok, out = py_probe(python, "import importlib.util as u;"
                               "print(' '.join(m for m in %r "
                               "if not u.find_spec(m)))" % mods)
    return out.split() if ok else mods


def pip_install(python, reqs, cwd=None):
    """装一组包：先走国内镜像，镜像不通再回官方源。"""
    if not reqs:
        return True
    last = None
    for index in (PYPI_MIRROR, PYPI_FALLBACK):
        if not index:
            continue
        cmd = [python, "-m", "pip", "install", "--no-input", "--no-cache-dir",
               "--disable-pip-version-check", "-i", index] + list(reqs)
        say("    pip install %s  ← %s" % (" ".join(reqs),
                                          index.split("/")[2]))
        try:
            r = subprocess.run(cmd, cwd=cwd, timeout=3600)
        except Exception as exc:                    # noqa: BLE001
            last = exc
            continue
        if r.returncode == 0:
            return True
        last = "exit %d" % r.returncode
    raise Abort("pip 安装失败（%s）。可以手动跑：\n    %s -m pip install %s"
                % (last, python, " ".join(reqs)))


def git_clone(repo, dest):
    """git clone --depth 1；GitHub 直连不通就换代理前缀。"""
    git = shutil.which("git")
    if not git:
        return False
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="echo")
    for pre in GH_PREFIXES:
        url = "%shttps://github.com/%s.git" % (pre, repo)
        tmp = dest + ".clone"
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        say("    git clone %s" % url)
        rc, _out = run_tool([git, "clone", "--depth", "1", url, tmp],
                            timeout=600, env=env)
        if rc == 0 and os.path.isfile(os.path.join(tmp, "__init__.py")):
            os.replace(tmp, dest)
            return True
        shutil.rmtree(tmp, ignore_errors=True)
    return False


def zip_fetch(repo, dest):
    """没有 git 或 clone 全失败：抓 GitHub 的源码 zip（走同一个代理列表）。"""
    tmpdir = dest + ".unzip"
    for pre in GH_PREFIXES:
        for branch in ("master", "main"):
            url = "%scodeload.github.com/%s/zip/refs/heads/%s" % (pre, repo, branch)
            zpath = dest + ".zip"
            try:
                _fetch_stream(url, zpath, None)
            except Exception:                       # noqa: BLE001
                continue
            if os.path.isdir(tmpdir):
                shutil.rmtree(tmpdir, ignore_errors=True)
            try:
                with zipfile.ZipFile(zpath) as zf:
                    zf.extractall(tmpdir)
            except Exception:                       # noqa: BLE001 —— 下到的是错误页
                os.remove(zpath)
                continue
            os.remove(zpath)
            inner = [d for d in os.listdir(tmpdir)
                     if os.path.isdir(os.path.join(tmpdir, d))]
            if len(inner) != 1:
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            os.replace(os.path.join(tmpdir, inner[0]), dest)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return os.path.isfile(os.path.join(dest, "__init__.py"))
    return False


def install_node(key, src, python):
    """装节点包 + 它的 pip 依赖。返回「有没有真的动了东西」。

    返回值决定要不要重启 ComfyUI：节点/依赖没变就不重启（重启一次要
    半分钟，用户可能正连着用）。
    """
    spec = NODES[key]
    dest = os.path.join(src, "custom_nodes", spec["dir"])
    changed = False
    if os.path.isfile(os.path.join(dest, "__init__.py")):
        say("  · %s 已装" % spec["dir"])
    else:
        say("  + %s（%s）" % (spec["dir"], spec["why"]))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not (git_clone(spec["repo"], dest) or zip_fetch(spec["repo"], dest)):
            raise Abort("节点包装不上：%s（%s）。手动：\n"
                        "    git clone https://github.com/%s \"%s\""
                        % (spec["dir"], spec["repo"], spec["repo"], dest))
        changed = True
    if spec["pip"] and python:
        need = missing_pkgs(python, spec["pip"])
        if need:
            say("  + %s 的依赖：%s" % (spec["dir"], " ".join(need)))
            pip_install(python, spec["pip"])
            changed = True
        else:
            say("  · %s 的依赖齐了" % spec["dir"])
    return changed


def install_shim(src):
    dest = os.path.join(src, "custom_nodes", SHIM_DIR, "__init__.py")
    if os.path.isfile(dest):
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(SHIM_CODE)
    say("  + custom_nodes/%s（transformers 5.x 的 BERT 补丁）" % SHIM_DIR)
    return True


# ---- 服务端校验 -------------------------------------------------------------

def server_get(url, path, timeout=8.0):
    try:
        with urllib.request.urlopen(url.rstrip("/") + path, timeout=timeout) as r:
            return json.load(r)
    except Exception:                               # noqa: BLE001
        return None


def server_online(url=DEFAULT_SERVER):
    return server_get(url, "/system_stats", timeout=3.0) is not None


def combo_of(url, node, key):
    info = server_get(url, "/object_info/" + node)
    if not info or node not in info:
        return None
    req = ((info[node] or {}).get("input") or {}).get("required") or {}
    val = req.get(key)
    if not val or not isinstance(val[0], list):
        return []
    return val[0]


def visible_state(url, src):
    """服务端现在认不认这些文件。返回 (ok_pairs, missing, node_flags)。"""
    ck = combo_of(url, "CheckpointLoaderSimple", "ckpt_name") or []
    unet = combo_of(url, "UnetLoaderGGUF", "unet_name")      # None = 节点没装
    vae = combo_of(url, "VAELoader", "vae_name") or []
    nodes = {
        "gguf": unet is not None,
        "rmbg": "SAM2Segment" in (server_get(url, "/object_info/SAM2Segment") or {}),
    }
    return {"ckpt": ck, "unet": unet or [], "vae": vae, "nodes": nodes}


def run_tool(argv, timeout=600, cwd=None, env=None):
    """跑一个外部命令，返回 (returncode, 文本)。

    **不用 text=True**：中文 Windows 上 tasklist/netstat/taskkill/git 的输出
    跟系统代码页走（GBK），而 `text=True` 会按 UTF-8 解（尤其开了
    PYTHONUTF8=1 的时候），于是解码在读取线程里抛 UnicodeDecodeError，
    调用方拿到的 stdout 是 None —— 这条路上层只能看见「什么都没找到」，
    比直接报错更难查。所以：拿 bytes，自己按 utf-8 宽容解码。
    """
    try:
        r = subprocess.run(argv, capture_output=True, timeout=timeout, cwd=cwd,
                           env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    raw = (r.stdout or b"") + (r.stderr or b"")
    for enc in ("utf-8", "gbk"):
        try:
            return r.returncode, raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return r.returncode, raw.decode("utf-8", "replace")


def port_owner(port=8188):
    """谁在监听这个端口。launcher 记的 pid 可能已经换代（重启过/被接管过）。"""
    if os.name == "nt":
        _rc, out = run_tool(["netstat", "-ano"], timeout=20)
        for line in out.splitlines():
            if (":%d" % port) in line and "LISTENING" in line.upper():
                pid = line.split()[-1]
                if pid.isdigit():
                    return int(pid)
        return 0
    _rc, out = run_tool(["lsof", "-t", "-i:%d" % port], timeout=20)
    parts = out.split()
    return int(parts[0]) if parts and parts[0].isdigit() else 0


def kill_pid(pid):
    rc, _out = run_tool(["taskkill", "/PID", str(pid), "/T", "/F"]
                        if os.name == "nt" else ["kill", "-9", str(pid)],
                        timeout=30)
    return rc == 0


def restart_server(home, python, url=DEFAULT_SERVER, timeout=180.0):
    """停掉再拉起。返回 (ok, note)。

    停的时候**不能只信 launcher 记的 pid**：ComfyUI 可能被别人的 bat 起过、
    已经换过一代进程，runtime 里那个 pid 早就死了，端口却还占着，于是
    「启动了」但新进程绑定失败。所以停完再探一次端口，还占着就按端口找真身。
    """
    if launch is None:
        return False, "没有 comfy_launcher，跳过重启（手动重启 ComfyUI 即可）"
    if launch.is_online(url):
        say("  停掉旧进程…")
        launch.stop()
        for _ in range(40):
            if not launch.is_online(url):
                break
            time.sleep(0.5)
        if launch.is_online(url):                   # 记录的 pid 不对，自己找
            pid = port_owner(launch.port_of(url))
            if pid:
                say("  端口 %d 仍被 pid %d 占着，强停"
                    % (launch.port_of(url), pid))
                kill_pid(pid)
                for _ in range(20):
                    if not launch.is_online(url):
                        break
                    time.sleep(0.5)
    if not launch.configured_home():                # 用户没选过，就把探测到的记下
        launch.set_home(home, python)
    say("  启动 ComfyUI…")
    try:
        res = launch.launch(url)
    except Exception as exc:                        # noqa: BLE001
        return False, "启动失败：%s" % exc
    if not res.get("ok"):
        tail = (res.get("log") or "").strip().splitlines()[-3:]
        return False, "没起来：%s %s" % (res.get("error"), " / ".join(tail))
    # launch() 只负责把进程拉起来，**不等就绪**（ensure_running 才等）。
    # 不在这里等，就等于「刚 spawn 完就判死」——冷启动要加载底模，半分钟起步。
    ready = launch.wait_ready(url, timeout=timeout, pid=res.get("pid") or 0,
                              log_path=res.get("log") or "")
    if ready.get("ok"):
        return True, "已重启并在线（pid %s）" % (res.get("pid") or "?")
    return False, "启动没就绪：%s" % (ready.get("error") or "超时")


# ---- 计划与体检 -------------------------------------------------------------

def select_assets(tier="std", with_groups=(), only=()):
    groups = []
    if only:
        groups = [g for g in only if g in GROUP_TITLE]
        unknown = [g for g in only if g not in GROUP_TITLE]
        if unknown:
            raise Abort("不认识的组：%s（可选 %s）"
                        % (" ".join(unknown), " / ".join(GROUP_TITLE)))
    else:
        groups = list(TIERS[tier])
    for g in with_groups:
        if g not in GROUP_TITLE:
            raise Abort("不认识的组：%s" % g)
        if g not in groups:
            groups.append(g)
    return [a for a in ASSETS if a["group"] in groups], groups


def needed_nodes(groups):
    return [k for k, spec in NODES.items()
            if any(g in spec["groups"] for g in groups)]


def report_rows(src, assets, groups):
    rows = []
    for g in groups:
        for a in assets:
            if a["group"] != g:
                continue
            p = os.path.join(src, a["dest"].replace("/", os.sep))
            have = os.path.getsize(p) if os.path.isfile(p) else 0
            state = "ok" if have == a["size"] else ("part" if have else "miss")
            rows.append({"group": g, "asset": a, "have": have, "state": state})
    return rows


def print_check(info, rows, groups, node_rows):
    say("ComfyUI : %s（%s）" % (info["src"] or "未找到", info["source"] or "-"))
    say("Python  : %s" % (info["python"] or "未找到"))
    say("镜像    : %s" % HF_MIRRORS[0])
    if not info["src"]:
        say("\n没找到 ComfyUI。三条路：")
        say("  · 已经装了：python tools/setup_comfy.py --home <含 main.py 的目录>")
        say("  · 没装：python tools/setup_comfy.py --install-comfyui")
        say("  · 插件里选过目录的话，这里会自动读到")
        return 2

    total_missing = 0
    for g in groups:
        say("\n[%s]" % GROUP_TITLE[g])
        for r in rows:
            if r["group"] != g:
                continue
            mark = {"ok": "✓", "part": "…", "miss": "✗"}[r["state"]]
            say("  %s %-46s %8s / %-8s" % (mark, r["asset"]["name"],
                                           human(r["have"]),
                                           human(r["asset"]["size"])))
            if r["state"] != "ok":
                total_missing += r["asset"]["size"] - r["have"]
    say("\n[节点包]")
    for key, spec in NODES.items():
        if not any(g in spec["groups"] for g in groups):
            continue
        mark = "✓" if node_rows.get(key, {}).get("installed") else "✗"
        say("  %s %-20s %s" % (mark, spec["dir"], spec["why"]))
    say("\n[服务端]")
    url = DEFAULT_SERVER
    if not server_online(url):
        say("  · 服务没在跑，装完会自动拉起并回读")
    else:
        st = visible_state(url, info["src"])
        say("  · 在线，底模 %d 个、gguf 主干 %d 个" % (len(st["ckpt"]),
                                                      len(st["unet"])))
        for key, spec in NODES.items():
            if any(g in spec["groups"] for g in groups):
                say("  · %s 节点：%s" % (spec["dir"],
                                        "已加载" if st["nodes"].get(key)
                                        else "没加载（重启后仍没有就看日志）"))
    if total_missing:
        say("\n还差 %s。跑一遍不带 --check 的命令就会下。" % human(total_missing))
        return 1
    say("\n权重齐了。")
    return 0


# ---- 主流程 -----------------------------------------------------------------

def run(args):
    tier = args.tier
    only = [g.strip() for g in (args.only or "").replace(",", " ").split() if g]
    with_groups = [g.strip() for g in (args.with_ or "").replace(",", " ").split()
                   if g]
    assets, groups = select_assets(tier, with_groups, only)

    info = find_comfy(args.home, args.python)
    if not info["src"] and args.install_comfyui:
        say("没找到 ComfyUI，先装一个（tools/setup_ai.py）")
        root = args.ai_dir or os.path.join(os.path.expanduser("~"),
                                           "SuperMrWang-AI")
        cmd = [sys.executable, os.path.join(HERE, "setup_ai.py"),
               "--dir", root]
        if args.cpu:
            cmd.append("--cpu")
        if subprocess.run(cmd).returncode != 0:
            raise Abort("setup_ai.py 失败，看它上面的输出")
        info = find_comfy(args.home or root, args.python)

    if not info["src"]:
        say("没找到 ComfyUI。")
        say("  · 已经装了：加 --home <含 main.py 的目录>")
        say("  · 没装：加 --install-comfyui")
        say("  · 也可以在 GIMP 里 SuperMrWang → AI → AI 环境 选一次，之后这里就认得")
        return 2
    if not info["python"] and not args.check:
        raise Abort("找到 ComfyUI（%s）但没找到它的 python.exe。\n%s"
                    % (info["src"], python_hint(info["home"], info["src"])))

    src, python = info["src"], info["python"]
    need_nodes = needed_nodes(groups)

    if args.check:
        node_rows = {k: {"installed": os.path.isfile(
            os.path.join(src, "custom_nodes", NODES[k]["dir"], "__init__.py"))}
            for k in NODES}
        return print_check(info, report_rows(src, assets, groups), groups,
                           node_rows)

    say("ComfyUI : %s" % src)
    say("Python  : %s" % python)
    say("档位    : %s（%s）" % (tier if not only else "only",
                               " / ".join(GROUP_TITLE[g] for g in groups)))

    # 1) 磁盘余量：宁可开跑前就拦住，也别下到 90% 写不进去
    rows = report_rows(src, assets, groups)
    missing = sum(r["asset"]["size"] - r["have"] for r in rows
                  if r["state"] != "ok")
    drive = os.path.splitdrive(src)[0] + os.sep if os.name == "nt" else "/"
    try:
        free = shutil.disk_usage(drive).free
    except OSError:
        free = 0
    if missing and free and free < missing + DISK_HEADROOM:
        raise Abort("空间不够：要下 %s，%s 只剩 %s。" % (human(missing), drive,
                                                       human(free)))

    # 2) 节点包 + 它的 pip 依赖（先做：pip 可能要几分钟，别等 6 GB 下完才报错）
    changed = False
    if need_nodes:
        say("\n[1/3] 节点包")
        for key in need_nodes:
            changed = install_node(key, src, python) or changed
    if "select" in groups and install_shim(src):
        changed = True

    # 3) 权重
    say("\n[2/3] 权重（%d 个文件，%s）" % (len(assets), human(missing)))
    done = skipped = 0
    failed = []
    for a in assets:
        try:
            r = download(a, src)
        except Abort as exc:
            failed.append((a, str(exc)))
            say("    ✗ %s" % a["name"])
            say("      %s" % str(exc).replace("\n", "\n      "))
            continue
        if r == "skip":
            skipped += 1
        else:
            done += 1
    say("  新下 %d 个，已有 %d 个%s"
        % (done, skipped, "，失败 %d 个" % len(failed) if failed else ""))

    # 4) 重启 + 回读。只有「节点/补丁变了」才必须重启——模型文件是启动时
    #    扫目录的，但扫的是目录清单，新增文件不必重启（2026-11-24 实测）。
    say("\n[3/3] 校验")
    need_restart = changed or (not server_online(DEFAULT_SERVER)
                               and not args.no_restart)
    if need_restart:
        if args.no_restart:
            say("  · 按 --no-restart 跳过；**手动重启 ComfyUI 后**新节点才可见")
        else:
            ok, note = restart_server(info["home"], python)
            say("  · %s" % note)
            if not ok:
                say("    手动跑 start-comfyui.bat，或 GIMP 里 AI 环境 → 启动")
    if server_online(DEFAULT_SERVER):
        st = visible_state(DEFAULT_SERVER, src)
        pool = st["ckpt"] + st["unet"] + st["vae"]
        for a in assets:
            base = os.path.basename(a["dest"])
            if a["group"] in ("sd15", "sdxl", "flux") and base not in pool:
                say("  ! 服务端还没列出 %s（重启一次 ComfyUI 就会出现）" % base)
        for key in need_nodes:
            say("  · %s：%s" % (NODES[key]["dir"],
                                "已加载" if st["nodes"].get(key) else "没加载"))
        say("  · 底模 %d 个、gguf 主干 %d 个"
            % (len(st["ckpt"]), len(st["unet"])))
    else:
        say("  · 服务不在线，跳过回读（下次在 GIMP 里用会自动拉起）")

    if failed:
        say("\n有 %d 个文件没下成，重跑同一条命令会接着下（断点续传）。"
            % len(failed))
        return 1
    say("\n装齐了。")
    say("下一步：GIMP → SuperMrWang → AI → AI Inpaint / AI Select by Name…")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        description="把插件要的 ComfyUI 依赖（节点包 / pip 包 / 模型权重）一次装齐")
    ap.add_argument("--tier", choices=sorted(TIERS), default="std",
                    help="min 只 SD1.5-inpaint；std 加 SDXL/选区/抠图（默认）；"
                         "full 再加 Flux")
    ap.add_argument("--with", dest="with_", default="",
                    help="在档位上追加组：flux / select / rmbg / sdxl / sd15")
    ap.add_argument("--only", default="",
                    help="只处理这些组（fetch_models.py 用它转发）")
    ap.add_argument("--check", action="store_true", help="只体检，不下载")
    ap.add_argument("--home", default="", help="ComfyUI 目录（含 main.py，或包着它）")
    ap.add_argument("--python", default="", help="那个 ComfyUI 用的 python.exe")
    ap.add_argument("--mirror", default="", help="HF 镜像（默认 hf-mirror.com）")
    ap.add_argument("--no-restart", action="store_true",
                    help="装完不重启 ComfyUI")
    ap.add_argument("--install-comfyui", action="store_true",
                    help="没找到 ComfyUI 时先调 setup_ai.py 装一个")
    ap.add_argument("--ai-dir", default="", help="--install-comfyui 的安装目录")
    ap.add_argument("--cpu", action="store_true", help="--install-comfyui 用 CPU 版")
    return ap


def main(argv=None):
    global HF_MIRRORS
    args = build_parser().parse_args(argv)
    if args.mirror:
        HF_MIRRORS = [args.mirror.rstrip("/")] + [m for m in HF_MIRRORS
                                                  if args.mirror not in m]
    try:
        return run(args)
    except Abort as exc:
        say("\n%s" % exc)
        return 1
    except KeyboardInterrupt:
        say("\n已中断。重跑会从 .part 接着下。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
