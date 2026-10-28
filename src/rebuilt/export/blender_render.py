"""Path-traced stills (Blender Cycles) straight from a compiled model.

    python3 -m rebuilt.export.blender_render MODEL.glb GENOME.json SITE.json SHOTS.json OUT_DIR [--samples N] [--scale S]

Geometry is the compiled model, unchanged. Each element gets a procedural PBR material picked from what the
Genome says it is (siding faces, shingle roofs, plank / tile floors, brick, block, stone, cabinets, quartz,
stainless, glass in real sash frames). Lighting is a physical sky + sun. Nothing is painted in by hand, so a
render can be regenerated for any property or design revision.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

from .render import render_cfg

FT = 0.3048


# ------------------------------------------------------------------ materials
def _hex(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c] + [1.0]


class M:
    """Small helper to build node materials."""

    def __init__(self, name):
        self.m = bpy.data.materials.new(name)
        self.m.use_nodes = True
        self.nt = self.m.node_tree
        self.bsdf = self.nt.nodes["Principled BSDF"]

    def n(self, kind, **kw):
        node = self.nt.nodes.new(kind)
        for k, v in kw.items():
            if k.startswith("in_"):
                key = k[3:]
                node.inputs[int(key) if key.isdigit() else key.replace("_", " ")].default_value = v
            else:
                setattr(node, k, v)
        return node

    def link(self, a, b):
        self.nt.links.new(a, b)

    def set(self, **kw):
        for k, v in kw.items():
            self.bsdf.inputs[k].default_value = v
        return self


def pos(mt):
    return mt.n("ShaderNodeNewGeometry").outputs["Position"]


def mat_plain(name, hexc, rough=0.6, metal=0.0):
    return M(name).set(**{"Base Color": _hex(hexc), "Roughness": rough, "Metallic": metal}).m


def mat_siding():
    mt = M("siding").set(**{"Base Color": _hex("#EEEDE7"), "Roughness": 0.55})
    sep = mt.n("ShaderNodeSeparateXYZ"); mt.link(pos(mt), sep.inputs[0])
    div = mt.n("ShaderNodeMath", operation="DIVIDE", in_1=0.17526)  # 6.9" exposure
    mt.link(sep.outputs["Z"], div.inputs[0])
    fr = mt.n("ShaderNodeMath", operation="FRACT"); mt.link(div.outputs[0], fr.inputs[0])
    # lap profile: board thickens toward its bottom edge, then a shadow line
    pw = mt.n("ShaderNodeMath", operation="POWER", in_1=0.6); mt.link(fr.outputs[0], pw.inputs[0])
    inv = mt.n("ShaderNodeMath", operation="SUBTRACT", in_0=1.0); mt.link(pw.outputs[0], inv.inputs[1])
    bump = mt.n("ShaderNodeBump", in_Strength=0.9, in_Distance=0.012); mt.link(inv.outputs[0], bump.inputs["Height"])
    mt.link(bump.outputs[0], mt.bsdf.inputs["Normal"])
    # faint shadow at each lap
    ramp = mt.n("ShaderNodeValToRGB"); mt.link(fr.outputs[0], ramp.inputs[0])
    ramp.color_ramp.elements[0].position = 0.0; ramp.color_ramp.elements[0].color = _hex("#A9A8A2")
    ramp.color_ramp.elements[1].position = 0.06; ramp.color_ramp.elements[1].color = _hex("#EEEDE7")
    mt.link(ramp.outputs[0], mt.bsdf.inputs["Base Color"])
    return mt.m


def mat_brickish(name, mortar_hex, c1, c2, w, h, mortar=0.006, bias=0.0, vec="xz", rough=0.85, bump=0.6, scale_noise=40.0, spec=0.5):
    """Brick-pattern based material (shingles, planks, tile, brick, block, pavers)."""
    mt = M(name).set(**{"Roughness": rough, "Specular IOR Level": spec})
    sep = mt.n("ShaderNodeSeparateXYZ"); mt.link(pos(mt), sep.inputs[0])
    comb = mt.n("ShaderNodeCombineXYZ")
    if vec == "xz":      # walls / vertical faces: horizontal = x + y, vertical = z
        add = mt.n("ShaderNodeMath", operation="ADD"); mt.link(sep.outputs["X"], add.inputs[0]); mt.link(sep.outputs["Y"], add.inputs[1])
        mt.link(add.outputs[0], comb.inputs["X"]); mt.link(sep.outputs["Z"], comb.inputs["Y"])
    elif vec == "roof":  # roofs: rows follow height, run along x + y
        add = mt.n("ShaderNodeMath", operation="ADD"); mt.link(sep.outputs["X"], add.inputs[0]); mt.link(sep.outputs["Y"], add.inputs[1])
        zz = mt.n("ShaderNodeMath", operation="MULTIPLY", in_1=1.8); mt.link(sep.outputs["Z"], zz.inputs[0])
        mt.link(add.outputs[0], comb.inputs["X"]); mt.link(zz.outputs[0], comb.inputs["Y"])
    else:                # floors: plan x, y
        mt.link(sep.outputs["X"], comb.inputs["X"]); mt.link(sep.outputs["Y"], comb.inputs["Y"])
    br = mt.n("ShaderNodeTexBrick", in_Scale=1.0, in_Mortar_Size=mortar, in_Bias=bias, in_Brick_Width=w, in_Row_Height=h,
              offset=0.5, squash=1.0)
    br.inputs["Color1"].default_value = _hex(c1); br.inputs["Color2"].default_value = _hex(c2)
    br.inputs["Mortar"].default_value = _hex(mortar_hex)
    mt.link(comb.outputs[0], br.inputs["Vector"])
    nz = mt.n("ShaderNodeTexNoise", in_Scale=scale_noise, in_Detail=6.0); mt.link(comb.outputs[0], nz.inputs["Vector"])
    mix = mt.n("ShaderNodeMix", data_type="RGBA", blend_type="OVERLAY", in_Factor=0.18)
    mt.link(br.outputs["Color"], mix.inputs[6]); mt.link(nz.outputs["Color"], mix.inputs[7])
    mt.link(mix.outputs[2], mt.bsdf.inputs["Base Color"])
    b = mt.n("ShaderNodeBump", in_Strength=bump, in_Distance=0.004); mt.link(br.outputs["Fac"], b.inputs["Height"])
    mt.link(b.outputs[0], mt.bsdf.inputs["Normal"])
    return mt.m


def mat_wood_floor():
    m = mat_brickish("wood-floor", "#3B2A1C", "#B58456", "#8E6440", 1.22, 0.178, mortar=0.0015, bias=0.1, vec="xy", rough=0.38,
                     bump=0.25, scale_noise=6.0)
    mt = m.node_tree  # add long grain streaks
    return m


def mat_stone():
    mt = M("stone").set(**{"Roughness": 0.9})
    vo = mt.n("ShaderNodeTexVoronoi", in_Scale=6.0); mt.link(pos(mt), vo.inputs["Vector"])
    ramp = mt.n("ShaderNodeValToRGB"); mt.link(vo.outputs["Distance"], ramp.inputs[0])
    ramp.color_ramp.elements[0].color = _hex("#5A534B"); ramp.color_ramp.elements[1].color = _hex("#A79C8D")
    nz = mt.n("ShaderNodeTexNoise", in_Scale=18.0, in_Detail=8.0); mt.link(pos(mt), nz.inputs["Vector"])
    mix = mt.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", in_Factor=0.35)
    mt.link(ramp.outputs[0], mix.inputs[6]); mt.link(nz.outputs["Color"], mix.inputs[7]); mt.link(mix.outputs[2], mt.bsdf.inputs["Base Color"])
    b = mt.n("ShaderNodeBump", in_Strength=1.0, in_Distance=0.03); mt.link(vo.outputs["Distance"], b.inputs["Height"]); mt.link(b.outputs[0], mt.bsdf.inputs["Normal"])
    return mt.m


def mat_noise(name, c1, c2, scale=8.0, rough=0.9, bump=0.2, metal=0.0, spec=0.5):
    mt = M(name).set(**{"Roughness": rough, "Metallic": metal, "Specular IOR Level": spec})
    nz = mt.n("ShaderNodeTexNoise", in_Scale=scale, in_Detail=10.0); mt.link(pos(mt), nz.inputs["Vector"])
    ramp = mt.n("ShaderNodeValToRGB"); mt.link(nz.outputs["Fac"], ramp.inputs[0])
    ramp.color_ramp.elements[0].color = _hex(c1); ramp.color_ramp.elements[1].color = _hex(c2)
    mt.link(ramp.outputs[0], mt.bsdf.inputs["Base Color"])
    b = mt.n("ShaderNodeBump", in_Strength=bump, in_Distance=0.01); mt.link(nz.outputs["Fac"], b.inputs["Height"]); mt.link(b.outputs[0], mt.bsdf.inputs["Normal"])
    return mt.m


def mat_glass():
    mt = M("glass").set(**{"Base Color": _hex("#F4F8FA"), "Roughness": 0.0, "IOR": 1.5, "Transmission Weight": 1.0})
    return mt.m


def mat_emit(name, hexc, strength):
    mt = M(name).set(**{"Base Color": _hex(hexc), "Emission Color": _hex(hexc), "Emission Strength": strength})
    return mt.m


FIN = {}   # finishes in effect for the current job (see apply_finishes)


def mat_image(name, path, size_x, size_y, vec="xz", rough=0.4, bump=0.0, spec=0.5):
    """Tiling image texture placed in world space at real size (size_x by size_y metres per repeat)."""
    mt = M(name).set(**{"Roughness": rough, "Specular IOR Level": spec})
    sep = mt.n("ShaderNodeSeparateXYZ"); mt.link(pos(mt), sep.inputs[0])
    comb = mt.n("ShaderNodeCombineXYZ")
    if vec == "xz":
        add = mt.n("ShaderNodeMath", operation="ADD"); mt.link(sep.outputs["X"], add.inputs[0]); mt.link(sep.outputs["Y"], add.inputs[1])
        u_src, v_src = add.outputs[0], sep.outputs["Z"]
    else:
        u_src, v_src = sep.outputs["X"], sep.outputs["Y"]
    du = mt.n("ShaderNodeMath", operation="DIVIDE", in_1=size_x); mt.link(u_src, du.inputs[0])
    dv = mt.n("ShaderNodeMath", operation="DIVIDE", in_1=size_y); mt.link(v_src, dv.inputs[0])
    mt.link(du.outputs[0], comb.inputs["X"]); mt.link(dv.outputs[0], comb.inputs["Y"])
    tex = mt.n("ShaderNodeTexImage"); tex.image = bpy.data.images.load(str(path), check_existing=True)
    mt.link(comb.outputs[0], tex.inputs["Vector"]); mt.link(tex.outputs["Color"], mt.bsdf.inputs["Base Color"])
    if bump:
        b = mt.n("ShaderNodeBump", in_Strength=bump, in_Distance=0.002); mt.link(tex.outputs["Color"], b.inputs["Height"]); mt.link(b.outputs[0], mt.bsdf.inputs["Normal"])
    return mt.m


def mat_from_spec(name, sp, base_dir):
    t = sp.get("type", "plain")
    if t == "plain":
        return mat_plain(name, sp["hex"], sp.get("rough", 0.6), sp.get("metal", 0.0))
    if t == "noise":
        return mat_noise(name, sp["c1"], sp["c2"], sp.get("scale", 8.0), sp.get("rough", 0.9), sp.get("bump", 0.2), sp.get("metal", 0.0), sp.get("spec", 0.5))
    if t == "brick":
        return mat_brickish(name, sp["mortar"], sp["c1"], sp["c2"], sp["w"], sp["h"], sp.get("mortar_size", 0.004), sp.get("bias", 0.0), sp.get("vec", "xy"),
                            sp.get("rough", 0.6), sp.get("bump", 0.3), sp.get("noise", 40.0), sp.get("spec", 0.5))
    if t == "image":
        return mat_image(name, Path(base_dir) / sp["file"], sp["size_x"], sp["size_y"], sp.get("vec", "xz"), sp.get("rough", 0.4), sp.get("bump", 0.0))
    if t == "speckle":     # granite-style: light base with sharp dark specks
        mt = M(name).set(**{"Roughness": sp.get("rough", 0.15), "Specular IOR Level": sp.get("spec", 0.5)})
        nz = mt.n("ShaderNodeTexNoise", in_Scale=sp.get("scale", 40.0), in_Detail=6.0); mt.link(pos(mt), nz.inputs["Vector"])
        ramp = mt.n("ShaderNodeValToRGB"); mt.link(nz.outputs["Fac"], ramp.inputs[0])
        ramp.color_ramp.elements[0].color = _hex(sp["c1"]); ramp.color_ramp.elements[1].color = _hex(sp["c2"])
        vo = mt.n("ShaderNodeTexVoronoi", in_Scale=sp.get("speck_scale", 90.0)); mt.link(pos(mt), vo.inputs["Vector"])
        th = mt.n("ShaderNodeMath", operation="LESS_THAN", in_1=sp.get("speck_size", 0.12)); mt.link(vo.outputs["Distance"], th.inputs[0])
        mix = mt.n("ShaderNodeMix", data_type="RGBA", blend_type="MIX")
        mt.link(th.outputs[0], mix.inputs[0]); mt.link(ramp.outputs[0], mix.inputs[6]); mix.inputs[7].default_value = _hex(sp["speck"])
        mt.link(mix.outputs[2], mt.bsdf.inputs["Base Color"])
        return mt.m
    if t == "glossy_tile":   # brick pattern with a clear-coat look (zellige / subway)
        m = mat_brickish(name, sp["mortar"], sp["c1"], sp["c2"], sp["w"], sp["h"], sp.get("mortar_size", 0.003), 0.0, sp.get("vec", "xz"), 0.08, sp.get("bump", 0.5), sp.get("noise", 25.0))
        return m
    raise ValueError(f"unknown finish type {t}")


def apply_finishes(mats, fin, base_dir):
    """Finishes from the project's finish schedule: override / add materials by key."""
    global FIN
    FIN = fin or {}
    for key, sp in (FIN.get("materials") or {}).items():
        mats[key] = mat_from_spec(key, sp, base_dir)
    return mats


