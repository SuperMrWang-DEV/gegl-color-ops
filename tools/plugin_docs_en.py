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

PLUGIN_EN["observe"] = dict(
    lede="""The most expensive mistake in retouching is adjusting what you cannot see yet. These
   six turn "build an inspection layer first" into one click: the copy, the filter and its
   settings are already in place. Hide it or delete it when you are done — not one pixel of the
   original was touched.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What gets created</h3><span class="pill">one copy</span></div>
      <pre><code>Observe · Steep curves    a copy + a layer filter (settings stay editable)
original layer            untouched, not one pixel changed</code></pre>
      <p>The copy carries the full pixels and the filter sits on the copy: right-click it →
         Layer → Filters and the parameters are still live. Nothing is baked into pixels, and
         deleting the layer leaves no trace.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why not an adjustment layer</h3></div>
      <p>GIMP 3 has no stand-alone adjustment layer, but a layer filter is the equivalent:
         <b>the settings are live, the pixels are not</b>. The only difference is that it has to
         hang off a layer, so we duplicate one first — no functionality is lost.</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>What the six show you</h3><span class="pill">no arguments, one click</span></div>
    <div class="table-wrap"><table class="op-table">
      <thead><tr><th>Menu item</th><th>Filter</th><th>What it reveals</th></tr></thead>
      <tbody>
        <tr><td><b>Black &amp; White</b></td><td><code>gimp:desaturate</code> (<b>luminance</b>)</td>
            <td>Structure, dust, bumps, brightness differences between patches. Most skin
                problems are already visible here; this is the layer that pairs with neutral
                grey and dodge &amp; burn</td></tr>
        <tr><td><b>Steep Curves</b></td><td>an S-curve, midtone slope about 2.3x</td>
            <td>Faint blotches and uneven tone. Transitions you would stare at for a minute
                turn into obvious patches</td></tr>
        <tr><td><b>Wave Curves</b></td><td>desaturate + a four-peak zigzag curve</td>
            <td>Banding, broken tone steps, steps inside a gradient. Continuous tone folds
                back and forth, so a break shows up at once — a contour map of the skin</td></tr>
        <tr><td><b>Saturation +100</b></td><td><code>gimp:hue-saturation</code>, +100</td>
            <td>Redness, colour casts, the edges of colour patches</td></tr>
        <tr><td><b>Threshold</b></td><td>desaturate + a hard step at the median</td>
            <td>Dust, acne, small specks. The harshest of the six — only shapes survive</td></tr>
        <tr><td><b>Posterize</b></td><td><code>gimp:posterize</code>, 4 levels</td>
            <td>Patch boundaries and whether a gradient is clean. Gentler, keeps some structure</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Why the threshold uses the median</h3></div>
      <p>A fixed 0.5 does not work: a dark image (night shot, dark screenshot, underexposed
         photo) sits entirely below 0.5 and comes out as one black block with nothing to see.
         Cutting at the layer's <b>median</b> keeps black and white roughly balanced.</p>
      <p>It also avoids <code>gimp:threshold</code>: its low / high arguments do not behave the
         way the two sliders in the UI do — measured, <code>low == high</code> (the obvious way
         to get a hard cut) turns the whole layer black, and narrowing the range moves the cut
         point around. A curve with a one-code step is deterministic: the cut is the median.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Two details that are easy to miss</h3></div>
      <p><b>Wave and threshold desaturate first.</b> Applied to colour, the contours pick up
         each channel's own hue (purple, green, blue rings) — informative but noisy, and it
         makes "is this patch uneven?" harder to judge. Letting the three channels cross the
         threshold separately also turns the threshold layer colour.</p>
      <p><b>Black &amp; white uses luminance, not lightness.</b> Luminance weights R/G/B the
         way the eye does: a red and a green patch can have the same lightness and still differ
         in luminance. Spotting blotches needs the latter.</p>
    </div>
  </div>""",
)

PLUGIN_EN["luminosity"] = dict(
    lede="""Luminosity masks turn "this part should be brighter" from a description into a
   selection you can load at any time. Seven channels cut by brightness, all in the channels
   dialog: double-click one and it becomes a selection. Brighten the sky, darken the ground,
   work on the midtones alone -- no more hand-painted masks.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What gets built</h3><span class="pill">seven channels</span></div>
      <pre><code>Luminosity · Lights 1 (&gt; 64)     widest highlight mask
Luminosity · Lights 2 (&gt; 128)
Luminosity · Lights 3 (&gt; 192)     only the brightest
Luminosity · Darks 1 (&lt; 192)      widest shadow mask
Luminosity · Darks 2 (&lt; 128)
Luminosity · Darks 3 (&lt; 64)
Luminosity · Midtones (64-192)   trapezoid, fading at both ends</code></pre>
      <p>They land in the <b>channels dialog</b>, not the layer stack -- that is their native
         form in Photoshop too. Double-click one to load it as a selection; curves, levels and
         sharpening then act only inside it.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Three steps to use it</h3></div>
      <p><b>1</b>　Select a layer, run the menu item -- all seven are built<br>
         <b>2</b>　Double-click a channel to load it as a selection<br>
         <b>3</b>　Duplicate the layer, adjust the curve inside the selection</p>
      <p>To hang one as a layer mask: select the channel, then right-click the layer
         (pairs with <b>Channel to Mask</b>). Re-running deletes the previous batch first, so
         the channels never pile up.</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>What each one selects</h3><span class="pill">linear level stretch</span></div>
    <div class="table-wrap"><table class="op-table">
      <thead><tr><th>Channel</th><th>How it is computed</th><th>What it picks</th></tr></thead>
      <tbody>
        <tr><td><b>Lights 1 (&gt; 64)</b></td><td>luminance 64-255 stretched to 0-255</td>
            <td>Sky, lit surfaces, white walls -- everything outside the shadows. The workhorse</td></tr>
        <tr><td><b>Lights 2 (&gt; 128)</b></td><td>128-255</td>
            <td>Clear highlights. Pull down highlights, recover cloud detail</td></tr>
        <tr><td><b>Lights 3 (&gt; 192)</b></td><td>192-255</td>
            <td>Clouds, lamps, specular hits. For touching only the brightest patch</td></tr>
        <tr><td><b>Darks 1 (&lt; 192)</b></td><td>inverse of Lights 3</td>
            <td>Everything from the shadows up into the midtones</td></tr>
        <tr><td><b>Darks 2 (&lt; 128)</b></td><td>inverse of Lights 2</td>
            <td>Clear shadow areas. Darken the edges into a vignette</td></tr>
        <tr><td><b>Darks 3 (&lt; 64)</b></td><td>inverse of Lights 1</td>
            <td>Crushed blacks. Lift shadow detail, clean up noise there</td></tr>
        <tr><td><b>Midtones (64-192)</b></td><td>Lights 1 minus Lights 3, normalised</td>
            <td>The tonal band the subject lives in, fading at both ends -- add contrast
                without touching highlights or shadows</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Why channels, not layers</h3></div>
      <p>A luminosity mask <i>is</i> a channel in Photoshop; "load as selection" is how it is
         used. Gray layers work too, but every use costs an extra "layer to selection" step --
         one extra step means it gets used less.</p>
      <p>All seven share one luminance pass: duplicate the layer, desaturate (weighted), read
         the pixels once, apply seven look-up tables, delete the copy. So they are cut from the
         same brightness and cannot drift apart.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Two implementation details</h3></div>
      <p><b>Midtones subtract, they do not multiply.</b> Multiplying two highlight masks peaks
         around 170 -- a muddy grey that needs another curve before it is usable as a mask.
         Subtracting and renormalising puts the peak at pure white with pure black at both
         ends.</p>
      <p><b>Built at 8 bits (256 levels).</b> A mask is a continuous gradient and 256 levels
         are invisible in almost any composite. If 16-bit landscape work ever shows stepping,
         the same masks can be routed through GEGL levels so the precision follows the image.</p>
    </div>
  </div>""",
)

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


PLUGIN_EN["channel-to-mask"] = dict(
    lede="""The native route is <b>Layer → Mask → Add Layer Mask → Channel</b>, then picking a
   channel in the dialog — one layer at a time. This plug-in reverses the order: pick a channel
   in the Channels dock, select the layers you want masked, right-click once. Several layers at
   a time, and an invert switch. It is the exact inverse of <code>Layer to Channel</code>.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>GIMP can do it — here is the difference</h3><span class="pill">four steps → one</span></div>
      <p>GIMP does have "mask from a channel", but the path is fixed: select the layer, menu to
         <b>Layer → Mask → Add Layer Mask</b>, choose the Channel type, then pick one in the
         dialog. Three layers means walking it three times.</p>
      <p>This plug-in adds three things only: <b>it lives in the right-click menu</b> (mask the
         layer you clicked), <b>it takes several layers at once</b> (multi-select in the Layers
         dock, all get the same content), and <b>it can invert</b> (mask by the channel's
         complement). Pixel results are bit-for-bit identical to the native route, mid-grey
         drift included.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Grey level is mask strength</h3></div>
      <ul class="deps">
        <li><b>Black</b> hides, <b>white</b> shows, <b>mid grey</b> is partial</li>
        <li>The channel is the one you <b>right-clicked in the Channels dock</b>; with no
            click it falls back to the dock selection, then to the only channel in the image.
            A name overrides all of that</li>
        <li>No mask yet → a new one is built the native way</li>
        <li>Mask already there → dropped and rebuilt, identical to a fresh native one, so <b>re-running refreshes it</b></li>
      </ul>
      <p>Offset layers need no attention: the mask matches the layer's size and samples the
         channel at the same canvas position, so nothing lands shifted.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Numbers identical to native</h3><span class="pill">128 → 188</span></div>
      <p>GIMP 3 has no direct "channel to mask" entry, so the native route is two steps:
         <b>channel → selection → mask from selection</b>. This plug-in takes the same road and
         calls the same <code>create_mask(SELECTION)</code>, so results match bit for bit —
         including the mid-grey drift: on a default 8-bit image a channel value of 128 produces
         a mask value of <b>188</b>, not 128.</p>
      <p>On 32-bit linear precision the channel itself holds linear values, the straight copy
         happens to be correct, and nothing drifts. The plug-in adds no compensation: whatever
         native does is what you get.</p>
    </div>
  </div>
  <p class="note">No dependency on this project's operators: it calls GIMP's own
     <code>gimp-image-select-item</code> and mask PDB, and never writes pixel buffers itself.
     Entering from a channel's right-click menu uses that very channel, so there is nothing to
     select first; when no source can be found it fails with an explicit message listing the
     available channels. Layer groups have no pixels, so it refuses and asks you
     to merge first.</p>""")


