"""Rehab scope: turns model quantities into priced decisions.

A *decision* is one thing Carter chooses (a room's floor, a roof plane, the windows on a building).
Each option of a decision carries the line items it implies, with quantities already computed
from the model. Pricing is then just qty × unit cost, so the browser page and this module price
the same way and all quantity rules live here.
"""
from __future__ import annotations

HEATED_SKIP = {"porch", "garage"}


def _cond(r, surface):
    return (r.get("condition") or {}).get(surface, "") or ""


def _line(key, qty, note=""):
    return {"key": key, "qty": round(float(qty), 2), "note": note}


def _opt(label, *lines):
    return {"label": label, "lines": [l for l in lines if l and l["qty"] > 0]}


def decisions(q: dict) -> list[dict]:
    D = []
    rooms = q["rooms"]
    ops = {o["id"]: o for o in q["openings"]}

    # ---- rooms ---------------------------------------------------------------
    for r in rooms:
        k = r["kind"]
        grp = f"Rooms · {r['name']}"
        rid = r["id"]
        fl, ex = r["floor_sf"], (r["existing"].get("floor") or "").lower()
        if k == "garage":
            continue
        wood = any(w in ex for w in ("hardwood", "softwood", "oak", "strip")) and "laminate" not in ex
        carpet = "carpet" in ex
        if k in ("porch", "closet"):
            dflt = "keep"
        elif k == "bath":
            dflt = "keep" if _cond(r, "floor") == "good" or "good" in _cond(r, "walls") else "tile"
        elif wood:
            dflt = "refinish"
        elif k == "bedroom" and carpet:
            dflt = "carpet"
        else:
            dflt = "lvp"
        demo = _line("floor_demo", fl) if (carpet or "vinyl" in ex or "laminate" in ex) else None
        D.append({"id": f"{rid}:floor", "group": grp, "label": "Floor", "existing": ex or "—", "default": dflt,
                  "options": {
                      "keep": _opt("Keep"),
                      "lvp": _opt("LVP", demo, _line("floor_lvp", fl * 1.08, "incl. 8% waste")),
                      "carpet": _opt("Carpet", demo, _line("floor_carpet", fl * 1.10, "incl. 10% waste")),
                      "tile": _opt("Tile", _line("floor_demo", fl), _line("floor_tile", fl * 1.10, "incl. 10% waste")),
                      "refinish": _opt("Refinish wood", _line("floor_refinish", fl)),
                  }})
        if k == "porch":
            continue
        D.append({"id": f"{rid}:paint", "group": grp, "label": "Walls & ceiling",
                  "existing": (r["existing"].get("walls") or "—"), "default": "paint",
                  "options": {"keep": _opt("Keep"),
                              "walls": _opt("Paint walls", _line("paint_walls", r["wall_sf"])),
                              "paint": _opt("Paint walls + ceiling", _line("paint_walls", r["wall_sf"]),
                                            _line("paint_ceiling", r["ceiling_sf"])),
                              "repair": _opt("Repair + paint all", _line("drywall_patch", 1),
                                             _line("paint_walls", r["wall_sf"]), _line("paint_ceiling", r["ceiling_sf"]))}})
        casing = sum((2 * ops[o]["h_in"] + ops[o]["w_in"]) / 12 * (1 if ops[o]["exterior"] else 2 if ops[o]["kind"] == "door" else 1)
                     for o in r["openings"] if ops[o]["kind"] in ("door", "window") and not ops[o]["screen"]) / 2
        D.append({"id": f"{rid}:trim", "group": grp, "label": "Base & casing",
                  "existing": (r["existing"].get("base") or r["existing"].get("trim") or "—"), "default": "paint",
                  "options": {"keep": _opt("Keep"),
                              "paint": _opt("Paint", _line("paint_trim", r["base_lf"] + casing)),
                              "replace": _opt("Replace + paint", _line("base_replace", r["base_lf"]),
                                              _line("casing_replace", casing), _line("paint_trim", r["base_lf"] + casing))}})
        if k == "kitchen":
            D.append({"id": f"{rid}:kitchen", "group": grp, "label": "Kitchen", "existing": "laminate tops, older cabinets",
                      "default": "remodel",
                      "options": {"keep": _opt("Keep"), "refresh": _opt("Refresh", _line("kitchen_refresh", 1)),
                                  "remodel": _opt(f"Remodel ({fl:.0f} sf)", _line("kitchen_remodel", fl))}})
        if k == "bath":
            good = "good" in _cond(r, "walls")
            D.append({"id": f"{rid}:bath", "group": grp, "label": "Bath", "existing": r["existing"].get("walls", "—"),
                      "default": "keep" if good else "remodel",
                      "options": {"keep": _opt("Keep"), "refresh": _opt("Refresh", _line("bath_refresh", 1)),
                                  "remodel": _opt("Remodel", _line("bath_remodel", 1))}})

    # ---- doors & windows -------------------------------------------------------
    for b in q["exterior"]:
        bid = b["building"]
        win = [o for o in q["openings"] if o["building"] == bid and o["kind"] == "window" and not o["screen"]]
        if win:
            big = sum(1 for o in win if o.get("large"))
            D.append({"id": f"{bid}:windows", "group": f"Openings · {b['name']}", "label": f"Windows ({len(win)})",
                      "existing": "wood sash / some vinyl", "default": "keep",
                      "options": {"keep": _opt("Keep"),
                                  "replace": _opt("Replace all", _line("window_std", len(win) - big),
                                                  _line("window_large", big))}})
        ed = [o for o in q["openings"] if o["building"] == bid and o["kind"] == "door" and o["exterior"]
              and not o["screen"] and o["w_in"] <= 72]
        if ed:
            D.append({"id": f"{bid}:extdoors", "group": f"Openings · {b['name']}", "label": f"Exterior doors ({len(ed)})",
                      "existing": ", ".join(o["name"] for o in ed)[:90], "default": "keep",
                      "options": {"keep": _opt("Keep"), "replace": _opt("Replace", _line("door_ext", len(ed)))}})
        if b["garage_doors"]:
            D.append({"id": f"{bid}:garagedoor", "group": f"Openings · {b['name']}", "label": "Garage door",
                      "existing": "overhead sectional", "default": "keep",
                      "options": {"keep": _opt("Keep"), "replace": _opt("Replace", _line("door_garage", b["garage_doors"]))}})
    idoors = [o for o in q["openings"] if o["kind"] == "door" and not o["exterior"]]
    std = [o for o in idoors if not o.get("french") and not o.get("bifold")]
    D.append({"id": "int-doors", "group": "Openings · House", "label": f"Interior doors ({len(idoors)})",
              "existing": "4-panel / panel doors", "default": "keep",
              "options": {"keep": _opt("Keep (paint with trim)"),
                          "replace": _opt("Replace all", _line("door_int", len(std)),
                                          _line("door_int_french", sum(1 for o in idoors if o.get("french"))),
                                          _line("door_bifold", sum(1 for o in idoors if o.get("bifold"))))}})

    # ---- exterior --------------------------------------------------------------
    for b in q["exterior"]:
        g = f"Exterior · {b['name']}"
        bid = b["building"]
        for rf in b["roofs"]:
            D.append({"id": f"{rf['id']}:roof", "group": g, "label": f"Roof — {rf['name']}",
                      "existing": f"{rf['pitch']} · {rf.get('condition') or ''}".strip(" ·"),
                      "default": "replace" if "poor" in (rf.get("condition") or "") else "keep",
                      "options": {"keep": _opt("Keep"), "replace": _opt(f"Replace ({rf['sf']:.0f} sf)",
                                                                        _line("roof_replace", rf["sf"] * 1.10, "incl. 10% waste/starter"))}})
        D.append({"id": f"{bid}:siding", "group": g, "label": "Siding", "existing": "wood bevel lap, paint weathered",
                  "default": "paint",
                  "options": {"keep": _opt("Keep"), "paint": _opt("Paint", _line("siding_paint", b["siding_sf"])),
                              "vinyl": _opt("Vinyl", _line("siding_vinyl", b["siding_sf"] * 1.10, "incl. 10% waste"))}})
        D.append({"id": f"{bid}:gutters", "group": g, "label": "Gutters & downspouts", "existing": "5\" K-style, fair",
                  "default": "keep",
                  "options": {"keep": _opt("Keep"), "replace": _opt("Replace", _line("gutter_replace", b["gutter_lf"]),
                                                                   _line("downspout_replace", b["downspout_lf"]))}})
        fs = b["fascia_lf"] + b["soffit_lf"]
        D.append({"id": f"{bid}:fascia", "group": g, "label": "Fascia & soffit", "existing": "painted wood, fair",
                  "default": "paint",
                  "options": {"keep": _opt("Keep"), "paint": _opt("Paint", _line("fascia_paint", fs)),
                              "wrap": _opt("Wrap + vinyl soffit", _line("fascia_wrap", b["fascia_lf"]),
                                           _line("soffit_vinyl", b["soffit_lf"]))}})
        if b["shutter_pairs"]:
            D.append({"id": f"{bid}:shutters", "group": g, "label": f"Shutters ({b['shutter_pairs']} sets)",
                      "existing": "fixed board shutters, one missing", "default": "keep",
                      "options": {"keep": _opt("Keep / paint with siding"),
                                  "replace": _opt("Replace", _line("shutter_replace", b["shutter_pairs"]))}})
        if b["screen_sf"]:
            D.append({"id": f"{bid}:screens", "group": g, "label": "Porch screens", "existing": "fixed screens",
                      "default": "rescreen",
                      "options": {"keep": _opt("Keep"), "rescreen": _opt("Re-screen", _line("screen_rescreen", b["screen_sf"]))}})

    # ---- systems & general -----------------------------------------------------
    f = q["fixtures"]
    hs = q["totals"]["heated_sf"]
    beds = sum(1 for r in rooms if r["kind"] == "bedroom")
    sys_ = [
        ("lights", "Light fixtures", f"{f['light']} counted", "replace", _line("light_fixture", f["light"])),
        ("devices", "Receptacles & switches", "older devices", "replace",
         _line("device_replace", max(f["receptacle"] + f["switch"], round(hs / 25)), "est. 1 device / 25 sf heated")),
        ("smoke", "Smoke / CO detectors", f"{f['smoke']} counted", "replace", _line("smoke_co", beds + 2)),
        ("elec", "Electrical repairs", "not inspected", "allow", _line("electrical_allow", 1)),
        ("plumb", "Plumbing repairs", "well + private sewer", "allow", _line("plumbing_allow", 1)),
        ("hvac", "HVAC service", "forced air + gas wall furnace", "allow", _line("hvac_allow", 1)),
        ("dump", "Dumpsters", "", "allow", _line("dumpster", 2)),
        ("clean", "Final clean", "", "allow", _line("clean", hs)),
        ("permit", "Permits", "", "allow", _line("permit", 1)),
    ]
    for sid, label, ex, onkey, ln in sys_:
        D.append({"id": f"sys:{sid}", "group": "Systems & general", "label": label, "existing": ex or "—", "default": onkey,
                  "options": {"none": _opt("None"), onkey: _opt("Include", ln)}})
    return D


def default_selections(D):
    return {d["id"]: d["default"] for d in D}


def price(D, sel: dict, pb: dict, contingency=0.10) -> dict:
    lines, sub = [], 0.0
    for d in D:
        opt = d["options"].get(sel.get(d["id"], d["default"]))
        if not opt:
            continue
        for ln in opt["lines"]:
            p = pb[ln["key"]]
            amt = ln["qty"] * p["cost"]
            sub += amt
            lines.append({"decision": d["id"], "group": d["group"], "choice": opt["label"], "item": p["label"],
                          "qty": ln["qty"], "unit": p["unit"], "unit_cost": p["cost"], "amount": round(amt, 2),
                          "trade": p["trade"], "source": p["source"], "note": ln["note"]})
    cont = sub * contingency
    by_trade = {}
    for l in lines:
        by_trade[l["trade"]] = by_trade.get(l["trade"], 0) + l["amount"]
    return {"lines": lines, "subtotal": round(sub, 2), "contingency": round(cont, 2), "total": round(sub + cont, 2),
            "by_trade": {k: round(v, 2) for k, v in sorted(by_trade.items(), key=lambda kv: -kv[1])}}
