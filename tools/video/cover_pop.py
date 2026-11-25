"""按平台爆款样式重做封面 / 图例。

和 cover.py / cover_bili.py 的深色极简风不是一路：
- B 站：明黄撞黑、超粗大字、红色角标、右侧斜切截图区、底部黑条
- 小红书：奶油底、黑标题、荧光黄马克笔高亮、胶囊标签、红笔圈注
- YouTube：深色 + 黄字 + 红箭头指向对比图

    python tools/video/cover_pop.py          # 出样张到 outputs/media/_preview/
    python tools/video/cover_pop.py all      # 出全套并写回各平台目录
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJ = os.path.dirname(ROOT)
MEDIA = os.path.join(PROJ, "outputs", "media")
SHOTS = os.path.join(ROOT, "tools", "video", "shots")

BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
REG = r"C:\Windows\Fonts\msyh.ttc"
MONO = r"C:\Windows\Fonts\consola.ttf"

# B 站 / YouTube：黄黑撞色
YEL = (255, 211, 46)
YEL2 = (255, 236, 120)
BLK = (14, 16, 22)
DRK = (18, 20, 27)
WHT = (250, 250, 248)
RED = (232, 48, 40)

# 小红书：奶油底 + 荧光黄
CRM = (255, 249, 238)
CRM2 = (246, 238, 224)
INK = (28, 26, 24)
GRY = (120, 114, 104)
MARK = (255, 228, 66)
PNK = (255, 106, 130)


def f(p, s):
    return ImageFont.truetype(p, s)


def crop_fill(path, size, y_bias=0.2, x_bias=0.5):
    im = Image.open(path).convert("RGB")
    tw, th = size
    sw, sh = im.size
    want = tw / th
    if sw / sh > want:
        nw = int(sh * want)
        x0 = int((sw - nw) * x_bias)
        im = im.crop((x0, 0, x0 + nw, sh))
    else:
        nh = int(sw / want)
        y0 = min(max(0, int((sh - nh) * y_bias)), sh - nh)
        im = im.crop((0, y0, sw, y0 + nh))
    return im.resize(size, Image.LANCZOS)


def shadow_paste(im, shot, xy, radius=18, spread=26, alpha=110, border=None, bw=0):
    w, h = shot.size
    x, y = xy
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius, fill=255)
    sh = Image.new("L", im.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([x - 4, y + 14, x + w + 4, y + h + 22],
                                         radius, fill=alpha)
    sh = sh.filter(ImageFilter.GaussianBlur(spread))
    im.paste(Image.new("RGB", im.size, (0, 0, 0)), (0, 0), sh)
    im.paste(shot, (x, y), mask)
    if border:
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(lay).rounded_rectangle(
            [bw // 2, bw // 2, w - 1 - bw // 2, h - 1 - bw // 2],
            radius, outline=border, width=bw)
        im.paste(lay, (x, y), lay)


def pill(d, xy, text, font, bg, fg, padx=26, pady=12, radius=None):
    x, y = xy
    tw = d.textlength(text, font=font)
    h = font.size + pady * 2
    r = radius if radius is not None else h // 2
    d.rounded_rectangle([x, y, x + tw + padx * 2, y + h], r, fill=bg)
    d.text((x + padx, y + pady - 2), text, font=font, fill=fg)
    return tw + padx * 2, h


def arrow(d, pts, color, width=14, head=34):
    """折线 + 三角箭头，pts 最后一对是箭尖。"""
    d.line(pts, fill=color, width=width, joint="curve")
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    a = math.atan2(y1 - y0, x1 - x0)
    for s in (+1, -1):
        d.line([(x1, y1),
                (x1 - head * math.cos(a - s * 0.5), y1 - head * math.sin(a - s * 0.5))],
               fill=color, width=width)


def mark(d, text, font, xy, color, thick=0.55):
    """荧光笔高亮：文字后面一条略斜的色带。"""
    x, y = xy
    tw = d.textlength(text, font=font)
    h = font.size
    d.polygon([(x - 8, y + h * 0.80), (x + tw + 8, y + h * 0.74),
               (x + tw + 8, y + h * 1.04), (x - 8, y + h * 1.10)], fill=color)
    d.text((x, y), text, font=font, fill=INK)


# ---------------------------------------------------------------- B 站 16:10

def bili():
    W, H = 2292, 1434
    im = Image.new("RGB", (W, H), YEL)
    d = ImageDraw.Draw(im)

    # 右侧深色斜切区
    d.polygon([(1330, 0), (W, 0), (W, H), (1150, H)], fill=DRK)

    # 顶部红色角标
    pill(d, (96, 92), "GIMP 3 · 开源免费", f(BOLD, 52), RED, WHT)

    # 主标题：黑字压在黄底上，最深对比
    d.text((92, 250), "GIMP 3", font=f(BOLD, 250), fill=BLK)
    t2 = f(BOLD, 158)
    d.text((96, 566), "缺的 54 个", font=t2, fill=BLK)
    d.text((96, 748), "调色工具", font=t2, fill=BLK)

    # 手写感下划线
    d.line([(100, 946), (700, 936)], fill=RED, width=16)

    # 一句卖点
    d.text((96, 1000), "色阶 · 曲线 · 蒙版 · 抠图 · 变形", font=f(REG, 60), fill=(60, 54, 30))

    # 底部黑条
    d.rectangle([0, H - 168, W, H], fill=BLK)
    d.text((96, H - 132), "GEGL 算子库  /  31 个插件  /  源码可查",
           font=f(BOLD, 58), fill=YEL)
    pill(d, (W - 400, H - 146), "8 分钟", f(BOLD, 46), YEL, BLK)

    # 右侧截图：白框，斜切区里居中
    shot = crop_fill(os.path.join(SHOTS, "op-levels.png"), (1000, 700), 0.16)
    shadow_paste(im, shot, (1268, 300), radius=14, spread=30, alpha=150,
                 border=WHT, bw=10)
    d = ImageDraw.Draw(im)

    # 红箭头从标题指向图
    arrow(d, [(1090, 880), (1170, 800), (1246, 726)], RED, width=16, head=38)

    # 图上角标：真实截图（压在图左上角）
    pill(d, (1236, 258), "真实界面截图", f(BOLD, 40), WHT, BLK)
    return im


# ---------------------------------------------------------------- 小红书 3:4

CW, CH = 1242, 1656


def xhs_cover():
    im = Image.new("RGB", (CW, CH), CRM)
    d = ImageDraw.Draw(im)

    # 顶部胶囊
    pill(d, (76, 78), "GIMP 3 · 开源免费 · GPL-3.0", f(BOLD, 38), INK, CRM)

    # 大标题
    d.text((72, 210), "免费修图", font=f(BOLD, 132), fill=INK)
    y = 372
    mark(d, "缺的 54 个", f(BOLD, 132), (72, y), MARK)
    d.text((72, y + 152), "调色工具", font=f(BOLD, 132), fill=INK)

    d.text((76, 720), "不转模式，Lab 亮度直接拉", font=f(REG, 46), fill=GRY)

    # 截图：白边 + 圆角
    shot = crop_fill(os.path.join(SHOTS, "op-levels.png"), (CW - 152, 574), 0.14)
    shadow_paste(im, shot, (76, 806), radius=16, spread=24, alpha=70,
                 border=(255, 255, 255), bw=12)
    d = ImageDraw.Draw(im)

    # 红笔圈注：圈住左边的原图（只提亮肤色、衣服不动）
    d.ellipse([198, 1072, 566, 1328], outline=PNK, width=9)
    ann = f(BOLD, 42)
    for i, line in enumerate(("只提亮肤色", "衣服不动")):
        d.text((592, 1136 + i * 58), line, font=ann, fill=PNK,
               stroke_width=8, stroke_fill=(255, 255, 255))

    # 底部
    pill(d, (76, CH - 220), "6 张图讲完", f(BOLD, 44), INK, CRM)
    d.text((CW - 300, CH - 208), "右滑 →", font=f(BOLD, 48), fill=GRY)
    return im


# ---------------------------------------------------------------- 小红书内页

def xhs_page(idx, kicker, title, mark_line, cap, shot, y_bias=0.16, xb=0.5,
             bad=None):
    """小红书内页：奶油底 + 大标题 + 马克笔 + 白框截图 + 底部一句。"""
    im = Image.new("RGB", (CW, CH), CRM)
    d = ImageDraw.Draw(im)

    pill(d, (76, 74), "%02d / 06 · %s" % (idx, kicker), f(BOLD, 36), INK, CRM)

    ty = 196
    tf = f(BOLD, 118)
    for line in title:
        if line == mark_line:
            mark(d, line, tf, (72, ty), MARK)
        else:
            d.text((72, ty), line, font=tf, fill=INK)
        ty += 148

    if shot:
        h = 700
        img = crop_fill(shot, (CW - 152, h), y_bias, xb)
        shadow_paste(im, img, (76, ty + 40), radius=16, spread=24, alpha=74,
                     border=(255, 255, 255), bw=12)
        d = ImageDraw.Draw(im)
        if bad:
            bx0, by0, bx1, by1, note = bad
            d.ellipse([bx0, by0, bx1, by1], outline=PNK, width=9)
            d.text((bx1 + 24, by0 + 18), note, font=f(BOLD, 40), fill=PNK,
                   stroke_width=8, stroke_fill=(255, 255, 255))

    # 底部说明
    cf = f(REG, 42)
    lines = wrap_lines(d, cap, cf, CW - 152)
    cy = CH - 150 - (len(lines) - 1) * 56
    for i, line in enumerate(lines):
        d.text((76, cy + i * 56), line, font=cf, fill=GRY)
    d.text((CW - 240, CH - 92), "右滑 →", font=f(BOLD, 40), fill=(180, 172, 158))
    return im


def wrap_lines(d, text, font, maxw):
    out, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=font) <= maxw:
            cur += ch
        else:
            out.append(cur)
            cur = ch
    if cur:
        out.append(cur)
    return out


def xhs_install():
    """第 6 张：三步安装，带链接胶囊。"""
    im = Image.new("RGB", (CW, CH), CRM)
    d = ImageDraw.Draw(im)
    pill(d, (76, 74), "06 / 06 · 装上", f(BOLD, 36), INK, CRM)

    d.text((72, 196), "解压扔进目录", font=f(BOLD, 118), fill=INK)
    d.text((72, 344), "重启 GIMP 就有", font=f(BOLD, 118), fill=INK)

    steps = [("1", "下载 zip", "仓库 docs/download/ 里"),
             ("2", "解压到插件目录", "gegl-0.4/plug-ins"),
             ("3", "重启 GIMP", "菜单栏多一栏 SuperMrWang")]
    y = 620
    for num, t1, t2 in steps:
        d.ellipse([76, y, 76 + 92, y + 92], fill=INK)
        d.text((76 + 34, y + 16), num, font=f(BOLD, 48), fill=CRM)
        d.text((200, y + 2), t1, font=f(BOLD, 58), fill=INK)
        d.text((200, y + 76), t2, font=f(REG, 34), fill=GRY)  # MONO 无中文会出豆腐
        y += 168

    bar = [76, CH - 300, CW - 76, CH - 150]
    d.rounded_rectangle(bar, 26, fill=INK)
    d.text((108, CH - 268), "github.com/SuperMrWang-DEV", font=f(MONO, 40), fill=YEL)
    d.text((108, CH - 210), "gegl-color-ops", font=f(MONO, 40), fill=YEL)
    d.text((CW - 300, CH - 92), "右滑 →", font=f(BOLD, 40), fill=(180, 172, 158))
    return im


# ---------------------------------------------------------------- YouTube 16:9

def youtube():
    W, H = 1280, 720
    im = Image.new("RGB", (W, H), DRK)
    d = ImageDraw.Draw(im)

    # 左侧黄色斜块
    d.polygon([(0, 0), (740, 0), (640, H), (0, H)], fill=YEL)

    d.text((54, 60), "GIMP 3", font=f(BOLD, 132), fill=BLK)
    d.text((54, 210), "54 FREE", font=f(BOLD, 92), fill=BLK)
    d.text((54, 312), "FILTERS", font=f(BOLD, 92), fill=BLK)
    d.text((58, 448), "open source · GPL-3.0", font=f(BOLD, 40), fill=(70, 58, 20))
    pill(d, (58, 528), "GEGL  color  ops", f(BOLD, 38), BLK, YEL)

    shot = crop_fill(os.path.join(SHOTS, "op-levels.png"), (560, 392), 0.14)
    shadow_paste(im, shot, (700, 168), radius=12, spread=22, alpha=150,
                 border=WHT, bw=8)
    d = ImageDraw.Draw(im)
    arrow(d, [(648, 470), (690, 420), (712, 372)], RED, width=12, head=30)

    d.text((706, 590), "before", font=f(BOLD, 34), fill=(150, 158, 180))
    d.text((1010, 590), "after", font=f(BOLD, 34), fill=YEL)
    return im


# ---------------------------------------------------------------- 公众号头图

def gzh():
    W, H = 2350, 1000
    im = Image.new("RGB", (W, H), YEL)
    d = ImageDraw.Draw(im)
    d.polygon([(1620, 0), (W, 0), (W, H), (1470, H)], fill=DRK)

    pill(d, (86, 84), "GIMP 3 · 开源免费", f(BOLD, 44), RED, WHT)
    d.text((82, 200), "缺的 54 个调色工具", font=f(BOLD, 132), fill=BLK)
    d.text((82, 360), "我给它补上了", font=f(BOLD, 132), fill=BLK)
    d.line([(88, 546), (760, 538)], fill=RED, width=12)
    d.text((86, 600), "色阶 / 曲线 / 蒙版 / 抠图 / 变形 / 透视", font=f(REG, 54),
           fill=(60, 54, 30))
    d.text((86, 700), "31 个插件 + 预编译包，解压即用", font=f(REG, 54),
           fill=(60, 54, 30))

    shot = crop_fill(os.path.join(SHOTS, "op-levels.png"), (720, 504), 0.14)
    shadow_paste(im, shot, (1548, 236), radius=12, spread=26, alpha=150,
                 border=WHT, bw=9)
    return im


# ---------------------------------------------------------------- 入口

def main(mode=None):
    if mode is None:
        mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    tag = "" if mode == "all" else "-黄黑"
    print("mode", mode)

    # B 站
    b = bili()
    dst = os.path.join(MEDIA, "01-bilibili")
    b.save(os.path.join(dst, "封面-高清.png"))
    b.resize((1146, 717), Image.LANCZOS).save(
        os.path.join(dst, "封面-1146x717.jpg"), quality=93, subsampling=0)
    print("  bili", b.size)

    # 小红书 6 张
    dst = os.path.join(MEDIA, "04-小红书")
    pages = [
        xhs_cover(),
        xhs_page(2, "色阶", ["同一个色阶", "七个色彩空间"], "七个色彩空间",
                 "七个空间各有各的量程，不能共用一个下拉框",
                 os.path.join(PROJ, "outputs", "curves-all.png"), 0.10),
        xhs_page(3, "变形", ["拖坏了", "能拖回来"], "能拖回来",
                 "打钉子不是推像素，参数随时改回去",
                 os.path.join(SHOTS, "op-puppet-warp.png"), 0.18),
        xhs_page(4, "透视", ["标一个四边形", "就能透视贴图"], "就能透视贴图",
                 "网格、贴图、沿台阶折上去，共用一台相机",
                 os.path.join(SHOTS, "plug-vanishing.png"), 0.16),
        xhs_page(5, "抠图", ["AI 抠图 +", "选择并遮住"], "选择并遮住",
                 "收缩、羽化、去色边、吸附，所见即所得",
                 os.path.join(SHOTS, "plug-refine.png"), 0.20),
        xhs_install(),
    ]
    for i, im in enumerate(pages, 1):
        im.save(os.path.join(dst, "%02d.jpg" % i), quality=93, subsampling=0)
    print("  xhs", len(pages), "张")

    # YouTube
    y = youtube()
    y.save(os.path.join(MEDIA, "05-youtube", "缩略图-1280x720.jpg"),
           quality=94, subsampling=0)
    print("  yt", y.size)

    # 公众号头图
    g = gzh()
    g.save(os.path.join(MEDIA, "03-公众号", "头图-2350x1000.png"))
    print("  gzh", g.size)

    # 预览小图
    pv = os.path.join(MEDIA, "_preview")
    os.makedirs(pv, exist_ok=True)
    b.resize((1146, 717), Image.LANCZOS).save(os.path.join(pv, "b站.jpg"), quality=92)
    y.resize((800, 450), Image.LANCZOS).save(os.path.join(pv, "youtube.jpg"), quality=92)
    g.resize((900, 383), Image.LANCZOS).save(os.path.join(pv, "公众号.jpg"), quality=92)
    for i, im in enumerate(pages, 1):
        im.resize((414, 552), Image.LANCZOS).save(
            os.path.join(pv, "小红书%d.jpg" % i), quality=90)
    print("OK", dst)


if __name__ == "__main__":
    main()
