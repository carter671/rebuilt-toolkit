# Authoring-tool integrations — status and test plan

**Nothing in this file is a tested result.** No Chief Architect, Revit or SketchUp installation or licence has been available to this implementation. Everything below is either desk research (cited) or general knowledge flagged as unverified, plus the protocol to establish the truth.

## Outcome ladder (use these words precisely)
1. **Viewable geometry** — the building appears and looks right.
2. **Editable generic geometry** — faces/solids can be moved or modified, but the app doesn't know it's a wall.
3. **BIM objects with retained semantics** — categorised as walls/doors/windows etc., properties (incl. `Rebuilt_Identity`, `Rebuilt_Provenance`) survive, but they don't behave like the app's own objects.
4. **Native parametric objects** — app-native walls/doors/windows/roofs/floors/levels that edit, host and regenerate normally.

Levels 1–3 are never evidence of level 4.

## Revit
- **IFC import, desk research:** opening an IFC directly gives correctly categorised elements but as in-place families that cannot be moved or changed like regular families, often with a blank type selector and missing parameters; linking then binding produces DirectShape objects that carry more parameters but are still not editable like regular system/component families ([Arkance, Revit IFC tip](https://ukcommunity.arkance.world/hc/en-us/articles/21566204744594-Revit-2022-Tip-Working-with-IFC-files-Elements-missing-limited-functionality)). Autodesk's open-source `revit-ifc` covers link/export, but notes most import logic runs inside closed Revit code ([Autodesk/revit-ifc](https://github.com/Autodesk/revit-ifc)).
  - **Expected best case via IFC: level 3.**
- **Path to level 4:** a Revit add-in (C#, Revit API) that reads Genome (or our IFC + `Rebuilt_Identity`) and calls `Wall.Create` on a level with a wall type matched to thickness, `FamilyInstance` creation hosted in those walls for doors/windows, `Floor.Create`, `FootPrintRoof` with slope-defining edges, `Level.Create` for storeys; store GenomeId in a shared parameter so a second run can update rather than duplicate.
- **Verification needs:** a Revit licence (any recent version), a Windows machine I can drive, and family libraries for doors/windows.

## SketchUp
- **Unverified general knowledge:** SketchUp Pro imports IFC as components/groups with IFC classification attributes; SketchUp has no native parametric wall object at all, so level 4 does not exist in the usual sense. The Ruby API can create groups/components, apply classifications and attribute dictionaries — enough for a level-3 adapter that writes GenomeId and provenance into attribute dictionaries ([SketchUp forum discussions on IFC import/export](https://forums.sketchup.com/t/ifc-import-to-export-from-sketchup-pro/46139)).
- **Plan:** (a) test IFC import on SketchUp Pro; (b) a Ruby extension that builds solids per element with tags per storey and classifications, so walls/openings stay separate selectable objects.
- **Verification needs:** SketchUp Pro licence; desktop machine.

## Chief Architect
- **Unverified / unknown:** I could not confirm from Chief Architect's own documentation whether current versions import IFC, or how imported IFC objects behave; the X16 changelog I checked mentions OBJ, DWG and PDF import fixes but nothing about IFC ([Chief Architect X16 changelog](https://cloud.chiefarchitect.com/1/pdf/documentation/chief-architect-x16-changelog.pdf)). I am not aware of a public modelling API for creating native Chief walls programmatically.
  - **Likely best case without an API:** level 1–2 (imported 3D symbol/geometry used as a reference to trace over with native walls).
- **Plan:** test on Carter's Chief installation: (1) IFC import if offered, (2) DWG plan import as a tracing underlay (we can export DXF plans from MODEL cheaply), (3) 3D symbol import (OBJ/DAE from our GLB). Ask Chief support about any automation interface. A **DXF/DWG plan underlay with layers per element type** may be the most useful practical route for Chief.
- **Verification needs:** Carter's Chief Architect version/edition and a machine to test on.

## Test protocol (per application)
1. Import `examples/fictional_house/output/model.ifc` (and later Waterloo Road).
2. Record per element type: present? category? editable how? hosted openings? levels created and at the right elevation? materials? `Rebuilt_Identity.GenomeId` visible?
3. Measure 10 reference dimensions in the app and compare to `compile_report.json`.
4. Try normal edits: move a wall, change its height, move a window along its wall, change roof pitch. Record what regenerates.
5. Write the result as `docs/integration-tests/<app>-<version>-<date>.md` with screenshots, classified on the ladder.
6. Round-trip (app → Genome) is a separate capability, designed only after step 5 for that app.
