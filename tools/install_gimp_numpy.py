#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 GIMP 3 自带的 Python 装 numpy。

为什么需要这个脚本（手装会踩的坑）：

1. GIMP 3 for Windows 自带一个精简 Python（没有 pip），所以不能 `pip install`。
2. 它是 **MSYS2 / MinGW** 构建：`sysconfig` 的 `EXT_SUFFIX` 是
       .cp314-mingw_x86_64_ucrt_llvm.pyd
   而 PyPI 上的 numpy 是 MSVC 构建的 `.cp314-win_amd64.pyd`。把官方 wheel
   解压进去、甚至改名，都会失败：
       - 不改名 → ModuleNotFoundError（importlib 按 EXT_SUFFIX 找不到文件）
       - 改名   → 导入表里写的是 python314.dll，GIMP 只有 libpython3.14.dll；
                  硬拷一份改名当 python314.dll 能过加载，但 PyInit 拿到的是
                  **另一个 CPython 实例**，报
                  "initialization of _multiarray_umath did not return an
                  extension module"
3. 唯一稳的路：用 MSYS2 的 `mingw-w64-ucrt-x86_64-python-numpy`（GCC 构建，
   链接 libpython3.14.dll，与 GIMP 同一个 DLL、同一个 CPython 实例），
   再把后缀从 `ucrt_gnu` 改成 `ucrt_llvm`，并补上它需要的 GCC 运行库。

用法：
    python tools/install_gimp_numpy.py                 # 自动找 GIMP
    python tools/install_gimp_numpy.py --gimp "D:/GIMP 3"
    python tools/install_gimp_numpy.py --msys2 "C:/msys64" --check

装完在 GIMP 里 `python-fu-eval` 里 import numpy 即可用。
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys

GIMP_MARK = os.path.join("lib", "python3.14", "site-packages")
MSYS2_SUFFIX = ".cp314-mingw_x86_64_ucrt_gnu.pyd"
GIMP_SUFFIX = ".cp314-mingw_x86_64_ucrt_llvm.pyd"
PKG = "mingw-w64-ucrt-x86_64-python-numpy"

# numpy 的 .pyd 动态链接这些；GIMP 是 clang 构建，一个都不带（只有 libwinpthread）。
DLLS = [
    "libgcc_s_seh-1.dll",
    "libgomp-1.dll",
    "libstdc++-6.dll",
    "libopenblas.dll",
    "libgfortran-5.dll",
    "libquadmath-0.dll",
]


def say(msg=""):
    print(msg)
    sys.stdout.flush()


def find_gimp(explicit=None):
    """找 GIMP 根目录（含 bin/gimp-console-3*.exe 和 lib/python3.14）。"""
    cands = []
    if explicit:
        cands.append(explicit)
    else:
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                cands.extend(glob.glob(os.path.join(base, "GIMP*")))
        for drive in ("C:", "D:", "E:"):
            for sub in ("", "Program Files", "fastsoftware", "software", "apps"):
                cands.extend(glob.glob(os.path.join(drive, sub, "GIMP*")))
    for c in cands:
        if os.path.isdir(os.path.join(c, GIMP_MARK)) and \
                glob.glob(os.path.join(c, "bin", "gimp-console-3*.exe")):
            return os.path.abspath(c)
    return None


def find_msys2(explicit=None):
    cands = [explicit] if explicit else []
    cands += [r"C:\msys64", r"D:\msys64", r"C:\msys32"]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "ucrt64", "bin")):
            return os.path.abspath(c)
    return None


