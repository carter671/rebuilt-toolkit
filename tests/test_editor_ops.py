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
