---
name: Channel Mixer Plus
blurb: the classic editor's Channel Mixer — a 3×3 matrix from R/G/B into each output channel, plus a constant offset per channel and a monochrome mode.
---

`lb:channel-mixer-plus` · menu **Colors → SuperMrWang → Blend → Channel Mixer Plus** ·
`GeglOperationPointFilter` (per-pixel)

## What it does

Each output channel is a weighted sum of the three input channels plus its own
constant offset:

```
R' = rr·R + rg·G + rb·B + r_off
G' = gr·R + gg·G + gb·B + g_off
B' = br·R + bg·G + bb·B + b_off
```

The defaults are the identity matrix (1 on the diagonal, 0 elsewhere) with every
offset at 0, so the operator passes the image through untouched until you move
something. Results are clipped to 0..1.

## Monochrome

With `monochrome` on, the three output channels share one set of coefficients
(`mono_r` / `mono_g` / `mono_b`, plus `mono_offset`) and the image turns grey — the
same thing the classic editor's monochrome checkbox does. The per-channel matrix is ignored
in that mode, so you can keep both settings and flip between them.

## Parameters

| Parameter | Default | Notes |
|---|---|---|
| `monochrome` | off | Single-coefficient grey output, classic style |
| `mono_r` / `mono_g` / `mono_b` | 0.33 / 0.33 / 0.34 | Monochrome weights (sum to 1 by default) |
| `mono_offset` | 0 | Monochrome constant |
| `rr_gain`, `rg_gain`, `rb_gain` | 1, 0, 0 | R out of R / G / B |
| `gr_gain`, `gg_gain`, `gb_gain` | 0, 1, 0 | G out of R / G / B |
| `bg_gain` etc. | … | Blue row, same layout |
| `r_offset`, `g_offset`, `b_offset` | 0 | Constant added to each output channel |

Every gain accepts −2…2, so you can subtract a channel as well as add it.

## How it differs from GEGL's built-in channel-mixer

GEGL core ships a `gegl:channel-mixer` with the same matrix, but no per-channel
constant and a "keep luminosity" option. This operator adds the offsets — which is
what the classic editor's Constant sliders are — and leaves luminosity preservation out,
because adding a constant and then rescaling luminance pulls the result in two
directions at once.

## Testing

```bash
./build.sh
python tools/check_gamma_domain.py   # with the identity matrix the operation must
                                     # pass the probe image through unchanged
```
