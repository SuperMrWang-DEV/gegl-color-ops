---
name: Lens Correction
blurb: distortion, vignetting and lateral CA in one resample, with an auto scale that keeps the corners in frame.
---

`lb:lens-correction` · menu **SuperMrWang → Distort → Lens Correction…** · single input

The three Lens Correction controls people actually turn: barrel / pincushion
distortion, vignetting and lateral chromatic aberration. One operator, one
resample. GIMP's own `gegl:lens-distortion` handles distortion only; stacking
the three as separate filters would resample the picture three times and lose
sharpness at each pass.

## Normalised radius

Every radius is measured against the **half diagonal**, so the four corners sit
exactly at `r = 1`:

```
r = |p − c| / (0.5 · √(w² + h²))
```

Normalising to the short edge would make one k1 pair produce different corner
shapes on 4:3 and 3:2 — and the corners are where distortion is most visible,
so that is the one place the numbers must mean the same thing.

## Distortion

The first two terms of the Brown–Conrady radial series:

```
s(r) = 1 + k1·r² + k2·r⁴
src  = c + (p − c) · s(r) · zoom
```

- `k1 > 0` samples from further out, shrinking the picture — this **removes
  barrel distortion** and is the direction Lightroom's "barrel" slider moves.
- `k1 < 0` inflates it, adding barrel / fisheye character.
- `k2` is the r⁴ term and only bites near the corners: it cleans up what k1
  leaves behind. Typical values are 0.01–0.05; the ±0.5 range exists for
  extreme fisheye work.

`r → s(r)` has to stay monotonic. Once it folds back, one slice of the picture
gets sampled twice and the border mirrors. `k1 = -0.5` is already near that
cliff, which is why the range stops there — past it you get a broken image, not
a stronger effect.

### Auto scale

`s(1) = 1 + k1 + k2` is the corner sampling ratio, so auto scale simply divides
by it: `zoom = 1 / (1 + k1 + k2)`. The corners land back on the frame and the
picture is only pulled slightly inward — no transparent notches. Turn it off to
see those notches; that is why it is on by default. The manual `zoom` multiplies
on top, the same thing Photoshop's "Scale" slider does.

## Vignette

```
t    = smoothstep(mid, mid + feather, r)
gain = 1 + vignette/100 · t
```

Negative darkens, positive lightens (`-100` is a black corner). `midpoint`
(default 0.55) is where the falloff starts, `feather` (0.45) its width; too
small a feather and you see a hard concentric ring, which is the easiest way to
make a vignette look cheap.

The vignette is computed from the **output** radius, not the distorted source
radius: it describes illumination falloff on the sensor and should not move
when the geometry changes.

## Lateral CA

```
r_red  = r · (1 + ca_red  / halfdiag · r²)
r_blue = r · (1 + ca_blue / halfdiag · r²)
```

The shift is given **in pixels at the corners**: `ca_red = 2` moves the red
channel 2 px outward at the corners while the centre stays put (the r² makes it
vanish near the middle). On a 24 MP frame the usual amount is ±1–3 px.

**Green does not participate.** Lateral CA means the three colours image at
slightly different scales; green is both the middle one and the focus
reference, so shifting it would drag the whole picture outward. Red and blue
normally take opposite signs — that mismatch is what a purple fringe is.

## Parameters

| Property | Default | Meaning |
|---|---|---|
| `k1` | 0 | radial r² term; positive removes barrel (shrinks), negative adds it |
| `k2` | 0 | radial r⁴ term, corner residual |
| `auto-zoom` | on | divide by `1 + k1 + k2` so the corners stay in frame |
| `zoom` | 1.0 | manual scale on top of auto |
| `vignette` | 0 | percent; negative darkens, positive lightens |
| `vignette-midpoint` | 0.55 | radius where the falloff starts (corners = 1) |
| `vignette-feather` | 0.45 | width of the transition |
| `ca-red` | 0 | red channel radial shift at the corners, px |
| `ca-blue` | 0 | blue channel radial shift at the corners, px |
| `abyss` | clamp | clamp / transparent / loop / black |
| `resampling` | nohalo | nearest / bilinear / cubic / nohalo / lohalo |

## Fast paths

With all three geometric controls at zero the operator does not sample at all:

| Case | What happens | 1600×2400 |
|---|---|---|
| Everything default | `gegl_buffer_copy` | 0.09 s |
| Vignette only | read band, multiply, write back | 0.05 s |
| Distortion, no CA | one nohalo sample per pixel | 1.10 s |
| Distortion + CA | three samples (R, G, B) | 2.69 s |
| Distortion + CA, bilinear | three linear samples | 0.92 s |

CA triples the sampler cost. Leave it at zero when you do not need it. On
768×1024 the same rows read 0.07 / 0.05 / 0.22 / 0.56 s. The plug-in previews
on a 560 px copy, about 30 ms per update, so the sliders track the hand.

## Compared with Photoshop

**Has:** all three in one dialog, a live (non-destructive) filter, eleven
scriptable properties, four edge policies, five resamplers, auto scale, and
independent vignette / CA controls.

**Missing:** lens profile lookup (`.lcp` / lensfun from EXIF), geometric
correction (perspective / rotate / shift), and the "Auto" button that estimates
k1 from edge detection. None of those are resampling problems — they are about
finding the numbers. With EXIF in hand you can compute them; without it, drag
the sliders the way you would in Photoshop.

## Regression

`tools/check_lens_correction_gimp.py`, 28 checks: the operator attaches as a
layer filter, properties read back, identity parameters are byte-for-byte
identical, the source pixels survive `append_filter`, sample radius in both
directions of k1 (the test image encodes its own radius as `R = 255·r`, so the
expected values are read off the pixels), auto scale keeps the corners opaque,
transparent vs clamp edge policy, three vignette sample points, positive
vignette lightening, CA moving only red and blue in opposite directions,
extreme parameters not exploding, and 0.077 s for a fully loaded 240×240 pass.
