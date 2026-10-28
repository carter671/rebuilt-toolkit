"""GLB export: one node per element with extras {genome_id, ifc_guid, type, rev}; plus a JSON sidecar
carrying the provenance/uncertainty/issue data that glTF cannot represent natively.

Axis convention: Genome is Z-up (x east, y north); glTF is Y-up, so (x, y, z) -> (x, z, -y).
"""
from __future__ import annotations

import json

import numpy as np
import pygltflib as gl

from ..genome.schema import Genome
from ..model.compile import CompiledModel
from .ifc import guid_for

DEFAULT_COLORS = {"wall": "#d9cbb3", "slab": "#b0aca4", "roof": "#5b5f66", "filling": "#8a5a36", "space": "#7fb3ff",
                  "component": "#e6e6e0"}


def element_colors(model: CompiledModel, g: Genome) -> dict:
    """Display colour per compiled element: own finish > covering cladding's finish > material > type default."""
    def fin(fid):
        f = g.finishes.get(fid) if fid else None
        return f.hex if f and f.hex else None

    clad = {}
    for eid, ce in model.elements.items():
        if ce.type == "component" and ce.data.get("kind") == "cladding" and ce.data.get("color"):
            for h in ce.data.get("hosts", []):
                clad[h] = ce.data["color"]
    out = {}
    for eid, ce in model.elements.items():
        gel = g.elements.get(eid.split("#")[0])
        own = fin(gel.info.finish) if gel is not None and gel.info else None
        if ce.type == "filling" and gel is not None and getattr(gel, "unit", None) and gel.unit.sash_finish and ce.ifc_class == "IfcDoor":
            own = own or fin(gel.unit.sash_finish)
        if ce.type == "component":
            own = own or ce.data.get("color")
        m = g.materials.get(ce.material) if ce.material else None
        out[eid] = own or clad.get(eid) or (m.color if m and m.color else None) or DEFAULT_COLORS.get(ce.type, "#cccccc")
    return out


def _rgba(hexc: str, a=1.0):
    h = hexc.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [a]


def _flat(mesh):
    v = mesh.verts[mesh.tris].reshape(-1, 3)
    v = np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1).astype(np.float32)
    tri = v.reshape(-1, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    L = np.linalg.norm(n, axis=1, keepdims=True)
    L[L == 0] = 1
    n = np.repeat(n / L, 3, axis=0).astype(np.float32)
    return v, n


def sidecar(model: CompiledModel, g: Genome) -> dict:
    issues_by = {}
    for i in model.issues.items:
        for e in i.elements:
            issues_by.setdefault(e, []).append(i.to_dict())
    els = {}
    for eid, ce in model.elements.items():
        data = {k: v for k, v in ce.data.items() if k not in ("plan_polygon", "boundary", "panels", "outline", "frame")}
        gel = g.elements.get(eid.split("#")[0])
        info = None
        if gel is not None:
            info = {k: v for k, v in gel.model_dump(mode="json", exclude_none=True, include={
                "info", "family", "phase", "history", "properties", "unit", "surfaces", "kind"}).items() if v not in ({}, [], "existing")}
            if gel.family and gel.family in g.families:
                info["family_info"] = g.families[gel.family].model_dump(mode="json", exclude_none=True)
        els[eid] = {"id": eid, "type": ce.type, "ifc_class": ce.ifc_class, "name": ce.name, "storey": ce.storey, "info": info or None,
                    "rev": ce.rev, "material": g.materials[ce.material].name if ce.material else None,
                    "data": data, "params": ce.params, "issues": issues_by.get(eid, []),
                    "ifc_guid": guid_for(g.project.id, eid)}
    return {"project": g.project.name, "fictional": g.project.fictional, "genome_revision": model.genome_revision,
            "model_hash": model.model_hash, "compiler_version": model.compiler_version,
            "storeys": [{"id": s.id, "name": s.name, "elevation": s.elevation.value} for s in g.storeys()],
            "finishes": {k: v.model_dump(mode="json", exclude_none=True) for k, v in g.finishes.items()},
            "capture": g.capture.model_dump(mode="json"),
            "elements": els, "issues": [i.to_dict() for i in model.issues.sorted()], "unsupported": model.unsupported,
            "observations": {k: v.model_dump(mode="json", exclude_none=True) for k, v in g.observations.items()}}


def export_glb(model: CompiledModel, g: Genome, path: str, include_spaces=True) -> dict:
    buf = bytearray()
    accessors, views, meshes, nodes, materials = [], [], [], [], []
    mat_index = {}

    def material(key, hexc, alpha=1.0):
        if key not in mat_index:
            mat_index[key] = len(materials)
            materials.append(gl.Material(
                name=key, doubleSided=True, alphaMode="BLEND" if alpha < 1 else "OPAQUE",
                pbrMetallicRoughness=gl.PbrMetallicRoughness(baseColorFactor=_rgba(hexc, alpha), metallicFactor=0.0, roughnessFactor=0.9)))
        return mat_index[key]

    def add_array(arr, target):
        while len(buf) % 4:
            buf.append(0)
        off = len(buf)
        buf.extend(arr.tobytes())
        views.append(gl.BufferView(buffer=0, byteOffset=off, byteLength=arr.nbytes, target=target))
        return len(views) - 1

    tri_counts = {}
    colors = element_colors(model, g)
    for eid, ce in model.elements.items():
        if ce.mesh is None or ce.type == "opening" or (ce.type == "space" and not include_spaces):
            continue
        v, n = _flat(ce.mesh)
        tri_counts[eid] = len(ce.mesh.tris)
        vi = add_array(v, gl.ARRAY_BUFFER)
        accessors.append(gl.Accessor(bufferView=vi, componentType=gl.FLOAT, count=len(v), type=gl.VEC3,
                                     min=v.min(0).tolist(), max=v.max(0).tolist()))
        ni = add_array(n, gl.ARRAY_BUFFER)
        accessors.append(gl.Accessor(bufferView=ni, componentType=gl.FLOAT, count=len(n), type=gl.VEC3))
        if ce.type == "space":
            mi = material("space", DEFAULT_COLORS["space"], 0.18)
        elif ce.type == "filling" and ce.ifc_class == "IfcWindow":
            mi = material("glass", "#9cc7e0", 0.45)
        else:
            mi = material(f"{ce.type}:{colors[eid]}", colors[eid])
        meshes.append(gl.Mesh(name=eid, primitives=[gl.Primitive(attributes=gl.Attributes(POSITION=len(accessors) - 2, NORMAL=len(accessors) - 1),
                                                               material=mi)]))
        nodes.append(gl.Node(name=eid, mesh=len(meshes) - 1, extras={
            "genome_id": eid, "type": ce.type, "ifc_class": ce.ifc_class, "rev": ce.rev, "storey": ce.storey,
            "ifc_guid": guid_for(g.project.id, eid)}))
    doc = gl.GLTF2(
        asset=gl.Asset(generator=f"Rebuilt MODEL {model.compiler_version}", version="2.0",
                       extras={"genome_revision": model.genome_revision, "model_hash": model.model_hash}),
        scene=0, scenes=[gl.Scene(nodes=list(range(len(nodes))))], nodes=nodes, meshes=meshes, materials=materials,
        accessors=accessors, bufferViews=views, buffers=[gl.Buffer(byteLength=len(buf))])
    doc.set_binary_blob(bytes(buf))
    doc.save_binary(path)
    sc = sidecar(model, g)
    with open(str(path).rsplit(".", 1)[0] + ".meta.json", "w") as fh:
        json.dump(sc, fh, indent=1, default=float)
    return {"nodes": len(nodes), "triangles": tri_counts}
