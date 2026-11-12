# lb:color-lookup · Color Lookup

按 Adobe Cube LUT 规范实现的「颜色查找」，对应 PS 的「颜色查找」调整图层。
PS 那侧只能手动跑脚本标定（见文末），所以这一支的数值验收先对齐**独立写的
Python 参考实现**，而不是 PS 输出。

- GEGL id：`lb:color-lookup`
- 菜单：`Colors → SuperMrWang → Blend → Color Lookup`
- 类型：`GeglOperationFilter`（按行扫描；LUT 在 `prepare()` 里加载并缓存）
- 参数：`file`（.cube 路径）、`strength`（0…1，默认 1）、
  `interpolation`（`trilinear` 默认 / `tetrahedral`）

## 算法

1. **解析**：`LUT_1D_SIZE` / `LUT_3D_SIZE` / `DOMAIN_MIN` / `DOMAIN_MAX` /
   `LUT_1D_INPUT_RANGE` / `LUT_3D_INPUT_RANGE` / `TITLE` / `#` 注释。
   节点值按声明的 domain 归一化到 0..1（`DOMAIN_MAX 255` 的表因此与 0..1 表等价）。
2. **1D shaper**（可选）：逐通道线性插值，先压一段曲线。
3. **3D 表**：文件里**红变化最快**，索引 `r + g·n + b·n²`。采样两种：
   - 三线性：8 个角点按体积权重相加；
   - 四面体：按 `fr/fg/fb` 的大小关系把立方体切成 6 个四面体，每个只走 3 条棱。
     灰轴附近不会出现三线性的楔形偏色，但离格点越远、表越不平滑，
     与三线性的差别越大（zigzag 表上可达 0.35，约 90 码）。
4. **强度**：`out = 源 + (查表结果 − 源) · strength`，在编码值上做 lerp。
5. 输出夹到 0..1；alpha 原样透传。

格式支持：**只认 `.cube`**（3D、纯 1D、1D+3D 都行）。`.3dl` / `.look` / `.csp`
尚未实现 —— `.3dl` 的轴序（红最快还是蓝最快）需要拿 PS 实测确认，不能靠猜。

## 为什么钉在感知格式

LUT 是给**编码值**（0..1 的 sRGB 码）定义的。pad 固定成 `R~G~B~A float`，
喂线性光会把整张表往错误的位置上采样，暗部会明显发灰。

## 坏文件怎么办

解析失败（文件不存在、节点数不足、`LUT_3D_SIZE` 越界）时 `g_warning` 一条，
算子退化成**恒等**。渲染不中断，也不会因为一个坏路径把整张图弄黑。

缓存键是「路径 + mtime + size」，只在 `prepare()` 里 stat 一次，
同一路径被替换了文件也会自动重载。

## 性能

`process()` 每像素：3 次（1D）+ 8 次（3D）表访问 + 约 20 次乘加。
33³ 是常见尺寸（约 430 KB），对缓存友好；纯 1D 表只走 3 次插值。

## 验收

```bash
python tools/check_color_lookup.py            # 7 个内置 LUT × 2 种插值 × 3 档强度
python tools/check_color_lookup.py x.cube     # 额外比对指定文件
```

内置用例：2 格/33 格单位元、反相、R/B 对调、平滑非线性（DOMAIN 0..1 与
DOMAIN_MAX 255 各一份，结果须一致）、`zigzag9`（专门区分两种插值）、纯 1D 表。
与独立 Python 实现逐像素比对，**全部 0.00 码**（8 位下逐位相同）。

## PS 侧待办

PS 2025 以「命令行带脚本」启动时，所有 `Mk`（建立调整图层）都会报
「命令建立: 当前不可用」——连亮度/对比度都建不出来，是启动期 UI 未就绪，
与描述符无关；`executeAction(colorLookup)` 当事件执行则不报错但**不改像素**。
所以要把 `color-lookup-cal/batch_cl.jsx` 存到本地、在已启动的 PS 里
`文件 → 脚本 → 浏览…` 手动跑一次，再用 `color-lookup-cal/compare.py`
对比 PS 输出与算子输出（脚本会同时报「PS vs 三线性」「PS vs 四面体」，
顺便定下 PS 到底用哪种插值）。