PLUGIN_EN["convert"] = dict(
    lede="""Channels, selections, layer masks and paths, converted in every direction: twelve
   menu items plus <b>Path to Bitmap</b>, each one click and done — no parameter dialog. Natively these paths are spread
   across four places, and <b>mask → channel does not exist at all</b>; it takes a detour
   through the selection in two steps. A path is a <b>lossy stop</b>: it carries geometry and
   no alpha, so anything going into a path is traced along the 50% contour.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Why it needs its own entry</h3><span class="pill">four places</span></div>
      <p>Doing the same thing natively means remembering three routes: <b>Select</b> menu to
         save a channel, the <b>channel context menu</b> to make a selection, and
         <b>Layers → Mask → Add Layer Mask</b> with a type picked in the dialog. Same family
         of operations, three locations, and the directions reverse halfway through.</p>
      <p>Worse, <b>mask → channel simply is not there</b>: GIMP has no such procedure, so it
         is "mask to selection" and then "selection to channel" — two steps, two menus. This
         plug-in makes it one.</p>
      <p>Paths are the same story: <b>path → selection</b> lives in the Paths context menu and
         <b>selection → path</b> in the Select menu, while <b>channel / mask ↔ path</b> has no
         native entry at all and has to be assembled by hand. All of it now sits in one
         submenu, named by destination.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Thirteen directions</h3><span class="pill">zero arguments</span></div>
      <ul class="deps">
        <li><b>Channel to Selection</b></li>
        <li><b>Selection to Channel</b></li>
        <li><b>Channel to Mask</b></li>
        <li><b>Mask to Channel</b></li>
        <li><b>Selection to Mask</b></li>
        <li><b>Mask to Selection</b></li>
        <li><b>Path to Selection</b></li>
        <li><b>Selection to Path</b></li>
        <li><b>Path to Channel</b></li>
        <li><b>Channel to Path</b></li>
        <li><b>Path to Mask</b></li>
        <li><b>Mask to Path</b></li>
        <li><b>Path to Bitmap</b> — rasterise to a pixel layer</li>
      </ul>
      <p>A menu item without an ellipsis <b>runs immediately</b>: the source is read from the
         context, so there is nothing to pick in a dialog.</p>
      <p>The last one is different from the other twelve. All of those shuffle objects inside
         GIMP; <b>Path to Bitmap</b> is the only one that turns geometry into pixels. A path
         carries no fill colour and no line width, so rasterising it here means filling its
         interior with the foreground colour — the same thing the native "Edit > Fill with
         foreground colour" does on a path. The new layer is cropped to the path's bounding
         box and offset back into place, so rasterising a 24×24 icon does not also hand you a
         4000×3000 empty layer. For outlines rather than solid shapes, use the native
         "Edit > Stroke Path".</p>
      <p>A <b>vector layer</b> (GIMP 3.2) is the other case: it carries its own fill colour,
         stroke colour and width, so it is rasterised <b>as it looks</b> and replaces that
         layer — one layer in, one layer out, no foreground-colour copy stacked on top.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>The source is always "current"</h3></div>
      <ul class="deps">
        <li><b>Channel</b> = the one right-clicked in the Channels dock, else the dock
            selection, else the only channel in the image</li>
        <li><b>Selection</b> = the active pixel selection; <b>none means select-all</b></li>
        <li><b>Mask</b> = the selected layer's layer mask</li>
        <li><b>Path</b> = the one right-clicked in the Paths dock, else the dock selection,
            else the only path in the image</li>
        <li>Sinks: a new channel or path, or masks on every selected layer</li>
      </ul>
      <p>An existing mask is <b>dropped and rebuilt</b>, bit-for-bit identical to a fresh
         native one — change the source and re-run to refresh.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Bit-for-bit with native</h3><span class="pill">the hard requirement</span></div>
      <p>None of the twelve directions touches a pixel buffer. Each one calls GIMP's own
         procedure: <code>gimp-image-select-item</code> for a channel or path to a selection,
         <code>gimp-selection-save</code> for a selection to a channel,
         <code>create_mask(SELECTION)</code> for a selection to a mask, and
         <code>plug-in-sel2path</code> — the procedure behind Select &gt; To Path — for a
         selection to a path. Where native has no direct entry (channel ↔ mask, channel / mask
         ↔ path) it runs the native two steps through the selection.</p>
      <p>That means mid greys carry the native drift: on a default 8-bit image a channel value
         of 128 reads back as <b>188</b> in the selection, and a selection value of 128 reads
         back as <b>55</b> in a channel. Selection ↔ mask converts properly in GIMP, so that
         pair does not drift. On 32-bit linear precision the six bitmap directions do not drift
         at all. The path directions follow the same chain: channel → path first becomes the
         188 selection, then the contour is taken at 50%, exactly like doing the two native
         steps by hand.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why single steps look wrong</h3></div>
      <p><b>It is not the plug-in's arithmetic.</b> Channels and masks store <code>Y'</code>
         (sRGB encoded); the selection stores linear alpha. Native copies the <code>Y'</code>
         value straight in as linear coverage, so 128 becomes 188, and the reverse direction
         squashes it to 55.</p>
      <p><b>Round trips cancel out.</b> 188 stored back into a channel becomes 128 again, so two
         steps in a row look fine; only a single step shows it. That is native behaviour and the
         plug-in does not compensate.</p>
      <p><b>Masks are 8-bit.</b> Expect ±1 quantisation in the deep shadows, exactly as native;
         offset layers align by canvas, also as native.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Relation to Channel to Mask</h3></div>
      <p><b>Channel to Mask...</b> (in the Mask group, with an ellipsis) is the
         <b>configurable</b> version of the same action: channel by name, invert, several
         layers at once.</p>
      <p><b>Convert → Channel to Mask</b> (no ellipsis) is the one-click version: it takes the
         channel you clicked in the dock and does not invert. Use the quick one day to day, the
         parameterised one when you need to adjust.</p>
    </div>
  </div>
  <p class="note">None of the twelve directions depends on this project's operators — they only
     call GIMP's own channel, selection, mask and path PDB. A missing source produces an explicit
     message (no channel found / no mask / no path / layer group has no pixels) instead of
     silently doing nothing. <b>A path is a lossy stop</b>: feathered, gradient and anti-aliased
     edges collapse to a hard boundary on the way into a path, because a path carries geometry
     and no alpha — the native To Path does the same. Going the other way loses nothing:
     rasterising a path gives clean hard edges.</p>""")

