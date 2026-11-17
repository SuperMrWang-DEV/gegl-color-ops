# lb:lch-compose · LCh 合成

把数据图还原成真实颜色：`R = L/100`、`G = C/140`、`B = 色相/360`，先把它们
乘回物理量（L*、C*、h），再由 babl 转成 RGB。

```
(L/100, C/140, h/360) ──lb:lch-compose──> 真实颜色
```

## 输入约定是硬的

本算子**无法分辨**输入是一张数据图还是一张普通照片——它一律按「R 是明度、
G 是彩度、B 是色相」解释。挂错地方会把照片当成数据算出一张乱七八糟的图。

正常用法是紧跟在 `lb:lch-dual` 之后（中间夹三条曲线）：

```
lb:lch-dual → L 曲线(红) → C 曲线(绿) → h 曲线(蓝) → lb:lch-compose
```

## 和 Lab 的关系

LCh 就是 Lab 的极坐标：`a = C·cos h`、`b = C·sin h`。转换走 babl 的
`CIE LCH(ab) alpha float`（D50），与 `lb:lch-levels`、`lb:lab-compose` 同一套
Lab 口径，所以三家算出来的颜色是一致的。

## 实测

- `dual → compose` 恒等往返：32 位浮点 **0.0005 码**，8 位 **0.49 码**。
- 在完整插件里（`tools/check_lch_split.py` 33 项）：改 C 曲线后 L* 与色相的偏差
  在 **0.00001 码**级。

## 注意

- 输出 alpha 恒 1，理由同 `lb:lch-dual`。
- 彩度或色相推到极端会出 sRGB 色域，8 位图按 0/1 裁掉——LCh 的色域比 sRGB 大，
  这是它本身的性质，不是算子的近似。
- 色相是环形量：0 与 1 表示同一个角度。
