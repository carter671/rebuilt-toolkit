"""Layered Genome validation: schema (in io.parse) -> references -> units/coords -> architecture -> profile."""
from __future__ import annotations

from ..geom2d import is_convex, is_simple, length, signed_area, sub
from ..issues import IssueList
from .profiles import PROFILES
from .schema import Component, Genome, Opening, Roof, Slab, Space, StoreyRef, Value, Wall

GEOM_PARAMS = {
    "wall": ["thickness", "height", "base_offset"],
    "opening": ["offset", "width", "height", "sill"],
    "slab": ["thickness", "top_offset"],
    "roof": ["pitch", "plate_height", "overhang", "rake_overhang", "thickness"],
    "space": ["height"],
    "component": ["size.w", "size.h", "size.d", "placement.u", "placement.z", "placement.gap"],
}
SIGNED = {"placement.u", "placement.z", "base_offset", "top_offset"}  # may be negative


def get_param(el, p):
    """Dotted parameter access: 'size.w', 'placement.z', 'properties.exposure'."""
    cur = el
    for part in p.split("."):
        if cur is None:
            return None
        cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None)
    return cur


def values_of(el):
    """Yield (param_name, Value) for an element's provenance-carrying parameters (incl. properties.*)."""
    for p in GEOM_PARAMS[el.type]:
        v = get_param(el, p)
        if isinstance(v, Value):
            yield p, v
    for k, v in sorted(el.properties.items()):
        yield f"properties.{k}", v


def v(val: Value | None, default: float | None = None) -> float | None:
    if val is None:
        return default
    return val.value if val.value is not None else default


def check_references(g: Genome, issues: IssueList):
    storey_ids = {s.id for s in g.storeys()}
    seen = set()
    for s in g.storeys():
        if s.id in seen:
            issues.add("DUPLICATE_ID", "error", f"duplicate storey id {s.id}", (s.id,), layer="reference")
        seen.add(s.id)
    for eid in g.elements:
        if eid in storey_ids:
            issues.add("DUPLICATE_ID", "error", f"element id {eid} collides with a storey id", (eid,), layer="reference")
    for eid, el in sorted(g.elements.items()):
        if hasattr(el, "storey") and el.storey not in storey_ids:
            issues.add("REF_MISSING_STOREY", "error", f"{eid}: storey '{el.storey}' not found", (eid,), layer="reference")
        if el.material and el.material not in g.materials:
            issues.add("REF_MISSING_MATERIAL", "error", f"{eid}: material '{el.material}' not found", (eid,), layer="reference")
        if isinstance(el, Opening):
            host = g.elements.get(el.host)
            if host is None:
                issues.add("REF_MISSING_HOST", "error", f"{eid}: host '{el.host}' not found", (eid,), layer="reference")
            elif not isinstance(host, Wall):
                issues.add("REF_HOST_NOT_WALL", "error", f"{eid}: host '{el.host}' is a {host.type}", (eid,), layer="reference")
            if el.filling and el.filling.material and el.filling.material not in g.materials:
                issues.add("REF_MISSING_MATERIAL", "error", f"{eid}: filling material not found", (eid,), layer="reference")
        if isinstance(el, Wall) and el.top:
            r = g.elements.get(el.top.attach)
            if not isinstance(r, Roof):
                issues.add("REF_MISSING_ROOF", "error", f"{eid}: top.attach '{el.top.attach}' is not a roof", (eid,), layer="reference")
        if isinstance(el, Roof):
            for r in el.trim_by:
                if not isinstance(g.elements.get(r), Roof) or r == eid:
                    issues.add("REF_TRIM_NOT_ROOF", "error", f"{eid}: trim_by '{r}' is not another roof", (eid,), layer="reference")
        if isinstance(el, Space):
            for w in el.bounded_by:
                if not isinstance(g.elements.get(w), Wall):
                    issues.add("REF_MISSING_BOUND", "error", f"{eid}: bounded_by '{w}' is not a wall", (eid,), layer="reference")
        if el.info:
            if el.info.finish and el.info.finish not in g.finishes:
                issues.add("REF_MISSING_FINISH", "error", f"{eid}: finish '{el.info.finish}' not found", (eid,), layer="reference")
            if el.info.observed:
                for ph in el.info.observed.photos:
                    if ph not in g.sources:
                        issues.add("REF_MISSING_SOURCE", "error", f"{eid}: photo source '{ph}' not found", (eid,), layer="reference")
                ob = el.info.observed.observation
                if ob and ob not in g.observations:
                    issues.add("REF_MISSING_OBSERVATION", "error", f"{eid}: info observation '{ob}' not found", (eid,), layer="reference")
        if el.family and el.family not in g.families:
            issues.add("REF_MISSING_FAMILY", "error", f"{eid}: family '{el.family}' not found", (eid,), layer="reference")
        if isinstance(el, Opening) and el.unit and el.unit.sash_finish and el.unit.sash_finish not in g.finishes:
            issues.add("REF_MISSING_FINISH", "error", f"{eid}: sash finish '{el.unit.sash_finish}' not found", (eid,), layer="reference")
        if isinstance(el, Space):
            for k, inf in el.surfaces.items():
                if inf.finish and inf.finish not in g.finishes:
                    issues.add("REF_MISSING_FINISH", "error", f"{eid}.surfaces.{k}: finish '{inf.finish}' not found", (eid,), layer="reference")
        if isinstance(el, Component):
            _check_component_refs(g, eid, el, issues)
        for _, val in values_of(el):
            for o in val.observations:
                if o not in g.observations:
                    issues.add("REF_MISSING_OBSERVATION", "error", f"{eid}: observation '{o}' not found", (eid,), layer="reference")
    for oid, ob in sorted(g.observations.items()):
        if ob.source and ob.source not in g.sources:
            issues.add("REF_MISSING_SOURCE", "error", f"observation {oid}: source '{ob.source}' not found", layer="reference")
        if ob.subject and ob.subject not in g.elements:
            issues.add("REF_MISSING_SUBJECT", "warning", f"observation {oid}: subject '{ob.subject}' not found", layer="reference")
    for ns in g.extensions:
        if ns not in g.project.extensions_declared:
            issues.add("EXTENSION_UNDECLARED", "error", f"extension namespace '{ns}' is not declared", layer="schema")


