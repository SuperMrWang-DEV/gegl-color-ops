# -*- coding: utf-8 -*-
"""从 bc-cal/bc_model.json 生成 ops/brightness-contrast-ps/bc-tables.h

算子不手抄任何常数：改标定数据 → 重新跑这个脚本即可。
表值是 8 位（0…254），与 Photoshop 内部 256 项 LUT 的粒度一致。
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 优先用工程内的副本（跟仓库一起走），没有就回退到标定目录
SRC = os.path.join(ROOT, 'ops', 'brightness-contrast-ps', 'bc_model.json')
if not os.path.exists(SRC):
    SRC = os.path.join(os.path.dirname(ROOT), 'bc-cal', 'bc_model.json')
DST = os.path.join(ROOT, 'ops', 'brightness-contrast-ps', 'bc-tables.h')

M = json.load(open(SRC, encoding='utf-8'))
modern = M['modern']
B_LEV = modern['b_levels']
C_LEV = modern['c_levels']
B_TAB = modern['b_table']
C_TAB = modern['c_table']
NX = len(modern['knot_x'])
LEG = M['legacy']


def emit_table(name, rows, levels, step):
    lines = []
    lines.append('#define %s_LEVELS %d' % (name.upper(), len(levels)))
    lines.append('#define %s_STEP   %d' % (name.upper(), step))
    # 必须是 int：亮度下限 -150 装不进 signed char
    lines.append('static const int %s_first = %d;' % (name, levels[0]))
    lines.append('static const unsigned char %s_table[%d][%d] = {'
                 % (name, len(rows), NX))
    for i, row in enumerate(rows):
        chunks = []
        for k in range(0, NX, 24):
            chunks.append('    ' + ','.join('%3d' % v for v in row[k:k + 24]) + ',')
        lines.append('  {   /* %+d */' % levels[i])
        lines.extend(chunks)
        lines.append('  },')
    lines.append('};')
    return '\n'.join(lines)


hdr = '''/* 自动生成，勿手改 —— 由 tools/gen_bc_tables.py 从 bc-cal/bc_model.json 导出
 * Generated file, do not edit. Produced by tools/gen_bc_tables.py from
 * bc-cal/bc_model.json (Photoshop 26.10, 16 bit/channel calibration).
 *
 * 新版（useLegacy = false）：两张一维表 —— 亮度族 61 档、对比度族 31 档，
 *   每档一条 255 点曲线（x = 0…254）。x = 255 是纯白保护特例，见算子。
 *   组合顺序固定为「先亮度、后对比度」。
 * 旧版（useLegacy = true）：闭式，只需 pivot 与亮度夹取范围。
 */
#ifndef BC_TABLES_H
#define BC_TABLES_H

#define BC_NX %d

/* 旧版：out = pivot + K·(x - pivot)，K = 1/(1-c/100) 或 1+c/100；
 * 亮度先夹到 ±BC_B_CLAMP。pivot 由 31 条曲线的公共不动点最小二乘得到。 */
#define BC_PIVOT      %.4ff
#define BC_B_CLAMP    %.2ff

%s

%s

#endif
''' % (NX, LEG['pivot'], float(LEG['brightness_clamp']),
       emit_table('bc_b', B_TAB, B_LEV, B_LEV[1] - B_LEV[0]),
       emit_table('bc_c', C_TAB, C_LEV, C_LEV[1] - C_LEV[0]))

os.makedirs(os.path.dirname(DST), exist_ok=True)
with open(DST, 'w', encoding='utf-8', newline='\n') as f:
    f.write(hdr)

print('写出 %s（%.1f KB，%d + %d 条曲线 × %d 点）'
      % (DST, os.path.getsize(DST) / 1024.0, len(B_TAB), len(C_TAB), NX))
