"""把分镜渲染成 3840x2160 的画面（PNG）。

深色底 + 紫蓝 accent，和站点视觉一致。文字全部画进底图，后面只做轻微推近，
所以坐标系就是最终成片坐标。
"""
import glob
import json
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "tools", "video", "frames")
SHOTS = os.path.join(ROOT, "tools", "video", "shots")

W, H = 3840, 2160
M = 200                     # 左右安全边

BG = (8, 11, 17)
INK = (240, 244, 252)
INK2 = (154, 166, 188)
INK3 = (110, 122, 145)
ACCENT = (111, 116, 255)
CYAN = (34, 211, 238)
LINE = (40, 48, 64)

F_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
F_REG = r"C:\Windows\Fonts\msyh.ttc"
F_MONO = r"C:\Windows\Fonts\consola.ttf"
F_MONOB = r"C:\Windows\Fonts\consolab.ttf"


def font(path, size):
    return ImageFont.truetype(path, size)


def bg_layer():
    """深色底 + 右上角光晕 + 极淡网格。"""
    im = Image.new("RGB", (W, H), BG)
    glow = Image.new("L", (W, H), 0)
    g = ImageDraw.Draw(glow)
    g.ellipse([W * .42, -H * .55, W * 1.32, H * .62], fill=64)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    im.paste(Image.new("RGB", (W, H), (46, 54, 140)), (0, 0), glow)

    glow2 = Image.new("L", (W, H), 0)
    g2 = ImageDraw.Draw(glow2)
    g2.ellipse([-W * .25, H * .55, W * .55, H * 1.35], fill=34)
    glow2 = glow2.filter(ImageFilter.GaussianBlur(240))
    im.paste(Image.new("RGB", (W, H), (16, 78, 110)), (0, 0), glow2)

    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 120):
        gd.line([(x, 0), (x, H)], fill=(255, 255, 255, 7))
    for y in range(0, H, 120):
        gd.line([(0, y), (W, y)], fill=(255, 255, 255, 7))
    im = Image.alpha_composite(im.convert("RGBA"), grid).convert("RGB")

    # 底部渐暗，给字幕留出干净的底
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        a = max(0, (y - H * .72) / (H * .28))
        grad.putpixel((0, y), int(150 * min(1, a) ** 1.6))
    grad = grad.resize((W, H))
    dark = Image.new("RGB", (W, H), (4, 6, 10))
    return Image.composite(dark, im, grad)


def spaced(draw, xy, text, f, fill, tracking=0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + tracking


def wrap(draw, text, f, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if draw.textlength(cur + ch, font=f) > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def head(im, d, chapter, title, sub, title_size=104, top=96):
    y = top
    if chapter:
        spaced(d, (M, y), chapter, font(F_BOLD, 30), ACCENT, tracking=6)
        y += 62
    d.text((M, y), title, font=font(F_BOLD, title_size), fill=INK)
    y += int(title_size * 1.30)
    if sub:
        sf = font(F_REG, 38)
        for ln in wrap(d, sub, sf, W - 2 * M):
            d.text((M, y), ln, font=sf, fill=INK2)
            y += 54
    return y


def card(im, src, box, radius=24, shadow=True):
    """把一张截图放进圆角卡片（自动裁顶部、按目标比例缩放）。"""
    x0, y0, x1, y1 = box
    tw, th = x1 - x0, y1 - y0
    im2 = Image.open(src).convert("RGB")
    need_h = int(im2.width * th / tw)
    if im2.height > need_h:
        im2 = im2.crop((0, 0, im2.width, need_h))
    elif im2.height < need_h:
        scale = th / im2.height
        im2 = im2.resize((int(im2.width * scale), th), Image.LANCZOS)
        if im2.width < tw:
            pad = Image.new("RGB", (tw, th), (13, 17, 25))
            pad.paste(im2, ((tw - im2.width) // 2, 0))
            im2 = pad
        else:
            im2 = im2.crop((0, 0, tw, th))
    im2 = im2.resize((tw, th), Image.LANCZOS)

    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw - 1, th - 1], radius, fill=255)

    if shadow:
        sh = Image.new("L", (W, H), 0)
        ImageDraw.Draw(sh).rounded_rectangle(
            [x0, y0 + 26, x1, y1 + 26], radius, fill=90)
        sh = sh.filter(ImageFilter.GaussianBlur(46))
        im.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), sh)

    im.paste(im2, (x0, y0), mask)

    # 底部渐隐：裁切处常落在半行文字上，硬切很脏
    fh = 220
    grad = Image.new("L", (1, fh), 0)
    for i in range(fh):
        grad.putpixel((0, i), int(255 * (i / fh) ** 1.15))
    grad = grad.resize((tw, fh))
    fade = Image.new("RGB", (tw, fh), BG)
    im.paste(fade, (x0, y0 + th - fh), grad)

    # 1px 描边
    ring = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle(
        [0, 0, tw - 1, th - 1], radius, outline=(90, 100, 130, 120), width=2)
    im.paste(ring, (x0, y0), ring)
    return im


