"""Components (Genome 0.2, G3/G4): trim, shutters, roof-edge members, gutters, downspouts, chimneys,
fixtures, equipment, posts, screens — plus information-only items.

Every component is placed relative to something that already exists (a wall face, an opening, two
walls' corner, a roof edge, a plan point or a room) so it follows its host when the host changes.
Geometry is deliberately simple (boxes / hulls): the point of G3 is position, extent, colour and
information, not millwork profiles.
"""
from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .. import geom2d as G
from ..genome.schema import Component, Size, Value

IN = 0.0254
# size defaults (metres) by kind when neither the element nor its family states one: basis "assumed"
KIND_DEFAULTS = {
    "trim": {"w": 3.5 * IN, "d": 0.75 * IN},
    "shutter": {"w": 15 * IN, "d": 1.0 * IN},
    "fascia": {"h": 5.5 * IN, "d": 0.75 * IN},
    "soffit": {"h": 0.625 * IN},
    "gutter": {"h": 5 * IN, "d": 5 * IN},
    "downspout": {"w": 3 * IN, "d": 2 * IN, "h": 3.0},
    "chimney": {"w": 0.6, "d": 0.6, "h": 1.0},
    "vent": {"w": 14 * IN, "h": 24 * IN, "d": 1.0 * IN},
    "fixture": {"w": 6 * IN, "h": 10 * IN, "d": 6 * IN},
    "equipment": {"w": 0.7, "h": 0.7, "d": 0.7},
    "post": {"w": 5.5 * IN, "d": 5.5 * IN, "h": 2.4},
    "screen": {"w": 0.9, "h": 2.0, "d": 1.0 * IN},
    "railing": {"w": 1.0, "h": 0.9, "d": 1.5 * IN},
    "stair": {"w": 0.9, "h": 0.5, "d": 1.0},
    "furnishing": {"w": 0.6, "h": 0.9, "d": 0.6},
    "other": {"w": 0.15, "h": 0.15, "d": 0.15},
}

# IFC4 class + predefined type by kind (fixture/equipment refined by info.category)
IFC_BY_KIND = {
    "cladding": ("IfcCovering", "CLADDING"), "trim": ("IfcCovering", "MOLDING"),
    "fascia": ("IfcCovering", "USERDEFINED:FASCIA"), "soffit": ("IfcCovering", "USERDEFINED:SOFFIT"),
    "shutter": ("IfcShadingDevice", "SHUTTER"), "gutter": ("IfcPipeSegment", "GUTTER"),
    "downspout": ("IfcPipeSegment", "RIGIDSEGMENT"), "chimney": ("IfcChimney", "NOTDEFINED"),
    "vent": ("IfcAirTerminal", "USERDEFINED:VENT"), "post": ("IfcColumn", "COLUMN"),
    "screen": ("IfcPlate", "USERDEFINED:SCREEN"), "railing": ("IfcRailing", "NOTDEFINED"),
    "stair": ("IfcStair", "NOTDEFINED"), "furnishing": ("IfcFurniture", "NOTDEFINED"),
    "fixture": ("IfcBuildingElementProxy", "NOTDEFINED"), "equipment": ("IfcBuildingElementProxy", "NOTDEFINED"),
    "other": ("IfcBuildingElementProxy", "NOTDEFINED"),
}
IFC_BY_CATEGORY = {
    "light": ("IfcLightFixture", "NOTDEFINED"), "exterior_light": ("IfcLightFixture", "NOTDEFINED"),
    "electric_meter": ("IfcFlowMeter", "ENERGYMETER"), "gas_meter": ("IfcFlowMeter", "GASMETER"),
    "water_meter": ("IfcFlowMeter", "WATERMETER"), "outlet": ("IfcOutlet", "POWEROUTLET"),
    "switch": ("IfcSwitchingDevice", "TOGGLESWITCH"), "panel": ("IfcElectricDistributionBoard", "DISTRIBUTIONBOARD"),
    "disconnect": ("IfcElectricDistributionBoard", "SWITCHBOARD"), "camera": ("IfcAudioVisualAppliance", "CAMERA"),
    "plumbing_fixture": ("IfcSanitaryTerminal", "NOTDEFINED"), "sink": ("IfcSanitaryTerminal", "SINK"),
    "toilet": ("IfcSanitaryTerminal", "TOILETPAN"), "bath": ("IfcSanitaryTerminal", "BATH"),
    "shower": ("IfcSanitaryTerminal", "SHOWER"), "appliance": ("IfcElectricAppliance", "NOTDEFINED"),
    "register": ("IfcAirTerminal", "DIFFUSER"), "radiator": ("IfcSpaceHeater", "RADIATOR"),
    "heater": ("IfcSpaceHeater", "NOTDEFINED"), "hvac_condenser": ("IfcUnitaryEquipment", "SPLITSYSTEM"),
    "window_ac": ("IfcUnitaryEquipment", "AIRCONDITIONINGUNIT"), "furnace": ("IfcBurner", "NOTDEFINED"),
    "water_heater": ("IfcTank", "STORAGE"), "hose_bib": ("IfcValve", "FAUCET"), "smoke_detector": ("IfcSensor", "SMOKESENSOR"),
    "doorbell": ("IfcAlarm", "BELL"), "fan": ("IfcFan", "NOTDEFINED"), "cabinet": ("IfcFurniture", "NOTDEFINED"),
    "countertop": ("IfcFurniture", "NOTDEFINED"), "fireplace": ("IfcBuildingElementProxy", "NOTDEFINED"),
}


