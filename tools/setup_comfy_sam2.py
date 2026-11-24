#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装好「按名称自动选区」需要的东西（SAM2 + GroundingDINO）。

菜单里那个「AI Select by Name…」不是纯 Python 的活：它借 ComfyUI-RMBG 的
SAM2Segment 节点，而那个节点要三样东西才跑得起来：

    1. 三个 PyPI 包：groundingdino-py / hydra-core / omegaconf
    2. 三份权重：SAM2-tiny、GroundingDINO-SwinT、bert-base-uncased
    3. 一个补丁：transformers 5.x 删掉了 BertModel.invert_attention_mask，
       而 groundingdino 的 bertwarper 直接取它 —— 不补就
       AttributeError: 'BertModel' object has no attribute 'invert_attention_mask'

权重默认走 https://hf-mirror.com（hf.co 国内直连是 0 字节卡死，不是慢）。
本脚本幂等：装过的跳过，权重大小对就跳过。

    python tools/setup_comfy_sam2.py                # 全都做
    python tools/setup_comfy_sam2.py --check        # 只看缺什么，不动手
    python tools/setup_comfy_sam2.py --home D:\\ComfyUI --python D:\\ComfyUI\\py312\\python.exe

装完**必须重启 ComfyUI**：节点和补丁都是启动时加载的。
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request

MIRROR = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")

PYPI = ["groundingdino-py", "hydra-core", "omegaconf", "iopath"]

# (相对 ComfyUI 根的子目录, 文件名, 镜像上的 repo, 大概字节数)
WEIGHTS = [
    ("models/sam2", "sam2.1_hiera_tiny-fp16.safetensors",
     "1038lab/sam2", 77980668),
    ("models/grounding-dino", "groundingdino_swint_ogc.safetensors",
     "1038lab/GroundingDINO", 699587568),
    ("models/grounding-dino", "GroundingDINO_SwinT_OGC.cfg.py",
     "1038lab/GroundingDINO", 1006),
    ("models/bert-base-uncased", "config.json", "bert-base-uncased", 570),
    ("models/bert-base-uncased", "vocab.txt", "bert-base-uncased", 231508),
    ("models/bert-base-uncased", "tokenizer.json", "bert-base-uncased", 466062),
    ("models/bert-base-uncased", "tokenizer_config.json",
     "bert-base-uncased", 48),
    ("models/bert-base-uncased", "model.safetensors",
     "bert-base-uncased", 440449768),
]

