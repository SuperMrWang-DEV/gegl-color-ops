# Calculations · 计算

> `lb:calculations` · 菜单 **颜色 → SuperMrWang → Calculations** · 双输入（input + aux）

对应 Photoshop 的 **图像 → 计算**：从两路各取一个通道（可以各自反相），按混合模式
算出灰度结果，输出成灰蒙版或 alpha 蒙版。

Replicates Photoshop's **Image → Calculations**: take one channel from each of two
sources (each optionally inverted), blend them, and output a grey or alpha mask.

## 参数 / Parameters

| 参数 | 默认 | 说明 |
|---|---|---|
| `source1-channel` | Luminance | 主输入取哪个通道：R/G/B/亮度/Alpha |
| `invert-source1` | 否 | 源 1 反相 |
| `source2-channel` | Luminance | aux 取哪个通道 |
| `invert-source2` | 否 | 源 2 反相 |
| `blend-mode` | Multiply | 26 种混合模式，与 PS 列表一致 |
| `opacity` | 100 | 混合强度 |
| `mask-enabled` | 否 | 再用一路通道做遮罩 |
| `mask-channel` | Luminance | 遮罩通道 |
| `invert-mask` | 否 | 遮罩反相 |
| `output-mode` | 灰蒙版 | 灰蒙版（贴图层蒙版）或 alpha 蒙版（直接当不透明度） |

## 与 PS 的对应关系 / How it maps to Photoshop

| PS | 这里 |
|---|---|
| Source 1: 图层 + 通道 + 反相 | input + `source1-channel` + `invert-source1` |
| Source 2: 图层 + 通道 + 反相 | aux + `source2-channel` + `invert-source2` |
| Blending / Opacity | `blend-mode` / `opacity` |
| Mask | `mask-channel` + `invert-mask` |
| Result: 新建文档 / 新建通道 | `output-mode` = 灰蒙版，得到的灰色层可当文档或通道用 |
| Result: 选区 | `output-mode` = alpha 蒙版，再配合 **选择 → 按 Alpha 转选区** |

PS 的「结果为选区」在 GEGL 里没法直接建立选区（算子只能输出像素），所以用
alpha 蒙版代替：把它当作图层的不透明度，或转成选区。PS 的「新建文档」也用
灰蒙版代替——灰蒙版单独复制一份就是灰度文档。

## 行为细节 / Behaviour notes

- **aux 没接时**第二路退化为本图，即「同一张图的两个通道互算」——这是计算最
  常用的场景（例如 R 与 G 相减做蒙版），单输入就能直接用。
- 差值类模式（Difference / Subtract / Divide）在混合后裁到 0..1，与 8bit 行为一致。
- 深色 / 浅色在单通道上下文里等价于变暗 / 变亮（只有一个通道，没有整像素概念）。
- 灰蒙版输出 alpha = 1，alpha 蒙版输出 alpha = 灰度值。

## 测试 / Testing

```bash
./build.sh
python tools/check_blend.py     # 含 3 个计算用例：叠底出灰、反相源 2、alpha 模式
```
