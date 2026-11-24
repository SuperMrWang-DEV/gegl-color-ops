#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线复算并比较几套「抹除」打分公式，用两批真实候选验证。

用法：python tools/_erase_rank_eval.py [rankin] [rankin2]
每批目录里要有 base.png / mask.png / cand0..2.png（见 _erase_rank_dump.py）。
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugin", "_shared"))

import ai_client as A
import quality as Q

SCORE_SIDE = 200
SETS = {
    "rankin":  ["条纹", "多手指", "干净白布"],
    "rankin2": ["米色块", "多手指", "干净白布"],
}
GOOD = "干净白布"


def load_rgba(path):
    w, h, ch, data = A.decode_png(open(path, "rb").read())
    if ch == 3:
        out = bytearray(w * h * 4)
        for i in range(w * h):
            out[i * 4:i * 4 + 3] = data[i * 3:i * 3 + 3]
            out[i * 4 + 3] = 255
        return w, h, bytes(out)
    return w, h, bytes(data)


def scale_rgba(data, w, h, nw, nh):
    out = bytearray(nw * nh * 4)
    xs = [min(w - 1, int(c * w / nw)) for c in range(nw)]
    for r in range(nh):
        sy = min(h - 1, int(r * h / nh))
        srow = sy * w
        base = r * nw * 4
        for c in range(nw):
            s = (srow + xs[c]) * 4
            out[base + c * 4:base + c * 4 + 4] = data[s:s + 4]
    return bytes(out)


def scale_gray(data, w, h, nw, nh):
    out = bytearray(nw * nh)
    xs = [min(w - 1, int(c * w / nw)) for c in range(nw)]
    for r in range(nh):
        sy = min(h - 1, int(r * h / nh))
        srow = sy * w
        base = r * nw
        for c in range(nw):
            out[base + c] = data[srow + xs[c]]
    return bytes(out)


def edge_density(buf, mask, thr=0.06):
    """选区内「强梯度」像素占比：条纹/补丁这类人造结构会明显偏高。"""
    w, h = buf.width, buf.height
    lum = buf.luminance()
    hit = total = 0
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            if mask[i] <= 128:
                continue
            gx = lum[i + 1] - lum[i - 1]
            gy = lum[i + w] - lum[i - w]
            if (gx * gx + gy * gy) ** 0.5 > thr:
                hit += 1
            total += 1
    return hit / float(max(1, total))


def formulas(s, ed, inside_colour):
    """几套总分。s 是 quality.Score，ed 是边缘密度。"""
    out = {}
    out["V0 现状(insert)"] = s.total
    out["V1 现状(removal)"] = (2.0 * max(0.0, s.seam - 1.0)
                               + 0.6 * max(0.0, -math.log(max(s.lap_ratio, 1e-6)))
                               + 0.6 * max(0.0, math.log(max(s.lap_ratio, 1e-6) / 1.5))
                               + 3.0 * s.colour + 6.0 * s.frame + 8.0 * s.leak)
    out["V2 去掉「比周围糊」"] = (2.0 * max(0.0, s.seam - 1.0)
                                 + 0.6 * max(0.0, math.log(max(s.lap_ratio, 1e-6) / 1.5))
                                 + 3.0 * s.colour + 6.0 * s.frame + 8.0 * s.leak)
    out["V3 V2+结构密度"] = out["V2 去掉「比周围糊」"] + 4.0 * ed
    out["V4 V3+色差加重"] = (2.0 * max(0.0, s.seam - 1.0)
                             + 0.6 * max(0.0, math.log(max(s.lap_ratio, 1e-6) / 1.5))
                             + 6.0 * s.colour + 6.0 * s.frame + 8.0 * s.leak
                             + 4.0 * ed)
    return out


for dname, names in SETS.items():
    d = os.path.join(r"D:/ComfyUI/test-out", dname)
    if not os.path.isdir(d):
        print("跳过（没有）", dname)
        continue
    bw, bh, base_px = load_rgba(os.path.join(d, "base.png"))
    mw, mh, mask_px = load_rgba(os.path.join(d, "mask.png"))
    gray = bytes(mask_px[i * 4] for i in range(mw * mh))
    scale = float(SCORE_SIDE) / max(1, max(bw, bh))
    sw = max(8, int(round(bw * scale)))
    sh = max(8, int(round(bh * scale)))
    base = Q.Buffer(sw, sh, scale_rgba(base_px, bw, bh, sw, sh), 4)
    small_mask = scale_gray(gray, mw, mh, sw, sh)
    cands = []
    for i in range(3):
        cw, chh, px = load_rgba(os.path.join(d, "cand%d.png" % i))
        cands.append(Q.Buffer(sw, sh, scale_rgba(px, cw, chh, sw, sh), 4))
    dist = Q.signed_distance(sw, sh, small_mask)

    print("\n==== %s  (%dx%d → 打分 %dx%d)" % (dname, bw, bh, sw, sh))
    rows = []
    for name, c in zip(names, cands):
        s = Q.score(base, c, small_mask, True, dist)
        ed = edge_density(c, small_mask)
        rows.append((name, s, ed))
        print("  %-6s seam %5.2f lap %5.3f colour %5.3f frame %5.3f "
              "leak %5.3f  边缘密度 %5.3f"
              % (name, s.seam, s.lap_ratio, s.colour, s.frame, s.leak, ed))

    keys = list(formulas(rows[0][1], rows[0][2], 0).keys())
    for k in keys:
        tots = [formulas(s, ed, 0)[k] for _n, s, ed in rows]
        best = names[min(range(3), key=lambda i: tots[i])]
        flag = "✓" if best == GOOD else "✗"
        print("  %-18s %s  选出 %s %s" % (
            k, " ".join("%6.3f" % t for t in tots), best, flag))
