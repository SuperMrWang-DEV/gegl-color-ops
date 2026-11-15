---
name: HSI Levels
blurb: Levels on H, S and I — the image-analysis model whose intensity is the mean of the three channels, not their maximum.
---

Menu: `Colors → SuperMrWang → Tone → HSI Levels` (a filter op)

## Overview

Independent levels for H, S and I. HSI is the model image analysis likes: **I is the
mean of the three channels**, closer to "how bright is this patch" than HSV's max;
S measures "how much white is mixed in" as `1 − min/I`; and hue is defined by a
cosine, which is a different angle from HSV's hexagon.

This model is not in GIMP/babl; the conversion lives in `common/color-levels.h`.

## Colour space

| Component | Range | Definition |
|---|---|---|
| H | 0–360° | `cos H = [(R−G)+(R−B)] / (2·√((R−G)²+(R−B)(G−B)))`, with `360−H` when B>G |
| S | 0–100% | `S = 1 − min(R,G,B)/I` — white mixed in only; black is carried by I |
| I | 0–100% | `I = (R+G+B)/3` |

Three things must be stated or the numbers will not line up:

1. **H is the cosine angle**, not HSV's component-ratio angle. They agree on pure
   colours (red 0°, green 120°, blue 240°) but differ by a few degrees on
   intermediate ones. An early version mixed HSV's angle with HSI's inverse
   transform and was off by 4 code values near pure colours; it is now exactly
   inverse, and identity comes back at 0 codes.
2. **S divides by I**, not by max. The same dark red has a much lower S in HSI than
   in HSV.
3. **I can overflow**: with I near 1 and a large S, the inverse transform produces
   channels above 1 (the HSI gamut is not a cube), which are clipped to `[0,1]` as
   sRGB.

The inverse uses HSI's cosine form, one segment per 120°:

```
H∈[0,120):  B = I(1−S),  R = I[1 + S·cos H / cos(60−H)],  G = 3I − R − B
```

(The other two segments rotate R→G→B.)

## Rules

- **Circular hue remap**: main arc (black point → white point) onto the output arc,
  the rest proportionally, both sharing the gamma; bit-exact at defaults; black and
  white point at one angle is a pure hue rotation.
- **S and I are linear**: clamp → normalise → gamma → output range; inverted output
  is an inverse. S to zero gives neutral grey; I to zero gives black.
- Crossed black and white points swap automatically; **alpha ≤ 0 passes through**.

## Verification

`python tools/check_color_levels.py hsi` (3 cases):

| Case | Criterion | Measured |
|---|---|---|
| identity (defaults) | ≤1 code per pixel against the source | max 0 |
| saturation to zero | neutral everywhere (\|R−G\|, \|G−B\| ≤ 2) | 0 |
| formula replay | Python recomputes RGB→HSI→levels→HSI→RGB, ≤2 codes | max 1 |

Replay parameters: H +25° overall (a full rotation), S 0/100 → 20/80 with γ=0.9,
I 0/100 → 5/95, covering the wrap-around map, the cosine inverse and the range
scaling.

## Known issues

- HSI's S is not interchangeable with HSV's or HSL's: an "S=40%" tuned in HSL is not
  the same colour in HSI. To compare across models, look at the RGB values.
- Saturated bright regions clip on the round trip (see above); the 0-code identity
  holds at 8-bit quantisation, and at float precision those pixels are simply out of
  gamut.
- It costs more than the other four: per pixel there is `acosf`/`sqrtf`-level work
  (plus three component lookups), so a 4K image is somewhat slower than
  `lab-levels`.
