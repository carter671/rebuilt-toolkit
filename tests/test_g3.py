"""G3 detail (Genome 0.2): components, information blocks, finishes — compile, IFC, GLB, drawings."""
import ifcopenshell
import ifcopenshell.util.element as U
import pytest

from rebuilt.export.drawings import export_pdf
from rebuilt.export.glb import element_colors, export_glb
from rebuilt.export.ifc import export_ifc
from rebuilt.export.ifc_validate import validate_ifc
from rebuilt.genome.io import parse
from rebuilt.model.compile import compile_genome


def M(v):
    return {"value": v, "basis": "measured"}


def O(v):
    return {"value": v, "basis": "observed", "confidence": 0.7, "verification": "verified"}


def wall(eid, s, e, top=None):
    d = {"type": "wall", "id": eid, "storey": "G", "start": list(s), "end": list(e), "thickness": M(0.2), "height": M(3.0),
         "alignment": "right", "exterior": True, "material": "frame"}
    if top:
        d["top"] = {"attach": top}
    return d


def comp(eid, kind, placement, size=None, **kw):
    d = {"type": "component", "id": eid, "storey": "G", "kind": kind, "placement": placement}
    if size:
        d["size"] = {k: O(v) for k, v in size.items()}
    d.update(kw)
    return d


def doc():
    E = {
        "S": wall("S", (0, 0), (8, 0)), "E": wall("E", (8, 0), (8, 6), top="R"),
        "N": wall("N", (8, 6), (0, 6)), "W": wall("W", (0, 6), (0, 0), top="R"),
        "F": {"type": "slab", "id": "F", "storey": "G", "kind": "base", "boundary": [[0, 0], [8, 0], [8, 6], [0, 6]], "thickness": M(0.2)},
        "R": {"type": "roof", "id": "R", "storey": "G", "form": "gable", "footprint": [[0, 0], [8, 0], [8, 6], [0, 6]],
              "edge_roles": ["eave", "rake", "eave", "rake"], "pitch": M(0.5), "plate_height": M(3.0), "overhang": M(0.3),
              "rake_overhang": M(0.15), "thickness": M(0.15)},
        "W1": {"type": "opening", "id": "W1", "host": "S", "kind": "window", "offset": M(2.0), "width": M(1.0), "height": M(1.4),
               "sill": M(0.9), "filling": {"type": "window", "operation": "double-hung"},
               "unit": {"type": "double-hung", "lites": "2/2", "frame_material": "wood", "storm": True}},
        "SP": {"type": "space", "id": "SP", "storey": "G", "name": "Room", "boundary": [[0.2, 0.2], [7.8, 0.2], [7.8, 5.8], [0.2, 5.8]],
               "height": M(2.7), "surfaces": {"walls": {"material": "plaster", "finish": "body"}}},
        "CL": comp("CL", "cladding", {"on": "wall", "wall": "S", "u": O(0), "z": O(0)}, hosts=["S", "E", "N", "W"], geometry="none",
                   properties={"exposure": O(0.165)}, info={"category": "siding", "subtype": "wood bevel lap", "finish": "body"}),
        "CB1": comp("CB1", "trim", {"on": "corner", "walls": ["S", "E"]}, {"w": 0.14, "d": 0.025}, info={"subtype": "corner board", "finish": "trim"}),
        "CS1": comp("CS1", "trim", {"on": "opening", "opening": "W1", "position": "surround"}, {"w": 0.1, "d": 0.02}, info={"finish": "trim"}),
        "SH1": comp("SH1", "shutter", {"on": "opening", "opening": "W1", "position": "both", "gap": O(0.1)}, {"w": 0.38, "d": 0.025},
                    info={"finish": "shutter", "condition": {"rating": "fair"}}),
        "FA": comp("FA", "fascia", {"on": "roof_edge", "roof": "R", "edges": [0, 2]}, {"h": 0.14, "d": 0.02}, info={"finish": "trim"}),
        "RK": comp("RK", "trim", {"on": "roof_edge", "roof": "R", "edges": [1, 3]}, {"h": 0.14, "d": 0.02}, info={"subtype": "rake board"}),
        "GU": comp("GU", "gutter", {"on": "roof_edge", "roof": "R", "edges": [0, 2], "gap": O(0.02)}, {"h": 0.127, "d": 0.127}),
        "SO": comp("SO", "soffit", {"on": "roof_edge", "roof": "R", "edges": [0, 1, 2, 3]}, {"h": 0.016}),
        "DS": comp("DS", "downspout", {"on": "point", "at": [7.9, -0.1], "z": O(0.0)}, {"w": 0.076, "d": 0.05, "h": 2.6}),
        "CH": comp("CH", "chimney", {"on": "point", "at": [2.0, 3.0], "z": O(2.5)}, {"w": 0.6, "d": 0.6, "h": 2.5},
                   info={"material": "brick", "finish": "brick"}),
        "LT": comp("LT", "fixture", {"on": "wall", "wall": "S", "u": O(5.0), "z": O(2.0)}, {"w": 0.15, "h": 0.25, "d": 0.15},
                   info={"category": "exterior_light", "subtype": "coach lantern", "finish": "black",
                         "observed": {"date": "2026-10-15", "by": "tester", "photos": ["ph1"]}}),
        "AP": comp("AP", "fixture", {"on": "space", "space": "SP", "location": "under the window"}, geometry="none",
                   info={"category": "register", "subtype": "floor register"}),
    }
    return {
        "schema_version": "0.1.0",  # migrates forward to 0.2.0
        "project": {"id": "t-g3", "name": "G3 detail test", "fictional": True},
        "property": {"id": "p"},
        "buildings": [{"id": "B", "name": "b", "storeys": [{"id": "G", "name": "G", "elevation": M(0.0), "height": M(3.0)}]}],
        "materials": {"frame": {"id": "frame", "name": "Wood frame", "category": "wood"}}, "elements": E,
        "sources": {"ph1": {"id": "ph1", "sha256": "0" * 64, "filename": "front.jpg", "media_type": "image/jpeg"}},
        "finishes": {"body": {"id": "body", "name": "Sage body", "hex": "#9EA691"}, "trim": {"id": "trim", "name": "Trim white", "hex": "#E4E6DC"},
                     "shutter": {"id": "shutter", "name": "Light sage", "hex": "#B5BDAE"}, "brick": {"id": "brick", "name": "Red brick", "hex": "#8E5A50"},
                     "black": {"id": "black", "name": "Black", "hex": "#1E1E1E"}},
        "capture": {"epoch": 1, "closed": True, "closed_by": "tester", "note": "test"},
    }


