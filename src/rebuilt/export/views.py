"""View extraction from compiled solids: plan cuts, vertical section cuts, and hidden-surface
projected faces (painter's order over planar face groups). Pure geometry; no drawing here."""
from __future__ import annotations

from dataclasses import dataclass

import manifold3d as mf
import numpy as np


@dataclass
class Face:
    element: str
    etype: str
    loops: list  # list of (k,2) arrays in screen coords
    depth: float  # larger = farther from viewer
    shade: float  # 0..1 lambert-ish
    normal: tuple = (0.0, 0.0, 0.0)  # world-space face normal


def view_basis(v, up=(0.0, 0.0, 1.0)):
    v = np.asarray(v, float)
    v = v / np.linalg.norm(v)
    up = np.asarray(up, float)
    r = np.cross(v, up)
    if np.linalg.norm(r) < 1e-9:  # looking straight down: screen right = +x, up = +y
        return v, np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    r /= np.linalg.norm(r)
    u = np.cross(r, v)
    return v, r, u


def _planar_faces(verts, tris, angle_tol=1e-4):
    """Group triangles into connected coplanar faces; return list of (tri indices, normal)."""
    P = verts[tris]
    n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    L = np.linalg.norm(n, axis=1)
    keep = L > 1e-14
    n[keep] /= L[keep, None]
    d = np.einsum("ij,ij->i", n, P[:, 0])
    key = np.round(np.c_[n * 1e4, d * 1e4]).astype(np.int64)
    # adjacency through shared edges
    edge_map = {}
    for t, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            edge_map.setdefault(tuple(sorted(e)), []).append(t)
    parent = list(range(len(tris)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for ts in edge_map.values():
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a, b = ts[i], ts[j]
                if keep[a] and keep[b] and (key[a] == key[b]).all():
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[ra] = rb
    groups = {}
    for t in range(len(tris)):
        if keep[t]:
            groups.setdefault(find(t), []).append(t)
    return [(np.array(g), n[g[0]]) for g in groups.values()]


def _boundary_loops(tris_sel):
    cnt = {}
    for a, b, c in tris_sel:
        for e in ((a, b), (b, c), (c, a)):
            k = tuple(sorted(e))
            cnt[k] = cnt.get(k, 0) + 1
    directed = {}
    for a, b, c in tris_sel:
        for e in ((a, b), (b, c), (c, a)):
            if cnt[tuple(sorted(e))] == 1:
                directed.setdefault(e[0], []).append(e[1])
    loops = []
    while directed:
        start = next(iter(directed))
        loop = [start]
        cur = start
        while True:
            nxts = directed.get(cur)
            if not nxts:
                break
            nxt = nxts.pop()
            if not nxts:
                del directed[cur]
            if nxt == start:
                break
            loop.append(nxt)
            cur = nxt
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def project_faces(meshes: dict, etypes: dict, view_dir, light=(0.4, -0.6, 0.7), cull_backfaces=True) -> tuple[list[Face], np.ndarray, np.ndarray]:
    v, r, u = view_basis(view_dir)
    lt = np.asarray(light, float)
    lt /= np.linalg.norm(lt)
    faces = []
    for eid, m in meshes.items():
        verts, tris = m.verts, m.tris
        scr = np.c_[verts @ r, verts @ u]
        dep = verts @ v
        for tsel, nrm in _planar_faces(verts, tris):
            facing = nrm @ v
            if cull_backfaces and facing > -1e-9:
                continue
            tri_idx = tris[tsel]
            loops = [scr[np.array(lp)] for lp in _boundary_loops(tri_idx)]
            if not loops:
                continue
            depth = float(dep[np.unique(tri_idx)].mean())
            shade = 0.55 + 0.45 * max(0.0, float(nrm @ lt))
            faces.append(Face(eid, etypes[eid], loops, depth, shade, tuple(float(x) for x in nrm)))
    faces.sort(key=lambda f: -f.depth)
    return faces, r, u


def section(solids: dict, etypes: dict, point, view_dir):
    """Vertical/arbitrary section. Returns (cut polygons per element in screen coords, the
    trimmed beyond-solids as meshes for projection, r, u)."""
    v, r, u = view_basis(view_dir)
    off = float(np.dot(v, point))
    R = np.array([[*r, 0.0], [*u, 0.0], [*(-v), 0.0]])
    cuts, beyond = {}, {}
    for eid, s in solids.items():
        rot = s.transform(R)
        cs = rot.slice(-off)
        polys = [np.asarray(p) for p in cs.to_polygons()] if not cs.is_empty() else []
        if polys:
            cuts[eid] = polys
        b = s.trim_by_plane(v.tolist(), off)
        if not b.is_empty():
            mm = b.to_mesh64()
            beyond[eid] = type("M", (), {"verts": np.asarray(mm.vert_properties[:, :3]), "tris": np.asarray(mm.tri_verts)})()
    return cuts, beyond, r, u, v


def plan_cut(solids: dict, z: float):
    out = {}
    for eid, s in solids.items():
        bb = s.bounding_box()
        if not (bb[2] < z < bb[5]):
            continue
        cs = s.slice(z)
        if not cs.is_empty():
            out[eid] = [np.asarray(p) for p in cs.to_polygons()]
    return out
