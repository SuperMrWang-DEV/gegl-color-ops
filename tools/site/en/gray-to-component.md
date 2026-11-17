---
name: Gray to Component
blurb: The encoder behind HSV/LCh Split (Curves): turns a component grey layer into the colour layer a blend mode can read, in one filter instead of three curves.
---

The **encoder** of the channel-grey grading workflow: take a decomposed component
grey layer and re-encode it into a colour layer "carrying" that component, so GIMP's
component blend modes can read it back.

It is the last step of the `HSV Split (Curves)` / `LCh Split (Curves)` plugins: one
filter replaces the old "scale + three `gimp:curves`" stack, so each component layer
is just **extract → curve → encode**.

```
image ──decompose──> component grey layer (H / S / L / C …)
                          │
                          ▼
                  lb:gray-to-component   <- this operator: grey -> colour form
                          │
                          ▼
        restore with a blend mode (GIMP's nine "Color" group modes + Lighten)
```

Why the step is needed: **a grey pixel has no defined hue or saturation.** Putting a
decomposed H grey layer into Hue blend mode does nothing — the mode cannot read a hue
out of grey. It first has to be encoded into a real colour on the wheel. GIMP has the
decomposition and the blend modes; the middle step was missing, and this operator is
it.

## What the input is

The grey layer's **pixel value is the component value** (`component-extract` output is
exactly that kind of layer): 0.5 in a `hue` layer means 180°, 0.5 in `lab-l` means
L* = 50. The operator takes the R channel as g and passes alpha straight through.

`input-space` says which domain those pixel values live in:

| Value | Used for | Stack buffer format |
|---|---|---|
| `encoded` (default) | 8/16-bit layers | `R'G'B'A float` |
| `linear` | 32-bit float linear images | `RGBA float` |

Getting it wrong makes babl insert one extra gamma step and the encoded values come
out too bright — the old version always declared `YA float` (reading the value as
linear luminance), which is why round trips were off by 83–255 code values on 8-bit
images.

## Mode table (encoding formulas calibrated by identity round trips in hsl-cal)

GIMP 3 collects component blend modes in the "Color" group, nine of them: **Hue /
Saturation / Color / Value / LCh Hue / LCh Chroma / LCh Color / LCh Lightness /
Luminance**. This operator feeds each of them, plus three single-channel RGB modes.

| Mode | Meaning of grey g | Output encoding | Blend mode to restore |
|---|---|---|---|
| `hue` | HSL hue h/360 | `hsl_to_rgb(g·360°, S=1, L=0.5)`, a hue wheel at full saturation and mid lightness | **Hue** (HSV_HUE) |
| `saturation` | HSV saturation s | `hsv_to_rgb(sat_hue, s, V=1)`, red hue by default | **Saturation** (HSV_SATURATION) |
| `color` | HSL hue h/360 | `hsl_to_rgb(g·360°, color_sat, L=0.5)`, saturation fixed by a parameter | **Color** (HSL_COLOR) |
| `value` | HSV value V | `(g,g,g)` neutral grey (V *is* the max channel) | **Value** (HSV_VALUE) |
| `lightness` | CIE lightness L/100 | `Lab(g·100, 0, 0)` written directly | **LCh Lightness** (LCH_LIGHTNESS) |
| `luminance` | same (CIE luminance Y) | byte-identical to `lightness` | **Luminance** (LUMINANCE) |
| `red` / `green` / `blue` | that channel's value | `(g,0,0)` / `(0,g,0)` / `(0,0,g)` | **Lighten**, three layers |
| `lch-hue` | CIE hue h/360 | `Lab(lch_l, C·cos h, C·sin h)`, C = `lch_c` | **LCh Hue** (LCH_HUE) |
| `lch-color` | same (h, C fixed by parameter) | byte-identical to `lch-hue` | **LCh Color** (LCH_COLOR) |
| `lch-chroma` | CIE chroma C/chroma_scale | `Lab(lch_l, C·cos h₀, C·sin h₀)`, h₀ = `lch_h` | **LCh Chroma** (LCH_CHROMA) |

