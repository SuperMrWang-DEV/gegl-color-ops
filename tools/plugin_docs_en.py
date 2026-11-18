# -*- coding: utf-8 -*-
"""插件的英文正文（lede + body）。

中文正文在 plugin_docs.PAGES 里，这里是它的英文对照。分开放的原因是正文是
大段手写 HTML，混在一个 dict 里会难以维护；plugin_docs 末尾会把这里的内容注进
PAGES 的 lede_en / body_en，模板按语言取用。
"""

PLUGIN_EN = {}

PLUGIN_EN["selection"] = dict(
    lede="""Right-click a layer and it becomes the current selection. What a GEGL operator
   leaves behind is usually a greyscale image whose next job is to be a mask — the native
   route takes four steps (duplicate → channel → paste → channel to selection), this takes
   one, and colour layers work directly.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What gets converted</h3><span class="pill">five channels</span></div>
      <p>Pick <b>Gray (luminance) / R / G / B / Alpha</b>. On a colour layer Gray means
         luminance, not HSL lightness — pure red reads ≈ 54/255, not 130. Black-and-white
         layers take a zero-copy channel-slice path that never touches a pixel.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Merging into the current selection</h3></div>
      <p><b>Replace / add / subtract / intersect</b> — the same four the Select menu
         offers — plus invert, to take the shadows instead of the highlights. An existing
         selection is not thrown away; it is combined the way you asked.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Offset layers</h3></div>
      <p>A layer smaller than the canvas, with an offset, is fine: the selection lands only
         where the layer sits and nothing outside it is selected. Layer groups have no
         pixels of their own, so the plug-in stops with an explicit error asking you to
         merge first.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Two GIMP 3 traps</h3><span class="pill">worked around</span></div>
      <p><b>1. A temporary channel gets clipped by the selection.</b> The shadow buffer's
         merge respects the active selection, so the selection is suspended with
         <code>Selection.none</code> before the temporary channel is written and restored
         afterwards — otherwise only the selected area carries data.</p>
      <p><b>2. <code>Y' float</code> is not luminance.</b> babl's Y' returns 0.51 for pure
         red, which is HSL lightness, not luminance. So Gray on a colour layer goes through
         a temporary copy with <code>desaturate</code> (LUMA), deleted as soon as it is
         done.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p><code>tools/check_layer_to_mask.py</code> runs 23 assertions inside a real GIMP
         3.2: grey values, invert, offset layers, colour luminance, the four single
         channels, the four combine modes, and that the result is not clipped while a
         selection is active.</p>
      <p>Speed: it reads array slices at C level — about 4 ms for one megapixel.</p>
    </div>
  </div>""")

PLUGIN_EN["channel"] = dict(
    lede="""Right-click a layer and it becomes a new alpha channel you can keep around. Always
   greyscale: black = not selected, white = fully selected, mid grey = partly selected. To
   use it as a mask, right-click it in the Channels tab and pick "Channel to Selection"
   (native GIMP), then come back to the layer.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Always greyscale</h3><span class="pill">unambiguous</span></div>
      <p>A colour layer is converted to luminance first, a black-and-white layer goes in as
         it is, and those grey values become the channel. There is no "take the R channel"
         option: the point is light and dark, without a single-colour channel getting in
         the way.</p>
      <p>The channel value <em>is</em> whether the pixel is selected:</p>
      <pre><code>black 0    → not selected
mid grey   → partly selected
white 255  → fully selected</code></pre>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Name and invert</h3></div>
      <p>The channel takes the layer's name by default and you can change it, so it is
         recognisable in the Channels tab. It can be inverted, and the status bar shows the
         channel name once it is created.</p>
      <p>To turn it back into a selection: right-click the channel → Channel to Selection
         (native GIMP), or go the other way and use Layer to Selection straight from the
         layer.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why copy-paste is not enough</h3></div>
      <p>Copy-paste can put grey into a channel, but it carries display effects such as layer
         masks along, and you still have to create the channel first and then paste as a
         selection — four steps. This reads the raw pixels: one step, and faster.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Measured</h3><span class="pill">23 assertions</span></div>
      <p><code>tools/check_layer_to_mask.py</code>: channel values, name, invert, colour
         layer to channel equals luminance, semi-transparent images weighted by alpha, and
         that the channel is not clipped by an active selection (the selection is suspended
         before the write and restored after).</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>It replaces gray-mask</h3></div>
      <p>The old <code>plugin/gray-mask</code> went through copy-paste and carried masks and
         layer modes, but it skipped luma conversion for colour layers and ignored offsets.
         Retired on 2026-11-18. These two read raw pixels — faster, and now the only way
         to convert.</p>
    </div>
  </div>""")

