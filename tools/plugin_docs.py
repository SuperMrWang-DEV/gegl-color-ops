# -*- coding: utf-8 -*-
"""Python 插件的页面数据（每支一条，条数由 plugins.html 自己数）。

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
        menu='图层右键 → SuperMrWang → Convert → Layer to Selection',
        menus=['图层右键 → SuperMrWang → Convert → Layer to Selection',
               'SuperMrWang → Convert → Layer to Selection'],
        pdb='lb-plugin-layer-to-selection(\n    image, drawables, channel, invert, operation)',
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
        menu='图层右键 → SuperMrWang → Convert → Layer to Channel',
        menus=['图层右键 → SuperMrWang → Convert → Layer to Channel',
               'SuperMrWang → Convert → Layer to Channel'],
        pdb='lb-plugin-layer-to-channel(\n    image, drawables, invert, name)',
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
      <div class="dl-head"><h3>它取代了 gray-mask</h3></div>
      <p>原来的 <code>plugin/gray-mask</code> 走复制粘贴、会带上蒙版和图层模式，
         但彩色层不按亮度转、也不管偏移，2026-11-18 已下线。这两个插件读
         <b>原始像素</b>，更快也更准，转换就只剩这一条路。</p>
    </div>
  </div>""",
    ),
    dict(
        key='split',
        slug='split-channels',
        title='Split Channels',
        tag=('通道', 't-mask'),
        count='图层 → R/G/B/A',
        menu='SuperMrWang → Convert → Split Channels',
        menus=['SuperMrWang → Convert → Split Channels',
               '图层右键 → SuperMrWang → Convert → Split Channels'],
        pdb='lb-plugin-split-channels(\n    image, drawables, include-alpha, hide-source, prefix)',
        lede="""一个图层一次拆成多条通道：R、G、B、Alpha 各存一条，通道面板里排好，
       原图层自动隐藏留作对照。原生做法是逐条「新建通道 → 复制 → 粘贴 → 合并」，
       四条就是十六步。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>一次拆完四路</h3><span class="pill">R · G · B · Alpha</span></div>
      <p>默认按分量拆四条，命名是「图层名 + 后缀」，通道面板里一眼能认出来。同名
         通道已存在时自动加序号，不会覆盖你之前存的东西。</p>
      <pre><code>图层「photo」
  ├ photo R       红分量
  ├ photo G       绿分量
  ├ photo B       蓝分量
  └ photo Alpha   透明分量</code></pre>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>灰度图不硬凑三份</h3></div>
      <p>灰度图里 R = G = B，拆三路等于三条全黑一样的通道，没有意义——这种图只拆
         一条 <b>Gray</b>；只有带透明时才多一条 Alpha。彩色图默认四路，把
         「含 Alpha」关掉就是三路。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>源图层默认隐藏</h3></div>
      <p>拆完把原图层眼睛关掉、不删除：画布上看到的就是拆分结果，想对照随时点回来。
         不需要这个行为就把「隐藏源图层」关掉，原图和通道并存。</p>
      <p>偏移的小图层也照样处理：通道恒为<b>画布大小</b>，图层没盖到的地方补黑，
         不会出现「通道尺寸跟着图层走、贴上去错位」的老问题。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>和 Layer to Channel 的分工</h3><span class="pill">一条 vs 多条</span></div>
      <p><b>Layer to Channel</b> 把整层压成<b>一条</b>灰度通道（恒按亮度），适合
         「这张灰度图当蒙版存档」。<b>Split Channels</b> 保留<b>分量本身</b>、一次
         出多条，适合「分开看 R/G/B 各自的分布」「单独修某一路」。两者产物都在通道
         面板里，可以并存。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3></div>
      <p><code>tools/check_split_channels.py</code> 31 条断言跑在真实 GIMP 3.2 里：
         四路内容与源图层同名通道逐项相等（索引错位一位就会露馅）、灰度图只出
         Gray、无 alpha 图层不出 Alpha、偏移图层外部补零、有选区时通道不被截断、
         前缀与重名序号。</p>
      <p>速度：600 万像素拆四路约 0.9 秒（一次读完整层再切片，不是每路读一遍）。</p>
    </div>
  </div>""",
    ),
    dict(
        key='hsv',
        slug='hsv-split-curves',
        title='HSV Split (Curves)',
        tag=('曲线', 't-color'),
        count='H / S / V',
        menu='SuperMrWang → Retouch → HSV Split (Curves) · single',
        menus=['SuperMrWang → Retouch → HSV Split (Curves) · single',
               'SuperMrWang → Retouch → HSV Split (Curves) · multi',
               '图层右键 → SuperMrWang → Retouch → 同上两条'],
        pdb='lb-plugin-hsv-split-curves(image, drawables, group)\n'
            'lb-plugin-hsv-split-curves-multi(image, drawables, group)',
        lede="""GIMP 的曲线只能选 R / G / B / Alpha——想单独曲「色相」或
       「饱和度」没有入口。这个插件把图层换成一张数据图（红=S、绿=V、蓝=色相），
       三条曲线各管一个分量，再由一个算子解回颜色：恒等时逐像素还原原图，
       改哪条曲线就只动那个分量。想要「每层能单独关掉」的老做法，菜单里选
       <b>· multi</b> 那条就行。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两种模式</h3><span class="pill">两条菜单</span></div>
      <p>菜单里是两条独立的过程——<b>… · single</b> 与 <b>… · multi</b>，
         点哪条就是哪个模式。对话框里只剩「收进图层组」一个开关。</p>
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
      <p>两个模式的恒等曲线都是<b>平滑样条</b>（SMOOTH，三个控制点
         <code>(0,0)</code>、<code>(128,128)</code>、<code>(255,255)</code>）。
         三个点都踩在 8 位格点上，所以这条平滑曲线与「铺 256 个采样点」在数值上
         完全等价——恒等往返差异见下。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测精度</h3></div>
      <p>single：32 位浮点图恒等往返 <b>0.0002 码</b>；8 位图 <b>0.49 码</b>（就是
         量化本身）。只改 S 曲线时，结果的 V 与色相偏差 <b>&lt; 0.001 码</b>——
         三个分量确实互不干扰。</p>
      <p>multi：浮点图三层合成的恒等往返 <b>0.0015 码</b>，隐藏原图层后照样叠得回去。
         比 single 大七倍——多出来的是三次编码来回的余数，但仍然在千分之一码量级，
         肉眼无感。8 位图上两个模式都是 <b>0.49 码</b>，量化盖过一切。所以精度上
         <b>single 更准</b>，multi 换来的是「每层能单独关」。</p>
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
        menu='SuperMrWang → Retouch → LCh Split (Curves) · single',
        menus=['SuperMrWang → Retouch → LCh Split (Curves) · single',
               'SuperMrWang → Retouch → LCh Split (Curves) · multi',
               '图层右键 → SuperMrWang → Retouch → 同上两条'],
        pdb='lb-plugin-lch-split-curves(image, drawables, group)\n'
            'lb-plugin-lch-split-curves-multi(image, drawables, group)',
        lede="""同样的思路换到 CIE LCh：明度、彩度、色相三条曲线。LCh 是 Lab 的
       极坐标写法——a、b 是直角坐标，一条一维曲线改它会连带改彩度和色相；换成
       (L, C, h) 之后，调彩度不动色相、调色相不动彩度。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两种模式</h3><span class="pill">两条菜单</span></div>
      <p>菜单里是两条独立的过程——<b>… · single</b> 与 <b>… · multi</b>，
         点哪条就是哪个模式。对话框里只剩「收进图层组」一个开关。</p>
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
  <p class="note"><b>实测</b>：浮点恒等往返 <b>0.0005 码</b>（multi 三层 <b>0.002 码</b>）、
     8 位 <b>0.49 码</b>——single 更准，multi 换的是分层开关。
     这个插件额外要过色相、彩度两张编码表，但曲线本身三个控制点踩在格点上，
     不额外引入误差。只改 C 曲线时 L* 与色相的偏差 <b>0.00001 码</b>级。彩度或色相推到极端会出
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
        menu='SuperMrWang → Retouch → HSL Split (Curves) · single',
        menus=['SuperMrWang → Retouch → HSL Split (Curves) · single',
               'SuperMrWang → Retouch → HSL Split (Curves) · multi',
               '图层右键 → SuperMrWang → Retouch → 同上两条'],
        pdb='lb-plugin-hsl-split-curves(image, drawables, group)\n'
            'lb-plugin-hsl-split-curves-multi(image, drawables, group)',
        lede="""GIMP 给 HSV 和 LCh 都配了分量混合模式，唯独 HSL 没有，也没有
       HSL 的色相入口。这个插件不拿 HSV 近似 HSL，而是把三者精确换算后打包进
       一张数据图，三条曲线各管一个分量。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两种模式</h3><span class="pill">两条菜单</span></div>
      <p>菜单里是两条独立的过程——<b>… · single</b> 与 <b>… · multi</b>，
         点哪条就是哪个模式。对话框里只剩「收进图层组」一个开关。</p>
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
  <p class="note"><b>实测</b>：浮点恒等往返 <b>0.0001 码</b>（multi 两层 <b>0.0014 码</b>）、
     8 位 <b>0.49 码</b>——single 更准，multi 换的是分层开关；
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
        menu='SuperMrWang → Retouch → Lab Split (Curves) · single',
        menus=['SuperMrWang → Retouch → Lab Split (Curves) · single',
               'SuperMrWang → Retouch → Lab Split (Curves) · multi',
               '图层右键 → SuperMrWang → Retouch → 同上两条'],
        pdb='lb-plugin-lab-split-curves(image, drawables, group)\n'
            'lb-plugin-lab-split-curves-multi(image, drawables, group)',
        lede="""在 CIELAB 里调曲线：L* 是感知明度，a 是绿–品红轴，b 是蓝–黄轴。
       「黄了压 b、偏绿推 a」比在 RGB 里拉曲线直观得多。三个分量打包进一张数据图，
       三条曲线各管一个通道。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两种模式</h3><span class="pill">两条菜单</span></div>
      <p>菜单里是两条独立的过程——<b>… · single</b> 与 <b>… · multi</b>，
         点哪条就是哪个模式。对话框里只剩「收进图层组」一个开关。</p>
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
         <code>L' = L*/100</code>。浮点恒等往返 <b>0.0024 码</b>（multi 两层
         <b>0.0044 码</b>）、8 位 <b>0.49 码</b>；
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
        menu='SuperMrWang → Retouch → HSI Split (Curves) · single',
        menus=['SuperMrWang → Retouch → HSI Split (Curves) · single',
               '图层右键 → SuperMrWang → Retouch → HSI Split (Curves) · single'],
        pdb='lb-plugin-hsi-split-curves(image, drawables, group)',
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
         所以全程不需要换算，往返 <b>0.0001 码</b>（8 位 <b>0.5 码</b>）。</p>
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
        menu='SuperMrWang → Retouch → 高低频磨皮',
        pdb='lb-plugin-frequency-separation(image, drawables, radius, group)',
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
        menu='SuperMrWang → Retouch → 双曲线磨皮',
        pdb='lb-plugin-dodge-burn(image, drawables, amount, group)',
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
        menu='SuperMrWang → Retouch → 中性灰磨皮',
        pdb='lb-plugin-neutral-grey(image, drawables, group)',
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
      <p>灰层的像素走 <code>get_shadow_buffer()</code> → <code>merge_shadow()</code>。
         直接写 <code>get_buffer()</code> 再 flush+update（上一版的做法）只保证数值对，
         投影和图层缩略图仍可能停在新图层的空内容上：<b>导出是对的、界面上那一层
         却是黑的</b>——而且只有「不带 AI」这一支会这样，AI 版本来就走 shadow
         路径。回归里盯住 <code>merge_shadow</code> 确实被调到。</p>
    </div>
  </div>""",
    ),
    dict(
        key='observe',
        slug='observe',
        title='观察层',
        tag=('观察', 't-noise'),
        count='六个菜单项',
        menu='SuperMrWang → Observe → 黑白 / 陡峭曲线 / 波浪曲线 / 饱和度 / 阈值 / 海报化',
        menus=['SuperMrWang → Observe → 六个菜单项，点了直接建',
               '图层右键 → SuperMrWang → Observe → 同上'],
        pdb='lb-plugin-observe-* 六个过程，全部零参数',
        lede="""修图最怕看不清问题就开始调。这六支把「先建一个观察层」压成一次点击：副本、滤镜、参数都已经配好，看完隐藏或删掉，原图层一个像素都没动。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">一层副本</span></div>
      <pre><code>观察 · 陡峭曲线        副本 + 图层滤镜（参数随时可改）
原图层                 不动，像素一个都没变</code></pre>
      <p>副本是完整的像素副本，滤镜挂在副本上——右键副本 → 图层 → 滤镜就能
         把参数调回来，不存在「效果烤死在像素里」这回事。看完删掉整层即可，
         不留痕迹。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么不做成调整图层</h3></div>
      <p>GIMP 3 没有 Photoshop 那种独立调整图层，但图层滤镜是等价的：<b>参数
         是活的、像素是死的</b>。差别只在于它必须挂在某个图层上，所以先复制一层
         再挂，功能上没有任何损失。</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>六种看什么</h3><span class="pill">零参数，点了就建</span></div>
    <div class="table-wrap"><table class="op-table">
      <thead><tr><th>菜单项</th><th>挂的滤镜</th><th>看什么</th></tr></thead>
      <tbody>
        <tr><td><b>黑白</b></td><td><code>gimp:desaturate</code>（<b>明度</b>）</td>
            <td>明暗结构、脏点、凹凸、色块之间的明度差。皮肤问题一大半在这一层
                就能看见，是和中性灰、双曲线配合最多的一层</td></tr>
        <tr><td><b>陡峭曲线</b></td><td>曲线 S 形，中间调斜率约 2.3 倍</td>
            <td>细微色斑、肤色不匀。原本要盯半天才看得出的过渡，被拉成明显的斑</td></tr>
        <tr><td><b>波浪曲线</b></td><td>去色 + 锯齿曲线（四个峰谷）</td>
            <td>色带、断层、渐变里的台阶。连续的色阶被反复翻折，哪里断了一眼
                就露出来——像等高线地形图</td></tr>
        <tr><td><b>饱和度</b></td><td><code>gimp:hue-saturation</code>，+100</td>
            <td>泛红、色偏、色块边界。皮肤该均匀的地方一泛红就跳出来</td></tr>
        <tr><td><b>阈值</b></td><td>去色 + 硬阶梯（切点＝中位数）</td>
            <td>灰尘、痘印、小污点。六种里最狠的一层，只剩形状</td></tr>
        <tr><td><b>海报化</b></td><td><code>gimp:posterize</code>，4 级</td>
            <td>大块边界、渐变是否干净。比阈值温和，还留一点结构</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>阈值为什么按中位数切</h3></div>
      <p>写死 0.5 是不行的：偏暗的图（夜景、深色截图、欠曝照片）整张都在 0.5
         以下，切出来是一块纯黑，什么都看不见。按图层亮度的<b>中位数</b>切，
         黑白天然各占一半。</p>
      <p>这里也没用 <code>gimp:threshold</code>：它的 low / high 语义和界面上那两个
         滑块并不一致——真实测下来，<code>low == high</code>（想切得干脆）会整片
         变黑，区间收窄切点还会飘。改成曲线做硬阶梯，切点就是中位数，行为确定。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>两个容易被忽略的细节</h3></div>
      <p><b>波浪和阈值先转灰。</b>直接对彩色图操作，等值线会带上各通道自己的
         色相（紫绿蓝的环），信息量大但看着闹，判断「这块肤色不匀」反而更难；
         三通道各自过切点还会让阈值图变成彩色。</p>
      <p><b>黑白用明度（Luminance），不用亮度（Lightness）。</b>前者按人眼对
         R/G/B 的敏感度加权，红绿两块在 Lightness 下亮度相同、在 Luminance 下
         能分开——挑色斑要的正是后者。</p>
    </div>
  </div>""",
    ),
    dict(
        key='luminosity',
        slug='luminosity',
        title='明度蒙版',
        tag=('蒙版', 't-mask'),
        count='七条通道',
        menu='SuperMrWang → Luminosity Masks → 明度蒙版（7 条通道）',
        menus=['SuperMrWang → Luminosity Masks → 生成七条明度通道',
               '图层右键 → SuperMrWang → Luminosity Masks → 同上'],
        pdb='lb-plugin-luminosity-mask(image, drawables)',
        lede="""明度蒙版把「哪块该亮、哪块该暗」从一句形容变成可以随时载入的选区：
   按亮度切七刀，全在通道面板里，双击就选中。提亮天空、压暗地面、单独修中间调，
   都不用再手画蒙版。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成什么</h3><span class="pill">七条通道</span></div>
      <pre><code>明度 · 亮部 1（&gt; 64）      最宽的高光蒙版
明度 · 亮部 2（&gt; 128）
明度 · 亮部 3（&gt; 192）     只剩最亮的那截
明度 · 暗部 1（&lt; 192）      最宽的暗部蒙版
明度 · 暗部 2（&lt; 128）
明度 · 暗部 3（&lt; 64）
明度 · 中间调（64–192）    两端渐隐的梯形</code></pre>
      <p>全部落在<b>通道面板</b>里，不是图层——这是它们在 PS 里的原生形态。双击任意
         一条就变成选区，曲线、色阶、锐化都只作用在选中的范围里。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>用法就三步</h3></div>
      <p><b>1</b>　选中图层 → 点菜单项，七条一次建好<br>
         <b>2</b>　双击通道 → 变成选区<br>
         <b>3</b>　复制一层，在选区里调曲线</p>
      <p>要挂成图层蒙版：选中通道后右键图层（配合 <b>Channel to Mask</b>）。
         重跑会先删掉上一批同名通道，不会越点越多。</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>七条各挑什么</h3><span class="pill">线性色阶拉伸</span></div>
    <div class="table-wrap"><table class="op-table">
      <thead><tr><th>通道</th><th>怎么算</th><th>挑出什么</th></tr></thead>
      <tbody>
        <tr><td><b>亮部 1（&gt; 64）</b></td><td>亮度 64–255 拉到 0–255</td>
            <td>天空、受光面、白墙——所有不在阴影里的地方。最常用的一条</td></tr>
        <tr><td><b>亮部 2（&gt; 128）</b></td><td>128–255</td>
            <td>明确的高光。压高光、加云层细节</td></tr>
        <tr><td><b>亮部 3（&gt; 192）</b></td><td>192–255</td>
            <td>云、灯、反光。只想动最亮的那一小块时用</td></tr>
        <tr><td><b>暗部 1（&lt; 192）</b></td><td>亮部 3 的反相</td>
            <td>从阴影一直到中间调的大片区域</td></tr>
        <tr><td><b>暗部 2（&lt; 128）</b></td><td>亮部 2 的反相</td>
            <td>明确的暗部。压暗四周做暗角</td></tr>
        <tr><td><b>暗部 3（&lt; 64）</b></td><td>亮部 1 的反相</td>
            <td>死黑。提暗部细节、去噪点就用这条</td></tr>
        <tr><td><b>中间调（64–192）</b></td><td>亮部 1 减亮部 3，再归一化</td>
            <td>主体所在的那一层，两端渐隐——加对比不碰高光和阴影</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>为什么是通道，不是图层</h3></div>
      <p>明度蒙版在 PS 里本来就是通道，「载入成选区」是它的用法。做成灰度图层也能看，
         但每次都要手动「图层转选区」，多一步就少用一次。</p>
      <p>七条通道共用一次明度提取：复制图层 → 去色（明度加权）→ 读一遍像素 →
         套七张映射表 → 删掉副本。所以七条是同一份亮度切的，不会因为算了两遍而对不齐。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>两个实现细节</h3></div>
      <p><b>中间调是相减，不是相乘。</b>两条亮部相乘，峰值只有 170 左右，蒙版灰蒙蒙的，
         当蒙版用时还得再补一条曲线；相减再按峰值归一化，峰值才是纯白、两端纯黑。</p>
      <p><b>按 8 位生成（256 级）。</b>蒙版本身是连续渐变，256 级在绝大多数叠加里看不出来。
         真遇上 16 位风光修图露台阶，可以改走 GEGL 色阶，让精度跟着图像走。</p>
    </div>
  </div>""",
    ),
    dict(
        key='ai-inpaint',
        slug='ai-inpaint',
        title='AI 局部重绘',
        tag=('AI', 't-noise'),
        count='选区 + 提示词',
        menu='SuperMrWang → AI → AI Inpaint…',
        menus=['SuperMrWang → AI → AI Inpaint…（简版：只问画什么）',
               'SuperMrWang → AI → AI Inpaint (Advanced)…（全参数）',
               'SuperMrWang → AI → AI Select by Name…（按名称自动选区）',
               'SuperMrWang → AI → AI Environment…（装 / 起 ComfyUI，看底模）'],
        menus_en=['SuperMrWang → AI → AI Inpaint… (three boxes)',
                  'SuperMrWang → AI → AI Inpaint (Advanced)… (every knob)',
                  'SuperMrWang → AI → AI Select by Name… (SAM2 selection)',
                  'SuperMrWang → AI → AI Environment… (install / start ComfyUI)'],
        pdb='lb-plugin-ai-inpaint(\n    image, drawables, prompt, preset, negative)\n'
            'lb-plugin-ai-inpaint-advanced(\n    image, drawables, prompt, preset, negative,\n'
            '    server, checkpoint, steps, cfg, seed, denoise,\n'
            '    grow, grow-mask-by, feather, timeout, keep-mask, scale)\n'
            'lb-plugin-ai-select(\n    image, drawables, object, sam2-model,\n'
            '    threshold, grow, shift-x, shift-y, server, timeout)\n'
            'lb-plugin-ai-env(image)',
        spec_note="处理对象是<b>当前选区</b>：先框出要改的地方，插件把这块连同周围一圈"
                  "裁下来交给 ComfyUI，回来的图当新图层贴回原位，羽化过的选区做图层蒙版。"
                  "没有选区它不会乱猜，会直接提示先框一块。",
        spec_note_en="It works on <b>the current selection</b>: frame what should change and "
                     "the plug-in crops that area plus a ring of context, sends it to "
                     "ComfyUI, then pastes the answer back as a new layer masked by your "
                     "feathered selection. With no selection it says so instead of guessing.",
        no_code_note=True,
        lede="""框一块地方，写一句提示词，剩下的交给本机 <b>ComfyUI</b>（Stable Diffusion）：
       插件把选区连同周围上下文裁下来、连蒙版一起送过去，等画完再把结果当新图层贴回原位。
       不需要联网，不需要账号，一张 1024×512 的图在本机显卡上约 9 秒。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>一次点击做了什么</h3><span class="pill">五步</span></div>
      <ol class="steps">
        <li>选区外扩 <code>grow</code>（默认 8 px，收拾接缝），外接框再带一圈上下文；</li>
        <li>裁切框宽高对齐到 <b>8</b>——VAE 是 8× 下采样，不对齐回来就错位；长宽比补到
            <b>≤ 2:1</b>，见下面「六个坑」；</li>
        <li>从<b>可见合成</b>读这块像素（图层比画布小时取到的是下面图层，不是黑），
            连同蒙版 PNG 发给 ComfyUI；</li>
        <li>轮询 <code>/history</code> 等它画完；</li>
        <li>结果读回成新图层，插在原图层正上方、偏移对回原地，羽化选区做图层蒙版。</li>
      </ol>
      <pre><code>AI Inpaint            新图层 · 带羽化图层蒙版
  └─ 原图层             不动，随时关掉对比

keep-mask 打开时，另存一条 "AI Mask" 通道，
以后想重新限定范围可以直接拿来用。</code></pre>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>选区要紧</h3><span class="pill">最容易踩</span></div>
      <p>蒙版盖住多少，模型就重画多少——它没有「这副眼镜戴在脸上该多大」的尺度概念。
         框满整个额头到脸颊，出来的就是一副盖住半张脸的巨大墨镜。贴着目标该在的位置
         框一条，上下各留 8~16 px 就够。</p>
      <p>边缘不用抠准：<code>grow</code> 会把选区外扩，<code>feather</code>（默认 4 px）
         管贴回时的过渡。真要精确形状，先在选区上做好再跑。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>三个框</h3><span class="pill">简版只有这些</span></div>
      <p><b>Prompt —— 这里该变成什么。</b>写<b>结果</b>，不写动作：要去掉一只瓶子，写
         <code>empty wooden table, wood grain</code>，别写 <code>remove the bottle</code>。
         常用词可以直接写中文，<code>prompt_tools</code> 翻成英文再送（SD 本身只读英文，
         中文提示词在它那里等于噪声）。</p>
      <p><b>What to paint（preset）—— 主体下拉。</b>猫 / 狗 / 人 / 花 / 树 / 咖啡 /
         食物 / 车。选了以后提示词只补细节（颜色、姿态、环境）。
         <b>抹掉东西就选 Erase（keep the background）</b>：它不往提示词里加字，
         作用是告诉候选打分器「这一格要留空」——三张候选里「填得最平」的那张
         才会胜出，而不是「画得最多」的那张。</p>
      <p><b>Negative prompt —— 不要什么。</b>默认已把画风压向照片：
         <code>illustration, cartoon, flat graphic, poster, vector art, cgi</code>。
         这是修图插件，先让模型别往矢量插画跑；想要画风自己改这一栏。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>多候选：出三张，自己挑</h3><span class="pill">variations</span></div>
      <p>一次采样可以出 2~4 张（<code>variations</code>，默认 3），先按接缝、糊／碎、
         跨边缘色台阶、选区外改动、结构密度打分，然后弹一个<b>缩略图挑选窗</b>：
         几张并排、标着序号和分数，点一下换一张，确认后只留选中的那张。</p>
      <p>缩略图只看「选区 + 30% 边距」——候选图层往往比选区高好几倍，整块缩下去
         三张会长得一模一样。勾掉「保留其余候选」就把没选中的删掉，默认留下当
         隐藏图层，随时点眼睛换回来。</p>
      <p class="muted small">批处理与「重复上次」不弹窗，直接用打分最优那张：
         一个会等鼠标的批处理任务等于卡死。<code>pick</code> 关掉也是这个行为。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>参数框</h3></div>
      <p>GIMP 3 不会替插件生成参数对话框，得插件自己建。这一支在 <code>run()</code> 里
         调 <code>_shared/lb_dialog.py</code>：交互模式弹框、取消就是取消，
         批处理与「上次的值」直接放行，不再偷偷按默认值跑一遍。</p>
      <p class="muted small">这一课上过的不止这一支：不自己建框，参数就全部隐形，
         永远按默认值执行。</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>高级版多出来的参数</h3><span class="pill">按需改，不是都得填</span></div>
    <div class="table-wrap"><table class="op-table">
      <thead><tr><th>参数</th><th>默认</th><th>什么时候动它</th></tr></thead>
      <tbody>
        <tr><td><code>server</code></td><td>空</td>
            <td>ComfyUI 不在 127.0.0.1:8188 时填；空则读 <code>$LB_COMFY_URL</code></td></tr>
        <tr><td><code>checkpoint</code></td><td>自动</td>
            <td>下拉，选项当场问 ComfyUI 要（SD 系 + Flux 系合一张表）；「自动」优先挑 SDXL inpaint</td></tr>
        <tr><td><code>steps</code></td><td>25</td>
            <td>要更细的质感往上加，25–30 之后收益很小</td></tr>
        <tr><td><code>cfg</code></td><td>7.5</td>
            <td>听不听话。太高会硬、出现重复图形；太低会飘</td></tr>
        <tr><td><code>seed</code></td><td>-1</td>
            <td>想复现同一张：把上一次日志里的种子填进来</td></tr>
        <tr><td><code>denoise</code></td><td>1.0</td>
            <td><b>加新物体保持 1.0</b>；只在「保留原结构、轻度改写」时降</td></tr>
        <tr><td><code>grow</code></td><td>8</td>
            <td>选区外扩多少像素再送。接缝明显就加大</td></tr>
        <tr><td><code>grow-mask-by</code></td><td>8</td>
            <td>模型可动的额外像素，8 px = 一个 latent 格；越大接缝越少、漂移越多</td></tr>
        <tr><td><code>feather</code></td><td>4</td>
            <td>贴回时图层蒙版的羽化半径</td></tr>
        <tr><td><code>timeout</code></td><td>600</td>
            <td>等 ComfyUI 的上限。CPU 兜底跑大图时往上调</td></tr>
        <tr><td><code>keep-mask</code></td><td>开</td>
            <td>要不要留 "AI Mask" 通道；只想要干净结果就关掉</td></tr>
        <tr><td><code>scale</code></td><td>0</td>
            <td>0 = 按底模的舒适尺寸送（SD1.5 512 / SDXL 1024）；1.0 = 原样送</td></tr>
        <tr><td><code>variations</code></td><td>3</td>
            <td>一次出几张（1~4）。简版也有。3 张里挑一张比赌一张稳得多，代价是采样时间乘上张数</td></tr>
        <tr><td><code>pick</code></td><td>开</td>
            <td>出多张时弹不弹挑选窗。关掉就静默用最优那张；批处理本来就不弹</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>依赖：一条命令下齐（模型 / 节点包 / 权重）</h3><span class="pill">2026-11-24</span></div>
    <p>插件是压缩包，可 AI 那几个功能要的东西都在 ComfyUI 那一侧：模型分五个目录、
       Flux 要 <code>ComfyUI-GGUF</code>、按名称选区要 <code>ComfyUI-RMBG</code> 和
       1.1 GB 权重。让用户照着文档放文件是这个项目最容易失败的地方，所以有一条入口
       包干——先体检，再下缺的：</p>
    <pre><code>python tools/setup_comfy.py --check     # 缺什么、多大、装在哪
python tools/setup_comfy.py             # 默认：inpaint 两档 + 选区 + 抠图
python tools/setup_comfy.py --tier min  # 最小：只 SD1.5-inpaint（4.3 GB）
python tools/setup_comfy.py --tier full # 再加 Flux.1 Fill（12 GB）</code></pre>
    <p>它自己找 ComfyUI（便携包 / 源码目录 / <code>setup_ai.py</code> 装的
       <code>py/</code> 布局都认，目录来自 <code>--home</code> → 插件里选过的那个 →
       常见路径）；节点包和它的 pip 依赖成对装（少了依赖那个节点会静默消失，比不装
       更难查）；下载先写 <code>.part</code> 再改名，<code>hf-mirror</code> →
       <code>huggingface.co</code> 换源不丢进度，<b>落盘尺寸对不上就重下</b>；
       开跑前算磁盘；最后只有节点/补丁变了才重启，重启会等到
       <code>/system_stats</code> 真的通，再回读 <code>/object_info</code> 确认
       「底模几个、gguf 主干几个、节点加载了没」。</p>
    <p><b>sdxl</b>：<code>sd_xl_base_1.0_inpainting_0.1.safetensors</code> 丢进
       <code>models/checkpoints/</code> 就能用——「inpaint 专用」和「SDXL」两个条件
       同时凑齐，8 GB 卡 30~40 秒一张，<b>不用装任何扩展</b>。同一块选区、同一句
       提示词，SD1.5 给的是「糊的正面坐姿猫」，SDXL 给的是一只趴着、带接触阴影、
       接缝看不出来的橘猫。</p>
    <p><b>flux</b>：<code>flux1-fill-dev-Q4_K_S.gguf</code>（→
       <code>models/diffusion_models/</code>）+ <code>t5xxl_fp8_e4m3fn</code> 和
       <code>clip_l</code>（→ <code>models/text_encoders/</code>）+ <code>ae.safetensors</code>
       （→ <code>models/vae/</code>），还要装 <code>custom_nodes/ComfyUI-GGUF</code>。
       8 GB 卡一张 1~3 分钟，<b>许可禁止商用</b>。它不是「换个底模」那么简单：
       主干走 <code>UnetLoaderGGUF</code>、文本编码器拆成 T5+CLIP-L 两个、解码用单独的
       <code>ae</code>、提示词强度由 <code>FluxGuidance</code>（默认 30）管而不是
       <code>cfg</code>（固定 1.0）。所以看到 <code>.gguf</code> 或名字带 flux，
       <code>inpaint()</code> 会把整张节点图换掉。四个文件缺一个都跑不起来，
       <code>flux_assets()</code> 会点名缺哪个、该放哪。</p>
    <p><b>三档实测</b>（同选区、同提示词、同一张地板）：SD1.5 的猫毛发是一团、
       狗的腿糊在一起；SDXL 形体和投影对了，但同一句「a small cream puppy」
       画了两只狗，写 `one single` 才收住；Flux 给一只奶油色小狗、四条腿都在地上，
       猫的毛尖和眼神都是清楚的。代价 74~84 秒/张。</p>
    <p><b>自动挑底模</b>优先 SDXL 那一档 inpaint（细节明显强过 SD1.5），
       <b>Flux 不进自动</b>——它慢一个数量级，自动挑会让人以为插件卡死了。</p>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>六个坑</h3><span class="pill">都在代码里绕开了</span></div>
      <p><b>1. 蒙版方向是反的。</b>ComfyUI 的 <code>LoadImage</code> 用 alpha 倒推蒙版
         （<code>mask = 1 - alpha</code>），所以「要重绘」必须写成<b>透明</b>。直接送灰度图
         会得到全 0 蒙版，跑完像素纹丝不动。</p>
      <p><b>2. 8× 对齐。</b>裁剪框宽高不是 8 的倍数就会被截断，回来的图比请求的小，
         贴回去整块错位。</p>
      <p><b>3. 模型必须和条件节点配对，配错就乱画。</b>inpaint 专用底模训练时见过
         「洞」，要配 <code>InpaintModelConditioning</code>（蒙版和被挖掉的图一起进条件）；
         普通底模配 <code>VAEEncode</code> + <code>SetLatentNoiseMask</code>。用普通底模
         走 <code>VAEEncodeForInpaint</code> 加 denoise 1.0 时，一块 260×100 的额头
         会被重绘出丝状眉毛和几道白痕、边界一条直线——这是 2026-11-24 的实测。
         换成 inpaint 底模 + 条件节点，同一块区域眉毛顺着原方向接上。</p>
      <p><b>4. 画幅比例。</b>SD 只在自己训练过的比例附近画得对。选区是眼睛那样一条
         1024×400（2.56:1）时，SDXL 会把整块画成平涂海报——一句
         <code>sunglasses</code> 出来是一块绿底配重复白色箭头。
         <code>plan_canvas_rect()</code> 一律先补到 ≤ 2:1：优先往画面里长真实像素，
         画面到边了才复制边缘，补出来的那圈贴回时被蒙版挡住。</p>
      <p><b>5. 短边与上下文。</b>只把长边对到 512 的话，1024×400 会变成 512×200 ——
         短边远低于 SD1.5 的 512，出来就是一排排重复图形；上下文只给 32 px 时
         模型看不到周围是什么，也会自己编。现在上下文按选区较长边的 0.75 倍给
         （至少 64 px），<code>work_size()</code> 两头卡：短边抬到家族下限
         （SD1.5 512 / SDXL 768），长边不超上限（768 / 1024）；大图里选一小块时
         还会先把上下文收窄（<code>fit_context()</code>），免得整块缩下去把细节
         缩没。</p>
      <p><b>6. 一次只画一张。</b>赌一张的失败率就是全部失败率。现在默认一次出
         <b>3 张</b>（<code>RepeatLatentBatch</code>，共享模型加载），按四项打分排序：
         接缝比周围硬不硬、填充区比周围糊还是碎、跨边缘有没有颜色台阶、选区外
         有没有被改动。最好的那张显示，其余藏在图层面板里（点眼睛就能换）。胜出
         那张再做两步收尾：<b>接缝色差补偿</b>（只补低频偏移，生成细节不动）和
         <b>颗粒匹配</b>（周围是颗粒感照片就补噪点，干净照片不加）。<code>Variations</code>
         设成 1 就是原来的一枪定生死。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>按名称自动选区</h3><span class="pill">不手描</span></div>
      <p><b>AI Select by Name…</b> 不描边，只写名字：<code>ear</code>、<code>left
         eye</code>、<code>the white shirt</code>。它把图层送去 ComfyUI，走
         ComfyUI-RMBG 的 <b>SAM2Segment</b>——GroundingDINO 先把文字变成候选框，
         SAM2 再按框切出蒙版——蒙版回来变成<b>普通 GIMP 选区</b>。这一步不改一个
         像素，后面的 AI 填充、调色、局部模糊、抠图都能接着用。</p>
      <p>实测 744×1120 的人像、<code>sam2.1_hiera_tiny</code> 档：<b>5.8 秒</b>选中
         74×102 的耳朵，边界和手描的一致。档位越大边缘越准（<code>base_plus</code>
         在杂乱背景上更稳），代价是慢一些。</p>
      <p><b>要在物体旁边加东西，记得平移选区。</b>SAM2 给的是物体轮廓、不含周围的
         留白：框住整只耳朵再写 <code>earring</code>，出来的是压在耳朵上的金环和一个
         黑洞；把 <code>Shift selection Y</code> 调 +58、让选区落到耳垂下方之后，
         才是一枚挂在耳垂上的金环。改物体本身（换衣服、去掉图案）就直接用原框。</p>
      <p>一次性准备：<code>python tools/setup_comfy_sam2.py</code>——装
         <code>groundingdino-py</code> / <code>hydra-core</code> / <code>omegaconf</code>、
         下 SAM2-tiny + GroundingDINO + bert-base-uncased（约 1.2 GB，走 hf-mirror）、
         再写一个 <code>custom_nodes/zz_bert_shim</code> 补丁（transformers 5.x 删掉了
         <code>BertModel.invert_attention_mask</code>，补上才能跑）。装完重启 ComfyUI。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>AI 环境</h3><span class="pill">装在哪都行</span></div>
      <p><b>AI Environment…</b> 打开先报状态：连不连得上、什么版本、几个底模，以及
         <b>ComfyUI 装在哪、用的是哪个 python</b>。目录不对就点
         <b>Choose folder…</b> 手选（含 <code>main.py</code> 的目录，或包着
         <code>ComfyUI/</code> 的外层目录），选择会存进配置文件，下回不用再选。</p>
      <p><b>Start</b> 起服务、<b>Stop</b> 停掉插件自己起的那个进程、
         <b>One-click install…</b> 首次装环境（约 10 GB：嵌入式 Python + torch cu128 +
         ComfyUI + 一份底模）、<b>Model folder</b> 直接打开
         <code>models\\checkpoints</code>、<b>Refresh</b> 重新探测并带出日志尾几行。</p>
      <p>默认开着「ComfyUI 没在运行时自动启动」：跑 AI 之前先探活，连不上就按选好的
         目录在<b>后台</b>拉起来（不弹控制台，输出写 <code>comfyui.log</code>），等它就绪
         再继续。只用手选过的目录、不去猜——猜错会拿另一个 Python 起别人的 ComfyUI。</p>
      <p class="muted small">配置：Windows 在 <code>%APPDATA%\\SuperMrWang\\comfyui.json</code>，
         Linux/macOS 在 <code>~/.config/SuperMrWang/comfyui.json</code>。安装器随插件走
         （包里的 <code>ai-setup/</code>），不需要另外去找。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>实测</h3><span class="pill">check_ai_inpaint*.py</span></div>
      <p><code>tools/check_ai_inpaint.py</code> <b>298 条</b>断言跑在本地 mock 服务上
         （不需要显卡）：蒙版方向、8× 对齐、画布补边、缩放倍率上下限、底模家族判定、
         工作流节点与连线、提示词中英转换、候选打分（插入 / 抹除两套判据）、失败退路。</p>
      <p><code>tools/check_ai_inpaint_gimp.py</code>（107 条）在真实 GIMP 3.2 里把过程跑一遍：
         选区 → 提示词 → 新图层、蒙版与通道、候选挑选窗的裁切与选择、乱填的底模名
         被下拉拒回。</p>
      <p>速度（RTX 3070 Ti，SDXL，25 步，1024×512）：<b>8.7 秒</b>。同一尺寸走 CPU
         兜底是 <b>94 秒</b>（384×256 实测），能跑但不适合批量。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>前提</h3></div>
      <p>一个在跑的 ComfyUI + 一份底模。插件只用标准库发 HTTP，不装任何 Python 依赖；
         HTTP 与 PNG 编解码都在 <code>plugin/_shared/ai_client.py</code> 里，
         回归测试用 <code>tools/mock_comfy.py</code> 顶替真服务。</p>
      <p>中文界面的人不用记参数名：<code>po/zh_CN.po</code> 里这些标签都翻过，
         菜单、参数框、状态提示都是中文。</p>
    </div>
  </div>""",
    ),
    dict(
        key='cutout',
        slug='cutout',
        title='抠图 / 移除背景',
        tag=('蒙版', 't-mask'),
        count='AI + 本地两条路',
        menu='SuperMrWang → Mask → 抠图 / 移除背景（本地 / AI）',
        menus=['SuperMrWang → Mask → 抠图 / 移除背景（本地）',
               'SuperMrWang → Mask → 抠图 / 移除背景（AI）'],
        menus_en=['SuperMrWang → Mask → Cut Out (Local)',
                  'SuperMrWang → Mask → Cut Out (AI)'],
        pdb='lb-plugin-cutout-local(\n    image, drawable, threshold, seeds, shrink,\n'
            '    feather, background, color, bg-file, keep-mask, use-selection)\n'
            'lb-plugin-cutout-ai(\n    image, drawable, model, resolution, sensitivity,\n'
            '    refine, shrink, feather, background, color, bg-file, keep-mask)',
        lede="""把主体从背景里抠出来：图层加一张羽化过的蒙版，主体之外透明，顺手还能
   垫一层纯色（白底证件照、电商主图）或一张新背景图。两条路——AI 那条连发丝都能
   分开，本地那条对付纯色和渐变背景是毫秒级的。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两条路各自管什么</h3><span class="pill">按素材挑</span></div>
      <div class="table-wrap"><table class="op-table">
        <thead><tr><th>菜单项</th><th>怎么找主体</th><th>什么时候用</th></tr></thead>
        <tbody>
          <tr><td><b>抠图（AI）</b></td>
              <td>缩略图发给本机 ComfyUI 的 <code>RMBG</code> 节点
                  （BiRefNet / RMBG-2.0），拿回来的 alpha 当蒙版</td>
              <td>头发、毛绒、透明玻璃、绿幕、复杂背景。单张 4~6 秒</td></tr>
          <tr><td><b>抠图（本地）</b></td>
              <td>从四条边的多个种子点泛洪选背景，再反选。已有选区时
                  <b>直接把选区当主体</b>，只做收边</td>
              <td>纯色、渐变、影棚白底；或者想先粗框一下再自动收边。毫秒级</td></tr>
        </tbody>
      </table></div>
      <p>两条路的收尾是同一段代码：蒙版 → 收缩 <code>shrink</code> 像素 → 羽化
         <code>feather</code> → 图层蒙版 + <code>Cutout Mask</code> 通道 → 按需垫背景。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>输出形态</h3></div>
      <p><b>透明</b>：只加蒙版，导出 PNG 就是透明底。<b>纯色</b>：在照片下面新建一层
         纯色（默认白），证件照、主图直接可用。<b>图片</b>：选一张背景图，按 cover
         等比缩放铺满、居中裁切，放在照片下面。</p>
      <p>三种都是非破坏的：原图层像素没动，蒙版随时能改，背景层删掉就回到透明。</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>实测</h3><span class="pill">RTX 3070 Ti</span></div>
    <p>SDXL 生成的一张 768×1024 卷发人像，RMBG-2.0 抠图：<b>4.6 秒</b>（含模型加载），
       主体占比 59.6%，发丝成缕保留，白衬衫边缘干净；<code>shrink=1</code> 收掉
       RMBG 边界外扩的半像素，白底上看不到白边。</p>
    <p>本地版在一张 400×300 的「白底 + 红方块」上：泛洪覆盖四边 100%，
       主体内部蒙版 255、四角 0，全程没有 Python 逐像素循环——
       <code>gimp-image-select-contiguous-color</code> 是 C 实现，24MP 也是毫秒级。</p>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>四个模型，门槛不一样</h3><span class="pill">2026-11 逐个实测</span></div>
    <p>ComfyUI-RMBG 的节点把四个模型摆在同一个下拉里，但它们的准备成本差得远。
       插件会把差别写在选项后面，选错时也会说清缺什么，而不是甩一句
       <code>No module named …</code>。</p>
    <div class="table-wrap"><table class="op-table">
      <thead><tr><th>模型</th><th>第一次用要做什么</th><th>实测</th></tr></thead>
      <tbody>
        <tr><td><b>RMBG-2.0</b></td>
            <td>无。装 ComfyUI-RMBG 时就连带下好了（812 MB）</td>
            <td>768×1024 人像 4.6 秒，发丝最干净 —— 默认选它</td></tr>
        <tr><td><b>BEN2</b></td><td>首次下约 1.1 GB 权重</td>
            <td>批量推理快，边缘略软；人像、商品都可以</td></tr>
        <tr><td><b>BEN</b></td><td>首次下约 1.1 GB 权重（实测下载 8 分钟）</td>
            <td>能用，但没有明显强过 BEN2，下载最久</td></tr>
        <tr><td><b>INSPYRENET</b></td>
            <td>要装 Python 包 <code>transparent-background</code>（连带
                onnxruntime），而且它默认走 CPU</td>
            <td>没装必炸；装了也比 RMBG-2.0 慢，不推荐</td></tr>
      </tbody>
    </table></div>
    <p>下载那几分钟里 ComfyUI 窗口只多出几行 <code>Downloading…</code>，进度条不动，
       插件这边只能等。所以超时提示写的是「正在下约 1.1 GB 权重，再等等」，
       而不是「图太大或步数太多」。等不了就换 RMBG-2.0。</p>
    <p>想自己核对：<code>python tools/check_cutout_models.py</code> 会把四个模型逐个
       真跑一遍，打印每个的耗时与失败原因。</p>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>蒙版怎么从 AI 的 alpha 变成选区</h3></div>
      <p>AI 回来的 alpha 尺寸是缩略图的（长边 ≤ 2048）。在 Python 里把它插值到
         4000×6000 要十几秒；这里建一个同尺寸的临时图层，RGB=白、A=alpha，
         插进图像后让 GIMP 自己 <code>gimp-layer-scale</code> 到画布大小，
         再 <code>select-item</code> 取它的 alpha——缩放是 C 做的，Python 只搬一次
         <code>mw×mh×4</code> 字节。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>两个静默失败</h3></div>
      <p><b>泛洪一个点都没选中时 GIMP 不报错</b>：选区是空的，反选之后就成了整张图，
         看起来像「把主体抠成了全白」。所以先看边框采样点的命中率，低于 35% 直接
         报错让人调阈值或换 AI 版。</p>
      <p><b>背景层插错位置会盖住照片</b>：<code>insert_layer</code> 的 position 从
         顶部数，插到照片的 pos 是插在它<b>上面</b>。要插 <code>pos + 1</code>。</p>
    </div>
  </div>""",
    ),
    dict(
        key='refine',
        slug='refine',
        title='选择并遮住',
        tag=('蒙版', 't-mask'),
        count='六根滑杆 + 实时预览',
        menu='SuperMrWang → Mask → 选择并遮住（精修边缘）…',
        menus=['SuperMrWang → Mask → 选择并遮住（精修边缘）…'],
        pdb='lb-plugin-refine-mask(image, drawables, radius, smart, smooth,\n'
            '    feather, contrast, shift, decontaminate, output, work-size)',
        lede="""选区做完了，边还是糊的：AI 抠图回来的 alpha 半透明、魔棒选出来的边
   像狗啃、羽化过的边上挂着背景色。这个对话框就是拿来收尾的——左边一块预览、
   右边六根滑杆，拖一下立刻重算，满意了点应用。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>六根滑杆</h3><span class="pill">和 PS 同名同向</span></div>
      <div class="table-wrap"><table class="op-table">
        <thead><tr><th>滑杆</th><th>做什么</th><th>什么时候拉</th></tr></thead>
        <tbody>
          <tr><td><b>边缘检测半径</b></td>
              <td>沿法线在 ±N 像素里找画面中真实的边缘，把蒙版剖面推过去。
                  「智能半径」勾上时，只有找到明显更强的边缘（1.35×）才动</td>
              <td>AI 抠的边糊出去一两像素、旁边正好有强边（头发对背景、衣领对皮肤）</td></tr>
          <tr><td><b>平滑</b></td>
              <td>盒式模糊一遍。锯齿、毛刺、零星飞点被摊平</td>
              <td>魔棒 / 快速选择出来的边像狗啃</td></tr>
          <tr><td><b>羽化</b></td>
              <td>三次盒式逼近高斯，软化过渡</td>
              <td>要贴到另一张图上，硬边会看出「剪纸」</td></tr>
          <tr><td><b>对比度</b></td>
              <td>把软边往 0 和 255 推（S 曲线，斜率最高 5×）</td>
              <td>羽化过头、边缘一圈雾；或者 AI 的 alpha 太软</td></tr>
          <tr><td><b>移动边缘</b></td>
              <td>整体加/减 alpha：正值外扩、负值内缩，软硬不变</td>
              <td>整体差半像素（白边、吃掉一圈轮廓）</td></tr>
          <tr><td><b>去色边</b></td>
              <td>半透明像素的颜色沿 alpha 梯度往里取「实心前景色」替换</td>
              <td>抠到浅底上有白边，抠到绿幕上有绿边</td></tr>
        </tbody>
      </table></div>
      <p>顺序是 <b>吸附 → 平滑 → 羽化 → 对比度 → 移动边缘</b>。羽化放在对比度
         之前，是为了让对比度还能把软边重新压硬；反过来做，羽化永远压在上面，
         那根滑杆就白给了。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>输出四种</h3></div>
      <p><b>图层蒙版</b>：挂在当前图层上，非破坏，随时能改。<br>
         <b>透明新图层</b>：复制一层、把蒙版烤进 alpha，去色边只在这条输出上生效
         （另外三种不碰像素）。<br>
         <b>选区</b>：只换选区，什么都不动。<br>
         <b>通道 + 选区</b>：存成「Refined Mask」通道，选区也留着。</p>
      <p>通道那条就是<b>画笔的入口</b>：PS 里那支「选择并遮住」的画笔，在这里
         换成——在通道上用黑白画笔涂（白加、黑减），再双击通道载入成选区。
         美术上的事交给 GIMP 自己的画笔，比插件里再搓一支靠谱。</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>实测</h3><span class="pill">768×1024 / RMBG 结果</span></div>
    <p>拿 SDXL 生成、RMBG-2.0 抠好的一张卷发人像当输入（alpha 就是蒙版）：
       <b>1.03 秒</b>跑完六项（半径 2 / 平滑 1 / 羽化 1 / 对比度 35 / 去色边 60），
       半透明像素从 40 万降到 1.3 万，边缘的浅色雾被收干净，23416 个边缘像素
       换了颜色。预览那一侧是 520 长边，拖滑杆到重画通常 <b>150 毫秒</b>。</p>
    <p>工作尺寸默认 1600 长边。GIMP 3 的 Python 里<b>没有 numpy</b>，模糊只能
       手写前缀和；1600×1067 跑一遍约 1~2 秒，再大就要等了。0 表示按原分辨率算，
       2400 万像素大概 10 秒起步。</p>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>和 PS 差在哪</h3></div>
      <p><b>有：</b>六根滑杆、实时预览、四种看片方式（棋盘格 / 白 / 黑 / 红蒙版）、
         四种输出。<b>没有：</b>画布上的那支减画笔、以及 PS 那种「按图重建 matte」
         的边缘检测。</p>
      <p>边缘检测这里是<b>沿法线平移剖面</b>：每个半透明像素在 ±半径内找最强边缘，
         明显更强就把蒙版挪过去（双线性重采样）。结果一样是把糊出去的边收回来，
         但它不会像 PS 那样重新解一遍前景色和不透明度。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>三个不下心就翻车的细节</h3></div>
      <p><b>通道读出来是线性的。</b>选区存成通道后，用 <code>"Y u8"</code> 读到的
         是线性亮度，而选区值和图层 alpha 是 sRGB 编码的（实测：通道写 128，
         选区读回 188）。不转这一下，精修完中间调整体下压，50% 等值线跟着漂。</p>
      <p><b>预览和应用必须是同一套代码。</b>两边都调同一个 <code>refine_mask</code>，
         只有分辨率不同。各写一套实现，早晚会漂成「预览好看、确定后不一样」。</p>
      <p><b>吸附要把位移沿法线传播到 ±半径。</b>只改半透明带的话，剖面搬过去没有
         地方接住，边界会塌成一道硬跳变。</p>
    </div>
  </div>""",
    ),
    dict(
        key='warp',
        slug='warp',
        title='木偶变形',
        tag=('变形', 't-distort'),
        count='钉子在画布上拖',
        menu='SuperMrWang → Distort → 木偶变形（网格变形）…',
        menus=['SuperMrWang → Distort → 木偶变形（网格变形）…'],
        pdb='lb-plugin-puppet-warp(image, drawables, pins, mode, radius, output)',
        lede="""姿势差一点、胳膊短一截、杯子被拍歪了——这些都不该开液化一格一格推。
   在图层上点几个钉子，拖住钉子把内容拽过去，钉子之间平滑地跟着走，
   离钉子远的地方一个字节都不动。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>怎么用</h3><span class="pill">点、拖、右键</span></div>
      <p>选图层 → 菜单 → 图片上<b>点一下就是一根钉子</b>（按住可以直接拖）；
         <b>拖钉子</b>画面跟着动；<b>右键点钉子</b>删掉它，或者选中后按 Delete。
         钉子拖过的范围由「影响半径」决定，圈外是严格的恒等——连一个字节都不重采样。</p>
      <p>三档解算：<b>刚性（MLS 相似）</b>只允许旋转 + 等比缩放，方角还是方的，
         纯摆位最好看；<b>自由（MLS 仿射）</b>再放开剪切和拉伸，适合把东西拉长；
         <b>ARAP</b> 在网格上解「尽可能刚性」，<b>大角度弯折时局部不会被压扁</b>，
         最接近 PS 的手感。</p>
      <p>ARAP 那一档要 numpy（见「GIMP 自带的 Python 与 numpy」），没装就不出现在
         下拉里；它也不用影响半径（靠弱锚定收口），选它时滑杆自动变灰。</p>
      <p>输出三档，第一档是 <b>非破坏滤镜</b>（对话框默认）：钉子和参数以
         <code>lb:puppet-warp</code> 的形式挂在图层滤镜栈上，<b>像素一个字节都不动</b>，
         之后随时能在图层属性里改参数、临时关掉或删掉；再跑一次对话框会从滤镜里
         把钉子读回来接着拖。另外两档是 <b>覆盖当前图层</b>、<b>复制到新图层</b>
         （把结果烤进像素）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>非交互也能跑</h3></div>
      <p>钉子是过程参数 <code>pins</code>，格式
         <code>sx,sy,dx,dy; sx,sy,dx,dy</code>（原位 → 拖到的地方，图层像素坐标），
         分号和换行都认，写两个数就表示没拖。对话框点应用时也是把钉子写成这个
         字符串再跑一遍，所以脚本能完整复现一次手动变形：</p>
      <p><code>lb-plugin-puppet-warp 图层 pins="100,200,140,200; 300,400,300,430"
         mode=rigid radius=30</code></p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>它是怎么算的</h3><span class="pill">MLS + ARAP 双路</span></div>
    <p>前两档是 <b>MLS</b>（移动最小二乘）：每个像素按到各钉子的距离加权，解一个
       最小二乘仿射，让「钉子原位」尽量对到「钉子现在的位置」。钉子上严格插值，
       场是光滑的。第三档是 <b>ARAP</b>：在 48×37 的网格上解
       Σ｜(xᵢ-xⱼ) - Rᵢ(vᵢ-vⱼ)｜²，局部步骤求每个顶点的最优旋转、全局步骤解
       Laplacian 系统，交替到收敛。</p>
    <p>五件事必须做对，否则画面会悄悄坏掉：</p>
    <p><b>① MLS 是全局的，要自己收口。</b>用 1/d² 权重时远处解出来的仍是一个像样的
       仿射，整张图会跟着轻微旋转（实测四角漂 0.7 px）。所以每个像素再乘一个
       到最近钉子的 smoothstep 窗口，圈外严格恒等。</p>
    <p><b>② 只在栅格上解，不是每个像素。</b>768×1024 逐像素解 8 个钉子要十几秒；
       改成在长边 140 个节点的栅格上解、重采样时对偏移量做双线性，误差 &lt; 0.02 px。</p>
    <p><b>③ 整行跳过的判据是「严格为 0」，不是「小于 0.5 px」。</b>节点间距 7 px，
       用 0.5 px 当阈值，节点之间那些 0.504 px 的位移会整行漏掉——纯 Python 里
       看不出来，和逐像素判断的 numpy 路径一比就差 2 万多个像素。</p>
    <p><b>④ ARAP 的钉子必须是硬约束。</b>把约束以「大权重」加进 Laplacian 看着更简单，
       但钉子合力不为零、L 的零空间又是常数向量，系统会把整张网格抬成均匀平移
       ——实测整幅画面平移到钉子位移，一个顶点都不形变。</p>
    <p><b>⑤ ARAP 只看边长，所以要加弱锚定。</b>「整张网格刚体转过去」是零能量解，
       只有一个钉子时整个画面会跟着旋转（实测中位位移 44 px）。加 0.06 的弱弹簧
       把远处按住；远处不动时弹簧不受力，不干扰形变。</p>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>实测</h3></div>
      <p>768×1024 图层、两个钉子、影响半径 25%：全分辨率变形 <b>0.15 秒</b>（含读写
         缓冲区，装了 numpy）。预览以前缩在 520 长边、<b>58 毫秒</b>一张（numpy 重采样），
         现在<b>直接调 C</b>，尺寸也放开到屏幕能给的：1600×1200 的图给 1064×798，
         一帧 <b>6～10 毫秒</b>，拖钉子完全跟手。</p>
      <p>1600×2400 的图局部拖一处 <b>0.7 秒</b>，影响半径拉满的全图重采样 <b>1.2 秒</b>
         （纯 Python 兜底分别是 2.4 / 6.2 秒）。ARAP 的网格分解只做一次（24 ms），
         拖钉子时每帧约 20 ms。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>和 PS 差在哪</h3></div>
      <p><b>有：</b>钉子上拖、刚性/自由/ARAP 三档、影响半径、网格叠加、右键删钉子、
         实时预览、非交互的钉子参数。<b>没有：</b>PS 的「深度」（钉子前后层级）、
         以及按 Alt 旋转整根钉子的那套手柄——要大角度旋转请直接转图层。</p>
      <p>图层组、文字层、矢量层会被明确拦下来（它们没有可变的像素），
         报错里直接说要先栅格化，而不是丢一串 GIMP 内部错误。</p>
    </div>
  </div>""",
    ),
    dict(
        key='mesh-warp',
        slug='mesh-warp',
        title='自由变形',
        tag=('变形', 't-distort'),
        count='网格 + 把手',
        menu='SuperMrWang → Distort → 自由变形（网格 + 把手）…',
        menus=['SuperMrWang → Distort → 自由变形（网格 + 把手）…'],
        pdb='lb-plugin-mesh-warp(image, drawables, mesh, output)',
        lede="""木偶变形是「拖内容」，这一支是「给内容套一张自由曲面」：图层上盖一张
   网格，拖交点改形状；选中交点会露出两个把手，拖把手能把网格线弯成曲线——
   鼓包、收腰、翻边这些直线格子做不到的形状，就靠这一步。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>怎么用</h3><span class="pill">拖点、再拖把手</span></div>
      <p>选图层 → 菜单 → 直接<b>拖网格交点</b>就是变了形。<b>鼠标划过哪个交点，
         它的四个把手圆点就亮出来</b>，不用先点一下选中；圆点就是把手，按住拖，
         网格线弯成曲线——「拐弯」靠的就是这一步。</p>
      <p><b>把手很小不好点？按住 Shift 拖交点。</b>位置不动，直接把两个把手
         往拖动方向掰：横拖弯竖着的线，竖拖弯横着的线。这是「只想拐弯、不想
         挪位置」时最顺的一条路。</p>
      <p><b>拖到边界会停住。</b>网格一旦自交，映射就不再一一对应，画面会先起褶子、
         再大一点整片花掉（白区里散着断线）。所以拖动时实时检查格子有没有翻过去：
         要翻就把这一步收回到不翻的位置，手感是「顶住了」，而不是「突然糊了」。
         把手弯到 90° 都不算翻，正常拐弯不会被拦。</p>
      <p><b>右键点交点</b>把那个点复位，选中后按 Delete 也行；右边有「重置选中」
         和「全部重置」。<b>网格密度</b>是<b>两个数字框：「横 × 竖」</b>，各 1～12 格，
         <b>横竖分开设</b>——做横向的带子就 8×2、做竖高的瓶子就 2×8，不必再迁就
         正方形。PS 默认那档是 3×3；只是想局部多几根线，就 <b>Alt+点击</b>加(
         见下），那才是无损的。</p>
      <p>虚线是原位网格，实线蓝的是变形后的网格，两者差多少一眼能看出来。</p>
      <p>输出三档，第一档是 <b>非破坏滤镜</b>（对话框默认）：网格挂在
         <code>lb:mesh-warp</code> 这条滤镜上，<b>像素一个字节都不动</b>，随时能改参数
         或关掉，重跑对话框会从滤镜里把网格读回来接着拖。另外两档是
         <b>覆盖当前图层</b>、<b>复制到新图层</b>（把结果烤进像素）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>非交互也能跑</h3></div>
      <p>网格是过程参数 <code>mesh</code>：第一段是格数，后面按行优先每个交点
         六个（或七个）数——
         <code>x,y,ux,uy,vx,vy,auto</code>，前两个是交点位置，中间四个是两个
         把手向量，最后一个 1/0 表示把手自动还是已手拖。写两个数就只给位置，
         其余按恒等网格补齐：</p>
      <p><code>lb-plugin-mesh-warp 图层 mesh="3,3; 100,200; 150,180" output=replace</code></p>
      <p>对话框点应用时就是把网格写成这个字符串再跑一遍，所以脚本能完整复现。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>自己加分割线</h3><span class="pill">Alt + 点击</span></div>
      <p>拖点不够用的时候，<b>按住 Alt 在画面上点一下</b>，就在点到的位置多一条网格线——
         方向跟着离得最近的那条线（竖向的线更近就加竖线）。下拉里的档位会变成
         <b>custom</b>，因为格数不再是正方形了。上限 12 条。</p>
      <p>这跟 PS 的 Alt+拖网格线是同一件事：<b>局部加密</b>。左边第 1 列可以只切成两半，
         右边第 3 格还是整块——不是整张网格一起变密。</p>
      <p>加过线的网格写回 <code>mesh</code> 参数时会多两段
         <code>u:0,1.33,1.83,2.67,4</code> 和 <code>v:…</code>，记的是每条线在参数空间
         里的位置。老串没有这两段，读回来就是等分。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>加一条线要付什么代价</h3></div>
      <p>格界不再等距，但<b>参数空间仍线性对应原图</b>，所以「哪个像素来自哪儿」一个字
         没变，变的只是插值。新线的交点和切向都从原曲面上取，于是画面几乎不动：温和
         变形（±10 px）实测曲面偏差 <b>0.6 px</b>、整张偏移场逐节点差 <b>0.4 px</b>。</p>
      <p>大幅变形下它会变成一次<b>重拟合</b>（±60 px 时 2–5 px）。因为我们每个角只存
         「位置 + 两个切向」，面片中间四个控制点的 twist 是靠四角位置估的，细分之后两侧
         的 twist 对不上。PS 存的是整张控制点网，它的细分是精确的——这是表示上的差距，
         不是算错。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>加线时三处最容易错</h3></div>
      <p><b>① 参数范围必须跟着列数走。</b>源坐标按 <code>u/cols</code> 铺，加一列就得把
         整条轴按 (cols+1)/cols 缩放，漏了整张图平移一次。</p>
      <p><b>② 切向要除以这个缩放系数。</b>切向是「每参数单位」的导数，参数变短，同一个
         像素跨度对应的导数就跟着变小。</p>
      <p><b>③ 把手圆点按格宽换算。</b>格宽不等时把手画在「节点 ± 切向×格宽/3」；顺手写成
         「± 切向/3」的话，窄格的把手会戳到隔壁格外面，拖起来还差一档。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3></div>
      <p>插线本身是 O(节点数)，一瞬间的事；预览由 C 直接渲染，一帧 40 毫秒上下，
         多一条线只多几片，手感不变。预览尺寸按屏幕可用区算——1600×1200 的图给
         1064×798，是以前 480 长边的两倍多，网格节点和把手才点得准。</p>
      <p>回归里盯的是「插线前后画面不动」：恒等网格插完线必须仍判为恒等（一个像素都不
         重采样）、新线的交点必须落在原曲面上（实测 0.00e+00 px）、两张偏移场逐节点差
         &lt; 0.5 px。</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>它是怎么算的</h3><span class="pill">FFD + 双三次 Bezier 面片</span></div>
    <p>标准做法叫 <b>FFD</b>（自由变形）：一格 = 一张 <b>4×4 控制点的双三次
       Bezier 曲面片</b>，把参数 (u,v) 映到图像坐标。角点是交点本身，边上 8 个
       点是「交点 ± 切向/3」——那把手的三个单位正好对应一个控制点，这也是
       PS 里把手为什么画在离交点那么远的地方。</p>
    <p>变形是反着做的：对每个目标像素 p，用 <b>Newton</b> 解 P(u,v) = p，
       拿到参数 (u,v) 之后，<b>源坐标取原位格上的位置</b>，再交给重采样。
       现场栅格（长边 140 个节点）算完后与木偶变形共用同一套
       <code>warp_rgba</code>，所以两条变形路线在像素层面是同一段代码。</p>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>五个不下心就翻车的细节</h3></div>
      <p><b>① 源坐标是 uv 在原位格上的位置，不是曲面上的位置。</b>曲面只回答
         「这个像素该落在哪个 uv」，源图是按原尺寸铺开的。弄反了画面会整体
         平移一次，看着像「没对齐」，很难往算法上想。</p>
      <p><b>② 面片中间四个控制点要加 twist 项。</b>只写「± 切向/3」的话，恒等
         网格解出来每格中心也是偏的——曲面就不再是平面了。补
         (P11-P10-P01+P00)/9 之后，恒等网格的场精确为 0。</p>
      <p><b>③ 把手必须自动限幅。</b>拖走中间交点 80 px，右边那格只剩 26 px 的弦
         却还带着 66 px 的切向，控制多边形来回折、格子自交，反解出两个分支，
         画面撕一道。所以拖节点时按邻居重算切向，并限到相邻弦长以内。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>还有两个</h3></div>
      <p><b>④ Newton 要限步。</b>曲面在交点附近被压扁时局部导数很小，一步能跨
         掉一整格，落到隔壁导数大的地方再跳回来——实测在格界上无限来回震，
         最后交出一个差 12 px 的解。单步限到 0.75 格就好了。</p>
      <p><b>⑤ 换网格密度是「重新拟合」，不是无损。</b>变密几乎看不出来
         （3→6 格误差 1.6 px），变稀（5→2）形状会明显不一样——一张 2×2 网格
         本来就只有一格，装不下复杂曲面。建议先定密度再拖。</p>
      <p>把手是<b>对称</b>的：一个交点的切向被左右两格共用，所以跨格 C1 连续。
        想要尖角目前做不到（PS 的把手也是成对拖的）。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>实测</h3></div>
      <p>768×1024 图层、拖一个交点 + 弯一处把手：<b>0.41 秒</b>（含读写缓冲区）。
         1600×2400 全流程 <b>1.3 秒</b>（解场 150 ms、重采样 1.16 s）。</p>
      <p>网格变形是<b>全局</b>的：只要动了一处，整幅画面都要重采样，所以预览尺寸
         直接决定一帧多贵。以前预览挤在 <b>480 长边</b>——不是因为够用，是因为
         Python/numpy 那条路一帧要 <b>84～97 毫秒</b>，再大就拖不动；对话框里于是只有
         巴掌大一块，节点挤成一团、把手圆点几乎点不中。现在
         <b>直接调算子里的 C</b>（ctypes 把像素指针传给 <code>mw_render_rgba_u8</code>），
         同一张 480×360 只要 <b>9 毫秒</b>，尺寸就交给 <code>preview_geom</code> 按屏幕
         可用区算：1600×1200 给到 <b>1064×798</b>，一帧 43 毫秒，拖动仍然跟手。</p>
      <p>为什么能快这么多、又不会出现「预览和结果不一样」：预览和烘焙调的是
         <b>同一个</b> <code>mw_field_for</code> + <code>mw_sample</code>，只是尺寸不同。
         实测同一张图两边逐像素差<b>中位 0、最大 1 级</b>（16 位输出取整那一下）。
         拿不到 .dll（别的机器、老版本算子）时自动退回 numpy 那条路，状态行末尾会
         从 <code>(C)</code> 变成 <code>(py)</code>，一眼就能看出走的哪条。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>和 PS 差在哪</h3></div>
      <p><b>有：</b>网格交点 + 贝塞尔把手、横竖分开的 1～12 格密度、Alt+点击自己加分割线、
         原位网格虚线对照、实时预览、脚本参数。<b>没有：</b>PS 的「变形预设」
         （弧形 / 旗帜 / 鱼眼那排），也没有「拆分 / 合并格子」（加线是重新拟合，
         不是保留原控制点的精确细分），以及木偶变形那边的「深度」层级。</p>
      <p>参照物：<b>Krita 的变形工具</b>（Warp）用的是同一类双三次曲面网格，
         <b>GIMP 自己的 Warp Transform</b> 是「推/拉」画笔式的，都值得对照着看。
         PhotoShop 的网格也是这个路子，所以手感能对上。</p>
    </div>
  </div>""",
    ),
    dict(
        key='vanishing-point',
        slug='vanishing-point',
        title='消失点',
        tag=('变形', 't-distort'),
        count='透视平面',
        menu='SuperMrWang → Distort → 消失点（透视平面）…',
        menus=['SuperMrWang → Distort → 消失点（透视平面）…'],
        pdb='lb-plugin-vanishing-point(\n    image, drawables, planes, mode, along, output, stairs)',
        lede="""这一支不拽像素，它是**给画面标一块「有透视的平面」**：拖一个四边形，
   它就代表三维世界里的一块矩形；网格按世界坐标等距铺开，于是自然朝消失点收敛。
   标好之后能往回拉——把整张图透视贴上去，或者把这块画面拉正成矩形；也能把这块
   平面**折成一级级台阶**，同一张图沿台阶连续铺上去。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>怎么用</h3><span class="pill">拖一个四边形</span></div>
      <p>选图层 → 菜单 → <b>在画面上拖出一个四边形</b>。这就是一块平面。拖它的四个角，
         让它贴住真实的墙、地面或桌面——不用很准，网格会告诉你差多少。</p>
      <p>选中平面后，每条边的中点有一个<b>小三角</b>，拖它就能从这条边再长出一块相邻
         平面。方向有两种：「<b>垂直于这块</b>」（PS 的墙对墙）和「<b>在同一平面里</b>」
         （同一面墙接着铺）。新平面的两条深度线自动指向垂直方向的消失点，所以不用手调
         就接得上。</p>
      <p>右侧两种活：<b>透视贴图</b>把整张图按四角铺到这个平面上，平面外一个字节都不动；
         <b>拉正</b>反过来，把这块画面展开成一张新矩形图层——拍歪的海报、路牌、名片
         就是这么救回来的。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>从脚本</h3></div>
      <p>平面是 <code>planes</code> 参数：每个平面 8 个数，四个角按
         「左上、右上、右下、左下」的顺序，多个平面用 <code>|</code> 隔开。<b>第一个</b>
         是生效的那个，其余只是留着让对话框下次还能读回来。</p>
      <p><code>lb-plugin-vanishing-point layer|<br>
         &nbsp;&nbsp;planes="100,120,900,80,1020,700,60,780" mode=paste output=replace</code></p>
      <p>只给 6 个数也行，第四角补成平行四边形。对话框按「应用」时会把用过的平面串写回
         这个参数，所以手动拖出来的东西脚本能原样重放。</p>
    </div>
  </div>

  <div class="dl primary-dl">
    <div class="dl-head"><h3>怎么算的</h3><span class="pill">单应 + 垂心</span></div>
    <p>四边形四角 ↔ 世界坐标的 (0,0)/(1,0)/(1,1)/(0,1)，八个参数用四点法解一个 8×8
       线性方程组，得到<b>单应矩阵</b> H。之后所有事都是 H 的正反用：</p>
    <p>· <b>网格</b>：世界里 s = k/N 的等距直线，逐条投影到图像上。所以网格是真的「等距」，
       近处稀、远处密，收敛到消失点——不是画出来的装饰线。<br>
       · <b>贴图</b>：源图四角 ↔ 平面四角，反解每个目标像素落在源图哪儿。<br>
       · <b>拉正</b>：反过来，输出矩形的 (s,t) 经 H 找到源坐标。</p>
    <p>第二面墙靠一条纯射影几何的事实：<b>三个互相垂直方向的消失点，构成一个三角形，
       而主点（画面中心）正是它的垂心</b>。所以知道平面自己的两个消失点，第三个方向
       不用相机内参、不用焦距就算得出来——只假设主点在画面正中。</p>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>折成台阶</h3><span class="pill">同一张图沿台阶连铺</span></div>
      <p>标好平面后勾上<b>「折成台阶」</b>，这块平面就沿一条边折成一级级台阶，图
         <b>沿台阶连续</b>铺上去——不是每级各贴一份，而是整张图被折过去。<b>起边</b>
         选折痕从哪条边起（远 / 近 / 右 / 左），<b>级数</b> 1–24，<b>踢面高</b>与
         <b>踏面深</b>都是平面的比例；踏面深填 0 = 自动 = 1/级数，正好铺满平面。
         踢面高取踏面深的一半左右最像真楼梯。</p>
      <p>脚本里是 <code>stairs="起边,级数,踢面高,踏面深,反向"</code>，例如
         <code>stairs="0,6,0.075,0,0"</code>；空串就是不起台阶。按「应用」时这一串
         会写回参数。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么必须真三维</h3><span class="pill">一块平面反解整台相机</span></div>
      <p>第一版想省事：拼几个四边形凑出台阶。越往上级差得越远，第 6 级的边已经偏出
         十几个像素——因为「抬高一个边长」在透视里不是「往下挪几个像素」，而是往
         <b>第三个维度</b>走一步。</p>
      <p>所以改成反解相机。一块有透视的平面其实把整台针孔相机都定死了：主点固定在
         画面中心、像素是方的、两个消失点正交，于是
         <code>f² = −(Vu−O)·(Vv−O)</code> 唯一给出焦距。<code>b = K⁻¹·p</code> 把三个
         角换算到相机坐标，归一化得旋转 <code>R</code>，<code>n = r1×r2</code> 是法线，
         相机位置 <code>eye = −Rᵀ·b3</code>。<b>z 的单位</b>是两边边长的几何平均——
         <code>b</code> 本身就是「长度 × 方向」，不是纯方向（这一条算错过一次，
         三维投影差到 278 px）。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>台阶的三个坑</h3></div>
      <p><b>1. 没有透视的四边形解不出焦距。</b>四边两组平行时（比如正对着拍的矩形），
         退回 <code>f = 1.5 × 长边</code>，状态行会写 approximate。这时正中间的踢面
         正好<b>侧对相机</b>、退化成一条线，必须丢掉——不丢就是一条白缝，还会让单应
         解奇异直接崩。</p>
      <p><b>2. 图会上下反。</b>源图第 0 行落在<b>最近</b>那一级上（v 沿台阶累加），
         所以海报要先上下翻一下才正——实测就是这么发现的。</p>
      <p><b>3. 台阶会自己挡住自己。</b>立起来的踢面盖住后面的踏面。取色判据必须按
         「最后一个覆盖该点的面片」算，不然回归里会误判成贴错。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3></div>
      <p>1600×2400、16 面片：<b>1.54 s</b>；预览 560 长边 16 面片 <b>172 ms/帧</b>，
         拖动跟得上。所有面片共用一块目标缓冲（numpy 里 <code>arr</code> /
         <code>sarr</code> 各只建一次），否则每贴一块面片就要重建 17 MB。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>三个非踩不可的</h3></div>
      <p><b>1. 单应必须先用 Hartley 归一化。</b>直接拿原始像素（上千的量级）解 8×8，
         条件数能差到 1e8，纯 Python 的高斯消元只好到 1e-3——四边形一歪，贴图就错位。
         归一化到「质心在原点、平均距离 √2」之后，残差回到 1e-13。</p>
      <p><b>2. 网格线要按齐次分母 w 的符号断开。</b>世界坐标往远处延伸时 w 会过零，
         越过零点的那一段是「地平线之后」的像，跟前面的点连起来会画出一条<b>横穿画面
         的假线</b>——看着像画面裂了一道。</p>
      <p><b>3. 第三方向的消失点不是「另一组边的交点」。</b>拿平面另一对边去求，得到的是
         同一个消失点，墙会贴到墙自己身上。必须是垂心关系。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>…还有两个</h3></div>
      <p><b>4. 延伸平面的两个远角不能取同一个 t。</b>都写成 <code>p + t·(V−p)</code> 会让
         新平面的上下两条边严格平行，u 方向消失点跑到 1e16 外面——等于把透视扔了。
         正确解：q0 落在 p0 的射线上，q1 由「落在 p1 的射线上」和「q0q1 过共享边方向的
         消失点」两条约束解出来。</p>
      <p><b>5. 贴图的边界是硬边，拉正的边界会脏。</b>贴图时平面外保持原样，所以边缘是
         一刀切；拉正时输出顶边正好压在四边形边上，双线性会混进一点外面，实测差 3 个
         色阶——肉眼看不出来，但回归里要把边界 6 px 排除掉，否则会误报。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>实测</h3></div>
      <p>768×1024 图层：贴图 <b>127 ms</b>、拉正 <b>71 ms</b>。1600×2400：
         贴图 <b>635 ms</b>、拉正 <b>356 ms</b>。比木偶变形慢，因为整块平面都要重采样；
         但只算平面的外接框，比「整幅透视」省一半。</p>
      <p>预览按 <b>560 长边</b>跑，一次约 <b>75 ms</b>，拖动跟得上手。纯 Python 那条路
         大概慢 4 倍（1200×900 一秒钟），只在没装 numpy 时用。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>和 PS 的差异</h3></div>
      <p><b>有：</b>四边形平面、朝消失点收敛的透视网格、从边延伸相邻平面（垂直 / 延续
         两种）、透视贴图、拉正成新图层、把平面折成 n 级台阶并沿台阶连续贴图。<br>
         <b>没有：</b>PS 最常用的那个「在平面上用图章/画笔，笔画自动贴合透视」——那要写
         GIMP 的绘图工具类，工作量是另一件事，台阶上同理；也没有导出 3D、没有「平面
         自动吸附共享消失点」（我们是靠拖角对齐）。台阶只有<b>一段</b>折（n 级同向），
         PS 可以在一个平面里画好几段折线、中途拐弯，这一点还没做。</p>
      <p>想对照着看：Krita 的「透视辅助线」是同一类东西（但只画线、不贴图），
         而真正的教科书名字叫 <b>homography-based image transfer</b>。</p>
    </div>
  </div>""",
    ),
    dict(
        key='ai-frequency',
        ai_comfy=True,
        slug='ai-frequency-separation',
        title='高低频磨皮（AI 预修）',
        tag=('磨皮', 't-tone'),
        count='一键 + 预修',
        menu='SuperMrWang → Retouch → 高低频磨皮（AI 预修）',
        menus=['SuperMrWang → Retouch → 高低频磨皮（AI 预修）',
               '图层右键 → SuperMrWang → Retouch → 高低频磨皮（AI 预修）'],
        pdb='lb-plugin-ai-frequency-separation(\n    image, drawables, prompt, source, radius,\n    denoise, server, checkpoint, steps, group)',
        lede="""结构和「高低频磨皮」一模一样，只有内容换了人做：两层用的不是原图，
       而是一张<b>已经修过一遍的参考图</b>——AI 低重绘，或本地降采样模糊。所以
       打开文件时色块已经铺平、痘印已经淡掉，接着在高频层补几笔就行，不必从
       零开始。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">与原版同构</span></div>
      <pre><code>高低频磨皮（AI 预修）      组 · 穿透（带 alpha 时组上还有蒙版）
  ├─ 2 · 高频（细节）      颗粒合并 + 高通
  ├─ 1 · 低频（影调）      正常 + 高斯模糊
  └─ 原图层（不动，隐藏它也不掉东西）</code></pre>
      <p>合成结果等于<b>参考图</b>，不是原图——这就是「工作痕迹」。想对照就把组
         的眼睛关掉，或按住 <kbd>Shift</kbd> 点眼睛临时隐藏。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>参考图从哪来</h3><span class="pill">参数 source</span></div>
      <p><b>AI 参考</b>：整层交给 ComfyUI 低重绘（默认 <code>denoise 0.35</code>），
         它认得出「这是皮肤」——痘印、泛红、局部色块被推平，五官与轮廓留住。
         <b>本地参考</b>：整层降采样再放大当低通，毫秒级、零依赖。</p>
      <p>AI 连不上时自动退回本地参考，并在提示里说清原因，不会弹一堆报错。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>选区</h3></div>
      <p>有选区时，参考图只替换选区内，选区外逐像素等于原图——可以只修脸，
         不动头发和背景。这一点三支 AI 磨皮插件一致。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>接着怎么修</h3></div>
      <ol class="steps">
        <li><b>高频层</b>：剩下没抹干净的痘印、毛孔，图章或修复画笔点掉。</li>
        <li><b>低频层</b>：还想更平的地方用低透明度画笔铺一下；铺过头就吸周围的
            颜色盖回来。</li>
        <li><b>半径</b>就是分界线：1024 长的图从 4–8 px 起试。两层半径是同一个量，
            改的时候一起改，否则叠回去就不再是参考图。</li>
      </ol>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3><span class="pill">check_retouch_ai*.py</span></div>
      <p>结构 / 混合模式 / 滤镜与原版逐项一致；本地参考路径在软斑测试图上把高频
         残留压到 <b>≤ 6 码</b>（原图为对照组）；参考图与原图一致时（mock 返回原图）
         痘印一位不动，说明不是无条件抹平。</p>
      <p class="muted small">参数：<code>source</code>（ai / local）、
         <code>radius</code> 0.2–100 px、<code>denoise</code> 0.05–0.9、
         <code>prompt</code>、<code>server</code> / <code>checkpoint</code> /
         <code>steps</code>、<code>group</code>。</p>
    </div>
  </div>""",
    ),
    dict(
        key='ai-dodge',
        ai_comfy=True,
        slug='ai-dodge-burn',
        title='双曲线磨皮（AI 预修）',
        tag=('磨皮', 't-tone'),
        count='一键 + 预涂',
        menu='SuperMrWang → Retouch → 双曲线磨皮（AI 预修）',
        menus=['SuperMrWang → Retouch → 双曲线磨皮（AI 预修）',
               '图层右键 → SuperMrWang → Retouch → 双曲线磨皮（AI 预修）'],
        pdb='lb-plugin-ai-dodge-burn(\n    image, drawables, prompt, source, amount,\n    prepaint, radius, denoise, server, checkpoint, steps, group)',
        lede="""还是提亮 / 压暗两条曲线层，区别是<b>蒙版已经不是全黑</b>：插件先把参考
       图和原图的亮度差算出来，折成蒙版浓度，预先涂上七成。打开文件就是「已经
       打过一轮双曲线」的状态。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">预涂蒙版</span></div>
      <pre><code>双曲线磨皮（AI 预修）      组 · 穿透
  ├─ 2 · 压暗（已预涂）    正常 + 压暗曲线 + 预涂蒙版
  ├─ 1 · 提亮（已预涂）    正常 + 提亮曲线 + 预涂蒙版
  └─ 原图层（不动）</code></pre>
      <p>暗于参考图的地方落在提亮蒙版，亮于参考图的地方落在压暗蒙版；背景与
         没差值的地方仍然是黑的（不参与合成）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>浓度不是全图一个系数</h3></div>
      <p>曲线是 <code>x + d·4x(1−x)</code>：两端不动、中间最鼓。所以同一个「提亮
         0.06」，在中灰需要 <code>蒙版 0.5</code>，在暗部要浓得多。插件按每个像素
         自己的亮度反算浓度，而不是全图乘一个数。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么只补七成</h3><span class="pill">prepaint 70%</span></div>
      <p>一次补平通常过头——参考图本身也有误差。默认 70%，剩下的交给你的画笔；
         想完全交给 AI 就设 100%，只想做个提示就设 30%。设 0% 等于原版插件
         （两张全黑蒙版）。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>接着怎么修</h3></div>
      <ol class="steps">
        <li>点中某一层的<b>蒙版缩略图</b>，柔边画笔、白色、不透明度 10–20%。</li>
        <li>不够亮的位置再补白；画过头用黑色盖回去，或者把预涂浓度调低重跑。</li>
        <li>想检查涂了多少：按住 <kbd>Alt</kbd> 点蒙版缩略图，只看黑白分布。</li>
      </ol>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3><span class="pill">check_retouch_ai*.py</span></div>
      <p>软斑测试图上，暗斑处提亮蒙版 ≈ <b>116</b>、亮斑处压暗蒙版 ≈ <b>129</b>，
         交叉位置为 0；<code>prepaint=0</code> 时两张蒙版全黑（与原版行为一致）；
         选区外的蒙版保持 0。</p>
      <p class="muted small">参数：<code>source</code>、<code>amount</code> 1–40%、
         <code>prepaint</code> 0–100%、<code>radius</code>（本地参考）、
         <code>denoise</code>、<code>prompt</code>、<code>group</code>。</p>
    </div>
  </div>""",
    ),
    dict(
        key='ai-grey',
        ai_comfy=True,
        slug='ai-neutral-grey',
        title='中性灰磨皮（AI 预修）',
        tag=('磨皮', 't-tone'),
        count='一键 + 预校正',
        menu='SuperMrWang → Retouch → 中性灰磨皮（AI 预修）',
        menus=['SuperMrWang → Retouch → 中性灰磨皮（AI 预修）',
               '图层右键 → SuperMrWang → Retouch → 中性灰磨皮（AI 预修）'],
        pdb='lb-plugin-ai-neutral-grey(\n    image, drawables, prompt, source, prepaint,\n    radius, denoise, server, checkpoint, steps, group)',
        lede="""那张 50% 灰的柔光层<b>不再是平的 128</b>：插件把「参考图比原图亮多少 /
       暗多少」反解成柔光需要的灰度，直接写进灰层。打开文件就是已经做过一轮
       中性灰、肤色被拉平了一截的状态。""",
        body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">128 ± 偏移</span></div>
      <pre><code>中性灰磨皮（AI 预修）        组 · 穿透
  └─ 1 · 中性灰（已预校正）  柔光 + 128±偏移的像素
     └─ 原图层（不动）</code></pre>
      <p>灰层里每个像素都是解析解：把柔光公式 <code>out = x + (2g−1)·…</code> 反推
         出「要让这里变成参考图，g 该是多少」，不是估的。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>它是像素，不是蒙版</h3></div>
      <p>所以橡皮擦、选区填充、渐变、复制粘贴都能用——比双曲线那版更耐改；
         代价是画过头只能靠 <code>#808080</code> 盖回去（双曲线那版把蒙版涂黑就行）。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>预校正多少</h3><span class="pill">prepaint 70%</span></div>
      <p>默认补七成：暗斑处灰层 &gt; 128（提亮）、油光处 &lt; 128（压暗）、背景
         ≈ 128（不动）。设 0% 就是原版那张平灰层。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>接着怎么修</h3></div>
      <ol class="steps">
        <li>选中灰层，柔边画笔、不透明度 5–15%：白色提亮、黑色压暗。</li>
        <li>画过头：前景色设 <code>#808080</code> 涂回去，等于「这一块没做」。</li>
        <li>觉得整体太强 / 太弱：关掉组，用 <code>prepaint</code> 换个比例重跑，
            原图层一直没动。</li>
      </ol>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3><span class="pill">check_retouch_ai.py</span></div>
      <p>灰层代回柔光公式，能把原图推回参考图的误差 <b>≤ 1 码</b>（六组亮度/差值
         组合，含正负方向）；软斑图上暗斑处 <b>162</b>、亮斑处 <b>97</b>、背景
         <b>128</b>；<code>prepaint=0</code> 整层 128。</p>
      <p class="muted small">参数：<code>source</code>、<code>prepaint</code> 0–100%、
         <code>radius</code>（本地参考）、<code>denoise</code>、<code>prompt</code>、
         <code>group</code>。</p>
    </div>
  </div>""",
    ),
    dict(
        key='alpha-curves',
        slug='alpha-curves',
        title='Alpha Curves（透明通道曲线）',
        tag=('蒙版', 't-mask'),
        count='α',
        area='Mask',
        menu='SuperMrWang → Mask → Alpha Curves',
        menus=['SuperMrWang → Mask → Alpha Curves',
               '图层右键 → SuperMrWang → Mask → Alpha Curves'],
        pdb='lb-plugin-alpha-curves(image, drawables, channel, shape)',
        lede="""GIMP 的曲线工具本来就有 Alpha 通道，但那条曲线只能调「已经存在的
       透明度」——它不知道红通道是多少。要按颜色通道决定透明度，得先把通道搬进
       alpha。这个插件把两步都做了：一条 <b>通道 → Alpha</b>，接一条
       <b>可以随便画的 alpha 曲线</b>。两条都是非破坏滤镜。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>生成的结构</h3><span class="pill">两条滤镜</span></div>
      <pre><code>Alpha Curves
  ├─ 2 · Alpha 曲线        gimp:curves（通道 = Alpha）
  └─ 1 · 通道 → Alpha      lb:channel-range-to-alpha</code></pre>
      <p>第 1 条把选定通道线性写进 alpha：四个滑块拉到 <code>l1=0、l2=255、
         r1=r2=255</code>，斜坡占满全程，映射退化成「alpha ← 通道值」。
         第 2 条就是普通的曲线，输入正好是那个通道值。</p>
      <p>点开「2 · Alpha 曲线」，初始是<b>三个控制点、一条平顶线</b>：
         <code>(0, 255)</code>、<code>(128, 255)</code>、<code>(255, 255)</code>。
         曲线是 <b>SMOOTH（平滑样条）</b>而不是手绘采样——只有三个抓手，往下拖任意
         一个，整条曲线跟着走，不用在几十个采样点里找位置。往下压一点就是「暗部
         半透明」，压到底就是「暗部全透明」，画成什么就是什么映射。</p>
      <p>挂上来的瞬间该通道被推成满不透明；想要「装上去先不动」的样子，把三个点
         拖回对角（45°）即可。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>和 Range → Alpha 的关系</h3></div>
      <p><code>lb:channel-range-to-alpha</code> 一步做完两件事：选通道、按四滑块
         的梯形把它乘进 alpha。曲线不能一步做——它看不到「通道是多少」，只能
         作用于 alpha 自己。所以这里拆成两条：先把通道搬进 alpha，再画曲线。</p>
      <p>反过来，算子的梯形只是曲线的一种形状。<code>shape</code> 参数给了四个
         现成起点（都是平滑曲线，挂上去以后随便拖）：</p>
      <ul class="deps">
        <li><code>auto</code> / <code>flat</code>（默认）＝ 三点全在顶，alpha 拉满</li>
        <li><code>band</code> ＝ 混合颜色带：两端收、中间满</li>
        <li><code>identity</code>（45°）＝ alpha 等于通道值，纯拷贝</li>
        <li><code>soft</code> ＝ smoothstep：暗部更透、亮部更实</li>
      </ul>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>实测</h3><span class="pill">check_alpha_curves.py</span></div>
      <p>恒等曲线时 alpha 与所选通道值差 <b>≤ 1 码</b>，RGB 一个码都不动；
         默认平顶把 alpha 拉满（最暗处也是 1）；<code>band</code> 与
         <code>lb:channel-range-to-alpha</code> 的梯形在两端与中段一致（<b>≤ 3 码</b>），
         最陡的拐角被样条磨圆，最多差 <b>42 码</b>——曲线是软的，算子的是硬拐角。
         8 位图 ≤ <b>2 码</b>。</p>
      <p>原图半透明时是<b>乘</b>不是替换：<code>alpha = 原 alpha × 曲线(通道值)</code>，
         与算子一致。回归 45 项。</p>
    </div>
  </div>
  <p class="note">两条滤镜都在图层上，图层面板里可以逐条关掉、随时改参数，不碰像素。
     选 <b>alpha</b> 作源通道时只挂第 2 条——那是最纯粹的「给现有透明度画曲线」。
     曲线的 trc 钉在编码值上，与 <code>channel-range-to-alpha</code> 的 0–255 滑块
     同一刻度。依赖 <code>lb:channel-range-to-alpha</code>（除 alpha 模式外）。</p>""",
    ),
    dict(
        key='color-range',
        slug='color-range',
        title='Color Range（色彩范围）',
        tag=('蒙版', 't-mask'),
        count='▤',
        area='Mask',
        menu='SuperMrWang → Mask → Color Range',
        menus=['SuperMrWang → Mask → Color Range',
               '图层右键 → SuperMrWang → Mask → Color Range'],
        pdb='lb-plugin-color-range(image, drawables)',
        lede="""GEGL 的算子参数是静态的：<code>lb:color-mask-select</code> 里高光、
       阴影、中间调各有一组限值，GIMP 的通用对话框会把四根 0–255 的滑杆
       <b>一起摆出来</b>，切换「选择颜色」时一根都不动。这个插件换成自己搭的
       对话框：选颜色系只给容差，选高光只给一根「范围」且默认 192，
       选阴影是 64，选中间调是上下限 64 / 192。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>为什么需要一层壳</h3><span class="pill">静态 vs 联动</span></div>
      <p>GEGL 的属性声明是<b>编译期固定</b>的：<code>property_enum</code> 和四个
         <code>property_int</code> 之间没有任何联动机制，对话框也没法因为枚举变了
         就换掉别的控件。所以算子那边只能四根杆常驻，选「红色」时那四根依旧
         占着界面、全程无效。</p>
      <p>能真正联动的是<b>程序自己的 GTK 对话框</b>。像素运算仍然交给
         <code>lb:color-mask-select</code>——壳只负责「哪个模式该显示哪几根杆、
         各自从多少起步」，所以两条入口算出来的像素完全一致。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>每个模式各自的起点</h3></div>
      <ul class="deps">
        <li><b>红 / 黄 / 绿 / 青 / 蓝 / 洋红</b>：颜色容差 50、最低彩度 0（范围是色相环，没有阈值杆）</li>
        <li><b>高光</b>：范围 <b>192</b>（亮度 ≥ 192 算高光）</li>
        <li><b>阴影</b>：范围 <b>64</b>（亮度 ≤ 64 算阴影）</li>
        <li><b>中间调</b>：下限 <b>64</b> / 上限 <b>192</b></li>
        <li><b>自定颜色</b>：取色按钮（默认纯红）+ 容差 + 最低彩度</li>
      </ul>
      <p>切模式只换页，各页自己记住自己的值：改过高光的 192 再切到阴影、切回来，
         还是改过之后的数。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>预览与落地</h3><span class="pill">红色叠加</span></div>
      <p>拖参数时画面上是<b>红色叠加</b>实时预览（60 ms 内连续改动合并成一次重算）。
         按「确定」时先把叠加关掉再合并，<b>红色不会被烤进图层</b>；蒙版写进
         图层 alpha。按「取消」把预览滤镜整个撤掉，连中途补上的 alpha 通道也回滚。</p>
      <p>与非破坏的区别：这里是<b>一次性应用</b>，合并后不能回改。想随时改参数，
         用菜单里的 <code>lb:color-mask-select</code> 算子版本挂成滤镜——同一份
         参数、同一份像素，只是界面朴素。</p>
    </div>
  </div>
  <p class="note">依赖 <code>lb:color-mask-select</code>；缺算子会明确报错并给出装包提示，
     不会静默什么都不做。图层组没有像素，会拒绝并提示先合并。</p>""",
    ),
    dict(
        key='channel-to-mask',
        slug='channel-to-mask',
        native_only=True,   # 只做原生路径的顺手封装，不含新算法
        title='Channel to Mask（通道转图层蒙版）',
        tag=('蒙版', 't-mask'),
        count='通道 → 蒙版',
        area='Mask',
        menu='SuperMrWang → Mask → Channel to Mask',
        menus=['SuperMrWang → Mask → Channel to Mask',
               '图层右键 → SuperMrWang → Mask → Channel to Mask',
               '通道右键 → SuperMrWang → Mask → Channel to Mask'],
        pdb='lb-plugin-channel-to-mask(image, drawables, channel-name, invert)',
        lede="""原生路线是「图层 → 蒙版 → 添加图层蒙版 → 通道」，弹窗里再挑一条通道，
       而且一次只能伺候一个图层。这个插件把顺序倒过来：先在通道面板选一条，
       再在图层面板选中要挂蒙版的图层，右键一次就好——多选几个就一次挂几个，
       还能顺手反相。和 <code>Layer to Channel</code> 正好是一对反向操作。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>原生也能做，差在哪</h3><span class="pill">四步 → 一步</span></div>
      <p>GIMP 自带「从通道取蒙版」，但路径是固定的：先选中图层，菜单进
         <b>图层 → 蒙版 → 添加图层蒙版</b>，类型选「通道」，弹窗里再挑一条通道。
         三个图层就要走三遍。</p>
      <p>这个插件只补三件事：<b>从右键进来</b>（点哪个图层就给哪个挂）、
         <b>一次多个</b>（图层面板多选，逐个挂上同一份内容）、<b>可反相</b>
         （按通道的补集遮罩，省一次反相操作）。像素结果与原生逐位相同，
         包括中间灰那点漂移。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>灰度值就是遮罩强度</h3></div>
      <ul class="deps">
        <li><b>黑</b> = 完全遮住，<b>白</b> = 完全露出，<b>中间灰</b> = 半透明</li>
        <li>通道取<b>通道面板里右键点中的那条</b>；没点过就用面板里选中的那条，
            图里只有一条通道时直接用它；也可以填名字指定</li>
        <li>图层<b>还没有蒙版</b> → 按原生方式新建</li>
        <li>图层<b>已有蒙版</b> → 先丢掉旧的再新建，结果与原生新建一致，<b>再跑一次就是刷新</b></li>
      </ul>
      <p>偏移的小图层不用管：蒙版跟图层同尺寸，取的是画布上同位置的通道值，
         不会整块错位。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>数值和原生一模一样</h3><span class="pill">128 → 188</span></div>
      <p>GIMP 3 没有「通道直接建蒙版」的入口，原生用户只能走两步：<b>通道 → 选区 →
         选区建蒙版</b>。这个插件走的就是同一条路，调的是同一个
         <code>create_mask(SELECTION)</code>，所以结果逐位相同——包括中间灰那点漂移：
         默认 8 位图上，通道 128 建出来的蒙版是 <b>188</b>，不是 128。</p>
      <p>32 位线性精度的图像上，通道本身就存线性值，直搬恰好正确，这条链路不漂。
         插件不做任何补偿，原生怎样就怎样。</p>
    </div>
  </div>
  <p class="note">不依赖任何自研算子：只调 GIMP 自己的 <code>gimp-image-select-item</code>
     与蒙版 PDB，不自己写像素缓冲。
     从通道面板右键进来时，点的哪条就用哪条，不必再在别处选中一次；
     真找不到源时会明确报错并列出可用的通道名，不会静默什么都不做。
     图层组没有像素，会拒绝并提示先合并。</p>""",
    ),
    dict(
        key='convert',
        slug='convert',
        native_only=True,   # 只做原生路径的顺手封装，不含新算法
        title='Convert（十二向互转 + 路径转位图）',
        tag=('转换', 't-mask'),
        count='十二向 + 位图',
        area='图层转换',
        menu='SuperMrWang → Convert → 十三项',
        menus=['SuperMrWang → Convert → 十三项，按目标命名',
               '图层右键 → SuperMrWang → Convert',
               '通道右键 / 路径右键 → SuperMrWang → Convert'],
        pdb='lb-plugin-conv-* 十三个过程，全部零参数',
        lede="""通道、选区、蒙版、路径四者两两互转，十二个方向各占一个菜单项，点下去
       直接执行、不弹参数框；另外一条 <b>Path to Bitmap</b> 把路径或矢量图层落成像素。原生菜单里这些路分散在四处，而且「蒙版 → 通道」
       「通道 → 路径」这类根本没有直连，只能绕选区两步走。路径这一站是<b>有损闸门</b>：
       它只有几何、没有 alpha，位图进路径时按 50% 等值线取轮廓。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>为什么值得单独做</h3><span class="pill">十三条路，散在四处</span></div>
      <p>原生要办同一件事，得记住三套路径：<b>选择</b>菜单里存通道、<b>通道右键</b>转选区、
         <b>图层面板右键 → 添加图层蒙版</b>再在弹窗里挑类型。同一类操作放在三个地方，
         方向还是反的。</p>
      <p>更关键的是<b>蒙版 → 通道根本没有</b>：GIMP 没有这个过程，只能先「蒙版到选区」
         再「选区存通道」，两步、两处菜单。这个插件把它做成一步。</p>
      <p>路径也一样：<b>路径 → 选区</b>在路径右键里、<b>选区 → 路径</b>在选择菜单里，
         而<b>通道 / 蒙版 ↔ 路径</b>两个方向原生压根没有入口，只能自己拼两步。
         现在这些全在同一个子菜单里，按目标命名。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>十三个方向</h3><span class="pill">全零参数</span></div>
      <ul class="deps">
        <li><b>Channel to Selection</b> · 通道 → 选区</li>
        <li><b>Selection to Channel</b> · 选区 → 通道</li>
        <li><b>Channel to Mask</b> · 通道 → 图层蒙版</li>
        <li><b>Mask to Channel</b> · 图层蒙版 → 通道</li>
        <li><b>Selection to Mask</b> · 选区 → 图层蒙版</li>
        <li><b>Mask to Selection</b> · 图层蒙版 → 选区</li>
        <li><b>Path to Selection</b> · 路径 → 选区</li>
        <li><b>Selection to Path</b> · 选区 → 路径</li>
        <li><b>Path to Channel</b> · 路径 → 通道</li>
        <li><b>Channel to Path</b> · 通道 → 路径</li>
        <li><b>Path to Mask</b> · 路径 → 图层蒙版</li>
        <li><b>Mask to Path</b> · 图层蒙版 → 路径</li>
        <li><b>Path to Bitmap</b> · 路径 / 矢量图层 → 像素图层（矢量图层用它自己的填充与描边原地替换；裸路径按前景色填充）</li>
      </ul>
      <p>没有省略号的菜单项就是<b>点一下直接跑</b>：源全从上下文取，不需要在对话框里
         再选一遍。</p>
      <p>最后一条和前面十二条不一样：前面都是 GIMP 内部几种对象之间倒腾，<b>Path to
         Bitmap</b> 是唯一一条把几何真正落成像素的——路径在 GIMP 里只存几何、没有填充色和
         线宽，所以替它选了「用前景色填内部」这一种落笔方式（与原生「编辑 → 用前景色填充
         路径」同义）。新图层只做路径外接框那么大、偏移对回原位，栅格化一个 24×24 的图标
         不会顺手生成一张 4000×3000 的空图层。要线稿（描边）就用原生「编辑 → 描边路径」。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>源永远是「当前」</h3></div>
      <ul class="deps">
        <li><b>通道</b> = 通道面板里右键点中的那条 → 面板里选中的那条 →
            图里唯一的那条，依次兜底</li>
        <li><b>选区</b> = 当前像素选区；<b>没有选区就当全选</b></li>
        <li><b>蒙版</b> = 选中图层的图层蒙版</li>
        <li><b>路径</b> = 路径面板里右键点中的那条 → 面板里选中的那条 →
            图里唯一的那条，同样三路兜底</li>
        <li>目标：通道 / 路径各新建一条、蒙版挂到选中图层（多选则每个都挂）</li>
      </ul>
      <p>已有蒙版时<b>先丢掉旧的再新建</b>，结果与原生新建逐位一致——改完源再跑
         一次就是刷新。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>结果与原生逐位一致</h3><span class="pill">硬指标</span></div>
      <p>十二个方向都不碰像素缓冲，一律转调 GIMP 自己的过程：通道 / 路径转选区用
         <code>gimp-image-select-item</code>，选区存通道用 <code>gimp-selection-save</code>，
         选区建蒙版用 <code>create_mask(SELECTION)</code>，选区描路径用
         <code>plug-in-sel2path</code>（就是「选择 → 路径」背后那个过程）。
         凡是原生没有直连的，就按原生的两步走：通道 ↔ 蒙版、通道 / 蒙版 ↔ 路径，
         都经选区这一站。</p>
      <p>所以中间灰带着原生那点漂移：默认 8 位图上，通道 128 进选区读回 <b>188</b>，
         选区 128 存通道读回 <b>55</b>；而选区与蒙版之间原生会换算，那一对不漂。
         32 位线性精度的图像上通道本身就存线性值，那六个方向都不漂。
         路径方向跟着这条链走：通道 → 路径是先变成 188 的选区再描轮廓，轮廓落在
         50% 等值线上，和原生手点两步的结果一样。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么单步看着不对</h3></div>
      <p><b>不是插件算错。</b>通道和蒙版存的是 <code>Y'</code>（sRGB 编码），选区存的是
         线性 alpha。原生在通道与选区交界处把 <code>Y'</code> 当线性覆盖率直搬，
         128 就变成了 188，反方向压成 55。</p>
      <p><b>往返会互相抵消。</b>188 存回通道又变回 128，所以连着跑两步看不出问题，
         单步才明显。这是原生的行为，插件不做补偿。</p>
      <p><b>蒙版是 8bit。</b>极暗处有 ±1 的量化误差，原生也一样；偏移图层按画布
         坐标对齐，原生建蒙版时同样如此。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>和 Channel to Mask 的关系</h3></div>
      <p><b>Channel to Mask...</b>（Mask 组，带省略号）是同一个动作的<b>可配置版</b>：
         能指定通道名、能反相、能一次挂多个图层。</p>
      <p><b>Convert → Channel to Mask</b>（无省略号）是一键版：取通道面板里点中的
         那条、不反相。日常右键直接跑一键版，需要细调时走带参数的那个。</p>
    </div>
  </div>
  <p class="note">十二个方向都不依赖自研算子，只调 GIMP 自己的通道、选区、蒙版、路径 PDB。
     缺源时会明确说缺什么（没选通道 / 没蒙版 / 没路径 / 图层组没有像素），不会静默什么都不做。
     <b>路径这一站有损</b>：羽化、渐变、抗锯齿的边缘在「位图 → 路径」时会被压成硬边界，
     这是路径只有几何、没有 alpha 决定的，原生 To Path 同样如此。反过来「路径 → 位图」
     不丢任何东西，栅格化出来就是干净的硬边。<b>矢量图层</b>（GIMP 3.2）是另一条路：
     它自己有填充色、描边色和线宽，所以按它<b>自己的样子</b>渲染成位图，替换掉原来那一层，
     不会再额外盖一张前景色的图上去。</p>""",
    ),
    dict(
        key='max-min',
        slug='max-min',
        title='最大 / 最小值（Max / Min）',
        tag=('蒙版', 't-mask'),
        count='2 个方向',
        area='Mask',
        menu='SuperMrWang → Mask → 最大值 / 最小值',
        menus=['SuperMrWang → Mask → 最大值 / 最小值',
               '图层右键 → SuperMrWang → Mask → 最大值 / 最小值'],
        menus_en=['SuperMrWang → Mask → Maximum / Minimum',
                  'Layer right-click → SuperMrWang → Mask → Maximum / Minimum'],
        pdb='lb-plugin-max-min(image, drawables, mode, radius, shape, affect-alpha)',
        lede="""Photoshop 的「最大值 / 最小值」滤镜：每个像素取邻域内的最大或最小值。
       最大值把亮区往外推、吞掉暗处的小点；最小值收亮区、啃掉残留的白边。
       GIMP 3 已经不带这个功能了——<code>gegl:dilate</code> / <code>gegl:erode</code>
       没被编进官方构建，<code>plug-in-dilate</code> 也早在 2.10 之后移除。
       所以这里用的是本项目自己的算子 <code>lb:max-min</code>。""",
        body="""<div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>两个方向，一件事的两面</h3><span class="pill">形态学</span></div>
      <p><b>最大值（膨胀）</b>：每个像素取邻域内的最大值，亮区向外长一圈，暗处的小点被吞掉。
         <b>最小值（腐蚀）</b>：取最小值，亮区向内收缩，白底上的黑点被抹掉、抠图残留的白边
         被啃干净。</p>
      <ul class="deps">
        <li><b>扩边 / 收边</b> · 蒙版、通道上加减一圈</li>
        <li><b>去灰尘点</b> · 最小值收拾亮斑，最大值收拾暗斑</li>
        <li><b>发光底图</b> · 最大值先撑开高光，再叠回去就是柔光晕</li>
        <li><b>做厚度</b> · 最小值内缩一层，与原图求差就是描边</li>
      </ul>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>GIMP 里为什么得自己写</h3></div>
      <p>2.10 之前有「滤镜 → 通用 → 膨胀 / 腐蚀」，之后交给 GEGL 的
         <code>gegl:dilate</code> / <code>gegl:erode</code>。这两个属于 GEGL 的
         workshop 算子，<b>官方 Windows 构建没有把它们编进去</b>：本机 3.2.8 上
         <code>gegl --list-all</code> 查不到，PDB 里也没有 <code>plug-in-dilate</code>。</p>
      <p>仅剩的原生相关过程是 <code>gimp-selection-grow</code> / <code>-shrink</code>，
         但它们只作用于选区，改不了一张蒙版或一个图层的像素。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>四个参数</h3><span class="pill">对应 PS 的对话框</span></div>
      <ul class="deps">
        <li><b>模式</b> · 最大值（膨胀）/ 最小值（腐蚀）</li>
        <li><b>半径</b> · 1–100 像素，r=1 即 3×3，边缘向外长一圈</li>
        <li><b>形状</b> · 方形（方窗）/ 圆形（圆盘），对应 PS 的「方形度 / 圆度」</li>
        <li><b>影响 alpha</b> · 默认关，PS 同样不动图层透明度</li>
      </ul>
      <p>半径语义与 PS 一致：r 表示检查 <b>(±r, ±r)</b> 的邻域，不是窗口边长——所以 r=1 得到
         的正是 3×3。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>彩色图上会偏色，这是对的</h3></div>
      <p>PS 对 RGB 复合图是<b>逐通道</b>取极值的，红蓝交界处因此冒出紫边。插件照这个语义做，
         不对通道做任何均衡或换算。</p>
      <p>要没有偏色就把目标换成单色的：蒙版、通道、灰度层。蒙版只有一张平面，取极值就是
         纯粹的扩边 / 收边。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>逐位正确：在缓冲自己的精度里比较</h3><span class="pill">u8 / u16 / f32</span></div>
      <p>极值只需要大小关系，但结果值必须原样搬出来。所以三个精度各展开一份代码：
         u8 比 u8、u16 比 u16、float32 比 float32，<b>中途不做任何格式转换</b>。把 u16 读成
         float 再写回，个别像素就会差 1 码，这里不给它机会。</p>
      <p>不做色彩管理、不做 gamma 换算——PS 的这两个滤镜同样是直接对通道值取极值。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>边缘不会暗一圈</h3></div>
      <p>画布外按复制边缘像素处理。对取极值来说，这与「只算窗口内的像素」<b>逐位等价</b>：
         补进来的永远是边缘那一列 / 那一行的副本，不引入新值，也就不像模糊那样在边上留暗边。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>速度</h3></div>
      <p><b>方窗可分离</b>：先横向、再纵向，两遍都与半径无关——3MP 图上 r=1 和 r=100 都只要
         几十毫秒。<b>圆盘</b>每行半宽不同、不能分离，代价随半径线性增长（3MP、r=100 约 1.2 秒）。</p>
    </div>
  </div>
  <p class="note">图层上是<b>非破坏滤镜</b>：参数随时可改、眼睛图标随时可关。蒙版和通道没有
     滤镜栈（GIMP 3 实测：往蒙版 append 一条滤镜，API 不报错，但渲染不受影响），所以这两类
     目标是直接写像素，靠撤销退回。回归：<code>check_max_min.py</code> 27 项（对 O(r²) 暴力
     实现逐位比对，u8 / u16 / f32 × 方 / 圆 × 三档半径，含跨分带与超图半径）+
     <code>check_max_min_plugin.py</code> 12 项（PDB、滤镜挂载、蒙版写像素、错误分支）。</p>""",
    ),
]