def _check_component_refs(g: Genome, eid: str, el: Component, issues: IssueList):
    pl = el.placement

    def need(ref, cls, what):
        if not isinstance(g.elements.get(ref), cls):
            issues.add("REF_PLACEMENT", "error", f"{eid}: placement {what} '{ref}' is not a {cls.__name__.lower()}", (eid,), layer="reference")
            return None
        return g.elements[ref]

    if pl.on == "wall":
        need(pl.wall, Wall, "wall")
    elif pl.on == "opening":
        need(pl.opening, Opening, "opening")
    elif pl.on == "corner":
        a, b = need(pl.walls[0], Wall, "wall"), need(pl.walls[1], Wall, "wall")
        if a is not None and b is not None and pl.walls[0] == pl.walls[1]:
            issues.add("REF_PLACEMENT", "error", f"{eid}: corner needs two different walls", (eid,), layer="reference")
    elif pl.on == "roof_edge":
        r = need(pl.roof, Roof, "roof")
        if r is not None:
            for i in pl.edges:
                if not 0 <= i < len(r.footprint):
                    issues.add("REF_PLACEMENT", "error", f"{eid}: roof edge {i} out of range for {pl.roof}", (eid,), layer="reference")
    elif pl.on == "space":
        need(pl.space, Space, "space")
        if pl.wall:
            need(pl.wall, Wall, "wall")
    for h in el.hosts:
        if not isinstance(g.elements.get(h), Wall):
            issues.add("REF_PLACEMENT", "error", f"{eid}: host '{h}' is not a wall", (eid,), layer="reference")
    if el.kind == "cladding" and not el.hosts:
        issues.add("CLADDING_NO_HOSTS", "warning", f"{eid}: cladding covers no walls", (eid,), layer="reference")


