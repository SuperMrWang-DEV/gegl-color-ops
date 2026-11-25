"""整理各平台发布素材到 outputs/media/。

一次生成：
  00-视频/            成片、16:9 封面、旁白稿
  01-bilibili/        16:10 封面 + 发布文案（标题/分区/标签/简介/章节）
  02-zhihu/           长文 + 配图
  03-公众号/          长文（标题改写）+ 配图
  04-小红书/          6 张 3:4 竖版卡 + 文案
  05-youtube/         中英标题/描述/标签
  06-微博/            短文案
  README.md           总索引

    python tools/video/build_media.py
"""
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJ = os.path.dirname(ROOT)
OUT_SRC = os.path.join(PROJ, "outputs")
VID = os.path.join(OUT_SRC, "video")
SHOTS = os.path.join(ROOT, "tools", "video", "shots")
MEDIA = os.path.join(OUT_SRC, "media")

BG = (8, 11, 17)
INK = (240, 244, 252)
INK2 = (156, 168, 190)
INK3 = (124, 136, 160)
ACCENT = (111, 116, 255)
ACCENT2 = (176, 180, 255)
CYAN = (34, 211, 238)

BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
REG = r"C:\Windows\Fonts\msyh.ttc"
MONO = r"C:\Windows\Fonts\consola.ttf"

REPO = "github.com/SuperMrWang-DEV/gegl-color-ops"
SITE = "superMrwang-dev.github.io/gegl-color-ops"


def f(p, s):
    return ImageFont.truetype(p, s)


def bg(w, h, warm=False):
    im = Image.new("RGB", (w, h), BG)
    spots = [([w * .30, -h * .62, w * 1.28, h * .86], (54, 62, 156), 240, 80),
             ([-w * .40, h * .46, w * .50, h * 1.45], (14, 88, 122), 240, 36)]
    if warm:
        spots.append(([w * .42, h * .58, w * 1.35, h * 1.5], (92, 54, 150), 240, 46))
    for box, col, blur, alpha in spots:
        g = Image.new("L", (w, h), 0)
        ImageDraw.Draw(g).ellipse(box, fill=alpha)
        g = g.filter(ImageFilter.GaussianBlur(blur))
        im.paste(Image.new("RGB", (w, h), col), (0, 0), g)
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    step = 96 if w > 1600 else 72
    for x in range(0, w, step):
        gd.line([(x, 0), (x, h)], fill=(255, 255, 255, 7))
    for y in range(0, h, step):
        gd.line([(0, y), (w, y)], fill=(255, 255, 255, 7))
    return Image.alpha_composite(im.convert("RGBA"), grid).convert("RGB")


def crop_fill(path, size, y_bias=0.22, x_bias=0.5):
    """按目标比例裁图，纵向取 y_bias 处，保留网页标题区。"""
    im = Image.open(path).convert("RGB")
    tw, th = size
    sw, sh = im.size
    want = tw / th
    if sw / sh > want:                    # 太宽，裁两边
        nw = int(sh * want)
        x0 = int((sw - nw) * x_bias)
        im = im.crop((x0, 0, x0 + nw, sh))
    else:                                 # 太高，裁上下
        nh = int(sw / want)
        y0 = max(0, int((sh - nh) * y_bias))
        y0 = min(y0, sh - nh)
        im = im.crop((0, y0, sw, y0 + nh))
    return im.resize(size, Image.LANCZOS)


def paste_round(im, shot, xy, radius=26, shadow=True, ring=True):
    w, h = shot.size
    x, y = xy
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius, fill=255)
    if shadow:
        sh = Image.new("L", (im.width, im.height), 0)
        ImageDraw.Draw(sh).rounded_rectangle(
            [x, y + 22, x + w, y + h + 22], radius, fill=110)
        sh = sh.filter(ImageFilter.GaussianBlur(40))
        im.paste(Image.new("RGB", im.size, (0, 0, 0)), (0, 0), sh)
    im.paste(shot, (x, y), mask)
    if ring:
        r = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(r).rounded_rectangle(
            [0, 0, w - 1, h - 1], radius, outline=(126, 136, 172, 150), width=3)
        im.paste(r, (x, y), r)