PAGES.append(dict(
    key='layer-style',
    slug='layer-style',
    title='图层样式',
    tag=('图层', 't-blend'),
    count='十个效果',
    menu='SuperMrWang → Layer → 图层样式…',
    menus=['SuperMrWang → Layer → 图层样式…'],
    pdb='lb-plugin-layer-style(image, drawables, style)',
    lede="""PS 的「图层 → 图层样式」这一整套：投影、内阴影、外发光、内发光、
   斜面和浮雕、光泽、颜色/渐变/图案叠加、描边。勾一个效果、拖几根滑杆，画面立刻
   跟着动；确定之后不烤进像素，而是给出一组**还能单独选中、隐藏、调不透明度的图层**。""",
    body="""  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>十个效果，一个面板</h3><span class="pill">10 个</span></div>
      <p><b>投影 / 内阴影</b>：颜色、不透明度、角度（可跟随全局光）、距离、扩展/阻塞、
         大小、12 条预设等高线、杂色。<b>外发光 / 内发光</b>：单色或渐变、柔和/精确两种
         技法、扩展、大小、范围；内发光还能选「边缘 / 居中」两个源。</p>
      <p><b>斜面和浮雕</b>：外斜面 / 内斜面 / 浮雕 / 枕状浮雕 / 描边浮雕五种样式，
         平滑 / 雕刻清晰 / 雕刻柔和三种方法，深度、方向、大小、软化、高度，高光与阴影
         各自有颜色和混合模式。<b>光泽</b>：角度、距离、大小、反相。</p>
      <p><b>颜色 / 渐变 / 图案叠加</b>：26 种混合模式，渐变有线性 / 径向 / 角度 / 对称 /
         菱形五种、可反相、可对齐图层。<b>描边</b>：外 / 内 / 居中三档，宽度按精确距离
         算（不靠模糊），填充可选颜色、渐变或图案。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>结果是一组真图层</h3><span class="pill">非破坏</span></div>
      <p>应用后会多一个叫 <code>原图层名 (layer style)</code> 的组，原图层被收进组里
         居中：<b>投影和外发光在它下面</b>，<b>内阴影、内发光、描边、三种叠加、斜面
         在它上面</b>。这个顺序就是 PS 的那套，所以半透明的原图层会「透出」阴影、
         内阴影只会压在内缘 —— 不需要额外裁蒙版。</p>
      <p>改参数再跑一次，组里的旧效果层会被整体换掉（原图层原封不动），不会越叠越多。
         每个效果层都是普通 RGBA 图层，可以单独关掉、调不透明度、加自己的蒙版。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>复制样式：一份代码串</h3><span class="pill">复制粘贴</span></div>
      <p>PS 是「右键 → 拷贝图层样式」，粘到另一个图层上是「右键 → 粘贴图层样式」。
         GIMP 没有「样式挂在图层上」这个宿主概念，所以这里换成一串代码：对话框底部展开
         <b>Style code</b>，里面就是当前样式的 JSON（换行缩进，全是 ASCII）；点
         <b>Copy code</b> 带走，到另一个图层的同一个对话框里点 <b>Paste and load</b>，
         或者把代码贴进框里再点 <b>Load this code</b>。参数面板、勾选框、预览会一起
         跟着变，确定之后就是同一份样式。</p>
      <p>代码里就是全部参数，没有藏起来的状态：数字越界会夹到边界、0–255 写法的颜色
         自动除以 255、认不出来的效果忽略并提示 —— 所以从旧版本或别的机器上拿来的
         代码也读得进去。这串东西正好就是 PDB 的 <code>style</code> 参数，脚本能原样
         回放，不需要再维护第二套格式。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>样式跟着图层走</h3><span class="pill">存进 XCF</span></div>
      <p>应用之后，这份 JSON 会被写成图层和组的<b>寄生数据</b>（parasite），跟着 XCF
         一起保存、跟着撤销一起回退。于是再点同一个图层的「图层样式」，看到的是
         <b>上次那一套参数</b>，不是默认值 —— 少了这一步，复制出去的就永远是默认样式，
         功能等于没有。</p>
      <p>把一份样式铺到很多图层上：在源图层复制，再到每个目标图层粘一次。尺寸按文档
         像素算，粘到尺寸不同的图层上数值原样保留（PS 也是这样）。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>和 PS 差在哪</h3></div>
      <p><b>有：</b>十个效果、26 种混合模式、全局光角度、12 条等高线、扩展/阻塞、
         挖空（无 / 浅 / 深）、本图层的混合颜色带（含两端拆分）、实时预览。</p>
      <p><b>没有：</b>纹理（斜面的图案浮雕）、3D 材质、自定义等高线编辑器、
         <b>下一图层</b>的混合颜色带、图案叠加的角度旋转（PS 也没有）、
         「在图层上直接拖投影手柄」那套交互。</p>
      <p>另外这个版本里「样式」不是挂在图层上的对象，改参数要重跑一遍（PS 是点开
         样式面板随时改）。不过参数本身会记在图层上，重跑时看到的就是上次那一套，
         调好一处再复制给其它图层，实际用起来差别不大。要「参数随时能改、原像素
         一点不动」，用下一节那条实时滤镜。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么交给 GIMP 的是「普通」模式</h3></div>
      <p>GIMP 3 默认的混合模式在<b>线性光</b>里算：实测 50% 的 204 叠在 51 上是
         <b>153</b>，而 PS 在 sRGB 值上算，结果是 <b>128</b>。直接把效果层挂上
         MULTIPLY / SCREEN，边和中间调会整体偏亮，柔边还会发白。</p>
      <p>所以插件把混合<b>先算进颜色里</b>，图层一律挂 <code>NORMAL_LEGACY</code>
         （纯 sRGB 的 over）。和 GEGL 对拍：实心区<b>最大色差 0.6/255、平均
         0.12/255</b>，等于同一张图。代价是效果层的颜色里带着「下方是什么」的痕迹，
         拖动它会跟着错 —— 图层样式本来也不是让你挪的。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl">
      <div class="dl-head"><h3>实测</h3></div>
      <p>768×1024、六种效果一起开：<b>1.7 s</b>（含 14 次全图合成），预览
         560 长边一帧 <b>60–100 ms</b>，拖滑杆跟得上手。描边和斜面用的都是精确
         带符号距离（不是模糊逼近），所以同样的参数在软边和硬边上厚度一致。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>非交互也能跑</h3></div>
      <p>整份样式是一个 JSON 字符串参数 <code>style</code>，对话框点应用时写的就是
         它，脚本可以原样回放：<code>lb-plugin-layer-style 图层 style="{\\"effects\\":
         {\\"drop-shadow\\": {\\"enabled\\": true, …}}}"</code>。渐变和图案取 GIMP
         当前的渐变 / 图案。</p>
    </div>
  </div>

  <div class="dl-grid">
    <div class="dl primary-dl">
      <div class="dl-head"><h3>同一套样式的另一条路：实时滤镜</h3><span class="pill">非破坏</span></div>
      <p>这一页讲的是<b>破坏性</b>的做法：算完就变成图层，原像素被换掉了，参数只能
         记着、不能随时调。仓库里另有一个 GEGL 算子 <code>lb:layer-style</code>
         （菜单不同：<code>SuperMrWang → Layer → Layer Style (live)…</code>），
         同一个引擎挂成<b>图层滤镜</b>——拖滑杆实时重算、眼睛图标可关、参数随 XCF
         存盘、原像素一个字节都不动。</p>
      <p>两条路各自有用：要「随时改」或者「存进 XCF 回头再调」，用滤镜那条；要
         「拿到十个能单独加蒙版、改不透明度、随手涂改的效果图层」，用这一条。滤镜
         版拿不到 GIMP 的图案库（GEGL 进程看不到 GIMP 资源），图案只能用六种程序化
         图形；渐变也只能给两个颜色。</p>
    </div>
    <div class="dl">
      <div class="dl-head"><h3>为什么不是同一份代码</h3></div>
      <p>GIMP 3 的非破坏编辑<b>只认 GEGL 算子</b>：滤镜栈里存的是算子名 + 属性值，
         所以必须是 C 编译出来的模块。Python 插件只能读写像素，再多的图层组也只是
         一份烤好的结果。</p>
      <p>两份实现共用同一套公式（<code>plugin/_shared/layer_style.py</code> 是 C 版的
         对照实现），对拍过：实心区平均差 <b>0.45/255</b>、p99 <b>5.0</b>。</p>
    </div>
  </div>""",
))

