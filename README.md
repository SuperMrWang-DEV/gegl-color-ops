# gegl-color-ops

[![GIMP 3](https://img.shields.io/badge/GIMP-3.x-5C5543?logo=gimp&logoColor=white)](https://www.gimp.org/)
[![GEGL 0.4](https://img.shields.io/badge/GEGL-0.4-2C4C6B)](https://gegl.org/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![Operations](https://img.shields.io/badge/operations-37-brightgreen)](#算子清单)

一组自研的 GEGL 颜色算子（GIMP 3 的滤镜内核），共 **41 个**，统一 `lb:` 命名空间，
在 GIMP 里位于 **图像 → 颜色 → SuperMrWang**。算法按公开公式与可观察的行为实现，
不含任何商业软件的代码或素材；文中出现的产品名仅用于说明某个算子参照了哪种行为，
与各厂商无隶属关系（详见文末「版权与商标」）。

> **在线版**：<https://superMrwang-dev.github.io/gegl-color-ops/> —— 每个算子一篇
> 算法说明（含参数、实测误差、示例图），Shortcut 下的八个插件也各有一篇，首页直接
> 下载免编译包。站点由 `python tools/site_build.py` 从 `ops/*/README.md` 与
> `tools/plugin_docs.py` 生成到 `docs/`，不用手写。

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
├── plugin/gray-mask/  # Python 插件：灰度图层一键 → 选区 / Alpha 通道
├── plugin/layer-to-selection/ # Python 插件：右键任意图层 → 选区
├── plugin/layer-to-channel/  # Python 插件：右键任意图层 → Alpha 通道（恒为灰度）
├── plugin/*-split-curves/    # Python 插件：HSV / LCh / HSL / Lab / HSI 分量分层 + 曲线（菜单 Shortcut）；
│                             #   菜单里两条：· single = 一层数据图三条曲线，
│                             #   · multi = 两三张分量层走原生分量混合模式（HSI 只有 single）
├── plugin/frequency-separation/ # Python 插件：高低频磨皮（低频 + 高频两层，合成即原图）
├── plugin/dodge-burn/        # Python 插件：双曲线磨皮（提亮 / 压暗两层，黑蒙版）
├── plugin/neutral-grey/      # Python 插件：中性灰磨皮（50% 灰 + 柔光）
├── plugin/alpha-curves/      # Python 插件：通道 → Alpha + 一条可编辑的 alpha 曲线（菜单 Mask）
├── plugin/sky-replace/       # Python 插件：一键换天（源码保留，.disabled 暂不安装）
├── dist/                 # 编好的模块，给不想编译的人直接下载（windows-x64 / linux-x64）
├── tools/                # 测试图生成、逐算子冒烟、对照表、文件头重排、注释双语化
├── tools/site/           # 站点样式源（生成时拷进 docs/assets/）
├── tools/plugin_docs.py  # 十一个插件页的正文与卡片文案（plugins/<slug> 文章页用）
├── docs/                 #  GitHub Pages 站点（tools/site_build.py 生成，别手改）
│   └── plugins/          #  十一个插件各一篇（菜单结构、原理、用法、实测）
├── build/                # 编译产物（build.sh 生成，可随时删）
└── LICENSE               # GPL-3.0
```

## 直接下载（免编译）

不想装工具链的，[`dist/`](dist/README.md) 里已经是编好的模块：

| 系统 | 取这个 | 放到 |
|---|---|---|
| Windows x64（整包） | [`docs/download/gegl-color-ops-windows-x64.zip`](docs/download/) | `%LOCALAPPDATA%\gegl-0.4\plug-ins` |
| Windows x64（单个） | `dist/windows-x64/*.dll` | 同上 |
| Linux x86_64 | `dist/linux-x64/*.so` | `~/.local/share/gegl-0.4/plug-ins` |

放完重启 GIMP。平台要求（glibc 版本之类）、每个文件对应哪个滤镜、怎么校验，
见 [`dist/README.md`](dist/README.md) 与 `dist/manifest.csv`；重新打包用
`python tools/make_dist.py`。

Python 插件走另一条线：`docs/download/gegl-color-ops-plugin-<名字>.zip` 一个插件一个包，
**它内部用到的算子模块（`lb:hsv-dual` 这类）已经打在包里的 `modules-windows-x64/`**，
下一次就齐，不用再单独找算子。`.py` 放进 GIMP 的 `plug-ins`，附带的模块放进 GEGL 的
`gegl-0.4/plug-ins`——两个目录不同，包内 `安装说明.txt` 分步写了。

> Linux 端 component 家族的 11 个模块（各空间的 dual / compose 与 gray-to-component）
> 还没出预编译包，插件包里的 `modules-linux-x64/` 因此暂时不存在；要用 Linux 就先
> `./build.sh` 编一份放进 GEGL 目录。Windows 端是齐的。

## 算子清单

菜单名（`gimp:menu-label`）只留主名，**不带括号**——括号会把 GIMP 的菜单/选项面板撑宽。
模型或来源这类信息写进 `description` 和本表最后一列，不塞进名字。

| GEGL id | 菜单名 | 完整标题 | 组 | 类型 | 作用 |
|---|---|---|---|---|---|
| `lb:hue-saturation` | Hue/Saturation | Hue/Saturation | Color | Point | HSL 色相/饱和度/明度，主控 + 六区间独立调 |
| `lb:hue-saturation-basic` | Hue/Saturation (Basic) | Hue/Saturation (Basic) | Color | Point | 三滑杆公式：色相旋转、饱和度相对缩放（s/(1−x)）、明度向白/黑混合；逐码对拍参考实现 |
| `lb:hue-range-basic` | Hue Range (Basic) | Hue/Saturation Range (Basic) | Color | Point | 色系范围：六色系四柄色条（内二柄全选、外二柄线性过渡），范围内按权重缩放应用色相/饱和度/明度；与上一个串联即「主控 + 分色系」 |
| `lb:hsl-seven` | HSL 8 Bands | HSL 8 Bands | Color | Point | 八段色相（含洋红）各调 H/S/L，RAW 编辑器 风格；旧七段属性名不变 |
| `lb:channel-mixer-plus` | Channel Mixer Plus | Channel Mixer Plus | Blend | Point | 经典图像编辑器 通道混合器 + 通道 offset + 单色模式 |
| `lb:channel-range-to-alpha` | Range → Alpha | Channel Range to Alpha | Mask | Point | 通道数值区间 → alpha（混合颜色带） |
| `lb:cmyk-primary-correction` | CMYK Primary | CMYK Primary Correction | Color | Point | 可选颜色：九组色域各存一份 C/M/Y/K，同时生效 |
| `lb:color-balance` | Color Balance | Color Balance | Color | Filter | 经典图像编辑器 色彩平衡：三区间指数相乘合成一条逐通道曲线，单段残差 0.30 码 |
| `lb:color-grading` | Color Grading | Color Grading | Color | Point | RAW 编辑器 颜色分级：阴影/中间调/高光/全局四轮盘 + 明度 + Blending/Balance，按亮度分带（模型对齐，未逐码标定） |
| `lb:color-lookup` | Color Lookup | Color Lookup | Blend | Filter | 经典图像编辑器 颜色查找：按 .cube 3D LUT（可带 1D shaper）查表，三线性 / 四面体可选 |
| `lb:match-color` | Match Color | Match Color | Color | Composer | 经典图像编辑器 匹配颜色：Lab 统计迁移（Reinhard），亮度/颜色强度/渐隐/中和 |
| `lb:colorize-hsl` | Colorize | Colorize | Color | Point | 经典图像编辑器 色相/饱和度「着色」实测复刻：扔掉原有 H/S，只留输入 L 的单色调，残差 0.03 码 |
| `lb:color-mask-select` | Mask by Color | Color Mask Select | Mask | Point | 经典图像编辑器 色彩范围：高光/阴影/中间调按「阈值 + 容差」实测复刻（平均 2.1 码），色系/自定色走容差窗 |
| `lb:lab-levels` | LAB Levels | LAB Levels | Levels | Filter | LAB 三通道各自黑白场 + 伽马，a/b 绕中性轴分段 |
| `lb:hsl-levels` | HSL Levels | HSL Levels | Levels | Filter | HSL 三分量色阶，色相按弧环形重映射 |
| `lb:hsb-levels` | HSB Levels | HSB Levels | Levels | Filter | HSB（HSV）三分量色阶，S/B 是 HSV 语义 |
| `lb:lch-levels` | LCH Levels | LCH Levels | Levels | Filter | CIE LCh 的 L/C/H 色阶，调色度不串色相 |
| `lb:cmyk-levels` | CMYK Levels | CMYK Levels | Levels | Filter | CMYK 四版墨量色阶（babl 分色，非 ICC） |
| `lb:hsi-levels` | HSI Levels | HSI Levels | Levels | Filter | HSI 三分量色阶，I 取三通道均值 |
| `lb:levels` | Levels | Levels | Levels | Point | 经典图像编辑器 色阶：复合 + R/G/B 四组输入黑/灰/白场与输出黑白场，0–255 刻度；gamma 方向经公开实测点验证（154@0.46→84、200@1.646→220） |
| `lb:exposure` | Exposure EV | Exposure EV | Tone | Filter | 经典图像编辑器 曝光：EV、偏移、伽马；整数图走伽马域、浮点图走线性域，按输入精度自动选路 |
| `lb:rgb-domain-grayscale` | Black & White | Black & White | Tone | Point | 经典图像编辑器 黑白：六色权重转灰 + 可选着色 |
| `lb:vibrance-hyper` | Natural Saturation | Natural Saturation | Color | Point | LAB 自然饱和度：色度双曲蒙版 + 肤色保护窗 + 色域收敛不扭色相 |
| `lb:vibrance` | Vibrance | Vibrance | Color | Point | 经典图像编辑器 自然饱和度实测复刻：ΔS = A(v)·S^p·(1−S)^q，叠红带与亮度项，16 位标定；只管饱和度，色温色调由 `lb:color-temperature-tint` 独立承担 |
| `lb:brightness-contrast` | Brightness/Contrast | Brightness/Contrast | Tone | Point | 经典图像编辑器 亮度/对比度实测复刻：新版两条曲线族查表 + 旧版闭式（pivot 89、b 夹 ±100） |
| `lb:xyz-multiply` | Photo Filter | Photo Filter | Blend | Point | **即 经典图像编辑器 照片滤镜**（实测复刻）：滤镜色在 D50 XYZ 域正片叠底，密度 + 保留明度（W3C SetLum）；不保留明度档 ≤0.71 码 |
| `lb:shadows-highlights` | Shadows/Highlights | Shadows/Highlights | Tone | Filter | 经典图像编辑器 阴影/高光实测复刻：边缘感知邻域亮度决定提亮提多少，含色调宽度、颜色、中间调对比度、修剪黑白。**不推荐日常使用（慢）**：半径 30 时每像素约 1.4 µs，2048×1536 默认参数净耗时 0.7 s，交互拖滑杆会卡；整体明暗请用 `lb:levels` / `lb:lab-levels`，见 `ops/shadows-highlights/.discouraged` |
| `lb:color-temperature-tint` | Color Temperature & Tint | Color Temperature & Tint | Color | Point | 经典图像编辑器 2026「色彩与自然饱和度」里的色温 / 色调：冷↔暖、绿↔洋红，中性灰跟着偏色、黑白不动 |
| `lb:apply-image` | Apply Image | Apply Image | Blend | Composer | 经典图像编辑器 应用图像：aux 层按 26 种混合模式压到本层，可只作用单通道；加法/减法带 缩放(1..2)/补偿值(±255)；源层没盖到和透明的地方原样输出 |
| `lb:calculations` | Calculations | Calculations | Blend | Composer | 经典图像编辑器 计算：两路通道混合出灰/alpha 蒙版，双源可各自反相；加法/减法带 缩放(1..2)/补偿值(±255)；源 2 透明处蒙版为 0 |
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

每个算子的算法说明、参数含义见 `ops/<算子名>/README.md`（原始文档）。

**两个双输入算子**（`apply-image` / `calculations`）除 `input` 外还有一个 `aux` pad。
两者都是 composer，但基类不同：`apply-image` 要按源图层的大小和位置决定「这块有没有
东西可混」，所以用 `GeglOperationComposer`（`process` 拿到的是 `GeglBuffer`，可以
`gegl_buffer_get_extent(aux)`）；`calculations` 输出的是整幅蒙版，缺的源按黑算，
用开销更小的 `GeglOperationPointComposer` 就够。

`apply-image` 的「有没有东西可混」分两层看：extent 是粗筛（图层盖到哪），源像素的
alpha 是细筛（这块地方真有像素吗）。抠图层的透明洞里 RGB 是 0，只看 extent 会把洞
一起乘黑——就是「相交区域里本不该动的地方也变了」。

`calculations` 输出的是蒙版，没有「原图」可保留，所以源 2 的 alpha 直接当覆盖率乘在
结果上：透明处蒙版为 0（不选中），半透明柔边按比例衰减。两个算子的判据一致——源层
没有像素的地方不让它的 RGB 0 参与运算，区别只在落点（保留原值 / 归零）。

**加法/减法的 缩放/补偿值**：与 经典图像编辑器 一致，混合模式选 加法
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
主场。`plugin/blend` 是一对 Python-Fu 插件，把 经典图像编辑器 对话框完整搬过来：

- `Apply Image` / `Calculations`，位于 **颜色 → SuperMrWang**
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
    `load-selection`。已经存在的灰度图层可以用 gray-mask 插件的
    **选择 → SuperMrWang → Grayscale Layer to Selection** 事后转
- 写入通道/灰度图层时会**临时挂起当前选区**（shadow buffer 的合并会遵守选区，
  否则新通道在选区外是黑的），写完后按需恢复旧选区或换成新结果
- 像素内核 `tools/blend_core.c` 编成 `blend_core.dll` 由 ctypes 调用，公式
  直接 include `common/blend.h`——**GEGL 算子与 Python 插件保证同一结果**；
  没有编译产物时自动退化为纯 Python（一致但慢）

```bash
./install-plugin.sh          # 装到 %APPDATA%/GIMP/3.x/plug-ins，重启 GIMP 生效
```

交互模式弹自定义对话框；批处理可用注册参数（`blend` 0..25 按 经典图像编辑器 顺序、
`source-image`/`source-layer` 等，见 `do_create_procedure`）。

### Python 插件版：plugin/gray-mask

**灰度图层 → 选区 / Alpha 通道** 的一键化。原生做法要绕三步
（加图层蒙版「灰度副本」→ 蒙版至选区 → 存储到通道）；插件把这条链压成
两个菜单项，位于 **选择 → SuperMrWang**：

- `Grayscale Layer to Selection`：活动图层灰度内容 → 当前选区，
  可选组合方式（替换/加/减/交）与反相
- `Grayscale Layer to Channel`：活动图层灰度内容 → 新建 Alpha 通道，
  默认沿用图层名，可反相
- `lb:color-mask-select` 等蒙版算子输出的黑白层可以直接接管后续流程；
  复制前自动全选（`edit_copy` 会被当前选区裁剪），粘贴后挪回源图层
  画布位置再锚定，偏移图层不会错位

回归：`tools/check_gray_mask.py`（8 条行为断言，跑在 gimp-console 的
python-fu-eval 里，不要求插件已安装）。

### Python 插件：plugin/layer-to-selection 与 plugin/layer-to-channel

**右键点哪个图层，就把它转成选区或通道。** GEGL 算子跑完常常留下一张灰度图，
往后的用途无非两种：当蒙版用（选区）或留档复用（通道）。原生流程要点四步
（复制 → 建通道 → 粘贴 → 蒙版转选区），这个插件一步完成，而且不要求图层是
「纯灰度」：

- 入口：**图层右键 → SuperMrWang**，也挂在 **选择 → SuperMrWang** 下
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

与 `plugin/gray-mask` 的分工：gray-mask 走复制/粘贴，会带上图层蒙版等显示
效果；这两个插件读原始像素、更快，日常「灰度图 → 蒙版」优先用它们。

回归：`tools/check_layer_to_mask.py`（23 条断言：灰度值、反相、偏移图层、
彩色亮度、四个单通道、通道值/名字/反相、**彩色图层转通道得到的是亮度而不是
R 通道**、**有选区时转通道不被截断**、四种组合方式）。

### Python 插件：plugin/alpha-curves

**把透明度本身当曲线来画。** GIMP 的曲线工具有 Alpha 通道，但它只能调「已经
存在的透明度」——曲线看不到红通道是多少。这个插件把两步都挂在图层上，都是
非破坏滤镜：

1. `1 · 通道 → Alpha` —— `lb:channel-range-to-alpha`，四个滑块拉到
   `l1=0 / l2=255 / r1=r2=255`，斜坡占满全程，退化成「alpha ← 通道值」；
2. `2 · Alpha 曲线` —— `gimp:curves`，通道 = Alpha，**一条普通的曲线**。

位置：**颜色 → SuperMrWang → Mask → Alpha Curves**，或图层右键 →
SuperMrWang → Shortcut。参数两项：源通道（gray / R / G / B / LAB L·A·B /
alpha）与初始形状（auto / band 梯形 / identity / soft）。

曲线能画成任意一维映射，所以梯形只是其中一种形状；`lb:channel-range-to-alpha`
的四滑块仍然有用——它一步就能把通道变成 alpha，而曲线必须先把通道搬进 alpha。

两条滤镜是**乘**的关系：`alpha = 原 alpha × 曲线(通道值)`，与算子一致；
原图不透明时就是 `曲线(通道值)`。选 `alpha` 作源通道时只挂第 2 条，纯调现有
透明度。实测：恒等曲线与通道值差 ≤ 0.01 码、RGB 零改动；梯形曲线与
`lb:channel-range-to-alpha` 逐像素一致（0.0005 码）。回归
`tools/check_alpha_curves.py` 32 项。

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
   等蒙版算子手工精修，再用 gray-mask 插件重新生成选区合成。

菜单位置 **图层 → SuperMrWang → Sky Replace**；批处理参数
`sky-file`/`threshold`(0..0.5)/`edge`/`feather`/`match-brightness`/
`save-mask-channel`。

回归：`tools/check_sky_replace.py`（13 条断言：分层、蒙版、合成像素、
亮度匹配、开关行为、报错路径；直方图期望值按 255·enc_srgb(v) 刻度
换算，跑在 gimp-console 的 python-fu-eval 里）。

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
图像 → 颜色 → SuperMrWang → Levels    → <算子>   （7 个色阶）
图像 → 颜色 → SuperMrWang → Component → <算子>   （10 个 dual / compose + 灰度转分量）
图像 → 颜色 → SuperMrWang → Tone / Color / Blend / Mask → <算子>
```

41 个算子按「找算子时的念头」分六组，避免一个子菜单里平铺二十多项：

| 组 | 想干什么 | 放什么 |
|---|---|---|
| `Levels` | 拉黑白场 / 调中间调（gamma） | Levels、LAB / HSL / HSB / LCH / CMYK / HSI 色阶——一级目录 |
| `Component` | 把分量拆开 / 拼回来 | HSV / HSL / Lab / LCh / HSI 的 `dual` + `compose` 成对，加灰度 → 分量编码——一级目录 |
| `Tone` | 太暗 / 太灰 / 反差不对 | 曝光、亮度/对比度、阴影/高光、黑白 |
| `Color` | 颜色不对 / 想加味道 | 色相饱和度、HSL 8 Bands、色彩平衡、颜色分级、色温色调、自然饱和度、Vibrance、可选颜色、着色 |
| `Blend` | 要把两样东西合起来 | 应用图像、计算、通道混合器、照片滤镜、颜色查找 |
| `Mask` | 要一个选区 | 色彩范围、通道区间 → alpha |

对应源码里的两个 class key（每个 `ops/*/*.c` 都有）：

```c
"gimp:menu-path",  "<Image>/Colors/SuperMrWang/Tone",
"gimp:menu-label", _("界面里显示的名字"),
```

**别手改 41 个文件**。分组表在 `tools/set_menu_group.py` 里，改完跑一遍即可
（按字节替换，仓库里 LF / CRLF 混用也不会把行尾搞乱）：

```bash
python tools/set_menu_group.py --check   # 先看现状与漏网
python tools/set_menu_group.py           # 写入
```

`<Image>` 是图像菜单，`/Colors` 是"颜色"子菜单，`/SuperMrWang` 是自建分组，
最后一节是组名。GIMP 3 的 `menu-path` 支持多级——内置就有
`<Image>/Image/Mode/Color Profile`——组不存在时会自动建。

改 `menu-path` **不影响 op id**：XCF 里已经用过的滤镜照旧能打开，
只是菜单位置会变，需要重新 `./build.sh` 并重启 GIMP。

## 验证与回归（tools/）

```bash
python tools/make_test_image.py out.png     # 生成色环+灰阶+明度测试图
./tools/smoke.sh                            # 每个算子用默认参数渲染一遍，抓崩溃/黑图
python tools/contact_sheet.py sheet.png build/smoke/*.png   # 拼成带标签的对照表
python tools/check_gamma_domain.py          # 数值回归：感知（伽马）域 + 全图像素核对
python tools/check_blend.py                 # 数值回归：双输入算子 23 用例（含通道映射、源层尺寸/偏移）
python tools/check_color_balance_fine.py    # 与 经典图像编辑器 实测比对：色彩平衡（--all 跑全部 609 档）
python tools/check_color_balance_ps.py      # 与 经典图像编辑器 实测比对：色彩平衡（含保留明度）
python tools/check_color_mask_select.py     # 与 经典图像编辑器 实测比对：色彩范围的高光/阴影/中间调曲线
python tools/check_color_grading.py         # 行为验证：颜色分级（恒等/分带/落位/Blending/Balance/全局）
python tools/check_levels_ps.py             # 与 经典图像编辑器 实测点比对：色阶（含 gamma 方向与指数形式）
python tools/check_lab_levels.py            # 数值回归：LAB 色阶（gimp-console 跑，21 项）
python tools/check_match_color.py           # 数值回归：匹配颜色（gimp-console 跑，17 项）
python tools/check_gray_to_component.py     # 灰度转分量：九个混合模式的恒等往返，39 条
python tools/check_xyz_multiply.py --all    # 数值回归：XYZ 正片叠底（36 组白点×叠加色×不透明度）
python tools/normalize_headers.py           # 预览文件头/命名重排，加 --write 落盘
python tools/set_menu_group.py --check      # 核对菜分组映射表与 ops 目录是否一一对应
python tools/make_dist.py                   # 把 build/ 整理成 dist/（含 manifest + 校验和）
./tools/check-linux.sh                      # 在 Linux/WSL 里验证 .so 能加载并渲染（不开 GIMP）
```

`smoke.sh` 只保证"不崩、有输出"；`check_gamma_domain.py` 用纯色小图对期望值
（黑白纯红 102、曝光 +1EV → 176、通道混合器恒等/R←G/单色等），并且**逐像素核对整张图**
而不是只看首像素——2026-11-11 那个「无 alpha 图出现马赛克」的 bug 就是首像素永远正确、
从第二个像素开始错位，只看一个点查不出来；
`check_blend.py` 用
`build/auxrun` 建双输入图，逐个核对混合公式（正片叠底 128×200=100、深色模式
取整像素、色相模式只换色相等）。这些脚本都会自动找 gegl 可执行文件，不在 PATH
也能跑；`smoke.sh` / `check_blend.py` 还支持 `OPS_DIR=` 指向旧版 DLL 目录做前后
对照（配合 `OUT_DIR=`）。

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
| `lb:channel-mixer-plus` / `lb:hsl-seven` / `lb:lab-levels` / `lb:vibrance-hyper` | 不变 |

旧布局产出的 DLL 文件名与新布局不同（如 `channelrangetoalpha.dll`、`color_balance.dll`、`hslseven.dll`），
装新版后请把插件目录里这些**旧文件名**的模块删掉，否则同一个 GEGL id 会被加载两次。
同理，`exposure` 已改名为 `lb-exposure`（见下），旧的 `exposure.dll` / `exposure.so` 也要删。

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