PLUGIN_EN["max-min"] = dict(
    lede="""Photoshop's Maximum / Minimum filter: every pixel takes the largest or smallest
   value in its neighbourhood. Maximum pushes bright areas outwards and swallows small dark
   specks; minimum shrinks bright areas and eats leftover fringes. GIMP 3 no longer has it —
   <code>gegl:dilate</code> / <code>gegl:erode</code> are not built into the official
   Windows binaries and <code>plug-in-dilate</code> was removed after 2.10 — so this uses the
   project's own <code>lb:max-min</code> operator.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Two directions, one operation</h3><span class="pill">morphology</span></div>
      <p><b>Maximum (dilate)</b> takes the largest value around each pixel: bright areas grow
         a ring outwards and small dark specks disappear. <b>Minimum (erode)</b> takes the
         smallest: bright areas shrink, dark specks vanish and the fringe left after a cut-out
         is chewed away.</p>
      <ul class="deps">
        <li><b>Grow / shrink</b> a mask or channel by a ring</li>
        <li><b>Despeckle</b> — minimum for bright specks, maximum for dark ones</li>
        <li><b>Glow base</b> — maximum spreads the highlights before blending back</li>
        <li><b>Thickness</b> — erode and subtract from the original for an outline</li>
      </ul>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why it has to be written here</h3></div>
      <p>Up to 2.10 there was Filters &gt; Generic &gt; Dilate / Erode; afterwards GEGL's
         <code>gegl:dilate</code> / <code>gegl:erode</code> took over. Those are workshop
         operators and <b>are not compiled into the official Windows build</b>: on 3.2.8
         <code>gegl --list-all</code> does not list them and there is no
         <code>plug-in-dilate</code> in the PDB at all.</p>
      <p>The only native leftovers are <code>gimp-selection-grow</code> /
         <code>-shrink</code>, and those work on selections only — they cannot change a mask or
         a layer's pixels.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Four parameters</h3><span class="pill">mirrors PS</span></div>
      <ul class="deps">
        <li><b>Mode</b> — maximum (dilate) / minimum (erode)</li>
        <li><b>Radius</b> — 1–100 px; r=1 is a 3×3 window, one ring outwards</li>
        <li><b>Shape</b> — square or round, i.e. PS's “Preserve: Squareness / Roundness”</li>
        <li><b>Affect alpha</b> — off by default; PS leaves layer opacity alone too</li>
      </ul>
      <p>Radius means the same thing as in PS: it checks a <b>(±r, ±r)</b> neighbourhood, not a
         window edge length — so r=1 gives exactly 3×3.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Colour fringing is correct</h3></div>
      <p>PS applies this per channel on an RGB composite, which is why red/blue edges pick up a
         magenta fringe. The operator does the same and makes no attempt to balance channels.</p>
      <p>For no fringing, target a single-plane drawable: a mask, a channel or a greyscale
         layer. On a mask the operation is pure grow / shrink.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Bit-exact: compared in the buffer's own precision</h3><span class="pill">u8 / u16 / f32</span></div>
      <p>A maximum only needs ordering, but the value still has to be carried out untouched.
         So there are three copies of the kernel: u8 compares u8, u16 compares u16, float32
         compares float32, with <b>no format conversion in between</b>. Reading a u16 as float
         and writing it back moves some pixels by one code — that is not allowed here.</p>
      <p>No colour management, no gamma conversion: PS's Maximum / Minimum also work straight on
         channel values.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>No darkened border</h3></div>
      <p>Outside the canvas the edge pixels are replicated. For a min/max that is
         <b>bit-identical</b> to only counting the in-canvas part of the window: the replicated
         values are copies of an edge pixel that is already inside it. Unlike a blur, nothing
         darkens at the border.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Speed</h3></div>
      <p><b>A square window is separable</b> — one horizontal pass, one vertical, both
         independent of the radius: on a 3 MP image r=1 and r=100 both take tens of
         milliseconds. <b>A disc</b> has a different half-width per row and cannot be split;
         its cost grows linearly with the radius (3 MP at r=100 is about 1.2 s).</p>
    </div>
  </div>
  <p class="note">On a layer this is a <b>non-destructive filter</b>: change the parameters or
     toggle it off at any time. Masks and channels carry no filter stack (measured on GIMP 3:
     appending a filter to a mask neither errors nor has any effect on rendering), so those two
     are baked into pixels and undone with undo. Regression: <code>check_max_min.py</code>
     (27 checks against an O(r²) brute force — u8 / u16 / f32 × square / round × three radii,
     plus band seams and a radius larger than the image) and
     <code>check_max_min_plugin.py</code> (12 checks: PDB, filter attachment, mask baking,
     error branches).</p>""")

PLUGIN_EN["cutout"] = dict(
    lede="""Lift the subject off its background: one feathered mask on the layer, everything
   else transparent — optionally with a flat colour (ID photos, product shots) or a new
   background picture underneath. Two routes: the AI one separates single hairs, the local
   one eats plain and gradient backgrounds in milliseconds.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Which route does what</h3><span class="pill">pick by photo</span></div>
      <div class="table-wrap"><table class="op-table">
        <thead><tr><th>Menu item</th><th>How it finds the subject</th><th>When to use it</th></tr></thead>
        <tbody>
          <tr><td><b>Cut Out (AI)</b></td>
              <td>A downscaled copy goes to the local ComfyUI <code>RMBG</code> node
                  (BiRefNet / RMBG-2.0); the returned alpha becomes the mask</td>
              <td>Hair, fur, glass, green screen, busy backgrounds. 4–6 s per image</td></tr>
          <tr><td><b>Cut Out (Local)</b></td>
              <td>Flood-fills the background from several seeds per border, then inverts.
                  With an existing selection, <b>the selection is the subject</b> and only
                  its edge is refined</td>
              <td>Plain, gradient or studio backgrounds; or rough-select first and let it
                  clean the edge. Milliseconds</td></tr>
        </tbody>
      </table></div>
      <p>Both routes end in the same code: mask → shrink by <code>shrink</code> px → feather
         by <code>feather</code> → layer mask plus a <code>Cutout Mask</code> channel →
         optional background underneath.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Output</h3></div>
      <p><b>Transparent</b>: just the mask — export a PNG and the background is gone.
         <b>Solid colour</b>: a flat layer (white by default) is created under the photo.
         <b>Image</b>: pick a picture; it is scale-to-cover and centre-cropped under the photo.</p>
      <p>All three are non-destructive: original pixels stay, the mask stays editable, and
         deleting the background layer brings transparency back.</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>Measured</h3><span class="pill">RTX 3070 Ti</span></div>
    <p>A 768×1024 SDXL portrait with curly hair, cut out with RMBG-2.0: <b>4.6 s</b>
       including model load, 59.6 % of the pixels kept, individual strands preserved, the
       white shirt edge clean. <code>shrink=1</code> removes the half-pixel the model adds
       outward, so no white fringe shows on a light background.</p>
    <p>The local route on a 400×300 “white background + red block” test image: border
       coverage 100 %, mask 255 inside the subject and 0 at all four corners, with no
       per-pixel Python loop — <code>gimp-image-select-contiguous-color</code> is C, so even
       24 MP is a matter of milliseconds.</p>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Turning an AI alpha into a selection</h3></div>
      <p>The alpha comes back at thumbnail size (long edge ≤ 2048). Interpolating that to
         4000×6000 in Python takes tens of seconds, so instead a temporary layer of the same
         size is created with RGB=white and A=alpha, inserted, scaled to the canvas by
         <code>gimp-layer-scale</code>, and finally <code>select-item</code>d. The scaling is
         C; Python moves <code>mw×mh×4</code> bytes once.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Two silent failures</h3></div>
      <p><b>A flood fill that selects nothing reports no error</b>: the selection is empty,
         inverting gives the whole image, and the result looks like “the subject became pure
         white”. So the border coverage is checked first; below 35 % it stops and says to
         raise the threshold or use the AI route.</p>
      <p><b>A background layer at the wrong index hides the photo</b>:
         <code>insert_layer</code> positions count from the top, so inserting at the photo's
         own position puts it <b>above</b>. It has to be <code>pos + 1</code>.</p>
    </div>
  </div>""")

PLUGIN_EN["refine"] = dict(
    lede="""The selection is there, the edge is not: alpha from an AI cut-out is
   half-transparent, a magic-wand edge looks gnawed, a feathered edge carries the old
   background colour. This dialog is the finishing pass — preview on the left, six
   sliders on the right, every change re-rendered immediately.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>The six sliders</h3><span class="pill">same names, same direction</span></div>
      <div class="table-wrap"><table class="op-table">
        <thead><tr><th>Slider</th><th>What it does</th><th>When to pull it</th></tr></thead>
        <tbody>
          <tr><td><b>Edge radius</b></td>
              <td>Searches ±N px along the normal for a real edge and moves the mask
                  profile onto it. With “smart” on, it only moves for an edge at least
                  1.35× stronger</td>
              <td>The AI edge is one or two pixels out and there is a strong edge
                  nearby (hair against background, collar against skin)</td></tr>
          <tr><td><b>Smooth</b></td>
              <td>One box blur pass: jaggies, specks and stray dots get flattened</td>
              <td>A magic-wand / quick-select edge looks gnawed</td></tr>
          <tr><td><b>Feather</b></td>
              <td>Three box passes approximating a Gaussian</td>
              <td>Pasting onto another picture, where a hard edge reads as cut paper</td></tr>
          <tr><td><b>Contrast</b></td>
              <td>Pushes the soft part towards 0 and 255 (S-curve, up to 5× slope)</td>
              <td>Over-feathered, a band of fog around the subject; or alpha that is
                  simply too soft</td></tr>
          <tr><td><b>Shift edge</b></td>
              <td>Adds or subtracts alpha: positive expands, negative contracts, the
                  softness stays</td>
              <td>The whole mask is half a pixel out (a white fringe, or eating into
                  the outline)</td></tr>
          <tr><td><b>Decontaminate</b></td>
              <td>Walks inwards along the alpha gradient and replaces half-transparent
                  colours with the solid foreground colour behind them</td>
              <td>A white fringe on a light background, a green fringe from a green
                  screen</td></tr>
        </tbody>
      </table></div>
      <p>The order is <b>snap → smooth → feather → contrast → shift</b>. Feather sits
         before contrast on purpose: contrast has to be able to harden a softened edge,
         otherwise feather always wins and that slider does nothing.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Four outputs</h3></div>
      <p><b>Layer mask</b>: attached to the current layer, non-destructive.<br>
         <b>New layer</b>: the layer is copied and the mask is baked into its alpha;
         decontaminate only applies here, because the other three do not touch
         pixels.<br>
         <b>Selection</b>: replaces the selection, nothing else changes.<br>
         <b>Channel + selection</b>: stored as a “Refined Mask” channel.</p>
      <p>That channel is the <b>brush entry point</b>: Photoshop's brush inside Select
         and Mask is replaced by painting black and white on the channel (white adds,
         black removes) and loading it back as a selection. GIMP's own brushes are
         better than a brush we would re-invent inside a plug-in.</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>Measured</h3><span class="pill">768×1024 / RMBG result</span></div>
    <p>Input: an SDXL portrait cut out with RMBG-2.0 (its alpha is the mask).
       All six steps in <b>1.03 s</b> (radius 2 / smooth 1 / feather 1 / contrast 35 /
       decontaminate 60): half-transparent pixels dropped from 400 k to 13 k, the pale
       haze on the edge was cleaned up, and 23 416 edge pixels changed colour. On the
       preview side (520 px long edge) a slider drag re-renders in under
       <b>150 ms</b>.</p>
    <p>The working size defaults to 1600 px on the long edge. GIMP 3's Python has
       <b>no numpy</b>, so blurs are written by hand with prefix sums: 1600×1067 takes
       one to two seconds, more takes longer. 0 means full resolution — 24 MP starts at
       about ten seconds.</p>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Where it differs from Photoshop</h3></div>
      <p><b>Has:</b> the six sliders, a live preview, four ways to look at the result
         (checker / white / black / red overlay), four outputs. <b>Has not:</b> the
         subtract brush on the canvas, and Photoshop's “rebuild the matte” edge
         detection.</p>
      <p>Edge detection here <b>slides the profile along the normal</b>: every
         half-transparent pixel looks for the strongest edge within ±radius and, if it
         is clearly stronger, the mask is resampled onto it. Same visible result —
         the smeared edge comes back — but it does not re-solve foreground colour and
         opacity the way Photoshop does.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Three details that bite</h3></div>
      <p><b>A channel reads back linear.</b> After saving a selection to a channel,
         <code>"Y u8"</code> gives linear luminance while selection values and layer
         alpha are sRGB-encoded (measured: write 128 into the channel, the selection
         reads 188). Skip that conversion and the whole midtone shifts down after
         refining, taking the 50 % contour with it.</p>
      <p><b>Preview and apply have to be the same code.</b> Both call the same
         <code>refine_mask</code>, only at different resolutions. Two implementations
         always drift into “looks great in the preview, different after Apply”.</p>
      <p><b>The snap has to propagate its offset along the normal to ±radius.</b>
         Moving only the half-transparent band leaves nothing to receive the shifted
         profile, and the edge collapses into a hard step.</p>
    </div>
  </div>""")

