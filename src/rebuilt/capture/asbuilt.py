"""Extract measurements from vector as-built floor-plan PDFs (text layer), without deriving geometry.

What it does
- Reads every text item with its position and drawing direction (PyMuPDF).
- Classifies items: dimension, room-size label ("16'-7" X 13'-2""), area ("219 SQ FT"),
  room name, opening code ("2459DH"), other.
- Parses imperial dimensions with fractions written as separate tokens ("8'-3  15 16 "").
- Decodes opening codes (width ft+in, height ft+in, optional type suffix) and flags ambiguity.
- Arithmetic closure check: finds runs of adjacent dimensions in the same band that sum exactly to
  another dimension. Closures validate the reading (and the drawing's own consistency); dimensions
  that close nothing are reported, not discarded.

What it deliberately does NOT do: build walls, rooms or a floor plan from the drawing. Every value
is an observation with basis "extracted", tied to page + position, for review against field data.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import asdict, dataclass, field

DIM_FT_IN = re.compile(r"(\d+)'(?:-(\d+)(?: (\d+) (\d+))?\")?")
DIM_IN = re.compile(r"(\d+)(?: (\d+) (\d+))?\"")
ROOM_SIZE = re.compile(r"(\d+)'-(\d+)\" X (\d+)'-(\d+)\"")
AREA = re.compile(r"(\d+) SQ FT")
CODE = re.compile(r"(\d{3,6})([A-Z]{0,2})")
SUFFIX = {"DH": "double-hung window", "FX": "fixed glazing", "DC": "suffix 'DC' (not defined on drawing)",
          "": "door / opening (no suffix)"}


def _norm(t: str) -> str:
    t = re.sub(r"\s+", " ", t.replace('"', ' " ')).strip()
    return t.replace(' "', '"').replace("' ", "'")


def parse_dim(t: str) -> float | None:
    s = _norm(t)
    m = DIM_FT_IN.fullmatch(s)
    if m:
        return int(m[1]) * 12 + int(m[2] or 0) + (int(m[3]) / int(m[4]) if m[3] else 0.0)
    m = DIM_IN.fullmatch(s)
    if m:
        return int(m[1]) + (int(m[2]) / int(m[3]) if m[2] else 0.0)
    return None


def fmt_in(v: float) -> str:
    ft, rem = divmod(round(v * 16), 192)
    i, f = divmod(rem, 16)
    from fractions import Fraction
    fr = f" {Fraction(f, 16)}" if f else ""
    return f"{ft}'-{i}{fr}\""


def decode_code(code: str) -> list[tuple[int, int, int, int]]:
    """All (w_ft, w_in, h_ft, h_in) readings of a code like 2459 / 32510 / 110511:
    1-digit feet, then 1- or 2-digit inches (< 12), for width then height."""
    out = []
    for wa in (1, 2):
        for ha in (1, 2):
            if 2 + wa + ha != len(code):
                continue
            wf, wi = int(code[0]), int(code[1:1 + wa])
            hf, hi = int(code[1 + wa]), int(code[2 + wa:])
            if wi < 12 and hi < 12 and not (wa == 2 and code[1] == "0") and not (ha == 2 and code[2 + wa] == "0"):
                out.append((wf, wi, hf, hi))
    return out


@dataclass
class Item:
    id: str
    page: str
    kind: str
    raw: str
    x: float
    y: float
    orient: str  # H, V (drawn vertically) or D (diagonal)
    value_in: float | None = None
    value_ft_in: str = ""
    extra: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    nearest_room: str = ""
    band: str = ""


def extract(pdf_path: str, page_label: str, prefix: str) -> list[Item]:
    import pymupdf

    page = pymupdf.open(pdf_path)[0]
    raw = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            d = ln["dir"]
            orient = "H" if abs(d[0]) > 0.99 else "V" if abs(d[1]) > 0.99 else "D"
            text = " ".join(s["text"] for s in spans).strip()
            # a line holding several overlapping dimension labels: split into separate dimensions
            if parse_dim(text) is None and len(spans) > 1 and text.count("'") + text.count('"') > 2:
                pieces = re.findall(r"\d+'(?:-\d+(?: \d+ \d+)?\")?|\d+(?: \d+ \d+)?\"", _norm(text))
                for n, piece in enumerate(pieces):
                    sb = spans[min(len(spans) - 1, round(n * (len(spans) - 1) / max(1, len(pieces) - 1)))]["bbox"]
                    raw.append((piece, (sb[0] + sb[2]) / 2, (sb[1] + sb[3]) / 2, orient, spans[0]["size"],
                                "split from overlapping labels; position approximate"))
                continue
            bx = ln["bbox"]
            raw.append((text, (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2, orient, spans[0]["size"], ""))

    items: list[Item] = []
    rooms = []
    for k, (t, x, y, o, size, note) in enumerate(sorted(raw, key=lambda r: (round(r[2]), round(r[1])))):
        it = Item(f"{prefix}-{k + 1:03d}", page_label, "other", t, round(x, 1), round(y, 1), o)
        if note:
            it.flags.append(note)
        m = ROOM_SIZE.fullmatch(t)
        if m:
            it.kind = "room_size"
            a, b = int(m[1]) * 12 + int(m[2]), int(m[3]) * 12 + int(m[4])
            it.extra = {"first_in": a, "second_in": b, "first": fmt_in(a), "second": fmt_in(b)}
        elif AREA.fullmatch(t):
            it.kind = "area"
            it.value_in = None
            it.extra = {"sq_ft": int(AREA.fullmatch(t)[1])}
        elif t.isupper() and re.fullmatch(r"[A-Z /]+", t) and t not in ("UP", "DN"):
            it.kind = "room_name"
            rooms.append(it)
        elif t in ("UP", "DN"):
            it.kind = "stair_arrow"
        elif CODE.fullmatch(t) and size < 9:
            it.kind = "opening_code"
            c, suf = CODE.fullmatch(t).groups()
            readings = decode_code(c)
            it.extra = {"type": SUFFIX.get(suf, f"suffix {suf}"), "readings": [
                {"width": f"{a}'-{b}\"", "height": f"{c_}'-{d}\"", "width_in": a * 12 + b, "height_in": c_ * 12 + d}
                for a, b, c_, d in readings]}
            if len(readings) != 1:
                it.flags.append("ambiguous code" if readings else "code not decodable")
            if suf == "DC":
                it.flags.append("suffix DC not defined on drawing")
        else:
            v = parse_dim(t)
            if v is not None:
                it.kind = "dimension"
                it.value_in = v
                it.value_ft_in = fmt_in(v)
            else:
                it.flags.append("unrecognised text")
        items.append(it)

    # nearest room label (label positions only — no room geometry is derived)
    for it in items:
        if rooms and it.kind not in ("room_name",):
            r = min(rooms, key=lambda r: (r.x - it.x) ** 2 + (r.y - it.y) ** 2)
            it.nearest_room = r.raw
    # room-size and area labels belong to the room name just above them
    for it in items:
        if it.kind in ("room_size", "area"):
            above = [r for r in rooms if 0 < it.y - r.y < 40 and abs(r.x - it.x) < 60]
            if above:
                it.nearest_room = min(above, key=lambda r: it.y - r.y).raw
    return items


PT_PER_IN = 1.5  # 1/4" = 1'-0" on a 72 pt/in PDF; checked against the drawing's own closures


def closures(items: list[Item], tol: float = 1 / 32, band: float = 45.0, pos_tol: float = 8.0,
             scale: float = PT_PER_IN, max_parts: int = 7) -> list[dict]:
    """Find sets of same-orientation dimensions in a band whose values sum to another dimension AND
    whose label positions are spaced as those values would be at the drawing scale. Uses label
    positions only; no wall or room geometry is constructed."""
    dims = [i for i in items if i.kind == "dimension"]
    along = lambda d: d.x if d.orient == "H" else d.y  # noqa: E731
    perp = lambda d: d.y if d.orient == "H" else d.x  # noqa: E731
    out = []
    for t in dims:
        if t.value_in < 12 or t.orient == "D":
            continue
        cands = sorted([d for d in dims if d is not t and d.orient == t.orient and abs(perp(d) - perp(t)) <= band
                        and d.value_in < t.value_in], key=along)
        half = t.value_in * scale / 2
        lo, hi = along(t) - half, along(t) + half

        def dfs(start_edge, chosen, total):
            if abs(total - t.value_in) <= tol and len(chosen) > 1:
                return [list(chosen)]
            if total > t.value_in + tol or len(chosen) >= max_parts:
                return []
            res = []
            for d in cands:
                if d in chosen:
                    continue
                exp_centre = start_edge + d.value_in * scale / 2
                slack = pos_tol + (30 if d.value_in < 30 else 0) + (20 if "approximate" in " ".join(d.flags) else 0)
                if abs(along(d) - exp_centre) <= slack:
                    res += dfs(start_edge + d.value_in * scale, chosen + [d], total + d.value_in)
            return res

        for run in dfs(lo, [], 0.0):
            if True:  # sum already equals the total; label spacing checked per part
                out.append({"total": t.id, "total_text": t.value_ft_in, "parts": [r.id for r in run],
                            "parts_text": [r.value_ft_in for r in run]})
    for f in out:
        f["check"] = "sum + label spacing"
    closed = {f["total"] for f in out}
    # relaxed pass for totals whose labels are not centred on their spans: consecutive labels (in
    # drawing order, one row over) whose values sum exactly to the total
    for t in dims:
        if t.id in closed or t.value_in < 12 or t.orient == "D":
            continue
        cands = sorted([d for d in dims if d is not t and d.orient == t.orient and 3 < abs(perp(d) - perp(t)) <= band
                        and d.value_in < t.value_in], key=along)
        for side in (1, -1):
            row = [d for d in cands if (perp(d) - perp(t)) * side > 0]
            for i in range(len(row)):
                acc = 0.0
                for j in range(i, min(len(row), i + max_parts)):
                    acc += row[j].value_in
                    if j > i and abs(acc - t.value_in) <= tol:
                        centre = (along(row[i]) + along(row[j])) / 2
                        if abs(centre - along(t)) <= t.value_in * scale / 2 + 40:
                            out.append({"total": t.id, "total_text": t.value_ft_in, "parts": [r.id for r in row[i:j + 1]],
                                        "parts_text": [r.value_ft_in for r in row[i:j + 1]], "check": "sum of adjacent labels"})
                    if acc > t.value_in + tol:
                        break
    # keep the simplest closure per total
    best = {}
    for f in out:
        k = f["total"]
        if k not in best or len(f["parts"]) < len(best[k]["parts"]):
            best[k] = f
    return [best[k] for k in sorted(best)]


def to_rows(items):
    return [asdict(i) for i in items]
