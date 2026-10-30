"""Compile a design saved by the click-and-drag editor into a design Genome.

    python3 -m rebuilt.design.editor_ops ASBUILT.genome.json DESIGN.json OUT.genome.json [LAYOUT.json]

DESIGN.json is the editor's saved doc: {"name", "base", "ops": [...], "cursor"}. Only ops[:cursor]
are applied (the rest were undone). The as-built file is never written.

Ops (all lengths in metres, plan coordinates):
  remove_wall   {wall}
  set_walls     {walls: {id: {s, e}}, openings: {id: off}}
  add_wall      {wall: {id, st, s, e, t, h, b, ext, name, stud?: 4 | 6, oc?: 16 | 24}}
  set_wall_spec {walls: [ids], ext?, extSet?, stud?: 4 | 6, oc?: 16 | 24, t?}   outside / inside wall, 2x4 / 2x6, stud spacing (inches); extSet = picked by hand
  add_opening   {opening: {id, host, kind, off, w, h, sill, name, op}}
  remove_opening{opening}
  set_opening   {opening, off?, w?, h?, sill?}
  name_room     {at: [x, y], name}
  add_item      {item: {id, cat, st, at, rot, w, d, h, z, name}}   catalogue item (cabinet, fixture, bed...)
  set_item      {item, at?, rot?, w?, d?, h?, z?, bump?, flush?}   bump = metres a cabinet sits out from the wall on a framed bump-out (flush with the fridge)
  remove_item   {item}
  set_roof      {roof, framing?: truss | rafter | unknown, roles?: [eave|rake|abut per footprint edge]}
  set_component {id, at?, wall?, u?, z?, remove?, label?, lines?}   move / remove an existing fixture (meter, AC, chimney)
  set_wall_top  {walls: [ids], top}   top-of-wall height above the floor (fit a taller ceiling)
  add_scope     {label, lines: [{key, qty, note}]}   a scope line with no geometry (e.g. fill in a stairwell)
  set_ceiling   {at, mode: flat | vault | reset, h}
  cut_wall      {wall, a, b, nid}   remove a stretch of wall: two ordinary walls with a gap
  add_beam      {beam: {id, wall, st, s, e, depth, plies?, z, name}}   replaces a bearing wall
  remove_beam   {beam}
  batch         {ops: [...]}   several of the above as one step (multi-select)

After the ops, rooms on every storey whose walls changed are re-derived from the wall
centrelines (same rule as the editor), then shrunk by half a wall so boundaries sit at the
finished faces. Rooms keep the id, name and data of the as-built room they contain; merged
rooms take the largest one's id. Each op also yields a scope line for the takeoff.
"""
from __future__ import annotations

import copy
import re
import json
import math
import sys
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

from . import DesignError, _v

FT = 3.2808399


def _wall_len(w):
    return math.dist(w["start"], w["end"])


LITE = {"none": "solid", "quarter": "1/4 lite", "half": "1/2 lite", "tq": "3/4 lite", "full": "full glass"}


def _door_text(op, lite, ext):
    """The editor's door type as the opening's filling.operation (the takeoff reads these words)."""
    op = op or "swing"
    if op == "slider":
        return "sliding glass patio door" if ext else "bypass slider"
    if op == "double":
        return "french pair, full glass, exterior" if ext else "french pair"
    if op == "swing":
        return f"exterior swing, {LITE.get(lite or 'none', 'solid')}" if ext else "swing"
    return {"pocket": "pocket door (pocket frame kit, header over door + pocket, no plumbing / wiring in the pocket)",
            "bifold": "bifold", "bypass": "bypass slider", "barn": "barn door on a surface track",
            "cased": "cased opening, no door", "overhead": "overhead"}.get(op, op)


def _door_key(op, lite, ext):
    op = op or "swing"
    if ext:
        return {"slider": "door_slider", "double": "door_ext_french"}.get(op, "door_ext_glass" if lite == "full" else "door_ext")
    return {"pocket": "door_pocket", "bifold": "door_bifold", "bypass": "door_bypass", "slider": "door_bypass", "barn": "door_barn",
            "double": "door_int_french", "cased": "cased_opening"}.get(op, "door_int")


def _wall_spec(w, ext, stud=None, oc=None):
    """Record a wall's framing (2x4 / 2x6, stud spacing) the editor chose, in the wall's info.material, e.g. '2x6 studs @ 16" o.c.'."""
    info = w.setdefault("info", {})
    m = re.match(r'2x(\d) studs @ (\d+)" o\.c\.', info.get("material") or "")
    stud = int(stud or (m and m.group(1)) or (6 if (w.get("thickness") or {}).get("value", 0.1143) >= 5.4 * 0.0254 else 4))
    oc = int(oc or (m and m.group(2)) or 16)
    info.update({"category": "exterior wall" if ext else "interior wall", "material": f'2x{stud} studs @ {oc}" o.c.',
                 "subtype": "new wall, sheathed + sided" if ext else "new wood stud partition"})


