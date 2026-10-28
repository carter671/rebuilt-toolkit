# Cross-review package (for exchange with the Codex implementation)

I have no access to Codex's files and have not communicated with it. Everything here is meant to make a
side-by-side comparison cheap once Carter shares both projects.

## What to hand over from this repo
| Item | Path |
|---|---|
| Architecture & phases | `docs/ARCHITECTURE.md`, `docs/PHASES.md` |
| Demonstrated vs intended | `docs/CAPABILITIES.md` |
| Design decisions & alternatives | `docs/DECISIONS.md` |
| Genome JSON Schema | `schemas/genome.schema.json` (generated from `src/rebuilt/genome/schema.py`) |
| Sample input | `examples/fictional_house/fictional_house.genome.json` (+ `build_genome.py`) |
| Controlled evidence set + ground truth | `examples/fictional_house/evidence/` (`truth.json`) |
| Implementation-neutral reference quantities | `examples/fictional_house/reference_quantities.json` |
| Generated outputs | `examples/fictional_house/output/` (IFC, GLB, PDF, viewer, compile/export reports) |
| Tests | `pytest` (79 tests) |
| Neutral IFC checker | `tools/reference_check.py OTHER.ifc [--map map.json]` |

## Subsystem interfaces (inputs → outputs)
| Subsystem | Input | Output |
|---|---|---|
| Capture | evidence files + current Genome | evidence store records; changeset adding `sources`/`observations`; `proposals.json` |
| Review | proposals, reviewer decisions, direct edits | changesets (JSON-pointer ops with `prev`), appended to `changes.jsonl` |
| Genome | JSON document | validated `Genome` object + `IssueList` (codes listed in `validate.py`) |
| MODEL | Genome + profile (+ optional cache) | `CompiledModel` (meshes, analytic data, provenance index, relations, issues, unsupported, model_hash) |
| Export | CompiledModel + Genome | IFC4, GLB + `.meta.json`, PDF, `export_report.json`, `compile_report.json`, `viewer.html` |

## Suggested comparison procedure
1. **Same building, both schemas.** Translate `fictional_house.genome.json` into Codex's format (or vice versa). Translation pain points are themselves findings — record each field that has no counterpart.
2. **Neutral quantities.** Run `tools/reference_check.py` on Codex's IFC (with a name mapping if its ids differ). Both implementations are then scored against hand-derived numbers, not against each other.
3. **Semantics.** Compare IFC class counts, void/fill relationships, GlobalId stability across a revision, psets carrying provenance.
4. **Failure behaviour.** Feed each implementation the mutations in `tests/test_genome.py::test_validation_codes` and `tests/test_model.py::test_unsupported_reported_not_dropped`; compare whether each fails loudly, and how.
5. **Capture.** Run both on `examples/fictional_house/evidence/` and score against `truth.json`.
6. **Determinism.** Two runs, shuffled input order → identical hash/geometry?

## Likely compatibility differences & migration paths
- **Units:** this repo stores metres; if Codex stores feet or mm, conversion is lossless, but keep the verbatim `input` string either way.
- **Value records:** if Codex uses bare numbers plus element-level metadata, map to `Value` with `basis` from the element-level field; per-property provenance cannot be recovered where it was never recorded.
- **Wall definition:** this repo uses centre/left/right-aligned baselines + resolved junctions; a face-polygon representation can be converted to baselines only for straight constant-thickness walls.
- **Openings:** offset from host baseline *start* to the near edge, sill from host base. Other conventions (centre-referenced, from a corner face) need a host-geometry-aware conversion.
- **Roofs:** this repo uses footprint + per-edge roles + single pitch. An explicit-planes representation is more general; ours converts to planes losslessly (`model/roofs.py::planes`), not the other way.
- **Merge strategy:** keep whichever Genome schema better separates identity, value provenance and geometry; write a migration (`genome/migrate.py` pattern) rather than a one-off converter.
