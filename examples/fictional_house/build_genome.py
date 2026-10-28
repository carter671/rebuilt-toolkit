"""Generates fictional_house.genome.json — a FICTIONAL test house used to establish correctness.

Every number here is a design value chosen so the reference truths in tests/test_reference.py
can be derived by hand. Nothing here describes a real property.

Run: python examples/fictional_house/build_genome.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent


def M(v, unc=0.003, input=None):
    d = {"value": v, "basis": "measured", "uncertainty": {"kind": "pm", "value": unc}}
    if input:
        d["input"] = input
    return d


def A(v, note=""):
    return {"value": v, "basis": "assumed"}


def I(v, conf, unc=None):
    d = {"value": v, "basis": "inferred", "confidence": conf}
    if unc is not None:
        d["uncertainty"] = {"kind": "pm", "value": unc}
    return d


STOREY = {"ref": "storey"}
els = {}


def wall(id, storey, s, e, t, h=STOREY, exterior=True, mat=None, top=None, name=""):
    els[id] = {"type": "wall", "id": id, "name": name or id, "storey": storey, "start": list(s), "end": list(e),
               "thickness": t, "height": h, "base_offset": M(0.0, 0.0), "exterior": exterior,
               "material": mat or ("mat-ext-wall" if exterior else "mat-int-wall")}
    if top:
        els[id]["top"] = {"attach": top}


def opening(id, host, kind, off, w, h, sill, op=""):
    fill = {"type": "none"} if kind == "void" else {
        "type": kind, "operation": op, "material": "mat-glass" if kind == "window" else "mat-door"}
    els[id] = {"type": "opening", "id": id, "name": id, "host": host, "kind": kind,
               "offset": M(off), "width": M(w), "height": M(h), "sill": M(sill), "filling": fill}


EXT = M(0.2, input="7 7/8\"")
INT = M(0.1)
BUMP = M(0.15)
GH = M(2.7)  # ground walls stop at the underside of the upper floor platform

# ---- Ground storey (G) ----
wall("W-G-S", "G", (0, 0), (10, 0), EXT, h=GH, name="Ground south wall")
wall("W-G-E", "G", (10, 0), (10, 7), EXT, h=GH, name="Ground east wall")
wall("W-G-N", "G", (10, 7), (0, 7), EXT, h=GH, name="Ground north wall")
wall("W-G-W", "G", (0, 7), (0, 0), EXT, h=GH, name="Ground west wall")
wall("W-G-I1", "G", (6, 0), (6, 7), INT, h=GH, exterior=False, name="Ground partition x=6")
wall("W-G-I2", "G", (0, 4), (6, 4), INT, h=GH, exterior=False, name="Ground partition y=4")
wall("W-G-BW", "G", (3.5, 0), (3.5, -2), BUMP, top="R-mud", name="Mudroom west wall")
wall("W-G-BS", "G", (3.5, -2), (6.5, -2), BUMP, h=M(2.4), name="Mudroom south wall")
wall("W-G-BE", "G", (6.5, -2), (6.5, 0), BUMP, top="R-mud", name="Mudroom east wall")
els["W-G-S"]["aliases"] = ["front wall", "south wall"]

# ---- Upper storey (U) ----
wall("W-U-S", "U", (0, 0), (10, 0), I(0.2, 0.7, 0.03), name="Upper south wall")
wall("W-U-E", "U", (10, 0), (10, 7), EXT, top="R-main", name="Upper east gable wall")
wall("W-U-N", "U", (10, 7), (0, 7), EXT, name="Upper north wall")
wall("W-U-W", "U", (0, 7), (0, 0), EXT, top="R-main", name="Upper west gable wall")
wall("W-U-I1", "U", (5, 0), (5, 7), INT, h=M(2.584), exterior=False, name="Upper partition x=5")

# ---- Openings ----
opening("O-G-S-W1", "W-G-S", "window", 1.0, 1.2, 1.2, 0.9, "double-hung")
opening("O-G-S-V1", "W-G-S", "void", 4.2, 1.6, 2.1, 0.0)
opening("O-G-S-W2", "W-G-S", "window", 7.5, 1.2, 1.2, 0.9, "double-hung")
opening("O-G-E-D1", "W-G-E", "door", 3.0, 0.9, 2.03, 0.0, "single-swing-left")
opening("O-G-N-W3", "W-G-N", "window", 2.0, 1.0, 1.0, 1.1, "slider")
opening("O-G-W-W4", "W-G-W", "window", 1.0, 1.0, 1.2, 0.9, "casement")
opening("O-G-BS-D2", "W-G-BS", "door", 1.05, 0.9, 2.03, 0.0, "single-swing-right")
opening("O-G-BE-W5", "W-G-BE", "window", 0.5, 0.8, 1.0, 1.0, "fixed")
opening("O-U-S-W6", "W-U-S", "window", 2.0, 1.0, 1.2, 0.9, "double-hung")
opening("O-U-S-W7", "W-U-S", "window", 7.0, 1.0, 1.2, 0.9, "double-hung")
opening("O-U-N-W8", "W-U-N", "window", 6.5, 1.0, 1.2, 0.9, "double-hung")
opening("O-U-W-W9", "W-U-W", "window", 3.0, 0.8, 1.0, 1.2, "fixed")

# ---- Slabs ----
els["S-G-base"] = {"type": "slab", "id": "S-G-base", "name": "Ground slab", "storey": "G", "kind": "base",
                   "boundary": [[-0.1, -0.1], [3.425, -0.1], [3.425, -2.075], [6.575, -2.075], [6.575, -0.1],
                                [10.1, -0.1], [10.1, 7.1], [-0.1, 7.1]],
                   "thickness": M(0.1), "top_offset": M(0.0, 0.0), "material": "mat-concrete"}
els["S-U-floor"] = {"type": "slab", "id": "S-U-floor", "name": "Upper floor", "storey": "U", "kind": "floor",
                    "boundary": [[-0.1, -0.1], [10.1, -0.1], [10.1, 7.1], [-0.1, 7.1]],
                    "thickness": M(0.25), "top_offset": M(0.0, 0.0), "material": "mat-floor"}
els["S-U-ceiling"] = {"type": "slab", "id": "S-U-ceiling", "name": "Upper ceiling", "storey": "U", "kind": "ceiling",
                      "boundary": [[0.1, 0.1], [9.9, 0.1], [9.9, 6.9], [0.1, 6.9]],
                      "thickness": A(0.016), "top_offset": M(2.6), "material": "mat-gypsum"}

# ---- Roofs ----
els["R-main"] = {"type": "roof", "id": "R-main", "name": "Main gable roof", "storey": "U", "form": "gable",
                 "footprint": [[-0.1, -0.1], [10.1, -0.1], [10.1, 7.1], [-0.1, 7.1]],
                 "edge_roles": ["eave", "rake", "eave", "rake"],
                 "pitch": {"value": 8 / 12, "basis": "measured", "uncertainty": {"kind": "pm", "value": 0.01}, "input": "8:12"},
                 "plate_height": M(2.6), "overhang": M(0.3, 0.01), "rake_overhang": M(0.2, 0.01),
                 "thickness": A(0.2), "material": "mat-roofing"}
els["R-mud"] = {"type": "roof", "id": "R-mud", "name": "Mudroom shed roof", "storey": "G", "form": "shed",
                "footprint": [[3.425, -2.075], [6.575, -2.075], [6.575, -0.1], [3.425, -0.1]],
                "edge_roles": ["eave", "rake", "abut", "rake"],
                "pitch": {"value": 0.25, "basis": "observed", "confidence": 0.6,
                          "uncertainty": {"kind": "pm", "value": 0.04}, "input": "about 3:12 (from photo)"},
                "plate_height": M(2.4), "overhang": M(0.25, 0.01), "rake_overhang": M(0.1, 0.01),
                "thickness": A(0.15), "material": "mat-roofing"}

# ---- Spaces ----
def space(id, storey, x0, y0, x1, y1, h, name, bounded_by):
    els[id] = {"type": "space", "id": id, "name": name, "storey": storey,
               "boundary": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "height": h, "bounded_by": bounded_by}


space("SP-G-living", "G", 0.1, 0.1, 5.95, 3.95, M(2.7), "Living", ["W-G-S", "W-G-W", "W-G-I1", "W-G-I2"])
space("SP-G-kitchen", "G", 0.1, 4.05, 5.95, 6.9, M(2.7), "Kitchen", ["W-G-N", "W-G-W", "W-G-I1", "W-G-I2"])
space("SP-G-family", "G", 6.05, 0.1, 9.9, 6.9, M(2.7), "Family", ["W-G-S", "W-G-E", "W-G-N", "W-G-I1"])
space("SP-G-mud", "G", 3.575, -1.925, 6.425, -0.1, M(2.4), "Mudroom", ["W-G-BW", "W-G-BS", "W-G-BE", "W-G-S"])
space("SP-U-bed1", "U", 0.1, 0.1, 4.95, 6.9, M(2.584), "Bedroom 1", ["W-U-S", "W-U-W", "W-U-N", "W-U-I1"])
space("SP-U-bed2", "U", 5.05, 0.1, 9.9, 6.9, M(2.584), "Bedroom 2", ["W-U-S", "W-U-E", "W-U-N", "W-U-I1"])

genome = {
    "schema_version": "0.1.0",
    "project": {
        "id": "proj-fictional-0001", "name": "Fictional Test House", "units": "m", "fictional": True,
        "coordinate_system": {"origin_description": "Centre-line intersection of ground south and west walls",
                              "true_north_deg": {"value": 0.0, "basis": "assumed"}},
    },
    "property": {"id": "prop-fictional-0001", "address": "FICTIONAL — no real address"},
    "buildings": [{"id": "B1", "name": "Main house", "storeys": [
        {"id": "G", "name": "Ground", "elevation": M(0.0, 0.0), "height": M(2.95)},
        {"id": "U", "name": "Upper", "elevation": M(2.95), "height": M(2.6)},
    ]}],
    "materials": {
        "mat-ext-wall": {"id": "mat-ext-wall", "name": "Exterior wall, generic", "category": "wood", "color": "#d9cbb3"},
        "mat-int-wall": {"id": "mat-int-wall", "name": "Interior partition, generic", "category": "gypsum", "color": "#efefef"},
        "mat-concrete": {"id": "mat-concrete", "name": "Concrete", "category": "concrete", "color": "#a7a7a2"},
        "mat-floor": {"id": "mat-floor", "name": "Timber floor assembly", "category": "wood", "color": "#b9946a"},
        "mat-gypsum": {"id": "mat-gypsum", "name": "Gypsum board", "category": "gypsum", "color": "#f4f4f0"},
        "mat-roofing": {"id": "mat-roofing", "name": "Asphalt shingle roof assembly", "category": "roofing", "color": "#5b5f66"},
        "mat-glass": {"id": "mat-glass", "name": "Glazing", "category": "glass", "color": "#9cc7e0"},
        "mat-door": {"id": "mat-door", "name": "Door leaf, timber", "category": "wood", "color": "#8a5a36"},
    },
    "elements": dict(sorted(els.items())),
}

if __name__ == "__main__":
    out = HERE / "fictional_house.genome.json"
    out.write_text(json.dumps(genome, indent=2) + "\n")
    print("wrote", out)