def apply_editor(asbuilt: dict, doc: dict, extras: dict | None = None) -> tuple[dict, list[dict]]:
    g = copy.deepcopy(asbuilt)
    E = g["elements"]
    ops = doc.get("ops", [])[: doc.get("cursor", len(doc.get("ops", [])))]
    flat = []
    for op in ops:   # a multi-wall edit is saved as one "batch" step
        flat.extend(op.get("ops", []) if op.get("do") == "batch" else [op])
    ops = flat
    layout, names, touched = [], [], set()
    door_lines = {}                                          # opening added in the design -> its layout entry
    base_spaces = {k: copy.deepcopy(e) for k, e in E.items() if e["type"] == "space"}

    def hosted(eid):
        return [k for k, e in E.items() if e.get("host") == eid or (e.get("placement") or {}).get("wall") == eid
                or (e.get("placement") or {}).get("opening") == eid]

    def drop(eid):
        for k in hosted(eid):
            if k in E:
                drop(k)
        E.pop(eid, None)

    def line(i, label, existing, lines):
        layout.append({"id": f"layout:{i}", "group": "Layout changes", "label": label, "existing": existing,
                       "default": "do", "options": {"do": {"label": "Do it", "lines": lines},
                                                    "skip": {"label": "Skip", "lines": []}}})

    template_wall = next((e for e in E.values() if e["type"] == "wall" and not e.get("exterior")), None)
    moved = {}
    items = {}
    covers = {}
    removed = {}
    ceilings = []
    beams = {}
    for i, op in enumerate(ops):
        do = op.get("do")
        if do == "remove_wall":
            w = E.get(op["wall"])
            if not w or w["type"] != "wall":
                raise DesignError(f"op {i}: no wall {op['wall']}")
            if w.get("exterior") and op["wall"] in asbuilt["elements"]:
                raise DesignError(f"op {i}: {op['wall']} is exterior")
            touched.add(w["storey"])
            if op["wall"] not in asbuilt["elements"]:      # a wall added earlier in the design, taken back out: nothing to demo
                drop(op["wall"])
                continue
            n_open = sum(1 for k in hosted(op["wall"]) if E[k]["type"] == "opening")
            L = _wall_len(w) * FT
            drop(op["wall"])
            removed[op["wall"]] = (len(layout), w["storey"])
            line(i, f"Remove wall: {w.get('name', op['wall'])}", f"{L:.1f} ft wall",
                 [{"key": "wall_remove", "qty": round(L, 2), "note": f"{L:.1f} lf, {n_open} opening(s) go with it"},
                  {"key": "header_bearing", "qty": 1, "note": "bearing status unknown — confirm before demo"}])
        elif do == "set_walls":
            for wid, v in op["walls"].items():
                w = E.get(wid)
                if not w:
                    continue
                if wid not in moved:
                    moved[wid] = (list(w["start"]), list(w["end"]))
                s_old, e_old = list(w["start"]), list(w["end"])
                w["start"], w["end"] = [round(c, 6) for c in v["s"]], [round(c, 6) for c in v["e"]]
                # things hung on the wall (vents, lights, meters) stay put in plan when its start moves along the line
                Lo = math.dist(s_old, e_old) or 1
                do_ = [(e_old[0] - s_old[0]) / Lo, (e_old[1] - s_old[1]) / Lo]
                ds = (s_old[0] - w["start"][0]) * do_[0] + (s_old[1] - w["start"][1]) * do_[1]
                if abs(ds) > 0.005:
                    for c in E.values():
                        pl = c.get("placement") or {}
                        if c["type"] == "component" and pl.get("on") == "wall" and pl.get("wall") == wid and isinstance(pl.get("u"), dict):
                            pl["u"]["value"] = round(pl["u"]["value"] + ds, 6)
                w.setdefault("_moved", w.get("phase") != "new")
                w["phase"] = "new"
                touched.add(w["storey"])
            for oid, off in (op.get("openings") or {}).items():
                if oid in E:
                    if off < 0:
                        print(f"  [note] {oid} ran {abs(off) / 0.0254:.1f}\" past its wall end after a move; pulled back to the end")
                    E[oid]["offset"] = _v(max(0.0, off), "design: wall moved")
        elif do == "add_wall":
            v = op["wall"]
            if template_wall is None:
                raise DesignError("no interior wall to copy settings from")
            ext = bool(v.get("ext"))
            tmpl = next((e for e in E.values() if e["type"] == "wall" and e.get("exterior") and e["storey"] == v["st"]), None) if ext else None
            w = copy.deepcopy(tmpl or template_wall)
            for k in ("info", "history", "top", "trim_by", "aliases"):
                w.pop(k, None)
            w.update({"id": v["id"], "name": v.get("name", "New wall"), "storey": v["st"], "phase": "new",
                      "start": [round(c, 6) for c in v["s"]], "end": [round(c, 6) for c in v["e"]],
                      "thickness": _v(v.get("t", 0.1143), "design: matches the building's outside walls" if ext else "design: new 2x4 partition"),
                      "height": _v(v.get("h", 2.44), "design: matches the building" if ext else "design: matches the room"),
                      "base_offset": _v(v.get("b", 0.0), "design"), "exterior": ext,
                      "info": {"category": "exterior wall" if ext else "interior wall",
                               "subtype": "new 2x6 wall, sheathed + sided to match (addition)" if ext else "new wood stud partition"}})
            if v.get("stud") or v.get("oc"):
                _wall_spec(w, ext, v.get("stud"), v.get("oc"))
            E[w["id"]] = w
            touched.add(w["storey"])
        elif do == "add_opening":
            v = op["opening"]
            w = E.get(v["host"])
            if not w:
                raise DesignError(f"op {i}: host wall {v['host']} is gone")
            kind = v.get("kind", "door")
            E[v["id"]] = {"type": "opening", "id": v["id"], "name": v.get("name", f"New {kind}"), "host": v["host"],
                          "kind": kind, "phase": "new", "offset": _v(v["off"], "design"), "width": _v(v["w"], "design"),
                          "height": _v(v["h"], "design"), "sill": _v(v.get("sill", 0.0), "design"),
                          "filling": {"type": "none"} if kind == "void" else
                          {"type": kind, "operation": _door_text(v.get("op"), v.get("lite"), bool(w.get("exterior"))) if kind == "door" else (v.get("op") or "double-hung")}}
            overhead = (v.get("op") or "") == "overhead"
            if (v.get("op") or "") == "open":
                E[v["id"]]["info"] = {"category": "opening", "subtype": "removed section"}
                touched.add(w["storey"])
                continue
            key = "window_std" if kind == "window" else "door_garage" if overhead else "cased_opening" if kind == "void" else _door_key(v.get("op"), v.get("lite"), bool(w.get("exterior")))
            door_lines[v["id"]] = len(layout)
            lines = [{"key": "opening_new", "qty": 1, "note": ""}, {"key": key, "qty": 1, "note": "trim it out" if kind == "void" else "unit"}]
            if v["w"] > 6 * 0.3048:
                lines.append({"key": "beam", "qty": 1, "note": f"{v['w'] * FT:.0f} ft header (LVL, engineer to size)"})
            line(i, f"{'Open up' if kind == 'void' else 'Add ' + ('garage door' if overhead else kind)}: {w.get('name', v['host'])}", f"{v['w'] * FT * 12:.0f}\" wide", lines)
        elif do == "remove_opening":
            o = E.get(op["opening"])
            if not o:
                raise DesignError(f"op {i}: no opening {op['opening']}")
            drop(op["opening"])
            if o.get("phase") != "new":
                line(i, f"Close up: {o.get('name', op['opening'])}", "", [{"key": "opening_close", "qty": 1, "note": ""}])
        elif do == "set_opening":
            o = E.get(op["opening"])
            if not o:
                raise DesignError(f"op {i}: no opening {op['opening']}")
            if (o.get("info") or {}).get("subtype") == "removed section":
                for k, f in (("off", "offset"), ("w", "width"), ("h", "height"), ("sill", "sill")):
                    if op.get(k) is not None:
                        o[f] = _v(op[k], "design")
                touched.add(E[o["host"]]["storey"])
                continue
            if (op.get("op") is not None or op.get("lite") is not None) and o.get("kind") == "door":      # door type changed
                ext = bool(E[o["host"]].get("exterior"))
                o.setdefault("_door", {})
                o["_door"].update({k: op[k] for k in ("op", "lite") if op.get(k) is not None})
                dop, dlite = o["_door"].get("op"), o["_door"].get("lite")
                o["filling"] = {**(o.get("filling") or {"type": "door"}), "type": "door", "operation": _door_text(dop, dlite, ext)}
                if op.get("name"):
                    o["name"] = op["name"]
                key = _door_key(dop, dlite, ext)
                if op["opening"] in door_lines:          # added in this design: its line follows the type
                    for ln in layout[door_lines[op["opening"]]]["options"]["do"]["lines"]:
                        if ln["key"].startswith("door_") or ln["key"] == "cased_opening":
                            ln["key"] = key
                else:
                    line(i, f"Change door: {o.get('name', op['opening'])}", "", [{"key": key, "qty": 1, "note": _door_text(dop, dlite, ext)}])
                    o["phase"] = "new"
            if op.get("swing") is not None or op.get("hinge") is not None:
                fl = o.get("filling") or {"type": "door"}
                fl["operation"] = f"swing door, hinged at the {'end' if op.get('hinge') == 'e' else 'start'} jamb, swings to the {'+' if (op.get('swing') or 1) > 0 else '-'} side of the wall"
                o["filling"] = fl
            widened = "w" in op and op["w"] is not None and abs(op["w"] - o["width"]["value"]) > 0.005
            for k, f in (("off", "offset"), ("w", "width"), ("h", "height"), ("sill", "sill")):
                if op.get(k) is not None:
                    o[f] = _v(op[k], "design")
            if widened and o.get("phase") != "new":
                o["phase"] = "new"
                for k in hosted(op["opening"]):
                    E.pop(k, None)
                line(i, f"Resize: {o.get('name', op['opening'])}", "", [{"key": "opening_widen", "qty": 1, "note": ""}])
        elif do == "name_room":
            names.append((op["at"], op["name"]))
            covers[len(names) - 1] = op.get("covers")
        elif do == "cut_wall":
            w = E.get(op["wall"])
            if not w or w["type"] != "wall":
                raise DesignError(f"op {i}: no wall {op['wall']}")
            L0 = math.dist(w["start"], w["end"]) or 1
            d = [(w["end"][0] - w["start"][0]) / L0, (w["end"][1] - w["start"][1]) / L0]
            ua = (op["a"][0] - w["start"][0]) * d[0] + (op["a"][1] - w["start"][1]) * d[1]
            ub = (op["b"][0] - w["start"][0]) * d[0] + (op["b"][1] - w["start"][1]) * d[1]
            nw = copy.deepcopy(w)
            for k in ("history", "aliases"):
                nw.pop(k, None)
            nw.update({"id": op["nid"], "name": op.get("nname") or f"{w.get('name', 'Wall')} (other side of the gap)",
                       "start": [round(c, 6) for c in op["b"]], "end": list(w["end"])})
            for k in [k for k, o in E.items() if o["type"] == "opening" and o.get("host") == w["id"]]:
                o = E[k]
                off, wd = o["offset"]["value"], o["width"]["value"]
                if off < ub - 0.01 and off + wd > ua + 0.01:
                    drop(k)
                elif off >= ub - 0.01:
                    o["host"] = nw["id"]
                    o["offset"] = _v(off - ub, "design: wall split around a gap")
            stubA, stubB = ua < 0.15, L0 - ub < 0.15          # a gap within 6" of an end runs to the end (no slivers)
            if stubA and stubB:
                drop(w["id"])
            elif stubB:
                w["end"] = [round(c, 6) for c in op["a"]]
                for k in [k for k, o in E.items() if o["type"] == "opening" and o.get("host") == nw["id"]]:
                    drop(k)
            elif stubA:
                for o in E.values():
                    if o["type"] == "opening" and o.get("host") == nw["id"]:
                        o["host"] = w["id"]
                w["start"] = [round(c, 6) for c in op["b"]]
            else:
                w["end"] = [round(c, 6) for c in op["a"]]
                E[nw["id"]] = nw
            touched.add(w["storey"])
            lf = (ub - ua) * FT
            line(i, f"Remove part of wall: {w.get('name', w['id'])}", f"{lf:.1f} ft",
                 [{"key": "wall_remove", "qty": round(lf, 1), "note": f"{lf:.1f} lf" + (", outside wall: patch siding + roof edge" if w.get("exterior") else "")},
                  {"key": "beam", "qty": 1, "note": f"{lf:.0f} ft header beam + posts (engineer to size)"},
                  {"key": "drywall_patch", "qty": 1, "note": "ceiling + floor patch where the wall was"}])
        elif do == "set_ceiling":
            ceilings = [c for c in ceilings if math.dist(c["at"], op["at"]) > 0.05]
            if op.get("mode") != "reset":
                ceilings.append({"at": op["at"], "mode": op["mode"], "h": op.get("h")})
        elif do == "rename":
            if op.get("kind") == "item":
                if op["id"] in items:
                    items[op["id"]]["name"] = op["name"]
            elif op["id"] in E:
                E[op["id"]]["name"] = op["name"]
        elif do == "set_roof":
            r = E.get(op["roof"])
            if r and r["type"] == "roof":
                if op.get("framing"):
                    info = r.setdefault("info", {}) or {}
                    r["info"] = info
                    info["subtype"] = {"truss": "framing: trusses 24\" o.c.", "rafter": "framing: rafters + ceiling joists 16\" o.c.",
                                       "unknown": "framing: not confirmed"}[op["framing"]]
                if op.get("roles"):
                    if len(op["roles"]) != len(r["footprint"]):
                        raise DesignError(f"op {i}: {op['roof']} needs {len(r['footprint'])} edge roles")
                    old_roles = list(r["edge_roles"])
                    r["edge_roles"] = list(op["roles"])
                    r["_roles_changed"] = True
                    if sorted(old_roles) != sorted(r["edge_roles"]) or old_roles != r["edge_roles"]:
                        line(i, f"Turn the roof: {r.get('name', r['id'])}", "", [
                            {"key": "frame_roof", "qty": round(Polygon(r["footprint"]).area * 10.7639 * 1.1, 0), "note": "new roof framing, ridge turned"},
                            {"key": "roof_replace", "qty": round(Polygon(r["footprint"]).area * 10.7639 * 1.2, 0), "note": "incl. waste"}])
        elif do == "set_component":
            c = E.get(op["id"])
            if not c or c["type"] not in ("component", "slab"):
                raise DesignError(f"op {i}: no component {op['id']}")
            nm = c.get("name", op["id"])
            if op.get("remove"):
                drop(op["id"])
            elif c["type"] == "slab":
                if op.get("boundary"):
                    c["boundary"] = [[round(v, 6) for v in q] for q in op["boundary"]]
            else:
                pl = c["placement"]
                if op.get("at") is not None:
                    pl["at"] = [round(v, 6) for v in op["at"]]
                if op.get("wall"):
                    pl["wall"] = op["wall"]
                if op.get("walls"):
                    pl["walls"] = list(op["walls"])
                if op.get("side"):
                    pl["side"] = op["side"]
                if op.get("u") is not None:
                    pl["u"] = _v(op["u"], "design: moved")
                if op.get("z") is not None:
                    pl["z"] = _v(op["z"], "design: moved")
            if op.get("lines"):
                line(i, op.get("label") or (f"Remove: {nm}" if op.get("remove") else f"Move: {nm}"), "", copy.deepcopy(op["lines"]))
        elif do == "set_wall_top":     # raise / lower walls to a top-of-wall height (e.g. to fit a taller ceiling)
            for wid in op["walls"]:
                w = E.get(wid)
                if w and w["type"] == "wall":
                    b = (w.get("base_offset") or {"value": 0.0})["value"]
                    w["height"] = _v(op["top"] - b, "design: top of wall set")
                    touched.add(w["storey"])
        elif do == "set_wall_spec":    # outside / inside, 2x4 / 2x6, stud spacing
            for wid in op["walls"]:
                w = E.get(wid)
                if not w or w["type"] != "wall":
                    raise DesignError(f"op {i}: no wall {wid}")
                ext = bool(op["ext"]) if op.get("ext") is not None else bool(w.get("exterior"))
                if op.get("t") is not None:
                    w["thickness"] = _v(op["t"], "design: wall framing changed")
                w["exterior"] = ext
                _wall_spec(w, ext, op.get("stud"), op.get("oc"))
                w["phase"] = "new" if wid not in asbuilt["elements"] else w.get("phase", "existing")
                touched.add(w["storey"])
        elif do == "add_scope":
            line(i, op["label"], op.get("existing", ""), copy.deepcopy(op["lines"]))
        elif do == "add_beam":
            beams[op["beam"]["id"]] = copy.deepcopy(op["beam"])
        elif do == "remove_beam":
            beams.pop(op["beam"], None)
        elif do == "add_item":
            items[op["item"]["id"]] = copy.deepcopy(op["item"])
        elif do == "set_item":
            it = items.get(op["item"])
            if it:
                for k in ("at", "rot", "w", "d", "h", "z", "st", "name", "bump", "flush", "style", "flip", "pick", "boxD", "retW"):
                    if op.get(k) is not None:
                        it[k] = copy.deepcopy(op[k])
        elif do == "remove_item":
            items.pop(op["item"], None)
        else:
            raise DesignError(f"op {i}: unknown op '{do}'")

    for wid, (s0, e0) in moved.items():
        w = E.get(wid)
        if not w:
            continue
        d = max(math.dist(s0, w["start"]), math.dist(e0, w["end"]))
        if d > 0.01 and w.pop("_moved", False):
            L = _wall_len(w) * FT
            line(f"move:{wid}", f"Move wall: {w.get('name', wid)} ({d * FT * 12:.0f}\")", "",
                 [{"key": "wall_remove", "qty": round(_wall_len({"start": s0, "end": e0}) * FT, 2), "note": "take down"},
                  {"key": "frame_int", "qty": round(L * w["height"]["value"] * FT, 1), "note": f"{L:.1f} lf rebuilt in the new spot, sf of wall"}])
    for w in E.values():
        w.pop("_moved", None) if w["type"] == "wall" else None
        w.pop("_door", None) if w["type"] == "opening" else None
        if w["type"] == "wall" and w.get("phase") == "new" and w["id"] not in moved:
            L = _wall_len(w) * FT
            A = round(L * w["height"]["value"] * FT, 1)
            if w.get("exterior"):
                line(f"new:{w['id']}", f"New outside wall: {w.get('name', 'wall')}", f"{L:.1f} ft",
                     [{"key": "frame_ext", "qty": A, "note": f"{L:.1f} lf"}, {"key": "insul_wall", "qty": A, "note": ""},
                      {"key": "siding_new", "qty": A, "note": "to match"}, {"key": "drywall", "qty": A, "note": "inside face"}])
            else:
                line(f"new:{w['id']}", f"New wall: {w.get('name', 'wall')}", f"{L:.1f} ft",
                     [{"key": "frame_int", "qty": A, "note": f"{L:.1f} lf, sf of wall"},
                      {"key": "drywall", "qty": round(2 * A, 1), "note": "both faces"}])

    for o in [e for e in E.values() if e["type"] == "opening" and (e.get("info") or {}).get("subtype") == "removed section"]:
        h = E[o["host"]]
        lf = o["width"]["value"] * FT
        line(f"open:{o['id']}", f"Remove part of wall: {h.get('name', h['id'])}", f"{lf:.1f} ft",
             [{"key": "wall_remove", "qty": round(lf, 1), "note": f"{lf:.1f} lf" + (", outside wall: patch siding + roof edge" if h.get("exterior") else "")},
              {"key": "beam", "qty": 1, "note": f"{lf:.0f} ft header beam + posts (engineer to size)"},
              {"key": "drywall_patch", "qty": 1, "note": "ceiling + floor patch where the wall was"}])
        # walls that ran into the removed stretch now stop at the face of the header line
        L = math.dist(h["start"], h["end"]) or 1
        dh = [(h["end"][0] - h["start"][0]) / L, (h["end"][1] - h["start"][1]) / L]
        u0, u1 = o["offset"]["value"], o["offset"]["value"] + o["width"]["value"]
        for w in [e for e in E.values() if e["type"] == "wall" and e["id"] != h["id"] and e["storey"] == h["storey"]]:
            for k in ("start", "end"):
                p = w[k]
                u = (p[0] - h["start"][0]) * dh[0] + (p[1] - h["start"][1]) * dh[1]
                if LineString([h["start"], h["end"]]).distance(Point(p)) < h["thickness"]["value"] / 2 + 0.03 and u0 + w["thickness"]["value"] / 2 < u < u1 - w["thickness"]["value"] / 2:
                    q = w["end" if k == "start" else "start"]
                    Lw = math.dist(p, q) or 1
                    back = h["thickness"]["value"] / 2 + 0.01
                    w[k] = [round(p[0] + (q[0] - p[0]) / Lw * back, 6), round(p[1] + (q[1] - p[1]) / Lw * back, 6)]
    for st in touched:
        _rederive_rooms(E, st, base_spaces, names, covers)
    _additions(asbuilt["elements"], E, layout)
    _ext_trims(E)
    _ceilings(E, ceilings, layout)
    from shapely.geometry import Polygon as _Pg
    for at, nm in names:       # names given in the editor stick even when no walls moved
        sp = next((e for e in E.values() if e["type"] == "space" and _Pg(e["boundary"]).buffer(0.1).contains(Point(at))), None)
        if sp and " + " not in sp["name"]:
            sp["name"] = nm
            sp["usage"] = nm
    framing = {r.get("storey"): (r.get("info") or {}).get("subtype", "") for r in E.values() if r["type"] == "roof"}
    for wid, (k, st) in removed.items():   # header line only where the roof could actually bear on the wall
        lines = layout[k]["options"]["do"]["lines"]
        if any(b["wall"] == wid for b in beams.values()) or "trusses" in framing.get(st, ""):
            layout[k]["options"]["do"]["lines"] = [x for x in lines if x["key"] != "header_bearing"]
        elif "rafters" in framing.get(st, ""):
            for x in lines:
                if x["key"] == "header_bearing":
                    x["note"] = "rafter roof — wall may carry ceiling joists; engineer to confirm"
    for b in beams.values():
        L = math.dist(b["s"], b["e"])
        d = [(b["e"][0] - b["s"][0]) / (L or 1), (b["e"][1] - b["s"][1]) / (L or 1)]
        b = dict(b, s=[b["s"][0] + d[0] * 0.06, b["s"][1] + d[1] * 0.06], e=[b["e"][0] - d[0] * 0.06, b["e"][1] - d[1] * 0.06])
        L = math.dist(b["s"], b["e"])
        mid = [(b["s"][0] + b["e"][0]) / 2, (b["s"][1] + b["e"][1]) / 2]
        E[b["id"]] = {"type": "component", "id": b["id"], "name": b.get("name", "LVL beam"), "storey": b["st"], "kind": "other", "phase": "new",
                      "geometry": "box", "placement": {"on": "point", "at": [round(mid[0], 6), round(mid[1], 6)], "z": _v(b["z"], "design: dropped beam under the ceiling joists"),
                                                       "rotation": round(math.degrees(math.atan2(b["e"][1] - b["s"][1], b["e"][0] - b["s"][0])), 3)},
                      "size": {"w": _v(L, "design"), "d": _v(b.get("plies", 3) * 0.04445, f"design: {b.get('plies', 3)}-ply 1-3/4 LVL"), "h": _v(b["depth"], "design: first-pass size (rebuilt.engineering) — engineer to confirm")},
                      "info": {"category": "beam", "subtype": "LVL beam replacing a bearing wall (engineer to confirm)", "material": f"{b.get('plies', 3)}-ply 1-3/4 LVL", "notes": f"replaces wall {b.get('wall') or ''}"}}
        layout.append({"id": f"layout:beam:{b['id']}", "group": "Layout changes", "label": f"Beam: {b.get('name', 'LVL beam')}",
                       "existing": f"{L * FT:.1f} ft", "default": "do",
                       "options": {"do": {"label": "Do it", "lines": [{"key": "beam", "qty": 1, "note": f"{L * FT:.1f} ft, {b.get('plies', 3)}-ply x {b['depth'] / 0.0254:.4g}\" LVL (first pass, engineer to confirm)"},
                                                                      {"key": "engineer", "qty": 1, "note": "beam + post sizing letter"}]},
                                   "skip": {"label": "Skip", "lines": []}}})
    cabinets = _place_items(E, items, layout)
    if extras is not None:
        extras["cabinets"] = cabinets
    return g, layout


