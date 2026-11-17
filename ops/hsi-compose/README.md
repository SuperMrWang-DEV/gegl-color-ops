# lb:hsi-compose · HSI 合成

`lb:hsi-dual` 的逆运算：把「`R = 饱和度`、`G = 强度`、`B = 色相/360`」的数据图还原成
真实颜色。alpha 被忽略，输出恒不透明。

```
(R=S, G=I, B=H/360) ──lb:hsi-compose──> sRGB
```

## 它是怎么算的

逆变换用 HSI 的**余弦式**，不是 HSV 的线性扇区：

```
H  < 120°   B = I(1−S)、R = I[1 + S·cosH / cos(60−H)]、G = 3I − R − B
H  < 240°   轮转 120°，R 取低值
其余        轮转 240°，G 取低值
```

用 HSV 的扇区公式会在 S 高、I 低时偏几十码——两者在等亮度平面上不是同一组基。
这段代码在 `common/color-levels.h`（`lb_cl_hsi_to_rgb`），与 `lb:hsi-levels` 共用。

## 输入输出

| | 格式 | 含义 |
|---|---|---|
| input | `R'G'B'A float` | **数值是数据**：`lb:hsi-dual` 的输出 |
| output | `R'G'B'A float` | sRGB 编码值，已裁到 [0,1] |

S、I 在转换里会被夹到 [0,1]，色相走 `wrap360`，RGB 输出裁到 [0,1]——HSI 的色域是
六边形棱锥，S/I 拉到极端时出界只能裁。

## 注意

- 「R 是饱和度、G 是强度、B 是色相」是**硬约定**：挂到照片上会把像素当 HSI 数据
  解释，结果出错但不报错。
- 把它和 `lb:hsi-levels` 区分开：那个是按色阶参数逐分量做 1D 映射，这个是给
  「曲线工作流」用的合成器。
