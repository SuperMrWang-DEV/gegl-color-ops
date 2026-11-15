---
name: LAB Levels
blurb: Levels on CIELAB L, a and b — perceptual lightness and the two colour axes, each with its own curve.
---

Menu: `Colors → SuperMrWang → Tone → LAB Levels` (a filter op)

## Overview

Independent levels for CIELAB's L/a/b channels: input black/white point, gamma,
output range. L controls lightness, a (green–magenta) and b (blue–yellow) control
colour cast — adjusting a/b leaves lightness and neutral colours untouched, which is
what separates this from RGB levels.

## Colour space

The operator works on babl's `CIE Lab alpha float` (**D50 white point**); RGB↔Lab is
babl's job, so the numbers agree with GIMP's own Lab tools (the pointer dialog, the
Lab mode of Curves) and with `lb:match-color`. Doing levels in Lab is a perceptual
mapping and does not rely on a "linear light" assumption (an older build carried its
own D65 linear RGB→XYZ conversion; that is gone).

## Rules

- **a/b gamma rotates around the neutral axis at 0**: the negative half
  `[in_black, 0]` and the positive half `[0, in_white]` are each normalised before
  the gamma. A neutral pixel (a=b=0, any grey) stays put at any gamma; dragging a/b
  gamma only changes how strong the coloured midtones lean.
- **Crossed black and white points swap automatically**: if the input black point is
  pulled past the white point (or the reverse), the swapped range is used and the
  image does not collapse to one colour.
- **Inverted output (negative) works**: with output low > high the map is reversed
  and clamped to the real bounds — an inverted L is a lightness negative, inverted
  a/b are chroma negatives.
- **Pixels with alpha ≤ 0 pass through**; the alpha channel is always preserved.
- L is clipped to `[0, 100]`, a/b to `[-128, 127]`; the output clamps automatically.
- L's gamma is ordinary levels semantics (around the midpoint of the input range),
  unlike a/b's rotation around the neutral axis.

## Performance

The levels map is a monotone 1D function, so `process` builds 4096-entry lookup tables
for L and for each half-axis of a/b, then does one lookup plus a linear interpolation
per pixel — no per-pixel `powf`. The half-axis split exists because the
around-the-axis map has a discontinuous derivative at 0, and interpolating across 0
amplified tiny near-neutral inputs (a +0.03 used to come out as +1.95). The tables are
rebuilt deterministically per `process`, so they agree across tiles.

## Verification

`tools/check_lab_levels.py` (21 cases via gimp-console): identity, neutral grey stays
neutral, gamma up and down, black/white remap and clipping, inverted-output
monotonicity, crossed points, transparent pass-through, alpha preservation, and a
whole-set check with combined parameters. Expected values come from a Python mirror of
the same levels rules, compared pixel by pixel (the input buffer is created in Lab
format, so mirror and operator see the same numbers).

```bash
"D:/fastsoftware/GIMP 3/bin/gimp-console-3.2.exe" -i -c -d -f \
    --batch-interpreter=python-fu-eval \
    -b "exec(open(r'<repo>/tools/check_lab_levels.py').read())" --quit
```

## Known issues

- With a/b gamma ≠ 1, small chroma near neutral is amplified (gamma=2 turns 0.008
  into 1.0). That is the shape of an around-the-axis gamma curve (steep near the
  axis) and Photoshop behaves the same way. On noisy images, use a mask or a smaller
  gamma.
- Compared with the old build (which carried its own D65 conversion) results differ
  slightly for the same input (the white point moved from D65 to D50), so old XCF
  files with this filter applied render a little differently.