def render_shot(im, d, sc):
    y = head(im, d, sc["chapter"], sc["title"], sc["sub"])
    top = max(y + 60, 470)
    src = os.path.join(SHOTS, sc["img"] + ".png")
    if not os.path.exists(src):
        return im
    x0, x1 = 400, W - 400
    card_h = min(int((x1 - x0) * 0.505), H - top - 200)
    card(im, src, (x0, top, x1, top + card_h))
    return im


def op_names():
    p = os.path.join(ROOT, "tools", "video", "op_titles.json")
    return json.load(open(p, encoding="utf-8"))


def render_grid(im, d, sc, groups):
    y = head(im, d, sc["chapter"], sc["title"], sc["sub"], title_size=92)
    names = op_names()
    members = []
    gl = sc["group"]
    for g in ([gl] if isinstance(gl, str) else gl):
        members += groups[g]

    n = len(members)
    cols = 2 if n <= 2 else 3 if n <= 3 else 4 if n <= 8 else 6
    gap = 40
    avail_w = W - 2 * 260
    cw = min(1000, (avail_w - (cols - 1) * gap) // cols)
    ch = int(cw / 1.471)
    rows = (n + cols - 1) // cols
    blk = rows * (ch + 34 + 56) + (rows - 1) * 46
    x0 = (W - (cols * cw + (cols - 1) * gap)) // 2
    y0 = int(max(y + 50, 470) + max(0, (H - 260 - max(y + 50, 470) - blk) / 2))

    for i, slug in enumerate(members[:18]):
        r, c = divmod(i, cols)
        bx = x0 + c * (cw + gap)
        by = y0 + r * (ch + 34 + 56 + 46)
        shot = os.path.join(ROOT, "ops", slug, "assets", "shot.png")
        if os.path.exists(shot):
            s = Image.open(shot).convert("RGB")
            s = s.crop((s.width // 2, 0, s.width, s.height))   # 右半 = 结果
            s = s.resize((cw, ch), Image.LANCZOS)
            mask = Image.new("L", (cw, ch), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], 14, fill=255)
            im.paste(s, (bx, by), mask)
            ImageDraw.Draw(im).rounded_rectangle(
                [bx, by, bx + cw - 1, by + ch - 1], 14, outline=(70, 80, 106), width=2)
        else:
            ph = Image.new("RGB", (cw, ch), (17, 21, 30))
            phd = ImageDraw.Draw(ph)
            for k in range(-ch, cw, 34):
                phd.line([(k, ch), (k + ch, 0)], fill=(26, 31, 44), width=8)
            mask = Image.new("L", (cw, ch), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], 14, fill=255)
            im.paste(ph, (bx, by), mask)
            ImageDraw.Draw(im).rounded_rectangle(
                [bx, by, bx + cw - 1, by + ch - 1], 14, outline=(70, 80, 106), width=2)
            note = "多输入算子 · 需在 GIMP 里建图"
            nf = font(F_REG, 26)
            d.text((bx + cw / 2, by + ch / 2), note, font=nf,
                   fill=(104, 116, 140), anchor="mm")
        label = names.get(slug, slug)
        size = 34 if len(label) <= 18 else 27
        d.text((bx + 2, by + ch + 16), label, font=font(F_BOLD, size), fill=(214, 222, 238))
        d.text((bx + 2, by + ch + 18 + int(size * 1.32)), "lb:" + slug,
               font=font(F_MONO, 21), fill=INK3)
    return im


def render_usage(im, d, sc):
    y = head(im, d, sc["chapter"], sc["title"], sc["sub"])
    items = [("GIMP 菜单", "SuperMrWang → Curves → LAB",
              "参数面板 + 实时预览，当非破坏滤镜挂图层"),
             ("gegl 命令行", "gegl in.jpg -o out.jpg -- lb:lab-curves",
              "批处理、脚本、CI 里跑，无需 GIMP"),
             ("ComfyUI 节点", "lb:lab-curves",
              "接进 AI 工作流，出图前先校色")]
    top = int(max(y + 50, 470) + max(0, (H - 250 - max(y + 50, 470) - 880) / 2))
    cw, gap = 1040, 60
    x0 = (W - (3 * cw + 2 * gap)) // 2
    for i, (t, code, desc) in enumerate(items):
        bx = x0 + i * (cw + gap)
        box = [bx, top, bx + cw, top + 470]
        panel = Image.new("RGBA", (cw, 470), (255, 255, 255, 0))
        pd = ImageDraw.Draw(panel)
        pd.rounded_rectangle([0, 0, cw - 1, 469], 24,
                             fill=(20, 25, 36, 255), outline=(52, 60, 82, 255), width=2)
        im.paste(panel, (bx, top), panel)
        d.text((bx + 54, top + 58), t, font=font(F_BOLD, 54), fill=INK)
        d.text((bx + 54, top + 148), code, font=font(F_MONO, 26), fill=CYAN)
        yy = top + 220
        for ln in wrap(d, desc, font(F_REG, 32), cw - 108):
            d.text((bx + 54, yy), ln, font=font(F_REG, 32), fill=INK2)
            yy += 46

    # 一段真实命令行
    top2 = top + 540
    lines = ["$ ./install.sh --verify",
             "  54 modules  →  %LOCALAPPDATA%\\gegl-0.4\\plug-ins",
             "  lb:levels  lb:lab-curves  lb:hue-saturation  ...",
             "  verify: 54/54 loaded"]
    box2 = [M, top2, W - M, top2 + 330]
    panel = Image.new("RGBA", (box2[2] - box2[0], 330), (10, 14, 21, 255))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle([0, 0, box2[2] - box2[0] - 1, 329], 20,
                         fill=(10, 14, 21, 255), outline=(46, 54, 74, 255), width=2)
    im.paste(panel, (box2[0], box2[1]), panel)
    yy = top2 + 46
    for i, ln in enumerate(lines):
        d.text((box2[0] + 46, yy), ln, font=font(F_MONO, 32),
               fill=(126, 231, 168) if i == 0 else (176, 188, 210))
        yy += 60
    return im


def render_tree(im, d, sc):
    y = head(im, d, sc["chapter"], sc["title"], sc["sub"])
    rows = [("gegl-color-ops/", ""),
            ("├── build.sh", "一键编译（gcc，跨平台）"),
            ("├── install.sh", "装到 GEGL 用户插件目录，--verify 自检"),
            ("├── meson.build", "等价工程，Linux / macOS / CI 用"),
            ("├── common/", "共用的曲线插值、LUT、色彩空间换算"),
            ("├── ops/<算子名>/", "54 个目录：<算子名>.c + 说明 + 截图"),
            ("├── plugin/", "31 个 Python 插件"),
            ("├── dist/", "编好的模块，给不想编译的人"),
            ("├── docs/", "GitHub Pages 站点（生成物，别手改）"),
            ("└── tools/", "测试图、冒烟、回归、站点生成")]
    rows_h = len(rows) * 128
    top = int(max(y + 50, 470) + max(0, (H - 250 - max(y + 50, 470) - rows_h) / 2))
    fm = font(F_MONO, 42)
    y2 = top
    for i, (p, note) in enumerate(rows):
        main = (126, 231, 168) if i == 0 else (222, 230, 244)
        d.text((M, y2), p, font=font(F_MONOB, 42) if i == 0 else fm, fill=main)
        d.text((M + 720, y2 + 6), note, font=font(F_REG, 31), fill=INK2)
        y2 += 128

    # 右侧补一块统计，否则右边三分之一全是空的
    bx = 2560
    stats = [("54", "个算子", ACCENT), ("31", "个插件", CYAN), ("10", "个分组", (126, 231, 168))]
    sy = top + 10
    d.line([(bx - 90, sy - 20), (bx - 90, sy + 470)], fill=(44, 52, 70), width=2)
    for num, label, col in stats:
        d.text((bx, sy), num, font=font(F_BOLD, 128), fill=col)
        d.text((bx + 6, sy + 158), label, font=font(F_REG, 36), fill=INK2)
        sy += 220
    return im


def render_hero(im, d, sc):
    f = font(F_BOLD, 148)
    sub = font(F_REG, 44)
    tw = d.textlength(sc["title"], font=f)
    d.text(((W - tw) / 2, 830), sc["title"], font=f, fill=INK)
    # 强调线
    d.rounded_rectangle([(W - 260) / 2, 1050, (W + 260) / 2, 1056], 3, fill=ACCENT)
    st = sc["sub"]
    d.text(((W - d.textlength(st, font=sub)) / 2, 1120), st, font=sub, fill=INK2)

    tag = "GEGL 色彩算子 · Python 插件"
    tf = font(F_BOLD, 34)
    d.text(((W - d.textlength(tag, font=tf)) / 2, 660), tag, font=tf, fill=ACCENT)
    return im


def render_outro(im, d, sc):
    f = font(F_BOLD, 132)
    d.text(((W - d.textlength(sc["title"], font=f)) / 2, 840), sc["title"],
           font=f, fill=INK)
    sub = font(F_REG, 42)
    d.text(((W - d.textlength(sc["sub"], font=sub)) / 2, 1020), sc["sub"],
           font=sub, fill=INK2)

    links = [("github.com/SuperMrWang-DEV/gegl-color-ops", "源码 / 预编译包"),
             ("supermrwang-dev.github.io/gegl-color-ops", "在线文档")]
    yy = 1180
    fm = font(F_MONO, 40)
    for url, note in links:
        u = font(F_REG, 34)
        w = d.textlength(url, font=fm)
        nx = (W - (w + 30 + d.textlength(note, font=u))) / 2
        d.text((nx, yy), url, font=fm, fill=CYAN)
        d.text((nx + w + 30, yy + 4), note, font=u, fill=INK3)
        yy += 90
    return im


def main():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from script import SCENES
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import set_menu_group as SMG

    os.makedirs(OUT, exist_ok=True)
    for sc in SCENES:
        im = bg_layer()
        d = ImageDraw.Draw(im)
        k = sc["kind"]
        if k == "hero":
            render_hero(im, d, sc)
        elif k == "shot":
            render_shot(im, d, sc)
        elif k == "grid":
            render_grid(im, d, sc, SMG.GROUPS)
        elif k == "usage":
            render_usage(im, d, sc)
        elif k == "tree":
            render_tree(im, d, sc)
        elif k == "outro":
            render_outro(im, d, sc)
        p = os.path.join(OUT, sc["key"] + ".png")
        im.save(p)
        print("OK", os.path.basename(p), os.path.getsize(p) // 1024, "KB")


if __name__ == "__main__":
    main()
