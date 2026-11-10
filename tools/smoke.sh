#!/usr/bin/env bash
# 每个算子用默认参数渲染一张测试图，抓崩溃 / 黑图 / 空输出。
#   用法: ./tools/smoke.sh [输入图]      默认用 tools/ 里自动生成的测试图
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${OUT_DIR:-$ROOT/build/smoke}"
IN="${1:-$ROOT/build/smoke-input.png}"
OPS="${OPS_DIR:-$ROOT/build}"     # 想跑旧版 DLL 对照时用 OPS_DIR=backup/xxx

# gegl 一般不在 PATH 上（GIMP 只装 exe），自己找一遍
GEGL_BIN="${GEGL_BIN:-$(command -v gegl 2>/dev/null || true)}"
for cand in "/d/fastsoftware/GIMP 3/bin/gegl.exe" \
            "/c/Program Files/GIMP 3/bin/gegl.exe" \
            "${LOCALAPPDATA:-/nonexistent}/Programs/GIMP 3/bin/gegl.exe"; do
  [ -n "$GEGL_BIN" ] && break
  [ -x "$cand" ] && GEGL_BIN="$cand"
done
[ -n "$GEGL_BIN" ] || { echo "✗ 找不到 gegl 可执行文件，可用 GEGL_BIN=... 指定" >&2; exit 1; }

if [ ! -f "$IN" ]; then
  python "$ROOT/tools/make_test_image.py" "$IN" || exit 1
fi

mkdir -p "$OUT"

# GEGL_PATH 在 Windows 上必须是 Windows 形式路径（C:/...），POSIX 的 /c/... 不认，
# 会导致连核心算子 gegl:nop 都加载不到（表现为 segfault）。
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
      BUILD_DIR="$(cd "$OPS" && pwd -W)"
      sep=";"
      for cand in "/d/fastsoftware/GIMP 3/lib/gegl-0.4" "/c/Program Files/GIMP 3/lib/gegl-0.4"; do
        [ -d "$cand" ] && SYS_OPS="$(cd "$cand" && pwd -W)" && break
      done
      ;;
  *)  BUILD_DIR="$OPS"; sep=":"; SYS_OPS="" ;;
esac
if [ -n "${SYS_OPS:-}" ]; then
  export GEGL_PATH="$BUILD_DIR$sep$SYS_OPS"
else
  export GEGL_PATH="$BUILD_DIR"
  echo "· 未找到 GIMP 自带算子目录，GEGL_PATH 只含 build/（核心算子可能缺失）"
fi

ok=0; fail=0
for c in "$ROOT"/ops/*/*.c; do
  name="$(basename "$c" .c)"
  op="$(grep -m1 -oE '"[a-z0-9]+:[A-Za-z0-9._-]+"' "$c" | tr -d '"')"
  if "$GEGL_BIN" "$IN" -o "$OUT/$name.png" -- "${op:-$name}" >/dev/null 2>"$OUT/$name.err"; then
    printf '  OK   %s\n' "${op:-$name}"; ok=$((ok+1))
  else
    printf '  FAIL %s  -> %s\n' "${op:-$name}" "$(head -2 "$OUT/$name.err" | tr '\n' ' ')"
    fail=$((fail+1))
  fi
done

echo "· 渲染成功 $ok / 失败 $fail  -> $OUT"
[ "$fail" -eq 0 ] || exit 1