PLUGIN_EN["split"] = dict(
    lede="""One layer becomes several channels in a single step: R, G, B and Alpha each get
   their own channel, lined up in the Channels dock, with the source layer hidden so you
   can still compare. The native route is channel-by-channel "new channel → copy → paste →
   merge" — sixteen steps for four channels.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>All four at once</h3><span class="pill">R · G · B · Alpha</span></div>
      <p>Each component becomes its own channel named "layer + suffix", so the Channels
         dock stays readable. A name that is already taken gets a number instead of
         overwriting what you stored earlier.</p>
      <pre><code>layer "photo"
  ├ photo R       red
  ├ photo G       green
  ├ photo B       blue
  └ photo Alpha   transparency</code></pre>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Grayscale images do not fake three</h3></div>
      <p>On a greyscale image R = G = B, so three channels would be three identical
         copies — it produces a single <b>Gray</b> channel instead, plus Alpha when the
         layer actually has transparency. Colour layers give four by default; turn
         "Include Alpha" off for three.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>The source layer hides itself</h3></div>
      <p>It is hidden, never deleted: the canvas shows you the split result and one click
         brings the original back. Turn "Hide source layer" off if you want both.</p>
      <p>Small offset layers work too: channels are always <b>canvas-sized</b> and the area
         the layer does not cover stays black, so nothing lands at the wrong place.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Versus Layer to Channel</h3><span class="pill">one vs many</span></div>
      <p><b>Layer to Channel</b> flattens the whole layer into <b>one</b> greyscale channel
         (always luminance) — for "keep this greyscale image as a mask". <b>Split
         Channels</b> keeps the <b>components themselves</b> and produces several — for
         "look at the R/G/B distributions separately" or "retouch one channel only". Both
         leave their results in the Channels dock and can coexist.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p><code>tools/check_split_channels.py</code> runs 31 assertions inside a real GIMP
         3.2: each channel equals the same component of the source layer (an off-by-one
         index shows up immediately), greyscale yields Gray only, no-alpha layers yield
         three, offset layers are padded with black, the channel is not clipped by an
         active selection, and prefix plus duplicate numbering behave.</p>
      <p>Speed: four channels from six megapixels take about 0.9 s — the layer is read once
         and then sliced, not read once per channel.</p>
    </div>
  </div>""")

PLUGIN_EN["hsv"] = dict(
    lede="""GIMP's curves only offer R / G / B / Alpha — there is no way to curve hue or
   saturation on its own. This plug-in turns the layer into a data image (red = S, green = V,
   blue = hue), gives each component its own curve, and one operator turns it back: at
   identity the original is restored pixel for pixel, and moving a curve moves only that
   component. Pick the <b>· multi</b> menu entry if you want the old "every layer switchable"
   layout.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Two modes</h3><span class="pill">two menu entries</span></div>
      <p>The menu holds two separate procedures — <code>… · single</code> and
         <code>… · multi</code> — and the one you click is the mode you get. The dialog has a
         single switch left: put everything in a layer group.</p>
      <pre><code>single  HSV split group · pass-through (plus a mask when there is alpha)
 └─ 1 · HSV S/V/H mode  Normal  ← one operator chain computes the whole HSV colour

multi   HSV split group · pass-through (plus a mask when there is alpha)
 ├─ 3 · Value mode       HSV value
 ├─ 2 · Saturation mode  HSV saturation
 └─ 1 · Hue mode         HSV hue</code></pre>
      <p>The single stack is: decompose (<code>lb:hsv-dual</code>) → S curve (red) →
         V curve (green) → H curve (blue) → compose (<code>lb:hsv-compose</code>). Each
         component owns one channel and none of them leaks into another.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>single or multi</h3></div>
      <p><b>single</b> sends S, V and H into <code>lb:hsv-compose</code> together: one layer,
         five filters, one encode, the smallest error.</p>
      <p><b>multi</b> is three component layers, each doing extract → curve → encode, stacked
         back with HSV's three component blend modes. Three layers means three encodes and
         three quantisations; what you buy is being able to switch any layer off — turn off
         the Hue layer and you see the intermediate result with only S/V changed, which makes
         it obvious what you are editing.</p>
      <p>Both modes use smooth splines for the identity curve (SMOOTH, three control points
         at (0,0), (128,128), (255,255)). All three sit on the 8-bit grid, so the spline is
         numerically identical to "256 sample points" — see the round-trip figures
         below.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Measured precision</h3></div>
      <p><b>single</b>: identity round trip 0.0002 codes on a 32-bit float image; 0.49 codes
         on 8-bit, which is the quantisation itself. Moving only the S curve leaves V and hue
         within <b>&lt; 0.001 codes</b> — the three components really are independent.</p>
      <p><b>multi</b>: the three-layer identity round trip measures 0.0015 codes in float,
         and it still stacks back with the original layer hidden. That is seven times the
         single figure — the leftover from three encode passes — but still in the
         thousandths of a code, invisible to the eye. In 8-bit both modes land on 0.49 codes
         where quantisation dominates. So single is more accurate; multi trades that for
         per-layer switches.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Watch out</h3></div>
      <p>The channel convention is hard: S in red, V in green, hue in blue. Pick the wrong
         channel for a curve and you feed one component's data into another. The hue curve
         must stay continuous (equal at both ends, no jumps in the middle); for a global hue
         rotation use <code>lb:hue-saturation</code>.</p>
      <p><code>single</code> depends on <code>lb:hsv-dual</code> /
         <code>lb:hsv-compose</code>; <code>multi</code> uses only GIMP's own
         <code>gegl:component-extract</code> and the HSV component blend modes.</p>
    </div>
  </div>""")