def check_units(g: Genome, issues: IssueList):
    for b in g.buildings:
        prev = None
        for s in b.storeys:
            if s.height.value is not None and s.height.value <= 0:
                issues.add("NONPOSITIVE", "error", f"storey {s.id} height must be > 0", (s.id,), layer="units")
            if prev and s.elevation.value is not None and prev.elevation.value is not None and s.elevation.value <= prev.elevation.value:
                issues.add("STOREY_ORDER", "error", f"storey {s.id} elevation not above {prev.id}", (s.id,), layer="units")
            prev = s
    nonneg = {"base_offset", "sill", "overhang", "rake_overhang", "offset", "top_offset"}
    for eid, el in sorted(g.elements.items()):
        for p, val in values_of(el):
            if val.value is None:
                if val.basis != "unknown":
                    issues.add("VALUE_NULL_NOT_UNKNOWN", "error", f"{eid}.{p}: null value requires basis 'unknown'", (eid,), layer="units")
                continue
            if val.basis == "unknown":
                issues.add("VALUE_UNKNOWN_WITH_NUMBER", "error", f"{eid}.{p}: basis 'unknown' must have null value", (eid,), layer="units")
            if p in SIGNED or p.startswith("properties."):
                pass
            elif p in nonneg or p == "placement.gap":
                if val.value < 0:
                    issues.add("NEGATIVE", "error", f"{eid}.{p} must be >= 0", (eid,), layer="units")
            elif val.value <= 0:
                issues.add("NONPOSITIVE", "error", f"{eid}.{p} must be > 0", (eid,), layer="units")
            if val.basis == "inferred" and val.confidence is None:
                issues.add("INFERENCE_NO_CONFIDENCE", "warning", f"{eid}.{p}: inferred value without confidence", (eid,), layer="units")
            if val.verification == "disputed" and len(val.conflicts) < 2:
                issues.add("DISPUTE_WITHOUT_CANDIDATES", "error", f"{eid}.{p}: disputed value needs >=2 conflict candidates", (eid,), layer="units")
        for name in ("boundary", "footprint"):
            poly = getattr(el, name, None)
            if poly is not None:
                if len(poly) < 3 or not is_simple(poly):
                    issues.add("POLYGON_NOT_SIMPLE", "error", f"{eid}.{name} is not a simple polygon", (eid,), layer="units")
                elif signed_area(poly) <= 0:
                    issues.add("POLYGON_NOT_CCW", "error", f"{eid}.{name} must be counter-clockwise", (eid,), layer="units")


def wall_height(g: Genome, w: Wall) -> float | None:
    if isinstance(w.height, StoreyRef):
        return v(g.storey(w.storey).height)
    return v(w.height)


