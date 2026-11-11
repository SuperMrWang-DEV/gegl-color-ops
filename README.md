# gegl-color-ops

[![GIMP 3](https://img.shields.io/badge/GIMP-3.x-5C5543?logo=gimp&logoColor=white)](https://www.gimp.org/)
[![GEGL 0.4](https://img.shields.io/badge/GEGL-0.4-2C4C6B)](https://gegl.org/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![Operations](https://img.shields.io/badge/operations-13-brightgreen)](#算子清单)

一组逆向实现的 GEGL 颜色算子（GIMP 3 的滤镜内核），当前启用 **13 个**（另有应用图像 / 计算 2 个暂时停用，
源码保留），统一 `lb:` 命名空间，
在 GIMP 里位于 **图像 → 颜色 → SuperMrWang**。

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
├── plugin/ps-blend/      # Python 插件：应用图像/计算的完整复刻版（当前已停用，源码保留）
├── tools/                # 测试图生成、逐算子冒烟、对照表、文件头重排、注释双语化
├── build/                # 编译产物（build.sh 生成，可随时删）
└── LICENSE               # GPL-3.0
```

## 算子清单

菜单名（`gimp:menu-label`）只留主名，**不带括号**——括号会把 GIMP 的菜单/选项面板撑宽。
模型或来源这类信息写进 `description` 和本表最后一列，不塞进名字。

| GEGL id | 菜单名 | 完整标题 | 类型 | 作用 |
|---|---|---|---|---|
| `lb:hue-saturation` | Hue/Saturation | Hue/Saturation | Point | HSL 色相/饱和度/明度，主控 + 六区间独立调 |
| `lb:hsl-seven` | HSL 7 Bands | HSL 7 Bands | Point | 七段色相各调 H/S/L，ACR 风格 |
| `lb:channel-mixer-plus` | Channel Mixer Plus | Channel Mixer Plus | Point | PS 通道混合器 + 通道 offset + 单色模式 |
| `lb:channel-range-to-alpha` | Range → Alpha | Channel Range to Alpha | Point | 通道数值区间 → alpha（混合颜色带） |
| `lb:cmyk-primary-correction` | CMYK Primary | CMYK Primary Correction | Point | 可选颜色：九组色域各存一份 C/M/Y/K，同时生效 |
| `lb:color-balance` | Color Balance | Color Balance | Filter | PS 色彩平衡：阴影/中间调/高光的 C-R、M-G、Y-B |
| `lb:colorize-hsl` | Colorize | Colorize | Filter | HSL 罩染，保留明暗结构 |
| `lb:color-mask-select` | Mask by Color | Color Mask Select | Point | PS 色彩范围：按选色 + 容差 + 羽化出蒙版 |
| `lb:lab-levels` | LAB Levels | LAB Levels | Filter | LAB 三通道各自黑白场 + 伽马 |
| `lb:exposure` | Exposure EV | Exposure EV | Filter | PS 曝光：EV、偏移、伽马 |
| `lb:rgb-domain-grayscale` | Black & White | Black & White | Point | PS 黑白：六色权重转灰 + 可选着色 |
| `lb:vibrance-hyper` | Natural Saturation | Natural Saturation | Point | LAB 自然饱和度：色度双曲蒙版 + 肤色保护窗 + 色域收敛不扭色相 |
| `lb:xyz-multiply` | XYZ Multiply | XYZ Multiply | Point | 以参考色做正片叠底（XYZ 域） |
| `lb:apply-image` | Apply Image | Apply Image | Composer | PS 应用图像：aux 层按 26 种混合模式压到本层，可只作用单通道 |
| `lb:calculations` | Calculations | Calculations | Composer | PS 计算：两路通道混合出灰/alpha 蒙版，双源可各自反相 |

每个算子的算法说明、参数含义见 `ops/<算子名>/README.md`（原始文档）。

**两个双输入算子**（`apply-image` / `calculations`，自 2026-11-11 起临时停用，见下文「临时停用与恢复」）用 `GeglOperationPointComposer`，
除 `input` 外还有一个 `aux` pad：

- GIMP 里 aux 由滤镜对话框的输入选择器指定（GIMP 3 会打印 `aux_label` 的名字）；
  这类滤镜**只能合并应用**，不能做非破坏性 fx，是 GIMP 目前的限制。
- aux 没接时自动退化为「源 = 本图」，此时等于同图内做通道混合——计算最常用的场景。
- gegl 命令行不支持双输入，测这两个算子要用 `build/auxrun`（`./build.sh` 顺带编译，
  源码见 `tools/auxrun.c`）。

### Python 插件版：plugin/ps-blend

GEGL 算子只接住了像素计算那一半；**输入选择**（任意打开图像的任意图层/通道、
遮罩指向第三张图）和**结果落地**（直接生成选区/新建 Alpha 通道）是插件 API 的
主场。`plugin/ps-blend` 是一对 Python-Fu 插件，把 PS 对话框完整搬过来：

- `Apply Image PS` / `Calculations PS`，位于 **颜色 → SuperMrWang**
- 源可以是任意打开图像的任意图层；通道含 Gray/R/G/B/Alpha/图层蒙版
- 计算结果四选一：活动选区 / 新建 Alpha 通道 / 新建灰度图层 / 写入图层 alpha
- 像素内核 `tools/psblend_core.c` 编成 `psblend_core.dll` 由 ctypes 调用，公式
  直接 include `common/blend.h`——**GEGL 算子与 Python 插件保证同一结果**；
  没有编译产物时自动退化为纯 Python（一致但慢）

```bash
./install-plugin.sh          # 装到 %APPDATA%/GIMP/3.x/plug-ins，重启 GIMP 生效
```

交互模式弹自定义对话框；批处理可用注册参数（`blend` 0..25 按 PS 顺序、
`source-image`/`source-layer` 等，见 `do_create_procedure`）。

## 命名与代码风格约定

改代码时请沿用下面几条，`python tools/normalize_headers.py --write` 可自动重排文件头。

**1. 名字三件套**

```
name             lb:<kebab-case>          GEGL 唯一 id，也是 GIMP 存进 XCF 的字符串，别乱改
gimp:menu-label  <短名>                    菜单里显示的字，尽量 ≤ 16 字符
title            <短名>                    搜索动作 / fx 名用；需要更完整的说法就换词，不加括号
```

菜单名规则：名词短语、首字母大写、**不加括号、不加省略号**、不用 "Plus/Hyper" 这类无信息词。
`Channel Mixer Plus`、`Mask by Color` 属固定叫法，保留。模型/来源（HSL、PS、RGB、ACR）
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
例外：`vibrance-hyper`、`lab-levels` 内部自己做线性 RGB→XYZ，天然需要线性光，
保留 `RGBA float`。

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
./build.sh                 # 产物在 build/ 下，13 个 .dll/.so/.dylib
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
touch plugin/ps-blend/.disabled        # 停用 Python 插件
```

- `build.sh` 会跳过带标记的算子目录（打印 `SKIP`），`build/` 里不再产出它的 `.dll`，
  `install.sh` 也就装不到它；`install-plugin.sh` 见到标记直接退出。
- 已经装进 `%LOCALAPPDATA%\gegl-0.4\plug-ins` 或 GIMP `plug-ins` 的旧模块不会被脚本清理，
  必须手动删掉那个 `.dll` / 插件目录，否则 GIMP 重启后照样加载。
- 恢复：删掉 `.disabled`，重跑 `./build.sh && ./install.sh`（插件版再 `./install-plugin.sh`）。

**当前状态（2026-11-11）**：`lb:apply-image`、`lb:calculations`、`plugin/ps-blend` 已临时停用，
源码完好；移走的二进制放在 `backup/disabled-20261111-apply-calc/`（`backup/` 不进仓库）。

## 在 GIMP 菜单位置

13 个算子全部注册在同一个菜单目录下：

```
图像 → 颜色 → SuperMrWang → <各算子>
```

对应源码里的两个 class key（每个 `ops/*/*.c` 都有，新增算子照抄即可）：

```c
"gimp:menu-path",  "<Image>/Colors/SuperMrWang",
"gimp:menu-label", _("界面里显示的名字"),
```

只想改目录名（比如换前缀）时，批量改这一处再 `./build.sh` 即可；
`<Image>` 是图像菜单，`/Colors` 是"颜色"子菜单，`/SuperMrWang` 就是自建的分组。

## 验证与回归（tools/）

```bash
python tools/make_test_image.py out.png     # 生成色环+灰阶+明度测试图
./tools/smoke.sh                            # 每个算子用默认参数渲染一遍，抓崩溃/黑图
python tools/contact_sheet.py sheet.png build/smoke/*.png   # 拼成带标签的对照表
python tools/check_gamma_domain.py          # 数值回归：确认算子跑在感知（伽马）域
python tools/check_blend.py                 # 数值回归：双输入算子的混合公式（16 用例）
python tools/normalize_headers.py           # 预览文件头/命名重排，加 --write 落盘
```

`smoke.sh` 只保证"不崩、有输出"；`check_gamma_domain.py` 用纯色小图对期望值
（黑白纯红 102、曝光 +1EV → 176 等），防止再退回线性光；`check_blend.py` 用
`build/auxrun` 建双输入图，逐个核对混合公式（正片叠底 128×200=100、深色模式
取整像素、色相模式只换色相等）。这些脚本都会自动找 gegl 可执行文件，不在 PATH
也能跑；`smoke.sh` / `check_blend.py` 还支持 `OPS_DIR=` 指向旧版 DLL 目录做前后
对照（配合 `OUT_DIR=`）。

## 新增一个算子

1. 建目录 `ops/<你的算子名>/`，放 `<你的算子名>.c`（单文件两段式：`#ifdef GEGL_PROPERTIES` / `#else`）；
2. 文件内三处命名必须自洽：`GEGL_OP_C_SOURCE <同目录文件名>`、`GEGL_OP_NAME <下划线标识>`、`"name", "lb:<算子名>"`；
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

## 许可证

GPL-3.0-or-later（见 `LICENSE`）。
