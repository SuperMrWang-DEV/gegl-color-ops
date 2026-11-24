# LAB Curves (lb:lab-curves)

Menu: `SuperMrWang → Curves → LAB Curves` (Filter)

## Overview

One curve per LAB channel. L drives lightness, a the red–green axis, b the
yellow–blue axis. **Moving L changes tone without touching colour**, which RGB
curves cannot do: there the three channels are coupled and brightening always
drags a colour cast along.

Levels maps three points (black, midtone, white); a curve maps any shape you like.
"Lift only the midtones and hold both ends" is not something three points can do.

The kernel lives in `common/curve.h` and is shared by all four curve operators:
point parsing, monotone cubic interpolation, a 1024-entry LUT, sampling. Each
operator only declares its babl format and component ranges.

## Colour space

Works directly in babl's `CIE Lab alpha float` (**D50**), so RGB↔Lab is babl's
job — the same numbers GIMP's own Lab tools, `lb:lab-levels` and `lb:match-color` use.

| Component | Range | Notes |
|---|---|---|
| L | 0–100 | CIE lightness, mapped linearly onto the 0…1 axis |
| a | −128…127 | red (+) to green (−); neutral 0 sits at 50.2% of the axis |
| b | −128…127 | yellow (+) to blue (−); same neutral |

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
curves="L 0,0 0.25,0.18 0.75,0.86 1,1|a 0,0 0.5,0.53 1,1|b 0,0 1,1"
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
gegl in.png -o out.png -- lb:lab-curves curves="L 0,0 0.5,0.7 1,1"
```
