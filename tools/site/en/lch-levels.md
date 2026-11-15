---
name: LCH Levels
blurb: Levels on CIE LCh — chroma and hue angle as separate channels, so changing one never drags the other along.
---

Menu: `Colors → SuperMrWang → Tone → LCH Levels` (a filter op)

## Overview

Independent levels for CIE LCh's L, C and H. Same Lab base as `lb:lab-levels`, but
in polar coordinates (chroma C and hue angle H instead of the a/b axes). **Changing
chroma in LCh does not drag the hue, and changing hue does not drag the chroma** —
which Lab levels cannot do (there, moving a changes C and H together).

## Colour space

Works directly on babl's `CIE LCH(ab) alpha float` (**D50 white point**); RGB↔LCh is
babl's job, the same convention as GIMP's "Decompose → LCH".

| Component | Range | Notes |
|---|---|---|
| L | 0–100 | CIE lightness |
| C | 0–~132 | chroma; inside sRGB the maximum is about 131 (pure blue), hence 132 |
| H | 0–360° | hue angle; 0° leans red (pure red is about 40°, pure blue about 301°) |

## Rules

- **Circular hue remap**: cut the circle at the black point, map the main arc
  (black point → white point) onto the output arc and the rest proportionally, both
  sharing the gamma. Bit-exact at defaults; black and white point at one angle means
  a pure hue rotation.
- **C is linear**: C to zero turns the image neutral grey (Lab a=b=0) — the most
  common way to desaturate. An inverted C output (low > high) gives a
  complementary-looking result while lightness stays put.
- **L is linear**: ordinary levels semantics, identical to `lab-levels`' L.
- **Crossed black and white points swap automatically.**
- **alpha ≤ 0 passes through.**
- Input above the gamut is clipped to C = 132; the output C can be pushed higher and
  whatever falls outside sRGB is clipped by babl's conversion back to RGB (the pixels
  GIMP's gamut warning would flag).

## Which operator for what

| Need | Use |
|---|---|
| Lower or raise chroma alone, hue untouched | this operator (C channel) |
| Rotate hue alone, chroma untouched | this operator (H channel) |
| Move the a and b axes separately (add yellow without green) | `lb:lab-levels` |
| Per-hue-range saturation/lightness, ACR style | `lb:hsl-seven` |

## Verification

`python tools/check_color_levels.py lch` (3 cases):

| Case | Criterion | Measured |
|---|---|---|
| identity (defaults) | ≤1 code per pixel against the source | max 0 |
| chroma to zero | neutral everywhere (\|R−G\|, \|G−B\| ≤ 2) | 0 |
| hue ring +180° | at least 80% of the ring row visibly changes colour | 72/72 |

LCh↔RGB lives inside babl and cannot be recomputed in Python, so there is no formula
replay here — but "C to zero must give neutral grey" and "H +180° must recolour the
whole ring" cover the conversion direction and the ring topology, and identity at
0 codes shows the round trip does not drift.

## Known issues

- H is meaningless when C≈0 (near-neutral); the operator treats it as H=0, and
  moving H then changes nothing.
- H's 360° and 0° are the same point, so output low/high of 360 and 0 are equivalent;
  the UI does not say so.