The two "same encoding" pairs are not laziness, they follow from what the blend modes
read:

- **`luminance` ≡ `lightness`**: Luminance reads CIE Y, and a neutral grey's Lab L maps
  monotonically to Y, so one `Lab(L,0,0)` gives both correctly.
- **`lch-color` ≡ `lch-hue`**: LCh Color reads hue and chroma only, and `lch-hue`'s
  chroma is already fixed by `lch-c`. The separate entry exists so you can match
  GIMP's mode names.

The table as formulas ($g$ is the input grey; $c_s$, $L_0$, $C$, $h_0$ are parameters):

```math
\begin{aligned}
\text{hue}:\quad & \operatorname{HSL2RGB}(360°g,\ 1,\ \tfrac{1}{2}) \\
\text{saturation}:\quad & \operatorname{HSV2RGB}(h_{\text{sat}},\ g,\ 1) \\
\text{color}:\quad & \operatorname{HSL2RGB}(360°g,\ c_s,\ \tfrac{1}{2}) \\
\text{value}:\quad & (g,\ g,\ g) \\
\text{lightness} \equiv \text{luminance}:\quad & \operatorname{Lab}(100g,\ 0,\ 0) \\
\text{lch-hue} \equiv \text{lch-color}:\quad & \operatorname{Lab}\bigl(L_0,\ C\cos 360°g,\ C\sin 360°g\bigr) \\
\text{lch-chroma}:\quad & \operatorname{Lab}\bigl(L_0,\ C\cos h_0,\ C\sin h_0\bigr) \\
\text{red/green/blue}:\quad & (g,0,0)\ /\ (0,g,0)\ /\ (0,0,g)
\end{aligned}
```

**The single-channel problem with Color**: Color mode reads hue and saturation
together, but one grey layer holds a single scalar. The trade-off here is "grey carries
hue, saturation comes from `color-sat`" — to recolour and desaturate at once, set
`color-sat` to 45%, simpler than hue first and a desaturating layer on top.

Three hard, calibrated conclusions (measured in hsl-cal, error in 0–255):

1. **HSL's S ≠ HSV's S.** GIMP's Saturation mode reads HSV semantics; encoding an HSL
   S layer directly is off by up to 214/255. This operator's `saturation` mode encodes
   with HSV semantics, and the identity round trip is < 2.
2. **HSL hue and CIE hue do not convert linearly.** Using `h·360` directly as an LCh
   hue is off by 139/255. The two wheels must be decomposed and encoded separately —
   which is why `hue` and `lch-hue` cannot be merged.
3. **The encoding layer must run at float32.** In 8-bit, Lab/LCh encodings written
   into the layer get quantised and hue/chroma break up (an inherent precision limit of
   the whole workflow on 8-bit images); at float32 even LCh values outside sRGB round
   trip exactly.

## Parameters

| Parameter | Default | Notes |
|---|---|---|
| `mode` | `hue` | See the table above |
| `sat-hue` | 0 (red) | Hue used by `saturation`. That layer only supplies saturation, so the value does not reach the final picture |
| `color-sat` | 100 | Saturation percentage fixed by `color`. At 100% the output equals `hue`; lower it for "recolour + desaturate" |
| `lch-l` | 54 | Fixed lightness for the LCh modes. When the blend mode reads only hue/chroma this value does not reach the result; a middling value keeps it inside the common gamut |
| `lch-c` | 30 | Fixed chroma for `lch-hue` / `lch-color`. Higher is more vivid; too high leaves sRGB |
| `lch-h` | 30 | Fixed hue angle for `lch-chroma` (0 = red); likewise does not reach the result |
| `chroma-scale` | 100 | Full range of `lch-chroma` (how much chroma grey 1.0 means). `component-extract` normalises C to 200 (`lch-c` = C/200), so feed decomposition output with **200**; keep 100 when building grey layers by hand |

