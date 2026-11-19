---
name: Add Noise
blurb: Gaussian or uniform noise, monochromatic or per channel, with a seed so the grain can be reproduced exactly.
---

`lb:add-noise` · menu **SuperMrWang → Noise → Add Noise** · one input

Random perturbation per pixel — film grain, ageing, or hiding the banding in an
8-bit gradient. Unlike Photoshop, the seed is exposed: same image and same seed
give byte-identical output.

## Parameters

| Parameter | Range | Default | Meaning |
|---|---|---|---|
| `amount` | 0–100% | 10 | Strength. Gaussian: σ = 25% × amount. Uniform: ±50% × amount |
| `distribution` | Gaussian / Uniform | Gaussian | Gaussian looks like film and sensor noise, uniform looks like dithering |
| `monochrome` | on / off | off | One value for all three channels, giving grey grain instead of colour speckle |
| `seed` | 0–999999 | 1 | Drives the sequence, so a look can be reproduced |

## Algorithm

Seeding is **per row**: row `y` gets a seed mixed from `seed` and `y` (hashed,
not added), so processing the image in bands gives exactly the same bytes as
processing it in one go. That is what makes reproducibility hold.

Gaussian noise comes from Box–Muller:

```
u1, u2 ~ U(0,1]
n = sqrt(−2 ln u1) · cos(2π u2)
```

Each channel draws its own `n`; with `monochrome` one draw is shared by all
three. `alpha` is never touched — noise changes pixel values, not opacity.

## Recipes

- **Film grain**: `amount=8 distribution=gaussian monochrome=on`
- **Hide 8-bit banding**: `amount=3 distribution=uniform monochrome=on`, then a 1px blur
- **Ageing**: `amount=15 distribution=gaussian`, balanced with `lb:reduce-noise`

## Compared with Photoshop

| | PS Add Noise | `lb:add-noise` |
|---|---|---|
| Amount / distribution / monochromatic | yes | yes |
| Reproducible | no — a new random sequence every apply | **yes** — same seed, same bytes |
| Touches alpha | no | no |

## Testing

`python tools/check_noise_sharpen.py` — identity at amount 0, same seed identical,
different seed different, three channels equal in monochrome mode, mean unmoved,
alpha passthrough.
