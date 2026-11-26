project('gegl-color-ops', 'c',
        version: '1.0.0',
        license: 'GPL-3.0-or-later',
        meson_version: '>=0.60')

# 所有算子共用同一份 config.h（GEGL 版本宏 / GETTEXT_PACKAGE）
gegl = dependency('gegl-0.4', required: true)
common_inc = include_directories('common')

# libm：build.sh 一直显式带 -lm，meson 这边漏了。Linux 的 glibc 不会隐式链接
# libm，用 sqrt/exp 的算子（max-min、color-balance…）编 .so 时虽然能过（共享库
# 允许未定义符号），但 dlopen 会报 undefined symbol: sqrt。Windows/MinGW 的
# msvcrt 自带这些符号，所以只在 Linux 暴露。
cc = meson.get_compiler('c')
m_dep = cc.find_library('m', required: false)
op_deps = [gegl]
if m_dep.found()
  op_deps += m_dep
endif

# libintl：common/i18n.c 在模块载入时自己 bindtextdomain。glibc 把它放在 libc 里
# （find_library 找不到 intl 是正常的，跳过即可）；Windows 的 MinGW 与部分 BSD
# 需要显式链接。找不到也不能让构建失败 —— 那样只是退化成英文 msgid。
intl_dep = cc.find_library('intl', required: false)
if intl_dep.found()
  op_deps += intl_dep
endif

