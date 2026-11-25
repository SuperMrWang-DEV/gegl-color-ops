"""把配好的旁白转回文字，和稿子逐句比对，找出读错的地方。

用法：
    python tools/video/asr_check.py            # 转写 audio/ 下全部 mp3
    python tools/video/asr_check.py 01-what    # 只查一条

faster-whisper 装在 3.13 那个解释器里（见 README），模型 small。
转写结果里凡是出现"哥格勒""计一计"这类东西，就说明缩写被念成了拼音；
中文错字则多半是多音字。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AUD = os.path.join(HERE, "audio")
sys.path.insert(0, HERE)
from script import SCENES  # noqa: E402


def load_model():
    from faster_whisper import WhisperModel
    return WhisperModel("small", device="cpu", compute_type="int8")


def to_pcm(src):
    """faster-whisper 自带的解码依赖 av，版本一错位就炸；这里自己解成
    16k 单声道 float32 数组直接喂给模型，绕开 av。"""
    import subprocess, tempfile, wave
    import numpy as np
    dst = os.path.join(tempfile.gettempdir(), "asr_" + os.path.basename(src) + ".wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", dst], check=True)
    with wave.open(dst) as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(model, path, prompt=None):
    """prompt 会强烈影响专有名词的写法（写了 GEGL 它就把什么音都往 GEGL 上凑），
    所以查读音时要传 prompt=""，让它自由转写。"""
    segs, _ = model.transcribe(to_pcm(path), language="zh", beam_size=5,
                               initial_prompt=prompt)
    return "".join(s.text for s in segs).strip()


def norm(s):
    """比对用：去掉空格和标点。"""
    import re
    return re.sub(r"[\s，。：；！？、,.!?;:]", "", s)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    model = load_model()
    bad = 0
    for sc in SCENES:
        if only and only not in sc["key"]:
            continue
        mp3 = os.path.join(AUD, sc["key"] + ".mp3")
        if not os.path.exists(mp3):
            continue
        got = transcribe(model, mp3)
        want = sc["narr"]
        flag = " " if norm(got) == norm(want) else "!"
        if flag == "!":
            bad += 1
            print("-" * 72)
            print("%s %s" % (flag, sc["key"]))
            print("  稿:", want)
            print("  听:", got)
        else:
            print("%s %s  一致" % (flag, sc["key"]))
    print("\n合计 %d 条待看" % bad)


if __name__ == "__main__":
    main()
