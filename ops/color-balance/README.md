> 本文件是该滤镜的说明文档。统一构建方式请见工程根目录 `README.md` 与 `build.sh`。

# GEGL_GIMP_PLUGIN_color_balance

对应 经典图像编辑器的「色彩平衡」调整。两个模式：

- **不保留明度（默认）**：经典图像编辑器的逐通道曲线，见下面「算法」一节。
- **保留明度**：MATLAB 零和矩阵（系数减中位数 → 高光 `in/(1−α)` → 阴影
  `(in−α)/(1−α)` → 中间调 `in^γ`），与经典图像编辑器实测最大差 3.0 码，未做改动。

---

## 算法（不保留明度）

一个通道（C-R 动 R、M-G 动 G、Y-B 动 B）只由自己那条滑杆决定，与其它两个通道无关。
三个色调区间的参数先合并成**一条**曲线：

```math
G = g_{\text{阴影}}\cdot g_{\text{中间调}}\cdot g_{\text{高光}},\qquad
b = \begin{cases} |s_{\text{阴}}|, & s_{\text{阴}} < 0 \\ 0, & \text{否则} \end{cases},
\qquad
W = \begin{cases} 255-s_{\text{高}}, & s_{\text{高}} > 0 \\ 255, & \text{否则} \end{cases}
```

```math
u = \frac{v-b}{W-b},\qquad \text{out} = 255\,u^{G}\quad (u \ge H)
```

近黑端另有一段「趾部」：G < 1 时 u^G 在 0 处斜率无穷，经典图像编辑器 实际是有限斜率起步。
把 [b, h0] 这一段换成三次 Hermite：

```math
h_0 = b + H\,(W-b),\qquad
y_1 = 255\,H^{G},\qquad
\text{out} = \operatorname{Hermite}\!\left(\frac{v-b}{h_0-b},\ S_u H,\ y_1,\ G\,y_1\right)
```

- 指数：中间调 `2^(∓s/100)`，阴影和高光各只有它的一半 `2^(∓s/200)`；
  算子用实测表（`cb-tables.h` 的 `CB_G`），不套公式。
- `Su`（归一化起点斜率）与 `H`（趾部宽度占比）都**只随复合指数 G 变化**，
  与「这个 G 是哪个区间给的」无关：单区间档与组合档落在同一条曲线上（表 `CB_TOE`）。
  G ≥ 0.85 时 H 衰减到 0，趾部自然消失。
- 忽略趾部的话，中间调 +100 在 v≈4 处会差 16 码；补上后全档 ≤ 0.3 码。

参数由 `cb-cal` 的经典图像编辑器标定得到（经典图像编辑器 26.10、16 位、600 档单区间 + 9 组合），
完整推导与精度见 `../../cb-cal/RESULTS.md`。

**不要手改 `cb-tables.h`**，它由 `cb-cal/gen_cb_tables.py` 从标定数据生成。

精度（1024 px 连续斜坡、16 位、全图逐像素）：

| 分组 | 最大 | 中位 |
|---|---|---|
| 阴影 ±1…±100 | 0.21 码 | 0.01 码 |
| 中间调 | 0.30 码 | 0.00 码 |
| 高光 | 0.27 码 | 0.00 码 |
| 组合 | 0.65 码 | 0.06 码 |

（0.03 码 = 1 个 16 位 LSB）

### 与两篇知乎文章的关系

工程早期按下面第 1 篇的「三段独立通道曲线、依次作用」实现，实测下来在高光正向和
阴影负向上偏到 30 码级，组合档更差。本轮重新标定后确认：三段不是依次作用，而是
指数相乘、黑场/白场各取一端的参数合并；单段曲线也不是文章里的 `1 − k·s` 线性指数。
第 2 篇的零和矩阵（保留明度）与实测吻合，保留原样。

---

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

Menu path: `Colors → SuperMrWang → Color → Color Balance`

#### Method 2: GEGL Operation

1. Go to `Filters → Generic → GEGL Operations`
2. In the search box, enter: `lb:color-balance`
3. Select it and click `OK` to apply

### 3. Algorithm (preserve-luminosity off)

Each range drives exactly one channel, independent of the other two. The three
ranges do **not** apply as three curves in sequence; their parameters merge into
a single levels-style curve:

```
G = g_shadow · g_midtone · g_highlight      exponents multiply
b = |s|        when the shadow slider is negative    (black point)
W = 255 - s    when the highlight slider is positive (white point)
otherwise b = 0, W = 255

out = 255 · ((v - b)/(W - b))^G            (u >= H)
```

Near black the power law is replaced by one cubic Hermite on `[b, h0]`:
`h0 = b + H·(W-b)`, `y1 = 255·H^G`, and the curve is
`Hermite((v-b)/(h0-b), Su·H, y1, G·y1)`.

Midtones use `2^(∓s/100)`, shadows and highlights half of that
(`2^(∓s/200)`); the op reads measured tables (`CB_G`) instead of the formula.
Both `Su` (normalised initial slope) and `H` (toe width) depend on the
composite exponent G alone — single-range and combo settings fall on the same
Su(G) — and H decays to 0 at G >= 0.85 (table `CB_TOE`).

Measured against classic image editor 26.10 (16-bit, 600 slider settings + 9 combos):
max 0.30 codes per range, 0.65 codes for combos. See `../../cb-cal/RESULTS.md`.

### 4. Preserve luminosity

Unchanged MATLAB zero-sum implementation; max 3.0 codes against the classic editor.

---

## 参考 / References

1. 色彩平衡调整图层的本质-背后的数学原理 - 王先生的副业 - 知乎
   https://zhuanlan.zhihu.com/p/679776283
2.经典图像编辑器中的色彩平衡调整图层的原理分析 - 章佳杰 - 知乎
   https://zhuanlan.zhihu.com/p/59450298

第 1 篇的三段曲线模型与实测不符（见上）；第 2 篇的零和矩阵与保留明度模式吻合。
Article 1's three-separate-curves model does not match the measurements; article
2's zero-sum matrix matches the preserve-luminosity mode.
