---
name: CMYK Levels
blurb: Independent levels for the C/M/Y/K plates — ink black and white points, gamma, output range — on babl's device-independent CMYK.
---

Menu: `Colors → SuperMrWang → Tone → CMYK Levels` (a filter op)

## Overview

Independent levels for each of the four printing plates: ink black point, white
point, gamma and output range. Use it for separations-level adjustments such as
"darken the K plate's midtones" or "add contrast to cyan only".

## Colour space

The operator works on babl's `CMYKA float`; RGB↔CMYK is done by babl, the same
conversion GIMP's "Decompose → CMYK" uses.

**This is not an ICC separation.** babl's CMYK includes black generation (in the
GCR/UCR sense). Measured:

| RGB | C | M | Y | K |
|---|---|---|---|---|
| neutral grey 0.5 | 0 | 0 | 0 | 78.6% |
| (0.8, 0.45, 0.2) | 0 | 71.7% | 94.5% | 39.6% |
| pure red | 0 | 100% | 100% | 0 |

So K is not `1−max(R,G,B)` — that would be 50% for grey 0.5, and this gives 78.6%.
For a real prepress separation (SWOP/FOGRA profiles) you need an ICC workflow; this
operator offers "device-independent babl separation + per-plate levels" and nothing
more.

## Rules

- All four components are **linear 0–100% ink channels**: clamp → normalise → gamma
  → output range.
- **K at maximum (output 100%) means solid black**: with K=100 the CMY values no
  longer matter, since the whole image collapses into the black plate.
- **C/M/Y at zero leaves only the K plate**: a neutral greyscale image with no
  coloured ink.
- **Levels map the ink that was already computed; they never re-run GCR.** Pulling K
  from 78.6% to 90% does not make CMY drop to keep total area coverage in check. To
  "deepen K while reducing CMY" you adjust two curves by hand, or go ICC.
- Crossing black and white points swap automatically; inverting the output range
  inverts the ink (white type becomes a solid).
- **alpha ≤ 0 is passed through.**

## Verification

`python tools/check_color_levels.py cmyk` (3 cases):

| Case | Criterion | Measured |
|---|---|---|
| identity (defaults) | ≤1 code per pixel against the source | max 0 |
| C/M/Y to zero | whole image neutral (\|R−G\|, \|G−B\| ≤ 2) | 0 |
| K at maximum | brightest channel ≤ 12 everywhere | 0 |

The identity case at 0 codes shows the RGB→CMYK→RGB round trip through babl does not
drift at default settings; the other two prove that zeroing or maxing a plate
produces the expected picture — i.e. the levels really act on the plate they name.

## Known issues

- babl's CMYK is a **simplified separation with no paper white or ink
  characteristics**; the ink it computes from a given RGB has nothing to do with
  real printing. It suits "adjust one plate locally", not proofing numbers.
- CMYK's gamut is smaller than sRGB, so round trips clip saturated colours
  (especially pure green and blue).
- In 8- and 16-bit modes the ink quantisation step is coarser than in RGB, so a hard
  K curve shows banding.