# editor catalogue -> component kind, category, and what the renderer builds from it
ITEM = {
    "base": ("fixture", "base cabinet", "base"), "sink": ("fixture", "sink base cabinet", "base"),
    "upper": ("fixture", "wall cabinet", "wall"), "tall": ("fixture", "tall cabinet", "tall"),
    "trash": ("fixture", "trash pull-out base cabinet", "base"), "corner": ("fixture", "corner base cabinet", None),
    "panel": ("fixture", "refrigerator end panel", None),
    "micro": ("equipment", "over-the-range microwave + wall cabinet", None), "hood": ("equipment", "range hood", None),
    "island": ("fixture", "kitchen island", "island"), "filler": ("fixture", "cabinet filler", None),
    "range": ("equipment", "range", "range"), "fridge": ("equipment", "refrigerator", "fridge"),
    "dw": ("equipment", "dishwasher", None), "vanity": ("fixture", "vanity", "vanity"),
    "toilet": ("fixture", "toilet", None), "tub": ("fixture", "bathtub", None), "shower": ("fixture", "shower", None),
    "washer": ("equipment", "washer", None), "dryer": ("equipment", "dryer", None),
    "king": ("furnishing", "bed", None), "queen": ("furnishing", "bed", None), "full": ("furnishing", "bed", None),
    "twin": ("furnishing", "bed", None), "night": ("furnishing", "nightstand", None), "dresser": ("furnishing", "dresser", None),
    "sofa": ("furnishing", "sofa", None), "table": ("furnishing", "dining table", None),
    "chair": ("furnishing", "lounge chair", None), "coffee": ("furnishing", "coffee table", None),
}


