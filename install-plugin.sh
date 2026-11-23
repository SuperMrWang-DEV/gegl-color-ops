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

# 翻译目录：plugin/_shared/lb_i18n.py 从 plug-ins/_shared 往上找 locale，
# 所以放在 plug-ins/locale 就能被命中。
if [ -d "$ROOT/locale" ]; then
  mkdir -p "$DST/plug-ins/locale"
  cp -r "$ROOT/locale/." "$DST/plug-ins/locale/"
  echo "· 已复制翻译目录（$(ls "$ROOT/locale" | tr '\n' ' ')）"
fi

# 一键装 ComfyUI 的安装器：插件里「AI 环境…」这个菜单项按 <插件目录>/ai-setup/
# 找它，找不到就只能让用户自己去翻仓库。所以安装时一定跟着拷过去。
if [ -f "$ROOT/tools/setup-ai.bat" ] && [ -f "$ROOT/tools/setup_ai.py" ]; then
  mkdir -p "$DST/plug-ins/ai-setup"
  cp "$ROOT/tools/setup-ai.bat" "$ROOT/tools/setup_ai.py" "$DST/plug-ins/ai-setup/"
  echo "· 已复制 AI 安装器 → $DST/plug-ins/ai-setup/（菜单 SuperMrWang → AI → AI Environment）"
fi
echo "· 重启 GIMP 后生效（菜单栏顶层多一个 SuperMrWang，与「颜色」「图层」平级）："
echo "    SuperMrWang → Convert    图层 → 选区 / 通道 / 一次拆出 R·G·B·Alpha（原始像素，彩色按亮度）"
echo "                             Channel / Selection / Mask / Path 十二向互转（零参数，点一下直接跑）"
echo "    SuperMrWang → Mask       Alpha Curves（通道 → Alpha + alpha 曲线）/ Color Range（色彩范围）"
echo "                             Channel to Mask（通道 → 图层蒙版）"
echo "                             最大值 / 最小值（膨胀 / 腐蚀，半径 1–100，蒙版扩边收边）"
echo "                             抠图 / 移除背景（本地：四边泛洪；AI：ComfyUI 的 RMBG-2.0）"
echo "                             选择并遮住（精修边缘：吸附/平滑/羽化/对比度/移动边缘/去色边）"
echo "    SuperMrWang → Blend      应用图像 / 计算"
echo "    SuperMrWang → Layer      图层样式（投影/内阴影/外发光/内发光/斜面浮雕/光泽/三种叠加/描边，
                             结果是一组可编辑图层，投影在外、内阴影在内；
                             对话框底部「Style code」可复制/粘贴整份样式到别的图层）"
echo "    SuperMrWang → Distort    Displace（按位移图重采样）/ 木偶变形（放钉子拖动，MLS 网格变形）
                             自由变形（贝塞尔网格 + 把手：拖交点改形状，拖把手弯网格线，Alt+点击加分割线）
                             消失点（拖四边形标出透视平面：贴图进去 / 拉正成矩形 / 折成台阶）"
echo "    SuperMrWang → AI         AI Inpaint（选区 + 提示词 → 本机 ComfyUI 重绘，需要 ComfyUI 在跑）"
echo "                             AI Inpaint (Advanced)（全参数，含底模下拉）"
echo "                             AI Environment（手选 ComfyUI 目录 / 自动启动 / 一键装 / 看模型清单）"
echo "    SuperMrWang → Retouch    HSV·HSL·Lab·LCh·HSI Split + 高低频/双曲线/中性灰磨皮"
echo "                             再各加一个「（AI 预修）」入口：结构 + 预修一起给"
echo "    图层右键 → SuperMrWang → Convert / Mask / Retouch   与上面同样的分组，只留单层能用的"
echo "    通道右键 → SuperMrWang → Convert / Mask             以通道为源的那几项，点的哪条就用哪条"
echo "  （gray-mask 已被 layer-to-* 取代，标记停用；sky-replace 同样停用）"