# ---------------------------------------------------------------- 小红书卡片

CW, CH = 1242, 1656


def wrap(d, text, font, maxw):
    """按字符断行，尽量在空格处断开（英文术语不会从中间劈开）。"""
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=font) <= maxw:
            cur += ch
        elif ch == " ":
            lines.append(cur)
            cur = ""
        else:
            cut = cur.rfind(" ")
            if cut > len(cur) * 0.5:
                lines.append(cur[:cut])
                cur = cur[cut + 1:] + ch
            else:
                lines.append(cur)
                cur = ch
    if cur:
        lines.append(cur)
    return lines


def xhs_card(idx, total, kicker, title_lines, shot=None, cap="", big=None,
             xb=0.5):
    im = bg(CW, CH, warm=(idx % 2 == 1))
    d = ImageDraw.Draw(im)
    x = 76

    # 顶部：序号 + 标签
    d.rounded_rectangle([x, 84, x + 12, 84 + 34], 5, fill=ACCENT)
    d.text((x + 28, 84), kicker, font=f(BOLD, 38), fill=ACCENT2)

    if big:                               # 封面：只排大字
        y = 232
        for line, size, col in big:
            d.text((x - 4, y), line, font=f(BOLD, size), fill=col)
            y += int(size * 1.28)
        if shot:
            im2 = crop_fill(shot, (CW - 2 * x, 470), 0.16)
            paste_round(im, im2, (x, CH - 470 - 196), radius=20)
        d.text((x, CH - 128), "开源 · GPL-3.0 · 免费", font=f(REG, 36), fill=INK3)
    else:
        y = 190
        for line in title_lines:
            d.text((x - 4, y), line, font=f(BOLD, 92), fill=INK)
            y += 118
        if shot:
            im2 = crop_fill(shot, (CW - 2 * x, 806), 0.20, xb)
            paste_round(im, im2, (x, y + 30))
        if cap:
            cf = f(REG, 40)
            lines = wrap(d, cap, cf, CW - 2 * x)
            cy = CH - 232 - (len(lines) - 1) * 56
            for i, line in enumerate(lines):
                d.text((x, cy + i * 56), line, font=cf, fill=INK2)
        d.text((x, CH - 136), REPO.split("/")[-1], font=f(MONO, 32), fill=(96, 106, 132))

    # 页码
    d.text((CW - 76 - 70, CH - 132), "%02d/%02d" % (idx, total),
           font=f(MONO, 34), fill=(110, 120, 146))
    return im


