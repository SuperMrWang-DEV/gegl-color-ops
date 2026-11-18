> 本文件是该滤镜的原始说明文档（构建命令按旧目录结构书写，已过时）。
> 统一构建方式请见工程根目录 `README.md` 与 `build.sh`。

# GEGL_GIMP_PLUGIN_rgb-domain-grayscale

![rgbdomaingrayscale](assets/rgbdomaingrayscale.png "rgbdomaingrayscale")

## English

### 1. Compile & Install Commands

#### Native Linux (System installed GIMP)

```bash
sh build_linux.sh
cp build/gegl-*.so ~/.local/share/gegl-0.4/plug-ins
```

#### Flatpak Linux (Flatpak GIMP)

```bash
sh build_linux.sh
cp build/gegl-*.so ~/.var/app/org.gimp.GIMP/data/gegl-0.4/plug-ins/
```

### 2. How to Open the Plugin (2 Methods)

After installation, **restart GIMP** to activate the plugin.

#### Method 1: Menu Bar (Recommended)

Menu path: `Colors → SuperMrWang → Tone → Black & White`

#### Method 2: GEGL Operation

1. Go to `Filters → Generic → GEGL Operations`
2. In the search box, enter: `lb:rgb-domain-grayscale`
3. Select it and click `OK` to apply

---

## 中文

### 1. 编译与安装命令

#### Linux 原生版（系统包安装的GIMP）

```bash
sh build_linux.sh
cp build/gegl-*.so ~/.local/share/gegl-0.4/plug-ins
```

#### Linux Flatpak 容器版（应用商店Flatpak GIMP）

```bash
sh build_linux.sh
cp build/gegl-*.so ~/.var/app/org.gimp.GIMP/data/gegl-0.4/plug-ins/
```

### 2. 插件打开方式（两种方法）

安装完成后**重启 GIMP**，插件即可使用。

#### 方法一：菜单打开（推荐）

菜单路径：`SuperMrWang → Tone → Black & White`

#### 方法二：GEGL 操作打开

1. 顶部菜单点击：`滤镜 → 通用 → GEGL 操作`
2. 在弹出窗口的搜索框输入：`lb:rgb-domain-grayscale`
3. 选中后点击「确定」即可使用插件

---

## Algorithm

Six hue sliders (red / yellow / green / cyan / blue / magenta) decide how much each
colour contributes to the grey result, and the result can then be tinted — the
classic editor's Black & White dialog: pull blue down to darken a sky, push yellow up
to brighten skin, everything else stays put.

For each pixel the three channels are sorted into $v_{\max} \ge v_{\text{mid}} \ge v_{\min}$.
Two weights apply: the slider of the **max channel's colour**, and the slider of the
"between" colour (yellow for R+G, cyan for G+B, magenta for B+R):

```math
v_{\max},\ v_{\text{mid}},\ v_{\min}\ \text{sorted} \quad\Rightarrow\quad
g = (v_{\max}-v_{\text{mid}})\,w_{\max} + (v_{\text{mid}}-v_{\min})\,w_{\text{hue}} + v_{\min}
```

Slider range −200…300 matches the classic editor dialog; the defaults (red 40,
yellow 60, green 40, cyan 60, blue 20, magenta 80) are taken from it.

### Tint

Tinting reproduces the classic editor's own maths, calibrated black-box against it
(18 tints, per-code agreement — see `bw-cal/RESULTS.md`). It is **not** a
`grey × colour` multiply. With tint $t=(t_R,t_G,t_B)$ and NTSC luma
$L = 0.3\,t_R + 0.59\,t_G + 0.11\,t_B$ (encoding domain), each output channel is:

```math
\text{out}_{ch} = \begin{cases}
(t_{ch}-t_{\min})\cdot \dfrac{g}{\,L-t_{\min}\,}, & g \le L-t_{\min} \quad \text{(bottom)} \\[8pt]
g + t_{ch} - L, & \text{otherwise} \quad \text{(middle)} \\[8pt]
1-(t_{\max}-t_{ch})\cdot \dfrac{1-g}{\,t_{\max}-L\,}, & g \ge 1-(t_{\max}-L) \quad \text{(top)}
\end{cases}
```

then pulled back toward grey by the strength slider, $\text{out}_{ch} \leftarrow
g + (\text{out}_{ch}-g)\cdot s$. The three pieces join continuously and the top/bottom
ones pass exactly through white/black, so a tinted image keeps its full tonal range.

