# CMYK Curves (lb:cmyk-curves)

Menu: `SuperMrWang → Curves → CMYK Curves` (Filter)

## Overview

One curve per ink plate. The usual four-colour moves: **shape the K
midtones** to control overall density, and **shape a single plate** (C, M or Y)
to correct a cast without disturbing the other three. Levels cannot do this — it
only moves a plate's black and white points, not its shape.

Levels maps three points (black, midtone, white); a curve maps any shape you like.
"Lift only the midtones and hold both ends" is not something three points can do.

The kernel lives in `common/curve.h` and is shared by all four curve operators:
point parsing, monotone cubic interpolation, a 1024-entry LUT, sampling. Each
operator only declares its babl format and component ranges.

## Colour space

Works directly in babl's `CMYKA float`, the same separation basis as
`lb:cmyk-levels` and `lb:cmyk-primary-correction` — **babl keeps CMYKA in
0…1**, not 0–100 percent. This is not an ICC-profile separation, so the result is
only self-consistent inside this working space.

| Component | Range | Notes |
|---|---|---|
| C | 0…1 | cyan ink |
| M | 0…1 | magenta ink |
| Y | 0…1 | yellow ink |
| K | 0…1 | black ink |

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
curves="C 0,0 0.5,0.42 1,1|M 0,0 1,1|Y 0,0 1,1|K 0,0 1,1"
```

- Coordinates are always normalised to 0…1; the operator does the physical mapping.
- An omitted component stays unchanged (a circular one stays at zero shift).
- Missing ends are filled with `(0,0)` / `(1,1)`; duplicate `x` keeps the last
  point; a bad token is skipped rather than rejecting the whole string — this
  string lives in a filter property and is meant to be hand-edited.
- Fewer than two valid points falls back to identity.



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
gegl in.png -o out.png -- lb:cmyk-curves curves="L 0,0 0.5,0.7 1,1"
```
