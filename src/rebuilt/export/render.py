"""Rendered look for the browser views: config from the Genome + injection into viewer.html / walk pages."""
from __future__ import annotations

import json
from pathlib import Path

LIB = Path(__file__).with_name("render_lib.js")


def _outward(w, side):
    (x0, y0), (x1, y1) = w["start"], w["end"]
    L = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** .5
    lx, ly = -(y1 - y0) / L, (x1 - x0) / L
    nx, ny = (lx, ly) if side == "left" else (-lx, -ly)
    return [round(nx, 4), round(-ny, 4)]          # genome (x, y) -> glTF (x, -z)


def opening_type(o) -> str:
    op = ((o.get("filling") or {}).get("operation") or "").lower() + " " + o.get("name", "").lower()
    if o["kind"] == "window":
        if "screen" in op:
            return "screen"
        if "double-hung" in op:
            return "dh"
        if "casement" in op:
            return "casement"
        return "picture"
    if "overhead" in op:
        return "overhead"
    if "sliding glass" in op:
        return "slider"
    if "french" in op:
        return "french"
    if "full glass" in op:
        return "glassdoor"
    if "half-lite" in op:
        return "halflite"
    return "panel"


def render_cfg(genome: dict) -> dict:
    E = genome["elements"]
    siding, win, fin, kind = {}, {}, {}, {}
    for e in E.values():
        if e["type"] == "component" and e["kind"] == "cladding" and e["placement"].get("on") == "wall":
            for h in e.get("hosts") or [e["placement"]["wall"]]:
                siding[h] = _outward(E[h], e["placement"].get("side", "left"))
        if e["type"] == "opening" and e.get("filling"):
            win[e["id"]] = {"t": opening_type(e), "w": e["width"]["value"], "h": e["height"]["value"],
                            "n": _outward(E[e["host"]], "left")}       # host wall normal: each face is skinned on its own
        if e["type"] == "component":
            fin[e["id"]] = (e.get("info") or {}).get("finish")
            kind[e["id"]] = (e.get("info") or {}).get("category") or e["kind"]
            if e["kind"] == "chimney":
                kind[e["id"]] = "chimney"
    return {"siding": siding, "win": win, "fin": fin, "kind": kind}


def patch_viewer(html_path, genome: dict, site: dict):
    p = Path(html_path); s = p.read_text()
    if "const RB = (" in s:
        return
    cfg = render_cfg(genome)
    lib = LIB.read_text() + f"\nconst RCFG={json.dumps(cfg)};const RSITE={json.dumps(site)};let RBh=null;\n"
    a = "new GLTFLoader().parse(bytes.buffer"
    assert a in s
    s = s.replace(a, lib + a, 1)
    b = "box.setFromObject(g.scene);setView('iso');"
    assert b in s
    s = s.replace(b, "box.setFromObject(g.scene);try{const hemi=scene.children.find(o=>o.isHemisphereLight);"
                     "RBh=RB.apply({scene,renderer,sun:dl,hemi,nodes,cfg:RCFG,site:RSITE,edges:v=>{grid.visible=!v}});}"
                     "catch(e){console.warn('render',e)}setView('iso');", 1)
    btn = '<button id="spaces">Spaces</button>'
    assert btn in s
    s = s.replace(btn, '<button id="rendered" class="on">Rendered</button>' + btn, 1)
    s = s.replace("document.getElementById('colour').onchange=colour;",
                  "document.getElementById('colour').onchange=()=>{colour();const b=document.getElementById('colour').value==='basis';"
                  "if(RBh){RBh.set(!b&&document.getElementById('rendered').classList.contains('on'))}};"
                  "document.getElementById('rendered').onclick=e=>{const on=!e.target.classList.contains('on');e.target.classList.toggle('on',on);if(RBh)RBh.set(on)};", 1)
    s = s.replace("renderer.setPixelRatio(devicePixelRatio);", "renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.outputColorSpace=THREE.SRGBColorSpace;", 1)
    p.write_text(s)
