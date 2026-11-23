---
name: Puppet Warp (live)
blurb: The puppet-warp solver (MLS similarity, MLS affine, ARAP) as a live GEGL filter on the layer — the pin list lives on the filter stack, not in the pixels.
---

The solver behind `plugin/puppet-warp` (MLS similarity / MLS affine / ARAP) moved
into C and attached to the layer as a **real-time filter**: the pin list is stored
on the filter, and not a single pixel of the layer is written.

```
layer ──▶ ┌──────────────────────────┐ ──▶ canvas
          │ lb:puppet-warp (filter)  │      pins / mode / radius
          └──────────────────────────┘      are the filter's properties
```

Pressing Apply only writes `pins` into the filter config and re-renders; running the
dialog again reads the pins back so you can keep dragging. Save as XCF, reopen, the
pins are still there — editable, and switchable off at any time.

> Menu: `SuperMrWang → Distort → Puppet Warp (live)…`.
> The destructive Python version sits in the same submenu; both stay available — use
> this one if you want the settings back, the other one (or “Replace this layer” in
> this dialog) to bake the result into pixels.

## Properties

| Property | Meaning |
| --- | --- |
| `pins` | `sx,sy,dx,dy; …`: where a pin was placed → where it was dragged, in layer pixels |
| `mode` | `similarity` (shape-preserving) / `affine` (stretch allowed) / `arap` (best for large bends) |
| `radius` | falloff radius as a percentage of the long side; strictly identity outside it. ARAP ignores it (global weak anchoring) |

## Why C

Non-destructive editing only exists for GEGL ops (`Gimp.DrawableFilter.new`); a
Python plug-in can only read and write pixels. MLS is a per-pixel closed form and
inherently tile-safe. ARAP solves a 48-node grid with a banded LDL: factor once,
reuse over 12 iterations, and solve again for the reverse field with the pins'
original and current positions swapped — the same formulas as the Python version,
checked pixel by pixel in the regression (`check_warp.py` / `_pw_probe.py`).

## Two traps

- **The field has to be cached, but never freed directly.** GEGL calls `process`
  per tile from several threads; a three-state slot (FREE / RESERVED / READY) plus
  LRU is what keeps another thread from releasing an array still in use.
- **The CLI takes `pins=value`, not `--pins=value`**, and the value cannot contain
  spaces (GEGL splits on whitespace). A wrong form does not error — it just hands
  back the original image, which is exactly how the comparison script first passed
  with everything wrong.
