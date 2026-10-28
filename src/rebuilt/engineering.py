"""Preliminary structural sizing: beams, headers, rafters and footings (simple spans, uniform load).

Standard allowable-stress checks (bending, shear, deflection) with published design values. This is a
first pass so a budget and a design can be checked before the engineer: it is NOT an engineered design.
Anything that fails every option here, or carries floor loads, is flagged for the engineer.

Loads (Central Ohio, IRC one/two-family defaults; change LOADS for another area):
  roof   dead 15 psf + snow 20 psf (ground snow, used as roof load like the IRC span tables)
  ceiling dead 10 psf + attic live 10 psf (limited storage)      floor dead 10 + live 40 psf
Deflection: roof / ceiling members L/240 total and L/360 snow; floor L/360 live.
Materials:
  LVL 2.0E (1-3/4" plies): Fb 2600 psi x (12/d)^0.136, Fv 285 psi, E 2.0e6 psi
  SPF No. 2 dimension lumber: Fb 875 psi x size factor (x1.15 repetitive for rafters), Fv 135 psi, E 1.4e6 psi
  load duration factor 1.15 (snow) on Fb and Fv. Soil bearing 1500 psf (IRC presumptive minimum).
"""
from __future__ import annotations

import math

LOADS = {"roof_dead": 15.0, "roof_snow": 20.0, "ceil_dead": 10.0, "ceil_live": 10.0, "floor_dead": 10.0, "floor_live": 40.0}
SOIL_PSF = 1500.0
CD = 1.15

LVL_DEPTHS = [9.25, 9.5, 11.25, 11.875, 14.0, 16.0, 18.0]
SAWN = {"2x6": (5.5, 1.3), "2x8": (7.25, 1.2), "2x10": (9.25, 1.1), "2x12": (11.25, 1.0)}   # depth in, size factor


def _check(span_ft, w_total_plf, w_live_plf, b_in, d_in, Fb, Fv, E, live_limit=360, total_limit=240):
    """utilisation (max of bending, shear, deflection) for a simply supported member"""
    L = span_ft * 12.0
    w, wl = w_total_plf / 12.0, w_live_plf / 12.0          # lb/in
    S, I, A = b_in * d_in ** 2 / 6, b_in * d_in ** 3 / 12, b_in * d_in
    M = w * L ** 2 / 8
    V = w * max(L / 2 - d_in, L / 4)                          # shear a depth in from the support
    defl_t = 5 * w * L ** 4 / (384 * E * I)
    defl_l = 5 * wl * L ** 4 / (384 * E * I)
    r = {"bending": (M / S) / Fb, "shear": (1.5 * V / A) / Fv,
         "deflection": max(defl_t / (L / total_limit), defl_l / (L / live_limit) if wl else 0)}
    return max(r.values()), r


def lvl(span_ft, w_total_plf, w_live_plf, plies=(3, 2, 4)):
    """shallowest LVL that works, trying ply counts in the order given (3 plies = a 2x6 wall), or None"""
    for n in plies:
        for d in LVL_DEPTHS:
            b = 1.75 * n
            Fb = 2600 * (12 / d) ** 0.136 * CD
            u, r = _check(span_ft, w_total_plf, w_live_plf, b, d, Fb, 285 * CD, 2.0e6)
            if u <= 1.0:
                return {"plies": n, "depth_in": d, "util": round(u, 2), "governs": max(r, key=r.get),
                        "label": f"{n}-ply 1-3/4\" x {d:g}\" LVL"}
    return None


def sawn_header(span_ft, w_total_plf, w_live_plf):
    """2-ply or 3-ply SPF No.2 header, else LVL"""
    for name, (d, cf) in SAWN.items():
        for n in (2, 3):
            u, r = _check(span_ft, w_total_plf, w_live_plf, 1.5 * n, d, 875 * cf * CD, 135 * CD, 1.4e6)
            if u <= 1.0:
                return {"label": f"{n}-{name} SPF #2", "plies": n, "depth_in": d, "util": round(u, 2), "governs": max(r, key=r.get)}
    x = lvl(span_ft, w_total_plf, w_live_plf)
    return x


def rafter(span_ft, spacing_in=16, pitch=5 / 12, dead=None, snow=None):
    """smallest SPF No.2 rafter for a horizontal clear span (loads per sf of plan); deflection L/240 total"""
    dead = LOADS["roof_dead"] if dead is None else dead
    snow = LOADS["roof_snow"] if snow is None else snow
    slope = math.sqrt(1 + pitch * pitch)
    s = spacing_in / 12.0
    w_t, w_l = (dead * slope + snow) * s, snow * s
    for name, (d, cf) in SAWN.items():
        u, r = _check(span_ft, w_t, w_l, 1.5, d, 875 * cf * 1.15 * CD, 135 * CD, 1.4e6, live_limit=240, total_limit=180)
        if u <= 1.0:
            return {"label": f"{name} @ {spacing_in}\" o.c.", "size": name, "util": round(u, 2), "governs": max(r, key=r.get)}
    return None


def beam_load(roof_trib_ft=0.0, ceil_trib_ft=0.0, floor_trib_ft=0.0, wall_plf=0.0):
    """uniform line load on a beam (plf): total and live"""
    L = LOADS
    total = roof_trib_ft * (L["roof_dead"] + L["roof_snow"]) + ceil_trib_ft * (L["ceil_dead"] + L["ceil_live"]) + \
        floor_trib_ft * (L["floor_dead"] + L["floor_live"]) + wall_plf
    live = roof_trib_ft * L["roof_snow"] + ceil_trib_ft * L["ceil_live"] + floor_trib_ft * L["floor_live"]
    return total, live


def footing(reaction_lb):
    """square pad for a post load on 1500 psf soil; IRC minimum 2'-0" for a post pad here"""
    side = max(2.0, math.ceil(math.sqrt(reaction_lb / SOIL_PSF) * 2) / 2)
    post = "(3) 2x6 built-up post" if reaction_lb <= 6000 else "6x6 post / (4) 2x6"
    return {"pad_ft": side, "label": f"{side:g}' x {side:g}' x 12\" concrete pad", "post": post}


def size_beam(name, span_ft, roof_trib_ft=0.0, ceil_trib_ft=0.0, floor_trib_ft=0.0, have_depth_in=None, have_plies=3, plies=(3, 2, 4)):
    """full sizing record for one beam"""
    w, wl = beam_load(roof_trib_ft, ceil_trib_ft, floor_trib_ft)
    need = lvl(span_ft, w, wl, plies)
    R = w * span_ft / 2
    rec = {"name": name, "span_ft": round(span_ft, 2), "roof_trib_ft": round(roof_trib_ft, 1), "ceil_trib_ft": round(ceil_trib_ft, 1),
           "floor_trib_ft": round(floor_trib_ft, 1), "load_plf": round(w), "reaction_lb": round(R), "need": need,
           "footing": footing(R), "engineer": bool(floor_trib_ft) or need is None}
    if have_depth_in is not None and need:
        u, _ = _check(span_ft, w, wl, 1.75 * have_plies, have_depth_in, 2600 * (12 / have_depth_in) ** 0.136 * CD, 285 * CD, 2.0e6)
        rec["have"] = f"{have_plies}-ply 1-3/4\" x {have_depth_in:g}\" LVL"
        rec["have_util"] = round(u, 2)
        rec["ok"] = u <= 1.0
    return rec
