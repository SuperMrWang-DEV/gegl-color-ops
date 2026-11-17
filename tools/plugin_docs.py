# -*- coding: utf-8 -*-
"""十个 Python 插件的页面数据。

plugins.html 的卡片与 plugins/<slug>.html 的文章正文都从这里来，改一处两边
一起变；正文来源是各插件源码与回归实测，数字都在 tools/check_*.py 里可复现。
"""

PAGES = [
    dict(
        key='selection',
        slug='layer-to-selection',
        title='Layer to Selection',
        tag=('选区', 't-mask'),
        count='图层 → 选区',
        menu='图层右键 → SuperMrWang → Layer to Selection',
        menus=['图层右键 → SuperMrWang → Layer to Selection',
               '选择 → SuperMrWang → Layer to Selection'],
        pdb='lb-plugin-layer-to-selection(\n    image, drawable, channel, invert, operation)',
        lede="""右键点一个图层，就把它转成当前选区。GEGL 算子跑完往往留下一张灰度图，
       它往后的用途多半是当蒙版——原生流程要点四步（复制 → 建通道 → 粘贴 →
       蒙版转选区），这里一步到位，而且彩色图层也能直接用。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>转什么内容</h3><span class="pill">五种通道</span></div>
      <p>可选 <b>Gray（亮度）/ R / G / B / Alpha</b>——彩色图层选 Gray 时按亮度算，
         不是 HSL 明度（纯红 ≈ 54/255，而不是 130）。黑白图层走零拷贝的通道切片
         快捷路径，不改动任何像素。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>怎么合进现有选区</h3></div>
      <p><b>替换 / 加 / 减 / 交</b>，与 GIMP 选区菜单一致；还能反相
         （选暗部而不是亮部）。已经有选区时不会丢，按你选的组合方式并进去。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>偏移图层</h3></div>
      <p>图层比画布小、带偏移也没问题：只在自己位置生效，界外不选中。图层组没有
         自己的像素，会明确报错并提示先合并。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两个 GIMP 3 的坑</h3><span class="pill">已绕开</span></div>
      <p><b>1. 临时通道会被选区截断。</b>shadow buffer 的 merge 遵守当前选区，
         所以读写临时通道前先 <code>Selection.none</code> 挂起、结束再恢复，
         否则通道只有选区内有内容。</p>
      <p><b>2. <code>Y' float</code> 不是亮度。</b>babl 的 Y' 对纯红给 0.51，
         那是 HSL 明度不是亮度，所以彩色图层的 Gray 走临时副本
         <code>desaturate</code>（LUMA），用完即删。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3></div>
      <p><code>tools/check_layer_to_mask.py</code> 23 条断言跑在真实 GIMP 3.2 里：
         灰度值、反相、偏移图层、彩色亮度、四个单通道、四种组合方式、
         以及有选区时结果不被截断。</p>
      <p>速度：直接读 array 的 C 级切片，100 万像素约 4 毫秒。</p>
    </div>
  </div>""",
    ),
    dict(
        key='channel',
        slug='layer-to-channel',
        title='Layer to Channel',
        tag=('通道', 't-mask'),
        count='图层 → 通道',
        menu='图层右键 → SuperMrWang → Layer to Channel',
        menus=['图层右键 → SuperMrWang → Layer to Channel',
               '选择 → SuperMrWang → Layer to Channel'],
        pdb='lb-plugin-layer-to-channel(\n    image, drawable, invert, name)',
        lede="""右键点一个图层，就把它变成一条新的 Alpha 通道，留档复用。恒为灰度：
       黑 = 不选中、白 = 完全选中、中间灰 = 部分选中。想拿它当蒙版，就在通道
       面板右键「通道到选区」（GIMP 原生）再回图层。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>恒为灰度</h3><span class="pill">语义明确</span></div>
      <p>彩色图层先按亮度转成灰度，黑白图层原样——然后把这些<b>灰度值写进通道</b>。
         没有「取 R 通道」这类选项：要的就是明暗，不给单色通道捣乱的机会。</p>
      <pre><code>通道值 = 该像素是否被选中
  黑 0     → 不选中
  中灰     → 部分选中
  白 255   → 完全选中</code></pre>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>名字与反相</h3></div>
      <p>默认沿用图层名，可以自己改——通道面板里一眼能认出来。可反相，
         建好后状态栏会提示通道名。</p>
      <p>想把它变回选区：通道面板右键该通道 → <b>通道到选区</b>（GIMP 原生），
         或者反过来用 Layer to Selection 直接从图层取。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么现成通道不行</h3></div>
      <p>复制粘贴能把灰度塞进通道，但会带上图层蒙版等<b>显示效果</b>，
         而且要先新建通道、再定位粘贴为选区，四步。这里读的是<b>原始像素</b>，
         一步，而且更快。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>实测</h3><span class="pill">23 条</span></div>
      <p><code>tools/check_layer_to_mask.py</code>：通道值、名字、反相、
         彩色转通道 = 亮度、半透明图按 alpha 加权、有活动选区时通道不被截断
         （写通道前先挂起选区，写完恢复）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>和 gray-mask 的分工</h3></div>
      <p><code>plugin/gray-mask</code> 走复制粘贴，会带上<b>显示效果</b>（蒙版、
         图层模式）；这两个插件读<b>原始像素</b>、不认显示效果，也更快。
         要「所见即所得」用 gray-mask，要「数据本身」用这两个。</p>
    </div>
  </div>""",
    ),
    dict(
        key='hsv',
        slug='hsv-split-curves',
        title='HSV Split (Curves)',
        tag=('曲线', 't-color'),
        count='H / S / V',
        menu='颜色 → SuperMrWang → Shortcut → HSV Split (Curves)',
        pdb='lb-plugin-hsv-split-curves(image, drawable, mode, group)',
        lede="""GIMP 的曲线只能选 R / G / B / Alpha——想单独曲「色相」或
       「饱和度」没有入口。这个插件把图层换成一张数据图（红=S、绿=V、蓝=色相），
       三条曲线各管一个分量，再由一个算子解回颜色：恒等时逐像素还原原图，
       改哪条曲线就只动那个分量。想要「每层能单独关掉」的老做法，把「模式」
       切到 <b>multi</b> 就行。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两种模式</h3><span class="pill">mode 参数</span></div>
      <pre><code>single   HSV split            组 · 穿透（带 alpha 时组上还有蒙版）
           └─ 1 · HSV S/V/H     模式 正常      ← 一条算子链算完整 HSV 色

multi    HSV split            组 · 穿透（带 alpha 时组上还有蒙版）
           ├─ 3 · Value         模式 HSV 明度
           ├─ 2 · Saturation    模式 HSV 饱和度
           └─ 1 · Hue           模式 HSV 色相</code></pre>
      <p>single 的滤镜栈：<code>decompose</code>（lb:hsv-dual）→
         <b>S 曲线（红）</b> → <b>V 曲线（绿）</b> → <b>H 曲线（蓝）</b> →
         <code>compose</code>（lb:hsv-compose）。三个分量各占一个通道，互不串门。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>single 还是 multi</h3></div>
      <p><b>single</b> 把 S、V、H 一起送进 <code>lb:hsv-compose</code>：一层、
         五条滤镜，一次算完，只编码一次，误差最小。</p>
      <p><b>multi</b> 是三张分量层，每层 <code>extract</code> → 曲线 →
         <code>encode</code>，再靠 HSV 的三个分量混合模式叠回去。三层就是三次
         编码、三次量化；换来的是每层都能单独关——拨掉 Hue 层就只剩调过 S/V 的
         中间结果，判断在改什么时很直观。</p>
      <p>两个模式的恒等曲线都逐像素还原原图。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测精度</h3></div>
      <p>single：32 位浮点图恒等往返 <b>0.0002 码</b>；8 位图 <b>0.49 码</b>（就是
         量化本身）。只改 S 曲线时，结果的 V 与色相偏差 <b>&lt; 0.001 码</b>——
         三个分量确实互不干扰。</p>
      <p>multi：浮点图三层合成的恒等往返 <b>0 码</b>，隐藏原图层后照样叠得回去。</p>
    </div>
  </div>
  <p class="note">通道约定是硬的：<b>S 在红、V 在绿、色相在蓝</b>。改曲线时选错通道，
     等于把另一个分量的数据当曲线输入。色相曲线必须连续（两端相等、中间不跳变），
     整体旋转色相请用 <code>lb:hue-saturation</code>。single 依赖
     <code>lb:hsv-dual</code> / <code>lb:hsv-compose</code>；multi 只用 GIMP 自带的
     <code>gegl:component-extract</code> 与 HSV 分量混合模式。</p>""",
    ),
    dict(
        key='lch',
        slug='lch-split-curves',
        title='LCh Split (Curves)',
        tag=('曲线', 't-blend'),
        count='L / C / h',
        menu='颜色 → SuperMrWang → Shortcut → LCh Split (Curves)',
        pdb='lb-plugin-lch-split-curves(image, drawable, mode, group)',
        lede="""同样的思路换到 CIE LCh：明度、彩度、色相三条曲线。LCh 是 Lab 的
       极坐标写法——a、b 是直角坐标，一条一维曲线改它会连带改彩度和色相；换成
       (L, C, h) 之后，调彩度不动色相、调色相不动彩度。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两种模式</h3><span class="pill">mode 参数</span></div>
      <pre><code>single   LCh split            组 · 穿透（带 alpha 时组上还有蒙版）
           └─ 1 · LCh L/C/h     模式 正常      ← 一条算子链算完整 LCh 色

multi    LCh split            组 · 穿透（带 alpha 时组上还有蒙版）
           ├─ 3 · Lightness     模式 LCh 明度
           ├─ 2 · Chroma        模式 LCh 彩度
           └─ 1 · Hue           模式 LCh 色相</code></pre>
      <p>single 的滤镜栈：<code>decompose</code>（lb:lch-dual）→
         <b>L 曲线（红）</b> → <b>C 曲线（绿）</b> → <b>h 曲线（蓝）</b> →
         <code>compose</code>（lb:lch-compose）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>量程</h3></div>
      <p>转换由 babl 的 <code>CIE LCH(ab) alpha float</code>（D50）完成，与
         <code>lb:lch-levels</code> 同一口径。数据图里：<code>L* 0…100 → L/100</code>、
         <code>C* 0…140 → C/140</code>（sRGB 最饱和的纯蓝约 133.8，留了余量）、
         <code>h 0…360° → h/360</code>。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>single 还是 multi</h3></div>
      <p><b>multi</b> 用 GIMP 原生的三个 LCh 分量混合模式，每层要把分量值「编码」
         成混合模式读得出来的颜色——色相层得造一个等 L*、等 C* 的色相圆（L*=70、
         C*=39.8，整圈在 sRGB 内），彩度层走黑→蓝直线。三层就是三次编码、三次
         量化，但每层能单独关掉。</p>
      <p><b>single</b> 把三个分量一起送进 compose，那套编码整个不需要，也没了
         逐层量化把色相带偏的风险。层数三降到一，滤镜十四条降到五条。</p>
    </div>
  </div>
  <p class="note"><b>实测</b>：浮点恒等往返 <b>0.0005 码</b>、8 位 <b>0.49 码</b>；
     只改 C 曲线时 L* 与色相的偏差 <b>0.00001 码</b>级。彩度或色相推到极端会出
     sRGB 色域，8 位图按 0/1 裁掉——LCh 的色域比 sRGB 大，这是它本身的性质。
     近中性色（C*≈0）的色相是噪声，但合成不受影响。依赖
     <code>lb:lch-dual</code> / <code>lb:lch-compose</code>。</p>""",
    ),
    dict(
        key='hsl',
        slug='hsl-split-curves',
        title='HSL Split (Curves)',
        tag=('曲线', 't-color'),
        count='H / S / L',
        menu='颜色 → SuperMrWang → Shortcut → HSL Split (Curves)',
        pdb='lb-plugin-hsl-split-curves(image, drawable, mode, group)',
        lede="""GIMP 给 HSV 和 LCh 都配了分量混合模式，唯独 HSL 没有，也没有
       HSL 的色相入口。这个插件不拿 HSV 近似 HSL，而是把三者精确换算后打包进
       一张数据图，三条曲线各管一个分量。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两种模式</h3><span class="pill">mode 参数</span></div>
      <pre><code>single   HSL split            组 · 穿透（带 alpha 时组上还有蒙版）
           └─ 1 · HSL S/L/H     模式 正常      ← 一条算子链算完整 HSL 色

multi    HSL split            组 · 穿透（带 alpha 时组上还有蒙版）
           ├─ 2 · Hue           模式 HSV 色相   ← 只替换 H
           └─ 1 · S / L         模式 正常        ← 算出 S、L 与色相</code></pre>
      <p>single 的滤镜栈：<code>decompose</code>（lb:hsl-dual）→
         <b>S 曲线（红）</b> → <b>L 曲线（绿）</b> → <b>H 曲线（蓝）</b> →
         <code>compose</code>（lb:hsl-compose）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>single 还是 multi</h3></div>
      <p>S 与 L 是耦合的：<code>C = (1−|2L−1|)·S</code>、<code>V = L + C/2</code>、
         <code>S_hsv = C/V</code>。要精确算回 HSV 的 S/V，编码器必须同时读到两者
         ——这正是它们要挤进同一张图的原因，两种模式都一样。</p>
      <p><b>multi</b> 在上面再加一层 Hue：借 HSV 的色相模式（HSL 与 HSV 的色相角
         完全相等），S、L 原样保留。把 Hue 层的眼睛一关，就能看到「原色相 +
         调过 S/L」的中间结果。</p>
      <p><b>single</b> 把色相也收进 compose，一层就够：少一层图、少一次编码量化，
         代价是少了那个可以单独关掉的开关。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>不拿 L 当 V</h3></div>
      <p>把 HSL 的 L 直接当 HSV 的 V 用会差很多：S=0.25 偏 <b>25 码</b>、S=1 偏
         <b>64 码</b>（差的正好是 C/2）。本插件在 compose 内部按上式换算，
         没有这个近似。</p>
    </div>
  </div>
  <p class="note"><b>实测</b>：浮点恒等往返 <b>0.0001 码</b>、8 位 <b>0.49 码</b>；
     只改 S 曲线时 L 与色相的偏差 <b>&lt; 0.001 码</b>。转换由 babl 的
     <code>HSLA float</code> 完成，与 <code>component-extract</code> 的
     <code>hsl-s</code> / <code>hsl-l</code> 同一口径。依赖
     <code>lb:hsl-dual</code> / <code>lb:hsl-compose</code>。</p>""",
    ),
    dict(
        key='lab',
        slug='lab-split-curves',
        title='Lab Split (Curves)',
        tag=('曲线', 't-blend'),
        count='L / a / b',
        menu='颜色 → SuperMrWang → Shortcut → Lab Split (Curves)',
        pdb='lb-plugin-lab-split-curves(image, drawable, mode, group)',
        lede="""在 CIELAB 里调曲线：L* 是感知明度，a 是绿–品红轴，b 是蓝–黄轴。
       「黄了压 b、偏绿推 a」比在 RGB 里拉曲线直观得多。三个分量打包进一张数据图，
       三条曲线各管一个通道。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两种模式</h3><span class="pill">mode 参数</span></div>
      <pre><code>single   Lab split            组 · 穿透（带 alpha 时组上还有蒙版）
           └─ 1 · Lab a/b/L     模式 正常        ← 一条算子链算完整 Lab 色

multi    Lab split            组 · 穿透（带 alpha 时组上还有蒙版）
           ├─ 2 · L             模式 LCh 明度   ← 只替换 L*
           └─ 1 · a / b         模式 正常        ← 算出 a、b 与明度</code></pre>
      <p>single 的滤镜栈：<code>decompose</code>（lb:lab-dual）→
         <b>a 曲线（红）</b> → <b>b 曲线（绿）</b> → <b>L 曲线（蓝）</b> →
         <code>compose</code>（lb:lab-compose）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>single 还是 multi</h3></div>
      <p>GIMP 只有 LCh 的三个分量混合模式，Lab 的 a、b 没有对应项。好在 L* 在
         Lab 与 LCh 里是同一个量（逐位精确），所以明度能单独一层借过来；a、b
         必须成对还原——它们共同决定彩度与色相，拆开就不是线性映射了。</p>
      <p><b>multi</b> 因此是两层：a/b 数据图层在下面算完整颜色，L 层用 LCh 明度
         模式盖上去只换明度。关掉 L 层就能看「原明度 + 调过 a/b」的中间结果。</p>
      <p><b>single</b> 把 L* 也收进 compose，两层变一层。少的不只是一个图，还少了
         「这层用混合模式、那层用正常模式」两套语义并存的地方。</p>
      <p>数据图里中性灰落在 <b>0.502</b>：a 曲线在 0.5 附近往上抬是往洋红推、
         往下压是往绿推；b 曲线同理（上=黄、下=蓝）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>量程与实测</h3></div>
      <p>按 babl 的 <code>CIE Lab float</code>（D50）：<code>a' = (a*+128)/255</code>、
         <code>L' = L*/100</code>。浮点恒等往返 <b>0.0024 码</b>、8 位 <b>0.49 码</b>；
         只改 a 曲线时结果的 b* 与 L* 偏差 <b>0.00001 码</b>级。</p>
    </div>
  </div>
  <p class="note">a、b 是直角坐标：调 a 会连带改彩度与色相（这正是「整体偏绿」该有的
     行为）。要彩度、色相各自单独动，用 LCh 那个插件。超 sRGB 色域的点在 8 位图上
     会被裁——那是色域的事实。依赖 <code>lb:lab-dual</code> /
     <code>lb:lab-compose</code>。</p>""",
    ),
    dict(
        key='hsi',
        slug='hsi-split-curves',
        title='HSI Split (Curves)',
        tag=('曲线', 't-color'),
        count='H / S / I',
        menu='颜色 → SuperMrWang → Shortcut → HSI Split (Curves)',
        pdb='lb-plugin-hsi-split-curves(image, drawable, group)',
        lede="""HSI 的 I 是 (R+G+B)/3，色相又用余弦定义——GIMP 的六条分量
       模式一条也对不上，连「借 HSV 色相换角」都会把 I 带走 22 码。于是三个分量
       合进同一层：红=S、绿=I、蓝=色相，三条曲线各管一个分量。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>只有一个模式</h3><span class="pill">single</span></div>
      <pre><code>HSI split          组 · 穿透（带 alpha 时组上还有蒙版）
  └─ 1 · HSI S/I/H   模式 正常   ← 一条算子链算完整 HSI 色
  └─ 原图层（不动，可以隐藏）</code></pre>
      <p>滤镜栈：<code>decompose</code>（lb:hsi-dual）→ <b>S 曲线（红）</b> →
         <b>I 曲线（绿）</b> → <b>H 曲线（蓝）</b> → <code>compose</code>
         （lb:hsi-compose）。三层分量各占一个通道，互不串门。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么没有 multi</h3></div>
      <p>HSI 一个分量模式都借不到：<code>I=(R+G+B)/3</code> 不是 V 也不是 L；
         色相用余弦定义，接到「HSV 色相」模式上换角时保留的是 HSV 的 S/V，
         <b>I 会被带走 0.085（约 22 码）</b>。所以三个分量只能一起算。</p>
      <p>别的四个插件有 multi（拆成两张或三张分量层）：那几家至少有一个分量能借到
         现成的分量混合模式——HSV、LCh 三个都有，HSL 借色相，Lab 借明度。HSI 一个
         都没有，硬拆就是不准，所以这里只有 single。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>两种色相角不是一回事</h3></div>
      <p>HSI 的色相是余弦定义（等亮度平面里的真实夹角），HSV 的是六边形投影上的
         参数角；两者只在 0°/30°/60° 重合，中间最多差 <b>1.117°</b>。数据图里存
         的是 HSI 的角度，<code>lb:hsi-compose</code> 也按 HSI 的余弦式逆变换，
         所以全程不需要换算，往返 <b>0.0001 码</b>。</p>
    </div>
  </div>
  <p class="note">平均强度 I 比 HSV 的 max 更接近感知亮度，这也是 HSI 常见于图像
     分析与曝光校正的原因。S、I 推到极端时逆变换会出 sRGB 色域（HSI 的色域是
     六边形棱锥，不是立方体），出界部分按 0/1 裁掉。依赖 <code>lb:hsi-dual</code> /
     <code>lb:hsi-compose</code> 两个算子，缺了没有回退，插件会直接报错。</p>""",
    ),
    dict(
        key='frequency',
        slug='frequency-separation',
        title='高低频磨皮',
        tag=('磨皮', 't-tone'),
        count='一键',
        menu='颜色 → SuperMrWang → Shortcut → 高低频磨皮',
        pdb='lb-plugin-frequency-separation(image, drawable, radius, group)',
        lede="""把一张脸拆成<b>影调</b>与<b>细节</b>两层：低频管大块明暗与肤色过渡，高频管毛孔、痘印、细纹。调低频等于重新铺光，调高频等于控制质感，两者互不干扰——这是影楼修图里最老也最稳的一套结构。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">穿透组</span></div>
      <pre><code>高低频磨皮            组 · 穿透（带 alpha 时组上还有蒙版）
  ├─ 2 · 高频（细节）  模式 颗粒合并 + 高通
  ├─ 1 · 低频（影调）  模式 正常 + 高斯模糊
  └─ 原图层（不动，可以隐藏）</code></pre>
      <p>两层各挂一条<b>非破坏滤镜</b>，半径是同一个量：改半径时两层一起改，
         否则叠回去就不再是原图。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>两个滤镜的参数</h3></div>
      <p>低频层是 <code>gegl:gaussian-blur</code>，<code>std-dev</code> = 半径；
         高频层是 <code>gegl:high-pass</code>，<code>std-dev</code> = 半径，
         <b><code>contrast</code> 必须设 2.0</b>。默认的 1.0 只出一半差值，
         叠回去整张图会偏灰——这条是实测踩出来的，不是猜的。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>恒等是怎么来的</h3><span class="pill">逐像素相同</span></div>
      <p>高通层其实是 <code>H = 0.5 + (原图 − 低频)</code>，叠回去用<b>颗粒合并</b>
         （<code>H + L − 0.5</code>），那个 0.5 的偏移正好抵消。所以刚建好时合成
         结果与原图逐像素相同；剩下的误差来自 <code>gegl:high-pass</code> 内部约
         <b>1 码</b>的定点偏移，与半径无关。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>怎么修</h3></div>
      <ol class="steps">
        <li><b>低频层</b>：低透明度画笔、图章或涂抹工具把色块铺平——汗斑、肤色不均、
            明暗过渡都归它。</li>
        <li><b>高频层</b>：图章 / 修复画笔点掉痘印、毛孔、细纹，只动质感不动明暗。</li>
        <li><b>半径</b>就是分界线：1024 长的图从 4–8 px 起试。太大，细节被当成影调
            一起揉掉；太小，高频里会留下大块色斑。</li>
        <li>想整体重来：把两层的半径同时改回，或直接删组重生成——原图层一直没动。</li>
      </ol>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3><span class="pill">check_retouch.py</span></div>
      <p>浮点与 8 位恒等 ≤ <b>1.5 码</b>；改半径后仍然恒等（说明是活的非破坏结构）；
         隐藏原图层后两层自己还原；带 alpha 的图由组蒙版保住透明度，零误差。</p>
      <p class="muted small">参数：<code>radius</code> 0.2–100 px（默认 8）、
         <code>group</code> 收进图层组。</p>
    </div>
  </div>""",
    ),
    dict(
        key='dodge',
        slug='dodge-burn',
        title='双曲线磨皮',
        tag=('磨皮', 't-tone'),
        count='一键',
        menu='颜色 → SuperMrWang → Shortcut → 双曲线磨皮',
        pdb='lb-plugin-dodge-burn(image, drawable, amount, group)',
        lede="""提亮一条曲线、压暗一条曲线，各自压在一张全黑蒙版下。涂到哪里，哪里才变亮或变暗——没涂的地方与原图逐像素相同，所以可以反复叠加、随时反悔。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">两层 · 黑蒙版</span></div>
      <pre><code>双曲线磨皮              组 · 穿透（带 alpha 时组上还有蒙版）
  ├─ 2 · 压暗（黑蒙版）  正常 · 曲线下压
  ├─ 1 · 提亮（黑蒙版）  正常 · 曲线上提
  └─ 原图层（不动，可以隐藏）</code></pre>
      <p>两层都是「正常」模式，各挂一条 <code>gimp:curves</code>（值通道）；
         蒙版全黑，所以刚建好时两层根本不参与合成——结果与原图<b>逐像素相同</b>。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>涂的是蒙版，不是图层</h3></div>
      <p>点中图层的<b>蒙版缩略图</b>（白框套住的那张小图，不是图层缩略图），
         选柔边画笔、白色，不透明度 10–20%。涂到的地方蒙版变白，那一层才显形：
         涂提亮层变亮、涂压暗层变暗。涂过头就把前景色换成黑，盖回去。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>曲线有多强</h3><span class="pill">12%</span></div>
      <p>「强度」参数是曲线在中间调偏离对角线的幅度：12 表示 0.5 处抬 0.12，
         约 <b>30 码</b>。默认 12，范围 1–40。宁少勿多——一层不够就再涂一遍，
         比一次涂死好收。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>怎么修</h3></div>
      <ol class="steps">
        <li><b>提亮</b>：额头、鼻梁、颧骨高点、眼下三角区——把该亮的地方推上去，
            脸就立起来了。</li>
        <li><b>压暗</b>：脸颊两侧、下颌线、鼻翼阴影、眼窝——把该退的地方收回去。</li>
        <li>每涂一遍就切到下一个图层顺序（提亮 → 压暗 → 再看），避免一路加亮
            把皮肤涂成塑料。</li>
        <li>想检查涂了多少：按住 <kbd>Alt</kbd> 点蒙版缩略图，只看蒙版；黑白分布
            一目了然。</li>
      </ol>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3><span class="pill">check_retouch.py</span></div>
      <p>恒等往返浮点 <b>0 码</b>、8 位 <b>0 码</b>（蒙版全黑，两层不参与）；
         蒙版涂白处严格等于曲线在该点的值；没涂的地方一位不动；带 alpha 的图
         透明度交给组蒙版，零误差。</p>
    </div>
  </div>""",
    ),
    dict(
        key='grey',
        slug='neutral-grey',
        title='中性灰磨皮',
        tag=('磨皮', 't-tone'),
        count='一键',
        menu='颜色 → SuperMrWang → Shortcut → 中性灰磨皮',
        pdb='lb-plugin-neutral-grey(image, drawable, group)',
        lede="""一张 50% 灰的柔光层，柔光在 0.5 处是恒等映射——刚建好时与原图逐像素相同。之后白色画笔提亮、黑色画笔压暗，原图像素一个都没动，整层删掉就能回到起点。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">一层</span></div>
      <pre><code>中性灰磨皮            组 · 穿透（带 alpha 时组上还有蒙版）
  └─ 1 · 中性灰        模式 柔光 · 整层 128 灰
  └─ 原图层（不动，可以隐藏）</code></pre>
      <p>只有一层、没有蒙版：整层铺满 0.5 编码灰，混合模式柔光。修的时候直接
         在这层上涂，不像双曲线要切到蒙版。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么是柔光，不是叠加</h3></div>
      <p>两者在 0.5 处都恒等，区别在斜率：柔光平缓，一两笔的改动落在几个码以内，
         适合反复微调；叠加是 2 倍斜率，同样力度下手重一倍，更容易出色斑。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么是 128，不是 Lab 中灰</h3></div>
      <p>灰层填的是编码值 0.5（8 位图 128）。Lab 的 L*=50 换算到 sRGB 只有 0.46
         左右，柔光叠上去会把整张图压暗一点点——那就不是恒等了。这条是中性灰
         最容易踩的坑。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>怎么修</h3></div>
      <ol class="steps">
        <li>点中「1 · 中性灰」这一层，柔边画笔，不透明度 <b>5–15%</b>、
            流量 10–30%。</li>
        <li><b>白色涂＝提亮</b>：推平暗斑、眼袋、法令纹阴影。</li>
        <li><b>黑色涂＝压暗</b>：收一收高光、压住油光、加深轮廓。</li>
        <li>涂过头就用 50% 灰（<code>#808080</code>）盖回去——这就是它比
            双曲线更好反悔的地方。</li>
      </ol>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测与一个实现注记</h3><span class="pill">0 码</span></div>
      <p>恒等往返浮点与 8 位都是 <b>0 码</b>；涂白变亮、涂黑变暗、没涂的地方
         一位不动；带 alpha 的图由组蒙版保住透明度。</p>
      <p>写灰层像素之后必须 <code>flush()</code> 再 <code>update()</code>：只改
         私有 buffer 不通知核心，投影不失效，<b>导出是对的、界面上那一层却是黑的</b>。
         这一版修的就是这个坑，回归里专门盯了一次 <code>update(0,0,W,H)</code>。</p>
    </div>
  </div>""",
    ),
]

