#!/usr/bin/env bash
# 在 macOS（Apple Silicon）上编出全部算子，把 .dylib 提交到 dist/macos-arm64/
# 并推到 dist/mac 分支。只干这一件事：不碰源码、不碰 dist/windows-x64、
# 不碰 dist/linux-x64。
#
# 用法（在仓库根目录）:
#   ./tools/dist_mac.sh              # 同步 → 编译 → 整理 → 提交 → 推到 dist/mac
#   ./tools/dist_mac.sh --dry-run    # 只同步/编译/整理，不提交不推送
#   ./tools/dist_mac.sh --no-pull    # 跳过 git pull（离线时用）
#   ./tools/dist_mac.sh --no-build   # 跳过编译，只整理现有的 build/
#
# 任务分工：
#   Windows 那台：写代码、编 Windows，推 main。
#   这台 Mac    ：只编 macOS，只写 dist/macos-arm64/，推 dist/mac 分支。
#   取产物      ：Windows 上 git fetch origin && git merge origin/dist/mac --no-ff
#
# 为什么用单独分支：二进制冲突没法 merge，只能整份选一边。让 Mac 只往
# dist/mac 写，main 的提交序列就不会被两个平台的产物互相搅动。
#
# 为什么必须先 pull：dist/manifest.csv 和 dist/SHA256SUMS.txt 是三个平台共用的，
# tools/make_dist.py 按「磁盘上现有文件」重算——不先 pull 就没有 Windows/Linux
# 的行，一提交就把它们抹掉。所以 pull 放在最前面。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BRANCH="${LB_DIST_BRANCH:-dist/mac}"
BASE="${LB_DIST_BASE:-main}"
PLAT="macos-arm64"
DRY=0
DO_PULL=1
DO_BUILD=1
for a in "$@"; do
  case "$a" in
    --dry-run)  DRY=1 ;;
    --no-pull)  DO_PULL=0 ;;
    --no-build) DO_BUILD=0 ;;
    -h|--help)  sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "✗ 不认识的参数：$a" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }

# ---- 0. 前置检查 -------------------------------------------------------------
if [ "$(uname -s)" != "Darwin" ]; then
  echo "✗ 这个脚本只在 macOS 上跑（当前：$(uname -s)）。" >&2
  echo "  Windows 用 tools/make_dist.py，Linux 由 CI 出包。" >&2
  exit 1
fi
[ -f build.sh ] && [ -d ops ] || { echo "✗ 请在仓库根目录运行" >&2; exit 1; }
command -v git >/dev/null || { echo "✗ 找不到 git" >&2; exit 1; }

PY=python3
$PY -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" \
  || { echo "✗ 需要 python3 ≥ 3.8" >&2; exit 1; }

# 只允许 dist/ 之外没有改动：这个脚本绝不能把代码改动顺手提交上去
dirty="$(git status --porcelain -- . ':(exclude)dist' || true)"
if [ -n "$dirty" ]; then
  echo "✗ dist/ 之外还有未提交的改动，先提交或 stash 再跑：" >&2
  printf '%s\n' "$dirty" >&2
  exit 1
fi

# ---- 1. 先同步（manifest 是三个平台共用的）----------------------------------
if [ "$DO_PULL" = 1 ]; then
  say "· git fetch + pull --rebase origin $BASE"
  git fetch --quiet origin
  git pull --rebase --quiet origin "$BASE"
  say "· 当前 HEAD：$(git log --oneline -1)"
else
  say "· 跳过同步（--no-pull）"
fi

# ---- 2. 编译 ----------------------------------------------------------------
if [ "$DO_BUILD" = 1 ]; then
  say "· ./build.sh（GEGL 头文件：brew install gegl）"
  ./build.sh
else
  say "· 跳过编译（--no-build）"
fi

# || true：没有 .dylib 时 ls 返回 2，set -e + pipefail 会让整个赋值静默退出，
# 那样就看不到下面那句「编译没成功？」的提示了
built=$(ls build/*.dylib 2>/dev/null | wc -l | tr -d ' ' || true)
say "· build/ 里有 $built 个 .dylib"
[ "$built" -gt 0 ] || { echo "✗ build/ 里没有 .dylib，编译没成功？" >&2; exit 1; }

# ---- 3. 整理进 dist/macos-arm64 ---------------------------------------------
say "· $PY tools/make_dist.py"
$PY tools/make_dist.py

# ---- 4. 只提交该提交的东西 ---------------------------------------------------
# manifest.csv / SHA256SUMS.txt 里带着 Windows、Linux 的行（pull 过就是齐的），
# 所以它们要一起提交——但只 add 这两个文件加本平台目录。
git add -A -- "dist/$PLAT" dist/manifest.csv dist/SHA256SUMS.txt

if git diff --cached --quiet; then
  say "· dist/ 没有变化（与已提交的一致），不需要提交"
  exit 0
fi

n=$(ls "dist/$PLAT"/*.dylib 2>/dev/null | wc -l | tr -d ' ' || true)
sample=$(ls "dist/$PLAT"/*.dylib 2>/dev/null | head -1 | xargs -n1 basename 2>/dev/null \
         | sed 's/\.dylib$//' || true)
[ -n "$sample" ] || sample="none"

say ""
say "· 将要提交："
git diff --cached --stat -- "dist/$PLAT" dist/manifest.csv dist/SHA256SUMS.txt | sed 's/^/    /'
say ""

if [ "$DRY" = 1 ]; then
  say "· --dry-run：不提交、不推送。"
  git reset --quiet
  exit 0
fi

git commit --quiet -m "dist(macos-arm64): 重新编译 $n 个模块（$sample 等）" \
  -m "由 tools/dist_mac.sh 在 Apple Silicon 上编译；只含 dist/$PLAT 与共用清单。
源码在 $BASE 上，本分支只承载 macOS 产物。"

say "· 推送 → origin $BRANCH"
git push origin "HEAD:$BRANCH"

say ""
say "✓ 完成，$n 个 .dylib 已推到 $BRANCH。"
say "  Windows 那台取用： git fetch origin && git merge origin/$BRANCH --no-ff"