BY_KEY = {p["key"]: p for p in PAGES}

# 英文正文单独一个模块（大段 HTML，混在这里不好读）
try:
    from plugin_docs_en import PLUGIN_EN as _PLUGIN_EN
except ImportError:  # 直接 import 的场合（tools 不在 sys.path）
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from plugin_docs_en import PLUGIN_EN as _PLUGIN_EN

# ---- 卡片与文章页共用的派生字段 ---------------------------------------------
# 卡片只放一句（plugins.html 就只剩十块方格），长的都在文章页里。

BRIEF = {
    "selection": "右键任意图层，把它转成当前选区：Gray / R / G / B / Alpha，"
                 "四种组合方式，可反相。",
    "channel": "右键任意图层，把它变成一条灰度 Alpha 通道，可反相、可自定义名。",
    "split": "右键任意图层，一次拆出 R / G / B / Alpha 四条通道，原图层自动隐藏作对照。",
    "hsv": "拆成 H / S / V 三张分量层，每层一条原生曲线，恒等还原。",
    "lch": "同上，换成 CIE LCh 明度 / 彩度 / 色相，感知均匀。",
    "hsl": "GIMP 没有 HSL 分量模式，这个插件精确换算，不拿 HSV 近似。",
    "lab": "a 与 b 合一层、L* 一层，调 a 只动 a、调 b 只动 b。",
    "hsi": "I 借不到任何分量模式，三个分量合进一层、三条曲线各管一个。",
    "frequency": "低频管影调、高频管细节，叠起来就是原图；半径决定分界。",
    "dodge": "提亮 / 压暗两条曲线压在黑蒙版下：涂到哪里动哪里。",
    "grey": "一层 50% 灰、柔光下恒等；白笔提亮、黑笔压暗、灰盖回去。",
    "observe": "六种观察层各一个菜单项：黑白、陡峭曲线、波浪曲线、饱和度、阈值、海报化。",
    "luminosity": "按亮度切七刀：亮部/暗部各 3 档 + 中间调，双击通道即变选区。",
    "ai-inpaint": "框一块地方、写一句提示词，交给本机 ComfyUI 重画，结果当新图层贴回原位。",
    "ai-frequency": "结构同高低频，两层的内容换成一张已经修过一遍的参考图。",
    "ai-dodge": "两条曲线的蒙版按参考图的差值预先涂好七成，打开就能继续补。",
    "ai-grey": "灰层不再是平的 128：按参考图反解出偏移，已做一轮中性灰。",
    "cutout": "两条路：AI（RMBG）连发丝一起抠，本地版从四边泛洪吃纯色背景。",
    "refine": "选区做完了边还是糊的：六根滑杆 + 实时预览，把边缘收干净。",
    "warp": "点几个钉子拖住画面走：钉子之间平滑过渡，圈外一个字节都不动。",
    "vanishing-point": "拖一个四边形标出透视平面：网格朝消失点收敛，能把图贴上去、也能拉正。",
    "mesh-warp": "盖一张贝塞尔网格：拖交点改形状，选中交点拖把手把网格线弯成曲线。",
    "alpha-curves": "把颜色通道写进 alpha，再接一条三个控制点的平滑曲线："
                    "挂上去先拉满，往下拖即成形状。",
    "color-range": "色彩范围的定制对话框：选什么颜色，下面就只显示那种颜色的参数，"
                   "高光 192 / 阴影 64 / 中间调 64–192 各自归位。",
    "channel-to-mask": "选中通道面板里的一条通道，右键图层就把它挂成图层蒙版："
                       "多选图层一次挂齐，可反相。",
    "max-min": "形态学的最大值（膨胀）与最小值（腐蚀）：扩边、收边、去亮点暗点，"
               "半径 1–100、方形或圆盘可选。",
    "layer-style": "十个 PS 图层样式效果，结果是一组可编辑图层：投影在外、内阴影在内。",
    "convert": "通道、选区、蒙版、路径四者两两互转，十二个方向各一个菜单项、点一下"
               "就完事，不弹参数框；另加一条路径 / 矢量图层转位图。",
}