def build_materials():
    return {
        "siding": mat_siding(),
        "shingle": mat_brickish("shingle", "#242220", "#5A5753", "#423F3B", 0.34, 0.08, mortar=0.004, bias=-0.2, vec="roof", rough=1.0, bump=1.0, spec=0.12),
        "drywall": mat_plain("drywall", "#EDE9E1", 0.92),
        "ceiling": mat_plain("ceiling", "#F4F2EC", 0.95),
        "trim": mat_plain("trim", "#FAFAF7", 0.35),
        "gutter": mat_plain("gutter", "#F3F3F0", 0.3, 0.2),
        "wood_floor": mat_wood_floor(),
        "tile": mat_brickish("tile", "#A7A39B", "#D9D5CD", "#CFCAC1", 0.61, 0.305, mortar=0.004, vec="xy", rough=0.25, bump=0.3),
        "shower_tile": mat_brickish("shower-tile", "#B8B2A8", "#E3DED5", "#D8D2C7", 0.305, 0.076, mortar=0.003, vec="xz", rough=0.15, bump=0.3),
        "brick": mat_brickish("brick", "#B5ADA2", "#8F4E3F", "#7A4134", 0.2, 0.065, mortar=0.01, vec="xz", rough=0.9, bump=0.8),
        "block": mat_brickish("block", "#8F928C", "#B8BAB3", "#ABADA6", 0.406, 0.203, mortar=0.008, vec="xz", rough=0.95, bump=0.6),
        "pavers": mat_brickish("pavers", "#8E8172", "#C9B595", "#B9A383", 0.305, 0.305, mortar=0.006, vec="xy", rough=0.85, bump=0.5),
        "concrete": mat_noise("concrete", "#A39F97", "#BEBAB2", 30, 0.9, 0.05, spec=0.3),
        "asphalt": mat_noise("asphalt", "#262421", "#3E3B37", 60, 1.0, 0.15, spec=0.1),
        "grass": mat_noise("grass", "#344D1F", "#6A8A3E", 1.2, 1.0, 0.4, spec=0.15),
        "deck": mat_brickish("deck", "#3A2C20", "#7F6248", "#6D533C", 2.4, 0.14, mortar=0.004, vec="xy", rough=0.8, bump=0.3),
        "stone": mat_stone(),
        "cabinet": mat_plain("cabinet", "#ECE8DE", 0.35),
        "island": mat_plain("island", "#7F96A6", 0.35),
        "quartz": mat_noise("quartz", "#F1F0EC", "#FBFAF8", 120, 0.12, 0.02),
        "steel": mat_noise("steel", "#B4B8BC", "#CDD1D4", 400, 0.28, 0.02, metal=1.0),
        "porcelain": mat_plain("porcelain", "#FBFBFA", 0.08),
        "fabric": mat_noise("fabric", "#6E7783", "#7F8894", 200, 0.95, 0.05),
        "linen": mat_noise("linen", "#E7E3DA", "#F2EFE8", 150, 0.95, 0.05),
        "walnut": mat_brickish("walnut", "#3A2616", "#6B4A30", "#5A3D27", 1.5, 0.12, mortar=0.0, vec="xy", rough=0.4, bump=0.1),
        "black": mat_plain("black-metal", "#1C1C1C", 0.4, 0.6),
        "glass": mat_glass(),
        "frame": mat_plain("window-frame", "#F7F7F4", 0.4),
        "door": mat_plain("door", "#F4F2EC", 0.35),
        "garage_door": mat_brickish("garage-door", "#C9C9C6", "#F2F2EF", "#F2F2EF", 0.6, 0.53, mortar=0.01, vec="xz", rough=0.35, bump=0.8),
        "bulb": mat_emit("lamp", "#FFE3B8", 18.0),
    }


