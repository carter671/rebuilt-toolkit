"""Completeness profiles. A Genome can be valid for 'sketch' and invalid for 'verified' —
that is the intended progressive path from rough evidence to a checked model."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    name: str
    allow_unknown: bool
    allow_disputed: bool
    require_material: bool
    require_verified: bool
    defaults: dict = field(default_factory=dict)  # (element type, param) -> value (metres)
    description: str = ""


_REVIEW_DEFAULTS = {
    ("wall", "thickness"): 0.15,
    ("wall", "base_offset"): 0.0,
    ("opening", "sill"): 0.0,
    ("slab", "thickness"): 0.2,
    ("slab", "top_offset"): 0.0,
    ("roof", "overhang"): 0.3,
    ("roof", "rake_overhang"): 0.15,
    ("roof", "thickness"): 0.2,
}

PROFILES = {
    "sketch": Profile("sketch", True, True, False, False, _REVIEW_DEFAULTS,
                      "Topology-first. Unknowns and disputes allowed; defaults filled and flagged."),
    "review": Profile("review", True, True, False, False, _REVIEW_DEFAULTS,
                      "Model-review drawings. Unknowns allowed only where a declared default exists."),
    "ifc-exchange": Profile("ifc-exchange", False, False, True, False, {},
                            "No unknown or disputed geometry; materials required."),
    "verified": Profile("verified", False, False, True, True, {},
                        "Every geometric parameter human-verified."),
}
