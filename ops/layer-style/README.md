# lb:layer-style · 图层样式（非破坏）

PS 的「图层 → 图层样式」那十个效果，做成一条**挂在图层上的实时滤镜**：

```
图层 ──▶ ┌──────────────────────────┐ ──▶ 画布
         │ lb:layer-style（滤镜栈里）│
         │  投影 / 内阴影 / 两发光   │      参数存在滤镜上
         │  斜面 / 光泽 / 三叠加     │      原像素一个字节都没动
         │  描边                     │
         └──────────────────────────┘
```

勾一个效果、拖几根滑杆，画面立刻跟着动；关掉滤镜整块消失；存成 XCF 再打开，
滑杆还在原来的位置。这就是 PS 的「智能滤镜」，也就是 GIMP 3 里唯一的非破坏
编辑方式。

> 仓库里还有一份**破坏性**的 Python 版：`plugin/layer-style`（菜单是
> `SuperMrWang → Layer → 图层样式…`）。它把十个效果算完、造出一组可编辑图层
> 给你，代价是原像素被换成了图层组，参数不会再回来。两版功能面一样，要「随时
> 能改参数」用这一条，要「拿到能单独编辑的效果图层」用那一条。

## 为什么非得是 GEGL 算子

GIMP 3 的非破坏链路只认 GEGL 算子：`Gimp.DrawableFilter.new(drawable, op, name)`
把**算子名**挂到 drawable 的滤镜栈上，参数读写的是算子的属性，改完
`filter.update()` 重算一遍。滤镜栈随 XCF 存盘、随撤销回退。

Python 插件做不到这件事——它只能读像素、算、写像素。哪怕自己造十个图层，那也
已经是一份烤好的结果（这就是 `plugin/layer-style` 的做法）。所以「非破坏」不是
实现风格的选择题，而是「C / GEGL」还是「Python / 像素」的分水岭。

## 参数

所有效果的勾选框在第一层，缩进两格的参数属于上面那个效果。角度/高度跟随全局光
时，`angle`、`altitude` 被 `global-angle` / `global-altitude` 覆盖（PS 同）。

| 效果 | 属性 | 说明 |
|---|---|---|
| 全局 | `global-angle` 120° / `global-altitude` 30° | 全局光。勾了「使用全局光」的效果都读它 |
| 投影 | `shadow-on` / `-color` / `-opacity` 75 / `-angle` / `-global` / `-distance` 5 / `-spread` 0 / `-size` 5 / `-contour` linear | 大小＝模糊半径；扩展按阈值加硬边 |
| 外发光 | `glow-on` / `-color` `#fdfa87` / `-opacity` 75 / `-size` 8 / `-spread` 0 / `-range` 50 / `-contour` | 单色；`range` 是等高线作用区间的宽度 |
| 内阴影 | `ishadow-on` / `-color` / `-opacity` 75 / `-angle` / `-global` / `-distance` 5 / `-choke` 0 / `-size` 5 / `-contour` | 阻塞＝向内收的阈值 |
| 内发光 | `iglow-on` / `-color` / `-opacity` 75 / `-source` edge·center / `-choke` / `-size` / `-range` / `-contour` | 源＝边缘 / 居中 |
| 斜面和浮雕 | `bevel-on` / `-style` inner·outer·emboss·pillow·stroke / `-method` smooth·chisel-hard·chisel-soft / `-depth` 100 / `-direction` up·down / `-size` 5 / `-soften` 0 / `-angle` / `-global` / `-altitude` 30 / `-highlight-mode`·`-color`·`-opacity` / `-shadow-mode`·`-color`·`-opacity` / `-stroke-size` 3 | 五种样式 × 三种技法 |
| 光泽 | `satin-on` / `-color` / `-opacity` 50 / `-angle` 19 / `-distance` 11 / `-size` 14 / `-invert` / `-mode` | 两片镜像模糊相减，得大块软过渡 |
| 颜色叠加 | `color-on` / `-color` `#ff0000` / `-opacity` / `-mode` | |
| 渐变叠加 | `grad-on` / `-color1` / `-color2` / `-style` linear·radial·angle·reflected·diamond / `-angle` 90 / `-scale` 100 / `-reverse` / `-opacity` / `-mode` | 按整张图的包围盒铺，接缝为零 |
| 图案叠加 | `pattern-on` / `-kind` `dots`·`stripes`·`checker`·`grid`·`diagonal`·`rings` / `-color1` ·`-color2` / `-scale` / `-opacity` / `-mode` | 程序化图案，见下 |
| 描边 | `stroke-on` / `-size` 3 / `-position` outside·inside·center / `-color` / `-opacity` / `-mode` | 宽度按精确距离算，不靠模糊 |

26 种混合模式（`normal` … `lightercolor`）、12 条等高线（`linear`、`cone`、
`gauss`、`ring`、`sawtooth`、`notched`、`half-round` …）、5 种渐变样式。

**图案是算出来的，不是 GIMP 的图案库**：GEGL 算子跑在 GEGL 进程里，看不到 GIMP
的图案、渐变资源，所以渐变只能给两个颜色，图案给了六种可参数化的（点阵、斜纹、
棋盘、网、斜线、同心环）。要真图案叠加，用 Python 版。

## 渲染顺序

顺序照抄 PS，因为它决定了「半透明原图层会不会透出阴影」：