# ------------------------------------------------------------------ geometry helpers
def faces_by_normal(o, test):
    me = o.data
    R = o.matrix_world.to_3x3()
    return [p.index for p in me.polygons if test((R @ p.normal).normalized(), o.matrix_world @ p.center)]


def assign(o, mats, pick):
    """pick(normal, centre) -> material key; builds slots as needed."""
    o.data.materials.clear()
    slots = {}
    R = o.matrix_world.to_3x3()
    for p in o.data.polygons:
        k = pick((R @ p.normal).normalized(), o.matrix_world @ p.center)
        if k not in slots:
            slots[k] = len(o.data.materials)
            o.data.materials.append(mats[k])
        p.material_index = slots[k]


def box(name, mn, mx, mat, coll):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector([(mn[i] + mx[i]) / 2 + v.co[i] * (mx[i] - mn[i]) for i in range(3)])
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); coll.objects.link(ob); me.materials.append(mat)
    return ob


def sash(o, w, mats, coll, ext=True):
    """Replace a window / glass-door proxy panel with a real frame + glass."""
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
    mx = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
    thin = 0 if (mx.x - mn.x) < (mx.y - mn.y) else 1        # axis through the wall
    run = 1 - thin
    t = w["t"]
    f = 0.06 if t not in ("glassdoor", "french", "slider", "halflite") else 0.09
    d0, d1 = mn[thin] - 0.01, mx[thin] + 0.01
    pieces = []

    def P(a0, a1, z0, z1, mat, inset=0.0):
        lo, hi = [0, 0, 0], [0, 0, 0]
        lo[run], hi[run] = a0, a1
        lo[thin], hi[thin] = d0 + inset, d1 - inset
        lo[2], hi[2] = z0, z1
        pieces.append(box(f"{o.name}-part{len(pieces)}", lo, hi, mats[mat], coll))

    A0, A1, Z0, Z1 = mn[run], mx[run], mn.z, mx.z
    frame = "frame" if ext else "trim"
    door = "door_ext" if (ext and "door_ext" in mats) else "door"
    if t == "overhead":
        P(A0, A1, Z0, Z1, "garage_door", inset=0.015)
    elif t == "panel":
        P(A0, A1, Z0, Z1, door, inset=0.0)
    elif t == "screen":
        P(A0, A0 + 0.04, Z0, Z1, "trim"); P(A1 - 0.04, A1, Z0, Z1, "trim"); P(A0, A1, Z0, Z0 + 0.06, "trim"); P(A0, A1, Z1 - 0.04, Z1, "trim")
    else:
        P(A0, A0 + f, Z0, Z1, frame); P(A1 - f, A1, Z0, Z1, frame)
        P(A0, A1, Z1 - f, Z1, frame); P(A0, A1, Z0, Z0 + f * (1.6 if t in ("glassdoor", "french", "slider", "halflite") else 1.0), frame)
        if t == "dh":
            zm = (Z0 + Z1) / 2; P(A0, A1, zm - 0.035, zm + 0.035, frame)
        if t in ("french", "slider"):
            am = (A0 + A1) / 2; P(am - f / 2, am + f / 2, Z0, Z1, frame)
        gz0 = Z0 + f * 1.6
        if t == "halflite":
            zm = Z0 + (Z1 - Z0) * 0.52; P(A0, A1, Z0, zm, door); gz0 = zm
        P(A0 + f * 0.5, A1 - f * 0.5, gz0, Z1 - f * 0.5, "glass", inset=0.03)
    o.hide_render = True
    return pieces



