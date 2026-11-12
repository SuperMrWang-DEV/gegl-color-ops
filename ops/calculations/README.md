# Calculations · 计算

> `lb:calculations` · 菜单 **颜色 → SuperMrWang → Blend → Calculations** · 双输入（input + aux）

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

## 想要选区 / 通道：手动三步 / Getting a selection or channel by hand

GEGL 算子只能产出像素，碰不到选区、通道、图层这些图像对象，所以 PS 计算对话框
里的 Result 下拉在这里只能落到「灰蒙版 / alpha 蒙版」。要选区或通道，不改代码也
能做到：

1. **Ctrl+Shift+D 复制图层**——**必做**。GEGL 滤镜是直接改当前图层的像素，不像 PS
   的计算那样不碰原图，在副本上跑才不会把原图换掉。
2. 在副本上跑 **Colors → SuperMrWang → Blend → Calculations**，`Output` 选
   **Mask (alpha)**。这一步是关键：alpha 版把灰度写在图层的 alpha 上，才能用
   「alpha → 选区」；选灰蒙版的话 alpha 恒为 1，转出来是全选。
3. 拿选区：`Filters → Python-Fu → Console` 粘一行

   ```python
   img = Gimp.get_images()[0]
   img.select_item(Gimp.ChannelOps.REPLACE, img.get_selected_layers()[0])
   ```

   （`select_item` 就是「把某个 item 的 alpha 变成选区」，图层和通道都收。）
   要通道就接着用 **选择 → 保存到通道**（`gimp-selection-save`）。

需要成品的灰度图层当文档用，就在第 2 步选 `Mask (grey)`，然后「图层 → 复制图层 →
粘贴为新图像」。

`plugin/blend` 里的 Python 插件版把这几步做成了对话框里的 Result 选项（选区 /
新建 Alpha 通道 / 灰图层 / 写入图层 alpha），但插件目前是停用状态，见根目录
README「Python 插件版」。

GEGL ops can only return pixels — they cannot create selections, channels or layers —
so PS's Result drop-down collapses to grey / alpha mask here. The three steps above
get you the other two by hand. Note that the duplicate in step 1 is mandatory: a
GEGL filter rewrites the layer it runs on, unlike PS's Calculations.

## 行为细节 / Behaviour notes

- **aux 没接时**第二路退化为本图，即「同一张图的两个通道互算」——这是计算最
  常用的场景（例如 R 与 G 相减做蒙版），单输入就能直接用。
- 差值类模式（Difference / Subtract / Divide）在混合后裁到 0..1，与 8bit 行为一致。
- 深色 / 浅色在单通道上下文里等价于变暗 / 变亮（只有一个通道，没有整像素概念）。
- 灰蒙版输出 alpha = 1，alpha 蒙版输出 alpha = 灰度值。
- **通道编号**：枚举第 0 位留给 Composite 占位（`enum_value_skip`，不出现在
  下拉列表里），这样 `Red/Green/Blue/Luminance/Alpha` 的编号才和
  `common/blend.h` 的 `LB_CH_*` 对得上。少这个占位会让整张表错一位——默认的
  Luminance 实际取到蓝通道。
- **源 2 的透明像素不参与计算**：源层是抠图、文字层或带透明背景的图层时，
  透明区的 RGB 是 0，当作「黑数据」算进去会把蒙版算成一片黑。这里用源 2 的
  alpha 当覆盖率：alpha = 0 处蒙版输出 0（不选中），半透明柔边按比例衰减。
  源 2 通道选 Alpha 时，那个 alpha 是数据不是覆盖率，不重复相乘。
  Transparent pixels of source 2 take no part: on a cut-out the holes hold
  RGB 0, which would compute a solid black mask. Source 2's alpha is used as
  coverage — 0 gives a 0 mask (not selected), and soft mattes fade. When
  source 2's channel *is* alpha, that value is data, not coverage.
- **源层比主图小 / 带偏移**：aux 没覆盖到的像素按黑色参与计算（蒙版那里就是
  0）。PS 的计算要求两个来源同尺寸，这里不强制，缺的部分当黑。

## 测试 / Testing

```bash
./build.sh
python tools/check_blend.py     # 含 9 个计算用例：叠底出灰、反相源 2、alpha 模式、四种通道取值、
                               # 源层透明与半透明覆盖率
```
