---
name: Lab Compose
blurb: The inverse of Lab Dual Extract — reads a*, b* and L* back out of the data image and returns sRGB through babl, with D50 exactly matching GIMP's Lab.
---

Menu: `Colors → SuperMrWang → Component → Lab Compose` (a filter op)

## Overview

The inverse of `lb:lab-dual`: turns the `R = a*`, `G = b*`, `B = L*` data image back
into real colour. Alpha is ignored; the output is always opaque.

```
(R=a, G=b, B=L) ──lb:lab-compose──> sRGB
```

## How it computes

First undo the 0…1 mapping into babl's ranges, then let babl do the rest:

```
L* = B · 100
a* = R · 255 − 128
b* = G · 255 − 128
```

`babl_fish("CIE Lab float", "R'G'B'A float")` converts back to sRGB in one step. The
white point is D50 — the same one GIMP's Lab space, `component-extract`'s `lab-l` and
the three LCh component blend modes use — so the `dual → curves → compose` round trip
carries no table-lookup error (0.010 codes in float).

## Input and output

| | Format | Meaning |
|---|---|---|
| input | `R'G'B'A float` | **the numbers are data**: the output of `lb:lab-dual`, or a three-channel data image you assembled yourself |
| output | `R'G'B'A float` | sRGB encoded values, clipped to [0,1] |

Curves can push the data outside 0…1 (a raised to 1.4, say). Values are clamped back
into Lab's legal range first (a/b ∈ [−128,127], L ∈ [0,100]), and the RGB is clipped to
[0,1] afterwards, so no NaN or infinity reaches the buffer.

## Notes

- "R is a, G is b, B is L" is a **hard convention**: the operator cannot tell a data
  image from a photo. Pointed at a photo it interprets pixels as Lab data — wrong
  output, no error.
- It is the fourth filter in the `Lab Split (Curves)` chain. On its own it has one use:
  restoring somebody else's saved Lab data image to visible colour.
