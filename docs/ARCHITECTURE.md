# Rebuilt Reconstruction System — Architecture

Status legend used throughout this repo:

- **DEMONSTRATED** — implemented and covered by an automated test in `tests/`.
- **PARTIAL** — implemented for a stated subset; the limits are listed.
- **DESIGNED** — interface/schema defined here, no implementation yet.
- **RESEARCH** — capability not yet established; needs investigation or access we don't have.

The authoritative current status table is `docs/CAPABILITIES.md`. This document describes intent and structure.

---

## 0. System shape

```
             ┌──────────────────────────── review / corrections ───────────────────────────┐
             ▼                                                                              │
 raw evidence ──► CAPTURE ──► proposed changesets ──► human review ──► GENOME (authoritative)
 (photos, video,  (intake,      (pending, with       (accept/reject/      │ revisions, provenance,
  notes, plans,    extraction,   supporting           correct; audit)     │ uncertainty, conflicts
  measurements)    association)  evidence)                                ▼
                                                                        MODEL (compiler)
                                                                          │ deterministic geometry,
                                                                          │ validation report,
                                                                          │ element ↔ evidence links
                                                                          ▼
                                                                        EXPORT
                                                     IFC4 · GLB · PDF review set · export report
                                                     · (later) Chief / Revit / SketchUp adapters
```

The one rule that holds the system together: **Genome is the only authoritative store.**
Capture never writes geometry; it writes *observations* and *proposed changesets*.
MODEL never stores anything; it is a pure function `compile(genome, compiler_version) → model`.
The review UI never edits the model; it emits changesets against Genome, which are then recompiled.
Exports are generated only from a compiled model and stamp the Genome revision + model hash they came from.

This is what prevents model/spec drift: there is no second copy of the building to drift.

---

## 1. MODEL — architectural compiler

**Input:** a validated Genome document. **Output:** `CompiledModel` =

| Part | Content |
|---|---|
| `elements[id]` | solid geometry (closed, manifold triangle mesh, metres), analytic data (plan polygon, faces, net/gross areas, volume), element revision, input hash |
| `relations` | host/fill, containment, wall-junction graph, roof-attachment, space bounds |
| `issues` | validation/compile findings with code, severity, element ids, message |
| `unsupported` | features present in Genome the compiler did not build (never silently dropped) |
| `provenance_index` | element.param → basis, verification, uncertainty, observation ids |
| `model_hash` | SHA-256 over canonicalised geometry + compiler version |

### Pipeline stages
1. **Validate** Genome (schema → references → units/coordinates → architectural constraints). Errors stop compilation; warnings are carried into the report.
2. **Resolve** — compute derived parameters from explicit constraints (e.g. wall height from storey height when `height` is `{"ref": "storey"}`, roof attachment, opening placement). Conflicting or underdetermined constraints produce issues, not guesses.
3. **Junctions** — build the wall graph from endpoint coincidence (tolerance in Genome `tolerances.join`), classify L / T / X / free ends, compute plan polygons with mitred L-corners and butt T-joins.
4. **Construct** solids: walls (plan polygon extruded, optionally clipped by attached roof underside), slabs, roof panels, opening voids, fillings (door/window proxies), spaces.
5. **Cut** openings with real booleans (manifold3d) — wall solids have actual holes.
6. **Check** post-conditions: every solid closed & manifold, openings fully inside host face, no wall–wall overlap beyond junction regions, spaces inside storey footprint, roof covers its footprint.
7. **Hash & cache** — each element has an input hash (its own resolved params + params of dependencies). Recompilation reuses cached solids whose input hash is unchanged; the report lists rebuilt elements.

### Determinism
Same Genome + same compiler version + supported environment (pinned manifold3d/numpy versions, `requirements.lock`) → same `model_hash`. Element iteration is sorted by id; floats are rounded to 1e-6 m before hashing. Tested in `tests/test_model.py::test_deterministic`.

