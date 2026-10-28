# Implementation Phases & Acceptance Criteria

Each phase is "done" only when every acceptance test listed is automated and passing (or, for real-property phases, an evaluation report against independent measurements exists).

## M1 — Fictional house, end to end (this delivery)
Scope: `examples/fictional_house/` — a 1½-storey house (ground floor + partial upper storey under a gable roof), irregular L-ish ground footprint is **not** in M1's roof scope; the house is rectangular with an interior T-junction layout and one bump-out at the ground floor with its own shed roof.

| # | Acceptance criterion | Test |
|---|---|---|
| A1 | Genome validates against JSON Schema, references, units, constraints; malformed variants produce the specific expected error codes | `test_genome.py` |
| A2 | Bare numbers are normalised to `basis: assumed` with a warning | `test_genome.py` |
| A3 | Compiled wall, slab, roof volumes and net wall face areas match **hand-computed** truth within 1e-6 m³ / m² | `test_reference.py` |
| A4 | Every opening produces a real void: wall volume = gross − Σ opening volumes; ray through an opening centre does not hit the wall | `test_model.py` |
| A5 | L-corners mitred, T-junctions butted: no wall-wall volumetric overlap > 1e-9 m³ | `test_model.py` |
| A6 | Gable walls clipped to roof underside; no wall pokes through roof | `test_model.py` |
| A7 | Deterministic `model_hash` across two runs and across shuffled element order | `test_model.py` |
| A8 | Unsupported features (e.g. a curved wall, roof form `planes` with valleys) are reported, not dropped | `test_model.py` |
| A9 | Changing one wall height rebuilds that wall, its openings and dependent spaces only; others reused from cache | `test_model.py` |
| A10 | IFC4 export: spatial tree, every element present with expected IFC class, 1 IfcRelVoidsElement + 1 IfcRelFillsElement per filled opening, stable GlobalIds across revisions | `test_export.py` |
| A11 | IFC geometry, recomputed independently by OpenCASCADE, matches MODEL volumes within 1e-4 m³ per element | `test_export.py` |
| A12 | GLB: one node per element, extras carry genome_id; triangle counts match model | `test_export.py` |
| A13 | PDF set generated with the expected sheets; dimension strings come from Genome values | `test_export.py` |
| A14 | Edit → changeset → recompile → exports reflect the change; changeset log replays to identical Genome | `test_review.py` |

## M2 — Controlled evidence set (Capture)
Inputs: field notes (text), a measurement CSV, a sketch image with a reference dimension, and photos — all of the fictional house, with a ground-truth Genome held **out of** the pipeline.

| # | Criterion |
|---|---|
| B1 | Originals are content-addressed and immutable; duplicates detected (exact in M1 ✔, perceptual for photos in M2) |
| B2 | Notes parser: ≥ 95% of dimension statements extracted with correct value & unit on the controlled set (M1 ✔ for text) |
| B3 | Association: ≥ 90% of observations attached to the correct element (M1 ✔ for text) |
| B4 | Planted conflict detected and surfaced as `disputed`; planted typo flagged as an outlier (M1 ✔) |
| B5 | Starting from a skeleton Genome (topology only, all dims `unknown`), accepting proposals yields a Genome whose compiled dimensions are within stated uncertainty of ground truth |
| B6 | Next-best-measurement list ranks the missing/assumed values that most affect the model |
| B7 | Photo intake: frames/photos tagged to faces/rooms; *no* absolute dimension promoted from a photo without a scale reference |
| B8 | Review UI in browser: evidence side-by-side with proposal, accept/reject/correct emits changesets |

## M3 — Geometric complexity
Intersecting roof systems (straight-skeleton roof solver for arbitrary simple polygons, valleys/hips), split levels, partial storeys, additions with their own roofs meeting the main roof, spaces derived from wall graph, curved walls (optional). Acceptance: reference models hand-built and checked in OpenCASCADE + one independently modelled test building (modelled by a human in another tool from the same dimensions) compared element by element.

## M4 — Real evidence: 7244 Waterloo Road
Only with evidence Carter provides or explicitly authorises. Deliverables: evidence store, reviewed Genome, model, exports, and an **evaluation report** against independent reference measurements (tape/laser by a person, not derived from the photos used for reconstruction). Photogrammetry evaluated here with measured error statistics.

## M5 — Authoring-tool integrations
Per application (Chief Architect, Revit, SketchUp), separately:
1. Format-level test (IFC import) → classify the outcome on the four-level ladder (viewable / editable generic / BIM semantic / native parametric) with screenshots and a written test log.
2. Adapter where an API exists (Revit API add-in creating native Walls/Floors/FamilyInstances hosted in walls; SketchUp Ruby API with IFC classification; Chief Architect — investigate; no public modelling API is known to us, so likely import-only).
3. Round-trip editing as its own design + test cycle.
Requires licences/installations on a machine we can drive — **blocked on access**.