PLUGIN_EN["lch"] = dict(
    lede="""The same idea in CIE LCh: three curves for lightness, chroma and hue. LCh is Lab in
   polar form — a and b are rectangular, so a 1D curve on one of them drags chroma and hue
   along. In (L, C, h) you can move chroma without touching hue, and hue without touching
   chroma.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Two modes</h3><span class="pill">two menu entries</span></div>
      <p>The menu holds two separate procedures — <code>… · single</code> and
         <code>… · multi</code> — and the one you click is the mode you get. The dialog has a
         single switch left: put everything in a layer group.</p>
      <pre><code>single  LCh split group · pass-through (plus a mask when there is alpha)
 └─ 1 · LCh L/C/h mode  Normal  ← one operator chain computes the whole LCh colour

multi   LCh split group · pass-through (plus a mask when there is alpha)
 ├─ 3 · Lightness mode  LCh lightness
 ├─ 2 · Chroma mode     LCh chroma
 └─ 1 · Hue mode        LCh hue</code></pre>
      <p>The single stack is: decompose (<code>lb:lch-dual</code>) → L curve (red) →
         C curve (green) → h curve (blue) → compose (<code>lb:lch-compose</code>).</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Ranges</h3></div>
      <p>The conversion is babl's <code>CIE LCH(ab) alpha float</code> (D50), the same one
         <code>lb:lch-levels</code> uses. In the data image: L* 0…100 → L/100, C* 0…140 →
         C/140 (the most saturated sRGB blue is about 133.8, so there is headroom), and
         h 0…360° → h/360.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>single or multi</h3></div>
      <p><b>multi</b> uses GIMP's three native LCh component blend modes, which forces every
         layer to <em>encode</em> its component as a colour the mode can read — the hue layer
         has to fake a ring of constant L* and C* (L*=70, C*=39.8, the whole circle inside
         sRGB), the chroma layer goes along the black→blue line. Three layers, three encodes,
         three quantisations, but every layer switches off on its own.</p>
      <p><b>single</b> sends all three components into compose, so none of that encoding is
         needed and hue can no longer be dragged off by per-layer quantisation. Three layers
         become one, fourteen filters become five.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p>Float identity round trip 0.0005 codes (multi with three layers: 0.002 codes),
         0.49 codes in 8-bit — single is more accurate, multi trades that for the switches.
         This plug-in additionally has to cross the hue and chroma encoding tables, but the
         curves themselves sit on grid points and add nothing.</p>
      <p>Editing only the C curve leaves L* and hue at the 0.00001-code level. Extreme chroma
         or hue leaves sRGB and 8-bit output clips at 0/1 — LCh's gamut is simply larger. Hue
         near neutral (C*≈0) is noise, but composition is unaffected. Depends on
         <code>lb:lch-dual</code> / <code>lb:lch-compose</code>.</p>
    </div>
  </div>""")

