project('gegl-color-ops', 'c',
        version: '1.0.0',
        license: 'GPL-3.0-or-later',
        meson_version: '>=0.60')

# 所有算子共用同一份 config.h（GEGL 版本宏 / GETTEXT_PACKAGE）
gegl = dependency('gegl-0.4', required: true)
common_inc = include_directories('common')

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
  ['hsl-seven',               'hsl-seven',               'hsl-seven.c'],
  ['lab-levels',              'lab-levels',              'lab-levels.c'],
  ['hsl-levels',              'hsl-levels',              'hsl-levels.c'],
  ['hsb-levels',              'hsb-levels',              'hsb-levels.c'],
  ['lch-levels',              'lch-levels',              'lch-levels.c'],
  ['cmyk-levels',             'cmyk-levels',             'cmyk-levels.c'],
  ['hsi-levels',              'hsi-levels',              'hsi-levels.c'],
  ['exposure',                'lb-exposure',             'lb-exposure.c'],
  ['rgb-domain-grayscale',    'rgb-domain-grayscale',    'rgb-domain-grayscale.c'],
  ['vibrance-hyper',          'vibrance-hyper',          'vibrance-hyper.c'],
  ['vibrance',             'vibrance',             'vibrance.c'],
  ['brightness-contrast',  'lb-brightness-contrast',  'lb-brightness-contrast.c'],
  ['xyz-multiply',            'xyz-multiply',            'xyz-multiply.c'],
  ['shadows-highlights',      'shadows-highlights',      'shadows-highlights.c'],
  # 分量层编码器：HSV/LCh Split 插件的最后一步
  ['gray-to-component',       'gray-to-component',       'gray-to-component.c'],
  # 双输入（aux）算子。本表是手工维护的，加算子时必须同步；带 .disabled 标记的
  # 算子不入表也不编译。CI 用集合比对核对本表与 ops/ 下的源码目录，漏列或多列
  # 都会点名。
  ['apply-image',             'apply-image',             'apply-image.c'],
  ['calculations',            'calculations',            'calculations.c'],
  ['match-color',             'match-color',             'match-color.c'],
  ['color-temperature-tint',   'color-temperature-tint',   'color-temperature-tint.c'],
]

foreach op : ops
  # 每个算子单独编译成一个共享模块；GEGL_OP_C_SOURCE 的自包含 include
  # 需要把算子自己的目录放进搜索路径，因此两处 include_directories 都不能省。
  shared_module(op[1],
                join_paths('ops', op[0], op[2]),
                include_directories: [common_inc, include_directories(join_paths('ops', op[0]))],
                dependencies: gegl,
                c_args: ['-O2', '-Wall'],
                name_prefix: '',
                install: false)
endforeach
