---
name: Exposure EV
blurb: the classic editor's Exposure adjustment with two formulas — 8-bit sRGB and 32-bit linear — chosen automatically from the input precision.
---

Menu: `Colors → SuperMrWang → Tone → Exposure EV`

## Two formulas, picked from the input precision

`precision` property: `auto` (default) / `encoded` (force the 8-bit path) /
`linear` (force the 32-bit path). `auto` reads the source format of the input pad:
integer formats (`u8` / `u16`) take branch one, float formats (`float` / `half` /
`double`) take branch two. 16-bit images are gamma-encoded as well, so they share
branch one with 8-bit.

### Branch one: integer formats (sRGB gamma-encoded values)

```
v1 = min(c · 2^(EV/2.2), 1)
v2 = clamp(v1^2.2 + offset, 0, 1)^(1/2.2)
v3 = v2^(1/gamma)
```

Multiplying by `2^(EV/2.2)` in the gamma domain is exactly equivalent to multiplying
by `2^EV` in linear light and saves two exponentiations; `offset` is a linear-light
quantity, hence the single decode to 2.2 in the middle and the re-encode afterwards.

**The `min(…, 1)` cannot be dropped.** Highlights are clipped first and the offset is
added afterwards, which is what lets a negative offset pull blown highlights back.
Skip it and `EV>0` with a negative offset pushes the whole bright region to solid
white. The old implementation was missing this line.

### Branch two: float formats (linear light)

```
v1 = c · 2^EV + offset
v2 = clamp(v1, 0, ∞)^(1/gamma)
```

The input is already linear, so there is no 2.2 round trip; exposure is one multiply
and the offset is added directly.

**One difference from the Java version**: Java ends with `clamp(…, 0, 1)`, this
operator only clamps the lower bound. 32-bit images allow HDR, and truncating to 0…1
would flatten the highlights; negative values must be clamped or `pow` returns NaN.

## Acceptance

```bash
python tools/check_exposure.py
```

12 parameter sets (EV −3…+2, offset ±0.15, gamma 0.45…2.2) × 64 grey levels:

- branch one against Java's `exposureChannel`: max **0.00 code values**
- branch two against Java's `exposureChannel2`: max **0.00 code values**
- with an integer PNG, `auto` and `encoded` are pixel-identical (0 differences)
- with a float EXR, `auto` and `linear` are identical and differ from `encoded` on
  2944 pixels — proof that `auto` really switches branches rather than adding an
  inert switch