### Geometric scope by phase
| Feature | M1 | Later |
|---|---|---|
| Straight walls, any orientation/thickness/height, L/T/X junctions | ✔ | curved walls |
| Openings with real cuts, door/window/void, sill/head | ✔ | arched/shaped openings |
| Floor slabs, ceilings, multiple storeys | ✔ | split levels, stepped slabs |
| Irregular (non-rectangular) footprints | ✔ walls & slabs | |
| Gable, hip, shed roofs on rectangular footprint, overhang, eaves | ✔ gable/hip/shed | intersecting roof systems, valleys on L/T footprints (M3 — straight-skeleton solver) |
| Walls clipped to roof underside (gable ends) | ✔ | |
| Spaces from explicit boundaries | ✔ | spaces derived from wall graph |
| Materials (single material / simple layer list) | ✔ | assemblies with LOD |
| Framing, structural, MEP, estimating | ✘ declared extensions | separate phases |

### Inspection & correction
`viewer/` — single-file browser app driven by the GLB + a JSON sidecar (Genome slice per element). Orbit/zoom/select/isolate/hide, plan/elevation/section via the PDF set and section planes, per-element dimensions/materials/sources/uncertainty/verification, issue list.
Corrections are made through `rebuilt edit` (CLI) or the viewer's "propose correction" form, which **downloads a changeset JSON** — it does not mutate anything. Changesets are applied to Genome with author + reason, then recompiled. Native viewer write-back (without a file hop) is DESIGNED, not built.

---

## 2. Genome — authoritative specification

File: one JSON document per building project (`*.genome.json`), schema in `schemas/genome.schema.json` (generated from `src/rebuilt/genome/schema.py`). Current schema version: **0.1.0**.

### Top-level structure
```
{
  "schema_version": "0.1.0",
  "project":   {id, name, units:"m", tolerances, coordinate_system, survey_reference?},
  "property":  {id, address?, parcel?},
  "buildings": [{id, name, storeys:[{id, name, elevation:Q, height:Q}]}],
  "elements":  {<id>: Element},           # walls, openings, slabs, roofs, spaces
  "materials": {<id>: Material},
  "observations": {<id>: Observation},    # evidence-derived facts, never deleted
  "sources":   {<id>: SourceRef},         # pointers into the Capture evidence store
  "constraints": [Constraint],
  "revision":  {number, parent_hash, history:[ChangesetSummary]},
  "extensions": {<namespace>: {...}}      # namespaced, declared, never behaviour-changing
}
```

### Quantified, provenance-carrying values (`Q`)
Every geometric or material parameter that can come from evidence is a **Value record**, not a bare number:

```json
"height": {
  "value": 2.438,
  "basis": "measured",              // measured | observed | extracted | inferred | assumed | unknown
  "verification": "unverified",     // unverified | verified | disputed
  "uncertainty": {"kind": "pm", "value": 0.006},   // ± metres, 95% bound; or null
  "confidence": null,               // 0..1, only meaningful for basis=inferred
  "observations": ["obs-0007", "obs-0012"],
  "selection": {"by": "carter", "process": "review", "reason": "tape measure > photo estimate"},
  "input": "8' 0\""                 // the original human input, kept verbatim
}
```
Bare numbers are accepted as shorthand and normalised to `basis: "assumed"` with a warning — so nothing enters the model looking more certain than it is.

**Three separate notions (deliberately not merged):**
- **uncertainty** — how far the true value may be from `value` (a measurement property, in metres).
- **confidence** — the probability an *inference* is correct (e.g. "this opening is a window" = 0.8). Not a substitute for uncertainty.
- **verification** — a human has checked the value against evidence and signed it. A verified value keeps its basis (a verified inference is still an inference) and its uncertainty.

`basis: "unknown"` permits `value: null`. MODEL then either uses a declared profile default (marked `assumed` in the compiled provenance and reported) or refuses, depending on the compile profile.

**Conflicts:** when observations disagree beyond their combined uncertainty, `verification` becomes `"disputed"` and a `conflicts` list holds each candidate value with its observation ids. Nothing is discarded; resolution records the selected value and reason in `selection`.

