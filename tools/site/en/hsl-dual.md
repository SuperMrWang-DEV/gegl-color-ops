---
name: HSL Dual Extract
blurb: Packs HSL saturation, lightness and hue into a single data image — one channel per component, so two separate curves can act on S and L without losing the coupling between them.
---

Menu: `Colors → SuperMrWang → Component → HSL Dual Extract` (a filter op)

## Overview

Packs an image into **one data image**: `R = HSL saturation`, `G = HSL lightness`,
`B = hue/360`, all 0…1. Alpha is always 1.

```
input ── lb:hsl-dual ──> (R=S, G=L, B=H/360)
            │
            ├── S curve (red)
            ├── L curve (green)
            ▼
     lb:hsl-compose ──> real colour
```

## Why S and L share one image

HSL saturation and lightness are coupled:

```
C = (1 − |2L − 1|)·S        V = L + C/2        S_hsv = C/V
```

Turning an HSL (S, L) pair back into HSV's (S, V) exactly requires the encoder to
read **both** values at once. Split into two greyscale images, each carries only its
own component, and two independent 1D curves cannot express that two-variable map —
they are only correct while one of the two is held constant.

In one image the two curves own one channel each (red, green) and `lb:hsl-compose`
reads them together, which is exact. That is why `HSL Split (Curves)` uses this
operator as its first filter.

## Input and output

| | Format | Meaning |
|---|---|---|
| input | `R'G'B'A float` | the filter stack's encoding-domain buffer, same domain as `component-extract` |
| output | `R'G'B'A float` | **the numbers are data, not colour**: 0.6 / 0.5 / 0.583 = S 60%, L 50%, hue 210° |

The conversion is babl's `HSLA float`, the same one GIMP's own HSL extraction
(`hsl-s` / `hsl-l` from `component-extract`) uses; this operator only reorders
channels. babl already returns normalised 0…1 values (`h/360`, `s`, `l`), so no
extra scaling is applied.

Alpha is written as 1 unconditionally: a component layer has to be opaque, and
transparency belongs on a group mask — a semi-transparent blend layer would lerp
with alpha instead of replacing.

## Verification

`tools/check_hsl_split.py` runs the `dual → compose` identity round trip:
**0.0002 codes** on a 32-bit float image, ≤ 1 code on 8-bit (quantisation only).
Achromatic pixels (S = 0) have no defined hue on the babl side; the operator folds
non-finite values to 0 so no NaN leaks into the buffer.

## Notes

- The output is a data image — **do not read it as a photo**. It looks like a
  strange colour image; that is expected.
- It is only meaningful together with `lb:hsl-compose`.
