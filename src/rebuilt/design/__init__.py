"""Design module: edits a COPY of an as-built Genome into a design Genome.

The as-built is never touched. A design file lists plain-language layout changes; each one
becomes Genome edits (elements removed / added / resized, rooms merged) plus the scope lines
the change implies (demo, header, new opening, patching). The design Genome compiles with the
same MODEL, so plans, 3D and quantities for the design come out of the same engine.

design.json:
{
  "name": "Waterloo flip v1",
  "changes": [
    {"do": "remove_wall", "wall": "W1-LRP", "bearing": "no" | "yes" | "unknown",
     "merge": ["SP1-a", "SP1-b"], "room_name": "Open kitchen"},
    {"do": "add_opening", "wall": "W1-KE", "kind": "window", "width": "36\"", "height": "48\"",
     "sill": "36\"", "offset": "4'", "name": "New kitchen window"},
    {"do": "remove_opening", "opening": "O1-CL-D"},
    {"do": "resize_opening", "opening": "O1-KF-D", "width": "6'", "height": "80\""}
  ],
  "selections": {"<decision id>": "<option>"}     # finish choices, see takeoff.scope
}
"""
from __future__ import annotations

import copy
import math

from shapely.geometry import Polygon
from shapely.ops import unary_union

from ..units import parse_length


class DesignError(ValueError):
    pass


def _v(m, why):
    return {"value": round(float(m), 6), "basis": "assumed", "verification": "unverified",
            "selection": {"by": "design", "process": "design", "reason": why}}


def _len(x):
    return float(x) if isinstance(x, (int, float)) else parse_length(str(x))