@pytest.fixture(scope="module")
def gm():
    g, issues = parse(doc())
    assert g is not None, [i.message for i in issues.items]
    assert g.schema_version == "0.2.0"
    return g, compile_genome(g)


def test_components_compile_outside_hosts(gm):
    g, m = gm
    assert m.ok, [i.message for i in m.issues.errors]
    codes = m.issues.codes()
    assert "COMPONENT_INTERSECTS" not in codes, [i.message for i in m.issues.items if i.code == "COMPONENT_INTERSECTS"]
    assert "COMPONENT_NOT_PLACED" not in codes
    for k in ("CB1", "CS1", "SH1", "FA", "RK", "GU", "SO", "DS", "CH", "LT"):
        assert m.elements[k].mesh is not None and m.elements[k].mesh.volume() > 0, k
    for k in ("CL", "AP"):
        assert m.elements[k].mesh is None
    # exterior side detected: window casing and shutters sit south of the south wall's outer face (y = 0)
    assert m.elements["CS1"].mesh.bounds()[1][1] <= 1e-9
    assert m.elements["SH1"].data["pieces"] == 2
    lo, hi = m.elements["CB1"].mesh.bounds()
    assert hi[0] > 8.0 and lo[1] < 0.0  # wraps the SE outside corner
    assert m.elements["GU"].mesh.bounds()[0][1] < -0.3 - 0.02  # outside the fascia line
    assert m.elements["CL"].data["exposure"] == pytest.approx(0.165)


