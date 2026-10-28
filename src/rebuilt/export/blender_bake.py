"""Bake the Cycles look into the model, for a free walk-through that looks like the renders.

    blender -b --factory-startup -P render_server.py   (job kind "bake")   or
    python3 -m rebuilt.export.blender_bake MODEL.glb GENOME.json SITE.json PRESET.json OUT_DIR [--gpu]

The scene is built exactly as for the stills (blender_render.build: same materials, sash frames, furniture, lights,
sky and sun). Every opaque surface is then unwrapped into a few texture atlases and two things are baked per atlas:

  color_<i>.jpg   the surface colour (all the procedural materials: siding laps, plank floors, brick, stone ...)
  light_<i>.png   the light arriving at the surface (sun, sky, room lights, bounce light), path-traced, at a coarser
                  resolution; stored as sRGB-encoded (light * k[i]) so 8 bits keep the precision where it matters

The viewer multiplies the two (colour x light / k), so it shows the path-traced lighting while moving freely.
Glass and lamp bulbs are not baked; the viewer draws them itself. Interior door panels are left out so the
walker can pass through doorways.

Outputs in OUT_DIR: scene.glb (geometry, atlas UVs, extras: genome_id/type/storey + bake atlas index or mat),
color_*.jpg, light_*.png, bake.json.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np

from . import blender_render as BR
from .render import render_cfg

PRESET = {"sun_azimuth": 285, "sun_elevation": 30, "color_res": 4096, "texel_cm": 1.0, "light_div": 2,
          "light_samples": 768, "color_samples": 4, "site_half_m": 60.0, "light_smooth": 1.0}


def log(*a):
    print(*a, flush=True)


def _select(objs, active=None):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or objs[0]


def prep(genome, site_half):
    """Real geometry only: drop proxies, open interior doorways, apply modifiers + transforms, trim the lawn."""
    cfg = render_cfg(genome)
    E = genome["elements"]
    hide = set()
    for e in E.values():   # same rule as the walk-through: interior door leaves + screens are not drawn
        if e["type"] == "opening" and e.get("filling"):
            op = (e["filling"].get("operation") or "").lower()
            if (e["kind"] == "door" and not E[e["host"]].get("exterior")) or "screen" in op:
                hide.add(e["id"])
    for o in list(bpy.data.objects):
        if o.type != "MESH":
            if o.type in ("EMPTY", "CAMERA"):
                bpy.data.objects.remove(o)
            continue
        gid = o.get("genome_id", o.name)
        owner = o.name.split("#fill")[0]          # sash / door-leaf parts are named "<opening id>#fill-partN"
        if "#fill-part" in o.name and owner in hide:
            bpy.data.objects.remove(o); continue
        if o.hide_render or (o.get("type") == "filling" and gid.replace("#fill", "") in hide and gid.replace("#fill", "") not in cfg["win"]):
            bpy.data.objects.remove(o)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    _select(meshes)
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.make_single_user(object=True, obdata=True)
    bpy.ops.object.convert(target="MESH")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in meshes:                                   # the 400 m lawn -> a patch around the house
        if o.data.materials and o.data.materials[0].name.startswith("grass"):
            for v in o.data.vertices:
                v.co.x = max(-site_half, min(site_half, v.co.x - 15)) + 15
                v.co.y = max(-site_half, min(site_half, v.co.y - 10)) + 10
            o.name = "SITE-lawn"
    return meshes


def kind_of(o):
    names = {m.name.split(".")[0] for m in o.data.materials if m}
    if names and names <= {"glass"}:
        return "glass"
    if any(n.startswith("lamp") for n in names):
        return "lamp"
    return "bake"


def area(o):
    return sum(p.area for p in o.data.polygons)


def groups_for(objs, res, texel_m, eff=0.55):
    """Split objects into atlases so each keeps about texel_m per texel."""
    cap = (res * texel_m) ** 2 * eff
    tot = sum(area(o) for o in objs)
    n = max(1, math.ceil(tot / cap))
    bins = [[] for _ in range(n)]; load = [0.0] * n
    for o in sorted(objs, key=area, reverse=True):
        i = load.index(min(load)); bins[i].append(o); load[i] += area(o)
    return bins, load


def unwrap(objs, margin):
    for o in objs:
        for uv in list(o.data.uv_layers):
            o.data.uv_layers.remove(uv)
        o.data.uv_layers.new(name="bake")
    _select(objs)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.0, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.average_islands_scale()

    def pack(m):
        bpy.ops.uv.select_all(action="SELECT")
        try:
            bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=True, margin_method="FRACTION", margin=m, shape_method="AABB")
        except TypeError:
            bpy.ops.uv.pack_islands(rotate=True, margin=m)
        bpy.ops.object.mode_set(mode="OBJECT")
        e = max(float(_uvs(o).max()) for o in objs if len(o.data.loops))
        return e

    # Blender's multi-object pack can overshoot the unit square: re-pack with the margin scaled up, then shrink to fit
    ext = pack(margin)
    if ext > 1.001:
        bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
        ext = pack(margin * ext)
    if ext > 1.0:
        for o in objs:
            uv = _uvs(o) / ext
            o.data.uv_layers["bake"].data.foreach_set("uv", uv.ravel())
    log(f"  unwrapped {len(objs)} objects (pack extent {ext:.2f})")


def _uvs(o):
    a = np.empty(len(o.data.loops) * 2, np.float32)
    o.data.uv_layers["bake"].data.foreach_get("uv", a)
    return a.reshape(-1, 2)


def _bake_target(objs, img):
    """Point every material on these objects at img (the active Image Texture node is the bake target)."""
    for m in {m for o in objs for m in o.data.materials if m}:
        nt = m.node_tree
        node = nt.nodes.get("__bake__") or nt.nodes.new("ShaderNodeTexImage")
        node.name = "__bake__"; node.image = img
        for n in nt.nodes:
            n.select = False
        node.select = True; nt.nodes.active = node


def merged_copy(objs):
    """One joined duplicate of an atlas group (Cycles bakes one object far faster than hundreds).
    The originals are hidden from rendering while the copy stands in for them."""
    _select(objs)
    bpy.ops.object.duplicate()
    dup = list(bpy.context.selected_objects)
    bpy.context.view_layer.objects.active = dup[0]
    if len(dup) > 1:
        bpy.ops.object.join()
    m = bpy.context.view_layer.objects.active
    m.name = "__bake_merged__"
    for o in objs:
        o.hide_render = True
    return m


def drop_merged(m, objs):
    bpy.data.objects.remove(m)
    for o in objs:
        o.hide_render = False


def bake_pass(objs, img, kind, samples, margin):
    sc = bpy.context.scene
    sc.cycles.samples = samples
    sc.render.bake.margin = margin
    sc.render.bake.use_clear = True
    _bake_target(objs, img)
    _select(objs)
    t = time.time()
    if kind == "color":
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, uv_layer="bake", margin=margin, use_clear=True)
    else:
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"}, uv_layer="bake", margin=margin, use_clear=True)
    return time.time() - t


def srgb_encode(x):
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(np.maximum(x, 0), 1 / 2.4) - 0.055)


def fill_holes(img, iters=4):
    """Texels no face reached (thin trim, sub-texel faces, island edges) take the mean of baked neighbours."""
    m = img.max(axis=2) > 1e-6
    for _ in range(iters):
        if m.all():
            break
        acc = np.zeros_like(img); cnt = np.zeros(m.shape, np.float32); mi = img * m[..., None]
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx or dy:
                    acc += np.roll(np.roll(mi, dy, 0), dx, 1); cnt += np.roll(np.roll(m, dy, 0), dx, 1)
        new = (~m) & (cnt > 0)
        img[new] = acc[new] / cnt[new][:, None]; m = m | new
    return img


def smooth(a, w, h, sigma):
    """Light de-noise: masked Gaussian (normalised convolution) so empty atlas space doesn't darken island edges."""
    if sigma <= 0:
        a = a.copy(); a[:, :3] = fill_holes(a[:, :3].reshape(h, w, 3).copy()).reshape(-1, 3)
        return a
    r = max(1, int(round(sigma * 2)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2); k /= k.sum()
    img = fill_holes(a[:, :3].reshape(h, w, 3).copy()); m = (img.max(axis=2) > 1e-6).astype(np.float32)

    def conv(x):
        for ax in (0, 1):
            x = sum(wt * np.roll(x, s, axis=ax) for s, wt in zip(range(-r, r + 1), k))
        return x
    num = conv(img * m[..., None]); den = conv(m)[..., None]
    out = np.where(den > 1e-3, num / np.maximum(den, 1e-3), img) * (m[..., None] > 0)
    a = a.copy(); a[:, :3] = out.reshape(-1, 3)
    return a


def save_light(img, path, sigma=1.0):
    """Float light -> 8-bit sRGB-encoded (light * k). Returns k."""
    w, h = img.size
    a = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(a); a = a.reshape(-1, 4)
    a = smooth(a, w, h, sigma)
    lum = a[:, :3].max(axis=1)
    p = float(np.percentile(lum[lum > 1e-6], 99.5)) if (lum > 1e-6).any() else 1.0
    k = 0.92 / max(p, 1e-6)
    enc = np.clip(srgb_encode(np.clip(a[:, :3] * k, 0, 1)), 0, 1)
    out = bpy.data.images.new(img.name + "-8", w, h, alpha=False, float_buffer=False)
    out.colorspace_settings.name = "Non-Color"
    px = np.ones((w * h, 4), np.float32); px[:, :3] = enc
    out.pixels.foreach_set(px.ravel())
    out.filepath_raw = str(path); out.file_format = "PNG"; out.save()
    return k


def run(glb, genome, site, preset, out, gpu=False, finishes=None):
    P = {**PRESET, **preset}
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    G = json.loads(Path(genome).read_text()); S = json.loads(Path(site).read_text())
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = BR.build_materials()
    fin = json.loads(Path(finishes).read_text()) if finishes and Path(finishes).exists() else None
    BR.build(glb, G, S, mats, fin, Path(finishes).parent if finishes else ".")
    BR.setup_render(P["light_samples"], 1.0, P["sun_azimuth"], P["sun_elevation"], gpu=gpu)
    sc = bpy.context.scene
    sc.cycles.use_denoising = False; sc.cycles.use_adaptive_sampling = False
    meshes = prep(G, P["site_half_m"])
    for m in bpy.data.materials:
        b = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None
        if b and not b.inputs["Metallic"].is_linked and b.inputs["Metallic"].default_value > 0:
            b.inputs["Metallic"].default_value = 0.0
    kinds = {o.name: kind_of(o) for o in meshes}
    bake = [o for o in meshes if kinds[o.name] == "bake"]
    site_objs = [o for o in bake if o.name.startswith("SITE-") or o.name in ("drive", "road")]
    house = [o for o in bake if o not in site_objs]
    R = int(P["color_res"]); LR = max(256, R // int(P["light_div"]))
    bins, load = groups_for(house, R, P["texel_cm"] / 100)
    if site_objs:
        bins.append(site_objs); load.append(sum(area(o) for o in site_objs))
    log(f"bake: {len(meshes)} meshes, {len(house)} house + {len(site_objs)} site, {len(bins)} atlases "
        f"({', '.join(f'{a:.0f} m²' for a in load)}), colour {R}px, light {LR}px")
    margin_uv = 3.0 / LR                  # 3 light texels between islands (each box face is an island)
    meta = {"atlases": len(bins), "k": [], "color_res": R, "light_res": LR, "preset": P, "areas": load}
    for i, objs in enumerate(bins):
        unwrap(objs, margin_uv)
        merged = merged_copy(objs)
        col = bpy.data.images.new(f"color_{i}", R, R, alpha=False, float_buffer=False)
        tc = bake_pass([merged], col, "color", int(P["color_samples"]), 16)
        px = np.empty(R * R * 4, np.float32); col.pixels.foreach_get(px); px = px.reshape(-1, 4)
        px[:, :3] = fill_holes(px[:, :3].reshape(R, R, 3).copy()).reshape(-1, 3); col.pixels.foreach_set(px.ravel())
        col.filepath_raw = str(out / f"color_{i}.jpg"); col.file_format = "JPEG"
        try:
            col.save(quality=90)
        except TypeError:
            col.save()
        lig = bpy.data.images.new(f"light_{i}", LR, LR, alpha=False, float_buffer=True)
        tl = bake_pass([merged], lig, "light", int(P["light_samples"]), 4)
        drop_merged(merged, objs)
        meta["k"].append(save_light(lig, out / f"light_{i}.png", float(P["light_smooth"])))
        for o in objs:
            o["bake"] = i; o["mat"] = "bake"
        log(f"atlas {i}: {len(objs)} objects, colour {tc:.0f}s, light {tl:.0f}s")
    for o in meshes:
        if kinds[o.name] != "bake":
            o["mat"] = kinds[o.name]
            for uv in list(o.data.uv_layers):
                o.data.uv_layers.remove(uv)
    for o in bpy.data.objects:
        if o.type != "MESH":
            o.select_set(False)
    bpy.ops.export_scene.gltf(filepath=str(out / "scene.glb"), export_format="GLB", export_extras=True, export_materials="NONE",
                              export_normals=False, export_texcoords=True, export_apply=True, export_yup=True,
                              export_cameras=False, export_lights=False)
    meta["seconds"] = round(time.time() - t0)
    (out / "bake.json").write_text(json.dumps(meta, indent=1))
    log(f"bake done in {meta['seconds']}s")
    return [str(p) for p in sorted(out.iterdir())]


def main(argv):
    glb, genome, site, preset, out = argv[:5]
    run(glb, genome, site, json.loads(Path(preset).read_text()), out, gpu="--gpu" in argv)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[a.index("--") + 1:] if "--" in a else a)
