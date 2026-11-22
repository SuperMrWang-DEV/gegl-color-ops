# macOS arm64（Apple Silicon）

这个目录里的 `.dylib` 由 **另一台 Apple Silicon 机器**编译，不是 Windows 那台。

## 为什么单独一个目录 / 单独一条分支

三台"生产者"各写各的目录，互不覆盖：

| 平台 | 谁编 | 落在哪 | 推到哪 |
|---|---|---|---|
| Windows x64 | 开发机（MSYS2 gcc + `build.sh`） | `dist/windows-x64/*.dll` | `main` |
| Linux x86_64 | GitHub Actions `ubuntu-latest`（meson） | `dist/linux-x64/*.so` | CI artifact，人工取回 |
| macOS arm64 | 一台 MacBook（`./build.sh`） | `dist/macos-arm64/*.dylib` | `dist/mac` 分支 |

二进制冲突没法 merge，只能整份选一边。所以 **Mac 只写这个目录，推 `dist/mac`**，
开发机需要 macOS 产物时：

```bash
git fetch origin
git merge origin/dist/mac --no-ff      # 只带进 dist/macos-arm64 和清单
```

## 在 Mac 上怎么出这一份

```bash
brew install gegl            # 只装一次，build.sh 靠 pkg-config 找头文件
./tools/dist_mac.sh          # 同步 → 编译 → 整理 → 只提交本目录 → 推 dist/mac
```

`dist_mac.sh` 会先 `git pull --rebase`，这一步不能省：`dist/manifest.csv` 和
`dist/SHA256SUMS.txt` 是三个平台**共用**的，`tools/make_dist.py` 按磁盘上现有
文件重算，不先同步就会把 Windows / Linux 的行抹掉。

只想看看会提交什么：`./tools/dist_mac.sh --dry-run`。

## 用户怎么装

```bash
mkdir -p ~/Library/Application\ Support/gegl-0.4/plug-ins
cp dist/macos-arm64/*.dylib ~/Library/Application\ Support/gegl-0.4/plug-ins/
```

重启 GIMP。GEGL 0.4.60+ 在 macOS 只认 `.dylib`（不是 `.so`）。
Homebrew 装的 GIMP 用同一个目录。
