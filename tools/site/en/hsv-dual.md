---
name: HSV Dual Extract
blurb: Packs HSV saturation, value and hue into a single data image — three curves, one compose, instead of three separate layers that each quantise on the way back.
---

Menu: `Colors → SuperMrWang → Component → HSV Dual Extract` (a filter op)

## Overview

Packs an image into **one data image**: `R = HSV saturation`, `G = HSV value`,
`B = hue/360`, all 0…1. Alpha is always 1.

```
input ── lb:hsv-dual ──> (R=S, G=V, B=H/360)
            │
            ├── S curve (red)
            ├── V curve (green)
            ├── H curve (blue)
            ▼
     lb:hsv-compose ──> real colour
```

## Why pack all three into one image

HSV's three components are coupled:

```
V = max(R,G,B)              S = (max − min) / V
H = set by the ratio between them (linear within 60° steps)
```

For "change S only, leave V and H alone" to hold exactly, the composer has to read
all three at once. Split into three greyscale images and you can only swap them back
layer by layer with GIMP's HSV component blend modes — the old `HSV Split (Curves)`
route: three layers, each doing `extract → curves → encode`, three encodes and three
quantisations.

One image, three curves, one compose is just as exact with two fewer layers and half
the filters.

## Input and output

| | Format | Meaning |
|---|---|---|
| input | `R'G'B'A float` | the filter stack's encoding-domain buffer, same domain as `component-extract` |
| output | `R'G'B'A float` | **the numbers are data, not colour**: 0.6 / 0.8 / 0.583 = S 60%, V 80%, hue 210° |

The conversion is babl's `HSVA float`, the same one GIMP's HSV component mode uses;
babl already returns normalised 0…1 values (`h/360`, `s`, `v`), so this operator only
reorders channels.

Alpha is written as 1 unconditionally: a component layer has to be opaque, and
transparency belongs on a group mask.

## Verification

`tools/check_hsv_split.py` runs the `dual → compose` identity round trip:
**0.0002 codes** in 32-bit float, **0.49 codes** in 8-bit (which is the quantisation
itself). Grey pixels (S = 0) have no defined hue on the babl side; the operator folds
non-finite values to 0 so no NaN leaks into the buffer.

## Notes

- The output is a data image — **do not read it as a photo**.
- It only works paired with `lb:hsv-compose`.
