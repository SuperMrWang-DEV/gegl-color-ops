---
name: CMYK Primary
blurb: Photoshop's Selective Color — nine colour-range tabs, each holding its own C/M/Y/K ink amounts, all active at once.
---

Menu: `Colors → SuperMrWang → Color → CMYK Primary`

## Parameters

Matching Photoshop's **Selective Color**: each of the nine colour ranges keeps its
own independent C/M/Y/K values, so switching tabs never overwrites another group's
numbers, and all nine act on the image at the same time (a pixel that falls into
both "Reds" and "Whites" is affected by both).

- Sliders are named "range – ink": `Reds – Cyan`, `Yellows – Magenta`, … 9 × 4 = 36
  of them, in Photoshop's tab order: Reds → Yellows → Greens → Cyans → Blues →
  Magentas → Whites → Neutrals → Blacks.
- `Absolute Mode` is Photoshop's "Absolute" checkbox.
- The range is −100…+100, the same scale as Photoshop's sliders.

> Note: GEGL 0.4.72 as shipped here has no `property_group`, so the 36 sliders are
> flat in the panel and are told apart by their name prefix. Once GEGL is upgraded
> they can be folded into groups.

Regression check: `python tools/check_cmyk_sections.py` — verifies that a single
group matches the old build pixel for pixel, and that several groups act at once
without overwriting each other.
