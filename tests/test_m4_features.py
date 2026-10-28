"""M4 compiler features: intersecting roofs (trim_by), flush eaves, multi-way wall junctions."""
import pytest

from rebuilt.genome.io import parse
from rebuilt.model.compile import compile_genome


def M(v):
    return {"value": v, "basis": "measured"}


def base_doc():
    return {
        "schema_version": "0.1.0",
        "project": {"id": "t-m4", "name": "M4 feature test", "fictional": True},
        "property": {"id": "p"},
        "buildings": [{"id": "B", "name": "b", "storeys": [{"id": "G", "name": "G", "elevation": M(0.0), "height": M(3.0)}]}],
        "materials": {},
        "elements": {},
    }


def wall(eid, s, e, align="right", h=3.0, top=None, t=0.2):
    d = {"type": "wall", "id": eid, "storey": "G", "start": list(s), "end": list(e), "thickness": M(t), "height": M(h),
         "alignment": align, "exterior": True}
    if top:
        d["top"] = {"attach": top}
    return d


def roof(eid, fp, roles, trim=(), plate=3.0, pitch=1.0):
    return {"type": "roof", "id": eid, "storey": "G", "form": "gable", "footprint": fp, "edge_roles": roles, "pitch": M(pitch),
            "plate_height": M(plate), "overhang": M(0.3), "rake_overhang": M(0.1), "thickness": M(0.15), "trim_by": list(trim)}


def test_intersecting_gables_make_valleys():
    d = base_doc()
    # main gable 10 x 6 (ridge along x), cross gable 4 wide coming in from the south, extended to the main ridge
    d["elements"]["R1"] = roof("R1", [[0, 0], [10, 0], [10, 6], [0, 6]], ["eave", "rake", "eave", "rake"])
    d["elements"]["R2"] = roof("R2", [[3, -5], [7, -5], [7, 3], [3, 3]], ["rake", "eave", "abut", "eave"], trim=["R1"], pitch=1.0)
    g, issues = parse(d)
    m = compile_genome(g)
    assert m.ok, m.issues.items
    r1, r2 = m._solids["R1"], m._solids["R2"]
    assert (r1 ^ r2).volume() < 1e-9  # no interpenetration
    assert m.elements["R2"].data["trimmed_by"] == ["R1"]
    # cross gable has equal span-to-pitch → ridge 2 m below main ridge rise 3 m: dies into the main slope
    top2 = m.elements["R2"].mesh.verts[:, 2].max()
    assert top2 < m.elements["R1"].data["top_z"]
    # nothing of R2 is left under R1's surface: sample a point inside R1 below its top
    import manifold3d as mf
    probe = mf.Manifold.cube([0.05, 0.05, 0.05]).translate([4.97, 2.97, 4.4])
    assert (probe ^ r2).volume() < 1e-12


def test_flush_eave_has_no_overhang():
    d = base_doc()
    d["elements"]["R"] = roof("R", [[0, 0], [4, 0], [4, 3], [0, 3]], ["flush-eave", "rake", "eave", "rake"])
    g, _ = parse(d)
    m = compile_genome(g)
    lo, _ = m.elements["R"].mesh.bounds()
    assert lo[1] == pytest.approx(0.0, abs=1e-6)  # flush on the south
    assert m.elements["R"].mesh.bounds()[1][1] == pytest.approx(3.3, abs=1e-6)


def test_three_way_junction_resolved_without_overlap():
    d = base_doc()
    # a through wall along y=0, two walls meeting it at the same point from both sides, plus an L corner
    d["elements"]["A"] = wall("A", (0, 0), (8, 0), align="center")
    d["elements"]["B"] = wall("B", (4, 0), (4, 3), align="center", h=2.5)
    d["elements"]["C"] = wall("C", (4, -3), (4, 0), align="center", h=2.8)
    g, _ = parse(d)
    m = compile_genome(g)
    assert m.ok, [i.message for i in m.issues.items]
    s = m._solids
    for a, b in (("A", "B"), ("A", "C"), ("B", "C")):
        assert (s[a] ^ s[b]).volume() < 1e-9
    # the through wall keeps its full length
    assert m.elements["A"].mesh.volume() == pytest.approx(8 * 0.2 * 3.0, abs=1e-6)
    assert "JUNCTION_MULTI_RESOLVED" in m.issues.codes()


def test_corner_with_collinear_continuation_does_not_protrude():
    d = base_doc()
    # L corner (outer faces aligned) plus a lower wall continuing the south wall line to the west
    d["elements"]["S"] = wall("S", (0, 0), (5, 0))
    d["elements"]["E"] = wall("E", (0, 4), (0, 0))  # outer face x=0, body east
    d["elements"]["P"] = wall("P", (-2, 0), (0, 0), h=2.0, t=0.1)
    g, _ = parse(d)
    m = compile_genome(g)
    assert m.ok, [i.message for i in m.issues.items]
    xs = m.elements["S"].mesh.verts[:, 0]
    assert xs.min() >= -1e-9  # S does not stick out past E's outer face into P
    s = m._solids
    assert (s["S"] ^ s["E"]).volume() < 1e-9 and (s["S"] ^ s["P"]).volume() < 1e-9
