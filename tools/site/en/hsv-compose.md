---
name: HSV Compose
blurb: Turns the HSV data image back into real colour in one pass — three components in, final pixel out, no per-layer encode round trip.
---

Menu: `Colors → SuperMrWang → Component → HSV Compose` (a filter op)

## Overview

Restores a data image to real colour: `R = saturation`, `G = value`, `B = hue/360`
(all 0…1) go in, the matching RGB comes out of the HSV definition.

```
(R=S, G=V, B=H/360) ──lb:hsv-compose──> real colour
```

## The input convention is strict

The operator **cannot tell** a data image from an ordinary photo — it always reads
R as saturation, G as value and B as hue. Put it in the wrong place and it will
happily turn a photo into nonsense.

The intended chain keeps it right behind `lb:hsv-dual`, with the curves in between:

```
lb:hsv-dual → S curve (red) → V curve (green) → H curve (blue) → lb:hsv-compose
```

## Why not use the HSV component blend modes

GIMP's `HSV Hue / HSV Saturation / HSV Value` modes can also change HSV, but each
layer only sees one component: the hue layer changes the angle while keeping the S
and V of what is underneath — which, for HSV, happens to be exactly "change hue
only", so the old route works. The price is three layers, each needing its component
extracted to grey, curved, and re-encoded as a colour "carrying" that component, plus
a group float buffer in 8-bit just to stay colour-accurate.

A single compose has none of that: the three components live in one pipeline and the
result *is* the final colour.

## Verification

- `dual → compose` identity round trip: **0.0002 codes** in 32-bit float,
  **0.49 codes** in 8-bit.
- Inside the full plug-in (`tools/check_hsv_split.py`, 33 assertions): after editing
  the S curve, V and hue deviate by **< 0.001 codes**.

## Notes

- Output alpha is always 1, for the same reason as `lb:hsv-dual`.
- Input outside 0…1 is clamped; NaN folds to 0.
- Hue is circular: 0 and 1 are the same angle, so do not expect "1.0 is more than
  0.0" in the data image.