def _bb(o):
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return (Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb))),
            Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb))))


def cyl(name, x, y, z0, z1, r, mat, coll, verts=24):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r, radius2=r, depth=z1 - z0)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(x, y, (z0 + z1) / 2))
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me); bm.free(); ob = bpy.data.objects.new(name, me); coll.objects.link(ob); me.materials.append(mat); return ob


def cone(name, x, y, z0, z1, r0, r1, mat, coll):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=False, segments=32, radius1=r0, radius2=r1, depth=z1 - z0)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(x, y, (z0 + z1) / 2))
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me); bm.free(); ob = bpy.data.objects.new(name, me); coll.objects.link(ob); me.materials.append(mat)
    ob.modifiers.new("solid", "SOLIDIFY").thickness = 0.004
    return ob


def replace_furnishing(o, gid, mats, coll, ceiling_z):
    """Model a few illustrative pieces properly; returns light positions."""
    mn, mx = _bb(o); cx, cy = (mn.x + mx.x) / 2, (mn.y + mx.y) / 2
    lights = []
    jar = FIN.get("pendants") == "jar"
    if jar and (gid.startswith("LT-ISL") or gid == "LT-DIN"):
        spots = [(cx, cy)]
        z = mn.z if gid.startswith("LT-ISL") else mn.z + 0.25
        if gid == "LT-DIN":                      # a pair along the dining table's long axis
            t = bpy.data.objects.get("D-TABLE")
            if t:
                tm, tx = _bb(t); tcx, tcy = (tm.x + tx.x) / 2, (tm.y + tx.y) / 2
                along_x = (tx.x - tm.x) >= (tx.y - tm.y); d = 0.42
                spots = [(tcx - d, tcy), (tcx + d, tcy)] if along_x else [(tcx, tcy - d), (tcx, tcy + d)]
        metal = mats.get("brass", mats["black"])
        for k, (px, py) in enumerate(spots):
            nm = f"{gid}-jar{k}"
            me = bpy.data.meshes.new(nm); bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
            for v in bm.verts:
                v.co.x *= 0.105; v.co.y *= 0.105; v.co.z = v.co.z * 0.115 + z + 0.115
            for f in bm.faces:
                f.smooth = True
            bm.to_mesh(me); bm.free()
            ob = bpy.data.objects.new(nm, me); coll.objects.link(ob); me.materials.append(mats["glass"])
            cyl(nm + "-cap", px, py, z + 0.215, z + 0.265, 0.03, metal, coll, 20)
            cyl(nm + "-cord", px, py, z + 0.265, ceiling_z, 0.004, mats["black"], coll, 8)
            if "bulb_soft" not in mats:
                mats["bulb_soft"] = mat_emit("lamp-soft", "#FFD9A0", 3.0)
            cyl(nm + "-bulb", px, py, z + 0.08, z + 0.16, 0.012, mats["bulb_soft"], coll, 10)
            ob.location = (px, py, 0)
            lights.append(Vector((px, py, z + 0.12)))
    elif gid.startswith("LT-ISL"):
        z = mn.z
        cone(gid + "-shade", cx, cy, z, z + 0.24, 0.17, 0.05, mats["black"], coll)
        cyl(gid + "-cord", cx, cy, z + 0.24, ceiling_z, 0.004, mats["black"], coll, 8)
        cyl(gid + "-bulb", cx, cy, z + 0.05, z + 0.12, 0.035, mats["bulb"], coll, 12)
        lights.append(Vector((cx, cy, z + 0.02)))
    elif gid == "LT-DIN" and not jar:
        z = mn.z + 0.3
        ring = bpy.data.meshes.new("ring"); bm = bmesh.new()
        bmesh.ops.create_circle(bm, cap_ends=False, segments=48, radius=0.32)
        bmesh.ops.translate(bm, verts=bm.verts, vec=(cx, cy, z)); bm.to_mesh(ring); bm.free()
        rob = bpy.data.objects.new(gid + "-ring", ring); coll.objects.link(rob); ring.materials.append(mats["black"])
        sk = rob.modifiers.new("tube", "SKIN"); rob.modifiers.new("smooth", "SUBSURF").levels = 1
        for v in rob.data.skin_vertices[0].data:
            v.radius = (0.008, 0.008)
        for k in range(6):
            a = k * math.pi / 3
            cyl(f"{gid}-bulb{k}", cx + 0.32 * math.cos(a), cy + 0.32 * math.sin(a), z + 0.01, z + 0.08, 0.022, mats["bulb"], coll, 10)
        cyl(gid + "-rod", cx, cy, z, ceiling_z, 0.006, mats["black"], coll, 8)
        lights.append(Vector((cx, cy, z + 0.05)))
    elif gid.startswith("K-STOOL"):
        h = 0.66
        cyl(gid + "-seat", cx, cy, h - 0.04, h, 0.19, mats["walnut"], coll)
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            cyl(gid + "-leg", cx + dx * 0.12, cy + dy * 0.12, mn.z, h - 0.04, 0.014, mats["black"], coll, 8)
        cyl(gid + "-ring", cx, cy, 0.25, 0.27, 0.15, mats["black"], coll)
    elif gid.startswith("D-CHAIR"):
        T = Vector((39.45 * FT, 27.5 * FT))                    # dining table centre: chairs face it
        d = (T - Vector((cx, cy))); facex = abs(d.x) > abs(d.y)
        sw = 0.44
        box(gid + "-seat", (cx - sw / 2, cy - sw / 2, 0.43), (cx + sw / 2, cy + sw / 2, 0.47), mats["walnut"], coll)
        for dx in (-1, 1):
            for dy in (-1, 1):
                box(gid + "-leg", (cx + dx * 0.19 - 0.02, cy + dy * 0.19 - 0.02, 0), (cx + dx * 0.19 + 0.02, cy + dy * 0.19 + 0.02, 0.43), mats["walnut"], coll)
        if facex:
            bx = cx - math.copysign(sw / 2 - 0.02, d.x)
            box(gid + "-back", (bx - 0.02, cy - sw / 2, 0.47), (bx + 0.02, cy + sw / 2, 0.92), mats["walnut"], coll)
        else:
            by = cy - math.copysign(sw / 2 - 0.02, d.y)
            box(gid + "-back", (cx - sw / 2, by - 0.02, 0.47), (cx + sw / 2, by + 0.02, 0.92), mats["walnut"], coll)
    elif gid == "D-TABLE":
        box(gid + "-top", (mn.x, mn.y, 0.72), (mx.x, mx.y, 0.76), mats["walnut"], coll)
        for x in (mn.x + 0.08, mx.x - 0.14):
            for y in (mn.y + 0.08, mx.y - 0.14):
                box(gid + "-leg", (x, y, 0), (x + 0.06, y + 0.06, 0.72), mats["walnut"], coll)
    else:
        return None
    o.hide_render = True
    return lights

