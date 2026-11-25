"""截 4K 视频用的高清页面图（2x DPR，1440 逻辑宽 → 2880 物理像素）。

落 tools/video/shots/<slug>.png。站点是浅色主题，画布也走浅色。
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(ROOT, "tools", "video", "shots")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# (slug, 相对 docs 的页面, 逻辑视口高)
PAGES = [
    ("home", "index.html", 900),
    ("overview", "overview.html", 1000),
    ("ops", "ops.html", 1400),
    ("plugins", "plugins.html", 1400),
    ("guide", "guide.html", 1000),
    # 算子详情页
    ("op-levels", "ops/levels.html", 1400),
    ("op-lab-curves", "ops/lab-curves.html", 1400),
    ("op-hue-saturation", "ops/hue-saturation.html", 1400),
    ("op-channel-range", "ops/channel-range-to-alpha.html", 1400),
    ("op-unsharp", "ops/unsharp-mask.html", 1400),
    ("op-dual", "ops/hsi-dual.html", 1400),
    ("op-layer-style", "ops/layer-style.html", 1400),
    ("op-puppet-warp", "ops/puppet-warp.html", 1500),
    ("op-mesh-warp", "ops/mesh-warp.html", 1500),
    ("op-exposure", "ops/exposure.html", 1400),
    # 插件页
    ("plug-curves", "plugins/curves.html", 1400),
    ("plug-split", "plugins/lab-split-curves.html", 1300),
    ("plug-cutout", "plugins/cutout.html", 1300),
    ("plug-refine", "plugins/refine.html", 1400),
    ("plug-warp", "plugins/warp.html", 1400),
    ("plug-mesh", "plugins/mesh-warp.html", 1400),
    ("plug-vanishing", "plugins/vanishing-point.html", 1400),
    ("plug-freq", "plugins/frequency-separation.html", 1300),
    ("plug-dodge", "plugins/dodge-burn.html", 1300),
    ("plug-ai-inpaint", "plugins/ai-inpaint.html", 1300),
    ("plug-ai-upscale", "plugins/ai-upscale.html", 1300),
    ("plug-selection", "plugins/layer-to-selection.html", 1300),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    for slug, rel, h in PAGES:
        src = os.path.join(DOCS, rel)
        if not os.path.exists(src):
            print("MISS", rel)
            continue
        dst = os.path.join(OUT, slug + ".png")
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
               "--force-device-scale-factor=2",
               "--window-size=1440,%d" % h,
               "--screenshot=" + dst,
               "file:///" + src.replace("\\", "/")]
        r = subprocess.run(cmd, capture_output=True)
        ok = os.path.exists(dst)
        print(("OK   " if ok else "FAIL ") + slug,
              (str(os.path.getsize(dst)) + "B") if ok else r.returncode)


if __name__ == "__main__":
    main()
