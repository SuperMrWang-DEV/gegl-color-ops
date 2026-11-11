#!/usr/bin/env bash
# 验证 build/*.so 能否被 GEGL 加载并正确渲染，不需要开 GIMP。Linux（原生或 WSL）
# 和 macOS CI 都能用；macOS 上 gcc 会被解析成 clang，一样能编 ldcheck。
#   用法: ./tools/check-linux.sh
#         OPS_DIR=dist/linux-x64 ./tools/check-linux.sh    # 验已打包的产物
#
# 注意：变量一律写成 ${VAR} —— macOS 的 bash 3.2 会把变量名后面紧跟的
# 多字节字符（如全角括号）连进变量名，报 unbound variable。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPS="${OPS_DIR:-$ROOT/build}"
OUT="${OUT_DIR:-$ROOT/build}"

CC="${CC:-gcc}"
command -v "$CC" >/dev/null || { echo "✗ 需要 $CC" >&2; exit 1; }
pkg-config --exists gegl-0.4 || { echo "✗ 需要 gegl-0.4 开发头文件（apt install libgegl-dev）" >&2; exit 1; }
[ -d "$OPS" ] || { echo "✗ 找不到模块目录 ${OPS}，先编译" >&2; exit 1; }

# GEGL 只从一个 GEGL_PATH 找插件，系统自带的 core 算子目录必须一起给，否则
# buffer-source / write-buffer 都加载不到，测试程序会崩在空节点上。
SYS_OPS="$(pkg-config --variable=libdir gegl-0.4)/gegl-0.4"

mkdir -p "$OUT"
"$CC" "$ROOT/tools/ldcheck.c" $(pkg-config --cflags --libs gegl-0.4) -o "$OUT/ldcheck"

IDs=()
for c in "$ROOT"/ops/*/*.c; do
  [ -f "$(dirname "$c")/.disabled" ] && continue
  id="$(grep -m1 -oE '"name",[[:space:]]*"[a-z0-9]+:[A-Za-z0-9._-]+"' "$c" | grep -oE '"[a-z0-9]+:[A-Za-z0-9._-]+"' | tr -d '"')"
  [ -n "$id" ] && IDs+=("$id")
done

echo "· 模块目录 ${OPS}（$(ls "$OPS"/*.so 2>/dev/null | wc -l) 个 .so）"
GEGL_PATH="$OPS:$SYS_OPS" "$OUT/ldcheck" "${IDs[@]}"