def _front(rot):
    r = math.radians(rot)
    fx, fy = -math.sin(r), math.cos(r)
    return ("+x" if fx > 0 else "-x") if abs(fx) > abs(fy) else ("+y" if fy > 0 else "-y")


def _place_items(E, items, layout):
    """Editor items become components (box at a point, rotated); casework also gets a renderer spec."""
    cabinets, lf = [], {"base": 0.0, "wall": 0.0, "tall": 0.0, "island": 0.0}
    counter_sf, fixtures, appliances = 0.0, [], 0
    bumps = []                                              # cabinets pulled out flush with the fridge: framed bump-out behind
    hardware = {"trash": 0, "lazy": 0, "panel": 0, "hood": 0}
    for it in items.values():
        if (it.get("bump") or 0) > 0.002:
            bumps.append(it)
        kind, cat, cab = ITEM.get(it["cat"], ("furnishing", it["cat"], None))
        if it["cat"] == "tall" and it.get("style") == "linen":      # a pantry at vanity depth is a linen cabinet
            cat = "linen cabinet"
        E[it["id"]] = {"type": "component", "id": it["id"], "name": it.get("name", cat), "storey": it["st"], "kind": kind,
                       "phase": "new", "geometry": "box",
                       "placement": {"on": "point", "at": [round(it["at"][0], 6), round(it["at"][1], 6)],
                                     "z": _v(it.get("z", 0.0), "design"), "rotation": round(it.get("rot", 0.0), 3)},
                       "size": {"w": _v(it["w"], "design"), "d": _v(it["d"], "design"), "h": _v(it["h"], "design")},
                       "info": {"category": cat, "subtype": f"design: {it.get('name', cat)}"}}
        rot = it.get("rot", 0.0) % 90
        if cab and min(rot, 90 - rot) < 1:                  # the renderer builds axis-aligned casework
            spec = {"id": it["id"], "kind": cab, "front": _front(it.get("rot", 0.0))}
            if cab in ("base", "vanity"):
                spec["unit"] = it["w"] + 0.001                # one cabinet box per item
                if it["cat"] == "sink":
                    spec["drawers"] = False
            if cab == "tall":
                ax = 0 if spec["front"][1] == "y" else 1
                c, half = it["at"][ax], it["w"] / 2
                spec["units"] = [{"a": [round((c - half) * FT, 3), round((c + half) * FT, 3)], "type": "pantry"}]
            cabinets.append(spec)
        w_ft = it["w"] * FT
        if it["cat"] == "corner" and it.get("style", "lazy") != "blind":     # L-shaped corner: 36" along each wall
            lf["base"] += (it["w"] + it["d"] - 0.6096) * FT
            counter_sf += (it["w"] * it["d"] - (it["w"] - 0.6096) * (it["d"] - 0.6096)) / 0.3048 ** 2 + 0.2
            hardware["lazy"] += it.get("style", "lazy") == "lazy"
        elif it["cat"] in ("base", "sink", "filler", "trash", "corner") and it.get("z", 0) < 1.0:
            hardware["trash"] += it["cat"] == "trash"
            lf["base"] += w_ft
            counter_sf += w_ft * (it["d"] + (it.get("bump") or 0) + 0.025) * FT     # the top runs back to the wall over a bump-out
        elif it["cat"] == "upper" or (it["cat"] == "filler" and it.get("z", 0) >= 1.0):
            lf["wall"] += w_ft
        elif it["cat"] == "tall":
            lf["tall"] += w_ft
        elif it["cat"] == "island":
            lf["island"] += w_ft
            counter_sf += w_ft * it["d"] * FT
        elif it["cat"] == "vanity":
            fixtures.append(f"vanity {it['w'] * FT * 12:.0f}\"")
        elif it["cat"] in ("toilet", "tub", "shower"):
            fixtures.append(it["cat"])
        elif it["cat"] in ("range", "fridge", "dw"):
            appliances += 1
            if it["cat"] == "dw":                            # the countertop runs over the dishwasher
                counter_sf += w_ft * (it["d"] + (it.get("bump") or 0) + 0.025) * FT
        elif it["cat"] == "panel":
            hardware["panel"] += 1
        elif it["cat"] == "micro":                            # the cabinet over the microwave is upper run; the microwave is an appliance
            lf["wall"] += w_ft
            appliances += 1
        elif it["cat"] == "hood":
            hardware["hood"] += 1
    lines = []
    run = max(lf["base"], lf["wall"])
    if run:
        lines.append({"key": "cab_base", "qty": round(run, 1), "note": f"{lf['base']:.1f} lf base, {lf['wall']:.1f} lf upper"})
    if lf["tall"]:
        lines.append({"key": "cab_tall", "qty": round(lf["tall"], 1), "note": ""})
    if lf["island"]:
        lines.append({"key": "cab_island", "qty": round(lf["island"], 1), "note": ""})
    if counter_sf:
        lines.append({"key": "counter", "qty": round(counter_sf, 1), "note": "base runs + island"})
    if appliances:
        lines.append({"key": "appliances", "qty": 1, "note": f"{appliances} placed"})
    if fixtures:
        lines.append({"key": "plumb_fixture", "qty": len(fixtures), "note": ", ".join(fixtures)})
    if hardware["trash"]:
        lines.append({"key": "trash_pullout", "qty": hardware["trash"], "note": "double-bin pull-out kit"})
    if hardware["hood"]:
        lines.append({"key": "range_hood", "qty": hardware["hood"], "note": "stainless chimney hood, ducted outside"})
    if hardware["panel"]:
        lines.append({"key": "fridge_panel", "qty": hardware["panel"], "note": "full-height end panel beside the fridge"})
    if hardware["lazy"]:
        lines.append({"key": "lazy_susan", "qty": hardware["lazy"], "note": "corner lazy susan"})
    if bumps:
        b_lf = sum(it["w"] for it in bumps) * FT
        sizes = ", ".join(f"{it['w'] / 0.0254:.0f}\" wide x {it['h'] / 0.0254:.0f}\" tall x {it['bump'] / 0.0254:.1f}\" deep" for it in bumps)
        layout.append({"id": "layout:bumpout", "group": "Layout changes", "label": "Framed bump-out behind cabinets flush with the fridge",
                       "existing": "", "default": "do",
                       "options": {"do": {"label": "Do it", "lines": [{"key": "cab_bumpout", "qty": round(b_lf, 1),
                                                                       "note": f"2x4 plates + studs @ 16\" o.c., drywall; {sizes}"}]},
                                   "skip": {"label": "Skip", "lines": []}}})
    if lines:
        layout.append({"id": "layout:items", "group": "Layout changes", "label": "Cabinets, fixtures + appliances (from the design)",
                       "existing": "", "default": "do",
                       "options": {"do": {"label": "Do it", "lines": lines}, "skip": {"label": "Skip", "lines": []}}})
    return cabinets


