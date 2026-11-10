# wb:hue-saturation — GEGL 色相/饱和度算子

仿 GIMP「色相-饱和度」滤镜的 GEGL point filter，在 **HSL** 空间逐像素调整，
工作于感知（非线性）RGB 格式 `R~G~B~A float`，自动跟随源色彩空间。

## 功能

- **主控**：`hue`（度数 ±180）、`saturation`（±1，加法）、`lightness`（±1，加法）
- **六个色相区间**（红/黄/绿/青/蓝/品红，中心各相隔 60°）各自拥有独立的
  `*-hue / *-saturation / *-lightness`，按三角形权重与主控叠加
- **`overlap`**（0–1）：区间宽度 = 60° × (1 + overlap)。默认 0 = 六个区间恰好铺满色环、
  区间中心获得 100% 设定；调大则相邻区间互相渗透（柔和但峰值强度按权重比例稀释）
- 灰阶像素（S < 1e-5）不染色：色相/饱和度调整被跳过，仅应用明度
- 全零参数时直接 memcpy 透传（含 alpha），HDR 超范围值按 [0,1] 截断后计算

## 构建（MSYS2 mingw64 / Git Bash）

```bash
export PKG_CONFIG_PATH="/d/fastsoftware/GIMP 3/lib/pkgconfig"
eval gcc -shared -I. -O2 -Wall wb-hue-saturation.c \
  $(pkg-config --cflags --libs gegl-0.4) -o wb-hue-saturation.dll
```

## 验证（不进 GIMP）

```bash
export GEGL_PATH="$(pwd -W);D:/fastsoftware/GIMP 3/lib/gegl-0.4"
gegl --info wb:hue-saturation
gegl test-in.png -o out.png -- wb:hue-saturation hue=45 green-saturation=-0.5
```

## 安装到 GIMP 3

把 `wb-hue-saturation.dll` 拷入 `%LOCALAPPDATA%\gegl-0.4\plug-ins\` 后**重启 GIMP**，
用 `/` 打开 Search Actions 搜索 "Hue-Saturation (WB)"，滤镜以非破坏性 fx 形式挂在图层上。

## 在 GIMP 3 Python 中调用

```python
from gi.repository import Gimp, Gegl

filter = Gimp.DrawableFilter.new(drawable, Gegl.Orientation.AUTO, "wb:hue-saturation", 0)
config = filter.get_config()
config.set_property("hue", 45.0)          # 度
config.set_property("saturation", 0.3)    # -1..1
config.set_property("green-saturation", -0.5)
drawable.merge_filter(filter)             # 非破坏性；Gimp.displays_flush() 刷新
```

## 已验证结果（GEGL CLI 数值校验）

| 用例 | 结果 |
|---|---|
| 零参数恒等 | 输出与输入逐字节一致（max diff = 0） |
| `hue=60` | 红(0°)→黄(60°)、青(180°)→蓝(240°)，精确 +60° |
| `saturation=0.45` | HSL S: 0.082 → 0.535（精确 +0.45），色相/明度不变 |
| 灰阶带 | 完全不变（achromatic guard 生效） |
| `green-hue=-55 green-saturation=-0.7` | 仅绿/黄绿区间偏移至 ~82° 并去饱和，红/蓝/品红不受影响 |

## 文件

- `wb-hue-saturation.c` — 算子源码（单文件，GEGL_OP_POINT_FILTER）
- `wb-hue-saturation.dll` — 编译产物（GEGL 0.4.72 / mingw64）
- `make_test_image.py` — 生成测试图（HSL 色环 + 灰阶带 + 明度带）
- `verify.py` / `compose.py` — 数值校验与对比图拼接
- `test-in.png`、`out-*.png`、`demo.png` — 测试图与结果
