"""4K 介绍片的分镜与旁白（8 分钟版）。

一条镜头 = 一句旁白 + 一张 3840x2160 的画面。镜长由配音实际时长决定
（build.py 量完 mp3 再定），这里只写内容。

长度预算：48 镜 × 1.1s 固定开销 + 字数/4.35 ≈ 480s，所以每镜旁白控制在
40 字上下，单镜 hold 不超过 11s（画面滑动余量 400px，1px/帧）。
"""

A, C, G, O = (111, 116, 255), (34, 211, 238), (126, 231, 168), (255, 176, 108)

# kind: hero | shot | grid | usage | tree | stat | code | steps | duo | outro
SCENES = [
    dict(key="00-hero", chapter="", kind="hero",
         title="54 个算子，一条调色链",
         sub="gegl-color-ops · GIMP 3 · GEGL 0.4 · GPL-3.0",
         narr="给 GIMP 3 写的一整套色彩算子：五十四算子，三十一个插件，一条调色链。"),

    # ---------- 01 这是什么 ----------
    dict(key="01-what", chapter="01 · 这是什么", kind="shot", img="home",
         title="GIMP 3 的滤镜内核叫 GEGL",
         sub="每个滤镜就是一个算子，算子之间可以拼成图",
         narr="GEGL 是 GIMP 3 的滤镜内核，一个滤镜就是一个算子。这些算子带 lb 前缀，"
              "在菜单里单占一栏。"),

    dict(key="02-why", chapter="01 · 这是什么", kind="stat",
         title="为什么还要自己写一套",
         sub="GIMP 自带的曲线、色阶只给一套参数，分色彩空间的版本得一个个补",
         items=[("54", "个算子", A), ("31", "个插件", C), ("10", "个分组", G)],
         narr="为什么要自己写：自带的曲线和色阶只给一套参数，想要 Lab、LCh、CMYK "
              "各来一份，只能一个个补。"),

    dict(key="03-install", chapter="01 · 这是什么", kind="steps",
         title="装起来没有安装程序",
         sub="零依赖 · 免编译 · 不碰系统目录",
         items=[("1", "下载模块", "dist 里是编译好的 dll / so，按平台挑"),
                ("2", "放进用户目录", "GEGL 的 plug-ins 目录，不写系统路径"),
                ("3", "重启 GIMP", "菜单里直接多出 SuperMrWang 一栏")],
         narr="装起来没有安装程序：下载模块，放进 GEGL 的用户插件目录，重启 GIMP 就有了。"),

    dict(key="04-usage", chapter="01 · 这是什么", kind="usage",
         title="同一套代码，三种用法",
         sub="GIMP 菜单 · gegl 命令行 · ComfyUI 节点",
         narr="同一套代码三种用法：GIMP 里点菜单，命令行用 gegl 直接调，"
              "或者接进 ComfyUI 当节点。"),

    # ---------- 02 仓库 ----------
    dict(key="05-tree", chapter="02 · 仓库", kind="tree",
         title="一个算子，一个 C 文件",
         sub="算子、插件、站点、回归脚本都在同一个仓库里",
         narr="仓库是唯一源码工程：一个算子一个目录一个 C 文件，插件、站点、"
              "回归脚本都在里面。"),

    dict(key="06-build", chapter="02 · 仓库", kind="code",
         title="一条脚本编完全部",
         sub="build.sh 走 gcc，meson.build 给 Linux / macOS / CI",
         lines=[("$ ./build.sh", "cmd"),
                ("  gcc -O2 -shared ops/*/*.c -o dist/*.dll", "out"),
                ("  54 modules built", "dim"),
                ("$ ./install.sh --verify", "cmd"),
                ("  verify: 54/54 loaded", "key")],
         narr="编译只要一条 build.sh，gcc 编出五十四个模块；install.sh 装好之后逐个自检，"
              "确认全部加载成功。"),

    dict(key="07-test", chapter="02 · 仓库", kind="stat",
         title="每个算子都有回归断言",
         sub="改插值、改 LUT、改色彩空间换算，跑一遍就知道哪里偏了",
         items=[("1502", "条断言", A), ("54", "个算子全覆盖", C),
                ("3", "个平台 CI", G)],
         narr="每个算子都带回归断言，加起来一千五百多条。改插值改 LUT，跑一遍就知道"
              "哪边数值偏了。"),

    # ---------- 03 站点 ----------
    dict(key="08-ops", chapter="03 · 站点", kind="shot", img="ops",
         title="五十四篇文档，从源码生成",
         sub="菜单路径 · 色彩空间 · 参数表 · 实测误差 · 中英双语",
         narr="网站从源码生成，五十四篇文档一篇不少。每篇都写清菜单路径、色彩空间、"
              "参数表和实测误差。"),

    dict(key="09-compare", chapter="03 · 站点", kind="shot", img="op-lab-curves",
         title="每篇开头都是一张前后对比",
         sub="同一张测试卡：上半照片，下半色卡、灰阶、四像素栅格",
         narr="每篇开头是一张前后对比：同一张测试卡，左边原图右边结果，上半照片，"
              "下半色卡和灰阶。"),

    dict(key="10-detail", chapter="03 · 站点", kind="shot", img="op-layer-style",
         title="算法、参数、坑，都写在页面里",
         sub="插值方式 · LUT 大小 · 与 Photoshop 的实测差异",
         narr="再往下是算法说明：插值怎么做、LUT 多大、哪些地方和 Photoshop 有出入，"
              "都写清楚了。"),

    dict(key="11-i18n", chapter="03 · 站点", kind="duo",
         title="全部页面都是双语的",
         sub="术语按 GIMP 官方译法对齐，自己看和发给别人都合适",
         imgs=[("overview", "概览 / Overview"), ("guide", "指南 / Guide")],
         narr="每个页面都有中英两版，术语按 GIMP 官方译法对齐，自己看和发给别人看都合适。"),

    dict(key="12-plugins", chapter="03 · 站点", kind="shot", img="plugins",
         title="另一半：31 个 Python 插件",
         sub="把算子串成流程，而不只是单个滤镜",
         narr="插件是另一半：三十一个 Python 插件，把算子串成流程，拆通道、叠曲线、"
              "分层磨皮、蒙版互转。"),

    # ---------- 04 五十四算子 ----------
    dict(key="13-levels", chapter="04 · 五十四算子", kind="grid", group="Levels",
         title="色阶：七个色彩空间，各一套",
         sub="同一个色阶工具，量程与分量按色彩空间走",
         narr="五十四个算子分成十组。第一组是色阶：同一个色阶工具，七个色彩空间各有一套。"),

    dict(key="14-levels2", chapter="04 · 五十四算子", kind="shot", img="op-levels",
         title="同一种操作，不同的坐标轴",
         sub="RGB 三个通道 · Lab 亮度加两个对立轴 · CMYK 印刷四色",
         narr="同一个色阶，量程和分量跟着色彩空间走：RGB 走三个通道，Lab 走亮度加两个对立轴。"),

    dict(key="15-component", chapter="04 · 五十四算子", kind="grid", group="Component",
         title="分量：拆开调，再合回去",
         sub="dual 是拆分，compose 是合并，gray-to-component 把灰度铺进某个分量",
         narr="第二组是分量：把图拆成通道，调完再合回去。dual 负责拆，compose 负责合，"
              "拆出来的是数据层。"),

    dict(key="16-dual", chapter="04 · 五十四算子", kind="shot", img="op-dual",
         title="拆出来的每一层都能单独调",
         sub="一层一个分量，改完用合并算子按指定公式叠回去",
         narr="拆出来的每一层都能单独上曲线、单独模糊，改完再用合并算子按指定公式叠回去。"),

    dict(key="17-tone", chapter="04 · 五十四算子", kind="grid", group="Tone",
         title="明暗：曝光、对比、阴影高光",
         sub="还有一条只改明度、完全不动颜色的灰度路径",
         narr="第三组是明暗：曝光、亮度对比度、阴影高光，还有一条只改明度、"
              "完全不动颜色的灰度路径。"),

    dict(key="18-blend", chapter="04 · 五十四算子", kind="grid", group="Blend",
         title="混合：Photoshop 的那套公式",
         sub="应用图像、计算、通道混合、正片叠底、颜色查找",
         narr="第四组是混合：应用图像、计算、通道混合、正片叠底、颜色查找。"
              "Photoshop 那套公式这里都有。"),

    dict(key="19-color", chapter="04 · 五十四算子", kind="grid", group="Color",
         title="颜色：饱和度、平衡、白平衡",
         sub="色相带选择 · 自然饱和度 · 色温色调",
         narr="第五组是颜色：色相饱和度、色彩平衡、白平衡、自然饱和度，"
              "还有按色相带只动某一段的。"),

    dict(key="20-hue", chapter="04 · 五十四算子", kind="shot", img="op-hue-saturation",
         title="色相带：只动你想动的那一段",
         sub="按色相划区间，区间内改饱和与明度，区间外一点不碰",
         narr="色相带是把色相环切成几段，只改落在区间里的颜色。调树叶不带上皮肤，"
              "就靠这个。"),

    dict(key="21-mask", chapter="04 · 五十四算子", kind="grid", group="Mask",
         title="蒙版：按颜色选，按通道转",
         sub="颜色范围、通道转 alpha、最大最小值做膨胀腐蚀",
         narr="第六组是蒙版：按颜色范围选、把通道转成 alpha、用最大最小值做膨胀和腐蚀。"),

    dict(key="22-alpha", chapter="04 · 五十四算子", kind="shot", img="op-channel-range",
         title="通道转 alpha：抠图的地基",
         sub="给一段亮度区间，落在区间里的是前景，外面的全透明",
         narr="通道转 alpha 是抠图的地基：给一段亮度区间，落在这段里的算前景，"
              "外面的全透明。"),

    dict(key="23-sharpen", chapter="04 · 五十四算子", kind="grid",
         group=["Sharpen", "Noise"],
         title="锐化与杂色",
         sub="USM 锐化 · 加噪 · 降噪 · 去灰尘划痕",
         narr="第七第八组是锐化和杂色：USM 锐化、加噪、降噪、去灰尘划痕，"
              "修图和做旧两头都够用。"),

    dict(key="24-unsharp", chapter="04 · 五十四算子", kind="shot", img="op-unsharp",
         title="细节类算子得看原始尺寸",
         sub="四像素栅格按 1:1 裁出来，边缘怎么过渡一目了然",
         narr="锐化这类算子看整图没意义，页面上给的是四像素栅格的原始尺寸局部，"
              "边缘怎么过渡一目了然。"),

    dict(key="25-distort", chapter="04 · 五十四算子", kind="grid", group="Distort",
         title="扭曲：三个都是大件",
         sub="置换贴图 · 木偶变形 · 自由变形",
         narr="第九组是扭曲，只有三个，但都是大件：置换贴图、木偶变形、自由变形，"
              "后面还要细说。"),

    dict(key="26-warp", chapter="04 · 五十四算子", kind="shot", img="op-puppet-warp",
         title="木偶变形用 MLS，自由变形用面片",
         sub="非刚性移动最小二乘 vs FFD + 双三次 Bezier",
         narr="木偶变形用移动最小二乘，标几个钉子周围跟着走；自由变形用 FFD 加双三次面片，"
              "能把曲面捏得很顺。"),

    dict(key="27-mesh", chapter="04 · 五十四算子", kind="shot", img="op-mesh-warp",
         title="面片是 C1 连续的，格子不会撕开",
         sub="把手自动限幅，网格可以随手加分割线",
         narr="每个格子的把手是对称的，跨格 C1 连续，画面不会在格子边界撕开一道；"
              "需要更密的控制就加分割线。"),

    dict(key="28-layer", chapter="04 · 五十四算子", kind="grid", group="Layer",
         title="图层样式：参数一一对应",
         sub="投影 · 内阴影 · 描边 · 内外发光",
         narr="最后是图层样式：投影、内阴影、描边、内外发光，参数和 Photoshop 一一对应。"),

    dict(key="29-style", chapter="04 · 五十四算子", kind="shot", img="op-layer-style",
         title="八十多个参数，一个不少",
         sub="角度 · 距离 · 扩散 · 大小 · 杂色 · 等高线",
         narr="图层样式一共八十多个参数，角度、距离、扩散、大小、杂色，"
              "Photoshop 面板上有的这里都有。"),

    # ---------- 05 插件 ----------
    dict(key="30-curves", chapter="05 · 插件", kind="shot", img="plug-curves",
         title="曲线：四个色彩空间，实时预览",
         sub="每个分量一条任意曲线，改参数不落像素",
         narr="插件里最值得看的是曲线：四个色彩空间，每个分量一条任意曲线，"
              "右边实时预览，满意了再应用。"),

    dict(key="32-split", chapter="05 · 插件", kind="shot", img="plug-split",
         title="分通道曲线：一次生成五层",
         sub="每层带一条标准曲线，在 GIMP 自己的曲线面板上改",
         narr="分通道曲线一次生成五层，一层一个分量，每层都带一条标准曲线，"
              "在 GIMP 自己的曲线面板上改。"),

    dict(key="33-cutout", chapter="05 · 插件", kind="shot", img="plug-cutout",
         title="抠图：AI 一条路，本地一条路",
         sub="RMBG 模型走 ComfyUI，四边泛洪走本地，纯色背景毫秒级",
         narr="抠图两条路：AI 走 ComfyUI 的 RMBG 模型，本地走四边泛洪，"
              "纯色背景毫秒级出结果。"),

    dict(key="34-refine", chapter="05 · 插件", kind="shot", img="plug-refine",
         title="选择并遮住：边缘怎么收都行",
         sub="收缩 · 羽化 · 去色边 · 吸附，预览与应用同一套算法",
         narr="抠完进选择并遮住：收缩、羽化、去色边、吸附，全在一张蒙版上算。"
              "预览和应用走同一套算法。"),

    dict(key="35-puppet", chapter="05 · 插件", kind="shot", img="plug-warp",
         title="木偶变形：圈外像素严格不动",
         sub="MLS 全局解 + 到最近钉子的平滑收口",
         narr="木偶变形插件是 MLS，拖动钉子周围跟着走。权重收到最近的钉子上，"
              "圈外的像素严格不动。"),

    dict(key="36-mesh", chapter="05 · 插件", kind="shot", img="plug-mesh",
         title="自由变形：换密度只重拟合",
         sub="FFD + 双三次面片，改网格密度不用重画",
         narr="自由变形用 FFD 加双三次面片，可以随手加分割线。换网格密度只是重拟合，"
              "拉好的形状不会跳。"),

    dict(key="37-vp", chapter="05 · 插件", kind="shot", img="plug-vanishing",
         title="消失点：标一个四边形，反解相机",
         sub="画网格 · 贴图 · 拉正 · 一块平面沿台阶折上去",
         narr="消失点只要标一个四边形就能反解相机：画网格、贴图、拉正，"
              "还能把这块平面沿着台阶折上去。"),

    dict(key="38-freq", chapter="05 · 插件", kind="shot", img="plug-freq",
         title="分频磨皮：纹理和肤色分开",
         sub="低频改肤色，高频留纹理，半径自己填",
         narr="分频磨皮把图分成高低频两层，纹理留在上面，肤色改下面，半径自己填。"),

    dict(key="39-dodge", chapter="05 · 插件", kind="shot", img="plug-dodge",
         title="双曲线磨皮：不破坏像素结构",
         sub="一层加深一层减淡，用曲线控制力度",
         narr="双曲线磨皮反过来：一层加深一层减淡，用曲线控制力度，像素结构一点不动。"),

    dict(key="40-ai", chapter="05 · 插件", kind="shot", img="plug-ai-inpaint",
         title="AI 系列：结果回写成图层",
         sub="AI 修补 · AI 扩图 · AI 放大 · AI 磨皮",
         narr="AI 那几支把 ComfyUI 接进来：修补、扩图、放大、磨皮，结果直接回写成图层。"),

    dict(key="41-ai2", chapter="05 · 插件", kind="shot", img="plug-ai-upscale",
         title="模型、倍数、候选数都能选",
         sub="放大指定模型和倍数，扩图指定方向和像素",
         narr="放大能选模型和倍数，扩图能选方向和像素，都支持多个候选，跑完挑一张。"),

    dict(key="42-selection", chapter="05 · 插件", kind="shot", img="plug-selection",
         title="蒙版、选区、通道，互相转",
         sub="图层转选区 · 选区转通道 · 通道转蒙版",
         narr="还有一组专门做转换：图层转选区、选区转通道、通道转蒙版，中间不用手工描一遍。"),

    # ---------- 06 工程 ----------
    dict(key="43-perf", chapter="06 · 工程", kind="stat",
         title="重采样只算脏区",
         sub="栅格解场 + 行级脏段扫描，圈外像素整行复制",
         items=[("0.15s", "768 × 1024 变形", A), ("0.7s", "1600 × 2400 变形", C),
                ("140ms", "曲线预览", G)],
         narr="重采样只算脏区：先栅格解场，再按行扫脏段，圈外整行复制，全高清图不到一秒。"),

    dict(key="44-comfy", chapter="06 · 工程", kind="steps",
         title="ComfyUI 接进来只要三步",
         sub="配置存在用户目录，不写进仓库",
         items=[("1", "填地址", "ComfyUI 的 http 地址，默认 8188"),
                ("2", "选目录", "指向它的安装目录，用来起进程"),
                ("3", "勾自动启动", "没在跑就拉起来，日志落在本地")],
         narr="ComfyUI 集成三步：填地址、选目录、勾自动启动。之后不用管，日志写在本地。"),

    dict(key="45-ci", chapter="06 · 工程", kind="code",
         title="站点和算子都有自检",
         sub="链接、包、断言、对话框，全部脚本化",
         lines=[("$ python tools/check_site.py", "cmd"),
                ("  94 pages · 0 dead links · 31 packs", "out"),
                ("$ python tools/check_ops.py", "cmd"),
                ("  54/54 ops · 1502 assertions", "key"),
                ("$ python tools/check_plugin_dialogs.py", "cmd"),
                ("  211 checks passed", "key")],
         narr="站点和算子都有自检脚本：链接、包、断言、对话框全跑一遍。三个平台的 CI 各编一次。"),

    dict(key="46-license", chapter="06 · 工程", kind="stat",
         title="许可与平台",
         sub="GPL-3.0，和 GIMP 本身一致",
         items=[("GPL-3.0", "许可证", A), ("3", "个平台", C), ("0", "个运行时依赖", G)],
         narr="许可证是 GPL-3.0，和 GIMP 本身一致。Windows 有预编译包，"
              "Linux 和 macOS 编一次。"),

    # ---------- 07 收尾 ----------
    dict(key="47-download", chapter="07 · 装上", kind="shot", img="guide",
         title="下载，或者自己编一次",
         sub="预编译包 · 安装说明 · 平台差异 · 常见问题",
         narr="想用的话，下载页有现成的包和安装说明；想改，源码和说明都在仓库里。"),

    dict(key="48-outro", chapter="", kind="outro",
         title="gegl-color-ops",
         sub="54 个算子 · 31 个插件 · 54 篇文档 · 1502 条回归断言",
         narr="仓库、文档、预编译包都在 GitHub 上，链接在下面。欢迎提问题，也欢迎补算子。"),
]