SHIM_NAME = "zz_bert_shim"
SHIM_CODE = '''# -*- coding: utf-8 -*-
"""给 transformers 5.x 补回 BertModel.invert_attention_mask（由 setup_comfy_sam2.py 生成）。

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


def find_home(want=""):
    """ComfyUI 根目录：参数 > 插件配置 > 常见路径。返回含 main.py 的那一层。"""
    cands = []
    if want:
        cands.append(want)
    cfg = os.path.join(os.environ.get("APPDATA", ""), "SuperMrWang",
                       "comfyui.json")
    if os.path.isfile(cfg):
        try:
            with open(cfg, encoding="utf-8") as fh:
                home = (json.load(fh) or {}).get("home") or ""
            if home:
                cands.append(home)
        except Exception:
            pass
    cands += [r"D:\ComfyUI", r"C:\ComfyUI", os.path.expanduser("~/ComfyUI")]
    for c in cands:
        if not c:
            continue
        for base in (c, os.path.join(c, "ComfyUI")):
            if os.path.isfile(os.path.join(base, "main.py")):
                return os.path.abspath(base)
    return ""


def missing_pkgs(python):
    code = ("import importlib.util as u;"
            "print(' '.join(m for m in %r if not u.find_spec(m)))"
            % [p.replace("-", "_").split("_")[0] for p in PYPI])
    try:
        out = subprocess.run([python, "-c", code], capture_output=True,
                             text=True, timeout=120)
        return out.stdout.split()
    except Exception:
        return []


def have_size(path, want):
    """大小对得上就算装好了（权重是定长文件，够用）。"""
    try:
        return os.path.getsize(path) == want
    except OSError:
        return False


def fetch(url, dest, want):
    tmp = dest + ".part"
    print("  下载 %s（%.0f MB）…" % (os.path.basename(dest), want / 1048576.0))
    req = urllib.request.Request(url, headers={"User-Agent": "SuperMrWang/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, \
            open(tmp, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    got = os.path.getsize(tmp)
    if want and abs(got - want) > 4096:
        os.remove(tmp)
        raise RuntimeError("大小不对：%d（期望 %d）" % (got, want))
    os.replace(tmp, dest)


def main():
    ap = argparse.ArgumentParser(description="装 SAM2 + GroundingDINO（按名称选区用）")
    ap.add_argument("--home", default="", help="ComfyUI 根目录（含 main.py）")
    ap.add_argument("--python", default="", help="ComfyUI 用的 python.exe")
    ap.add_argument("--check", action="store_true", help="只检查，不安装")
    args = ap.parse_args()

    home = find_home(args.home)
    if not home:
        print("没找到 ComfyUI。用 --home 指一下（那个含 main.py 的目录）。")
        return 2
    python = args.python or os.path.join(home, "..", "py312", "python.exe")
    python = os.path.abspath(python)
    print("ComfyUI: %s" % home)
    print("Python : %s%s" % (python, "" if os.path.isfile(python) else "  ← 不存在"))
    print("镜像   : %s" % MIRROR)

    plan = []
    if os.path.isfile(python):
        missing = missing_pkgs(python)
        if missing:
            plan.append(("pip", missing))
        else:
            print("· PyPI 包齐了")
    else:
        plan.append(("nopython", []))

    need = []
    for rel, name, repo, size in WEIGHTS:
        path = os.path.join(home, rel, name)
        if have_size(path, size):
            continue
        need.append((rel, name, repo, size))
    if not need:
        print("· 权重齐了")
    shim = os.path.join(home, "custom_nodes", SHIM_NAME, "__init__.py")
    need_shim = not os.path.isfile(shim)

    if not need and not need_shim and not plan:
        print("\n全都装好了。重启 ComfyUI 就能用「AI Select by Name…」。")
        return 0
    if args.check:
        for _rel, name, _repo, size in need:
            print("· 缺权重 %s（%.0f MB）" % (name, size / 1048576.0))
        if need_shim:
            print("· 缺补丁节点 custom_nodes/%s" % SHIM_NAME)
        for kind, items in plan:
            if kind == "pip":
                print("· 缺 PyPI 包：%s" % " ".join(items))
            elif kind == "nopython":
                print("· 找不到 ComfyUI 的 python.exe")
        return 1

    for kind, items in plan:
        if kind == "pip":
            print("\n装 PyPI 包：%s" % " ".join(items))
            subprocess.check_call([python, "-m", "pip", "install", "--no-input",
                                   "--disable-pip-version-check"] +
                                  ["groundingdino-py", "hydra-core",
                                   "omegaconf", "iopath"])
        elif kind == "nopython":
            print("\n跳过 PyPI：没找到 python.exe，手动装 "
                  "groundingdino-py hydra-core omegaconf iopath")

    for rel, name, repo, size in need:
        dest = os.path.join(home, rel, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        url = "%s/%s/resolve/main/%s" % (MIRROR, repo, name)
        try:
            fetch(url, dest, size)
        except Exception as exc:
            print("  失败：%s —— 手动放到 %s" % (exc, dest))
            return 1

    if need_shim:
        os.makedirs(os.path.dirname(shim), exist_ok=True)
        with open(shim, "w", encoding="utf-8") as fh:
            fh.write(SHIM_CODE)
        print("\n已写补丁节点：%s" % shim)

    print("\n装完了。**重启 ComfyUI**（节点和补丁都在启动时加载），"
          "然后在 GIMP 里 SuperMrWang → AI → AI Select by Name…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
