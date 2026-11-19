# -*- coding: utf-8 -*-
"""检查每个算子的「菜单三件套」是否齐：id、gimp:menu-path、gimp:menu-label。

背景（2026-11-20）：锐化 / 杂色四个算子写完后只注册了 GEGL 名字，漏了
`gimp:menu-path`，于是 GIMP 的 Filters 菜单里根本看不见它们 —— 但 `gegl --info`
照样能查到、命令行照照样能跑，自检脚本全绿，所以一直没被发现。
这里把「看得见」这件事也变成一条可测的断言。

判据：
  · 每个 ops/<dir>/<dir>.c 的 class_init 里必须有 gimp:menu-path；
  · 路径必须落在 <Image>/SuperMrWang/<组> 上，且组名与 set_menu_group.GROUPS 一致
    （否则站点分组和实际菜单会漂）；
  · gimp:menu-label 必须存在（GIMP 3 拿它当菜单项文字）。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import set_menu_group as SMG  # noqa: E402

OPS = os.path.join(os.path.dirname(HERE), "ops")

MENU = re.compile(r'"gimp:menu-path"\s*,\s*"([^"]+)"')
LABEL = re.compile(r'"gimp:menu-label"\s*,\s*_?\("([^"]+)"')
NAME = re.compile(r'"name"\s*,\s*"([^"]+)"')


def main():
    bad, ok = [], 0
    for d in sorted(os.listdir(OPS)):
        p = os.path.join(OPS, d)
        if not os.path.isdir(p):
            continue
        cs = [f for f in sorted(os.listdir(p)) if f.endswith(".c")]
        if not cs:
            continue
        src = open(os.path.join(p, cs[0]), encoding="utf-8", errors="replace").read()
        # class_init 里的键值集中在一处；GEGL_PROPERTIES 段里不会有 menu-path
        op_id = NAME.search(src)
        menu = MENU.search(src)
        label = LABEL.search(src)
        want = SMG.group_of(d)

        problems = []
        if not op_id:
            problems.append("没有 name 键")
        if not menu:
            problems.append("没有 gimp:menu-path")
        if not label:
            problems.append("没有 gimp:menu-label")
        if menu and want:
            expect = "<Image>/SuperMrWang/%s" % want
            if menu.group(1) != expect:
                problems.append("菜单路径 %s，分组表要求 %s" % (menu.group(1), expect))
        if want is None and menu:
            problems.append("不在 set_menu_group.GROUPS 里，站点会兜底塞进 Blend")

        if problems:
            bad.append((d, op_id.group(1) if op_id else "?", problems))
        else:
            ok += 1

    for d, op_id, problems in bad:
        print("FAIL %-24s %-22s %s" % (d, op_id, "；".join(problems)))
    print("\n%d 个算子菜单齐全，%d 个有问题" % (ok, len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
