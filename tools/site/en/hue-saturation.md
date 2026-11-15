---
name: Hue/Saturation
blurb: GIMP-style Hue/Saturation — a master control plus six hue ranges, all offsets added in HSL.
---

A GEGL point filter modelled on GIMP's Hue-Saturation filter: per-pixel adjustments in
**HSL**, working on the perceptual (non-linear) `R~G~B~A float` format and following
the source colour space automatically.

## Features

- **Master**: `hue` (degrees, ±180), `saturation` (±1, additive), `lightness` (±1,
  additive)
- **Six hue ranges** (red / yellow / green / cyan / blue / magenta, centres 60° apart),
  each with its own `*-hue / *-saturation / *-lightness`, blended with the master by a
  triangular weight
- **`overlap`** (0–1): range width = 60° × (1 + overlap). The default of 0 makes the six
  ranges tile the wheel exactly, with each centre getting 100% of its setting; raising
  it lets neighbours bleed into each other (softer, but the peak strength is diluted in
  proportion)
- Grey pixels (S < 1e-5) are not tinted: the hue and saturation adjustments are
  skipped and only lightness is applied
- All-zero parameters `memcpy` straight through (alpha included); HDR values outside
  the range are clipped to [0,1] before the maths

## Usage in GIMP 3 Python

```python
from gi.repository import Gimp, Gegl

filter = Gimp.DrawableFilter.new(drawable, Gegl.Orientation.AUTO, "lb:hue-saturation", 0)
config = filter.get_config()
config.set_property("hue", 45.0)          # degrees
config.set_property("saturation", 0.3)    # -1..1
config.set_property("green-saturation", -0.5)
drawable.merge_filter(filter)             # non-destructive; Gimp.displays_flush() to refresh
```

## Verified behaviour (GEGL CLI)

| Case | Result |
|---|---|
| all-zero identity | output byte-identical to input (max diff = 0) |
| `hue=60` | red (0°)→yellow (60°), cyan (180°)→blue (240°), exactly +60° |
| `saturation=0.45` | HSL S: 0.082 → 0.535 (exactly +0.45), hue and lightness unchanged |
| grey band | completely unchanged (the achromatic guard works) |
| `green-hue=-55 green-saturation=-0.7` | only the green/yellow-green range moves to ~82° and desaturates; red, blue and magenta are untouched |