def _ceilings(E, ceilings, layout):
    """Ceiling changes from the editor: flat height on the room, or vaulted to the roof."""
    from shapely.geometry import Polygon as Pg
    ridged = {}
    by_space = {}
    for c in ceilings:           # one setting per room (the last one given wins)
        sp = next((e for e in E.values() if e["type"] == "space" and Pg(e["boundary"]).buffer(0.1).contains(Point(c["at"]))), None)
        if sp:
            by_space.pop(sp["id"], None)
            by_space[sp["id"]] = c
    ceilings = list(by_space.values())
    for c in ceilings:
        sp = next((e for e in E.values() if e["type"] == "space" and Pg(e["boundary"]).buffer(0.1).contains(Point(c["at"]))), None)
        if not sp:
            continue
        area = Pg(sp["boundary"]).area * 10.7639
        roof = next((e for e in E.values() if e["type"] == "roof" and e["storey"] == sp["storey"] and Pg(e["footprint"]).contains(Point(c["at"]))), None)
        sub = ((roof or {}).get("info") or {}).get("subtype", "")
        info = sp.setdefault("info", {})
        if c["mode"] == "vault":
            info["notes"] = (info.get("notes", "") + " · design: vaulted ceiling following the roof").lstrip(" ·")
            lines = [{"key": "demo_select", "qty": round(area, 0), "note": "take down the flat ceiling"},
                     {"key": "insul_roof", "qty": round(area * 1.1, 0), "note": "insulate the roof slope"},
                     {"key": "drywall", "qty": round(area * 1.12, 0), "note": "sloped ceiling"}]
            if "trusses" in sub:
                lines.append({"key": "frame_roof", "qty": round(area, 0), "note": "scissor trusses over this room (truss order)"})
            elif roof and roof["id"] in ridged:
                lines.append({"key": "frame_roof", "qty": round(area * 0.3, 0), "note": f"rafter ties out; carried by the ridge beam (see {ridged[roof['id']]})"})
            else:     # one structural ridge beam per roof covers every vaulted room under it
                lines += [{"key": "beam", "qty": 1, "note": "structural ridge beam + posts down to footings — ceiling joists / rafter ties come out"},
                          {"key": "engineer", "qty": 1, "note": "vault: ridge beam, posts + footings"}]
                if roof:
                    ridged[roof["id"]] = sp["name"]
            layout.append({"id": f"layout:ceil:{sp['id']}", "group": "Layout changes", "label": f"Vault the ceiling: {sp['name']}", "existing": "",
                           "default": "do", "options": {"do": {"label": "Do it", "lines": lines}, "skip": {"label": "Skip", "lines": []}}})
        else:
            old = sp["height"]["value"] if isinstance(sp.get("height"), dict) else 2.44
            sp["height"] = _v(c["h"], "design: ceiling height")
            if abs(c["h"] - old) < 0.02:
                continue
            plate = roof["plate_height"]["value"] if roof else None
            lines = [{"key": "drywall", "qty": round(area, 0), "note": f"new ceiling at {c['h'] * FT:.2f} ft"}]
            if c["h"] < old:
                lines.insert(0, {"key": "frame_int", "qty": round(area, 0), "note": "drop-ceiling framing"})
            elif plate and c["h"] > plate + 0.02:
                lines += [{"key": "frame_ext", "qty": round(math.sqrt(area) * 4 * (c["h"] - plate) * FT, 0), "note": "raise the walls"},
                          {"key": "frame_roof", "qty": round(area, 0), "note": "raise / reframe the roof over it"},
                          {"key": "engineer", "qty": 1, "note": "raised ceiling + roof"}]
            layout.append({"id": f"layout:ceil:{sp['id']}", "group": "Layout changes", "label": f"Ceiling to {c['h'] * FT:.1f} ft: {sp['name']}", "existing": f"{old * FT:.1f} ft",
                           "default": "do", "options": {"do": {"label": "Do it", "lines": lines}, "skip": {"label": "Skip", "lines": []}}})


def _attach_walls(E, rf):
    """After a roof is turned: walls under its rake / abut edges run up to it, walls under its eaves stop at the plate."""
    P = rf["footprint"]
    n = len(P)
    for w in [e for e in E.values() if e["type"] == "wall" and e["storey"] == rf["storey"] and e.get("exterior")]:
        mid = Point((w["start"][0] + w["end"][0]) / 2, (w["start"][1] + w["end"][1]) / 2)
        L = _wall_len(w) or 1
        dw = [(w["end"][0] - w["start"][0]) / L, (w["end"][1] - w["start"][1]) / L]
        for i in range(n):
            a, b = P[i], P[(i + 1) % n]
            Le = math.dist(a, b) or 1
            if LineString([a, b]).distance(mid) > 0.35 or abs(dw[0] * (b[0] - a[0]) / Le + dw[1] * (b[1] - a[1]) / Le) < 0.95:
                continue
            if rf["edge_roles"][i] == "eave":
                if (w.get("top") or {}).get("attach") == rf["id"]:
                    w.pop("top", None)
                    w["height"] = _v(rf["plate_height"]["value"] - (w.get("base_offset") or {"value": 0.0})["value"], "design: eave wall, up to the plate")
            else:
                w["top"] = {"attach": rf["id"]}
            break


