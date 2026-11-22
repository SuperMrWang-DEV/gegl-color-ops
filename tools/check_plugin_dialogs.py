# -*- coding: utf-8 -*-
"""回归：每个插件都能弹出参数对话框。

    "D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
        --batch-interpreter=python-fu-eval \
        -b "exec(open(r'<repo>/tools/check_plugin_dialogs.py').read())" --quit

为什么需要这条：GIMP 3 **不会**自动给插件生成参数对话框。参数注册得再完整、
过程挂在菜单上也一样——run() 里不自己 `GimpUi.ProcedureDialog.new(...)` 再
`run()`，点菜单就是用默认值直接开跑，用户永远看不到任何输入框。

这个 bug 特别阴：菜单在、PDB 里查得到、插件照常「工作」（用默认值），
只有用户体验上少了所有可调参数。ai-inpaint 因为默认提示词是空串，
才把它暴露成「提示词是空的」这种报错。

所以这里对每个 lb-plugin-* 过程做两件事：

1. 源码里必须有 run_dialog 调用（静态）；
2. 真的用 GimpUi.ProcedureDialog 把控件建出来，且能建出的子控件数 > 0
   （动态——参数类型不被支持、Choice 造错时，这一步会炸）。

第 2 步在 gimp-console 的 headless 模式下也能跑：Windows 有桌面，
GTK 能初始化，只是不真的把窗口显示出来。
"""
import os
import re
import sys

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, GimpUi, GObject

FAIL = []
OK = 0


def ok(name, cond, detail=""):
    global OK
    if cond:
        OK += 1
    else:
        FAIL.append("%s%s" % (name, ("  [%s]" % detail) if detail else ""))


def _repo_root():
    """python-fu-eval 是 exec 进来的，__file__ 不一定存在。"""
    cands = []
    try:
        cands.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except NameError:
        pass
    cwd = os.getcwd()
    cands += [cwd, os.path.join(cwd, "SuperMrWang"),
              os.path.join(cwd, "..", "SuperMrWang")]
    for c in cands:
        if os.path.exists(os.path.join(c, "plugin", "_shared", "lb_dialog.py")):
            return os.path.abspath(c)
    raise SystemExit("找不到仓库根目录：请在 <repo> 或 <repo>/tools 下运行")


ROOT = _repo_root()


def plugin_sources():
    """(插件名, py 路径) —— 只算有 run() 的 Python 插件。"""
    root = os.path.join(ROOT, "plugin")
    out = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d) or name.startswith("_"):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".py") and not f.startswith("_"):
                p = os.path.join(d, f)
                src = open(p, encoding="utf-8").read()
                if "def run(self, procedure, run_mode" in src:
                    out.append((name, p, src))
    return out


def test_static():
    """源码层面：run() 里必须调用 run_dialog，且 lb_dialog 真的导进来了。"""
    for name, path, src in plugin_sources():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        ok("%s 导入了 lb_dialog" % rel, "import lb_dialog" in src)
        ok("%s 在 run() 里弹对话框" % rel,
           "run_dialog(procedure, run_mode, config)" in src)
        # 取消时必须返回 CANCEL，否则用户点「取消」照样会跑一遍
        ok("%s 取消时返回 CANCEL" % rel,
           "PDBStatusType.CANCEL" in src)


def test_runtime():
    """动态层面：每个**已装**的过程都能把参数控件建出来。

    只验 PDB 里真实存在的过程——源码里点名的名字可能只是 `'lb-plugin-conv-'`
    这类拼接前缀，或者那支插件当次没装（下载包是单支的）。
    """
    GimpUi.init("lb-dialog-check")
    pdb = Gimp.get_pdb()
    registered = skipped = no_args = 0
    for name, path, src in plugin_sources():
        for pname in sorted(set(re.findall(
                r"lb-plugin-[a-z0-9]+(?:-[a-z0-9]+)*", src))):
            proc = pdb.lookup_procedure(pname)
            if proc is None:
                skipped += 1
                continue
            registered += 1
            try:
                cfg = proc.create_config()
                # 零参数的命令（如 ai-inpaint 的「AI Environment…」）本来就不该
                # 弹参数框——它自己开 Gtk 对话框做别的事。这类过程跳过去，
                # 否则「控件数 > 0」永远是假的。
                if not list(cfg.list_properties()):
                    no_args += 1
                    continue
                dlg = GimpUi.ProcedureDialog.new(proc, cfg, "check")
                GimpUi.window_set_transient(dlg)
                dlg.fill()
                kids = dlg.get_content_area().get_children()
                ok("%s 对话框有控件" % pname, len(kids) > 0, "%d 个" % len(kids))
                # 光有标签不算：每个文本类参数都得有真正能操作的东西
                # （普通参数是 LabelEntry 输入框，Choice 参数是 StringComboBox 下拉）。
                # 用 get_widget 按参数名取——比数控件个数准，能定位到具体哪个参数没渲染。
                missing = []
                for prop in cfg.list_properties():
                    if prop.value_type.name != "gchararray":
                        continue
                    w = dlg.get_widget(prop.name, GObject.TYPE_STRING)
                    if w is None:
                        missing.append(prop.name)
                ok("%s 文本参数都有控件" % pname, not missing, "缺：" + ",".join(missing))
                dlg.destroy()
            except Exception as exc:
                ok("%s 对话框能建出来" % pname, False,
                   "%s: %s" % (type(exc).__name__, exc))
    if registered == 0:
        print("（PDB 里没有 lb-plugin-* —— 插件没装，跳过动态检查）")
        return
    ok("至少检查到 10 个过程（说明装上了）", registered >= 10,
       "实际 %d，未装 %d，零参数 %d" % (registered, skipped, no_args))


def test_helper():
    """助手自身的语义：非交互模式绝不弹框，空参数不弹空框。"""
    sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))
    import lb_dialog
    ok("NONINTERACTIVE 不弹框",
       lb_dialog.run_dialog(None, Gimp.RunMode.NONINTERACTIVE, None) is True)
    ok("WITH_LAST_VALS 不弹框",
       lb_dialog.run_dialog(None, Gimp.RunMode.WITH_LAST_VALS, None) is True)


def main():
    test_helper()
    test_static()
    test_runtime()
    if FAIL:
        print("\n失败 %d 条：" % len(FAIL))
        for f in FAIL:
            print("  " + f)
        raise AssertionError("check_plugin_dialogs: %d 条失败" % len(FAIL))
    print("\n全部通过（%d 条断言）" % OK)


main()
