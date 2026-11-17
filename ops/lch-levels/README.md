# LCH Levels（lb:lch-levels）

菜单：`SuperMrWang → Levels → LCH Levels`（Filter 类）

## 概述

CIE LCh 的 L / C / H 三个分量各自做独立色阶。和 `lb:lab-levels` 是同一套
Lab 底子，区别在坐标：Lab 是直角坐标（a、b 两轴），LCh 是极坐标
（色度 C 与色相角 H）。**在 LCh 上调色度不会连带改色相，改色相也不会连带
改色度**——这是 Lab 色阶做不到的（那里动 a 就会同时改 C 和 H）。

## 色彩空间

直接工作在 babl 的 `CIE LCH(ab) alpha float`（**D50 白点**）上，RGB↔LCh
交给 babl，与 GIMP「分解 → LCH」同一套口径。

| 分量 | 量程 | 说明 |
|---|---|---|
| L | 0–100 | CIE 明度 |
| C | 0–~132 | 色度，sRGB 色域内最大约 131（纯蓝），所以量程给到 132 |
| H | 0–360° | 色相角，0° 偏红（纯红约 40°，纯蓝约 301°） |

```math
z = (h-\text{ia}) \bmod 360,\qquad
S_{\text{in}} = (\text{ib}-\text{ia}) \bmod 360,\qquad
S_{\text{out}} = (\text{ob}-\text{oa}) \bmod 360
```

```math
h' = \bigl(\text{base} + \text{span}\cdot t^{1/\gamma}\bigr) \bmod 360,\qquad
(t,\ \text{base},\ \text{span}) =
\begin{cases}
\left(\dfrac{z}{S_{\text{in}}},\ \text{oa},\ S_{\text{out}}\right), & z \le S_{\text{in}} \\[10pt]
\left(\dfrac{z-S_{\text{in}}}{360-S_{\text{in}}},\ \text{oa}+S_{\text{out}},\ 360-S_{\text{out}}\right), & z > S_{\text{in}}
\end{cases}
```

$S_{\text{in}}$ 或 $S_{\text{out}}$ 为 0（黑白场重合）时按整圈 $360°$ 处理。


```math
u = \operatorname{clamp}\!\left(\frac{x-x_{\text{lo}}}{x_{\text{hi}}-x_{\text{lo}}},\,0,\,1\right),
\qquad
\text{out} = o_{\text{lo}} + u^{1/\gamma}\,\bigl(o_{\text{hi}}-o_{\text{lo}}\bigr)
```

$o_{\text{lo}} > o_{\text{hi}}$ 时输出反相；结果夹在
$[\min(o_{\text{lo}},o_{\text{hi}}),\ \max(o_{\text{lo}},o_{\text{hi}})]$ 内。

## 规则细则

- **H 环形重映射**：把圆在黑场处剪开，主弧（黑场 → 白场）映到输出弧，
  剩余弧按比例跟进，两段共用 gamma。默认参数逐位还原；黑白场重合 =
  纯色相旋转。
- **C 线性**：C 归零 → 全图变中性灰（Lab 的 a=b=0），这是最常用的「去色」
  手法；C 反向输出（下限 > 上限）会得到互补色的味道，但明度不动。
- **L 线性**：普通色阶语义，与 `lab-levels` 的 L 完全一致。
- **黑白场交叉自动交换**。
- **alpha ≤ 0 透传**。
- C 超过色域的输入会被 clamp 到 132；输出 C 可以拉高，超出 sRGB 的部分由
  babl 转回 RGB 时裁掉（等价于 GIMP 色域警告里的那些像素）。

## 与 lb:lab-levels / lb:hue-saturation 的关系

| 需求 | 用哪个 |
|---|---|
| 单独压/提色度，色相不动 | 本算子（C 通道） |
| 单独转色相，色度不动 | 本算子（H 通道） |
| 分别调 a、b 两轴（比如只加黄不加绿） | `lb:lab-levels` |
| 按色相段分别调饱和度/明度（RAW 编辑器 风格） | `lb:hsl-seven` |

## 验证

`python tools/check_color_levels.py lch`（3 项）：

| 用例 | 判据 | 实测 |
|---|---|---|
| 恒等（默认参数） | 与源图逐像素 ≤1 码 | 最大 0 |
| 色度归零 | 全图中性（\|R−G\|、\|G−B\| ≤2） | 0 |
| 色相环 +180° | 色相环那一行 80% 以上采样点明显变色 | 72/72 |

LCh↔RGB 的转换在 babl 里，Python 无法复算，所以这里不做公式对拍——但
「C 归零必须得到中性灰」「H 转 180° 必须整环变色」这两条已经把转换方向和
色相环的拓扑覆盖住了；恒等能到 0 码，说明往返没有数值漂移。

## 已知事项

- H 在 C≈0（近中性色）时无意义，算子按 H=0 处理；此时调 H 不影响画面。
- H 的 360°/0° 是同一点，输出下限/上限给到 360 与 0 是等价的，界面不做
  特殊提示。