### Identity vs revision
- Element `id` is stable for the life of the building element (`W-north`, `D-front`, or generated `el_…`). It never changes when geometry changes.
- Element `rev` increments whenever any of its properties change. Genome `revision.number` increments per applied changeset.
- Exports derive IFC GlobalIds from `uuid5(project.id, element.id)` so the same wall keeps the same GlobalId across revisions.

### Coordinates
Project coordinate system: right-handed, metres, +Z up, origin chosen by the project (typically a building corner), +Y = **project north**. `true_north_deg` gives rotation to true north; `survey_reference` optionally ties the origin to a surveyed point (EPSG code + easting/northing/elevation). Storey elevations are relative to project Z=0. Wall baselines are 2D in storey coordinates.

### Elements (M1)
- **Wall** — `storey`, `start`, `end` ([x,y]), `thickness` Q, `height` Q or `{"ref":"storey"}`, `base_offset` Q, `alignment` (`center`|`left`|`right` of start→end), `exterior` bool, `material`, `top` (`{"attach": roof_id}` optional).
- **Opening** — `host` (wall id), `kind` (`door`|`window`|`void`), `offset` Q (from host start along baseline to opening's near edge), `width` Q, `height` Q, `sill` Q, `filling` (`{type, operation?, material?}` or null).
- **Slab** — `storey`, `kind` (`floor`|`ceiling`|`base`), `boundary` polygon, `thickness` Q, `top_offset` Q.
- **Roof** — `storey` (bearing level), `form` (`gable`|`hip`|`shed`|`planes`), `footprint` polygon (wall-plate outline), `pitch` Q (rise/run or degrees with unit), `ridge_axis` (`x`|`y`), `overhang` Q (eave), `rake_overhang` Q, `thickness` Q, `plate_height` Q.
- **Space** — `storey`, `name`, `boundary` polygon, `bounded_by` [wall ids], `height` Q.

### Validation layers (`rebuilt validate`)
1. JSON Schema (structural).
2. Referential integrity (every host/storey/material/observation/source id resolves; no orphan openings).
3. Units & coordinates (positive dimensions, tolerances, polygon orientation & simplicity, storey ordering).
4. Architectural constraints (opening fits within host length/height, sill+height ≤ wall height, wall lengths > thickness, roof footprint closed, spaces non-overlapping per storey).
5. **Profile completeness** — profiles in `src/rebuilt/genome/profiles.py`: `sketch` (anything goes, unknowns allowed), `review` (geometry required, unknowns allowed with defaults, reported), `ifc-exchange` (no unknown geometry; materials required), `verified` (all geometry verified). A Genome can be valid for `sketch` and fail `verified` — that's the intended progressive path.

### Changesets & migrations
A changeset is `{id, author, timestamp, reason, source:"capture"|"review"|"cli", ops:[{op:"set"|"add"|"remove", path, value, prev}]}` — paths are JSON Pointers. Applying records `prev` so changesets are reversible, bumps element `rev`s and Genome revision, and appends to `revision.history`. The full changeset log lives beside the Genome (`<name>.changes.jsonl`) so any revision is reproducible from the initial file.

Migrations: `src/rebuilt/genome/migrate.py` holds ordered functions `migrate_X_to_Y`; loaders migrate forward automatically and record the migration in history. Unknown **major** versions are refused. Extension namespaces must be declared in `project.extensions_declared`; undeclared keys anywhere fail validation (`additionalProperties: false`), so undocumented fields cannot quietly change behaviour.

---

## 3. Capture — evidence intake

### Evidence store (`<project>/evidence/`)
- `originals/<sha256>.<ext>` — content-addressed, immutable, never modified.
- `manifest.jsonl` — one record per original: `{source_id, sha256, filename, media_type, received_at, provided_by, tags:{level?,room?,face?}, note?}`.
- `derived/` — frames, OCR text, transcripts, annotations; each with `derived_from` (source id) and `process` (tool + version + params).

### Processing stages
| Stage | Output | M1 status |
|---|---|---|
| Ingest any file, hash, dedupe exact duplicates | manifest record | DEMONSTRATED |
| Field notes & measurement sheets → structured observations (ft-in/metric parsing, element/room/face phrases) | Observation records | DEMONSTRATED (rule-based parser) |
| Associate observations to candidate elements (labels, aliases, room+face matching) | `candidate_elements` with scores | DEMONSTRATED (rule-based) |
| Conflict detection across observations | disputed values | DEMONSTRATED |
| Proposals → pending changesets | `proposals/*.json` | DEMONSTRATED |
| Next-best-measurement list | ranked requests | DEMONSTRATED (heuristic) |
| Photo/video frame extraction & dedupe (perceptual hash) | derived frames | DESIGNED (M2) |
| Drawing/plan reading (scale bar + dimension strings) | extracted observations | DESIGNED (M2) — LLM-vision assisted, always `basis: extracted`, review-required |
| Photogrammetry / SfM (COLMAP or similar) | point cloud, scaled by a known reference dimension | RESEARCH (M3) — must be validated against tape measurements before any value is promoted above `inferred` |
| Hidden construction | — | Out of scope: not recoverable from imagery; recorded as `unknown` |

**What imagery can and cannot give us (working assumptions, to be tested):** a single uncalibrated photo gives no absolute scale; it can support topology (which wall has how many windows, roof form, relative proportions) at `basis: observed/inferred`. Absolute dimensions from photos require a known reference in frame or a multi-view reconstruction with at least one measured scale reference; expected accuracy must be measured in M3 against tape/laser truth before it's trusted.

### Review workflow & automation boundary
| Operation | Automatic? |
|---|---|
| Ingest, hash, manifest, derived-asset generation | yes |
| Parse notes into observations | yes (observations are evidence, not truth) |
| Attach observation to element when match is exact (id/alias) | yes |
| Raise a conflict / mark disputed | yes |
| Change any Genome value, add/remove elements | **review required** |
| Promote anything to `verified` | **human only** |

`rebuilt review` lists pending proposals with supporting evidence (source file, quoted note line, parsed value) and supports accept / reject / correct (accept with an edited value). Every decision is written to the changeset log with author and reason.

---

## 4. Export

| Target | Content | Status |
|---|---|---|
| **IFC4 (ADD2 TC1)** via IfcOpenShell | Project→Site→Building→Storey; IfcWall (SweptSolid; walls attached to roofs carry IfcBooleanClippingResult with half-spaces), IfcOpeningElement + IfcRelVoidsElement, IfcDoor/IfcWindow + IfcRelFillsElement, IfcSlab, IfcRoof aggregating IfcSlab(ROOF), IfcSpace; materials; deterministic GlobalIds; `Rebuilt_Identity` & `Rebuilt_Provenance` psets | DEMONSTRATED for M1 scope |
| IFC validation | re-open, schema check, relationship checks, and **independent geometry check**: IfcOpenShell's OpenCASCADE kernel recomputes every element's volume, compared to MODEL's manifold3d volume | DEMONSTRATED |
| **GLB** | one node per element, `extras` = {genome_id, ifc_guid, type, rev}; sidecar JSON with provenance | DEMONSTRATED |
| **PDF review set** | per-storey plans (true section cut at 1.2 m), roof plan, 4 elevations, building section, axonometric, dimensions (ft-in + m), opening schedule, uncertainty/assumption notes, "model review — not for permit or construction" title block | DEMONSTRATED |
| **Export report** | what was retained / transformed / approximated / omitted per target | DEMONSTRATED |
| Chief Architect / Revit / SketchUp | see `docs/INTEGRATIONS.md` | RESEARCH — no tested integration yet |

Drawings are cut/projected from the same compiled meshes that produce the IFC and GLB, and annotated from the same Genome values — there is no separate drawing model.

---

## 5. Evaluation principle

Self-consistency tests (exports agree with the model) are necessary but not sufficient. Each milestone also has **independent references**:
- M1: hand-computed analytic truths for the fictional house (written in the test file, not derived from the compiler) + OpenCASCADE cross-check of volumes via IFC.
- M2: a controlled evidence set whose ground truth is known (synthetic notes with a planted conflict and a planted typo); measure extraction precision/recall and final dimension error.
- M3+: real property (7244 Waterloo Road) evaluated against independent tape/laser measurements and any existing drawings Carter provides — never against the system's own outputs.
