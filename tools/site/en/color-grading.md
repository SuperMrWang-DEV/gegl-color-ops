---
name: Color Grading
blurb: the RAW editor's Color Grading panel — shadow, midtone, highlight and global wheels with per-band luminance, plus Blending and Balance.
---

Added 2026-11-12. Reproduces the **Color Grading** panel of the RAW editor /
the classic RAW editor: shadow, midtone, highlight and global wheels (hue + saturation),
each with its own luminance slider, plus Blending and Balance.

## Menu

`Colors → SuperMrWang → Color → Color Grading`

## Parameters (14, one for one with the the RAW editor panel)

| Parameter | Range | Default | Notes |
|---|---|---|---|
| Global Hue / Saturation / Luminance | 0–360 / 0–100 / −100–100 | 0 / 0 / 0 | Global wheel, acts evenly over the whole frame |
| Shadows Hue / Saturation / Luminance | same | 0 / 0 / 0 | Shadow wheel |
| Midtones Hue / Saturation / Luminance | same | 0 / 0 / 0 | Midtone wheel |
| Highlights Hue / Saturation / Luminance | same | 0 / 0 / 0 | Highlight wheel |
| Blending | 0–100 | 50 | Cross-fade width between neighbouring tonal bands (0 = hard split) |
| Balance | −100–100 | 0 | Shifts the shadow/highlight reach (positive = toward highlights) |

## Model

Bands are chosen from the pixel's own Rec.709 luminance (gamma domain):

- default splits: shadow/midtone **0.3**, midtone/highlight **0.7**;
- Blending spreads both hard boundaries into smoothstep transitions (100 → ±0.25
  each), and the midtone weight is 1 − shadow − highlight;
- Balance ±100 shifts both boundaries by ±0.25.

```math
h = 0.25\cdot\frac{\text{Blending}}{100},\qquad
e_{\text{sh}} = 0.3 + 0.25\cdot\frac{B}{100},\qquad
e_{\text{hi}} = 0.7 + 0.25\cdot\frac{B}{100}
```

```math
w_{\text{sh}} = 1-\operatorname{smooth}\!\left(\frac{Y-e_{\text{sh}}}{2h}+\frac{1}{2}\right),\qquad
w_{\text{hi}} = \operatorname{smooth}\!\left(\frac{Y-e_{\text{hi}}}{2h}+\frac{1}{2}\right),\qquad
w_{\text{mid}} = 1-w_{\text{sh}}-w_{\text{hi}}
```

One pass of a wheel (multiplied by the band weight w):

- luminance: `V += Lw × 0.005 × w` (same coefficient as `lb:hsl-bands`);
- tint strength `t = Sat/100 × w`: blend toward the **wheel colour at the same
  luminance**, `rgb = rgb·(1−t) + tint·t` with `tint = HSV(wheel hue, 1, V)`.
  Grey pixels pick up the tint naturally; a hue close to the wheel's complement is
  desaturated (mixed with grey). **Hue is never interpolated**, so there is no seam
  where the rotation direction flips.

```math
V \leftarrow V + 0.005\,L_w\,w,\qquad
t = \frac{\text{Sat}}{100}\,w,\qquad
\text{rgb} \leftarrow \text{rgb}\,(1-t) + \text{tint}\,t,\qquad
\text{tint} = \operatorname{HSV}(h_w,\,1,\,V)
```

> Fixed 2026-11-12: the first version used "converge the hue toward the wheel hue",
> which flipped `roundf`'s rotation direction at complementary hues (≈180° apart)
> and produced vertical banding on clipped highlights (visible in the night-blue
> demo image). It now blends toward the wheel colour, and
> `check_color_grading.py` gained a "no seam at complementary hues" test (jump of
> 1.2 code values between adjacent columns, threshold 8).

Order of execution: the global wheel (weight 1) first, then the three bands.

## Calibration status (honest disclosure)

the classic editor 2025 on this machine has **no the RAW editor plug-in installed**, so this
operator could not be calibrated code by code the way `colorize` and
`color-mask-select` were. The 0.3/0.7 splits, the ±0.25 transitions and the Rec.709
luminance are a reasonable model built from the RAW editor's documented behaviour, **not
black-box measurements**. The structure and parameter semantics map one for one onto
the the RAW editor panel; numeric behaviour is checked against that design model by
`tools/check_color_grading.py`.

## Verification

```bash
python tools/check_color_grading.py    # 12 behavioural checks (identity / bands / placement /
                                       # Blending / Balance / global / no seam)
python tools/smoke.sh                  # smoke test for every operator
```

## Known limitations

- The wheels have no separate "range" slider (hovering a wheel in the RAW editor lets you move
  the luminance endpoints); the splits are fixed at 0.3/0.7 and only Blending/Balance
  adjust the transition and the offset.
- Banding uses the pixel's own luminance (Rec.709, gamma domain), not a neighbourhood
  luminance; for neighbourhood behaviour use `lb:shadows-highlights`.