TAG_EN = {"曲线": "Curves", "磨皮": "Retouching", "选区": "Selection",
          "通道": "Channels", "蒙版": "Mask", "转换": "Convert", "AI": "AI",
          "观察": "Inspect", "变形": "Distort", "图层": "Layer"}

TITLE_EN = {
    "ai-inpaint": "AI Inpaint",
    "frequency": "Frequency Separation",
    "ai-frequency": "Frequency Separation (AI prep)",
    "ai-dodge": "Dodge & Burn (AI prep)",
    "ai-grey": "Neutral Grey (AI prep)",
    "dodge": "Dodge & Burn",
    "grey": "Neutral Grey",
    "observe": "Inspection Layers",
    "cutout": "Cut Out / Remove Background",
    "refine": "Select and Mask",
    "warp": "Puppet Warp",
    "mesh-warp": "Free Transform (Mesh)",
    "vanishing-point": "Vanishing Point",
    "luminosity": "Luminosity Masks",
    "alpha-curves": "Alpha Curves",
    "color-range": "Color Range",
    "channel-to-mask": "Channel to Mask",
    "max-min": "Max / Min",
    "convert": "Convert",
    "layer-style": "Layer Style",
}

BRIEF_EN = {
    "selection": "Right-click any layer and turn it into the current selection: "
                 "Gray / R / G / B / Alpha, four combine modes, optional invert.",
    "channel": "Right-click any layer and turn it into a grayscale alpha channel — "
               "invertible, with a custom name.",
    "split": "Right-click any layer and get R / G / B / Alpha as four channels at "
             "once; the source layer hides itself for reference.",
    "hsv": "Splits into H / S / V component layers, one native curve each, restored "
           "bit-exactly.",
    "lch": "The same idea in CIE LCh: perceptual lightness, chroma and hue.",
    "hsl": "GIMP has no HSL component mode, so this converts exactly instead of "
           "approximating with HSV.",
    "lab": "a and b share one layer and L* gets its own — curve a and only a moves.",
    "hsi": "No component mode fits HSI, so all three share one layer with three "
           "curves.",
    "frequency": "Low frequency carries tone, high frequency carries detail; stacked "
                 "they rebuild the original.",
    "dodge": "Two curves, one lightening and one darkening, under a black mask — "
             "paint where you want them.",
    "grey": "A 50% grey layer is identity under soft light: white brush lightens, "
            "black darkens, grey paints it back.",
    "observe": "Six inspection layers, one menu item each: black & white, steep "
               "curves, wave curves, saturation, threshold, posterize.",
    "luminosity": "Seven channels cut by luminance: three lights, three darks and "
                  "midtones — double-click one to load it as a selection.",
    "cutout": "Two routes: AI (RMBG) keeps hair and fur, the local one "
              "flood-fills a plain background from the border.",
    "refine": "The selection is done but the edge is mush: six sliders and a "
              "live preview to clean it up.",
    "warp": "Drop a few pins and drag the picture with them: smooth in between, "
            "and byte-for-byte untouched outside the falloff.",
    "mesh-warp": "Lay a Bezier grid on the layer: drag the points to reshape it, "
                 "select a point and drag its handles to bend the grid lines.",
    "vanishing-point": "Mark a perspective plane on the picture: the grid "
                     "converges to the vanishing points, and you can paste "
                     "into it or rectify it flat.",
    "ai-inpaint": "Frame an area, write what should be there, and a local ComfyUI "
                  "redraws it — the answer comes back as a new masked layer.",
    "ai-frequency": "Same structure as Frequency Separation, but both layers carry a "
                     "reference that was already retouched once.",
    "ai-dodge": "Both curve masks come pre-painted to 70% of the measured difference, "
                "so the dodging is already started.",
    "ai-grey": "The grey layer is no longer flat 128: the offset is solved from the "
               "reference, so one neutral-grey pass is already done.",
    "alpha-curves": "Writes a colour channel into alpha, then a smooth three-point "
                    "curve — pull it up to fill, drag down to shape.",
    "color-range": "A custom Colour Range dialog: pick what to target and only that "
                   "target's parameters appear.",
    "channel-to-mask": "Pick a channel in the Channels dock, right-click a layer and "
                       "it becomes that layer's mask — several layers at once, "
                       "invertible.",
    "max-min": "Morphological maximum (dilate) and minimum (erode): grow or shrink a "
               "mask, kill specks, radius 1–100, square or disc.",
    "layer-style": "Ten Photoshop layer effects, delivered as a group of editable layers: shadows below, "
                   "inner effects above.",
    "convert": "Channels, selections, layer masks and paths, all twelve directions as one-click "
                "menu items with no dialog.",
}

