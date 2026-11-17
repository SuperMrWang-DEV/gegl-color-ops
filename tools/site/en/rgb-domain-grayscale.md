---
name: Black & White
blurb: the classic editor's Black & White — six hue sliders decide how much each colour contributes to grey, with an optional tint.
---

`lb:rgb-domain-grayscale` · menu **Colors → SuperMrWang → Tone → Black & White** ·
`GeglOperationPointFilter` (per-pixel)

## What it does

Six hue sliders — red, yellow, green, cyan, blue, magenta — decide how strongly each
colour in the image contributes to the grey result, and the grey can then be tinted.
This is the classic editor's Black & White dialog: pull blue down and a blue sky goes dark,
push yellow up and skin brightens, without any of it touching the rest of the frame.

The three RGB channels are combined with the six hue weights summed; the slider range
−200…300 matches the the classic editor dialog, and the defaults (red 40, yellow 60, green 40,
cyan 60, blue 20, magenta 80) are the classic editor's.

## How the tint works

The tint is calibrated black-box against the classic editor (18 tints, per-code
agreement — see `bw-cal/RESULTS.md`). It is not a `grey × colour` multiply. With
`tint = (tR,tG,tB)` and `L = 0.3·tR + 0.59·tG + 0.11·tB` (NTSC luma, encoding domain):

| Region | Condition | Output |
|---|---|---|
| Middle | otherwise | `grey + tint − L` — a unit-slope shift, so black and white stay black and white |
| Top | `grey ≥ 1 − (tmax − L)` | `1 − (tmax − tint)·(1 − grey)/(tmax − L)` |
| Bottom | `grey ≤ L − tmin` | `(tint − tmin)·grey/(L − tmin)` |

The pieces join continuously and the outer two pass exactly through white and black,
so tinting never crushes the tonal range — highlights stay highlights.

## Parameters

| Parameter | Default | Notes |
|---|---|---|
| `red` / `yellow` / `green` | 40 / 60 / 40 | Weight of each hue family, −200…300 |
| `cyan` / `blue` / `magenta` | 60 / 20 / 80 | Weight of each hue family, −200…300 |
| `tint_enabled` | off | Tint the grey result |
| `tint_color` | `#E0D4B2` | Tint colour (a warm sepia by default) |
| `tint_strength` | 1 | How strongly the tint is applied, 0…1 |

## Notes

- The operator runs per pixel in the 8-bit sRGB gamma domain, so the weights behave
  like the ones in the classic editor's dialog.
- Alpha is preserved; transparent pixels stay transparent.
- Unlike GIMP's `Colors → Desaturate`, the conversion is not a fixed luma formula: you
  choose what each colour becomes, which is the whole point of Black & White.
