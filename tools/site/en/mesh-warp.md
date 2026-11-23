---
name: Mesh Warp (live)
blurb: The free-transform grid (FFD with bicubic Bezier patches) as a live GEGL filter — one mesh string on the filter stack, pixels untouched, re-running the dialog reads it back.
---

The C version of `plugin/mesh-warp`: free-form deformation with bicubic Bezier
patches, attached as a **real-time filter on the layer**. The grid string lives on
the filter, the pixels stay untouched, and running the dialog again reads the grid
back so you can keep dragging.

```
layer ──▶ ┌──────────────────────────┐ ──▶ canvas
          │ lb:mesh-warp (filter)    │      the mesh string is the only property
          └──────────────────────────┘
```

> Menu: `SuperMrWang → Distort → Mesh Warp (live)…`.
> The destructive version is the Python “Free Transform (Mesh + Handles)”; both stay
> available.

## Property

A single `mesh` string:

```
cols,rows; x,y,ux,uy,vx,vy[,auto]; …        # default U breakpoints
u:0,1,2,3                                   # written only after you add lines
v:0,1,2
```

`x,y` is the intersection point, `ux,uy` / `vx,vy` the two tangent vectors (per
parameter unit), and `auto=1` means the handles follow their neighbours and are
clamped automatically. The format matches `format_mesh_string` in
`plugin/_shared/mesh_warp.py`, so both directions read each other.

## Algorithm notes

- Each cell is a Bezier patch with 16 control points (the same construction as
  Photoshop's mesh warp). Target pixels are inverted to `(u,v)` with Newton, and the
  **source coordinate is taken from the uv position in the original grid** — swap
  that around and the whole image shifts once.
- Newton must clamp its step (0.75 cell) and stay inside `[0,cols]×[0,rows]`,
  otherwise it oscillates forever on a cell boundary.
- The inversion's initial guess is normalised by the **target canvas** width and
  height; using the mesh's own width makes the preview and the full-resolution pass
  converge to different branches (28 px apart in measurement).
- Handles are clamped to the neighbouring chord lengths, otherwise a patch
  overshoots, cells self-intersect and a tear appears on screen.
- Near fold points the C and Python solvers may land on different Newton branches:
  pixel-by-pixel agreement is mean ≈ 0.2 levels with a dozen pixels off by up to
  ~110 levels. That is a known difference in convention, and the regression allows
  for it.

## CLI

```bash
gegl in.png -o out.png -- lb:mesh-warp mesh="3,3;10,10,60,0,0,45,1;…"
```

The value cannot contain spaces (the GEGL CLI splits on whitespace); a wrong form
just hands back the original image without an error.
