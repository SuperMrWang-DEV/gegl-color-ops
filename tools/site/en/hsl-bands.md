---
name: HSL 8 Bands
blurb: Eight hue bands (red, orange, yellow, green, cyan, blue, purple, magenta), each with its own H/S/L shift — the RAW editor's HSL panel.
---

`lb:hsl-bands` · menu **SuperMrWang → Color → HSL 8 Bands** ·
`GeglOperationPointFilter` (per-pixel)

## What it does

Eight hue bands — red, orange, yellow, green, cyan, blue, purple, magenta — each with
its own hue, saturation and lightness shift: 24 sliders in all, weighted by hue band
and summed, with `feather` cross-fading adjacent bands. Pixels below
`min-saturation` (greys, which have no meaningful hue) can be skipped.

The reference is the RAW editor's HSL panel: pull one band's saturation down to
desaturate just those hues, or push a band's lightness to open up one colour without
touching the rest.

## Change of 2026-11-12: the magenta band was added

the RAW editor's mixer has eight bands; this operator had seven. The old purple band
(0.78–0.92) is now split in half: purple 0.78–0.85 and magenta 0.85–0.92.

The seven original property names and their boundary behaviour are unchanged.

## Change of 2026-11-18: the id was renamed

With the eighth band in place, `seven` in the id described the wrong thing. It is now
`lb:hsl-bands`, which no longer promises a band count. Filters already saved in XCF
files under the old id will show as unavailable; keeping the old `hsl-seven.dll`
alongside makes those files open again — the two ids do not collide.

## Algorithm

Eight hue bands each carry their own H/S/L offset, summed with band weights; the
boundaries cross-fade with smoothstep:

```math
w_k(h) = \sigma\!\left(h,\ s_k-f,\ s_k\right)\cdot\Bigl(1-\sigma\bigl(h,\ e_k,\ e_k+f\bigr)\Bigr),
\qquad f = 0.01\cdot\text{feather}
```

```math
H \mathrel{+}= \frac{\Delta H_k}{100}\cdot 60°\,w_k,\qquad
S \mathrel{+}= \frac{\Delta S_k}{100}\,w_k,\qquad
L \mathrel{+}= \frac{\Delta L_k}{100}\,w_k
```

The bands tile the circle (red 0–45°, orange 45–90°, … magenta 315–360°), so the
weights sum to 1. Pixels below `min-saturation` can be skipped entirely.


## Relation to `lb:hue-saturation`

`lb:hue-saturation` is the classic editor's dialog: a master control plus six hue ranges,
relative offsets, HSL arithmetic. This one is the RAW editor's mixer: eight bands, all
three components per band. Same idea, different layout and different numbers — pick
the one whose panel you are used to.
