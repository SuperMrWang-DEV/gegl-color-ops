# -*- coding: utf-8 -*-
"""把色温 / 色调的标定结果导出成 C 头文件。

产物：common/ps-temp-tint.h
  - pt_grid[][]      ：17 档参数网格
  - pt_coef[][][][]  ：网格点上的 3 次多项式系数（20 项 × 3 通道）
  - pt_coefs()       ：按 (temp,tint) 双线性插值系数
  - pt_build_lut()   ：把系数烘成 33³ LUT
  - pt_sample()      ：三线性查表

模型是 out = encode(clamp(P(lin_in)))：多项式活在线性域，PS 的硬裁切
（线性值被压到负值后切成 0）由 clamp 精确复现。早先在编码域直接拟合
编码值，裁切只能被逼近成一团糊，负色温区域的中位误差到过 90 码。

放在 common/ 下是因为两个算子都要用：色温/色调算子直接用，vibrance-ps 在
新引擎模式下把它作为前置步骤。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '..', 'vibrance-cal', 'temp_tint_grid17_lin.json')
DST = os.path.join(HERE, '..', 'common', 'ps-temp-tint.h')
DEG = 3
TERMS = (DEG + 1) * (DEG + 2) * (DEG + 3) // 6


def main():
    d = json.load(open(SRC, encoding='utf-8'))
    assert d['deg'] == DEG, d['deg']
    lv = sorted({int(k.split(',')[0]) for k in d['grid']})
    lv2 = sorted({int(k.split(',')[1]) for k in d['grid']})
    assert lv == lv2, (lv, lv2)
    n = len(lv)
    assert n * n == len(d['grid']), (n, len(d['grid']))

    out = []
    out.append('/* ===========================================================================')
    out.append(' * SuperMrWang · PS 色温 / 色调的实测系数表')
    out.append(' * ---------------------------------------------------------------------------')
    out.append(' * 由 tools/gen_temp_tint_tables.py 从 vibrance-cal/temp_tint_grid9.json 生成，')
    out.append(' * 请勿手改。标定方法见 ops/color-temperature-tint/README.md。')
    out.append(' *')
    out.append(' * 每个网格点存一组 3 次多项式系数（20 项 × 3 通道），输入是 sRGB 编码值')
    out.append(' * 解码后的线性值；顶点顺序与 Python 端 terms() 完全一致。')
    out.append(' * 映射为 out = encode(clamp(P(lin_in)))，裁切由 clamp 负责。')
    out.append(' * Generated file, do not edit by hand.')
    out.append(' * ======================================================================== */')
    out.append('')
    out.append('#ifndef PS_TEMP_TINT_H')
    out.append('#define PS_TEMP_TINT_H')
    out.append('')
    out.append('#define PT_LEVELS %d' % n)
    out.append('#define PT_TERMS  %d' % TERMS)
    out.append('#define PT_LUT    33')
    out.append('')
    out.append('static const gint pt_grid[PT_LEVELS] = {')
    for i in range(0, n, 9):
        out.append('  ' + ', '.join('%4d' % v for v in lv[i:i + 9]) + ',')
    out.append('};')
    out.append('')
    out.append('/* [ti*PT_LEVELS + ni][term][channel] */')
    out.append('static const float pt_coef[PT_LEVELS * PT_LEVELS][PT_TERMS][3] = {')
    for ti, t in enumerate(lv):
        for ni, nn in enumerate(lv):
            v = d['grid']['%d,%d' % (t, nn)]
            out.append('  { /* temp=%4d tint=%4d */' % (t, nn))
            for m in range(TERMS):
                out.append('    {%9.6ff,%9.6ff,%9.6ff},' % tuple(v[m]))
            out.append('  },')
    out.append('};')
    out.append('')
    out.append(r'''
/* 多项式顶点，顺序必须与标定脚本的 terms() 一致：
   常数项，然后 d=1..3，每个 d 内按 i=0..d、j=0..d-i 枚举 r^i g^j b^(d-i-j)。
   输入是**线性**值（0..1），进来的 r/g/b 已经是线性域 */
static void
pt_feats (gfloat  r,
          gfloat  g,
          gfloat  b,
          gfloat *f)
{
  gint m = 0, d, i, j;

  /* 标定是在居中坐标上做的（r' = 2r-1），这里必须同样居中，
   * 否则多项式与原系数对不上，输出会整体错乱 */
  r = 2.0f * r - 1.0f;
  g = 2.0f * g - 1.0f;
  b = 2.0f * b - 1.0f;

  f[m++] = 1.0f;
  for (d = 1; d <= 3; d++)
    for (i = 0; i <= d; i++)
      for (j = 0; j <= d - i; j++)
        {
          gint k = d - i - j;
          gfloat v = 1.0f;
          gint e;

          for (e = 0; e < i; e++) v *= r;
          for (e = 0; e < j; e++) v *= g;
          for (e = 0; e < k; e++) v *= b;
          f[m++] = v;
        }
}

/* 在 (temp,tint) 上双线性插值系数。t 用温度，n 用色调，越界取端点。
 * Bilinear interpolation of the polynomial coefficients. */
static void
pt_coefs (gfloat  t,
          gfloat  n,
          gfloat  out[PT_TERMS][3])
{
  gint  ti = 0, ni = 0, m, c;
  gfloat tf, nf;

  if (t <= pt_grid[0]) ti = 0;
  else if (t >= pt_grid[PT_LEVELS - 1]) ti = PT_LEVELS - 2;
  else while (ti < PT_LEVELS - 2 && t > pt_grid[ti + 1]) ti++;

  if (n <= pt_grid[0]) ni = 0;
  else if (n >= pt_grid[PT_LEVELS - 1]) ni = PT_LEVELS - 2;
  else while (ni < PT_LEVELS - 2 && n > pt_grid[ni + 1]) ni++;

  tf = (t - pt_grid[ti]) / (gfloat) (pt_grid[ti + 1] - pt_grid[ti]);
  nf = (n - pt_grid[ni]) / (gfloat) (pt_grid[ni + 1] - pt_grid[ni]);
  tf = CLAMP (tf, 0.0f, 1.0f);
  nf = CLAMP (nf, 0.0f, 1.0f);

  for (m = 0; m < PT_TERMS; m++)
    for (c = 0; c < 3; c++)
      {
        const float *a = pt_coef[ti * PT_LEVELS + ni][m];
        const float *b = pt_coef[(ti + 1) * PT_LEVELS + ni][m];
        const float *cc = pt_coef[ti * PT_LEVELS + ni + 1][m];
        const float *dd = pt_coef[(ti + 1) * PT_LEVELS + ni + 1][m];

        out[m][c] = (a[c] * (1.0f - tf) + b[c] * tf) * (1.0f - nf) +
                    (cc[c] * (1.0f - tf) + dd[c] * tf) * nf;
      }
}

/* sRGB 编码值 ↔ 线性值。标定出来的多项式活在线性域，所以建表时要先解码、
 * 算完再编码回去。只用于建表（每张图一次），逐像素不走这里 */
static inline gfloat
pt_to_lin (gfloat v)
{
  v = CLAMP (v, 0.0f, 1.0f);
  return v <= 0.04045f ? v / 12.92f : powf ((v + 0.055f) / 1.055f, 2.4f);
}

static inline gfloat
pt_to_srgb (gfloat v)
{
  v = CLAMP (v, 0.0f, 1.0f);
  return v <= 0.0031308f ? v * 12.92f
                         : 1.055f * powf (v, 1.0f / 2.4f) - 0.055f;
}

/* 把当前参数烘成 PT_LUT³ 的查找表。逐像素算 20 项 + 两次幂函数太慢，
 * 一张图只烘一次。
 * Bake a PT_LUT³ table once per image; per-pixel evaluation would be far too slow. */
static void
pt_build_lut (gfloat  t,
              gfloat  n,
              gfloat *lut)
{
  gfloat co[PT_TERMS][3];
  gint   ri, gi, bi, m, c;

  if (t == 0.0f && n == 0.0f)
    {
      /* 恒等：不必走多项式，也避开系数在原点附近的微小残差 */
      for (ri = 0; ri < PT_LUT; ri++)
        for (gi = 0; gi < PT_LUT; gi++)
          for (bi = 0; bi < PT_LUT; bi++)
            {
              gfloat *p = lut + ((ri * PT_LUT + gi) * PT_LUT + bi) * 3;
              p[0] = ri / (gfloat) (PT_LUT - 1);
              p[1] = gi / (gfloat) (PT_LUT - 1);
              p[2] = bi / (gfloat) (PT_LUT - 1);
            }
      return;
    }

  pt_coefs (t, n, co);

  for (ri = 0; ri < PT_LUT; ri++)
    for (gi = 0; gi < PT_LUT; gi++)
      for (bi = 0; bi < PT_LUT; bi++)
        {
          gfloat  f[PT_TERMS];
          gfloat *p = lut + ((ri * PT_LUT + gi) * PT_LUT + bi) * 3;

          /* 编码值解码到线性域再套多项式；clamp 复现 PS 的硬裁切，
           * 这一步是整个模型里唯一能表达「线性值被压到负数」的地方 */
          pt_feats (pt_to_lin (ri / (gfloat) (PT_LUT - 1)),
                    pt_to_lin (gi / (gfloat) (PT_LUT - 1)),
                    pt_to_lin (bi / (gfloat) (PT_LUT - 1)), f);

          for (c = 0; c < 3; c++)
            {
              gfloat s = 0.0f;

              for (m = 0; m < PT_TERMS; m++)
                s += f[m] * co[m][c];

              p[c] = pt_to_srgb (s);
            }
        }
}

/* 三线性查表。输入输出都是 0..1 的 sRGB 编码值（尚未乘 255）。
 * Trilinear lookup; rgb are sRGB-encoded values in 0..1. */
static inline void
pt_sample (const gfloat *lut,
           const gfloat *rgb,
           gfloat       *out)
{
  gfloat fr = CLAMP (rgb[0], 0.0f, 1.0f) * (PT_LUT - 1);
  gfloat fg = CLAMP (rgb[1], 0.0f, 1.0f) * (PT_LUT - 1);
  gfloat fb = CLAMP (rgb[2], 0.0f, 1.0f) * (PT_LUT - 1);
  gint   r0 = (gint) fr, g0 = (gint) fg, b0 = (gint) fb;
  gint   r1, g1, b1, c;
  gfloat tr, tg, tb;

  if (r0 > PT_LUT - 2) r0 = PT_LUT - 2;
  if (g0 > PT_LUT - 2) g0 = PT_LUT - 2;
  if (b0 > PT_LUT - 2) b0 = PT_LUT - 2;
  r1 = r0 + 1;
  g1 = g0 + 1;
  b1 = b0 + 1;
  tr = fr - r0;
  tg = fg - g0;
  tb = fb - b0;

  for (c = 0; c < 3; c++)
    {
      gfloat c000 = lut[((r0 * PT_LUT + g0) * PT_LUT + b0) * 3 + c];
      gfloat c001 = lut[((r0 * PT_LUT + g0) * PT_LUT + b1) * 3 + c];
      gfloat c010 = lut[((r0 * PT_LUT + g1) * PT_LUT + b0) * 3 + c];
      gfloat c011 = lut[((r0 * PT_LUT + g1) * PT_LUT + b1) * 3 + c];
      gfloat c100 = lut[((r1 * PT_LUT + g0) * PT_LUT + b0) * 3 + c];
      gfloat c101 = lut[((r1 * PT_LUT + g0) * PT_LUT + b1) * 3 + c];
      gfloat c110 = lut[((r1 * PT_LUT + g1) * PT_LUT + b0) * 3 + c];
      gfloat c111 = lut[((r1 * PT_LUT + g1) * PT_LUT + b1) * 3 + c];
      gfloat c00 = c000 + (c001 - c000) * tb;
      gfloat c01 = c010 + (c011 - c010) * tb;
      gfloat c10 = c100 + (c101 - c100) * tb;
      gfloat c11 = c110 + (c111 - c110) * tb;
      gfloat c0 = c00 + (c01 - c00) * tg;
      gfloat c1 = c10 + (c11 - c10) * tg;

      out[c] = c0 + (c1 - c0) * tr;
    }
}
''')
    out.append('#endif /* PS_TEMP_TINT_H */')
    out.append('')

    with open(DST, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(out))
    print('%s  %d 网格点 × %d 项 × 3 通道 = %d 个数  %.1f KB'
          % (DST, n * n, TERMS, n * n * TERMS * 3, os.path.getsize(DST) / 1024))


if __name__ == '__main__':
    main()