def test_chimney_cuts_roof(gm):
    g, m = gm
    assert m.elements["R"].data["cut_by"] == ["CH"]
    assert (m._solids["R"] ^ m._solids["CH"]).volume() < 1e-9
    assert m.elements["CH"].data["top_z"] > m.elements["R"].data["top_z"] - 0.2


def test_component_ifc_classes_info_and_validation(gm, tmp_path):
    g, m = gm
    p = tmp_path / "g3.ifc"
    export_ifc(m, g, str(p))
    f = ifcopenshell.open(str(p))
    by = {e.Tag: e for e in f.by_type("IfcElement") if getattr(e, "Tag", None)}
    assert by["CH"].is_a("IfcChimney")
    assert by["SH1"].is_a("IfcShadingDevice") and by["SH1"].PredefinedType == "SHUTTER"
    assert by["GU"].is_a("IfcPipeSegment") and by["GU"].PredefinedType == "GUTTER"
    assert by["LT"].is_a("IfcLightFixture")
    assert by["CL"].is_a("IfcCovering") and by["CL"].PredefinedType == "CLADDING"
    assert len(f.by_type("IfcRelCoversBldgElements")) == 4
    assert U.get_container(by["AP"]).is_a("IfcSpace")
    info = U.get_psets(by["LT"])["Rebuilt_Info"]
    assert info["Finish"].startswith("Black") and info["ObservedPhotos"] == "ph1"
    assert "Rebuilt_OpeningUnit" in U.get_psets(next(e for e in f.by_type("IfcWindow")))
    assert "Rebuilt_Surface_walls" in U.get_psets(next(e for e in f.by_type("IfcSpace")))
    rep = validate_ifc(str(p), m)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]


def test_finish_colours_in_glb_and_drawings(gm, tmp_path):
    g, m = gm
    cols = element_colors(m, g)
    assert cols["LT"] == "#1E1E1E" and cols["S"] == "#9EA691" and cols["CH"] == "#8E5A50"
    export_glb(m, g, str(tmp_path / "g3.glb"))
    sheets = export_pdf(m, g, str(tmp_path / "g3.pdf"))
    assert "A-501" in sheets


def test_inside_corner_boards_run_along_the_exterior_face():
    d = doc()
    # an L-shaped wing: a wall running north from the middle of the north wall makes an inside corner
    d["elements"]["X"] = wall("X", (5, 6), (5, 9))
    d["elements"]["X"]["alignment"] = "left"  # outer (west) face on the baseline, body to the east
    d["elements"]["IC"] = comp("IC", "trim", {"on": "corner", "walls": ["N", "X"], "sides": ["right", "left"]}, {"w": 0.14, "d": 0.025})
    g, _ = parse(d)
    m = compile_genome(g)
    ic = m.elements["IC"]
    assert ic.data["inside_corner"] is True
    lo, hi = ic.mesh.bounds()
    # board on N's north face runs west of x=5 (outside the wing), board on X's west face runs north of y=6
    assert hi[0] <= 5.0 + 1e-9 and lo[1] >= 6.0 - 1e-9
    assert "COMPONENT_INTERSECTS" not in m.issues.codes()


def test_close_capture_verifies_everything_and_keeps_basis(tmp_path):
    import json

    from rebuilt.review.project import Project

    d = doc()
    d["elements"]["W1"]["width"] = {"value": 1.0, "basis": "measured", "verification": "disputed",
                                    "conflicts": [{"value": 1.0, "note": "tape"}, {"value": 0.9, "note": "drawing"}]}
    src = tmp_path / "g.json"
    src.write_text(json.dumps(d))
    p = Project.init(tmp_path / "proj", src)
    g = p.close_capture("Owner", "capture closed for test")
    assert g.capture.closed and g.capture.closed_by == "Owner"
    w = g.elements["W1"].width
    assert w.verification == "verified" and w.basis == "measured" and len(w.conflicts) == 2
    assert g.elements["CH"].size.w.basis == "observed" and g.elements["CH"].size.w.verification == "verified"
    assert g.elements["CL"].properties["exposure"].verification == "verified"
    assert g.storey("G").height.verification == "verified"
    assert p.verify_replay()
