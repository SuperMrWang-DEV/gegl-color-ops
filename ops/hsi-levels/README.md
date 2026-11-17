# HSI Levels（lb:hsi-levels）

菜单：`颜色 → SuperMrWang → Levels → HSI Levels`（Filter 类）

## 概述

对 HSI 的 H / S / I 做独立色阶。HSI 是图像分析里常用的模型：**I 是三通道
均值**，比 HSV 的 max 更接近「这一块有多亮」，S 用 `1 − min/I` 度量「掺了
多少白」，色相则用余弦定义（与 HSV 的六边形角不是同一个角）。

这不是 GIMP/babl 自带的模型，转换在本工程的 `common/color-levels.h` 里。

## 色彩空间

| 分量 | 量程 | 定义 |
|---|---|---|
| H | 0–360° | `cos H = [(R−G)+(R−B)] / (2·√((R−G)²+(R−B)(G−B)))`，B>G 时取 `360−H` |
| S | 0–100% | `S = 1 − min(R,G,B)/I`，只掺白不掺黑（掺黑由 I 体现） |
| I | 0–100% | `I = (R+G+B)/3` |

三点必须说清，否则数值对不上：

1. **H 是余弦定义的角**，不是 HSV 的分量比角。两者在纯色上一致（红 0°、
   绿 120°、蓝 240°），但在中间色上会差几度。早期版本误用 HSV 的角配 HSI 的
   逆变换，实测纯色附近往返差 4 码；现在与逆变换严格互逆，恒等回到 0 码。
2. **S 的分母是 I**，不是 max。同一块暗红 HSI 的 S 会比 HSV 的 S 低得多。
3. **I 溢出会裁切**：`I` 接近 1 且 `S` 很大时，逆变换算出的通道值会超过 1
   （HSI 色域不是立方体），按 sRGB 裁到 `[0,1]`。

逆变换用 HSI 的余弦式，每 120° 一段：

```
H∈[0,120):  B = I(1−S),  R = I[1 + S·cos H / cos(60−H)],  G = 3I − R − B
```

（其余两段按 R→G→B 轮换。）

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

- **H 环形重映射**：主弧（黑场 → 白场）映到输出弧，剩余弧按比例跟进，
  两段共用 gamma；默认参数逐位还原；黑白场重合 = 纯色相旋转。
- **S / I 线性**：clamp → 归一化 → gamma → 输出范围，输出反向即反相。
  S 归零 → 全图中性灰；I 归零 → 全黑。
- 黑白场交叉自动交换；**alpha ≤ 0 透传**。

## 验证

`python tools/check_color_levels.py hsi`（3 项）：

| 用例 | 判据 | 实测 |
|---|---|---|
| 恒等（默认参数） | 与源图逐像素 ≤1 码 | 最大 0 |
| 饱和度归零 | 全图中性（\|R−G\|、\|G−B\| ≤2） | 0 |
| 公式对拍 | Python 复算 RGB→HSI→色阶→HSI→RGB，逐像素 ≤2 码 | 最大 1 |

公式对拍的参数：H 整体 +25°（整圈旋转）、S 0/100 → 20/80 γ=0.9、I 0/100 →
5/95，覆盖环绕映射、余弦逆变换与量程缩放。

## 已知事项

- HSI 与 HSV/HSL 的 S 不可互换：把 HSL 调好的「S=40%」搬到 HSI 上不是同一块
  颜色。要跨模型对照，看取色器里的 RGB 值。
- 高饱和高亮区域往返会有裁切（见上），恒等 0 码是 8 位量化意义下的；浮点
  精度下这些像素本身就是越出色域的。
- 计算量比另外四个大：每像素两次 `acosf`/`sqrtf` 级别的运算（另有 3 个分量
  查表），4K 图上比 `lab-levels` 慢一些。