# ------------------------------------------------------------------ scene
def build(glb, genome, site, mats, finishes=None, base_dir="."):
    bpy.ops.import_scene.gltf(filepath=str(glb))
    apply_finishes(mats, finishes, base_dir)
    cfg = render_cfg(genome)
    coll = bpy.context.scene.collection
    E = genome["elements"]
    lights = []
    for o in list(bpy.data.objects):
        if o.type != "MESH":
            continue
        gid = o.get("genome_id", o.name)
        typ = o.get("type", "")
        base = gid.replace("#fill", "")
        fin = cfg["fin"].get(gid)
        kind = cfg["kind"].get(gid, "")
        if typ == "space":
            bpy.data.objects.remove(o); continue
        if gid in {c["id"] for c in (FIN.get("cabinets") or [])}:
            continue                              # rebuilt as shaker casework after this loop
        nd = (FIN.get("nudge") or {}).get(gid)
        if nd:                                    # grow an element a few mm so it doesn't share faces with what it sits in
            mw = o.matrix_world; inv = mw.inverted()
            ws = [mw @ v.co for v in o.data.vertices]
            c = sum(ws, Vector()) / max(1, len(ws))
            for v, w in zip(o.data.vertices, ws):
                v.co = inv @ Vector([w[i] + (nd if w[i] > c[i] else -nd) for i in range(3)])
        ov = (FIN.get("by_id") or {}).get(gid)
        if ov:                                    # finish schedule wins: whole element, or body + top
            if isinstance(ov, str):
                assign(o, mats, lambda n, c, k=ov: k)
            else:
                assign(o, mats, lambda n, c, b=ov["body"], t=ov.get("top", ov["body"]): t if n.z > 0.9 else b)
            continue
        if typ == "wall":
            out = cfg["siding"].get(gid)
            if out:
                N = Vector((out[0], -out[1], 0))
                assign(o, mats, lambda n, c: "siding" if abs(n.z) < 0.3 and n.dot(N) > 0.9 else "drywall")
            else:
                assign(o, mats, lambda n, c: "drywall")
            continue
        if typ == "roof":
            assign(o, mats, lambda n, c: "shingle" if n.z > 0.3 else ("ceiling" if n.z < -0.3 else "trim"))
            continue
        if typ == "slab":
            k = {"S1-PAT": "pavers", "S-WALK": "concrete", "S1-FP": "concrete", "S1-GAR": "concrete", "S1-SP": "deck"}.get(gid, "wood_floor")
            assign(o, mats, lambda n, c, k=k: k if n.z > 0.9 else ("ceiling" if n.z < -0.9 else "trim"))
            continue
        if typ == "filling":
            opn = E.get(base, {}); host = E.get(opn.get("host", ""), {})
            if opn.get("kind") == "door" and not host.get("exterior") and FIN.get("open_interior_doors", True):
                o.hide_render = True; continue        # interior doors shown open (clear doorway), as in the walk-through
        if typ == "filling" and base in cfg["win"]:
            host = E.get(E.get(base, {}).get("host", ""), {})
            sash(o, cfg["win"][base], mats, coll, ext=bool(host.get("exterior", True))); continue
        # components
        if gid.startswith("FL-"):
            k = "tile" if fin == "fin-floor-tile" else "wood_floor"
            assign(o, mats, lambda n, c, k=k: k); continue
        if gid.startswith("FDN-"):
            assign(o, mats, lambda n, c: "block"); continue
        if kind == "chimney":
            assign(o, mats, lambda n, c: "brick"); continue
        k = {"fin-stone": "stone", "fin-steel": "steel", "fin-tile": "shower_tile", "fin-white": "porcelain", "fin-sofa": "fabric",
             "fin-bed": "linen", "fin-wood": "walnut", "fin-black": "black", "fin-gutter": "gutter", "fin-trimw": "trim",
             "fin-post": "trim", "fin-walk": "concrete", "fin-island": "island", "fin-cab": "cabinet"}.get(fin)
        if fin in ("fin-cab", "fin-island") and not any(gid.startswith(p) for p in ("P-SHELF", "K-UPPERS", "K-TALL", "M-LOCK")):
            assign(o, mats, lambda n, c, k=k: "quartz" if n.z > 0.9 else k); continue
        if gid.startswith(("LT-", "K-STOOL", "D-CHAIR", "D-TABLE")):
            r = replace_furnishing(o, gid, mats, coll, 9 * FT)
            if r is not None:
                lights += r
                continue
        if k:
            assign(o, mats, lambda n, c, k=k: k); continue
    if FIN.get("cabinets"):
        shaker_cabinets(FIN["cabinets"], mats, coll)
    bs = FIN.get("backsplash")
    if bs and bs.get("material") in mats:
        backsplash(bs, mats, coll)
    # interior lights: pendants / chandelier + recessed cans in the main rooms (E-101 intent)
    for p in lights:
        L = bpy.data.lights.new("pendant", "POINT"); L.energy = 40; L.color = (1.0, 0.86, 0.68); L.shadow_soft_size = 0.08
        ob = bpy.data.objects.new("pendant", L); ob.location = p; coll.objects.link(ob)
    for e in E.values():
        if e["type"] != "space" or e["storey"] not in ("1F", "2F"):
            continue
        nm = e["name"].lower()
        if any(x in nm for x in ("garage", "porch", "closet", "stair")):
            continue
        xs = [q[0] for q in e["boundary"]]; ys = [q[1] for q in e["boundary"]]
        z = (0 if e["storey"] == "1F" else 10 * FT) + e["height"]["value"] - 0.05
        L = bpy.data.lights.new("room", "AREA"); L.energy = 45 * max(1.0, (max(xs) - min(xs)) * (max(ys) - min(ys)) / 12)
        L.size = 0.6; L.color = (1.0, 0.9, 0.78)
        ob = bpy.data.objects.new("room-light", L); ob.location = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, z); coll.objects.link(ob)
    # site: grass, driveway, road
    g = site.get("grade", -0.457)
    bpy.ops.mesh.primitive_plane_add(size=400, location=(26 * FT * 0 + 15, 10, g - 0.01)); bpy.context.object.data.materials.append(mats["grass"])
    for key, mk, dz in (("drive", "asphalt", 0.012), ("road", "asphalt", 0.01)):
        if site.get(key):
            me = bpy.data.meshes.new(key); bm = bmesh.new()
            vs = [bm.verts.new((x, y, g + dz)) for x, y in site[key]]
            bm.faces.new(vs); bm.to_mesh(me); bm.free()
            ob = bpy.data.objects.new(key, me); coll.objects.link(ob); me.materials.append(mats[mk])


