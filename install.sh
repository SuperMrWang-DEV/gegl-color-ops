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
  fail=0
  for c in "$ROOT"/ops/*/*.c; do
    name="$(basename "$c" .c)"
    op="$(grep -m1 -oE '"[a-z0-9]+:[A-Za-z0-9._-]+"' "$c" | tr -d '"')"
    if gegl --info "${op:-$name}" >/dev/null 2>&1; then
      printf '  OK   %s\n' "${op:-$name}"
    else
      printf '  FAIL %s\n' "${op:-$name}"; fail=$((fail+1))
    fi
  done
  [ "$fail" -eq 0 ] && echo "· 全部注册成功" || { echo "· $fail 个未注册"; exit 1; }
fi
