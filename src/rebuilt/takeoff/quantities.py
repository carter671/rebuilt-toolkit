"""Takeoff quantities, read from a compiled model + its Genome.

Every number here comes from the compiled geometry or the Genome — nothing is typed in.
Units out: square feet (sf), linear feet (lf), counts (ea). Basis rolls up the weakest
provenance of the inputs, so the scope sheet can say which quantities are measured vs estimated.
"""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Point, Polygon

SF = 10.7639104  # m² → sf
LF = 3.2808399  # m → ft

_RANK = {"measured": 0, "extracted": 1, "observed": 2, "inferred": 3, "assumed": 4, "unknown": 5}
_WORST = {v: k for k, v in _RANK.items()}


def _worst(*bases):
    b = [_RANK.get(x, 4) for x in bases if x]
    return _WORST[max(b)] if b else "assumed"


def _basis(rec):
    if isinstance(rec, dict):
        return rec.get("basis", "assumed")
    return "assumed"


def _poly_perimeter(poly):
    return sum(math.dist(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def room_kind(name: str) -> str:
    n = name.lower()
    for kw, k in (("closet", "closet"), ("storage", "closet"), ("bath", "bath"), ("kitchen", "kitchen"), ("laundry", "laundry"), ("garage", "garage"),
                  ("porch", "porch"), ("closet", "closet"), ("storage", "closet"), ("bedroom", "bedroom"),
                  ("master", "bedroom"), ("hall", "hall"), ("foyer", "hall"), ("loft", "hall"),
                  ("landing", "hall"), ("living", "living"), ("dining", "living"), ("family", "living")):
        if kw in n:
            return k
    return "living"


def _up_area(mesh, min_nz=0.2):
    """Area of upward-facing triangles (roof covering surface after trims/cuts)."""
    v = mesh.verts[mesh.tris]
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    a = np.linalg.norm(n, axis=1) / 2
    nz = np.divide(n[:, 2], 2 * a, out=np.zeros_like(a), where=a > 0)
    return float(a[nz > min_nz].sum())


def _long_extent(mesh):
    lo, hi = mesh.bounds()
    return float(max(hi[0] - lo[0], hi[1] - lo[1]))


def quantities(model, genome: dict) -> dict:
    """genome: the raw Genome JSON dict (for names, info, buildings)."""
    G = genome["elements"]
    E = model.elements
    storey_bldg = {s["id"]: b["id"] for b in genome["buildings"] for s in b["storeys"]}
    bldg_name = {b["id"]: b["name"] for b in genome["buildings"]}

    # ---- openings ----------------------------------------------------------
    openings = []
    for oid, ce in sorted(E.items()):
        if ce.type != "opening":
            continue
        go = G[oid]
        host = G[go["host"]]
        fill = go.get("filling") or {}
        d = ce.data
        openings.append({
            "id": oid, "name": go.get("name", oid), "kind": d["kind"],
            "operation": fill.get("operation") or "",
            "w_in": round(d["width"] * 39.3701), "h_in": round(d["height"] * 39.3701),
            "area_sf": d["width"] * d["height"] * SF,
            "host": go["host"], "exterior": bool(host.get("exterior")),
            "storey": host["storey"], "building": storey_bldg[host["storey"]],
            "centre": d["centre"],
            "basis": _worst(_basis(go.get("width")), _basis(go.get("height"))),
            "screen": "screen" in (fill.get("operation") or "").lower() or "screen" in go.get("name", "").lower(),
        })
        o = openings[-1]
        txt = (o["operation"] + " " + o["name"]).lower()
        if o["kind"] == "door":
            o["exterior"] = any(w in txt for w in ("exterior", "entry", "back door", "screen door", "garage", "inswing", "outswing"))
            o["french"] = "french" in txt
            o["bifold"] = "bifold" in txt
        elif o["kind"] == "window":
            o["exterior"] = bool(host.get("exterior")) and "transom" not in txt or "transom" in txt
            o["large"] = o["area_sf"] >= 20 or "picture" in txt

    # ---- rooms -------------------------------------------------------------
    rooms = []
    for sid, ce in sorted(E.items()):
        if ce.type != "space":
            continue
        gs = G[sid]
        poly = Polygon(ce.data["boundary"])
        z0 = ce.data["base_z"]
        h = ce.data["height"]
        perim_m = _poly_perimeter(ce.data["boundary"])
        mine = []
        for o in openings:
            if storey_bldg.get(o["storey"]) != storey_bldg.get(gs["storey"]) or o["storey"] != gs["storey"]:
                continue
            if poly.distance(Point(o["centre"][0], o["centre"][1])) <= 0.25:
                mine.append(o)
        door_w_lf = sum(o["w_in"] / 12 for o in mine if o["kind"] in ("door", "void"))
        open_sf = sum(o["area_sf"] for o in mine)
        wall_sf = max(perim_m * LF * h * LF - open_sf, 0.0)
        surf = gs.get("surfaces") or {}
        rooms.append({
            "id": sid, "name": gs.get("name", sid), "storey": gs["storey"],
            "building": storey_bldg[gs["storey"]], "kind": room_kind(gs.get("name", "")),
            "floor_sf": ce.data["area"] * SF, "ceiling_sf": ce.data["area"] * SF,
            "perimeter_lf": perim_m * LF, "height_ft": h * LF, "wall_sf": wall_sf,
            "base_lf": max(perim_m * LF - door_w_lf, 0.0),
            "openings": [o["id"] for o in mine],
            "existing": {k: (v.get("subtype") or v.get("material") or "") for k, v in surf.items() if isinstance(v, dict)},
            "condition": {k: ((v.get("condition") or {}).get("rating") or "") for k, v in surf.items() if isinstance(v, dict)},
            "basis": _worst(_basis(gs.get("height")), "measured" if gs.get("bounded_by") else "inferred"),
        })

    # ---- exterior, by building -------------------------------------------
    ext = {b: {"building": b, "name": bldg_name[b], "roof_sf": 0.0, "roofs": [], "siding_sf": 0.0,
               "gutter_lf": 0.0, "downspout_lf": 0.0, "fascia_lf": 0.0, "soffit_lf": 0.0,
               "shutter_pairs": 0, "windows": 0, "ext_doors": 0, "garage_doors": 0, "screen_sf": 0.0}
           for b in bldg_name}
    for rid, ce in sorted(E.items()):
        if ce.type != "roof":
            continue
        b = storey_bldg[G[rid]["storey"]]
        a = _up_area(ce.mesh) * SF
        ext[b]["roof_sf"] += a
        ext[b]["roofs"].append({"id": rid, "name": G[rid].get("name", rid), "sf": a,
                                "pitch": (G[rid].get("pitch") or {}).get("input", ""),
                                "basis": _basis(G[rid].get("pitch")),
                                "condition": (((G[rid].get("info") or {}).get("condition")) or {}).get("notes") or ""})
    for cid, ce in sorted(E.items()):
        if ce.type != "component":
            continue
        gc = G[cid]
        k = ce.data.get("kind")
        st = gc.get("storey") or (G.get(gc["placement"].get("roof"), {}) or {}).get("storey")
        if not st and gc["placement"].get("wall"):
            st = G[gc["placement"]["wall"]]["storey"]
        if not st and gc["placement"].get("opening"):
            st = G[G[gc["placement"]["opening"]]["host"]]["storey"]
        b = storey_bldg.get(st, "B1")
        if k == "cladding":
            hosts = set(ce.data.get("hosts") or [])
            holes = sum(o["area_sf"] for o in openings if o["host"] in hosts and o["kind"] != "void")
            ext[b]["siding_sf"] += max(ce.data.get("approx_area", 0) * SF - holes, 0.0)
        elif k in ("gutter", "fascia", "soffit") and ce.mesh is not None:
            ext[b][f"{k}_lf"] += _long_extent(ce.mesh) * LF
        elif k == "downspout" and ce.mesh is not None:
            lo, hi = ce.mesh.bounds()
            ext[b]["downspout_lf"] += float(hi[2] - lo[2]) * LF
        elif k == "shutter":
            ext[b]["shutter_pairs"] += 1
    for o in openings:
        if not o["exterior"]:
            continue
        x = ext[o["building"]]
        if o["screen"]:
            x["screen_sf"] += o["area_sf"]
        elif o["kind"] == "window":
            x["windows"] += 1
        elif o["kind"] == "door" and "garage" in o["name"].lower() and o["w_in"] > 72:
            x["garage_doors"] += 1
        elif o["kind"] == "door":
            x["ext_doors"] += 1

    # ---- fixtures / systems (counts from the inventory) --------------------
    fixtures = {"light": 0, "receptacle": 0, "switch": 0, "smoke": 0, "toilet": 0, "tub": 0, "vanity": 0}
    for cid, gc in G.items():
        if gc["type"] != "component":
            continue
        n = gc.get("name", "").lower()
        for key, words in (("light", ("chandelier", "light", "fixture", "pendant", "lantern", "sconce")),
                           ("receptacle", ("receptacle", "outlet")), ("switch", ("switch",)),
                           ("smoke", ("smoke",)), ("toilet", ("toilet",)), ("tub", ("tub",)),
                           ("vanity", ("vanity",))):
            if any(w in n for w in words) and not ("washer outlet" in n and key == "receptacle"):
                fixtures[key] += 1
                break

    return {
        "address": (genome.get("property") or {}).get("address") or genome["project"].get("name"),
        "model_hash": model.model_hash, "genome_revision": model.genome_revision,
        "rooms": rooms, "openings": openings, "exterior": list(ext.values()), "fixtures": fixtures,
        "totals": {
            "heated_sf": sum(r["floor_sf"] for r in rooms if r["kind"] not in ("porch", "garage")),
            "windows": sum(1 for o in openings if o["kind"] == "window" and not o["screen"]),
            "int_doors": sum(1 for o in openings if o["kind"] == "door" and not o["exterior"]),
            "ext_doors": sum(1 for o in openings if o["kind"] == "door" and o["exterior"] and not o["screen"]),
        },
    }
