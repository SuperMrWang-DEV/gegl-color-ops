---
name: Dust & Scratches
blurb: replaces isolated specks with the median of the neighbours that are within the threshold, so dust disappears and real edges stay put.
---

`lb:dust-scratches` · menu **SuperMrWang → Noise → Dust & Scratches** · one input

Replaces pixels that differ too much from their surroundings — dust, scratches,
sensor defects — with the median of the neighbourhood, while leaving real edges
alone. Photoshop's Dust & Scratches, with one deliberate difference explained
below.

## Parameters

| Parameter | Range | Default | Meaning |
|---|---|---|---|
| `radius` | 1–10 | 2 | Neighbourhood radius; 1 is a 3×3 window. Bigger removes bigger specks and loses more detail |
| `threshold` | 0–255 | 0 | Neighbours that differ from the centre by more than this are **excluded** from the median. It is literally "how much of a difference counts as dust" |

## Algorithm

Per pixel, per channel:

1. Collect every neighbour within radius `r` that satisfies
   `|v − v₀| ≤ threshold` — **the centre itself does not count**;
2. take the median of those values;
3. if nothing qualified, fall back to the median of the whole window (again
   without the centre).

A median rather than a mean, because a median is not dragged by a few extreme
values: a bright speck averaged becomes a bigger grey smudge, medianed it simply
disappears.

Keeping the centre out of the set is the crucial difference from plain median
filtering. Dust is dust precisely because it differs from everything around it;
include it and it elects itself, which does nothing. Step 3 covers the middle of
a hard edge, where neither side qualifies: a slight smoothing is preferable to
leaving an isolated pixel behind.

## Recipes

- **Film scanning dust**: `radius=1 threshold=12`
- **Sensor defects**: `radius=2 threshold=30`
- **Small skin blemishes**: `radius=3 threshold=18`, locally only

Radius and threshold pull against each other: at `threshold=0` this is a plain
median filter (and blurs a lot); above roughly 30 it only touches pixels that are
clearly wrong.

## Compared with Photoshop

| | PS Dust & Scratches | `lb:dust-scratches` |
|---|---|---|
| Radius / threshold | yes | yes |
| Centre in the median set | yes (threshold 0 is a plain median) | **no**, so a speck still goes at high thresholds |
| When nothing qualifies | keep the original | fall back to the window median — edges stay sharp, specks do not survive |

## Testing

`python tools/check_noise_sharpen.py` — isolated bright speck removed, hard edge
untouched, uniform image unchanged, alpha passthrough.
