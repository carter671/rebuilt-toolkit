"""Editor designs: wall framing settings (outside / inside, 2x4 / 2x6, stud spacing) carry into the design Genome."""
import copy

from rebuilt.design.editor_ops import apply_editor
from rebuilt.genome.io import parse
from rebuilt.model.compile import compile_genome

IN = 0.0254


def test_add_wall_records_studs_and_spacing(raw):
    doc = {"cursor": 1, "ops": [{"do": "add_wall", "wall": {"id": "N-W-T1", "st": "G", "s": [3, 0], "e": [3, 4], "t": 6.5 * IN,
                                                             "h": 2.44, "b": 0, "ext": False, "name": "Wall", "stud": 6, "oc": 24}}]}
    dg, _ = apply_editor(copy.deepcopy(raw), doc)
    w = dg["elements"]["N-W-T1"]
    assert w["info"]["material"] == '2x6 studs @ 24" o.c.'
    assert compile_genome(parse(dg)[0]).ok


def test_set_wall_spec_changes_framing(raw):
    doc = {"cursor": 2, "ops": [
        {"do": "add_wall", "wall": {"id": "N-W-T2", "st": "G", "s": [3, 0], "e": [3, 4], "t": 4.5 * IN, "h": 2.44, "b": 0, "ext": False, "name": "Wall"}},
        {"do": "batch", "ops": [{"do": "set_wall_spec", "walls": ["N-W-T2", "W-G-I1"], "stud": 6, "oc": 16, "t": 6.5 * IN}]}]}
    dg, _ = apply_editor(copy.deepcopy(raw), doc)
    for wid in ("N-W-T2", "W-G-I1"):
        w = dg["elements"][wid]
        assert w["thickness"]["value"] == 6.5 * IN
        assert w["info"]["material"] == '2x6 studs @ 16" o.c.'
    assert raw["elements"]["W-G-I1"]["thickness"]["value"] == 0.1      # as-built untouched
    assert compile_genome(parse(dg)[0]).ok


def test_cabinets_flush_with_fridge_get_a_bump_out(raw):
    up = {"id": "N-I-U1", "cat": "upper", "st": "G", "at": [8, 0.05 + 0.1524 + 0.1524], "rot": 0, "w": 0.762, "d": 0.3048, "h": 0.9144, "z": 1.3716, "name": "Upper cabinet"}
    base = {"id": "N-I-B1", "cat": "base", "st": "G", "at": [8, 0.05 + 0.1524 + 0.3048], "rot": 0, "w": 0.762, "d": 0.6096, "h": 0.9144, "z": 0.0, "name": "Base cabinet"}
    doc = {"cursor": 3, "ops": [{"do": "add_item", "item": up}, {"do": "add_item", "item": base},
                                {"do": "batch", "ops": [{"do": "set_item", "item": "N-I-U1", "flush": True, "bump": 21 * IN},
                                                        {"do": "set_item", "item": "N-I-B1", "flush": True, "bump": 3 * IN}]}]}
    dg, layout = apply_editor(copy.deepcopy(raw), doc)
    b = next(x for x in layout if x["id"] == "layout:bumpout")
    line = b["options"]["do"]["lines"][0]
    assert line["key"] == "cab_bumpout" and line["qty"] == round(2 * 0.762 / 0.3048, 1)
    assert '21.0" deep' in line["note"] and '3.0" deep' in line["note"]
    items = next(x for x in layout if x["id"] == "layout:items")["options"]["do"]["lines"]
    counter = next(x for x in items if x["key"] == "counter")["qty"]
    assert counter == round(0.762 / 0.3048 * (0.6096 + 3 * IN + 0.025) / 0.3048, 1)     # the top runs back over the bump-out


def test_corner_and_trash_cabinets(raw):
    lazy = {"id": "N-I-C1", "cat": "corner", "style": "lazy", "st": "G", "at": [0.5, 0.5], "rot": 0, "w": 0.9144, "d": 0.9144, "h": 0.9144, "z": 0.0, "name": "Lazy susan corner"}
    trash = {"id": "N-I-T1", "cat": "trash", "st": "G", "at": [1.3, 0.35], "rot": 0, "w": 0.4572, "d": 0.6096, "h": 0.9144, "z": 0.0, "name": "Trash pull-out"}
    doc = {"cursor": 2, "ops": [{"do": "add_item", "item": lazy}, {"do": "add_item", "item": trash}]}
    dg, layout = apply_editor(copy.deepcopy(raw), doc)
    assert dg["elements"]["N-I-C1"]["info"]["category"] == "corner base cabinet"
    lines = {x["key"]: x for x in next(x for x in layout if x["id"] == "layout:items")["options"]["do"]["lines"]}
    assert lines["trash_pullout"]["qty"] == 1 and lines["lazy_susan"]["qty"] == 1
    assert "5.5 lf base" in lines["cab_base"]["note"]          # L corner 36" + 36" - 24" = 4 lf, plus the 18" trash = 5.5 lf
    assert compile_genome(parse(dg)[0]).ok


def test_fridge_panel_and_dishwasher_top(raw):
    dw = {"id": "N-I-D1", "cat": "dw", "st": "G", "at": [1.3, 0.35], "rot": 0, "w": 0.6096, "d": 0.6096, "h": 0.8763, "z": 0.0, "name": "Dishwasher"}
    sp = {"id": "N-I-S1", "cat": "filler", "auto": "sp", "of": "N-I-D1", "side": 1, "st": "G", "at": [1.6175, 0.35], "rot": 0, "w": IN, "d": 0.6096, "h": 0.9144, "z": 0.0, "name": 'DW spacer 1"'}
    pn = {"id": "N-I-P1", "cat": "panel", "auto": "panel", "of": "X", "side": 1, "st": "G", "at": [3, 0.5], "rot": 0, "w": 1.5 * IN, "d": 0.8382, "h": 2.286, "z": 0.0, "name": "Fridge end panel"}
    doc = {"cursor": 3, "ops": [{"do": "add_item", "item": dw}, {"do": "add_item", "item": sp}, {"do": "add_item", "item": pn}]}
    dg, layout = apply_editor(copy.deepcopy(raw), doc)
    lines = {x["key"]: x for x in next(x for x in layout if x["id"] == "layout:items")["options"]["do"]["lines"]}
    assert lines["fridge_panel"]["qty"] == 1
    assert lines["counter"]["qty"] > 0                     # dishwasher (and its spacer) get countertop
    assert dg["elements"]["N-I-P1"]["info"]["category"] == "refrigerator end panel"


def test_pantry_at_vanity_depth_is_a_linen_cabinet(raw):
    linen = {"id": "N-I-L1", "cat": "tall", "style": "linen", "st": "G", "at": [1.3, 0.3], "rot": 0, "w": 0.4572, "d": 21 * IN, "h": 84 * IN, "z": 0.0, "name": "Linen cabinet"}
    dg, layout = apply_editor(copy.deepcopy(raw), {"cursor": 1, "ops": [{"do": "add_item", "item": linen}]})
    assert dg["elements"]["N-I-L1"]["info"]["category"] == "linen cabinet"
    lines = {x["key"]: x for x in next(x for x in layout if x["id"] == "layout:items")["options"]["do"]["lines"]}
    assert lines["cab_tall"]["qty"] == 1.5
