"""Small, deterministic 2D helpers (no external kernel)."""
from __future__ import annotations

import math

Vec = tuple[float, float]


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def mul(a, s):
    return (a[0] * s, a[1] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def length(a):
    return math.hypot(a[0], a[1])


def unit(a):
    L = length(a)
    return (a[0] / L, a[1] / L)


def left_normal(d):
    return (-d[1], d[0])


def signed_area(poly) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2


def ensure_ccw(poly):
    return list(poly) if signed_area(poly) > 0 else list(reversed(poly))


def line_intersection(p, d, q, e):
    """Intersection of lines p + t d and q + s e. Returns None if parallel."""
    den = cross(d, e)
    if abs(den) < 1e-12:
        return None
    t = cross(sub(q, p), e) / den
    return add(p, mul(d, t))


def _seg_intersect(a, b, c, d) -> bool:
    def orient(p, q, r):
        v = cross(sub(q, p), sub(r, p))
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def is_simple(poly) -> bool:
    n = len(poly)
    if n < 3:
        return False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue
            c, d = poly[j], poly[(j + 1) % n]
            if _seg_intersect(a, b, c, d):
                return False
    return True


def is_convex(poly) -> bool:
    n = len(poly)
    sign = 0
    for i in range(n):
        c = cross(sub(poly[(i + 1) % n], poly[i]), sub(poly[(i + 2) % n], poly[(i + 1) % n]))
        if abs(c) < 1e-12:
            continue
        s = 1 if c > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def point_segment_param(p, a, b):
    """Return (t, dist) of p projected on segment a->b (t in metres along the segment)."""
    d = sub(b, a)
    L = length(d)
    u = mul(d, 1 / L)
    t = dot(sub(p, a), u)
    perp = abs(cross(u, sub(p, a)))
    return t, perp


def clip_halfplane(poly, a, b, c):
    """Keep the part of convex poly where a*x + b*y + c <= 0 (Sutherland–Hodgman)."""
    out = []
    n = len(poly)
    if n == 0:
        return out
    f = [a * x + b * y + c for x, y in poly]
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        fp, fq = f[i], f[(i + 1) % n]
        if fp <= 1e-12:
            out.append(p)
        if (fp < -1e-12 and fq > 1e-12) or (fp > 1e-12 and fq < -1e-12):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    # remove near-duplicates
    res = []
    for p in out:
        if not res or length(sub(p, res[-1])) > 1e-9:
            res.append(p)
    if len(res) > 1 and length(sub(res[0], res[-1])) < 1e-9:
        res.pop()
    return res


def offset_convex(poly, offsets):
    """Offset each edge i (poly[i]->poly[i+1]) of a CCW convex polygon outward by offsets[i]."""
    n = len(poly)
    lines = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        d = unit(sub(b, a))
        outward = (d[1], -d[0])  # right normal is outward for CCW
        lines.append((add(a, mul(outward, offsets[i])), d))
    pts = []
    for i in range(n):
        p1, d1 = lines[i - 1]
        p2, d2 = lines[i]
        pts.append(line_intersection(p1, d1, p2, d2))
    return pts


def polygons_overlap_area(p, q) -> float:
    """Overlap area of two simple polygons (uses shapely; only for validation, not geometry)."""
    from shapely.geometry import Polygon

    return Polygon(p).intersection(Polygon(q)).area