PLUGIN_EN["hsl"] = dict(
    lede="""GIMP ships component blend modes for HSV and LCh but not for HSL, and there is no
   HSL hue entry point either. This plug-in does not approximate HSL with HSV: it converts
   exactly, packs the three components into one data image and gives each its own curve.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Two modes</h3><span class="pill">two menu entries</span></div>
      <p>The menu holds two separate procedures — <code>… · single</code> and
         <code>… · multi</code> — and the one you click is the mode you get. The dialog has a
         single switch left: put everything in a layer group.</p>
      <pre><code>single  HSL split group · pass-through (plus a mask when there is alpha)
 └─ 1 · HSL S/L/H mode  Normal  ← one operator chain computes the whole HSL colour

multi   HSL split group · pass-through (plus a mask when there is alpha)
 ├─ 2 · Hue mode      HSV hue  ← replaces H only
 └─ 1 · S / L mode    Normal   ← computes S, L and hue</code></pre>
      <p>The single stack is: decompose (<code>lb:hsl-dual</code>) → S curve (red) →
         L curve (green) → H curve (blue) → compose (<code>lb:hsl-compose</code>).</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>single or multi</h3></div>
      <p>S and L are coupled: C = (1−|2L−1|)·S, V = L + C/2, S_hsv = C/V. Converting back to
         HSV's S/V exactly means the encoder must read both at once — which is why they share
         one image in both modes.</p>
      <p><b>multi</b> puts one more Hue layer on top, borrowing HSV's hue mode (HSL and HSV
         hue angles are identical) while S and L pass through. Switching the Hue layer's eye
         off shows you "original hue plus the S/L you just edited".</p>
      <p><b>single</b> folds hue into compose and needs one layer only: one layer less, one
         quantisation less, at the cost of that per-layer switch.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>L is not V</h3></div>
      <p>Using HSL's L as HSV's V is off by a lot: 25 codes at S=0.25, 64 codes at S=1
         (exactly C/2). This plug-in computes the real conversion inside compose instead of
         approximating it.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p>Float identity round trip 0.0001 codes (multi with two layers: 0.0014 codes),
         0.49 codes in 8-bit — single is more accurate, multi trades that for the switches.
         Editing only the S curve leaves L and hue within <b>&lt; 0.001 codes</b>.</p>
      <p>The conversion is babl's <code>HSLA float</code>, the same one
         <code>component-extract</code>'s <code>hsl-s</code> / <code>hsl-l</code> uses.
         Depends on <code>lb:hsl-dual</code> / <code>lb:hsl-compose</code>.</p>
    </div>
  </div>""")

PLUGIN_EN["lab"] = dict(
    lede="""Curves in CIELAB: L* is perceptual lightness, a runs green–magenta, b runs blue–yellow.
   "Pull b down when it is too yellow, push a up when it is too green" is far more direct than
   pulling RGB curves. The three components are packed into one data image, one channel each.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Two modes</h3><span class="pill">two menu entries</span></div>
      <p>The menu holds two separate procedures — <code>… · single</code> and
         <code>… · multi</code> — and the one you click is the mode you get. The dialog has a
         single switch left: put everything in a layer group.</p>
      <pre><code>single  Lab split group · pass-through (plus a mask when there is alpha)
 └─ 1 · Lab a/b/L mode  Normal  ← one operator chain computes the whole Lab colour

multi   Lab split group · pass-through (plus a mask when there is alpha)
 ├─ 2 · L mode      LCh lightness  ← replaces L* only
 └─ 1 · a / b mode  Normal         ← computes a, b and lightness</code></pre>
      <p>The single stack is: decompose (<code>lb:lab-dual</code>) → a curve (red) →
         b curve (green) → L curve (blue) → compose (<code>lb:lab-compose</code>).</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>single or multi</h3></div>
      <p>GIMP only has LCh component blend modes; Lab's a and b have no counterpart. L* is the
         same quantity in Lab and LCh (bit-exact), so lightness can be borrowed as its own
         layer — but a and b have to be restored as a pair, since together they set chroma and
         hue and splitting them is not a linear map.</p>
      <p><b>multi</b> is therefore two layers: the a/b data layer computes the full colour
         underneath, the L layer goes on top in LCh lightness mode and swaps lightness only.
         Switch the L layer off to see "original lightness plus edited a/b".</p>
      <p><b>single</b> folds L* into compose and turns two layers into one. What goes away is
         not just a layer but the situation where one layer uses a blend mode and the other
         uses Normal.</p>
      <p>In the data image neutral grey sits at 0.502: pulling the a curve above 0.5 pushes
         towards magenta, below it towards green; the b curve works the same way (up = yellow,
         down = blue).</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Ranges and measurements</h3></div>
      <p>Following babl's <code>CIE Lab float</code> (D50): a' = (a*+128)/255, L' = L*/100.
         Float identity round trip 0.0024 codes (multi with two layers: 0.0044 codes),
         0.49 codes in 8-bit. Editing only the a curve leaves b* and L* at the 0.00001-code
         level.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Watch out</h3></div>
      <p>a and b are rectangular: moving a changes chroma and hue as well (which is exactly
         what "the whole image went green" looks like). For chroma and hue independently, use
         the LCh plug-in. Points outside sRGB are clipped in 8-bit output — that is the gamut.
         Depends on <code>lb:lab-dual</code> / <code>lb:lab-compose</code>.</p>
    </div>
  </div>""")

