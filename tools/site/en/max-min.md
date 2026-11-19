---
name: Maximum / Minimum
blurb: Morphological dilate and erode — Photoshop's Maximum / Minimum filter. Grows or shrinks bright areas, radius 1–100, square or disc, compared in the buffer's own precision.
---

The two basic morphological operators, and the equivalent of Photoshop's
**Maximum / Minimum** filter: every output pixel takes the **largest** value in its
neighbourhood (dilate) or the **smallest** (erode).

```
        ┌─────────────┐               ┌─────────────┐
in ────▶│ take max    │──▶ bright out │ take min    │──▶ bright in
        └─────────────┘               └─────────────┘
```

Maximum pushes bright areas outwards and swallows small dark specks; minimum shrinks
bright areas and chews away the fringe left after a cut-out. Mask refinement,
despeckling, glow bases and outlines all use it.

## Why it has to be written here

Up to 2.10 GIMP had Filters → Generic → Dilate / Erode; afterwards GEGL's
`gegl:dilate` / `gegl:erode` took over. Those are **workshop** operators and are not
compiled into the official Windows build:

```
$ gegl --list-all | grep -E "dilate|erode"      # empty
$ PDB lookup plug-in-dilate                     # None
$ strings libgegl-0.4-0.dll | grep gegl:dilate  # empty
```

All three are empty on the 3.2.8 install this was written against. The only native
leftovers are `gimp-selection-grow` / `-shrink`, and those act on **selections** only —
they cannot change a mask or a layer's pixels.

So this operator calls no native procedure; it computes the result itself. That makes
it one of the few here that cannot be validated against a native reference — but
morphology is completely determined, see the verification section.

## Parameters

| Parameter | Range | Meaning |
|---|---|---|
| `mode` | `maximum` / `minimum` | dilate / erode |
| `radius` | 1–100 | neighbourhood radius in **pixels**; r=1 is 3×3, one ring outwards |
| `shape` | `square` / `round` | square window (±r, ±r); disc of radius r — PS's Squareness / Roundness |
| `affect-alpha` | boolean, off | when off, alpha is passed through (PS leaves layer opacity alone too) |

**Radius means the same as in Photoshop**: it checks a `(±r, ±r)` neighbourhood, not a
window edge length, so r=1 gives exactly 3×3 and not 2×2.

A disc uses `dx² + dy² ≤ r²`, i.e. a per-row half-width of `⌊√(r²−dy²)⌋`:

| r | dy=0 | dy=±1 | dy=±2 | dy=±3 |
|---|---|---|---|---|
| 1 | 1 | 0 | — | — |
| 2 | 2 | 1 | 0 | — |
| 3 | 3 | 2 | 2 | 0 |

## Algorithm

**A square window is separable**: a 2D window extremum equals a horizontal pass
followed by a vertical one, both 1D sliding extrema. The 1D pass uses **van Herk /
Gil-Werman**: split the row into blocks the size of the window, compute prefix and
suffix extrema inside each block, and any window is exactly covered by "the suffix
starting at its left edge + the prefix ending at its right edge" — two comparisons per
pixel. Total cost **O(n), independent of the radius**.

**A disc is not separable** (each row has a different half-width), so it falls back to
one horizontal pass per `dy` accumulated vertically: **O(n·r)**. At radius 100 that is
about 100× the comparisons of a square window, but extrema are compares, not
multiplies, so a 3 MP image is still seconds.

Measured on 3.0 MP u8 RGB, single thread:

| Shape | Radius | Time |
|---|---|---|
| square | 1 | 13 ms |
| square | 100 | 43 ms |
| disc | 10 | 63 ms |
| disc | 100 | 1.26 s |

Square r=1 versus r=100 differing by only 3× is the O(n) claim in practice.

## Precision: three copies of the kernel

An extremum only needs ordering, but **the value itself must be carried out
untouched**. So `maxmin-kernel.h` is a template included three times by `max-min.c`
with different `PLANE_T` macros, generating identical u8 / u16 / float32 code:

```c
#define PLANE_T     guint8
#define PLANE_BAND  band_u8
#include "maxmin-kernel.h"
```

The buffer's own precision is the precision used for the comparison, with **no format
conversion in between**. Reading a u16 as float and writing it back moves individual
pixels by one code — that is not allowed here. Equally, no colour management and no
gamma conversion: PS's Maximum / Minimum also work straight on channel values, and
following that semantics is what reproduces the same colour fringing.

## Borders

Outside the canvas the edge pixels are replicated. For an extremum that is
**bit-identical** to only counting the in-canvas part of the window: the replicated
values are copies of an edge pixel that is already inside the window, so no new value
enters. Unlike a blur, nothing darkens at the border — and no extra abyss parameter is
needed.

## Per channel

Each colour / grey component is processed independently and **alpha is left alone by
default**, which is PS's semantics too: the filter does not change layer opacity. Turn
`affect-alpha` on to include it.

Colour images therefore show fringing (magenta along red/blue edges). That is not a
bug, it is what per-channel extrema do. To avoid it, target a single-plane drawable: a
mask, a channel or a greyscale layer.

## Verification

There is no native implementation on this machine to compare against, so the reference
is an **O(r²) four-deep loop** (the plain-Python `brute()` in
`tools/check_max_min.py`) — a completely separate code path from van Herk:

```
python  tools/check_max_min.py   # runs inside GIMP's python-fu, see the header
```

27 checks covering:

- u8 / u16 / float32, **byte-for-byte / bit-for-bit identical**
- square and disc × maximum and minimum × radii 1 / 2 / 5
- single-channel `Y u8` (the mask case) and RGBA
- alpha untouched by default, and with `affect-alpha` on
- image borders (the brute force clamps too, so both must agree)
- a 301 px tall image crossing the 128-row band boundary, to prove the bands join
- radius 100 on a 9×7 image, where the window is larger than the canvas
- minimum then maximum (an opening): the isolated speck disappears, the square holds
- a 2000×1500 performance sample

The plug-in layer has its own `tools/check_max_min_plugin.py` (12 checks): procedure
registration, non-destructive filter attachment, mask baking, layer-group rejection,
out-of-range radius stopped by the argument check.

## Two traps in the banded implementation

Input is read in 128-row bands with `r` pixels of horizontal and vertical margin, all
channels processed before the band is written back. **The channel loop must sit inside
the band loop**: the other way round, the next channel rebuilds the band from the input
and overwrites the previous channel's result. That was the first version — six u8 cases
failed while the single-channel ones all passed, which makes it easy to miss.

And the column scratch buffer must be sized `max(pw, ph)`. Allocating only `pw` bytes
writes out of bounds on tall, narrow bands — which shows up as the plug-in crashing
after a dozen cases rather than as a wrong pixel.
