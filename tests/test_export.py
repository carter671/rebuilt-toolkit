"""A10–A13 — IFC (with independent OpenCASCADE geometry check), GLB, PDF, export report."""
import json
import subprocess

import ifcopenshell
import ifcopenshell.util.element as U
import pygltflib
import pytest

from rebuilt.export.drawings import export_pdf
from rebuilt.export.glb import export_glb
from rebuilt.export.ifc import export_ifc
from rebuilt.export.ifc_validate import validate_ifc
from rebuilt.export.report import export_all
from rebuilt.genome import changeset as CS
from rebuilt.model.compile import compile_genome


@pytest.fixture(scope="module")
def ifc_path(model, genome, tmp_path_factory):
    p = tmp_path_factory.mktemp("ifc") / "house.ifc"
    export_ifc(model, genome, str(p))
    return p


def test_ifc_validates_independently(ifc_path, model):
    r = validate_ifc(str(ifc_path), model)
    failed = [c for c in r["checks"] if not c["ok"]]
    assert not failed, failed
    assert len(r["geometry"]) >= 30
    assert all(v["occ_volume"] > 0 for v in r["geometry"].values())


def test_ifc_semantics(ifc_path):
    f = ifcopenshell.open(str(ifc_path))
    assert f.schema == "IFC4"
    assert len(f.by_type("IfcWall")) == 14 and len(f.by_type("IfcWindow")) == 9 and len(f.by_type("IfcDoor")) == 2
    assert len(f.by_type("IfcRoof")) == 2 and len([s for s in f.by_type("IfcSlab") if s.PredefinedType == "ROOF"]) == 3
    assert len(f.by_type("IfcCovering")) == 1 and len(f.by_type("IfcSpace")) == 6
    w1 = next(o for o in f.by_type("IfcOpeningElement") if o.Name == "O-G-S-W1")
    host = w1.VoidsElements[0].RelatingBuildingElement
    assert U.get_psets(host)["Rebuilt_Identity"]["GenomeId"] == "W-G-S"
    assert w1.HasFillings[0].RelatedBuildingElement.is_a("IfcWindow")
    prov = U.get_psets(next(w for w in f.by_type("IfcWall") if w.Name == "Upper south wall"))["Rebuilt_Provenance"]
    assert prov["thickness.basis"] == "inferred" and prov["thickness.confidence"] == pytest.approx(0.7)
    gable = next(w for w in f.by_type("IfcWall") if w.Name == "Upper west gable wall")
    assert gable.Representation.Representations[0].RepresentationType == "Clipping"


def test_globalids_stable_across_revisions(genome, model, tmp_path):
    cs = CS.make("t", "edit", [CS.set_value_op("W-G-E", "thickness", 0.22, by="t")])
    g2, _ = CS.apply(genome, cs)
    m2 = compile_genome(g2)
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    export_ifc(model, genome, str(a))
    export_ifc(m2, g2, str(b))
    fa, fb = ifcopenshell.open(str(a)), ifcopenshell.open(str(b))
    ga = {e.GlobalId: e.Name for e in fa.by_type("IfcElement")}
    gb = {e.GlobalId: e.Name for e in fb.by_type("IfcElement")}
    assert ga == gb
    wb = next(e for e in fb.by_type("IfcWall") if e.Name == "Ground east wall")
    assert U.get_psets(wb)["Rebuilt_Identity"]["ElementRevision"] == 2


def test_glb_identity(model, genome, tmp_path):
    p = tmp_path / "m.glb"
    info = export_glb(model, genome, str(p))
    gl = pygltflib.GLTF2().load(str(p))
    ids = {n.extras["genome_id"] for n in gl.nodes}
    expected = {k for k, e in model.elements.items() if e.type != "opening"}
    assert ids == expected
    for n in gl.nodes:
        acc = gl.accessors[gl.meshes[n.mesh].primitives[0].attributes.POSITION]
        assert acc.count == 3 * info["triangles"][n.name]
    meta = json.loads((tmp_path / "m.meta.json").read_text())
    assert meta["elements"]["W-U-S"]["params"]["thickness"]["basis"] == "inferred"


def test_pdf_set(model, genome, tmp_path):
    p = tmp_path / "set.pdf"
    sheets = export_pdf(model, genome, str(p), ["note"])
    assert sheets == ["G-001", "A-001", "A-100", "A-101", "A-110", "A-201", "A-202", "A-301", "A-302", "A-401"]
    text = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True).stdout
    assert text.count("MODEL REVIEW DRAWING") == len(sheets)
    assert "33'-5 9/16\"" in text  # 10.200 m overall, from compiled outside faces
    assert "3'-11 1/4\"" in text  # W1 width 1.2 m in the opening schedule
    assert "8:12" in text and "3:12" in text


def test_export_report(model, genome, tmp_path):
    rep = export_all(model, genome, tmp_path, "m")
    t = rep["targets"]
    assert t["ifc"]["validation"]["ok"]
    for k in ("retained", "transformed", "approximated", "omitted"):
        assert t["ifc"][k] and t["glb"][k] and t["pdf"][k]
    assert t["revit"]["status"] == "not implemented"