def check_architecture(g: Genome, issues: IssueList):
    for eid, el in sorted(g.elements.items()):
        if isinstance(el, Wall):
            L = length(sub(el.end, el.start))
            t = v(el.thickness)
            if L < 1e-6:
                issues.add("WALL_ZERO_LENGTH", "error", f"{eid}: zero-length wall", (eid,), layer="architecture")
            elif t and L <= t:
                issues.add("WALL_SHORTER_THAN_THICK", "warning", f"{eid}: length {L:.3f} <= thickness", (eid,), layer="architecture")
            if el.shape != "straight":
                issues.add("UNSUPPORTED_WALL_SHAPE", "warning", f"{eid}: wall shape '{el.shape}' not supported by compiler", (eid,), layer="architecture")
        elif isinstance(el, Opening):
            host = g.elements.get(el.host)
            if not isinstance(host, Wall):
                continue
            L = length(sub(host.end, host.start))
            o, wd, h, s = v(el.offset), v(el.width), v(el.height), v(el.sill)
            if None in (o, wd):
                continue
            if o + wd > L + 1e-9:
                issues.add("OPENING_OUTSIDE_HOST", "error",
                           f"{eid}: offset+width {o + wd:.3f} exceeds host length {L:.3f}", (eid, el.host), layer="architecture")
            hh = None if host.top else wall_height(g, host)
            if hh is not None and None not in (h, s) and s + h > hh + 1e-9:
                issues.add("OPENING_ABOVE_HOST", "error",
                           f"{eid}: sill+height {s + h:.3f} exceeds host height {hh:.3f}", (eid, el.host), layer="architecture")
            if el.kind == "door" and s and s > 0.3:
                issues.add("DOOR_HIGH_SILL", "warning", f"{eid}: door with sill {s:.3f} m", (eid,), layer="architecture")
            if el.shape != "rectangle":
                issues.add("UNSUPPORTED_OPENING_SHAPE", "warning", f"{eid}: opening shape '{el.shape}' not supported", (eid,), layer="architecture")
        elif isinstance(el, Roof):
            n = len(el.footprint)
            if len(el.edge_roles) != n:
                issues.add("ROOF_EDGE_ROLES", "error", f"{eid}: edge_roles length {len(el.edge_roles)} != footprint edges {n}", (eid,), layer="architecture")
            elif not ({"eave", "flush-eave"} & set(el.edge_roles)):
                issues.add("ROOF_NO_EAVE", "error", f"{eid}: roof needs at least one eave edge", (eid,), layer="architecture")
            if not is_convex(el.footprint):
                issues.add("UNSUPPORTED_ROOF_NONCONVEX", "warning",
                           f"{eid}: non-convex roof footprint requires the M3 straight-skeleton solver", (eid,), layer="architecture")
            if el.form == "planes":
                issues.add("UNSUPPORTED_ROOF_FORM", "warning", f"{eid}: roof form 'planes' not supported yet", (eid,), layer="architecture")
    # spaces on the same storey must not overlap
    spaces = [e for _, e in sorted(g.elements.items()) if isinstance(e, Space)]
    for i, a in enumerate(spaces):
        for b in spaces[i + 1:]:
            if a.storey == b.storey and is_simple(a.boundary) and is_simple(b.boundary):
                from ..geom2d import polygons_overlap_area

                if polygons_overlap_area(a.boundary, b.boundary) > 1e-6:
                    issues.add("SPACE_OVERLAP", "error", f"spaces {a.id} and {b.id} overlap", (a.id, b.id), layer="architecture")


def check_profile(g: Genome, profile: str, issues: IssueList):
    prof = PROFILES[profile]
    for eid, el in sorted(g.elements.items()):
        for p, val in values_of(el):
            if val.basis == "unknown" and (el.type == "component" or p.startswith("properties.")):
                if not prof.allow_unknown:
                    issues.add("PROFILE_UNKNOWN", "error", f"{eid}.{p} is unknown (profile {profile})", (eid,), layer="profile")
                continue  # component sizes fall back to family / kind defaults (reported by the compiler)
            if val.basis == "unknown":
                if not prof.allow_unknown:
                    issues.add("PROFILE_UNKNOWN", "error", f"{eid}.{p} is unknown (profile {profile})", (eid,), layer="profile")
                elif (el.type, p) not in prof.defaults:
                    issues.add("PROFILE_NO_DEFAULT", "error", f"{eid}.{p} is unknown and has no profile default", (eid,), layer="profile")
                else:
                    issues.add("PROFILE_DEFAULTED", "warning",
                               f"{eid}.{p} unknown; profile default {prof.defaults[(el.type, p)]} used (assumed)", (eid,), layer="profile")
            if val.verification == "disputed" and not prof.allow_disputed:
                issues.add("PROFILE_DISPUTED", "error", f"{eid}.{p} is disputed (profile {profile})", (eid,), layer="profile")
            if prof.require_verified and val.verification != "verified":
                issues.add("PROFILE_UNVERIFIED", "error", f"{eid}.{p} is not verified", (eid,), layer="profile")
        if prof.require_material and el.type in ("wall", "slab", "roof") and not el.material:
            issues.add("PROFILE_NO_MATERIAL", "error", f"{eid} has no material (profile {profile})", (eid,), layer="profile")


def validate(g: Genome, profile: str = "review") -> IssueList:
    issues = IssueList()
    check_references(g, issues)
    check_units(g, issues)
    if not issues.errors:
        check_architecture(g, issues)
    check_profile(g, profile, issues)
    return issues
