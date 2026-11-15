---
name: HSL Levels
blurb: Levels on H, S and L separately — hue, saturation and lightness each get their own black/white point, gamma and output range.
---

Menu: `Colors → SuperMrWang → Tone → HSL Levels` (a filter op)

## Overview

Independent levels for HSL's H, S and L: input black/white point, gamma, output
range. Compared with RGB levels this changes **three perceptual dimensions**: hue,
saturation and lightness each follow their own curve without crosstalk.

## Colour space

The operator works directly on babl's `HSLA float`; RGB↔HSL is babl's job — the same
conversion GIMP's "Decompose → HSL" and "Extract Component → HSL Saturation/Lightness"
use. There is no hand-written colour conversion inside the operator.

- H: 0–360°, stored as babl's 0–1 normalised value, shown in degrees
- S: 0–100%, defined as `S = (max−min) / (1 − |2L−1|)` (HSL's S, not HSV's)
- L: 0–100%, `L = (max+min)/2`

## Rules

- **Hue is circular** and cannot be clamped like an ordinary channel. The circle is
  cut at the black point: the main arc "black point → white point (clockwise)" maps
  linearly onto the output arc "output low → output high", the remaining arc maps
  proportionally onto the remaining arc length, and both share the gamma. It is
  continuous all the way round; the defaults (0/360 → 0/360, γ=1) restore the input
  bit for bit.
- **Black and white point at the same angle means the whole circle**: pulling both
  to one angle gives "pure hue rotation + wrap-around gamma" instead of collapsing to
  a single colour.
- **S and L are ordinary linear channels**: clamp to the input range → normalise →
  gamma → map onto the output range. An inverted output (low > high) gives a
  negative-style inverse.
- **Crossed black and white points swap automatically**, so overshooting a slider
  never produces a negative range.
- **Pixels with alpha ≤ 0 pass through untouched**; their colour is not mapped.

## Relation to lb:lab-levels

`lab-levels` works in CIE Lab, where a and b are bipolar channels (gamma rotates
around the neutral axis at 0). Here everything is in HSL, where all three components
are single-polar quantities starting at 0, so gamma means exactly what it means in
ordinary levels. For perceptual lightness use `lab-levels`' L; to move **a range of
hues** around, or to treat saturation differently by lightness, use this.

## Verification

`python tools/check_color_levels.py hsl` (5 cases):

| Case | Criterion | Measured |
|---|---|---|
| identity (defaults) | ≤1 code per pixel against the source | max 0 |
| saturation to zero | \|R−G\|, \|G−B\| ≤ 2 everywhere | 0 |
| lightness to zero | brightest channel ≤ 12 everywhere | 0 |
| formula replay | Python recomputes the same chain (arc remap + gamma + HSL round trip), ≤2 codes | max 1 |
| transparent pass-through | RGB of alpha=0 rows unchanged | 0 |

The formula replay uses parameters with gamma and crossed points (H 30/330 → 0/300,
γ=1.4; S 10/90 → 0/100, γ=0.8; L 5/95, γ=1.1), so both segments of the circular map,
the gamma direction and the output range are covered.

## Known issues

- Neutral colours (S=0) have no defined hue; the operator treats them as H=0, and
  once S is zero the hue slider changes nothing — a property of HSL itself.
- In 8-bit the quantisation step between neighbouring hues is about 1.4°, so a steep
  hue curve shows mild banding. Work in 16-bit or float when you can.
