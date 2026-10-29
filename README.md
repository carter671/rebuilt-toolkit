# Rebuilt toolkit

Takes an un-renovated house from a tape-and-photo walk to a 3D model, a click-and-drag design editor, an automatic
design review with first-pass structural sizes, a priced takeoff / rehab budget, a lot (setback) check and a permit plan.

- **How the process runs, step by step:** [`docs/WORKFLOW.md`](docs/WORKFLOW.md)
- **House files** (as-builts, photos, designs, lot files, budgets) live in the separate private repo
  **`carter671/rebuilt-properties`** — this repo is code only.

## Set up (once per computer or Claude session)
```bash
git clone https://github.com/carter671/rebuilt-toolkit.git && cd rebuilt-toolkit
python3 -m venv .venv && . .venv/bin/activate          # optional
pip install -r requirements.lock && pip install -e . && pip install pyshp pypdf openpyxl shapely pyogrio geopandas
pytest -q                                               # all green before you use it
npm i three@0.160.0 playwright                          # only for the editor checks / renders / floor-plan PDF
```

## Layout
| Folder | What |
|---|---|
| `src/rebuilt/` | Genome (house record), MODEL compiler, exports (IFC, GLB, PDF, viewer), capture, takeoff, `engineering.py` (beam / header / rafter / footing sizes) |
| `editor/` | the design editor page (`build.py plan.json "Address" index.html --base-id ID --site site.json`) |
| `workflow/` | `takeoff.py`, `budget_xlsx.py`, `editor_check.js`, `model_shots.js`, `floorplan_pdf.js` |
| `site/` | `lot_import.py` (county parcel file → lot lines), `lot_check.py` (setbacks) |
| `permits/` | `permits.py` + one rules file and blank forms per building office (`jurisdictions/`, `forms/`) |
| `render-server/` | optional Blender GPU renderer for a Windows PC |
| `tests/` | `pytest` |

## Working together
- Branch, change, `pytest -q`, open a pull request; keep `main` green. Small commits with a plain-English message.
- Adding a township or city: add `permits/jurisdictions/<office>.json` and its blank forms under `permits/forms/<office>/`.
- Never put a house's files in this repo — they go in `rebuilt-properties/<house>/`.

---

## Reconstruction system (technical overview)

**Capture → Genome → MODEL → Export**, with review feeding corrections back into Genome.

| Subsystem | What it is | Code |
|---|---|---|
| **Genome** | Versioned, vendor-neutral building specification with per-property provenance, uncertainty and verification | `src/rebuilt/genome/` · `schemas/genome.schema.json` |
| **MODEL** | Deterministic compiler: Genome → validated solids (walls with real opening cuts, junctions, slabs, roofs, spaces) | `src/rebuilt/model/` |
| **Export** | IFC4 (independently checked with OpenCASCADE), GLB + provenance sidecar, PDF model-review set, browser viewer, export report | `src/rebuilt/export/` |
| **Capture** | Evidence store, text/CSV extraction, association, conflict detection, proposals, next-best measurement | `src/rebuilt/capture/` |
| **Review** | Project directory, proposal decisions, corrections, verification, replayable change log | `src/rebuilt/review/` · `rebuilt` CLI |

This is **milestone M1** on a fictional house. Read `docs/CAPABILITIES.md` for exactly what is demonstrated vs designed vs untested — in particular, Chief Architect / Revit / SketchUp integration is **not** built or tested yet, and photo/video Capture is M2.

## Quick start
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock && pip install -e .
pytest                                   # 79 acceptance tests

rebuilt validate examples/fictional_house/fictional_house.genome.json
rebuilt build    examples/fictional_house/fictional_house.genome.json out/
#  → out/model.ifc  model.glb  model.meta.json  model.pdf  viewer.html  export_report.json  compile_report.json

# evidence → review loop
rebuilt init    myproj examples/fictional_house/fictional_house.genome.json
rebuilt capture myproj examples/fictional_house/evidence/field_notes.txt:"Field tech A" examples/fictional_house/evidence/measurements.csv:"Crew B"
rebuilt proposals myproj
rebuilt decide  myproj <proposal-id> accept --by "Your name" --reason "..."
rebuilt edit    myproj O-G-S-W1 width "3' 11 5/8\"" --by "Your name" --reason "third measurement"
rebuilt status  myproj      # revision, replay check, profile readiness
rebuilt next    myproj      # what to measure next
rebuilt render  myproj      # rebuild myproj/out from the current genome
```
Requires Python ≥ 3.11 and `pdftotext` (poppler) only for one PDF test. Tested on Linux, Python 3.13, versions pinned in `requirements.lock`.

## Docs
- `docs/ARCHITECTURE.md` — full system design, data model, automation boundary
- `docs/PHASES.md` — milestones M1–M5 with acceptance criteria
- `docs/CAPABILITIES.md` — demonstrated vs intended, known failures
- `docs/DECISIONS.md` — decisions and rejected alternatives
- `docs/INTEGRATIONS.md` — Chief Architect / Revit / SketchUp research and test protocol
- `docs/CODEX_EXCHANGE.md` — how to cross-review with the Codex implementation
- `docs/WATERLOO_ROAD.md` — evidence needed for the real-property milestone

Output drawings are **model-review drawings**, not permit, construction or certified documents.
