"""MODEL compiler: Genome -> CompiledModel (deterministic solids + analytic data + report).

compile_genome() is a pure function of (genome, profile, COMPILER_VERSION). The optional cache
lets recompilation reuse solids whose input hash did not change; it never changes results.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import manifold3d as mf
import numpy as np

from .. import geom2d as G
from ..genome.profiles import PROFILES
from ..genome.schema import Component, Genome, Opening, Roof, Slab, Space, StoreyRef, Value, Wall
from ..genome.validate import get_param, validate, values_of
from ..issues import IssueList
from . import components as C
from . import roofs as R
from . import walls as W

COMPILER_VERSION = "0.2.0"
_RANK = {"measured": 0, "extracted": 1, "observed": 2, "inferred": 3, "assumed": 4, "unknown": 5}
EPS_CUT = 0.005  # opening voids extend this far past each wall face
FILL_THICK = {"door": 0.045, "window": 0.07}


@dataclass
class Mesh:
    verts: np.ndarray  # (n,3) float64, metres
    tris: np.ndarray  # (m,3) int64

    def volume(self) -> float:
        v = self.verts[self.tris]
        return float(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6)

    def bounds(self):
        return self.verts.min(0), self.verts.max(0)


@dataclass
class CompiledElement:
    id: str
    type: str  # wall | opening | filling | slab | roof | space
    ifc_class: str
    rev: int
    storey: str | None
    mesh: Mesh | None
    parts: dict = field(default_factory=dict)  # named sub-meshes (roof panels)
    data: dict = field(default_factory=dict)  # analytic quantities
    params: dict = field(default_factory=dict)  # param -> provenance record (value used, basis, ...)
    material: str | None = None
    input_hash: str = ""
    name: str = ""


@dataclass
class CompiledModel:
    genome_revision: int
    compiler_version: str
    profile: str
    elements: dict[str, CompiledElement]
    relations: dict
    issues: IssueList
    unsupported: list[dict]
    rebuilt: list[str]
    reused: list[str]
    model_hash: str = ""
    _solids: dict = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        return not self.issues.errors

    def by_type(self, t):
        return [e for _, e in sorted(self.elements.items()) if e.type == t]

    def report(self) -> dict:
        return {
            "compiler_version": self.compiler_version,
            "genome_revision": self.genome_revision,
            "profile": self.profile,
            "model_hash": self.model_hash,
            "ok": self.ok,
            "counts": {t: len(self.by_type(t)) for t in ("wall", "opening", "filling", "slab", "roof", "space")},
            "issues": [i.to_dict() for i in self.issues.sorted()],
            "unsupported": self.unsupported,
            "rebuilt": self.rebuilt,
            "reused": self.reused,
        }


class CompileError(RuntimeError):
    def __init__(self, issues: IssueList):
        super().__init__("; ".join(i.message for i in issues.errors))
        self.issues = issues


# ---------------------------------------------------------------- helpers

def _mesh(m: mf.Manifold) -> Mesh:
    mm = m.to_mesh64()
    return Mesh(np.asarray(mm.vert_properties[:, :3], dtype=np.float64), np.asarray(mm.tri_verts, dtype=np.int64))


def _prism(poly, z0: float, h: float) -> mf.Manifold:
    cs = mf.CrossSection([np.asarray(G.ensure_ccw(poly), dtype=np.float64)])
    return mf.Manifold.extrude(cs, h).translate([0.0, 0.0, z0])


def _local_box(frame: W.WallFrame, u0, u1, v0, v1, z0, z1) -> mf.Manifold:
    box = mf.Manifold.cube([u1 - u0, v1 - v0, z1 - z0]).translate([u0, v0, z0])
    d, n = frame.d, frame.n
    T = np.array([[d[0], n[0], 0.0, frame.start[0]], [d[1], n[1], 0.0, frame.start[1]], [0.0, 0.0, 1.0, 0.0]])
    return box.transform(T)


def _clip_below_planes(m: mf.Manifold, planes: list[R.RoofPlane]) -> mf.Manifold:
    for p in planes:
        nrm = np.array([p.a, p.b, -1.0])
        L = float(np.linalg.norm(nrm))
        m = m.trim_by_plane((nrm / L).tolist(), -p.c / L)
    return m


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


class _Resolver:
    """Resolves Value records to numbers, applying profile defaults and recording provenance."""

    def __init__(self, g: Genome, profile: str, issues: IssueList):
        self.g, self.prof, self.issues = g, PROFILES[profile], issues

    def val(self, el, param, rec: dict, default=None):
        v = get_param(el, param)
        if v is None:
            rec[param] = {"value": default, "basis": "assumed", "defaulted": True, "note": "absent; compiler default"}
            return default
        if isinstance(v, StoreyRef):
            s = self.g.storey(el.storey)
            rec[param] = {**self._prov(s.height), "from": f"storey {s.id} height"}
            return s.height.value
        assert isinstance(v, Value)
        if v.value is None:
            d = self.prof.defaults.get((el.type, param))
            rec[param] = {**self._prov(v), "value": d, "basis": "assumed", "defaulted": True,
                          "note": f"unknown; profile '{self.prof.name}' default"}
            return d
        rec[param] = self._prov(v)
        return v.value

    @staticmethod
    def _prov(v: Value) -> dict:
        d = {"value": v.value, "basis": v.basis, "verification": v.verification,
             "uncertainty": v.uncertainty.value if v.uncertainty else None,
             "confidence": v.confidence, "observations": list(v.observations)}
        if v.input:
            d["input"] = v.input
        if v.conflicts:
            d["conflicts"] = [c.model_dump() for c in v.conflicts]
        return d


# ---------------------------------------------------------------- main

def compile_genome(g: Genome, profile: str = "review", cache: dict | None = None, check_overlaps: bool = True) -> CompiledModel:
    issues = validate(g, profile)
    if issues.errors:
        raise CompileError(issues)
    res = _Resolver(g, profile, issues)
    els: dict[str, CompiledElement] = {}
    solids: dict[str, mf.Manifold] = {}
    unsupported: list[dict] = []
    rebuilt, reused = [], []
    cache = cache if cache is not None else {}
    tol = g.project.tolerances.join

    def storey_z(sid):
        return g.storey(sid).elevation.value

    def cached(key, build):
        if key in cache:
            reused.append(key[0])
            return cache[key]
        out = build()
        cache[key] = out
        rebuilt.append(key[0])
        return out

    E = dict(sorted(g.elements.items()))
    skip: dict[str, str] = {}

    # ---- unsupported features (reported, never silently built differently)
    for eid, el in E.items():
        if isinstance(el, Wall) and el.shape != "straight":
            skip[eid] = f"wall shape '{el.shape}'"
        if isinstance(el, Opening) and el.shape != "rectangle":
            skip[eid] = f"opening shape '{el.shape}'"
        if isinstance(el, Roof) and (el.form == "planes" or not G.is_convex(el.footprint)):
            skip[eid] = "roof form 'planes'" if el.form == "planes" else "non-convex roof footprint (needs M3 solver)"
    changed = True
    while changed:  # propagate to dependents
        changed = False
        for eid, el in E.items():
            if eid in skip:
                continue
            dep = None
            if isinstance(el, Opening) and el.host in skip:
                dep = el.host
            if isinstance(el, Wall) and el.top and el.top.attach in skip:
                dep = el.top.attach
            if dep:
                skip[eid] = f"depends on unsupported element {dep}"
                changed = True
    for eid, why in sorted(skip.items()):
        unsupported.append({"element": eid, "reason": why, "action": "not built"})
        issues.add("UNSUPPORTED_FEATURE", "warning", f"{eid}: {why}; not built", (eid,), layer="compile")

    # ---- chimneys (point-placed) first: they cut the roofs they pass through
    chimneys = {}
    for eid, el in E.items():
        if isinstance(el, Component) and el.kind == "chimney" and el.placement.on == "point" and el.geometry == "box" and eid not in skip:
            rec = {}
            w = C.size_value(g, el, "w", rec, res)
            d = C.size_value(g, el, "d", rec, res)
            h = C.size_value(g, el, "h", rec, res)
            z0 = storey_z(el.storey) + C.pval(el.placement.z, rec, "placement.z", res)
            chimneys[eid] = (C.oriented_box(el.placement.at[0], el.placement.at[1], w, d, z0, h, el.placement.rotation), rec,
                             {"w": w, "d": d, "h": h, "base_z": z0, "top_z": z0 + h})

    # ---- roofs first (walls may attach to them); roofs that die into others after their hosts
    roof_data = {}
    roof_mass = {}
    roof_parts = {}
    roof_ids = [eid for eid, el in E.items() if isinstance(el, Roof) and eid not in skip]
    ordered, seen_r = [], set()

    def _visit(r, stack=()):
        if r in seen_r:
            return
        if r in stack:
            issues.add("ROOF_TRIM_CYCLE", "error", f"roof trim cycle through {r}", (r,), layer="compile")
            return
        for o in E[r].trim_by:
            if o in roof_ids:
                _visit(o, stack + (r,))
        seen_r.add(r)
        ordered.append(r)

    for r in roof_ids:
        _visit(r)
    for eid in ordered:
        el = E[eid]
        rec = {}
        slope = res.val(el, "pitch", rec)
        plate = res.val(el, "plate_height", rec)
        eave = res.val(el, "overhang", rec, 0.0)
        rake = res.val(el, "rake_overhang", rec, 0.0)
        thick = res.val(el, "thickness", rec)
        zp = storey_z(el.storey) + plate
        fp = [tuple(p) for p in el.footprint]
        pnls = R.panels(fp, el.edge_roles, zp, slope, eave, rake, thick)
        pls = R.planes(fp, el.edge_roles, zp, slope)
        roof_data[eid] = pls
        key = (eid, _h([el.model_dump(mode="json"), zp]))

        def build(pnls=pnls):
            parts = {}
            for k, pn in enumerate(pnls):
                a, b, c = pn.plane.a, pn.plane.b, pn.plane.c
                m = _prism(pn.region, 0.0, pn.vertical_thickness)
                m = m.transform(np.array([[1, 0, 0, 0], [0, 1, 0, 0], [a, b, 1, c]], dtype=float))
                parts[f"panel-{k}-edge{pn.edge}"] = m
            return parts

        parts = cached(key, build)
        trimmed = [o for o in el.trim_by if o in roof_mass]
        for o in el.trim_by:
            if o not in roof_mass:
                issues.add("ROOF_TRIM_MISSING", "warning", f"{eid}: trim_by roof {o} was not built; no trim applied", (eid, o), layer="compile")
        if trimmed:
            cutter = mf.Manifold.batch_boolean([roof_mass[o] for o in trimmed], mf.OpType.Add) if len(trimmed) > 1 else roof_mass[trimmed[0]]
            parts = {k: m - cutter for k, m in parts.items()}
            parts = {k: m for k, m in parts.items() if not m.is_empty() and m.volume() > 1e-12}
        cut_by = []
        for cid, (cm, _, _) in sorted(chimneys.items()):
            if any(not (m ^ cm).is_empty() for m in parts.values()):
                cut_by.append(cid)
                parts = {k: m - cm for k, m in parts.items()}
        parts = {k: m for k, m in parts.items() if not m.is_empty() and m.volume() > 1e-12}
        whole = mf.Manifold.batch_boolean(list(parts.values()), mf.OpType.Add) if len(parts) > 1 else next(iter(parts.values()))
        solids[eid] = whole
        roof_parts[eid] = parts
        dv = pnls[0].vertical_thickness
        top = max(pn.plane.z(p) for pn in pnls for p in pn.region) + dv
        if trimmed or cut_by:
            top = max(pn.plane.z(p) for pn in pnls for p in pn.region) + dv if not trimmed else float(whole.bounding_box()[5])
        outline_pts = R.overhang_outline(fp, el.edge_roles, eave, rake)
        lo_z = min(pn.plane.z(p) for pn in pnls for p in pn.region) - 1.0
        mass = _prism(outline_pts, lo_z, top - lo_z + 1.0)
        mass = _clip_below_planes(mass, [R.RoofPlane(p.edge, p.a, p.b, p.c + dv) for p in pls])
        roof_mass[eid] = mass
        els[eid] = CompiledElement(
            eid, "roof", "IfcRoof", el.rev, el.storey, _mesh(whole),
            parts={k: _mesh(m) for k, m in parts.items()},
            data={"plate_z": zp, "slope": slope, "panels": [
                {"edge": pn.edge, "region": [list(p) for p in pn.region], "plane": [pn.plane.a, pn.plane.b, pn.plane.c],
                 "plan_area": abs(G.signed_area(pn.region)),
                 "slope_area": abs(G.signed_area(pn.region)) * (1 + slope * slope) ** 0.5} for pn in pnls],
                "outline": [list(p) for p in R.overhang_outline(fp, el.edge_roles, eave, rake)],
                "top_z": top, "vertical_thickness": pnls[0].vertical_thickness, "volume": whole.volume(),
                "trimmed_by": trimmed, "cut_by": cut_by},
            params=rec, material=el.material, input_hash=key[1], name=el.name)

    # ---- wall frames & junctions
    frames, wrec = {}, {}
    for eid, el in E.items():
        if isinstance(el, Wall) and eid not in skip:
            rec = {}
            t = res.val(el, "thickness", rec)
            wrec[eid] = rec
            frames[eid] = W.make_frame(eid, el.storey, el.start, el.end, t, el.alignment)
    def _prio(wid):
        el = E[wid]
        h = storey_z(el.storey) + (res.val(el, "height", {}, 0.0) if not isinstance(el.height, StoreyRef) else g.storey(el.storey).height.value or 0)
        return (1 if el.top else 0, round(h, 6), 1 if el.exterior else 0, round(frames[wid].off_left - frames[wid].off_right, 6))

    plans = W.resolve(frames, tol, issues, {w: _prio(w) for w in frames})

    openings_by_host: dict[str, list[str]] = {}
    for eid, el in E.items():
        if isinstance(el, Opening) and eid not in skip:
            openings_by_host.setdefault(el.host, []).append(eid)

    # ---- walls with opening cuts, fillings
    for wid, plan in plans.items():
        el: Wall = E[wid]
        rec = wrec[wid]
        f = plan.frame
        base = storey_z(el.storey) + res.val(el, "base_offset", rec, 0.0)
        height = res.val(el, "height", rec)
        planes = roof_data.get(el.top.attach) if el.top else None
        if planes is not None:
            rp = els[el.top.attach].params
            src = max(("pitch", "plate_height"), key=lambda k: _RANK.get(rp[k]["basis"], 4))
            rec["height"] = {"value": None, "basis": rp[src]["basis"], "verification": rp[src].get("verification"),
                             "from": f"clipped to roof {el.top.attach} (governed by roof {src})", "derived": True,
                             "uncertainty": None, "observations": rp[src].get("observations", [])}
        top_z = els[el.top.attach].data["top_z"] + 1.0 if planes else base + height
        op_specs = []
        for oid in sorted(openings_by_host.get(wid, [])):
            o: Opening = E[oid]
            orec = {}
            off = res.val(o, "offset", orec)
            w = res.val(o, "width", orec)
            h = res.val(o, "height", orec)
            sill = res.val(o, "sill", orec, 0.0)
            op_specs.append((oid, o, off, w, h, sill, orec))
        neighbour_inputs = sorted(set(plan.start_junction.others + plan.end_junction.others))
        key_obj = [el.model_dump(mode="json"), [frames[n].__dict__ for n in neighbour_inputs],
                   [E[o].model_dump(mode="json") for o, *_ in op_specs], base,
                   [p.__dict__ for p in planes] if planes else None, [list(p) for p in plan.polygon]]
        key = (wid, _h(key_obj))

        def build(plan=plan, base=base, height=height, planes=planes, top_z=top_z, op_specs=op_specs, f=f):
            gross = _prism(plan.polygon, base, (top_z - base) if planes else height)
            if planes:
                gross = _clip_below_planes(gross, planes)
            voids = {}
            for oid, o, off, w, h, sill, _ in op_specs:
                voids[oid] = _local_box(f, off, off + w, f.off_right - EPS_CUT, f.off_left + EPS_CUT, base + sill, base + sill + h)
            net = gross - mf.Manifold.batch_boolean(list(voids.values()), mf.OpType.Add) if voids else gross
            return gross, net, voids

        gross, net, voids = cached(key, build)
        solids[wid] = net
        cs = W.clear_span(plan)
        els[wid] = CompiledElement(
            wid, "wall", "IfcWall", el.rev, el.storey, _mesh(net),
            data={"baseline": [list(f.start), list(f.end)], "length": f.length, "thickness": f.off_left - f.off_right,
                  "base_z": base, "height": None if planes else height, "top_z": None if planes else base + height,
                  "plan_polygon": [list(p) for p in plan.polygon], "clear_span": list(cs),
                  "junctions": {"start": plan.start_junction.__dict__, "end": plan.end_junction.__dict__},
                  "butted_by": plan.butted_by, "gross_volume": gross.volume(), "volume": net.volume(),
                  "exterior": el.exterior, "attached_roof": el.top.attach if el.top else None,
                  "frame": {"d": list(f.d), "n": list(f.n), "off_left": f.off_left, "off_right": f.off_right}},
            params=rec, material=el.material, input_hash=key[1], name=el.name)

        # opening checks + opening/filling elements
        for oid, o, off, w, h, sill, orec in op_specs:
            if off < cs[0] - 1e-9 or off + w > cs[1] + 1e-9:
                issues.add("OPENING_IN_JUNCTION", "error",
                           f"{oid}: span {off:.3f}-{off + w:.3f} leaves host clear span {cs[0]:.3f}-{cs[1]:.3f}", (oid, wid), layer="compile")
            for (bw, side, u0, u1) in plan.butted_by:
                if u0 < off + w - 1e-9 and u1 > off + 1e-9:
                    issues.add("OPENING_BLOCKED_BY_WALL", "error", f"{oid}: wall {bw} butts into the opening", (oid, wid, bw), layer="compile")
            head = base + sill + h
            if planes:
                corners = [G.add(G.add(f.start, G.mul(f.d, uu)), G.mul(f.n, vv)) for uu in (off, off + w) for vv in (f.off_left, f.off_right)]
                lim = min(min(p.z(c) for p in planes) for c in corners)
                if head > lim + 1e-9:
                    issues.add("OPENING_ABOVE_HOST", "error", f"{oid}: head {head:.3f} above roof-clipped wall top {lim:.3f}", (oid, wid), layer="compile")
            vm = voids[oid]
            ctr_u, ctr_v = off + w / 2, (f.off_left + f.off_right) / 2
            centre = G.add(G.add(f.start, G.mul(f.d, ctr_u)), G.mul(f.n, ctr_v))
            els[oid] = CompiledElement(
                oid, "opening", "IfcOpeningElement", o.rev, el.storey, _mesh(vm),
                data={"host": wid, "kind": o.kind, "offset": off, "width": w, "height": h, "sill": sill,
                      "sill_z": base + sill, "head_z": head, "centre": [centre[0], centre[1], base + sill + h / 2],
                      "depth": f.off_left - f.off_right + 2 * EPS_CUT, "void_volume": vm.volume()},
                params=orec, input_hash=key[1], name=o.name)
            if o.filling and o.filling.type != "none":
                ft = FILL_THICK[o.filling.type]
                fm = _local_box(f, off, off + w, ctr_v - ft / 2, ctr_v + ft / 2, base + sill, head)
                fid = f"{oid}#fill"
                solids[fid] = fm
                els[fid] = CompiledElement(
                    fid, "filling", "IfcDoor" if o.filling.type == "door" else "IfcWindow", o.rev, el.storey, _mesh(fm),
                    data={"opening": oid, "host": wid, "kind": o.filling.type, "operation": o.filling.operation,
                          "width": w, "height": h, "thickness": ft, "volume": fm.volume(), "representation": "proxy-panel"},
                    params=orec, material=o.filling.material, input_hash=key[1], name=f"{o.name} {o.filling.type}")

    # ---- eave overhangs that run over another block's wall (e.g. an eave continuing into a valley over a
    # projecting wing's eave wall): notch the overhang around that wall. Only intersections lying wholly in the
    # overhang zone (outside the roof's own wall-plate footprint) are notched; anything else stays an overlap error.
    for rid in ordered:
        if rid not in solids:
            continue
        rel = E[rid]
        outline = els[rid].data["outline"]
        lo = float(solids[rid].bounding_box()[2]) - 1.0
        hi = float(solids[rid].bounding_box()[5]) + 1.0
        zone = _prism(outline, lo, hi - lo) - _prism([tuple(p) for p in rel.footprint], lo - 1.0, hi - lo + 2.0)
        rb = solids[rid].bounding_box()
        notch = []
        for wid in sorted(plans):
            if wid not in solids or (E[wid].top and E[wid].top.attach == rid):
                continue
            wb = solids[wid].bounding_box()
            if any(rb[j] >= wb[j + 3] - 1e-9 or wb[j] >= rb[j + 3] - 1e-9 for j in range(3)):
                continue
            x = solids[rid] ^ solids[wid]
            v = x.volume()
            if v > 1e-9 and abs((x ^ zone).volume() - v) < 1e-9:
                notch.append(wid)
        if notch:
            parts = roof_parts[rid]
            cutter = mf.Manifold.batch_boolean([solids[w] for w in notch], mf.OpType.Add) if len(notch) > 1 else solids[notch[0]]
            parts = {k: m - cutter for k, m in parts.items()}
            parts = {k: m for k, m in parts.items() if not m.is_empty() and m.volume() > 1e-12}
            whole = mf.Manifold.batch_boolean(list(parts.values()), mf.OpType.Add) if len(parts) > 1 else next(iter(parts.values()))
            solids[rid] = whole
            ce = els[rid]
            ce.mesh, ce.parts = _mesh(whole), {k: _mesh(m) for k, m in parts.items()}
            ce.data["notched_by"] = notch
            ce.data["volume"] = whole.volume()
            issues.add("ROOF_OVERHANG_NOTCHED", "info", f"{rid}: eave overhang notched around wall(s) {', '.join(notch)}",
                       (rid, *notch), layer="compile")

    # ---- slabs
    for eid, el in E.items():
        if not isinstance(el, Slab) or eid in skip:
            continue
        rec = {}
        t = res.val(el, "thickness", rec)
        top = storey_z(el.storey) + res.val(el, "top_offset", rec, 0.0)
        key = (eid, _h([el.model_dump(mode="json"), top]))
        m = cached(key, lambda el=el, t=t, top=top: _prism(el.boundary, top - t, t))
        solids[eid] = m
        area = abs(G.signed_area(el.boundary))
        els[eid] = CompiledElement(eid, "slab", "IfcSlab", el.rev, el.storey, _mesh(m),
                                   data={"kind": el.kind, "top_z": top, "bottom_z": top - t, "thickness": t,
                                         "area": area, "volume": m.volume(), "boundary": [list(p) for p in el.boundary]},
                                   params=rec, material=el.material, input_hash=key[1], name=el.name)

    # ---- spaces
    for eid, el in E.items():
        if not isinstance(el, Space) or eid in skip:
            continue
        rec = {}
        h = res.val(el, "height", rec)
        z0 = storey_z(el.storey)
        key = (eid, _h([el.model_dump(mode="json"), z0]))
        m = cached(key, lambda el=el, h=h, z0=z0: _prism(el.boundary, z0, h))
        area = abs(G.signed_area(el.boundary))
        els[eid] = CompiledElement(eid, "space", "IfcSpace", el.rev, el.storey, _mesh(m),
                                   data={"area": area, "height": h, "volume": m.volume(), "base_z": z0,
                                         "boundary": [list(p) for p in el.boundary], "usage": el.usage},
                                   params=rec, input_hash=key[1], name=el.name)
        for wid in el.bounded_by:
            if wid in solids:
                x = m ^ solids[wid]
                ov = x.volume()
                if ov > 1e-9:
                    d = _depth(x)
                    if d <= g.project.tolerances.overlap:
                        issues.add("OVERLAP_WITHIN_TOLERANCE", "info", f"{eid} and wall {wid} interpenetrate {d * 1000:.2f} mm",
                                   (eid, wid), layer="compile")
                    else:
                        issues.add("SPACE_WALL_OVERLAP", "error", f"{eid} overlaps wall {wid} by {ov:.6f} m3 (depth {d * 1000:.1f} mm)",
                                   (eid, wid), layer="compile")

    # ---- components (G3/G4)
    _compile_components(g, E, skip, res, els, solids, frames, plans, roof_data, roof_mass, chimneys, issues, storey_z)

    # ---- post-condition checks
    for eid, ce in els.items():
        sol = solids.get(eid)
        if sol is not None and (sol.status() != mf.Error.NoError or sol.is_empty() or sol.volume() <= 0):
            issues.add("SOLID_INVALID", "error", f"{eid}: solid invalid or empty", (eid,), layer="compile")
    if check_overlaps:
        _overlap_check(solids, els, issues, g.project.tolerances.overlap)

    relations = _relations(g, els)
    model = CompiledModel(g.revision.number, COMPILER_VERSION, profile, dict(sorted(els.items())), relations,
                          issues, unsupported, sorted(set(rebuilt)), sorted(set(reused) - set(rebuilt)))
    model._solids = solids
    model.model_hash = model_hash(model)
    return model


def _compile_components(g, E, skip, res, els, solids, frames, plans, roof_data, roof_mass, chimneys, issues, storey_z):
    from shapely.geometry import Polygon as SP

    slabs_by_storey: dict[str, list] = {}
    for el in E.values():
        if isinstance(el, Slab) and el.kind in ("floor", "base"):
            slabs_by_storey.setdefault(el.storey, []).append(el.boundary)
    all_slabs = [b for v in slabs_by_storey.values() for b in v]
    cents = {}
    for wid, f in frames.items():
        cents.setdefault(E[wid].storey, []).append(G.add(f.start, G.mul(f.d, f.length / 2)))
    ext_sign = {}

    def esign(wid):
        if wid not in ext_sign:
            f = frames[wid]
            st = E[wid].storey
            c = tuple(np.mean(cents[st], axis=0))
            ext_sign[wid] = C.exterior_sign(f, slabs_by_storey.get(st) or all_slabs, c)
        return ext_sign[wid]

    def wall_top_at(wid, p):
        wd = els[wid].data
        if wd["top_z"] is not None:
            return wd["top_z"]
        return min(pl.z(p) for pl in roof_data[wd["attached_roof"]])

    def finish_hex(el):
        fid = (el.info.finish if el.info else None) or (g.families[el.family].info.finish if el.family and el.family in g.families else None)
        return g.finishes[fid].hex if fid and fid in g.finishes else None

    for eid, el in E.items():
        if not isinstance(el, Component) or eid in skip:
            continue
        rec, data = {}, {"kind": el.kind, "placement": el.placement.on, "phase": el.phase}
        pl = el.placement
        cls, pdt = C.ifc_class_for(el)
        data["predefined_type"] = pdt
        data["color"] = finish_hex(el)
        solid, msg = None, None
        try:
            if el.kind == "cladding":
                exp = el.properties.get("exposure")
                data["exposure"] = exp.value if exp else None
                if exp:
                    rec["properties.exposure"] = res._prov(exp)
                data["hosts"] = list(el.hosts)
                area = 0.0
                for h in el.hosts:
                    if h in els:
                        wd = els[h].data
                        top = wd["top_z"] if wd["top_z"] is not None else max(
                            wall_top_at(h, p) for p in (wd["baseline"][0], wd["baseline"][1]))
                        area += wd["length"] * (top - wd["base_z"])
                data["approx_area"] = area
            elif el.geometry == "none" or pl.on == "space":
                if pl.on == "space":
                    data.update({"space": pl.space, "wall": pl.wall, "location": pl.location})
            elif el.kind == "chimney" and pl.on == "point":
                solid, rec0, d0 = chimneys[eid]
                rec.update(rec0)
                data.update(d0)
                data["cuts_roofs"] = sorted(r for r, ce in els.items() if ce.type == "roof" and eid in ce.data.get("cut_by", []))
            elif el.geometry == "prism":
                if not el.outline or len(el.outline) < 3 or pl.on != "point":
                    raise ValueError("prism geometry needs an outline and a point placement (for its base height)")
                h = C.size_value(g, el, "h", rec, res)
                z0 = storey_z(el.storey) + C.pval(pl.z, rec, "placement.z", res)
                solid = C.plan_prism([tuple(p) for p in el.outline], z0, z0 + h)
                data.update({"outline": [list(p) for p in el.outline], "base_z": z0, "top_z": z0 + h})
            elif pl.on == "point":
                w = C.size_value(g, el, "w", rec, res)
                d = C.size_value(g, el, "d", rec, res)
                h = C.size_value(g, el, "h", rec, res)
                z0 = storey_z(el.storey) + C.pval(pl.z, rec, "placement.z", res)
                solid = C.oriented_box(pl.at[0], pl.at[1], w, d, z0, h, pl.rotation)
                data.update({"at": list(pl.at), "base_z": z0, "top_z": z0 + h})
            elif pl.on == "wall":
                if pl.wall not in frames or pl.wall not in els:
                    raise ValueError(f"host wall {pl.wall} not built")
                f = frames[pl.wall]
                sg = C.side_sign(pl.side, esign(pl.wall))
                w = C.size_value(g, el, "w", rec, res)
                h = C.size_value(g, el, "h", rec, res)
                d = C.size_value(g, el, "d", rec, res)
                u = C.pval(pl.u, rec, "placement.u", res)
                z0 = els[pl.wall].data["base_z"] + C.pval(pl.z, rec, "placement.z", res)
                v0, v1 = C.face_band(f, sg, 0.0, d)
                solid = C.local_box(f, u - w / 2, u + w / 2, v0, v1, z0, z0 + h)
                if el.kind in ("trim", "post"):  # trim and posts stop under eaves / soffits
                    hit = [r for r in sorted(roof_data) if r in solids and not (solid ^ solids[r]).is_empty()]
                    for r in hit:
                        solid = solid - solids[r]
                    if hit:
                        data["stopped_under"] = hit
                data.update({"host": pl.wall, "side": "left" if sg > 0 else "right", "base_z": z0, "top_z": z0 + h})
            elif pl.on == "opening":
                od = els[pl.opening].data
                wid = od["host"]
                f = frames[wid]
                sg = C.side_sign(pl.side, esign(wid))
                off, wo, sz, hz = od["offset"], od["width"], od["sill_z"], od["head_z"]
                gap = C.pval(pl.gap, rec, "placement.gap", res) if pl.gap is not None else 0.0
                boxes = []
                if el.kind == "trim":
                    cw = C.size_value(g, el, "w", rec, res)
                    t = C.size_value(g, el, "d", rec, res)
                    v0, v1 = C.face_band(f, sg, 0.0, t)
                    is_win = od["kind"] == "window"
                    if pl.position in ("surround",):
                        boxes += [C.local_box(f, off - gap - cw, off - gap, v0, v1, sz, hz + gap + cw),
                                  C.local_box(f, off + wo + gap, off + wo + gap + cw, v0, v1, sz, hz + gap + cw)]
                    if pl.position in ("surround", "head"):
                        boxes.append(C.local_box(f, off - gap - cw, off + wo + gap + cw, v0, v1, hz + gap, hz + gap + cw))
                    if (pl.position == "surround" and is_win) or pl.position == "sill":
                        sv0, sv1 = C.face_band(f, sg, 0.0, 2 * t)
                        boxes.append(C.local_box(f, off - gap - cw - t, off + wo + gap + cw + t, sv0, sv1, sz - 1.5 * C.IN, sz))
                else:  # shutters, vents beside an opening
                    sw = C.size_value(g, el, "w", rec, res)
                    sh = el.size.h.value if (el.size.h and el.size.h.value is not None) else None
                    if sh is None:
                        sh = hz - sz
                        rec["size.h"] = {"value": sh, "basis": "inferred", "from": f"opening {pl.opening} height", "derived": True}
                    else:
                        C.size_value(g, el, "h", rec, res)
                    t = C.size_value(g, el, "d", rec, res)
                    v0, v1 = C.face_band(f, sg, 0.0, t)
                    zc = (sz + hz) / 2
                    if pl.position in ("start", "both"):
                        boxes.append(C.local_box(f, off - gap - sw, off - gap, v0, v1, zc - sh / 2, zc + sh / 2))
                    if pl.position in ("end", "both"):
                        boxes.append(C.local_box(f, off + wo + gap, off + wo + gap + sw, v0, v1, zc - sh / 2, zc + sh / 2))
                solid = mf.Manifold.batch_boolean(boxes, mf.OpType.Add) if len(boxes) > 1 else boxes[0]
                hit = [r for r in sorted(roof_data) if r in solids and not (solid ^ solids[r]).is_empty()]
                for r in hit:  # casings and shutters stop under eaves / roofs below them
                    solid = solid - solids[r]
                if hit:
                    data["stopped_under"] = hit
                data.update({"host": wid, "opening": pl.opening, "position": pl.position, "pieces": len(boxes),
                             "side": "left" if sg > 0 else "right"})
            elif pl.on == "corner":
                a, b = pl.walls
                fa, fb = frames[a], frames[b]
                sa, sb = C.side_sign(pl.sides[0], esign(a)), C.side_sign(pl.sides[1], esign(b))
                la = G.add(fa.start, G.mul(fa.n, fa.off_left if sa > 0 else fa.off_right))
                lb = G.add(fb.start, G.mul(fb.n, fb.off_left if sb > 0 else fb.off_right))
                P = G.line_intersection(la, fa.d, lb, fb.d)
                if P is None:
                    raise ValueError("corner walls are parallel")
                w = C.size_value(g, el, "w", rec, res)
                t = C.size_value(g, el, "d", rec, res)
                z0 = min(els[a].data["base_z"], els[b].data["base_z"])
                hv = el.size.h if el.size.h and el.size.h.value is not None else None
                z1 = z0 + C.size_value(g, el, "h", rec, res) if hv else min(wall_top_at(a, P), wall_top_at(b, P))
                if not hv:
                    rec["size.h"] = {"value": z1 - z0, "basis": "inferred", "from": "lower of the two wall tops at the corner", "derived": True}
                pieces = []
                oa, ob = G.mul(fa.n, float(sa)), G.mul(fb.n, float(sb))
                pa, pb = SP(plans[a].polygon), SP(plans[b].polygon)
                from shapely.geometry import LineString as _LS
                from shapely.geometry import Point as _Pt

                def _runs(fr, o_self, poly_self, poly_other):
                    """Directions along the wall from the corner whose face is exterior: the wall's own body is
                    behind the face there and the other wall's body is not in front of it."""
                    ok = []
                    for sgn in (1.0, -1.0):
                        dd = G.mul(fr.d, sgn)
                        inside = G.add(G.add(P, G.mul(dd, 0.3)), G.mul(o_self, -0.01))
                        strip = _LS([G.add(G.add(P, G.mul(dd, 0.005)), G.mul(o_self, 0.01)), G.add(G.add(P, G.mul(dd, 0.3)), G.mul(o_self, 0.01))])
                        if poly_self.contains(_Pt(inside)) and not poly_other.buffer(-1e-6).intersects(strip):
                            ok.append(sgn)
                    return ok

                ra, rb = _runs(fa, oa, pa, pb), _runs(fb, ob, pb, pa)
                if len(ra) != 1 or len(rb) != 1:
                    raise ValueError("cannot tell which way the corner boards run (walls do not form a single corner)")
                concave = G.dot(G.mul(fa.d, ra[0]), ob) > 0
                for (fr, sg_, other) in ((fa, sa, fb), (fb, sb, fa)):
                    ta = ra[0] if fr is fa else rb[0]
                    o = G.mul(fr.n, float(sg_))
                    ext = t if (fr is fa and not concave) else 0.0
                    p0 = G.add(P, G.mul(fr.d, -ta * ext))
                    p1 = G.add(P, G.mul(fr.d, ta * w))
                    pieces.append(C.plan_prism([p0, p1, G.add(p1, G.mul(o, t)), G.add(p0, G.mul(o, t))], z0, z1))
                solid = mf.Manifold.batch_boolean(pieces, mf.OpType.Add)
                for rid in sorted(r for r in roof_data if r in solids):  # stop under eaves / soffits
                    solid = solid - solids[rid]
                data.update({"corner": [P[0], P[1]], "walls": [a, b], "base_z": z0, "top_z": z1, "inside_corner": bool(concave)})
            elif pl.on == "roof_edge":
                if pl.roof not in els:
                    raise ValueError(f"roof {pl.roof} not built")
                rel = E[pl.roof]
                size = {}
                for k in ("w", "h", "d"):
                    val = C.size_value(g, el, k, rec, res)
                    size[k] = val
                gap = C.pval(pl.gap, rec, "placement.gap", res) if pl.gap is not None else 0.0
                parts = C.roof_edge_solids(el.kind, rel, els[pl.roof].data, roof_data[pl.roof], pl.edges, size, gap,
                                           els[pl.roof].data["slope"])
                if not parts:
                    raise ValueError("no buildable edges (abut edges carry no trim)")
                solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add) if len(parts) > 1 else parts[0]
                if pl.within:
                    bb = solid.bounding_box()
                    solid = solid ^ _prism([tuple(p) for p in pl.within], bb[2] - 1.0, bb[5] - bb[2] + 2.0)
                    data["within"] = [list(p) for p in pl.within]
                # members stop where the edge runs into roofs that meet this one (valleys) and into walls/slabs
                # (an eave that is flush against a taller block); what is removed is recorded
                cut = sorted({o for o in rel.trim_by if o in roof_mass} |
                             {r for r, rr in E.items() if isinstance(rr, Roof) and pl.roof in rr.trim_by and r in roof_mass})
                for o in cut:
                    m_o = roof_mass[o]
                    own = [roof_mass[t] for t in E[o].trim_by if t in roof_mass]
                    if own:  # the meeting roof's own valleys: it does not exist where it was trimmed away
                        m_o = m_o - (mf.Manifold.batch_boolean(own, mf.OpType.Add) if len(own) > 1 else own[0])
                    solid = solid - m_o
                clipped = []
                sb = solid.bounding_box()
                for k in sorted(solids):
                    if els[k].type in ("wall", "slab") and not solid.is_empty():
                        kb = solids[k].bounding_box()
                        if any(sb[j] >= kb[j + 3] - 1e-9 or kb[j] >= sb[j + 3] - 1e-9 for j in range(3)):
                            continue
                        if (solid ^ solids[k]).volume() > 1e-9:
                            solid = solid - solids[k]
                            clipped.append(k)
                data.update({"roof": pl.roof, "edges": list(pl.edges), "trimmed_by": cut, "clipped_by": clipped})
        except (ValueError, KeyError) as ex:
            msg = str(ex)
        if msg:
            issues.add("COMPONENT_NOT_PLACED", "warning", f"{eid}: {msg}; kept as information only", (eid,), layer="compile")
            data["not_placed"] = msg
            solid = None
        if solid is not None:
            if solid.is_empty() or solid.volume() <= 1e-12:
                issues.add("COMPONENT_EMPTY", "warning", f"{eid}: geometry empty after trimming; kept as information only", (eid,), layer="compile")
                solid = None
            else:
                solids[eid] = solid
                data["volume"] = solid.volume()
                bb = solid.bounding_box()
                data["bbox"] = [list(bb[:3]), list(bb[3:])]
        els[eid] = CompiledElement(eid, "component", cls, el.rev, el.storey, _mesh(solid) if solid is not None else None,
                                   data=data, params=rec, material=el.material,
                                   input_hash=_h(el.model_dump(mode="json")), name=el.name)
    _component_clearance(els, solids, issues, g.project.tolerances.overlap)


