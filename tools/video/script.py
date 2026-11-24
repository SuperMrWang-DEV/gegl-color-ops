"""4K 介绍片的分镜与旁白。

一条镜头 = 一句旁白 + 一张 3840x2160 的画面。镜长由配音实际时长决定
（build.py 量完 mp3 再定），这里只写内容。
"""

# 章节标 / 标题 / 副标题 / 画面类型 / 素材 / 旁白
# kind: hero | shot | grid | usage | tree | outro
SCENES = [
    dict(key="00-hero", chapter="", kind="hero",
         title="54 个算子，一条调色链",
         sub="gegl-color-ops · GIMP 3 · GEGL 0.4 · GPL-3.0",
         narr="给 GIMP 3 写的一整套色彩算子。五十四个 GEGL 算子，"
              "三十一个 Python 插件，两个包，一条完整的调色链。"),

    dict(key="01-home", chapter="01 · 这是什么", kind="shot", img="home",
         title="给 GIMP 3 的一套色彩算子",
         sub="GEGL 是 GIMP 3 的滤镜内核，每个滤镜就是一个算子",
         narr="先说这是什么。GIMP 3 的滤镜内核叫 GEGL，每个滤镜就是一个算子。"
              "这个仓库写了五十四个，全部带 lb 前缀，在菜单栏顶层单独占一个 SuperMrWang。"),

    dict(key="02-install", chapter="01 · 这是什么", kind="shot", img="overview",
         title="零依赖，免编译",
         sub="模块丢进 GEGL 用户插件目录，重启即可",
         narr="装起来没有安装程序。把编译好的模块丢进 GEGL 的用户插件目录，"
              "重启 GIMP，菜单里就有了。零依赖，免编译。"),

    dict(key="03-usage", chapter="01 · 这是什么", kind="usage",
         title="同一套代码，三种用法",
         sub="GIMP 菜单 · gegl 命令行 · ComfyUI 节点",
         narr="同一套代码，三种用法：GIMP 里点菜单，命令行用 gegl 直接调，"
              "或者接进 ComfyUI 当节点跑批。"),

    dict(key="04-tree", chapter="02 · 仓库", kind="tree",
         title="一个算子，一个 C 文件",
         sub="唯一源码工程：算子、插件、站点、回归脚本都在里面",
         narr="仓库是唯一的源码工程。一个算子一个目录，一个 C 文件，一次编译全部出来。"
              "插件、站点、回归脚本都在同一个仓库里。"),

    dict(key="05-site", chapter="03 · 站点", kind="shot", img="ops",
         title="五十四篇文档，从源码生成",
         sub="菜单路径 · 色彩空间 · 参数表 · 实测误差 · 中英双语",
         narr="网站是从源码生成的。每个算子一篇文档：菜单路径、色彩空间、参数表、实测误差，"
              "中英文各一版，五十四篇一篇不少。"),

    dict(key="06-compare", chapter="03 · 站点", kind="shot", img="op-lab-curves",
         title="每篇开头都是一张前后对比",
         sub="同一张测试卡：上半照片，下半色卡、灰阶、四像素栅格",
         narr="每篇开头都是这样一张前后对比。同一张测试卡，左边原图，右边结果。"
              "上半是照片，下半是色卡、灰阶和四像素栅格，色偏和细节一眼能看出来。"),

    dict(key="07-detail", chapter="03 · 站点", kind="shot", img="op-layer-style",
         title="算法、参数、坑，都写在页面里",
         sub="插值方式 · LUT 大小 · 与 Photoshop 的实测差异",
         narr="再往下是算法说明：插值怎么做、LUT 多大、哪些地方和 Photoshop 有出入。"),

    dict(key="08-plugins", chapter="03 · 站点", kind="shot", img="plugins",
         title="另一半：31 个 Python 插件",
         sub="把算子串成流程，而不只是单个滤镜",
         narr="插件是另一半。三十一个 Python 插件，把算子串成流程："
              "拆通道、叠曲线、分层磨皮、蒙版互转。"),

    dict(key="09-levels", chapter="04 · 五十四算子", kind="grid", group="Levels",
         title="色阶：七个色彩空间，各一套",
         sub="同一个色阶工具，量程与分量按色彩空间走",
         narr="五十四个算子按你找滤镜时的念头分成十组。第一组是色阶：同一个色阶工具，"
              "在 RGB、Lab、HSL、HSB、LCH、CMYK、HSI 七个色彩空间各有一套。"),

    dict(key="10-component", chapter="04 · 五十四算子", kind="grid", group="Component",
         title="分量：拆开调，再合回去",
         sub="dual 是拆分，compose 是合并，gray-to-component 是灰度铺进某个分量",
         narr="第二组是分量：把图拆成各自的通道，调完再合回去。dual 是拆分，compose 是合并。"),

    dict(key="11-tone", chapter="04 · 五十四算子", kind="grid", group="Tone",
         title="明暗：曝光、对比、阴影高光",
         sub="还有一条只改明度、不动颜色的灰度路径",
         narr="第三组是明暗：曝光、亮度对比度、阴影高光，还有一条只改明度、不动颜色的灰度路径。"),

    dict(key="12-color", chapter="04 · 五十四算子", kind="grid", group="Color",
         title="颜色：饱和度、平衡、白平衡",
         sub="色相带选择、自然饱和度、色温色调",
         narr="第四组是颜色：色相饱和度、色彩平衡、白平衡、自然饱和度，"
              "还有按色相带做选择的 hsl-bands。"),

    dict(key="13-blend", chapter="04 · 五十四算子", kind="grid", group="Blend",
         title="混合：Photoshop 的那套公式",
         sub="应用图像、计算、通道混合、正片叠底",
         narr="第五组是混合：应用图像、计算、通道混合、正片叠底。"
              "Photoshop 里那套混合公式，这里都有对应的算子。"),

    dict(key="14-mask", chapter="04 · 五十四算子", kind="grid", group="Mask",
         title="蒙版：按颜色选，按通道转",
         sub="颜色范围、通道转 alpha、最大最小值做膨胀腐蚀",
         narr="第六组是蒙版：按颜色范围选、把通道转成 alpha、用最大最小值做膨胀和腐蚀。"),

    dict(key="15-sharpen", chapter="04 · 五十四算子", kind="grid",
         group=["Sharpen", "Noise"],
         title="锐化与杂色",
         sub="USM 锐化 · 加噪 · 降噪 · 去灰尘划痕",
         narr="第七、第八组是锐化和杂色：USM 锐化、加噪、降噪、去灰尘划痕。"),

    dict(key="16-distort", chapter="04 · 五十四算子", kind="grid", group="Distort",
         title="扭曲：三个都是大件",
         sub="置换贴图 · 木偶变形 · 自由变形",
         narr="第九组是扭曲：置换贴图、木偶变形、自由变形。三个都是大件。"),

    dict(key="17-layer", chapter="04 · 五十四算子", kind="grid", group="Layer",
         title="图层样式：参数一一对应",
         sub="投影 · 内阴影 · 描边 · 内外发光",
         narr="最后是图层样式：投影、内阴影、描边、内外发光，参数和 Photoshop 一一对应。"),

    dict(key="18-curves", chapter="05 · 插件", kind="shot", img="plug-curves",
         title="曲线：四个色彩空间，实时预览",
         sub="每个分量一条任意曲线，改参数不落像素",
         narr="插件里最值得看的是曲线：四个色彩空间，每个分量一条任意曲线，"
              "右边实时预览，改参数不落像素。"),

    dict(key="19-refine", chapter="05 · 插件", kind="shot", img="plug-refine",
         title="抠图与选择并遮住",
         sub="AI 走 ComfyUI 的 RMBG，本地走四边泛洪",
         narr="抠图有两条路：AI 走 ComfyUI 的 RMBG 模型，本地走四边泛洪，毫秒级。"
              "抠完进「选择并遮住」精修边缘。"),

    dict(key="20-warp", chapter="05 · 插件", kind="shot", img="plug-mesh",
         title="木偶变形与自由变形",
         sub="MLS 与 FFD + 双三次面片，1600 万像素一秒左右",
         narr="木偶变形用 MLS，自由变形用 FFD 加双三次面片。"
              "都做了栅格解场和脏区扫描，四百万像素一秒上下。"),

    dict(key="21-vp", chapter="05 · 插件", kind="shot", img="plug-vanishing",
         title="消失点：标一个四边形，反解相机",
         sub="画网格 · 贴图 · 拉正 · 平面沿台阶折上去",
         narr="消失点更进一步：标一个四边形就能反解相机，画网格、贴图、拉正，"
              "还能把一块平面沿着台阶一路折上去。"),

    dict(key="22-ai", chapter="05 · 插件", kind="shot", img="plug-ai-inpaint",
         title="AI 系列：接 ComfyUI",
         sub="AI 扩图 · AI 放大 · AI 修补，结果回写成图层",
         narr="AI 那几支把 ComfyUI 接进来：AI 扩图、AI 放大、AI 修补，结果直接回写成图层。"),

    dict(key="23-download", chapter="06 · 装上", kind="shot", img="guide",
         title="下载，或者编一次",
         sub="Windows 预编译包 · Linux/macOS 走 meson 或 build.sh",
         narr="想用的话，Windows 直接下预编译包；Linux 和 macOS 用 meson 或 build.sh "
              "编一次，五十四个算子一起出来。"),

    dict(key="24-outro", chapter="", kind="outro",
         title="gegl-color-ops",
         sub="54 个算子 · 31 个插件 · 54 篇文档 · 1200+ 条回归断言",
         narr="仓库、站点、文档都在 GitHub 上，GPL-3.0。五十四篇文档，三十一个插件，"
              "一千多条回归断言。链接在下面。"),
]
