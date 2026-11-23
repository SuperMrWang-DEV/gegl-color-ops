# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 3D 场景（反解相机 / 台阶折面）
 ---------------------------------------------------------------------------
 purpose   给「消失点」加一层真正的三维：一块平面本身就足以定出整台相机。

           平面四角 ↔ 世界 (0,0)/(1,0)/(1,1)/(0,1)，于是有单应 H。把
           「三个互垂方向的消失点、主点是垂心」再往前推一步：主点 (cx,cy)
           在画面中心、像素是方的，那焦距就唯一确定了——

               f² = −(Vu−O)·(Vv−O)

           两条消失点射线正交，这个式子就是它的投影表达式。有了 f，
           K⁻¹ 就能把消失点变回三维方向，相机的旋转 R 就有了；
           平移 t 由 K⁻¹H 的第三列给出。至此可以投影**任意**三维点。

           有了相机，「楼梯」就不再是拼四边形：台阶是在平面自己的坐标
           (s,t,z) 里算出来的——踏面 z 每级抬 rise、踢面立在台阶前缘——
           再逐点投影成图像里的四边形。

 note      两个必须记住的：
           0. **没有透视的四边形（直接拖出来的矩形）只能近似。** 两组边
              平行时焦距无从确定，只好按「正对着的方板」算：这时正中间的
              踢面正好侧对相机、退化成一条线，会被丢掉。要真台阶，把
              四边形拖成近大远小的梯形。
           1. **z 的正负号是约定，不是算出来的。** 消失点只定方向、不定朝向，
              +z 到底朝相机还是背相机，得看相机眼睛的 z 坐标。默认取
              「朝相机」那一侧：地板上就是向上，墙面上就是朝屋里凸。
           2. **世界坐标的长度单位来自四边形自己的边长。** 单应只定得出
              两条边的长度比，定不出绝对尺寸；`|K⁻¹·h|` 正好就是边长
              （h 是单应的列），所以 z 用两条边长的几何平均当单位——
              听起来绕，其实就是「一格高 = 一条边的长度」。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import math

import perspective as P

# f² 小于这个值说明两个消失点几乎正交在原点附近，解不出真实焦距
MIN_F2 = 1e-6
# 台阶最多几级（再多投影出来也就一两像素一级，没意义）
MAX_STEPS = 24


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    ln = math.sqrt(_dot(a, a))
    if ln < 1e-12:
        return None, 0.0
    return (a[0] / ln, a[1] / ln, a[2] / ln), ln


class Camera(object):
    """由一块平面反解出来的针孔相机。

    世界坐标就是平面自己的坐标：s、t ∈ [0,1] 落在平面内，z 垂直于平面，
    单位与平方面积的几何平均边长一致。project() 把它投到图像像素。
    """

    __slots__ = ("f", "cx", "cy", "b1", "b2", "b3", "nz", "eye", "aspect",
                 "approx")

    def __init__(self, f, cx, cy, b1, b2, b3, nz, eye, aspect, approx=False):
        self.f = f
        self.cx = cx
        self.cy = cy
        self.b1 = b1            # 平面 u 方向：K 乘上 (单位向量 × 边长)
        self.b2 = b2
        self.b3 = b3            # 原点（corners[0]）在相机坐标里的位置
        self.nz = nz            # 法向：单位向量 × 几何平均边长
        self.eye = eye          # 相机在平面世界里的位置
        self.aspect = aspect    # 两条边的长度比（≠1 说明标注的不是正方形）
        self.approx = approx    # True = 焦距是假设的（四边形没有透视）

    # -- 投影 --------------------------------------------------------------
    def _cam(self, s, t, z):
        b1, b2, b3, nz = self.b1, self.b2, self.b3, self.nz
        return (b1[0] * s + b2[0] * t + b3[0] + nz[0] * z,
                b1[1] * s + b2[1] * t + b3[1] + nz[1] * z,
                b1[2] * s + b2[2] * t + b3[2] + nz[2] * z)

    def depth(self, s, t, z):
        return self._cam(s, t, z)[2]

    def project(self, s, t, z=0.0):
        """世界 (s,t,z) → 图像 (x,y)。跑到相机后面就返回 None。"""
        X, Y, W = self._cam(s, t, z)
        if W <= P.W_EPS:
            return None
        x = self.f * X / W + self.cx
        y = self.f * Y / W + self.cy
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        if abs(x) > P.CLAMP or abs(y) > P.CLAMP:
            return None
        return x, y

    def toward(self):
        """+z 是不是朝相机那一侧。True = +z 朝相机。"""
        return self.eye[2] > 0.0

    def up(self):
        """「朝相机」那一侧的符号：地板向上、墙面朝屋里凸都靠它。"""
        return 1.0 if self.toward() else -1.0


