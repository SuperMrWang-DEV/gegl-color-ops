"""试听样音：把修订后的念法用几个音色念一遍，拼成一条，连听就能挑。

    python tools/video/audition.py

产出 outputs/video/audition.mp3 + audition.txt（带时间轴）。
"念错清单"里 GIMP/GEGL 那几句都含在样句里，所以这一条也能顺便验收修订。
"""
import asyncio
import os
import subprocess
import sys

VDIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(VDIR))
sys.path.insert(0, VDIR)
from pron import spoken  # noqa: E402

OUT = os.path.join(os.path.dirname(ROOT), "outputs", "video")
TMP = os.path.join(VDIR, "audio", "_audition")
RATE = "-2%"

LINES = [
    "GEGL 是 GIMP 3 的滤镜内核，一个滤镜就是一个算子。这些算子带 lb 前缀，在菜单里单占一栏。",
    "木偶变形用移动最小二乘，标几个钉子周围跟着走；自由变形用 FFD 加双三次面片，能把曲面捏得很顺。",
    "抠图两条路：AI 走 ComfyUI 的 RMBG 模型，本地走四边泛洪，纯色背景毫秒级出结果。",
]

VOICES = [
    ("zh-CN-YunxiNeural", "云希 · 现用"),
    ("zh-CN-YunjianNeural", "云健 · 浑厚解说"),
    ("zh-CN-YunyangNeural", "云扬 · 新闻播音"),
]


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(" ".join(cmd) + "\n" + r.stderr[-800:])


def dur(p):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", p], capture_output=True, text=True).stdout.strip())


async def main():
    import edge_tts
    os.makedirs(TMP, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    parts, lines = [], []
    t = 0.0

    # 0. 旧念法（直接取已成片里那一句的开头 6 秒）
    old = os.path.join(VDIR, "audio", "01-what.mp3")
    if os.path.exists(old):
        p = os.path.join(TMP, "a_old.mp3")
        sh(["ffmpeg", "-y", "-v", "error", "-i", old, "-t", "7", p])
        parts.append(p)
        lines.append("%5.1fs  旧念法（原片）：GEGL / GIMP 都是引擎自己猜的读法" % t)
        t += dur(p) + 0.7

    for vi, (voice, label) in enumerate(VOICES, 1):
        lines.append("")
        lines.append("%5.1fs  ── %s ──" % (t, label))
        for li, src in enumerate(LINES, 1):
            say = spoken(src)
            p = os.path.join(TMP, "v%d_%d.mp3" % (vi, li))
            if not os.path.exists(p):
                await edge_tts.Communicate(say, voice, rate=RATE).save(p)
            parts.append(p)
            lines.append("%5.1fs    %d. %s" % (t, li, say[:34] + ("…" if len(say) > 34 else "")))
            t += dur(p) + 0.7

    # 逐段加静音再拼
    wavs = []
    for i, p in enumerate(parts):
        w = os.path.join(TMP, "s%02d.wav" % i)
        sh(["ffmpeg", "-y", "-v", "error", "-i", p,
            "-af", "apad=pad_dur=0.7,aresample=48000", "-ac", "2", w])
        wavs.append(w)
    lst = os.path.join(TMP, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for w in wavs:
            f.write("file '%s'\n" % w.replace("\\", "/"))
    out = os.path.join(OUT, "audition.mp3")
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-b:a", "160k", out])
    txt = os.path.join(OUT, "audition.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nOUT", out, "%.1fs" % dur(out))


if __name__ == "__main__":
    asyncio.run(main())
