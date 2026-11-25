# 介绍片（4K · 8 分钟）

成片不在仓库里（4K 八分钟 200 MB+，超过 GitHub 单文件上限），生成到
`../outputs/video/`。这里是可复现的工程。

```bash
python tools/video/shoot.py     # 1. 截站点高清图（2x DPR → tools/video/shots）
python tools/video/render.py    # 2. 按分镜渲染 3840×2160 画布（frames/）
python tools/video/build.py     # 3. 配音 + 字幕 + 编码 + 拼接（outputs/video/*.mp4）
python tools/video/cover.py     # 4. 封面（outputs/video/cover.png）
```

`build.py plan` 只跑配音并打印时长表，不编码 —— 改文案时先看这个，
总长要压在 8 分钟左右。

## 五个文件各管什么

| 文件 | 职责 |
|---|---|
| `script.py` | 分镜表：章节、标题、副标题、画面类型、素材、旁白。**改内容只动这里** |
| `render.py` | 把一条分镜画成 4K PNG：深色底 + 紫蓝 accent，和站点一致 |
| `build.py` | edge-tts 配音 → 量时长定镜长 → 每镜编码（字幕烧进片段）→ concat → 混音 + loudnorm |
| `cover.py` | 4K 封面 |
| `shoot.py` | Chrome 2× DPR 截站点页面 |

画面类型：`hero` 开场、`shot` 整页截图卡片、`grid` 一类算子的缩略图矩阵、
`usage` 三种用法三卡 + 命令行、`tree` 仓库结构 + 统计、`stat` 大数字、
`code` 终端块、`steps` 横向步骤卡、`duo` 左右两卡、`outro` 结尾。

## 画面运动：为什么不用 zoompan

第一版用 `zoompan` 做 1.00→1.045 的推近，成片**肉眼可见地抖**。
量化后原因是整数裁剪：帧间位移应在每帧 -0.48 px 稳定推进，实测却在
-1.85…+1.85 之间来回跳（每帧退 2 px 或原地不动），这就是"抖"。

现在的做法，三个必须同时满足：

1. **预放大一次**（`build.prep()` → `tools/video/pre/*.png`，4240×2320），
   之后每帧只做无损 `crop`。
2. **位移严格 1 px/帧**：速度恒定的整数平移是平滑的，不匀速才是抖。
3. **`crop` 必须加 `exact=1`**：默认会把 x 舍入到偶数，2 px 位移就变成
   「+2 / 0」交替 —— 平均速度对但节奏不均，仍然抖。

改完实测帧间位移 `1.000 ± 0.014 px`（残差是编码噪声）。

配套约束：预放大留出 **400 px** 横向余量，所以 `render.M = 400`（左右安全
边距）。**别把 M 调小**，否则滑到极限时标题会被裁掉。

## 几个坑

- **镜长由配音决定**：`hold = max(voice + 1.1, 4.2)`，所以文案长度就是片长。
  现在是 48 镜 / 2074 字 → 484 s。单镜别超过 13 s（400 px 余量 ÷ 30 fps）。
- **字幕在每条片段里单独烧**（`ass` 滤镜），不是最后统一烧 —— 这样只编码一遍 4K。
  Windows 路径要传相对文件名 + `cwd=BUILD`，否则 `ass=C:/...` 里的冒号会被当成
  参数分隔符。
- 无对比图的算子（`cmyk-compose` / `displace` / `match-color`，多输入 pad，CLI
  喂不了）在网格里画斜纹占位 + 一行说明，不要 P 一张假图。
- 字幕断行**切点只能落在标点之后**，否则会出现以「，」开头的行。
- 音频最后过一遍 `loudnorm=I=-16:TP=-1.5`：原始素材 mean 只有 -28 dB，
  手机外放听不清。
- 改 `build.py` 的 `RATE`（语速）后要删 `tools/video/audio/`，否则缓存会命中
  旧语速的 mp3。
