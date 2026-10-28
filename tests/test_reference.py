"""A3 — compiled quantities vs HAND-DERIVED reference values for the fictional house.

The expected numbers below are derived from the design dimensions with plain arithmetic (see the
comments), using a self-contained polygon-integral helper. Nothing here calls the compiler's
geometry code, so these are independent of the implementation under test.
"""
import math

import pytest

TOL = 1e-6


def area_centroid(poly):
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    a /= 2
    return abs(a), (cx / (6 * a), cy / (6 * a))


def integral_linear(poly, f):
    """∫∫ f dA for linear f over a polygon = area * f(centroid)."""
    A, c = area_centroid(poly)
    return A * f(*c)


def clip_y(poly, y0, keep_below):
    out = []
    for p, q in zip(poly, poly[1:] + poly[:1]):
        pin = p[1] <= y0 if keep_below else p[1] >= y0
        qin = q[1] <= y0 if keep_below else q[1] >= y0
        if pin:
            out.append(p)
        if pin != qin:
            t = (y0 - p[1]) / (q[1] - p[1])
            out.append((p[0] + t * (q[0] - p[0]), y0))
    return out


S = 2 / 3  # 8:12
DV_MAIN = 0.2 * math.sqrt(1 + S * S)
DV_MUD = 0.15 * math.sqrt(1 + 0.25 ** 2)

# gable wall W-U-W: mitred plan, base z 2.95, plate 5.55, roof underside rises from y=-0.1 and 7.1
_UW = [(-0.1, -0.1), (0.1, 0.1), (0.1, 6.9), (-0.1, 7.1)]
_uw_above = (integral_linear(clip_y(_UW, 3.5, True), lambda x, y: S * (y + 0.1))
             + integral_linear(clip_y(_UW, 3.5, False), lambda x, y: S * (7.1 - y)))
UW = 1.4 * 2.6 + _uw_above - 0.8 * 1.0 * 0.2

# mudroom side walls: from main-wall outer face y=-0.1 to the mitred corner; shed underside z = 2.4 + 0.25 (y + 2.075)
_BW = [(3.425, -2.075), (3.575, -1.925), (3.575, -0.1), (3.425, -0.1)]
BW = integral_linear(_BW, lambda x, y: 2.4 + 0.25 * (y + 2.075))

EXPECTED_VOLUMES = {
    # rectangular loop, centre-line 10 x 7, t=0.2, mitred: plan area = L * t exactly
    "W-G-S": 10 * 0.2 * 2.7 - (1.2 * 1.2 + 1.6 * 2.1 + 1.2 * 1.2) * 0.2,
    "W-G-E": 7 * 0.2 * 2.7 - 0.9 * 2.03 * 0.2,
    "W-G-N": 10 * 0.2 * 2.7 - 1.0 * 1.0 * 0.2,
    "W-G-W": 7 * 0.2 * 2.7 - 1.0 * 1.2 * 0.2,
    "W-G-I1": (6.9 - 0.1) * 0.1 * 2.7,  # T-butted to inner faces
    "W-G-I2": (5.95 - 0.1) * 0.1 * 2.7,  # butts W-G-W inner face (x=0.1) and W-G-I1 face (x=5.95)
    "W-G-BS": 3 * 0.15 * 2.4 - 0.9 * 2.03 * 0.15,
    "W-G-BW": BW,
    "W-G-BE": BW - 0.8 * 1.0 * 0.15,  # mirror image + window
    "W-U-S": 10 * 0.2 * 2.6 - 2 * 1.0 * 1.2 * 0.2,
    "W-U-N": 10 * 0.2 * 2.6 - 1.0 * 1.2 * 0.2,
    "W-U-W": UW,
    "W-U-E": UW + 0.8 * 1.0 * 0.2,  # mirror image, no window
    "W-U-I1": 6.8 * 0.1 * 2.584,
    "R-main": 2 * (10.6 * 3.9) * DV_MAIN,  # panels: x -0.3..10.3, y -0.4..3.5 / 3.5..7.4
    "R-mud": (3.35 * 2.225) * DV_MUD,  # x 3.325..6.675, y -2.325..-0.1 (no overhang at abutment)
    "S-G-base": (10.2 * 7.2 + 3.15 * 1.975) * 0.1,
    "S-U-floor": 10.2 * 7.2 * 0.25,
    "S-U-ceiling": 9.8 * 6.8 * 0.016,
    "SP-G-living": 5.85 * 3.85 * 2.7,
    "SP-G-mud": 2.85 * 1.825 * 2.4,
    "O-G-S-W1#fill": 1.2 * 1.2 * 0.07,
    "O-G-E-D1#fill": 0.9 * 2.03 * 0.045,
}


@pytest.mark.parametrize("eid,expected", sorted(EXPECTED_VOLUMES.items()))
def test_volume_matches_hand_derivation(model, eid, expected):
    assert model.elements[eid].mesh.volume() == pytest.approx(expected, abs=TOL)


def test_roof_heights(model):
    r = model.elements["R-main"].data
    assert r["plate_z"] == pytest.approx(5.55, abs=TOL)
    assert r["top_z"] == pytest.approx(5.55 + 3.6 * S + DV_MAIN, abs=TOL)  # ridge top
    lo, hi = model.elements["R-main"].mesh.bounds()
    assert lo[2] == pytest.approx(5.55 - 0.3 * S, abs=TOL)  # eave underside at overhang edge
    assert (lo[0], hi[0]) == pytest.approx((-0.3, 10.3), abs=TOL)


def test_space_areas(model):
    assert model.elements["SP-G-family"].data["area"] == pytest.approx(3.85 * 6.8, abs=TOL)
    assert model.elements["SP-U-bed2"].data["area"] == pytest.approx(4.85 * 6.8, abs=TOL)


def test_opening_positions(model):
    d = model.elements["O-G-N-W3"].data  # north wall runs (10,7)->(0,7); offset 2.0, width 1.0
    assert d["centre"] == pytest.approx([7.5, 7.0, 1.6], abs=TOL)
    d = model.elements["O-U-W-W9"].data  # west gable (0,7)->(0,0); offset 3.0, width 0.8, storey 2.95
    assert d["centre"] == pytest.approx([0.0, 3.6, 2.95 + 1.2 + 0.5], abs=TOL)


def test_hip_roof_reference(raw):
    """Same footprint as a hip roof: 4 panels, total plan = footprint + 0.3 m eave all round."""
    from rebuilt.model.compile import compile_genome

    from .conftest import variant

    def hip(d):
        d["elements"]["R-main"]["form"] = "hip"
        d["elements"]["R-main"]["edge_roles"] = ["eave"] * 4
    g, _ = variant(raw, hip)
    m = compile_genome(g)
    r = m.elements["R-main"]
    assert len(r.data["panels"]) == 4
    assert r.mesh.volume() == pytest.approx(10.8 * 7.8 * DV_MAIN, abs=TOL)
    assert r.data["top_z"] == pytest.approx(5.55 + 3.6 * S + DV_MAIN, abs=TOL)
    # hip ends: each end panel is a triangle in plan with apex on the ridge, 3.6 m in from the footprint
    ends = [p for p in r.data["panels"] if len(p["region"]) == 3]
    assert len(ends) == 2 and all(p["plan_area"] == pytest.approx(0.5 * 7.8 * 3.9, abs=TOL) for p in ends)
    assert not ({"WALL_OVERLAP", "ELEMENT_OVERLAP"} & m.issues.codes())
