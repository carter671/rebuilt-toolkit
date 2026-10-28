"""One call: as-built Genome (+ design) → compiled model → quantities → decisions → priced scope + plan data."""
from __future__ import annotations

import json
from pathlib import Path

from ..design import apply_design
from ..genome.io import parse
from ..model.compile import CompileError, compile_genome
from .pricebook import load_pricebook
from .quantities import quantities
from .scope import decisions, default_selections, price


def plan_data(model, genome: dict) -> dict:
    """2D plan geometry per storey for drawing (metres, project coords)."""
    G = genome["elements"]
    out = {}
    for eid, ce in sorted(model.elements.items()):
        st = ce.storey
        if st is None:
            continue
        s = out.setdefault(st, {"walls": [], "openings": [], "rooms": []})
        if ce.type == "wall":
            s["walls"].append({"id": eid, "poly": ce.data["plan_polygon"], "ext": bool(ce.data.get("exterior")),
                               "new": G[eid].get("phase") == "new"})
        elif ce.type == "space":
            s["rooms"].append({"id": eid, "name": G[eid].get("name", eid), "poly": ce.data["boundary"]})
    for eid, ce in sorted(model.elements.items()):
        if ce.type != "opening":
            continue
        w = model.elements[ce.data["host"]]
        (x0, y0), (x1, y1) = w.data["baseline"]
        L = w.data["length"]
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        a, b = ce.data["offset"], ce.data["offset"] + ce.data["width"]
        out[w.storey]["openings"].append({"id": eid, "kind": ce.data["kind"], "host": w.id,
                                          "p0": [x0 + ux * a, y0 + uy * a], "p1": [x0 + ux * b, y0 + uy * b],
                                          "new": G[eid].get("phase") == "new"})
    return out


def run_scope(genome_path, design_path=None, prices_path=None, contingency=0.10) -> dict:
    asbuilt = json.loads(Path(genome_path).read_text())
    design = json.loads(Path(design_path).read_text()) if design_path else {"name": "As-built", "changes": []}
    dg, layout = apply_design(asbuilt, design)
    g, issues = parse(dg)
    if g is None:
        raise SystemExit("design genome invalid: " + "; ".join(i.message for i in issues.items if i.severity == "error"))
    try:
        model = compile_genome(g, "review")
    except CompileError as e:
        raise SystemExit("design does not compile: " + "; ".join(i.message for i in e.issues.sorted() if i.severity == "error"))
    q = quantities(model, dg)
    D = layout + decisions(q)
    sel = default_selections(D)
    sel.update(design.get("selections", {}))
    pb = load_pricebook(prices_path)
    ab_model = model if not design.get("changes") else compile_genome(parse(asbuilt)[0], "review")
    return {"design": design, "quantities": q, "decisions": D, "selections": sel, "pricebook": pb,
            "contingency": contingency, "priced": price(D, sel, pb, contingency),
            "plans": {"design": plan_data(model, dg), "asbuilt": plan_data(ab_model, asbuilt)},
            "storeys": [{"id": s["id"], "name": s["name"], "building": b["name"]}
                        for b in asbuilt["buildings"] for s in b["storeys"]]}
