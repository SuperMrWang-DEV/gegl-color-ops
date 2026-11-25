"""生成 4K 封面（视频首帧/上传缩略图）。"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(os.path.dirname(ROOT), "outputs", "video", "cover.png")
W, H = 3840, 2160
BG = (8, 11, 17)
INK = (240, 244, 252)
INK2 = (154, 166, 188)
ACCENT = (111, 116, 255)
CYAN = (34, 211, 238)


def f(p, s):
    return ImageFont.truetype(p, s)


BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
REG = r"C:\Windows\Fonts\msyh.ttc"
MONO = r"C:\Windows\Fonts\consola.ttf"


def bg():
    im = Image.new("RGB", (W, H), BG)
    for box, col, blur, alpha in (
            ([W * .38, -H * .6, W * 1.35, H * .75], (52, 60, 150), 240, 70),
            ([-W * .3, H * .5, W * .5, H * 1.4], (14, 84, 118), 250, 36)):
        g = Image.new("L", (W, H), 0)
        ImageDraw.Draw(g).ellipse(box, fill=alpha)
        g = g.filter(ImageFilter.GaussianBlur(blur))
        im.paste(Image.new("RGB", (W, H), col), (0, 0), g)
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 120):
        gd.line([(x, 0), (x, H)], fill=(255, 255, 255, 8))
    for y in range(0, H, 120):
        gd.line([(0, y), (W, y)], fill=(255, 255, 255, 8))
    return Image.alpha_composite(im.convert("RGBA"), grid).convert("RGB")


def main():
    im = bg()
    d = ImageDraw.Draw(im)
    x = 230

    tag = "GEGL 算子库 · 免费开源 · GPL-3.0"
    tf = f(BOLD, 44)
    d.text((x, 696), tag, font=tf, fill=(176, 180, 255))

    d.text((x - 10, 764), "GIMP 3", font=f(BOLD, 268), fill=INK)

    mid = f(BOLD, 134)
    d.text((x - 6, 1142), "少了 54 个", font=mid, fill=INK)
    d.text((x - 6, 1290), "调色算子", font=mid, fill=(176, 180, 255))
    d.rounded_rectangle([x, 1482, x + 300, 1490], 4, fill=ACCENT)

    sub = f(REG, 44)
    for i, line in enumerate([
            "色阶 · 色彩平衡 · 通道混合 · 蒙版 · 抠图",
            "31 个 Python 插件把它串成流程"]):
        d.text((x, 1542 + i * 66), line, font=sub, fill=INK2)

    # 右侧：一张真实对比图
    src = os.path.join(ROOT, "tools", "video", "shots", "op-lab-curves.png")
    shot = Image.open(src).convert("RGB")
    shot = shot.crop((360, 660, 2226, 1310))         # 页面里的 Original/Result 对比条
    tw, th = 2000, 697
    shot = shot.resize((tw, th), Image.LANCZOS)
    bx, by = W - tw - 200, 820
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw - 1, th - 1], 26, fill=255)
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).rounded_rectangle([bx, by + 28, bx + tw, by + th + 28], 26, fill=96)
    sh = sh.filter(ImageFilter.GaussianBlur(52))
    im.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), sh)
    im.paste(shot, (bx, by), mask)
    ring = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle([0, 0, tw - 1, th - 1], 26,
                                           outline=(120, 130, 165, 130), width=3)
    im.paste(ring, (bx, by), ring)

    cap = f(REG, 30)
    d.text((bx + 4, by + th + 42), "同一张测试卡，左原图，右结果（lb:lab-curves）",
           font=cap, fill=(120, 132, 156))

    foot = f(MONO, 30)
    d.text((x, H - 190), "gegl-color-ops  ·  github.com/SuperMrWang-DEV", font=foot,
           fill=(96, 108, 132))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    im.save(OUT)
    print("OK", OUT, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()
