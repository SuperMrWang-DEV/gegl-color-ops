# lb:gray-to-component · 灰度转分量

通道灰度调色工作流里的**编码器**：把分解出来的分量灰度层，重新编码成
「携带该分量」的彩色层，交给 GIMP 的分量混合模式读回去。

```
原图 ──分解──> 分量灰度层（H / S / L / C …）
                    │
                    ▼
            lb:gray-to-component   ← 本算子：灰度 → 该分量的彩色表示
                    │
                    ▼
        混合模式还原（Hue / Saturation / LCh Lightness / LCh Hue / LCh Chroma）
```

为什么需要这一步：**灰度像素的色相和饱和度是无定义的**。把分解出的 H 灰度层
直接设成「色相」混合模式毫无效果——混合模式从灰里读不出色相。必须先把它编
码成色环上的真实颜色，混合模式才有东西可读。GIMP 的分解和混合模式都是现成
的，唯独中间这一步没有，本算子补的就是这一环。

## 模式表（编码公式经 hsl-cal 恒等往返实测校准）

| 模式 | 灰度 g 的语义 | 输出编码 | 配哪个混合模式还原 |
|---|---|---|---|
| `hue` | HSL 色相 h/360 | `hsl_to_rgb(g·360°, S=1, L=0.5)`，饱和度亮度拉满的色相轮 | **Hue**（HSV_HUE） |
| `saturation` | HSV 饱和度 s | `hsv_to_rgb(sat_hue, s, V=1)`，默认红相 | **Saturation**（HSV_SATURATION） |
| `lightness` | CIE 明度 L/100 | `Lab(g·100, 0, 0)` 直写 | **LCh Lightness** / Luminance |
| `red` / `green` / `blue` | 该通道值 | `(g,0,0)` / `(0,g,0)` / `(0,0,g)` | **Lighten** 三层叠合 |
| `lch-hue` | CIE 色相 h/360 | `Lab(lch_l, C·cos(h), C·sin(h))`，C = `lch_c` | **LCh Hue** |
| `lch-chroma` | CIE 色度 C/chroma_scale | `Lab(lch_l, C·cos(h₀), C·sin(h₀))`，h₀ = `lch_h` | **LCh Chroma** |

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
| `lch-l` | 54 | LCh 模式用的固定明度。混合模式只读色相/色度时此值不进结果，取中庸值以留在常见色域内 |
| `lch-c` | 30 | `lch-hue` 模式用的固定色度。越大越鲜艳，过大可能超出 sRGB 色域 |
| `lch-h` | 30 | `lch-chroma` 模式用的固定色相角（0=红），同样不进结果 |
| `chroma-scale` | 100 | `lch-chroma` 的满量程（灰度 1.0 对应多少色度）。sRGB 的蓝/品红 C 可达 ~130，需要覆盖宽色域时调大，**但必须与分解侧一致** |

## 典型用法

**换色相**（保留明暗和饱和度）：

1. 原图复制一层 → `lb:gray-to-component` 选 `hue`，输入是「色相」分解出的灰度层；
2. 该层混合模式设 **Hue**；
3. 在灰度层上做色阶/曲线/反相——色相就跟着转，褶皱阴影全在。

**只调饱和度**：同上，`saturation` 模式 + **Saturation** 混合模式。

**Lab 空间调色**（不碰明度）：`lch-chroma` + **LCh Chroma**，拖灰度的曲线只改
鲜艳度；`lch-hue` + **LCh Hue** 只转色相。

**RGB 单通道重组**：三个 `red`/`green`/`blue` 模式各编码一层，混合模式都用
**Lighten** 自下而上叠——`max((r,0,0),(0,g,0),(0,0,b))` 正好还原 `(r,g,b)`。

## 验收

`tools/check_gray_to_component.py`（23 项，gimp-console 跑）：

- **A. 编码公式**：17 级灰度斜坡喂算子，Lab 域模式直读 Lab 输出对拍；RGB 域
  模式读回 RGB 与镜像的 HSL/HSV 公式对拍；含端点语义（hue 0=红 / 0.5=青）、
  saturation 端点（0=白 / 1=纯红）、透明像素透传。
- **B. 恒等往返**（金标准，与 hsl-cal 同一方法）：24 个探针色做分解 → 编码 →
  混合还原，逐像素比对原图，**全部 ≤2/255**：hue→Hue、saturation→Saturation、
  lightness→LCh Lightness、lch-hue→LCh Hue、lch-chroma→LCh Chroma（量程 100 /
  132 两档）、RGB 三通道→Lighten 叠合、hue+saturation 串联。

## 技术备注

- 输出格式钉成 `CIE Lab alpha float`：Lab/LCh 模式**零转换直写**（a=C·cos h、
  b=C·sin h 就是 CIE LCh 的定义式）；HSL/RGB 模式用 `babl_fish` 把整行转 Lab，
  与 GIMP 内部转换同源，不引入自实现转换的漂移。
- 无 aux pad，可直接作为 GIMP 3 非破坏滤镜挂在灰度图层上（不受
  `Gimp.DrawableFilter` 拒收 aux 算子的限制），整条工作流全程非破坏。
- 透明像素（alpha≤0）输出保持透明。
- 输入 `YA float`：分解出的灰度层是 RGBA 时由 babl 自动转成 CIE 亮度。
