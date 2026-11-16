---
name: Colorize
blurb: the classic editor's Colorize checkbox from Hue/Saturation — input hue and saturation are discarded, only lightness survives.
---

Reproduces the **"Colorize" checkbox** in the classic editor's Hue/Saturation dialog,
calibrated against measurements rather than approximated (the old build used a
fill layer plus an Overlay grey and had nothing to do with the classic editor; it is gone). The
calibration data is in `colorize-cal/RESULTS.md`.

- GEGL id: `lb:colorize-hsl`
- Menu: `Colors → SuperMrWang → Color → Colorize`
- Type: `GeglOperationPointFilter` (per-pixel, no neighbourhood)
- Parameters: `hue` (0…360, absolute hue), `saturation` (0…100, absolute),
  `lightness` (−100…100)

## Algorithm

Take HSL's L on **sRGB encoded values** (`R~G~B~A float`, the perceptual domain, not
linear light), then:

```
t  = lightness / 100
L' = L + t·(1−L)      (t > 0)
L' = L·(1+t)          (t < 0)
out = HSL2RGB(hue, saturation/100, L')
```

That is all. Three findings carry the whole model:

1. **The input pixel's H and S are discarded entirely.** A hue ring with equal L and
   equal S, one full turn around the wheel, comes out with a spread of **0.00 code
   values** inside a single band — the output depends on input L alone.
2. **All three sliders are absolute, not relative.** Hues 0/30/60/120/180/240/300
   land exactly on the hue of the same name; saturations 25/50/75 land on HSL
   S = 0.250/0.500/0.750; lightness 0 leaves `L' = L`.
3. **The lightness slider is linear in L**, moving exactly t/2 at the midpoint L=0.5
   and nothing at either end. Outside 0 and 1 it clamps (l=+100 is white, l=−100 is
   black).

The hue slider **does not wrap**: negative values clamp to 0 (measured −20 gives pure
red, not 340°). The operator handles that explicitly and `value_range` is 0…360.

## Acceptance

`python tools/check_colorize_ps.py` renders the calibration chart through the gegl CLI
and compares it with classic image editor 26.10's 16-bit export, pixel by pixel (in 8-bit code
values):

| Metric | Result |
|---|---|
| Parameter sets | 104 (all lightness steps of 5, saturation steps of 5, hue steps of 20 plus fractional ones, 8 three-slider combinations) |
| Samples | 512×256 each, 13.63 million pixels in total |
| Median | 0.008 code |
| 95th percentile | 0.016 code |
| Max | 0.03 code |

0.03 code is one 16-bit LSB, coming from floating-point truncation on the the classic editor
side rather than model error.

> Note: `tools/contact_sheet.py`'s `read_png` converts 16-bit with `v*255//65535`
> (integer floor), which reads 32895 as 127 instead of 128 and invents a fake 1-code
> deviation. The acceptance script therefore uses the float reader in
> `bc-cal/readpng.py` (`v/257`).

## Difference from `lb:hue-saturation`

`lb:hue-saturation` is the **relative** mode (offset the pixel's own H/S/L, with six
hue ranges adjustable separately), i.e. the classic editor with Colorize unchecked.
`lb:colorize-hsl` is the **absolute** mode: it throws the existing colour away, keeps
only the tonal structure, and turns the whole image into a monochrome tint. They are
complementary, not interchangeable.