def _extend_slope(E, R0, reg, t, t_old, wall_top, st, label, n_r, layout, area_sf):
    """Carry the house roof's slope out over an addition along its eave, at a lower pitch (a 'saltbox' / broken
    back). The new plane starts where it meets the old slope behind the eave and runs down to the addition's
    far wall; the old slope under it comes off. Returns the new roof id, or None when it does not fit
    (would need under 2/12, would break past the ridge, or the addition runs past the house ends)."""
    F0 = R0["footprint"]
    n0 = len(F0)
    if n0 != 4:
        return None
    cx, cy = sum(p[0] for p in F0) / n0, sum(p[1] for p in F0) / n0
    poly = reg.buffer(t, join_style=2)
    best = None
    for k0 in range(n0):
        if R0["edge_roles"][k0] != "eave":
            continue
        a0, b0 = F0[k0], F0[(k0 + 1) % n0]
        Le = math.dist(a0, b0)
        u0 = [(b0[0] - a0[0]) / Le, (b0[1] - a0[1]) / Le]
        nv = [-u0[1], u0[0]]
        if (cx - a0[0]) * nv[0] + (cy - a0[1]) * nv[1] < 0:
            nv = [-nv[0], -nv[1]]                     # inward, toward the ridge
        pts = list(poly.exterior.coords)
        ws = [(p[0] - a0[0]) * nv[0] + (p[1] - a0[1]) * nv[1] for p in pts]
        us = [(p[0] - a0[0]) * u0[0] + (p[1] - a0[1]) * u0[1] for p in pts]
        if max(ws) > 0.3:                             # not out beyond this eave
            continue
        if best is None or min(ws) < best[0]:
            best = (min(ws), k0, a0, u0, nv, min(us), max(us), Le)
    if not best:
        return None
    wmin, k0, a0, u0, nv, umin, umax, Le = best
    dA = -wmin                                       # how far the addition runs out past the eave edge
    if umin < -0.3 or umax > Le + 0.3:
        return None
    s0, plate0 = R0["pitch"]["value"], R0["plate_height"]["value"]
    half = max(abs((p[0] - a0[0]) * nv[0] + (p[1] - a0[1]) * nv[1]) for p in F0) / 2
    pick = None
    for p in (3 / 12, 2.5 / 12, 2 / 12):
        if s0 - p <= 0.02:
            continue
        d = (wall_top - plate0 + p * dA) / (s0 - p)  # where the new plane meets the old slope, measured in from the eave
        if 0 < d <= 0.85 * half:
            pick = (p, d)
            break
    if not pick:
        # taller addition walls: start the new plane at the ridge (the whole back slope is replaced), if that is still >= 2/12
        p = (plate0 + half * s0 - wall_top) / (half + dA)
        narrow = (umax - umin) / 2 / 3 <= plate0 + half * s0 - wall_top - 0.15   # a 4/12 gable fits under the ridge: use that
        if not narrow and 2 / 12 - 1e-6 <= p < s0 - 0.02:
            pick = (p, half)
    if not pick:
        return None
    p, d = pick
    sides = []
    for uu, end in ((umin, 0.0), (umax, Le)):
        if abs(uu - end) < 0.3:
            sides.append((end, "rake"))               # lines up with the house's gable end: same rake overhang
        else:
            sides.append((uu, "abut"))                # stops part-way along the house: flush edge + a cheek wall
    Q = lambda u, w: (a0[0] + u0[0] * u + nv[0] * w, a0[1] + u0[1] * u + nv[1] * w)
    pts = [Q(sides[0][0], d), Q(sides[1][0], d), Q(sides[1][0], -dA), Q(sides[0][0], -dA)]
    roles = ["abut", sides[1][1], "eave", sides[0][1]]
    area = sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4)) / 2
    if area < 0:
        pts = [pts[3], pts[2], pts[1], pts[0]]
        roles = [roles[2], roles[1], roles[0], roles[3]]
    rid = f"RF-ADD-{st}-{n_r}"
    rf = {"type": "roof", "id": rid, "name": f"{label} roof (house back slope carried out at {p * 12:.1f}/12)", "storey": st,
          "form": "shed", "phase": "new", "footprint": [[round(x, 6), round(y, 6)] for x, y in pts], "edge_roles": roles,
          "pitch": _v(p, f"design: {p * 12:.1f}/12, meets the old slope {d * FT:.1f} ft in from the eave"),
          "plate_height": _v(wall_top, "design: top of the addition walls"),
          "overhang": _v(0.3048, "design: 12 in eaves"),
          "rake_overhang": _v((R0.get("rake_overhang") or {"value": 0.3048})["value"] + 0.05, "design: just past the house rake so it covers the old rake trim"),
          "thickness": copy.deepcopy(R0["thickness"])}
    if R0.get("material"):
        rf["material"] = R0["material"]
    # other roofs it runs into (a garage alongside): the new roof dies into them where it is lower
    rf["_ext_host"] = R0["id"]      # trims against neighbouring roofs are set once every storey is done (see _additions)
    E[rid] = rf
    R0["trim_by"] = list(dict.fromkeys((R0.get("trim_by") or []) + [rid]))   # the old slope under it comes off
    # walls: the house's gable-end walls that cross the break line are split there; the part out back runs up to
    # the new plane. Addition walls along its sides do the same.
    zone = Polygon(rf["footprint"]).buffer(0.2, join_style=2)
    for w in [e for e in list(E.values()) if e["type"] == "wall" and e.get("exterior") and e["storey"] == st]:
        s, e_ = w["start"], w["end"]
        ws_, we_ = [(q[0] - a0[0]) * nv[0] + (q[1] - a0[1]) * nv[1] for q in (s, e_)]
        us_ = [(q[0] - a0[0]) * u0[0] + (q[1] - a0[1]) * u0[1] for q in (s, e_)]
        L = _wall_len(w) or 1
        along_v = abs(ws_ - we_) / L > 0.95
        if not along_v or not (min(us_) > sides[0][0] - 0.3 and max(us_) < sides[1][0] + 0.3) or \
                not zone.intersects(LineString([s, e_])):
            continue
        if (w.get("top") or {}).get("attach") == R0["id"] and min(ws_, we_) < d - 0.05 < max(ws_, we_) - 0.05 + 0.05 and max(ws_, we_) > d + 0.05:
            # split at the break line: (d) on the house side stays under the old roof
            fr = (ws_ - d) / (ws_ - we_)
            cut = [round(s[0] + (e_[0] - s[0]) * fr, 6), round(s[1] + (e_[1] - s[1]) * fr, 6)]
            nw = copy.deepcopy(w)
            nid = f"{w['id']}-OUT"
            nw.update({"id": nid, "name": f"{w.get('name', w['id'])} (under the extended roof)", "phase": "new",
                       "top": {"attach": rid}})
            for kk in ("history", "aliases"):
                nw.pop(kk, None)
            out_first = ws_ < we_                    # start is the out-back end
            u_cut = fr * L
            if out_first:
                nw["start"], nw["end"] = list(s), cut
                w["start"] = cut
            else:
                nw["start"], nw["end"] = cut, list(e_)
                w["end"] = cut
            E[nid] = nw
            for o in [x for x in E.values() if x.get("host") == w["id"] or ((x.get("placement") or {}).get("on") == "wall" and (x.get("placement") or {}).get("wall") == w["id"])]:
                key = "offset" if o.get("host") == w["id"] else None
                val = o["offset"]["value"] if key else (o["placement"]["u"]["value"] if isinstance(o["placement"].get("u"), dict) else None)
                if val is None:
                    continue
                if out_first:
                    if val < u_cut:
                        (o.__setitem__("host", nid) if key else o["placement"].__setitem__("wall", nid))
                    else:
                        (o["offset"] if key else o["placement"]["u"]).__setitem__("value", round(val - u_cut, 6))
                elif val >= u_cut:
                    (o.__setitem__("host", nid) if key else o["placement"].__setitem__("wall", nid))
                    (o["offset"] if key else o["placement"]["u"]).__setitem__("value", round(val - u_cut, 6))
        elif max(ws_, we_) <= d + 0.05:
            if (w.get("top") or {}).get("attach") != R0["id"] or min(ws_, we_) < -0.05:
                w["top"] = {"attach": rid}
                w["height"] = _v(wall_top + 3.0 - (w.get("base_offset") or {"value": 0.0})["value"], "design: clipped to the extended roof")
    # cheek walls: where the new plane stops part-way along the house it stands above the old slope
    tmpl = next((e for e in E.values() if e["type"] == "wall" and e.get("exterior") and e["storey"] == st and e["id"] not in R0.get("trim_by", []) and e.get("phase") == "new"), None)
    cheeks = []
    for j, (uu, role) in enumerate(sides):
        if role != "abut" or tmpl is None:
            continue
        uc = uu - t / 2 if j == 1 else uu + t / 2
        cw = copy.deepcopy(tmpl)
        for kk in ("history", "aliases", "top"):
            cw.pop(kk, None)
        cid = f"N-W-CHEEK-{st}-{n_r}-{j}"
        cw.update({"id": cid, "name": "Cheek wall where the extended roof stands above the old slope", "phase": "new",
                   "start": [round(v, 6) for v in Q(uc, d)], "end": [round(v, 6) for v in Q(uc, 0.01)],
                   "thickness": _v(t, "design: matches the addition walls"),
                   "base_offset": _v(plate0, "design: sits on the house wall plate"), "height": _v(3.0, "design: clipped to the extended roof"),
                   "top": {"attach": rid}, "exterior": True})
        E[cid] = cw
        cheeks.append(cid)
    plan_sf = Polygon(rf["footprint"]).area * 10.7639
    old_sf = max(0.0, plan_sf - area_sf)
    roof_sf = plan_sf * math.sqrt(1 + p * p) * 1.12
    eave_lf = sum(math.dist(pts[i], pts[(i + 1) % 4]) for i in range(4) if roles[i] == "eave")
    layout.append({"id": f"layout:addition:{st}:{n_r}", "group": "Layout changes",
                   "label": f"Addition: {label} ({area_sf:.0f} sf, house back slope carried out at {p * 12:.1f}/12)",
                   "existing": "", "default": "do",
                   "options": {"do": {"label": "Do it", "lines": [
                       {"key": "foundation", "qty": round(area_sf * 1.1, 0), "note": "to the outside of the walls"},
                       {"key": "demo_select", "qty": round(old_sf, 0), "note": "strip the old back slope where the new roof ties in"},
                       {"key": "frame_roof", "qty": round(roof_sf, 0), "note": f"{p * 12:.1f}/12 rafters from the old slope to the new back wall"},
                       {"key": "roof_replace", "qty": round(roof_sf, 0), "note": f"{p * 12:.1f}/12 is low-slope: ice & water shield under the whole plane"},
                       {"key": "insul_roof", "qty": round(area_sf, 0), "note": ""},
                       {"key": "drywall", "qty": round(area_sf, 0), "note": "ceiling"},
                       {"key": "gutter_new", "qty": round(eave_lf * FT, 0), "note": ""},
                       {"key": "elec_new", "qty": round(area_sf, 0), "note": ""},
                       {"key": "hvac_extend", "qty": round(area_sf, 0), "note": "if it will be heated"},
                       {"key": "permit_addition", "qty": 1, "note": ""}]
                       + ([{"key": "frame_ext", "qty": round(sum(0.5 * (d) * (d * (s0 - p)) for _ in cheeks) * 10.7639, 0), "note": "cheek wall(s), sided to match"}] if cheeks else [])},
                       "skip": {"label": "Skip", "lines": []}}})
    return rid


def _ext_trims(E):
    """An extended slope dies into any neighbouring roof (a garage alongside) where it is the lower one."""
    for rf in [e for e in E.values() if e["type"] == "roof" and e.get("_ext_host")]:
        host = rf.pop("_ext_host")
        fp_rf = Polygon(rf["footprint"]).buffer(0.5, join_style=2)
        others = [e["id"] for e in E.values() if e["type"] == "roof" and e["id"] not in (host, rf["id"])
                  and Polygon(e["footprint"]).buffer(0.5, join_style=2).intersects(fp_rf) and rf["id"] not in (e.get("trim_by") or [])]
        if others:
            rf["trim_by"] = others


