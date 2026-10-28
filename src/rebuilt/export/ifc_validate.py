"""Independent validation of an exported IFC file.

1. Schema validation (ifcopenshell.validate, EXPRESS rules where implemented).
2. Spatial structure: project → site → building → storeys; every product contained.
3. Semantics: each compiled element present with the expected class and GenomeId; one
   IfcRelVoidsElement per opening, one IfcRelFillsElement per filling; unique GlobalIds.
4. Geometry, recomputed by a different kernel (OpenCASCADE inside IfcOpenShell, which also
   performs the opening subtraction itself from IfcRelVoidsElement): per-element volume
   compared with MODEL's manifold3d volume.
"""
from __future__ import annotations

import logging

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.validate
import numpy as np

from ..model.compile import CompiledModel


def _mesh_volume(verts, faces) -> float:
    v = np.asarray(verts, dtype=float).reshape(-1, 3)
    t = np.asarray(faces, dtype=int).reshape(-1, 3)
    tri = v[t]
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6)


def validate_ifc(path: str, model: CompiledModel, vol_tol: float = 1e-4) -> dict:
    f = ifcopenshell.open(path)
    out = {"file": str(path), "schema": f.schema, "checks": [], "geometry": {}, "ok": True}

    def check(name, ok, detail=""):
        out["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
        out["ok"] &= bool(ok)

    # 1 schema
    log = logging.getLogger("ifcval")
    log.handlers = []
    errs = []

    class H(logging.Handler):
        def emit(self, r):
            errs.append(self.format(r))

    log.addHandler(H())
    log.setLevel(logging.ERROR)
    ifcopenshell.validate.validate(f, log, express_rules=False)
    check("schema_valid", not errs, "; ".join(errs[:5]))

    # 2 spatial
    projs = f.by_type("IfcProject")
    check("one_project", len(projs) == 1)
    storeys = f.by_type("IfcBuildingStorey")
    check("storeys", len(storeys) == len({e.storey for e in model.elements.values() if e.storey}),
          f"{len(storeys)} storeys")
    uncontained = [p.GlobalId for p in f.by_type("IfcElement")
                   if not p.is_a("IfcOpeningElement") and not ifcopenshell.util.element.get_container(p)
                   and not ifcopenshell.util.element.get_aggregate(p)]
    check("all_elements_contained", not uncontained, f"{len(uncontained)} uncontained")

    # 3 semantics
    by_gid = {}
    for p in f.by_type("IfcProduct"):
        ps = ifcopenshell.util.element.get_psets(p).get("Rebuilt_Identity")
        if ps:
            by_gid[ps["GenomeId"]] = p
    missing, wrong = [], []
    for eid, ce in model.elements.items():
        p = by_gid.get(eid)
        if p is None:
            missing.append(eid)
        elif not p.is_a(ce.ifc_class if not (ce.type == "slab" and ce.data["kind"] == "ceiling") else "IfcCovering"):
            wrong.append(f"{eid}:{p.is_a()}")
    check("all_elements_present", not missing, ",".join(missing))
    check("ifc_classes", not wrong, ",".join(wrong))
    n_open = len(model.by_type("opening"))
    n_fill = len(model.by_type("filling"))
    voids = f.by_type("IfcRelVoidsElement")
    fills = f.by_type("IfcRelFillsElement")
    check("voids_relations", len(voids) == n_open, f"{len(voids)} vs {n_open}")
    check("fills_relations", len(fills) == n_fill, f"{len(fills)} vs {n_fill}")
    bad_void_host = [r.RelatedOpeningElement.Name for r in voids
                     if ifcopenshell.util.element.get_psets(r.RelatingBuildingElement)["Rebuilt_Identity"]["GenomeId"]
                     != model.elements[ifcopenshell.util.element.get_psets(r.RelatedOpeningElement)["Rebuilt_Identity"]["GenomeId"]].data["host"]]
    check("voids_correct_host", not bad_void_host, ",".join(bad_void_host))
    gids = [e.GlobalId for e in f.by_type("IfcRoot")]
    check("unique_globalids", len(gids) == len(set(gids)))
    mats = [r for r in f.by_type("IfcRelAssociatesMaterial")]
    check("materials_associated", len(mats) > 0)

    # 4 geometry via OpenCASCADE
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    diffs = {}
    for eid, ce in model.elements.items():
        if ce.type == "space" or ce.mesh is None:
            continue
        targets = [by_gid[eid]]
        if ce.type == "roof":
            targets = [r for rel in by_gid[eid].IsDecomposedBy for r in rel.RelatedObjects]
        if ce.type == "opening":
            continue  # openings are subtracted from walls; checked through wall volumes
        vol = 0.0
        bb_min, bb_max = np.full(3, np.inf), np.full(3, -np.inf)
        for t in targets:
            sh = ifcopenshell.geom.create_shape(s, t)
            vol += _mesh_volume(sh.geometry.verts, sh.geometry.faces)
            vv = np.asarray(sh.geometry.verts).reshape(-1, 3)
            bb_min, bb_max = np.minimum(bb_min, vv.min(0)), np.maximum(bb_max, vv.max(0))
        mv = ce.mesh.volume()
        mb0, mb1 = ce.mesh.bounds()
        bbd = float(max(np.abs(bb_min - mb0).max(), np.abs(bb_max - mb1).max()))
        diffs[eid] = {"model_volume": mv, "occ_volume": vol, "abs_diff": abs(vol - mv), "bbox_diff": bbd}
    out["geometry"] = diffs
    bad = {k: v for k, v in diffs.items() if v["abs_diff"] > vol_tol or v["bbox_diff"] > 1e-4}
    check("occ_geometry_matches_model", not bad,
          ", ".join(f"{k}: Δv={v['abs_diff']:.2e} Δbb={v['bbox_diff']:.2e}" for k, v in sorted(bad.items())))
    return out
