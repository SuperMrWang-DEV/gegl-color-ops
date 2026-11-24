#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载更高质量的重绘 / 填充模型到本机 ComfyUI。

2026-11-24 实测：8GB 显存的 3070 Ti，SD1.5-inpaint 是明显的瓶颈（画出来的猫
形体对但缺细节、正面容易发糊）。这里补两档：

  sdxl      sd_xl_base_1.0_inpainting_0.1.safetensors   6.9 GB
            9 通道 inpaint 专用，SDXL 分辨率，插件现有 condition 配方直接能用。
  flux      flux1-fill-dev-Q4_K_S.gguf + t5xxl_fp8 + clip_l + ae   12 GB
            Flux.1 Fill dev 的 4bit 量化，质量上限那一档；慢，且要 ComfyUI-GGUF。

用法：
  python tools/fetch_models.py                # 两档都下
  python tools/fetch_models.py sdxl           # 只下其中一档
  python tools/fetch_models.py --check        # 只体检，不下载
断点续传（curl -C -），重复跑不会重下已完成的部分。
"""

import os
import sys
import time
import urllib.request

COMFY = os.environ.get("LB_COMFY_HOME") or r"D:\ComfyUI\ComfyUI"
MIRROR = os.environ.get("LB_HF_MIRROR") or "https://hf-mirror.com"

# (仓库, 仓库内文件名, 落盘相对路径, 期望字节数)
FILES = {
    "sdxl": [
        ("wangqyqq/sd_xl_base_1.0_inpainting_0.1.safetensors",
         "sd_xl_base_1.0_inpainting_0.1.safetensors",
         "models/checkpoints/sd_xl_base_1.0_inpainting_0.1.safetensors",
         6938069944),
    ],
    "flux": [
        ("YarvixPA/FLUX.1-Fill-dev-GGUF", "flux1-fill-dev-Q4_K_S.gguf",
         "models/diffusion_models/flux1-fill-dev-Q4_K_S.gguf", 6809920800),
        ("comfyanonymous/flux_text_encoders", "t5xxl_fp8_e4m3fn.safetensors",
         "models/text_encoders/t5xxl_fp8_e4m3fn.safetensors", 4893934904),
        ("comfyanonymous/flux_text_encoders", "clip_l.safetensors",
         "models/text_encoders/clip_l.safetensors", 246144152),
        ("black-forest-labs/FLUX.1-schnell", "ae.safetensors",
         "models/vae/ae.safetensors", 335304388),
    ],
}

USE_MB = 1024 * 1024
CHUNK = 4 * USE_MB


def _human(n):
    return "%.1f MB" % (n / USE_MB) if n < 1024 * USE_MB else "%.2f GB" % (n / USE_MB / 1024)


def fetch(repo, name, dest, want, tries=8):
    """带断点续传的下载。Windows 自带的 curl 是 7.55（2017），不认识
    --retry-all-errors，也不认 http2，干脆整段用标准库自己写：Range 续传
    + 指数退避重试，中途断网不会从头再来（6.5 GB 重下一次就半小时）。"""
    dest = os.path.join(COMFY, dest.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = "%s/%s/resolve/main/%s" % (MIRROR, repo, name)
    print("  ↓ %s" % name)
    print("    %s" % url)
    for attempt in range(1, tries + 1):
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
        if want and have == want:
            print("    ✓ %s（已完整）" % _human(have))
            return True
        if have and want and have > want:
            print("    已有文件比预期大，删掉重下")
            os.remove(dest)
            have = 0
        req = urllib.request.Request(url, headers={"User-Agent": "lb-fetch/1"})
        if have:
            req.add_header("Range", "bytes=%d-" % have)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                code = getattr(resp, "status", 200)
                mode = "ab" if (have and code == 206) else "wb"
                if mode == "wb":
                    have = 0
                total = want or 0
                with open(dest, mode) as fh:
                    done = have
                    last = 0.0
                    while True:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        pct = (done * 100.0 / total) if total else 0
                        print("    %s / %s  %5.1f%%" % (
                            _human(done), _human(total) if total else "?", pct),
                            end="\r", flush=True)
                    print()
        except Exception as exc:                    # 网络中断：退避后重试
            wait = min(30, 2 ** attempt)
            print("    ! %s: %s —— %d s 后重试（%d/%d）" % (
                type(exc).__name__, str(exc)[:90], wait, attempt, tries))
            time.sleep(wait)
            continue
        got = os.path.getsize(dest) if os.path.exists(dest) else 0
        if not want or got == want:
            print("    ✓ %s" % _human(got))
            return True
        print("    ! 大小不符 %s / %s，继续续传" % (_human(got), _human(want)))
        time.sleep(2)
    print("    ✗ 放弃")
    return False


def check():
    print("ComfyUI: %s" % COMFY)
    if not os.path.isdir(COMFY):
        print("  ✗ 目录不存在")
        return 1
    for group, items in FILES.items():
        print("\n[%s]" % group)
        for _repo, _name, dest, want in items:
            p = os.path.join(COMFY, dest.replace("/", os.sep))
            have = os.path.getsize(p) if os.path.exists(p) else 0
            mark = "✓" if have == want else ("…" if have else "✗")
            print("  %s %-58s %7.1f / %.1f MB" % (
                mark, os.path.basename(p), have / USE_MB, want / USE_MB))
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--check" in sys.argv[1:]:
        return check()
    groups = args or ["sdxl", "flux"]
    bad = 0
    for g in groups:
        if g not in FILES:
            print("未知档位：%s（可选 %s）" % (g, " / ".join(FILES)))
            return 2
        print("\n[%s]" % g)
        for item in FILES[g]:
            if not fetch(*item):
                bad += 1
    print("\n完成，失败 %d 个" % bad if bad else "\n全部就绪")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
