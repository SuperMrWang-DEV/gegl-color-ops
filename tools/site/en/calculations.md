---
name: Calculations
blurb: the classic editor's Image → Calculations: pull one channel from each of two sources, invert either, blend, and output a grey or alpha mask.
---

`lb:calculations` · menu **Colors → SuperMrWang → Blend → Calculations** · two inputs (input + aux)

Replicates the classic editor's **Image → Calculations**: take one channel from each of two
sources (each optionally inverted), blend them into a greyscale result, and output
it as a grey mask or an alpha mask.

## Parameters

| Parameter | Default | Notes |
|---|---|---|
| `source1-channel` | Luminance | Channel read from the main input: R/G/B/luminance/alpha |
| `invert-source1` | no | Invert source 1 |
| `source2-channel` | Luminance | Channel read from aux |
| `invert-source2` | no | Invert source 2 |
| `blend-mode` | Multiply | 26 modes, matching the classic editor's list |
| `opacity` | 100 | Blend strength |
| `mask-enabled` | no | Use one more channel as a mask |
| `mask-channel` | Luminance | Mask channel |
| `invert-mask` | no | Invert the mask |
| `output-mode` | grey mask | Grey mask (paste into a layer mask) or alpha mask (use directly as opacity) |

## How it maps to the classic editor

| the classic editor | Here |
|---|---|
| Source 1: layer + channel + invert | input + `source1-channel` + `invert-source1` |
| Source 2: layer + channel + invert | aux + `source2-channel` + `invert-source2` |
| Blending / Opacity | `blend-mode` / `opacity` |
| Mask | `mask-channel` + `invert-mask` |
| Result: new document / new channel | `output-mode` = grey mask; the grey layer works as a document or channel |
| Result: selection | `output-mode` = alpha mask, then **Select → Selection from Alpha** |

the classic editor's "Result: selection" cannot be produced straight from a GEGL operator
(operators only return pixels), so an alpha mask stands in for it: use it as the
layer's opacity or convert it to a selection. "New document" is likewise replaced
by a grey mask — copy that layer into a new image and you have a greyscale document.

## Getting a selection or channel by hand

A GEGL op produces pixels and cannot touch selections, channels or layers, so the
Result drop-down of the classic editor's dialog collapses to "grey mask / alpha mask" here.
You can still get the other two without changing code:

1. **Ctrl+Shift+D to duplicate the layer — mandatory.** A GEGL filter rewrites the
   pixels of the layer it runs on, unlike the classic editor's Calculations, so running on a
   copy is what keeps the original intact.
2. On the copy run **Colors → SuperMrWang → Blend → Calculations** with `Output` set
   to **Mask (alpha)**. This step matters: the alpha version writes the grey values
   into the layer's alpha, which is what "alpha → selection" needs; with a grey mask
   the alpha is always 1 and the conversion selects everything.
3. To get the selection, open `Filters → Python-Fu → Console` and paste one line:

   ```python
   img = Gimp.get_images()[0]
   img.select_item(Gimp.ChannelOps.REPLACE, img.get_selected_layers()[0])
   ```

   (`select_item` is exactly "turn an item's alpha into a selection" and accepts
   layers and channels.) For a channel, follow up with **Select → Save to Channel**
   (`gimp-selection-save`).

If you want a finished greyscale layer to use as a document, pick `Mask (grey)` in
step 2 and then "Layer → Duplicate Layer → Paste as New Image".

The Python plug-in in `plugin/blend` turns these steps into Result options in the
dialog (selection / new alpha channel / grey layer / write into layer alpha), but
that plug-in is currently disabled — see "Python plug-in" in the root README.

## Behaviour notes

- **With no aux connected** the second source falls back to the input, i.e. "blend
  two channels of the same image" — the most common use of Calculations (R minus G
  for a mask, for instance) works with a single input.
- Difference-like modes (Difference / Subtract / Divide) are clipped to 0..1 after
  blending, matching 8-bit behaviour.
- Darker / Lighter Color degenerate to Darken / Lighten here: there is only one
  channel, so there is no whole-pixel notion.
- A grey mask outputs alpha = 1; an alpha mask outputs alpha = the grey value.
- **Channel numbering**: enum value 0 is a Composite placeholder
  (`enum_value_skip`, not shown in the drop-down) so that
  `Red/Green/Blue/Luminance/Alpha` line up with `LB_CH_*` in `common/blend.h`.
  Without the placeholder the whole table shifts by one — the default Luminance
  would silently read the blue channel.
- **Transparent pixels of source 2 take no part.** On a cut-out, text layer or any
  layer with a transparent background the holes hold RGB 0, and counting them as
  "black data" computes a solid black mask. Source 2's alpha is used as coverage:
  alpha = 0 gives a 0 mask (not selected) and a soft matte fades proportionally.
  When source 2's channel *is* alpha, that value is data, not coverage, so it is
  not multiplied in again.
- **A source layer smaller than the input or offset**: uncovered pixels take part
  as black (which means 0 in the mask). the classic editor requires both sources to match in
  size; this operator does not, and treats the missing part as black.

## Testing

```bash
./build.sh
python tools/check_blend.py     # includes 9 Calculations cases: multiply to grey, inverted source 2,
                                # alpha mode, all four channel sources, transparent and semi-transparent
                                # source coverage
```
