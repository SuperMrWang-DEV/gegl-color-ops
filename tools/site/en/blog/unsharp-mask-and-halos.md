---
title: Why sharpening grows white fringes, and how to stop it
date: 2026-11-18
lede: Unsharp masking is just adding the difference back, and the bill is overshoot. Photoshop pays it with fading and deconvolution; we pay it with something cheaper — clamping the result to the neighbourhood extremes.
tags: Sharpen, USM, Halos
---

Unsharp masking comes from the darkroom: a blurred negative serves as a mask, the original
is subtracted from it, and edges float up. The digital version is the same idea in one line:

```math
\text{out} = v + a \cdot (v - \text{blur}(v))
```

`a` is the amount; the blur radius decides what counts as an edge. The larger the
difference, the sharper — and that difference is exactly where the trouble lives.

## Overshoot: where the fringe comes from

Take an ideal step edge: 0 on the left, 1 on the right. After blurring, both sides have a
transition; say the pixel just left of the edge is lifted to 0.15 and the one just right of
it is pulled down to 0.85.

| Position | `v` | `blur` | `v − blur` | output at `a=1` |
|---|---|---|---|---|
| dark side | 0.00 | 0.15 | −0.15 | **−0.15** |
| bright side | 1.00 | 0.85 | +0.15 | **1.15** |

Adding the difference back pushes the dark side below zero and the bright side above one.
An 8-bit buffer clamps both, so it merely looks harder. But on a float buffer, or through a
blend mode, the excess is real: a dark line on one side, a bright line on the other. That is
the fringe.

The larger the amount and the radius, the bigger the overshoot. So the classic symptom of
over-sharpening is not "too sharp" — it is **edges that glow and look dirty**.

## Three usual remedies

1. **Threshold.** Pixels whose difference is below `threshold/255` pass through untouched.
   This stops noise being amplified, and does nothing at all for a genuine hard edge —
   where the difference is largest.
2. **Fade highlights / shadows.** The two sliders in Photoshop's Smart Sharpen. Right
   direction, but global: it also lets go of the midtones that most need sharpening.
3. **Deconvolution.** "Remove lens blur" is blind deconvolution. It attacks overshoot at
   the root, at the cost of speed and sensitivity to its parameters.

## Our fourth: clamp to the neighbourhood extremes

For each pixel, take `[lo, hi]` over the **original** 3×3 neighbourhood, clamp the sharpened
value into it, then blend with the unclamped version by `fringe` (0–100%):

```math
\text{out} = (1-f)\cdot\big(v + a\,d\big) + f\cdot \mathrm{clamp}\big(v + a\,d,\; lo,\; hi\big)
```

Two extremes explain why it works:

- **Hard edge**: the 3×3 neighbourhood already contains both 0 and 1, so `[lo, hi] = [0, 1]`
  and the clamp does nothing — and a hard edge cannot get any steeper anyway, so "nothing"
  is exactly right.
- **Soft edge**: the extremes are the two ends of the transition, so the clamped result is
  pressed towards the ends, never past them. The ramp gets steeper; it never overshoots.

With `fringe=100` the result **cannot** gain a bright or dark fringe. The cost is that
genuine highlight spill — that small blown specular patch — is flattened too. For the
Photoshop "glowing highlights" look, set `fringe` to 30–50 and keep a little overshoot.

## Large radii

Small radii (σ ≤ 4) use a true Gaussian, separable, cost proportional to the radius. But the
local-contrast / clarity style wants radius 15, sometimes 50, and `O(n·σ)` on forty
megapixels is slow.

Large radii fall back to **three chained box blurs**. Three boxes have variance
`3·((2r+1)²−1)/12`, so the radius is

```math
r = \frac{\sqrt{4\sigma^2 + 1} - 1}{2}
```

The cost is independent of the radius (`O(n)`, a fixed handful of adds per pixel), and at
σ ≥ 4 the difference from a true Gaussian is below 1/255 — unmeasurable on 8-bit output,
and the last bit or two at 16-bit.

## Choosing parameters

| Goal | radius | amount | threshold | fringe |
|---|---|---|---|---|
| Texture sharpening | 1.0 | 120% | 3 | 100 |
| Local contrast / clarity | 15 | 40% | 0 | 60 |
| Last pass before downscaling | 0.8 | 90% | 2 | 100 |

Order matters: **denoise first, sharpen second**. USM treats noise as edges; `lb:reduce-noise`
smooths only flat areas and leaves edges alone, so the two belong together.

## Self-check

The sharpening assertions in `python tools/check_noise_sharpen.py`:

- `amount=0` and `threshold=255` are bit-exact identities;
- with halo suppression on and off, compare overshoot on both sides of a hard edge:
  at `fringe=100` it must be zero;
- a soft edge ends up with fewer steps (it really did get steeper) without crossing its ends;
- a hard edge is unchanged under full suppression;
- alpha passes through untouched.

The menu entry is `SuperMrWang → Sharpen → Unsharp Mask`.