BY_KEY = {p["key"]: p for p in PAGES}

# ---- 卡片与文章页共用的派生字段 ---------------------------------------------
# 卡片只放一句（plugins.html 就只剩十块方格），长的都在文章页里。

BRIEF = {
    "selection": "右键任意图层，把它转成当前选区：Gray / R / G / B / Alpha，"
                 "四种组合方式，可反相。",
    "channel": "右键任意图层，把它变成一条灰度 Alpha 通道，可反相、可自定义名。",
    "hsv": "拆成 H / S / V 三张分量层，每层一条原生曲线，恒等还原。",
    "lch": "同上，换成 CIE LCh 明度 / 彩度 / 色相，感知均匀。",
    "hsl": "GIMP 没有 HSL 分量模式，这个插件精确换算，不拿 HSV 近似。",
    "lab": "a 与 b 合一层、L* 一层，调 a 只动 a、调 b 只动 b。",
    "hsi": "I 借不到任何分量模式，三个分量合进一层、三条曲线各管一个。",
    "frequency": "低频管影调、高频管细节，叠起来就是原图；半径决定分界。",
    "dodge": "提亮 / 压暗两条曲线压在黑蒙版下：涂到哪里动哪里。",
    "grey": "一层 50% 灰、柔光下恒等；白笔提亮、黑笔压暗、灰盖回去。",
}

