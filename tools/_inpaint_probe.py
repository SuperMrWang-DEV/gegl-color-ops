#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：同一张脸、同一块蒙版，比三种「填充配方」会不会乱画。

A 现状（通用底模 + VAEEncodeForInpaint + denoise 1.0）
B 换 inpaint 专用底模，其余同 A
C 改进配方（通用底模 + VAEEncode + SetLatentNoiseMask + denoise 0.85）

跑法：python tools/_inpaint_probe.py [A|B|C ...]
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import ai_client as A

SRC = r"D:\ComfyUI\ComfyUI\input\lb-inpaint-src.png"
OUT = r"D:\ComfyUI\test-out"
PROMPT = "smooth forehead skin with natural freckles, photorealistic, soft light"


def make_mask(w, h, box, feather=0):
    """box = (x1,y1,x2,y2)，白 = 要重绘。feather 只做简单的 3px 过渡。"""
    x1, y1, x2, y2 = box
    gray = bytearray(w * h)
    for y in range(max(0, y1), min(h, y2)):
        row = y * w
        for x in range(max(0, x1), min(w, x2)):
            gray[row + x] = 255
    return A.mask_png(w, h, bytes(gray))


def run_a(client, src, mask, ckpt):
    """现状：VAEEncodeForInpaint + denoise 1.0。"""
    return A.inpaint(client, src, mask, PROMPT, checkpoint=ckpt,
                     steps=25, cfg=7.5, seed=12345, denoise=1.0,
                     grow_mask_by=8, prefix="probe-a")


def run_c(client, src, mask, ckpt):
    """改进：普通模型 + SetLatentNoiseMask，只往洞里加噪。"""
    t0 = time.time()
    src_name, _ = client.upload_image("probe-c-src.png", src)
    msk_name, _ = client.upload_image("probe-c-mask.png", mask)
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "LoadImage", "inputs": {"image": src_name}},
        "3": {"class_type": "LoadImage", "inputs": {"image": msk_name}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": PROMPT, "clip": ["1", 1]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "", "clip": ["1", 1]}},
        "6": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}},
        "10": {"class_type": "SetLatentNoiseMask",
               "inputs": {"samples": ["6", 0], "mask": ["3", 1]}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0],
                         "negative": ["5", 0], "latent_image": ["10", 0],
                         "seed": 12345, "steps": 25, "cfg": 7.5,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "denoise": 0.85}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0],
                                                    "vae": ["1", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": "probe-c"}},
    }
    pid = client.queue(wf)
    entry = client.wait(pid, timeout=900.0)
    img = A.first_image(entry)
    blob = client.download(img["filename"], img.get("subfolder", ""),
                           img.get("type", "output"))
    return [blob], {"seconds": round(time.time() - t0, 2)}


def run_d(client, src, mask, ckpt):
    """正解试配：inpaint 专用模型 + InpaintModelConditioning（mask 进条件）。"""
    t0 = time.time()
    src_name, _ = client.upload_image("probe-d-src.png", src)
    msk_name, _ = client.upload_image("probe-d-mask.png", mask)
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "LoadImage", "inputs": {"image": src_name}},
        "3": {"class_type": "LoadImage", "inputs": {"image": msk_name}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": PROMPT, "clip": ["1", 1]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "", "clip": ["1", 1]}},
        "11": {"class_type": "InpaintModelConditioning",
               "inputs": {"positive": ["4", 0], "negative": ["5", 0],
                          "vae": ["1", 2], "pixels": ["2", 0],
                          "mask": ["3", 1], "noise_mask": True}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["11", 0],
                         "negative": ["11", 1], "latent_image": ["11", 2],
                         "seed": 12345, "steps": 25, "cfg": 7.5,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0],
                                                    "vae": ["1", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": "probe-d"}},
    }
    pid = client.queue(wf)
    entry = client.wait(pid, timeout=900.0)
    img = A.first_image(entry)
    blob = client.download(img["filename"], img.get("subfolder", ""),
                           img.get("type", "output"))
    return [blob], {"seconds": round(time.time() - t0, 2)}


def main():
    want = [a.upper() for a in sys.argv[1:]] or ["A", "B", "C"]
    src = open(SRC, "rb").read()
    w, h = 1024, 512
    box = (640, 10, 900, 110)
    mask = make_mask(w, h, box)
    open(os.path.join(OUT, "probe-mask.png"), "wb").write(mask)
    print("蒙版：额头一块 %d×%d，白=重绘" % (box[2] - box[0], box[3] - box[1]))

    client = A.ComfyClient("")
    plans = {
        "A": ("sd_xl_base_1.0.safetensors", run_a, "现状：通用 SDXL + ForInpaint + 1.0"),
        "B": ("sd-v1-5-inpainting.ckpt", run_a, "专用：SD1.5-inpaint + ForInpaint + 1.0"),
        "C": ("sd_xl_base_1.0.safetensors", run_c, "改进：通用 SDXL + noise mask + 0.85"),
        "D": ("sd-v1-5-inpainting.ckpt", run_d, "正解：inpaint 模型 + InpaintModelConditioning"),
    }
    for key in want:
        ckpt, fn, desc = plans[key]
        print("\n[%s] %s" % (key, desc))
        t0 = time.time()
        blobs, info = fn(client, src, mask, ckpt)
        path = os.path.join(OUT, "probe-%s.png" % key.lower())
        open(path, "wb").write(blobs[0])
        print("   %.1f s → %s" % (time.time() - t0, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
