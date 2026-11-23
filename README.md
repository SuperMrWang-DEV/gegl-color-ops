# gegl-color-ops

[![GIMP 3](https://img.shields.io/badge/GIMP-3.x-5C5543?logo=gimp&logoColor=white)](https://www.gimp.org/)
[![GEGL 0.4](https://img.shields.io/badge/GEGL-0.4-2C4C6B)](https://gegl.org/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![Operations](https://img.shields.io/badge/operations-47-brightgreen)](#算子清单)

一组自研的 GEGL 颜色算子（GIMP 3 的滤镜内核），共 **47 个**，统一 `lb:` 命名空间，
在 GIMP 里收在菜单栏顶层的 **SuperMrWang** 菜单下（和「颜色」「图层」平级）。算法按公开公式与可观察的行为实现，
不含任何商业软件的代码或素材；文中出现的产品名仅用于说明某个算子参照了哪种行为，
与各厂商无隶属关系（详见文末「版权与商标」）。

> **在线版**：<https://superMrwang-dev.github.io/gegl-color-ops/> —— 每个算子一篇
> 算法说明（含参数、实测误差、示例图），Retouch 下的插件也各有一篇，另有一个
> **博客**栏目写长文（为什么这么实现、哪里踩过坑，中英双版），首页直接下载免编译包。
> 站点由 `python tools/site_build.py` 从 `ops/*/README.md`、`tools/plugin_docs.py`
> 与 `tools/site/blog/*.md` 生成到 `docs/`，不用手写。

每个算子都是单文件 C（含 `#ifdef GEGL_PROPERTIES` 段），直接编译成 GEGL 插件模块，
可作为非破坏性 fx 挂在图层上。本仓库是唯一源码工程：一次编译出全部算子。

```bash
git clone https://github.com/SuperMrWang-DEV/gegl-color-ops.git
cd gegl-color-ops
./build.sh && ./install.sh --verify     # 需要 GIMP 3 自带的 GEGL 开发头文件
```

```
gegl-color-ops/
├── build.sh              # 一键编译（gcc，跨平台）
├── install.sh            # 编译 + 安装到 GEGL 用户插件目录（可选 --verify）
├── meson.build           # 等价工程，供 Linux/macOS 或 CI 使用
├── common/config.h       # 所有算子共用的版本宏 / GETTEXT_PACKAGE
├── ops/<算子名>/          # 每个算子一个目录：<算子名>.c + 原始说明 + 截图
├── plugin/blend/      # Python 插件：应用图像/计算的完整复刻版（四种落地：选区/通道/灰度层/图层 alpha）
├── plugin/gray-mask/  # Python 插件：灰度图层 → 选区 / Alpha 通道（已下线，仅留回归）
├── plugin/layer-to-selection/ # Python 插件：右键任意图层 → 选区
├── plugin/layer-to-channel/  # Python 插件：右键任意图层 → Alpha 通道（恒为灰度）
├── plugin/channel-to-mask/   # Python 插件：右键任意图层 → 把选中的通道挂成图层蒙版
├── plugin/convert/           # Python 插件：通道/选区/蒙版/路径 十二向互转 + 路径转位图（零参数）
├── plugin/max-min/           # Python 插件：最大值（膨胀）/ 最小值（腐蚀），半径 1–100
├── plugin/split-channels/    # Python 插件：右键任意图层 → 一次拆出 R/G/B/Alpha 四条通道
├── plugin/*-split-curves/    # Python 插件：HSV / LCh / HSL / Lab / HSI 分量分层 + 曲线（菜单 Retouch）；
│                             #   菜单里两条：· single = 一层数据图三条曲线，
│                             #   · multi = 两三张分量层走原生分量混合模式（HSI 只有 single）
├── plugin/frequency-separation/ # Python 插件：高低频磨皮（低频 + 高频两层，合成即原图）
├── plugin/dodge-burn/        # Python 插件：双曲线磨皮（提亮 / 压暗两层，黑蒙版）
├── plugin/neutral-grey/      # Python 插件：中性灰磨皮（50% 灰 + 柔光）
├── plugin/observe/           # Python 插件：观察层六种（黑白 / 陡峭 / 波浪 / 饱和 / 阈值 / 海报化）
├── plugin/luminosity-mask/   # Python 插件：明度蒙版七条通道（亮部/暗部各 3 档 + 中间调）
├── plugin/ai-frequency-separation/ # Python 插件：高低频磨皮（AI 预修，两层内容 = 参考图）
├── plugin/ai-dodge-burn/     # Python 插件：双曲线磨皮（AI 预修，蒙版已预涂）
├── plugin/ai-neutral-grey/   # Python 插件：中性灰磨皮（AI 预修，灰层已反解）
├── plugin/alpha-curves/      # Python 插件：通道 → Alpha + 一条可编辑的 alpha 曲线（菜单 Mask）
├── plugin/sky-replace/       # Python 插件：一键换天（源码保留，.disabled 暂不安装）
├── dist/                 # 编好的模块，给不想编译的人直接下载（windows-x64 / linux-x64）
├── tools/                # 测试图生成、逐算子冒烟、对照表、文件头重排、注释双语化
├── tools/site/           # 站点样式源（生成时拷进 docs/assets/）
│   ├── blog/             #   博客长文正文（中文），英文在 en/blog/
│   └── en/               #   算子文章与博客的英文正文
├── tools/plugin_docs.py  # 十九个插件页的正文与卡片文案（plugins/<slug> 文章页用）
├── docs/                 #  GitHub Pages 站点（tools/site_build.py 生成，别手改）
│   ├── plugins/          #  十九个插件各一篇（菜单结构、原理、用法、实测）
│   └── blog/             #  博客长文（中英双版、带目录）
├── build/                # 编译产物（build.sh 生成，可随时删）
└── LICENSE               # GPL-3.0
```

## 直接下载（免编译）

不想装工具链的，[`dist/`](dist/README.md) 里已经是编好的模块：

| 系统 | 取这个 | 放到 |
|---|---|---|
| Windows x64（整包） | [`docs/download/gegl-color-ops-windows-x64.zip`](docs/download/) | `%LOCALAPPDATA%\gegl-0.4\plug-ins` |
| Linux x86_64（整包） | [`docs/download/gegl-color-ops-linux-x64.zip`](docs/download/) | `~/.local/share/gegl-0.4/plug-ins` |
| Windows x64（单个） | `dist/windows-x64/*.dll` | 同上 |
| Linux x86_64（单个） | `dist/linux-x64/*.so` | 同上 |

放完重启 GIMP。平台要求（glibc 版本之类）、每个文件对应哪个滤镜、怎么校验，
见 [`dist/README.md`](dist/README.md) 与 `dist/manifest.csv`；重新打包用
`python tools/make_dist.py`。

Python 插件走另一条线，两种取法都行：

- **整包（推荐）**：[`gegl-color-ops-plugins-windows-x64.zip`](docs/download/) /
  [`gegl-color-ops-plugins-linux-x64.zip`](docs/download/)——11 个 `.py` 全在里面，
  连同它们依赖的模块。
- **单装**：`docs/download/gegl-color-ops-plugin-<名字>.zip`，一个插件一个包。

两种包都**自带插件内部用到的算子模块**（`lb:hsv-dual` 这类，放在 `modules-<平台>/`），
不用再单独找算子。`.py` 放进 GIMP 的 `plug-ins`，附带的模块放进 GEGL 的
`gegl-0.4/plug-ins`——两个目录不同，包内 `安装说明.txt` 分步写了。

> Linux 端 component 家族的 11 个模块（各空间的 dual / compose 与 gray-to-component）
> 还没出预编译包，所以 Linux 插件整包里只有 `channel-range-to-alpha`；五个
> **Split (Curves)** 插件要在 Linux 上用，先 `./build.sh` 编一份放进 GEGL 目录。
> `hsl-bands`（2026-11-18 由 `hsl-seven` 改名）的 Linux `.so` 同样等下一次 CI。
> Windows 端是齐的。

## 算子清单

菜单名（`gimp:menu-label`）只留主名，**不带括号**——括号会把 GIMP 的菜单/选项面板撑宽。
模型或来源这类信息写进 `description` 和本表最后一列，不塞进名字。

| GEGL id | 菜单名 | 完整标题 | 组 | 类型 | 作用 |
|---|---|---|---|---|---|
| `lb:hue-saturation` | Hue/Saturation | Hue/Saturation | Color | Point | HSL 色相/饱和度/明度，主控 + 六区间独立调 |
| `lb:hue-saturation-basic` | Hue/Saturation (Basic) | Hue/Saturation (Basic) | Color | Point | 三滑杆公式：色相旋转、饱和度相对缩放（s/(1−x)）、明度向白/黑混合；逐码对拍参考实现 |
| `lb:hue-range-basic` | Hue Range (Basic) | Hue/Saturation Range (Basic) | Color | Point | 色系范围：六色系四柄色条（内二柄全选、外二柄线性过渡），范围内按权重缩放应用色相/饱和度/明度；与上一个串联即「主控 + 分色系」 |
| `lb:hsl-bands` | HSL 8 Bands | HSL 8 Bands | Color | Point | 八段色相（含洋红）各调 H/S/L，RAW 编辑器 风格 |
| `lb:channel-mixer-plus` | Channel Mixer Plus | Channel Mixer Plus | Blend | Point |经典图像编辑器通道混合器 + 通道 offset + 单色模式 |
| `lb:channel-range-to-alpha` | Range → Alpha | Channel Range to Alpha | Mask | Point | 通道数值区间 → alpha（混合颜色带） |
| `lb:max-min` | Maximum / Minimum | Maximum / Minimum | Mask | Area | 形态学最大值（膨胀）/ 最小值（腐蚀）：邻域取极值，方窗可分离 O(n)、圆盘 O(n·r)；u8/u16/float 各自在原生精度里比较，不换算色彩空间 |
| `lb:cmyk-primary-correction` | CMYK Primary | CMYK Primary Correction | Color | Point | 可选颜色：九组色域各存一份 C/M/Y/K，同时生效 |
| `lb:color-balance` | Color Balance | Color Balance | Color | Filter |经典图像编辑器色彩平衡：三区间指数相乘合成一条逐通道曲线，单段残差 0.30 码 |
| `lb:color-grading` | Color Grading | Color Grading | Color | Point | RAW 编辑器 颜色分级：阴影/中间调/高光/全局四轮盘 + 明度 + Blending/Balance，按亮度分带（模型对齐，未逐码标定） |
| `lb:color-lookup` | Color Lookup | Color Lookup | Blend | Filter |经典图像编辑器颜色查找：按 .cube 3D LUT（可带 1D shaper）查表，三线性 / 四面体可选 |
| `lb:match-color` | Match Color | Match Color | Color | Composer |经典图像编辑器匹配颜色：Lab 统计迁移（Reinhard），亮度/颜色强度/渐隐/中和 |
| `lb:colorize-hsl` | Colorize | Colorize | Color | Point |经典图像编辑器色相/饱和度「着色」实测复刻：扔掉原有 H/S，只留输入 L 的单色调，残差 0.03 码 |
| `lb:color-mask-select` | Mask by Color | Color Mask Select | Mask | Point |经典图像编辑器色彩范围：高光/阴影/中间调按「阈值 + 容差」实测复刻（平均 2.1 码），色系/自定色走容差窗 |
| `lb:lab-levels` | LAB Levels | LAB Levels | Levels | Filter | LAB 三通道各自黑白场 + 伽马，a/b 绕中性轴分段 |
| `lb:hsl-levels` | HSL Levels | HSL Levels | Levels | Filter | HSL 三分量色阶，色相按弧环形重映射 |
| `lb:hsb-levels` | HSB Levels | HSB Levels | Levels | Filter | HSB（HSV）三分量色阶，S/B 是 HSV 语义 |
| `lb:lch-levels` | LCH Levels | LCH Levels | Levels | Filter | CIE LCh 的 L/C/H 色阶，调色度不串色相 |
| `lb:cmyk-levels` | CMYK Levels | CMYK Levels | Levels | Filter | CMYK 四版墨量色阶（babl 分色，非 ICC） |
| `lb:hsi-levels` | HSI Levels | HSI Levels | Levels | Filter | HSI 三分量色阶，I 取三通道均值 |
| `lb:levels` | Levels | Levels | Levels | Point |经典图像编辑器色阶：复合 + R/G/B 四组输入黑/灰/白场与输出黑白场，0–255 刻度；gamma 方向经公开实测点验证（154@0.46→84、200@1.646→220） |
| `lb:exposure` | Exposure EV | Exposure EV | Tone | Filter |经典图像编辑器曝光：EV、偏移、伽马；整数图走伽马域、浮点图走线性域，按输入精度自动选路 |
| `lb:rgb-domain-grayscale` | Black & White | Black & White | Tone | Point |经典图像编辑器黑白：六色权重转灰 + 可选着色 |
| `lb:vibrance-hyper` | Natural Saturation | Natural Saturation | Color | Point | LAB 自然饱和度：色度双曲蒙版 + 肤色保护窗 + 色域收敛不扭色相 |
| `lb:vibrance` | Vibrance | Vibrance | Color | Point |经典图像编辑器自然饱和度实测复刻：ΔS = A(v)·S^p·(1−S)^q，叠红带与亮度项，16 位标定；只管饱和度，色温色调由 `lb:color-temperature-tint` 独立承担 |
| `lb:brightness-contrast` | Brightness/Contrast | Brightness/Contrast | Tone | Point |经典图像编辑器亮度/对比度实测复刻：新版两条曲线族查表 + 旧版闭式（pivot 89、b 夹 ±100） |
| `lb:xyz-multiply` | Photo Filter | Photo Filter | Blend | Point | **即经典图像编辑器照片滤镜**（实测复刻）：滤镜色在 D50 XYZ 域正片叠底，密度 + 保留明度（W3C SetLum）；不保留明度档 ≤0.71 码 |
| `lb:shadows-highlights` | Shadows/Highlights | Shadows/Highlights | Tone | Filter |经典图像编辑器阴影/高光实测复刻：边缘感知邻域亮度决定提亮提多少，含色调宽度、颜色、中间调对比度、修剪黑白。**不推荐日常使用（慢）**：半径 30 时每像素约 1.4 µs，2048×1536 默认参数净耗时 0.7 s，交互拖滑杆会卡；整体明暗请用 `lb:levels` / `lb:lab-levels`，见 `ops/shadows-highlights/.discouraged` |
| `lb:color-temperature-tint` | Color Temperature & Tint | Color Temperature & Tint | Color | Point | 经典图像编辑器 2026「色彩与自然饱和度」里的色温 / 色调：冷↔暖、绿↔洋红，中性灰跟着偏色、黑白不动 |
| `lb:apply-image` | Apply Image | Apply Image | Blend | Composer |经典图像编辑器应用图像：aux 层按 26 种混合模式压到本层，可只作用单通道；加法/减法带 缩放(1..2)/补偿值(±255)；源层没盖到和透明的地方原样输出 |
| `lb:calculations` | Calculations | Calculations | Blend | Composer |经典图像编辑器计算：两路通道混合出灰/alpha 蒙版，双源可各自反相；加法/减法带 缩放(1..2)/补偿值(±255)；源 2 透明处蒙版为 0 |
| `lb:gray-to-component` | Gray To Component | Gray To Component | Component | Point | 分量灰度 → 彩色编码：把 `component-extract` 出来的灰度层编成「携带该分量」的彩色，分量混合模式才读得出来。分量曲线插件的旧版靠它做编码；现在五个插件都直接走 dual / compose，它更像一件独立工具（手工搭分层时仍有用） |
| `lb:hsl-dual` | HSL Dual Extract | HSL Dual Extract | Component | Point | HSL 分量曲线的提取器：一张图同时携带三分量（R = 饱和度、G = 明度、B = 色相/360）。S 与 L 耦合，必须同时读到才能精确换回 HSV 的 S/V；`HSL Split (Curves)` 的第一道滤镜 |
| `lb:hsl-compose` | HSL Compose | HSL Compose | Component | Point | HSL 分量曲线的合成器：把（R = S、G = L、B = H/360）的数据图还原成真实 HSL 色。babl 做转换，与 GIMP 自己的 HSL 同口径，往返 0.00001 码 |
| `lb:lab-dual` | Lab Dual Extract | Lab Dual Extract | Component | Point | Lab 分量曲线的提取器：R = a、G = b、B = L*，一张图带齐三个分量（a/b 归一化到 0…1，中性灰落在 0.502）。a 与 b 是直角坐标，没有可借的分量混合模式，只能联合算出颜色；`Lab Split (Curves)` 的第一道滤镜 |
| `lb:lab-compose` | Lab Compose | Lab Compose | Component | Point | Lab 分量曲线的合成器：把（R = a、G = b、B = L*）的数据图还原成真实 Lab 色。babl 的 `CIE Lab float`（D50）做转换，与 GIMP 的 Lab 空间同口径，浮点往返 0.010 码 |
| `lb:hsv-dual` | HSV Dual Extract | HSV Dual Extract | Component | Point | HSV 分量曲线的提取器：R = 饱和度、G = 明度、B = 色相/360，一张图带齐三个分量（babl `HSVA float`，0…1 归一化）；`HSV Split (Curves)` 的第一道滤镜 |
| `lb:hsv-compose` | HSV Compose | HSV Compose | Component | Point | HSV 分量曲线的合成器：把（R = S、G = V、B = H/360）的数据图按 HSV 定义算回真实色，浮点往返 0.0002 码 |
| `lb:lch-dual` | LCh Dual Extract | LCh Dual Extract | Component | Point | LCh 分量曲线的提取器：R = L*/100、G = C*/140、B = 色相/360（babl `CIE LCH(ab) alpha float`，D50）。彩度量程取 140，sRGB 最饱和的纯蓝 133.8 也装得下；`LCh Split (Curves)` 的第一道滤镜 |
| `lb:lch-compose` | LCh Compose | LCh Compose | Component | Point | LCh 分量曲线的合成器：把（R = L、G = C、B = h）的数据图乘回物理量再转 RGB，与 `lb:lch-levels` 同一套 Lab 口径，浮点往返 0.0005 码 |
| `lb:hsi-dual` | HSI Dual Extract | HSI Dual Extract | Component | Point | HSI 分量曲线的提取器：R = 饱和度、G = 强度、B = 色相/360。色相用 HSI 自己的余弦角（与 HSV 的参数角最多差 1.117°）；`HSI Split (Curves)` 的唯一一道提取器 |
| `lb:hsi-compose` | HSI Compose | HSI Compose | Component | Point | HSI 分量曲线的合成器：把（R = S、G = I、B = H/360）的数据图按余弦式逆变换还原成真实色，与 `lb:hsi-levels` 共用 common/color-levels.h 里那份 HSI |
| `lb:displace` | Displace | Displace | Distort | Composer | 按位移图重采样：一张 RGBA 图同时给 X/Y（R/G），位移图不乘 alpha，覆盖不到的像素原样输出，单位可按长边百分比，五种越界策略，默认 nohalo 不振铃 |
| `lb:unsharp-mask` | Unsharp Mask | Unsharp Mask | Sharpen | Area | PS「USM 锐化 / 智能锐化」等价：σ ≤ 4 用真高斯、更大退化为三次盒式（O(n)）；数量/半径/阈值齐备，外加把结果夹到原图 3×3 极值的光晕抑制 |
| `lb:add-noise` | Add Noise | Add Noise | Noise | Filter | PS「添加杂色」等价：高斯 / 均匀、可单色、按行播种所以分带不影响结果，同种子逐位可复现 |
| `lb:reduce-noise` | Reduce Noise | Reduce Noise | Noise | Area | PS「减少杂色」等价：sigma 滤波（Lee），只平均与中心相近的邻居，强度 / 保留细节 / 每通道可调，边缘不动 |
| `lb:dust-scratches` | Dust & Scratches | Dust & Scratches | Noise | Area | PS「蒙尘与划痕」等价：取阈值内邻居的中值，中心自己不入集合，所以孤立灰尘被抹掉而真实边缘不动 |

每个算子的算法说明、参数含义见 `ops/<算子名>/README.md`（原始文档）。

**三个双输入算子**（`apply-image` / `calculations` / `displace`）除 `input` 外还有一个
`aux` pad。三者都是 composer，但基类不同：`apply-image` 要按源图层的大小和位置决定
「这块有没有东西可混」，所以用 `GeglOperationComposer`（`process` 拿到的是
`GeglBuffer`，可以 `gegl_buffer_get_extent(aux)`）；`calculations` 输出的是整幅蒙版，
缺的源按黑算，用开销更小的 `GeglOperationPointComposer` 就够；`displace` 同样要
extent 来判断位移图盖到哪（盖不到的地方原样输出），并且要自己建 sampler，也只能用
`GeglOperationComposer`。

`apply-image` 的「有没有东西可混」分两层看：extent 是粗筛（图层盖到哪），源像素的
alpha 是细筛（这块地方真有像素吗）。抠图层的透明洞里 RGB 是 0，只看 extent 会把洞
一起乘黑——就是「相交区域里本不该动的地方也变了」。

`calculations` 输出的是蒙版，没有「原图」可保留，所以源 2 的 alpha 直接当覆盖率乘在
结果上：透明处蒙版为 0（不选中），半透明柔边按比例衰减。两个算子的判据一致——源层
没有像素的地方不让它的 RGB 0 参与运算，区别只在落点（保留原值 / 归零）。

**加法/减法的 缩放/补偿值**：与经典图像编辑器一致，混合模式选 加法
（Linear Dodge）或 减法 时，公式变为 `结果 = (A ± B) / 缩放 + 补偿值`，缩放
1.0..2.0、补偿值 ±255（8bit 口径，内部归一化）；其余模式这两个参数被忽略。
共享内核 `common/blend.h` 的 `lb_blend_separable` 统一收 `scale/offset` 两个
参数，GEGL 算子、ctypes C 内核和纯 Python 后备三条路径同源。

- GIMP 里 aux 由滤镜对话框的输入选择器指定（GIMP 3 会打印 `aux_label` 的名字）；
  这类滤镜**只能合并应用**，不能做非破坏性 fx，是 GIMP 目前的限制。
- aux 没接时自动退化为「源 = 本图」，此时等于同图内做通道混合——计算最常用的场景。
- gegl 命令行不支持双输入，测这两个算子要用 `build/auxrun`（`./build.sh` 顺带编译，
  源码见 `tools/auxrun.c`）。

### Python 插件版：plugin/blend

GEGL 算子只接住了像素计算那一半；**输入选择**（任意打开图像的任意图层/通道、
遮罩指向第三张图）和**结果落地**（直接生成选区/新建 Alpha 通道）是插件 API 的
主场。`plugin/blend` 是一对 Python-Fu 插件，把经典图像编辑器对话框完整搬过来：

- `Apply Image` / `Calculations`，位于 **SuperMrWang**
- 源可以是任意打开图像的任意图层；通道含 Gray/R/G/B/Alpha/图层蒙版
- 混合模式选 加法/减法时多出 **缩放（1.0..2.0）与 补偿值（-255..255）**
  两个输入框，其余模式忽略；GEGL 算子同名参数 `scale`/`offset`
- 计算结果四选一：活动选区 / 新建 Alpha 通道 / 新建灰度图层 / 写入图层 alpha
- 计算多两个开关：
  - **Range（计算范围）**：`Whole layer` 整幅图层 / `Selection only` 只算当前
    选区——选区外结果归零（=不选中），灰度图层在选区外透明；没有选区时退回
    整幅。批处理参数 `scope`（0/1）
  - **Load result as selection（同时载入为选区）**：结果写成通道/灰度图层/
    图层 alpha 的同时，把同一份灰度也载入为活动选区，一步到位。批处理参数
    `load-selection`。已经存在的灰度图层可以用 layer-to-selection 插件的
    **SuperMrWang → Convert → Layer to Selection** 事后转
- 写入通道/灰度图层时会**临时挂起当前选区**（shadow buffer 的合并会遵守选区，
  否则新通道在选区外是黑的），写完后按需恢复旧选区或换成新结果
- 像素内核 `tools/blend_core.c` 编成 `blend_core.dll` 由 ctypes 调用，公式
  直接 include `common/blend.h`——**GEGL 算子与 Python 插件保证同一结果**；
  没有编译产物时自动退化为纯 Python（一致但慢）

```bash
./install-plugin.sh          # 装到 %APPDATA%/GIMP/3.x/plug-ins，重启 GIMP 生效
```

交互模式弹自定义对话框；批处理可用注册参数（`blend` 0..25 按经典图像编辑器顺序、
`source-image`/`source-layer` 等，见 `do_create_procedure`）。

### Python 插件版：plugin/gray-mask（已下线）

曾经把「灰度图层 → 选区 / Alpha 通道」压成两个菜单项（`Grayscale Layer to
Selection` / `to Channel`），但实现是复制/粘贴，比 `plugin/layer-to-selection`、
`plugin/layer-to-channel` 弱：彩色图层不按亮度转、不挂起选区、偏移图层也处理不
干净。2026-11-18 起菜单项撤掉，功能由那两个插件接管（它们同样吃灰度层，而且
更快），`SuperMrWang → Convert` 下不再出现名字相近的两套条目。

源码和 `tools/check_gray_mask.py`（8 条行为断言，跑在 gimp-console 的
python-fu-eval 里，不要求插件已安装）保留着，作为那条复制/粘贴链的回归；
要恢复菜单就删 `plugin/gray-mask/.disabled` 再跑 `./install-plugin.sh`。

### Python 插件：plugin/layer-to-selection 与 plugin/layer-to-channel

**右键点哪个图层，就把它转成选区或通道。** GEGL 算子跑完常常留下一张灰度图，
往后的用途无非两种：当蒙版用（选区）或留档复用（通道）。原生流程要点四步
（复制 → 建通道 → 粘贴 → 蒙版转选区），这个插件一步完成，而且不要求图层是
「纯灰度」：

- 入口：**图层右键 → SuperMrWang**，也挂在 **SuperMrWang → Convert** 下
- `Layer to Selection`：通道可选 **Gray（亮度）/ R / G / B / Alpha**，可选四种
  组合方式（替换/加/减/交）与反相
- `Layer to Channel`：**恒为灰度**——彩色图层先按亮度转灰度，灰度图层原样，
  再把这些灰度值写成通道值（黑=不选中、白=完全选中）。没有「取 R 通道」这类
  选项，避免拿到单色通道而不是明暗。可反相、可自定义通道名，建好会在状态栏
  提示通道名
- 直接读图层 buffer（不走复制粘贴），**比画布小、带偏移的图层**只在自己
  位置生效，界外不选中
- 灰度内容走零拷贝的通道切片快捷路径；彩色图层的 Gray 才复制一份做
  `desaturate`（babl 的 `Y' float` 是 HSL 明度——纯红会读成 0.51，不是亮度）；
  临时图层用完就删，并把活动图层还给原来选中的那个
- 图层组没有自己的像素，会明确报错提示先合并组

`plugin/gray-mask`（已下线）当年走复制/粘贴、会带上图层蒙版等显示效果；这两个
插件读原始像素、更快，现在「灰度图 → 蒙版」只剩这一条路。

回归：`tools/check_layer_to_mask.py`（23 条断言：灰度值、反相、偏移图层、
彩色亮度、四个单通道、通道值/名字/反相、**彩色图层转通道得到的是亮度而不是
R 通道**、**有选区时转通道不被截断**、四种组合方式）。

### Python 插件：plugin/convert（十二向转换 + 路径转位图）

```
SuperMrWang → Convert → Channel to Selection / Selection to Channel
                      → Channel to Mask / Mask to Channel
                      → Selection to Mask / Mask to Selection
                      → Path to Selection / Selection to Path
                      → Path to Channel / Channel to Path
                      → Path to Mask / Mask to Path
                      → Path to Bitmap
图层右键 → SuperMrWang → Convert（同样十三项）
通道右键 → SuperMrWang → Convert（以通道为源的三项）
路径右键 → SuperMrWang → Convert（以路径为源的四项）
```

**只是原生方式的便捷实现**：不新增任何算法，十二个方向全部转调 GIMP 自带的 PDB 过程，
所以结果与手点原生菜单逐位相同；插件的作用只是把散在四处菜单、要跨三四步的动作收成一次点击。

**一个插件，十三个过程，全部零参数。** 通道、选区、蒙版、路径四者两两互转，每条路一个菜单项，
点下去直接执行，不弹参数框——源都从上下文取：

| 方向 | 源 | 落点 |
| --- | --- | --- |
| 通道 → 选区 | 通道面板里右键点中的那条（否则取面板选中的、或图里唯一的） | 像素选区 |
| 选区 → 通道 | 当前选区（**没有选区 = 全选**） | 新建通道 `Selection` |
| 通道 → 蒙版 | 同上 | 选中图层的蒙版（多选则每个都挂） |
| 蒙版 → 通道 | 选中图层的蒙版 | 新建通道 `<图层名> Mask` |
| 选区 → 蒙版 | 当前选区 | 选中图层的蒙版 |
| 蒙版 → 选区 | 选中图层的蒙版 | 像素选区 |
| 路径 → 选区 | 路径面板里右键点中的那条（否则取面板选中的、或图里唯一的） | 像素选区 |
| 选区 → 路径 | 当前选区 | 新建路径 `Selection` |
| 路径 → 通道 | 同上 | 新建通道 `<路径名>` |
| 通道 → 路径 | 同「通道 → 选区」 | 新建路径 `Channel <通道名>` |
| 路径 → 蒙版 | 同上 | 选中图层的蒙版 |
| 蒙版 → 路径 | 选中图层的蒙版 | 新建路径 `<图层名> Mask` |
| 路径 → 位图 | 矢量图层 / 路径 | 矢量图层：按它自己的填充与描边渲染，**替换**原层；裸路径：新建像素图层（前景色填充，裁到路径外接框） |

原生那些路散在四个地方（选择菜单、通道右键、图层面板右键、路径右键），其中**「蒙版 → 通道」
根本不存在**，只能先蒙版到选区再选区存通道；**「通道 / 蒙版 ↔ 路径」**同样没有直连。
这里把它们都做成一步。

**前十二个方向都转调原生过程，结果逐位一致**；第十三个是唯一真·新建像素的：

- **路径 → 位图**（`Path to Bitmap`）有两种来源：
  - **矢量图层**（GIMP 3.2 的 `GimpVectorLayer`）：它自己有填充色、描边色和线宽，所以
    按它**自己的样子**渲染成一张同尺寸位图，**替换掉原来那一层**——一层进、一层出，
    不会按前景色另造一张盖上去。实现上 GIMP 没有「把矢量图层降级」的 API
    （`rasterize()` 只刷新渲染缓存、类型仍是矢量；`Layer.flatten()` 也不降级），
    所以读缓存 → 写进新 RGBA 层 → `image.remove_layer()` 摘掉原层。
  - **裸路径**：路径只存几何、不带填充色和线宽，所以替它选了「用前景色填内部」这一种
    落笔方式，与原生「编辑 → 用前景色填充路径」同义（原生那条内部也是先转选区再填，
    边缘同样一像素过渡）。新图层只做路径外接框那么大、偏移对回原位，栅格化一个
    24×24 的图标不会顺手生成一张 4000×3000 的空图层。要线稿（描边）而不是实心形状时，
    用原生「编辑 → 描边路径」。

其余十二个不碰像素缓冲：通道 / 路径转选区走
`gimp-image-select-item`，选区存通道走 `gimp-selection-save`，选区建蒙版走
`create_mask(SELECTION)`，选区描路径走 `plug-in-sel2path`（「选择 → 路径」背后那个过程）。
「通道 ↔ 蒙版」「通道 / 蒙版 ↔ 路径」原生没有直连，就按原生的两步走，中间都经选区这一站。

因此中间灰带着原生那点漂移：默认 8 位图上，通道 128 进选区读回 **188**，选区 128
存通道读回 **55**；而选区 ↔ 蒙版原生自己会换算，那一对不漂。32 位线性精度的图像上
通道本身就存线性值，那六个位图方向都不漂。这是刻意的——要的就是「原生怎样就怎样」。
路径方向跟着这条链走：通道 → 路径是先变成 188 的选区再描轮廓，轮廓落在 50% 等值线上。

三个注意点：

1. **没有选区时先按全选处理**（原生过程没有选区会拒绝执行），通道名 `Selection`；
2. **已有蒙版先丢掉再新建**，结果与原生新建逐位一致，重跑即刷新；
3. **路径这一站有损**：它只有几何、没有 alpha，「位图 → 路径」会把羽化、渐变、抗锯齿
   的边缘压成硬边界（原生 To Path 也一样）；「路径 → 选区 / 通道 / 蒙版」出来也是
   干净的硬边。路径重名自动加序号，重跑不覆盖旧路径。

回归：`tools/check_convert.py`（72 条断言，每个方向都拿原生 PDB 的结果当基准逐位
比较；另覆盖 32 位线性精度、偏移图层、多图层、已有蒙版重建、无选区、三种错误分支，
以及路径六向、羽化过路径的硬边化、路径取源兜底、重跑命名，和「路径 → 位图」的
裁切/偏移/与原生逐位一致）。
`tools/check_convert_pixels.py` 是加严版：0–255 全幅渐变、整幅 4096 像素逐像素比，
u8 与 32 位线性各跑一遍十二向，要求偏差为 0（24 项）。

### Python 插件：plugin/max-min

```
SuperMrWang → Mask → 最大值 / 最小值
图层右键 → SuperMrWang → Mask → 最大值 / 最小值
```

Photoshop「最大值 / 最小值」的等价物：最大值＝膨胀（亮区外扩、吞掉暗处小点），
最小值＝腐蚀（亮区收缩、啃掉残留白边）。

**这个功能 GIMP 3 已经没有了**：`gegl:dilate` / `gegl:erode` 属于 GEGL 的
workshop 算子，官方 Windows 构建没编进去，`plug-in-dilate` 也在 2.10 之后移除
（本机 3.2.8 上三条都验过：`gegl --list-all` 空、PDB 查不到、DLL 里没有字符串）。
所以这里用的是本项目自己的算子 `lb:max-min`，不是转调原生。

| 参数 | 范围 | 说明 |
|---|---|---|
| 模式 | 最大值 / 最小值 | 膨胀 / 腐蚀 |
| 半径 | 1–100 px | r=1 即 3×3，边缘向外长一圈（与 PS 同语义） |
| 形状 | 方形 / 圆形 | 方窗 (±r, ±r) / 圆盘；对应 PS 的方形度 / 圆度 |
| 影响 alpha | 默认关 | PS 同样不动图层透明度 |

挂载方式按目标分两路：

- **图层** → 非破坏滤镜，参数随时改、可以关掉；
- **蒙版 / 通道** → 直接写像素（GIMP 3 的蒙版没有滤镜栈：往蒙版 append 一条滤镜，
  API 不报错但渲染不受影响），靠撤销退回。

彩色图上会出现紫边——PS 也是逐通道取极值，这是语义的一部分。要没有偏色就把目标
换成蒙版、通道或灰度层。

回归：`tools/check_max_min.py`（27 项，对 O(r²) 暴力实现逐位比，u8/u16/f32 ×
方/圆 × 三档半径，含跨分带与超图半径）、`tools/check_max_min_plugin.py`（12 项，
PDB / 滤镜挂载 / 蒙版写像素 / 错误分支）。

### Python 插件：plugin/channel-to-mask

```
图层右键 → SuperMrWang → Mask → Channel to Mask...
通道右键 → SuperMrWang → Mask → Channel to Mask...（点的哪条就用哪条）
```

**只是原生方式的便捷实现**：像素仍由 GIMP 自己的 `gimp-image-select-item` 与
`create_mask(SELECTION)` 产生，插件只负责把它们串起来、再加一个反相。

**它是 `layer-to-channel` 的反向。** 那个把图层压成通道，这个把通道挂回图层当蒙版。
GIMP 自带的「从通道取蒙版」藏在 **图层 → 蒙版 → 添加图层蒙版 → 通道**，弹窗里
还得再挑一次通道，而且一次只管一个图层。这里只补三件事：

- **从右键进来**：点哪个图层就给哪个挂蒙版；图层面板多选时逐个挂上同一份内容
- **可反相**：按通道的补集遮罩，省掉「先反相再挂」那一步
- **可刷新**：图层已有蒙版时先丢掉旧的再新建，结果与原生新建逐位一致

通道取「通道面板里右键点中的那条」，没有的话依次退到面板里选中的、图里唯一的，
也可以填名字指定。灰度值就是遮罩强度：
黑遮住、白露出、中间灰半透明。偏移的小图层不用管——蒙版跟图层同尺寸，取的是
画布上同位置的通道值。

**数值与原生逐位一致**（`tools/check_channel_to_mask.py` 拿原生结果当基准比对）。
GIMP 3 没有「通道直接建蒙版」的入口，原生用户只能走「通道 → 选区 → 选区建蒙版」，
本插件走同一条路、调同一个 `create_mask(SELECTION)`。所以中间灰也照样带原生的漂移：
8 位图上通道 128 建出来的蒙版是 **188**，32 位线性精度则不漂。反相在原生里没有对应
动作，做法是清掉选区再整块反相。

回归：`tools/check_channel_to_mask.py`（21 条断言，跑在 gimp-console 的
python-fu-eval 里，不要求插件已安装）。

### Python 插件：plugin/split-channels

**一个图层拆成多条通道。** 和 `layer-to-channel` 是一对：那个把整层压成**一条**
灰度通道，这个保留**分量本身**、一次出多条。

- 入口：**SuperMrWang → Convert → Split Channels**，也挂在图层右键同一个位置
- 默认拆 **R / G / B / Alpha** 四路，命名「图层名 R」「图层名 G」「图层名 B」
  「图层名 Alpha」；同名通道已存在自动加序号，不覆盖已有内容
- 灰度图 R = G = B，拆三路是三条一样的通道，没有意义——这种图只出 **Gray**，
  带透明才多一条 Alpha；彩色图关掉「含 Alpha」就只出三路
- 拆完把**源图层隐藏**（不删除），画布上直接看到结果，想对照点回眼睛即可；
  「隐藏源图层」关掉则原图与通道并存
- 通道恒为**画布大小**：比画布小、带偏移的图层，没盖到的区域补黑，不会出现
  「通道跟着图层尺寸走、贴上去错位」
- 一次读完整层数据再按分量切片，不是每路读一遍 buffer；600 万像素拆四路约 0.9 秒
- 写通道前先挂起选区，否则 shadow buffer 的 merge 会被选区截断，通道只有
  选区内有内容

两个插件都在通道面板里产出，可以并存。回归：`tools/check_split_channels.py`
（31 条断言：四路内容与源图层同名通道逐项相等、灰度图只出 Gray、无 alpha
图层不出 Alpha、偏移图层外部补零、有选区时通道不被截断、前缀与重名序号）。

### Python 插件：plugin/alpha-curves

**把透明度本身当曲线来画。** GIMP 的曲线工具有 Alpha 通道，但它只能调「已经
存在的透明度」——曲线看不到红通道是多少。这个插件把两步都挂在图层上，都是
非破坏滤镜：

1. `1 · 通道 → Alpha` —— `lb:channel-range-to-alpha`，四个滑块拉到
   `l1=0 / l2=255 / r1=r2=255`，斜坡占满全程，退化成「alpha ← 通道值」；
2. `2 · Alpha 曲线` —— `gimp:curves`，通道 = Alpha，**一条普通的曲线**。

位置：**SuperMrWang → Mask → Alpha Curves**，或图层右键 →
SuperMrWang → Retouch。参数两项：源通道（gray / R / G / B / LAB L·A·B /
alpha）与初始形状（auto / band 梯形 / identity / soft）。

曲线能画成任意一维映射，所以梯形只是其中一种形状；`lb:channel-range-to-alpha`
的四滑块仍然有用——它一步就能把通道变成 alpha，而曲线必须先把通道搬进 alpha。

两条滤镜是**乘**的关系：`alpha = 原 alpha × 曲线(通道值)`，与算子一致；
原图不透明时就是 `曲线(通道值)`。选 `alpha` 作源通道时只挂第 2 条，纯调现有
透明度。实测：恒等曲线与通道值差 ≤ 0.01 码、RGB 零改动；梯形曲线与
`lb:channel-range-to-alpha` 逐像素一致（0.0005 码）。回归
`tools/check_alpha_curves.py` 32 项。

### Python 插件：plugin/color-range

**色彩范围的真对话框。** 算子 `lb:color-mask-select` 的参数是 GEGL 静态属性：
高光、阴影、中间调各有一组限值，GIMP 的通用对话框会把四根 0–255 的滑杆一起
摆出来，而且切换「选择颜色」时一根都不动。这个插件用 GTK 自己搭界面，按模式
换参数页：

| 模式 | 界面上的参数 | 默认 |
|---|---|---|
| 红 / 黄 / 绿 / 青 / 蓝 / 洋红 | 颜色容差、最低彩度 | 50 / 0 |
| 自定颜色 | 取色按钮、容差、最低彩度 | 纯红 / 50 / 0 |
| 高光 | 范围、容差 | **192** / 50 |
| 阴影 | 范围、容差 | **64** / 50 |
| 中间调 | 范围下限、范围上限、容差 | **64 / 192** / 50 |

公共的羽化（10）、反相、红色叠加预览在各页之外。切换模式只换页，每页自己
记住自己的值。像素运算仍由 `lb:color-mask-select` 完成——壳只决定「哪个模式
显示哪几根杆、从多少起步」，所以两条入口算出的像素一致。

拖参数时画面是红色叠加实时预览（60 ms 内合并重算）；「确定」先关叠加再合并，
红色不会烤进图层，蒙版写进 alpha；「取消」撤掉整条预览滤镜，连中途补上的
alpha 都有回滚。与算子版本的区别是**一次性应用**——想随时回改就用菜单里的
算子挂成非破坏滤镜。

位置：**SuperMrWang → Mask → Color Range**，或图层右键 → SuperMrWang。
回归 `tools/check_color_range.py`（40 项：十个模式的默认值、对话框各页取值、
切模式不串值、合并后不留滤镜、RGB 零改动、高光/阴影两端方向、无 alpha 自动补、
图层组被拒）。

### Python 插件：plugin/sky-replace（暂不发布）

> 源码保留在仓库里，目录带 `.disabled` 标记，install-plugin.sh 不会安装；
> 站点与下载包也暂不放出。想启用：删除 `plugin/sky-replace/.disabled`
> 再跑 `./install-plugin.sh`。

**一键换天**。选中照片图层 + 指定一张天空图，一次点击完成：

1. 从图像顶边三个种子点做泛洪选择（GIMP 3 的采样阈值/判据走
   context，插件用 context_push/pop 避免污染用户设置），把连通的
   天空选出来；经典算法，无需 AI 模型，蓝天/晴天照片效果好；
2. 选区按参数收缩/羽化（`edge` 正=收缩、负=扩张，默认收 1px
   收掉前景光晕）；顶行覆盖率 <60% 时报错提示而非静默输出；
3. 天空图按 cover 方式缩放、居中裁切，插到照片图层**正上方**
   （插下方会被不透明照片完全盖住）；
4. 亮度匹配：两张天空区直方图均值的 gamma 关系（注意 GIMP levels
   的 gamma>1 是提亮，曲线 = in^(1/γ)），把新天空亮度拉到与原
   天空一致，可在对话框关掉；
5. 选区转成天空图层的图层蒙版，前景自然露出；
6. 可选存为 `Sky Mask` 通道：对分割不满意时，用 lb:color-mask-select
   等蒙版算子手工精修，再用 Layer to Selection 重新生成选区合成。

菜单位置 **SuperMrWang → Blend → Sky Replace**；批处理参数
`sky-file`/`threshold`(0..0.5)/`edge`/`feather`/`match-brightness`/
`save-mask-channel`。

回归：`tools/check_sky_replace.py`（13 条断言：分层、蒙版、合成像素、
亮度匹配、开关行为、报错路径；直方图期望值按 255·enc_srgb(v) 刻度
换算，跑在 gimp-console 的 python-fu-eval 里）。

### Python 插件：plugin/observe（观察层六种）

修图前先看清问题，比什么都省时间。六种观察层各一个菜单项，
`SuperMrWang → Observe`，**零参数、点了就建**：

| 菜单项 | 挂的滤镜 | 看什么 |
| --- | --- | --- |
| 黑白 | `gimp:desaturate`（**明度**） | 明暗结构、脏点、凹凸、色块的明度差 |
| 陡峭曲线 | 曲线 S 形，中间调斜率约 2.3× | 细微色斑、肤色不匀 |
| 波浪曲线 | 去色 + 锯齿曲线（四个峰谷） | 色带、断层、渐变里的台阶 |
| 饱和度 +100 | `gimp:hue-saturation` | 泛红、色偏、色块边界 |
| 阈值 | 去色 + 硬阶梯（切点 = 中位数） | 灰尘、痘印、小污点（最狠的一层） |
| 海报化（4 级） | `gimp:posterize` | 大块边界、渐变是否干净 |

生成的是**副本 + 图层滤镜**，不是改像素：参数随时能改（右键副本 → 图层 → 滤镜），
删掉整层就干净，原图层一个像素都没动。相当于 GIMP 3 里的调整图层——GIMP 没有
独立调整层，但图层滤镜是等价的，代价是得先复制一层。

三个实现上的坑，都写进注释和回归了：

1. **阈值不能写死 0.5**。偏暗的图（夜景、深色截图、欠曝照片）整张都在 0.5 以下，
   切出来是一块纯黑。按图层亮度**中位数**切（`gimp-drawable-histogram` 的第三个
   返回值，0…255 刻度），黑白天然各半。
2. **也别用 `gimp:threshold`**。它的 `low` / `high` 语义和界面上那两个滑块不一致：
   实测 `low == high`（想切得干脆）整片变黑，区间收窄切点还会飘。改成曲线做一个码
   宽的硬阶梯，切点就是中位数，行为确定。
3. **波浪和阈值先转灰**。直接对彩色图操作，等值线带上各通道的色相（紫绿蓝环），
   判断「这块肤色不匀」反而更难；三通道各自过切点还会让阈值图变成彩色。

回归：`tools/check_observe.py`（57 条，真 GIMP 内跑：六个过程都注册、只多一层副本、
插在原层正上方、原层像素逐位不变、每个滤镜挂得上、六种效果的方向对——去色后三通道
相等、陡峭曲线暗部更暗亮部更亮、波浪出现反向台阶、阈值只有两种值且暗图也切得开、
海报化每通道不超过 4 级）。

### Python 插件：plugin/luminosity-mask（明度蒙版七条）

把「哪块该亮、哪块该暗」从一个形容词变成可以随时载入的选区。一次生成七条通道，
双击任意一条就变成选区，之后曲线、色阶、锐化只作用在那一块：

| 通道 | 怎么算 | 挑出什么 |
| --- | --- | --- |
| 亮部 1（> 64） | 亮度 64–255 拉到 0–255 | 天空、受光面、白墙——所有不在阴影里的地方 |
| 亮部 2（> 128） | 128–255 | 明确的高光 |
| 亮部 3（> 192） | 192–255 | 云、灯、反光，只想动最亮那一小块时用 |
| 暗部 1（< 192） | 亮部 3 的反相 | 从阴影一直到中间调的大片区域 |
| 暗部 2（< 128） | 亮部 2 的反相 | 明确的暗部，做暗角常用 |
| 暗部 3（< 64） | 亮部 1 的反相 | 死黑，提暗部细节用这条 |
| 中间调（64–192） | 亮部 1 减亮部 3，再归一化 | 主体所在的层，两端渐隐 |

用法三步：选图层 → 点菜单项；双击通道 → 变选区；复制一层，在选区里调曲线。
要挂成图层蒙版就选中通道后右键图层（配合 `channel-to-mask`）。

三个实现上的取舍：

1. **通道，不是图层**。明度蒙版在 PS 里本来就是通道，「载入成选区」是它的用法；
   做成灰度图层每次还要多一步「图层转选区」。
2. **中间调是相减再归一化，不是相乘**。两条亮部相乘峰值只有 170 左右，蒙版灰蒙蒙；
   相减后峰值到 255、两端 0，当蒙版用时不用再补曲线。
3. **按 8 位生成**。蒙版是连续渐变，256 级在绝大多数叠加里看不出来；真遇到 16 位
   风光露台阶，可以改走 GEGL 色阶。

七条共用一次明度提取（复制 → 去色（明度加权）→ 读一遍 → 套七张映射表 → 删副本），
所以它们切自同一份亮度，不会因为算两遍而对不齐。重跑会先删掉上一批同名通道。

回归：`tools/check_luminosity_mask.py`（51 条：映射表逐值、通道数量与命名、渐变图上
的实际取值、暗部是亮部反相、中间调峰值归一化、重跑幂等、图层组被拒、无 alpha 图）。

### Python 插件：plugin/cutout（抠图 / 移除背景）

把主体从背景里抠出来，给图层加一张羽化蒙版，主体之外透明；也可以顺手垫一层纯色
（白底证件照、电商主图）或一张背景图。两条路按素材挑：

| 菜单项 | 怎么找主体 | 什么时候用 |
| --- | --- | --- |
| **抠图 / 移除背景（AI）** | 缩略图发给本机 ComfyUI 的 `RMBG` 节点（BiRefNet / RMBG-2.0），拿回来的 alpha 当蒙版 | 头发、毛绒、玻璃、绿幕、复杂背景。单张 4~6 秒 |
| **抠图 / 移除背景（本地）** | 从四条边撒多个种子点泛洪选背景，再反选；**已有选区时直接把选区当主体**，只做收边 | 纯色、渐变、影棚白底；或先粗框再自动收边。毫秒级 |

两条路的收尾是同一段代码：蒙版 → 收缩 `shrink` 像素 → 羽化 `feather` → 图层蒙版 +
`Cutout Mask` 通道 → 按需垫背景。**都是非破坏的**：原图层像素没动，蒙版随时能改，
删掉背景层就回到透明。

三个实现上的取舍（改代码前先看这几条）：

1. **AI 的 alpha 走「临时图层 + alpha」再 `select-item`**。alpha 是缩略图尺寸
   （长边 ≤ 2048），在 Python 里插值到 4000×6000 要十几秒；建一个同尺寸临时图层
   （RGB=白、A=alpha）插进图像，让 GIMP `gimp-layer-scale` 到画布尺寸再取 alpha，
   缩放是 C 做的，Python 只搬一次 `mw×mh×4` 字节。
2. **本地泛洪必须查覆盖率**。一个点都没选中时 GIMP 不报错，选区是空的，反选之后
   变成整张图——看起来像「主体被抠成了全白」。所以边框采样点命中率 < 35% 直接报错。
3. **背景层插 `pos + 1`**。`insert_layer` 的 position 从顶部数，插在照片自己的
   position 上是插到它**上面**，会把照片整块盖住。

实测（RTX 3070 Ti）：768×1024 卷发人像，RMBG-2.0 **4.6 秒**（含模型加载），
主体占 59.6%，发丝成缕保留、白衬衫边缘干净；`shrink=1` 收掉模型外扩的半像素，
浅底上看不到白边。本地版在 400×300 的「白底 + 红方块」上泛洪覆盖四边 100%、
主体内 255 / 四角 0，全程没有 Python 逐像素循环。

**前提**：AI 那条要有 ComfyUI + `ComfyUI-RMBG` 节点包 + 一份 BiRefNet 模型
（`models/RMBG/RMBG-2.0/`）。节点包不在时会直接说清装哪个仓库，而不是把
ComfyUI 的 `node_errors` 原样甩出来。本地那条什么都不需要。

回归：`tools/check_cutout.py`（70 条：种子点分布、偏移换算、alpha 残影闸、
cover 缩放、背景三选一、工作流参数、mock 端到端、节点缺失文案、源码约束）+
`tools/check_cutout_gimp.py`（30 条：蒙版真的落在像素上、选区路径、三种背景、
cover 之后的尺寸与偏移、失败路径不留蒙版/选区）。

### Python 插件：plugin/refine-mask（选择并遮住）

抠完、选完，边还是糊的——这个插件就是收尾那一步。菜单：`SuperMrWang → Mask →
选择并遮住（精修边缘）…`，输入是**当前选区**（没有选区就找 `Cutout Mask` /
`Refined Mask` 通道）。

| 滑杆 | 做什么 | 什么时候拉 |
| --- | --- | --- |
| **边缘检测半径** | 沿法线在 ±N px 内找画面真实边缘，把蒙版剖面推过去；勾「只吸附明显更强的边缘」时阈值 1.35× | AI 的边糊出去一两像素、旁边正好有强边 |
| **平滑** | 一遍盒式模糊，摊平锯齿和飞点 | 魔棒 / 快速选择出来的狗啃边 |
| **羽化** | 三次盒式逼近高斯 | 要贴到另一张图上，硬边像剪纸 |
| **对比度** | 软边往 0/255 推（S 曲线，斜率最高 5×） | 边缘一圈雾、AI 的 alpha 太软 |
| **移动边缘** | 整体加/减 alpha，正值外扩 | 整体差半像素（白边 / 吃掉轮廓） |
| **去色边** | 半透明像素沿 alpha 梯度向内取实心前景色 | 浅底白边、绿幕绿边 |

顺序是**吸附 → 平滑 → 羽化 → 对比度 → 移动边缘**。羽化放在对比度之前，是为了
让对比度还能把软边重新压硬；反过来做，羽化永远压在上面，那根滑杆等于没有。

输出四种：**图层蒙版**（非破坏）、**透明新图层**（蒙版烤进 alpha，去色边只在这条
生效）、**选区**、**通道 + 选区**。通道那条就是「画笔」的入口：在 `Refined Mask`
通道上用黑白画笔加减，再双击载入成选区——GIMP 自己的画笔比插件里搓一支靠谱。

三个不下心就翻车的实现细节：

1. **通道读出来是线性的**。`gimp-selection-save` 的通道用 `"Y u8"` 读到的是线性
   亮度，而选区值 / 图层 alpha 是 sRGB 编码的（实测：通道写 128 → 选区读回 188）。
   不转这一下，精修完中间调整体下压，50% 等值线跟着漂。转换只在读通道那一步做，
   写回走「临时图层 alpha」（直通 0..255），方向不会搞反。
2. **预览和应用必须是同一套代码**。两边都调 `refine_math.refine_mask`，只有分辨率
   不同（预览 520 长边、精修 1600 长边）。各写一套，早晚漂成「预览好看、确定后不一样」。
3. **吸附要把位移沿法线传播到 ±半径**。只改半透明带的话，剖面搬过去没有地方接住，
   边界会塌成一道硬跳变（实测：软边 17–22、真边缘 26，只改带内会塌在 22 处一刀切）。

工作尺寸默认 1600 长边：**GIMP 3 的 Python 里没有 numpy**，模糊只能手写前缀和，
1600×1067 一遍约 1~2 秒；0 表示原分辨率（10 秒起步）。实测 768×1024 的 RMBG
结果跑完六项 **1.03 秒**，半透明像素 40 万 → 1.3 万；预览拖滑杆重画 < 150 ms。

和 PS 的差距：没有画布上的那支减画笔，边缘检测也是「沿法线平移剖面」而不是
「按图重建 matte」。六根滑杆、实时预览、四种看片方式、四种输出都在。

回归：`tools/check_refine.py`（61 条，纯 Python：LUT、gamma 往返、盒式/高斯、
吸附、对比度/移动边缘、去色边公式、预览合成、性能闸）+ `tools/check_refine_gimp.py`
（51 条，真 GIMP：选区↔通道往返、缩放回画布、三种输出落点、去色边改真像素、
对话框与预览、run() 胶水）。

### Python 插件：plugin/puppet-warp（木偶变形 / 网格变形）

PS 的「木偶变形」在这里是：**在图层上点几个钉子、拖住钉子把内容拽过去**。
菜单：`SuperMrWang → Distort → 木偶变形（网格变形）…`。

- **点一下** = 放一根钉子（按住可以直接拖）；**拖钉子** = 拽画面；
  **右键钉子** = 删掉，或者选中后按 Delete。
- **影响半径**（长边百分比，默认 30%）决定一根钉子能拽多远。圈外是**严格的恒等**：
  不重采样，一个字节都不动。
- **三档解算**：
  - **刚性（MLS 相似）** — 只允许旋转 + 等比缩放，方角还是方的；纯摆位最好看。
  - **自由（MLS 仿射）** — 再放开剪切与拉伸，适合把东西拉长。
  - **ARAP** — 网格上解 As-Rigid-As-Possible，每一小片只允许刚体运动，
    **大角度弯折时局部不会被压扁**（最接近 PS 的手感）。这一档要 numpy，
    没装就不出现在下拉里；它也不用影响半径（靠弱锚定收口），选它时滑杆自动变灰。
- **输出**：覆盖当前图层 / 复制到新图层。**网格叠加** 可以看场被拽成什么样。
- 钉子也是参数 `pins="sx,sy,dx,dy; …"`，所以脚本能完整复现一次手动变形。

装 numpy 见上面「GIMP 自带的 Python 与 numpy」一节（`tools/install_gimp_numpy.py`）。
数学层是**双路**的：有 numpy 走向量化，没有就退回纯 Python，两条路的像素最多差 1 级
（回归里钉死了）。

#### MLS 那三档的三个坑

1. **MLS 是全局的，必须自己收口。** 用 1/d² 权重时远处解出来的仍是一个像样的仿射，
   整张图会跟着轻微旋转（实测四角漂 0.7 px）。所以每个像素再乘一个「到最近钉子」
   的 smoothstep 窗口，圈外严格恒等——不是「差不多」，是字节相等。
2. **只在栅格上解，不是每个像素。** 768×1024 逐像素解 8 个钉子要十几秒；改成在
   长边 140 个节点的栅格上解、重采样时对偏移量做双线性，误差 **< 0.02 px**。
   注意：MLS 的矩阵 `M` 本身随查询点变（权重里带 p），所以**用有限差分去测「相似
   模式保形」会误判**（实测差分出 0.48/0.93 的伪剪切），要测就直接看 `M`。
3. **整行跳过的判据必须是「严格为 0」，不能是「小于 0.5 px」。** 节点间距 7 px，
   用 0.5 px 当阈值会让节点之间那些 0.504 px 的位移整行漏掉——纯 Python 里看不出来，
   但和 numpy 那条逐像素判断的路一比，同一张图会差 2 万多个像素。

#### ARAP 那档的两个坑（都是「整张图平移」）

4. **钉子必须是硬约束（Dirichlet），不能是「大权重的软约束」。** 把约束以 1e4 的权重
   加进 Laplacian 看着更简单，但钉子的合力不为零，而 L 的零空间是常数向量，
   系统直接把整张网格抬成均匀平移——实测整幅画面平移到钉子位移，一个顶点都不形变。
   改成「钉子覆盖的 4 个顶点直接固定、其余顶点自由」才解得出调和形变。
5. **ARAP 只看边长，所以「整张网格刚体转过去」是零能量解。** 只有一个钉子时解会
   变成整个画面跟着旋转（实测中位位移 44 px）。加 0.06 的弱位置锚定（网格边权是 1）
   把远处按住：远处不动的时弹簧不受力，所以不干扰形变，只在被带着走时收口。

另外：ARAP 的 R 用 2×2 闭式解（`tr(R S) = cosθ(S00+S11) + sinθ(S01-S10)`，
直接 atan2），不批量 SVD；法方程只对**自由顶点**求逆并缓存（钉子原位不变 → 约束集
不变），所以拖钉子时每帧只是一次矩阵乘。预览用 34 节点的网格（~577 顶点），
应用用 48。

#### 实测（numpy 路径）

| 场景 | 纯 Python | numpy |
| --- | --- | --- |
| 140×106 节点的场解算 | 31 ms | **6 ms** |
| 768×1024 全流程（含读写缓冲区） | 0.35 s | **0.15 s** |
| 1600×2400 局部（半径 30%） | 2.4 s | **0.7 s** |
| 1600×2400 全图重采样 | 6.2 s | **1.2 s** |
| 预览 520 长边（拖钉子 70 ms 节流） | ~0.1 s | **58 ms** |
| ARAP 预分解 / 每帧 | — | 24 ms / ~20 ms |

和 PS 的差距：没有「深度」（钉子前后层级），也没有 Alt 拖拽旋转整根钉子的手柄——
要大角度旋转请直接转图层。图层组 / 文字层 / 矢量层会被明确拦下并说明要先栅格化。

回归：`tools/check_warp.py`（58 条：钉子插值、局部性、连续性、栅格误差、相似 vs 仿射
的矩阵性质、重采样、行级剪枝、字符串往返、**numpy 与纯 Python 的场/像素一致性**、
**ARAP 的钉子精确性 / 远处不动 / 保形性优于 MLS / 缓存**、960 万像素性能闸）+
`tools/check_warp_gimp.py`（57 条，真 GIMP：过程注册与参数表、像素真的搬走、圈外
逐像素字节相等、alpha、无 alpha 图层的写回格式、新图层输出、四种守卫、对话框与
预览、**ARAP 档真的改像素且不碰远处、切档时滑杆联动**、768×1024 全流程）。

### Python 插件：plugin/mesh-warp（自由变形 / 网格 + 把手）

PS 的「编辑 → 变换 → 变形」在这里是：**图层上盖一张贝塞尔网格，拖交点改形状，
选中交点后拖把手把网格线弯成曲线**。菜单：`SuperMrWang → Distort → 自由变形（网格 + 把手）…`。

和木偶变形的分工：那个是「拖内容」（钉子 → MLS/ARAP，只动钉子周围）；这个是
「给内容套一张自由曲面」（FFD，全局，带把手，能做出鼓包/收腰/翻边）。

- **拖网格交点** = 变形。**点一下交点选中它** → 冒出四个小圆点，那是两个把手的
  两端（对称，拖哪头都一样），按住拖就把网格线弯成曲线。
- **右键交点** = 那个点复位（选中后按 Delete 同效）；右侧另有「重置选中 / 全部重置」。
- **网格密度** 2×2 ～ 6×6 格（PS 默认 3×3）。虚线是原位网格，蓝线是变形后的网格。
- **Alt+点击画面 = 自己加一条分割线**（PS 的 Alt+拖网格线）。方向跟着最近的网格线，
  在点到的位置切开那一格——局部加密，不是整张网格一起变密。加过线后密度下拉变成
  `custom`，上限 12 条。
- **输出**：覆盖当前图层 / 复制到新图层。
- 网格也是参数：`mesh="cols,rows; u:…; v:…; x,y,ux,uy,vx,vy,auto; …"`（行优先，每点 6 或
  7 个数，写 2 个数就只给位置），脚本能完整复现。`u:` / `v:` 两段只有自己加过线时才有，
  记的是每条线在参数空间的位置；老串没有这两段，读回来就是等分。

#### 数学：双三次 Bezier 面片 + Newton 反解

一格是一张 **4×4 控制点**的双三次 Bezier 曲面片：四个角是交点，边上 8 个点是
「交点 ± 切向/3」（把手的三个单位正好是一个控制点），中间 4 个点由角点与 twist
项推出。变形反着做：对每个目标像素 p 用 Newton 解 `P(u,v) = p`，**源坐标取 uv 在
原位格上的位置**，再交给 `warp_rgba`（和木偶变形共用同一个重采样器）。

五个不下心就翻车的细节（加分割线的三条在站点页里）：

1. **源坐标是 uv 在原位格上的位置，不是曲面上的位置。** 曲面只回答「这个像素落在
   哪个 uv」。弄反了整幅画面平移一次，看着像「没对齐」。
2. **面片中间四个控制点要加 twist 项 `(P11-P10-P01+P00)/9`。** 只写「± 切向/3」，
   连恒等网格解出来每格中心都是偏的（曲面不再是平面）。
3. **把手必须自动限幅。** 拖走中间交点 80 px，右边那格只剩 26 px 的弦，却还带着
   66 px 的切向 → 控制多边形来回折 → 格子自交 → 反解出两个分支 → 画面撕一道。
   所以拖节点时按邻居重算切向，并限到相邻弦长以内（`mesh_warp.Mesh.auto_refresh`）。
4. **Newton 必须限步。** 曲面被压扁处局部导数很小，一步能跨掉一整格，落到隔壁
   导数大的地方再跳回来——实测在格界上无限来回震，最后差 12 px。单步限 0.75 格。
5. **换网格密度是「重新拟合」。** 变密几乎无损（3→6 格 1.6 px），变稀（5→2）形状
   会明显不同：2×2 只有一格，装不下复杂曲面。先定密度再拖。

#### 实测

| 场景 | 时间 |
| --- | --- |
| 768×1024 全流程（拖点 + 弯一处把手，含读写缓冲区） | **0.41 s** |
| 1600×2400 解场（140 节点栅格） | 153 ms |
| 1600×2400 全图重采样 | 1.16 s |
| 预览 480 长边（拖动 70 ms 节流） | ~95 ms |

网格变形是**全局**的：动一处，整幅画面都要重采样，所以预览比木偶变形（只重采样
一小块，520 长边 58 ms）慢——这是代价，不是没优化。

和 PS 的差距：没有「变形预设」（弧形 / 旗帜 / 鱼眼那排）、没有网格「拆分」；
把手是**对称**的（一个交点的切向被左右两格共用，跨格 C1 连续），做不出独立尖角。
参照物：Krita 的 Warp 变形用的是同一类双三次曲面网格，GIMP 自己的 Warp Transform
是推/拉画笔式的。

回归：`tools/check_mesh_warp.py`（46 条：恒等零场与字节相等、交点插值、Newton 反解、
把手解析值与对称性、自动把手防自交、两路场一致、字符串往返、换密度误差、像素搬迁、
768×1024 性能闸）+ `tools/check_mesh_warp_gimp.py`（52 条，真 GIMP：过程注册、
像素真的搬走、角点不动、alpha 与无 alpha 写回、新图层输出、守卫、对话框里拖点/拖把手/
换密度/复位、768×1024 全流程）。

### Python 插件：plugin/vanishing-point（消失点 / 透视平面）

PS 的「滤镜 → 消失点」在这里是：**拖一个四边形标出画面里一块有透视的平面**，
网格按世界坐标等距铺开、自然朝消失点收敛；然后能把整张图透视贴上去，
或者把这块画面拉正成矩形；还能把这块平面**折成一级级台阶**，同一张图沿台阶连续
铺上去。菜单：`SuperMrWang → Distort → 消失点（透视平面）…`。

和前两支变形的分工：木偶变形拖内容（MLS/ARAP）、自由变形套曲面（FFD），
这支是**先标出空间**，贴图和拉正都是这块平面的正反用。
四边形四角 ↔ 世界 (0,0)/(1,0)/(1,1)/(0,1)，解出单应 H，之后全在 H 上做。

- **拖一个四边形** = 建平面。拖四个角让它贴住真实的墙/地/桌面。
- **拖边中点的小三角** = 从这条边再长一块平面。方向可选「垂直于这块」（PS 的墙对墙）
  或「在同一平面里」（同一面墙接着铺）。新平面的深度线自动指向垂直消失点。
- **两种活**：「透视贴图」把整张图按四角铺上去，平面外一个字节不动；
  「拉正」把这块画面展开成新矩形图层（拍歪的海报/路牌这么救）。
- **右键平面** = 删掉。Delete 同效。
- **勾「折成台阶」** = 这块平面沿一条边折成 n 级台阶，整张图**沿台阶连续**折上去
  （不是每级各贴一份）。起边（远/近/右/左）、级数 1–24、踢面高、踏面深都是平面的
  比例；踏面深 0 = 自动 = 1/级数。脚本参数 `stairs="起边,级数,踢面高,踏面深,反向"`。
- 平面是参数：`planes="x0,y0,x1,y1,x2,y2,x3,y3 | …"`（四角按左上、右上、右下、左下，
  第一个生效，其余的留着回填对话框；只给 6 个数第四角补成平行四边形）。

三条非踩不可的（另外两条在站点页里）：

1. **单应必须先用 Hartley 归一化**。原始像素（上千量级）直接进 8×8，条件数到 1e8，
   纯 Python 高斯消元只到 1e-3，四边形一歪贴图就错位；归一化后残差回到 1e-13。
2. **网格线要按齐次分母 w 的符号断开**。世界坐标往外延伸时 w 过零，越过零点是
   「地平线之后」的像，连起来会画出一条横穿画面的假线。
3. **第三方向的消失点不是「另一组边的交点」**，是垂心关系：三个互相垂直方向的消失点
   构成三角形，主点（画面中心）是它的垂心。用边交点会得到同一个点，墙贴到墙自己身上。

还有一条延伸平面的：两个远角**不能取同一个 t**（都写成 `p + t·(V−p)` 会让新平面两条边
严格平行，u 方向消失点跑到 1e16 外，等于把透视扔了）。q0 落在 p0 射线上，q1 由
「在 p1 射线上」和「q0q1 过共享边方向的消失点」两条约束解出。

台阶是**真三维**，不是拼四边形：一块有透视的平面能反解整台针孔相机
（主点在画面中心 → `f² = −(Vu−O)·(Vv−O)` 唯一给出焦距；`b = K⁻¹·p` 归一化得旋转，
`n = r1×r2` 是法线，`eye = −Rᵀ·b3`）。z 的单位是两边边长的几何平均——`b` 本身就是
「长度 × 方向」。拼四边形那版第 6 级的边偏出十几个像素，因为「抬高一个边长」是往第三
个维度走一步，不是往下挪几个像素。两条新坑：四边两组都平行时解不出焦距，退回
`f = 1.5 × 长边`（状态行标 approximate），这时正中的踢面侧对相机会退化成一条线，
必须丢掉否则是白缝 + 单应奇异；源图第 0 行落在**最近**那一级上，图反了要先把源图
上下翻一下。

实测：768×1024 贴图 127 ms、拉正 71 ms；1600×2400 贴图 635 ms、拉正 356 ms；
预览 560 长边约 75 ms。纯 Python 慢约 4 倍（numpy 缺失时兜底）。
台阶 1600×2400 / 16 面片 1.54 s，预览 172 ms/帧。

和 PS 的差距：**没有 PS 最常用的那个「在平面上用图章/画笔、笔画自动贴合透视」**——
那要写 GIMP 的绘图工具类，是另一件事（台阶上同理）；也没有导出 3D、平面之间不自动
吸附共享消失点（靠拖角对齐）。台阶只做**单段**折（n 级同向），PS 可以在一个平面里
画好几段折线、中途拐弯。参照物：Krita 的透视辅助线是同类东西（但只画线不贴图），这套算法
的教科书名字是 homography-based image transfer。

回归：`tools/check_perspective.py`（50 条：单应与逆单应残差、直线保直、真 3D 场景反推
三个消失点（40 个随机相机，误差应为 0）、垂心检验、网格过角点与无假线、贴图内部正确/
外部逐字节不动/alpha 混合、拉正往返与竖直边、延伸平面共用边与透视一致、两路像素一致、
序列化与退化四边形）+ `tools/check_scene3d.py`（41 条：由平面反解相机的焦距精确复现、
三维投影误差 < 1e-8、矩形退回近似、台阶面片数/凸性/交替、接缝 < 1e-9、踏面消失点不变、
踢面立柱收敛到第三消失点、贴图取色（含自遮挡）、面外像素为 0、两路一致、性能、参数串
往返）+ `tools/check_perspective_gimp.py`（61 条，真 GIMP：过程注册、贴图真写回、
无 alpha 图层、新图层输出、拉正尺寸、台阶参数串与真改像素、守卫、对话框建平面/拖角/
延伸/新建删除、config 往返）。

### Python 插件：plugin/ai-*（AI 磨皮，三支「预修版」）

原来的三支磨皮（高低频 / 双曲线 / 中性灰）是「干净结构 + 你自己修」。这三支
一行都不会改它们，而是各开一个新入口：**结构搭好的同时把活也干了一部分**，
打开文件就是一张有工作痕迹的图，剩下的是收尾。

| 菜单项 | 打开时已经做完的 | 你接着做什么 |
| --- | --- | --- |
| **高低频磨皮（AI 预修）** | 两层内容是一张修过一遍的参考图（合成结果 = 参考图），色块已平、痘印已淡 | 高频层点掉残留细节，低频层铺色 |
| **双曲线磨皮（AI 预修）** | 提亮 / 压暗蒙版已按差值预涂 70%，浓度按每像素自己的亮度反算 | 补白、涂黑收尾 |
| **中性灰磨皮（AI 预修）** | 灰层不是平的 128，而是按柔光公式反解出的 128±偏移 | 5–15% 白 / 黑画笔收尾，`#808080` 擦回 |

参考图两条路，参数 `source` 选：

- **AI 参考**：整层交给 ComfyUI 做一次整图低重绘（`denoise` 默认 0.35，走
  `VAEEncode → KSampler` 的 img2img 工作流，不是 inpaint——inpaint 会把整个
  latent 清空，出来的是另一张脸）。它认得「这是皮肤」：痘印、泛红、色块被推平，
  五官与轮廓留住。提示词可以直接写中文（`prompt_tools` 词表），留空用内置的
  `clean natural skin`。
- **本地参考**：整层降采样再放大当低通，毫秒级、零依赖；本质是「自动双曲线」。

规则：

1. 连不上 ComfyUI 时先按「AI 环境」里选好的目录**自动拉起服务**；还是不行就**退回本地参考**，并在提示里说清原因——不静默失败，
   也不弹一堆报错。
2. **有选区时只在选区内预修**，选区外逐像素等于原图（参考图整层混合，选区外
   alpha=0）。
3. 预修不是 100%：双曲线与中性灰默认补 70%，剩下的留给画笔。设 0% 等于原版
   插件（全黑蒙版 / 平灰层）。
4. 参数里那个 `radius` 在 AI 模式下不影响参考图（AI 自己按底模选 512 / 1024），
   只在 `local` 模式下当低通截止半径。

回归（两套，都不需要显卡）：

```bash
python tools/check_retouch_ai.py          # 87 条：数学 / 柔光反解 / img2img 工作流 / mock 端到端 / 源码约束
python tools/check_retouch.py             # 真 GIMP，76 条：三支磨皮的结构、滤镜、恒等、画笔、无 alpha 图
python tools/check_observe.py             # 真 GIMP，57 条：六种观察层的结构、滤镜、效果方向、暗图
python tools/check_luminosity_mask.py     # 真 GIMP，51 条：七条明度通道的映射表、内容、幂等
# 真 GIMP，67 条：结构、预涂蒙版、灰层、选区、AI 退回
gimp-console -b "exec(open('tools/check_retouch_ai_gimp.py').read())"
```

### ComfyUI 起不来 / AI 那一路没反应

三个症状，一个根因链条，从下往上查：

| 现象 | 真正的原因 | 怎么办 |
| --- | --- | --- |
| 插件跑完提示「ComfyUI was not reachable」，出来的是本地参考 | 8188 上没人监听 | 先起 ComfyUI，等窗口里出现 `To see the GUI go to` 再跑插件 |
| 双击 `start-comfyui.bat`，窗口一闪就关 | 显卡没被驱动认到：torch 在 import 阶段就抛 `RuntimeError: No CUDA GPUs are available`，ComfyUI 走不到「起服务」那一步 | 新版启动脚本探测不到显卡会自动加 `--cpu`；慢一些，但参考图照样能生成 |
| 上面那条报错对应的设备管理器里，显卡标着 **Code 43** | Windows 把这个设备停了（`CM_PROB_FAILED_POST_START`），重启也没用 | 重装 NVIDIA 驱动（官网 Game Ready，安装时选「自定义 → 执行清洁安装」）。这是系统层问题，插件改不了 |

一行自查：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8188/system_stats   # 200 才算活
```

插件不会静默失败：`source=ai` 但连不上时退回本地参考，并把「下一步做什么」
写进状态消息（服务没开 / 一闪就关多半是 Code 43 / 没装过），不是只丢一个
`URLError`。

**启动脚本里一个中文都别放。** cmd 在 `chcp 65001` 下是按字节偏移回读批处理
文件的，中文行会让偏移漂移：实测 `for /f` 之后的中文行会被截断成
「`'xx'` 不是内部或外部命令」，`goto` 标签之后的行会被整个吞掉，最后表现成
「脚本跑到一半没了」。所以 `start-comfyui.bat` 里全 ASCII，中文提示写在旁边
的 txt / md 里，用 `type` 原样打出来——`type` 只搬字节，不解析。

取探测结果也别用 `for /f`：实测同一个 `python -c` 手动跑返回 `1`，
`for /f` 却什么都没抓到，于是显卡好好的也被判成「没有显卡」。改成
python 的退出码 + `if errorlevel 1 set EXTRA=--cpu`，稳定得多。

### Python 插件：plugin/ai-inpaint（AI 局部重绘）

**选区 + 一句提示词 → 本机 ComfyUI 重画 → 贴回成带蒙版的新图层**。框住想改的
地方，跑 **SuperMrWang → AI → AI Inpaint…**，选区内换成 AI 重绘的像素，边界靠
羽化过的选区蒙版过渡，原图那层不动。

菜单下有三个入口，前两个是同一个实现：

| 菜单项 | 问你的东西 | 什么时候用 |
| --- | --- | --- |
| **AI Inpaint…** | 画什么（`prompt`）+ 画什么主体（`preset` 下拉）+ 不要什么（`negative`） | 日常。三个框，其余参数用默认值 |
| **AI Inpaint (Advanced)…** | 上面三项 + `server` / `checkpoint`（下拉）/ `steps` / `cfg` / `seed` / `denoise` / `grow` / `grow-mask-by` / `feather` / `timeout` / `keep-mask` / `scale` | 要复现同一张结果、要挑底模、要调步数或降 `denoise` 保结构 |
| **AI Environment…** | 不问你，直接报状态（连上没、版本、有哪些底模）+ 手选目录 / 启动 / 停止 | 第一次装 ComfyUI、装在别的盘、服务没起、想换模型 |

为什么拆两个：GIMP 的参数对话框是一次性把参数全铺开的，没法折叠。十几个采样
参数一摆，真正要填的那个框就被埋掉了——用起来像「只能重绘、不能指定画什么」。
简版只留「画什么 / 画哪个主体 / 不要什么」。

**注册顺序有个坑**：`add_menu_path()` 必须写在 `set_menu_label()` 之后。反过来
写，GIMP 会静默把菜单路径丢掉——PDB 里查得到过程、插件看着像装好了，但菜单里
什么都没有（`pluginrc` 里那条 `menu-path` 数会写成 0）。拆简版/高级版那次就是
把顺序写反了，AI 菜单整轮不见。`tools/check_ai_inpaint.py` 现在盯着这条。

需要的东西：

1. 本机跑着 ComfyUI（默认 `http://127.0.0.1:8188`，可用环境变量
   `LB_COMFY_URL` 或对话框里的「ComfyUI address」盖掉）；
2. `models/checkpoints/` 里有一份 SD1.5 底模。自动挑底模时会**优先挑名字里不带
   `inpaint` 的**——9 通道的 inpaint 专用模型在 `VAEEncodeForInpaint` 这条路上
   不认提示词，只会把蒙版区抹平。

流程（`ai_inpaint()` 是模块级函数，`tools/check_ai_inpaint_gimp.py` 直接调它做回归）：

1. 选区外扩 `grow` 像素，外接框再带一圈 `CONTEXT_PAD`（32px）上下文；
2. 裁切框宽高对齐到 8 的整数倍，并按画布夹紧；
3. **画布补到长宽比 ≤ 2:1**（`ai_client.plan_canvas_rect()`）：超宽条先往画面里
   长高（拿真实像素当上下文），画面到边了才复制边缘像素补边，补出来的那圈贴回
   时被蒙版挡住；
4. 从**可见合成**（`Gimp.Layer.new_from_visible`）读这块像素——图层比画布小、
   带偏移时，界外取到的是下面的图层，不是黑色；
5. 选区存成蒙版 PNG 交给 ComfyUI，等 `/history` 报完成；
6. 结果 PNG 读回成图层，插在原图层正上方、偏移对回裁切框原点；羽化后的选区
   存成 `AI Mask` 通道，同时用作图层蒙版（`keep-mask` 关掉就只留蒙版不收通道）。

高级版参数：`prompt` / `preset` / `negative` / `server` / `checkpoint` /
`steps`(25) / `cfg`(7.5) / `seed`(-1=每次随机) / `denoise`(1.0) / `grow`(8) /
`grow-mask-by`(8) / `feather`(4) / `timeout`(600s) / `keep-mask` / `scale`(0=按底模)。

### 提示词怎么写（这是最影响效果的一件事）

**`prompt` 默认是空的**——不能预填一句通用文案，否则点确定的人会得到一块跟画面
毫无关系的色块。填的时候记住两件事：

1. **写「这里应该是什么」，不要写「把什么去掉」。** 想去掉一个瓶子，写
   `empty wooden table, wood grain`，别写 `remove the bottle` —— 模型没有
   「删除」这个概念，它只会照着你的字面画。要删的东西放进 `negative`
   （`bottle, glass`），它才是「别出现」的那一栏。
2. **中文可以直接写。** SD 的文本编码器是 OpenCLIP，词表里没有汉字，中文送进去
   等于**随机重绘**；所以插件在中间加了一层 `plugin/_shared/prompt_tools.py`：
   450 条常用词的中英对照，按最长匹配换掉（`画一只小猫` → `small kitten`，
   `一只小猫坐在木质桌子上` → `small kitten sitting on wooden table`）。换不掉
   的词会**点名报错**（`这些词还没收进中文词表：赛博朋克`），不会把半截中文静默
   送下去。日文/韩文不在表里，仍然会被拦。
3. **懒得写就选 `preset`。** 「画什么主体」是一个真正的下拉框：小猫 / 小狗 /
   人 / 花 / 树 / 咖啡 / 食物 / 汽车。选了「小猫」就相当于提示词前面自动带上
   `a small cat, fluffy fur, detailed eyes`，你在 `prompt` 里补细节就行
   （`戴着一顶帽子` → `a small cat, fluffy fur, detailed eyes, wearing hat`）。
   只选主体、`prompt` 留空也能跑。

以前的默认值是一句 `clean background, seamless, photorealistic, sharp focus`，
结果点开菜单直接点确定的人（很正常的行为）会得到一块跟画面毫无关系的干净色块，
2026-11-20 有用户原话反馈「它就给我随便重绘了一个东西，跟图片完全不搭」。所以
默认值改成空，宁可报错也不给默认内容。

**提示词写对了之后，影响效果的还是选区与参数**：选区只框住目标、`grow` 给足周边
上下文（8–16）、`denoise` 想保留原结构就降到 0.6–0.8。SD 系列在小面积补材质上
可靠，大面积重画或要具体物体仍会跑偏——那是模型的能力边界，不是提示词没写对。

**四个坑**（都写进了代码注释，改的时候别绕回去）：

- **蒙版方向**：ComfyUI 的 `LoadImage` 用 **alpha 倒推** mask（`mask = 1 - alpha`），
  所以「白＝要重绘」必须写成**透明**。直接送一张白底黑区的灰度图，得到的是全 0
  的 mask，跑完像素纹丝不动（2026-11-20 踩过）。`ai_client.mask_png()` 负责这件事。
- **对齐到 8**：VAE 是 8× 下采样，裁切框宽高不是 8 的倍数时 ComfyUI 会截断，
  回来的图比请求的小一圈，贴回去整体错位。`ai_client.align_rect()` 负责这件事。
- **别用 inpaint 专用底模**：`InpaintModelConditioning` 在 ComfyUI v0.46 上不生效
  （开关 `noise_mask` 都不改像素），`VAEEncode` 只吐糊团；工作流走普通 SD1.5 +
  `VAEEncodeForInpaint`。
- **画幅比例别超过 2:1**：SD 只在自己训练过的比例附近画得对。眼睛那样的一条
  1024×400（2.56:1）送进 SDXL，整块会被画成「平涂海报 + 重复图形」——2026-11-23
  用户报的「输入 `sunglasses` 却给我一块绿色路牌」（绿底、白色箭头、两辆车）就是
  这个，**不是提示词没生效**（ComfyUI 存的 PNG 元数据里 `text` 确实是 `sunglasses`）。
  同一句提示、同样的图，把画布补成 1024×512 就正常戴上墨镜了。所以
  `plan_canvas_rect()` 一律先把画布补到 ≤2:1 再送。默认的 `negative` 里也加了
  `illustration, cartoon, flat graphic, poster`，压一压往矢量海报跑的趋势。

**选区别框太大。** 蒙版里画多少，模型就重画多少：框满一整块眼睛区域，模型就会
把墨镜按整块的大小画出来（结果是一副「巨大墨镜」），因为它没有「戴在脸上」这个
尺度概念。想把眼镜戴上，选区贴着眼镜该在的位置框一条，上下别带上额头和脸颊。

**一键装环境**（Windows，`tools/setup-ai.bat` 双击即可）：

```bat
tools\setup-ai.bat                      :: 装到 %USERPROFILE%\SuperMrWang-AI，默认 SDXL
tools\setup-ai.bat --model sd15         :: 体积小一半、速度快约 3 倍
tools\setup-ai.bat --dir D://lb-ai       :: 换目录（需要 ~16 GB 空闲）
tools\setup-ai.bat --cpu                :: 没有 N 卡：能跑，一张 512² 要 1~3 分钟
tools\setup-ai.bat --verify             :: 只体检已装好的环境
```

**装了插件的人不用去找这个 bat**：菜单里 **SuperMrWang → AI → AI Environment…**
就是它的图形入口（`lb-plugin-ai-env`，零参数，不改图）。对话框开出来先做体检，
按钮分两排：

| 按钮 | 干什么 |
| --- | --- |
| **Start** | 直接 `python main.py --listen 127.0.0.1 --port 8188` 起服务——**后台进程，不弹控制台**，输出写进 `comfyui.log`；找不到解释器时才退回 `start-comfyui.bat` |
| **Stop** | 停掉**插件自己起的**那个进程（`taskkill /T /F`）；别人起的服务不会被误杀 |
| **Choose folder…** | **手动指定 ComfyUI 装在哪**（选含 `main.py` 的目录，或包着 `ComfyUI/` 的外层目录），存进配置文件，下回不用再选 |
| **Choose python…** | 目录里找不到解释器（或想指定某个 venv）时，手动指一个 `python.exe` |
| **One-click install…** | 跑 `setup-ai.bat`（首次约 10 GB，一个窗口里跑完，跑完回来点 Start） |
| **Model folder** | 打开 `<安装目录>\ComfyUI\models\checkpoints`，往里丢模型最省事 |
| **Refresh** | 重新探一次：连上了没、版本、有哪些底模，以及**日志最后几行** |

下面还有一个勾选框 **「ComfyUI 没在运行时自动启动」**（默认开）。勾着的话，
每次跑 AI 操作前插件会先探一下 `/system_stats`，连不上就按你选的目录**自己把
服务拉起来、等它就绪**，再继续重绘——不用先手动开一个服务。启动期间 GIMP 的
进度条会转，界面不假死；超过 180 秒没起来就把 `comfyui.log` 的尾巴端给你。

**配置存在哪、长什么样**（`comfy_launcher.config_path()`）：

| 平台 | 路径 |
| --- | --- |
| Windows | `%APPDATA%\SuperMrWang\comfyui.json` |
| Linux / macOS | `~/.config/SuperMrWang/comfyui.json` |

```json
{
  "auto_start": true,
  "extra_args": "",
  "home": "D:\\ComfyUI",
  "python": "D:\\ComfyUI\\py312\\python.exe",
  "url": ""
}
```

`home` 是目录、`python` 留空就自动找（`py312/`、`python_embeded/`、`venv/Scripts/`、
`.venv/`、外层目录的 `py3xx/` 依次试）；`url` 留空 = `http://127.0.0.1:8188`，
也可以继续用环境变量 `LB_COMFY_URL` / `LB_COMFY_HOME` 盖掉。想手工改配置也行，
插件下次读的就是这个文件（`LB_COMFY_CONFIG` 可以把整个路径换掉）。

**自动启动只用「你手选过的目录」，不会去猜。** 猜出来的目录只出现在状态文字里
（「这儿好像有一个，点 Choose folder 确认一下」）。原因很实在：猜错一次就是
「拿另一个 Python 去起别人的 ComfyUI」，报错全是 `ModuleNotFoundError`，比不起
更难查——2026-11-23 写这条时回归里就踩过一次。目录一个字都没选过时，
`ensure_running()` 直接告诉你「去 AI Environment 里选」，然后 AI 那一路退回本地
参考（磨皮）或报错（重绘）。

没有显卡、`torch.cuda.is_available()` 为假时，ComfyUI 会在 import 阶段就退出。
自动启动会看日志：退出且提到 CUDA → 用 `--cpu` 再来一次（慢，但出得来图）。
`stop()` 之后 pid 也会从 `comfyui-run.json` 里清掉，不会拿着一个死 pid 乱打。

上面那一块是**实时状态**：连不上会写清是「服务没开」还是「压根没装」，模型清单
会按家族和「不认提示词」标出来（`checkpoint_note()`）。做这个入口的原因是：
拿到单支插件包的人只有一个 zip，既不知道仓库在哪、也不会去开终端翻 `tools/`。

安装器跟着插件走：`install-plugin.sh` 会把 `tools/setup-ai.bat` + `setup_ai.py`
复制成 `plug-ins/ai-setup/`，插件按 `<插件目录>/ai-setup/`、`../ai-setup/`、
`../../tools/` 依次找（`find_installer()`）。没有 Windows 桌面时
（`os.startfile` 不可用）只报路径，不假装成功。

它自己下载一份嵌入式 Python（不碰系统环境），再装 torch cu128、ComfyUI 和一份
底模，最后起服务自检一遍。**为什么不是一个 zip**：torch 的 CUDA 轮子 2.5 GB、
底模 2~7 GB，打进包里既过不了分发许可，也没人愿意下一个 10 GB 的安装包。
普通 PyPI 包走清华源（`LB_PYPI_MIRROR` 可改），CUDA 轮子只能走官方源。

三个坑写进了脚本，改的时候别绕回去：

- `torch` / `torchvision` / `torchaudio` 要从 `requirements.txt` 里**整行**剔掉，
  否则会按 requirements 的版本号重装成 CPU 版。但只能剔这三行——用
  `grep -v "^torch"` 会把 `torchsde` 一起删掉，缺依赖直接起不来。
- 嵌入式 Python 要先改 `python312._pth`（加 `Lib\site-packages` 和 `import site`），
  否则 pip 装完 import 不到任何东西。
- `.bat` 里不能有嵌套 `if (...)` 块配 `>=`：cmd 会把 `>` 当重定向，报
  `... was unexpected at this time`。全用 `goto`。

**换模型**：把 `.safetensors` 丢进 `<安装目录>\ComfyUI\models\checkpoints\`，
重启服务即可。插件按文件名认家族：带 `xl` / `sdxl` 的按 **1024** 长边送图，其余
按 **512**；裁切框先缩放到这个尺寸、回来再缩回原尺寸贴（`detect_family()` /
`work_scale()`，倍率限制在 0.25×–4×）。所以「换模型」不需要改代码，只需要一份
文件。

**多个模型时怎么选**（高级版的 `checkpoint` 是下拉，不是手打文件名）：

1. **自动（推荐）** —— 默认值 `auto`。按名字排序挑第一个**不带 `inpaint`** 的
   模型：9 通道 inpaint 专用模型在 `VAEEncodeForInpaint` 上不认提示词，只会把
   蒙版区抹平，所以自动挑会让开它们（`first_checkpoint()`）。
2. **点名要哪个** —— 下拉里的候选项是**当场问 ComfyUI 要的**
   （`/object_info/CheckpointLoaderSimple`），每项后面标着家族和舒适尺寸：
   `juggernautXL_v9.safetensors（SDXL · 1024）`、
   `dreamshaper_8.safetensors（SD1.5 · 512）`、
   `sd-v1-5-inpainting.ckpt（inpaint 专用 · 不认提示词，别选）`。
   选谁就用谁，`family_target()` 据此决定送 1024 还是 512。
3. **不想每次选** —— 环境变量 `LB_COMFY_CKPT` 写完整文件名，自动挑就固定用它；
   名字对不上时安静退回自动挑，不报错。

下拉是在**注册菜单时**建的，所以有个前提：GIMP 启动那一刻 ComfyUI 得在跑。
没跑（或 1.5 秒没回）就退回老文本框，让用户手写文件名——**绝不让连不上服务
这件事拖慢 GIMP 启动**。换个模型/刚开了服务，重开 GIMP 即可刷新列表。

**为什么不把「自动」做得更聪明**（比如按显存挑模型）：ComfyUI 的 `/object_info`
不给模型大小和显存需求，SDXL 也可能只有 2 GB 的特化版；按名字猜比让用户选更
容易错，所以只做「跳过 inpaint 专用」这一条确定无害的规则。

实测（RTX 3070 Ti 8 GB，同一张图、同一个蒙版）：

| 底模 | 体积 | 送图尺寸 | 单次耗时 | 表现 |
|---|---|---|---|---|
| SD1.5 fp16 | 2.1 GB | 512 | 5.7 s | 小面积补背景稳；大面积会糊成色块 |
| SDXL base 1.0 | 6.9 GB | 856×1024 | 17.5 s | 能画出木纹/陶盆这类材质，颜色更听提示词；但**上下文一致性**仍会崩（见下） |

**「换大模型」能解决的和你以为的不一样。** 实拍图上去掉一只苹果，SD1.5 给的是
一团糊，SDXL 给的是一块**纹理清楚、方向不对**的木头——清晰度上去了，但它不理解
桌面的透视和光照方向，边缘还会留一圈可见的圆。这是 SD 系列 inpaint 的固有短板
（蒙版区被当作独立小图重绘），不是链路问题。真要「看不出来」，得往三个方向走：
蒙版画准 + `grow` 给足上下文、`denoise` 降到 0.6~0.8 保留原结构、或者换
Flux.1-Fill 这类**专门为 inpaint 训练**的模型（12B，8 GB 显存要走 GGUF Q4 +
分块 offload，单张 1~3 分钟；注意它的许可**禁止商用**）。


回归（两套，都不需要显卡）：

```bash
# 116 条：PNG 编解码、蒙版方向、对齐、工作流、mock 端到端、中文词表与预设
python tools/check_ai_inpaint.py
"D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval \
    -b "exec(open(r'<repo>/tools/check_ai_inpaint_gimp.py', encoding='utf-8').read())" --quit
# 43 条：真 GIMP 里的选区→蒙版→贴回、中文/预设提示词、简版与高级版的参数装配
```

`tools/mock_comfy.py` 也能单独起一个假服务（不带参数就监听 8188），想在没有模型
的机器上点一遍菜单时用：

```bash
python tools/mock_comfy.py --port 8188        # 重绘结果 = 蒙版区填成固定蓝色
```

**AI Inpaint 不在 47 个算子里**：它是 Python 插件，不编进 GEGL 模块，也不需要
`./build.sh`。`./install-plugin.sh` 会把 `plugin/ai-inpaint/` 和它依赖的
`plugin/_shared/` 一起装到 GIMP 用户插件目录。

站点上现在有它自己的页面与单独下载包（`docs/plugins/ai-inpaint.html`、
`docs/download/gegl-color-ops-plugin-ai-inpaint.zip`），包里额外带一个
`ai-setup/`：`setup-ai.bat` + `setup_ai.py`。没有 ComfyUI 的人下这一个包就有
插件和安装器，不用回仓库翻。整包里同样带 `plugins/ai-setup/`。这条规格靠
`PLUGIN_SPECS` 的 `setup=True` 打开（`site_build._zip_add_setup()` 负责塞文件）。

## 命名与代码风格约定

改代码时请沿用下面几条，`python tools/normalize_headers.py --write` 可自动重排文件头。

**1. 名字三件套**

```
name             lb:<kebab-case>          GEGL 唯一 id，也是 GIMP 存进 XCF 的字符串，别乱改
gimp:menu-label  <短名>                    菜单里显示的字，尽量 ≤ 16 字符
title            <短名>                    搜索动作 / fx 名用；需要更完整的说法就换词，不加括号
```

菜单名规则：名词短语、首字母大写、**不加括号、不加省略号**、不用 "Plus/Hyper" 这类无信息词。
`Channel Mixer Plus`、`Mask by Color` 属固定叫法，保留。模型/来源（HSL、RGB、RAW 编辑器等）
一律写进 `description`，避免菜单与选项面板被括号撑宽。

**不得与 GIMP / GEGL 自带算子重名**。GIMP 3 自带 `Exposure`（`gegl:exposure`）、
`Vibrance`（`gegl:vibrance`）、`Make Gray`（`gegl:gray`），所以本工程的三个算子改名为
`Exposure EV`、`Black & White`、`Natural Saturation`。新增算子前先跑一次
`gegl --list-all` + `gegl --info` 查标题，或用下面的片段一次列出所有重名：

```bash
for op in $(gegl --list-all); do gegl --info "$op"; done | grep '^title ' | sort | uniq -d
```

**2. `GEGL_OP_NAME` 必须带 `lb_` 前缀**

它决定注册的 GType 名，GEGL 用裸字符串注册，不带命名空间会与核心算子撞名——
例如写成 `exposure` 会撞上 GEGL 自带的 `gegl:exposure`，后果是该算子**静默加载失败**
（`gegl --info` 查不到，但编译、安装全都没报错）。所以统一 `lb_<snake_case>`。

**3. 文件头注释盒（78 列，中英双语）**

```c
/* ===========================================================================
 * SuperMrWang · GEGL 算子 / GEGL Operation
 * ---------------------------------------------------------------------------
 * id         lb:xxx
 * menu       菜单名
 * purpose    一句话说清做什么
 *            One line on what the op does.
 * algorithm  核心思路，可续行
 *            Core idea, wrapped in English.
 * type       GeglOperationPointFilter（逐像素 / per-pixel）
 * reference  算法来源（可选，没有就整段省略）
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 *            GPL-3.0-or-later, see LICENSE at the project root
 * ======================================================================== */
```

字段固定 6 个（`id` / `menu` / `purpose` / `algorithm` / `type` / `reference` / `license`），
每段**先中文、后英文**，工具按 78 列自动折行（CJK 记 2 列，URL 不拆）。
`tools/normalize_headers.py` 里的 `OPS` 表就是唯一数据源，改元数据只改那一处。

**4. include 顺序固定**

```c
#include "config.h"
#include <glib/gi18n-lib.h>
#include <math.h>
#include <string.h>   /* 仅在用到 memset/memcpy 时 */
```

`#ifdef GEGL_PROPERTIES` 之后空一行；行尾一律 LF。

**5. 代码内分隔线统一一种**

```c
/* ---- 段名 ------------------------------------------------------------- */
```

原来混用 `// ====`、`/* ---- */`、`// 注释` 的写法已统一成上面这种，整行注释也一律 `/* */`。
分隔线同样双语：`/* ---- 主处理 / main processing ---- */`。

**7. 色彩域：逐像素运算一律用感知（伽马）格式**

```c
/* 输入/输出钉成感知格式，公式拿到的才是伽马值
 * Pin the pads to the perceptual format so the maths sees gamma values */
static const Babl *
perceptual_format (GeglOperation *op)
{
  return babl_format_with_space ("R~G~B~A float",
                                 gegl_operation_get_source_space (op, "input"));
}
```

babl 的 `RGBA float` 是**线性光**；按 8bit sRGB 伽马域逆向的公式若声明它，
babl 会把伽马值转成线性值再喂进来，结果整体偏移（黑白纯红 red=40 应为 102，
实测 170；曝光 +1EV 只顶 0.45 档）。曾把 8 个算子钉成线性光，2026-11-10 全部
改回感知格式（`R~G~B~A float`，随图像色彩空间走，`hue-saturation` 一直是对的）。
例外：`vibrance-hyper` 内部自己做线性 RGB→XYZ，天然需要线性光，
保留 `RGBA float`；`lab-levels` 则直接在 babl `CIE Lab alpha float`
（D50 白点，与 GIMP 原生 Lab 工具一致）上逐通道工作，也不属感知/线性之争。

**8. 所有注释中英双语**

```c
/* 中文说明 / English note */          // 一行放得下就单行
/* 中文说明
 * English note. */                  // 否则中文在上、英文在下
gfloat a = 1.0f;   /* 中文 / English */   // 行尾注释同理
```

维护用 `tools/i18n_blocks.py`（按「注释块」定位，不碰代码）：

```bash
python tools/i18n_blocks.py todo                     # 找出缺中文或缺英文的块
python tools/i18n_blocks.py scan <算子名>             # 列出块号 / 行号 / 原文
python tools/i18n_blocks.py apply <算子名> <map.json> # 按块号替换（写盘前校验代码字符未变）
python tools/i18n_blocks.py check                    # 与 git HEAD 比对代码本体是否零改动
```

映射文件里 `{"zh": "...", "en": "..."}` 由工具自动排版，`{"div": "名称"}` 生成分隔线，
`{"tail": "..."}` 只改行尾注释，`null` 表示删除该块（用于合并重复的中英两块）。

## GIMP 自带的 Python 与 numpy

GIMP 3 for Windows 自带一个**精简、无 pip** 的 Python（当前 3.14.10，MSYS2/MinGW
构建），插件跑在里面。想在插件里用 numpy，不能 `pip install`，也不能拿系统 Python
装——两边互相看不见。

```bash
python tools/install_gimp_numpy.py           # 自动找 GIMP 与 MSYS2
python tools/install_gimp_numpy.py --check   # 只验证
```

它会做四件事：从 MSYS2 的 `ucrt64` 拿 `mingw-w64-ucrt-x86_64-python-numpy`
（必要时 `pacman -S`），覆盖复制进 GIMP 的 `site-packages`，把
`.cp314-mingw_x86_64_ucrt_gnu.pyd` **改名成 `..._ucrt_llvm.pyd`**，再把
`libopenblas / libgfortran / libgcc_s_seh / libgomp / libstdc++ / libquadmath`
补进 `GIMP/bin`（只补缺的，不覆盖）。

**为什么必须用 MinGW 构建的那一份**（两个坑，都很安静）：

1. GIMP 的 `sysconfig.get_config_var('EXT_SUFFIX')` 是
   `.cp314-mingw_x86_64_ucrt_llvm.pyd`，PyPI 官方 wheel 是 `.cp314-win_amd64.pyd`。
   不解压改名 → `ModuleNotFoundError`；改名 → 它导入表里要 `python314.dll`，
   GIMP 只有 `libpython3.14.dll`，于是 `DLL load failed`。
2. 有人会想「拷一份 `libpython3.14.dll` 改名成 `python314.dll` 不就行了」——不行。
   加载能过，但 `PyInit` 是在**另一个 CPython 实例**里创建的，返回时报
   `initialization of _multiarray_umath did not return an extension module`。
   MSYS2 那份链接的是 `libpython3.14.dll`，和 GIMP 是同一个实例，所以能用。

装好后在 GIMP 进程内实测：`numpy 2.4.6` + OpenBLAS，`linalg.solve(1000×1000)`
约 **0.015 秒**。GIMP 升级会换成新的 `python3.XX` 目录，**升级后要重跑一次**
（脚本幂等，不删任何已有文件）。

## 构建

**方式一：gcc 直编（Windows/MSYS2、Linux、macOS 通用，已验证）**

```bash
cd gegl-color-ops
./build.sh                 # 产物在 build/ 下，41 个 .dll/.so/.dylib
```

脚本会自动探测 `gegl-0.4.pc`（先试 `D:/fastsoftware/GIMP 3/lib/pkgconfig` 等常见位置），也可手动指定：

```bash
export PKG_CONFIG_PATH="/d/fastsoftware/GIMP 3/lib/pkgconfig"
./build.sh
```

**方式二：meson（等价，适合 CI）**

```bash
export PKG_CONFIG_PATH="/d/fastsoftware/GIMP 3/lib/pkgconfig"
meson setup build-meson && ninja -C build-meson
```

两个关键编译约定（改工程时别破坏）：

1. `-I<算子目录>` 必须存在——`gegl-op.h` 会通过 `GEGL_OP_C_SOURCE` 把该 `.c` 自身再包含一次；
2. `GEGL_OP_C_SOURCE` 的文件名必须与磁盘上真实文件名**完全一致**，否则编译报找不到文件。

## 三台机器的分工（产物怎么合流）

代码只在一台机器上写，三份二进制各自有归属目录，**互不覆盖**：

| 产物 | 谁编 | 落在 | 推到 |
|---|---|---|---|
| Windows x64 `.dll` | 开发机（MSYS2 gcc） | `dist/windows-x64/` | `main` |
| Linux x86_64 `.so` | GitHub Actions（meson） | `dist/linux-x64/` | CI artifact，人工取回 |
| macOS arm64 `.dylib` | 一台 Apple Silicon Mac | `dist/macos-arm64/` | `dist/mac` 分支 |

在 Mac 上出那一份：

```bash
brew install gegl
./tools/dist_mac.sh              # pull --rebase → build.sh → make_dist → 只提交本平台 → 推 dist/mac
./tools/dist_mac.sh --dry-run    # 只看看会提交什么
```

开发机取 macOS 产物：`git fetch origin && git merge origin/dist/mac --no-ff`（只带进那一个目录）。
合并之后重跑 `python tools/site_build.py`，主页与下载页会自动多出 macOS 的算子整包、
插件整包和每个算子页的 `.dylib` 直链；没合并时那两处退回「从 Actions 下」的提示，
构建不报错。

三条必须守的规则，破一条就会出事：

1. **谁都不许写别人的目录**。二进制冲突**没法 merge**，只能整份选一边，一不小心
   就把另一平台攒齐的产物覆盖掉。`tools/make_dist.py` 只在 `build/` 里有该平台产物
   时才动那个目录，没有就跳过——所以同一个脚本在 Windows 上跑不会碰 `dist/macos-arm64`。
2. **生成清单前必须先 `git pull --rebase`**。`dist/manifest.csv` 和
   `dist/SHA256SUMS.txt` 是三个平台共用的，清单按「磁盘上现有文件」重算；不先同步
   就没有另外两个平台的行，一提交就把它们抹掉。`dist_mac.sh` 把 pull 放在第一步就是
   为了这个。
3. **macOS 产物走 `dist/mac` 分支，不直接进 main**。main 的提交序列只跟代码走，
   产物按需合进来，历史干净、review 也看得清。

## 安装

```bash
./install.sh            # 编译 + 复制到用户插件目录
./install.sh --verify   # 复制后再用 gegl CLI 逐个确认注册
```

默认目标目录：

| 平台 | 路径 |
|---|---|
| Windows | `%LOCALAPPDATA%\gegl-0.4\plug-ins` |
| Linux | `~/.local/share/gegl-0.4/plug-ins` |
| macOS | `~/Library/Application Support/gegl-0.4/plug-ins` |

装完**重启 GIMP**，在 `/`（Search Actions）里搜标题即可；GIMP 会把滤镜以非破坏性 fx 挂在图层上。
想临时试跑、不装进 GIMP：

```bash
GEGL_PATH="$PWD/build;/d/fastsoftware/GIMP 3/lib/gegl-0.4" gegl in.png -o out.png -- lb:exposure exposure=1.0
```

### 下载包怎么装（不编译）

把 zip 解开后**连 `locale/` 一起**放进上表目录 —— 里面是
`locale/zh_CN/LC_MESSAGES/gegl-color-ops.mo`。少了它模块照样加载，菜单、参数名和
说明只是回落到英文，不会报错，所以很容易被当成「没做多语言」。

Python 插件是**另一套目录**（GIMP 自己的 `plug-ins/`，不是 GEGL 那个）：除 `.py`
之外还要有 `_shared/`（`lb_i18n.py` 翻译取值、`lb_dialog.py` 参数对话框）和
`locale/`，三者放在同一层。单个插件包与整包的 `安装说明.txt` 里都写了这一步。

### 界面语言

翻译跟 **GIMP 的界面语言**走，不跟操作系统走。GIMP 3：编辑 → 首选项 → 界面 → 语言，
选中文，完全退出再打开。临时验证：

```bash
LANG=zh_CN.UTF-8 gimp              # 中文
LANG=en_US.UTF-8 gimp              # 英文
LB_LOCALEDIR=/path/to/locale gimp  # 直接指定语言包目录
```

插件的菜单名会被 GIMP 缓存进 `pluginrc`，里面存的是**已经翻译好的字符串**、不带语言
标记，所以切语言后它不会自己失效，菜单会停在旧语言。删掉
`%APPDATA%\GIMP\3.x\pluginrc`（Linux `~/.config/GIMP/3.x/pluginrc`）再启动即可。
算子不受影响——它们每次启动都重新取。

## 插件的参数对话框要自己弹

**GIMP 3 不会自动给插件生成参数对话框。** 参数用 `add_*_argument` 注册得再完整、
过程也挂在菜单上，只要 `run()` 里没有自己建 `GimpUi.ProcedureDialog` 再 `run()`，
点菜单就是**用默认值直接开跑**——用户看不到任何输入框。

这个 bug 特别阴：菜单在、PDB 里查得到、插件也确实「工作」（用默认值），
只有「所有可调参数」这一层被悄悄吃掉了。2026-11-22 就是这样：22 支 Python 插件
全都有这个问题，直到 AI 局部重绘因为默认提示词是空串，才把它暴露成
「提示词是空的」这句报错。

正确写法（三行，已经在 `plugin/_shared/lb_dialog.py` 里封装成 `run_dialog`）：

```python
if run_mode == Gimp.RunMode.INTERACTIVE:
    dialog = GimpUi.ProcedureDialog.new(procedure, config, title)
    GimpUi.window_set_transient(dialog)
    dialog.fill()
    if not dialog.run():
        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    dialog.destroy()
```

几条规矩：

- **只在 `INTERACTIVE` 弹**。`WITH_LAST_VALS`（重复上次）和 `NONINTERACTIVE`
  （批处理）再弹框就是骚扰甚至卡死回归脚本。
- **取消要返回 `CANCEL`**，别让用户点了「取消」还照样跑一遍。
- **弹不出来不能让插件失败**：`lb_dialog` 兜底退回默认值并打一条消息。
- 对话框标题按 Pango 标记解析，菜单名里的 `&` 要转义，否则标题解析失败。
  助手已经 `markup_escape_text` 过了。
- 参数本身由 GIMP 按类型生成控件，但 `GimpParamCoreObjectArray`（`drawables`）
  会报 `non supported type` 警告——那本来就不该让人填，忽略。

回归：`tools/check_plugin_dialogs.py` 把每支插件的源码断言 + 真的用
`GimpUi.ProcedureDialog` 把控件建一遍。**只断言源码里出现 `add_menu_path` 那种
写法是不够的**——本轮和上次「菜单消失」都是这么漏过去的。

## 多语言（gettext）

界面上的一切文案都走 gettext，域名是 `gegl-color-ops`（`common/config.h`）。约定
**msgid 一律写英文**，译文放在 `po/<lang>.po`；缺译时原样显示英文，不会出现半截中文。

```bash
python tools/i18n.py extract   # 扫 ops/*/*.c 与 plugin/*/*.py，刷新 po/gegl-color-ops.pot
python tools/i18n.py build     # po/*.po -> locale/<lang>/LC_MESSAGES/gegl-color-ops.mo
python tools/i18n.py check     # msgid 里不许留中文；占位符数量要一致；报告缺译与过期条目
```

目录现状：1045 条 msgid，中文 364 条（原来就是中文的那些，加五个分量曲线插件的
菜单名），其余是本来就写英文的标题 / 说明。`check` 把「缺译」当提示不算失败——缺译只是
回落到英文；但 **msgid 里出现中文**、**msgstr 为空**、**占位符数量与 msgid 不一致** 都算错误。

`locale/<lang>/LC_MESSAGES/*.mo` **是提交进仓库的产物**：C 侧的构造函数和插件的
`lb_i18n.py` 直接读它，构建过程不生成。改了 `po/` 记得跑一次 `build` 再提交，
CI 会重编一遍并比对，不同步直接红。

翻译菜单名时注意占位符：`"HSV Split (Curves) · %s" % _("multi")` —— 模式词要单独包
`_()`，否则 extract 抓不到 `multi`（它藏在条件表达式里），中文界面会停在英文。

两侧的衔接方式不同，都要靠自己找目录（GIMP 不会替我们 bindtextdomain）：

- **C 算子**：`common/i18n.c` 是独立编译单元（`build.sh` 与 `meson.build` 都把它和每个算子一起编），
  用 `__attribute__((constructor))` 在模块载入时 `bindtextdomain`，目录按 `.dll`/`.so` 自身位置
  推：`locale/` → `../locale` → `../share/locale`。
- **Python 插件**：`plugin/_shared/lb_i18n.py`，标准库 `gettext` + `GLib.get_language_names()`
  （Windows 上 locale 模块读的是系统区域设置，而 GIMP 界面语言可以单独选，两者经常不一致）。
- **枚举标签**（`enum_value` 的第三个参数）不需要包 `_()`：GEGL 在 `enum_end` 里会自己对它
  做 `dgettext(GETTEXT_PACKAGE)`，进目录即可翻译。

`./install.sh` 会把 `locale/` 复制到模块旁边，`./install-plugin.sh` 复制到 `plug-ins/locale`；
调试时也可以用 `LB_LOCALEDIR=/some/locale` 直接盖掉搜索顺序。

注意两件事：

1. `%APPDATA%\GIMP\3.2\pluginrc` 缓存的是**已翻译**的菜单名与过程说明，而且不记录语言。
   换界面语言后如果菜单还停在旧语言，删掉 `pluginrc` 让 GIMP 重建。
2. 改 `GETTEXT_PACKAGE` 之前它借的是 GEGL 自己的语言包（`gegl-0.4`），会串味：`Blend mode`、
   `Contrast` 这类同名 msgid 在中文界面里会显示成德文或日文。

## 临时停用与恢复

想先让某个算子/插件从 GIMP 里消失、但源码继续留在工程里，就在它的目录放一个 `.disabled` 标记：

```bash
touch ops/apply-image/.disabled        # 停用这个 GEGL 算子
touch plugin/blend/.disabled        # 停用 Python 插件
```

- `build.sh` 会跳过带标记的算子目录（打印 `SKIP`），`build/` 里不再产出它的 `.dll`，
  `install.sh` 也就装不到它；`install-plugin.sh` 逐个 `plugin/` 子目录安装，见到标记跳过。
- 已经装进 `%LOCALAPPDATA%\gegl-0.4\plug-ins` 或 GIMP `plug-ins` 的旧模块不会被脚本清理，
  必须手动删掉那个 `.dll` / 插件目录，否则 GIMP 重启后照样加载。
- 恢复：删掉 `.disabled`，重跑 `./build.sh && ./install.sh`（插件版再 `./install-plugin.sh`）。

**当前状态（2026-11-12）**：全部恢复启用——两个 GEGL 算子已在修掉「源图层尺寸」
与「通道编号」两个 bug 后恢复（见 `5d0e267`），`plugin/blend` 也已删掉
`.disabled` 重新安装；旧二进制留在 `backup/disabled-20261111-apply-calc/`
（`backup/` 不进仓库）。

插件停用期间照样可以跑它的回归——`tools/check_blend_plugin.py` 直接按文件路径加载
`plugin/blend/blend.py`，不依赖是否安装：

```bash
"D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval \
    -b "exec(open(r'<repo>/tools/check_blend_plugin.py').read())" --quit
```

## 在 GIMP 菜单位置

41 个算子注册在同一个菜单目录下；色阶家族与分量家族各自单独收进一级目录，
避免一长串：

```
SuperMrWang → Levels    → <算子>   （7 个色阶）
SuperMrWang → Component → <算子>   （10 个 dual / compose + 灰度转分量）
SuperMrWang → Tone / Color / Blend / Mask → <算子>
SuperMrWang → Sharpen / Noise / Distort → <算子>
SuperMrWang → AI        → AI Inpaint… / AI Inpaint (Advanced)… / AI Environment…
SuperMrWang → Retouch   → 高低频 / 双曲线 / 中性灰磨皮
                          各自再加一个「（AI 预修）」入口
SuperMrWang → Observe   → 黑白 / 陡峭曲线 / 波浪曲线 / 饱和度 / 阈值 / 海报化
                          观察层，点了就建（也是 Python 插件）
SuperMrWang → Luminosity Masks → 生成七条明度通道（亮部/暗部各 3 档 + 中间调）
                          （以上都是 Python 插件，不在 47 个算子里）
```

47 个算子按「找算子时的念头」分九组，避免一个子菜单里平铺二十多项：

| 组 | 想干什么 | 放什么 |
|---|---|---|
| `Levels` | 拉黑白场 / 调中间调（gamma） | Levels、LAB / HSL / HSB / LCH / CMYK / HSI 色阶——一级目录 |
| `Component` | 把分量拆开 / 拼回来 | HSV / HSL / Lab / LCh / HSI 的 `dual` + `compose` 成对，加灰度 → 分量编码——一级目录 |
| `Tone` | 太暗 / 太灰 / 反差不对 | 曝光、亮度/对比度、阴影/高光、黑白 |
| `Color` | 颜色不对 / 想加味道 | 色相饱和度、HSL 8 Bands、色彩平衡、颜色分级、色温色调、自然饱和度、Vibrance、可选颜色、着色 |
| `Blend` | 要把两样东西合起来 | 应用图像、计算、通道混合器、照片滤镜、颜色查找 |
| `Mask` | 要一个选区 | 色彩范围、通道区间 → alpha |
| `Sharpen` | 边缘不够利 / 想更清澈 | USM 锐化（带可调光晕抑制） |
| `Noise` | 要颗粒 / 要去颗粒 / 去灰尘 | 添加杂色、减少杂色、蒙尘与划痕 |
| `Distort` | 要把图掰弯 / 做折射 | 置换（一张 RGBA 同时给 X/Y） |

对应源码里的两个 class key（每个 `ops/*/*.c` 都有）：

```c
"gimp:menu-path",  "<Image>/SuperMrWang/Tone",
"gimp:menu-label", _("界面里显示的名字"),
```

**别手改 47 个文件**。分组表在 `tools/set_menu_group.py` 里，改完跑一遍即可
（按字节替换，仓库里 LF / CRLF 混用也不会把行尾搞乱）：

```bash
python tools/set_menu_group.py --check   # 先看现状与漏网
python tools/set_menu_group.py           # 写入
```

`<Image>` 是图像菜单，`/SuperMrWang` 是菜单栏顶层的自建菜单（第一级不在内置
菜单里，GIMP 就新建一个，出现在「滤镜」右边），后面几节是分组名。GIMP 3 的
`menu-path` 支持多级——内置就有 `<Image>/Image/Mode/Color Profile`——组不存在
时会自动建。

改 `menu-path` **不影响 op id**：XCF 里已经用过的滤镜照旧能打开，
只是菜单位置会变，需要重新 `./build.sh` 并重启 GIMP。

> 踩过的坑：`gegl --info lb:xxx` 能查到、命令行能跑、自检脚本全绿，**不等于 GIMP
> 菜单里看得见**。漏了 `gimp:menu-path` 的算子只会注册成 GEGL 名字，在 GIMP 里
> 根本不出现（2026-11-20 锐化 / 杂色四个算子就是这样，装了一个多月没人提是因为
> 它们压根没进过菜单）。`tools/check_menu.py` 把这条钉成断言，CI 也会跑。

## 验证与回归（tools/）

```bash
python tools/make_test_image.py out.png     # 生成色环+灰阶+明度测试图
./tools/smoke.sh                            # 每个算子用默认参数渲染一遍，抓崩溃/黑图
python tools/contact_sheet.py sheet.png build/smoke/*.png   # 拼成带标签的对照表
python tools/check_gamma_domain.py          # 数值回归：感知（伽马）域 + 全图像素核对
python tools/check_blend.py                 # 数值回归：双输入算子 23 用例（含通道映射、源层尺寸/偏移）
python tools/check_color_balance_fine.py    # 与经典图像编辑器实测比对：色彩平衡（--all 跑全部 609 档）
python tools/check_color_balance_ps.py      # 与经典图像编辑器实测比对：色彩平衡（含保留明度）
python tools/check_color_mask_select.py     # 与经典图像编辑器实测比对：色彩范围的高光/阴影/中间调曲线
python tools/check_color_grading.py         # 行为验证：颜色分级（恒等/分带/落位/Blending/Balance/全局）
python tools/check_levels_ps.py             # 与经典图像编辑器实测点比对：色阶（含 gamma 方向与指数形式）
python tools/check_lab_levels.py            # 数值回归：LAB 色阶（gimp-console 跑，21 项）
python tools/check_match_color.py           # 数值回归：匹配颜色（gimp-console 跑，17 项）
python tools/check_gray_to_component.py     # 灰度转分量：九个混合模式的恒等往返，39 条
python tools/check_xyz_multiply.py --all    # 数值回归：XYZ 正片叠底（36 组白点×叠加色×不透明度）
python tools/check_convert.py               # 数值回归：十二向转换 vs GIMP 原生 + 路径转位图（72 项）
python tools/check_convert_pixels.py        # 逐像素回归：十二向 × 两档精度，偏差必须为 0（24 项）
python tools/check_max_min.py                 # 数值回归：形态学极值 vs O(r²) 暴力（27 项）
python tools/check_max_min_plugin.py          # 插件回归：PDB / 滤镜挂载 / 蒙版写像素（12 项）
python tools/compare_native.py              # 诊断：十二向转换 vs GIMP 原生，两列数值应完全相同
python tools/normalize_headers.py           # 预览文件头/命名重排，加 --write 落盘
python tools/set_menu_group.py --check      # 核对菜分组映射表与 ops 目录是否一一对应
python tools/check_menu.py                  # 每个算子都有 id / menu-path / menu-label，且路径与分组表一致
python tools/check_ai_inpaint.py            # AI 重绘的 HTTP/PNG 链路（对着 mock ComfyUI，不需要显卡）
# 下面三条要在真 GIMP 里跑（插件已装好）；用 gimp-console，不用开界面
gimp-console -b "exec(open('tools/check_plugin_dialogs.py').read())"   # 每个插件都能弹出参数框（145 条）
gimp-console -b "exec(open('tools/check_retouch.py').read())"          # 磨皮三支（非 AI）：结构 / 滤镜 / 恒等 / 画笔（76 条）
gimp-console -b "exec(open('tools/check_observe.py').read())"          # 观察层六种：结构 / 滤镜 / 效果方向（57 条）
gimp-console -b "exec(open('tools/check_luminosity_mask.py').read())"  # 明度蒙版七条：映射表 / 内容 / 幂等（51 条）
gimp-console -b "exec(open('tools/check_retouch_ai_gimp.py').read())"  # 磨皮三支（AI 预修）：结构 / 预涂蒙版 / 灰层 / 选区（67 条）
gimp-console -b "exec(open('tools/check_ai_inpaint_gimp.py').read())"  # AI 重绘的落位与蒙版
python tools/run_plugin_checks.py           # 上面九套一次跑完（783 条），把条数写进 tools/plugin_assertions.json
python tools/run_plugin_checks.py --check   # 只核对：json 是不是比脚本旧了（站点构建会自动喊）
python tools/make_dist.py                   # 把 build/ 整理成 dist/（含 manifest + 校验和）
./tools/check-linux.sh                      # 在 Linux/WSL 里验证 .so 能加载并渲染（不开 GIMP）
python tools/git_push_api.py --dry-run      # 推送兜底：github.com:443 不通时改走 Git Data API
```

站点插件总览上那个「N 条回归断言」不再是手写数字：`run_plugin_checks.py` 真实跑一遍
写 `tools/plugin_assertions.json`，`site_build.py` 读出来求和；某个脚本比 json 新
（也就是改了测试没重跑）时构建会打印警告、页面显示 `—`，而不是继续挂着作废的数目。

`smoke.sh` 只保证"不崩、有输出"；`check_gamma_domain.py` 用纯色小图对期望值
（黑白纯红 102、曝光 +1EV → 176、通道混合器恒等/R←G/单色等），并且**逐像素核对整张图**
而不是只看首像素——2026-11-11 那个「无 alpha 图出现马赛克」的 bug 就是首像素永远正确、
从第二个像素开始错位，只看一个点查不出来；
`check_blend.py` 用
`build/auxrun` 建双输入图，逐个核对混合公式（正片叠底 128×200=100、深色模式
取整像素、色相模式只换色相等）。这些脚本都会自动找 gegl 可执行文件，不在 PATH
也能跑；`smoke.sh` / `check_blend.py` 还支持 `OPS_DIR=` 指向旧版 DLL 目录做前后
对照（配合 `OUT_DIR=`）。

## 推送受阻时的兜底：git_push_api.py

本机到 `github.com:443` 的 HTTPS 常年不通（直连超时、换 IP 超时、走代理报
`schannel: server closed abruptly`），但 `api.github.com` 一直可用，凭据管理器里也存着
带 `repo` + `workflow` 权限的 token。`tools/git_push_api.py` 就是为此写的：本地照常
`git commit`，然后用 Git Data API 把提交链搬上去。

```bash
git add -A && git commit -m "..."          # 本地提交不受影响
python tools/git_push_api.py --dry-run     # 先看要传多少、推哪些提交
python tools/git_push_api.py               # 真推（默认 12 路并发传 blob）
```

它依次做四件事：按需 `POST /git/blobs`（远端已有的 sha 直接跳过）、自下而上
`POST /git/trees`、`POST /git/commits` 接上远端 head、`PATCH /git/refs/heads/main`。
推完再把远端新建的 commit 对象用 `hash-object -w` 还原到本地并把 `origin/main` 和本地
分支对齐——没有 fetch 也能让 `git status` 保持干净。

踩过的坑（脚本里都已处理，重写时别再去掉）：

- **tree 的非递归 GET 会假 404**：刚创建的 tree 用 `?recursive=1` 能读、普通 GET 返回
  404。`remote_tree()` 因此对 404 退回递归读取再筛根级条目。
- **不要拿本地 sha 当远端 tree 结果**。内容寻址下两者经常相同，但对象没写进远端时
  commit 建得出来、GET 却 404。每层都真的 POST 一次。
- **commit 的 message 尾换行会被 GitHub 去掉**，所以远端 sha 与本地必然不同。这不是
  丢内容，`adopt_remote()` 会按同一规则还原对象并对齐 refs。
- **串行传 blob 会超时**：18MB / 上千个小文件逐个往返要二十分钟，先并发预取再建树。

## 新增一个算子

1. 建目录 `ops/<你的算子名>/`，放 `<你的算子名>.c`（单文件两段式：`#ifdef GEGL_PROPERTIES` / `#else`）；
2. 文件内三处命名必须自洽：`GEGL_OP_C_SOURCE <同目录文件名>`、`GEGL_OP_NAME <下划线标识>`、`"name", "lb:<算子名>"`；
   文件名还不能和 GEGL 内置算子的源文件名同名（GType 由文件名生成，见「与旧布局的对应关系」里 exposure 的例子），需要时加前缀改成 `lb-xxx.c`；
3. `./build.sh` 会自动发现并编译——**不需要改任何脚本或清单**；
4. 需要额外头文件就放 `common/`（已默认加入 include 路径）。

## 与旧布局的对应关系

早期是 12 个独立仓库 + 1 个单文件算子，已合并改名。GEGL id 变更一览（旧 → 新）：

| 旧 id | 新 id |
|---|---|
| `lb:channelrangetoalpha` | `lb:channel-range-to-alpha` |
| `lb:colormaskselect` | `lb:color-mask-select` |
| `lb:CMYKPC` | `lb:cmyk-primary-correction` |
| `lb:ps-colorbalance` | `lb:color-balance` |
| `lb:ps-colorize` | `lb:colorize-hsl` |
| `lb:ps-exposure` | `lb:exposure` |
| `lb:rgbdomaingrayscale` | `lb:rgb-domain-grayscale` |
| `lb:xyzmultiply` | `lb:xyz-multiply` |
| `wb:hue-saturation` | `lb:hue-saturation` |
| `lb:hsl-seven` | `lb:hsl-bands` |
| `lb:channel-mixer-plus` / `lb:lab-levels` / `lb:vibrance-hyper` | 不变 |

旧布局产出的 DLL 文件名与新布局不同（如 `channelrangetoalpha.dll`、`color_balance.dll`、`hslseven.dll`），
装新版后请把插件目录里这些**旧文件名**的模块删掉，否则同一个 GEGL id 会被加载两次。
同理，`exposure` 已改名为 `lb-exposure`（见下），旧的 `exposure.dll` / `exposure.so` 也要删。

**为什么 hsl-seven 要改名**：它最早是七段色相（红橙黄绿青蓝紫），2026-11-12 按
RAW 编辑器的八段混色器拆出洋红段后，id 里的 `seven` 就和实际不符了。改名成
`lb:hsl-bands` 之后名字不再承诺段数，也不必再随段数变化。代价是**旧 XCF 里挂着的
`lb:hsl-seven` 非破坏滤镜会显示为不可用**；要处理老工程可以暂时把旧的 `hsl-seven.dll`
留在插件目录——两个 id 互不冲突，能同时存在，处理完再删。

**为什么 exposure 要改名**：GEGL 给每个算子生成的 GType 名是 `GeglOp<源文件名>.c`，
不看 `GEGL_OP_NAME`。源文件叫 `exposure.c` 时生成的类型名与 GEGL 内置 `gegl:exposure`
完全相同，Linux（GEGL 0.4.48）下的表现是控制台报
`Two different plugins tried to register 'GeglOpexposure_c'`，然后整个 .so 静默不生效
（`gegl --info lb:exposure` 查不到），Windows 上恰好没撞上而已。改名成 `lb-exposure.c`
之后两边都干净——这也是 `tools/check-linux.sh` 存在的原因：不开 GIMP 也能发现这种问题。

## 版权与商标

- **代码是原创的**。每个算子都按公开的数学公式与可观察的行为自行实现，不含、也未复制
  任何商业软件的源代码或二进制；仓库里没有反编译产物，也不调用任何厂商的专有接口或
  SDK。
- **界面与文档不出现第三方商标**。菜单名、对话框标题、算子显示名、README 与站点正文
  均为本项目自定表述（`lb:` 命名空间），不使用任何厂商的 logo、图标或界面截图。
  仅对业界公开的格式与色空间规范沿用其标准名称（如 `.cube` LUT、Adobe RGB），属于
  对规范名称的指示性引用，不表示与本项目存在任何隶属关系。
- **截图都是 GIMP**。`ops/*/assets/` 下的图是在 GIMP 里运行本项目算子的界面。

All code in this repository is original: algorithms are re-implemented from published
mathematics and observable behaviour, without copying any commercial software's source
or binaries, and no vendor-specific interfaces or SDKs are used. Operation names,
dialog titles, documentation and site copy are written in this project's own terms;
no third-party logos, icons or UI screenshots are used. Standard format and colour-space
names (such as `.cube` LUT or Adobe RGB) are cited nominatively as specification names
only. This project is not affiliated with, endorsed by, or authorised by any vendor.

如认为此处有不当使用，请开 issue，核实后会调整措辞或移除相关内容。

## 许可证

GPL-3.0-or-later（见 `LICENSE`）。
