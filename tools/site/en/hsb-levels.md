---
name: HSB Levels
blurb: Levels on H, S and B (the numbers your colour picker shows) — nearly identical to HSL Levels, but S and V are different quantities.
---

Menu: `Colors → SuperMrWang → Tone → HSB Levels` (a filter op)

## Overview

Independent levels for HSB (that is, HSV — the three numbers on a colour picker):
H, S and B. It looks a lot like HSL Levels, but **S and B are different quantities**,
so the same slider value feels different in the two operators. Do not mix them up.

## Colour space

The operator works on babl's `HSVA float`; RGB↔HSV is babl's job.

| Component | Range | Definition |
|---|---|---|
| H | 0–360° | the same hue angle as HSL |
| S | 0–100% | `S = (max−min)/max = 1 − min/V` (HSV's S) |
| B | 0–100% | `B = V = max(R,G,B)`, the brightest channel |

HSL's S is `(max−min)/(1−|2L−1|)`, HSV's is `(max−min)/max` — the same colour can
sit at very different numbers on the two scales (light pink is HSL S=100% but HSV
S≈20%). So "push S down to 60%" gives visibly different pictures in the two
operators.

## Rules

- **Circular hue remap**: the main arc (black point → white point) maps onto the
  output arc, the rest follows proportionally, both sharing the gamma; continuous
  around the circle, bit-exact at defaults. Black and white point at the same angle
  means the whole circle, i.e. a pure hue rotation.
- **S and B are linear**: clamp → normalise → gamma → output range; an inverted
  output is an inverse.
- **Crossed black and white points swap automatically.**
- **alpha ≤ 0 passes through.**
- B to zero is pure black (V is the max channel, so 0 means all three are 0). An
  inverted B output gives a negative-style "bright goes dark, dark goes bright"
  result while hue and saturation keep their own mappings.

## Choosing between this and lb:hsl-levels

- Only want "how saturated" without touching brightness → either will do, but HSL's
  S is closer to perceived saturation; HSV's S runs high in the shadows (a dark red
  is still S=100%).
- Want to control "the brightest channel" directly → use HSB's B, which is exactly
  max; pulling B down caps the highlights.
- Want to work on "midtone lightness" → use HSL's L or `lab-levels`' L.

## Verification

`python tools/check_color_levels.py hsb` (3 cases):

| Case | Criterion | Measured |
|---|---|---|
| identity (defaults) | ≤1 code per pixel against the source | max 0 |
| saturation to zero | neutral everywhere (\|R−G\|, \|G−B\| ≤ 2) | 0 |
| formula replay | Python recomputes HSV↔RGB and the same levels chain, ≤2 codes | max 1 |

Replay parameters: H +40° overall (a full rotation from 0/360 to 40/40), S 15/100 →
0/100 with γ=1.2, B 0/100 → 10/90, covering hue wrapping and both gamma directions.

## Known issues

- Black pixels (B=0) have no defined S or H; the operator treats them as 0, and
  raising B keeps them black (V decides the brightness ceiling).
- At 8-bit precision a very dark colour has only a few quantisation steps, so a steep
  B curve shows banding.
