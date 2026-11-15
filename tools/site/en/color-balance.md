---
name: Color Balance
blurb: Photoshop's Color Balance — one merged levels-style curve per channel, measured against PS to 0.3 code values, plus the legacy preserve-luminosity mode.
---

Photoshop's **Color Balance**, in two modes:

- **Preserve luminosity off (default)**: Photoshop's per-channel curve, see
  "Algorithm" below.
- **Preserve luminosity on**: the MATLAB zero-sum matrix (subtract the median from
  the coefficients → highlights `in/(1−α)` → shadows `(in−α)/(1−α)` → midtones
  `in^γ`), left unchanged; max 3.0 code values from Photoshop.

## Algorithm (preserve luminosity off)

One channel (C-R drives R, M-G drives G, Y-B drives B) is decided by its own slider
alone, independent of the other two. The three tonal-range parameters first merge
into **a single** curve:

```
G = g_shadow · g_midtone · g_highlight          the three exponents multiply
b = |s|        when the shadow slider is negative  (black point raised)
W = 255 − s    when the highlight slider is positive (white point lowered)
otherwise b = 0, W = 255

u   = (v − b) / (W − b)
out = 255 · u^G                                 (u ≥ H)
```

Near black there is a **toe**: for G < 1, `u^G` has infinite slope at 0, while
Photoshop starts with a finite slope. The segment `[b, h0]` is replaced by a cubic
Hermite:

```
h0  = b + H · (W − b)
y1  = 255 · H^G                       value at the right end of the segment
out = Hermite( (v−b)/(h0−b), Su·H, y1, G·y1 )
```

- Exponents: midtones `2^(∓s/100)`, shadows and highlights half of that
  `2^(∓s/200)`; the operator reads measured tables (`CB_G` in `cb-tables.h`) rather
  than evaluating the formula.
- `Su` (normalised initial slope) and `H` (toe width as a fraction) depend on the
  composite exponent G alone, not on which range produced it: single-range and
  combined settings fall on the same curve (table `CB_TOE`). At G ≥ 0.85, H decays
  to 0 and the toe disappears on its own.
- Ignoring the toe, midtones +100 is off by 16 code values at v≈4; with it, the
  whole range is within 0.3.

The parameters come from the Photoshop calibration in `cb-cal` (PS 26.10, 16-bit,
600 single-range settings + 9 combinations); the full derivation and accuracy are in
`../../cb-cal/RESULTS.md`.

**Do not edit `cb-tables.h` by hand** — it is generated from the calibration data by
`cb-cal/gen_cb_tables.py`.

Accuracy (1024 px continuous ramp, 16-bit, every pixel of the image):

| Group | Max | Median |
|---|---|---|
| Shadows ±1…±100 | 0.21 code | 0.01 code |
| Midtones | 0.30 code | 0.00 code |
| Highlights | 0.27 code | 0.00 code |
| Combinations | 0.65 code | 0.06 code |

(0.03 code = one 16-bit LSB)

### Relation to the two Zhihu articles

The project first implemented article 1's model — three independent channel curves
applied in sequence — and measured it drifting by 30 code values on highlights in
the positive direction and shadows in the negative direction, worse still for
combinations. Re-calibration showed that the three ranges do **not** apply in
sequence: their exponents multiply and the black/white point parameters merge. Nor
is a single range the linear `1 − k·s` exponent the article proposes. Article 2's
zero-sum matrix (preserve luminosity) does match the measurements and is kept as is.

## References

1. The mathematics behind the Color Balance adjustment layer — 王先生的副业, Zhihu
   https://zhuanlan.zhihu.com/p/679776283
2. How Photoshop's Color Balance adjustment layer works — 章佳杰, Zhihu
   https://zhuanlan.zhihu.com/p/59450298

Article 1's three-curve model does not match the measurements; article 2's zero-sum
matrix matches the preserve-luminosity mode.
