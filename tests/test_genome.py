"""A1, A2 — Genome schema, layered validation, profiles, migrations, changesets."""
import pytest

from rebuilt.genome import changeset as CS
from rebuilt.genome.io import genome_hash, parse
from rebuilt.genome.migrate import MigrationError
from rebuilt.genome.validate import validate
from rebuilt.units import UnitError, fmt_ft_in, parse_length, parse_pitch

from .conftest import variant


def test_example_valid(genome):
    issues = validate(genome, "review")
    assert not issues.errors and not issues.warnings


@pytest.mark.parametrize("text,m", [("12' 6\"", 3.81), ("7 7/8\"", 0.200025), ("2'-11 7/16\"", 0.9001125),
                                    ("3' 11 1/4\"", 1.20015), ("150 mm", 0.15), ("3.2 m", 3.2), ("8'", 2.4384)])
def test_parse_length(text, m):
    assert parse_length(text) == pytest.approx(m, abs=1e-9)


def test_units_strict():
    with pytest.raises(UnitError):
        parse_length("12")
    with pytest.raises(UnitError):
        parse_length("5' 14\"")
    assert parse_pitch("8:12") == pytest.approx(2 / 3)
    assert fmt_ft_in(10.2) == "33'-5 9/16\""


def test_bare_numbers_become_assumed(raw):
    g, issues = variant(raw, lambda d: d["elements"]["W-G-S"].__setitem__("thickness", 0.2))
    assert g is not None
    assert "VALUE_SHORTHAND" in issues.codes()
    v = g.elements["W-G-S"].thickness
    assert v.basis == "assumed" and v.value == 0.2


def test_unknown_field_rejected(raw):
    g, issues = variant(raw, lambda d: d["elements"]["W-G-S"].__setitem__("colour", "red"))
    assert g is None and "SCHEMA_INVALID" in issues.codes()


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d["elements"]["O-G-S-W1"].__setitem__("host", "W-NOPE"), "REF_MISSING_HOST"),
    (lambda d: d["elements"]["O-G-S-W1"].__setitem__("host", "S-G-base"), "REF_HOST_NOT_WALL"),
    (lambda d: d["elements"]["W-G-S"].__setitem__("storey", "X"), "REF_MISSING_STOREY"),
    (lambda d: d["elements"]["W-G-S"].__setitem__("material", "mat-x"), "REF_MISSING_MATERIAL"),
    (lambda d: d["elements"]["O-G-S-W1"]["offset"].__setitem__("value", 9.5), "OPENING_OUTSIDE_HOST"),
    (lambda d: d["elements"]["O-G-S-W1"]["height"].__setitem__("value", 2.5), "OPENING_ABOVE_HOST"),
    (lambda d: d["elements"]["W-G-S"]["thickness"].__setitem__("value", -0.2), "NONPOSITIVE"),
    (lambda d: d["elements"]["W-G-S"]["thickness"].__setitem__("value", None), "VALUE_NULL_NOT_UNKNOWN"),
    (lambda d: d["elements"]["W-G-S"]["thickness"].__setitem__("verification", "disputed"), "DISPUTE_WITHOUT_CANDIDATES"),
    (lambda d: d["elements"]["S-G-base"].__setitem__("boundary", [[0, 0], [1, 1], [1, 0], [0, 1]]), "POLYGON_NOT_SIMPLE"),
    (lambda d: d["elements"]["S-G-base"].__setitem__("boundary", list(reversed(d["elements"]["S-G-base"]["boundary"]))), "POLYGON_NOT_CCW"),
    (lambda d: d.__setitem__("extensions", {"acme": {}}), "EXTENSION_UNDECLARED"),
    (lambda d: d["elements"]["SP-G-kitchen"].__setitem__("boundary", [[0.1, 3.0], [5.95, 3.0], [5.95, 6.9], [0.1, 6.9]]), "SPACE_OVERLAP"),
    (lambda d: d["elements"]["R-main"].__setitem__("edge_roles", ["eave", "rake", "eave"]), "ROOF_EDGE_ROLES"),
])
def test_validation_codes(raw, mutate, code):
    g, issues = variant(raw, mutate)
    if g is not None:
        issues.extend(validate(g, "review"))
    assert code in issues.codes(), issues.codes()


def test_profiles_progression(raw):
    def unknown(d):
        d["elements"]["R-main"]["thickness"] = {"value": None, "basis": "unknown"}
        d["elements"]["W-G-S"].pop("material")
    g, _ = variant(raw, unknown)
    assert not validate(g, "sketch").errors
    rv = validate(g, "review")
    assert not rv.errors and "PROFILE_DEFAULTED" in rv.codes()
    assert {"PROFILE_UNKNOWN", "PROFILE_NO_MATERIAL"} <= validate(g, "ifc-exchange").codes()
    assert "PROFILE_UNVERIFIED" in validate(g, "verified").codes()


def test_confidence_only_for_inference(raw):
    g, issues = variant(raw, lambda d: d["elements"]["W-G-S"]["thickness"].__setitem__("confidence", 0.9))
    assert g is None


def test_migration_and_version_refusal(raw):
    import copy
    d = copy.deepcopy(raw)
    d["schema_version"] = "0.0.3"
    op = d["elements"].pop("O-G-S-W1")
    d["openings"] = [op]
    g, issues = parse(d)
    assert g is not None and "O-G-S-W1" in g.elements and "MIGRATED" in issues.codes()
    d2 = copy.deepcopy(raw)
    d2["schema_version"] = "1.0.0"
    with pytest.raises(MigrationError):
        parse(d2)


def test_changeset_apply_bumps_and_replays(genome):
    cs = CS.make("tester", "fix", [CS.set_value_op("W-G-E", "thickness", 0.21, by="tester")], at="2026-01-01T00:00:00+00:00")
    g2, applied = CS.apply(genome, cs)
    assert g2.elements["W-G-E"].rev == genome.elements["W-G-E"].rev + 1
    assert g2.elements["W-G-W"].rev == genome.elements["W-G-W"].rev
    assert g2.revision.number == genome.revision.number + 1
    assert applied["ops"][0]["prev"]["value"] == 0.2  # previous value recorded (reversible)
    assert genome_hash(CS.replay(genome, [applied])) == genome_hash(g2)


def test_changeset_cannot_corrupt(genome):
    cs = CS.make("t", "bad", [{"op": "set", "path": "/elements/W-G-E/thickness/value", "value": -1}])
    with pytest.raises(CS.ChangeError):
        CS.apply(genome, cs)