def ifc_class_for(el: Component) -> tuple[str, str]:
    cat = (el.info.category if el.info else "") or ""
    if el.kind in ("fixture", "equipment", "vent", "other") and cat in IFC_BY_CATEGORY:
        return IFC_BY_CATEGORY[cat]
    return IFC_BY_KIND.get(el.kind, ("IfcBuildingElementProxy", "NOTDEFINED"))


def size_value(g, el: Component, key: str, rec: dict, res):
    """Element size -> family size -> kind default; records provenance under 'size.<key>'."""
    v = getattr(el.size, key)
    src = "element"
    if (v is None or v.value is None) and el.family and el.family in g.families:
        fv = getattr(g.families[el.family].size, key)
        if fv is not None and fv.value is not None:
            v, src = fv, f"family {el.family}"
    if v is not None and v.value is not None:
        rec[f"size.{key}"] = {**res._prov(v), **({"from": src} if src != "element" else {})}
        return v.value
    d = KIND_DEFAULTS.get(el.kind, KIND_DEFAULTS["other"]).get(key)
    if d is None:
        return None
    rec[f"size.{key}"] = {"value": d, "basis": "assumed", "defaulted": True, "note": f"kind default for {el.kind}"}
    return d


def pval(v: Value | None, rec: dict, name: str, res, default=0.0):
    if v is None or v.value is None:
        rec[name] = {"value": default, "basis": "assumed", "defaulted": True, "note": "absent; compiler default"}
        return default
    rec[name] = res._prov(v)
    return v.value


def hull(points) -> mf.Manifold:
    return mf.Manifold.hull_points([list(map(float, p)) for p in points])


def oriented_box(cx, cy, w, d, z0, h, rot_deg=0.0) -> mf.Manifold:
    m = mf.Manifold.cube([w, d, h]).translate([-w / 2, -d / 2, 0.0]).rotate([0.0, 0.0, rot_deg]).translate([cx, cy, z0])
    return m


def plan_prism(poly, z0, z1) -> mf.Manifold:
    poly = G.ensure_ccw([tuple(p) for p in poly])
    return mf.Manifold.extrude(mf.CrossSection([poly]), z1 - z0).translate([0.0, 0.0, z0])


# ----------------------------------------------------------------- wall sides

def exterior_sign(frame, storey_slabs, storey_walls_centroid) -> int:
    """+1 if the wall's left face is the exterior, -1 if the right face is."""
    from shapely.geometry import Point, Polygon

    mid = G.add(frame.start, G.mul(frame.d, frame.length / 2))
    pl = G.add(mid, G.mul(frame.n, frame.off_left + 0.15))
    pr = G.add(mid, G.mul(frame.n, frame.off_right - 0.15))
    polys = [Polygon(b) for b in storey_slabs]
    inl = any(p.contains(Point(pl)) for p in polys)
    inr = any(p.contains(Point(pr)) for p in polys)
    if inl and not inr:
        return -1
    if inr and not inl:
        return 1
    c = storey_walls_centroid
    return 1 if G.dot(G.sub(mid, c), frame.n) > 0 else -1