AREA = {"selection": "图层转换", "channel": "图层转换"}

DEPS = {
    "hsv": ["lb:hsv-dual", "lb:hsv-compose", "gimp:curves"],
    "lch": ["lb:lch-dual", "lb:lch-compose", "gimp:curves"],
    "hsl": ["lb:hsl-dual", "lb:hsl-compose", "gimp:curves"],
    "lab": ["lb:lab-dual", "lb:lab-compose", "gimp:curves"],
    "hsi": ["lb:hsi-dual", "lb:hsi-compose"],
    "frequency": ["gegl:gaussian-blur", "gegl:high-pass"],
    "dodge": ["gimp:curves"],
    "grey": [],
}

DEPS_NOTE = {
    "grey": "不依赖任何自研算子：只往缓冲区里写像素，用 GIMP 自己的柔光混合模式。"
            "装了插件就能用。",
    "selection": "不依赖任何自研算子：直接读图层字节（array 的 C 级切片，"
                 "100 万像素约 4 毫秒），只调 GIMP 自己的选区 PDB。",
    "channel": "不依赖任何自研算子：直接读图层字节，只调 GIMP 自己的通道 PDB。",
}

for _p in PAGES:
    _p["brief"] = BRIEF[_p["key"]]
    _p["area"] = AREA.get(_p["key"], "Shortcut 快捷方式")
    _p["deps"] = DEPS.get(_p["key"], [])
    if "menus" not in _p:
        _name = _p["menu"].split("→")[-1].strip()
        _p["menus"] = ["颜色 → SuperMrWang → Shortcut → " + _name,
                       "图层右键 → SuperMrWang → Shortcut → " + _name]
    _p["deps_note"] = DEPS_NOTE.get(
        _p["key"], "靠下面这些算子干活，装插件时它们必须已注册"
                   "（<code>build.sh</code> 或 dll 包里都有）：")
del _p
