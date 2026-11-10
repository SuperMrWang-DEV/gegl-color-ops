#!/usr/bin/env bash
# SuperMrWang · GEGL 算子集合 —— 一键编译
#   用法: ./build.sh            编译到 build/
#         CC=clang ./build.sh   换编译器
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$ROOT/build"

# ---------- 1. 定位 gegl-0.4 的 pkg-config ----------
sep=":"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) sep=";" ;; esac

if ! pkg-config --exists gegl-0.4 2>/dev/null; then
  for cand in \
      "/d/fastsoftware/GIMP 3/lib/pkgconfig" \
      "/c/Program Files/GIMP 3/lib/pkgconfig" \
      "${LOCALAPPDATA:-/nonexistent}/Programs/GIMP 3/lib/pkgconfig" \
      "/usr/lib/pkgconfig" \
      "/usr/local/lib/pkgconfig"
  do
    if [ -d "$cand" ] && ls "$cand"/gegl-0.4.pc >/dev/null 2>&1; then
      export PKG_CONFIG_PATH="$cand${PKG_CONFIG_PATH:+$sep$PKG_CONFIG_PATH}"
      echo "· 使用 PKG_CONFIG_PATH=$cand"
      break
    fi
  done
fi

if ! pkg-config --exists gegl-0.4 2>/dev/null; then
  echo "✗ 找不到 gegl-0.4.pc，请先导出 PKG_CONFIG_PATH 指向 GIMP/GEGL 的 pkgconfig 目录" >&2
  exit 1
fi

CFLAGS_GEGL="$(pkg-config --cflags gegl-0.4)"
LIBS_GEGL="$(pkg-config --libs gegl-0.4)"

# ---------- 1.5 选工具链 ----------
# 机器上可能并存多个 gcc（如 Strawberry Perl 自带的 MinGW），它们缺少 libintl.h、
# 且 ABI 与 GIMP 官方 MSYS2 构建不同。这里用「能否预处理 gegl 的头」来筛。
# 注意: pkg-config 输出的路径含转义空格（GIMP\ 3），必须经 eval 展开，
#       否则 -I 会在空格处被切断。
probe() {
  local cc="$1" tmp="$ROOT/.probe.c" rc
  # gi18n-lib.h 要求先定义 GETTEXT_PACKAGE（正式编译时由 common/config.h 提供）
  printf '#define GETTEXT_PACKAGE "probe"\n#include <glib/gi18n-lib.h>\n#include <gegl.h>\n' > "$tmp"
  eval "\"$cc\" -fsyntax-only $CFLAGS_GEGL \"$tmp\"" >/dev/null 2>&1
  rc=$?
  rm -f "$tmp"
  return $rc
}
CANDIDATES=()
[ -n "${CC:-}" ] && CANDIDATES+=("$CC")
CANDIDATES+=("/c/msys64/mingw64/bin/gcc" "/mingw64/bin/gcc" "x86_64-w64-mingw32-gcc" "gcc" "cc" "clang")
TOOLCHAIN=""
for cand in "${CANDIDATES[@]}"; do
  command -v "$cand" >/dev/null 2>&1 || continue
  if probe "$cand"; then TOOLCHAIN="$cand"; break; fi
done
if [ -z "$TOOLCHAIN" ]; then
  echo "✗ 没有找到能编译 gegl 头文件的编译器（试过: ${CANDIDATES[*]}）" >&2
  echo "  提示: 用 CC=/c/msys64/mingw64/bin/gcc ./build.sh 指定，或装 MSYS2 mingw-w64-gcc" >&2
  exit 1
fi
echo "· 编译器 $TOOLCHAIN ($("$TOOLCHAIN" -dumpversion))"

# ---------- 2. 按平台决定后缀 ----------
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) EXT=dll ;;
  Darwin)               EXT=dylib ;;
  *)                    EXT=so ;;
esac

mkdir -p "$OUT"
echo "· gegl-0.4 $(pkg-config --modversion gegl-0.4) / 输出 $OUT/*.$EXT"

# ---------- 3. 逐个编译 ops/<name>/<name>.c ----------
fail=0; total=0
for c in "$ROOT"/ops/*/*.c; do
  dir="$(dirname "$c")"; name="$(basename "$c" .c)"; total=$((total+1))
  # -I<算子目录>  ：让 gegl-op.h 通过 GEGL_OP_C_SOURCE 自包含该 .c
  # -I<common>    ：共用 config.h
  if eval "$TOOLCHAIN" -shared -O2 -fPIC -Wall \
        -I"$dir" -I"$ROOT/common" \
        "$c" $CFLAGS_GEGL $LIBS_GEGL -lm \
        -o "$OUT/$name.$EXT" 2>"$OUT/.build-$name.log"; then
    printf '  OK   %-26s -> build/%s.%s\n' "${dir##*/}" "$name" "$EXT"
    rm -f "$OUT/.build-$name.log"
  else
    printf '  FAIL %-26s （详见 build/.build-%s.log）\n' "${dir##*/}" "$name"
    fail=$((fail+1))
  fi
done

echo "· 共 $total 个算子，失败 $fail 个"
[ "$fail" -eq 0 ] || exit 1
