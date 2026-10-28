"""Unit parsing and formatting. Canonical length unit is the metre; canonical pitch is rise/run.

The parser is deliberately strict: anything it cannot read unambiguously raises UnitError
rather than guessing (Capture turns that into a review item, not a value).
"""
from __future__ import annotations

import math
import re
from fractions import Fraction

FT = 0.3048
IN = 0.0254


class UnitError(ValueError):
    pass


_FRAC = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_FT_IN = re.compile(
    rf"^\s*(?:(?P<ft>{_FRAC})\s*(?:'|’|ft\.?|feet|foot)\s*-?\s*)?"
    rf"(?:(?P<inch>{_FRAC})\s*(?:\"|”|''|in\.?|inch(?:es)?)?)?\s*$",
    re.IGNORECASE,
)
_METRIC = re.compile(r"^\s*(?P<v>-?\d+(?:\.\d+)?)\s*(?P<u>mm|cm|m|meters?|metres?)\s*$", re.IGNORECASE)


def _num(s: str) -> float:
    s = s.strip()
    if " " in s:
        whole, frac = s.split()
        return float(int(whole) + Fraction(frac))
    return float(Fraction(s)) if "/" in s else float(s)


def parse_length(text: str, default_unit: str | None = None) -> float:
    """Parse a length string to metres. Examples: 12' 6", 12'6, 12 ft 6 in, 7' 11 1/2", 150 mm, 3.2 m.

    A bare number is only accepted when default_unit is given ("m", "mm", "ft", "in").
    """
    t = text.strip()
    if not t:
        raise UnitError("empty length")
    m = _METRIC.match(t)
    if m:
        v = float(m["v"])
        u = m["u"].lower()
        return v / 1000 if u == "mm" else v / 100 if u == "cm" else v
    if re.fullmatch(r"-?\d+(?:\.\d+)?", t):
        if default_unit is None:
            raise UnitError(f"bare number '{t}' has no unit")
        v = float(t)
        return {"m": v, "mm": v / 1000, "cm": v / 100, "ft": v * FT, "in": v * IN}[default_unit]
    m = _FT_IN.match(t)
    if m and (m["ft"] or m["inch"]):
        has_ft_mark = m["ft"] is not None
        has_in_mark = bool(re.search(r"(\"|”|''|in\.?|inch)", t, re.IGNORECASE))
        if m["inch"] and not has_ft_mark and not has_in_mark:
            raise UnitError(f"ambiguous length '{t}'")
        ft = _num(m["ft"]) if m["ft"] else 0.0
        inch = _num(m["inch"]) if m["inch"] else 0.0
        if inch >= 12 and ft:
            raise UnitError(f"inches >= 12 in '{t}'")
        return ft * FT + inch * IN
    raise UnitError(f"cannot parse length '{t}'")


def parse_pitch(text: str) -> float:
    """'8:12', '8/12', '8 in 12' -> rise/run; '30deg' / '30°' -> tan(angle)."""
    t = text.strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?::|/|in)\s*(\d+(?:\.\d+)?)", t)
    if m:
        return float(m[1]) / float(m[2])
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:deg|degrees|°)", t)
    if m:
        return math.tan(math.radians(float(m[1])))
    raise UnitError(f"cannot parse pitch '{text}'")


def fmt_ft_in(metres: float, denom: int = 16) -> str:
    """Format metres as feet-inches to the nearest 1/denom inch, e.g. 12'-6 1/4\"."""
    neg = metres < 0
    total = round(abs(metres) / IN * denom)
    ft, rem = divmod(total, 12 * denom)
    inch, frac = divmod(rem, denom)
    s = f"{ft}'-{inch}"
    if frac:
        f = Fraction(frac, denom)
        s += f" {f.numerator}/{f.denominator}"
    return ("-" if neg else "") + s + '"'


def fmt_pitch(ratio: float) -> str:
    return f"{ratio * 12:.4g}:12"
