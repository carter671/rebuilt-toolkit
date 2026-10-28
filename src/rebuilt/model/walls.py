"""Wall junction resolution: L (mitred), T (butted), collinear (square), free ends.

Works purely on Genome baselines in 2D. Output per wall: plan polygon (CCW) plus a junction record.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import geom2d as G
from ..issues import IssueList


@dataclass
class WallFrame:
    id: str
    storey: str
    start: tuple
    end: tuple
    d: tuple  # unit direction start->end
    n: tuple  # left normal
    length: float
    off_left: float  # offset of left face from baseline along n
    off_right: float  # offset of right face (negative = right side)

    def face_line(self, side: str):
        off = self.off_left if side == "L" else self.off_right
        return G.add(self.start, G.mul(self.n, off)), self.d

    def u(self, p) -> float:
        return G.dot(G.sub(p, self.start), self.d)

    def v(self, p) -> float:
        return G.dot(G.sub(p, self.start), self.n)


@dataclass
class Junction:
    kind: str  # "L", "T", "collinear", "free", "multi"
    others: list[str] = field(default_factory=list)


@dataclass
class WallPlan:
    frame: WallFrame
    polygon: list  # CCW: [S_R, E_R, E_L, S_L]
    start_junction: Junction
    end_junction: Junction
    butted_by: list = field(default_factory=list)  # [(wall_id, side 'L'|'R', u0, u1)] walls T-ing into this one
    ends: dict = field(default_factory=dict)  # {"S": {"L": pt, "R": pt}, "E": {...}}


def make_frame(wid, storey, start, end, thickness, alignment) -> WallFrame:
    d = G.unit(G.sub(end, start))
    n = G.left_normal(d)
    if alignment == "center":
        ol, orr = thickness / 2, -thickness / 2
    elif alignment == "left":  # baseline is the left face; body to the right
        ol, orr = 0.0, -thickness
    else:  # baseline is the right face; body to the left
        ol, orr = thickness, 0.0
    return WallFrame(wid, storey, tuple(start), tuple(end), d, n, G.length(G.sub(end, start)), ol, orr)


def _away_sides(f: WallFrame, at_start: bool):
    """Face sides named relative to the direction pointing away from the node."""
    return ("L", "R") if at_start else ("R", "L")  # (left-of-away, right-of-away)


def resolve(frames: dict[str, WallFrame], tol: float, issues: IssueList, priority: dict | None = None) -> dict[str, WallPlan]:
    """priority: wall id -> sortable key; higher wins material at multi-way junctions."""
    ids = sorted(frames)
    ends = {}  # (wid, is_start) -> point
    for w in ids:
        ends[(w, True)] = frames[w].start
        ends[(w, False)] = frames[w].end

    # endpoint points for each (wall, end): dict side -> point on that face line
    pts = {}
    junc = {}
    butted = {w: [] for w in ids}
    multi_nodes: dict[tuple, dict] = {}
    multi_ends: list = []

    for (w, is_start), p in sorted(ends.items()):
        f = frames[w]
        same = [k for k, q in ends.items() if k[0] != w and frames[k[0]].storey == f.storey and G.length(G.sub(p, q)) <= tol]
        tees = []
        for o in ids:
            if o == w or frames[o].storey != f.storey or any(k[0] == o for k in same):
                continue
            t, perp = G.point_segment_param(p, frames[o].start, frames[o].end)
            if perp <= tol and tol < t < frames[o].length - tol:
                tees.append(o)
        away = f.d if is_start else G.mul(f.d, -1)
        la, ra = _away_sides(f, is_start)
        res = {}
        if not same and not tees:
            junc[(w, is_start)] = Junction("free")
        elif len(same) == 1 and not tees:
            o, o_start = same[0]
            g = frames[o]
            o_away = g.d if o_start else G.mul(g.d, -1)
            ola, ora = _away_sides(g, o_start)
            if abs(G.cross(away, o_away)) < 1e-9:
                junc[(w, is_start)] = Junction("collinear", [o])
            else:
                # region ccw from A to B is bounded by A's left-of-away and B's right-of-away
                pA, dA = f.face_line(la)
                pB, dB = g.face_line(ora)
                res[la] = G.line_intersection(pA, dA, pB, dB)
                pA, dA = f.face_line(ra)
                pB, dB = g.face_line(ola)
                res[ra] = G.line_intersection(pA, dA, pB, dB)
                junc[(w, is_start)] = Junction("L", [o])
                for side in (la, ra):
                    if G.length(G.sub(res[side], p)) > 4 * max(abs(f.off_left - f.off_right), 1e-3):
                        issues.add("JUNCTION_ACUTE", "warning", f"{w}: very acute junction with {o}", (w, o), layer="compile")
        elif len(tees) == 1 and not same:
            o = tees[0]
            g = frames[o]
            side = "L" if G.cross(g.d, away) > 0 else "R"
            qB, dB = g.face_line(side)
            for s in (la, ra):
                pA, dA = f.face_line(s)
                res[s] = G.line_intersection(pA, dA, qB, dB)
            if res[la] is None or res[ra] is None:      # runs along the other wall instead of into it
                issues.add("JUNCTION_PARALLEL", "warning", f"{w}: ends on {o} but runs parallel to it; left square", (w, o), layer="compile")
                junc[(w, is_start)] = Junction("free")
                res = {}
            else:
                junc[(w, is_start)] = Junction("T", [o])
                us = sorted([g.u(res[la]), g.u(res[ra])])
                butted[o].append((w, side, us[0], us[1]))
        else:
            others = sorted({k[0] for k in same} | set(tees))
            junc[(w, is_start)] = Junction("multi", others)
            # square end at the node; a stub reaching past the node is added later, but only where it lies
            # inside a non-collinear neighbour (fills the corner, never sticks out); overlaps are then removed
            # by priority-ordered 2D subtraction (exact for vertical prisms)
            node = multi_nodes.setdefault((round(p[0], 6), round(p[1], 6), f.storey), {"end": set(), "through": set()})
            node["end"].add(w)
            node["end"].update(k[0] for k in same)
            node["through"].update(tees)
            multi_ends.append((w, is_start, others))
        for s in ("L", "R"):
            if s not in res:
                pl, _ = f.face_line(s)
                res[s] = G.add(pl, G.mul(f.d, f.length if not is_start else 0.0))
        pts[(w, is_start)] = res

    plans = {}
    for w in ids:
        s, e = pts[(w, True)], pts[(w, False)]
        poly = [s["R"], e["R"], e["L"], s["L"]]
        if G.signed_area(poly) < 0:
            poly = list(reversed(poly))
        if not G.is_simple(poly):
            issues.add("WALL_PLAN_INVALID", "error", f"{w}: resolved plan polygon self-intersects", (w,), layer="compile")
        plans[w] = WallPlan(frames[w], poly, junc[(w, True)], junc[(w, False)], sorted(butted[w]), {"S": s, "E": e})

    if multi_nodes:
        from shapely.geometry import Polygon

        from shapely.ops import unary_union

        pr = priority or {}
        orig = {w: Polygon(plans[w].polygon) for w in ids}
        for w, is_start, others in multi_ends:
            f = frames[w]
            nb = [orig[o] for o in others if abs(G.cross(f.d, frames[o].d)) > 1e-6]
            if not nb:
                continue
            ext = max(abs(frames[o].off_left - frames[o].off_right) for o in others)
            u0 = 0.0 if is_start else f.length
            u1 = u0 - ext if is_start else u0 + ext
            q = lambda u, off: G.add(G.add(f.start, G.mul(f.d, u)), G.mul(f.n, off))  # noqa: E731
            stub = Polygon([q(u0, f.off_right), q(u1, f.off_right), q(u1, f.off_left), q(u0, f.off_left)])
            add = stub.intersection(unary_union(nb))
            if add.area > 1e-12:
                merged = Polygon(plans[w].polygon).union(add)
                if merged.geom_type == "Polygon":
                    plans[w].polygon = G.ensure_ccw([tuple(c) for c in list(merged.simplify(1e-9).exterior.coords)[:-1]])
        base = {w: Polygon(plans[w].polygon) for w in ids}
        for node, mem in sorted(multi_nodes.items()):
            # walls running THROUGH the node keep their material; walls ending there yield by priority
            through = sorted(mem["through"], key=lambda w: (pr.get(w, (0,)), w), reverse=True)
            ending = sorted(mem["end"] - mem["through"], key=lambda w: (pr.get(w, (0,)), w), reverse=True)
            order = through + ending
            members = set(order)
            for i, w in enumerate(order[1:], 1):
                cur = Polygon(plans[w].polygon)
                for hi in order[:i]:
                    cur = cur.difference(base[hi])
                if cur.geom_type == "MultiPolygon":
                    parts = sorted(cur.geoms, key=lambda g: -g.area)
                    if parts[1].area > 1e-6:
                        issues.add("JUNCTION_FRAGMENT", "warning", f"{w}: junction trimming left a fragment; largest part kept", (w,), layer="compile")
                    cur = parts[0]
                if cur.is_empty or cur.area < 1e-9:
                    issues.add("JUNCTION_CONSUMED", "error", f"{w}: wall entirely consumed by higher-priority walls at a junction", (w,), layer="compile")
                    continue
                cur = cur.simplify(1e-9)
                coords = [tuple(c) for c in list(cur.exterior.coords)[:-1]]
                plans[w].polygon = G.ensure_ccw(coords)
            issues.add("JUNCTION_MULTI_RESOLVED", "info",
                       f"{len(members)}-way junction resolved by priority ({' > '.join(order)})", tuple(order), layer="compile")
    return plans


def clear_span(plan: WallPlan) -> tuple[float, float]:
    """Along-baseline range where BOTH faces of the (possibly trimmed) wall polygon exist."""
    from shapely.geometry import LineString, Polygon

    f = plan.frame
    poly = Polygon(plan.polygon)
    rng = []
    for off in (f.off_left - 1e-4, f.off_right + 1e-4):
        p0 = G.add(f.start, G.mul(f.n, off))
        a, b = G.add(p0, G.mul(f.d, -1e3)), G.add(p0, G.mul(f.d, f.length + 1e3))
        seg = poly.intersection(LineString([a, b]))
        if seg.is_empty:
            return (0.0, 0.0)
        us = [f.u(c) for g in getattr(seg, "geoms", [seg]) for c in g.coords]
        rng.append((min(us), max(us)))
    return max(rng[0][0], rng[1][0]), min(rng[0][1], rng[1][1])
