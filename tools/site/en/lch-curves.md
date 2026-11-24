# LCh Curves (lb:lch-curves)

Menu: `SuperMrWang → Curves → LCh Curves` (Filter)

## Overview

One curve per LCh component. Same Lab basis as `lb:lab-curves`, different
coordinates: Lab is Cartesian, LCh is polar (chroma C plus hue angle h).
**Changing chroma here does not drag the hue along** — which Lab curves cannot
promise, since moving a changes both C and h.

Levels maps three points (black, midtone, white); a curve maps any shape you like.
"Lift only the midtones and hold both ends" is not something three points can do.

The kernel lives in `common/curve.h` and is shared by all four curve operators:
point parsing, monotone cubic interpolation, a 1024-entry LUT, sampling. Each
operator only declares its babl format and component ranges.

## Colour space

Works directly in babl's `CIE LCH(ab) alpha float` (**D50**).

| Component | Range | Notes |
|---|---|---|
| L | 0–100 | CIE lightness |
| C | 0–132 | chroma; the most saturated sRGB blue reaches about 131, hence 132 |
| h | 0–360° | hue angle, **circular**, uses an offset curve (below) |

## Interpolation

**Fritsch–Carlson monotone cubic Hermite**, not a natural spline.

A spline overshoots between control points: draw a curve that rises steeply and
then flattens and the flat part bulges above its control points. On lightness
that is a visible banding step; on a/b it is a ring of colour that was never in
the picture. Fritsch–Carlson keeps each tangent pair inside a circle of radius
$3|d|$ ($d$ being the secant slope), so the interpolant cannot leave the box
between neighbouring points.

## Parameters

One string argument, `curves`, split into components by `|`, each holding `x,y`
control points:

```
curves="L 0,0 0.5,0.55 1,1|C 0,0 0.5,0.62 1,1|h 0,0.55 1,0.55"
```

- Coordinates are always normalised to 0…1; the operator does the physical mapping.
- An omitted component stays unchanged (a circular one stays at zero shift).
- Missing ends are filled with `(0,0)` / `(1,1)`; duplicate `x` keeps the last
  point; a bad token is skipped rather than rejecting the whole string — this
  string lives in a filter property and is meant to be hand-edited.
- Fewer than two valid points falls back to identity.

## Hue is an offset curve

Hue is circular, and both obvious approaches fail:

- A diagonal curve maps 0 and 1 to different heights, leaving a **hard seam**
  where 0° meets 360°;
- Forcing the ends together kills whole-ring rotation, which is exactly what a
  hue curve is usually for.

So h uses an **offset curve**: x is the input hue, **0.5 means no shift**.

| Drawing | Effect |
|---|---|
| a flat line at y = 0.5 | no shift (default) |
| a flat line at y = 0.55 | rotate the whole ring by +18° (0.05 × 360°) |
| a bent line | move only some hue bands |

The shift is clamped to ±0.5: beyond that it is just turning the other way and
the curve would fold over itself. Zero-chroma pixels are skipped — grey has no
hue, and inventing an angle for it only adds noise.

## Pitfalls

- **Ranges follow babl's internal units, not the property units.**
  `CIE LCH(ab) float` holds physical values (L 0–100, C 0–132, h 0–360), while
  `HSVA` and `CMYKA` are **0–1** internally. Writing HSV as if it were 0–360
  makes a hue shift do nothing: the value 18 is read as eighteen full turns.
- **Transparent pixels pass through**: alpha ≤ 0 is never remapped.
- **The curve is a strict 0…1 map**, unlike levels it cannot cross the output
  black and white points to invert. Use levels for a negative.

## Checks

`tools/check_curves.py`: identity, semantics, **no overshoot**, alpha, parsing
tolerance, plus a point-by-point cross-check between the C operator and the
Python curve implementation (`plugin/_shared/curve_math.py`, max difference ≤ 2
codes).

```bash
python tools/check_curves.py
gegl in.png -o out.png -- lb:lch-curves curves="L 0,0 0.5,0.7 1,1"
```
