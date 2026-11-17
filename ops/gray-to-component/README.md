# lb:gray-to-component · 灰度转分量

通道灰度调色工作流里的**编码器**：把分解出来的分量灰度层，重新编码成
「携带该分量」的彩色层，交给 GIMP 的分量混合模式读回去。

它是 `HSV Split (Curves)` / `LCh Split (Curves)` 两个插件的最后一步——把原来
「scale 加三条 gimp:curves」压成**一个滤镜**，图层面板里每张分量层只剩
extract → curve → encode 三条。

```
原图 ──分解──> 分量灰度层（H / S / L / C …）
                    │
                    ▼
            lb:gray-to-component   ← 本算子：灰度 → 该分量的彩色表示
                    │
                    ▼
        混合模式还原（GIMP「颜色」组 9 个模式 + Lighten 叠合）
```

## 输入是什么

灰度层的**像素值就是分量数值**（`component-extract` 的输出就是这种层）：
`hue` 层里 0.5 表示 180°，`lab-l` 层里 0.5 表示 L*=50。算子取 R 通道作 g、
alpha 原样透传。

`input-space` 决定像素值读在哪个域：

| 值 | 用在哪 | 栈缓冲格式 |
|---|---|---|
| `encoded`（默认） | 8/16 位图层 | `R'G'B'A float` |
| `linear` | 32 位浮点线性图 | `RGBA float` |

选错会让 babl 多插一次 gamma，编码值整体偏亮——旧版固定声明 `YA float`
（= 把数值当线性亮度）在 8 位图上往返偏 83–255 码，就是这么来的。

为什么需要这一步：**灰度像素的色相和饱和度是无定义的**。把分解出的 H 灰度层
直接设成「色相」混合模式毫无效果——混合模式从灰里读不出色相。必须先把它编
码成色环上的真实颜色，混合模式才有东西可读。GIMP 的分解和混合模式都是现成
的，唯独中间这一步没有，本算子补的就是这一环。

## 模式表（编码公式经 hsl-cal 恒等往返实测校准）

GIMP 3 把分量类混合模式集中在「颜色」组，共 9 个：**Hue / Saturation / Color /
Value / LCh Hue / LCh Chroma / LCh Color / LCh Lightness / Luminance**。本算子
每个都能喂，另外多给三个 RGB 单通道模式。

| 模式 | 灰度 g 的语义 | 输出编码 | 配哪个混合模式还原 |
|---|---|---|---|
| `hue` | HSL 色相 h/360 | `hsl_to_rgb(g·360°, S=1, L=0.5)`，饱和度亮度拉满的色相轮 | **Hue**（HSV_HUE） |
| `saturation` | HSV 饱和度 s | `hsv_to_rgb(sat_hue, s, V=1)`，默认红相 | **Saturation**（HSV_SATURATION） |
| `color` | HSL 色相 h/360 | `hsl_to_rgb(g·360°, color_sat, L=0.5)`，饱和度由参数固定 | **Color**（HSL_COLOR） |
| `value` | HSV 明度 V | `(g,g,g)` 中性灰（V 就是最大通道） | **Value**（HSV_VALUE） |
| `lightness` | CIE 明度 L/100 | `Lab(g·100, 0, 0)` 直写 | **LCh Lightness**（LCH_LIGHTNESS） |
| `luminance` | 同上（CIE 亮度 Y） | 与 `lightness` 逐字节相同 | **Luminance**（LUMINANCE） |
| `red` / `green` / `blue` | 该通道值 | `(g,0,0)` / `(0,g,0)` / `(0,0,g)` | **Lighten** 三层叠合 |
| `lch-hue` | CIE 色相 h/360 | `Lab(lch_l, C·cos h, C·sin h)`，C = `lch_c` | **LCh Hue**（LCH_HUE） |
| `lch-color` | 同上（h，C 由参数固定） | 与 `lch-hue` 逐字节相同 | **LCh Color**（LCH_COLOR） |
| `lch-chroma` | CIE 色度 C/chroma_scale | `Lab(lch_l, C·cos h₀, C·sin h₀)`，h₀ = `lch_h` | **LCh Chroma**（LCH_CHROMA） |

