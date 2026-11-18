---
name: HSI Compose
blurb: The inverse of HSI Triple Extract, using HSI's cosine inverse rather than HSV's linear sectors — the two are not the same basis on the constant-luminance plane.
---

Menu: `Colors → SuperMrWang → Component → HSI Compose` (a filter op)

## Overview

The inverse of `lb:hsi-dual`: turns the `R = saturation`, `G = intensity`,
`B = hue/360` data image back into real colour. Alpha is ignored; the output is always
opaque.

```
(R=S, G=I, B=H/360) ──lb:hsi-compose──> sRGB
```

## How it computes

The inverse transform uses HSI's **cosine form**, not HSV's linear sectors:

```
H  < 120°   B = I(1−S),  R = I[1 + S·cosH / cos(60−H)],  G = 3I − R − B
H  < 240°   rotate by 120°, R takes the low value
otherwise   rotate by 240°, G takes the low value
```

Using HSV's sector formula instead is off by tens of codes at high S and low I — the
two are not the same basis on the constant-luminance plane. The code lives in
`common/color-levels.h` (`lb_cl_hsi_to_rgb`) and is shared with `lb:hsi-levels`.

## Input and output

| | Format | Meaning |
|---|---|---|
| input | `R'G'B'A float` | **the numbers are data**: the output of `lb:hsi-dual` |
| output | `R'G'B'A float` | sRGB encoded values, clipped to [0,1] |

S and I are clamped to [0,1] inside the transform, hue wraps with `wrap360`, and the
RGB output is clipped to [0,1] — HSI's gamut is a hexagonal pyramid, so out-of-gamut
results at extreme S/I can only be clipped.

## Notes

- "R is saturation, G is intensity, B is hue" is a **hard convention**: pointed at a
  photo it interprets pixels as HSI data — wrong output, no error.
- Do not confuse it with `lb:hsi-levels`: that one applies per-component 1D levels
  mappings, this one is the composer for the curve workflow.