# ------------------------------------------------------------------ shaker casework (finishes "cabinets")
class _Frame:
    """Local frame of a casework element: a = along the run, d = depth measured from the back (wall) toward the front."""

    def __init__(self, mn, mx, front):
        self.t = 0 if front[1] == "x" else 1
        self.ax = 1 - self.t
        self.s = -1 if front[0] == "-" else 1
        self.back = mx[self.t] if self.s == -1 else mn[self.t]
        self.D = mx[self.t] - mn[self.t]
        self.mn, self.mx = mn, mx

    def box(self, name, a0, a1, d0, d1, z0, z1, mat, coll):
        lo, hi = [0, 0, 0], [0, 0, 0]
        lo[self.ax], hi[self.ax] = min(a0, a1), max(a0, a1)
        p0, p1 = self.back + self.s * d0, self.back + self.s * d1
        lo[self.t], hi[self.t] = min(p0, p1), max(p0, p1)
        lo[2], hi[2] = z0, z1
        return box(name, lo, hi, mat, coll)

    def point(self, a, d, z):
        v = [0.0, 0.0, z]; v[self.ax] = a; v[self.t] = self.back + self.s * d
        return Vector(v)


def _shaker(F, nm, a0, a1, z0, z1, D, mat, coll, rail=0.057):
    """Shaker front: recessed centre panel inside a 2-1/4 in frame (3/4 in thick)."""
    F.box(nm + "-panel", a0, a1, D - 0.019, D - 0.006, z0, z1, mat, coll)
    r = min(rail, (a1 - a0) / 4, (z1 - z0) / 4)
    F.box(nm + "-stileL", a0, a0 + r, D - 0.019, D, z0, z1, mat, coll)
    F.box(nm + "-stileR", a1 - r, a1, D - 0.019, D, z0, z1, mat, coll)
    F.box(nm + "-railB", a0 + r, a1 - r, D - 0.019, D, z0, z0 + r, mat, coll)
    F.box(nm + "-railT", a0 + r, a1 - r, D - 0.019, D, z1 - r, z1, mat, coll)


def _slab(F, nm, a0, a1, z0, z1, D, mat, coll):
    F.box(nm + "-slab", a0, a1, D - 0.019, D, z0, z1, mat, coll)


def _pull(F, nm, ac, zc, D, metal, coll, length=0.16):
    F.box(nm + "-bar", ac - length / 2, ac + length / 2, D + 0.024, D + 0.036, zc - 0.006, zc + 0.006, metal, coll)
    for k in (-1, 1):
        F.box(nm + f"-post{k}", ac + k * 0.064 - 0.005, ac + k * 0.064 + 0.005, D, D + 0.026, zc - 0.005, zc + 0.005, metal, coll)


def _knob(F, nm, ac, zc, D, metal, coll):
    me = bpy.data.meshes.new(nm); bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.015)
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(nm, me); coll.objects.link(ob); me.materials.append(metal)
    ob.location = F.point(ac, D + 0.03, zc)
    F.box(nm + "-post", ac - 0.005, ac + 0.005, D, D + 0.02, zc - 0.005, zc + 0.005, metal, coll)


def _units(a0, a1, target=0.762):
    n = max(1, round((a1 - a0) / target)); w = (a1 - a0) / n
    return [(a0 + i * w, a0 + (i + 1) * w) for i in range(n)]


def _segments(a0, a1, skips):
    segs, cur = [], a0
    for s0, s1 in sorted(skips):
        if s0 > cur + 0.05:
            segs.append((cur, min(s0, a1)))
        cur = max(cur, s1)
    if a1 > cur + 0.05:
        segs.append((cur, a1))
    return segs


def _base_unit(F, nm, u0, u1, D, H, body, metal, coll, drawer=True, gap=0.003):
    """Base cabinet: carcass + toe kick + top drawer + 1-2 doors with knobs."""
    F.box(nm + "-case", u0, u1, 0.0, D - 0.019, 0.10, H, body, coll)
    F.box(nm + "-toe", u0, u1, 0.0, D - 0.075, 0.0, 0.10, body, coll)
    top = H - gap
    if drawer:
        dz0 = top - 0.15
        _shaker(F, nm + "-dr", u0 + gap, u1 - gap, dz0, top, D, body, coll, rail=0.045)
        _pull(F, nm + "-drp", (u0 + u1) / 2, (dz0 + top) / 2, D, metal, coll)
        top = dz0 - 2 * gap
    w = u1 - u0
    doors = [(u0, u1)] if w < 0.62 else [(u0, (u0 + u1) / 2), ((u0 + u1) / 2, u1)]
    for k, (d0, d1) in enumerate(doors):
        _shaker(F, f"{nm}-door{k}", d0 + gap, d1 - gap, 0.10 + gap, top, D, body, coll)
        hinge_left = (k == 1) if len(doors) == 2 else True
        ka = d0 + 0.045 if hinge_left else d1 - 0.045
        if len(doors) == 2:
            ka = d0 + 0.045 if k == 1 else d1 - 0.045
        _knob(F, f"{nm}-knob{k}", ka, top - 0.06, D, metal, coll)


