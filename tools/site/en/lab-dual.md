---
name: Lab Dual Extract
blurb: Packs a* and b* into two channels of one data image so two curves can move them independently — Lab's axes have no blend mode of their own in GIMP.
---

Menu: `Colors → SuperMrWang → Component → Lab Dual Extract` (a filter op)

## Overview

Packs an image into **one data image**: `R = a*`, `G = b*`, `B = L*`, all 0…1.
Alpha is always 1.

```
input ── lb:lab-dual ──> (R=a, G=b, B=L)
            │
            ├── a curve (red)
            ├── b curve (green)
            ▼
     lb:lab-compose ──> real Lab colour
            │
     (an L curve can then sit on top, LCh lightness mode)
```

## Why a and b share one image

Lab's `a` and `b` are **rectangular coordinates**, and GIMP's component blend modes
only know HSV / LCh / Luminance — there is no "a" and no "b". LCh's `C` (chroma) and
`h` (hue) are the polar form of a/b, so it looks like they could stand in:

```
C = √(a² + b²)        h = atan2(b, a)
```

But each layer's curve only sees its own single scalar. For the a curve and the b
curve to map **independently**, both values have to be in hand at the same time and
converted to `(C, h)` together — while the "LCh chroma" layer holds only a C and
cannot know what happened to b. Two 1D curves cannot express that two-variable map;
it has to be computed jointly:

```
a curve ─┐
         ├─> (a', b') ─> Lab ─> real colour
b curve ─┘
```

What comes out is already a complete colour (L∗ included), so the "L layer" only needs
one `LCh lightness` mode: Lab's L∗ and LCh's L∗ are **the same quantity**, which makes
that step bit-exact with no approximation.

## Input and output

| | Format | Meaning |
|---|---|---|
| input | `R'G'B'A float` | the filter stack's encoding-domain buffer, same domain as `component-extract` |
| output | `R'G'B'A float` | **the numbers are data, not colour**: 0.745 / 0.502 / 0.382 = a∗ 62, b∗ 0, L∗ 38 |

Ranges follow babl's `CIE Lab float` (D50 white point, the same Lab space GIMP uses):

```
a' = (a* + 128) / 255      neutral grey a* = 0 lands on 0.502
b' = (b* + 128) / 255      neutral grey b* = 0 lands on 0.502
L' = L* / 100
```

Alpha is written as 1 unconditionally: a component layer has to be opaque, and
transparency belongs on a group mask — a semi-transparent blend layer would lerp with
alpha instead of replacing.

## Verification

`tools/check_lab_split.py` runs the `dual → compose` identity round trip:
**0.010 codes** on a 32-bit float image, **0.499 codes** on 8-bit (quantisation only).
After editing the a curve the result lands on the Lab point where "a∗ moved, b∗ and L∗
did not", within **0.0026 codes** (zero pixels over 0.5 codes).

Lab points outside sRGB (which happens when a∗/b∗ are pushed hard) are clipped to
[0,1] by `lb:lab-compose` — that is the gamut, not an error in the operator.

## Notes

- The output is a data image — **do not read it as a photo**. It looks like a strange
  colour image; that is expected.
- It is only meaningful together with `lb:lab-compose`.
- Negative or above-1 values are not truncated in float images (the curves can still
  read them); clipping happens when the result is projected to 8-bit.
