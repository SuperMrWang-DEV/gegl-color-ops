---
name: Levels
blurb: the classic editor's Levels dialog — composite plus R/G/B, five numbers each, 0–255 scale, with the classic editor's gamma direction.
---

A reproduction of the classic editor's **Levels** dialog: **composite plus R/G/B**, four
groups of five numbers each — input black, input grey, input white, output black,
output white — on a 0–255 scale that matches the classic editor's numeric fields one for one.

Panel: `Colors → SuperMrWang → Tone → Levels`.

## Model

Per channel:

```
t   = clamp((v - inLow) / (inHigh - inLow), 0, 1)
t'  = t ^ (1 / gamma)
out = outLow + t' * (outHigh - outLow)
```

- `inLow` and below is crushed to `outLow`, `inHigh` and above to `outHigh`, and the
  middle is redistributed along the gamma curve;
- **gamma > 1 brightens, gamma < 1 darkens** — the same direction as the classic editor's field.
  Note this is the opposite of the usual gamma intuition: the classic editor's slider value goes
  straight into the reciprocal position of `1/gamma`, and writing the exponent as
  `t^gamma` flips the whole direction;
- the input range stretches everything: after setting `inLow = 64`, `v = 240` becomes
  235 rather than staying put;
- when `inHigh == inLow` the range collapses to a point and is handled as a step
  (anything ≥ that value is white) instead of dividing by zero.

Order: **the composite group first (one curve for all three channels), then the
per-channel groups**. Per-channel groups default to identity, so "touch only the
composite" is bit-identical to the classic editor's RGB mode and "touch only red" matches the classic editor's Red
channel mode. All four groups can be stacked, which is more than the classic editor allows (one
channel at a time).

## Domain

Everything is computed per channel in the **8-bit sRGB gamma domain**, never decoded
to linear. Levels' black and white points mean "0–255 encoded values", and feeding
linear light would make the numeric fields disagree with the classic editor. The operator pins both
pads to a perceptual format (`R~G~B~A float`) in `prepare`, so no upstream
`linear-rgb` is needed.

## Verification

```bash
python tools/check_levels_ps.py
```

11 cases on two levels:

**A — mathematics.** A Python mirror of the C model, compared pixel by pixel on a
256-column greyscale probe (column x is exactly grey x, so no interpolation), all
0.00 code values:

| Case | Check |
|---|---|
| all defaults | 0 / 20 / 128 / 240 / 255 identity |
| input black 64 | crush, mid and high end stretched to 235 |
| input white 192 | full white, low end stretched to 27 |
| output 50–200 | ends land on 50 / 200, middle stays linear |
| gamma 2.0 / 0.5 | brighter / darker, endpoints fixed |
| combination | 50 / 0.7 / 200 → 30 / 220 |
| single channel | red only, green and blue untouched |

**B — reference points.** Two published the classic editor measurements, specifically to pin down
gamma's **direction and exponent form**:

| Input | gamma | the classic editor | This operator | Deviation |
|---|---|---|---|---|
| 154 | 0.46 | 84 | 85 | 1.19 code |
| 200 | 1.646 | 220 | 220 | 0.01 code |

These matter: a test that only checks "C agrees with Python" cannot catch a reversed
exponent, because both sides would be wrong together. The values come from a
measured pixel posted in the vendor's community and the accepted `out = in^(1/gamma)`.

## Why there is no per-code calibration on this machine

On this machine, the classic editor 2025 (26.10.0) throws "could not complete the command
because of a program error" for both the `Lvls` `executeAction` event and `Mk`
adjustment-layer creation, and the DOM's `LayerKind.LEVELS` only offers
text-or-normal. The diagnostic log is in `../lvls-cal/_diag2.txt`. `colorRange` does
run, so ExtendScript as a whole is fine — those two commands are blocked in this
installation.

Hence the reference is public measurements rather than local calibration. **If you
can run the classic editor scripts on another machine, fix `ps_levels.jsx` in `lvls-cal/` and re-run
it, and this can be upgraded to a per-code calibration.**

## Difference from GIMP's own Levels

GIMP's `Colors → Levels` is a private app-level implementation, and GEGL's
`gegl:levels` has only **four** properties — `in-low / in-high / out-low / out-high` —
with no gamma, no per-channel groups and no 0–255 scale (check `gegl --info
gegl:levels`). This operator fills a genuine hole at the GEGL level: the classic editor levels
parameters now work from scripts, batch jobs and the `gegl` command line.
