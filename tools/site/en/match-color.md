---
name: Match Color
blurb: the classic editor's Match Color — Reinhard's Lab mean/variance transfer from another layer or image, with Luminance, Color Intensity, Fade and Neutralize.
---

A reproduction of the classic editor's **Image → Adjustments → Match Color**: transfer the
colour statistics of **another image or layer** onto this one. The core is the
L\*a\*b\* mean–variance affine transfer proposed by Reinhard et al. in 2001, which
the classic editor still uses.

## Model

Working in CIELAB (D50), per channel, for L, a and b:

```
out = (v − μ_target) · (σ_source / σ_target) + μ_source
```

Statistics are computed over the **whole layer** (the classic editor does the same), with the
source coming from the layer wired to the `aux` pad. With no aux connected the source
falls back to this layer itself, i.e. an identity map.

## Mapping to the classic editor's sliders

| the classic editor | Here | Semantics (model-aligned, not code-calibrated) |
|---|---|---|
| Luminance (1–200, default 100) | `luminance` | Scales how much of the L map applies: `k = slider/100`, and the map converges as `lerp(1, ratio, k)`. 100 = exact match, 200 = double correction, 1 = almost nothing |
| Color Intensity (default 100) | `color-intensity` | Same, for a/b only |
| Fade (0–100) | `fade` | Multiplies the whole map by `(1 − fade/100)`; equivalent to the classic editor's Edit → Fade |
| Neutralize | `neutralize` | Forces the output a/b means to 0 (removes the cast) while L is untouched; the source still supplies contrast |

> the classic editor 2025's Match Color **has no scripting interface** (no DOM API for the
> dialog, and both `Mk` and `matchColor` are refused), so there is no measured
> reference to calibrate against. This is model alignment, not black-box calibration —
> the same situation as Levels, and stated here honestly.

## Global statistics, tiled rendering

GEGL's `process` only sees a small tile at a time, while means and variances need the
whole layer:

- on the first `process`, input and aux are scanned once (in Lab, accumulating
  sum/sum²) and cached on the operation instance (guarded by a mutex, keyed by buffer
  pointer + extent + level);
- later tiles reuse the cache, so **dragging a slider in the preview does not
  recompute**;
- if the source layer changes (a non-destructive preview), tick "Refresh stats" once
  and it resets itself.

## Details

- **Transparent pixels do not enter the statistics**: both target and source drop
  alpha ≤ 0, so a cut-out's holes cannot drag the statistics toward black (a trap
  already hit once in Apply Image / Calculations).
- **σ guard**: σ < 1e-3 is treated as a constant channel and the ratio becomes 1. A
  flat-colour source just shifts the output mean to its own mean colour (the
  `(v − μt)` term is 0 anyway).
- **Clipping**: output L to [0, 100], a/b to [−128, 127], matching the classic editor working
  in 8-bit L\*a\*b\*.
- **Nothing to do with "only the intersection acts"**: Match Color is not a per-pixel
  blend. The source only donates statistics and the map applies to the whole target
  layer — exactly the classic editor's behaviour.
- The map is affine, so geometry need not line up: the source layer can be any size or
  offset.

## Verification

```bash
./build.sh
"D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval \
    -b "exec(open(r'<repo>/tools/check_match_color.py').read())" --quit
```

17 cases: identity, mean transfer, variance scaling, both ends of the Luminance and
Color Intensity sliders, Fade 50/100, Neutralize (including an assertion that the
output mean is ≈0), transparent aux holes excluded from the statistics, target alpha
preserved, 100-row cross-tile consistency, identity without aux, and extreme maps
staying in range. Expected values come from a Python mirror of the model, with Lab
readings taken straight from babl (the same conversion path as the operator, so the
test does not argue in a circle).
