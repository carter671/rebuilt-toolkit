"""Export a Genome (+ its compiled GLB) as the compact plan the design editor works on.

    python3 -m rebuilt.design.editor_export GENOME.json MODEL.glb OUT.json [--name NAME]

Everything is in metres, plan coordinates (x east, y north). Walls are centrelines with
thickness; openings sit at `off` metres from the wall start, spanning `w`. Components carry a
plan box (from the compiled model) so the editor can draw cabinets, fixtures and furniture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _v(x, d=None):
    if isinstance(x, dict):
        return x.get("value", d)
    return d if x is None else x


def export(genome: dict, glb: str | None = None, name: str | None = None) -> dict:
    E = genome["elements"]
    storeys = {}
    for b in genome["buildings"]:
        for s in b["storeys"]:
            storeys[s["id"]] = {"elev": s["elevation"]["value"], "building": b["id"], "name": s.get("name", s["id"])}
    walls, openings, spaces, comps, roofs = [], [], [], [], []
    for e in E.values():
        t = e["type"]
        if t == "wall":
            walls.append({"id": e["id"], "st": e["storey"], "s": [round(v, 4) for v in e["start"]], "e": [round(v, 4) for v in e["end"]],
                          "t": round(_v(e.get("thickness"), 0.114), 4), "h": round(_v(e.get("height"), 2.44), 4),
                          "b": round(_v(e.get("base_offset"), 0.0), 4), "ext": bool(e.get("exterior")), "name": e.get("name", "")})
        elif t == "opening":
            fill = e.get("filling") or {}
            openings.append({"id": e["id"], "host": e["host"], "kind": e.get("kind", "door"), "off": round(_v(e.get("offset"), 0), 4),
                             "w": round(_v(e.get("width"), 0.8), 4), "h": round(_v(e.get("height"), 2.03), 4),
                             "sill": round(_v(e.get("sill"), 0.0), 4), "name": e.get("name", ""),
                             "op": (fill.get("operation") or "") if isinstance(fill, dict) else ""})
        elif t == "roof" and e.get("footprint"):
            roofs.append({"id": e["id"], "name": e.get("name", ""), "st": e["storey"], "form": e.get("form", "gable"),
                          "fp": [[round(a, 4), round(b, 4)] for a, b in e["footprint"]], "roles": e.get("edge_roles", []),
                          "pitch": round(_v(e.get("pitch"), 0.333), 4), "plate": round(_v(e.get("plate_height"), 2.44), 4),
                          "oh": round(_v(e.get("overhang"), 0.3), 4), "rake": round(_v(e.get("rake_overhang"), 0.3), 4),
                          "framing": ((e.get("info") or {}).get("framing") or "unknown")})
        elif t == "space":
            spaces.append({"id": e["id"], "name": e.get("name", e["id"]), "st": e["storey"],
                           "poly": [[round(a, 4), round(b, 4)] for a, b in e["boundary"]], "h": round(_v(e.get("height"), 2.44), 4)})
    boxes = _component_boxes(glb) if glb else {}
    for e in E.values():
        if e["type"] != "component" or e["id"] not in boxes:
            continue
        mn, mx = boxes[e["id"]]
        info = e.get("info") or {}
        comps.append({"id": e["id"], "name": e.get("name", ""), "st": e.get("storey"), "kind": e.get("kind", ""),
                      "cat": info.get("category", ""), "min": mn, "max": mx})
    return {"name": name or genome.get("project", {}).get("name", "As-built"), "units": "m", "storeys": storeys,
            "walls": walls, "openings": openings, "spaces": spaces, "comps": comps, "roofs": roofs}


def _component_boxes(glb):
    """Axis-aligned plan boxes per element id, read from the compiled GLB (y-up -> plan)."""
    import struct
    import numpy as np
    raw = Path(glb).read_bytes()
    jl = struct.unpack_from("<I", raw, 12)[0]
    g = json.loads(raw[20:20 + jl])
    bl = struct.unpack_from("<I", raw, 20 + jl)[0]
    binc = raw[28 + jl:28 + jl + bl]
    out = {}
    for node in g.get("nodes", []):
        if "mesh" not in node:
            continue
        gid = (node.get("extras") or {}).get("genome_id") or node.get("name", "")
        mesh = g["meshes"][node["mesh"]]
        pts = []
        for prim in mesh["primitives"]:
            acc = g["accessors"][prim["attributes"]["POSITION"]]
            if "min" in acc and "max" in acc:
                pts += [acc["min"], acc["max"]]
        if not pts:
            continue
        a = np.array(pts)
        t = node.get("translation", [0, 0, 0])
        lo, hi = a.min(0) + t, a.max(0) + t
        # glTF y-up: plan x = x, plan y = -z, height = y
        mn = [round(float(lo[0]), 4), round(float(-hi[2]), 4), round(float(lo[1]), 4)]
        mx = [round(float(hi[0]), 4), round(float(-lo[2]), 4), round(float(hi[1]), 4)]
        out[gid] = (mn, mx)
    return out


def main(argv):
    genome, glb, out = argv[:3]
    name = argv[argv.index("--name") + 1] if "--name" in argv else None
    data = export(json.loads(Path(genome).read_text()), glb, name)
    Path(out).write_text(json.dumps(data, separators=(",", ":")))
    print(f"{len(data['walls'])} walls, {len(data['openings'])} openings, {len(data['spaces'])} rooms, {len(data['comps'])} components -> {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
