"""Capture pipeline: ingest → extract → register observations → reconcile → proposals → next-best.

Automation boundary (see docs/ARCHITECTURE.md §3):
  automatic: ingest/hash/manifest, extraction, registering sources + observations in Genome
             (evidence only — no building value changes), conflict and plausibility flags.
  review   : every change to a building value, any association that is not an exact id/tag/alias
             match, every dispute resolution, anything that would mark a value verified.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from ..genome import changeset as CS
from ..genome.schema import Genome, Value
from .extract import Extracted, parse_measurement_csv, parse_notes
from .store import EvidenceStore

BASIS_RANK = {"measured": 0, "extracted": 1, "observed": 2, "inferred": 3, "assumed": 4, "unknown": 5}
PROP_PARAM = {"thickness": "thickness", "width": "width", "height": "height", "sill": "sill", "pitch": "pitch",
              "overhang": "overhang"}


def _obs_id(source_id, locator, prop, idx):
    return "obs-" + hashlib.sha256(f"{source_id}|{locator}|{prop}|{idx}".encode()).hexdigest()[:10]


def extract_file(store: EvidenceStore, rec: dict, g: Genome) -> list[Extracted]:
    p = store.path_of(rec["source_id"])
    name = rec["filename"].lower()
    if name.endswith(".csv"):
        return parse_measurement_csv(p.read_text(), g)
    if name.endswith((".txt", ".md")):
        return parse_notes(p.read_text(), g, recorded_by=rec.get("provided_by", ""))
    return []  # photos/video/PDF drawings: registered as sources; extractors are M2


def register(g: Genome, store: EvidenceStore, records: list[dict], author: str):
    """Return (changeset adding sources+observations, extracted list with ids, unprocessed sources)."""
    ops, items, unprocessed = [], [], []
    for rec in records:
        sid = rec["source_id"]
        if sid not in g.sources:
            ops.append({"op": "add", "path": f"/sources/{sid}", "value": {
                "id": sid, "sha256": rec["sha256"], "filename": rec["filename"], "media_type": rec["media_type"],
                "description": rec.get("note", "")}})
        exs = extract_file(store, rec, g)
        if not exs:
            unprocessed.append({"source": sid, "filename": rec["filename"],
                                "reason": "no extractor for this media type yet (M2: photos, video, drawings)"})
        seen = {}
        for ex in exs:
            k = (ex.locator, ex.prop)
            seen[k] = seen.get(k, 0) + 1
            oid = _obs_id(sid, ex.locator, ex.prop, seen[k])
            items.append((oid, sid, ex))
            if oid in g.observations:
                continue
            ob = {"id": oid, "kind": ex.kind, "source": sid, "locator": ex.locator, "text": ex.text,
                  "recorded_by": ex.recorded_by, "status": "active"}
            if ex.subject:
                ob["subject"] = ex.subject
            if ex.prop:
                ob["property"] = ex.prop
            if ex.value is not None:
                ob["value"] = round(ex.value, 7)
                ob["uncertainty"] = {"kind": "pm", "value": round(ex.uncertainty, 6)}
            ops.append({"op": "add", "path": f"/observations/{oid}", "value": ob})
    cs = CS.make(author, "capture: register evidence and observations", ops, source="capture") if ops else None
    return cs, items, unprocessed


def _combine(obs: list[tuple[str, float, float]]):
    """Inverse-variance mean of (id, value, ±95% bound). Returns (value, ±95% bound)."""
    w = [1 / max(u / 1.96, 1e-6) ** 2 for _, _, u in obs]
    v = sum(wi * x for wi, (_, x, _) in zip(w, obs)) / sum(w)
    return v, 1.96 / math.sqrt(sum(w))


def reconcile(g: Genome, items) -> list[dict]:
    proposals = []

    def add(p):
        p["id"] = "prop-" + hashlib.sha256(json.dumps(p, sort_keys=True, default=str).encode()).hexdigest()[:8]
        p["status"] = "pending"
        proposals.append(p)

    groups: dict[tuple, list] = {}
    for oid, sid, ex in items:
        flags = [f for f in ex.flags if f.startswith("IMPLAUSIBLE")]
        if flags:
            add({"kind": "reject_observation", "observation": oid, "subject": ex.subject, "property": ex.prop,
                 "value": ex.value, "evidence": [_ev(oid, sid, ex)], "rationale": "; ".join(flags) +
                 " — likely a recording error; recommend reject and re-measure", "review_required": True})
            continue
        if ex.kind == "statement":
            if "REPORTED_UNKNOWN" in ex.flags:
                add({"kind": "note_unknown", "subject": ex.subject, "property": ex.prop, "evidence": [_ev(oid, sid, ex)],
                     "rationale": "field note reports this value could not be observed; keep basis as-is and request measurement",
                     "review_required": False})
            continue
        if ex.value is None or not ex.prop:
            continue
        if ex.subject is None:
            add({"kind": "associate", "observation": oid, "property": ex.prop, "value": ex.value,
                 "candidates": [{"element": c.element, "score": c.score, "reason": c.reason} for c in ex.candidates],
                 "evidence": [_ev(oid, sid, ex)],
                 "rationale": "no single unambiguous element; choose the subject(s)", "review_required": True})
            continue
        groups.setdefault((ex.subject, PROP_PARAM.get(ex.prop, ex.prop)), []).append((oid, sid, ex))

    for (subj, param), obs in sorted(groups.items()):
        el = g.elements[subj]
        cur: Value | None = getattr(el, param, None) if isinstance(getattr(el, param, None), Value) else None
        trip = [(oid, ex.value, ex.uncertainty) for oid, _, ex in obs]
        evid = [_ev(oid, sid, ex) for oid, sid, ex in obs]
        conflict = any(abs(a[1] - b[1]) > a[2] + b[2] for i, a in enumerate(trip) for b in trip[i + 1:])
        if conflict:
            add({"kind": "dispute", "subject": subj, "property": param, "current": _cur(cur),
                 "candidates": [{"value": v, "observations": [o], "uncertainty": u} for o, v, u in trip],
                 "evidence": evid, "rationale": f"{len(trip)} observations disagree beyond their combined uncertainty",
                 "review_required": True})
            continue
        val, unc = _combine(trip)
        basis = "measured" if any(ex.kind == "measurement" for _, _, ex in obs) else "observed"
        agrees = cur is not None and cur.value is not None and abs(cur.value - val) <= unc + (cur.uncertainty.value if cur.uncertainty else 0)
        better = cur is None or BASIS_RANK[basis] < BASIS_RANK[cur.basis] or (cur.uncertainty is None) or unc < cur.uncertainty.value
        kind = "corroborate" if agrees and not better else "set_value"
        add({"kind": kind, "subject": subj, "property": param, "current": _cur(cur),
             "proposed": {"value": round(val, 7), "basis": basis, "uncertainty": round(unc, 6),
                          "observations": [o for o, _, _ in trip]},
             "agrees_with_current": bool(agrees), "evidence": evid,
             "rationale": ("new evidence agrees with current value" if agrees else "evidence differs from current value")
             + ("; improves basis/uncertainty" if better else ""), "review_required": True})
    return proposals


def _ev(oid, sid, ex):
    return {"observation": oid, "source": sid, "locator": ex.locator, "excerpt": ex.text[:160], "raw_value": ex.raw_value}


def _cur(v: Value | None):
    if v is None:
        return None
    return {"value": v.value, "basis": v.basis, "verification": v.verification,
            "uncertainty": v.uncertainty.value if v.uncertainty else None}


ACTIONS = {
    "thickness": "Measure wall thickness at a door or window jamb (tape, ±1/16\")",
    "height": "Measure floor-to-ceiling / opening height with a tape or laser at two points",
    "width": "Measure rough-opening width inside the jambs",
    "sill": "Measure sill height from finished floor",
    "pitch": "Read pitch with a level and tape (rise over 12\") or pitch gauge on the rake",
    "overhang": "Measure eave overhang horizontally from wall face to fascia",
    "plate_height": "Measure from floor to the underside of the soffit / top plate at an exterior wall",
    "rake_overhang": "Measure rake overhang at a gable end",
    "offset": "Measure from the wall corner to the opening edge",
    "base_offset": "Check wall base elevation against the floor",
    "top_offset": "Measure ceiling height",
}


TYPE_ACTIONS = {
    ("roof", "thickness"): "Measure roof assembly depth at the fascia or rake edge, perpendicular to the slope",
    ("slab", "thickness"): "Measure slab/board thickness at an access hatch, register or fixture box",
    ("space", "height"): "Laser-measure floor to ceiling at two points in the room",
}


def next_best(g: Genome, model, reported_unknown: set = frozenset(), limit=12) -> list[dict]:
    out = []
    for eid, ce in model.elements.items():
        if ce.type in ("filling",):
            continue
        impact = {"wall": (ce.data.get("length", 1) * (ce.data.get("height") or 2.5)) / 10, "roof": ce.data.get("volume", 1) / 2,
                  "slab": ce.data.get("area", 1) / 20, "space": ce.data.get("area", 1) / 20, "opening": 0.5}.get(ce.type, 0.5)
        for p, rec in ce.params.items():
            if rec.get("derived"):
                continue
            b = "assumed" if rec.get("defaulted") else rec.get("basis", "assumed")
            score = BASIS_RANK.get(b, 4) + (12 if rec.get("verification") == "disputed" else 0) + (2 if (eid, p) in reported_unknown else 0)
            if score <= 1:
                continue
            out.append({"element": eid, "param": p, "basis": b, "verification": rec.get("verification"),
                        "score": round(score * (1 + impact), 3), "action": TYPE_ACTIONS.get((ce.type, p), ACTIONS.get(p, f"Measure {p}")),
                        "why": f"{b}{' / disputed' if rec.get('verification') == 'disputed' else ''}; impact {impact:.2f}"})
    out.sort(key=lambda r: (-r["score"], r["element"], r["param"]))
    return out[:limit]


def run_capture(g: Genome, store_root: str | Path, files: list[tuple[str, str]], author: str):
    """files: [(path, provided_by)]. Returns (new genome, register changeset, proposals, unprocessed)."""
    store = EvidenceStore(store_root)
    recs = [store.ingest(p, provided_by=by)[0] for p, by in files]
    cs, items, unprocessed = register(g, store, recs, author)
    if cs:
        g, cs = CS.apply(g, cs)
    proposals = reconcile(g, items)
    return g, cs, proposals, unprocessed