两组「同编码」不是偷懒，是混合模式的语义决定的：

- **`luminance` ≡ `lightness`**：Luminance 读 CIE 亮度 Y，中性灰的 Lab L 与 Y
  单调对应，同一份 `Lab(L,0,0)` 同时给出正确的 L 和 Y。
- **`lch-color` ≡ `lch-hue`**：LCh Color 只读色相 + 色度，而 `lch-hue` 的色度
  本来就由 `lch-c` 固定住了。单列一条纯粹是让人按 GIMP 的模式名对号入座。

把上表写成式子（$g$ 是输入的灰度，$c_s$、$L_0$、$C$、$h_0$ 是参数）：

```math
\begin{aligned}
\text{hue}:\quad & \operatorname{HSL2RGB}(360°g,\ 1,\ \tfrac{1}{2}) \\
\text{saturation}:\quad & \operatorname{HSV2RGB}(h_{\text{sat}},\ g,\ 1) \\
\text{color}:\quad & \operatorname{HSL2RGB}(360°g,\ c_s,\ \tfrac{1}{2}) \\
\text{value}:\quad & (g,\ g,\ g) \\
\text{lightness} \equiv \text{luminance}:\quad & \operatorname{Lab}(100g,\ 0,\ 0) \\
\text{lch-hue} \equiv \text{lch-color}:\quad & \operatorname{Lab}\bigl(L_0,\ C\cos 360°g,\ C\sin 360°g\bigr) \\
\text{lch-chroma}:\quad & \operatorname{Lab}\bigl(L_0,\ C\cos h_0,\ C\sin h_0\bigr) \\
\text{red/green/blue}:\quad & (g,0,0)\ /\ (0,g,0)\ /\ (0,0,g)
\end{aligned}
```

**Color 的单通道困境**：Color 模式要同时读色相和饱和度，可一层灰度只有一个
标量。本算子的取舍是「灰度携带色相，饱和度由 `color-sat` 给定」——想整幅换色
同时压饱和度，就把 `color-sat` 调到 45%，比先 `hue` 再叠一层降饱和简单。

三个校准出来的硬结论（hsl-cal 实测，误差按 0–255 计）：

1. **HSL 的 S ≠ HSV 的 S**。GIMP 的 Saturation 模式读的是 HSV 语义，拿 HSL 分解
   出的 S 层直接编码，误差高达 214/255。本算子的 `saturation` 模式按 HSV 语义
   编码，恒等往返误差 <2。
2. **HSL 色相与 CIE 色相不可线性互转**。把 `h·360` 直接当 LCh 色相用，误差
   139/255。两套色轮必须各自分解、各自编码——这就是 `hue` 和 `lch-hue` 两个
   模式不能合并的原因。
3. **编码层要工作在 float32**。8-bit 图像下 Lab/LCh 编码写入图层会被量化，
   色相/色度被打碎（这也是普通 8-bit 图上这套流程精度有限的固有原因）；
   float32 下连超出 sRGB 色域的 LCh 值都能原样往返。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `mode` | `hue` | 见上表 |
| `sat-hue` | 0（红） | `saturation` 模式用的色相。该层只提供饱和度，色相在还原时不进入结果，取值不影响最终画面 |
| `color-sat` | 100 | `color` 模式固定的饱和度百分比。100% 时输出与 `hue` 相同；调低即「换色 + 降饱和」 |
| `lch-l` | 54 | LCh 模式用的固定明度。混合模式只读色相/色度时此值不进结果，取中庸值以留在常见色域内 |
| `lch-c` | 30 | `lch-hue` / `lch-color` 用的固定色度。越大越鲜艳，过大可能超出 sRGB 色域 |
| `lch-h` | 30 | `lch-chroma` 模式用的固定色相角（0=红），同样不进结果 |
| `chroma-scale` | 100 | `lch-chroma` 的满量程（灰度 1.0 对应多少色度）。sRGB 的蓝/品红 C 可达 ~130，需要覆盖宽色域时调大，**但必须与分解侧一致** |