def shaker_cabinets(specs, mats, coll):
    """Replace casework boxes with shaker cabinetry + counters + hardware, per the finish schedule."""
    metal = mats.get("brass", mats["black"])
    for sp in specs:
        o = bpy.data.objects.get(sp["id"])
        if not o:
            continue
        mn, mx = _bb(o)
        o.hide_render = True
        F = _Frame(mn, mx, sp["front"])
        A0, A1 = mn[F.ax], mx[F.ax]
        body = mats[sp.get("material", "cabinet")]
        top_mat = mats[sp.get("top", "quartz")]
        kind, nm = sp["kind"], sp["id"]
        skips = [(a * FT, b * FT) for a, b in sp.get("skip", [])]
        if kind in ("base", "vanity"):
            D = F.D; H = mx.z - mn.z - 0.032
            for si, (s0, s1) in enumerate(_segments(A0, A1, skips)):
                for ui, (u0, u1) in enumerate(_units(s0, s1, sp.get("unit", 0.762))):
                    _base_unit(F, f"{nm}-s{si}u{ui}", u0, u1, D, H, body, metal, coll, drawer=sp.get("drawers", True))
                F.box(f"{nm}-top{si}", s0, s1, 0.0, D + 0.025, H, H + 0.032, top_mat, coll)
        elif kind == "wall":
            D = F.D; z0, z1 = mn.z, mx.z
            for si, (s0, s1) in enumerate(_segments(A0, A1, skips)):
                for ui, (u0, u1) in enumerate(_units(s0, s1, 0.762)):
                    F.box(f"{nm}-s{si}u{ui}-case", u0, u1, 0.0, D - 0.019, z0, z1, body, coll)
                    w = u1 - u0
                    doors = [(u0, u1)] if w < 0.62 else [(u0, (u0 + u1) / 2), ((u0 + u1) / 2, u1)]
                    for k, (d0, d1) in enumerate(doors):
                        _shaker(F, f"{nm}-s{si}u{ui}-door{k}", d0 + 0.003, d1 - 0.003, z0 + 0.003, z1 - 0.003, D, body, coll)
                        ka = (d1 - 0.045) if (len(doors) == 1 or k == 0) else (d0 + 0.045)
                        _knob(F, f"{nm}-s{si}u{ui}-knob{k}", ka, z0 + 0.07, D, metal, coll)
        elif kind == "island":
            Dc = sp.get("cab_depth", 0.76); D = F.D; H = mx.z - mn.z - 0.032
            Fc = _Frame(mn, mx, sp["front"])        # cabinets sit on the front side; seating overhang behind
            Fc.back = (mn[Fc.t] + (D - Dc)) if Fc.s == 1 else (mx[Fc.t] - (D - Dc))
            mid = (A0 + A1) / 2; sink_w, dw_w = 0.914, 0.61
            sink = (mid - sink_w / 2, mid + sink_w / 2); dw = (sink[1], sink[1] + dw_w)
            for k, (u0, u1) in enumerate(_units(A0, sink[0], 0.762)):
                _base_unit(Fc, f"{nm}-L{k}", u0, u1, Dc, H, body, metal, coll)
            _base_unit(Fc, f"{nm}-sink", sink[0], sink[1], Dc, H, body, metal, coll, drawer=False)
            Fc.box(f"{nm}-dw-case", dw[0], dw[1], 0.0, Dc - 0.019, 0.10, H, body, coll)
            Fc.box(f"{nm}-dw", dw[0] + 0.003, dw[1] - 0.003, Dc - 0.019, Dc, 0.10, H - 0.003, mats.get("appliance_white", body), coll)
            _pull(Fc, f"{nm}-dwp", (dw[0] + dw[1]) / 2, H - 0.06, Dc, metal, coll, length=0.45)
            for k, (u0, u1) in enumerate(_units(dw[1], A1, 0.762)):
                _base_unit(Fc, f"{nm}-R{k}", u0, u1, Dc, H, body, metal, coll)
            # finished back panel on the seating side
            Fc.box(f"{nm}-backpanel", A0, A1, -0.019, 0.0, 0.0, H, body, coll)
            F.box(f"{nm}-top", A0 - 0.02, A1 + 0.02, 0.0, D + 0.025, H, H + 0.032, top_mat, coll)
            # undermount sink + faucet
            steel = mats.get("steel", mats["black"])
            F.box(f"{nm}-sinkbowl", mid - 0.38, mid + 0.38, D - 0.53, D - 0.08, H + 0.0325, H + 0.0335, steel, coll)
            fz = H + 0.032
            fp = F.point(mid, D - 0.60, 0.0)
            cyl(f"{nm}-faucet", fp.x, fp.y, fz, fz + 0.40, 0.014, metal, coll, 16)
            F.box(f"{nm}-spout", mid - 0.012, mid + 0.012, D - 0.60, D - 0.38, fz + 0.37, fz + 0.40, metal, coll)
        elif kind == "range":              # Cafe-style slide-in: white body, black glass top + window, brass handle and knobs
            D = F.D; H = mx.z - mn.z; app = mats.get("appliance_white", body); blk = mats["black"]
            F.box(nm + "-body", A0 + 0.003, A1 - 0.003, 0.0, D + 0.01, 0.0, H, app, coll)
            F.box(nm + "-cooktop", A0 + 0.01, A1 - 0.01, 0.03, D + 0.0, H, H + 0.006, blk, coll)
            F.box(nm + "-window", A0 + 0.09, A1 - 0.09, D + 0.01, D + 0.014, 0.25, 0.62, blk, coll)
            _pull(F, nm + "-handle", (A0 + A1) / 2, 0.70, D + 0.01, metal, coll, length=(A1 - A0) - 0.12)
            for k in range(5):
                _knob(F, f"{nm}-k{k}", A0 + (A1 - A0) * (k + 1) / 6, H - 0.05, D + 0.01, metal, coll)
        elif kind == "fridge":             # French-door fridge: two doors + freezer drawer, brass bar handles
            D = F.D; z1 = mx.z; app = mats.get("appliance_white", body); blk = mats["black"]
            mid = (A0 + A1) / 2; zf = 0.80
            F.box(nm + "-body", A0, A1, 0.0, D, 0.0, z1, app, coll)
            F.box(nm + "-seam", mid - 0.002, mid + 0.002, D, D + 0.002, zf, z1 - 0.02, blk, coll)
            F.box(nm + "-seamF", A0 + 0.01, A1 - 0.01, D, D + 0.002, zf - 0.004, zf, blk, coll)
            for k, a in enumerate((mid - 0.05, mid + 0.05)):
                F.box(f"{nm}-h{k}", a - 0.007, a + 0.007, D + 0.026, D + 0.04, zf + 0.25, zf + 0.95, metal, coll)
                for zz in (zf + 0.27, zf + 0.93):
                    F.box(f"{nm}-h{k}p{zz:.2f}", a - 0.005, a + 0.005, D, D + 0.028, zz - 0.005, zz + 0.005, metal, coll)
            _pull(F, nm + "-fz", mid, zf - 0.07, D, metal, coll, length=0.55)
        elif kind == "tall":
            D = F.D; z0, z1 = mn.z, mx.z
            for u in sp["units"]:
                u0, u1 = u["a"][0] * FT, u["a"][1] * FT; t = u["type"]; un = f"{nm}-{t}{u0:.2f}"
                F.box(un + "-case", u0, u1, 0.0, D - 0.019 if t != "filler" else D, z0, z1, body, coll)
                if t == "filler":
                    continue
                if t == "bridge":          # cabinet above the fridge
                    zb = u["z0"] * FT
                    _shaker(F, un + "-door", u0 + 0.003, u1 - 0.003, zb + 0.003, z1 - 0.003, D, body, coll)
                    _knob(F, un + "-knob", (u0 + u1) / 2, zb + 0.06, D, metal, coll)
                elif t == "oven":
                    zo0, zo1 = 0.86, 1.56
                    _shaker(F, un + "-drw1", u0 + 0.003, u1 - 0.003, 0.10, 0.47, D, body, coll, rail=0.05)
                    _pull(F, un + "-p1", (u0 + u1) / 2, 0.40, D, metal, coll)
                    _shaker(F, un + "-drw2", u0 + 0.003, u1 - 0.003, 0.48, zo0 - 0.003, D, body, coll, rail=0.05)
                    _pull(F, un + "-p2", (u0 + u1) / 2, zo0 - 0.07, D, metal, coll)
                    app = mats.get("appliance_white", body)
                    F.box(un + "-oven", u0 + 0.01, u1 - 0.01, D - 0.019, D + 0.004, zo0, zo1, app, coll)
                    F.box(un + "-glass", u0 + 0.07, u1 - 0.07, D, D + 0.006, zo0 + 0.08, zo1 - 0.16, mats["black"], coll)
                    _pull(F, un + "-ovp", (u0 + u1) / 2, zo1 - 0.08, D + 0.004, metal, coll, length=0.5)
                    _shaker(F, un + "-up", u0 + 0.003, u1 - 0.003, zo1 + 0.003, z1 - 0.003, D, body, coll)
                    _knob(F, un + "-upk", u1 - 0.045, zo1 + 0.07, D, metal, coll)
                else:                      # tall pantry: two stacked doors
                    zm = 1.45
                    _shaker(F, un + "-lo", u0 + 0.003, u1 - 0.003, 0.10, zm, D, body, coll)
                    _shaker(F, un + "-hi", u0 + 0.003, u1 - 0.003, zm + 0.006, z1 - 0.003, D, body, coll)
                    _knob(F, un + "-k1", u0 + 0.045, zm - 0.08, D, metal, coll)
                    _knob(F, un + "-k2", u0 + 0.045, zm + 0.09, D, metal, coll)