def camera_from_plane(plane, w, h):
    """由平面四角反解针孔相机。解不出来（退化四边形）返回 None。

    有边严格平行（比如直接拖一个矩形）时两组边都没有交点，焦距就无从确定
    —— 这时退回「正视近似」：焦距取 1.5×长边，相当于用长焦拍一块正对着
    的方板。几何上不再是这台相机的真实解，但台阶能正常出，不会卡死。
    """
    if plane is None or not plane.is_valid():
        return None
    Vu, Vv = plane.vanish_uv()
    cx, cy = w * 0.5, h * 0.5
    f = None
    if Vu is not None and Vv is not None:
        du = (Vu[0] - cx, Vu[1] - cy)
        dv = (Vv[0] - cx, Vv[1] - cy)
        if math.hypot(*du) > 1e-6 and math.hypot(*dv) > 1e-6:
            # 两条消失点射线正交 → f² = −(Vu−O)·(Vv−O)
            f2 = -(du[0] * dv[0] + du[1] * dv[1])
            if f2 > MIN_F2:
                f = math.sqrt(f2)
    approx = f is None
    if approx:
        f = 1.5 * max(float(w), float(h), 4.0)

    # b = K⁻¹ H，H 的三列分别对应 u 方向、v 方向、原点
    H = plane.H()
    h = [H[0], H[1], H[2], H[3], H[4], H[5], H[6], H[7], 1.0]
    # K⁻¹ = [[1/f, 0, −cx/f], [0, 1/f, −cy/f], [0, 0, 1]]
    b1 = ((h[0] - cx * h[6]) / f, (h[3] - cy * h[6]) / f, h[6])
    b2 = ((h[1] - cx * h[7]) / f, (h[4] - cy * h[7]) / f, h[7])
    b3 = ((h[2] - cx) / f, (h[5] - cy) / f, 1.0)
    r1, l1 = _norm(b1)
    r2, l2 = _norm(b2)
    if r1 is None or r2 is None or l1 < 1e-9 or l2 < 1e-9:
        return None
    n = _cross(r1, r2)
    n, _ln = _norm(n)
    if n is None:
        return None
    # b = K⁻¹·p = 边长 × 方向，所以 |b1|、|b2| 就是这块四边形在三维里的
    # 两条边长。z 用两者的几何平均当单位（单应定不出绝对尺寸）。
    scale = math.sqrt(l1 * l2)
    nz = (n[0] * scale, n[1] * scale, n[2] * scale)
    # 相机位置：C = −Rᵀ t，R = [r1 r2 n]（只看 z 的符号，不必除以边长）
    t3 = b3
    eye = (-(_dot(r1, t3)),
           -(_dot(r2, t3)),
           -(_dot(n, t3)))
    return Camera(f, cx, cy, b1, b2, b3, nz, eye, l1 / l2, approx)


# ---- 面片 ------------------------------------------------------------------

class Face(object):
    """一块三维面片投影到图像上的四边形，外加它在展开图里的 uv 矩形。

    uv 是**全局**坐标：u ∈ [0,1] 横跨整块平面，v 沿台阶展开的长度
    （0 是世界里的起点，总共 total_v）。贴图时 u→源的 x、v→源的 y，
    所以整张图会沿台阶连续地「铺」过去，而不是每级各贴一份。
    """

    __slots__ = ("quad", "u0", "v0", "u1", "v1", "kind")

    def __init__(self, quad, u0, v0, u1, v1, kind="tread"):
        self.quad = quad
        self.u0 = u0
        self.v0 = v0
        self.u1 = u1
        self.v1 = v1
        self.kind = kind

    def bbox(self, w, h):
        return P._bbox(self.quad, w, h)

    def is_valid(self):
        return (P.quad_area(self.quad) >= 1.0
                and P.is_convex(self.quad))


def _edge_uv(edge, a, b):
    """台阶局部坐标 (a 沿踏步方向, b 横向) → 平面的世界 (s,t)。

    edge 是台阶「从哪条边开始」：0 下边（+t）、1 右边（−s）、
    2 上边（−t）、3 左边（+s）。四种情况都是同一个旋转，保持手性。
    """
    edge = int(edge) % 4
    if edge == 0:
        return b, a
    if edge == 1:
        return 1.0 - a, b
    if edge == 2:
        return 1.0 - b, 1.0 - a
    return a, 1.0 - b