AREA_EN = {"图层转换": "Convert", "Mask": "Mask", "Retouch 修饰": "Retouch",
           "Layer": "Layer",
           "AI": "AI"}

DEPS_NOTE_EN = {
    "ai-inpaint": "No operator modules and nothing to compile: the pixels are painted "
                  "by Stable Diffusion inside your own ComfyUI, and the plug-in only "
                  "crops, posts over HTTP and pastes back. It needs "
                  "<code>ai_client.py</code> and <code>prompt_tools.py</code> from "
                  "<code>plugin/_shared/</code> (inside the download) plus a running "
                  "ComfyUI — if there is none, the <b>AI Environment…</b> menu entry "
                  "installs and starts one, and the installer ships in the "
                  "<code>ai-setup/</code> folder of this zip.",
    "ai-frequency": "Only GIMP's own <code>gegl:gaussian-blur</code> and "
                    "<code>gegl:high-pass</code> — no extra operator modules. It does "
                    "need <code>retouch_prep.py</code>, <code>retouch_math.py</code> "
                    "and <code>ai_client.py</code> from <code>plugin/_shared/</code>, "
                    "and they are inside the download.",
    "ai-dodge": "Only GIMP's own <code>gimp:curves</code> — no extra operator modules. "
                "It does need <code>retouch_prep.py</code>, <code>retouch_math.py</code> "
                "and <code>ai_client.py</code> from <code>plugin/_shared/</code>, and "
                "they are inside the download.",
    "ai-grey": "No operator modules at all: it writes pixels into the buffer and uses "
               "GIMP's own soft-light mode. It does need <code>retouch_prep.py</code> "
               "and <code>retouch_math.py</code> from <code>plugin/_shared/</code>, "
               "already included.",
    "grey": "No dependency on this project's operators: it only writes pixels into "
            "the buffer and uses GIMP's own soft-light mode. Install the plug-in and "
            "it works.",
    "selection": "No dependency on this project's operators: it reads layer bytes "
                 "directly (a C-level array slice, about 4 ms for one megapixel) and "
                 "only calls GIMP's own selection PDB.",
    "channel": "No dependency on this project's operators: it reads layer bytes "
               "directly and only calls GIMP's own channel PDB.",
    "split": "No dependency on this project's operators: the layer is read "
             "once and sliced per component; only GIMP's own channel PDB is "
             "used.",
    "max-min": "Uses this project's own lb:max-min operator, because GIMP 3 no "
               "longer ships dilate / erode. The module is inside the plug-in "
               "zip — drop it into the GEGL module folder.",
}

