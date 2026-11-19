---
name: Reduce Noise
blurb: a sigma filter that averages only neighbours close to the centre pixel, so flat areas smooth out and edges stay exactly where they were.
---

`lb:reduce-noise` · menu **SuperMrWang → Noise → Reduce Noise** · one input

Averages only the neighbours that are close to the centre pixel; the ones that
differ a lot — edges, detail — take no part. Flat areas are smoothed, edges
survive untouched. This is a sigma filter (Lee 1983), the family Photoshop's
Reduce Noise belongs to.

## Parameters

| Parameter | Range | Default | Meaning |
|---|---|---|---|
| `strength` | 0–100% | 50 | Threshold t = 22% × strength; larger smooths harder |
| `detail` | 0–100% | 20 | Narrows t by up to 80%, keeping texture |
| `radius` | 1–10 | 2 | Neighbourhood radius; 1 is a 3×3 window |
| `per-channel` | on / off | off | Off: one weight set shared by all channels (colour speckle goes, hues stay). On: each channel on its own |

## Algorithm

For every pixel, over the `(2r+1)²` neighbourhood, the weight comes from the
largest channel difference `d`:

```
w = max(0, 1 − (d / t)²)
out = Σ(w·v) / Σw
```

Neighbours with `d > t` get weight 0, so pixels on the far side of an edge
cannot pull this side over. That is why it does not blur edges — and it needs
no edge detection to do it. The centre pixel has `d = 0` and therefore weight 1.

With `per-channel` off, `d` is the maximum over the three channels and one
weight set is applied to all of them: colour noise averages out while the ratios
between channels stay put, so nothing turns grey. With `strength = 0` the
threshold is 0 and only identical neighbours contribute — the output is the
input.

## Recipes

- **High-ISO cleanup**: `strength=60 detail=25 radius=2 per-channel=on`
- **Colour speckle only**: `strength=80 detail=0 radius=3 per-channel=off`
- **Before frequency separation**: `strength=40 detail=60 radius=2`

## Compared with Photoshop

| | PS Reduce Noise | `lb:reduce-noise` |
|---|---|---|
| Strength / preserve details / per channel | yes | yes |
| Radius | fixed, derived from strength internally | **adjustable** |
| Remove JPEG artifact | yes | no — 8×8 block detection is a different algorithm |
| Sharpen details | yes, as a post-pass | no — follow with `lb:unsharp-mask` |

## Testing

`python tools/check_noise_sharpen.py` — identity at strength 0, noise standard
deviation at least halved, mean not drifting, hard edge untouched, alpha
passthrough.