PLUGIN_EN["ai-frequency"] = dict(
    lede="""The structure is exactly the same as Frequency Separation — the pixels are
   not. Both layers carry a <b>reference that was already retouched once</b>: a low-denoise
   ComfyUI pass, or a locally blurred copy. You open a file where the colour is already
   evened out and most blemishes are gone, and finish on top.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What it builds</h3><span class="pill">same as the original</span></div>
      <pre><code>Frequency Separation (AI prep)   group · pass-through (masked when the source has alpha)
  ├─ 2 · High frequency (detail) grain merge + high pass
  ├─ 1 · Low frequency (tone)    normal + gaussian blur
  └─ the original layer (untouched, safe to hide)</code></pre>
      <p>The composite equals the <b>reference</b>, not the original — that is the
         pre-work. Toggle the group to compare, or hold <kbd>Shift</kbd> and click its eye.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Where the reference comes from</h3><span class="pill">source</span></div>
      <p><b>AI</b>: the whole layer goes through ComfyUI at <code>denoise 0.35</code>. It
         knows this is skin — blemishes, redness and blotches flatten out while features
         and edges stay. <b>Local</b>: downscale-then-upscale as a low-pass, milliseconds
         and no dependencies.</p>
      <p>If ComfyUI is not reachable the plug-in falls back to the local reference and says
         so in the message, instead of throwing a wall of errors.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Selections</h3></div>
      <p>With a selection active, only that area is replaced by the reference; everything
         outside stays pixel-identical to your layer. All three AI retouching plug-ins
         behave this way.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Finishing it</h3></div>
      <ol class="steps">
        <li><b>High layer</b>: clone or heal the blemishes that are left.</li>
        <li><b>Low layer</b>: brush a little more evenness where you want it; sample
            neighbouring colour to undo.</li>
        <li><b>Radius</b> is the cutoff: start at 4–8 px on a 1024-px image. Both layers
            share the radius — change them together or the stack no longer rebuilds the
            reference.</li>
      </ol>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3><span class="pill">check_retouch_ai*.py</span></div>
      <p>Structure, blend modes and filters match the original plug-in item for item. On
         the soft-blob test image the local reference leaves <b>≤ 6 levels</b> of high-pass
         residue (the original image is used as the control). When the reference equals the
         original (the mock returns it unchanged) nothing is flattened.</p>
      <p class="muted small">Arguments: <code>source</code> (ai / local),
         <code>radius</code> 0.2–100 px, <code>denoise</code> 0.05–0.9,
         <code>prompt</code>, <code>server</code> / <code>checkpoint</code> /
         <code>steps</code>, <code>group</code>.</p>
    </div>
  </div>""",
)

PLUGIN_EN["ai-dodge"] = dict(
    lede="""Still two curves, one lightening and one darkening — but <b>the masks are no
   longer black</b>. The plug-in measures how far the reference sits above or below your
   layer, turns that into mask density and paints 70% of it for you.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What it builds</h3><span class="pill">pre-painted masks</span></div>
      <pre><code>Dodge &amp; Burn (AI prep)   group · pass-through
  ├─ 2 · Burn (pre-painted)  normal + darken curve + painted mask
  ├─ 1 · Dodge (pre-painted) normal + lighten curve + painted mask
  └─ the original layer (untouched)</code></pre>
      <p>Areas darker than the reference land in the dodge mask, brighter ones in the burn
         mask; flat areas and the background stay black and take no part.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Density is per pixel, not global</h3></div>
      <p>The curve is <code>x + d·4x(1−x)</code>: pinned at both ends, strongest in the
         middle. Lifting by 0.06 needs mask 0.5 at mid-grey and a much denser mask in the
         shadows, so the density is solved from each pixel's own value.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why only 70%</h3><span class="pill">prepaint</span></div>
      <p>A full correction usually overshoots — the reference has its own error. 70% leaves
         the last part to your brush; set 100% to hand it all over, 30% for a hint, 0% for
         the original plug-in (two black masks).</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Finishing it</h3></div>
      <ol class="steps">
        <li>Click a layer's <b>mask thumbnail</b>, pick a soft white brush at 10–20%.</li>
        <li>Paint more where it is not there yet; black takes a stroke back, or lower
            <code>prepaint</code> and run again.</li>
        <li><kbd>Alt</kbd>-click the mask thumbnail to look at the mask alone.</li>
      </ol>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3><span class="pill">check_retouch_ai*.py</span></div>
      <p>On the soft-blob test image the dark blob lands at ≈ <b>116</b> in the dodge mask
         and the bright one at ≈ <b>129</b> in the burn mask, with zero at the crossover;
         <code>prepaint=0</code> gives two fully black masks, exactly like the original
         plug-in, and everything outside a selection stays 0.</p>
      <p class="muted small">Arguments: <code>source</code>, <code>amount</code> 1–40%,
         <code>prepaint</code> 0–100%, <code>radius</code> (local reference),
         <code>denoise</code>, <code>prompt</code>, <code>group</code>.</p>
    </div>
  </div>""",
)

PLUGIN_EN["ai-grey"] = dict(
    lede="""That 50% grey Soft Light layer is <b>no longer flat 128</b>: the plug-in solves
   the soft-light formula backwards for the reference and writes the result into the
   layer. You open a file where one neutral-grey pass is already done.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What it builds</h3><span class="pill">128 ± offset</span></div>
      <pre><code>Neutral Grey (AI prep)          group · pass-through
  └─ 1 · Neutral grey (pre-corrected)  soft light + 128±offset pixels
     └─ the original layer (untouched)</code></pre>
      <p>Every pixel is an analytic solution: <code>out = x + (2g−1)·…</code> inverted for
         g, not a guess.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Pixels, not a mask</h3></div>
      <p>So erasers, fills, gradients and paste all work — it takes more abuse than the
         dodge &amp; burn version. The price: overshooting can only be undone with
         <code>#808080</code>, whereas the curve version just paints its mask black.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>How much is pre-corrected</h3><span class="pill">prepaint 70%</span></div>
      <p>70% by default: shadows land above 128 (lightened), highlights below 128
         (darkened), flat background at 128. 0% gives the original flat grey layer.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Finishing it</h3></div>
      <ol class="steps">
        <li>Select the grey layer, soft brush at 5–15%: white lightens, black darkens.</li>
        <li>Overshot? Set the foreground to <code>#808080</code> and paint it back — that
            means "do nothing here".</li>
        <li>Too strong overall? Hide the group, change <code>prepaint</code> and run again;
            your original layer never moved.</li>
      </ol>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3><span class="pill">check_retouch_ai.py</span></div>
      <p>Feeding the grey layer back through the soft-light formula reproduces the
         reference within <b>≤ 1 level</b> across six combinations of base value and delta,
         in both directions. On the blob image: <b>162</b> on the dark blob, <b>97</b> on
         the bright one, <b>128</b> on the background; <code>prepaint=0</code> is flat 128.</p>
      <p class="muted small">Arguments: <code>source</code>, <code>prepaint</code> 0–100%,
         <code>radius</code> (local reference), <code>denoise</code>, <code>prompt</code>,
         <code>group</code>.</p>
    </div>
  </div>""",
)


