"""First-pass structural sizing (rebuilt.engineering): hand-checked values."""
import pytest

from rebuilt import engineering as E


def test_beam_load_roof_and_ceiling():
    w, wl = E.beam_load(roof_trib_ft=10, ceil_trib_ft=5)
    assert w == pytest.approx(10 * 35 + 5 * 20)
    assert wl == pytest.approx(10 * 20 + 5 * 10)


def test_check_matches_hand_calc():
    # 3-ply 1-3/4 x 14 LVL, 19.1 ft, 726 plf: M = 726*19.1^2/8 = 33,107 ft-lb; S = 5.25*14^2/6 = 171.5 in^3
    u, r = E._check(19.1, 726, 396, 5.25, 14, 2600 * (12 / 14) ** 0.136 * E.CD, 285 * E.CD, 2.0e6)
    fb = 33107 * 12 / 171.5
    assert r["bending"] == pytest.approx(fb / (2600 * (12 / 14) ** 0.136 * 1.15), rel=0.01)
    assert u == max(r.values())


def test_lvl_picks_shallowest_three_ply():
    x = E.lvl(19.1, 726, 396)
    assert (x["plies"], x["depth_in"]) == (3, 14.0)
    assert x["util"] <= 1.0
    assert E._check(19.1, 726, 396, 5.25, 11.875, 2600 * (12 / 11.875) ** 0.136 * E.CD, 285 * E.CD, 2.0e6)[0] > 1.0


def test_lvl_none_when_too_long():
    assert E.lvl(40, 1500, 800) is None


def test_size_beam_record():
    b = E.size_beam("back", 19.1, 13.2, 13.2, have_depth_in=16)
    assert b["load_plf"] == 726 and b["reaction_lb"] == pytest.approx(726 * 19.1 / 2, abs=2)
    assert b["ok"] and b["need"]["depth_in"] == 14.0
    assert b["footing"]["pad_ft"] == 2.5 and not b["engineer"]
    assert E.size_beam("floor", 12, 0, 0, floor_trib_ft=6)["engineer"]


def test_headers_and_rafters():
    assert E.sawn_header(3.25, *E.beam_load(13, 13))["label"] == "2-2x6 SPF #2"
    assert E.sawn_header(8.25, *E.beam_load(17.4, 16.75))["label"].endswith("LVL")
    sizes = [E.rafter(s, 16, 5 / 12)["size"] for s in (10, 14, 18)]
    assert sizes == sorted(sizes, key=lambda n: int(n.split("x")[1]))
    assert E.rafter(30) is None


def test_footing_minimum_and_growth():
    assert E.footing(2000)["pad_ft"] == 2.0
    assert E.footing(9000)["pad_ft"] == 2.5
    assert E.footing(9000)["post"].startswith("6x6")
