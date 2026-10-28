# Rebuilt house workflow: un-renovated house → design → budget → build

Agreed with Carter 2026-10-28. Reference run: 10050 Winchester Rd, Design A (`winchester/design-A/`).

| # | Step | Who | Output |
|---|------|-----|--------|
| 0 | Real prices (once, then kept current) | Carter exports Jobber / QuickBooks job line items (CSV); Claude builds `prices.json` | installed rate per pricebook key |
| 1 | Quick look + rough budget | Claude | low / medium / gut $ ranges before committing |
| 2 | Capture | Carter, guided (skill `rebuilt-property-capture`) | as-built Genome + model |
| 3 | Lot check (< 10 min) | Claude | parcel lines + setbacks shown in the editor as a no-build zone |
| 4 | Design to the budget | Carter / Kevin in the editor | design doc in the editor db |
| 5 | Automatic engineering + layout review | Claude (editor checks + full build) | fixes applied as "Review fix" steps |
| 6 | Takeoff + budget | Claude | `<address>-Takeoff-Budget.xlsx` |
| 7 | Renders / permit set — only when needed | Claude | renders, tour, floor plan PDF, permit sheets (planned) |
| 8 | Build; actual costs feed the pricebook | Doug / GC, Jobber | updated `prices.json` |

## Where things live
- Code: GitHub `carter671/rebuilt-toolkit` (this repo). House files: GitHub `carter671/rebuilt-properties`, one folder per house
  (`<house>/` as-built + evidence, `<house>/design-<X>/` design ops, lot `site.json`, takeoff, budget, `property.json`, permit plan).
- The old "Rebuilt Model Toolkit" page backup is frozen as of 2026-10-28; the repos are the source of truth from then on.
- Editors are published pages, one per house; their designs live in the page's own database (pull with ArtifactData and commit
  the design JSON to the house folder after each review).

## Commands (repo checked out as `rebuilt-toolkit/`; paths below use `rebuilt/` for it)

```
# editor for a property (after the as-built is final)
rebuilt build ASBUILT.genome.json out/
python3 -m rebuilt.design.editor_export ASBUILT.genome.json out/model.glb plan.json --name "123 Main St"
python3 rebuilt/editor/build.py plan.json "123 Main St" index.html
#   rebuilding an editor that already has designs? add --base-id <the live page's base_id> or its designs won't show
#   publish index.html as an artifact, capabilities {db:{}, user:{}, sample:{}}; designs live in db collection "designs"

# pull a design and build it
#   ArtifactData get designs/<doc id> -> design.json  ({name, ops, cursor})
python3 -m rebuilt.design.editor_ops ASBUILT.genome.json design.json D.genome.json D.layout.json
rebuilt build D.genome.json out-D/            # compile_report.json must have 0 errors; IFC validation PASS

# review
D=design.json O=chk node rebuilt/workflow/editor_check.js          # the editor's own checks (run from the editor folder)
node rebuilt/workflow/model_shots.js out-D/model.glb shots/D [views.json]   # renders from every side
DESIGN=design.json TITLE="123 Main St — Design A" CITY="Town, OH" node rebuilt/workflow/floorplan_pdf.js plan.pdf

# takeoff + budget
python3 rebuilt/workflow/takeoff.py ASBUILT.genome.json D.genome.json D.layout.json takeoff.json --name "Design A"
python3 rebuilt/workflow/budget_xlsx.py takeoff.json OUT.xlsx [--prices prices.json]
python3 <xlsx skill>/scripts/recalc.py OUT.xlsx 60                 # must report 0 errors
```
Node scripts need `NODE_PATH=$(npm root -g)` and three.js 0.160 (`npm i three@0.160.0`, or `THREE_DIR=.../node_modules/three`).

## What the review must catch (step 5)
- Roofs: every roof ties in; no new ridge above the house ridge; no two eaves draining into each other; nothing seen from the street that shouldn't be.
  The compile picks, in order: shed tucked under the eave → the house slope carried out at 2-3/12 (`_extend_slope`) → a gable tied in under the house ridge (4/12 if it fits) → the slope carried from the ridge (taller addition walls).
  A garage or wing that butts the house: turn its roof (`set_roof roles`) so the side against the house is a gable end/`abut`.
