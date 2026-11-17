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

## Algorithm

Per pixel in HSL: each of the six hue ranges carries its own offset, blended with
triangular weights and added to the master values.

```math
w_k(h) = \max\!\left(0,\ 1-\frac{\lvert h-c_k\rvert_{\text{circ}}}{60°\,(1+o)}\right),
\qquad c_k = 60°\,k,\quad k = 0..5
```

```math
\hat w_k = \frac{w_k}{\sum_{j=0}^{5} w_j},\qquad
H \mathrel{+}= \text{hue} + \sum_k \hat w_k\,\text{hue}_k,\quad
S \mathrel{+}= \sum_k \hat w_k\,\text{sat}_k,\quad
L \mathrel{+}= \sum_k \hat w_k\,\text{light}_k
```

- $o$ is `overlap`: the half width is $60°(1+o)$, so at 0 the six ranges tile the
  circle exactly and each centre gets full weight;
- greys ($S<10^{-5}$) skip hue and saturation and only take lightness, so they are
  never tinted;
- all-zero parameters memcpy straight through.


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
