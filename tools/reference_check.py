"""Check ANY implementation's IFC of the fictional house against the hand-derived reference
quantities — useful for cross-reviewing another implementation (e.g. Codex's) on equal terms.

  python tools/reference_check.py OTHER.ifc [--map mapping.json]

Elements are matched by `Rebuilt_Identity.GenomeId`, else by `Name`, else via an optional
mapping file {"reference id": "their GlobalId or Name"}. Volumes are computed by IfcOpenShell's
OpenCASCADE kernel (openings subtracted from walls), so the check is independent of both MODELs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as U
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REF = Path(__file__).resolve().parents[1] / "examples/fictional_house/reference_quantities.json"


def vol(shape):
    v = np.asarray(shape.geometry.verts).reshape(-1, 3)
    t = np.asarray(shape.geometry.faces).reshape(-1, 3)
    tri = v[t]
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc")
    ap.add_argument("--map")
    a = ap.parse_args()
    ref = json.loads(REF.read_text())
    mapping = json.loads(Path(a.map).read_text()) if a.map else {}
    f = ifcopenshell.open(a.ifc)
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    idx = {}
    for p in f.by_type("IfcProduct"):
        gid = (U.get_psets(p).get("Rebuilt_Identity") or {}).get("GenomeId")
        for k in filter(None, (gid, p.Name, p.GlobalId)):
            idx.setdefault(k, p)
    rows, worst = [], 0.0
    for rid, expected in sorted(ref["volumes_m3"].items()):
        key = mapping.get(rid, rid)
        p = idx.get(key)
        if p is None:
            rows.append((rid, expected, None, "MISSING"))
            continue
        parts = [p] + ([o for r in p.IsDecomposedBy for o in r.RelatedObjects] if p.is_a("IfcRoof") else [])
        got = sum(vol(ifcopenshell.geom.create_shape(s, q)) for q in parts if q.Representation)
        err = abs(got - expected)
        worst = max(worst, err)
        rows.append((rid, expected, got, "ok" if err <= ref["tolerance_m3"] else f"Δ {err:.6f}"))
    for r in rows:
        print(f"{r[0]:<16} ref {r[1]:10.6f}  got {'—' if r[2] is None else f'{r[2]:10.6f}'}  {r[3]}")
    bad = [r for r in rows if r[3] != "ok"]
    print(f"\n{len(rows) - len(bad)}/{len(rows)} within ±{ref['tolerance_m3']} m³ (worst Δ {worst:.2e})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
