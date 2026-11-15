---
name: Hue/Saturation (PS)
blurb: Three sliders from the given Photoshop formula — global hue rotation, relative saturation scaling, lightness mixed toward white or black. No Colorize, no hue ranges.
---

An implementation of Photoshop's Hue/Saturation with the three-slider formula:
global hue rotation, relative saturation scaling, and lightness mixed toward white or
black. No Colorize checkbox and no per-hue ranges.

- GEGL id: `lb:ps-hue-saturation`
- Menu: `Colors → SuperMrWang → Color → Hue/Saturation (PS)`
- Type: `GeglOperationPointFilter` (per-pixel, no neighbourhood)
- Parameters: `hue` (−180…180°), `saturation` (−100…100), `lightness` (−100…100)

The specification lives in `tools/ref_ps_hue_sat.py` (a literal transcription of the
original code plus a float comparison), and the acceptance script is
`tools/check_ps_hue_saturation.py`.

## Algorithm

On **sRGB encoded values** (`R~G~B~A float`, the perceptual domain, not linear
light), in four steps:

```
t = lightness / 100
r,g,b <- c + t·(1−c)   (t > 0)      # screen with neutral grey
         c·(1+t)       (t < 0)      # multiply with neutral grey
h,s,l <- RGB2HSL(r,g,b)
h <- (h + hue) mod 360
x = saturation / 100
s <- s/(1−x)  (x > 0)                # hyperbolic expansion
     s·(1+x)  (x < 0)                # linear contraction
s <- clamp(s, 0, 1)
out = HSL2RGB(h, s, l)
```

The order matters: lightness lands in RGB first, then the result is converted to HSL
for hue and saturation — so saturation acts on the **post-lightness** S, not on the
original one.

## Two differences from the original code

Neither is about what the algorithm means; both are implementation defects:

| Difference | Original | Here | Why |
|---|---|---|---|
| Precision | h rounded to 1°, s/l to 1%, output truncated with `int()` | all float | that quantisation is **1.73 code values** dark on average, **9** at worst (see the breakdown in `tools/ref_ps_hue_sat.py`) |
| `saturation=+100` | `s/(1−1)` → `ZeroDivisionError` | full saturation (when `s>0`) | as `x→1⁻`, `s/(1−x)→+∞`, which clamps to 1 — the left limit |

## Acceptance

```bash
python tools/check_ps_hue_saturation.py     # 27 parameter sets × 4096 colours
python tools/ref_ps_hue_sat.py              # quantisation-error breakdown
python tools/analyze_ps_hue_sat.py          # behaviour checks on the three curves
```

Result: max deviation **0.002 code values** (one 16-bit LSB is 0.0039), i.e. code-exact
against the formula. The script also prints the mean difference from the input, so it
cannot pass by accidentally reading the source image back.

## Is the formula reasonable?

**What holds up**

1. **The lightness slider never touches hue.** Both branches are uniform affine maps
   `c ↦ k·c + b`, and hue depends only on the ratio of channel differences; the measured
   Δh is always 0. It is also monotone, exact at the ends (+100 white, −100 black) and
   never overflows — steadier than editing HSL's L, which slams into white at the top.
2. **Clean endpoints.** −100 lands exactly on neutral grey, +100 on full saturation;
   both directions converge to meaningful colours with no inversion or jump.
3. **The order is intuitive.** Set the tone (lightness) first, then the colour strength
   (saturation), and saturation sees the brightened S — avoiding the classic
   "saturate then brighten and blow out" problem.
4. **No out-of-gamut path.** HSL→RGB keeps the gamut by construction and S is clamped
   to [0,1], so no parameter combination emits an illegal value.

**What does not**

1. **The positive side's scale does not match its label.** The positive multiplier is
   `1/(1−x)`, not `1+x`: `+25` is ×1.33 (+33%), `+50` is ×2 (+100%), `+90` is ×10. Only
   the negative side is an honest percentage (`−50` is ×0.5). The two halves of the
   same slider are on different scales.
2. **The positive side has a cliff and loses detail.** Every pixel with `s ≥ 1−x` clamps
   to 100: at `+50` half of all pixels with S≥50% collapse onto one value, and at `+100`
   every coloured pixel becomes fully saturated — saturation binarisation, in effect.
   It shows up as flat patches and banding.
3. **Lightness affects S very asymmetrically.** `+60` pushes the S of (100,30,10) from
   82% down to 23%, while `−60` leaves it at 82%. You asked for lightness; brightening
   also visibly desaturates and greys the image.
4. **HSL's S is not perceptual.** The same S looks very different on yellow and on blue,
   so one setting behaves differently across hues. Inherent to the HSL model; the
   formula cannot avoid it.
5. **Quantisation loss (original code).** The 1% s/l steps alone cost up to 8 code
   values and −1.25 on average, systematically dark — the price of an 8-bit integer
   implementation, not part of the algorithm.
