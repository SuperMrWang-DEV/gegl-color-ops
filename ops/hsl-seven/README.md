> 本文件是该滤镜的原始说明文档（构建命令按旧目录结构书写，已过时）。
> 统一构建方式请见工程根目录 `README.md` 与 `build.sh`。

# GEGL_GIMP_PLUGIN_hslseven

> 2026-11-12：按 RAW 编辑器 8 段混色器补齐洋红段——原紫段 0.78~0.92 对半拆为
> 紫 0.78~0.85 与洋红 0.85~0.92。旧 7 段属性名与边界行为不变，算子 id
> 仍为 `lb:hsl-seven`（GIMP 存进 XCF 的字符串，不能改）。

## English

### 1. Compile & Install Commands

#### Native Linux (System installed GIMP)

```bash
sh build_linux.sh
cp build/gegl-*.so ~/.local/share/gegl-0.4/plug-ins
```

#### Flatpak Linux (Flatpak GIMP)

```bash
sh build_linux.sh
cp build/gegl-*.so ~/.var/app/org.gimp.GIMP/data/gegl-0.4/plug-ins/
```

### 2. How to Open the Plugin (2 Methods)

After installation, **restart GIMP** to activate the plugin.

#### Method 1: Menu Bar (Recommended)

Menu path: `Colors → SuperMrWang → Color → HSL 8 Bands`

#### Method 2: GEGL Operation

1. Go to `Filters → Generic → GEGL Operations`
2. In the search box, enter: `lb:hsl-seven`
3. Select it and click `OK` to apply

---

## 中文

### 1. 编译与安装命令

#### Linux 原生版（系统包安装的GIMP）

```bash
sh build_linux.sh
cp build/gegl-*.so ~/.local/share/gegl-0.4/plug-ins
```

#### Linux Flatpak 容器版（应用商店Flatpak GIMP）

```bash
sh build_linux.sh
cp build/gegl-*.so ~/.var/app/org.gimp.GIMP/data/gegl-0.4/plug-ins/
```

### 2. 插件打开方式（两种方法）

安装完成后**重启 GIMP**，插件即可使用。

#### 方法一：菜单打开（推荐）

菜单路径：`SuperMrWang → Color → HSL 8 Bands`

#### 方法二：GEGL 操作打开

1. 顶部菜单点击：`滤镜 → 通用 → GEGL 操作`
2. 在弹出窗口的搜索框输入：`lb:hsl-seven`
3. 选中后点击「确定」即可使用插件

---

## 这个算子做什么

八段色相（红 / 橙 / 黄 / 绿 / 青 / 蓝 / 紫 / 洋红）各带一组 H/S/L 偏移，共 24 个
滑块，按色相段加权叠加，段间由 `feather` 交叉淡化；饱和度低于 `min-saturation`
的灰像素可以选择跳过（灰没有有意义的色相）。参照物是 RAW 编辑器 的 HSL 面板：
只想压掉某几个色相的饱和、或者只把某个色相提亮，就拖那一段。

## 算法

八段色相各有一套 H/S/L 偏移，按段权重叠加；段边界用 smoothstep 交叉淡化：

```math
w_k(h) = \sigma\!\left(h,\ s_k-f,\ s_k\right)\cdot\Bigl(1-\sigma\bigl(h,\ e_k,\ e_k+f\bigr)\Bigr),
\qquad f = 0.01\cdot\text{feather}
```

```math
H \mathrel{+}= \frac{\Delta H_k}{100}\cdot 60°\,w_k,\qquad
S \mathrel{+}= \frac{\Delta S_k}{100}\,w_k,\qquad
L \mathrel{+}= \frac{\Delta L_k}{100}\,w_k
```

八段首尾相接（红 0–45°、橙 45–90°……洋红 315–360°），权重和恒为 1；
$S < \text{min-saturation}$ 的灰像素可以整段跳过。

## 2026-11-12：补上洋红段

RAW 编辑器 的混色器是八段，本算子原来只有七段。原紫段（0.78–0.92）对半拆成
紫 0.78–0.85 与洋红 0.85–0.92。

原来七段的属性名与边界行为不变，算子 id 仍是 `lb:hsl-seven`——这个字符串是 GIMP
存进 XCF 的东西，不能改。

## 与 lb:hue-saturation 的分工

`lb:hue-saturation` 是 经典图像编辑器的对话框：一个主控加六个色相区间，做的是相对偏移、在 HSL
上加减。本算子对应 RAW 编辑器 的混色器：八段、每段三个分量。思路相同，面板与数值
都不同，看惯哪个用哪个。