AREA = {"selection": "图层转换", "channel": "图层转换", "split": "图层转换",
        "convert": "图层转换",
        "layer-style": "Layer",
        "ai-inpaint": "AI",
        "cutout": "Mask",
        "refine": "Mask",
        "warp": "Distort",
        "mesh-warp": "Distort",
        "vanishing-point": "Distort",
        "alpha-curves": "Mask", "color-range": "Mask",
        "channel-to-mask": "Mask", "max-min": "Mask"}

DEPS = {
    "ai-inpaint": [],
    "cutout": [],
    "refine": [],
    "warp": [],
    "mesh-warp": [],
    "vanishing-point": [],
    "hsv": ["lb:hsv-dual", "lb:hsv-compose", "gimp:curves"],
    "lch": ["lb:lch-dual", "lb:lch-compose", "gimp:curves"],
    "hsl": ["lb:hsl-dual", "lb:hsl-compose", "gimp:curves"],
    "lab": ["lb:lab-dual", "lb:lab-compose", "gimp:curves"],
    "hsi": ["lb:hsi-dual", "lb:hsi-compose"],
    "frequency": ["gegl:gaussian-blur", "gegl:high-pass"],
    "dodge": ["gimp:curves"],
    "grey": [],
    "observe": [],
    "luminosity": [],
    "ai-frequency": ["gegl:gaussian-blur", "gegl:high-pass"],
    "ai-dodge": ["gimp:curves"],
    "ai-grey": [],
    "alpha-curves": ["lb:channel-range-to-alpha", "gimp:curves"],
    "color-range": ["lb:color-mask-select"],
    "channel-to-mask": [],
    "max-min": ["lb:max-min"],
    "convert": [],
    "layer-style": [],
    "split": [],
}