## 典型用法

**换色相**（保留明暗和饱和度）：

1. 原图复制一层 → `lb:gray-to-component` 选 `hue`，输入是「色相」分解出的灰度层；
2. 该层混合模式设 **Hue**；
3. 在灰度层上做色阶/曲线/反相——色相就跟着转，褶皱阴影全在。

**只调饱和度**：同上，`saturation` 模式 + **Saturation** 混合模式。

**换色同时压饱和**：`color` 模式 + **Color** 混合模式，`color-sat` 设 40–60%。
一层就把色相和饱和度一起换掉，明度还是原图的。

**只要 HSV 明度**：`value` 模式 + **Value** 混合模式——输出中性灰，Value 读的
就是最大通道，曲线拖灰度直接改明度。

**Lab 空间调色**（不碰明度）：`lch-chroma` + **LCh Chroma**，拖灰度的曲线只改
鲜艳度；`lch-hue` + **LCh Hue** 只转色相；`lch-color` + **LCh Color** 则把色度
一并钉在 `lch-c` 上。

**RGB 单通道重组**：三个 `red`/`green`/`blue` 模式各编码一层，混合模式都用
**Lighten** 自下而上叠——`max((r,0,0),(0,g,0),(0,0,b))` 正好还原 `(r,g,b)`。

## 验收

`tools/check_gray_to_component.py`（39 项，gimp-console 跑）：

- **A. 编码公式**：17 级灰度斜坡喂算子，Lab 域模式（含 `luminance` / `lch-color`
  两个别名）直读 Lab 输出对拍；RGB 域模式读回 RGB 与镜像的 HSL/HSV 公式对拍，
  `color-sat` 跑 100 / 40 两档、`sat-hue` 跑 0 / 210 两档确认参数真的进了公式；
  含端点语义（hue 0=红 / 0.5=青）、value（0=黑 / 1=白 / 中性）、`color-sat=0`
  退化成灰、两组别名输出逐分量相同。
- **B. 恒等往返**（金标准，与 hsl-cal 同一方法）：24 个探针色做分解 → 编码 →
  混合还原，逐像素比对原图，**全部 ≤2/255**：hue→Hue、saturation→Saturation、
  value→Value、lightness→LCh Lightness、luminance→Luminance、lch-hue→LCh Hue、
  lch-chroma→LCh Chroma（量程 100 / 132 两档）、RGB 三通道→Lighten 叠合、
  hue+saturation 串联。Color / LCh Color 是双分量模式，恒等条件要求底层
  饱和度 / 色度与参数一致，所以各配一套专用探针：Color 用 S=100% 与 S=60%
  两组色环，LCh Color 用 C=30 的 LCh 圆环。
- **透明像素**：32×8 棋盘（85/256 全透明）逐像素比对 alpha，透明处 Lab 必须为 0。

## 技术备注

- 输出格式钉成 `CIE Lab alpha float`：Lab/LCh 模式**零转换直写**（a=C·cos h、
  b=C·sin h 就是 CIE LCh 的定义式）；HSL/RGB 模式用 `babl_fish` 把整行转 Lab，
  与 GIMP 内部转换同源，不引入自实现转换的漂移。
- **RGB 域模式的透明像素必须在 `rgb_line` 里落位**：整行交给 `babl_process` 时
  它会重写 `out_line` 的每一个像素，只在 `out_line` 里写 0 会被中间行（未初始化）
  覆盖，导致透明像素的 alpha 变成随机值。早先 2×1 的小用例靠堆内存恰好为 0
  蒙过去了，换成 32×8 棋盘才暴露——现已修正。
- 无 aux pad，可直接作为 GIMP 3 非破坏滤镜挂在灰度图层上（不受
  `Gimp.DrawableFilter` 拒收 aux 算子的限制），整条工作流全程非破坏。
- 透明像素（alpha≤0）输出保持透明。
- 输入 `YA float`：分解出的灰度层是 RGBA 时由 babl 自动转成 CIE 亮度。