PLUGIN_EN["hsi"] = dict(
    lede="""HSI's I is (R+G+B)/3 and its hue comes from a cosine definition, so none of GIMP's
   six component modes match — even borrowing HSV hue to rotate the angle drags I by 22 codes.
   All three components therefore share one layer: red = S, green = I, blue = hue, one curve
   each.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>One mode only</h3><span class="pill">single</span></div>
      <pre><code>HSI split group · pass-through (plus a mask when there is alpha)
 └─ 1 · HSI S/I/H mode  Normal  ← one operator chain computes the whole HSI colour
 └─ original layer (untouched, can be hidden)</code></pre>
      <p>Filter stack: decompose (<code>lb:hsi-dual</code>) → S curve (red) →
         I curve (green) → H curve (blue) → compose (<code>lb:hsi-compose</code>). Each
         component owns one channel and none of them leaks into another.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why there is no multi</h3></div>
      <p>HSI cannot borrow a single component mode: I=(R+G+B)/3 is neither V nor L, and hue is
         a cosine definition, so wiring it into "HSV hue" mode preserves HSV's S/V and drags I
         by 0.085 (about 22 codes). The three components can only be computed together.</p>
      <p>The other four plug-ins do have multi (two or three component layers) because each of
         them can borrow at least one native component blend mode — HSV and LCh have all
         three, HSL borrows hue, Lab borrows lightness. HSI has none, so splitting it would
         simply be inaccurate. Hence single only.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>The two hue angles are not the same thing</h3></div>
      <p>HSI's hue is a cosine definition — the true angle inside the constant-luminance plane
         — while HSV's is a parametric angle on a hexagonal projection. They agree at
         0°/30°/60° and differ by up to 1.117° in between. The data image stores the HSI angle
         and <code>lb:hsi-compose</code> inverts with the HSI cosine form, so nothing is ever
         converted halfway: the round trip is 0.0001 codes (0.5 codes in 8-bit).</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Watch out</h3></div>
      <p>Average intensity I is closer to perceived brightness than HSV's max, which is why HSI
         turns up in image analysis and exposure correction. Pushing S or I to the extremes
         sends the inverse outside sRGB (HSI's gamut is a hexagonal pyramid, not a cube) and
         whatever falls out is clipped at 0/1. Depends on <code>lb:hsi-dual</code> /
         <code>lb:hsi-compose</code>; there is no fallback, the plug-in raises an error if
         either is missing.</p>
    </div>
  </div>""")

