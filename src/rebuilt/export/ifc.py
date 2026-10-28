"""IFC4 (ADD2 TC1) export of a CompiledModel.

Geometry strategy (all in storey-local coordinates, metres):
- Walls: IfcExtrudedAreaSolid of the junction-resolved plan polygon ("SweptSolid"); walls attached
  to a roof get IfcBooleanClippingResult with one IfcHalfSpaceSolid per roof plane ("Clipping").
- Openings: IfcOpeningElement (extruded footprint) + IfcRelVoidsElement to the host wall, so the
  receiving application performs the cut itself.
- Doors/windows: IfcDoor/IfcWindow proxy panel + IfcRelFillsElement.
- Slabs: IfcSlab (FLOOR/BASESLAB); ceilings: IfcCovering(CEILING).
- Roofs: IfcRoof aggregating one IfcSlab(ROOF) per panel; each panel is a profile in the roof plane
  extruded vertically (non-perpendicular extrusion) — exactly the MODEL prism.
- Spaces: IfcSpace aggregated by the storey.
GlobalIds are uuid5(project id / element id), so they are stable across Genome revisions.
"""
from __future__ import annotations

import math
import uuid

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.guid
import numpy as np

from ..genome.schema import Genome
from ..model.compile import CompiledModel

IFC_SCHEMA = "IFC4"


def guid_for(project_id: str, key: str) -> str:
    return ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, f"rebuilt:{project_id}/{key}").hex)


class _B:
    def __init__(self, f):
        self.f = f

    def pt(self, *c):
        return self.f.createIfcCartesianPoint([float(x) for x in c])

    def dr(self, *c):
        return self.f.createIfcDirection([float(x) for x in c])

    def ax3(self, loc=(0, 0, 0), z=(0, 0, 1), x=(1, 0, 0)):
        return self.f.createIfcAxis2Placement3D(self.pt(*loc), self.dr(*z), self.dr(*x))

    def poly_profile(self, pts2):
        pts = [self.pt(*p) for p in pts2] + [self.pt(*pts2[0])]
        return self.f.createIfcArbitraryClosedProfileDef("AREA", None, self.f.createIfcPolyline(pts))

    def extrude(self, pts2, z0, depth, position=None, direction=(0, 0, 1)):
        pos = position or self.ax3((0, 0, z0))
        return self.f.createIfcExtrudedAreaSolid(self.poly_profile(pts2), pos, self.dr(*direction), float(depth))


def _brep(b: "_B", mesh, z_off: float):
    f = b.f
    pts = [f.createIfcCartesianPoint([float(x), float(y), float(z - z_off)]) for x, y, z in mesh.verts]
    faces = [f.createIfcFace([f.createIfcFaceOuterBound(f.createIfcPolyLoop([pts[i] for i in tri]), True)]) for tri in mesh.tris]
    return f.createIfcFacetedBrep(f.createIfcClosedShell(faces))


def _finish_label(g: Genome, fid):
    if not fid:
        return ""
    fn = g.finishes.get(fid)
    return f"{fn.name} ({fn.hex})" if fn and fn.hex else (fn.name if fn else fid)


