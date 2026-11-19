# Unsharp Mask · USM 锐化

> `lb:unsharp-mask` · 菜单 **SuperMrWang → Sharpen → Unsharp Mask** · 单输入

用「原图 − 模糊图」的差值把边缘加陡，是 Photoshop「锐化 → USM 锐化」的等价物，
并且把「智能锐化」真正想要的那件事——**不让硬边长出白边**——做成了一个滑杆。

Sharpens against a blurred copy, and turns the one thing Smart Sharpen is really
after — no white fringes along hard edges — into a slider.

## 参数 / Parameters

| 参数 | 范围 | 默认 | 含义 |
|---|---|---|---|
| `radius` 半径 | 0.1–100 | 2.0 | 参考模糊的半径（σ）。小半径锐化纹理，大半径做局部对比（清澈感） |
| `amount` 数量 | 0–500% | 100 | 差值加回去的比例，PS 的 Amount |
| `threshold` 阈值 | 0–255 | 0 | 差值小于这个码数判为平坦区，原样保留，避免放大颗粒 |
| `fringe` 光晕抑制 | 0–100% | 100 | 把结果夹到原图 3×3 邻域的 [min, max]，100 时完全不产生过冲 |

`fringe` 是这个名字的由来：普通 USM 在硬边两侧各留一条白边/黑边（fringe），
夹到邻域极值之后就没有了。

The word fringe is where the name comes from: plain unsharp masking leaves a
bright and a dark fringe on either side of a hard edge; clamping to the 3×3
neighbourhood removes them.

## 算法

1. **参考模糊**。σ ≤ 4 时用真高斯核做可分离卷积（半宽 3σ）；更大时改用
   **三次盒式模糊串联**——三次盒式的方差是 `3·((2r+1)²−1)/12`，反解
   `r = (√(4σ²+1) − 1)/2`。代价与半径无关（O(n) 而不是 O(n·σ)），
   而 σ ≥ 4 时两者分歧已小于 1/255。
2. **差值** `d = v − blur`。`|d| ≤ threshold/255` 直接输出原值。
3. **锐化** `v + amount·d`。
4. **光晕抑制**：取原图 3×3 的 `lo`/`hi`，把上一步结果夹进 `[lo, hi]`，
   再按 `fringe` 与未夹版本混合。

第 4 步的性质值得说清楚：**硬边上它等于不锐化**（3×3 里没有过渡可陡化），
**软边上它把过渡压陡但不过冲**。所以 100% 时这张图永远不会多出白边，
代价是高光的微弱溢出会被压掉——想要 PS 那种「亮部发光」的锐利感就把
`fringe` 调到 30–50。

## 用法 / Recipes

- **纹理锐化**：`radius=1.0 amount=120 threshold=3 fringe=100`
- **局部对比（清澈感）**：`radius=15 amount=40 threshold=0 fringe=60`
- **输出前最后一刀**：`radius=0.8 amount=90 threshold=2 fringe=100`，配合缩图后使用

## 与 Photoshop 的差异

| | PS USM | PS 智能锐化 | `lb:unsharp-mask` |
|---|---|---|---|
| 半径 / 数量 / 阈值 | 有 | 有 | 有 |
| 光晕抑制 | 无 | 「移去：高斯/镜头模糊」+ 高光/阴影淡化 | 3×3 极值夹取，0–100 可调 |
| 去卷积 | 无 | 「移去镜头模糊」是盲反卷积 | 无（本算子只做 USM） |

PS 的「锐化 / 进一步锐化 / 锐化边缘」是三个固定参数的 USM 预设，用本算子
配 `amount` 即可复现，不再单独出三个算子。

## 测试 / Testing

`python tools/check_noise_sharpen.py`：数量 0 与阈值 255 恒等、开/关光晕抑制的
过冲对比、软边过渡级数变少、硬边完全抑制时不变、alpha 透传。
