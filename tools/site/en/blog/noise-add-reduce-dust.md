---
title: The noise trio: easy to add, possible to remove
date: 2026-11-19
lede: Add Noise, Reduce Noise and Dust & Scratches share one Photoshop menu, but making them usable comes down to details: can the random numbers be reproduced, does denoising smear edges, and does an isolated speck elect itself.
tags: Noise, Denoise, Median
---

Photoshop's Filter → Noise menu holds a row of entries: Add Noise, Reduce Noise, Dust &
Scratches, Median. They look like four unrelated tools; they are really two directions —
adding noise and removing it — plus one special case for isolated pixels. We built three
operators along that split: `lb:add-noise`, `lb:reduce-noise`, `lb:dust-scratches`.

## 1. Add Noise: the random numbers have to be reproducible

Photoshop draws a fresh set of random numbers on every application. Apply twice with the
same settings and the grain is completely different; trying to compare amount 8 with amount
10 means comparing grain *and* seed at once, which is not a comparison. The only way to
reproduce is to duplicate the layer and keep it — clumsy and heavy.

The hard part is not randomness, it is randomness **under tiled processing**. GEGL cuts a
large image into bands across threads. If the random numbers are drawn by "which pixel am I
on", a different split gives a different result: the same image produces different grain at
different thread counts, which is worse than Photoshop's irreproducibility.

So the seed is mixed with the **row index**: row `y` gets its stream from hash(`seed`, `y`),
and advances along the row. As a result:

- whole image, eight bands, one thread, eight threads — all **bit-identical**;
- changing `seed` gives a whole new grain, and the same seed always returns the same one.

Gaussian noise uses Box–Muller with `u1, u2 ~ U(0,1]`:

```math
n = \sqrt{-2 \ln u_1} \cdot \cos(2\pi u_2)
```

With `monochrome` on, all three channels share one `n` (grey grain); off, each draws its
own (colour grain). `alpha` is never touched — grain changes pixel values, not layer
opacity.

## 2. Reduce Noise: average only the neighbours that look alike

A plain blur smears edges; a bilateral filter preserves them but is slow. Photoshop's
Reduce Noise takes the middle road: the sigma filter (Lee, 1983). For each pixel, look at the
`(2r+1)²` neighbourhood and weight each neighbour by the *largest* per-channel difference
`d`:

```math
w = \max\left(0,\; 1 - \left(\frac{d}{t}\right)^2\right),
\qquad \text{out} = \frac{\sum w\,v}{\sum w}
```

Neighbours with `d > t` get zero weight, so pixels on the other side of an edge simply do
not participate in the average. That is why it does not smear, with no edge detection and
none of the bilateral filter's exponentials.

Three parameters, three jobs:

- `strength` sets `t` (higher wipes harder);
- `detail` lowers `t` again, keeping more texture (Photoshop's Preserve Details);
- `radius` is the search window. Photoshop derives it internally from strength; we expose
  it, because the gap between radius 2 and radius 5 is far larger than between strength 40
  and 50.

With `per-channel` off, `d` is the maximum across channels and **one weight set is shared**.
That detail matters: colour speckle is three independent offsets, so a shared weight
averages all three channels over the same neighbours and the ratios between channels
survive — no greyed-out colour after denoising. With it on, each channel runs its own
weights, which suits monochrome noise.

At `strength=0`, `t=0` and only identical neighbours qualify, so the output is bit-exact.
That is one of the assertions.

## 3. Dust & Scratches: the speck must not elect itself

The idea is one sentence: **replace a pixel that differs too much from its surroundings with
the median of the neighbourhood.** Median rather than mean, because the median is not dragged
by a few extremes — a bright speck becomes a larger grey blot under a mean, and simply
disappears under a median.

But copying "median filter" does not work, for a very concrete reason: **dust is dust
precisely because it differs from everything around it.** Suppose a bright pixel of 0.9 sits
in a flat region of 0.5, with a threshold of 0.1. Every neighbour is rejected for differing
too much, so the candidate set is just the centre pixel — and the median of one value is
that value. The pixel survives untouched. Keeping the centre in the set makes the filter fail
in exactly the case it exists for.

So the set **excludes the centre**. The remaining neighbours are filtered by threshold:

```math
\text{out} = \operatorname{median}\{\,v_k : |v_k - v_0| \le \tau,\; k \ne 0\,\}
```

When nothing qualifies — the middle of a hard edge, where both sides differ a lot — it falls
back to the median of the whole window. The fallback exists because a slight smoothing is
better than a surviving speck: the whole-window median at an edge midpoint still lies on the
edge, while an isolated speck is replaced outright.

At `threshold=0` every difference counts, the set is empty, and everything falls back to the
full-window median — a plain median filter, and quite blurry. Push the threshold past 30 and
only "obviously wrong" pixels move.

## Ordering the three

| Goal | Order |
|---|---|
| Film grain | `add-noise` (monochrome, amount 8), optionally `unsharp-mask` |
| High-ISO cleanup | `reduce-noise` (strength 60, detail 25) then `unsharp-mask` (amount 60) |
| Film scans / hot pixels | `dust-scratches` (radius 1, threshold 12), rest unchanged |
| Ageing | `add-noise` then `reduce-noise`, to make the grain uneven |

**Denoise before sharpening.** The other way round amplifies noise as if it were edges.

## Self-check

`python tools/check_noise_sharpen.py` runs 23 assertions across the three operators:

- amount / strength zero is a bit-exact identity;
- the same seed twice is bit-identical, a different seed differs;
- monochrome mode gives all three channels the same perturbation;
- the mean does not drift after adding noise (within ±3 code values);
- denoising halves the noise standard deviation, leaves the mean alone, and does not move a
  hard edge;
- an isolated bright speck is removed and a flat image is unchanged;
- alpha passes through untouched in all three.

The menu entries sit together under `SuperMrWang → Noise`.
