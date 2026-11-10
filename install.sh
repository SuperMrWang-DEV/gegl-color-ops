#!/usr/bin/env bash
# SuperMrWang · GEGL 算子集合 —— 编译 + 安装到 GEGL 用户插件目录
#   用法: ./install.sh                      默认目标目录
#         GEGL_PLUGIN_DIR=/path ./install.sh 自定义目标
#         ./install.sh --verify             装完立刻用 gegl CLI 逐个确认注册
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY=0
[ "${1:-}" = "--verify" ] && VERIFY=1

"$ROOT/build.sh"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) EXT=dll
      : "${DEST:=${LOCALAPPDATA:-$HOME/AppData/Local}/gegl-0.4/plug-ins}" ;;
  Darwin)               EXT=dylib
      : "${DEST:=$HOME/Library/Application Support/gegl-0.4/plug-ins}" ;;
  *)                    EXT=so
      : "${DEST:=$HOME/.local/share/gegl-0.4/plug-ins}" ;;
esac
DEST="${GEGL_PLUGIN_DIR:-$DEST}"

mkdir -p "$DEST"
echo "· 安装到 $DEST"
cp -f "$ROOT/build"/*.$EXT "$DEST"/
echo "· 已复制 $(ls "$ROOT/build"/*.$EXT | wc -l) 个模块（重启 GIMP 生效）"

if [ "$VERIFY" = "1" ]; then
  echo "· 逐个确认注册（gegl --info）"

  # gegl 通常不在 PATH 里（GIMP 只带 exe 不改进系统环境），这里自己找，
  # 找到后把 GEGL_PATH 指向「刚装好的目录 + GIMP 自带算子」，避免误判未注册。
  GEGL_BIN="${GEGL_BIN:-$(command -v gegl 2>/dev/null || true)}"
  for cand in \
      "/d/fastsoftware/GIMP 3/bin/gegl.exe" \
      "/c/Program Files/GIMP 3/bin/gegl.exe" \
      "${LOCALAPPDATA:-/nonexistent}/Programs/GIMP 3/bin/gegl.exe"
  do
    [ -n "$GEGL_BIN" ] && break
    [ -x "$cand" ] && GEGL_BIN="$cand"
  done
  if [ -z "$GEGL_BIN" ]; then
    echo "· 找不到 gegl 可执行文件，跳过校验（可用 GEGL_BIN=... ./install.sh --verify 指定）"
    exit 0
  fi

  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      DEST_WIN="$(cd "$DEST" && pwd -W 2>/dev/null || echo "$DEST")"
      SYS_OPS="$(cd "$(dirname "$GEGL_BIN")/../lib/gegl-0.4" 2>/dev/null && pwd -W || true)"
      sep=";";;
    *)  DEST_WIN="$DEST"; SYS_OPS=""; sep=":";;
  esac
  [ -n "${SYS_OPS:-}" ] && export GEGL_PATH="$DEST_WIN$sep$SYS_OPS" || export GEGL_PATH="$DEST_WIN"

  fail=0
  for c in "$ROOT"/ops/*/*.c; do
    name="$(basename "$c" .c)"
    op="$(grep -m1 -oE '"[a-z0-9]+:[A-Za-z0-9._-]+"' "$c" | tr -d '"')"
    if "$GEGL_BIN" --info "${op:-$name}" >/dev/null 2>&1; then
      printf '  OK   %s\n' "${op:-$name}"
    else
      printf '  FAIL %s\n' "${op:-$name}"; fail=$((fail+1))
    fi
  done
  [ "$fail" -eq 0 ] && echo "· 全部注册成功" || { echo "· $fail 个未注册"; exit 1; }
fi
