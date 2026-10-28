#!/usr/bin/env bash
# Reproduces the M1 Capture → review → render session on the FICTIONAL house.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; P="${1:-$HERE/demo_project}"
rm -rf "$P"
rebuilt init "$P" "$HERE/fictional_house.genome.json"
rebuilt capture "$P" "$HERE/evidence/field_notes.txt:Field tech A" "$HERE/evidence/measurements.csv:Crew B"
pid() { python3 -c "import json,sys;print(next(p['id'] for p in json.load(open('$P/proposals.json')) if p['kind']=='$1' and p.get('subject')=='$2' and p.get('property')=='$3'))"; }
pid_assoc() { python3 -c "import json;print(next(p['id'] for p in json.load(open('$P/proposals.json')) if p['kind']=='associate' and p['property']=='$1'))"; }
rebuilt decide "$P" "$(pid set_value W-U-S thickness)" accept --by Reviewer --reason "tape at W6 jamb"
rebuilt decide "$P" "$(pid dispute O-G-S-W1 width)" dispute --by Reviewer --reason "two crews disagree; hold until re-measured"
rebuilt decide "$P" "$(pid_assoc height)" accept --subjects SP-U-bed1,SP-U-bed2 --by Reviewer --reason "storey-wide ceiling height"
rebuilt decide "$P" "$(pid_assoc overhang)" accept --subjects R-main --by Reviewer --reason "note refers to main roof"
rebuilt decide "$P" "$(pid reject_observation W-G-I1 thickness)" accept --by Reviewer --reason "41 in is a typo"
rebuilt decide "$P" "$(pid set_value O-G-E-D1 width)" accept --by Reviewer --reason "36 in door"
rebuilt decide "$P" "$(pid set_value R-mud pitch)" accept --by Reviewer --reason "level and tape"
rebuilt status "$P"
rebuilt next "$P"
rebuilt render "$P"
