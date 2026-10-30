"""Write an empty plan.json for a NEW building (nothing built yet), so the design editor opens on a blank page.

    python3 blank_plan.py plan.json "Detached in-law suite"
    python3 build.py plan.json "Detached in-law suite" index.html [--site site.json]

One building (B1) with one first floor at grade and no walls, openings, rooms, roofs or fixtures.
Everything is in metres, plan coordinates (x east, y north) -- same shape as editor_export.export().
"""
import json
import sys
from pathlib import Path


def blank_plan(name: str) -> dict:
    return {"name": name, "units": "m",
            "storeys": {"1F": {"elev": 0.0, "building": "B1", "name": "First floor"}},
            "walls": [], "openings": [], "spaces": [], "comps": [], "roofs": []}


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.write_text(json.dumps(blank_plan(sys.argv[2] if len(sys.argv) > 2 else "New building"), indent=1))
    print("blank plan ->", out)
