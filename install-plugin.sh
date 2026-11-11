#!/usr/bin/env bash
# 安装 Python 插件到 GIMP 用户插件目录 / install the Python plug-in
# 用法: ./install-plugin.sh [GIMP用户配置目录]
#   缺省自动挑 AppData/Roaming/GIMP 下最新的 3.x
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/plugin/ps-blend"

# .disabled 标记 = 源码保留但暂时不安装（删掉标记即恢复）
if [ -f "$SRC/.disabled" ]; then
  echo "· plugin/ps-blend 已标记停用（plugin/ps-blend/.disabled），跳过安装"
  echo "  恢复方法：rm plugin/ps-blend/.disabled && ./install-plugin.sh"
  exit 0
fi

DST="${1:-}"
if [ -z "$DST" ]; then
  for d in "$APPDATA/GIMP"/3.* "$HOME/AppData/Roaming/GIMP"/3.*; do
    [ -d "$d" ] && DST="$d"
  done
fi
if [ -z "${DST:-}" ]; then
  echo "✗ 找不到 GIMP 用户配置目录，请手动指定：./install-plugin.sh <GIMP目录>" >&2
  exit 1
fi

mkdir -p "$DST/plug-ins"
rm -rf "$DST/plug-ins/ps-blend"
cp -r "$SRC" "$DST/plug-ins/ps-blend"
echo "· 已安装到 $DST/plug-ins/ps-blend"
echo "· 重启 GIMP 后生效：颜色 → SuperMrWang → Apply Image PS / Calculations PS"
