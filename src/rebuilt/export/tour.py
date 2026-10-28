"""360° tour page: panoramas rendered by blender_render (pano shots) + a stop graph."""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("tour_template.html")
FT = 0.3048


def build_tour(genome: dict, stops: list[dict], out_html, title: str, subtitle: str, note: str, start: str, img_dir="panos/", walk: str | None = None):
    rooms = []
    for e in genome["elements"].values():
        if e["type"] == "space" and e["storey"] in ("1F", "2F"):
            rooms.append({"floor": e["storey"], "poly": [[round(x / FT, 2), round(y / FT, 2)] for x, y in e["boundary"]]})
    xs = [p[0] for r in rooms for p in r["poly"]]; ys = [p[1] for r in rooms for p in r["poly"]]
    data = {"title": title, "subtitle": subtitle, "note": note, "start": start, "dir": img_dir, "stops": stops, "rooms": rooms, "walk": walk,
            "bounds": [min(xs) - 4, min(ys) - 4, max(xs) + 4, max(ys) + 4]}
    html = TEMPLATE.read_text().replace("__TITLE__", title).replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    Path(out_html).write_text(html)
    return Path(out_html)
