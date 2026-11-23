---
name: Layer Style (live)
blurb: Photoshop's ten layer effects as a live GEGL filter — drop shadow, inner shadow, both glows, bevel and emboss, satin, three overlays, stroke. The style lives on the filter stack, so nothing is baked into the pixels.
---

Photoshop's **Layer → Layer Style** set as one real-time filter attached to the
layer:

```
layer ──▶ ┌──────────────────────────┐ ──▶ canvas
          │ lb:layer-style (filter)  │
          │  shadow / inner shadow   │      parameters live on the filter
          │  both glows / bevel      │      the pixels are never written
          │  satin / 3 overlays/stroke│
          └──────────────────────────┘
```

Tick an effect, drag a slider, the image follows. Switch the filter off and it
disappears. Save as XCF, reopen, and every slider is still where you left it.
That is Photoshop's "smart filter", and it is the only non-destructive editing
GIMP 3 has.

> There is also a **destructive** Python twin in this repository:
> `plugin/layer-style` (menu `SuperMrWang → Layer → 图层样式…`). It computes the
> same ten effects and hands you back a group of editable layers — the price is
> that the original pixels are replaced and the parameters never come back. Same
> feature surface: take this one when you want to keep editing the parameters,
> take that one when you want the effects as separate layers.

## Why this has to be a GEGL op

GIMP 3's non-destructive chain only understands GEGL operations.
`Gimp.DrawableFilter.new(drawable, op_name, name)` puts the **operation name** on
the drawable's filter stack, the parameters are the operation's properties, and
`filter.update()` recomputes. The stack is saved in the XCF and undone with the
undo history.

A Python plug-in cannot do that — it can only read pixels, compute, and write
pixels. Even if it invents ten layers, that is already a baked result (which is
exactly what `plugin/layer-style` does). "Non-destructive" is not a matter of
taste; it is the line between C/GEGL and Python/pixels.

## Parameters

Effect switches sit at the top level; the indented parameters belong to the
effect above them. With "use global light" ticked, `angle` and `altitude` are
overridden by `global-angle` / `global-altitude`, exactly like Photoshop.

| Effect | Properties | Notes |
|---|---|---|
| Global | `global-angle` 120°, `global-altitude` 30° | Every effect that has "use global light" reads it |
| Drop shadow | `shadow-on`, `-color`, `-opacity` 75, `-angle`, `-global`, `-distance` 5, `-spread` 0, `-size` 5, `-contour` | size = blur radius, spread hardens the ramp |
| Outer glow | `glow-on`, `-color` `#fdfa87`, `-opacity` 75, `-size` 8, `-spread` 0, `-range` 50, `-contour` | solid colour only |
| Inner shadow | `ishadow-on`, `-color`, `-opacity`, `-angle`, `-global`, `-distance`, `-choke` 0, `-size`, `-contour` | choke pulls the ramp inwards |
| Inner glow | `iglow-on`, `-color`, `-opacity`, `-source` edge/center, `-choke`, `-size`, `-range`, `-contour` | source = edge or centre |
| Bevel & emboss | `bevel-on`, `-style` inner/outer/emboss/pillow/stroke, `-method` smooth/chisel-hard/chisel-soft, `-depth` 100, `-direction` up/down, `-size` 5, `-soften` 0, `-angle`, `-global`, `-altitude` 30, `-highlight-mode`/`-color`/`-opacity`, `-shadow-mode`/`-color`/`-opacity`, `-stroke-size` 3 | five styles × three techniques |
| Satin | `satin-on`, `-color`, `-opacity` 50, `-angle` 19, `-distance` 11, `-size` 14, `-invert`, `-mode` | two mirrored blurs, subtracted |
| Colour overlay | `color-on`, `-color` `#ff0000`, `-opacity`, `-mode` | |
| Gradient overlay | `grad-on`, `-color1`/`-color2`, `-style` linear/radial/angle/reflected/diamond, `-angle` 90, `-scale` 100, `-reverse`, `-opacity`, `-mode` | laid out over the whole image, so no tile seams |
| Pattern overlay | `pattern-on`, `-kind` dots/stripes/checker/grid/diagonal/rings, `-color1`/`-color2`, `-scale`, `-opacity`, `-mode` | procedural patterns, see below |
| Stroke | `stroke-on`, `-size` 3, `-position` outside/inside/center, `-color`, `-opacity`, `-mode` | width from an exact distance field, not a blur |

26 blend modes, 12 contours (`linear`, `cone`, `gauss`, `ring`, `sawtooth`,
`notched`, `half-round` …), 5 gradient styles.

**Patterns are computed, not GIMP's pattern library.** A GEGL op runs inside the
GEGL process and cannot see GIMP's patterns or gradients, so gradients get two
colours and patterns are six parameterisable kinds. For real patterns, use the
Python version.

## Render order