- Layout: every bedroom has an egress window; living spaces have windows; no garage door into a bedroom; doors don't open into walls; duplicate / sliver walls; openings past wall ends.
- Structure (assume rafters unless the attic shows trusses): outside walls that hold the roof edge, cut or moved → beams; bearing walls moved → beams; vaults under rafters → ONE structural ridge beam per roof; ceilings above the wall plate need taller walls.
- Utilities on walls that become interior: meter + service mast, AC + disconnect, dryer vent, crawl access, chimney.
- Fix with design ops (all undoable in the editor): `set_roof {roles}`, `set_component {id, at|wall,u|remove, lines}`, `set_wall_top {walls, top}`, `add_scope {label, lines}`, plus the usual wall/opening/ceiling/beam ops. Save to the design doc (pin `if_version`) only after republishing the editor if the editor code changed.

## Structure sizing (step 5, automatic) — `rebuilt/engineering.py`
A first pass so the design and the budget aren't guessing; an engineer still confirms and stamps.
- Loads: roof 15 dead + 20 snow psf, ceiling 10 + 10, floor 10 + 40; L/240 total, L/360 live; soil 1500 psf; duration factor 1.15.
- Members: LVL 2.0E 1-3/4" plies (3-ply first = a 2x6 wall), SPF #2 headers and rafters @16".
- Tributary: rafters bear on the eaves and on a ridge beam (only when a room under that roof is vaulted); ceiling joists bear
  on the eaves and on every beam running the same way. A beam at an old outside wall that an addition moved out also carries
  half the run to the new outside wall. Beams carrying a floor → engineer.
- Editor: every beam is sized live; "too small" is a fixable check (upsizes it); sizes, post loads, pads and headers for new
  openings go in the Engineer to-do list; Add-beam fixes use the calculated size, not a rule of thumb.
- Takeoff: `structure` in takeoff.json (beams, headers, rafters by clear span between supports); the Framing & Structure tab
  shows sizes, plies, post loads and pads; the Material List orders LVL by depth x plies and counts footings.

## Lot check (step 3) — `rebuilt/site/` (needs `pip install pyshp`)
```
python3 rebuilt/site/lot_import.py PARCELS.zip PARCEL_ID ASBUILT.genome.json site.json [--addresses ADDRESSES.zip] \
        --setbacks front=..,side=..,rear=..,accessory_side=..,accessory_rear=..,max_coverage_pct=.. --source "Fairfield parcels <date>"
python3 rebuilt/editor/build.py plan.json "123 Main St" index.html --base-id <id> --site site.json
python3 rebuilt/site/lot_check.py site.json ASBUILT.genome.json D.genome.json [--adj dx,dy,rot]
```
- Parcel files: county GIS download (Fairfield: co.fairfield.oh.us/gis → parcels.zip, addresses.zip). One file per county, reused.
- House orientation from its measured compass bearing; position from the county address point (else centred) — nudge with
  Lot → Move lot / rotate in the editor (saved to db site/<base id>; pass the same nudge to lot_check / permits as lot_adj).
- Editor: Lot button shows lot lines + shaded setbacks; new walls inside a setback are a check (variance or redesign);
  existing walls inside one go to the engineer list as legal nonconforming. Click an edge label to switch front / side / rear.
- permits.py --site site.json --design D.genome.json adds the lot result and files a Variance automatically when new work is over.

## Permits (step 7) — `rebuilt/permits/permits.py`
```
python3 rebuilt/permits/permits.py takeoff.json property.json permits/ --asbuilt ASBUILT.genome.json [--jurisdiction ID]
```
- property.json per house: address, parcel, county, zoning, acres, owner, applicant, well_septic, old_town, demolish, variance.
- Jurisdiction from the parcel's tax district (Fairfield: first 3 digits — 037 Violet Twp, 042/055/066 Canal Winchester city).
  A Canal Winchester mailing address is often the township.
- Rules per office in `permits/jurisdictions/<id>.json`; that office's blank forms in `permits/forms/<id>/` are pre-filled
  (owner / applicant / property / request) — sign and date by hand.
- Canal Winchester Old Town Overlay applies only inside the Historic / Preservation District map (Old Town Guidelines, P&Z):
  then a Certificate of Appropriateness from the Landmarks Commission comes first (15 days before the meeting), wood/brick/stone.
- Output: permit-plan.md (applications, attachments, who supplies what, to-dos) + permit-plan.json + filled PDFs.
- Add an office: copy a jurisdiction file, list its applications, map each form's fields (positions via pypdf widget rects).

## Budget rules (step 6)
- Gut rehab assumed: every non-garage room gets finishes; existing windows Replace; open doorways get doors. Change Openings → Action or Rooms → Finished to scope down.
- Pricebook rates are still `placeholder` until step 0. Rates not in the pricebook are added in `budget_xlsx.py` (ADDED, red "added — verify"); a pricebook entry with the same key wins.
- Allowances (red on the Cabinets tab) cover what the design needs but hasn't drawn (appliances, vanities, toilets).