def build_xhs(dst):
    os.makedirs(dst, exist_ok=True)
    total = 6
    cards = [
        xhs_card(1, total, "免费开源 · GPL-3.0", [], cap="",
                 shot=os.path.join(SHOTS, "op-lab-curves.png"),
                 big=[("GIMP 3", 200, ACCENT2),
                      ("免费修图", 100, INK),
                      ("缺的那套调色工具", 96, INK),
                      ("我补了 54 个", 116, INK)]),
        xhs_card(2, total, "01 · 色阶", ["同一个色阶", "七个色彩空间"],
                 os.path.join(SHOTS, "op-levels.png"),
                 "RGB / HSB / HSL / HSI / Lab / LCh / CMYK 各有各的量程"),
        xhs_card(3, total, "02 · 变形", ["拖坏了", "能拖回来"],
                 os.path.join(SHOTS, "op-puppet-warp.png"),
                 "打钉子，不是推像素；参数随时改回去"),
        xhs_card(4, total, "03 · 透视", ["标一个四边形", "透视贴图"],
                 os.path.join(SHOTS, "plug-vanishing.png"),
                 "网格、贴图、沿台阶折上去，共用一套相机"),
        xhs_card(5, total, "04 · 抠图", ["AI 抠图 +", "选择并遮住"],
                 os.path.join(SHOTS, "plug-refine.png"),
                 "收缩、羽化、去色边、吸附，预览即所得"),
        xhs_card(6, total, "05 · 装上", ["解压扔进目录", "重启就有"],
                 os.path.join(SHOTS, "home.png"),
                 "Windows / Linux 都有现成包，全部 GPL-3.0", xb=0.0),
    ]
    for i, im in enumerate(cards, 1):
        p = os.path.join(dst, "%02d.jpg" % i)
        im.save(p, quality=92, subsampling=0)
        print("  xhs", os.path.basename(p), im.size, os.path.getsize(p) // 1024, "KB")


# ---------------------------------------------------------------- 文章配图


def build_article_shots(dst):
    os.makedirs(dst, exist_ok=True)
    picks = [
        ("01-七个色阶", "op-levels.png"),
        ("02-拆分合并", "op-dual.png"),
        ("03-木偶变形", "op-puppet-warp.png"),
        ("04-自由变形", "op-mesh-warp.png"),
        ("05-消失点", "plug-vanishing.png"),
        ("06-选择并遮住", "plug-refine.png"),
        ("07-分通道曲线", "plug-split.png"),
        ("08-首页", "home.png", 0.0),
    ]
    for item in picks:
        name, src = item[0], item[1]
        xb = item[2] if len(item) > 2 else 0.5
        p = os.path.join(SHOTS, src)
        im = crop_fill(p, (1600, 1000), 0.18, xb)
        out = os.path.join(dst, name + ".jpg")
        im.save(out, quality=90, subsampling=0)
        print("  shot", os.path.basename(out), os.path.getsize(out) // 1024, "KB")


# ---------------------------------------------------------------- 文案

BILI_TITLE = "GIMP 3 缺的那套调色工具，我用 GEGL 补了 54 个 + 31 个插件"

BILI_DESC = """GIMP 3 的滤镜内核叫 GEGL，一个滤镜就是一个算子。这套 gegl-color-ops 给它补了 54 个色彩算子：
色阶、曲线、色彩平衡、通道混合、蒙版、抠图、木偶变形、自由变形……

同一个色阶工具能按 RGB / Lab / LCh / CMYK 各来一套参数，不用转模式、不用分解重组 —— 这是 GIMP 自带版本做不到的。
另外配了 31 个 Python 插件（分通道曲线、抠图、选择并遮住、磨皮、图层样式……），把算子串成能直接上手的流程。
全部 GPL-3.0，Windows / Linux 有预编译包，解压扔进插件目录就能用。

仓库（源码 / 文档 / 预编译包）：https://github.com/SuperMrWang-DEV/gegl-color-ops
在线文档（54 篇算子说明，中英双语）：https://superMrwang-dev.github.io/gegl-color-ops/

章节：
{t}"""

BILI_CHAPTERS = """0:00 片头
0:09 01 · 这是什么
0:52 02 · 仓库
1:24 03 · 站点
2:16 04 · 五十四算子
5:12 05 · 插件
7:15 06 · 工程
7:57 07 · 装上
8:06 片尾"""

BILI_TAGS = "GIMP GEGL 调色 开源软件 修图 插件 Photoshop 色彩管理 免费软件"

ZHIHU_TOPICS = "GIMP、开源软件、图像处理、修图、设计工具"

GZH_TITLE = "GIMP 缺的那套调色工具，我给它补了 54 个（附下载）"

GZH_SUMMARY = ("GIMP 没有 Lab 模式，改个亮度得分解重组，一来一回多出三张图层。"
               "我给它写了 54 个色彩算子和 31 个插件：不转模式就能单独动 Lab 的 L、LCh 的彩度；"
               "变形能拖回来，透视贴图标一个四边形就行。Windows / Linux 有现成包，全部 GPL-3.0。")

XHS_TEXT = """用 GIMP 修图最烦的一件事：想只提亮肤色、不动衣服，得先「分解」成三个灰度层，改完再「重组」合回去。GIMP 没有 Lab 模式，只能这么绕。

所以我自己写了 54 个色彩算子 + 31 个插件，全部开源免费。

现在可以这样用：
· 不转模式，直接挂一个 Lab 色阶，只动亮度
· 再挂一个 LCh 的，只动彩度；要印前看效果，挂 CMYK 的
· 拆分 / 合并一键搞定，不用手动分解再重组
· 木偶变形打钉子拖，拖坏了拖回来；自由变形整幅扳正
· 标一个四边形就能透视贴图、画网格、沿台阶折上去
· 抠图走 AI，抠完接「选择并遮住」，预览什么样出来什么样

Windows / Linux 都有现成包，解压扔进插件目录，重启 GIMP 菜单栏顶层就多一栏。

源码 / 下载 / 文档都在主页，主页链接放在评论区第一条（正文放外链会限流）。

#GIMP #开源软件 #修图 #调色 #免费软件 #PS替代"""

WB_TEXT = """给 GIMP 3 写了 54 个色彩算子 + 31 个插件，开源免费。

起因只是想单独提亮肤色又不动衣服，结果 GIMP 没有 Lab 模式，只能分解重组。
现在不转模式就能挂 Lab 色阶、LCh 曲线；变形能拖回来；标一个四边形就能透视贴图。

Windows / Linux 都有解压即用的包。视频 8 分钟，讲完了每个算子干什么。
仓库：https://github.com/SuperMrWang-DEV/gegl-color-ops

#GIMP# #开源软件# #修图#"""

YT_TITLE = "I wrote 54 color filters for GIMP 3 because it was missing them"

YT_DESC = """GIMP 3's filter engine is GEGL — every filter is an "operation", a loadable module.
This project adds 54 color operations to it, plus 31 Python plug-ins that chain them into workflows.

What's in it:
- Levels / Curves in 7 color spaces (RGB, HSB, HSL, HSI, Lab, LCh, CMYK) — no need to convert the image mode or decompose into grayscale layers first
- Split / Compose for 6 color spaces, plus per-component curves
- Exposure, shadows/highlights, hue-saturation, color balance, channel mixer, apply image, color lookup
- Masks: select by color range, channel to alpha, dilate/erode
- Warps: puppet warp (pin-based, reversible), free-form mesh deform, displacement
- Vanishing point: mark one quad, then texture-map with correct perspective
- Cutout (AI via ComfyUI RMBG, or local flood fill) + "refine mask" (contract, feather, decontaminate edges, snap to edges)
- Frequency-separation / dodge & burn retouching, layer styles (drop shadow, glow, stroke — 80+ params)

Everything is GPL-3.0. Prebuilt packages for Windows and Linux — unzip into the GEGL plug-in folder and restart GIMP.

Repo: https://github.com/SuperMrWang-DEV/gegl-color-ops
Docs (bilingual, 54 ops + 31 plug-ins): https://superMrwang-dev.github.io/gegl-color-ops/

Chapters:
0:00 Intro
0:09 01 · What this is
0:52 02 · The repo
1:24 03 · The docs site
2:16 04 · The 54 operations
5:12 05 · The plug-ins
7:15 06 · Engineering
7:57 07 · Install
8:06 Outro

Note: all operations are implemented independently from public formulas and observable behavior; no code or assets from commercial software are included. Photoshop is mentioned only to indicate which effect an operation corresponds to.

#GIMP #GEGL #OpenSource #PhotoEditing #ColorGrading"""

YT_TAGS = "GIMP, GEGL, GIMP 3, open source, photo editing, color grading, levels, curves, Lab, LCh, CMYK, puppet warp, free Photoshop alternative"

README = """# 发布素材总目录

整包按平台分好了，每个文件夹里都有一份 `发布文案.txt`，内容可以直接复制。
下面按建议的发布顺序排。

| 目录 | 内容 | 干什么用 |
|---|---|---|
| `00-视频/` | 成片（4K / 8:16 / 155MB）、16:9 封面、旁白稿 | 所有视频平台共用这一份 mp4 |
| `01-bilibili/` | 黄黑大字封面（1146×717 可直接上传）、发布文案 | B 站主发 |
| `02-zhihu/` | 长文 markdown、8 张配图 | 知乎文章 |
| `03-公众号/` | 长文（标题按公众号风格改过）、摘要、8 张配图、2350×1000 头图 | 公众号 |
| `04-小红书/` | 6 张奶油底竖版卡（1242×1656，马克笔高亮 + 红笔圈注）、短文案 | 图文笔记 |
| `05-youtube/` | 1280×720 缩略图、中英标题 / 描述 / 标签 | 海外同步 |
| `06-微博/` | 短文案 | 带视频或配图转发 |

## 建议顺序

1. **B 站先发**，视频审核要一会儿，先占住发布时间。
2. B 站过审拿到链接后，**知乎发文章**，开头补一句视频链接。
3. **公众号**同一篇，标题改了，摘要已写好。
4. **小红书**用 6 张卡，首图是关键，别裁别加字。
5. **微博 / YouTube** 收尾，微博带上 B 站链接。

## 几个容易踩的点

- B 站封面必须用 `01-bilibili/封面-1146x717.jpg`（16:10）。用 16:9 的会被裁掉上下。
  `封面-高清.png` 是 2 倍图，留着以后改字用。
- B 站简介里的链接不是超链接，观众得手点复制；所以章节表放在最下面，别被折叠。
- 知乎直接粘 markdown 会丢格式，先粘纯文本再手动分段；配图按 `02-zhihu/配图/01…08` 的顺序插。
- 公众号正文里的外链点了不能跳，仓库地址建议放在「阅读原文」里。
- 小红书简介放外链会限流，文案里已经改成「主页链接在评论区」。
- 视频 155MB，B 站上传没问题；YouTube 建议直接传这个 4K 版，别压。
- 所有封面 / 卡片都由 `tools/video/cover_pop.py` 生成，改字改那里再跑 build_media，
  别手改 jpg——下次重建会被覆盖。

## 一句话卖点（各平台都写了，需要临时改口时用）

> GIMP 3 少了 Photoshop 那一整套调色工具：没有 Lab 模式，改亮度要分解重组，变形撤不回来，贴图对不上透视。
> 这套东西补了 54 个色彩算子 + 31 个插件，不转模式、参数可回退、全部开源免费。
"""


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("  txt ", os.path.relpath(path, MEDIA), os.path.getsize(path), "B")


def main():
    if os.path.isdir(MEDIA):
        shutil.rmtree(MEDIA)
    os.makedirs(MEDIA)
    print("->", MEDIA)

    # 00 视频
    d = os.path.join(MEDIA, "00-视频")
    os.makedirs(d, exist_ok=True)
    for src, dst in (("gegl-color-ops-4k.mp4", "gegl-color-ops-4k.mp4"),
                     ("cover.png", "封面-16x9-4K.png"),
                     ("narration.txt", "旁白稿.txt")):
        s = os.path.join(VID, src)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(d, dst))
            print("  copy", dst, os.path.getsize(os.path.join(d, dst)) // 1024 // 1024, "MB")

    # 01 B 站（封面由 cover_pop.py 生成，这里只建目录）
    d = os.path.join(MEDIA, "01-bilibili")
    os.makedirs(d, exist_ok=True)
    w(os.path.join(d, "发布文案.txt"),
      "【标题】（上限 80 字）\n%s\n\n"
      "【封面】封面-1146x717.jpg（16:10，黄黑大字版，直接上传不要裁）\n\n"
      "【分区】科技 → 软件应用\n"
      "【时长】8:16   【分辨率】3840×2160\n\n"
      "【标签】（复制进去，空格分隔）\n%s\n\n"
      "【简介】\n%s\n\n"
      "【置顶评论】\n"
      "项目全部开源在 GPL-3.0，源码、文档、Windows / Linux 预编译包都在仓库里：\n"
      "https://github.com/SuperMrWang-DEV/gegl-color-ops\n"
      "有问题或者想补算子，issue 里说。\n"
      % (BILI_TITLE, BILI_TAGS, BILI_DESC.replace("{t}", BILI_CHAPTERS)))

    # 知乎 / 公众号
    art = open(os.path.join(OUT_SRC, "zhihu-gegl-color-ops.md"), encoding="utf-8").read()
    d = os.path.join(MEDIA, "02-zhihu")
    os.makedirs(d, exist_ok=True)
    w(os.path.join(d, "文章.md"), art)
    build_article_shots(os.path.join(d, "配图"))
    w(os.path.join(d, "发布文案.txt"),
      "【标题】（知乎标题上限 50 字，这个 28 字）\n"
      "我给 GIMP 3 补了 54 个滤镜，因为它少了一整套修图工具\n\n"
      "【话题】（发的时候挂这几个，最多 5 个）\n%s\n\n"
      "【正文】见 文章.md\n\n"
      "【配图顺序】按 配图/01…08 编号插在对应小节里，缩略图不用管\n\n"
      "【视频】B 站发布后，把链接补在文章开头第一段末尾：\n"
      "视频版（8 分钟，逐个算子演示）：https://www.bilibili.com/video/BV______\n"
      % ZHIHU_TOPICS)

    d = os.path.join(MEDIA, "03-公众号")
    os.makedirs(d, exist_ok=True)
    body = art.split("\n", 1)[1] if art.startswith("#") else art
    w(os.path.join(d, "文章.md"), "# " + GZH_TITLE + "\n" + body)
    build_article_shots(os.path.join(d, "配图"))
    w(os.path.join(d, "发布文案.txt"),
      "【标题】\n%s\n\n"
      "【摘要】（不超过 120 字，这个 96 字）\n%s\n\n"
      "【作者】可留空\n"
      "【原创】是\n"
      "【正文】见 文章.md\n\n"
      "【注意】文中的仓库链接在公众号里点不动，放到「阅读原文」；\n"
      "正文链接处改成「见文末阅读原文」即可。\n\n"
      "【封面】头图-2350x1000.png（已是 2.35:1，黄黑大字版，直接上传）\n"
      % (GZH_TITLE, GZH_SUMMARY))

    # 小红书
    d = os.path.join(MEDIA, "04-小红书")
    build_xhs(d)
    w(os.path.join(d, "发布文案.txt"),
      "【标题】（上限 20 字）\nGIMP 免费修图，我补了 54 个滤镜\n\n"
      "【正文】\n%s\n\n"
      "【图】3:4 竖版，上传后不要裁，顺序别乱：\n"
      "  01 封面 · 我补了 54 个\n  02 同一个色阶 · 七个色彩空间\n  03 拖坏了能拖回来\n"
      "  04 标一个四边形 · 透视贴图\n  05 AI 抠图 + 选择并遮住\n  06 解压扔进目录 · 重启就有\n"
      % XHS_TEXT)

    # YouTube
    d = os.path.join(MEDIA, "05-youtube")
    os.makedirs(d, exist_ok=True)
    w(os.path.join(d, "发布文案.txt"),
      "【Title】\n%s\n\n【Description】\n%s\n\n【Tags】（逗号分隔）\n%s\n\n"
      "【Thumbnail】缩略图-1280x720.jpg（黄黑撞色 + 红箭头，已是 16:9）\n"
      "【Category】Science & Technology\n【Language】Chinese (video), English (title/desc)\n"
      % (YT_TITLE, YT_DESC, YT_TAGS))

    # 微博
    d = os.path.join(MEDIA, "06-微博")
    os.makedirs(d, exist_ok=True)
    w(os.path.join(d, "发布文案.txt"),
      "【正文】\n%s\n\n【配图】01-bilibili/封面-1146x717.jpg 或直接带 B 站视频卡片\n" % WB_TEXT)

    w(os.path.join(MEDIA, "README.md"), README)

    # 封面 / 图例统一由 cover_pop.py 出：B 站黄黑、小红书奶油、YouTube 深色
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cover_pop
    cover_pop.main("all")

    total = sum(os.path.getsize(os.path.join(r, x))
                for r, _, fs in os.walk(MEDIA) for x in fs)
    print("\nDONE", MEDIA, "%.1f MB" % (total / 1024 / 1024))


if __name__ == "__main__":
    main()
