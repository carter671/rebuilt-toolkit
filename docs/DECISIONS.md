# Design decisions (and the alternatives not taken)

| # | Decision | Why | Alternative considered |
|---|---|---|---|
| D1 | Genome is the only authoritative store; MODEL is a pure function | Model and spec cannot drift if there's only one; any revision reproducible | Editable model synced back to spec (drift-prone) |
| D2 | JSON + Pydantic, `extra="forbid"`, JSON Schema generated from code | One source of truth for schema; strict by default; readable diffs | Protobuf/SQLite (less inspectable), IFC as the master (vendor-shaped, weak at uncertainty) |
| D3 | Canonical metres; keep verbatim input strings | Unambiguous maths; nothing lost from field notation | Store inches (US-centric, still needs conversions for IFC) |
| D4 | Per-property `Value` records with separate basis / verification / uncertainty / confidence | Brief requires these to be distinct; property-level provenance | Element-level confidence (too coarse) |
| D5 | Bare numbers allowed but forced to `assumed` | Convenient authoring without false precision | Rejecting bare numbers (hostile to quick sketching) |
| D6 | Unknown values: null + basis `unknown`; profile defaults are explicit and reported | Never invent a precise number silently | Required fields everywhere (blocks progressive modelling) |
| D7 | Wall baselines + junction resolution in MODEL | Matches how people measure; IFC/Revit/Chief all think in wall axes | Store final face polygons (loses wall semantics) |
| D8 | manifold3d for solids & booleans | Robust, deterministic, guaranteed-manifold booleans; small dependency | OpenCASCADE everywhere (heavier, slower); trimesh+blender (non-deterministic env) |
| D9 | Independent IFC check with OpenCASCADE | A second kernel computing the same volumes catches errors in either path | Self-consistency only (insufficient per brief) |
| D10 | Roof as lower envelope of eave planes on a convex footprint | Exact for gable/hip/shed and their convex mixes; tiny code | Straight skeleton now (needed for valleys — M3) |
| D11 | Unsupported features are not built, and dependents aren't either | "Report, don't silently simplify" | Building an approximation (would look plausible and be wrong) |
| D12 | Overlaps below `tolerances.overlap` (2 mm) are info, not errors | Measured values differ from design by sub-mm; real conflicts are cm-scale | Zero tolerance (floods review with noise) |
| D13 | Capture registers evidence automatically, changes building values only through review | Matches the brief's automation boundary; auditable | Auto-apply high-confidence values (premature before measuring accuracy on real data) |
| D14 | Rule-based text extraction first; LLM/vision extraction later behind the same `Extracted` interface, always `basis: extracted/observed` + review | Deterministic, testable baseline to compare learned extractors against | LLM first (harder to test, can hallucinate values) |
| D15 | Viewer emits correction files rather than writing back | Keeps one write path (changesets with author/reason); works offline | Live write-back server (more infrastructure; DESIGNED for later) |
| D16 | PDF via matplotlib from the same solids | Same geometry for all outputs; true-scale vector drawings | Separate 2D drafting model (drift) |
| D17 | Stable IFC GlobalIds = uuid5(project, element id) | Identity survives revisions and re-exports | Random GUIDs (break downstream links on every export) |