PLUGIN_EN["frequency"] = dict(
    lede="""Splits a face into <b>tone</b> and <b>detail</b>: low frequency carries the broad light
   and shade and skin transitions, high frequency carries pores, blemishes and fine lines.
   Editing low frequency is relighting, editing high frequency is controlling texture, and the
   two do not interfere — the oldest and steadiest structure in retouching.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What gets created</h3><span class="pill">pass-through group</span></div>
      <pre><code>Frequency Separation group · pass-through (plus a mask when there is alpha)
 ├─ 2 · High frequency (detail)  Grain merge + high pass
 ├─ 1 · Low frequency (tone)     Normal + Gaussian blur
 └─ original layer (untouched, can be hidden)</code></pre>
      <p>Each layer carries one non-destructive filter and both use the same radius: change the
         radius on one and it has to change on the other, otherwise the stack no longer
         reproduces the original.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>The two filter settings</h3></div>
      <p>Low frequency is <code>gegl:gaussian-blur</code> with std-dev = radius; high frequency
         is <code>gegl:high-pass</code> with std-dev = radius and <b>contrast set to 2.0</b>. The
         default 1.0 produces only half the difference and the stack comes back grey — that one
         was measured, not guessed.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why it is an identity</h3><span class="pill">pixel exact</span></div>
      <p>The high-pass layer is really H = 0.5 + (original − low), and stacking back uses grain
         merge (H + L − 0.5), so the 0.5 offset cancels. A freshly created group is therefore
         pixel-identical to the original layer; the remaining error comes from about 1 code of
         fixed-point offset inside <code>gegl:high-pass</code> and does not depend on the
         radius.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>How to work with it</h3></div>
      <ul>
        <li><b>Low frequency:</b> a low-opacity brush, clone or smudge tool flattens the
            patches — blotchiness, uneven skin tone and light transitions all live here.</li>
        <li><b>High frequency:</b> clone or healing brush removes blemishes, pores and fine
            lines without touching the light.</li>
        <li>The radius is the dividing line: on a 1024-pixel image start at 4–8 px. Too large
            and detail gets smeared into tone; too small and broad patches stay in the high
            frequency.</li>
        <li>To start over, set both radii back or delete the group and generate it again — the
            original layer was never touched.</li>
      </ul>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3><span class="pill">check_retouch.py</span></div>
      <p>Identity within 1.5 codes in float and 8-bit; still an identity after changing the
         radius (so the structure really is live); hiding the original layer lets the two
         rebuild it; images with alpha keep their transparency through the group mask, zero
         error.</p>
      <p>Parameters: radius 0.2–100 px (default 8), and a group toggle.</p>
    </div>
  </div>""")

PLUGIN_EN["dodge"] = dict(
    lede="""One curve to lighten, one to darken, each under a fully black mask. Paint where you
   want it and only there does the image get lighter or darker — everywhere else stays
   pixel-identical, so you can keep stacking and undo at any time.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What gets created</h3><span class="pill">two layers, black masks</span></div>
      <pre><code>Dodge &amp; Burn group · pass-through (plus a mask when there is alpha)
 ├─ 2 · Darken (black mask)  Normal · curve pulled down
 ├─ 1 · Lighten (black mask) Normal · curve pushed up
 └─ original layer (untouched, can be hidden)</code></pre>
      <p>Both layers are in Normal mode with one <code>gimp:curves</code> (value channel) each;
         the masks are fully black, so the moment the group is created the two layers do not
         take part in the composite — pixel-identical to the original.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>You paint the mask, not the layer</h3></div>
      <p>Click the layer's mask thumbnail (the small image with the white frame, not the layer
         thumbnail), pick a soft brush, white, opacity 10–20%. Where you paint the mask turns
         white and that layer shows through: painting the lighten layer brightens, painting the
         darken layer darkens. Overdone? Switch the foreground to black and paint it back.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>How strong the curve is</h3><span class="pill">12%</span></div>
      <p>The "strength" parameter is how far the curve deviates from the diagonal at midtones:
         12 means 0.12 at 0.5, about 30 codes. Default 12, range 1–40. Err on the weak side — one
         more pass is easier to take than one too many.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>How to work with it</h3></div>
      <ul>
        <li><b>Lighten:</b> forehead, bridge of the nose, cheekbone highlights, the triangle
            under the eyes — push up what should be forward and the face reads as three
            dimensional.</li>
        <li><b>Darken:</b> the sides of the cheeks, jawline, shadow beside the nose, eye
            sockets — pull back what should recede.</li>
        <li>Alternate as you go (lighten → darken → look again) instead of adding brightness
            in one direction until the skin looks plastic.</li>
        <li>To check how much you painted, Alt-click the mask thumbnail to view the mask on its
            own — the black and white distribution is obvious.</li>
      </ul>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3><span class="pill">check_retouch.py</span></div>
      <p>Identity round trip 0 codes in float and 0 codes in 8-bit (the masks are black, the
         layers do not take part); where the mask is white the result equals the curve value
         exactly; untouched pixels do not move by one bit; images with alpha keep transparency
         through the group mask, zero error.</p>
    </div>
  </div>""")

