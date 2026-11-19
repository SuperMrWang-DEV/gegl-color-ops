---
name: Unsharp Mask
blurb: sharpen against a blurred copy with the amount, radius and threshold of Photoshop's Unsharp Mask, plus a halo stage that keeps hard edges from growing white fringes.
---

`lb:unsharp-mask` · menu **SuperMrWang → Sharpen → Unsharp Mask** · one input

Steepens edges by adding back the difference between the image and a blurred
copy — Photoshop's Unsharp Mask, plus the one thing Smart Sharpen is really
after, as a slider.

## Parameters

| Parameter | Range | Default | Meaning |
|---|---|---|---|
| `radius` | 0.1–100 | 2.0 | σ of the reference blur. Small sharpens texture, large builds local contrast (the clarity look) |
| `amount` | 0–500% | 100 | How much of the difference is added back |
| `threshold` | 0–255 | 0 | Differences below this many levels count as flat area and are left alone |
| `fringe` | 0–100% | 100 | Clamp the result to the 3×3 neighbourhood of the original; at 100 there is no overshoot at all |

`fringe` is where the name comes from: plain unsharp masking leaves a bright and
a dark fringe on either side of a hard edge, and clamping to the local
extremes removes them.

## Algorithm

1. **Reference blur.** For σ ≤ 4 a true Gaussian kernel, separable (half width
   3σ). Above that, three chained box blurs: the variance of three boxes is
   `3·((2r+1)²−1)/12`, so `r = (√(4σ²+1) − 1)/2`. Cost independent of radius —
   O(n) instead of O(n·σ) — and past σ = 4 the two agree to better than 1/255.
2. **Difference** `d = v − blur`. If `|d| ≤ threshold/255` the pixel is emitted
   unchanged.
3. **Sharpen** `v + amount·d`.
4. **Halo suppression.** Take the 3×3 min/max of the *original*, clamp step 3
   into `[lo, hi]`, then blend towards the unclamped value by `fringe`.

What step 4 does is worth stating plainly: on a perfect step edge it is a no-op
(there is no transition left to steepen), and on a soft edge it steepens without
overshoot. At 100% the result can never grow a fringe, at the cost of losing
very small highlight overflow — use 30–50% if you want the PS-style
"glowing highlights" kind of sharpness.

## Recipes

- **Texture**: `radius=1.0 amount=120 threshold=3 fringe=100`
- **Local contrast**: `radius=15 amount=40 threshold=0 fringe=60`
- **Final output pass**: `radius=0.8 amount=90 threshold=2 fringe=100`, after resizing

## Compared with Photoshop

| | PS Unsharp Mask | PS Smart Sharpen | `lb:unsharp-mask` |
|---|---|---|---|
| Radius / amount / threshold | yes | yes | yes |
| Halo control | no | Remove: Gaussian / Lens Blur, plus fade | 3×3 clamp, 0–100% |
| Deconvolution | no | "Remove Lens Blur" is blind deconvolution | no — this op is USM only |

PS's Sharpen / Sharpen More / Sharpen Edges are three fixed presets of the same
USM; set `amount` here instead of shipping three operators.

## Testing

`python tools/check_noise_sharpen.py` — identity at amount 0 and at threshold
255, overshoot with and without the halo stage, fewer intermediate steps across
a soft edge, no change on a hard edge at 100%, alpha passthrough.