def side_sign(side: str, ext: int) -> int:
    return {"left": 1, "right": -1, "exterior": ext, "interior": -ext}[side]


def face_band(frame, sgn: int, gap: float, depth: float):
    """v-range of a band sitting on the face of side sgn, starting `gap` off the face, `depth` thick."""
    if sgn > 0:
        return frame.off_left + gap, frame.off_left + gap + depth
    return frame.off_right - gap - depth, frame.off_right - gap


def local_box(frame, u0, u1, v0, v1, z0, z1) -> mf.Manifold:
    d, n, s = frame.d, frame.n, frame.start
    pts = [G.add(G.add(s, G.mul(d, u)), G.mul(n, v)) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]
    return plan_prism(pts, z0, z1)


# ----------------------------------------------------------------- roof edges

def roof_top_z(planes, dv, p):
    return min(pl.z(p) for pl in planes) + dv


def roof_under_z(planes, p):
    return min(pl.z(p) for pl in planes)


def edge_breaks(a, b, panel_regions):
    """Parameters t in [0,1] along a->b where the roof surface changes plane (ridge/hip points)."""
    d = G.sub(b, a)
    L2 = G.dot(d, d)
    ts = {0.0, 1.0}
    nrm = G.unit((-d[1], d[0]))
    for reg in panel_regions:
        for p in reg:
            if abs(G.dot(G.sub(p, a), nrm)) < 1e-6:
                t = G.dot(G.sub(p, a), d) / L2
                if 1e-6 < t < 1 - 1e-6:
                    ts.add(round(t, 9))
    return sorted(ts)


def roof_edge_solids(kind, roof_el, rdata, planes, edges, size, gap, slope):
    """Fascia / rake board / gutter / soffit along the given footprint edges of a compiled roof."""
    fp = [tuple(p) for p in roof_el.footprint]
    ol = [tuple(p) for p in rdata["outline"]]
    regions = [pn["region"] for pn in rdata["panels"]]
    dv = rdata["vertical_thickness"]
    n = len(fp)
    out = []
    for i in edges:
        a, b = fp[i], fp[(i + 1) % n]
        oa, ob = ol[i], ol[(i + 1) % n]
        dirv = G.unit(G.sub(ob, oa))
        outw = (dirv[1], -dirv[0])  # right normal = outward for CCW
        role = roof_el.edge_roles[i]
        if role == "abut":
            continue
        ts = edge_breaks(oa, ob, regions)
        for t0, t1 in zip(ts[:-1], ts[1:]):
            p0 = G.add(oa, G.mul(G.sub(ob, oa), t0))
            p1 = G.add(oa, G.mul(G.sub(ob, oa), t1))
            if kind in ("fascia", "trim", "gutter"):
                if kind == "gutter":
                    g0, g1 = gap, gap + size["d"]
                    drop = 0.5 * IN
                    zt = [roof_top_z(planes, dv, p) - drop for p in (p0, p1)]
                    zb = [z - size["h"] for z in zt]
                else:
                    g0, g1 = gap, gap + size["d"]
                    zt = [roof_top_z(planes, dv, p) for p in (p0, p1)]
                    zb = [z - size["h"] for z in zt]
                pts = []
                for p, z_t, z_b in zip((p0, p1), zt, zb):
                    for g_ in (g0, g1):
                        q = G.add(p, G.mul(outw, g_))
                        pts += [(q[0], q[1], z_b), (q[0], q[1], z_t)]
                out.append(hull(pts))
            elif kind == "soffit":
                # between the wall face line and the overhang edge; level on eaves, following the roof on rakes
                # project p0/p1 back onto the footprint edge line
                fd = G.unit(G.sub(b, a))
                q0 = G.add(a, G.mul(fd, G.dot(G.sub(p0, a), fd)))
                q1 = G.add(a, G.mul(fd, G.dot(G.sub(p1, a), fd)))
                th = size["h"]
                if role in ("eave", "flush-eave"):
                    z = roof_under_z(planes, p0)
                    pts = [(x, y, zz) for (x, y) in (p0, p1, q0, q1) for zz in (z - th, z)]
                else:
                    pts = []
                    for (x, y) in (p0, p1, q0, q1):
                        z = roof_under_z(planes, (x, y))
                        pts += [(x, y, z - th), (x, y, z)]
                if G.length(G.sub(p0, q0)) > 1e-4:
                    out.append(hull(pts))
    return out
