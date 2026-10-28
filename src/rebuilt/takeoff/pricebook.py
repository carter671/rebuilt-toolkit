"""Price book: unit costs keyed by item. Defaults are PLACEHOLDERS (rough Central Ohio installed
contractor cost, labor + material) until Rebuilt's own numbers replace them. Every price carries
`source` so the scope sheet shows which numbers are Rebuilt's and which are placeholders.
"""
from __future__ import annotations

import json
from pathlib import Path

PLACEHOLDER = "placeholder"

# key: (label, unit, unit_cost, trade)
DEFAULTS = {
    # interior finishes
    "paint_walls":      ("Paint walls (2 coats, minor patch)", "sf", 1.75, "Paint"),
    "paint_ceiling":    ("Paint ceiling", "sf", 1.25, "Paint"),
    "paint_trim":       ("Paint trim & doors", "lf", 1.50, "Paint"),
    "floor_lvp":        ("LVP flooring installed", "sf", 6.50, "Flooring"),
    "floor_carpet":     ("Carpet & pad installed", "sf", 4.00, "Flooring"),
    "floor_tile":       ("Tile floor installed", "sf", 14.00, "Flooring"),
    "floor_refinish":   ("Refinish hardwood (sand, 3 coats)", "sf", 4.50, "Flooring"),
    "floor_demo":       ("Remove existing flooring", "sf", 1.25, "Demo"),
    "base_replace":     ("New baseboard installed", "lf", 4.50, "Carpentry"),
    "casing_replace":   ("New door/window casing", "lf", 4.00, "Carpentry"),
    "drywall_patch":    ("Drywall / plaster repair allowance", "room", 250.00, "Drywall"),
    # rooms
    "kitchen_refresh":  ("Kitchen refresh: paint cabinets, new counters, sink, faucet, hardware", "ea", 7500.00, "Kitchen"),
    "kitchen_remodel":  ("Kitchen remodel: cabinets, counters, backsplash, sink, appliances", "sf", 120.00, "Kitchen"),
    "bath_refresh":     ("Bath refresh: vanity, toilet, faucet, mirror, light, accessories", "ea", 3500.00, "Bath"),
    "bath_remodel":     ("Bath remodel: gut, tub/shower + surround, vanity, toilet, fixtures", "ea", 11000.00, "Bath"),
    # doors / openings
    "door_int":         ("Interior prehung door", "ea", 375.00, "Carpentry"),
    "door_int_french":  ("Interior French door pair", "ea", 1400.00, "Carpentry"),
    "door_bifold":      ("Bifold door pair", "ea", 300.00, "Carpentry"),
    "door_ext":         ("Exterior door (steel/fiberglass) installed", "ea", 1600.00, "Carpentry"),
    "door_garage":      ("Garage overhead door installed", "ea", 2200.00, "Carpentry"),
    "window_std":       ("Replacement window (vinyl double-hung)", "ea", 650.00, "Windows"),
    "window_large":     ("Replacement window (large / picture / paired)", "ea", 1100.00, "Windows"),
    # exterior
    "roof_replace":     ("Tear-off + architectural shingles", "sf", 5.25, "Roofing"),
    "siding_paint":     ("Exterior paint (siding, prep + 2 coats)", "sf", 3.00, "Exterior"),
    "siding_vinyl":     ("Vinyl siding over / replace", "sf", 9.00, "Exterior"),
    "gutter_replace":   ("Seamless 5\" gutters", "lf", 12.00, "Exterior"),
    "downspout_replace":("Downspouts", "lf", 9.00, "Exterior"),
    "fascia_wrap":      ("Wrap fascia (aluminum)", "lf", 14.00, "Exterior"),
    "soffit_vinyl":     ("Vented vinyl soffit", "lf", 16.00, "Exterior"),
    "fascia_paint":     ("Paint fascia & soffit", "lf", 4.00, "Exterior"),
    "shutter_replace":  ("Replace shutter set", "ea", 160.00, "Exterior"),
    "screen_rescreen":  ("Re-screen porch openings", "sf", 3.50, "Exterior"),
    # systems / whole house
    "light_fixture":    ("Replace light fixture", "ea", 150.00, "Electrical"),
    "device_replace":   ("Replace receptacles / switches (per device)", "ea", 18.00, "Electrical"),
    "smoke_co":         ("Smoke / CO detector", "ea", 65.00, "Electrical"),
    "electrical_allow": ("Electrical repairs allowance", "ls", 2500.00, "Electrical"),
    "plumbing_allow":   ("Plumbing repairs allowance", "ls", 2000.00, "Plumbing"),
    "hvac_allow":       ("HVAC service / repairs allowance", "ls", 1500.00, "HVAC"),
    "dumpster":         ("Dumpster (20 yd)", "ea", 650.00, "General"),
    "clean":            ("Final clean", "sf", 0.35, "General"),
    "permit":           ("Permits allowance", "ls", 750.00, "General"),
    # layout changes (design module)
    "wall_remove":      ("Remove non-bearing wall (incl. patch ceiling/floor)", "lf", 55.00, "Framing"),
    "header_bearing":   ("Bearing wall: LVL beam, posts, engineer letter (allowance)", "ea", 4500.00, "Framing"),
    "opening_new":      ("New opening in wall (frame, header, finish)", "ea", 900.00, "Framing"),
    "opening_close":    ("Close existing opening (frame, drywall, siding)", "ea", 650.00, "Framing"),
    "opening_widen":    ("Widen opening (new header, finish)", "ea", 1100.00, "Framing"),
    # ---- remodel + addition (design module, D-2 style projects) ----
    "demo_select":      ("Selective interior demolition (affected area)", "sf", 4.00, "Demo"),
    "haz_test":         ("Asbestos + lead paint testing (pre-1978)", "ls", 850.00, "General"),
    "engineer":         ("Structural engineer (beams, footings, framing)", "ls", 3500.00, "Design"),
    "permit_set":       ("Permit drawings / design professional", "ls", 3000.00, "Design"),
    "permit_addition":  ("Building + zoning permits (addition)", "ls", 2500.00, "General"),
    "beam":             ("LVL / steel beam with posts + footings (per beam)", "ea", 4500.00, "Framing"),
    "foundation":       ("Footings + crawl/slab foundation (new footprint)", "sf", 38.00, "Foundation"),
    "slab_garage":      ("Garage slab extension (4\" on base)", "sf", 9.00, "Foundation"),
    "frame_ext":        ("Exterior wall framing, sheathing + wrap (2x6)", "sf", 14.00, "Framing"),
    "frame_int":        ("Interior partition framing", "sf", 5.00, "Framing"),
    "frame_floor":      ("Floor framing + subfloor (new 2nd floor)", "sf", 16.00, "Framing"),
    "frame_roof":       ("Roof framing + sheathing", "sf", 12.00, "Framing"),
    "siding_new":       ("New lap siding + trim to match", "sf", 11.00, "Exterior"),
    "insul_wall":       ("Wall insulation (R-20)", "sf", 2.00, "Insulation"),
    "insul_roof":       ("Ceiling / vault insulation (R-49)", "sf", 3.25, "Insulation"),
    "drywall":          ("Drywall hang + finish", "sf", 3.25, "Drywall"),
    "drywall_fire":     ("5/8\" Type X at garage walls + ceiling", "sf", 3.75, "Drywall"),
    "win_egress":       ("Egress casement window 36x48 (new)", "ea", 850.00, "Windows"),
    "win_fixed":        ("Fixed transom window (new)", "ea", 450.00, "Windows"),
    "door_slider":      ("8' sliding glass door, header, sill pan", "ea", 3600.00, "Doors"),
    "door_ext_glass":   ("Full-glass exterior door 3'x8'", "ea", 1900.00, "Doors"),
    "door_pocket":      ("Pocket door + frame", "ea", 650.00, "Doors"),
    "door_bypass":      ("Bypass closet sliders", "ea", 450.00, "Doors"),
    "door_fire":        ("20-min self-closing door (garage)", "ea", 950.00, "Doors"),
    "cased_opening":    ("Cased opening (trimmed, no door)", "ea", 350.00, "Doors"),
    "cab_base":         ("Base + upper cabinets", "lf", 450.00, "Kitchen"),
    "cab_tall":         ("Tall cabinets / pantry wall", "lf", 900.00, "Kitchen"),
    "cab_island":       ("Island cabinets", "lf", 650.00, "Kitchen"),
    "counter":          ("Quartz countertops", "sf", 75.00, "Kitchen"),
    "appliances":       ("Appliance package allowance (range, hood, fridge, wall oven, micro, DW)", "ls", 9000.00, "Kitchen"),
    "backsplash":       ("Tile backsplash", "sf", 25.00, "Kitchen"),
    "pantry_shelf":     ("Pantry shelving + counter", "ls", 1200.00, "Kitchen"),
    "bath_owner":       ("Owner's bath build: tile shower + bench, tub surround, double vanity, toilet room", "ea", 18000.00, "Bath"),
    "bath_powder":      ("Powder room: vanity, toilet, mirror, light, tile floor", "ea", 4500.00, "Bath"),
    "laundry_fit":      ("Laundry: fold counter, uppers, dryer vent", "ls", 1500.00, "Carpentry"),
    "lockers":          ("Mudroom lockers + bench", "ls", 2400.00, "Carpentry"),
    "closet_fit":       ("Closet shelving + rods", "ea", 250.00, "Carpentry"),
    "fireplace":        ("Direct-vent gas fireplace + stone surround", "ls", 8500.00, "Specialties"),
    "stair_new":        ("Stair rebuild: open rail, treads, guard", "ls", 6500.00, "Carpentry"),
    "elec_new":         ("Electrical, new + remodeled areas (E-101)", "sf", 6.50, "Electrical"),
    "panel_upgrade":    ("Panel / service upgrade to 200 A (verify)", "ls", 3200.00, "Electrical"),
    "plumb_fixture":    ("Plumbing rough + set, per fixture", "ea", 1200.00, "Plumbing"),
    "gas_relocate":     ("Relocate range gas + hood vent", "ls", 900.00, "Plumbing"),
    "hvac_extend":      ("HVAC: extend ducts / new zone for added area", "sf", 12.00, "HVAC"),
    "exhaust_fan":      ("Bath / laundry exhaust fans ducted out", "ea", 350.00, "HVAC"),
    "patio":            ("Paver / concrete patio", "sf", 22.00, "Site"),
    "front_porch":      ("Covered front porch: footings, posts, roof, steps", "ls", 9000.00, "Exterior"),
    "driveway":         ("Asphalt driveway on stone base", "sf", 5.50, "Site"),
    "culvert":          ("Driveway curb cut, culvert + permit", "ea", 2500.00, "Site"),
    "gutter_new":       ("Seamless gutters + downspouts (new roofs)", "lf", 14.00, "Exterior"),
    "meter_relocate":   ("Relocate electric meter base + service mast (utility coordination)", "ls", 2800.00, "Electrical"),
    "ac_relocate":      ("Relocate AC condenser, pad, disconnect + line set", "ls", 1800.00, "HVAC"),
    "chimney_remove":   ("Remove exterior block chimney to grade, patch roof + siding", "ls", 2400.00, "Exterior"),
    "dryer_vent":       ("Re-route dryer vent (roof or side wall jack, rigid duct)", "ls", 450.00, "HVAC"),
    "equip_relocate":   ("Relocate water softener + septic controls (plumbing + electrical)", "ls", 1400.00, "Plumbing"),
}


def default_pricebook() -> dict:
    return {k: {"label": v[0], "unit": v[1], "cost": v[2], "trade": v[3], "source": PLACEHOLDER}
            for k, v in DEFAULTS.items()}


def load_pricebook(path: str | Path | None) -> dict:
    """Defaults overlaid with a Rebuilt price file: {"key": cost} or {"key": {"cost":..}}."""
    pb = default_pricebook()
    if path and Path(path).exists():
        for k, v in json.loads(Path(path).read_text()).items():
            cost = v["cost"] if isinstance(v, dict) else v
            if k in pb:
                pb[k].update(cost=float(cost), source="rebuilt")
            else:
                d = v if isinstance(v, dict) else {}
                pb[k] = {"label": d.get("label", k), "unit": d.get("unit", "ea"), "cost": float(cost),
                         "trade": d.get("trade", "Other"), "source": "rebuilt"}
    return pb
