# HSL Levels（lb:hsl-levels）

菜单：`SuperMrWang → Levels → HSL Levels`（Filter 类）

## 概述

对 HSL 的 H / S / L 三个分量各自做独立的色阶：输入黑场/白场、gamma、
输出下限/上限。和 RGB 色阶相比，它改的是**感知意义上的三个维度**：色相、
饱和度、明度各走各的曲线，互不串扰。

## 色彩空间

直接工作在 babl 的 `HSLA float` 上，RGB↔HSL 交给 babl——与 GIMP 的
「分解 → HSL」「提取分量 → HSL 饱和度/明度」用同一套转换，算子内部没有
自己写的色彩转换代码。

- H：0–360°，内部是 babl 的 0–1 归一化值，界面按度数给
- S：0–100%，定义是 `S = (max−min) / (1 − |2L−1|)`（HSL 的 S，不是 HSV 的）
- L：0–100%，`L = (max+min)/2`

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

- **色相是环形的**，不能像普通通道那样 clamp。做法是把圆在黑场处剪开：
  主弧「黑场 → 白场（顺时针）」线性映到输出弧「输出下限 → 输出上限」，
  剩下的弧按比例映到剩余的弧长，两段共用 gamma。整圈上连续，
  默认参数（0/360 → 0/360，γ=1）逐位还原。
- **黑白场重合 = 整圈**：把输入黑白场拉到同一个角度，等于「纯色相旋转 +
  gamma 环绕」，而不是塌成单色。
- **S/L 是普通线性通道**：clamp 到输入范围 → 归一化 → gamma → 映射到输出
  范围。输出反向（下限 > 上限）会得到负片式的反相。
- **黑白场交叉自动交换**，滑杆拉过头不会算出负区间。
- **alpha ≤ 0 的像素原样透传**，色彩不再被映射。

## 与 lb:lab-levels 的关系

`lab-levels` 在 CIE Lab 上做，a/b 是两极性通道（gamma 绕中性轴 0 转动）；
这里在 HSL 上做，三个分量都是「单极性」的 0 起量，所以 gamma 语义就是普通
色阶。要按感知亮度调明度用 `lab-levels` 的 L；要让**某一范围的色相**挪位置、
或者把饱和度按明度分开处理，用这个。

## 验证

`python tools/check_color_levels.py hsl`（5 项）：

| 用例 | 判据 | 实测 |
|---|---|---|
| 恒等（默认参数） | 与源图逐像素 ≤1 码 | 最大 0 |
| 饱和度归零 | 全图 \|R−G\|、\|G−B\| ≤2 | 0 |
| 明度归零 | 全图最亮通道 ≤12 | 0 |
| 公式对拍 | Python 复算同一条链路（弧重映射 + gamma + HSL 往返），逐像素 ≤2 码 | 最大 1 |
| 透明像素透传 | alpha=0 行的 RGB 完全不动 | 0 |

公式对拍用的是带 gamma 与交叉黑白场的一组参数（H 30/330 → 0/300，γ=1.4；
S 10/90 → 0/100，γ=0.8；L 5/95，γ=1.1），所以环形映射的两段、gamma 方向、
输出量程都被覆盖到了。

## 已知事项

- 中性色（S=0）的色相没有定义，算子按 H=0 处理；S 归零后 H 怎么调都不影响
  画面，这是 HSL 本身的性质。
- 8 位图里相邻色相的量化台阶在色相环上约 1.4°，色相曲线拉得很陡时会出现
  轻微色带，建议在 16 位/浮点精度下操作。
