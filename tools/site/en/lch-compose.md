---
name: LCh Compose
blurb: Turns the LCh data image back into colour — lightness, chroma and hue multiplied back to physical units, then converted through babl's D50 LCh space.
---

Menu: `Colors → SuperMrWang → Component → LCh Compose` (a filter op)

## Overview

Restores a data image to real colour: `R = L/100`, `G = C/140`, `B = hue/360` are
scaled back to physical units (L*, C*, h) and handed to babl for the RGB conversion.

```
(L/100, C/140, h/360) ──lb:lch-compose──> real colour
```

## The input convention is strict

The operator **cannot tell** a data image from an ordinary photo — it always reads
R as lightness, G as chroma and B as hue. Put it in the wrong place and it will
happily turn a photo into nonsense.

The intended chain keeps it right behind `lb:lch-dual`, with the curves in between:

```
lb:lch-dual → L curve (red) → C curve (green) → h curve (blue) → lb:lch-compose
```

## Relation to Lab

LCh is Lab in polar form: `a = C·cos h`, `b = C·sin h`. The conversion goes through
babl's `CIE LCH(ab) alpha float` (D50), the same Lab definition `lb:lch-levels` and
`lb:lab-compose` use, so all three agree on the resulting colour.

## Verification

- `dual → compose` identity round trip: **0.0005 codes** in 32-bit float,
  **0.49 codes** in 8-bit.
- Inside the full plug-in (`tools/check_lch_split.py`, 33 assertions): after editing
  the C curve, L* and hue deviate on the order of **0.00001 codes**.

## Notes

- Output alpha is always 1, for the same reason as `lb:lch-dual`.
- Extreme chroma or hue leaves the sRGB gamut and 8-bit output clips at 0/1 — LCh's
  gamut is larger than sRGB, which is a property of the space, not an approximation
  in the operator.
- Hue is circular: 0 and 1 are the same angle.
