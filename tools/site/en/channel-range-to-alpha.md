---
name: Range → Alpha
blurb: Turn a numeric range of one channel into alpha — the classic editor's "Blend If" as a standalone operator, with LAB and luminance channels available.
---

`lb:channel-range-to-alpha` · menu **Colors → SuperMrWang → Mask → Range → Alpha** ·
`GeglOperationPointFilter` (per-pixel)

## What it does

Pick one channel, set a window of values that should stay opaque, and everything
outside it fades to transparent. This is the classic editor's **Blend If** (the sliders under
"Blend If: Gray" in Layer Style) rebuilt as an operator you can stack anywhere.

```math
\alpha(x) = \begin{cases}
0, & x < l_1 \ \text{or}\ x > r_2 \\[4pt]
\dfrac{x-l_1}{l_2-l_1}, & l_1 \le x < l_2 \\[10pt]
1, & l_2 \le x \le r_1 \\[4pt]
1-\dfrac{x-r_1}{r_2-r_1}, & r_1 < x \le r_2
\end{cases}
```

`l1 → l2` is the shadow ramp, `r1 → r2` the highlight ramp. Setting `l1 = l2` (or
`r1 = r2`) gives a hard edge instead of a ramp; that is deliberate, not a
degenerate case to be repaired.

## Channels

| `channel` | Value mapped to the 0–255 slider scale |
|---|---|
| `red`, `green`, `blue` | the gamma-encoded channel × 255 |
| `gray` | 0.299 R + 0.587 G + 0.114 B, × 255 |
| `lab-l` | L* (0…100) normalised to 0…255 |
| `lab-a` | a* (−128…127) normalised to 0…255 |
| `lab-b` | b* (−128…127) normalised to 0…255 |

LAB is computed inside the operator (sRGB → XYZ with a D65 matrix → L\*a\*b\*), so no
extra conversion node is needed in the pipeline. The sliders are calibrated in 8-bit
0–255 terms, which is why the operator asks for gamma-encoded samples — feed it
linear light and the whole window shifts.

## Behaviour notes

- **Equal sliders mean a hard edge.** An earlier version forced overlapping sliders
  apart by a minimum step; at the defaults (0/0 and 255/255) that invented a phantom
  feather band, so pixels with a zero-valued channel became transparent without the
  user touching anything. Fixed on 2026-11-12.
- Slider pairs are sorted before use, so `l1 > l2` cannot invert the ramp.
- Alpha ≤ 0 pixels are passed through; otherwise alpha is multiplied into the input
  alpha rather than replacing it.
- Everything is per-pixel with no neighbourhood, so it is cheap enough to sit under
  a slider.