def apply_design(asbuilt: dict, design: dict) -> tuple[dict, list[dict]]:
    """Returns (design_genome_dict, layout_decisions). Raises DesignError on a bad change."""
    g = copy.deepcopy(asbuilt)
    E = g["elements"]
    layout = []

    def hosted_on(eid):
        out = []
        for k, e in E.items():
            p = e.get("placement") or {}
            if e.get("host") == eid or p.get("wall") == eid or p.get("opening") == eid:
                out.append(k)
        return out

    def drop(eid):
        for k in hosted_on(eid):
            if k in E:
                drop(k)
        E.pop(eid, None)
        for e in E.values():
            if e.get("type") == "space" and eid in e.get("bounded_by", []):
                e["bounded_by"] = [w for w in e["bounded_by"] if w != eid]
            hosts = (e.get("placement") or {}).get("hosts")
            if hosts and eid in hosts:
                e["placement"]["hosts"] = [h for h in hosts if h != eid]

    for i, ch in enumerate(design.get("changes", [])):
        do = ch.get("do")
        cid = f"layout:{i}"
        if do == "remove_wall":
            w = E.get(ch["wall"])
            if not w or w["type"] != "wall":
                raise DesignError(f"change {i}: no wall {ch['wall']}")
            if w.get("exterior"):
                raise DesignError(f"change {i}: {ch['wall']} is an exterior wall — not supported as a removal")
            L = math.dist(w["start"], w["end"]) * 3.2808399
            nops = [k for k in hosted_on(ch["wall"]) if E[k]["type"] == "opening"]
            drop(ch["wall"])
            if ch.get("merge"):
                a, *rest = ch["merge"]
                if a not in E or any(r not in E for r in rest):
                    raise DesignError(f"change {i}: merge rooms not found {ch['merge']}")
                polys = [Polygon(E[s]["boundary"]) for s in ch["merge"]]
                th = float(w["thickness"]["value"]) + 0.02
                u = unary_union([p.buffer(th / 2, join_style=2) for p in polys]).buffer(-th / 2, join_style=2)
                if u.geom_type != "Polygon":
                    raise DesignError(f"change {i}: rooms {ch['merge']} don't touch across {ch['wall']}")
                from shapely.geometry.polygon import orient
                u = orient(u.simplify(0.01), sign=1.0)
                E[a]["boundary"] = [[round(x, 6), round(y, 6)] for x, y in list(u.exterior.coords)[:-1]]
                E[a]["bounded_by"] = sorted(set(E[a].get("bounded_by", [])).union(*[E[r].get("bounded_by", []) for r in rest]))
                if ch.get("room_name"):
                    E[a]["name"] = ch["room_name"]
                for r in rest:
                    for e in E.values():
                        if (e.get("placement") or {}).get("space") == r:
                            e["placement"]["space"] = a
                    E.pop(r)
            bearing = ch.get("bearing", "unknown")
            lines = [{"key": "wall_remove", "qty": round(L, 2), "note": f"{L:.1f} lf, {len(nops)} opening(s) go with it"}]
            if bearing != "no":
                lines.append({"key": "header_bearing", "qty": 1,
                              "note": "bearing status " + ("confirmed" if bearing == "yes" else "unknown — have the GC/engineer confirm")})
            layout.append({"id": cid, "group": "Layout changes", "label": f"Remove wall: {w.get('name', ch['wall'])}",
                           "existing": f"{L:.1f} ft wall", "default": "do",
                           "options": {"do": {"label": "Do it", "lines": lines}, "skip": {"label": "Skip", "lines": []}}})
        elif do == "add_opening":
            w = E.get(ch["wall"])
            if not w or w["type"] != "wall":
                raise DesignError(f"change {i}: no wall {ch['wall']}")
            oid = ch.get("id") or f"N-{ch['wall']}-{i}"
            kind = ch.get("kind", "window")
            wd, ht = _len(ch["width"]), _len(ch["height"])
            sill = _len(ch.get("sill", 0 if kind == "door" else 0.9144))
            off = _len(ch["offset"])
            L = math.dist(w["start"], w["end"])
            if off < 0 or off + wd > L:
                raise DesignError(f"change {i}: opening runs past the wall ({L * 3.28:.1f} ft long)")
            E[oid] = {"type": "opening", "id": oid, "name": ch.get("name", f"New {kind}"), "host": ch["wall"],
                      "kind": kind, "phase": "new", "offset": _v(off, "design"), "width": _v(wd, "design"),
                      "height": _v(ht, "design"), "sill": _v(sill, "design"),
                      "filling": {"type": kind, "operation": ch.get("operation", "new " + kind)}}
            key = "window_std" if kind == "window" else ("door_ext" if w.get("exterior") else "door_int")
            layout.append({"id": cid, "group": "Layout changes", "label": f"Add {kind}: {E[oid]['name']}",
                           "existing": f"on {w.get('name', ch['wall'])}", "default": "do",
                           "options": {"do": {"label": "Do it", "lines": [
                               {"key": "opening_new", "qty": 1, "note": ""},
                               {"key": key, "qty": 1, "note": "unit"}]},
                               "skip": {"label": "Skip", "lines": []}}})
        elif do == "remove_opening":
            o = E.get(ch["opening"])
            if not o or o["type"] != "opening":
                raise DesignError(f"change {i}: no opening {ch['opening']}")
            drop(ch["opening"])
            layout.append({"id": cid, "group": "Layout changes", "label": f"Close up: {o.get('name', ch['opening'])}",
                           "existing": "", "default": "do",
                           "options": {"do": {"label": "Do it", "lines": [{"key": "opening_close", "qty": 1, "note": ""}]},
                                       "skip": {"label": "Skip", "lines": []}}})
        elif do == "resize_opening":
            o = E.get(ch["opening"])
            if not o or o["type"] != "opening":
                raise DesignError(f"change {i}: no opening {ch['opening']}")
            w = E[o["host"]]
            L = math.dist(w["start"], w["end"])
            wd = _len(ch["width"]) if "width" in ch else o["width"]["value"]
            off = o["offset"]["value"] - max(0.0, (wd - o["width"]["value"]) / 2)
            off = min(max(off, 0.15), L - wd - 0.15)
            if off < 0:
                raise DesignError(f"change {i}: {wd * 3.28:.1f} ft won't fit in that wall")
            o["width"] = _v(wd, "design: resized")
            o["offset"] = _v(off, "design: re-centred after resize")
            if "height" in ch:
                o["height"] = _v(_len(ch["height"]), "design: resized")
            o["phase"] = "new"
            for k in hosted_on(ch["opening"]):  # old shutters/casings no longer fit
                E.pop(k, None)
            layout.append({"id": cid, "group": "Layout changes", "label": f"Widen: {o.get('name', ch['opening'])}",
                           "existing": "", "default": "do",
                           "options": {"do": {"label": "Do it", "lines": [{"key": "opening_widen", "qty": 1, "note": ""}]},
                                       "skip": {"label": "Skip", "lines": []}}})
        else:
            raise DesignError(f"change {i}: unknown change '{do}'")

    g["project"]["name"] = f"{asbuilt['project'].get('name', '')} — {design.get('name', 'design')}"
    return g, layout