DEPS_NOTE = {
    "ai-inpaint": "不依赖任何自研算子，也不用编译：像素由你自己那台 ComfyUI 里的 "
                  "Stable Diffusion 画，插件只负责裁图、发 HTTP、贴回。需要 "
                  "<code>plugin/_shared/</code> 里的 <code>ai_client.py</code> 与 "
                  "<code>prompt_tools.py</code>（下载包里带上了），以及一个在跑的 "
                  "ComfyUI——没有的话菜单里的 <b>AI 环境…</b> 可以一键装、一键起，"
                  "安装器就在这个包的 <code>ai-setup/</code> 目录里。",
    "grey": "不依赖任何自研算子：只往缓冲区里写像素，用 GIMP 自己的柔光混合模式。"
            "装了插件就能用。",
    "selection": "不依赖任何自研算子：直接读图层字节（array 的 C 级切片，"
                 "100 万像素约 4 毫秒），只调 GIMP 自己的选区 PDB。",
    "channel": "不依赖任何自研算子：直接读图层字节，只调 GIMP 自己的通道 PDB。",
    "split": "不依赖任何自研算子：读一次图层数据后按分量切片，只调 GIMP 自己的通道 PDB。",
    "channel-to-mask": "不依赖任何自研算子：只读通道像素、只调 GIMP 自己的蒙版 PDB。",
    "convert": "不依赖任何自研算子：十二个方向都只调 GIMP 自己的通道、选区、蒙版、路径 PDB（位图那条读的是图层自己的渲染）。",
    "ai-frequency": "只用 GIMP 自带的 <code>gegl:gaussian-blur</code> 与 "
                    "<code>gegl:high-pass</code>，不需要额外的算子模块。但要 "
                    "<code>plugin/_shared/</code> 里的 <code>retouch_prep.py</code>、"
                    "<code>retouch_math.py</code>、<code>ai_client.py</code>——"
                    "下载包里已经带上了。",
    "ai-dodge": "只用 GIMP 自带的 <code>gimp:curves</code>，不需要额外的算子模块。"
                "但要 <code>plugin/_shared/</code> 里的 <code>retouch_prep.py</code>、"
                "<code>retouch_math.py</code>、<code>ai_client.py</code>——"
                "下载包里已经带上了。",
    "ai-grey": "不依赖任何算子模块：只往缓冲区写像素，用 GIMP 自己的柔光模式。"
               "但要 <code>plugin/_shared/retouch_prep.py</code> 与 "
               "<code>retouch_math.py</code>——下载包里已经带上了。",
    "max-min": "用本项目自己的算子 lb:max-min（GIMP 3 已不带 dilate / erode）。"
               "插件包里已附带这个模块，按 readme 放进 GEGL 模块目录即可。",
}

