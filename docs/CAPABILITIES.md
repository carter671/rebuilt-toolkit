# Capabilities — demonstrated vs. intended (compiler 0.2.0, schema 0.2.0)

Run `pytest` to reproduce everything marked DEMONSTRATED (103 tests, ~10 s). Every DEMONSTRATED claim
below names the test that proves it.

| Area | Capability | Status | Evidence |
|---|---|---|---|
| Genome | Documented JSON Schema, strict (no undeclared fields) | DEMONSTRATED | `schemas/genome.schema.json`; `test_unknown_field_rejected` |
| Genome | Per-property provenance: basis / verification / uncertainty / confidence / observations / selection / conflicts / original input | DEMONSTRATED | `schema.Value`; `test_provenance_carried` |
| Genome | Bare numbers never enter as certain (→ `assumed` + warning) | DEMONSTRATED | `test_bare_numbers_become_assumed` |
| Genome | Layered validation with stable codes (schema, reference, units, architecture, profile) | DEMONSTRATED | `test_validation_codes` (14 cases) |
| Genome | Profiles sketch → review → ifc-exchange → verified | DEMONSTRATED | `test_profiles_progression` |
| Genome | Changesets: reversible (prev values), rev bumps, replay = current | DEMONSTRATED | `test_changeset_apply_bumps_and_replays`, `test_capture_review_loop` |
| Genome | Migrations; newer schema refused | DEMONSTRATED (one sample migration) | `test_migration_and_version_refusal` |
| Genome | Stable identity vs revision | DEMONSTRATED | `test_globalids_stable_across_revisions` |
| Genome | Constraints (`equal`, `parallel` …) | DESIGNED — schema field exists; solver not implemented | — |
| MODEL | Straight walls, any orientation/thickness, centre/left/right alignment | DEMONSTRATED (centre); PARTIAL (left/right untested) | `test_reference` |
| MODEL | L (mitred), T (butted), collinear, free ends | DEMONSTRATED | `test_junction_classification` |
| MODEL | 3+-way junctions (through walls win; ending walls yield by roof-attached > height > exterior > thickness; corner stubs only inside neighbours) | DEMONSTRATED | `test_m4_features.py` |
| MODEL | Openings as real boolean cuts; doors/windows/voids | DEMONSTRATED | `test_openings_are_real_voids` |
| MODEL | Slabs (base, floor), ceilings, irregular polygons, multiple storeys | DEMONSTRATED | `test_reference` |
| MODEL | Roofs: gable, hip, shed on convex footprints; eave/rake overhangs; abutment edges | DEMONSTRATED (gable, shed, hip) | `test_roof_heights`, `test_hip_roof_reference` |
| MODEL | Walls clipped to roof underside (gables, shed side walls) | DEMONSTRATED | `test_gable_walls_under_roof` |
| MODEL | Intersecting roofs: a roof extended into another and trimmed by its mass (`trim_by`) → valleys; `flush-eave` edges | DEMONSTRATED | `test_intersecting_gables_make_valleys`, `test_flush_eave_has_no_overhang` |
| MODEL | Single non-convex roof footprints (one roof with valleys) | UNSUPPORTED — reported, dependents not built; model as intersecting convex roofs instead | `test_unsupported_reported_not_dropped` |
| MODEL | Split levels, partial storeys | DESIGNED (M3) | — |
| MODEL | Spaces from explicit boundaries; derived-from-walls | DEMONSTRATED / DESIGNED (M3) | — |
| MODEL | Overlap, junction-zone, blocked-opening, roof-head checks | DEMONSTRATED (caught a real error in my own fictional house) | `test_conflicting_geometry_reported` |
| MODEL | Deterministic hash; element-order independent | DEMONSTRATED | `test_deterministic_and_order_independent` |
| MODEL | Incremental rebuild of affected elements only | DEMONSTRATED | `test_incremental_rebuild` |
| Export | IFC4 with spatial tree, voids/fills, materials, psets, quantities | DEMONSTRATED | `test_ifc_semantics` |
| Export | IFC geometry recomputed by an independent kernel (OpenCASCADE) matches MODEL ≤1e-4 m³ & bbox ≤0.1 mm | DEMONSTRATED (all 36 elements; actual Δ ≈ 1e-7) | `test_ifc_validates_independently` |
| Export | GLB per-element nodes with Genome identity; sidecar provenance | DEMONSTRATED | `test_glb_identity`; also loaded with three.js GLTFLoader in Node |
| Export | PDF review set: notes, schedule, plans (true cuts), roof plan, 4 elevations, 2 sections, 3D views, true-scale imperial | DEMONSTRATED | `test_pdf_set` |
| Export | Export report retained/transformed/approximated/omitted | DEMONSTRATED | `test_export_report` |
| Genome | G3 components: cladding, trim (corner boards incl. inside corners, casings, rake boards, bands), shutters, fascia, soffits, gutters, downspouts, chimneys (cut the roofs), vents, fixtures, equipment, posts; information-only items | DEMONSTRATED | `test_g3.py` |
| Genome | Information blocks (category, material, finish, condition, observed date/by/photos), finishes registry, families, phase, history | DEMONSTRATED | `test_component_ifc_classes_info_and_validation` |
| Review | Capture closure: one changeset verifies every value, bases and dispute candidates kept | DEMONSTRATED | `test_close_capture_verifies_everything_and_keeps_basis` |
| MODEL | Eave overhang notched around another block's wall (only inside the overhang zone) | DEMONSTRATED (Waterloo: R1, R3, R8) | Waterloo build |
| Export | Components → IFC classes (IfcCovering CLADDING/MOLDING, IfcShadingDevice, IfcPipeSegment GUTTER, IfcChimney, IfcLightFixture, IfcFlowMeter …), Rebuilt_Info psets, colour styles; OCC volume check on every component | DEMONSTRATED | `test_component_ifc_classes_info_and_validation`; Waterloo IFC validation PASS |
| Export | Drawings: finish colours, siding courses at the recorded exposure, component schedule sheets | DEMONSTRATED | `test_finish_colours_in_glb_and_drawings` |
| Export | Chief Architect / Revit / SketchUp | RESEARCH — untested; see INTEGRATIONS.md | — |
| Review | Browser viewer: orbit/zoom, select, isolate/hide, storey filter, provenance colouring, section plane, measure, issues, correction download | PARTIAL — built; script syntax-checked and GLB load tested in Node; **not yet exercised in a real browser by an automated test** | `examples/fictional_house/output/viewer.html` |
| Review | Correction → changeset → recompile → re-export | DEMONSTRATED (CLI) | `test_capture_review_loop` |
| Capture | Content-addressed immutable evidence store, exact-duplicate detection | DEMONSTRATED | `test_store_immutable_and_dedup` |
| Capture | Field notes + measurement CSV → observations (ft-in/metric/pitch) | DEMONSTRATED on the controlled set: 17/17 values, 17/17 associations, 0 spurious | `test_extraction_against_truth` |
| Capture | Conflict detection, implausible-value flag, reported-unknown | DEMONSTRATED | `test_capture_review_loop` |
| Capture | Proposals with evidence; accept / reject / correct / hold disputed / associate | DEMONSTRATED | `test_capture_review_loop` |
| Capture | Next-best-measurement ranking | DEMONSTRATED (heuristic) | `test_capture_review_loop` |
| Capture | Vector as-built PDFs: every printed dimension, room size, area and opening code with sheet position; string closure checks | DEMONSTRATED on the Waterloo Rd as-builts (83 dims, 51 codes, all printed strings close) | `capture/asbuilt.py`, `test_asbuilt.py` |
| Capture | Photos, video frames, sketches, spoken notes | DESIGNED (M2) — files are ingested and registered; no extractor yet (reported as "awaiting extractors") | — |
| Capture | Photogrammetry / absolute dimensions from imagery | RESEARCH (M3) | — |
| Real property | 7244 Waterloo Road | PARTIAL — G3 as-built (476 elements incl. 334 components), capture closed and verified by the owner; IFC/OCC check passes; independent review done; NOT evaluated against held-back measurements | docs/WATERLOO_ROAD.md |

## Known failures and limits (honest list)
- The parser is rule-based and tuned on one controlled set I wrote; expect lower accuracy on real notes. That's what M2 measures.
- Explicit space boundaries do not follow wall changes (a thicker wall can make spaces overlap it; reported within tolerance or as an error).
- Door swings in plans are generic (hinge at opening start, swing inward); Genome `operation` is free text.
- Painter's-algorithm hidden-surface removal in elevations/axonometrics can mis-order faces; floor-slab tops are dropped from overall views because they defeat the sort.
- Components are boxes/hulls (no millwork profiles); downspout elbows are not modelled; interior items are information only.
- IFC walls are profile extrusions, not `IfcMaterialLayerSetUsage` + axis; some tools prefer the latter for native conversion.
- Fixed thicknesses for door (45 mm) and window (70 mm) proxy panels.
- Single pitch per roof; roof planes all start at the same plate height.
- The PDF date stamp makes PDFs non-byte-identical across days (geometry and numbers are deterministic).