PLUGIN_EN["ai-inpaint"] = dict(
    lede="""Frame an area, write one line of prompt, and your own <b>ComfyUI</b>
   (Stable Diffusion) does the rest: the plug-in crops the selection plus a ring of
   context, sends it with a mask, waits for the answer and pastes it back as a new layer.
   No account, no upload — 1024×512 comes back in about 9 seconds on a local GPU.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>What one click does</h3><span class="pill">five steps</span></div>
      <ol class="steps">
        <li>Grow the selection by <code>grow</code> (8 px by default, hides the seam) and take
            its bounding box plus context;</li>
        <li>Align the crop to <b>8</b> — the VAE downsamples 8×, and a crop that is not a
            multiple comes back truncated and pastes out of place — then pad the aspect
            ratio to <b>≤ 2:1</b> (see “four traps” below);</li>
        <li>Read those pixels from the <b>visible composite</b> (a layer smaller than the
            canvas gives you the layer below, not black) and post them with a mask PNG;</li>
        <li>Poll <code>/history</code> until the job is done;</li>
        <li>Load the result as a new layer directly above the original, offset back to where
            it came from, masked by the feathered selection.</li>
      </ol>
      <pre><code>AI Inpaint            new layer · feathered layer mask
  └─ original layer     untouched, toggle it to compare

With keep-mask on, an "AI Mask" channel is kept as well,
so you can re-limit the area later.</code></pre>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Keep the selection tight</h3><span class="pill">the usual trap</span></div>
      <p>Whatever the mask covers is what gets repainted — the model has no idea how big a
         pair of glasses should be on a face. Frame the whole forehead-to-cheek band and you
         get glasses covering half the head. Frame the strip where they belong, 8–16 px of
         slack on each side is plenty.</p>
      <p>The edges do not need to be precise: <code>grow</code> expands the mask and
         <code>feather</code> (4 px by default) blends the pasted result back in.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Three boxes</h3><span class="pill">that is the simple version</span></div>
      <p><b>Prompt — what should be there.</b> Describe the <b>result</b>, not the action:
         to remove a bottle write <code>empty wooden table, wood grain</code>, not
         <code>remove the bottle</code>. Common Chinese words are fine — the plug-in
         translates them first; SD itself only reads English, so raw Chinese is just noise
         to it.</p>
      <p><b>What to paint (preset) — a subject drop-down.</b>Cat / dog / person / flower /
         tree / coffee / food / car. Pick one and the prompt only needs the details
         (colour, pose, surroundings).</p>
      <p><b>Negative prompt — what must not appear.</b>The default already leans photo:
         <code>illustration, cartoon, flat graphic, poster, vector art, cgi</code>. This is a
         retouching plug-in, so the model is told not to drift into vector art; change the
         line if you want a stylised result.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>The parameter dialog</h3></div>
      <p>GIMP 3 does not build a dialog for a plug-in — the plug-in has to. This one calls
         <code>_shared/lb_dialog.py</code> from <code>run()</code>: interactive runs get a
         dialog, cancel really cancels, and batch runs or “last values” pass straight
         through instead of silently running with defaults.</p>
      <p class="muted small">Every plug-in in this project learned it the hard way: without a
         dialog of your own, every parameter is invisible and the defaults always win.</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>What the advanced version adds</h3><span class="pill">change on demand</span></div>
    <div class="table-wrap"><table class="op-table">
      <thead><tr><th>Parameter</th><th>Default</th><th>When to touch it</th></tr></thead>
      <tbody>
        <tr><td><code>server</code></td><td>empty</td>
            <td>ComfyUI is not on 127.0.0.1:8188; empty reads <code>$LB_COMFY_URL</code></td></tr>
        <tr><td><code>checkpoint</code></td><td>automatic</td>
            <td>Dropdown filled by asking ComfyUI; “automatic” is the first non-inpaint model</td></tr>
        <tr><td><code>steps</code></td><td>25</td>
            <td>More for finer texture; little gain past 25–30</td></tr>
        <tr><td><code>cfg</code></td><td>7.5</td>
            <td>How literally to follow the prompt. Too high goes hard and repeats shapes</td></tr>
        <tr><td><code>seed</code></td><td>-1</td>
            <td>To reproduce a result, paste the seed from the previous run's message</td></tr>
        <tr><td><code>denoise</code></td><td>1.0</td>
            <td><b>Keep 1.0 when adding something new</b>; lower only to keep the structure</td></tr>
        <tr><td><code>grow</code></td><td>8</td>
            <td>How far to expand the selection before sending — raise it if a seam shows</td></tr>
        <tr><td><code>grow-mask-by</code></td><td>8</td>
            <td>Extra pixels the model may touch (8 px = one latent cell); more = fewer seams, more drift</td></tr>
        <tr><td><code>feather</code></td><td>4</td>
            <td>Feather radius of the layer mask used when pasting back</td></tr>
        <tr><td><code>timeout</code></td><td>600</td>
            <td>How long to wait for ComfyUI; raise it for CPU fallback on big images</td></tr>
        <tr><td><code>keep-mask</code></td><td>on</td>
            <td>Keep the “AI Mask” channel, or turn it off for a clean result</td></tr>
        <tr><td><code>scale</code></td><td>0</td>
            <td>0 = send at the model's comfy size (SD1.5 512 / SDXL 1024); 1.0 = send as is</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Four traps</h3><span class="pill">all worked around</span></div>
      <p><b>1. The mask is inverted.</b>ComfyUI's <code>LoadImage</code> derives the mask
         from alpha (<code>mask = 1 - alpha</code>), so “repaint here” has to be
         <b>transparent</b>. Send a grey image and you get an all-zero mask — the run finishes
         and not one pixel moves.</p>
      <p><b>2. Align to 8.</b>A crop whose sides are not multiples of 8 gets truncated, comes
         back smaller than requested and pastes out of place.</p>
      <p><b>3. Inpaint-only checkpoints ignore the prompt.</b>A 9-channel model on
         ComfyUI's <code>VAEEncodeForInpaint</code> path only flattens the masked area and
         leaves a pale rim. The workflow uses a plain checkpoint, and the dropdown labels
         inpaint-only models so you can avoid them.</p>
      <p><b>4. Aspect ratio.</b>SD only draws well near the ratios it was trained on. A
         1024×400 (2.56:1) strip across the eyes makes SDXL fall back to flat poster art — a
         prompt of <code>sunglasses</code> came back as a green board with repeated white
         arrows. <code>plan_canvas_rect()</code> pads to ≤ 2:1 first, growing into real
         pixels where the image allows and only replicating edges at the border; that ring is
         masked out when pasting back.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>AI Environment</h3><span class="pill">any folder</span></div>
      <p><b>AI Environment…</b> opens with the state: reachable or not, which version, how
         many checkpoints — and <b>where ComfyUI lives and which python it runs</b>. If the
         path is wrong, <b>Choose folder…</b> picks it by hand (the folder holding
         <code>main.py</code>, or the wrapper folder holding <code>ComfyUI/</code>); the
         choice is saved, so you only do it once.</p>
      <p><b>Start</b> / <b>Stop</b> manage the process the plug-in started,
         <b>One-click install…</b> sets everything up the first time (about 10 GB: embedded
         Python + torch cu128 + ComfyUI + one checkpoint), <b>Model folder</b> opens
         <code>models\\checkpoints</code>, <b>Refresh</b> re-probes and shows the log tail.</p>
      <p>“Start ComfyUI automatically when it is not running” is on by default: before an AI
         pass the plug-in probes <code>/system_stats</code>, and if nothing answers it starts
         the server <b>in the background</b> from the folder you picked (no console window,
         output to <code>comfyui.log</code>) and waits for it. Only an explicitly chosen
         folder is used — never a guess: guessing once meant launching someone else's
         ComfyUI with the wrong Python.</p>
      <p class="muted small">Config: <code>%APPDATA%\\SuperMrWang\\comfyui.json</code> on
         Windows, <code>~/.config/SuperMrWang/comfyui.json</code> elsewhere. The installer
         ships with the plug-in, in the <code>ai-setup/</code> folder of the zip.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Measured</h3><span class="pill">check_ai_inpaint*.py</span></div>
      <p><code>tools/check_ai_inpaint.py</code> runs <b>168 assertions</b> against a local
         mock service (no GPU needed): mask direction, 8× alignment, canvas padding, scale
         limits, checkpoint family detection, workflow nodes and wiring, Chinese-to-English
         prompt handling, failure paths.</p>
      <p><code>tools/check_ai_inpaint_gimp.py</code> runs the procedure inside real GIMP 3.2:
         selection → prompt → new layer, mask and channel, and a bogus checkpoint name being
         rejected by the dropdown.</p>
      <p>Speed (RTX 3070 Ti, SDXL, 25 steps, 1024×512): <b>8.7 s</b>. The same size on CPU
         fallback is <b>94 s</b> (measured at 384×256) — it works, but not for batches.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Requirements</h3></div>
      <p>A running ComfyUI and one checkpoint. The plug-in uses only the standard library
         over HTTP — no Python dependencies; the HTTP and PNG code lives in
         <code>plugin/_shared/ai_client.py</code>, and the regression suite swaps the real
         service for <code>tools/mock_comfy.py</code>.</p>
      <p>Chinese UI is complete for this plug-in: menus, the parameter dialog and the status
         messages are all translated in <code>po/zh_CN.po</code>.</p>
    </div>
  </div>""",
)