def _info_props(g: Genome, el, info=None) -> dict:
    """Rebuilt_Info pset: the element's information block (LOI) + phase + history, flattened."""
    info = info if info is not None else getattr(el, "info", None)
    fam = g.families.get(el.family) if el is not None and el.family else None
    props = {}
    if fam:
        props["Family"] = fam.name
    src = [fam.info] if fam else []
    if info:
        src.append(info)
    for inf in src:
        for k in ("category", "subtype", "material", "manufacturer", "model", "serial", "notes"):
            if getattr(inf, k):
                props[k.capitalize()] = getattr(inf, k)
        if inf.finish:
            props["Finish"] = _finish_label(g, inf.finish)
        if inf.install_year and inf.install_year.value is not None:
            props["InstallYear"] = int(inf.install_year.value)
            props["InstallYear.basis"] = inf.install_year.basis
        if inf.condition:
            props["Condition"] = inf.condition.rating
            if inf.condition.notes:
                props["ConditionNotes"] = inf.condition.notes
        if inf.observed:
            o = inf.observed
            if o.date:
                props["ObservedDate"] = o.date
            if o.by:
                props["ObservedBy"] = o.by
            if o.photos:
                props["ObservedPhotos"] = ",".join(o.photos)
            if o.observation:
                props["ObservationId"] = o.observation
            if o.confidence is not None:
                props["ObservationConfidence"] = float(o.confidence)
    if el is not None:
        if el.phase != "existing" or props:
            props["Phase"] = el.phase
        for k, v in sorted(el.properties.items()):
            if v.value is not None:
                props[f"{k}"] = float(v.value)
                props[f"{k}.basis"] = v.basis
        if el.history:
            props["History"] = "; ".join(f"{h.date or '?'} {h.event}{(': ' + h.note) if h.note else ''}" for h in el.history)
    return props


def _style(f, item, hexcol: str, cache: dict):
    if hexcol not in cache:
        h = hexcol.lstrip("#")
        r, gg, bb = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        rgb = f.createIfcColourRgb(None, r, gg, bb)
        shading = f.createIfcSurfaceStyleShading(rgb, 0.0)
        cache[hexcol] = f.createIfcSurfaceStyle(hexcol, "BOTH", [shading])
    f.createIfcStyledItem(item, [cache[hexcol]], None)


