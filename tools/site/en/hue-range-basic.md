---
name: Hue/Saturation Range
blurb: Hue, saturation and lightness inside one hue family with a soft four-handle colour bar — the per-family half of the classic Hue/Saturation dialog. Chain it after Hue/Saturation (Basic) for master + per-family editing, and with Colorize the trio reproduces the whole dialog.
---

## Hue/Saturation Range

A classic Hue/Saturation dialog does three things: master adjustments over the
whole image, per-family adjustments inside soft hue ranges, and colorize. This
project splits that across three operators — **Hue/Saturation (Basic)** covers
the master path, **Colorize** covers colorize, and this op is the missing
per-family half: pick a hue family, adjust hue / saturation / lightness inside
its soft range.

### The four-handle colour bar

Each family has four handles on the hue circle. Pixels between the two inner
handles are selected fully (weight 1); the weight ramps **linearly** from the
inner handles out to the outer two handles; everything beyond is untouched.
The defaults give each family centre ±15° selected and ±45° falloff, so the
six families tile the wheel with overlapping feather:

| Family | Falloff L | Range L | Range R | Falloff R |
|---|---|---|---|---|
| Reds | 315 | 345 | 15 | 45 |
| Yellows | 15 | 45 | 75 | 105 |
| Greens | 75 | 105 | 135 | 165 |
| Cyans | 135 | 165 | 195 | 225 |
| Blues | 195 | 225 | 255 | 285 |
| Magentas | 255 | 285 | 315 | 345 |

A handle value of -1 (the default) follows the family default; dragging it
sets an absolute angle from 0 to 360. Handles may cross 0/360 — the range is
unwrapped around its inner span first.

### Weighted adjustments, same formula as the master op

The weight is computed on the pixel's **original** hue — the range behaves
like an internal mask. Achromatic pixels (R = G = B) join no family, so greys
are never tinted. The four-handle bar weights are piecewise linear:

```math
w(h) = \begin{cases}
0, & h < o_l \ \text{or}\ h > o_r \\[4pt]
1, & i_l \le h \le i_r \\[4pt]
\dfrac{h-o_l}{i_l-o_l}, & o_l \le h < i_l \\[10pt]
\dfrac{o_r-h}{o_r-i_r}, & i_r < h \le o_r
\end{cases}
```

Handles live on the $0..360°$ circle; the range is unwrapped around its inner span
first, so handles dragged across $0/360$ still work. The adjustments then scale by the weight and run through the
exact same formula as Hue/Saturation (Basic): lightness as screen/multiply
toward white/black, hue as a rotation, saturation as a relative scale
(s/(1−x) up, s(1+x) down). At weight 1 the result is bit-identical to the
master op; at weight 0 the pixel passes through untouched.

### Verification

`tools/check_hue_range_basic.py` renders a nine-patch swatch card and compares
every pixel against a line-by-line Python reference of the same maths:
8 cases — default ranges, weight-scaled hue (orange at 30° gets exactly half
the shift of red), saturation driven to full, lightness, wrap-around handles,
the green family, and a chained master → range run — all match to **0.0
codes** across 216 sample points (tolerance 2).
