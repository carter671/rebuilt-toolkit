"""Takeoff + Design modules: quantities come from the model, designs recompile, pricing is qty × cost."""
import pytest

from rebuilt.design import DesignError, apply_design
from rebuilt.genome.io import parse
from rebuilt.model.compile import compile_genome
from rebuilt.takeoff.pricebook import default_pricebook, load_pricebook
from rebuilt.takeoff.quantities import SF, quantities
from rebuilt.takeoff.scope import decisions, default_selections, price


def test_room_areas_match_model(model, raw):
    q = quantities(model, raw)
    for r in q["rooms"]:
        assert r["floor_sf"] == pytest.approx(model.elements[r["id"]].data["area"] * SF)
        assert r["wall_sf"] > 0 and r["base_lf"] > 0
    assert sum(1 for o in q["openings"] if o["kind"] == "window") == 9


def test_pricing_is_qty_times_cost(model, raw, tmp_path):
    q = quantities(model, raw)
    D = decisions(q)
    pb = default_pricebook()
    p = price(D, default_selections(D), pb, contingency=0.1)
    assert p["subtotal"] == pytest.approx(sum(l["qty"] * l["unit_cost"] for l in p["lines"]), abs=0.05)
    assert p["total"] == pytest.approx(p["subtotal"] * 1.1, abs=0.05)
    # Rebuilt's own price overrides the placeholder and is marked as such
    f = tmp_path / "prices.json"
    f.write_text('{"paint_walls": 2.0}')
    pb2 = load_pricebook(f)
    assert pb2["paint_walls"]["cost"] == 2.0 and pb2["paint_walls"]["source"] == "rebuilt"


def test_design_remove_wall_merge_recompiles(raw):
    d = {"changes": [{"do": "remove_wall", "wall": "W-G-I2", "bearing": "no",
                      "merge": ["SP-G-kitchen", "SP-G-living"], "room_name": "Great room"}]}
    dg, layout = apply_design(raw, d)
    assert "W-G-I2" not in dg["elements"] and "SP-G-living" not in dg["elements"]
    assert "W-G-I2" in raw["elements"]  # as-built untouched
    g, _ = parse(dg)
    m = compile_genome(g)
    assert m.ok
    before = compile_genome(parse(raw)[0])
    merged = m.elements["SP-G-kitchen"].data["area"]
    assert merged > before.elements["SP-G-kitchen"].data["area"] + before.elements["SP-G-living"].data["area"]
    assert layout[0]["options"]["do"]["lines"][0]["key"] == "wall_remove"


def test_design_openings(raw):
    d = {"changes": [{"do": "add_opening", "wall": "W-G-E", "kind": "window", "width": "3'", "height": "4'",
                      "sill": "3'", "offset": "1'"},
                     {"do": "resize_opening", "opening": "O-G-N-W3", "width": "5'"},
                     {"do": "remove_opening", "opening": "O-U-W-W9"}]}
    dg, layout = apply_design(raw, d)
    m = compile_genome(parse(dg)[0])
    assert m.ok and len(layout) == 3
    assert m.elements["O-G-N-W3"].data["width"] == pytest.approx(1.524)
    assert "O-U-W-W9" not in m.elements


def test_design_refuses_bad_changes(raw):
    with pytest.raises(DesignError):
        apply_design(raw, {"changes": [{"do": "remove_wall", "wall": "W-G-N"}]})  # exterior
    with pytest.raises(DesignError):
        apply_design(raw, {"changes": [{"do": "add_opening", "wall": "W-G-I1", "kind": "door",
                                        "width": "3'", "height": "7'", "offset": "200'"}]})
