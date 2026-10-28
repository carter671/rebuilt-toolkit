"""Changesets: the only way Genome changes after creation.

A changeset is a list of JSON-Pointer ops with the previous value recorded, so it is reversible
and replayable. Applying bumps the rev of every touched element and the Genome revision number,
and appends a summary to revision.history. The full changesets live in <name>.changes.jsonl.
"""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
from pathlib import Path

from .io import parse, to_json
from .schema import Genome


class ChangeError(ValueError):
    pass


def _split(path: str) -> list[str]:
    if not path.startswith("/"):
        raise ChangeError(f"path must be a JSON pointer: {path}")
    return [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]


def _get(doc, parts):
    cur = doc
    for p in parts:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    return cur


def _set(doc, parts, value):
    parent = _get(doc, parts[:-1])
    k = parts[-1]
    if isinstance(parent, list):
        parent[int(k)] = value
    else:
        parent[k] = value


def _remove(doc, parts):
    parent = _get(doc, parts[:-1])
    if isinstance(parent, list):
        del parent[int(parts[-1])]
    else:
        del parent[parts[-1]]


def make(author: str, reason: str, ops: list[dict], source: str = "cli", at: str | None = None) -> dict:
    at = at or _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    body = {"author": author, "reason": reason, "source": source, "at": at, "ops": ops}
    cid = "cs-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    return {"id": cid, **body}


def apply(g: Genome, cs: dict) -> tuple[Genome, dict]:
    """Apply a changeset. Returns (new genome, the changeset with 'prev' filled in)."""
    doc = to_json(g)
    cs = copy.deepcopy(cs)
    touched = set()
    for op in cs["ops"]:
        parts = _split(op["path"])
        if parts[0] in ("revision",):
            raise ChangeError("revision is managed by the changeset system")
        if op["op"] == "set":
            try:
                op.setdefault("prev", copy.deepcopy(_get(doc, parts)))
            except (KeyError, IndexError):
                op.setdefault("prev", None)
            _set(doc, parts, op["value"])
        elif op["op"] == "add":
            try:
                _get(doc, parts)
                raise ChangeError(f"add: {op['path']} already exists")
            except (KeyError, IndexError):
                pass
            _set(doc, parts, op["value"])
            op["prev"] = None
        elif op["op"] == "remove":
            op["prev"] = copy.deepcopy(_get(doc, parts))
            _remove(doc, parts)
        else:
            raise ChangeError(f"unknown op {op['op']}")
        if parts[0] == "elements" and len(parts) > 1:
            touched.add(parts[1])
    for eid in sorted(touched):
        el = doc["elements"].get(eid)
        if el is not None and not any(o["op"] == "add" and o["path"] == f"/elements/{eid}" for o in cs["ops"]):
            el["rev"] = el.get("rev", 1) + 1
    rev = doc.setdefault("revision", {"number": 0, "history": []})
    rev["number"] = rev.get("number", 0) + 1
    rev.setdefault("history", []).append({
        "id": cs["id"], "number": rev["number"], "author": cs["author"], "at": cs["at"],
        "reason": cs["reason"], "source": cs.get("source", "cli"), "ops": len(cs["ops"]),
    })
    new, issues = parse(doc)
    if new is None:
        raise ChangeError("changeset produces an invalid genome: " + "; ".join(i.message for i in issues.errors))
    from .validate import validate

    errs = validate(new, "sketch").errors
    if errs:
        raise ChangeError("changeset produces an invalid genome: " + "; ".join(i.message for i in errs))
    return new, cs


def append_log(path: str | Path, cs: dict):
    with open(path, "a") as f:
        f.write(json.dumps(cs, sort_keys=True) + "\n")


def read_log(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def replay(base: Genome, log: list[dict]) -> Genome:
    g = base
    for cs in log:
        clean = {k: v for k, v in cs.items()}
        clean["ops"] = [{k: v for k, v in op.items() if k != "prev"} for op in cs["ops"]]
        g, _ = apply(g, clean)
    return g


def set_value_op(eid: str, param: str, value: float, basis="measured", verification="unverified",
                 uncertainty: float | None = None, observations=(), input_text=None, by="", reason="",
                 process="cli") -> dict:
    rec = {"value": value, "basis": basis, "verification": verification,
           "selection": {"by": by, "process": process, "reason": reason}}
    if uncertainty is not None:
        rec["uncertainty"] = {"kind": "pm", "value": uncertainty}
    if observations:
        rec["observations"] = list(observations)
    if input_text:
        rec["input"] = input_text
    return {"op": "set", "path": f"/elements/{eid}/{param}", "value": rec}
