---
name: HSI Triple Extract
blurb: Packs HSI saturation, intensity and hue into one data image — HSI matches none of GIMP's component blend modes, so all three have to be computed together.
---

Menu: `Colors → SuperMrWang → Component → HSI Triple Extract` (a filter op)

## Overview

Packs an image into **one data image**: `R = saturation`, `G = intensity`,
`B = hue/360`, all 0…1. Alpha is always 1.

```
input ── lb:hsi-dual ──> (R=S, G=I, B=H/360)
            │
            ├── S curve (red)
            ├── I curve (green)
            ├── H curve (blue)
            ▼
     lb:hsi-compose ──> real colour
```

## Why all three share one image

HSI's definition matches **none** of GIMP's ready-made component blend modes:

```
I = (R+G+B)/3          HSV's V = max        ✗
S = 1 − min/I          HSL's S differs      ✗
H = angle from a cosine HSV's parametric    ✗ off by up to 1.117°
```

Hue is the part that is easy to miss. HSI's hue angle is

```
cos H = [(R−G) + (R−B)] / (2·√((R−G)² + (R−B)(G−B)))
```

which measures the true angle of the chroma vector inside the constant-luminance
plane; HSV's hue is a parametric angle on a hexagonal projection. The two agree only
at 0°/30°/60°… and are off by ±1.08° at 15°, 45°, 75°…

So even wiring the hue layer to "HSV hue" mode has two problems: the angles are not
the same (about 1°, a few codes on saturated colours), and that mode preserves HSV's
S and V, **dragging HSI's S and I along** — measured, a single hue curve moves I by
0.085 (about 22 codes). All three components therefore have to be computed jointly,
in one layer.

## Input and output

| | Format | Meaning |
|---|---|---|
| input | `R'G'B'A float` | the filter stack's encoding-domain buffer |
| output | `R'G'B'A float` | **the numbers are data, not colour**: 0.85 / 0.45 / 0.583 = S 85%, I 45%, hue 210° |

The conversion uses the code in this repository's `common/color-levels.h`, shared with
`lb:hsi-levels`: `I = (R+G+B)/3`, `S = 1 − min/I`, hue by the cosine formula.

Alpha is written as 1 unconditionally: a component layer has to be opaque, and
transparency belongs on a group mask.

## Verification

`tools/check_hsi_split.py` runs the `dual → compose` identity round trip:
**0.0001 codes** on a 32-bit float image, **0.499 codes** on 8-bit (quantisation
only). After editing any one curve the result lands on the HSI point where only that
component moved: S and I within 0.0001, hue angle within **0.0013°**.

## Notes

- The output is a data image — **do not read it as a photo**.
- It is only meaningful together with `lb:hsi-compose`.
- HSI's gamut is a hexagonal pyramid, not a cube: pushing S or I to the extremes sends
  the inverse transform outside sRGB, and compose clips what falls out.
