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
      <div class="dl-head"><h3>AI Environment</h3><span class="pill">no ComfyUI yet?</span></div>
      <p><b>AI Environment…</b> opens with the state: reachable or not, which version, how
         many checkpoints — and four buttons: <b>Start ComfyUI</b>, <b>One-click install…</b>
         (about 10 GB the first time: embedded Python + torch cu128 + ComfyUI + one
         checkpoint), <b>Model folder</b> (opens <code>models\\checkpoints</code>),
         <b>Refresh</b>.</p>
      <p>The status line tells “not running” apart from “not installed” instead of just
         saying “cannot connect”. The installer ships with the plug-in, in the
         <code>ai-setup/</code> folder of the zip.</p>
      <p class="muted small">Why not one big zip: torch's CUDA wheels are 2.5 GB and a
         checkpoint 2–7 GB — that fails distribution licensing and nobody wants a 10 GB
         download.</p>
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
