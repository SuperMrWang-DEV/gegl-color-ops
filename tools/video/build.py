"""合成 4K 介绍片。

流程：旁白 → edge-tts（缓存）→ 量时长定镜长 → 渲染画面 → 每镜编码（含字幕
烧入）→ concat → 混音 → 成片。
"""
import asyncio
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VDIR = os.path.join(ROOT, "tools", "video")
AUD = os.path.join(VDIR, "audio")
CLIPS = os.path.join(VDIR, "clips")
FRAMES = os.path.join(VDIR, "frames")
BUILD = os.path.join(VDIR, "build")
PRE = os.path.join(VDIR, "pre")
# 成片不进仓库（4K 五分钟 160MB+，GitHub 单文件上限 100MB）
OUT = os.path.join(os.path.dirname(ROOT), "outputs", "video")

VOICE = "zh-CN-YunjianNeural"   # 云健：低沉浑厚，技术解说压得住
RATE = "-2%"
W, H, FPS = 3840, 2160, 30
LEAD, TAIL, MIN_HOLD = 0.38, 0.72, 4.2

sys.path.insert(0, VDIR)
from script import SCENES  # noqa: E402
from pron import spoken    # noqa: E402


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(" ".join(cmd)[:300] + "\n" + r.stderr[-1500:])
    return r.stdout


def dur_of(p):
    out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", p])
    return float(out.strip())


# ---------- 1. 配音 ----------

async def tts_all():
    """配音带清单缓存：spoken 文本或音色一变，对应的 mp3 就自动重合成。

    以前只判"文件存在"，改了稿子还得手动删 audio/，很容易出"画面新、声音旧"。
    """
    import hashlib
    import edge_tts
    os.makedirs(AUD, exist_ok=True)
    mpath = os.path.join(AUD, "_manifest.json")
    manifest = {}
    if os.path.exists(mpath):
        manifest = json.load(open(mpath, encoding="utf-8"))
    for sc in SCENES:
        say = spoken(sc["narr"])
        tag = hashlib.md5(("%s|%s|%s" % (say, VOICE, RATE)).encode("utf-8")).hexdigest()[:10]
        mp3 = os.path.join(AUD, sc["key"] + ".mp3")
        if manifest.get(sc["key"]) == tag and os.path.exists(mp3) and os.path.getsize(mp3) > 2000:
            continue
        c = edge_tts.Communicate(say, VOICE, rate=RATE)
        await c.save(mp3)
        manifest[sc["key"]] = tag
        print("TTS", sc["key"], round(dur_of(mp3), 2), "s")
    json.dump(manifest, open(mpath, "w", encoding="utf-8"), indent=1)


# ---------- 2. 字幕 ----------

def split_lines(text, maxlen=20):
    """按标点切字幕行。切点只落在标点之后，避免出现以逗号开头的行。"""
    parts = re.split(r"(?<=[，。：；！？])", text)
    lines, cur = [], ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not cur:
            cur = p
        elif len(cur) + len(p) <= maxlen:
            cur += p
        else:
            lines.append(cur)
            cur = p
        while len(cur) > maxlen + 6:
            cut = max(cur.rfind(ch, 0, maxlen + 6) for ch in "，、：")
            cut = cut + 1 if cut > maxlen // 2 else maxlen
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur:
        lines.append(cur)

    out = []
    for l in lines:
        if out and l and l[0] in "，。：；！？、）":
            out[-1] += l[0]
            l = l[1:]
        if l.strip():
            out.append(l.strip())
    return out


def ass_for(sc, voice_dur, hold):
    """该镜的字幕：从 LEAD 开始，按字数比例分配时间。"""
    lines = split_lines(sc["narr"])
    total = sum(len(l) for l in lines) or 1
    usable = min(voice_dur + 0.25, hold - LEAD - 0.15)
    t = LEAD
    ev = []
    for l in lines:
        d = usable * len(l) / total
        ev.append((t, t + d, l))
        t += d
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: %d
PlayResY: %d
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Microsoft YaHei,66,&H00F7FBFF,&H00F7FBFF,&H00120A06,&H96000000,-1,0,0,0,100,100,1,0,1,4,2,2,120,120,92,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" % (W, H)
    body = ""
    for a, b, txt in ev:
        body += "Dialogue: 0,%s,%s,Sub,,0,0,0,,%s\n" % (ts(a), ts(b), txt)
    return head + body


def ts(t):
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return "%d:%02d:%05.2f" % (h, m, s)


# ---------- 3. 单镜编码 ----------