def stair_faces(plane, w, h, steps=6, rise=0.12, run=0.0, edge=0, flip=False):
    """把一块平面变成楼梯，返回 (faces, info)。

    台阶沿 edge 指向对面生长：每级先铺一块踏面（z 抬高一级），再立一块
    踢面。run 是踏面深（世界单位，0 = 自动 = 1/steps 铺满），rise 是踢面高。

    返回的 faces 是 (踏面, 踢面, 踏面, …) 交替的列表，v 沿台阶累加，
    所以整张图能沿台阶连续铺上去。info 里有相机、总高、总展开长和
    失败原因（cam 为 None 时 faces 为空）。
    """
    info = {"cam": None, "faces": 0, "height": 0.0, "total_v": 0.0,
            "steps": 0, "run": 0.0, "reason": ""}
    cam = camera_from_plane(plane, w, h)
    if cam is None:
        info["reason"] = "no-camera"
        return [], info

    steps = max(1, min(MAX_STEPS, int(steps)))
    run = float(run) if run and run > 0 else 1.0 / steps
    run = max(0.02, min(1.0, run))
    n = int(math.floor(1.0 / run + 1e-9))
    n = max(1, min(steps, n))
    rise = float(rise)
    sign = cam.up() * (-1.0 if flip else 1.0)

    def pt(a, b, z):
        s, t = _edge_uv(edge, a, b)
        return cam.project(s, t, z)

    faces = []
    dropped = 0
    v = 0.0
    for k in range(n):
        z0 = sign * k * rise
        z1 = sign * (k + 1) * rise
        a0 = k * run
        a1 = (k + 1) * run
        # 踏面：uv 的 u 沿台阶「宽」（b），v 沿台阶「走」（a）——和踢面一致。
        # 顺序反了不会报错，只会把整张图转 90° 铺上去。
        q = (pt(a0, 0.0, z0), pt(a0, 1.0, z0),
             pt(a1, 1.0, z0), pt(a1, 0.0, z0))
        if any(p is None for p in q):
            info["reason"] = "behind-camera"
            return [], info
        if P.quad_area(q) >= 1.0 and P.is_convex(q):
            faces.append(Face(q, 0.0, v, 1.0, v + run, "tread"))
        else:
            dropped += 1
        v += run
        q = (pt(a1, 0.0, z0), pt(a1, 1.0, z0),
             pt(a1, 1.0, z1), pt(a1, 0.0, z1))
        if any(p is None for p in q):
            info["reason"] = "behind-camera"
            return [], info
        # 正视近似（四边形没有透视）时，正中间的踢面会正好侧对着相机、
        # 退化成一条线——这种面片直接丢掉，画出来也是一条白缝。
        if P.quad_area(q) >= 1.0 and P.is_convex(q):
            faces.append(Face(q, 0.0, v, 1.0, v + rise, "riser"))
        else:
            dropped += 1
        v += rise

    info.update({"cam": cam, "faces": len(faces), "height": n * abs(rise),
                 "total_v": v, "steps": n, "run": run, "rise": rise,
                 "dropped": dropped})
    return faces, info


def face_bboxs(faces, w, h):
    return [f.bbox(w, h) for f in faces]


def paste_faces(dst, w, h, src, sw, sh, faces, total_v, mix=True,
                progress=None):
    """把 src 沿展开图铺到一串面片上（踏面/踢面连续，不重复）。

    每个面片自己的四边形用单应做透视，源坐标由 uv 线性映射：
        sx = u · sw          sy = v / total_v · sh
    所以整张图只有一份，沿台阶折过去——像把一张海报裹在台阶上。
    """
    if not faces:
        raise ValueError(_no_faces_msg())
    if total_v <= 1e-9:
        raise ValueError(_no_faces_msg())
    ky = float(sh) / total_v
    maps = []
    for f in faces:
        if P.quad_area(f.quad) < 1.0 or not P.is_convex(f.quad):
            continue                    # 退化面片（侧对相机）没有面积
        H = P.homography(((f.u0, f.v0), (f.u1, f.v0),
                          (f.u1, f.v1), (f.u0, f.v1)), f.quad)
        Hi = P.invert_h(H)
        # u ∈ [0,1] → 源 x ∈ [0,sw]；v → 源 y ∈ [0,sh]
        Hi = (Hi[0] * sw, Hi[1] * sw, Hi[2] * sw,
              Hi[3] * ky, Hi[4] * ky, Hi[5] * ky, Hi[6], Hi[7])
        x0, y0, x1, y1 = f.bbox(w, h)
        # 两道裁剪：v 带挡住「顺着 v 延续下去」的颜色，四边形挡住逆单应
        # 越过无穷远线之后在包围盒另一角冒出来的零星像素。
        band = (0.0, f.v0 * ky - 0.5, float(sw - 1), f.v1 * ky + 0.5)
        maps.append((Hi, x0, y0, x1, y1, band, f.quad))
    return P.paste_many(dst, w, h, src, sw, sh, maps, mix=mix,
                        progress=progress)


def _no_faces_msg():
    return "no stair faces to paste"


def format_stair_string(stairs):
    """台阶参数 → "edge,steps,rise,run,flip"（脚本/对话框回放用）。"""
    if not stairs:
        return ""
    return "%d,%d,%.4f,%.4f,%d" % (
        int(stairs.get("edge", 0)), int(stairs.get("steps", 6)),
        float(stairs.get("rise", 0.12)), float(stairs.get("run", 0.0)),
        1 if stairs.get("flip") else 0)


def parse_stair_string(text):
    """解析 format_stair_string 的输出；空串 = 不起台阶。"""
    out = {"on": False, "edge": 0, "steps": 6, "rise": 0.12, "run": 0.0,
           "flip": False}
    if not text or not str(text).strip():
        return out
    vals = []
    for raw in str(text).replace(";", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            vals.append(float(raw))
        except ValueError:
            return out
    if len(vals) < 5:
        return out
    out.update({"on": True,
                "edge": int(vals[0]) % 4,
                "steps": max(1, min(MAX_STEPS, int(vals[1]))),
                "rise": max(0.002, min(2.0, vals[2])),
                "run": max(0.0, min(1.0, vals[3])),
                "flip": bool(int(vals[4]))})
    return out
