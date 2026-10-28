"""Scope for a designed remodel + addition, taken off the compiled DESIGN model.

Quantities come from the design Genome: element phase ("existing" | "new") says what is built new,
wall face areas come from the compiled solids (net of openings), roofs from their top surfaces,
casework from the component sizes, openings from the schedule data carried on each opening.
Room finishes reuse takeoff.scope.decisions(), so the same room choices work for as-built and design.
"""
from __future__ import annotations

from shapely.geometry import Polygon

from .quantities import LF, SF, _up_area, quantities
from .scope import _line, _opt, decisions as room_decisions


def _face_sf(ce):
    t = ce.data.get("thickness") or 0.1
    return (ce.mesh.volume() / t) * SF if ce.mesh is not None else 0.0


def _dec(id, group, label, existing, default, options):
    return {"id": id, "group": group, "label": label, "existing": existing, "default": default, "options": options}


def _incl(id, group, label, note, *lines, default="do"):
    return _dec(id, group, label, note, default, {"do": _opt("Include", *lines), "skip": _opt("Leave out")})


def design_decisions(model, genome: dict, site: dict, remodel_rooms: list[str], new_rooms: list[str]) -> tuple[list, dict]:
    G = genome["elements"]
    E = model.elements
    q = quantities(model, genome)
    rm = {r["name"]: r for r in q["rooms"]}
    D = []

    # ---------- quantities from the model ----------
    wall = {"ext_new": 0.0, "ext_old": 0.0, "int_new": 0.0, "fire": 0.0}
    for wid, ce in E.items():
        if ce.type != "wall":
            continue
        g = G[wid]
        a = _face_sf(ce)
        if g.get("material") == "mat-trim":          # porch screen framing
            continue
        if wid in site.get("fire_walls", []):
            wall["fire"] += a
        if g.get("exterior"):
            wall["ext_new" if g.get("phase") == "new" else "ext_old"] += a
        elif g.get("phase") == "new":
            wall["int_new"] += a
    roof = {"new": 0.0, "old": []}
    for rid, ce in E.items():
        if ce.type != "roof":
            continue
        a = _up_area(ce.mesh) * SF
        if G[rid].get("phase") == "new":
            roof["new"] += a
        else:
            roof["old"].append((rid, G[rid]["name"], a))
    fam = sum(_up_area(E[r].mesh) * SF for r in site.get("vault_roofs", []))
    new_2f = site.get("new_2f_sf") or sum(Polygon(G[s]["boundary"]).area * SF for s in site.get("new_floor_slabs", []))
    new_1f = sum(rm[n]["floor_sf"] for n in new_rooms if n in rm)
    remodel = sum(rm[n]["floor_sf"] for n in remodel_rooms if n in rm)
    eave_new = 0.0
    for rid, ce in E.items():
        if ce.type == "roof" and G[rid].get("phase") == "new":
            fp, roles = G[rid]["footprint"], G[rid]["edge_roles"]
            for i, r in enumerate(roles):
                if r == "eave":
                    a, b = fp[i], fp[(i + 1) % len(fp)]
                    eave_new += ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 * LF

    def comp(cid, dim):
        s = G[cid]["size"][dim]["value"] / 0.3048
        return s

    # ---------- openings from the schedule ----------
    cnt = {}
    for oid, g in G.items():
        if g["type"] != "opening" or g.get("phase") != "new":
            continue
        op = ((g.get("filling") or {}).get("operation") or "").lower()
        host = G[g["host"]]
        w_in = g["width"]["value"] / 0.0254
        if g["kind"] == "void":
            k = "cased_opening"
        elif g["kind"] == "window":
            k = "win_egress" if "egress" in op else "win_fixed" if "fixed" in op else "window_std"
        elif "overhead" in op:
            k = "door_garage"
        elif "sliding glass" in op:
            k = "door_slider"
        elif "full glass" in op:
            k = "door_ext_glass"
        elif "20-min" in op or "solid core" in op:
            k = "door_fire"
        elif host.get("exterior"):
            k = "door_ext"
        elif "pocket" in op:
            k = "door_pocket"
        elif "french" in op:
            k = "door_int_french"
        elif "bypass" in op:
            k = "door_bypass"
        elif "bifold" in op:
            k = "door_bifold"
        else:
            k = "door_int"
        cnt[k] = cnt.get(k, 0) + 1
    labels = {"window_std": "new double-hung", "win_egress": "egress casements", "win_fixed": "gable transoms",
              "door_garage": "garage doors", "door_slider": "8' slider", "door_ext_glass": "glass yard / porch doors",
              "door_ext": "front entry door", "door_fire": "mudroom fire door", "door_pocket": "pocket doors",
              "door_int_french": "office French pair", "door_bypass": "closet bypass sliders", "door_bifold": "coat closet bifolds",
              "door_int": "interior doors", "cased_opening": "cased openings"}

    # ---------- decisions ----------
    g0 = "Design + permits"
    D.append(_incl("d:eng", g0, "Structural engineer", "beams B1–B4, footings, 2F framing", _line("engineer", 1)))
    D.append(_incl("d:set", g0, "Permit drawings", "schematic set is not for construction", _line("permit_set", 1)))
    D.append(_incl("d:permit", g0, "Permits", "addition + remodel", _line("permit_addition", 1)))
    D.append(_incl("d:haz", g0, "Hazmat testing", "house predates 1978 (D-101 note 8)", _line("haz_test", 1)))

    g1 = "Demolition"
    D.append(_incl("x:demo", g1, f"Interior demo ({remodel:.0f} sf)", "old kitchen wing, old bath, laundry, closets",
                   _line("demo_select", remodel)))
    D.append(_incl("x:dump", g1, "Dumpsters", "addition-size job", _line("dumpster", 4)))

    g2 = "Structure + shell"
    D.append(_incl("s:beams", g2, f"Beams B1–B4 ({site['beams']})", "engineer to size", _line("beam", site["beams"])))
    D.append(_incl("s:fdn", g2, f"Foundation, new footprint ({site['foundation_sf']:.0f} sf)", "family room + connector",
                   _line("foundation", site["foundation_sf"])))
    D.append(_incl("s:gslab", g2, f"Garage slab extension ({site['garage_ext_sf']:.0f} sf)", "9' strip, B4 wall removed",
                   _line("slab_garage", site["garage_ext_sf"])))
    D.append(_incl("s:extw", g2, f"New exterior walls ({wall['ext_new']:.0f} sf net)", "2x6, sheathed + wrapped",
                   _line("frame_ext", wall["ext_new"])))
    D.append(_incl("s:2f", g2, f"New 2nd-floor framing ({new_2f:.0f} sf)", "over the kitchen wing", _line("frame_floor", new_2f)))
    D.append(_incl("s:roof", g2, f"New roofs ({roof['new']:.0f} sf)", "family vault, new 2F, garage, connector, porch",
                   _line("frame_roof", roof["new"]), _line("roof_replace", roof["new"] * 1.10, "shingles incl. 10% waste"),
                   _line("gutter_new", eave_new, "new eaves")))
    D.append(_incl("s:intw", g2, f"New interior walls ({wall['int_new']:.0f} sf)", "one face", _line("frame_int", wall["int_new"])))
    D.append(_incl("s:siding", g2, "Siding on new walls", "lap siding to match (A-201 note 1)", _line("siding_new", wall["ext_new"])))
    D.append(_incl("s:insul", g2, "Insulation", "R-20 walls, R-49 ceiling / vault",
                   _line("insul_wall", wall["ext_new"]), _line("insul_roof", fam + new_2f)))
    D.append(_incl("s:dw", g2, "Drywall, new work", "new partitions both sides, new exterior walls, new ceilings",
                   _line("drywall", wall["int_new"] * 2 + wall["ext_new"] + fam + new_2f),
                   _line("drywall_fire", wall["fire"], "garage side + mudroom")))
    D.append(_incl("s:stair", g2, "Stair", "16 risers, open rail (A-101 note 2)", _line("stair_new", 1)))

    g3 = "Openings (A-501)"
    for k in sorted(cnt):
        D.append(_incl(f"o:{k}", g3, f"{labels.get(k, k).capitalize()} ({cnt[k]})", "new per schedule", _line(k, cnt[k])))

    g4 = "Kitchen (A-104 / A-401)"
    base_lf = comp("K-RANGEWALL", "d") + comp("D-BUFFET", "d")
    isl_lf, tall_lf = comp("K-ISLAND", "d"), comp("K-TALL", "w")
    counter = comp("K-RANGEWALL", "d") * comp("K-RANGEWALL", "w") + comp("K-ISLAND", "d") * comp("K-ISLAND", "w") \
        + comp("D-BUFFET", "d") * comp("D-BUFFET", "w")
    D.append(_dec("k:cab", g4, "Cabinets", f"{base_lf:.1f} lf base/upper · {isl_lf:.1f} lf island · {tall_lf:.1f} lf tall",
                  "mid", {"mid": _opt("Mid-range", _line("cab_base", base_lf), _line("cab_island", isl_lf), _line("cab_tall", tall_lf)),
                          "skip": _opt("Leave out")}))
    D.append(_incl("k:counter", g4, f"Quartz counters ({counter:.0f} sf)", "range wall, island, buffet", _line("counter", counter)))
    D.append(_incl("k:bs", g4, "Backsplash", "range wall + coffee bar",
                   _line("backsplash", (comp("K-RANGEWALL", "d") + comp("D-BUFFET", "d")) * 1.5)))
    D.append(_incl("k:app", g4, "Appliances", "30\" range, hood, 36\" fridge, wall oven, micro, DW", _line("appliances", 1)))
    D.append(_incl("k:pan", g4, "Walk-in pantry", "shelves both sides + counter", _line("pantry_shelf", 1)))

    g5 = "Baths, laundry, mudroom"
    D.append(_incl("b:owner", g5, "Owner's bath", "3'x5'5\" shower + bench, tub, 5' double vanity, toilet room", _line("bath_owner", 1)))
    D.append(_incl("b:powder", g5, "Powder room (expanded)", "30\" vanity, broom closet removed", _line("bath_powder", 1)))
    D.append(_dec("b:hall", g5, "Hall bath (2F)", "existing, stays in place", "keep",
                  {"keep": _opt("Keep"), "refresh": _opt("Refresh", _line("bath_refresh", 1)), "remodel": _opt("Remodel", _line("bath_remodel", 1))}))
    D.append(_incl("b:laundry", g5, "Laundry fit-out", "fold counter over W/D, uppers", _line("laundry_fit", 1)))
    D.append(_incl("b:mud", g5, "Mudroom lockers", "4 lockers, bench, hooks", _line("lockers", 1)))
    D.append(_incl("b:closets", g5, "Closet fit-out", "walk-in, coat, bedrooms 3 + 4", _line("closet_fit", site["closets"])))
    D.append(_incl("b:fp", g5, "Fireplace", "direct-vent gas, stone floor to ceiling", _line("fireplace", 1)))

    g6 = "Systems"
    D.append(_incl("m:elec", g6, f"Electrical ({new_1f + new_2f + remodel:.0f} sf new + remodeled)", "per E-101",
                   _line("elec_new", new_1f + new_2f + remodel)))
    D.append(_dec("m:panel", g6, "Service upgrade", "verify existing service (E-101 note 6)", "do",
                  {"do": _opt("200 A upgrade", _line("panel_upgrade", 1)), "skip": _opt("Existing is enough")}))
    D.append(_incl("m:plumb", g6, f"Plumbing ({site['fixtures']} fixtures)", "owner's bath, powder, kitchen, laundry",
                   _line("plumb_fixture", site["fixtures"]), _line("gas_relocate", 1)))
    D.append(_incl("m:hvac", g6, f"HVAC for added area ({new_1f + new_2f:.0f} sf)", "extend / new zone",
                   _line("hvac_extend", new_1f + new_2f), _line("exhaust_fan", site["fans"])))
    D.append(_incl("m:smoke", g6, "Smoke / CO alarms", "every bedroom + level, interconnected", _line("smoke_co", site["alarms"])))

    g7 = "Exterior + site"
    for rid, name, a in roof["old"]:
        if "porch" in name.lower() and "front" in name.lower():
            continue
        D.append(_dec(f"e:{rid}", g7, f"Existing roof — {name}", f"{a:.0f} sf", "replace" if rid in site.get("reroof", []) else "keep",
                      {"keep": _opt("Keep"), "replace": _opt("Re-roof to match", _line("roof_replace", a * 1.10, "incl. 10% waste"))}))
    D.append(_dec("e:siding", g7, f"Existing siding ({wall['ext_old']:.0f} sf)", "paint to match the new work", "paint",
                  {"keep": _opt("Keep"), "paint": _opt("Paint", _line("siding_paint", wall["ext_old"])),
                   "new": _opt("Re-side", _line("siding_new", wall["ext_old"] * 1.10))}))
    D.append(_incl("e:patio", g7, f"New patio ({site['patio_sf']:.0f} sf)", "pavers or concrete (C-101)", _line("patio", site["patio_sf"])))
    D.append(_incl("e:porch", g7, "Covered front porch", "posts, footings, 3/12 roof, steps", _line("front_porch", 1)))
    D.append(_dec("e:drive", g7, f"Curved driveway (~{site['drive_sf']:.0f} sf)", "12' wide + 27'x24' apron, 2 curb cuts (C-101)",
                  "asphalt", {"asphalt": _opt("Asphalt", _line("driveway", site["drive_sf"]), _line("culvert", 2)),
                              "skip": _opt("Leave out")}))
    D.append(_incl("e:clean", g7, "Final clean", "", _line("clean", q["totals"]["heated_sf"])))

    # ---------- room finishes (reused) ----------
    for d in room_decisions(q):
        if not d["group"].startswith("Rooms"):
            continue
        if d["id"].endswith(":kitchen") or d["id"].endswith(":bath") or d["group"].endswith("· Stair"):
            continue
        D.append(d)
    return D, q
