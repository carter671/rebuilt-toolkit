"""B1–B4 (text evidence) and A14 — Capture against the controlled evidence set's ground truth,
then the review → changeset → recompile → export loop."""
import json
import shutil

import pytest

from rebuilt.capture.extract import parse_measurement_csv, parse_notes
from rebuilt.capture.pipeline import next_best, run_capture
from rebuilt.capture.store import EvidenceStore
from rebuilt.export.ifc import export_ifc
from rebuilt.export.ifc_validate import validate_ifc
from rebuilt.genome.validate import validate
from rebuilt.model.compile import compile_genome
from rebuilt.review.project import Project

from .conftest import EVIDENCE, HOUSE

TRUTH = json.loads((EVIDENCE / "truth.json").read_text())


def _extract_all(genome):
    return {"field_notes.txt": parse_notes((EVIDENCE / "field_notes.txt").read_text(), genome),
            "measurements.csv": parse_measurement_csv((EVIDENCE / "measurements.csv").read_text(), genome)}


def test_extraction_against_truth(genome):
    """Values, units and properties: every truth row must be found exactly once with the right value."""
    got = _extract_all(genome)
    found = correct_val = correct_assoc = 0
    total = 0
    for fname, rows in TRUTH.items():
        if not fname.endswith((".txt", ".csv")):
            continue
        for t in rows:
            total += 1
            cands = [e for e in got[fname] if e.locator == t["locator"] and e.prop == t["property"]]
            if not cands:
                continue
            e = cands[0]
            found += 1
            if t["value"] is None or (e.value is not None and abs(e.value - t["value"]) < 1e-6):
                correct_val += 1
            subj = t["subject"]
            if subj == "AMBIGUOUS":
                ok = e.subject is None and len(e.candidates) >= 2
            elif isinstance(subj, list):
                ok = e.subject is None and set(subj) <= {c.element for c in e.candidates}
            elif e.kind == "statement":
                ok = subj in {c.element for c in e.candidates}
            else:
                ok = e.subject == subj
            correct_assoc += ok
            for flag in [t.get("expect_flag")] if t.get("expect_flag") else []:
                assert any(f.startswith(flag) for f in e.flags), (t, e.flags)
    assert found == total
    assert correct_val / total >= 0.95  # B2
    assert correct_assoc / total >= 0.90  # B3
    extra = sum(len(v) for v in got.values()) - total
    assert extra == 0, "no spurious observations"


def test_store_immutable_and_dedup(tmp_path):
    s = EvidenceStore(tmp_path / "ev")
    r1, new1 = s.ingest(EVIDENCE / "field_notes.txt", provided_by="A")
    copy = tmp_path / "renamed_copy.txt"
    shutil.copy(EVIDENCE / "field_notes.txt", copy)
    r2, new2 = s.ingest(copy, provided_by="B")
    assert new1 and not new2 and r1["source_id"] == r2["source_id"]
    assert s.verify() == []
    assert not (s.path_of(r1["source_id"]).stat().st_mode & 0o222)


@pytest.fixture()
def project(tmp_path):
    return Project.init(tmp_path / "proj", HOUSE)


def _by(props, kind, subject=None, prop=None):
    return [p for p in props if p["kind"] == kind and (subject is None or p.get("subject") == subject)
            and (prop is None or p.get("property") == prop)]


def test_capture_review_loop(project):
    g0 = project.genome()
    g, cs, props, unproc = run_capture(g0, project.evidence, [(EVIDENCE / "field_notes.txt", "Field tech A"),
                                                             (EVIDENCE / "measurements.csv", "Crew B")], "tester")
    project.record_applied(g, cs)
    project.add_proposals(props)
    # automatic step changed evidence only, never building values
    for eid, el in g0.elements.items():
        assert el.model_dump(exclude={"rev"}) == g.elements[eid].model_dump(exclude={"rev"})
    assert len(g.observations) == 17 and len(g.sources) == 2
    # B4: planted conflict and typo
    assert _by(props, "dispute", "O-G-S-W1", "width")
    assert _by(props, "reject_observation", "W-G-I1", "thickness")
    assert all(p["review_required"] for p in props if p["kind"] in ("set_value", "dispute", "associate", "reject_observation"))

    pid = _by(project.proposals(), "set_value", "W-U-S", "thickness")[0]["id"]
    project.decide(pid, "accept", "Reviewer", "tape at jamb")
    pid = _by(project.proposals(), "dispute", "O-G-S-W1", "width")[0]["id"]
    project.decide(pid, "dispute", "Reviewer", "need a third measurement")
    g = project.genome()
    w1 = g.elements["O-G-S-W1"].width
    assert w1.verification == "disputed" and len(w1.conflicts) == 2 and w1.value == 1.2  # value not replaced
    assert g.elements["W-U-S"].thickness.basis == "measured" and g.elements["W-U-S"].thickness.observations
    m = compile_genome(g)  # disputed allowed under 'review' profile
    assert m.ok
    assert "PROFILE_DISPUTED" in validate(g, "ifc-exchange").codes()  # but blocks the exchange profile

    # resolve with a reviewer correction; the change flows to the model and the IFC
    project.edit("O-G-S-W1", "width", "3' 11 5/8\"", "Reviewer", "third measurement resolves dispute")
    g = project.genome()
    assert g.elements["O-G-S-W1"].width.value == pytest.approx(1.2097, abs=1e-4)
    assert g.elements["O-G-S-W1"].width.verification == "unverified"
    m = compile_genome(g)
    assert m.elements["O-G-S-W1"].data["width"] == pytest.approx(1.2097, abs=1e-4)
    p = project.root / "rev.ifc"
    export_ifc(m, g, str(p))
    assert validate_ifc(str(p), m)["ok"]
    # A14: the log replays to the identical genome
    assert project.verify_replay()

    # next-best measurement list ranks the assumed roof thickness first
    nb = next_best(g, m)
    assert nb[0]["element"] == "R-main" and nb[0]["param"] == "thickness"


def test_verify_requires_resolution(project):
    project.verify_value("W-G-S", "thickness", "Reviewer", "checked on site")
    assert project.genome().elements["W-G-S"].thickness.verification == "verified"
    assert project.genome().elements["W-G-S"].thickness.basis == "measured"  # verification does not change basis