PLUGIN_EN["warp"] = dict(
    lede="""The pose is slightly off, the arm a bit short, the cup knocked crooked — none of
   that deserves pixel-by-pixel liquify. Drop a few pins on the layer, drag the pins and
   the picture follows: smooth in between, and byte-for-byte untouched far away.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>How it works</h3><span class="pill">click, drag, right-click</span></div>
      <p>Pick a layer → menu → <b>click once on the picture to place a pin</b> (holding
         the button drags it right away); <b>drag a pin</b> and the pixels follow;
         <b>right-click a pin</b> to delete it, or select it and press Delete. How far a
         pin reaches is set by <b>Falloff</b>; outside that circle the layer is left alone
         completely — not even resampled.</p>
      <p>Three solvers. <b>Rigid (MLS similarity)</b> allows only rotation and uniform
         scale, so square corners stay square — best for moving something around.
         <b>Free (MLS affine)</b> adds shear and stretch: good for lengthening, bad for
         faces. <b>ARAP</b> solves “as rigid as possible” on a mesh, so <b>a big bend does
         not squash the patch</b> — the closest to Photoshop's behaviour.</p>
      <p>ARAP needs numpy (see “GIMP's own Python and numpy”); without it the entry is not
         in the dropdown. It also ignores Falloff — the slider greys out when you pick it.</p>
      <p>Two outputs: <b>replace this layer</b>, or <b>copy to a new layer</b> so the
         original stays around for comparison.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Works without a mouse, too</h3></div>
      <p>The pins are a procedure argument, <code>pins</code>, written as
         <code>sx,sy,dx,dy; sx,sy,dx,dy</code> (where a pin was placed → where it was
         dragged, in layer pixels). Semicolons and newlines both separate; two numbers
         mean “placed but not dragged”. Pressing Apply writes exactly that string back
         into the config and runs the same code, so a script can reproduce a manual warp
         step for step:</p>
      <p><code>lb-plugin-puppet-warp layer pins="100,200,140,200; 300,400,300,430"
         mode=rigid radius=30</code></p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>How it is computed</h3><span class="pill">MLS + ARAP</span></div>
    <p>The first two modes are <b>MLS</b> (moving least squares): each pixel gets weights
       from its distance to every pin, then a least-squares affine is solved that maps
       “where the pin was” onto “where the pin is now”. Interpolation at the pins is exact
       and the field is smooth. The third is <b>ARAP</b>: on a 48×37 mesh it minimises
       Σ｜(xᵢ-xⱼ) - Rᵢ(vᵢ-vⱼ)｜², alternating a local step (best rotation per vertex) with a
       global Laplacian solve until it converges.</p>
    <p>Five things have to be right or the picture quietly goes wrong:</p>
    <p><b>① MLS is global, so it needs a cutoff.</b> With 1/d² weights the far field is
       still a perfectly good affine — the whole image drifts slightly (measured: corners
       moved 0.7 px). Every pixel is therefore multiplied by a smoothstep window measured
       from the nearest pin; outside it the map is the identity.</p>
    <p><b>② Solve on a grid, not per pixel.</b> Solving 8 pins per pixel at 768×1024 takes
       ten-odd seconds. Solving on a grid of 140 nodes along the long edge and bilinearly
       interpolating the offsets costs 0.02 px of accuracy.</p>
    <p><b>③ A row is skipped only when its displacement is exactly zero</b> — not “under
       0.5 px”. Nodes are 7 px apart, so a 0.5 px threshold silently drops the 0.504 px
       displacements between nodes: invisible in pure Python, but it makes 20 000+ pixels
       differ from the per-pixel numpy path.</p>
    <p><b>④ ARAP pins must be hard constraints.</b> Adding them to the Laplacian with a big
       weight looks simpler, but their total force is non-zero and the nullspace of L is
       the constant vector, so the solver lifts the whole mesh into a uniform translation
       — measured: the entire picture translated to the pin offset, zero deformation.</p>
    <p><b>⑤ ARAP only measures edge lengths, so it needs a weak anchor.</b> “Rotate the
       whole mesh rigidly” is a zero-energy solution; with a single pin the picture just
       spins (measured: median displacement 44 px). A 0.06 spring pulls every vertex back
       home — it costs nothing when the vertex is already there, so it does not fight the
       deformation.</p>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p>768×1024 layer, two pins, falloff 25 %: full-resolution warp in <b>0.15 s</b>
         including buffer read and write (with numpy). The preview runs at a 520 px long
         edge — <b>58 ms</b> per redraw, which keeps up with the hand.</p>
      <p>On a 1600×2400 photo a local drag costs <b>0.7 s</b>; resampling everything
         (falloff 100 %) takes <b>1.2 s</b>. Pure-Python fallback: 2.4 s / 6.2 s. The ARAP
         mesh is factored once (24 ms); dragging then costs about 20 ms per frame.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Where it differs from Photoshop</h3></div>
      <p><b>Has:</b> draggable pins, rigid / free / ARAP modes, falloff, mesh overlay, right-click
         delete, live preview, a non-interactive pin argument. <b>Does not have:</b>
         Photoshop's depth (pins in front of / behind each other) and the Alt-drag rotation
         handle — for big rotations, rotate the layer instead.</p>
      <p>Layer groups, text and vector layers are refused with a plain sentence (they have
         no pixels of their own) instead of a GIMP-internal error.</p>
    </div>
  </div>""",
)

PLUGIN_EN["mesh-warp"] = dict(
    lede="""Puppet warp pulls the content around; this one puts a free-form surface over
   it. A Bezier grid is laid on the layer: drag a grid point to change the shape, select
   a point to reveal its handles, drag a handle and the grid line bends into a curve —
   which is how a bulge, a waist or a flipped edge becomes possible at all.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Using it</h3><span class="pill">points, then handles</span></div>
      <p>Pick a layer → menu → <b>drag a grid point</b> and the picture deforms. Click a
         point to select it: <b>four small dots</b> appear around it — the two ends of its
         handles (symmetric, either end drags the same). Drag one and the grid line bends.</p>
      <p><b>Right-click a point</b> to reset it; Delete does the same for the selected one,
         and the sidebar has <i>Reset selected</i> / <i>Reset all</i>. <b>Grid density</b>
         goes from 2×2 to 6×6 cells — Photoshop's default is 3×3. When that is not
         enough, <b>Alt+click</b> to add lines of your own (below).</p>
      <p>The dashed lines are the original grid, the blue ones the deformed grid, so the
         amount of movement is obvious. Output either <b>replaces the layer</b> or
         <b>copies to a new one</b>.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>From a script</h3></div>
      <p>The mesh is the <code>mesh</code> argument: the cell counts first, then six (or
         seven) numbers per grid point, row by row —
         <code>x,y,ux,uy,vx,vy,auto</code>: position, the two handle vectors, and 1/0 for
         “handle derived from the neighbours” vs “dragged by hand”. Two numbers are enough
         (position only), the rest of the lattice stays identity:</p>
      <p><code>lb-plugin-mesh-warp layer mesh="3,3; 100,200; 150,180" output=replace</code></p>
      <p>The dialog writes exactly this string when you press Apply, so a script can
         replay a manual warp.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Adding your own split lines</h3><span class="pill">Alt + click</span></div>
      <p>When dragging points is not enough, <b>hold Alt and click on the picture</b> and a
         grid line appears right there — its direction follows whichever line is nearest
         (a vertical one means a new vertical line). The density drop-down switches to
         <b>custom</b>, because the cells are no longer square. Twelve lines is the cap.</p>
      <p>That is what Photoshop's Alt+drag on a grid line does: <b>local refinement</b>.
         Split column one in half and column three stays whole — the grid does not get
         denser everywhere.</p>
      <p>A grid with added lines writes two extra chunks into the <code>mesh</code>
         argument, <code>u:0,1.33,1.83,2.67,4</code> and <code>v:…</code>, holding each
         line's position in parameter space. Older strings have no such chunks and read back
         as evenly spaced.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>What one line costs</h3></div>
      <p>The breaks are no longer even, but <b>parameter space still maps linearly to the
         original image</b> — which pixel comes from where does not change, only the
         interpolation. The new line takes its points and tangents from the existing
         surface, so the picture barely moves: at a mild deformation (±10 px) the measured
         surface deviation is <b>0.6 px</b> and the whole offset field differs by
         <b>0.4 px</b>.</p>
      <p>Under heavy deformation it becomes a <b>refit</b> (2–5 px at ±60 px). Each corner
         only stores a position and two tangents, so the twist of the four middle control
         points is estimated from the corners; after splitting, the two sides disagree.
         Photoshop stores the whole control net, so its subdivision is exact — a difference
         in representation, not a bug.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Three easy mistakes when adding a line</h3></div>
      <p><b>1. The parameter range has to follow the column count.</b> Source coordinates go
         as <code>u/cols</code>, so adding a column means scaling the whole axis by
         (cols+1)/cols — miss it and the picture shifts once.</p>
      <p><b>2. Tangents must be divided by that same factor.</b> A tangent is a derivative
         per parameter unit; shorter units mean a smaller derivative for the same pixel
         span.</p>
      <p><b>3. Handle dots scale with cell width.</b> With unequal cells a handle sits at
         "node ± tangent × cell / 3". Writing "± tangent / 3" makes handles in narrow cells
         stick out into the neighbour, and dragging is off by one notch.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p>Adding a line is O(nodes) — instant. The preview still runs at a 480 px long edge,
         around 100 ms a frame; one more line adds a few patches, not a change in feel.</p>
      <p>The regression watches one thing: the picture must not move. An identity grid with
         an added line still has to classify as identity (not one pixel resampled), the new
         line's points must land on the existing surface (measured 0.00e+00 px), and the two
         offset fields must agree within 0.5 px per node.</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>How it is computed</h3><span class="pill">FFD, bicubic Bezier patches</span></div>
    <p>The textbook name is <b>FFD</b> (free-form deformation): each cell is a
       <b>bicubic Bezier patch with 16 control points</b> mapping (u,v) to image
       coordinates. The corners are the grid points, the eight edge control points are
       “point ± tangent/3” — three units of handle is exactly one control point, which is
       also why Photoshop draws the handle that far out.</p>
    <p>The warp runs backwards: for every destination pixel p, <b>Newton</b> solves
       P(u,v) = p; the source coordinate is then <b>the position of (u,v) on the original
       lattice</b>, handed to the resampler. The field is solved on a raster (140 nodes on
       the long edge) and then goes through the very same <code>warp_rgba</code> as puppet
       warp — one resampler for both tools.</p>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Three things that quietly break it</h3></div>
      <p><b>1. The source coordinate is the uv on the original lattice, not a point on the
         surface.</b> The surface only answers “which uv lands on this pixel”; the source
         image stays laid out at its own size. Get this wrong and the whole picture shifts
         once — it looks like a misalignment, not a maths bug.</p>
      <p><b>2. The four inner control points need the twist term.</b> With only “± tangent/3”
         even an identity grid comes out bent at the cell centre — the surface is no longer
         a plane. Adding (P11-P10-P01+P00)/9 makes the identity field exactly zero.</p>
      <p><b>3. The handles must be auto-limited.</b> Drag the middle point 80 px and the
         right cell keeps a 66 px tangent on a 26 px chord: the control polygon folds back,
         the cell self-intersects, the inverse has two branches and the picture tears. So
         moving a point re-derives the tangents from its neighbours and clamps them to the
         shorter adjacent chord.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>…and two more</h3></div>
      <p><b>4. Newton needs a step limit.</b> Where the surface is squashed the local
         derivative is tiny, one step crosses a whole cell, lands where the derivative is
         large and jumps back — measured as endless oscillation on cell boundaries, ending
         12 px off. Limiting a step to 0.75 cell fixes it.</p>
      <p><b>5. Changing the grid density is a re-fit, not lossless.</b> Denser is invisible
         (3→6 cells: 1.6 px); sparser visibly changes the shape — a 2×2 grid only has one
         cell to work with. Pick the density first, then drag.</p>
      <p>Handles are <b>symmetric</b>: a point's tangent is shared by the cells on both
         sides, which keeps the surface C1 across cell borders. Sharp corners are not
         possible (Photoshop drags its handles in pairs too).</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p>768×1024 layer, one point dragged plus one handle bent: <b>0.41 s</b> including
         buffer read and write. 1600×2400 end to end: <b>1.3 s</b> (field 150 ms,
         resampling 1.16 s).</p>
      <p>This warp is <b>global</b>: move one point and every pixel needs resampling. The
         preview therefore runs at a 480 px long edge, about <b>95 ms</b> per redraw —
         slower than puppet warp (520 px, only a patch resampled). That is the cost, not a
         missing optimisation.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Where it differs from Photoshop</h3></div>
      <p><b>Has:</b> grid points with Bezier handles, 2×2 to 6×6 density, Alt+click to add
         split lines of your own, a dashed original grid for reference, live preview and a
         scriptable mesh. <b>Does not have:</b> Photoshop's warp presets (arc / flag /
         fisheye), nor splitting / merging cells into a new topology (adding a line is a
         refit, not the exact subdivision Photoshop gets from storing the whole control
         net), nor the depth ordering that puppet warp itself lacks.</p>
      <p>Useful references: <b>Krita's Warp transform</b> uses the same kind of bicubic
         surface mesh, while <b>GIMP's own Warp Transform</b> is the push/pull brush. Both
         are worth comparing against.</p>
    </div>
  </div>""",
)

