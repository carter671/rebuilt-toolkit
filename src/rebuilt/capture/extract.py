"""Text evidence → observations, and observation → candidate element association.

Rule-based and deliberately conservative: it extracts what it can state precisely, attaches an
observation to an element automatically only on an exact id/tag/alias match, and leaves every
other association as ranked candidates for human review. It never fabricates a value.

Compass words (north/south/...) are interpreted in PROJECT north unless true north is recorded.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

import numpy as np

from ..genome.schema import Genome, Opening, Roof, Space, Wall
from ..units import UnitError, parse_length, parse_pitch

LEN_RE = re.compile(
    r"(?<![\w/])(?:"
    r"\d+\s*['’]\s*-?\s*(?:\d+(?:\s+\d+/\d+)?|\d+/\d+)?\s*(?:\"|”|'')?"  # 3' 11 1/4"  or 8'
    r"|\d+(?:\s+\d+/\d+)?\s*(?:\"|”|'')"  # 7 7/8"
    r"|\d+(?:\.\d+)?\s*(?:mm|cm|m)\b"  # 150 mm, 3.2 m
    r")"
)
PITCH_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?::|/|in)\s*12\b")
PROP_WORDS = [
    ("pitch", r"\bpitch|\bslope"),
    ("sill", r"\bsill"),
    ("overhang", r"\boverhang|\beave"),
    ("thickness", r"\bthick(?:ness)?\b"),
    ("width", r"\bwide\b|\bwidth\b"),
    ("height", r"\btall\b|\bhigh\b|\bheight\b"),
]
COMPAT = {
    "thickness": ("wall", "slab", "roof"), "width": ("opening",), "height": ("opening", "wall", "space"),
    "sill": ("opening",), "pitch": ("roof",), "overhang": ("roof",),
}
STOREY_SYNONYMS = {
    "upper": ["upper", "upstairs", "second floor", "2nd floor"],
    "ground": ["ground", "downstairs", "first floor", "1st floor", "main floor"],
}
HEDGES = re.compile(r"\babout\b|\bapprox|\bby eye\b|\broughly\b|\bmaybe\b|\b~", re.I)
UNCERTAIN_ONLY = re.compile(r"\bnot sure\b|\bcould not\b|\bcouldn't\b|\bunknown\b", re.I)
PLAUSIBLE = {  # metres (or rise/run for pitch)
    ("wall", "thickness"): (0.05, 0.6), ("opening", "width"): (0.3, 5.0), ("opening", "height"): (0.3, 3.5),
    ("opening", "sill"): (0.0, 2.5), ("space", "height"): (1.8, 6.0), ("wall", "height"): (1.0, 12.0),
    ("roof", "pitch"): (0.0, 2.5), ("roof", "overhang"): (0.0, 1.5), ("slab", "thickness"): (0.005, 1.0),
    ("roof", "thickness"): (0.05, 0.8),
}


@dataclass
class Candidate:
    element: str
    score: float
    reason: str


@dataclass
class Extracted:
    kind: str  # measurement | observation | statement
    text: str
    locator: str
    prop: str | None = None
    value: float | None = None
    uncertainty: float | None = None
    hedged: bool = False
    candidates: list[Candidate] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    recorded_by: str = ""
    raw_value: str | None = None

    @property
    def subject(self) -> str | None:
        """Auto-associated subject: exactly one candidate at score >= 0.85."""
        top = [c for c in self.candidates if c.score >= 0.85]
        return top[0].element if len(top) == 1 else None


# ------------------------------------------------------------ element index

class ElementIndex:
    def __init__(self, g: Genome):
        self.g = g
        self.ids = {k.lower(): k for k in g.elements}
        self.tags = {}
        for k, el in g.elements.items():
            if isinstance(el, Opening):
                self.tags.setdefault(k.split("-")[-1].lower(), []).append(k)
        self.aliases = {}
        for k, el in g.elements.items():
            for a in el.aliases + ([el.name] if el.name and el.name != k else []):
                self.aliases.setdefault(a.lower(), []).append(k)
        self.storey_words = {}
        for s in g.storeys():
            words = {s.name.lower(), s.id.lower()}
            for key, syn in STOREY_SYNONYMS.items():
                if key in s.name.lower():
                    words.update(syn)
            for w in words:
                self.storey_words[w] = s.id
        self.space_names = {el.name.lower(): k for k, el in g.elements.items() if isinstance(el, Space)}
        self.outward = self._outward_dirs()

    def _outward_dirs(self):
        out = {}
        by_storey = {}
        for k, el in self.g.elements.items():
            if isinstance(el, Wall) and el.exterior:
                by_storey.setdefault(el.storey, []).append(k)
        for sid, ws in by_storey.items():
            pts = np.array([p for w in ws for p in (self.g.elements[w].start, self.g.elements[w].end)])
            cen = pts.mean(0)
            for w in ws:
                el = self.g.elements[w]
                s, e = np.array(el.start), np.array(el.end)
                d = (e - s) / np.linalg.norm(e - s)
                n = np.array([-d[1], d[0]])
                if np.dot((s + e) / 2 - cen, n) < 0:
                    n = -n
                out[w] = n
        return out

    def storeys_in(self, text: str) -> set[str]:
        t = text.lower()
        return {sid for w, sid in self.storey_words.items() if re.search(rf"\b{re.escape(w)}\b", t)}

    def candidates(self, text: str, prop: str | None) -> list[Candidate]:
        t = text.lower()
        cands: dict[str, Candidate] = {}

        def add(eid, score, why):
            el = self.g.elements[eid]
            if prop and el.type not in COMPAT.get(prop, ()):
                return
            if eid not in cands or cands[eid].score < score:
                cands[eid] = Candidate(eid, score, why)

        for tok in re.findall(r"[A-Za-z][\w-]*\d[\w-]*|[A-Z]-[\w-]+", text):
            k = tok.lower().rstrip(".,;:")
            if k in self.ids:
                add(self.ids[k], 1.0, f"explicit id {self.ids[k]}")
            for eid in self.tags.get(k, []):
                add(eid, 0.9, f"opening tag {tok}")
        for a, eids in self.aliases.items():
            if len(a) > 3 and re.search(rf"\b{re.escape(a)}\b", t):
                for eid in eids:
                    add(eid, 0.85 if len(eids) == 1 else 0.6, f"alias '{a}'")
        storeys = self.storeys_in(text)
        rooms = [k for n, k in self.space_names.items() if re.search(rf"\b{re.escape(n)}\b", t)]
        compass = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}
        for word, vec in compass.items():
            if re.search(rf"\b{word}\b", t):
                for eid, n in self.outward.items():
                    el = self.g.elements[eid]
                    if storeys and el.storey not in storeys:
                        continue
                    if float(np.dot(n, vec)) > 0.95:
                        add(eid, 0.85 if storeys else 0.6, f"{word}-facing exterior wall{' on ' + el.storey if storeys else ''}")
                if "eave" in t or "roof" in t:
                    for eid, el in self.g.elements.items():
                        if isinstance(el, Roof):
                            fp = el.footprint
                            for i, role in enumerate(el.edge_roles):
                                a, b = np.array(fp[i]), np.array(fp[(i + 1) % len(fp)])
                                d = (b - a) / np.linalg.norm(b - a)
                                if role == "eave" and float(np.dot([d[1], -d[0]], vec)) > 0.95:
                                    add(eid, 0.6, f"roof with a {word} eave")
        if ("partition" in t or "between" in t) and len(rooms) >= 2:
            # the wall that SEPARATES the rooms: bounds both, with their centroids on opposite sides
            a, b = rooms[0], rooms[1]
            ca = np.mean(self.g.elements[a].boundary, axis=0)
            cb = np.mean(self.g.elements[b].boundary, axis=0)
            shared = set(self.g.elements[a].bounded_by) & set(self.g.elements[b].bounded_by)
            sep = []
            for eid in sorted(shared):
                w = self.g.elements[eid]
                s0, e0 = np.array(w.start), np.array(w.end)
                d = e0 - s0
                side = lambda c: np.sign(d[0] * (c[1] - s0[1]) - d[1] * (c[0] - s0[0]))  # noqa: E731
                if side(ca) * side(cb) < 0:
                    sep.append(eid)
            for eid in sep:
                add(eid, 0.85 if len(sep) == 1 else 0.6, f"wall separating {a} and {b}")
        if prop == "height" and "ceiling" in t:
            for eid, el in self.g.elements.items():
                if isinstance(el, Space) and (not storeys or el.storey in storeys) and (not rooms or eid in rooms):
                    add(eid, 0.7, "space on the named storey (ceiling height is storey-wide)")
        if ("roof" in t) and prop in ("pitch", "thickness", "overhang"):
            for eid, el in self.g.elements.items():
                if isinstance(el, Roof):
                    nm = el.name.lower()
                    if any(w in t for w in nm.split() if len(w) >= 4 and w not in ("roof",)):
                        add(eid, 0.85, f"roof name '{el.name}'")
        nouns = {"wall": "wall", "window": "opening", "door": "opening", "roof": "roof", "slab": "slab", "ceiling": "space"}
        named_types = {v for k, v in nouns.items() if re.search(rf"\b{k}s?\b", t)}
        for c in cands.values():
            el = self.g.elements[c.element]
            if c.score < 1.0 and named_types and el.type not in named_types:
                c.score = round(c.score - 0.3, 3)
                c.reason += " (element type not named in text)"
            if c.score < 1.0 and storeys and getattr(el, "storey", None) and el.storey not in storeys:
                c.score = round(c.score * 0.5, 3)
                c.reason += " (different storey named)"
        return sorted(cands.values(), key=lambda c: (-c.score, c.element))


# ------------------------------------------------------------ parsing

def _prop_in(text: str) -> str | None:
    for name, rx in PROP_WORDS:
        if re.search(rx, text, re.I):
            return name
    return None


def _default_unc(prop: str, hedged: bool, value: float) -> float:
    if prop == "pitch":
        return 0.08 if hedged else 0.01
    return max(0.05, 0.1 * value) if hedged else 0.003


def parse_notes(text: str, g: Genome, recorded_by: str = "") -> list[Extracted]:
    idx = ElementIndex(g)
    out: list[Extracted] = []
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        loc = f"line {ln}"
        line_prop = _prop_in(line)
        found = []
        for m in PITCH_RE.finditer(line):
            found.append(("pitch", m.group(0), float(m.group(1)) / 12, m.start()))
        for m in LEN_RE.finditer(line):
            if any(f[3] <= m.start() < f[3] + len(f[1]) for f in found):
                continue
            try:
                found.append((None, m.group(0).strip(), parse_length(m.group(0)), m.start()))
            except UnitError:
                out.append(Extracted("statement", line, loc, flags=[f"UNPARSEABLE_VALUE:{m.group(0)}"], recorded_by=recorded_by))
        if not found:
            prop = line_prop
            cands = idx.candidates(line, prop)
            ex = Extracted("statement", line, loc, prop=prop, candidates=cands, recorded_by=recorded_by)
            if UNCERTAIN_ONLY.search(line):
                ex.flags.append("REPORTED_UNKNOWN")
            out.append(ex)
            continue
        hedged = bool(HEDGES.search(line))
        # clause-level property: text between this value and the previous one (and just after)
        found.sort(key=lambda f: f[3])
        for i, (kind_prop, s, val, pos) in enumerate(found):
            prev_end = found[i - 1][3] + len(found[i - 1][1]) if i else 0
            nxt = found[i + 1][3] if i + 1 < len(found) else len(line)
            clause = line[prev_end:nxt]
            prop = kind_prop or _prop_in(line[pos:nxt]) or _prop_in(clause) or line_prop
            cands = idx.candidates(line, prop)
            ex = Extracted("observation" if hedged else "measurement", line, loc, prop, val,
                           _default_unc(prop or "", hedged, val), hedged, cands, recorded_by=recorded_by, raw_value=s)
            if prop is None:
                ex.flags.append("NO_PROPERTY")
            subj = ex.subject
            if subj and prop:
                lo, hi = PLAUSIBLE.get((g.elements[subj].type, prop), (-1e9, 1e9))
                if not lo <= val <= hi:
                    ex.flags.append(f"IMPLAUSIBLE:{val:.3f} outside [{lo}, {hi}]")
            out.append(ex)
    return out


def parse_measurement_csv(text: str, g: Genome) -> list[Extracted]:
    """CSV columns: element, property, value, uncertainty, measured_by, method (header required)."""
    idx = ElementIndex(g)
    out = []
    for i, row in enumerate(csv.DictReader(io.StringIO(text)), 2):
        loc = f"row {i}"
        line = ", ".join(f"{k}={v}" for k, v in row.items())
        prop = (row.get("property") or "").strip().lower()
        raw = (row.get("value") or "").strip()
        try:
            val = parse_pitch(raw) if prop == "pitch" else parse_length(raw)
        except UnitError as e:
            out.append(Extracted("statement", line, loc, prop, flags=[f"UNPARSEABLE_VALUE:{e}"]))
            continue
        unc_raw = (row.get("uncertainty") or "").strip()
        try:
            unc = (parse_pitch(unc_raw + ":12") if prop == "pitch" else parse_length(unc_raw)) if unc_raw else _default_unc(prop, False, val)
        except UnitError:
            unc = _default_unc(prop, False, val)
        cands = idx.candidates(row.get("element", ""), prop)
        ex = Extracted("measurement", line, loc, prop, val, unc, False, cands, recorded_by=row.get("measured_by", ""), raw_value=raw)
        if ex.subject:
            lo, hi = PLAUSIBLE.get((g.elements[ex.subject].type, prop), (-1e9, 1e9))
            if not lo <= val <= hi:
                ex.flags.append(f"IMPLAUSIBLE:{val:.3f}")
        out.append(ex)
    return out
