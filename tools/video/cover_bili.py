"""B 站投稿封面（16:10，官方建议 1146×717）。

和 4K 片头封面不是一个东西：
- 比例是 16:10，不是 16:9；
- 尺寸小（信息流里缩到 300px 宽），所以主标题要少字、极大；
- 底部固定一条链接条，写上仓库主页，缩到手机端也能认出是 GitHub。

    python tools/video/cover_bili.py

产出 outputs/video/cover-bilibili.png（2292×1434）和 -1146.jpg（可直接上传）。
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTDIR = os.path.join(os.path.dirname(ROOT), "outputs", "video")
W, H = 2292, 1434                      # 16:10，2 倍于官方建议尺寸
BG = (8, 11, 17)
INK = (240, 244, 252)
INK2 = (156, 168, 190)
ACCENT = (111, 116, 255)
ACCENT2 = (176, 180, 255)
CYAN = (34, 211, 238)

BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
REG = r"C:\Windows\Fonts\msyh.ttc"
MONO = r"C:\Windows\Fonts\consola.ttf"

REPO = "github.com/SuperMrWang-DEV/gegl-color-ops"


def f(p, s):
    return ImageFont.truetype(p, s)


def bg():
    im = Image.new("RGB", (W, H), BG)
    for box, col, blur, alpha in (
            ([W * .34, -H * .75, W * 1.3, H * .9], (54, 62, 156), 260, 80),
            ([-W * .34, H * .42, W * .52, H * 1.45], (14, 88, 122), 260, 38)):
        g = Image.new("L", (W, H), 0)
        ImageDraw.Draw(g).ellipse(box, fill=alpha)
        g = g.filter(ImageFilter.GaussianBlur(blur))
        im.paste(Image.new("RGB", (W, H), col), (0, 0), g)
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 96):
        gd.line([(x, 0), (x, H)], fill=(255, 255, 255, 7))
    for y in range(0, H, 96):
        gd.line([(0, y), (W, y)], fill=(255, 255, 255, 7))
    return Image.alpha_composite(im.convert("RGBA"), grid).convert("RGB")


def paste_shot(im, path, box, size, top, radius=24):
    """右侧那张真实对比图：裁出页面里的 Original/Result 条，加圆角+投影。"""
    shot = Image.open(path).convert("RGB").crop(box).resize(size, Image.LANCZOS)
    tw, th = size
    bx, by = W - tw - 108, top
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw - 1, th - 1], radius, fill=255)
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).rounded_rectangle([bx, by + 26, bx + tw, by + th + 26],
                                         radius, fill=104)
    sh = sh.filter(ImageFilter.GaussianBlur(46))
    im.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), sh)
    im.paste(shot, (bx, by), mask)
    ring = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle([0, 0, tw - 1, th - 1], radius,
                                           outline=(126, 136, 172, 140), width=3)
    im.paste(ring, (bx, by), ring)
    return bx, by, th


def main():
    im = bg()
    d = ImageDraw.Draw(im)
    x = 112

    # 1. 标签行
    d.rounded_rectangle([x, 96, x + 16, 96 + 40], 6, fill=ACCENT)
    d.text((x + 38, 96), "GEGL 算子库 · 免费开源 · GPL-3.0",
           font=f(BOLD, 46), fill=(176, 180, 255))

    # 2. 主标题：GIMP 3 单独一行放到最大，缩略图里也认得出来
    d.text((x - 8, 178), "GIMP 3", font=f(BOLD, 232), fill=INK)
    mid = f(BOLD, 142)
    d.text((x - 6, 470), "少了 54 个", font=mid, fill=INK)
    d.text((x - 6, 634), "调色算子", font=mid, fill=ACCENT2)
    d.rounded_rectangle([x, 830, x + 330, 840], 5, fill=ACCENT)

    # 3. 一句话介绍
    sub = f(REG, 50)
    d.text((x, 900), "色阶、曲线、蒙版、抠图、变形、透视", font=sub, fill=INK2)
    d.text((x, 966), "另配 31 个插件，把算子串成流程", font=sub, fill=INK2)

    # 4. 右侧真实效果图：下压到链接条上方，中间的空白就没了
    shot = os.path.join(ROOT, "tools", "video", "shots", "op-lab-curves.png")
    if os.path.exists(shot):
        bx, by, th = paste_shot(im, shot, (360, 660, 2226, 1310), (980, 613), 470)
        d.text((bx + 4, by + th + 34), "同一张测试卡，左原图，右结果",
               font=f(REG, 32), fill=(124, 136, 160))

    # 5. 底部链接条：通栏，缩到 300px 宽也还在
    bar_l, bar_r = 96, W - 96
    bar_t, bar_b = H - 168, H - 76
    bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    bd.rounded_rectangle([bar_l, bar_t, bar_r, bar_b], 18, fill=(18, 22, 34, 235),
                         outline=(78, 88, 120, 255), width=2)
    im.paste(bar, (0, 0), bar)

    # GH 小徽标
    cy = (bar_t + bar_b) // 2
    bd = ImageDraw.Draw(im)
    bd.rounded_rectangle([bar_l + 26, cy - 26, bar_l + 96, cy + 26], 10, fill=ACCENT)
    bd.text((bar_l + 38, cy - 19), "GH", font=f(BOLD, 30), fill=(255, 255, 255))

    bd.text((bar_l + 122, cy - 25), REPO, font=f(MONO, 42), fill=(226, 232, 245))
    # 右端留空：B 站播放页会在右下角叠一个时长标签，别把话写在那儿

    os.makedirs(OUTDIR, exist_ok=True)
    png = os.path.join(OUTDIR, "cover-bilibili.png")
    im.save(png)
    jpg = os.path.join(OUTDIR, "cover-bilibili-1146.jpg")
    im.resize((1146, 717), Image.LANCZOS).save(jpg, quality=92, subsampling=0)
    for p in (png, jpg):
        print("OK", p, os.path.getsize(p) // 1024, "KB")


if __name__ == "__main__":
    main()
