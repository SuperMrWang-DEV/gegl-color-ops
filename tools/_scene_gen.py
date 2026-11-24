#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时探针：先用 SDXL 出一张「空地板」底图，好在上面指定区域画小猫。

跑法：python tools/_scene_gen.py [提示词...]
产物：D:\\ComfyUI\\test-out\\scene-src.png
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import ai_client as A

OUT = r"D:\ComfyUI\test-out\scene-src.png"
DEFAULT = ("cozy scandinavian living room interior, light oak wooden floor in "
           "the foreground, soft morning daylight from a window, empty floor, "
           "no people, no animals, photorealistic, 35mm photo, sharp focus")
NEG = ("people, person, animal, cat, dog, text, watermark, cartoon, painting, "
       "blurry, lowres")


def main():
    prompt = " ".join(sys.argv[1:]).strip() or DEFAULT
    client = A.ComfyClient("")
    ckpt = "sd_xl_base_1.0.safetensors"
    print("底模", ckpt)
    print("提示词", prompt)
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": NEG, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["2", 0],
                         "negative": ["3", 0], "latent_image": ["4", 0],
                         "seed": 20261124, "steps": 28, "cfg": 7.0,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "denoise": 1.0}},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0], "filename_prefix": "scene-src"}},
    }
    t0 = time.time()
    pid = client.queue(wf)
    entry = client.wait(pid, timeout=900.0)
    img = A.first_image(entry)
    blob = client.download(img["filename"], img.get("subfolder", ""),
                           img.get("type", "output"))
    open(OUT, "wb").write(blob)
    print("%.1f s → %s (%d KB)" % (time.time() - t0, OUT, len(blob) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