```mermaid
flowchart TD
  A["像素 r, g, b<br/>排序成 max / mid / min"] --> B["按 max–mid 的通道组合<br/>取「最大值色相」+「夹色」两根滑杆"]
  B --> C["g = (max−mid)·w₁ + (mid−min)·w₂ + min"]
  C --> D{"着色开？"}
  D -- "否" --> E["输出中性灰"]
  D -- "是" --> F["三段 SetLum<br/>中段 g + t − L；顶/底段向白 / 黑收缩"]
  F --> G["按强度回插<br/>彩色输出"]
```

## Parameters

| parameter | default | meaning |
|---|---|---|
| `red` / `yellow` / `green` | 40 / 60 / 40 | hue weights, −200…300 |
| `cyan` / `blue` / `magenta` | 60 / 20 / 80 | hue weights, −200…300 |
| `tint_enabled` | off | tint the grey result |
| `tint_color` | `#E0D4B2` | tint colour (warm brown by default) |
| `tint_strength` | 1 | tint strength, 0…1 |

## Notes

- Per-pixel, in the 8-bit sRGB gamma domain, so the sliders feel like the classic
  editor dialog.
- Alpha is preserved; transparent pixels stay transparent.
- Unlike GIMP's Desaturate, the grey value is not a fixed luminance formula — what
  each colour turns into is up to you, which is the whole point of Black & White.

---

## 算法

六个色相滑杆（红 / 黄 / 绿 / 青 / 蓝 / 品红）决定每种颜色对灰度的贡献，
结果还可以着色——就是 经典图像编辑器的「黑白」对话框：把蓝拉低压暗天空，把黄推高提亮肤色，
其余部分不受影响。

逐像素把三通道排序成 $v_{\max} \ge v_{\text{mid}} \ge v_{\min}$，用到两个权重：
**最大值通道**的色相滑杆，以及夹在中间的那根滑杆（红+绿用黄、绿+蓝用青、蓝+红用品红）：

```math
g = (v_{\max}-v_{\text{mid}})\,w_{\max} + (v_{\text{mid}}-v_{\min})\,w_{\text{夹色}} + v_{\min}
```

滑块量程 −200…300 与经典图像编辑器界面一致，默认值
（红 40、黄 60、绿 40、青 60、蓝 20、品红 80）取自 经典图像编辑器。

### 着色

着色走的是经典图像编辑器自己的算法（18 组色相 × 饱和度黑盒标定，逐码吻合，见
`bw-cal/RESULTS.md`），**不是**「灰度 × 颜色」的乘法。记着色 $t=(t_R,t_G,t_B)$，
NTSC 亮度 $L = 0.3\,t_R + 0.59\,t_G + 0.11\,t_B$（编码域），每个输出通道：

```math
\text{out}_{ch} = \begin{cases}
(t_{ch}-t_{\min})\cdot \dfrac{g}{\,L-t_{\min}\,}, & g \le L-t_{\min} \quad \text{（底部）} \\[8pt]
g + t_{ch} - L, & \text{其余} \quad \text{（中段）} \\[8pt]
1-(t_{\max}-t_{ch})\cdot \dfrac{1-g}{\,t_{\max}-L\,}, & g \ge 1-(t_{\max}-L) \quad \text{（顶部）}
\end{cases}
```

再按强度滑杆往灰度回插：$\text{out}_{ch} \leftarrow g + (\text{out}_{ch}-g)\cdot s$。
三段在断点处连续，顶/底两段精确过白/黑端点，所以着色后整幅图的明暗层次不会塌掉。

```mermaid
flowchart TD
  A["像素 r, g, b<br/>排序成 max / mid / min"] --> B["按 max–mid 的通道组合<br/>取「最大值色相」+「夹色」两根滑杆"]
  B --> C["g = (max−mid)·w₁ + (mid−min)·w₂ + min"]
  C --> D{"着色开？"}
  D -- "否" --> E["输出中性灰"]
  D -- "是" --> F["三段 SetLum<br/>中段 g + t − L；顶/底段向白 / 黑收缩"]
  F --> G["按强度回插<br/>彩色输出"]
```

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `red` / `yellow` / `green` | 40 / 60 / 40 | 各色系的权重，−200…300 |
| `cyan` / `blue` / `magenta` | 60 / 20 / 80 | 各色系的权重，−200…300 |
| `tint_enabled` | 关 | 给灰度结果着色 |
| `tint_color` | `#E0D4B2` | 着色颜色（默认是暖棕） |
| `tint_strength` | 1 | 着色强度，0…1 |

## 说明

- 逐像素在 8 位 sRGB 伽马域计算，滑块手感与经典图像编辑器对话框一致。
- alpha 保留，透明像素仍然透明。
- 与 GIMP 的「去色」不同：这里的灰度不是固定亮度公式，每种颜色变成什么由你决定，
  这正是「黑白」的用处。