PLUGIN_EN["vanishing-point"] = dict(
    lede="""This one does not drag pixels around. It marks **a plane that has perspective**
   on the picture: drag out a quadrilateral and it stands for a rectangle in the 3D world.
   The grid is laid out at even spacing in world units, so it converges to the vanishing
   points by itself. Once the plane is marked you can use it in either direction — paste
   the whole picture into it, or rectify that patch back to a flat rectangle. You can also
   **fold the plane into steps** and have one picture run continuously up them.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Using it</h3><span class="pill">drag one quadrilateral</span></div>
      <p>Pick a layer → menu → <b>drag a quadrilateral</b> on the picture. That is a plane.
         Drag its four corners until it sits on a real wall, floor or tabletop — it does not
         have to be exact, the grid shows you how far off you are.</p>
      <p>With a plane selected, every edge carries a <b>little triangle at its midpoint</b>;
         drag it to grow a neighbouring plane from that edge. Two directions:
         <b>perpendicular</b> (Photoshop's wall-next-to-wall) and <b>in the same plane</b>
         (the same wall, further along). The new plane's depth lines point at the
         perpendicular vanishing point automatically, so it joins up without hand-tuning.</p>
      <p>Two jobs on the right: <b>paste into the plane</b> lays the whole layer onto the
         quadrilateral, leaving everything outside untouched; <b>rectify</b> does the
         opposite and unfolds that patch into a flat rectangular layer — how you rescue a
         poster, street sign or business card shot at an angle.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>From a script</h3></div>
      <p>The mesh is the <code>planes</code> argument: eight numbers per plane, four corners
         in the order top-left, top-right, bottom-right, bottom-left, planes separated by
         <code>|</code>. The <b>first</b> one is the one that acts; the rest are kept so the
         dialog can read them back next time.</p>
      <p><code>lb-plugin-vanishing-point layer|<br>
         &nbsp;&nbsp;planes="100,120,900,80,1020,700,60,780" mode=paste output=replace</code></p>
      <p>Six numbers are enough too — the fourth corner is completed as a parallelogram.
         Pressing Apply writes the plane string back into this argument, so a script can
         replay a hand-dragged plane exactly.</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>How it is computed</h3><span class="pill">homography + orthocentre</span></div>
    <p>The four corners map to world (0,0)/(1,0)/(1,1)/(0,1); eight parameters, one 8×8
       linear system, and you have a <b>homography</b> H. Everything after that is H used
       forwards or backwards:</p>
    <p>· <b>Grid</b> — evenly spaced world lines s = k/N, projected one by one. So the grid
       really is evenly spaced in the world: wide near the camera, tight far away, converging
       to the vanishing points. It is not decoration.<br>
       · <b>Paste</b> — the source image's four corners map to the plane's four corners;
          every destination pixel is solved back to a source coordinate.<br>
       · <b>Rectify</b> — the reverse: each output pixel's (s,t) goes through H to find the
          source.</p>
    <p>The second wall rests on one fact of projective geometry: <b>the vanishing points of
       three mutually perpendicular directions form a triangle whose orthocentre is the
       principal point</b> (the centre of the frame). So from a plane's own two vanishing
       points the third direction follows with no camera intrinsics and no focal length —
       the only assumption is that the principal point is in the middle.</p>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Folding it into steps</h3><span class="pill">one picture, continuous</span></div>
      <p>Tick <b>fold into steps</b> and the plane folds along one edge into n treads and
         risers, with the picture running <b>continuously</b> up them — one copy folded over,
         not one copy per step. Choose the <b>edge</b> the fold starts from (far / near /
         right / left), the <b>count</b> (1–24), the <b>riser</b> and the <b>run</b>, both as
         fractions of the plane. Run 0 means "auto" = 1/count, which fills the plane exactly.
         A riser around half the run reads like a real staircase.</p>
      <p>From a script: <code>stairs="edge,count,riser,run,flip"</code>, for example
         <code>stairs="0,6,0.075,0,0"</code>; an empty string means no fold. Apply writes the
         string back into the argument.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why it has to be real 3D</h3><span class="pill">one plane solves the camera</span></div>
      <p>The first attempt tried to be cheap: stitch a few quadrilaterals together into a
         staircase. The higher the step, the worse the drift — by step six the edge was off
         by a dozen pixels. Raising something by one side length is not "move it down a few
         pixels" in perspective; it is a step along the <b>third axis</b>.</p>
      <p>So the camera is solved instead. A plane with perspective pins the whole pinhole
         camera: principal point at the centre of the frame, square pixels, orthogonal
         vanishing points, therefore <code>f² = −(Vu−O)·(Vv−O)</code> gives the focal length
         uniquely. Then <code>b = K⁻¹·p</code> brings three corners into camera space,
         normalising them gives the rotation <code>R</code>, <code>n = r1×r2</code> is the
         normal and <code>eye = −Rᵀ·b3</code> the position. <b>The unit of z</b> is the
         geometric mean of the two side lengths — <code>b</code> already carries length,
         it is not a pure direction (getting this wrong once put the 3D projection off by
         278 px).</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Three traps in the fold</h3></div>
      <p><b>1. A quad without perspective cannot yield a focal length.</b> When both pairs of
         edges are parallel (a rectangle shot head-on), it falls back to
         <code>f = 1.5 × long side</code> and the status line says approximate. The riser in
         the middle is then <b>edge-on</b> to the camera and collapses to a line — it has to
         be dropped, or you get a white seam and a singular homography that aborts.</p>
      <p><b>2. The picture comes out upside down.</b> Source row 0 lands on the <b>nearest</b>
         step (v accumulates along the stairs), so a poster has to be flipped first. Found by
         looking at the render, not by reading the code.</p>
      <p><b>3. Steps occlude themselves.</b> A standing riser hides the tread behind it, so the
         sampling test has to use "the last face that covers this pixel" — otherwise the
         regression reports a mismatch that is not there.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p>1600×2400 with 16 faces: <b>1.54 s</b>. Preview at a 560 px long edge, 16 faces:
         <b>172 ms</b> per redraw, which keeps up with dragging. All faces share one
         destination buffer (<code>arr</code> / <code>sarr</code> are built once), otherwise
         every face rebuilds 17 MB.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Three things that quietly break it</h3></div>
      <p><b>1. The homography must be solved on Hartley-normalised points.</b> Feeding raw
         pixel coordinates (thousands) into an 8×8 system puts the condition number near
         1e8, and plain Gaussian elimination only lands at 1e-3 — nudge one corner and the
         paste is misaligned. Normalising to "centroid at the origin, mean distance √2"
         brings the residual back to 1e-13.</p>
      <p><b>2. Grid lines must break where the homogeneous denominator changes sign.</b>
         Extending the world outward makes w cross zero; past that point you are looking at
         the image <i>behind the horizon</i>, and joining it to the previous points draws a
         bogus line straight across the picture — it looks like the frame has been torn.</p>
      <p><b>3. The third vanishing point is not "the intersection of the other pair of
         edges".</b> Doing that returns the same vanishing point you started with and the
         wall lands on top of itself. It has to be the orthocentre relation.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>…and two more</h3></div>
      <p><b>4. The two far corners of a grown plane must not share one t.</b> Writing both
         as <code>p + t·(V−p)</code> makes the new plane's two edges exactly parallel and
         sends its u vanishing point out past 1e16 — perspective thrown away. The correct
         construction: q0 sits on p0's ray, and q1 comes from intersecting "on p1's ray"
         with "q0q1 passes through the shared edge's vanishing point".</p>
      <p><b>5. Paste has a hard edge; rectify has a dirty one.</b> Paste leaves the outside
         untouched, so the border is a clean cut. Rectify puts its first row exactly on the
         quadrilateral's edge, where bilinear sampling mixes in a little of the outside —
         measured at 3 levels, invisible to the eye, but the regression has to skip 6 px at
         the border or it reports a false failure.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p>768×1024 layer: paste <b>127 ms</b>, rectify <b>71 ms</b>. 1600×2400: paste
         <b>635 ms</b>, rectify <b>356 ms</b>. Slower than puppet warp because the whole
         plane is resampled — but only the plane's bounding box is touched, which halves the
         work compared with a full-frame perspective transform.</p>
      <p>The preview runs at a <b>560 px long edge</b>, about <b>75 ms</b> per redraw, which
         keeps up with the drag. The pure-Python path is roughly 4× slower (one second at
         1200×900) and only runs when numpy is missing.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Where it differs from Photoshop</h3></div>
      <p><b>Has:</b> quadrilateral planes, a grid that converges to the vanishing points,
         growing a neighbouring plane from an edge (perpendicular or continuing), paste into
         the plane, rectify to a new layer, folding the plane into n steps with the picture
         running continuously over them.<br>
         <b>Does not have:</b> Photoshop's most-used trick — cloning and painting <i>on</i>
         the plane with the stroke following the perspective. That needs a GIMP paint tool
         subclass and is a job of its own — same for painting on the steps. Also no 3D
         export, and planes do not snap to each other's vanishing points (you align them by
         dragging corners). The fold is <b>single-segment</b> (n steps in one direction);
         Photoshop lets you draw several segments inside one plane and turn corners, which
         is not done here.</p>
      <p>Worth comparing against: <b>Krita's perspective assistants</b> are the same idea but
         only draw guides, they do not transfer images. The textbook name for the transfer
         itself is <b>homography-based image transfer</b>.</p>
    </div>
  </div>""",
)


