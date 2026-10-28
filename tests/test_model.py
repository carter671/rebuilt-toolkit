"""A4–A9 — MODEL behaviour: real cuts, junctions, roof clipping, determinism, unsupported, incremental rebuild."""
import copy

import manifold3d as mf
import numpy as np
import pytest

from rebuilt.genome import changeset as CS
from rebuilt.genome.io import parse
from rebuilt.model.compile import CompileError, compile_genome

from .conftest import variant


def test_compiles_clean(model):
    assert model.ok
    assert not model.issues.warnings
    assert model.report()["counts"] == {"wall": 14, "opening": 12, "filling": 11, "slab": 3, "roof": 2, "space": 6}


def test_openings_are_real_voids(model):
    for op in model.by_type("opening"):
        wall = model._solids[op.data["host"]]
        # rebuild the void from the exported opening mesh (float32) and intersect with the cut wall
        m = op.mesh
        void = mf.Manifold(mf.Mesh(vert_properties=m.verts.astype(np.float32), tri_verts=m.tris.astype(np.uint32)))
        assert (wall ^ void).volume() < 1e-7, op.id  # float32 round-off only
        gross = model.elements[op.data["host"]].data["gross_volume"]
        assert gross > model.elements[op.data["host"]].data["volume"]


def test_wall_volume_equals_gross_minus_openings(model):
    for w in model.by_type("wall"):
        ops = [o for o in model.by_type("opening") if o.data["host"] == w.id]
        t = w.data["thickness"]
        cut = sum(o.data["width"] * o.data["height"] * t for o in ops)
        assert w.data["volume"] == pytest.approx(w.data["gross_volume"] - cut, abs=1e-7), w.id


def test_junction_classification(model):
    j = {w.id: (w.data["junctions"]["start"]["kind"], w.data["junctions"]["end"]["kind"]) for w in model.by_type("wall")}
    assert j["W-G-S"] == ("L", "L") and j["W-G-I1"] == ("T", "T") and j["W-G-BW"] == ("T", "L")
    assert j["W-U-I1"] == ("T", "T")
    s = model.elements["W-G-S"].data["butted_by"]
    assert {b[0] for b in s} == {"W-G-I1", "W-G-BW", "W-G-BE"}


def test_no_unexpected_overlaps(model):
    assert not ({"WALL_OVERLAP", "ELEMENT_OVERLAP", "SPACE_WALL_OVERLAP"} & model.issues.codes())


def test_gable_walls_under_roof(model):
    planes = [p["plane"] for p in model.elements["R-main"].data["panels"]]
    for wid in ("W-U-E", "W-U-W"):
        v = model.elements[wid].mesh.verts
        lim = np.min([a * v[:, 0] + b * v[:, 1] + c for a, b, c in planes], axis=0)
        assert (v[:, 2] <= lim + 1e-9).all()
        assert v[:, 2].max() == pytest.approx(5.55 + 3.6 * 2 / 3, abs=1e-6)  # ridge underside (planes vary in y only)


def test_deterministic_and_order_independent(genome, raw):
    a = compile_genome(genome).model_hash
    b = compile_genome(genome).model_hash
    d = copy.deepcopy(raw)
    d["elements"] = dict(reversed(list(d["elements"].items())))
    g2, _ = parse(d)
    c = compile_genome(g2).model_hash
    assert a == b == c


def test_unsupported_reported_not_dropped(raw):
    def mutate(d):
        d["elements"]["W-G-N"]["shape"] = "arc"
        d["elements"]["R-mud"]["footprint"] = [[3.425, -2.075], [6.575, -2.075], [6.575, -0.1], [5.0, -1.0], [3.425, -0.1]]
        d["elements"]["R-mud"]["edge_roles"] = ["eave", "rake", "abut", "abut", "rake"]
    g, _ = variant(raw, mutate)
    m = compile_genome(g)
    un = {u["element"]: u["reason"] for u in m.unsupported}
    assert "W-G-N" in un and "R-mud" in un
    assert "O-G-N-W3" in un  # hosted in the unsupported wall
    assert "W-G-BW" in un and "W-G-BE" in un  # attached to the unsupported roof
    assert "W-G-N" not in m.elements and "UNSUPPORTED_FEATURE" in m.issues.codes()


def test_conflicting_geometry_reported(raw):
    g, _ = variant(raw, lambda d: d["elements"]["O-U-N-W8"]["offset"].__setitem__("value", 4.0))  # under partition W-U-I1
    m = compile_genome(g)
    assert "OPENING_BLOCKED_BY_WALL" in m.issues.codes()
    g, _ = variant(raw, lambda d: d["elements"]["O-G-S-W1"]["offset"].__setitem__("value", 0.0))  # into the corner
    assert "OPENING_IN_JUNCTION" in compile_genome(g).issues.codes()
    g, _ = variant(raw, lambda d: d["elements"]["W-G-I1"]["thickness"].__setitem__("value", 0.5))  # partition swallows spaces
    assert "SPACE_WALL_OVERLAP" in compile_genome(g).issues.codes()


def test_validation_errors_block_compile(raw):
    g, _ = variant(raw, lambda d: d["elements"]["O-G-S-W1"]["offset"].__setitem__("value", 9.5))
    with pytest.raises(CompileError):
        compile_genome(g)


def test_incremental_rebuild(genome):
    cache = {}
    first = compile_genome(genome, cache=cache)
    assert first.reused == []
    cs = CS.make("t", "taller east wall", [CS.set_value_op("W-G-E", "height", 2.75, by="t")])
    g2, _ = CS.apply(genome, cs)
    second = compile_genome(g2, cache=cache)
    assert second.rebuilt == ["W-G-E"]
    assert "W-G-W" in second.reused and "R-main" in second.reused
    assert second.model_hash != first.model_hash
    assert compile_genome(g2).model_hash == second.model_hash  # cache never changes results


def test_provenance_carried(model):
    p = model.elements["W-U-S"].params["thickness"]
    assert p["basis"] == "inferred" and p["confidence"] == 0.7
    h = model.elements["W-G-BW"].params["height"]
    assert h["derived"] and h["basis"] == "observed" and "R-mud" in h["from"]
