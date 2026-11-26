---
name: Clarity & Dehaze
blurb: mid-frequency local contrast plus dark-channel dehazing — the two Camera Raw sliders that fix flat, hazy pictures.
---

`lb:clarity-dehaze` · menu **SuperMrWang → Color → Clarity & Dehaze…** · single input

GIMP has no equivalent for either. `gegl:unsharp-mask` is high-frequency
sharpening, which is not what clarity does, and there is nothing at all for
dehazing. The two live in one operator because they share the same problem
shape — a local statistic over a window — and because in Camera Raw they sit
two rows apart in the same panel.

## Clarity is mid-frequency, not sharpening

Sharpening works on **high** frequency: pixel-scale edges. Clarity works on
**mid** frequency: the tens-of-pixels scale where foliage layers, cloud volume
and skin structure live. So clarity opens up a flat photograph without
amplifying grain — the grain is not in the band it touches.

```
Y     = 0.2126 R + 0.7152 G + 0.0722 B      Rec.709 on encoded values
low   = three box passes ≈ Gaussian, radius = clarity-radius
d     = Y − low
d'    = h · tanh(d / h)                     h from clarity-protect
w     = 1 − |2Y − 1|²                       midtone weight
gain  = 1 + amount · w · d' / max(low, 0.08)
RGB  *= gain
```

Three choices carry the behaviour:

**Relative gain.** Dividing by `low` instead of adding the absolute difference
is what keeps shadows from turning into noise — their local average is 0.03, so
an absolute boost would be enormous relative to the signal — and what keeps
highlights from clipping the moment the slider moves.

**tanh compression.** Wherever `|d|` is far above `h`, the overshoot on either
side of a hard edge is squeezed to ±h, so edges grow no bright or dark halo.
Texture with amplitude within `h` passes through almost unchanged. That
distinction is the whole difference between clarity and unsharp mask.
`h = 0.03 + (1 − protect)²`, so protection 0 leaves `h = 1.03` (effectively
linear, no compression) and 1 narrows it to 0.03.

**Midtone weight.** `1 − |2Y − 1|²` is full in the midtones and zero at pure
black and white. Shadows have no room to give — pushing them is noise — and
highlights just go dead white.

Radius 40 px is where "mid" ends: smaller slides toward sharpening (texture
turns brittle), larger slides toward global contrast, which is a curve, not
clarity. On a 1920-wide frame that is about 2% of the width. Negative amounts
are a useful de-clarity: mid frequencies soften while detail survives, which is
far more presentable on skin than a Gaussian blur.

## Dehaze: inverting atmospheric scattering

Air mixes atmospheric light `A` into the scene `J` in proportion to distance:

```
I = J·t + A·(1 − t)
```

He, Sun & Tang (2009) invert it with the dark channel prior:

```
dark  = min over window( min(R,G,B) )       window = dehaze-radius
A     = mean of original pixels at the brightest 0.1% of dark
t     = 1 − ω · dark / max(lum(A), ε)       clamped to [0.12, 1]
J     = (I − A) / t + A
O     = I + s · (J − I)                     s = amount / 100
```

`A` comes from a 1024-bucket histogram rather than a sort — sorting four million
floats is the only thing here that would actually be slow.

- **ω** (`dehaze-keep`, 0.95) leaves a little haze. A full solve looks fake;
  a trace of atmosphere reads as a photograph.
- **The window** (15 px) must be larger than the brightest object inside the
  haze, or the transmission map follows object outlines instead of depth and
  the result looks like grey patches pasted over the picture.
- **The 0.12 floor on `t`** is hard: below it, 1/t multiplies noise tenfold and
  the shadows turn into coloured blotches.
- **Saturation** (0 by default, usually 10–20) compensates for the colour being
  pulled toward the grey airlight. It scales chroma around luma, leaving hue
  alone.

Negative amounts add haze, which is occasionally the point — a bit of aerial
perspective gives the foreground depth.

### Where the prior breaks

It assumes every hazy-free scene has one very dark channel. A frame full of sky,
or a large white subject (snow, a white wall), breaks that: `A` lands on the
subject itself and you get a grey sky and vignette-shaped blotches on the white
wall. Coloured haze — yellow dust, cyan spray — does not fit either, since the
prior assumes grey fog. In both cases keep the amount under 30, or use clarity
alone.

## Order, and why the whole frame is required

Dehaze runs first, then clarity. Clarity works on luma and dehaze has already
changed RGB, so the operator recomputes `Y` between the two passes; reusing the
old luma puts the low pass out of step with the new pixels and leaves a halo in
the shadows.

`get_required_for_output` returns the **full** extent: the airlight needs a
whole-frame statistic, and handing it only the requested region would make the
preview and the export use two different values of `A`. The look would jump
between them.

Both amounts at zero take a true identity path (`gegl_buffer_copy`), with no
float round trip.

## Measured, 1600×2400

| Setting | Time |
| --- | --- |
| Both zero (fast path, incl. layer copy) | 0.20 s |
| Clarity only (radius 40) | 2.03 s |
| Dehaze only (window 15) | 1.21 s |
| Both | 3.59 s |

Clarity is three box passes (six directional passes) and dehaze is a monotone
deque for the window minimum plus a histogram for the airlight — both O(N), so
a larger window costs nothing.

## Regression

`tools/check_clarity_dehaze_gimp.py`, 24 checks: byte-for-byte identity and the
original layer untouched; flat colour unchanged (d = 0); a sine grating
increasing contrast at +80 and decreasing it at −80; relative overshoot at a
hard edge under 0.35, down to 0.025 at protection 1.0; midtone gain 1.86×
against shadow gain 1.56×; synthetic haze inversion taking MAE from 40.4 to
14.0; uniform fog (I ≡ A) not exploding; negative amounts adding haze; saturation
compensation; extreme parameters; timing.

The test scenes are all **analytically known** — sine gratings, a hard step, a
synthetic fog — so the expected values come straight from the formulas. No
second implementation is needed to check the first.

One detail worth keeping: the synthetic haze image includes a sky patch where
all three channels equal `A`. Without it the airlight is underestimated, because
the dark channel is `min(R,G,B)` and a coloured patch is never bright in all
three — the inversion then looks worse than it is.

## Not implemented

Local dehazing (depth- or luma-masked, sky only), multi-scale clarity (the
radius is single), and a Photoshop-style "Auto". The first two are a matter of
more parameters; the third is a matter of estimating them.
