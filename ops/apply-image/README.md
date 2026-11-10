# Apply Image · 应用图像

> `lb:apply-image` · 菜单 **颜色 → SuperMrWang → Apply Image** · 双输入（input + aux）

对应 Photoshop 的 **图像 → 应用图像**：把一张图（另一个图层 / 另一个文件）当作源，
按混合模式、不透明度、遮罩压到当前图层上，还可以只作用于某一个通道。

Replicates Photoshop's **Image → Apply Image**: takes a second image as the source,
blends it onto the current layer with a blend mode, opacity and mask, optionally
into a single channel.

## 参数 / Parameters

| 参数 | 默认 | 说明 |
|---|---|---|
| `blend-mode` | Multiply | 26 种混合模式，顺序与 PS 一致（Normal … Divide、Darker/Lighter Color、Hue … Luminosity） |
| `opacity` | 100 | 混合强度，0 = 不动，100 = 完全应用 |
| `target-channel` | Composite | 结果写回哪个通道；可选整个合成或单个 R/G/B/亮度/Alpha |
| `source-channel` | Composite | 从 aux 取哪个通道作为源 |
| `mask-enabled` | 否 | 用一路通道当遮罩 |
| `mask-from` | Source layer | 遮罩取自 aux 还是本层 |
| `mask-channel` | Composite | 遮罩通道（Composite 取亮度） |
| `invert-mask` | 否 | 遮罩反相 |
| `preserve-transparency` | 否 | 全透明像素保持不动（PS 的「保留透明区域」） |
| `output-mode` | Composite | 输出合成结果 / 灰蒙版 / alpha 蒙版 |

## 与 PS 的对应关系 / How it maps to Photoshop

| PS | 这里 |
|---|---|
| Source: 图像 + 图层 | `aux` pad，在滤镜对话框里选 |
| Source: 通道 | `source-channel` |
| Target: 通道 | `target-channel` |
| Blending / Opacity | `blend-mode` / `opacity` |
| Preserve Transparency | `preserve-transparency` |
| Mask: 图层 + 通道 + 反相 | `mask-from` + `mask-channel` + `invert-mask` |

PS 的遮罩可以指向**第三张**图（既不是目标也不是源），GEGL 的 composer 只有
两个输入，所以这里限定在「本层」或「源层」二选一——实际用法里这两处覆盖了
绝大多数场合。

PS's mask may point at a *third* image. A GEGL composer only exposes two inputs,
so the mask is limited to either the target or the source, which covers the
common cases.

## 行为细节 / Behaviour notes

- **aux 没接时**源退化为本图，可以用来做「同图内通道互混」；
  Without an aux connected the source falls back to the input itself.
- 目标是单通道时只改那一个通道，其余原样保留；源是合成时取亮度作标量。
  With a single-channel target only that channel changes; a composite source is
  reduced to luminance.
- 深色 / 浅色（Darker / Lighter Color）比较整像素亮度后取其中一方**全部通道**，
  不是逐通道取最小/最大——这一点和「变暗 / 变亮」不同。
- 在 8bit sRGB 伽马域计算，与 PS 的混合模式定义同域；结果会裁到 0..1。
- GIMP 里这类带 aux 的滤镜目前**只能合并应用**，不能保存成非破坏性 fx。

## 测试 / Testing

```bash
./build.sh              # 顺带编译出 build/auxrun（双输入 runner）
python tools/check_blend.py
```