PLUGIN_EN["layer-style"] = dict(
    lede="""Photoshop's Layer Styles, the whole set: drop shadow, inner shadow, outer and
   inner glow, bevel and emboss, satin, colour / gradient / pattern overlay and stroke. Tick an
   effect, drag a slider, the picture follows. Nothing gets baked into pixels — you get a group of
   layers you can still select, hide and fade one by one.""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Ten effects, one panel</h3><span class="pill">10</span></div>
      <p><b>Drop / inner shadow</b>: colour, opacity, angle (optionally following the global
         light), distance, spread / choke, size, one of 12 preset contours, noise. <b>Outer /
         inner glow</b>: solid colour or gradient, softer or precise technique, spread, size,
         range; the inner glow can radiate from the edge or from the centre.</p>
      <p><b>Bevel and emboss</b>: outer bevel / inner bevel / emboss / pillow emboss / stroke
         emboss, smooth / chisel hard / chisel soft, depth, direction, size, soften, altitude,
         with separate highlight and shadow colours and blend modes. <b>Satin</b>: angle,
         distance, size, invert.</p>
      <p><b>Colour / gradient / pattern overlay</b>: 26 blend modes; gradients can be linear,
         radial, angled, reflected or diamond, reversed, aligned to the layer. <b>Stroke</b>:
         outside / inside / centre, width measured as an exact distance (not a blur), filled
         with a colour, a gradient or a pattern.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>The result is real layers</h3><span class="pill">non-destructive</span></div>
      <p>Applying creates a group called <code>layer name (layer style)</code> and moves the
         original layer into the middle of it: <b>drop shadow and outer glow go underneath it</b>,
         <b>inner shadow, inner glow, stroke, the three overlays and the bevel go on top</b>. That
         is Photoshop's stacking order, so a semi-transparent layer lets its shadow show through
         and an inner shadow only presses on the inside edge — no extra masking needed.</p>
      <p>Run it again after changing a slider and the old effect layers inside the group are
         replaced; the original layer is never touched and nothing piles up. Every effect layer is
         an ordinary RGBA layer: switch it off, fade it, give it its own mask.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Copying a style: one string of code</h3>
        <span class="pill">copy / paste</span></div>
      <p>Photoshop does it with right-click → Copy Layer Style, then Paste Layer Style on the
         target. GIMP has no host concept of a style attached to a layer, so here it is a
         string: expand <b>Style code</b> at the bottom of the dialog and you get the current
         style as JSON (indented, pure ASCII). <b>Copy code</b> takes it away;
         <b>Paste and load</b> in the other layer's dialog reads the clipboard, or paste into
         the box yourself and press <b>Load this code</b>. Sliders, checkboxes and the preview
         all follow, and Apply then gives that same style.</p>
      <p>The string holds every parameter and no hidden state: out-of-range numbers are
         clamped to the limit, colours written 0–255 are divided by 255, unknown effect names
         are ignored with a note — so codes from an older version or another machine still
         load. It is exactly the PDB's <code>style</code> argument, so scripts replay it with
         no second format to keep in sync.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>The style travels with the layer</h3>
        <span class="pill">stored in the XCF</span></div>
      <p>After applying, that JSON is attached to the layer and the group as a
         <b>parasite</b>: it is saved in the XCF and rolls back with undo. So opening Layer
         Style on that layer again shows <b>the values you last used</b>, not the defaults —
         without that step the copy feature would only ever copy the defaults, which is the
         same as not having it.</p>
      <p>To cover many layers with one style: copy on the source layer, then paste once per
         target. Sizes are document pixels, so pasting onto a differently sized layer keeps
         the numbers as they are — same as Photoshop.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>Where it differs from Photoshop</h3></div>
      <p><b>There:</b> all ten effects, 26 blend modes, global light, 12 contours,
         spread / choke, knockout (none / shallow / deep), "blend if: this layer" with both
         softness handles, live preview.</p>
      <p><b>Not there:</b> texture (pattern bevels), 3D materials, a custom contour editor,
         "blend if: underlying layer", rotating the pattern (Photoshop cannot either), and
         dragging shadow handles straight on the canvas.</p>
      <p>In this version the style is not an object hanging off the layer, so changing a parameter
         means running the plug-in again (Photoshop reopens the panel at any time). The values
         themselves are remembered on the layer, so a re-run starts from what you last applied —
         and one good style can be pasted onto the rest. For "parameters editable at any time,
         pixels untouched", see the live filter below.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why GIMP is handed plain "normal" layers</h3></div>
      <p>GIMP 3's default blend modes work in <b>linear light</b>: measured, 50% of 204 over 51
         gives <b>153</b>, while Photoshop blends sRGB values and gives <b>128</b>. Hang MULTIPLY
         or SCREEN straight onto an effect layer and edges and midtones come out too bright, with
         soft edges glowing.</p>
      <p>So the plug-in <b>blends first, in the colour itself</b>, and every layer is
         <code>NORMAL_LEGACY</code> (a plain sRGB over). Cross-checked against GEGL: maximum
         channel difference in solid areas <b>0.6/255</b>, mean <b>0.12/255</b> — the same
         picture. The cost is that an effect layer's colour carries a trace of what was under it,
         so dragging the layer would smear; layer styles are not meant to be dragged anyway.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>Measured</h3></div>
      <p>768×1024 with six effects on: <b>1.7 s</b>, including 14 full-frame composites. The
         560-pixel preview runs a frame in <b>60–100 ms</b>, so sliders keep up. Stroke and bevel
         use an exact signed distance field rather than a blur, so the same number gives the same
         thickness on a soft edge and a hard one.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Scriptable</h3></div>
      <p>The whole style is one JSON string argument, <code>style</code>, and the dialog writes
         exactly what it applied, so a script can replay it. Gradients and patterns come from
         GIMP's current gradient and pattern.</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>The other way to get the same styles: a live filter</h3><span class="pill">non-destructive</span></div>
      <p>This page describes the <b>destructive</b> route: the effects are computed once and
         become layers, the original pixels are replaced, and the parameters are only remembered,
         never re-applied. The repository also ships a GEGL op,
         <code>lb:layer-style</code> (different menu:
         <code>SuperMrWang → Layer → Layer Style (live)…</code>), which attaches the same engine
         as a <b>layer filter</b>: sliders recompute live, the eye icon switches it off, the
         parameters are saved in the XCF, and the pixels are never written to.</p>
      <p>Both have their use. Want to keep tweaking, or reopen the file next month and adjust?
         Use the filter. Want ten separate effect layers you can mask, fade and paint on? Use
         this one. The filter version cannot reach GIMP's pattern library (a GEGL process cannot
         see GIMP resources), so patterns are six procedural kinds and gradients are two
         colours.</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>Why it is not one code base</h3></div>
      <p>GIMP 3's non-destructive editing <b>only understands GEGL operations</b>: the filter
         stack stores an operation name plus property values, so it has to be a C module. A
         Python plug-in can only read and write pixels; any number of groups is still a baked
         result.</p>
      <p>Both implementations share the same formulas
         (<code>plugin/_shared/layer_style.py</code> is the reference the C version was checked
         against): mean difference in solid areas <b>0.45/255</b>, p99 <b>5.0</b>.</p>
    </div>
  </div>""",
)
