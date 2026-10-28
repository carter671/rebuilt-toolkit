"""Roof solver for convex footprints with per-edge roles (eave / rake / abut).

Every eave edge carries a plane rising inward at the roof pitch from the wall-plate line. The
roof surface is the lower envelope (minimum) of those planes; each panel is the region of the
overhang outline where its plane is the minimum. For convex footprints with a single pitch this
is exactly the straight-skeleton roof (gable, hip, shed and any convex combination).
Non-convex footprints (valleys) are M3 and are reported unsupported, not approximated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .. import geom2d as G


@dataclass
class RoofPlane:
    edge: int
    a: float  # z = a*x + b*y + c (underside)
    b: float
    c: float

    def z(self, p) -> float:
        return self.a * p[0] + self.b * p[1] + self.c


@dataclass
class RoofPanel:
    edge: int
    plane: RoofPlane
    region: list  # plan polygon, CCW
    vertical_thickness: float


def planes(footprint, roles, plate_z: float, slope: float) -> list[RoofPlane]:
    out = []
    n = len(footprint)
    for i in range(n):
        if roles[i] not in ("eave", "flush-eave"):
            continue
        a, b = footprint[i], footprint[(i + 1) % n]
        d = G.unit(G.sub(b, a))
        nin = G.left_normal(d)  # inward for a CCW footprint
        # z = plate + slope * dot(p - a, nin)
        out.append(RoofPlane(i, slope * nin[0], slope * nin[1], plate_z - slope * G.dot(a, nin)))
    return out


def overhang_outline(footprint, roles, eave: float, rake: float):
    offs = [eave if r == "eave" else rake if r == "rake" else 0.0 for r in roles]  # flush-eave / abut: no overhang
    return G.offset_convex(footprint, offs)


def panels(footprint, roles, plate_z, slope, eave, rake, thickness) -> list[RoofPanel]:
    pls = planes(footprint, roles, plate_z, slope)
    outline = overhang_outline(footprint, roles, eave, rake)
    dv = thickness * math.sqrt(1 + slope * slope)
    res = []
    for p in pls:
        region = list(outline)
        for q in pls:
            if q is p:
                continue
            # keep where p.z <= q.z  ->  (p.a-q.a)x + (p.b-q.b)y + (p.c-q.c) <= 0
            region = G.clip_halfplane(region, p.a - q.a, p.b - q.b, p.c - q.c)
        if len(region) >= 3 and abs(G.signed_area(region)) > 1e-9:
            res.append(RoofPanel(p.edge, p, G.ensure_ccw(region), dv))
    return res
