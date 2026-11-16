---
name: Mask by Color
blurb: Photoshop's Color Range as a mask operator — colour presets, custom colour, and highlight/shadow/midtone modes calibrated against Photoshop 2025.
---

## Behaviour change (rewritten 2026-11-12)

The old implementation had a fatal bug: with the default `Min Saturation = 0` the
saturation gate degenerated into `smooth_step(s, 0, 0)`, which is 0/0 for a grey
pixel (s = 0) and yields NaN; alpha was written as 0, so **every grey pixel was
judged transparent in every mode** — the white, black and midtone modes were
entirely broken — and `fuzziness = 0` produced NaN too. The match formula (channel
difference plus a negative-start transition band) also made "tolerance" mean
something different in each mode.

The rewritten unified model maps each pixel to a "mismatch" d ∈ [0,1] (0 = exact
match) and sets `alpha = 1 − smoothstep(d, w·(1−feather), w)` with **w =
fuzziness/200** (at fz=200 the window spans the largest possible mismatch:
complementary hues, pure black ↔ pure white):

| Mode | Definition of d |
|---|---|
| red/yellow/green/cyan/blue/magenta | hue-wheel distance (complement = 1), multiplied by the chroma gate (s×v — a near-black pixel's hue is numeric noise) |
| highlights | d = 1 − luminance |
| shadows | d = luminance |
| midtones | d = 2·\|luminance − 0.5\| |
| custom colour | CIELAB ΔE ÷ 100, with ΔE94's lightness weight kL=2 (lightness difference halved) |

- feather (0–100): width of the transition inside the tolerance window's inner
  edge; feather=10 fades over the inner 10% of the window
- Min Saturation: floor on chroma (s×v) for the colour presets, 0 = a fixed floor of 0.25
- Invert (new): inverts the mask, like Photoshop's "Invert" checkbox
- Red Overlay Preview now defaults to off: applying it with preview on bakes the red
  tint into the layer, so turn it off when you are done looking

Sixteen-patch regression: red / yellow / white / black / midtone / custom / invert /
fz0 / fz200 all match the semantics above.

## Highlights / shadows / midtones use a model measured from Photoshop

The unified model above still had a problem: **one "tolerance" slider decided both
the threshold and the softness**, so tightening the range inevitably hardened the
transition — while Photoshop has two independent sliders. That is exactly why it
felt bad to use.

### First, "Color Range cannot be scripted" was a misunderstanding

Two earlier attempts ended with `Photoshop.exe` quitting, and the conclusion was
written down as "Adobe's Color Range is not scriptable". There were two real traps:

1. **ExtendScript's `File` object has no `flush()`.** `say()` called
   `f.writeln(s); f.flush();` — `writeln` had already written the line and `flush`
   threw, so the log never got past line 1 and it looked like PS crashed inside
   `executeAction`. With `open("a") / writeln / close` per line the log runs to the
   end.
2. `executeAction('colorRange', desc, DialogModes.NO)` **always worked** — no dialog,
   no OK button. `DialogModes.ALL` is what hangs the script on a modal dialog.

Photoshop 2026 is blocked by a security policy on this machine (`reg.exe`
blacklist), so **PS 2025 (26.10.0)** is the reference; the two versions behave the
same for Color Range. The driver scripts live in `clrr-cal/`.

### Parameter key names: dig them out of the binary, do not guess

Keys such as `shadowsUpperLimit` can be found by searching `Photoshop.exe`, and the
surrounding strings are the whole schema. The essential ones (which most tutorials
online do not mention):

```
fuzziness / minimum / maximum           for sampled colours
highlightsFuzziness
midtonesFuzziness
shadowsFuzziness                       <- per tone mode, not a shared fuzziness
highlightsLowerLimit
midtonesLowerLimit / midtonesUpperLimit
shadowsUpperLimit
invert / colors(highlights|midtones|shadows|outOfGamut|skinTone)
```

A wrong key **does not raise an error**, it silently does nothing — feeding
`fuzziness` to the shadow mode gave bit-identical output at 0 and 200, which is how
this was found.

### The measured model

- **Luminance is Rec.601 in the gamma domain** (0.299/0.587/0.114), not Lab L\*: at
  limit 100 the 50% crossing lands at luma 100.9, at limit 150 it lands at 149.0.
- **The limit is a hard boundary and tolerance spreads the band by "how much is left
  before the extreme"**:

| Mode | Band |
|---|---|
| shadows | `band = fz·(255 − lim)`, from lim all the way to white |
| highlights | `band = fz·lim`, from lim all the way to black |
| midtones | lower edge `fz·low` (to black), upper edge `fz·(255 − high)` (to white), intersected |

`fz` is Photoshop's 0–100 tolerance (this operator takes 0–200 and halves it
internally), so **tolerance at maximum means the band exactly reaches pure
black/white**, matching how PS feels.

- The curve is not a plain smoothstep: the measured 50% point sits at **0.555** of the
  band (9 parameter sets, 53–58%), while a smoothstep puts it at 0.5 and comes out
  about 10 code values bright in the middle. It is
  `alpha = 1 − smoothstep(t^1.2)`, and 1.2 is the best power over 24 reference
  curves.

### Accuracy (against PS 2025, 0–255 code values)

- Over all 768 sampled points: **mean 2.12 code values**, max 32.3 (on the tail where
  alpha < 20, i.e. the visible difference between "almost nothing selected" and
  "a little selected").
- At integer limit/tolerance settings (fz = 0) the hard boundary is bit-exact.
- Per-pixel recheck with `clrr-cal/verify_op.py`: 35 parameter sets on a 512 px ramp,
  whole-image comparison, mean 1.46 code values.

`tools/check_color_mask_select.py` freezes that reference table into regression
cases (`../clrr-cal/ps_color_range_ref.json`; skipped automatically when absent).

### New parameters

| Parameter | Default | Effect |
|---|---|---|
| `shadows-limit` | 64 | Shadow upper limit (everything below is selected) |
| `highlights-limit` | 192 | Highlight lower limit (everything above is selected) |
| `midtone-low` / `midtone-high` | 64 / 192 | Midtone upper and lower limits |

The defaults were also measured: with no limits passed, Photoshop's 50% crossings
sit at 85.8 for shadows and 167.7 for highlights, which back-solves to limit=64/192
with tolerance 20.

**Feather does not take part in these three modes** — PS's soft edge is decided
entirely by tolerance, and forcing a feather in would break the comparison. The
colour presets and custom colour still use the tolerance-window model (unchanged).