def _component_clearance(els, solids, issues, tol):
    """Components must sit outside walls/roofs/slabs (beyond the overlap tolerance) — chimneys excepted (they cut roofs)."""
    hosts = sorted(k for k in solids if els[k].type in ("wall", "roof", "slab"))
    hb = {k: solids[k].bounding_box() for k in hosts}
    for cid in sorted(k for k in solids if els[k].type == "component"):
        cb = solids[cid].bounding_box()
        for h in hosts:
            B = hb[h]
            if any(cb[j] >= B[j + 3] - 1e-9 or B[j] >= cb[j + 3] - 1e-9 for j in range(3)):
                continue
            x = solids[cid] ^ solids[h]
            if x.volume() > 1e-9 and _depth(x) > tol:
                issues.add("COMPONENT_INTERSECTS", "warning",
                           f"{cid} ({els[cid].data['kind']}) intersects {h} by {_depth(x) * 1000:.1f} mm", (cid, h), layer="compile")


def _depth(m: mf.Manifold) -> float:
    b = m.bounding_box()
    return min(b[3] - b[0], b[4] - b[1], b[5] - b[2])


def _overlap_check(solids, els, issues: IssueList, tol: float):
    ids = sorted(k for k in solids if els[k].type in ("wall", "slab", "roof", "filling"))
    bbs = {k: solids[k].bounding_box() for k in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            A, B = bbs[a], bbs[b]
            if any(A[j] >= B[j + 3] - 1e-9 or B[j] >= A[j + 3] - 1e-9 for j in range(3)):
                continue
            x = solids[a] ^ solids[b]
            v = x.volume()
            if v > 1e-9:
                ta, tb = els[a].type, els[b].type
                d = _depth(x)
                if d <= tol:
                    issues.add("OVERLAP_WITHIN_TOLERANCE", "info", f"{a} and {b} interpenetrate {d * 1000:.2f} mm "
                               f"(≤ overlap tolerance {tol * 1000:.1f} mm)", (a, b), layer="compile")
                    continue
                code = "WALL_OVERLAP" if ta == tb == "wall" else "ELEMENT_OVERLAP"
                issues.add(code, "error", f"{a} and {b} overlap by {v:.6f} m3 (depth {d * 1000:.1f} mm)", (a, b), layer="compile")


def _relations(g: Genome, els) -> dict:
    rel = {"voids": [], "fills": [], "contained_in_storey": {}, "wall_junctions": [], "roof_attachment": [], "space_bounds": []}
    for eid, ce in els.items():
        if ce.type == "opening":
            rel["voids"].append([ce.data["host"], eid])
        if ce.type == "filling":
            rel["fills"].append([ce.data["opening"], eid])
        if ce.storey and ce.type != "opening":
            rel["contained_in_storey"].setdefault(ce.storey, []).append(eid)
        if ce.type == "wall":
            for end in ("start", "end"):
                j = ce.data["junctions"][end]
                for o in j["others"]:
                    rel["wall_junctions"].append([eid, end, j["kind"], o])
            if ce.data["attached_roof"]:
                rel["roof_attachment"].append([eid, ce.data["attached_roof"]])
    for eid, el in sorted(g.elements.items()):
        if isinstance(el, Space) and eid in els:
            for w in el.bounded_by:
                rel["space_bounds"].append([eid, w])
    return rel


def model_hash(model: CompiledModel) -> str:
    h = hashlib.sha256(model.compiler_version.encode())
    for eid, ce in sorted(model.elements.items()):
        h.update(eid.encode())
        if ce.mesh is not None and len(ce.mesh.tris):
            # hash order-independent geometry: sorted, rounded vertex triples per triangle
            tri = np.round(ce.mesh.verts[ce.mesh.tris], 6) + 0.0
            tri = np.sort(tri.reshape(len(tri), -1).view([("", tri.dtype)] * 9).ravel())
            h.update(tri.tobytes())
    return h.hexdigest()
