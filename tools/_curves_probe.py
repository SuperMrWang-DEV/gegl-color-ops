# -*- coding: utf-8 -*-
"""看曲线截图右下角有没有被裁：取几行扫最右的非白像素，再和画布宽度比。"""
import cairo

OUT = r"C:\Users\Administrator\WorkBuddy\2026-11-10-21-12-59\outputs"

for name in ("lab", "lch", "hsv", "cmyk"):
    p = OUT + "\\curves-%s.png" % name
    s = cairo.ImageSurface.create_from_png(p)
    w, h = s.get_width(), s.get_height()
    buf = s.get_data()
    stride = s.get_stride()

    def px(x, y):
        o = y * stride + x * 4
        return buf[o + 2], buf[o + 1], buf[o], buf[o + 3]   # r,g,b,a

    def rightmost(y, thresh=200):
        for x in range(w - 1, -1, -1):
            r, g, b, _a = px(x, y)
            if min(r, g, b) < thresh:
                return x
        return -1

    rows = {"output": h - 22, "graph": int(h * 0.45), "title": 18}
    print(name, "%dx%d" % (w, h),
          {k: rightmost(v) for k, v in rows.items()})
