# lb:color-grading — 颜色分级（RAW 编辑器 Color Grading 风格）

2026-11-12 新增。复刻 classic RAW editors 的
**Color Grading（颜色分级）**面板：阴影 / 中间调 / 高光 / 全局四个轮盘
（色相 + 饱和度），各带独立的明度滑杆，外加 Blending 与 Balance。

## 菜单位置

`Colors → SuperMrWang → Color → Color Grading`

## 参数（14 项，与 RAW 编辑器 面板一一对应）

| 参数 | 范围 | 默认 | 说明 |
|---|---|---|---|
| Global Hue / Saturation / Luminance | 0–360 / 0–100 / −100–100 | 0 / 0 / 0 | 全局轮盘，整幅画面均匀生效 |
| Shadows Hue / Saturation / Luminance | 同上 | 0 / 0 / 0 | 阴影轮盘 |
| Midtones Hue / Saturation / Luminance | 同上 | 0 / 0 / 0 | 中间调轮盘 |
| Highlights Hue / Saturation / Luminance | 同上 | 0 / 0 / 0 | 高光轮盘 |
| Blending | 0–100 | 50 | 相邻亮度带的交叉淡化宽度（0 = 硬分界） |
| Balance | −100–100 | 0 | 平移阴影/高光的势力范围（正 = 偏高光） |

## 算法模型

按像素的 Rec.709 亮度（伽马域）分带：

- 分界默认：阴影/中间调 **0.3**，中间调/高光 **0.7**；
- Blending 把两条硬边界铺成 smoothstep 过渡（100 → 各 ±0.25），
  中间调权重 = 1 − 阴影 − 高光；
- Balance ±100 把两条分界一起平移 ±0.25。

```math
h = 0.25\cdot\frac{\text{Blending}}{100},\qquad
e_{\text{sh}} = 0.3 + 0.25\cdot\frac{B}{100},\qquad
e_{\text{hi}} = 0.7 + 0.25\cdot\frac{B}{100}
```

```math
w_{\text{sh}} = 1-\operatorname{smooth}\!\left(\frac{Y-e_{\text{sh}}}{2h}+\frac{1}{2}\right),\qquad
w_{\text{hi}} = \operatorname{smooth}\!\left(\frac{Y-e_{\text{hi}}}{2h}+\frac{1}{2}\right),\qquad
w_{\text{mid}} = 1-w_{\text{sh}}-w_{\text{hi}}
```

每个轮盘的一次染色（乘以带权重 w）：

- 明度：`V += Lw × 0.005 × w`（与 `lb:hsl-seven` 同系数）；
- 染色强度 `t = Sat/100 × w`：往**同明度的轮盘纯色**混合，
  `rgb = rgb·(1−t) + tint·t`，`tint = HSV(轮盘色相, 1, V)`。
  灰像素自然吃到染色；与轮盘色接近互补的色相则被去饱和（掺灰），
  **不在色相上做插值**，所以没有「旋转方向翻转」的接缝。

```math
V \leftarrow V + 0.005\,L_w\,w,\qquad
t = \frac{\text{Sat}}{100}\,w,\qquad
\text{rgb} \leftarrow \text{rgb}\,(1-t) + \text{tint}\,t,\qquad
\text{tint} = \operatorname{HSV}(h_w,\,1,\,V)
```

> 2026-11-12 修正：初版用「色相向轮盘色相收敛」的模型，在互补色相
> （色相差 ≈ 180°）处 `roundf` 的旋转方向会翻转，裁切高光上会爆出
> 竖条纹（在 night-blue 演示图里可见）。已改为向轮盘色混合，
> `check_color_grading.py` 新增「互补色相无接缝」检测（相邻列跳变
> 1.2 码，阈值 8）。

执行顺序：全局轮盘（权重 1）先做，三个带再做。

## 标定状态（诚实声明）

本机 经典图像编辑器 2025 **未装 RAW 编辑器 插件**，无法像 colorize / color-mask-select
那样逐码标定。分界 0.3/0.7、过渡 ±0.25、Rec.709 亮度等均为按 RAW 编辑器 公开
行为设定的合理模型，**不是黑盒实测值**。结构、参数语义与 RAW 编辑器 面板
一一对应；数值行为由 `tools/check_color_grading.py` 按设计模型验证。

## 验证

```bash
python tools/check_color_grading.py    # 行为验证 12 项（恒等 / 分带 / 落位 / Blending / Balance / 全局 / 无接缝）
python tools/smoke.sh                  # 全算子冒烟
```

## 已知限制

- 轮盘没有独立的「范围」滑杆（RAW 编辑器 悬停轮盘可调亮度范围端点）；
  分界固定 0.3/0.7，只能用 Blending/Balance 调整过渡与偏移。
- 亮度分带用的是像素自身亮度（Rec.709 伽马域），不是邻域亮度；
  要「按邻域」的效果请用 `lb:shadows-highlights`。
