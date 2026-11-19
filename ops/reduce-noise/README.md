# Reduce Noise · 减少杂色

> `lb:reduce-noise` · 菜单 **SuperMrWang → Noise → Reduce Noise** · 单输入

只平均「和中心差不多」的邻居，差得多的（边缘、细节）不参与。结果是平坦区
被磨平、边缘原样保留——这是 sigma 滤波（Lee 1983），PS「减少杂色」用的
也是这一族。

Averages only neighbours close to the centre pixel. Flat areas are smoothed,
edges survive untouched — a sigma filter, the family Photoshop's Reduce Noise
belongs to.

## 参数 / Parameters

| 参数 | 范围 | 默认 | 含义 |
|---|---|---|---|
| `strength` 强度 | 0–100% | 50 | 阈值 t = 22% × strength；越大抹得越狠 |
| `detail` 保留细节 | 0–100% | 20 | 把 t 最多收窄 80%，保纹理 |
| `radius` 半径 | 1–10 | 2 | 邻域半径，1 即 3×3 |
| `per-channel` 每通道 | 开 / 关 | 关 | 关时三通道共用一份权重（色噪点一起消失、色调不变）；开时各算各的 |

## 算法

对每个像素，取 `(2r+1)²` 邻域，用通道差的最大值 `d` 定权重：

```
w = max(0, 1 − (d / t)²)
out = Σ(w·v) / Σw
```

`d > t` 的邻居权重为 0，所以边缘另一侧的像素不会把这一侧拉过去——这就是
它不糊边的原因，不需要任何边缘检测。中心像素的 `d = 0`，权重恒为 1。

`per-channel` 关闭时，`d` 取三个通道的最大值，权重只有一份，三个通道共用：
彩色噪点被平均掉，通道之间的比例关系不变（不会出现「降噪后颜色发灰」）。

`strength = 0` 时 `t = 0`，只有完全相同的邻居参与平均，结果就是原图。

## 用法 / Recipes

- **高 ISO 降噪**：`strength=60 detail=25 radius=2 per-channel=on`
- **只剩彩色噪点**：`strength=80 detail=0 radius=3 per-channel=off`
- **磨皮前置**：`strength=40 detail=60 radius=2`，随后交给高低频磨皮

## 与 Photoshop 的差异

| | PS 减少杂色 | `lb:reduce-noise` |
|---|---|---|
| 强度 / 保留细节 / 每通道 | 有 | 有 |
| 半径 | 固定（内部按强度推导） | **可调** |
| 移去 JPEG 伪影 | 有 | 无（属于 8×8 块检测，另一个算法） |
| 锐化细节 | 有（降噪后回调） | 无（接一个 `lb:unsharp-mask` 即可） |

## 测试 / Testing

`python tools/check_noise_sharpen.py`：强度 0 恒等、噪点标准差降到一半以下、
均值不漂移、硬边不动、α 透传。
