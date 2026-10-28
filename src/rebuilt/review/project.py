"""A Rebuilt project directory and the review workflow.

<project>/
  base.genome.json   the Genome as first created (never edited)
  genome.json        current Genome (== base + replay(changes.jsonl), checked by `verify_replay`)
  changes.jsonl      append-only changesets with author, reason and previous values
  proposals.json     Capture proposals and their review status
  evidence/          content-addressed evidence store (see capture/store.py)
  out/               generated model + exports (disposable; regenerate from genome.json)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..genome import changeset as CS
from ..genome.io import genome_hash, load, save, to_json
from ..genome.schema import Genome, Value
from ..units import parse_length, parse_pitch


class ReviewError(ValueError):
    pass


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.genome_path = self.root / "genome.json"
        self.base_path = self.root / "base.genome.json"
        self.log_path = self.root / "changes.jsonl"
        self.proposals_path = self.root / "proposals.json"
        self.evidence = self.root / "evidence"
        self.out = self.root / "out"

    @classmethod
    def init(cls, root, genome_file) -> "Project":
        p = cls(root)
        p.root.mkdir(parents=True, exist_ok=True)
        g, issues = load(genome_file)
        if g is None:
            raise ReviewError("; ".join(i.message for i in issues.errors))
        save(g, p.base_path)
        save(g, p.genome_path)
        p.log_path.write_text("")
        p.proposals_path.write_text("[]\n")
        return p

    def genome(self) -> Genome:
        g, issues = load(self.genome_path)
        if g is None:
            raise ReviewError("; ".join(i.message for i in issues.errors))
        return g

    def apply(self, cs: dict) -> Genome:
        g, cs = CS.apply(self.genome(), cs)
        save(g, self.genome_path)
        CS.append_log(self.log_path, cs)
        return g

    def record_applied(self, g: Genome, cs: dict):
        """For changesets already applied in memory (e.g. by capture)."""
        save(g, self.genome_path)
        CS.append_log(self.log_path, cs)

    def verify_replay(self) -> bool:
        base, _ = load(self.base_path)
        return genome_hash(CS.replay(base, CS.read_log(self.log_path))) == genome_hash(self.genome())

    # ---------------------------------------------------------- proposals
    def proposals(self) -> list[dict]:
        return json.loads(self.proposals_path.read_text()) if self.proposals_path.exists() else []

    def save_proposals(self, props):
        self.proposals_path.write_text(json.dumps(props, indent=1, default=float) + "\n")

    def add_proposals(self, new):
        cur = self.proposals()
        ids = {p["id"] for p in cur}
        cur += [p for p in new if p["id"] not in ids]
        self.save_proposals(cur)

    def _find(self, pid):
        props = self.proposals()
        for p in props:
            if p["id"] == pid:
                return props, p
        raise ReviewError(f"no proposal {pid}")

    def decide(self, pid: str, decision: str, by: str, reason: str = "", value: float | None = None,
               candidate: int | None = None, subjects: list[str] | None = None) -> Genome | None:
        """decision: accept | reject | dispute. `value` overrides (a correction); `candidate` picks a
        dispute candidate; `subjects` resolves an 'associate' proposal."""
        props, p = self._find(pid)
        if p["status"] != "pending":
            raise ReviewError(f"{pid} already {p['status']}")
        g = self.genome()
        ops = []
        sel = {"by": by, "process": "review", "reason": reason or p.get("rationale", "")}
        if decision == "reject":
            if p["kind"] == "reject_observation":
                raise ReviewError("use accept to reject the flagged observation, or 'keep' via dispute")
            p["status"] = "rejected"
        elif p["kind"] == "reject_observation":
            ops.append({"op": "set", "path": f"/observations/{p['observation']}/status", "value": "rejected"})
            p["status"] = "accepted"
        elif p["kind"] == "note_unknown":
            p["status"] = "acknowledged"
        elif p["kind"] in ("set_value", "corroborate"):
            pr = p["proposed"]
            cur = getattr(g.elements[p["subject"]], p["property"])
            obs = sorted(set((cur.observations if isinstance(cur, Value) else []) + pr["observations"]))
            if p["kind"] == "corroborate" and value is None:
                rec = cur.model_dump(mode="json", exclude_none=True)
                rec["observations"] = obs
            else:
                rec = {"value": value if value is not None else pr["value"], "basis": pr["basis"],
                       "verification": "unverified", "uncertainty": {"kind": "pm", "value": pr["uncertainty"]},
                       "observations": obs, "selection": sel}
                if value is not None:
                    rec["selection"]["reason"] = (reason or "") + " [value corrected by reviewer]"
            ops.append({"op": "set", "path": f"/elements/{p['subject']}/{p['property']}", "value": rec})
            p["status"] = "accepted" if value is None else "corrected"
        elif p["kind"] == "dispute":
            cands = [{"value": c["value"], "observations": c["observations"], "note": f"±{c['uncertainty']:.4f}"} for c in p["candidates"]]
            cur = getattr(g.elements[p["subject"]], p["property"])
            obs = sorted(set(cur.observations + [o for c in p["candidates"] for o in c["observations"]]))
            if decision == "dispute" or (candidate is None and value is None):
                rec = cur.model_dump(mode="json", exclude_none=True)
                rec.update({"verification": "disputed", "conflicts": cands, "observations": obs})
                p["status"] = "held-disputed"
            else:
                c = p["candidates"][candidate] if candidate is not None else None
                rec = {"value": value if value is not None else c["value"], "basis": "measured", "verification": "unverified",
                       "uncertainty": {"kind": "pm", "value": c["uncertainty"] if c else 0.003},
                       "observations": obs, "conflicts": cands, "selection": sel}
                p["status"] = "resolved"
            ops.append({"op": "set", "path": f"/elements/{p['subject']}/{p['property']}", "value": rec})
        elif p["kind"] == "associate":
            if not subjects:
                raise ReviewError("associate requires subjects")
            for s in subjects:
                cur = getattr(g.elements[s], p["property"], None)
                ob = g.observations[p["observation"]]
                u = ob.uncertainty.value if ob.uncertainty else None
                basis = "measured" if ob.kind == "measurement" else "observed"
                rec = {"value": value if value is not None else p["value"], "basis": basis, "verification": "unverified",
                       "observations": sorted(set((cur.observations if isinstance(cur, Value) else []) + [p["observation"]])),
                       "selection": sel}
                if u is not None:
                    rec["uncertainty"] = {"kind": "pm", "value": u}
                if basis == "observed":
                    rec["confidence"] = 0.6
                ops.append({"op": "set", "path": f"/elements/{s}/{p['property']}", "value": rec})
            if len(subjects) == 1:
                ops.append({"op": "set", "path": f"/observations/{p['observation']}/subject", "value": subjects[0]})
            p["status"] = "accepted"
            p["resolved_subjects"] = subjects
        else:
            raise ReviewError(f"cannot {decision} a {p['kind']} proposal")
        p["decided_by"], p["decision_reason"] = by, reason
        if ops:
            cs = CS.make(by, f"review {pid} ({p['kind']}): {reason}".strip(), ops, source="review")
            g = self.apply(cs)
            p["changeset"] = cs["id"]
        self.save_proposals(props)
        return g

    # ---------------------------------------------------------- direct corrections
    def edit(self, eid: str, param: str, value_text: str, by: str, reason: str, basis: str = "measured",
             uncertainty_text: str | None = None, verify: bool = False) -> Genome:
        g = self.genome()
        if eid not in g.elements:
            raise ReviewError(f"no element {eid}")
        val = parse_pitch(value_text) if param == "pitch" else parse_length(value_text, default_unit="m")
        unc = None
        if uncertainty_text:
            unc = parse_pitch(uncertainty_text + ":12") if param == "pitch" else parse_length(uncertainty_text, default_unit="m")
        cur = getattr(g.elements[eid], param, None)
        op = CS.set_value_op(eid, param, val, basis=basis, verification="verified" if verify else "unverified",
                             uncertainty=unc, observations=cur.observations if isinstance(cur, Value) else (),
                             input_text=value_text, by=by, reason=reason, process="cli")
        return self.apply(CS.make(by, reason, [op], source="cli"))

    def verify_value(self, eid: str, param: str, by: str, reason: str) -> Genome:
        g = self.genome()
        cur = getattr(g.elements[eid], param)
        if not isinstance(cur, Value) or cur.value is None:
            raise ReviewError("can only verify a value that exists")
        if cur.verification == "disputed":
            raise ReviewError("resolve the dispute before verifying")
        rec = cur.model_dump(mode="json", exclude_none=True)
        rec["verification"] = "verified"
        rec["selection"] = {"by": by, "process": "review", "reason": reason}
        return self.apply(CS.make(by, f"verify {eid}.{param}: {reason}",
                                  [{"op": "set", "path": f"/elements/{eid}/{param}", "value": rec}], source="review"))

    def close_capture(self, by: str, reason: str, at: str | None = None) -> Genome:
        """Close the current capture epoch: every value record is accepted as verified by `by`.

        Bases are untouched (a photo estimate stays 'observed'). Disputed values keep their selected value
        and their candidates (as history) and become verified. One changeset, so it can be replayed/reverted.
        """
        import datetime as _dt

        at = at or _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
        doc = to_json(self.genome())
        ops = []

        def esc(k):
            return str(k).replace("~", "~0").replace("/", "~1")

        def walk(node, path):
            if isinstance(node, dict):
                if "basis" in node and "value" in node and set(node) <= set(Value.model_fields):
                    if node.get("value") is not None and node.get("verification") != "verified":
                        rec = dict(node)
                        was = rec.get("verification", "unverified")
                        rec["verification"] = "verified"
                        prior = (node.get("selection") or {}).get("reason", "")
                        rec["selection"] = {"by": by, "process": "review", "at": at,
                                            "reason": reason + (" — dispute closed: selected value kept, candidates retained as history"
                                                                if was == "disputed" else "") + (f" | earlier selection: {prior}" if prior else "")}
                        ops.append({"op": "set", "path": path, "value": rec})
                    return
                for k, v in node.items():
                    if path == "" and k in ("observations", "sources", "revision", "capture"):
                        continue
                    walk(v, f"{path}/{esc(k)}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}/{i}")

        walk(doc, "")
        cap = dict(doc.get("capture") or {})
        cap.update({"closed": True, "closed_at": at, "closed_by": by, "note": reason})
        ops.append({"op": "set", "path": "/capture", "value": cap})
        return self.apply(CS.make(by, f"close capture epoch {cap.get('epoch', 1)}: {reason}", ops, source="review", at=at))

    def clean_out(self):
        if self.out.exists():
            shutil.rmtree(self.out)
