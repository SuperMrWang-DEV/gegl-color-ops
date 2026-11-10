# gegl-color-ops

[![GIMP 3](https://img.shields.io/badge/GIMP-3.x-5C5543?logo=gimp&logoColor=white)](https://www.gimp.org/)
[![GEGL 0.4](https://img.shields.io/badge/GEGL-0.4-2C4C6B)](https://gegl.org/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![Operations](https://img.shields.io/badge/operations-13-brightgreen)](#算子清单)

一组逆向实现的 GEGL 颜色算子（GIMP 3 的滤镜内核），共 **13 个**，统一 `lb:` 命名空间，
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
├── tools/                # 测试图生成、逐算子冒烟、对照表拼接、文件头重排
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
| `lb:exposure` | Exposure | Exposure | Filter | PS 曝光：EV、偏移、伽马 |
| `lb:rgb-domain-grayscale` | Grayscale | Grayscale | Point | PS 黑白：六色权重转灰 + 可选着色 |
| `lb:vibrance-hyper` | Vibrance | Vibrance | Point | 双曲自然饱和度，保护高饱和与肤色 |
| `lb:xyz-multiply` | XYZ Multiply | XYZ Multiply | Point | 以参考色做正片叠底（XYZ 域） |

每个算子的算法说明、参数含义见 `ops/<算子名>/README.md`（原始文档）。

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

**2. `GEGL_OP_NAME` 必须带 `lb_` 前缀**

它决定注册的 GType 名，GEGL 用裸字符串注册，不带命名空间会与核心算子撞名——
例如写成 `exposure` 会撞上 GEGL 自带的 `gegl:exposure`，后果是该算子**静默加载失败**
（`gegl --info` 查不到，但编译、安装全都没报错）。所以统一 `lb_<snake_case>`。

**3. 文件头注释盒（78 列）**

```c
/* ===========================================================================
 * SuperMrWang · GEGL Operation
 * ---------------------------------------------------------------------------
 * id     : lb:xxx
 * 菜单   : 菜单名
 * 作用   : 一句话说清做什么
 * 算法   : 核心思路，可换行续写，续行与首行左对齐
 * 类型   : GeglOperationPointFilter / GeglOperationFilter
 * 参考   : 算法来源（可选，没有就整行省略）
 * 许可   : GPL-3.0-or-later，见工程根目录 LICENSE
 * ======================================================================== */
```

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
python tools/normalize_headers.py           # 预览文件头/命名重排，加 --write 落盘
```

`smoke.sh` 只保证"不崩、有输出"；算法正确性仍建议在 GIMP 里对着实拍图看。

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
