---
name: Vibrance (Lab)
blurb: An appearance-based vibrance in Lab — hyperbolic chroma mask, skin-tone protection and gamut mapping that never shifts hue.
---

## Algorithm (rewritten 2026-11)

Everything happens in LAB (D65) on linear sRGB, following the input colour space
automatically.

**Mask structure** `M = M_chroma(C*) × M_skin(h) × M_gamut`

- `M_chroma = 1/(1 + atten·(C*/50)^1.3)`: reads the **source** chroma C\*, so the
  higher the chroma the lower the gain; the exponent 1.3 makes C\*>60 fall off faster
  than a plain hyperbola. Independent of the Saturation slider.
- `M_skin`: reduces the weight around LAB hue 55° (orange and skin tones) with chroma
  8–80, using a smoothstep window so the boundary has no hard edge. Strength is set by
  `Skin Protection` (default 0.7); 0 disables it.
- `M_gamut`: after chroma is scaled at the **original hue and lightness**, anything
  outside sRGB is pulled back by a five-step bisection to the largest value inside the
  gamut. Hue and lightness never change, which replaces per-channel clipping (clipping
  twists hue).

The `vibrance` slider (±50 in the UI) is equivalent to at most ×2 at +50 and ×3 at
+100 for low-chroma C\*; the global `Saturation` is a separate linear chroma multiply
that ignores the mask.

Measured (10 standard patches, vibrance=+50): hue shift ≤ 0.7° (the old build reached
10.2°); skin tones gain 1.16–1.18× (old build 1.47–1.55×); low-chroma areas 1.76–2.00×.
At vibrance=0 and saturation=1 the output is byte-identical to the input.

## Relation to `lb:vibrance`

`lb:vibrance` is the numerical reproduction of Photoshop's Vibrance — match the
numbers, no artistic controls. This one is an appearance model: the parameters mean
something (chroma ceiling, skin protection, gamut handling) and the result looks good,
but it will not agree with Photoshop code for code. Use this when you want control,
that one when you want PS to agree.