def _additions(E0, E, layout):
    """New rooms outside an existing building: slab, roof and the scope that goes with them.

    A building made bigger by moving a whole side out keeps its own roof, stretched. Anything
    else outside the old outline is an addition: one roof per connected addition, a shed tucked
    under the old eave when there is room, otherwise its own gable tied in (ridge running out)."""
    from shapely.geometry import Polygon as Pg, box as Box
    from shapely.ops import unary_union as UU
    for st in sorted({e["storey"] for e in E.values() if e["type"] == "space"}):
        old_ext = [e for e in E0.values() if e["type"] == "wall" and e["storey"] == st and e.get("exterior")]
        if not old_ext:
            continue
        xs = [c for w in old_ext for c in (w["start"][0], w["end"][0])]
        ys = [c for w in old_ext for c in (w["start"][1], w["end"][1])]
        B = [min(xs), max(xs), min(ys), max(ys)]

        def side_shift(axis, val):
            on = [w for w in old_ext if abs(w["start"][axis] - val) < 0.05 and abs(w["end"][axis] - val) < 0.05]
            ds = [((E[w["id"]]["start"][axis] + E[w["id"]]["end"][axis]) / 2 - val) for w in on if w["id"] in E]
            return ds[0] if ds and all(abs(d - ds[0]) < 0.02 for d in ds) and len(ds) == len(on) else 0.0
        sh = [side_shift(0, B[0]), side_shift(0, B[1]), side_shift(1, B[2]), side_shift(1, B[3])]
        roof0 = next((e for e in E.values() if e["type"] == "roof" and e["storey"] == st and e["id"] in E0), None)
        if roof0 and any(abs(v) > 0.01 for v in sh):      # the whole side moved: stretch the old roof with it
            tol = 0.6
            roof0["footprint"] = [[round(x + (sh[0] if abs(x - B[0]) < tol else sh[1] if abs(x - B[1]) < tol else 0), 6),
                                   round(y + (sh[2] if abs(y - B[2]) < tol else sh[3] if abs(y - B[3]) < tol else 0), 6)] for x, y in roof0["footprint"]]
        B = [B[0] + sh[0], B[1] + sh[1], B[2] + sh[2], B[3] + sh[3]]
        box = Box(B[0], B[2], B[1], B[3])
        if roof0 and roof0.pop("_roles_changed", False):
            _attach_walls(E, roof0)
        t_old = max(w["thickness"]["value"] for w in old_ext)
        new_ext = [e for e in E.values() if e["type"] == "wall" and e["storey"] == st and e.get("exterior") and e["id"] not in E0]
        if not new_ext:
            continue
        t = max(w["thickness"]["value"] for w in new_ext)
        slabs = sorted((e for e in E0.values() if e["type"] == "slab" and e["storey"] == st), key=lambda e: -Pg(e["boundary"]).area)
        pieces = []
        for sp in [e for e in E.values() if e["type"] == "space" and e["storey"] == st]:
            out_part = Pg(sp["boundary"]).difference(box.buffer(t_old / 2 + 0.005, join_style=2))
            for poly in ([out_part] if out_part.geom_type == "Polygon" else list(getattr(out_part, "geoms", []))):
                if poly.area < 1.0:
                    continue
                poly = orient(poly.buffer(0), sign=1.0)
                pieces.append((sp, poly))
                if slabs:
                    sl = copy.deepcopy(slabs[0])
                    sl.pop("history", None)
                    sl.update({"id": f"SL-{sp['id']}-ADD{len(pieces)}", "name": f"{sp['name']} floor (addition)", "phase": "new",
                               "boundary": [[round(x, 6), round(y, 6)] for x, y in list(orient(poly.buffer(-0.02, join_style=2), sign=1.0).exterior.coords)[:-1]]})
                    E[sl["id"]] = sl
        if not pieces:
            continue
        merged = UU([p.buffer(0.2, join_style=2) for _, p in pieces]).buffer(-0.2, join_style=2)
        regions = [merged] if merged.geom_type == "Polygon" else list(merged.geoms)
        R0 = next((E.get(e["id"], e) for e in E0.values() if e["type"] == "roof" and e["storey"] == st), None)   # as designed (turned, stretched)
        for n_r, reg in enumerate(sorted(regions, key=lambda r: -r.area)):
            names = [sp["name"] for sp, p in pieces if p.intersects(reg)]
            label = " + ".join(dict.fromkeys(names)) or "Addition"
            area_sf = reg.area * 10.7639
            fp = reg.buffer(t, join_style=2).difference(box.buffer(t_old / 2, join_style=2))
            fp = fp if fp.geom_type == "Polygon" else max(fp.geoms, key=lambda x: x.area)
            fp = fp.envelope if fp.area / max(fp.envelope.area, 1e-9) > 0.8 else fp
            fp = orient(fp.simplify(0.005), sign=1.0)
            P = list(fp.exterior.coords)[:-1]
            n = len(P)
            lens = [math.dist(P[i], P[(i + 1) % n]) for i in range(n)]
            roles, abut = [], []
            for i in range(n):
                a, b = P[i], P[(i + 1) % n]
                mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                touching = box.exterior.distance(mid) < t_old / 2 + t + 0.05
                roles.append("abut" if touching else "rake")
                if touching:
                    abut.append(i)
            wall_top = max(w["height"]["value"] + w["base_offset"]["value"] for w in new_ext)
            plate, pitch, form, note = wall_top, 1 / 3, "gable", ""
            if abut and n == 4:
                k = abut[0]
                depth = lens[(k + 1) % 4]
                against_eave = False
                if R0:
                    a, b = P[k], P[(k + 1) % 4]
                    mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    F0 = R0["footprint"]
                    k0 = min(range(len(F0)), key=lambda q: LineString([F0[q], F0[(q + 1) % len(F0)]]).distance(mid))
                    against_eave = R0["edge_roles"][k0] == "eave"
                room = (R0["plate_height"]["value"] - 0.05 - wall_top) if (R0 and against_eave) else 9.0
                ext = None
                if room >= depth * 2 / 12:
                    form, pitch = "shed", min(0.25, room / depth)
                    roles[(k + 2) % 4] = "eave"
                    note = f", {pitch * 12:.1f}/12 shed" + (" tucked under the house eave" if against_eave else "")
                elif against_eave and (ext := _extend_slope(E, R0, reg, t, t_old, wall_top, st, label, n_r, layout, area_sf)):
                    continue    # the house's own slope carried out over the addition (one roof plane, no valleys)
                else:   # no room under the eave for a shed: own gable, ridge running out from the building
                    roles[(k + 1) % 4] = "eave"
                    roles[(k + 3) % 4] = "eave"
                    if R0:      # keep its ridge below the house ridge so it ties in with two valleys
                        F0 = R0["footprint"]
                        k0e = R0["edge_roles"].index("eave")
                        a0, b0 = F0[k0e], F0[(k0e + 1) % len(F0)]
                        u0 = [(b0[0] - a0[0]) / math.dist(a0, b0), (b0[1] - a0[1]) / math.dist(a0, b0)]
                        span0 = max(abs((p[0] - a0[0]) * -u0[1] + (p[1] - a0[1]) * u0[0]) for p in F0)
                        host_rise = span0 / 2 * R0["pitch"]["value"] + R0["plate_height"]["value"] - wall_top
                        half = lens[k] / 2
                        pitch = max(2 / 12, min(1 / 3, (host_rise - 0.15) / max(half, 0.1)))
                        if against_eave:   # run the gable on into the old slope; the old roof trims it (valleys)
                            ridge_up = wall_top + half * pitch - R0["plate_height"]["value"]
                            reach = max(0.0, ridge_up / R0["pitch"]["value"]) + 0.15
                            a, b = P[k], P[(k + 1) % 4]
                            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                            gx, gy = sum(q[0] for q in P) / 4, sum(q[1] for q in P) / 4
                            ex, ey = b[0] - a[0], b[1] - a[1]
                            el_ = math.hypot(ex, ey)
                            nx, ny = -ey / el_, ex / el_
                            if (mx - gx) * nx + (my - gy) * ny < 0:
                                nx, ny = -nx, -ny
                            P[k] = (a[0] + nx * reach, a[1] + ny * reach)
                            P[(k + 1) % 4] = (b[0] + nx * reach, b[1] + ny * reach)
                            lens = [math.dist(P[i], P[(i + 1) % n]) for i in range(n)]
                    note = f", {pitch * 12:.1f}/12 gable tied into the house roof"
            else:
                for i in sorted(range(n), key=lambda i: -lens[i])[:2]:
                    roles[i] = "eave"
            rf = {"type": "roof", "id": f"RF-ADD-{st}-{n_r}", "name": f"{label} roof (addition{note})", "storey": st, "form": form, "phase": "new",
                  "footprint": [[round(x, 6), round(y, 6)] for x, y in P], "edge_roles": roles,
                  "pitch": _v(pitch, f"design: {pitch * 12:.1f}/12 {form}"), "plate_height": _v(plate, "design: top of the addition walls"),
                  "overhang": _v(0.3048, "design: 12 in eaves"), "rake_overhang": _v(0.1524, "design: 6 in rakes"),
                  "thickness": copy.deepcopy(R0["thickness"]) if R0 else _v(0.2, "design")}
            if R0 and R0.get("material"):
                rf["material"] = R0["material"]
            if R0 and abut:
                rf["trim_by"] = [R0["id"]]
            E[rf["id"]] = rf
            for w in new_ext:      # new walls under a sloped (rake) edge run up to the new roof
                mid = Point((w["start"][0] + w["end"][0]) / 2, (w["start"][1] + w["end"][1]) / 2)
                for i in range(n):
                    if roles[i] == "rake" and LineString([P[i], P[(i + 1) % n]]).distance(mid) < t:
                        w["top"] = {"attach": rf["id"]}
                        w["height"] = _v(plate + 3.0 - w["base_offset"]["value"], "design: clipped to the addition roof")
            eave_lf = sum(lens[i] for i in range(n) if roles[i] == "eave") * FT
            roof_sf = area_sf * math.sqrt(1 + pitch ** 2) * 1.12
            layout.append({"id": f"layout:addition:{st}:{n_r}", "group": "Layout changes", "label": f"Addition: {label} ({area_sf:.0f} sf{note})",
                           "existing": "", "default": "do",
                           "options": {"do": {"label": "Do it", "lines": [
                               {"key": "foundation", "qty": round(area_sf * 1.1, 0), "note": "to the outside of the walls"},
                               {"key": "frame_roof", "qty": round(roof_sf, 0), "note": f"{pitch * 12:.0f}/12 {form}"},
                               {"key": "roof_replace", "qty": round(roof_sf, 0), "note": "shingles to match"},
                               {"key": "insul_roof", "qty": round(area_sf, 0), "note": ""},
                               {"key": "drywall", "qty": round(area_sf, 0), "note": "ceiling"},
                               {"key": "gutter_new", "qty": round(eave_lf, 0), "note": ""},
                               {"key": "elec_new", "qty": round(area_sf, 0), "note": ""},
                               {"key": "hvac_extend", "qty": round(area_sf, 0), "note": "if it will be heated"},
                               {"key": "permit_addition", "qty": 1, "note": ""}]},
                               "skip": {"label": "Skip", "lines": []}}})


