# 介绍片（4K · 5 分钟）

成片不在仓库里（4K 五分钟 160 MB+，超过 GitHub 单文件上限），生成到
`../outputs/video/`。这里是可复现的工程。

```bash
python tools/video/shoot.py     # 1. 截站点高清图（2x DPR → tools/video/shots）
python tools/video/render.py    # 2. 按分镜渲染 3840×2160 画布（frames/）
python tools/video/build.py     # 3. 配音 + 字幕 + 编码 + 拼接（outputs/video/*.mp4）
python tools/video/cover.py     # 4. 封面（outputs/video/cover.png）
```

`build.py plan` 只跑配音并打印时长表，不编码 —— 改文案时先看这个，
总长要压在 5 分钟左右。

## 四个文件各管什么

| 文件 | 职责 |
|---|---|
| `script.py` | 分镜表：章节、标题、副标题、画面类型、素材、旁白。**改内容只动这里** |
| `render.py` | 把一条分镜画成 4K PNG：深色底 + 紫蓝 accent，和站点一致 |
| `build.py` | edge-tts 配音 → 量时长定镜长 → 每镜编码（字幕烧进片段）→ concat → 混音 + loudnorm |
| `cover.py` | 4K 封面 |

画面类型：`hero` 开场、`shot` 整页截图卡片、`grid` 一类算子的缩略图矩阵、
`usage` 三种用法三卡 + 命令行、`tree` 仓库结构 + 统计、`outro` 结尾。

## 几个坑

- **镜长由配音决定**：`hold = max(voice + 1.1, 4.2)`，所以文案长度就是片长。
  现在的稿子是 1300 字左右 → 298.8 s。
- **字幕在每条片段里单独烧**（`ass` 滤镜），不是最后统一烧 —— 这样只编码一遍 4K。
  Windows 路径要传相对文件名 + `cwd=BUILD`，否则 `ass=C:/...` 里的冒号会被当成
  参数分隔符。
- `zoompan` 的输入先 `scale` 到 1.06 倍且**宽高取偶数**，否则 yuv420p 报错；
  推近范围 1.00→1.045，超过 1.06 就会从放大变成插值模糊。
- 无对比图的算子（`cmyk-compose` / `displace` / `match-color`，多输入 pad，CLI
  喂不了）在网格里画斜纹占位 + 一行说明，不要 P 一张假图。
- 字幕断行**切点只能落在标点之后**，否则会出现以「，」开头的行。
- 音频最后过一遍 `loudnorm=I=-16:TP=-1.5`：原始素材 mean 只有 -28 dB，
  手机外放听不清。
