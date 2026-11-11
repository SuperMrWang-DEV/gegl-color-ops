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
  ['channel-range-to-alpha',  'channel-range-to-alpha',  'channel-range-to-alpha.c'],
  ['channel-mixer-plus',      'channel-mixer-plus',      'channel-mixer-plus.c'],
  ['cmyk-primary-correction', 'cmyk-primary-correction', 'cmyk-primary-correction.c'],
  ['color-mask-select',       'color-mask-select',       'color-mask-select.c'],
  ['color-balance',           'color-balance',           'color-balance.c'],
  ['colorize-hsl',            'colorize-hsl',            'colorize-hsl.c'],
  ['hsl-seven',               'hsl-seven',               'hsl-seven.c'],
  ['lab-levels',              'lab-levels',              'lab-levels.c'],
  ['exposure',                'lb-exposure',             'lb-exposure.c'],
  ['rgb-domain-grayscale',    'rgb-domain-grayscale',    'rgb-domain-grayscale.c'],
  ['vibrance-hyper',          'vibrance-hyper',          'vibrance-hyper.c'],
  ['vibrance-ps',             'vibrance-ps',             'vibrance-ps.c'],
  ['brightness-contrast-ps',  'brightness-contrast-ps',  'lb-brightness-contrast.c'],
  ['xyz-multiply',            'xyz-multiply',            'xyz-multiply.c'],
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