## Typical uses

**Rotate hue** (keeping tone and saturation):

1. Duplicate the layer → `lb:gray-to-component` with mode `hue`, fed by the hue
   decomposition;
2. set that layer's blend mode to **Hue**;
3. run levels/curves/invert on the grey layer — the hue follows, and every fold and
   shadow stays.

**Saturation only**: same, mode `saturation` with **Saturation**.

**Recolour and desaturate at once**: mode `color` with **Color**, `color-sat` at
40–60%. One layer swaps hue and saturation together; lightness stays the original's.

**HSV value only**: mode `value` with **Value** — the output is neutral grey, Value
reads the max channel, and a curve on the grey edits brightness directly.

**Lab-space grading** (lightness untouched): `lch-chroma` + **LCh Chroma** changes
vividness only; `lch-hue` + **LCh Hue** rotates hue only; `lch-color` + **LCh Color**
pins chroma to `lch-c` as well.

**RGB channel recomposition**: one layer each of `red`/`green`/`blue`, all in
**Lighten**, stacked bottom-up — `max((r,0,0),(0,g,0),(0,0,b))` restores exactly
`(r,g,b)`.

## Verification

`tools/check_gray_to_component.py` (39 cases, run in gimp-console):

- **A. Encoding formulas**: a 17-step grey ramp through the operator; Lab-domain modes
  (including the `luminance` / `lch-color` aliases) compared against the Lab output
  directly, RGB-domain modes against mirrored HSL/HSV formulas with `color-sat` at 100
  and 40 and `sat-hue` at 0 and 210, confirming the parameters really reach the maths,
  plus endpoint semantics (hue 0 = red / 0.5 = cyan), value (0 = black / 1 = white /
  neutral), `color-sat=0` degenerating to grey, and both alias pairs agreeing
  component-wise.
- **B. Identity round trips** (the gold standard, same method as hsl-cal): 24 probe
  colours through decompose → encode → blend, compared per pixel with the original,
  **all ≤ 2/255**: hue→Hue, saturation→Saturation, value→Value, lightness→LCh
  Lightness, luminance→Luminance, lch-hue→LCh Hue, lch-chroma→LCh Chroma (ranges 100
  and 132), the three RGB channels→Lighten, and hue+saturation in series. Color / LCh
  Color are two-component modes whose identity needs the underlying
  saturation/chroma to match the parameters, so each gets dedicated probes: Color with
  S=100% and S=60% rings, LCh Color with a C=30 LCh ring.
- **Transparent pixels**: a 32×8 checkerboard (85/256 fully transparent), alpha
  compared per pixel; transparent areas must be Lab 0.

## Technical notes

- The output format is pinned to `CIE Lab alpha float`: the Lab/LCh modes write
  straight through with zero conversion (a=C·cos h, b=C·sin h *is* the definition of
  CIE LCh), while the HSL/RGB modes use `babl_fish` to convert each row to Lab, the
  same conversion GIMP uses internally, so no hand-written conversion drift creeps in.
- **Transparent pixels in the RGB-domain modes must be placed in `rgb_line`**: handing
  a whole row to `babl_process` rewrites every pixel of `out_line`, so writing 0 only
  into `out_line` got overwritten by the intermediate row (uninitialised), leaving
  random alpha on transparent pixels. An earlier 2×1 case passed only because the heap
  happened to be zero; a 32×8 checkerboard exposed it. Fixed.
- No aux pad, so it can sit on a grey layer as a GIMP 3 non-destructive filter (it is
  not blocked by `Gimp.DrawableFilter`'s refusal of aux operators), making the whole
  workflow non-destructive.
- Transparent pixels (alpha ≤ 0) stay transparent.
- The input pad is `R'G'B'A float` (or `RGBA float` with `input-space=linear`), the
  same domain as the upstream buffer, so babl never re-gammas the component value.
