---
name: Photo Filter
blurb: Photoshop's Photo Filter, reproduced end to end — colour fill + multiply + density in linear sRGB, with W3C preserve-luminosity.
---

This operator **is** Photoshop's Photo Filter. Internally PS's `Filter → Adjustments →
Photo Filter` is equivalent to "solid colour fill + multiply + density", and this
operator reproduces the whole chain from measurement. The parameters map one for one:

| PS Photo Filter | `lb:xyz-multiply` | Notes |
|---|---|---|
| Filter colour | `overlay_color` | PS's twenty-odd presets are shortcuts; it is still a colour underneath |
| Density 0–100% | `opacity` 0–1 | divided by 100 |
| Preserve Luminosity | `preserve_luminosity` | **on by default**, matching PS's factory setting |
| — (PS has none) | `white_mode` | reference white point, **D50 by default** (PS's Lab white) |

## Algorithm (reverse-engineered, not guessed)

1. Linearise sRGB and convert to D50 XYZ with the **standard Bradford** cone-response
   matrix (not the adaptation matrix itself);
2. multiply each channel by `k = (1-d) + d · (filter colour XYZ / D50 white)`, where
   `d` is the density;
3. convert back to encoded values; if preserve-luminosity is on, apply the **W3C /
   PDF SetLum + ClipColor** (on encoded values, Rec.601 weights 0.3/0.59/0.11).

Steps 1–2 in linear sRGB are equivalent to one constant 3×3 matrix
`M = XYZ2sRGB · A⁻¹ · diag(k) · A · sRGB2XYZ`, computed once per `process`.

The evidence (all reproducible from `photo-filter-cal/`):

- pure red at 50% density turns 128 grey into a **G of 92**. Multiplying in linear
  light gives 92.6; multiplying encoded values would give only 64.
- pure red, 100% density, preserve luminosity: 128 grey becomes **(218, 90, 90)**, and
  SetLum by hand is exactly (217.6, 89.6, 89.6); preserving L\* in Lab, multiplicative
  restoration or Rec.709 weights all miss (median 5–45 code values).
- the back-solved filter colour XYZ (0.453, 0.222, 0.0166) is within 1% of "pure red
  converted to D50 divided by the D50 white" (0.4522, 0.2225, 0.0169), while
  normalising by D65 is off by 4.4% — hence D50.

## Measured accuracy (PS 2025)

| Group | Settings | Max | Median |
|---|---|---|---|
| 256-step greyscale, no preserve-luminosity | 9 | **0.71 code** | 0.12–0.40 |
| 256-step greyscale, preserve-luminosity | 3 | 1.86 code | 0.26–0.42 |
| Colour 64×64, no preserve-luminosity | 3 | **0.65 code** | 0.35–0.39 |
| Colour 64×64, preserve-luminosity | 3 | 5.65 code | 0.56–0.69 |

The large errors in the preserve-luminosity groups occur only at clipping boundaries
(55–96 of the 12288 channel values in a full colour chart) and come from PS rounding in
a different order than the W3C reference; away from those boundaries the median is
within 0.7 code values.

## Reproducing the chain

```bash
python photo-filter-cal/make_probe.py        # 256×16 greyscale probe (sRGB ICC embedded)
# run photo-filter-cal/batch_pf.jsx in PS       # 12 greyscale settings
# run photo-filter-cal/batch_pf_color.jsx in PS # 6 colour settings
python photo-filter-cal/model_pf.py         # model vs PS
python tools/check_photo_filter.py          # operator vs PS (end to end)
python tools/check_xyz_multiply.py --all    # operator vs an independent reference
```
