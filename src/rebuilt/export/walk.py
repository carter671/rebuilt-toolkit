"""First-person walk-through page from a compiled GLB + its Genome (self-contained HTML)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from shapely.geometry import Polygon

TEMPLATE = Path(__file__).with_name("walk_template.html")
SKIP_GO = ("closet", "stair", "toilet", "landing", "coat")


def build_walk(genome: dict, glb_path, out, title: str, subtitle: str, stair: dict, tour: list[dict],
               start: str, grade_m: float = -0.457, site: dict | None = None, photos: dict | None = None, baked: dict | None = None) -> Path:
    """baked: optional {"dir": "bake/", "k": [...], "exposure": 1.0} -> loads the baked scene instead of embedding the GLB.
    photos: optional {"url": tour page, "stops": [{id, name, x, y (feet), floor}]} — shows a "360° photo here" button near each stop."""
    from .render import LIB, render_cfg
    E = genome["elements"]
    lv = {}
    for b in genome["buildings"]:
        for s in b["storeys"]:
            lv[s["id"]] = s["elevation"]["value"]
    rooms = []
    for e in E.values():
        if e["type"] != "space":
            continue
        poly = Polygon(e["boundary"])
        c = poly.representative_point()
        x0, y0, x1, y1 = poly.bounds
        look = [1, 0] if (x1 - x0) >= (y1 - y0) else [0, 1]
        rooms.append({"name": e["name"], "storey": e["storey"], "poly": [[round(a, 3), round(b, 3)] for a, b in e["boundary"]],
                      "at": [round(c.x, 3), round(c.y, 3)], "look": look, "sf": round(poly.area * 10.7639),
                      "go": not any(k in e["name"].lower() for k in SKIP_GO) and e["storey"] in lv})
    for t in tour:
        rooms.append({"name": t["name"], "storey": t["storey"], "poly": [], "at": [t["at"][0] * 0.3048, t["at"][1] * 0.3048],
                      "look": t["look"], "pitch": t.get("pitch", -0.04), "go": True})
    hide, glassy, upper = [], [], []
    for e in E.values():
        if e["type"] == "opening" and e.get("filling"):
            host = E[e["host"]]
            op = (e["filling"].get("operation") or "").lower()
            if e["kind"] == "window" or "glass" in op or "french" in op:
                glassy.append(e["id"])
            if e["kind"] == "door" and not host.get("exterior") or "screen" in op:
                hide.append(e["id"])
        if e.get("storey") == "2F" or (e["type"] == "slab" and e.get("storey") == "2F"):
            upper.append(e["id"])
    xs = [p[0] for r in rooms for p in r["poly"]]; ys = [p[1] for r in rooms for p in r["poly"]]
    data = {"title": title, "subtitle": subtitle, "levels": lv, "grade": grade_m, "rooms": rooms,
            "tour": [t["name"] for t in tour], "start": start, "stair": {k: v * 0.3048 for k, v in stair.items()},
            "hideFill": hide, "glass": glassy, "upperIds": upper,
            "bounds": [min(xs), min(ys), max(xs), max(ys)], "rcfg": render_cfg(genome), "site": site or {"grade": grade_m},
            "photos": {"url": photos["url"], "stops": [{"id": q["id"], "name": q["name"], "x": q["x"] * 0.3048, "y": q["y"] * 0.3048,
                       "floor": "2F" if q.get("floor") == "2F" else "1F"} for q in photos["stops"]]} if photos else None,
            "baked": baked}
    glb = "" if baked else base64.b64encode(Path(glb_path).read_bytes()).decode()
    html = (TEMPLATE.read_text().replace("__RENDERLIB__", LIB.read_text()).replace("__TITLE__", title)
            .replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/")).replace("__GLB__", glb))
    Path(out).write_text(html)
    return Path(out)
