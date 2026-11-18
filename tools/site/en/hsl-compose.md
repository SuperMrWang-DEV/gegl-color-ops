---
name: HSL Compose
blurb: Turns the HSL data image back into real colour. The mirror half of HSL Dual Extract — without it the packed channels mean nothing.
---

Menu: `Colors → SuperMrWang → Component → HSL Compose` (a filter op)

## Overview

Restores a data image to real colour: `R = saturation`, `G = lightness`,
`B = hue/360` (all 0…1) go in, the matching HSL colour comes out, alpha is 1.

```
(R=S, G=L, B=H/360) ──lb:hsl-compose──> real colour
```

## The input convention is strict

The operator **cannot tell** a data image from an ordinary photo — it always reads
R as saturation, G as lightness and B as hue. Put it in the wrong place and it will
happily turn a photo into nonsense.

The intended chain keeps it right behind `lb:hsl-dual`, with the curves in between:

```
lb:hsl-dual → S curve (red) → L curve (green) → lb:hsl-compose
```

The two curves only touch R and G, so B (hue) passes through untouched and compose
sees the original hue.

## Why not just treat S as V

The difference between HSL and HSV sits exactly here: `V = L + C/2`, and
`C = (1−|2L−1|)·S` carries the saturation. Feeding HSL's L straight into the
"HSV value" blend mode is off by **25–64 codes** on mid-lightness saturated colours
(at S=1, L=0.5 the error is exactly C/2 = 64 codes). This operator computes the
formula above instead of approximating it.

The conversion is babl's `HSLA float`, the same one GIMP's own HSL uses.

## Verification

- `dual → compose` identity round trip: **0.0002 codes** in 32-bit float, ≤ 1 code
  in 8-bit.
- Inside the full plug-in (Hue layer and blend mode included), all 28 assertions in
  `tools/check_hsl_split.py` pass: after editing the S curve the result's HSL
  saturation equals `f(original S)`, with lightness and hue within 0.0001 codes.

## Notes

- Output alpha is always 1, for the same reason as `lb:hsl-dual`.
- Input outside 0…1 is clamped; NaN folds to 0.
