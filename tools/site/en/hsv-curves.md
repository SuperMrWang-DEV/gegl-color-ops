# HSV Curves (lb:hsv-curves)

Menu: `SuperMrWang → Curves → HSV Curves` (Filter)

## Overview

One curve per HSV component (hue, saturation, value). Same model as
`lb:hsb-levels`. The two everyday uses are an **S curve that pulls high
saturation down** (so the picture stops shouting) and a **V curve that lifts the
midtones**.

Levels maps three points (black, midtone, white); a curve maps any shape you like.
"Lift only the midtones and hold both ends" is not something three points can do.

The kernel lives in `common/curve.h` and is shared by all four curve operators:
point parsing, monotone cubic interpolation, a 1024-entry LUT, sampling. Each
operator only declares its babl format and component ranges.

## Colour space

Works directly in babl's `HSVA float`, the same basis as `lb:hsv-dual` and
`lb:hsb-levels`. **babl keeps HSVA in 0…1**, not 0–360 / 0–100.

| Component | Range | Notes |
|---|---|---|
| H | 0…1 | hue, **circular**, uses an offset curve (0.5 = no shift) |
| S | 0…1 | saturation |
| V | 0…1 | value |

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
curves="H 0,0.5 1,0.5|S 0,0 0.85,0.52 1,0.7|V 0,0 1,1"
```

- Coordinates are always normalised to 0…1; the operator does the physical mapping.
- An omitted component stays unchanged (a circular one stays at zero shift).
- Missing ends are filled with `(0,0)` / `(1,1)`; duplicate `x` keeps the last
  point; a bad token is skipped rather than rejecting the whole string — this
  string lives in a filter property and is meant to be hand-edited.
- Fewer than two valid points falls back to identity.

## Hue is an offset curve

As in `lb:lch-curves`: x is the input hue, 0.5 means no shift. A flat line at
another height rotates the whole ring; a bent line moves only some bands. See
that page for why neither a diagonal nor a forced pair of ends works — hue is
circular. Zero-saturation pixels (S ≈ 0) are skipped.

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
gegl in.png -o out.png -- lb:hsv-curves curves="L 0,0 0.5,0.7 1,1"
```