def export_ifc(model: CompiledModel, g: Genome, path: str) -> ifcopenshell.file:
    f = ifcopenshell.file(schema=IFC_SCHEMA)
    b = _B(f)
    pid = g.project.id
    gid = lambda k: guid_for(pid, k)  # noqa: E731

    # units & contexts
    units = [f.createIfcSIUnit(None, "LENGTHUNIT", None, "METRE"),
             f.createIfcSIUnit(None, "AREAUNIT", None, "SQUARE_METRE"),
             f.createIfcSIUnit(None, "VOLUMEUNIT", None, "CUBIC_METRE"),
             f.createIfcSIUnit(None, "PLANEANGLEUNIT", None, "RADIAN")]
    tn = g.project.coordinate_system.true_north_deg
    tn_rad = math.radians(tn.value) if tn and tn.value is not None else 0.0
    ctx = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1e-5, b.ax3(),
                                                    f.createIfcDirection([-math.sin(tn_rad), math.cos(tn_rad)]))
    body = f.createIfcGeometricRepresentationSubContext("Body", "Model", None, None, None, None, ctx, None, "MODEL_VIEW", None)
    project = f.createIfcProject(gid("project"), None, g.project.name, "Generated by Rebuilt MODEL — review model",
                                 None, None, None, [ctx], f.createIfcUnitAssignment(units))

    site_pl = f.createIfcLocalPlacement(None, b.ax3())
    site = f.createIfcSite(gid("site"), None, g.property.address or "Site", None, None, site_pl, None, None, "ELEMENT",
                           None, None, None, None, None)
    bld_entities, storeys = [], {}
    for bd in g.buildings:
        bpl = f.createIfcLocalPlacement(site_pl, b.ax3())
        be = f.createIfcBuilding(gid(f"building/{bd.id}"), None, bd.name, None, None, bpl, None, None, "ELEMENT", None, None, None)
        bld_entities.append(be)
        st_list = []
        for s in bd.storeys:
            spl = f.createIfcLocalPlacement(bpl, b.ax3((0, 0, s.elevation.value)))
            se = f.createIfcBuildingStorey(gid(f"storey/{s.id}"), None, s.name, None, None, spl, None, s.id, "ELEMENT", s.elevation.value)
            storeys[s.id] = (se, spl, s.elevation.value)
            st_list.append(se)
        f.createIfcRelAggregates(gid(f"agg/building/{bd.id}"), None, None, None, be, st_list)
    f.createIfcRelAggregates(gid("agg/project"), None, None, None, project, [site])
    f.createIfcRelAggregates(gid("agg/site"), None, None, None, site, bld_entities)

    def shape(items, rtype):
        return f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(body, "Body", rtype, items)])

    def local_pl(storey_id):
        return f.createIfcLocalPlacement(storeys[storey_id][1], b.ax3())

    contained: dict[str, list] = {}
    space_agg: dict[str, list] = {}
    by_material: dict[str, list] = {}
    ifc_of: dict[str, object] = {}
    in_space: dict[str, list] = {}
    styles: dict[str, object] = {}

    for eid, ce in model.elements.items():
        z_off = storeys[ce.storey][2] if ce.storey else 0.0
        ent = None
        if ce.type == "wall":
            d = ce.data
            depth = (d["top_z"] - d["base_z"]) if d["top_z"] is not None else (model.elements[d["attached_roof"]].data["top_z"] + 1.0 - d["base_z"])
            solid = b.extrude(d["plan_polygon"], d["base_z"] - z_off, depth)
            rtype = "SweptSolid"
            if d["attached_roof"]:
                for (a, bb, c) in [p["plane"] for p in model.elements[d["attached_roof"]].data["panels"]]:
                    nrm = np.array([-a, -bb, 1.0])
                    nrm /= np.linalg.norm(nrm)
                    xdir = np.array([1.0, 0.0, 0.0]) if abs(nrm[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
                    xdir = xdir - nrm * xdir.dot(nrm)
                    xdir /= np.linalg.norm(xdir)
                    plane = f.createIfcPlane(b.ax3((0, 0, c - z_off), tuple(nrm), tuple(xdir)))
                    # normal points up, into the half-space material being removed -> AgreementFlag False
                    hs = f.createIfcHalfSpaceSolid(plane, False)
                    solid = f.createIfcBooleanClippingResult("DIFFERENCE", solid, hs)
                rtype = "Clipping"
            ent = f.createIfcWall(gid(eid), None, ce.name or eid, None, None, local_pl(ce.storey), shape([solid], rtype), eid,
                                  "SOLIDWALL")
        elif ce.type == "opening":
            host = model.elements[ce.data["host"]].data["frame"]
            hb = model.elements[ce.data["host"]].data["baseline"][0]
            dd, nn = host["d"], host["n"]
            u0, u1 = ce.data["offset"], ce.data["offset"] + ce.data["width"]
            from ..model.compile import EPS_CUT
            v0, v1 = host["off_right"] - EPS_CUT, host["off_left"] + EPS_CUT
            corner = lambda u, v: (hb[0] + dd[0] * u + nn[0] * v, hb[1] + dd[1] * u + nn[1] * v)  # noqa: E731
            pts = [corner(u0, v0), corner(u1, v0), corner(u1, v1), corner(u0, v1)]
            from ..geom2d import ensure_ccw
            solid = b.extrude(ensure_ccw(pts), ce.data["sill_z"] - z_off, ce.data["height"])
            ent = f.createIfcOpeningElement(gid(eid), None, ce.name or eid, None, None, local_pl(ce.storey),
                                            shape([solid], "SweptSolid"), eid, "OPENING")
        elif ce.type == "filling":
            op = model.elements[ce.data["opening"]].data
            host = model.elements[ce.data["host"]].data
            fr, hb = host["frame"], host["baseline"][0]
            dd, nn = fr["d"], fr["n"]
            vc = (fr["off_left"] + fr["off_right"]) / 2
            t = ce.data["thickness"]
            corner = lambda u, v: (hb[0] + dd[0] * u + nn[0] * v, hb[1] + dd[1] * u + nn[1] * v)  # noqa: E731
            u0, u1 = op["offset"], op["offset"] + op["width"]
            from ..geom2d import ensure_ccw
            pts = ensure_ccw([corner(u0, vc - t / 2), corner(u1, vc - t / 2), corner(u1, vc + t / 2), corner(u0, vc + t / 2)])
            solid = b.extrude(pts, op["sill_z"] - z_off, op["height"])
            if ce.ifc_class == "IfcDoor":
                ent = f.createIfcDoor(gid(eid), None, ce.name, None, None, local_pl(ce.storey), shape([solid], "SweptSolid"),
                                      eid, op["height"], op["width"], "DOOR", None, ce.data["operation"] or None)
            else:
                ent = f.createIfcWindow(gid(eid), None, ce.name, None, None, local_pl(ce.storey), shape([solid], "SweptSolid"),
                                        eid, op["height"], op["width"], "WINDOW", None, ce.data["operation"] or None)
        elif ce.type == "slab":
            d = ce.data
            solid = b.extrude(d["boundary"], d["bottom_z"] - z_off, d["thickness"])
            if d["kind"] == "ceiling":
                ent = f.createIfcCovering(gid(eid), None, ce.name, None, None, local_pl(ce.storey), shape([solid], "SweptSolid"), eid, "CEILING")
            else:
                ent = f.createIfcSlab(gid(eid), None, ce.name, None, None, local_pl(ce.storey), shape([solid], "SweptSolid"), eid,
                                      "BASESLAB" if d["kind"] == "base" else "FLOOR")
        elif ce.type == "roof":
            roof = f.createIfcRoof(gid(eid), None, ce.name, None, None, local_pl(ce.storey), None, eid,
                                   {"gable": "GABLE_ROOF", "hip": "HIP_ROOF", "shed": "SHED_ROOF"}.get(g.elements[eid].form, "NOTDEFINED"))
            panels = []
            dv = ce.data["vertical_thickness"]
            if ce.data.get("trimmed_by") or ce.data.get("cut_by") or ce.data.get("notched_by"):
                # panels cut where this roof dies into others (valleys): exported as faceted B-reps
                for k, (pname, pm) in enumerate(sorted(ce.parts.items())):
                    pk = f"{eid}/panel-{k}"
                    brep = _brep(b, pm, z_off)
                    pe = f.createIfcSlab(gid(pk), None, f"{ce.name} panel {k}", None, None,
                                         f.createIfcLocalPlacement(storeys[ce.storey][1], b.ax3()), shape([brep], "Brep"), pk, "ROOF")
                    panels.append(pe)
                    ifc_of[pk] = pe
                    if ce.material:
                        by_material.setdefault(ce.material, []).append(pe)
            for k, pn in enumerate([] if (ce.data.get("trimmed_by") or ce.data.get("cut_by") or ce.data.get("notched_by")) else ce.data["panels"]):
                a, bb, c = pn["plane"]
                nrm = np.array([-a, -bb, 1.0]) / math.sqrt(a * a + bb * bb + 1)
                xdir = np.array([1.0, 0.0, a])
                if np.linalg.norm(np.cross(xdir, nrm)) < 1e-6:
                    xdir = np.array([0.0, 1.0, bb])
                xdir = xdir - nrm * xdir.dot(nrm)
                xdir /= np.linalg.norm(xdir)
                ydir = np.cross(nrm, xdir)
                origin = np.array([0.0, 0.0, c])
                loc2 = []
                for (x, y) in pn["region"]:
                    P = np.array([x, y, a * x + bb * y + c]) - origin
                    loc2.append((float(P.dot(xdir)), float(P.dot(ydir))))
                up = np.array([0.0, 0.0, 1.0])
                ext_dir = (float(up.dot(xdir)), float(up.dot(ydir)), float(up.dot(nrm)))
                pos = b.ax3((0, 0, c - z_off), tuple(nrm), tuple(xdir))
                solid = f.createIfcExtrudedAreaSolid(b.poly_profile(loc2), pos, b.dr(*ext_dir), float(dv))
                pk = f"{eid}/panel-{k}"
                pe = f.createIfcSlab(gid(pk), None, f"{ce.name} panel {k}", None, None,
                                     f.createIfcLocalPlacement(storeys[ce.storey][1], b.ax3()), shape([solid], "SweptSolid"), pk, "ROOF")
                panels.append(pe)
                ifc_of[pk] = pe
                if ce.material:
                    by_material.setdefault(ce.material, []).append(pe)
            f.createIfcRelAggregates(gid(f"agg/{eid}"), None, None, None, roof, panels)
            ent = roof
        elif ce.type == "component":
            pdt = ce.data.get("predefined_type", "NOTDEFINED")
            otype = None
            if pdt.startswith("USERDEFINED:"):
                pdt, otype = "USERDEFINED", pdt.split(":", 1)[1]
            rep = None
            if ce.mesh is not None:
                item = _brep(b, ce.mesh, z_off)
                if ce.data.get("color"):
                    _style(f, item, ce.data["color"], styles)
                rep = shape([item], "Brep")
            ent = f.create_entity(ce.ifc_class, GlobalId=gid(eid), Name=ce.name or eid, ObjectType=otype or ce.data["kind"],
                                  ObjectPlacement=local_pl(ce.storey), Representation=rep, Tag=eid)
            try:
                ent.PredefinedType = pdt
            except Exception:  # class without PredefinedType or value outside its enumeration
                pass
            if ce.data.get("space"):
                in_space.setdefault(ce.data["space"], []).append(ent)
                ifc_of[eid] = ent
                if ce.material:
                    by_material.setdefault(ce.material, []).append(ent)
                continue
        elif ce.type == "space":
            d = ce.data
            solid = b.extrude(d["boundary"], d["base_z"] - z_off, d["height"])
            ent = f.createIfcSpace(gid(eid), None, ce.name, None, None, local_pl(ce.storey), shape([solid], "SweptSolid"), eid,
                                   "ELEMENT", "INTERNAL", None)
        if ent is None:
            continue
        ifc_of[eid] = ent
        if ce.type == "space":
            space_agg.setdefault(ce.storey, []).append(ent)
        elif ce.type != "opening":
            contained.setdefault(ce.storey, []).append(ent)
        if ce.material and ce.type != "roof":
            by_material.setdefault(ce.material, []).append(ent)

    for sid, items in sorted(contained.items()):
        f.createIfcRelContainedInSpatialStructure(gid(f"contain/{sid}"), None, None, None, items, storeys[sid][0])
    for sid, items in sorted(space_agg.items()):
        f.createIfcRelAggregates(gid(f"agg/spaces/{sid}"), None, None, None, storeys[sid][0], items)
    for sp, items in sorted(in_space.items()):
        if sp in ifc_of:
            f.createIfcRelContainedInSpatialStructure(gid(f"contain/space/{sp}"), None, None, None, items, ifc_of[sp])
    for eid, ce in model.elements.items():
        # IFC: a covering covers one element, so cladding is one IfcCovering per host wall, aggregated by the Genome element
        if ce.type == "component" and ce.data["kind"] == "cladding":
            parts = []
            for h in ce.data.get("hosts", []):
                if h in ifc_of:
                    pc = f.create_entity("IfcCovering", GlobalId=gid(f"{eid}/{h}"), Name=f"{ce.name or eid} on {h}", ObjectType="cladding",
                                         ObjectPlacement=local_pl(model.elements[h].storey), Tag=f"{eid}/{h}", PredefinedType="CLADDING")
                    f.createIfcRelCoversBldgElements(gid(f"covers/{eid}/{h}"), None, None, None, ifc_of[h], [pc])
                    parts.append(pc)
            if parts:
                f.createIfcRelAggregates(gid(f"agg/{eid}"), None, None, None, ifc_of[eid], parts)
    for host, op in model.relations["voids"]:
        f.createIfcRelVoidsElement(gid(f"voids/{op}"), None, None, None, ifc_of[host], ifc_of[op])
    for op, fill in model.relations["fills"]:
        f.createIfcRelFillsElement(gid(f"fills/{fill}"), None, None, None, ifc_of[op], ifc_of[fill])
    for mid, items in sorted(by_material.items()):
        m = g.materials[mid]
        mat = f.createIfcMaterial(m.name, None, m.category)
        f.createIfcRelAssociatesMaterial(gid(f"mat/{mid}"), None, None, None, items, mat)

    # property sets
    for eid, ce in model.elements.items():
        ent = ifc_of.get(eid)
        if ent is None:
            continue
        ps = ifcopenshell.api.pset.add_pset(f, product=ent, name="Rebuilt_Identity")
        ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={
            "GenomeId": eid, "ElementRevision": int(ce.rev), "GenomeRevision": int(model.genome_revision),
            "CompilerVersion": model.compiler_version, "ModelHash": model.model_hash, "ProjectId": pid})
        props = {}
        for p, rec in sorted(ce.params.items()):
            props[f"{p}.basis"] = str(rec.get("basis"))
            if rec.get("verification"):
                props[f"{p}.verification"] = rec["verification"]
            if rec.get("uncertainty") is not None:
                props[f"{p}.uncertainty_m"] = float(rec["uncertainty"])
            if rec.get("confidence") is not None:
                props[f"{p}.confidence"] = float(rec["confidence"])
            if rec.get("observations"):
                props[f"{p}.observations"] = ",".join(rec["observations"])
            if rec.get("defaulted"):
                props[f"{p}.defaulted"] = True
        if props:
            ps = ifcopenshell.api.pset.add_pset(f, product=ent, name="Rebuilt_Provenance")
            ifcopenshell.api.pset.edit_pset(f, pset=ps, properties=props)
        gel = g.elements.get(eid.split("#")[0])
        if gel is not None:
            info_props = _info_props(g, gel)
            if info_props:
                ps = ifcopenshell.api.pset.add_pset(f, product=ent, name="Rebuilt_Info")
                ifcopenshell.api.pset.edit_pset(f, pset=ps, properties=info_props)
            if getattr(gel, "unit", None) is not None and ce.type == "filling":
                u = gel.unit
                props_u = {k: v for k, v in {"UnitType": u.type, "Lites": u.lites, "FrameMaterial": u.frame_material,
                                              "SashFinish": _finish_label(g, u.sash_finish), "Hardware": u.hardware}.items() if v}
                for k in ("storm", "screen"):
                    if getattr(u, k) is not None:
                        props_u[k.capitalize()] = bool(getattr(u, k))
                if props_u:
                    ps = ifcopenshell.api.pset.add_pset(f, product=ent, name="Rebuilt_OpeningUnit")
                    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties=props_u)
            for k, inf in sorted(getattr(gel, "surfaces", {}).items()):
                sp = _info_props(g, None, inf)
                if sp:
                    ps = ifcopenshell.api.pset.add_pset(f, product=ent, name=f"Rebuilt_Surface_{k}")
                    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties=sp)
        if ce.type == "wall":
            ps = ifcopenshell.api.pset.add_pset(f, product=ent, name="Pset_WallCommon")
            ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"IsExternal": bool(ce.data["exterior"])})
            q = f.createIfcElementQuantity(gid(f"qto/{eid}"), None, "Qto_WallBaseQuantities", None, None, [
                f.createIfcQuantityLength("Length", None, None, ce.data["length"], None),
                f.createIfcQuantityLength("Width", None, None, ce.data["thickness"], None),
                f.createIfcQuantityVolume("GrossVolume", None, None, ce.data["gross_volume"], None),
                f.createIfcQuantityVolume("NetVolume", None, None, ce.data["volume"], None)])
            f.createIfcRelDefinesByProperties(gid(f"qtorel/{eid}"), None, None, None, [ent], q)
        if ce.type == "space":
            q = f.createIfcElementQuantity(gid(f"qto/{eid}"), None, "Qto_SpaceBaseQuantities", None, None, [
                f.createIfcQuantityArea("NetFloorArea", None, None, ce.data["area"], None),
                f.createIfcQuantityLength("Height", None, None, ce.data["height"], None)])
            f.createIfcRelDefinesByProperties(gid(f"qtorel/{eid}"), None, None, None, [ent], q)
    f.write(path)
    return f