def backsplash(bs, mats, coll):
    """Tile panel on the wall behind a base-cabinet run, from the counter up to the wall cabinets."""
    run, up = bpy.data.objects.get(bs["run"]), bpy.data.objects.get(bs.get("uppers", ""))
    if not run:
        return
    rm, rx = _bb(run)
    um, ux = _bb(up) if up else (rm, rx)
    thin = 0 if (rx.x - rm.x) < (rx.y - rm.y) else 1           # depth axis of the run
    wall_at_min = abs(rm[thin] - um[thin]) < abs(rx[thin] - ux[thin])
    face = (rm[thin] if wall_at_min else rx[thin])
    d0, d1 = (face, face + 0.006) if wall_at_min else (face - 0.006, face)
    z0 = rx.z + 0.002
    z1 = um.z - 0.002 if up and um.z > z0 + 0.2 else z0 + bs.get("height", 0.457)
    lo, hi = [0, 0, 0], [0, 0, 0]
    a = 1 - thin
    lo[a], hi[a] = rm[a], rx[a]; lo[thin], hi[thin] = d0, d1; lo[2], hi[2] = z0, z1
    box("BACKSPLASH", lo, hi, mats[bs["material"]], coll)


def use_gpu(prefer=("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")):
    """Switch Cycles to the best GPU backend available (RTX cards: OptiX). Returns the backend, or None for CPU."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        return None
    for kind in prefer:
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        devs = [d for d in prefs.devices if d.type == kind]
        if devs:
            for d in prefs.devices:
                d.use = d.type == kind
            bpy.context.scene.cycles.device = "GPU"
            print("GPU:", kind, ", ".join(d.name for d in devs), flush=True)
            return kind
    print("GPU: none found, rendering on CPU", flush=True)
    return None


def setup_render(samples, scale, sun_az, sun_el, gpu=False):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"; sc.cycles.device = "CPU"; sc.cycles.samples = samples
    sc.cycles.use_denoising = True; sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.cycles.use_adaptive_sampling = True; sc.cycles.adaptive_threshold = 0.02
    if gpu:
        use_gpu()
    sc.cycles.max_bounces = 8; sc.cycles.diffuse_bounces = 4; sc.cycles.glossy_bounces = 3; sc.cycles.transmission_bounces = 8
    sc.cycles.caustics_reflective = False; sc.cycles.caustics_refractive = False; sc.cycles.light_sampling_threshold = 0.01
    sc.render.resolution_percentage = int(scale * 100)
    sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "AgX - Medium High Contrast"
    w = bpy.data.worlds.new("sky"); sc.world = w; w.use_nodes = True
    nt = w.node_tree; bg = nt.nodes["Background"]
    sky = nt.nodes.new("ShaderNodeTexSky"); sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation = math.radians(sun_el); sky.sun_rotation = math.radians(sun_az)
    try:
        sky.sun_disc = False
    except Exception:
        pass
    nt.links.new(sky.outputs[0], bg.inputs[0]); bg.inputs[1].default_value = 0.35
    sun = bpy.data.lights.new("sun", "SUN"); sun.energy = 3.2; sun.angle = math.radians(0.6); sun.color = (1.0, 0.95, 0.88)
    so = bpy.data.objects.new("sun", sun); sc.collection.objects.link(so)
    a, e = math.radians(sun_az), math.radians(sun_el)       # compass azimuth (clockwise from north), elevation
    to_sun = Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))
    so.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler()


def shoot(shots, out_dir):
    sc = bpy.context.scene
    done = []
    for s in shots:
        cam = bpy.data.cameras.new(s["name"]); cam.lens = s.get("lens", 24); cam.sensor_width = 36
        co = bpy.data.objects.new(s["name"], cam); sc.collection.objects.link(co)
        co.location = Vector([v * FT for v in s["eye"]])
        if s.get("pano"):
            # 360° equirectangular: image centre = north, east to the right, zenith at the top
            cam.type = "PANO"
            try:
                cam.panorama_type = "EQUIRECTANGULAR"
            except Exception:
                cam.cycles.panorama_type = "EQUIRECTANGULAR"
            cam.clip_start = 0.05
            co.rotation_euler = (math.pi / 2, 0, 0)
        else:
            d = Vector([v * FT for v in s["look"]]) - co.location
            co.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        sc.camera = co
        sc.render.resolution_x, sc.render.resolution_y = s.get("res", (1600, 900))
        if "samples" in s:
            sc.cycles.samples = s["samples"]
        if s.get("pano"):
            sc.render.image_settings.file_format = "JPEG"; sc.render.image_settings.quality = 90
            sc.render.filepath = str(Path(out_dir) / f"{s['name']}.jpg")
        else:
            sc.render.image_settings.file_format = "PNG"
            sc.render.filepath = str(Path(out_dir) / f"{s['name']}.png")
        t = time.time(); bpy.ops.render.render(write_still=True)
        print(f"rendered {s['name']} in {time.time() - t:.0f}s", flush=True)
        done.append(sc.render.filepath)
    return done


def main(argv):
    glb, genome, site, shots, out = argv[:5]
    samples = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 96
    scale = float(argv[argv.index("--scale") + 1]) if "--scale" in argv else 1.0
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None
    run(glb, genome, site, json.loads(Path(shots).read_text()), out, samples, scale, only, gpu="--gpu" in argv)


def run(glb, genome, site, S, out, samples=96, scale=1.0, only=None, gpu=False, finishes=None):
    """One render job: build the scene from the model and shoot the requested views.
    finishes: optional path to the project's finishes.json (materials + per-element overrides)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = build_materials()
    fin = json.loads(Path(finishes).read_text()) if finishes and Path(finishes).exists() else None
    build(glb, json.loads(Path(genome).read_text()), json.loads(Path(site).read_text()), mats, fin, Path(finishes).parent if finishes else ".")
    setup_render(samples, scale, S.get("sun_azimuth", 235), S.get("sun_elevation", 38), gpu=gpu)
    Path(out).mkdir(parents=True, exist_ok=True)
    return shoot([s for s in S["shots"] if not only or s["name"] in only], out)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[a.index("--") + 1:] if "--" in a else a)
