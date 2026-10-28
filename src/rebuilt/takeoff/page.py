"""Interactive Design + Scope page from a run_scope() result."""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("page_template.html")


def _round(o):
    if isinstance(o, float):
        return round(o, 3)
    if isinstance(o, list):
        return [_round(x) for x in o]
    if isinstance(o, dict):
        return {k: _round(v) for k, v in o.items()}
    return o


def build_page(res: dict, out: str | Path, title: str, intro: str = "Every quantity comes from the as-built model. Pick what happens to each room and surface; the total updates as you go.") -> Path:
    q = res["quantities"]
    data = {
        "key": (q["address"] or "property") + "|" + res["design"].get("name", "design"),
        "address": q["address"], "design": res["design"].get("name", "As-built"),
        "model_hash": q["model_hash"], "genome_revision": q["genome_revision"],
        "heated_sf": q["totals"]["heated_sf"], "contingency": res["contingency"],
        "decisions": res["decisions"], "selections": res["selections"], "pricebook": res["pricebook"],
        "rooms": [{k: r[k] for k in ("id", "name", "storey", "floor_sf", "wall_sf", "height_ft")} for r in q["rooms"]],
        "plans": res["plans"]["design"], "storeys": res["storeys"],
    }
    js = json.dumps(_round(data), separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("__TITLE__", title).replace("__INTRO__", intro).replace("__DATA__", js)
    Path(out).write_text(html)
    return Path(out)