Copied from Photoshop, because it decides whether a semi-transparent layer lets
the shadow show through:

```
1. drop shadow   ┐ into an empty accumulator
2. outer glow    ┘
3. the content     ← composited with over
4. inner shadow    ← multiply, inside the edge only
5. inner glow      ← screen
6. colour / gradient / pattern overlay ← rgb only, alpha untouched
7. satin
8. bevel: shadow sheet first, highlight sheet after
9. stroke          ← over
```

Step 3 must be **over**, not an assignment: assigning wipes the shadow and glow
that were just drawn underneath (that was the first bug — the drop shadow simply
did not appear). Step 6 paints rgb and leaves alpha alone, because overlays do
not change layer opacity in Photoshop either.

## Algorithm notes

**Blending happens in sRGB values, not in linear light.** GIMP 3's default
blend modes compute in linear light: 50 % of 204 over 51 gives **153**, while
Photoshop works on the sRGB values and gives **128**. This op treats the sRGB
components as plain numbers, so soft edges do not wash out.

**The signed distance field is exact.** Stroke width, spread/choke and the bevel
height map all need "how far is the edge". The op uses Felzenszwalb's
parabola-envelope **exact** Euclidean distance transform (outside first, then
inside, two O(n) passes) instead of the ±k row approximation the numpy version
uses — so a given width is the same thickness on soft and hard edges, and
diagonals are not over-measured. All-empty and all-solid tiles take their own
branch, otherwise "no content in this tile" would be read as distance 0.

**Blur is three box passes.** Three box blurs of radius r have variance
`3·(2r+1)²/12`; the radius is solved from σ² with the same formula as the numpy
twin. Sliding window, two adds and two subtracts per pixel.

**Two tiling traps.** `process()` only receives a small piece of the result
(a 420×300 render arrived as six 70×300 tiles), so:

- the bounding box for gradients and patterns must be the **whole image**
  (recorded in `prepare`, sampled at `gx + x`). With tile-local coordinates each
  tile restarts the gradient and the seam is a hard 70 px step.
- the effects read neighbours, so `get_required_for_output` returns the entire
  input and `process()` grows the work rectangle by
  `margin = largest size + stroke`, reading with `GEGL_ABYSS_NONE` so anything
  outside counts as transparent.

## Verification

```
gimp-console -i -c -d -f --batch-interpreter=python-fu-eval \
    -b "exec(open(r'<repo>/tools/check_layer_style_gegl.py').read())" --quit
```

`tools/check_layer_style_gegl.py` has **30 checkpoints**, all of them about
non-destructiveness itself:

- after appending the filter the layer's pixels are **byte-for-byte unchanged**
- changing a property plus `update()` changes the render; `set-visible(false)`
  restores the original and switching it back restores the effect
- `set-opacity(0.5)` gives half strength (note: `set_opacity` returns `None`, and
  you **must** call `update()` after touching the config, or you read back 1.0
  and nothing changes on screen)
- save to XCF and reopen: the filter is still on the stack with `distance=20` and
  `shadow_on` intact, and the **XCF still stores the original pixels**, not the
  baked result
- `merge_filters()` empties the stack and only then do the pixels become the
  result
- 768×1024 with four effects enabled, `merge_filters` takes **0.03 s**

Parity with the numpy twin (`plugin/_shared/layer_style.py`) on 420×300 with drop
shadow + bevel + stroke + colour overlay: mean difference **0.83/255** overall,
**0.45/255** mean and **5.0** p99 where alpha > 128. The remaining large deltas
sit on 1 px, near-transparent edges where the two rasterisations cover
sub-pixels differently.

Speed (`gegl` CLI, process start included): 400×300 **1.74 s**, 1600×1200
**1.52 s**, 3200×2400 **7.71 s** with all ten effects on.

## Installation

```
./build.sh                      # produces build/layer-style.dll
./install.sh --verify           # installs into the GEGL user plug-in directory
```

On Windows GIMP only scans its own `lib/gegl-0.4/`, so copy
`build/layer-style.dll` there and fully quit and restart GIMP (unlike the Python
plug-in, which goes into `plug-ins/`). Two copies of the same module on the path
trigger `Two different plugins tried to register 'gegl_op_lb_layer_style'`.

## Differences from Photoshop

**Has:** ten effects, 26 blend modes, global light, 12 contours, spread/choke,
five gradient styles with reverse, three stroke positions, exact distance field,
true live editing.
**Missing:** texture (pattern bevels), 3D materials, a contour editor, "blend if
underlying layer", knockout, on-canvas shadow handles, real pattern resources.

Parameters are edited in the Layers dialog: the filter is a child row under the
layer with its own eye icon, and double-clicking it opens the panel GIMP
generates from the property tree. Nothing is lost, but there is no Photoshop-style
panel that stacks all ten effects — the hierarchy is expressed by the indentation
in the property names.
