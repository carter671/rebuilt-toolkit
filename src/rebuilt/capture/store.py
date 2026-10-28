"""Evidence store: content-addressed, immutable originals + manifest + derived assets.

Layout under <root>/:
  originals/<sha256><ext>   never modified after ingest
  derived/<id>.<ext>        frames, OCR text, parsed tables ... each with derived_from + process
  manifest.jsonl            one record per original (append-only)
  derived.jsonl             one record per derived asset (append-only)
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import mimetypes
import shutil
from pathlib import Path


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class EvidenceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        (self.root / "originals").mkdir(parents=True, exist_ok=True)
        (self.root / "derived").mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "manifest.jsonl"
        self.derived = self.root / "derived.jsonl"

    def _read(self, p: Path) -> list[dict]:
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []

    def records(self) -> list[dict]:
        return self._read(self.manifest)

    def derived_records(self) -> list[dict]:
        return self._read(self.derived)

    def get(self, source_id: str) -> dict:
        for r in self.records():
            if r["source_id"] == source_id:
                return r
        raise KeyError(source_id)

    def path_of(self, source_id: str) -> Path:
        r = self.get(source_id)
        return self.root / "originals" / (r["sha256"] + Path(r["filename"]).suffix.lower())

    def ingest(self, path: str | Path, provided_by: str = "", tags: dict | None = None, note: str = "",
               received_at: str | None = None) -> tuple[dict, bool]:
        """Ingest a file. Returns (record, is_new). Exact duplicates return the existing record."""
        p = Path(path)
        digest = sha256_file(p)
        for r in self.records():
            if r["sha256"] == digest:
                return r, False
        dest = self.root / "originals" / (digest + p.suffix.lower())
        shutil.copyfile(p, dest)
        dest.chmod(0o444)
        rec = {
            "source_id": f"src-{digest[:10]}", "sha256": digest, "filename": p.name,
            "media_type": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
            "bytes": p.stat().st_size,
            "received_at": received_at or _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
            "provided_by": provided_by, "tags": tags or {}, "note": note,
        }
        with open(self.manifest, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec, True

    def add_derived(self, source_id: str, kind: str, content: bytes | str, ext: str, process: dict) -> dict:
        data = content.encode() if isinstance(content, str) else content
        did = "drv-" + hashlib.sha256(data + json.dumps(process, sort_keys=True).encode()).hexdigest()[:10]
        for r in self.derived_records():
            if r["derived_id"] == did:
                return r
        (self.root / "derived" / f"{did}{ext}").write_bytes(data)
        rec = {"derived_id": did, "derived_from": source_id, "kind": kind, "file": f"{did}{ext}", "process": process}
        with open(self.derived, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec

    def verify(self) -> list[str]:
        """Re-hash every original; return ids whose content no longer matches (should be empty)."""
        bad = []
        for r in self.records():
            if sha256_file(self.path_of(r["source_id"])) != r["sha256"]:
                bad.append(r["source_id"])
        return bad
