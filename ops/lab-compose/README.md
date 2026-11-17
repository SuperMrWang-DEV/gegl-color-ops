# lb:lab-compose · Lab 合成

`lb:lab-dual` 的逆运算：把「`R = a*`、`G = b*`、`B = L*`」的数据图还原成真实颜色。
alpha 被忽略，输出恒不透明。

```
(R=a, G=b, B=L) ──lb:lab-compose──> sRGB
```

## 它是怎么算的

先把 0…1 还原成 babl 的量程，再交给 babl：

```
L* = B · 100
a* = R · 255 − 128
b* = G · 255 − 128
```

`babl_fish("CIE Lab float", "R'G'B'A float")` 一步转回 sRGB。白点 D50，与 GIMP 的
Lab 空间、`component-extract` 的 `lab-l`、LCh 三条分量混合模式都是同一套，所以
`dual → curves → compose` 的往返没有查表误差（浮点 0.010 码）。

## 输入输出

| | 格式 | 含义 |
|---|---|---|
| input | `R'G'B'A float` | **数值是数据**：`lb:lab-dual` 的输出，或你自己拼的三通道数据图 |
| output | `R'G'B'A float` | sRGB 编码值，已裁到 [0,1] |

曲线可以把数据推到 0…1 之外（比如把 a 拉高到 1.4）。转换前先夹回 Lab 的合法量程
（a/b ∈ [−128,127]、L ∈ [0,100]），转换后再把 RGB 裁到 [0,1]，避免 NaN/无穷进缓冲。

## 注意

- 「R 是 a、G 是 b、B 是 L」是**硬约定**：算子分辨不出输入是数据图还是普通照片。
  挂到照片上会把像素当 Lab 数据解释，结果是错的但不会报错。
- 它是 `Lab Split (Curves)` 那条链的第 4 道滤镜，单独用只有一个场景：把别人存的
  Lab 数据图还原成可见颜色。
