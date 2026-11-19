# Add Noise · 添加杂色

> `lb:add-noise` · 菜单 **SuperMrWang → Noise → Add Noise** · 单输入

给每个像素叠一层随机扰动。加胶片颗粒、做旧、掩盖 8 位渐变的色带都用它。
与 PS 的不同在于**种子可控**：同一张图、同一个种子，输出逐位相同。

Adds random noise per pixel. Unlike Photoshop, the seed is exposed, so the same
image and the same seed give byte-identical output.

## 参数 / Parameters

| 参数 | 范围 | 默认 | 含义 |
|---|---|---|---|
| `amount` 数量 | 0–100% | 10 | 噪点强度。高斯时 σ = 25% × amount，均匀时幅度 ±50% × amount |
| `distribution` 分布 | 高斯 / 均匀 | 高斯 | 高斯像胶片与传感器噪点；均匀像数字抖动 |
| `monochrome` 单色 | 开 / 关 | 关 | 三个通道共用同一个扰动，得到灰度颗粒而不是彩色噪点 |
| `seed` 种子 | 0–999999 | 1 | 决定随机序列，用于复现 |

## 算法

按**行**播种：第 `y` 行的种子由 `seed` 与 `y` 混合得到（`y` 参与哈希，
不是简单相加），因此分带处理与整张处理逐位相同——这是「可复现」能成立的前提。
高斯用 Box–Muller：

```
u1, u2 ~ U(0,1]
n = sqrt(−2 ln u1) · cos(2π u2)
```

三个通道各自取一个 `n`；`monochrome` 时只取一次，三个通道共用。

`alpha` 完全不动：叠噪点改的是像素值，不是图层透明度。

## 用法 / Recipes

- **胶片颗粒**：`amount=8 distribution=gaussian monochrome=on`
- **掩盖 8 位色带**：`amount=3 distribution=uniform monochrome=on`，再叠 1px 模糊
- **做旧**：`amount=15 distribution=gaussian`，配合 `lb:reduce-noise` 反向调节

## 与 Photoshop 的差异

| | PS 添加杂色 | `lb:add-noise` |
|---|---|---|
| 数量 / 分布 / 单色 | 有 | 有 |
| 可复现 | 无（每次应用都换随机数） | **有**（同种子逐位相同） |
| 影响 alpha | 不动 | 不动 |

## 测试 / Testing

`python tools/check_noise_sharpen.py`：数量 0 恒等、同种子逐位相同、换种子不同、
单色时三通道相等、均值不偏移、α 透传。
