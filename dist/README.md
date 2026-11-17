# 直接下载（不用编译）

这里放的是**已经编译好的 GEGL 模块**，下载后扔进 GEGL 插件目录就能用，不需要装
GCC、MSYS2、meson 那一套。内容与当前分支的源码同步（`tools/make_dist.py` 生成）。

想要一次性拿齐（31 个 `.dll` 打成一个包、附安装说明）：
[`docs/download/gegl-color-ops-windows-x64.zip`](../docs/download/)（约 1.3 MB，
由 `python tools/site_build.py` 顺带打包）。在线说明页：
<https://superMrwang-dev.github.io/gegl-color-ops/>。

## 选哪个目录

| 系统 | 下载 | 放到 |
|---|---|---|
| Windows x64 | [`windows-x64/`](windows-x64) 里的 31 个 `.dll` | `%LOCALAPPDATA%\gegl-0.4\plug-ins` |
| Linux x86_64 | [`linux-x64/`](linux-x64) 里的 30 个 `.so` | `~/.local/share/gegl-0.4/plug-ins` |
| macOS (Apple Silicon) | 本目录暂无，见下方「macOS 怎么拿」 | `~/Library/Application Support/gegl-0.4/plug-ins` |

> **两端产物同源**：Windows 由本机 MSYS2 交叉编译，Linux 由 GitHub Actions 的
> `ubuntu-latest` 编出后取回，模块名与 `manifest.csv` 一一对应。
>
> `gray-to-component.dll` 目前只有 Windows 版（Linux 那个 `.so` 等下一次 CI 出）。
> 它只给 HSV/LCh 分量曲线插件当编码器用；Linux 上暂时缺它时插件会自动退回三条
> 曲线编码，功能不受影响。
> `lb:gray-to-component` 2026-11-15 曾停编，2026-11-17 起恢复（HSV/LCh 分量曲线
> 插件要用它当编码器，一个滤镜顶三条曲线），所以模块数从 28 变成 30/31。

- GIMP Flatpak（Linux）：放进 `~/.var/app/org.gimp.GIMP/data/gegl-0.4/plug-ins`

## macOS 怎么拿

macOS 包由 GitHub Actions 在 Apple Silicon 云机器（`macos-15`）上编译：仓库
**每次 push 都会构建**，产物以 artifact 形式挂在 Actions 运行页
（`macos-arm64`，与算子总数同步，当前 31 个 `.dylib`）——GitHub 上打开 Actions → 选最新一次 run →
Artifacts 里下载。装了 Homebrew GIMP 的用户把这些 `.dylib` 放到
`~/Library/Application Support/gegl-0.4/plug-ins` 即可。

注意：**macOS 上 GEGL 0.4.60+ 只加载 `.dylib`**（GEGL 自己的模块扫描写死了
平台后缀，`.so` 会被静默跳过；Linux 上仍是 `.so`）。build.sh 按平台输出正确
后缀；CI 里同样跑加载 + 恒等渲染验证，绿灯才算数。

放完**重启 GIMP**，滤镜出现在「图像 → 颜色 → SuperMrWang」下的
Tone / Color / Blend / Mask 四个分组里。

## 可以只下一个

每个 `.dll` / `.so` 都是独立算子，只想要某个滤镜就只下那一个文件。

## 每个文件对应哪个滤镜

见 [`manifest.csv`](manifest.csv)：`platform, file, op_id, title, bytes, sha256`。
`op_id` 就是 GEGL 里的名字（例如 `lb:hue-saturation`），出问题时可以直接查：

```bash
gegl --info lb:hue-saturation
```

## 构建环境（挑包前先看一眼）

| 包 | 编译环境 | 适用 |
|---|---|---|
| `windows-x64` | MSYS2 mingw-w64 gcc 13，GEGL 0.4.72 头文件 | 64 位 GIMP 3（GEGL 0.4.x） |
| `linux-x64` | Ubuntu 24.04，gcc 13，GEGL 0.4.48 | x86_64，**glibc ≥ 2.39**（Ubuntu 24.04+、Fedora 40+、Debian 13、Arch）；更老的发行版请自己编译 |
| `macos-arm64`（CI artifact） | GitHub Actions macos-15，clang，Homebrew GEGL | Apple Silicon（M1/M2/M3/M4），装了 Homebrew GIMP 或带 GEGL 的应用 |

两点实话说在前面：

1. Linux 包是在 Ubuntu 24.04 上编的，因为它链的是较新的 glibc，Ubuntu 22.04 之类
   老系统会报 `GLIBC_2.39 not found`。要兼容更老的发行版，用 CI 或自己的机器编一次。
2. Linux 包**没有在 GIMP 图形界面里逐个点过**，但 CI 每次构建都会跑
   `tools/check-linux.sh`：按源码目录（跳过 `.disabled`）逐个把算子建出来跑恒等渲染，
   全绿才留下 artifact。GIMP 里看不到时，先用上面的 `gegl --info` 确认算子是否被加载。

## 校验完整性

```bash
cd dist && sha256sum -c SHA256SUMS.txt
```

Windows 没有 `sha256sum`，用 PowerShell 比对 `manifest.csv`：

```powershell
Get-FileHash dist/windows-x64/hue-saturation.dll -Algorithm SHA256
```

## 升级 / 卸载

- **装新版前先删旧文件**。`exposure` 已改名为 `lb-exposure`（Linux 下原名会和 GEGL
  内置 `exposure` 的 GType 撞车，导致算子静默不加载），所以旧的 `exposure.dll` /
  `exposure.so` 必须删掉，否则同一个 `lb:exposure` 会被注册两次。
- 卸载 = 把放进去的这些文件删掉，GIMP 重启后菜单里就没了。
- 回退到旧版本：直接拿上一个 commit 里的 `dist/` 覆盖。