PLUGIN_EN["grey"] = dict(
    lede="""A 50% grey layer set to soft light — soft light is an identity at 0.5, so a freshly
   created layer is pixel-identical to the original. From there a white brush lightens and a
   black brush darkens, without a single original pixel being touched: delete the layer and you
   are back at the start.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What gets created</h3><span class="pill">one layer</span></div>
      <pre><code>Neutral Grey group · pass-through (plus a mask when there is alpha)
 └─ 1 · Neutral grey  Soft light · the layer is all 128 grey
 └─ original layer (untouched, can be hidden)</code></pre>
      <p>One layer, no mask: the whole layer is filled with encoded grey 0.5 and set to soft
         light. You paint straight on this layer, unlike dodge &amp; burn where you switch to a
         mask.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why soft light, not overlay</h3></div>
      <p>Both are identities at 0.5 and differ in slope: soft light is gentle, so one or two
         strokes land within a few codes — right for repeated fine adjustment. Overlay is twice
         the slope, twice as strong for the same pressure, and much easier to blotch.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why 128, not Lab mid grey</h3></div>
      <p>The layer is filled with encoded value 0.5 (128 in 8-bit). Lab's L*=50 converts to
         about 0.46 in sRGB, and soft-lighting that darkens the whole image a little — which is
         no longer an identity. This is the trap neutral grey is most often caught by.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>How to work with it</h3></div>
      <ul>
        <li>Select the "1 · Neutral grey" layer, soft brush, opacity 5–15%, flow 10–30%.</li>
        <li>White paints light: flatten dark patches, bags under the eyes, nasolabial
            shadows.</li>
        <li>Black paints dark: pull back highlights, knock down shine, deepen contours.</li>
        <li>Overdone? Paint it back with 50% grey (#808080) — this is where it beats dodge
            &amp; burn, which needs the mask inverted.</li>
      </ul>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured, and one implementation note</h3><span class="pill">0 codes</span></div>
      <p>Identity round trip is 0 codes in both float and 8-bit; white lightens, black darkens,
         untouched pixels do not move by one bit; images with alpha keep transparency through
         the group mask.</p>
      <p>After writing the grey pixels the plug-in must <code>flush()</code> and then
         <code>update()</code>: changing only the private buffer without telling the core
         leaves the projection stale, so the export is right while that layer looks black on
         screen. This release fixes exactly that, and the regression suite now asserts an
         <code>update(0,0,W,H)</code>.</p>
    </div>
  </div>""")

PLUGIN_EN["alpha-curves"] = dict(
    lede="""GIMP's curves tool does have an Alpha channel, but that curve can only edit
   transparency that already exists — it has no idea what the red channel holds. Deciding
   transparency from a colour channel means moving the channel into alpha first. This plug-in
   does both steps: <b>channel → alpha</b>, then an <b>alpha curve you can draw</b>. Both are
   non-destructive filters.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What gets created</h3><span class="pill">two filters</span></div>
      <pre><code>Alpha Curves
 ├─ 2 · Alpha curve    gimp:curves (channel = Alpha)
 └─ 1 · Channel → alpha  lb:channel-range-to-alpha</code></pre>
      <p>The first filter writes the chosen channel into alpha linearly: the four sliders go to
         l1=0, l2=255, r1=r2=255 so the ramp fills the whole range and the mapping collapses to
         "alpha ← channel value". The second is an ordinary curve whose input is exactly that
         channel value.</p>
      <p>Open "2 · Alpha curve" and it starts with three control points on a flat top:
         (0, 255), (128, 255), (255, 255). The curve is SMOOTH rather than a hand-drawn sample
         table — three handles, drag any one and the whole curve follows, no hunting through
         dozens of sampled dots. Press it down a little and the shadows become semi-transparent;
         press it to the bottom and they vanish. Whatever you draw is the mapping.</p>
      <p>The moment it is attached the channel is pushed to fully opaque; for "attach it and
         change nothing", drag the three points back onto the diagonal (45°).</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Relation to Range → Alpha</h3></div>
      <p><code>lb:channel-range-to-alpha</code> does two things in one step: pick a channel and
         multiply it into alpha through a four-slider trapezoid. A curve cannot do that in one
         step — it cannot see "what the channel is", only alpha itself. Hence two filters here:
         move the channel into alpha, then draw the curve.</p>
      <p>Conversely, the operator's trapezoid is just one shape a curve can take. The
         <code>shape</code> parameter offers four starting points, all smooth curves and all
         draggable once attached:</p>
      <ul>
        <li><code>auto</code> / <code>flat</code> (default) = three points at the top, alpha
            wide open</li>
        <li><code>band</code> = blend-if style: closed at both ends, open in the middle</li>
        <li><code>identity</code> (45°) = alpha equals the channel value, a plain copy</li>
        <li><code>soft</code> = smoothstep: shadows more transparent, highlights more solid</li>
      </ul>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Measured</h3><span class="pill">check_alpha_curves.py</span></div>
      <p>With the identity curve, alpha differs from the chosen channel by ≤ 1 code and RGB does
         not move by a single code; the default flat top opens alpha completely (even the
         darkest point is 1); <code>band</code> matches
         <code>lb:channel-range-to-alpha</code>'s trapezoid at both ends and in the middle
         (≤ 3 codes), while the sharpest corner is rounded by the spline and can differ by up to
         42 codes — the curve is soft where the operator has a hard corner. 8-bit output is
         ≤ 2 codes.</p>
      <p>When the source is semi-transparent the result is a multiply, not a replace:
         alpha = original alpha × curve(channel value), matching the operator. 45 assertions in
         the regression suite.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Notes</h3></div>
      <p>Both filters sit on the layer, so they can be switched off one by one in the Layers
         panel and re-tuned at any time without touching pixels. Choosing alpha as the source
         channel attaches only the second filter — the purest form of "curve the transparency I
         already have".</p>
      <p>The curve's trc is pinned to encoded values, the same scale as
         <code>channel-range-to-alpha</code>'s 0–255 sliders. Depends on
         <code>lb:channel-range-to-alpha</code> (except in alpha mode).</p>
    </div>
  </div>""")

