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

# 已废弃、但仍可能残留在用户插件目录里的旧目录：直接移出，避免它抢先注册
# 过程名（旧 layer-to-mask 会占住 lb-plugin-layer-to-selection，导致新插件
# 注册失败、菜单少一项）。
RETIRED="gray-mask layer-to-mask sky-replace"
mkdir -p "$DST/_retired-plugins"
for NAME in $RETIRED; do
  if [ -d "$DST/plug-ins/$NAME" ]; then
    mv "$DST/plug-ins/$NAME" "$DST/_retired-plugins/$NAME-retired-$(date +%Y%m%d%H%M%S)"
    echo "· 移出残留旧插件 $NAME → $DST/_retired-plugins/"
  fi
done

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
echo "· 重启 GIMP 后生效（菜单栏顶层多一个 SuperMrWang，与「颜色」「图层」平级）："
echo "    SuperMrWang → Convert    图层 → 选区 / 通道 / 一次拆出 R·G·B·Alpha（原始像素，彩色按亮度）"
echo "                             Channel / Selection / Mask / Path 十二向互转（零参数，点一下直接跑）"
echo "    SuperMrWang → Mask       Alpha Curves（通道 → Alpha + alpha 曲线）/ Color Range（色彩范围）"
echo "                             Channel to Mask（通道 → 图层蒙版）"
echo "                             最大值 / 最小值（膨胀 / 腐蚀，半径 1–100，蒙版扩边收边）"
echo "    SuperMrWang → Blend      应用图像 / 计算"
echo "    SuperMrWang → Retouch    HSV·HSL·Lab·LCh·HSI Split + 高低频/双曲线/中性灰磨皮"
echo "    图层右键 → SuperMrWang → Convert / Mask / Retouch   与上面同样的分组，只留单层能用的"
echo "    通道右键 → SuperMrWang → Convert / Mask             以通道为源的那几项，点的哪条就用哪条"
echo "  （gray-mask 已被 layer-to-* 取代，标记停用；sky-replace 同样停用）"
