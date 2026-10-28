"""Loading, normalising, migrating and saving Genome documents."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from ..issues import IssueList
from ..units import UnitError, parse_length, parse_pitch
from .migrate import migrate
from .schema import Genome

VALUE_KEYS = {
    "elevation", "height", "thickness", "base_offset", "offset", "width", "sill", "top_offset",
    "pitch", "plate_height", "overhang", "rake_overhang", "true_north_deg",
}


def _normalise_values(node, path: str, issues: IssueList):
    """Convert shorthand (bare numbers / unit strings) into Value records with basis=assumed."""
    if isinstance(node, dict):
        for k in list(node.keys()):
            v = node[k]
            p = f"{path}/{k}"
            if k in VALUE_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                node[k] = {"value": float(v), "basis": "assumed"}
                issues.add("VALUE_SHORTHAND", "warning",
                           f"bare number at {p} normalised to basis 'assumed'", path=p, layer="schema")
            elif k in VALUE_KEYS and isinstance(v, str):
                try:
                    num = parse_pitch(v) if k == "pitch" else parse_length(v)
                except UnitError as e:
                    issues.add("UNIT_UNPARSEABLE", "error", f"{p}: {e}", path=p, layer="units")
                    continue
                node[k] = {"value": num, "basis": "assumed", "input": v}
                issues.add("VALUE_SHORTHAND", "warning",
                           f"string '{v}' at {p} normalised to basis 'assumed'", path=p, layer="schema")
            else:
                _normalise_values(v, p, issues)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _normalise_values(v, f"{path}/{i}", issues)


def parse(raw: dict) -> tuple[Genome | None, IssueList]:
    issues = IssueList()
    doc = copy.deepcopy(raw)
    doc, mig_notes = migrate(doc)
    for n in mig_notes:
        issues.add("MIGRATED", "info", n, layer="schema")
    for k in ("elements", "buildings", "project"):
        if k in doc:
            _normalise_values(doc[k], f"/{k}", issues)
    if issues.errors:
        return None, issues
    try:
        g = Genome.model_validate(doc)
    except ValidationError as e:
        for err in e.errors():
            loc = "/" + "/".join(str(x) for x in err["loc"])
            issues.add("SCHEMA_INVALID", "error", f"{loc}: {err['msg']}", path=loc, layer="schema")
        return None, issues
    # element ids must match their dict keys
    for k, el in g.elements.items():
        if el.id != k:
            issues.add("ID_KEY_MISMATCH", "error", f"element key '{k}' != id '{el.id}'", (k,), layer="schema")
    return g, issues


def load(path: str | Path) -> tuple[Genome | None, IssueList]:
    return parse(json.loads(Path(path).read_text()))


def to_json(g: Genome) -> dict:
    return g.model_dump(mode="json", exclude_none=True)


def dumps(g: Genome) -> str:
    return json.dumps(to_json(g), indent=2, sort_keys=False) + "\n"


def save(g: Genome, path: str | Path):
    Path(path).write_text(dumps(g))


def genome_hash(g: Genome) -> str:
    return hashlib.sha256(json.dumps(to_json(g), sort_keys=True).encode()).hexdigest()