# 预放大尺寸：crop 只能在整数像素上取，所以留出 400x160 的可滑动余量。
# 画面左右安全边距（render.M=400）就是给这块让的，别把 M 调小。
# 关键：每帧位移必须严格等量（1 或 2 px），速度恒定的整数平移是平滑的；
# zoompan 那种整数缩放会让位移在 -2..+2 之间来回跳，那就是抖动。
PW, PH = 4240, 2320
XSPAN = PW - W


def prep(sc):
    """把画面预放大一次，后面每帧只做无损 crop。"""
    src = os.path.join(FRAMES, sc["key"] + ".png")
    dst = os.path.join(PRE, sc["key"] + ".png")
    os.makedirs(PRE, exist_ok=True)
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        sh(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
            "-vf", "scale=%d:%d:flags=lanczos" % (PW, PH), dst])
    return dst


def make_clip(sc, voice, hold, idx, fade_in, fade_out):
    png = prep(sc)
    mp4 = os.path.join(CLIPS, "%02d.mp4" % idx)
    wav = os.path.join(CLIPS, "%02d.wav" % idx)
    ass = os.path.join(BUILD, "%02d.ass" % idx)
    os.makedirs(CLIPS, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    open(ass, "w", encoding="utf-8").write(ass_for(sc, voice, hold))

    n = int(round(hold * FPS))
    # 严格 1px/帧：速度恒定，人眼看到的是平滑横移
    dpx = 1
    x0 = max(0, XSPAN - n * dpx)
    if idx % 2:
        xexpr = "%d+(%d-n)*%d" % (x0, n - 1, dpx)   # 从右往左
    else:
        xexpr = "%d+n*%d" % (x0, dpx)               # 从左往右
    vf = (
        # exact=1 必须加：默认 crop 会把 x 舍入到偶数，2px 位移就变成
        # 「+2 / 0」交替 —— 平均速度对但节奏不均，肉眼就是抖。
        "crop=%d:%d:x='%s':y=%d:exact=1,"
        "ass=%s,"
        "fade=t=in:st=0:d=%.2f,fade=t=out:st=%.2f:d=%.2f,"
        "format=yuv420p"
    ) % (W, H, xexpr, (PH - H) // 2, os.path.basename(ass),
         fade_in, hold - fade_out, fade_out)
    sh(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS),
        "-t", "%.2f" % hold, "-i", png,
        "-vf", vf, "-frames:v", str(n),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-g", str(FPS * 2), "-an", mp4], cwd=BUILD)

    # 音频：前导静音 + 配音 + 补到镜长
    src = os.path.join(AUD, sc["key"] + ".mp3")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
        "-af", "adelay=%d:all=1,apad=whole_dur=%.3f,aresample=48000" % (LEAD * 1000, hold),
        "-ac", "2", "-t", "%.3f" % hold, wav])
    return mp4, wav


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(tts_all())

    plan = []
    for i, sc in enumerate(SCENES):
        v = dur_of(os.path.join(AUD, sc["key"] + ".mp3"))
        hold = max(v + LEAD + TAIL, MIN_HOLD)
        plan.append((i, sc, v, round(hold, 3)))

    total = sum(p[3] for p in plan)
    print("镜头 %d，总长 %.1fs（%.1f 分钟）" % (len(plan), total, total / 60))
    for i, sc, v, hold in plan:
        print("  %-14s voice %5.2f  hold %5.2f" % (sc["key"], v, hold))

    if only == "plan":
        return

    for i, sc, v, hold in plan:
        fade_in = 0.55 if i == 0 else 0.0
        fade_out = 0.9 if i == len(plan) - 1 else 0.0
        make_clip(sc, v, hold, i, fade_in, fade_out)
        print("CLIP", i, sc["key"], "%.1fs" % hold, flush=True)

    # 拼接
    lst = os.path.join(BUILD, "clips.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for i, _, _, _ in plan:
            f.write("file '%s'\n" % os.path.join(CLIPS, "%02d.mp4" % i).replace("\\", "/"))
    video = os.path.join(BUILD, "video.mp4")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", lst, "-c", "copy", video])

    alst = os.path.join(BUILD, "audio.txt")
    with open(alst, "w", encoding="utf-8") as f:
        for i, _, _, _ in plan:
            f.write("file '%s'\n" % os.path.join(CLIPS, "%02d.wav" % i).replace("\\", "/"))
    audio = os.path.join(BUILD, "audio.wav")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", alst, "-c", "copy", audio])

    os.makedirs(OUT, exist_ok=True)
    final = os.path.join(OUT, "gegl-color-ops-4k.mp4")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", audio,
        "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", final])
    print("DONE", final, "%.1f MB" % (os.path.getsize(final) / 1048576),
          "%.1fs" % dur_of(final))


if __name__ == "__main__":
    main()