```
1. 投影      ┐ 两条都画进空缓冲（acc）
2. 外发光    ┘
3. 原内容    ← over 到 acc 上
4. 内阴影    ← MULTIPLY，只压在内缘
5. 内发光    ← SCREEN
6. 颜色 / 渐变 / 图案叠加 ← 只改 rgb，alpha 不动
7. 光泽
8. 斜面：阴影片先、高光片后
9. 描边       ← over
```

第 3 步必须是 **over**，不能是赋值：赋值会把刚画好的投影、外发光整块擦掉
（第一版就是这么错的，投影完全不出现）。第 6 步只刷 rgb 不改 alpha——PS 的
叠加效果也不改图层透明度。

## 算法上的几处选择

**在 sRGB 值上混，不在线性光里混。** GIMP 3 默认的混合模式在线性光域算：实测
50% 的 204 叠在 51 上得 **153**，PS 在 sRGB 值上是 **128**。算子直接把 sRGB
分量当数字用，和 PS 对齐；柔边不会发白。

**带符号距离是精确的。** 描边宽度、扩展/阻塞、斜面的高度图都要「到边缘多远」。
这里用 Felzenszwalb 的抛物线包络做**精确**欧氏距离变换（先算外部、再算内部，
两趟 O(n)），不是 numpy 版那种 ±k 行近似——所以软边和硬边上同样的参数厚度一致，
斜对角也不会被算宽。全空 / 全实心的块有单独分支，避免把「这一块里没有内容」
当成距离 0。

**模糊是三次盒式。** 三次盒式的方差是 `3·(2r+1)²/12`，令它等于 `σ²` 反解半径，
与 numpy 版同一个公式。滑动窗口，每像素两次加减。

**tile 化渲染的两个坑。** `process()` 每次只拿到结果的一小块（420×300 实测被切
成六块 70×300），所以：

- 渐变、图案的包围盒必须换成**整张图**（`prepare` 里记下全图矩形，采样点用
  `gx + x`）。用块内坐标，每块各跑一遍渐变，接缝是一条 70 px 的硬边。
- 效果要读邻居，`get_required_for_output` 直接返回整张输入，`process` 里把
  work 区域外扩 `margin = 最大 size + 描边`，用 `GEGL_ABYSS_NONE` 读，越界的
  当透明。

## 正确性验证

```
gimp-console -i -c -d -f --batch-interpreter=python-fu-eval \
    -b "exec(open(r'<仓库>/tools/check_layer_style_gegl.py').read())" --quit
```

（`tools/run_plugin_checks.py` 走的就是这一行；脚本要用 GIMP 自带的 Python，
因为 `Gimp.DrawableFilter` 只有 GIMP 进程里有。）

`tools/check_layer_style_gegl.py` **30 项**，验的全是「非破坏」这件事本身：

- 挂上滤镜之后，原图层像素**逐字节不变**
- 改参数 + `update()` 之后画面变了；`set-visible(false)` 回到原样，再打开又是效果
- `set-opacity(0.5)` 得到半量（注意：`set_opacity` 返回 `None`，改 config 之后
  **必须** `update()`，否则读回的还是 1.0、画面也不动）
- 存 XCF → 重开：滤镜还在栈里，`distance=20`、`shadow_on` 都还在，**XCF 里存的
  仍是原像素**而不是烤好的结果
- `merge_filters()` 之后滤镜栈空了、像素才变成结果
- 768×1024 四个效果全开，`merge_filters` **0.03 s**

数学层与 numpy 版（`plugin/_shared/layer_style.py`）对拍：420×300、投影 + 斜面 +
描边 + 颜色叠加，整体平均差 **0.83/255**；alpha>128 的区域平均 **0.45/255**、
p99 **5.0**。剩下的大差都发生在 1 px 的极淡边缘上——两边的轮廓亚像素覆盖不同。

速度（`gegl` 命令行，含进程启动）：400×300 **1.74 s**、1600×1200 **1.52 s**、
3200×2400 **7.71 s**，十个效果全开。

## 安装

```
./build.sh                      # 产出 build/layer-style.dll
./install.sh --verify           # 装到 GEGL 用户插件目录并逐个确认注册
```

Windows 上 GIMP 只扫自己的 `lib/gegl-0.4/`，把 `build/layer-style.dll` 复制到
`<GIMP>/lib/gegl-0.4/` 再完全退出 GIMP 重开即可（和 `plugin/layer-style` 那种
Python 插件不同，它不走 `plug-ins/` 目录）。同一目录里放两份同样的 dll 会报
`Two different plugins tried to register 'gegl_op_lb_layer_style'`。

## 和 PS 差在哪

**有**：十个效果、26 种混合模式、全局光、12 条等高线、扩展 / 阻塞、渐变五种
样式与反相、描边三档位置、精确距离场、真实时（滤镜挂在栈上）。
**没有**：纹理（斜面的图案浮雕）、3D 材质、自定义等高线编辑器、「下一图层」
混合颜色带、挖空、在画布上直接拖投影手柄、真正的图案资源（见上）。

改参数在「图层」对话框里：滤镜是图层下面的一条子项（带自己的眼睛图标），
双击它就打开 GIMP 按属性自动生成的参数面板，改完确认，画面立刻重算。参数不会
丢，但也没有 PS 那样一个把所有效果竖着排开的面板——GEGL 的 UI 是按属性名自动
生成的，效果的层级只能靠参数名前面的缩进表示。
