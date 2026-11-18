---
name: LCh Dual Extract
blurb: Packs lightness, chroma and hue into one data image in polar form — so a curve can add chroma or rotate hue without dragging the other two along.
---

Menu: `Colors → SuperMrWang → Component → LCh Dual Extract` (a filter op)

## Overview

Packs an image into **one data image**: `R = lightness L*/100`, `G = chroma C*/140`,
`B = hue/360`, all 0…1. Alpha is always 1.

```
input ── lb:lch-dual ──> (R=L/100, G=C/140, B=h/360)
            │
            ├── L curve (red)
            ├── C curve (green)
            ├── h curve (blue)
            ▼
     lb:lch-compose ──> real colour
```

## Why polar coordinates

Lab's `a` and `b` are rectangular: `C² = a² + b²`, `h = atan2(b, a)`. A 1D curve on a
changes chroma *and* hue together — on screen that reads as a cast. "Add chroma only"
or "rotate hue only" has to be expressed in polar form first, which is what this
operator does.

Once the image is (L, C, h), the three curves are independent and `lb:lch-compose`
computes the colour back. The old `LCh Split (Curves)` used three component layers and
three LCh blend modes, and had to encode each component as a colour the blend mode
could read (the hue layer needed a ring of constant L* and C*) — a single-layer
pipeline drops all of that.

## Ranges (measured, babl D50)

| Component | babl units | Data image |
|---|---|---|
| L* | 0…100 | `L/100` |
| C* | 0…about 133.8 (full sRGB gamut) | `C/140` |
| h | 0…360° | `h/360` |

Chroma is divided by 140 rather than 135: the most saturated sRGB point is pure blue
at `C*≈133.8`, and the extra headroom lets the whole circle fit. In 8-bit one code is
about 0.55 C* units, so the round-trip quantisation stays within 0.5 codes.

## Verification

`tools/check_lch_split.py` runs the `dual → compose` identity round trip:
**0.0005 codes** in 32-bit float, **0.49 codes** in 8-bit. Neutral grey (C = 0) has no
defined hue on the babl side; the operator folds non-finite values to 0.

## Notes

- The output is a data image — **do not read it as a photo**.
- It only works paired with `lb:lch-compose`, and the two must share the same ranges —
  change one and you have to change the other.
