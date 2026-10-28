# 7244 Waterloo Road — real-property target

**Status (2026-10-15): G3 as-built; capture epoch 2 (guided tape walk) closed.** The tape walk re-measured the disputed block sizes, room depths, eave and floor heights, the garage door, the porch end and the compass bearing (road side faces 103°; element names use project directions). Evidence: Carter's field notes, two as-built PDFs, a roof-pitch table, 39 photos (10 exterior, 24 interior + 5) and the Redfin listing text. Carter closed capture and accepted all of it as verified; every value is verified with its basis kept (photo estimates stay "observed"). Directions are inferred (porch = east, road = west, garage = north).

Model: 476 compiled elements — walls, openings, roofs (incl. the back hall's low shed roof and the kitchen south gable above it), slabs, rooms, plus 334 components (siding by face with exposure and colour, corner boards, casings, shutters, gable vents, fascia, soffits, rake boards, gutters, downspouts, three chimneys, cupola, vent stacks, lights, meters, AC, cameras, porch posts/mullions/rails, exposed foundation faces, and 172 interior items as room information). The listing's "attached garage" conflicts with the photos (detached) and is recorded.

What the as-builts contributed: printed dimensions and opening codes, and the block arrangement. No lengths were scaled from linework; positions scaled from as-built symbols are marked "inferred".

Not done: interior items placed as 3D objects; 2F partitions; evaluation against held-back measurements (none provided).

## What improves it next (in order of value)
1. **Any existing drawings** — plans, permit sets, appraisal sketch with dimensions, previous listing floor plan. (Becomes `basis: extracted`.)
2. **Exterior perimeter tape measurements** — every exterior wall segment, outside face to outside face, plus wall thickness at a door/window jamb. This alone fixes the footprint.
3. **Per room:** two wall lengths, ceiling height, and each door/window: width, height, sill, distance from the nearest corner.
4. **Roof:** pitch on each roof plane (level + tape, rise over 12"), eave overhang, and which edges are eaves vs gables.
5. **Photos:** each exterior face square-on, each corner at 45°, each room from two opposite corners; a tape measure visible in at least one photo per face. (Topology now; scale evidence for M3 photogrammetry.)
6. **Walkthrough video** (optional) — frames are extracted and stored as derived assets in M2.
7. **Independent check set** — 10–15 dimensions measured by a second person or a laser, *held back* from the pipeline, used only to score the result.

Write notes the natural way ("kitchen north wall 12' 6", window over sink 36 wide 48 tall, sill 42") — Capture is designed to parse that, and anything it can't place unambiguously becomes a review question instead of a guess.

## Authorisation
Please say explicitly whether I may use any public sources (e.g. county auditor records, aerial imagery) for this address. Until then I will use only what you provide.

## Evaluation (when evidence exists)
`docs/eval/waterloo-road-<date>.md`: per-dimension error vs the held-back check set, what was measured vs inferred vs assumed, unresolved disputes, and which outputs are fit for which purpose.