def _rederive_rooms(E, st, base_spaces, names, covers=None):
    walls = [e for e in E.values() if e["type"] == "wall" and e["storey"] == st]
    segs = []
    for w in walls:
        a, b = list(w["start"]), list(w["end"])
        # pull ends drawn to another wall's face onto its centreline (same rule as the editor)
        for k in (0, 1):
            p, q = (a, b) if k == 0 else (b, a)
            dx, dy = p[0] - q[0], p[1] - q[1]
            L = math.hypot(dx, dy) or 1
            dx, dy = dx / L, dy / L
            best, bd = None, 1e9
            for o in walls:
                if o is w:
                    continue
                ox, oy = o["end"][0] - o["start"][0], o["end"][1] - o["start"][1]
                OL = math.hypot(ox, oy) or 1
                ox, oy = ox / OL, oy / OL
                if abs(ox * dx + oy * dy) > 0.9:
                    continue
                nx, ny = -oy, ox
                den = dx * nx + dy * ny
                t = ((o["start"][0] - p[0]) * nx + (o["start"][1] - p[1]) * ny) / den
                if t < -0.005 or abs(t) > o["thickness"]["value"] / 2 + 0.03 or abs(t) >= bd:   # only lengthen
                    continue
                hit = (p[0] + dx * t, p[1] + dy * t)
                if LineString([o["start"], o["end"]]).distance(Point(hit)) > 0.03:
                    continue
                best, bd = hit, abs(t)
            if best:
                p[0], p[1] = best
        segs.append([a, b])
    # weld endpoints that sit within 3 cm of each other or of another wall line (drawn by hand)
    pts = [p for sg in segs for p in sg]
    for sg in segs:
        for p in sg:
            for q in pts:
                if q is not p and 1e-9 < math.dist(p, q) < 0.03:
                    p[0], p[1] = q[0], q[1]
                    break
    for sg in segs:
        for p in sg:
            for other in segs:
                if other is sg:
                    continue
                ln = LineString(other)
                if 1e-9 < ln.distance(Point(p)) < 0.03:
                    q = ln.interpolate(ln.project(Point(p)))
                    p[0], p[1] = q.x, q.y
    out = []
    for w, sg in zip(walls, segs):
        cuts = sorted((o["offset"]["value"], o["offset"]["value"] + o["width"]["value"]) for o in E.values()
                      if o["type"] == "opening" and o.get("host") == w["id"] and (o.get("info") or {}).get("subtype") == "removed section")
        if not cuts:
            out.append(sg)
            continue
        L = math.dist(w["start"], w["end"]) or 1
        d = [(w["end"][0] - w["start"][0]) / L, (w["end"][1] - w["start"][1]) / L]
        at = lambda u: [w["start"][0] + d[0] * u, w["start"][1] + d[1] * u]
        a = sg[0]
        for x0, x1 in cuts:
            out.append([a, at(x0)])
            a = at(x1)
        out.append([a, sg[1]])
    segs = [LineString(sg) for sg in out if math.dist(sg[0], sg[1]) > 0.05]
    faces = [f for f in polygonize(unary_union(segs)) if f.area > 0.15]
    thick = {w["id"]: w["thickness"]["value"] for w in walls}
    half = (sorted(thick.values())[len(thick) // 2] if thick else 0.114) / 2

    old = {k: e for k, e in base_spaces.items() if e["storey"] == st}
    for k in old:
        E.pop(k, None)
    used = set()
    for n, f in enumerate(sorted(faces, key=lambda f: -f.area)):
        inner = f.buffer(-half, join_style=2)
        if inner.is_empty:
            continue
        if inner.geom_type != "Polygon":
            inner = max(inner.geoms, key=lambda x: x.area)
        inner = orient(inner.simplify(0.005), sign=1.0)
        contains = [k for k, e in old.items() if f.contains(Polygon(e["boundary"]).representative_point())]
        contains.sort(key=lambda k: -Polygon(old[k]["boundary"]).area)
        given = [nm for at, nm in names if f.contains(Point(at))]
        if contains and contains[0] not in used:
            sp = copy.deepcopy(old[contains[0]])
            used.add(contains[0])
            if len(contains) > 1:
                sp["name"] = " + ".join(old[k]["name"].split(" (")[0] for k in contains)
                info = sp.setdefault("info", {})
                info["notes"] = (info.get("notes", "") + " · design: merged " + ", ".join(contains)).lstrip(" ·")
        else:
            if f.area / (f.length / 2) < 0.3:   # a chase between two walls, not a room
                continue
            nm = "New room" if (old or used) else ("Garage" if "GAR" in st.upper() else "Room")
            used.add(f"SP-N{n}-{st}")
            sp = {"type": "space", "id": f"SP-N{n}-{st}", "name": nm, "storey": st,
                  "height": copy.deepcopy(next(iter(old.values()))["height"]) if old else _v(2.44, "design"),
                  "info": {"category": "room", "subtype": "new"}}
        if given:
            # a merged room keeps the old room names, with any renamed part swapped for its new name
            gpts = [(at, nm) for at, nm in names if f.contains(Point(at))]
            parts = []
            for k in contains:
                ren = [nm for at, nm in gpts if Polygon(old[k]["boundary"]).buffer(0.1).contains(Point(at))]
                parts.append(ren[-1] if ren else old[k]["name"].split(" (")[0])
            extra = [nm for at, nm in gpts if not any(Polygon(old[k]["boundary"]).buffer(0.1).contains(Point(at)) for k in contains)]
            parts += extra[-1:]
            nm = " + ".join(dict.fromkeys(parts)) if parts else given[-1]
            # a name given to the whole room (it covered every old room now inside it) wins outright
            for gi in range(len(names) - 1, -1, -1):
                cv = (covers or {}).get(gi)
                if isinstance(cv, list) and f.contains(Point(names[gi][0])) and all(k in cv for k in contains):
                    nm = names[gi][1]
                    break
            sp["name"] = nm
            sp["usage"] = nm
        sp["boundary"] = [[round(x, 6), round(y, 6)] for x, y in list(inner.exterior.coords)[:-1]]
        sp.pop("bounded_by", None)
        E[sp["id"]] = sp


def main(argv):
    asb, design, out = argv[:3]
    extras = {}
    g, layout = apply_editor(json.loads(Path(asb).read_text()), json.loads(Path(design).read_text()), extras)
    if "--finishes" in argv:      # renderer casework spec for the placed cabinets
        Path(argv[argv.index("--finishes") + 1]).write_text(json.dumps({"cabinets": extras["cabinets"]}, indent=1))
    doc = json.loads(Path(design).read_text())
    g["project"]["name"] = f"{g['project'].get('name', '')} — {doc.get('name', 'design')}"
    Path(out).write_text(json.dumps(g, indent=1))
    if len(argv) > 3 and not argv[3].startswith("--"):
        Path(argv[3]).write_text(json.dumps(layout, indent=1))
    rooms = sorted((e for e in g["elements"].values() if e["type"] == "space"), key=lambda e: -Polygon(e["boundary"]).area)
    print(f"{len(layout)} scope items; rooms:")
    for r in rooms:
        print(f"  {r['storey']:4} {r['name']:40} {Polygon(r['boundary']).area * 10.7639:7.0f} sf")


if __name__ == "__main__":
    main(sys.argv[1:])
