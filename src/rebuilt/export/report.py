"""Export orchestration and the export report (retained / transformed / approximated / omitted)."""
from __future__ import annotations

import json
from pathlib import Path

from ..genome.schema import Genome
from ..model.compile import CompiledModel
from .drawings import export_pdf
from .glb import export_glb
from .ifc import IFC_SCHEMA, export_ifc
from .ifc_validate import validate_ifc

STATIC = {
    "ifc": {
        "format": f"{IFC_SCHEMA} (ADD2 TC1), STEP physical file",
        "retained": [
            "Project/Site/Building/BuildingStorey hierarchy with storey elevations",
            "Element classes: IfcWall, IfcOpeningElement, IfcDoor, IfcWindow, IfcSlab (FLOOR/BASESLAB/ROOF), IfcCovering (CEILING), IfcRoof, IfcSpace",
            "Wall–opening voiding (IfcRelVoidsElement) and opening filling (IfcRelFillsElement)",
            "Roof assembly: IfcRoof aggregating one IfcSlab(ROOF) per panel",
            "Materials (single IfcMaterial per element) and category",
            "Stable GlobalIds derived from Genome element ids (same across revisions)",
            "Rebuilt_Identity pset (GenomeId, ElementRevision, GenomeRevision, ModelHash)",
            "Rebuilt_Provenance pset per parameter: basis, verification, uncertainty, confidence, observation ids",
            "Pset_WallCommon.IsExternal, Qto_WallBaseQuantities, Qto_SpaceBaseQuantities",
        ],
        "transformed": [
            "Junction-resolved wall plan polygons are exported as extruded profiles (wall axis/thickness are in Qto, not as IfcMaterialLayerSetUsage)",
            "Roof-attached walls exported as IfcBooleanClippingResult with half-spaces (Representation 'Clipping')",
            "Roof panels: profiles lying in the roof plane extruded vertically (non-perpendicular extrusion)",
        ],
        "approximated": [
            "Doors/windows are proxy panels (no frames, sashes, swing geometry); OverallWidth/Height = rough opening",
        ],
        "omitted": [
            "Material layer sets/assemblies (not in Genome v0.1)",
            "Observation records and evidence files (referenced by id only)",
            "Conflict candidates for disputed values (only the selected value + 'disputed' flag)",
            "Wall axis representation and wall connection relationships (IfcRelConnectsPathElements) — planned",
            "Type objects (IfcWallType, IfcDoorType ...) — planned",
        ],
    },
    "glb": {
        "format": "glTF 2.0 binary (GLB) + <name>.meta.json sidecar",
        "retained": ["Per-element meshes as separate nodes", "node.extras: genome_id, ifc_guid, type, ifc_class, rev, storey",
                     "Display colours from Genome materials"],
        "transformed": ["Z-up → Y-up axis swap (x, y, z) → (x, z, -y)", "Flat-shaded, de-indexed triangles"],
        "approximated": ["Glass and spaces rendered translucent"],
        "omitted": ["All BIM semantics beyond node extras: no relationships, hosting, materials-as-data, quantities in the GLB itself "
                    "(provided in the sidecar JSON instead)", "Opening voids (cuts are already applied to walls)"],
    },
    "pdf": {
        "format": "PDF, ANSI B (11×17 in) sheets, true-scale imperial architectural scales",
        "retained": ["Plans cut from solids per storey", "Roof plan from panel regions", "Elevations and sections projected from solids",
                     "Opening schedule from Genome values", "Provenance colour-coding and non-measured-value table"],
        "transformed": ["Dimensions rounded to 1/16 in; metres shown to mm"],
        "approximated": ["Hidden-surface removal by painter's ordering of planar faces (may mis-order rare interpenetrating faces)",
                         "Door swings drawn generically (hinge at opening start, inward)"],
        "omitted": ["Annotations required for permit/construction documents", "Stairs, MEP, framing, structure, site"],
    },
}


def export_all(model: CompiledModel, g: Genome, out_dir: str | Path, name: str = "model") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ifc_path, glb_path, pdf_path = out / f"{name}.ifc", out / f"{name}.glb", out / f"{name}.pdf"
    export_ifc(model, g, str(ifc_path))
    ifc_val = validate_ifc(str(ifc_path), model)
    glb_info = export_glb(model, g, str(glb_path))
    notes = [f"IFC: {ifc_val['schema']}; independent OCC check {'PASSED' if ifc_val['ok'] else 'FAILED'} "
             f"({len(ifc_val['geometry'])} elements)",
             f"GLB: {glb_info['nodes']} nodes, identity via node extras + sidecar JSON",
             "Chief Architect / Revit / SketchUp: no tested native integration yet — see INTEGRATIONS.md"]
    sheets = export_pdf(model, g, str(pdf_path), notes)
    report = {
        "genome_revision": model.genome_revision, "model_hash": model.model_hash, "compiler_version": model.compiler_version,
        "profile": model.profile, "unsupported_in_model": model.unsupported,
        "targets": {
            "ifc": {**STATIC["ifc"], "file": ifc_path.name, "validation": ifc_val},
            "glb": {**STATIC["glb"], "file": glb_path.name, "nodes": glb_info["nodes"], "triangles": glb_info["triangles"]},
            "pdf": {**STATIC["pdf"], "file": pdf_path.name, "sheets": sheets},
            "chief_architect": {"status": "not implemented", "see": "docs/INTEGRATIONS.md"},
            "revit": {"status": "not implemented", "see": "docs/INTEGRATIONS.md"},
            "sketchup": {"status": "not implemented", "see": "docs/INTEGRATIONS.md"},
        },
    }
    (out / "export_report.json").write_text(json.dumps(report, indent=1, default=float))
    (out / "compile_report.json").write_text(json.dumps(model.report(), indent=1, default=float))
    return report
