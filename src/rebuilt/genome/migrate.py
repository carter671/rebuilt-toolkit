"""Schema migrations. Each migration is a pure function on raw JSON; loaders migrate forward.

Rules:
- Same major version: forward migration is automatic and recorded.
- Different (higher) major version than this code knows: refused.
- A migration never invents measurement data; new required fields get basis "unknown" or a
  documented default with basis "assumed".
"""
from __future__ import annotations

from .schema import SCHEMA_VERSION


class MigrationError(ValueError):
    pass


def _v(s: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in s.split("."))
    return a, b, c


def _m_0_0_x_to_0_1_0(doc: dict) -> dict:
    # Pre-release drafts used "openings" as a top-level list; fold into elements.
    for o in doc.pop("openings", []) or []:
        o.setdefault("type", "opening")
        doc.setdefault("elements", {})[o["id"]] = o
    doc["schema_version"] = "0.1.0"
    return doc


def _m_0_1_x_to_0_2_0(doc: dict) -> dict:
    # 0.2 only adds optional structures (info, components, finishes, families, capture): no data changes.
    doc["schema_version"] = "0.2.0"
    return doc


MIGRATIONS = [((0, 0), "0.1.0", _m_0_0_x_to_0_1_0), ((0, 1), "0.2.0", _m_0_1_x_to_0_2_0)]


def migrate(doc: dict) -> tuple[dict, list[str]]:
    notes = []
    ver = doc.get("schema_version", "0.0.0")
    cur = _v(SCHEMA_VERSION)
    if _v(ver)[0] > cur[0] or _v(ver) > cur:
        raise MigrationError(f"document schema {ver} is newer than supported {SCHEMA_VERSION}")
    for (maj, minr), target, fn in MIGRATIONS:
        v = _v(doc.get("schema_version", "0.0.0"))
        if (v[0], v[1]) == (maj, minr) and v < _v(target):
            doc = fn(doc)
            notes.append(f"migrated {'.'.join(map(str, v))} -> {target}")
    return doc, notes