for _p in PAGES:
    _p["brief"] = BRIEF[_p["key"]]
    _p["brief_en"] = BRIEF_EN.get(_p["key"], "")
    _en = _PLUGIN_EN.get(_p["key"], {})
    _p["lede_en"] = _en.get("lede", "")
    _p["body_en"] = _en.get("body", "")
    _p["tag_en"] = TAG_EN.get(_p["tag"][0], _p["tag"][0])
    _p["title_en"] = TITLE_EN.get(_p["key"], _p["title"])
    _p["area_en"] = AREA_EN.get(AREA.get(_p["key"], "Retouch 修饰"), "Retouch")
    _p["area"] = AREA.get(_p["key"], "Retouch 修饰")
    _p["deps"] = DEPS.get(_p["key"], [])
    if "menus" not in _p:
        _name = _p["menu"].split("→")[-1].strip()
        _p["menus"] = ["SuperMrWang → Retouch → " + _name,
                       "图层右键 → SuperMrWang → Retouch → " + _name]
    _p["deps_note_en"] = DEPS_NOTE_EN.get(
        _p["key"], "The operators below do the work. <b>They are already inside this "
                   "plug-in's download</b> (<code>modules-windows-x64</code> / "
                   "<code>modules-linux-x64</code>) — nothing else to fetch:")
    _p["deps_note"] = DEPS_NOTE.get(
        _p["key"], "靠下面这些算子干活。<b>它们已经打进这个插件的下载包</b>"
                   "（<code>modules-windows-x64</code> / ""<code>modules-linux-x64</code>），不用另外去下：")
del _p
