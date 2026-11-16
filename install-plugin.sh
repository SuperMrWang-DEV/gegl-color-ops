#!/usr/bin/env bash
# 安装 Python 插件到 GIMP 用户插件目录 / install the Python plug-ins
# 用法: ./install-plugin.sh [GIMP用户配置目录]
#   缺省自动挑 AppData/Roaming/GIMP 下最新的 3.x
# plugin/ 下的每个子目录各装一份；带 .disabled 标记的跳过。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$ROOT/plugin"

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
for SRC in "$SRC_ROOT"/*/; do
  NAME="$(basename "$SRC")"
  # .disabled 标记 = 源码保留但暂时不安装（删掉标记即恢复）
  if [ -f "$SRC/.disabled" ]; then
    echo "· plugin/$NAME 已标记停用（plugin/$NAME/.disabled），跳过"
    echo "  恢复方法：rm plugin/$NAME/.disabled && ./install-plugin.sh"
    continue
  fi
  rm -rf "$DST/plug-ins/$NAME"
  cp -r "$SRC" "$DST/plug-ins/$NAME"
  echo "· 已安装到 $DST/plug-ins/$NAME"
done
echo "· 重启 GIMP 后生效："
echo "    颜色 → SuperMrWang       应用图像 / 计算"
echo "    选择 → SuperMrWang       图层 → 选区 / 通道（含 gray-mask）"
echo "    图层右键 → SuperMrWang   Layer to Selection / Layer to Channel"
echo "  （sky-replace 已标 .disabled 暂不安装；恢复：rm plugin/sky-replace/.disabled）"