# [目录名, 模块名, 源文件名]。模块名即产出的 .so 文件名（不能带 lib 前缀），
# 与源文件名保持一致 —— GEGL 的 GType 名取自源文件名，两边对齐才能和
# build.sh 的产出（按源文件名命名）完全对应。
ops = [
  ['hue-saturation',          'hue-saturation',          'hue-saturation.c'],
  ['hue-saturation-basic',       'hue-saturation-basic',       'hue-saturation-basic.c'],
  ['hue-range-basic',            'hue-range-basic',            'hue-range-basic.c'],
  ['channel-range-to-alpha',  'channel-range-to-alpha',  'channel-range-to-alpha.c'],
  ['channel-mixer-plus',      'channel-mixer-plus',      'channel-mixer-plus.c'],
  ['cmyk-primary-correction', 'cmyk-primary-correction', 'cmyk-primary-correction.c'],
  ['color-mask-select',       'color-mask-select',       'color-mask-select.c'],
  ['color-balance',           'color-balance',           'color-balance.c'],
  ['color-lookup',            'color-lookup',            'color-lookup.c'],
  ['color-grading',           'color-grading',           'color-grading.c'],
  ['levels',               'levels',               'levels.c'],
  ['colorize-hsl',            'colorize-hsl',            'colorize-hsl.c'],
  ['hsl-bands',               'hsl-bands',               'hsl-bands.c'],
  ['lab-levels',              'lab-levels',              'lab-levels.c'],
  ['hsl-levels',              'hsl-levels',              'hsl-levels.c'],
  ['hsb-levels',              'hsb-levels',              'hsb-levels.c'],
  ['lch-levels',              'lch-levels',              'lch-levels.c'],
  ['cmyk-levels',             'cmyk-levels',             'cmyk-levels.c'],
  ['hsi-levels',              'hsi-levels',              'hsi-levels.c'],
  # 曲线家族：四条任意曲线，共用 common/curve.h 的单调三次插值
  ['lab-curves',              'lab-curves',              'lab-curves.c'],
  ['lch-curves',              'lch-curves',              'lch-curves.c'],
  ['hsv-curves',              'hsv-curves',              'hsv-curves.c'],
  ['cmyk-curves',             'cmyk-curves',             'cmyk-curves.c'],
  ['exposure',                'lb-exposure',             'lb-exposure.c'],
  ['rgb-domain-grayscale',    'rgb-domain-grayscale',    'rgb-domain-grayscale.c'],
  ['vibrance-hyper',          'vibrance-hyper',          'vibrance-hyper.c'],
  ['vibrance',             'vibrance',             'vibrance.c'],
  ['brightness-contrast',  'lb-brightness-contrast',  'lb-brightness-contrast.c'],
  ['xyz-multiply',            'xyz-multiply',            'xyz-multiply.c'],
  ['shadows-highlights',      'shadows-highlights',      'shadows-highlights.c'],
  # 分量层编码器：HSV/LCh Split 插件的最后一步
  ['gray-to-component',       'gray-to-component',       'gray-to-component.c'],
  # HSL 适配器：把 S/L 挤进一张数据图（两者耦合，必须同时读到），再合成回
  # 真实颜色。HSL Split 插件靠这两个算子做到与直接改 HSL 完全等价。
  ['hsl-dual',                'hsl-dual',                'hsl-dual.c'],
  ['hsl-compose',             'hsl-compose',             'hsl-compose.c'],
  # Lab / HSI 适配器：a 与 b 是直角坐标、HSI 的色相角又与 HSV 差 1°，都没有
  # 现成的分量混合模式可借，只能把分量挤进一张数据图联合算出完整颜色。
  ['lab-dual',                'lab-dual',                'lab-dual.c'],
  ['lab-compose',             'lab-compose',             'lab-compose.c'],
  ['hsi-dual',                'hsi-dual',                'hsi-dual.c'],
  ['hsi-compose',             'hsi-compose',             'hsi-compose.c'],
  ['hsv-dual',                'hsv-dual',                'hsv-dual.c'],
  ['hsv-compose',             'hsv-compose',             'hsv-compose.c'],
  # LCh 与 Lab 同一套 D50 口径，但色相是极角、彩度上限 140，分量曲线单独一对
  ['lch-dual',                'lch-dual',                'lch-dual.c'],
  ['lch-compose',             'lch-compose',             'lch-compose.c'],
  # 双输入（aux）算子。本表是手工维护的，加算子时必须同步；带 .disabled 标记的
  # 算子不入表也不编译。CI 用集合比对核对本表与 ops/ 下的源码目录，漏列或多列
  # 都会点名。
  ['apply-image',             'apply-image',             'apply-image.c'],
  ['calculations',            'calculations',            'calculations.c'],
  ['match-color',             'match-color',             'match-color.c'],
  # 邻域算子（区域滤波）：形态学最大值/最小值，输入需要向外扩半径
  ['max-min',                 'max-min',                 'max-min.c'],
  # 置换：单张矢量场 + 可调黑白场/中点，修掉 gegl:displace 的几处硬限制
  ['displace',                'displace',                'displace.c'],
  # 镜头校正：畸变 / 暗角 / 横向色差，一次重采样，自动缩放兜住四角
  ['lens-correction',         'lens-correction',         'lens-correction.c'],
  # 清晰度 / 去朦胧：中频局部对比 + 暗通道先验，Camera Raw 的两个滑块
  ['clarity-dehaze',          'clarity-dehaze',          'clarity-dehaze.c'],
  # 锐化与杂色：PS「锐化 → USM」与「杂色」四个滤镜的等价物
  ['unsharp-mask',            'unsharp-mask',            'unsharp-mask.c'],
  ['add-noise',               'add-noise',               'add-noise.c'],
  ['reduce-noise',            'reduce-noise',            'reduce-noise.c'],
  ['dust-scratches',          'dust-scratches',          'dust-scratches.c'],
  ['color-temperature-tint',   'color-temperature-tint',   'color-temperature-tint.c'],
  # 图层样式（非破坏版）：参数挂在滤镜栈上，供 GIMP 的「图层滤镜」使用。
  # 破坏性的 Python 版在 plugin/layer-style，两版并存、各走各的入口。
  ['layer-style',             'layer-style',             'layer-style.c'],
  # 变形（非破坏版）：MLS / ARAP 与 FFD + 双三次 Bezier 面片，钉子串 / 网格串
  # 挂在滤镜栈上；破坏性的 Python 版在 plugin/puppet-warp、plugin/mesh-warp，
  # 对话框点应用时默认写的就是这两条滤镜。
  ['puppet-warp',             'puppet-warp',             'puppet-warp.c'],
  ['mesh-warp',               'mesh-warp',               'mesh-warp.c'],
]

foreach op : ops
  # 每个算子单独编译成一个共享模块；GEGL_OP_C_SOURCE 的自包含 include
  # 需要把算子自己的目录放进搜索路径，因此两处 include_directories 都不能省。
  shared_module(op[1],
                join_paths('ops', op[0], op[2]),
                'common/i18n.c',
                include_directories: [common_inc, include_directories(join_paths('ops', op[0]))],
                dependencies: op_deps,
                c_args: ['-O2', '-Wall'],
                name_prefix: '',
                install: false)
endforeach