PLUGIN_EN["color-range"] = dict(
    lede="""GEGL operator properties are static: <code>lb:color-mask-select</code> holds a set of
   limits for highlights, shadows and midtones, and GIMP's generic dialog displays all four
   0–255 sliders <b>at once</b>, none of them changing when you switch the target. This plug-in
   replaces it with its own dialog: pick a hue family and you get tolerance only, pick highlights
   and you get one range slider defaulting to 192, shadows 64, midtones a low of 64 and a high of
   192.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Why a shell is needed</h3><span class="pill">static vs dynamic</span></div>
      <p>GEGL property declarations are fixed at compile time: there is no mechanism linking a
         <code>property_enum</code> to four <code>property_int</code>s, and a dialog cannot swap
         other widgets out when the enum changes. The operator therefore has to keep all four
         sliders permanently, and with "red" selected they still occupy the interface while doing
         nothing at all.</p>
      <p>What can really react is the program's own GTK dialog. The pixel work still goes to
         <code>lb:color-mask-select</code> — the shell only decides "which mode shows which
         sliders, and what each starts at", so both entry points compute identical pixels.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Starting point per mode</h3></div>
      <ul>
        <li>Red / yellow / green / cyan / blue / magenta: colour tolerance 50, minimum chroma 0
            (the range is the hue circle, there is no threshold slider)</li>
        <li>Highlights: range 192 (luminance ≥ 192 counts as highlight)</li>
        <li>Shadows: range 64 (luminance ≤ 64 counts as shadow)</li>
        <li>Midtones: low 64 / high 192</li>
        <li>Custom colour: picker button (pure red by default) + tolerance + minimum chroma</li>
      </ul>
      <p>Switching modes only swaps the page, and each page remembers its own values: change the
         highlight 192, switch to shadows, come back — it is still your number.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Preview and commit</h3><span class="pill">red overlay</span></div>
      <p>While you drag, the canvas shows a live red overlay (changes within 60 ms are merged
         into one recompute). Pressing OK turns the overlay off before merging, so no red is baked
         into the layer; the mask is written into the layer's alpha. Cancel removes the preview
         filter entirely, including any alpha channel added along the way.</p>
      <p>The difference from a non-destructive filter: this applies once and cannot be re-tuned
         after merging. If you want live parameters, attach the menu's
         <code>lb:color-mask-select</code> operator as a filter — same parameters, same pixels,
         plainer interface.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Notes</h3></div>
      <p>Depends on <code>lb:color-mask-select</code>; if the operator is missing the plug-in
         fails with an explicit error and a hint about the download rather than silently doing
         nothing. Layer groups have no pixels, so it refuses and asks you to merge first.</p>
    </div>
  </div>""")
