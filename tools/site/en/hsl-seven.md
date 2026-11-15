---
name: HSL 8 Bands
blurb: Eight hue bands (red, orange, yellow, green, cyan, blue, purple, magenta), each with its own H/S/L shift — Camera Raw's HSL panel.
---

`lb:hsl-seven` · menu **Colors → SuperMrWang → Color → HSL 8 Bands** ·
`GeglOperationPointFilter` (per-pixel)

## What it does

Eight hue bands — red, orange, yellow, green, cyan, blue, purple, magenta — each with
its own hue, saturation and lightness shift: 24 sliders in all, weighted by hue band
and summed, with `feather` cross-fading adjacent bands. Pixels below
`min-saturation` (greys, which have no meaningful hue) can be skipped.

The reference is Adobe Camera Raw's HSL panel: pull one band's saturation down to
desaturate just those hues, or push a band's lightness to open up one colour without
touching the rest.

## Change of 2026-11-12: the magenta band was added

Camera Raw's mixer has eight bands; this operator had seven. The old purple band
(0.78–0.92) is now split in half: purple 0.78–0.85 and magenta 0.85–0.92.

The seven original property names and their boundary behaviour are unchanged, and the
operator id stays `lb:hsl-seven` — that string is what GIMP stores in XCF files and
cannot be renamed.

## Relation to `lb:hue-saturation`

`lb:hue-saturation` is Photoshop's dialog: a master control plus six hue ranges,
relative offsets, HSL arithmetic. This one is Camera Raw's mixer: eight bands, all
three components per band. Same idea, different layout and different numbers — pick
the one whose panel you are used to.
