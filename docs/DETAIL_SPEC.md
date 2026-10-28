# Detail specification — what an as-built carries, and in what form (Genome 0.2)

This is the contract between capture and the model. A "real as-built" is three things at once:

| Axis | Question it answers | Where it lives |
|---|---|---|
| **Geometry (LOD)** | Where is it, how big, what shape? | element geometric parameters (Value records) → compiled solids |
| **Information (LOI)** | What is it, what's it made of, what color, what condition, what make/model? | `info` block + `properties` on every element; `finishes` registry; `types` |
| **Time (the 4th dimension)** | When was it observed, by whom, from what; what changed; is it existing, to be removed, or new? | observations (dated, sourced); `info.observed`; `history` events; `phase`; changeset log |

Every number anywhere keeps the provenance contract from 0.1: basis (measured / extracted / observed / inferred / assumed / unknown), uncertainty, confidence, verification, source observations.

## 1. Levels of detail

| Level | Geometry | Information | Example |
|---|---|---|---|
| **G1 massing** | blocks, roofs | name only | M1 fictional house |
| **G2 architectural** | walls, openings, slabs, roofs, rooms | materials | Waterloo first pass |
| **G3 envelope** | + trim, shutters, fascia, soffit, gutters, downspouts, chimneys, exterior fixtures, siding courses | + finish/color, condition, type, photo refs | **Waterloo target now** |
| G4 interior fit-out | + cabinets, appliances, plumbing fixtures, lights, registers as placed objects | + manufacturer/model/serial | Waterloo: interior items recorded as room information (with stated sizes); not yet placed as objects |
| G5 systems | duct/pipe/wire routes, structure | + capacities, circuits | out of scope until there is evidence |

Rule: **information is never held back for lack of geometry.** An item with a known type, location and condition but no measured size is still recorded (info-only, or a symbolic box marked `assumed`).

## 2. Element catalog (Genome 0.2)

Common to every element:
- `info`: `category`, `subtype`, `material`, `finish` (→ finishes registry), `manufacturer`, `model`, `serial`, `install_year` (Value), `condition` {`rating`: good/fair/poor/failed/unknown, `notes`}, `observed` {`date`, `by`, `photos`: [source ids], `observation`: id}, `notes`.
- `family`: optional reference into `families` (shared defaults for size and information, overridable per element — like IFC types).
- `phase`: `existing` (default) / `demolish` / `new` / `temporary` — renovation scenarios.
- `history`: dated events (`installed`, `replaced`, `repaired`, `painted`, `observed_damage`), each with source.
- `properties`: named Value records for anything numeric not in the element's own fields (e.g. `exposure`, `gutter_width`).

| Element | Geometry fields | IFC class |
|---|---|---|
| wall / opening / slab / roof / space | (0.1) | (0.1) |
| **cladding** | host walls, `exposure`, `profile`, `start_z` | IfcCovering CLADDING + RelCoversBldgElements |
| **trim** | subtype (corner board, casing, rake board, band, sill, header, skirt, mullion), host (corner of two walls / opening / roof edge / wall face), `w` (face width), `d` (thickness) | IfcCovering MOLDING |
| **fascia / soffit / gutter** | roof + footprint edges (+ optional `within` plan polygon for a partial run, `gap` off the overhang edge); members stop where the edge runs into a meeting roof or a wall | IfcCovering USERDEFINED (FASCIA / SOFFIT), IfcPipeSegment GUTTER |
| **downspout** | plan point, top/bottom z, section | IfcPipeSegment (downspout) |
| **chimney** | footprint, base z, top elevation | IfcChimney |
| **shutter** | host opening, side, width | IfcShadingDevice SHUTTER |
| **fixture** | placement: on a wall face (`wall`, `u`, `z`, `side`), in a space, or free point; box size | by category: IfcLightFixture, IfcAirTerminal, IfcFlowMeter, IfcUnitaryEquipment, IfcSpaceHeater, IfcSanitaryTerminal, IfcElectricAppliance, IfcBuildingElementProxy |
| space finishes | walls / ceiling / floor / base / crown / wainscot each an info record | Pset on IfcSpace |

Openings gain a `unit` record: `type` (double-hung, casement, fixed, picture, slider, panel door, French door, screen panel, overhead door…), `lites`, `frame_material`, `sash_finish`, `storm`, `screen`.

## 3. Finishes and families
- `finishes`: id → {name, hex (approximate unless from a paint chip), product/brand, sheen, basis}. Elements reference them; changing one color updates every element that uses it.
- `families`: id → default `info` + default size Values (e.g. "original window casing: 4½″ × 1″ painted wood, finish trim"). Exceptions are recorded on the element.

## 4. Capture record (what each inventory row must contain)
`category, subtype, building part, face/room, floor, location (relative to corners/openings), size + method, material, color name + hex, condition + note, photos, confidence, date observed, observer`.
Rows become Genome **observations** with a structured `data` payload; elements cite them. Nothing is lost if the model cannot place an item yet.

## 5. Verification semantics
- `verification: verified` = a person accepted the value. It does not change the basis: a photo estimate accepted as final is `observed` + `verified`.
- A **capture epoch** can be closed (`rebuilt close-capture PROJECT --by --reason`): one changeset marks every value verified by that person, keeps bases, keeps dispute candidates as history, and records `capture.closed`. New evidence opens a new epoch and is reconciled by changesets.
- Corner boards: `sides` names the face of each wall; outside vs inside corners are detected from the wall bodies. Trim and posts on walls stop under eaves/soffits.

## 6. Acceptance tests for G3 (tests/test_g3.py — 6 tests)
- Every element type validates, compiles to closed solids (or is declared info-only), exports to the IFC class above, and appears in GLB with its finish color.
- Trim, shutters, gutters, fascia stay outside the wall body (no interpenetration with walls/roofs beyond the overlap tolerance).
- Chimneys penetrate roofs cleanly (roof solids are cut).
- Elevations draw siding courses at the recorded exposure.
- Info (color, condition, photos) survives into IFC property sets and the viewer.
