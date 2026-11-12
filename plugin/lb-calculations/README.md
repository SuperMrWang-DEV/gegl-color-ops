# 计算（GEGL 薄壳）

PS「图像 → 计算」的**结果落地**部分：把 GEGL 算子 `lb:calculations` 算出来的
灰度，变成选区 / Alpha 通道 / 灰度图层 / 图层 alpha。

和 `plugin/ps-blend` 的区别只有一个字：**像素谁算**。这里的像素全部由算子算，
本文件里没有第二份混合公式；`ps-blend` 自带一套 `psblend.py` 内核（复用
`common/blend.h`），两套要同步维护。

| | 本插件 | plugin/ps-blend |
|---|---|---|
| 像素来源 | GEGL 算子 `lb:calculations` | 自带内核（ctypes / 纯 Python） |
| 算子修 bug 后 | 自动继承 | 要手动同步三处 |
| 源 | 任意打开图像的任意图层 + 通道 | 同左 |
| 遮罩 | 任意图像任意图层（第三张图要跑两趟） | 同左，一趟 |
| 结果 | 选区 / 通道 / 灰度层 / 图层 alpha | 同左 |
| 依赖 | 算子已安装（`./install.sh`） | 只有 Python |

菜单：**颜色 → SuperMrWang → Calculations (GEGL)...**，和 `Calculations PS...`
并排，方便对照。

## 为什么是「手搭 GEGL 图」

两条近路都堵死了：

1. **算子本身**落不了选区——GEGL 只输出像素，它拿不到 GIMP 的选区/通道/图层。
2. **`Gimp.DrawableFilter`** 是让插件在 GIMP 里跑算子的标准姿势，但带 aux 的算
   子会被直接拒掉：`effects with an 'aux' pad cannot be applied
   non-destructively`。而计算天生需要两路输入。

所以只能自己在插件进程里接一张三节点的小图：

```
buffer-source(源 1) ─┐
                     ├─ lb:calculations ─ blit_buffer ─> 结果
buffer-source(源 2) ─┘
```

两个 `Gegl.Buffer` 都是画布大小、原点在 0,0：算子按同一坐标读 input 和 aux，
图层比画布小或带偏移时，直接把图层自己的 buffer 喂进去会整体错位（补 0 对应
PS 把缺的那块当黑）。

## 几个 GIMP 3 Python 的坑

- **插件进程没有初始化 GEGL**。`Gegl.Node.create_child()` 会直接把进程干掉
  （op factory 的哈希表还是空指针）。开头必须先 `Gegl.init()`，而且要在任何
  `Gegl.Buffer.new()` 之前。
- **`gegl:buffer-sink` 用不了**：它的 `buffer` 属性在 typelib 里是 `gpointer`，
  Python 写不进去，读出来是 `None`。改用 `node.blit_buffer(buffer, rect, level,
  abyss_policy)` 把结果画进自己的 `Gegl.Buffer`。
- **`Gegl.Buffer.new()` 是 5 个参数**：`(格式名, x, y, 宽, 高)`；`set()` 只要
  3 个（`rect, 格式, 数据`），行距由 rect 宽度推——和 C 里 `GEGL_AUTO_ROWSTRIDE`
  同一个坑，只写整幅时安全。
- **枚举属性按 nick 字符串设**：`node.set_enum_as_string("blend-mode",
  "multiply")`。整数会在 `Gimp.DrawableFilterConfig` 上被当成字符串拒掉。
- **选区缓冲是单通道 `Y float`**。用 `R'G'B'A float` 读会被 babl 转换（59 读成
  132），校验选区要按 `Y float` 读。
- **`gimp_image_insert_layer` 的 `-1` 是「活动层之上」**，不是「最底下」：想放
  底层用 `position = len(get_layers())`。

## 遮罩的来源与代价

算子的 `mask-channel` 只能读 **aux（源 2）** 的通道。所以：

- 遮罩取自源 2 → 一趟搞定，用算子自带的 mask 参数；
- 遮罩来自第三张图 → 跑两趟（`opacity=100` 得混合结果、`opacity=0` 得源 1），
  再在 Python 里按 `out = v1 + (blended - v1) × 遮罩 × 不透明度` 插值。遮罩在
  这段里只是「取哪个通道」，不是混合公式；两趟都带着源 2 的 alpha 覆盖率，而
  覆盖率是线性因子，插值后再乘等价。

## 验证

```bash
export GEGL_PATH="<repo>/build;D:/fastsoftware/GIMP 3/lib/gegl-0.4"
"D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval \
    -b "exec(open(r'<repo>/tools/check_thin_calc.py').read())" --quit
```

9 项：无遮罩 multiply、遮罩取源 2、遮罩取第三张图、源 2 透明洞、选区、Alpha
通道、图层 alpha、单通道 + 反相。期望值按 `lb:calculations` 的公式手算。

## 已知限制

- **批处理（PDB）从 Python 调不通**：参数都注册好了，但 `Gimp.ImageProcedure`
  的 `drawables` 属性要 `GimpCoreObjectArray`，这个类型没暴露给 Python 3.14 的
  GI（`Gimp` 模块里只有 `ParamCoreObjectArray`）。C/Scheme 侧调用不受影响。
- 计算一次会同时开 2 个进缓冲 + 1 个出缓冲 + 1 份 Python 浮点数组，约
  `4 × 宽 × 高 × 16` 字节。和 `ps-blend` 同量级。
