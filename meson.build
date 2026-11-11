project('gegl-color-ops', 'c',
        version: '1.0.0',
        license: 'GPL-3.0-or-later',
        meson_version: '>=0.60')

# 所有算子共用同一份 config.h（GEGL 版本宏 / GETTEXT_PACKAGE）
gegl = dependency('gegl-0.4', required: true)
common_inc = include_directories('common')

# [目录名, 源文件名]，目录名即产出的模块名（不能带 lib 前缀）
ops = [
  ['hue-saturation',          'hue-saturation.c'],
  ['channel-range-to-alpha',  'channel-range-to-alpha.c'],
  ['channel-mixer-plus',      'channel-mixer-plus.c'],
  ['cmyk-primary-correction', 'cmyk-primary-correction.c'],
  ['color-mask-select',       'color-mask-select.c'],
  ['color-balance',           'color-balance.c'],
  ['colorize-hsl',            'colorize-hsl.c'],
  ['hsl-seven',               'hsl-seven.c'],
  ['lab-levels',              'lab-levels.c'],
  ['exposure',                'lb-exposure.c'],
  ['rgb-domain-grayscale',    'rgb-domain-grayscale.c'],
  ['vibrance-hyper',          'vibrance-hyper.c'],
  ['xyz-multiply',            'xyz-multiply.c'],
]

foreach op : ops
  # 每个算子单独编译成一个共享模块；GEGL_OP_C_SOURCE 的自包含 include
  # 需要把算子自己的目录放进搜索路径，因此两处 include_directories 都不能省。
  shared_module(op[0],
                join_paths('ops', op[0], op[1]),
                include_directories: [common_inc, include_directories(join_paths('ops', op[0]))],
                dependencies: gegl,
                c_args: ['-O2', '-Wall'],
                name_prefix: '',
                install: false)
endforeach
