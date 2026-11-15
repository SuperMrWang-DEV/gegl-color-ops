---
name: Black & White
blurb: Photoshop's Black & White — six hue sliders decide how much each colour contributes to grey, with an optional tint.
---

`lb:rgb-domain-grayscale` · menu **Colors → SuperMrWang → Tone → Black & White** ·
`GeglOperationPointFilter` (per-pixel)

## What it does

Six hue sliders — red, yellow, green, cyan, blue, magenta — decide how strongly each
colour in the image contributes to the grey result, and the grey can then be tinted.
This is Photoshop's Black & White dialog: pull blue down and a blue sky goes dark,
push yellow up and skin brightens, without any of it touching the rest of the frame.

The three RGB channels are combined with the six hue weights summed; the slider range
−200…300 matches the PS dialog, and the defaults (red 40, yellow 60, green 40,
cyan 60, blue 20, magenta 80) are Photoshop's.

## Parameters

| Parameter | Default | Notes |
|---|---|---|
| `red` / `yellow` / `green` | 40 / 60 / 40 | Weight of each hue family, −200…300 |
| `cyan` / `blue` / `magenta` | 60 / 20 / 80 | Weight of each hue family, −200…300 |
| `tint_enabled` | off | Tint the grey result |
| `tint_color` | `#E0D4B2` | Tint colour (a warm sepia by default) |
| `tint_strength` | 1 | How strongly the tint is applied, 0…1 |

## Notes

- The operator runs per pixel in the 8-bit sRGB gamma domain, so the weights behave
  like the ones in Photoshop's dialog.
- Alpha is preserved; transparent pixels stay transparent.
- Unlike GIMP's `Colors → Desaturate`, the conversion is not a fixed luma formula: you
  choose what each colour becomes, which is the whole point of Black & White.
