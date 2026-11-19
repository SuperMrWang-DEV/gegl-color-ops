# Dust & Scratches · 蒙尘与划痕

> `lb:dust-scratches` · 菜单 **SuperMrWang → Noise → Dust & Scratches** · 单输入

把与周围差得太远的孤立像素（灰尘、划痕、传感器坏点）用邻域中值替换，
同时尽量不动真实的边缘与细节。PS「杂色 → 蒙尘与划痕」的等价物。

Replaces isolated pixels with the median of their neighbours. Photoshop's
Dust & Scratches, with one deliberate difference explained below.

## 参数 / Parameters

| 参数 | 范围 | 默认 | 含义 |
|---|---|---|---|
| `radius` 半径 | 1–10 | 2 | 邻域半径，1 即 3×3。越大去掉的斑点越大，细节也丢得越多 |
| `threshold` 阈值 | 0–255 | 0 | 与中心差超过这个码数的邻居**不参与**取中值。阈值就是「多大的差才算灰尘」 |

## 算法

对每个像素、每个通道：

1. 收集半径 `r` 内所有满足 `|v − v₀| ≤ threshold` 的邻居——**中心自己不算**；
2. 取这些值的中值；
3. 一个合格的都没有时，退回整窗（去中心）的中值。

用中值而不是均值，是因为中值不会被少数极端值拉动：一个亮斑在均值里会被摊成
一个更大的灰斑，在中值里直接被丢掉。

**中心自己不入集合**是与「直接套中值滤波」的关键差别。灰尘之所以是灰尘，
就因为它和周围都不一样；把它算进集合，它自己就会当选，等于什么都没做。
第 3 步的兜底是为了硬边正中——那里两侧邻居都不合格，此时宁可轻微平滑，
也不要留下一个孤点。

## 用法 / Recipes

- **扫底片灰尘**：`radius=1 threshold=12`
- **去传感器坏点**：`radius=2 threshold=30`
- **柔化皮肤小瑕疵**：`radius=3 threshold=18`，只做局部

半径与阈值是一对反向旋钮：`threshold=0` 时就是纯中值滤波（很糊），
阈值开到 30 以上才只动「明显不对」的像素。

## 与 Photoshop 的差异

| | PS 蒙尘与划痕 | `lb:dust-scratches` |
|---|---|---|
| 半径 / 阈值 | 有 | 有 |
| 中值集合是否含中心 | 含（阈值 0 时等于纯中值） | **不含**，孤点在阈值很大时也能去掉 |
| 全不合格时的行为 | 保持原值 | 退回整窗中值（硬边不糊，孤点不残留） |

## 测试 / Testing

`python tools/check_noise_sharpen.py`：孤立亮点被抹掉、硬边不动、纯色图不变、α 透传。
