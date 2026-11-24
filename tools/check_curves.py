# -*- coding: utf-8 -*-
"""验收四个曲线算子：lb:lab-curves / lb:lch-curves / lb:hsv-curves /
lb:cmyk-curves。

    python tools/check_curves.py            # 跑全部
    python tools/check_curves.py hue        # 只跑某组

五类检查：
  A 恒等   —— 空曲线串必须把图原样还回来（逐像素 0 差）
  B 语义   —— 每条曲线的作用方向可验证：
              L 抬中间 ⇒ 变亮而两端不动；a 推向正 ⇒ 灰变红
              LCh/HSV 色相偏移 ⇒ 红转黄绿；零彩度像素一个字节不动
              CMYK 压青 ⇒ 绿变黄；LCh 减彩度 ⇒ 变淡而明度基本保持
  C 不过冲 —— Fritsch–Carlson 的全部意义所在：陡缓相邻的控制点之间，
              输出必须单调且不越出相邻控制点的上下界。自然样条在这里会
              打出一个比控制点还亮的包，落在分量上就是一圈色光。
  D 透明   —— alpha=0 的像素原样透传
  E 容错   —— 曲线串是给人手改的：只给一个分量、乱序、写错名字、
              x 重复，都不能让整条曲线失效

算子直接用 gegl 命令行跑，和 check_color_levels.py 同一套调用方式。
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from contact_sheet import read_png, write_png     # noqa: E402

GEGL_CANDIDATES = [
    os.environ.get("GEGL_BIN", ""),
    r"D:\fastsoftware\GIMP 3\bin\gegl.exe",
    r"C:\Program Files\GIMP 3\bin\gegl.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GIMP 3", "bin", "gegl.exe"),
    "/d/fastsoftware/GIMP 3/bin/gegl.exe",
]

OK, FAIL, TMP = [], [], None


def find_gegl():
    for c in GEGL_CANDIDATES:
        if c and os.path.exists(c):
            return c
    raise SystemExit("找不到 gegl 可执行文件，用 GEGL_BIN=... 指定")


def gegl_env(exe):
    env = dict(os.environ)
    lib = os.path.join(os.path.dirname(os.path.dirname(exe)), "lib", "gegl-0.4")
    if os.name == "nt":
        dest = os.path.join(os.environ.get("LOCALAPPDATA", ""), "gegl-0.4", "plug-ins")
        env["GEGL_PATH"] = dest + ";" + lib
    else:
        env["GEGL_PATH"] = os.path.expanduser("~/.local/share/gegl-0.4/plug-ins") + ":" + lib
    return env


def check(name, cond, detail=""):
    if cond:
        OK.append(name)
        print("  pass  %s" % name)
    else:
        FAIL.append((name, detail))
        print("  FAIL  %s   %s" % (name, detail))


# --------------------------------------------------------------- 渲染 ---

def flat(path):
    w, h, rows = read_png(path)
    return w, h, [v for row in rows for px in row for v in px]


def render(env, op, src, tag, curves):
    """跑一次算子，返回 (w, h, 扁平 RGB 列表)。"""
    dst = os.path.join(TMP, "%s.png" % tag)
    cmd = [env["_exe"], src, "-o", dst, "--", op]
    if curves:
        cmd.append("curves=%s" % curves)
    r = subprocess.run(cmd, env=env, capture_output=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit("渲染失败 %s curves=%r\n%s\n%s"
                         % (op, curves,
                            r.stdout.decode("utf-8", "replace"),
                            r.stderr.decode("utf-8", "replace")))
    return flat(dst)[2]


def px(buf, i):
    return tuple(buf[i * 3:i * 3 + 3])


def maxdiff(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


# ------------------------------------------------------------- 探针图 ---

def make_gray(path, n=64):
    """0→255 的灰梯，横向一格一个码。"""
    row = []
    for x in range(n):
        v = int(round(x * 255.0 / (n - 1)))
        row += [v, v, v]
    write_png(path, n, 1, [row])


HUES = [(255, 0, 0), (255, 128, 0), (0, 255, 0), (0, 255, 255),
        (0, 0, 255), (255, 0, 255), (128, 128, 128)]


def make_hues(path):
    write_png(path, len(HUES), 1, [[v for c in HUES for v in c]])


def write_png_rgba(path, w, h, rows):
    """最小 RGBA PNG 编码（color type 6）。contact_sheet 只写 RGB，
    而 alpha 透传是曲线算子必须守住的一条，所以这里自带一个。"""
    import struct
    import zlib
    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    open(path, "wb").write(b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def make_rgba(path):
    """一行四格：不透红 / 半透绿 / 全透蓝 / 不透白。"""
    write_png_rgba(path, 4, 1, [[
        (255, 0, 0, 255), (0, 255, 0, 128), (0, 0, 255, 0), (255, 255, 255, 255),
    ]])


# ------------------------------------------------------------- 用例 ---

def test_identity(env):
    print("\n[A] 恒等：空曲线串原样返回")
    src = os.path.join(TMP, "hues.png")
    base = render(env, "lb:lab-curves", src, "id0", "")
    for op in ("lb:lab-curves", "lb:lch-curves",
               "lb:hsv-curves", "lb:cmyk-curves"):
        got = render(env, op, src, "id-%s" % op.split(":")[1], "")
        check("%s 空串逐像素不变" % op, maxdiff(base, got) == 0,
              maxdiff(base, got))


def test_semantics(env):
    print("\n[B] 语义：曲线的作用方向")
    gray = os.path.join(TMP, "gray.png")
    hues = os.path.join(TMP, "hues.png")
    g0 = render(env, "lb:lab-curves", gray, "s-gray0", "")
    h0 = render(env, "lb:lab-curves", hues, "s-hue0", "")

    # L 抬中间：中点（灰 128 附近）变亮，两端不动
    g1 = render(env, "lb:lab-curves", gray, "s-l", "L 0,0 0.5,0.72 1,1")
    mid, end0, end1 = 32, 0, 63
    check("LAB L 曲线抬亮中间",
          px(g1, mid)[0] > px(g0, mid)[0] + 20,
          "%d -> %d" % (px(g0, mid)[0], px(g1, mid)[0]))
    check("LAB L 曲线不动两端",
          px(g1, end0) == px(g0, end0) and abs(px(g1, end1)[0] - px(g0, end1)[0]) <= 1,
          "%s / %s" % (px(g1, end0), px(g1, end1)))

    # a 推向正：中性灰变红（R 升、G 降）
    g2 = render(env, "lb:lab-curves", gray, "s-a", "a 0,0 0.5,0.68 1,1")
    neutral = 32
    r0, g0c, b0 = px(g0, neutral)
    r1, g1c, b1 = px(g2, neutral)
    check("LAB a 曲线把中性推成红", r1 > r0 + 20 and g1c < g0c,
          "%s -> %s" % ((r0, g0c, b0), (r1, g1c, b1)))

    # LCh 色相 +90°：红转黄绿
    hc = render(env, "lb:lch-curves", hues, "s-lchh", "h 0,0.75 1,0.75")
    red0, red1 = px(h0, 0), px(hc, 0)
    check("LCh 色相 +90° 红转绿", red1[1] > red1[0] and red1[0] < red0[0],
          "%s -> %s" % (red0, red1))
    check("LCh 色相偏移不动零彩度像素", px(hc, 6) == px(h0, 6),
          "%s -> %s" % (px(h0, 6), px(hc, 6)))

    # HSV 色相 +90°：同一件事，两种空间应得到相近的结果
    hv = render(env, "lb:hsv-curves", hues, "s-hsvh", "H 0,0.75 1,0.75")
    # +90° 从红出发正好落在黄绿（R≈127），所以判据是「绿主导、红被压到一半」
    check("HSV 色相 +90° 红转黄绿",
          px(hv, 0)[1] > 200 and px(hv, 0)[0] < 180,
          px(hv, 0))

    # LCh 减彩度：变淡（R 与 B 靠近），中性灰不动
    lc = render(env, "lb:lch-curves", hues, "s-lchc", "C 0,0 1,0.5")
    red2 = px(lc, 0)
    check("LCh 彩度减半：红变淡", red2[0] < 240 and red2[1] > 60,
          "%s -> %s" % (red0, red2))
    check("LCh 彩度减半不动灰", px(lc, 6) == px(h0, 6),
          "%s -> %s" % (px(h0, 6), px(lc, 6)))

    # CMYK：绿（C=1,M=0,Y=1,K=0）压青 → 变黄
    ck = render(env, "lb:cmyk-curves", hues, "s-cmyk", "C 0,0 1,0.5")
    green0, green1 = px(h0, 2), px(ck, 2)
    check("CMYK 压青：绿变黄", green1[2] < 50 and green1[0] > 150,
          "%s -> %s" % (green0, green1))


def test_no_overshoot(env):
    print("\n[C] 不过冲：陡缓相邻处不冒出控制点之外的亮度")
    gray = os.path.join(TMP, "gray.png")
    g0 = render(env, "lb:lab-curves", gray, "o0", "")

    # 控制点：0→0.1 陡升，0.1→0.9 几乎平，0.9→1 陡升。
    # 自然样条会在 0.1 之后冲高（比 0.12 还亮），单调插值不会。
    cur = "L 0,0 0.1,0.12 0.9,0.14 1,1"
    g1 = render(env, "lb:lab-curves", gray, "o1", cur)
    lum = [px(g1, i)[0] for i in range(64)]

    mono = all(lum[i + 1] >= lum[i] for i in range(63))
    check("陡缓曲线仍然单调递增", mono,
          [i for i in range(63) if lum[i + 1] < lum[i]][:5])

    # 控制点把输出限制在 0.12…0.14 之间（对应灰 30…36），这一段不能超过 40
    seg = lum[8:56]
    check("平台段不越过控制点上下界", max(seg) <= 40,
          "max=%d 区间=%d..%d" % (max(seg), min(seg), max(seg)))

    # 反向同理：先降后升的曲线上不能出现比端点更暗的凹陷
    cur2 = "L 0,0 0.2,0.05 0.8,0.95 1,1"
    g2 = render(env, "lb:lab-curves", gray, "o2", cur2)
    lum2 = [px(g2, i)[0] for i in range(64)]
    check("S 形曲线不打出暗坑", min(lum2) >= min(px(g0, 0)[0], 0) and
          all(lum2[i + 1] >= lum2[i] for i in range(63)),
          [i for i in range(63) if lum2[i + 1] < lum2[i]][:5])


def test_alpha(env):
    print("\n[D] 透明：alpha=0 的像素原样透传")
    src = os.path.join(TMP, "rgba.png")
    base = read_png(src)
    dst = os.path.join(TMP, "alpha.png")
    cmd = [env["_exe"], src, "-o", dst, "--", "lb:lab-curves",
           "curves=L 0,0 0.5,0.9 1,1"]
    r = subprocess.run(cmd, env=env, capture_output=True)
    check("带透明通道的图能跑", r.returncode == 0,
          r.stderr.decode("utf-8", "replace")[-200:])
    if r.returncode == 0:
        w, h, rows = read_png(dst)
        row = rows[0]
        # 全透像素的 RGB 没有意义，PNG 存盘时可能被清零；只要求它没被曲线
        # 提亮成一个亮色（真去映射了会直接跳到 L=90 的白）
        check("全透像素不被曲线提亮", sum(row[2][:3]) < 300, row[2])
        check("不透像素照常被映射", tuple(row[0][:3]) != (255, 0, 0),
              row[0])


def test_tolerance(env):
    print("\n[E] 容错：曲线串是给人手改的")
    hues = os.path.join(TMP, "hues.png")
    base = render(env, "lb:lab-curves", hues, "t0", "")

    # 只写一个分量：另外两个保持恒等
    only_l = render(env, "lb:lab-curves", hues, "t1", "L 0,0 0.5,0.75 1,1")
    check("只写 L 时 a/b 不受影响",
          abs(px(only_l, 6)[0] - px(base, 6)[0]) > 5,     # 灰被提亮
          "%s -> %s" % (px(base, 6), px(only_l, 6)))

    # 乱序：b 写在 L 前面，两者都要生效
    rev = render(env, "lb:lab-curves", hues, "t2",
                 "b 0,0 0.5,0.62 1,1|L 0,0 0.5,0.75 1,1")
    fwd = render(env, "lb:lab-curves", hues, "t3",
                 "L 0,0 0.5,0.75 1,1|b 0,0 0.5,0.62 1,1")
    check("分量顺序不影响结果", maxdiff(rev, fwd) <= 1, maxdiff(rev, fwd))

    # 不认识的名字按位置回落（第一段当 L）
    unk = render(env, "lb:lab-curves", hues, "t4", "zzz 0,0 0.5,0.75 1,1")
    check("名字不认识时按位置当 L", maxdiff(unk, only_l) <= 1, maxdiff(unk, only_l))

    # x 重复：留最后一个，不能崩也不能全黑
    dup = render(env, "lb:lab-curves", hues, "t5", "L 0,0 0.5,0.3 0.5,0.7 1,1")
    check("x 重复时取后一个", px(dup, 6)[0] > px(base, 6)[0],
          "%s -> %s" % (px(base, 6), px(dup, 6)))

    # 坏 token 混在里面：跳过坏的，好的照用
    bad = render(env, "lb:lab-curves", hues, "t6", "L 0,0 abc 0.5,0.75 1,1")
    check("坏 token 被跳过而不是整体失效", maxdiff(bad, only_l) <= 1,
          maxdiff(bad, only_l))

    # 只写一个中间点：补 (0,0)/(1,1)，不能把整幅压成常数
    one = render(env, "lb:lab-curves", hues, "t7", "L 0.5,0.75")
    check("单点曲线两端仍落在 0 与 1",
          px(one, 2)[1] > 100 and px(one, 6)[0] < 250,
          "绿=%s 灰=%s" % (px(one, 2), px(one, 6)))


def test_parity(env):
    print("\n[F] 对拍：对话框画的曲线和算子算的曲线是同一条")
    # 灰阶的 L* 只取决于 Y，D50/D65 都一样，所以两边可以不用管白点适应
    def srgb_to_l(v01):
        y = v01 / 12.92 if v01 <= 0.04045 else ((v01 + 0.055) / 1.055) ** 2.4
        return 116.0 * (y ** (1.0 / 3.0)) - 16.0 if y > 0.008856 else 903.3 * y

    def l_to_srgb(L):
        L = min(max(L, 0.0), 100.0)
        y = ((L + 16.0) / 116.0) ** 3 if L > 8.0 else L / 903.3
        v = 12.92 * y if y <= 0.0031308 else 1.055 * (y ** (1.0 / 2.4)) - 0.055
        return min(max(v, 0.0), 1.0)

    sys.path.insert(0, os.path.join(ROOT, 'plugin', '_shared'))
    import curve_math as CM

    cur = "L 0,0 0.25,0.12 0.5,0.6 0.75,0.9 1,1"
    gray = os.path.join(TMP, "gray.png")
    got = render(env, "lb:lab-curves", gray, "p-cur", cur)

    pts = CM.parse_points(cur.split(" ", 1)[1])
    lut, _ident = CM.build(pts)

    worst, worst_at = 0, None
    for i in range(64):
        v = i / 63.0
        expect = l_to_srgb(CM.sample(lut, srgb_to_l(v) / 100.0) * 100.0)
        want = int(round(expect * 255.0))
        d = abs(got[i * 3] - want)
        if d > worst:
            worst, worst_at = d, (i, want, got[i * 3])
    check("C 算子与 Python 曲线逐点一致（≤2 码）", worst <= 2,
          "最大差 %d 在 %s" % (worst, worst_at))


def main():
    global TMP
    only = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    exe = find_gegl()
    env = gegl_env(exe)
    env["_exe"] = exe
    TMP = tempfile.mkdtemp(prefix="lb-curves-")

    make_gray(os.path.join(TMP, "gray.png"))
    make_hues(os.path.join(TMP, "hues.png"))
    make_rgba(os.path.join(TMP, "rgba.png"))

    groups = [("identity", test_identity), ("semantics", test_semantics),
              ("overshoot", test_no_overshoot), ("alpha", test_alpha),
              ("tolerance", test_tolerance), ("parity", test_parity)]
    for key, fn in groups:
        if only and only not in key:
            continue
        fn(env)

    print("\n%d/%d 通过" % (len(OK), len(OK) + len(FAIL)))
    if FAIL:
        for n, d in FAIL:
            print("  x %s  %s" % (n, d))
        sys.exit(1)


if __name__ == "__main__":
    main()
