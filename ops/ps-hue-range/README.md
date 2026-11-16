# GEGL_GIMP_PLUGIN_ps-hue-range

## English

**Hue/Saturation Range** — per-family hue, saturation and lightness inside a
soft four-handle hue range. Chain it after **Hue/Saturation (Basic)** (master,
whole image) and use **Colorize** for tinting: the three operators together
reproduce the classic Hue/Saturation dialog (edit dropdown + colour bar +
colorize checkbox).

### Parameters

| Property | Default | Meaning |
|---|---|---|
| Channel Range | Reds | Reds / Yellows / Greens / Cyans / Blues / Magentas |
| Falloff Left / Range Left / Range Right / Falloff Right | -1 | The four colour-bar handles. Inner two select fully (weight 1); the bands out to the outer two ramp **linearly**. -1 follows the family default (centre ±15 selected, ±45 falloff); dragged values are absolute degrees 0–360 |
| Hue | 0 | Rotation in degrees, scaled by the per-pixel range weight |
| Saturation | 0 | Relative saturation in percent (same formula as the master op) |
| Lightness | 0 | Percent, positive blends toward white, negative toward black |

### Family defaults (degrees)

| Family | Falloff L | Range L | Range R | Falloff R |
|---|---|---|---|---|
| Reds | 315 | 345 | 15 | 45 |
| Yellows | 15 | 45 | 75 | 105 |
| Greens | 75 | 105 | 135 | 165 |
| Cyans | 135 | 165 | 195 | 225 |
| Blues | 195 | 225 | 255 | 285 |
| Magentas | 255 | 285 | 315 | 345 |

### Algorithm notes

- The weight is computed on the **original** hue (before any adjustment),
  like an internal mask; achromatic pixels (R = G = B) join no family.
- Adjustments scale by the weight and reuse the exact master-op formula
  (lightness screen/multiply → HSL → hue add → relative saturation scale):
  at weight 1 the result is bit-identical to Hue/Saturation (Basic); at
  weight 0 the pixel is untouched.
- Handles may be dragged across 0/360; the range is unwrapped around its
  inner span so wrap-around ranges behave.

### Verification

`tools/check_ps_hue_range.py` renders a nine-patch swatch card through gegl
and compares every pixel against a line-by-line Python reference:
8 cases (defaults, weight-scaled hue, saturation to full, lightness,
wrap-around handles, green family, and a chained master → range run) all
match to **0.0 codes** (216 sample points, tolerance 2).

## 中文

**色相/饱和度·范围** —— 在一个色相族的软范围内调整色相、饱和度、明度。
与 **Hue/Saturation (Basic)**（全图/Master）串联，再用 **Colorize** 着色：
三个算子合起来复刻经典「色相/饱和度」对话框（编辑下拉 + 底部色条 + 着色）。

### 参数

| 属性 | 默认 | 含义 |
|---|---|---|
| 色系范围 | 红系 | 红 / 黄 / 绿 / 青 / 蓝 / 品红 |
| 过渡左 / 范围左 / 范围右 / 过渡右 | -1 | 色条四柄：内二柄之间全选（权重 1），向外二柄**线性**过渡。-1 = 跟随色系默认（中心 ±15 全选、±45 过渡）；拖动后为绝对角度 0–360 |
| 色相 | 0 | 旋转角度，按逐像素范围权重缩放 |
| 饱和度 | 0 | 相对饱和度百分比（与全图算子同一公式） |
| 明度 | 0 | 百分比，正向混白、负向混黑 |

### 色系默认范围（度）

| 色系 | 过渡左 | 范围左 | 范围右 | 过渡右 |
|---|---|---|---|---|
| 红 | 315 | 345 | 15 | 45 |
| 黄 | 15 | 45 | 75 | 105 |
| 绿 | 75 | 105 | 135 | 165 |
| 青 | 135 | 165 | 195 | 225 |
| 蓝 | 195 | 225 | 255 | 285 |
| 品红 | 255 | 285 | 315 | 345 |

### 算法要点

- 权重作用在【原始】色相上（先算 w 再调整），语义与内部蒙版一致；
  无彩像素（R=G=B）不参与任何色系。
- 调整量按 w 缩放后走全图算子的同一套公式（明度 screen/multiply → HSL →
  色相加法 → 饱和度相对缩放）：w=1 时与 Hue/Saturation (Basic) 逐位一致，
  w=0 时逐位等于原图。
- 四柄可拖过 0/360，实现按内区跨度解环绕。

### 验收

`tools/check_ps_hue_range.py`：9 色块色卡过 gegl，与 Python 参考实现
（逐字同式）逐像素对比——8 个用例（默认范围、权重缩放色相、饱和度拉满、
明度、环绕柄、绿系、链式 Master→Range）216 个采样点全部 **0 码**。