def run(cmd, **kw):
    say("  $ " + " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ensure_msys2_numpy(msys2):
    """确保 MSYS2 里装了 ucrt64 的 python-numpy；没有就用 pacman 装。"""
    site = os.path.join(msys2, "ucrt64", "lib", "python3.14", "site-packages")
    if os.path.isdir(os.path.join(site, "numpy")):
        say("[1/4] MSYS2 里已有 numpy，跳过 pacman")
        return site

    pacman = os.path.join(msys2, "usr", "bin", "pacman.exe")
    if not os.path.isfile(pacman):
        raise SystemExit("找不到 %s，无法安装 MSYS2 包" % pacman)
    say("[1/4] 用 pacman 安装 %s（含 openblas / omp 依赖）" % PKG)
    r = run([pacman, "-S", "--noconfirm", "--needed", PKG])
    say(r.stdout.strip()[-600:] or r.stderr.strip()[-600:])
    if not os.path.isdir(os.path.join(site, "numpy")):
        raise SystemExit("pacman 装完了但没找到 %s" % os.path.join(site, "numpy"))
    return site


def copy_numpy(msys_site, gimp_site):
    """覆盖式复制，**不删除**目标目录。

    重装时直接 rmtree 会被拦（也确实没必要）：numpy 的目录结构是完整的，
    同名文件覆盖掉就够。多出来的旧文件留着也无害，import 时用不到。
    """
    say("[2/4] 复制 numpy 到 GIMP 的 site-packages（覆盖同名文件）")
    copied = []
    for name in sorted(os.listdir(msys_site)):
        if not name.startswith("numpy"):
            continue
        src, dst = os.path.join(msys_site, name), os.path.join(gimp_site, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        copied.append(name)
        say("  + " + name)
    if not any(n == "numpy" for n in copied):
        raise SystemExit("没复制到 numpy 目录")


def fix_suffix(gimp_site):
    """ucrt_gnu → ucrt_llvm：GIMP 的 importlib 只认后者。"""
    say("[3/4] 修正扩展后缀 %s → %s" % (MSYS2_SUFFIX, GIMP_SUFFIX))
    n = 0
    already = 0
    for path in glob.glob(os.path.join(gimp_site, "numpy", "**", "*.pyd"),
                          recursive=True):
        if path.endswith(MSYS2_SUFFIX):
            # 用 replace 而不是 rename：重跑时 llvm 那份已经在了，
            # rename 在 Windows 上不能覆盖已存在的目标。
            os.replace(path, path[:-len(MSYS2_SUFFIX)] + GIMP_SUFFIX)
            n += 1
        elif path.endswith(GIMP_SUFFIX):
            already += 1
    say("  改名 %d 个，已经是 llvm 后缀的 %d 个" % (n, already))
    if n == 0 and already == 0:
        raise SystemExit("一个 .pyd 都没找到，检查 numpy 是不是它自己的构建")


def install_dlls(msys2, gimp_root):
    say("[4/4] 补 GCC 运行库到 GIMP/bin（只补缺的，不覆盖已有）")
    src_dir = os.path.join(msys2, "ucrt64", "bin")
    dst_dir = os.path.join(gimp_root, "bin")
    for name in DLLS:
        src, dst = os.path.join(src_dir, name), os.path.join(dst_dir, name)
        if not os.path.isfile(src):
            raise SystemExit("MSYS2 里没有 %s" % src)
        if os.path.isfile(dst):
            say("  = %s（已有）" % name)
            continue
        shutil.copy2(src, dst)
        say("  + %s" % name)


def verify(gimp_root):
    """用 GIMP 自己的 python.exe 真 import 一次。"""
    exe = os.path.join(gimp_root, "bin", "python.exe")
    code = (
        "import numpy as np\n"
        "print('numpy', np.__version__)\n"
        "a = np.arange(12, dtype=np.float64).reshape(3, 4)\n"
        "print('matmul', (a @ a.T)[0].tolist())\n"
        "print('solve', round(float(np.linalg.solve("
        "np.eye(4), np.ones(4))[0]), 3))\n"
    )
    r = subprocess.run([exe, "-c", code], capture_output=True, text=True)
    say("  " + (r.stdout.strip() or r.stderr.strip()[-400:]))
    return r.returncode == 0 and "numpy" in r.stdout


def main():
    ap = argparse.ArgumentParser(description="给 GIMP 3 自带 Python 装 numpy")
    ap.add_argument("--gimp", help="GIMP 根目录，例如 \"D:/GIMP 3\"")
    ap.add_argument("--msys2", help="MSYS2 根目录，默认 C:/msys64")
    ap.add_argument("--check", action="store_true", help="只验证，不安装")
    args = ap.parse_args()

    gimp = find_gimp(args.gimp)
    if not gimp:
        raise SystemExit("没找到 GIMP 3（需要有 bin/gimp-console-3*.exe 和 "
                         "lib/python3.14/site-packages），用 --gimp 指定")
    gimp_site = os.path.join(gimp, GIMP_MARK)
    say("GIMP:  %s" % gimp)
    say("site:  %s" % gimp_site)

    if args.check:
        ok = verify(gimp)
        raise SystemExit(0 if ok else 1)

    msys2 = find_msys2(args.msys2)
    if not msys2:
        raise SystemExit("没找到 MSYS2（需要 ucrt64/bin），用 --msys2 指定")
    say("MSYS2: %s" % msys2)

    msys_site = ensure_msys2_numpy(msys2)
    copy_numpy(msys_site, gimp_site)
    fix_suffix(gimp_site)
    install_dlls(msys2, gimp)

    say("")
    if verify(gimp):
        say("搞定。在 GIMP 里 python-fu-eval 就能 import numpy 了。")
        return 0
    say("装完了但 import 失败，把上面的报错贴出来。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
