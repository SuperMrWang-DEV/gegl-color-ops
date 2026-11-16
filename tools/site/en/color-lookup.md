---
name: Color Lookup
blurb: the classic editor's Color Lookup adjustment built on the Adobe Cube LUT spec — trilinear or tetrahedral interpolation, with strength.
---

An implementation of "Color Lookup" following the Adobe Cube LUT specification,
matching the classic editor's Color Lookup adjustment layer. the classic editor can only be
calibrated with a manually-run script here (see the end), so numeric acceptance
targets an **independently written Python reference** rather than the classic editor output.

- GEGL id: `lb:color-lookup`
- Menu: `Colors → SuperMrWang → Blend → Color Lookup`
- Type: `GeglOperationFilter` (row scan; the LUT is loaded and cached in `prepare()`)
- Parameters: `file` (a .cube path), `strength` (0…1, default 1),
  `interpolation` (`trilinear` default / `tetrahedral`)

## Algorithm

1. **Parse**: `LUT_1D_SIZE` / `LUT_3D_SIZE` / `DOMAIN_MIN` / `DOMAIN_MAX` /
   `LUT_1D_INPUT_RANGE` / `LUT_3D_INPUT_RANGE` / `TITLE` / `#` comments. Node
   values are normalised to 0..1 by the declared domain, so a table with
   `DOMAIN_MAX 255` behaves the same as a 0..1 table.
2. **1D shaper** (optional): per-channel linear interpolation, one curve first.
3. **3D table**: **red varies fastest** in the file, index `r + g·n + b·n²`. Two
   ways to sample:
   - trilinear: the 8 corners weighted by volume;
   - tetrahedral: split the cube into 6 tetrahedra according to the ordering of
     `fr/fg/fb`, each using only 3 edges. No trilinear wedge near the grey axis,
     but the further from a lattice point and the less smooth the table, the more it
     differs from trilinear (up to 0.35 on the zigzag table, about 90 code values).
4. **Strength**: `out = source + (lookup − source) · strength`, lerped on encoded
   values.
5. Output clipped to 0..1; alpha passes through untouched.

Format support: **`.cube` only** (3D, pure 1D, 1D+3D). `.3dl` / `.look` / `.csp`
are not implemented — `.3dl`'s axis order (red fastest or blue fastest) would need
to be confirmed against the classic editor, and guessing is not good enough.

## Why the perceptual format is pinned

A LUT is defined for **encoded values** (0..1 sRGB code). The pad is pinned to
`R~G~B~A float`; feeding linear light samples the table at the wrong place and the
shadows visibly turn grey.

## Bad files

On a parse failure (missing file, too few nodes, `LUT_3D_SIZE` out of range) the
operator emits one `g_warning` and degrades to **identity**. Rendering is not
interrupted, and one bad path cannot turn the whole image black.

The cache key is "path + mtime + size", stat'ed once in `prepare()`, so replacing
the file at the same path reloads it automatically.

## Performance

Per pixel, `process()` does 3 (1D) + 8 (3D) table reads and about 20 multiply-adds.
33³ is the common size (about 430 KB) and cache-friendly; a pure 1D table needs only
3 interpolations.

## Acceptance

```bash
python tools/check_color_lookup.py            # 7 built-in LUTs × 2 interpolations × 3 strengths
python tools/check_color_lookup.py x.cube     # additionally compare a given file
```

Built-in cases: 2-point and 33-point identity, invert, R/B swap, a smooth
non-linearity (one with DOMAIN 0..1 and one with DOMAIN_MAX 255, which must agree),
`zigzag9` (specifically to separate the two interpolations) and a pure 1D table.
Compared pixel by pixel against the independent Python implementation, **all
0.00 code values** (bit-identical at 8 bits).

## the classic editor-side to-do

When the classic editor 2025 is launched with a script on the command line, every `Mk`
(create adjustment layer) reports "command not currently available" — even
brightness/contrast fails. The UI is simply not ready that early and it has nothing
to do with the descriptor; running `executeAction(colorLookup)` as an event does not
error but **does not change pixels** either. So save
`color-lookup-cal/batch_cl.jsx` locally, run it by hand from an already-running the classic editor
via File → Scripts → Browse…, then compare the classic editor output with the operator using
`color-lookup-cal/compare.py` (the script reports both "the classic editor vs trilinear" and
"the classic editor vs tetrahedral" and thereby settles which interpolation the classic editor uses).
