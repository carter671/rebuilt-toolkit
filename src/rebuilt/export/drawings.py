"""PDF model-review drawing set, cut and projected from the same compiled solids as IFC/GLB.

Sheets: cover & notes, opening schedule, one plan per storey (true cut at storey + 1.2 m), roof plan,
four exterior elevations, two building sections, overall and detail axonometric views.
Every sheet carries a "MODEL REVIEW — NOT FOR PERMIT OR CONSTRUCTION" title block, the Genome
revision and model hash. Dimensions are read from the compiled model of that revision.
"""
from __future__ import annotations

import datetime as _dt
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Arc, FancyArrow, PathPatch, Polygon, Rectangle  # noqa: E402
from matplotlib.path import Path  # noqa: E402

from ..genome.schema import Genome  # noqa: E402
from ..model.compile import CompiledModel  # noqa: E402
from ..units import fmt_ft_in, fmt_pitch  # noqa: E402
from . import views as V  # noqa: E402

SHEET = (17.0, 11.0)  # ANSI B / tabloid landscape, inches
DRAW = (0.45, 1.45, 16.1, 9.1)  # drawing area: x, y, w, h (inches)
SCALES = [(48, '1/4" = 1\'-0"'), (64, '3/16" = 1\'-0"'), (96, '1/8" = 1\'-0"'), (128, '3/32" = 1\'-0"'),
          (192, '1/16" = 1\'-0"'), (384, '1/32" = 1\'-0"')]
BASIS_COLOR = {"measured": "#111111", "extracted": "#1f4e9c", "observed": "#1f7a8c", "inferred": "#d9822b",
               "assumed": "#c0392b", "unknown": "#8e44ad"}
BASIS_RANK = {"measured": 0, "extracted": 1, "observed": 2, "inferred": 3, "assumed": 4, "unknown": 5}
FACE_COLOR = {"wall": "#ece4d6", "slab": "#cfcac0", "roof": "#8b9097", "filling": "#b08463", "glass": "#bcd9ea",
              "component": "#e6e6e0"}
VIEW_TYPES = ("wall", "slab", "roof", "filling", "component")
BELOW_CUT_KINDS = ("stair", "furnishing", "fixture", "equipment", "railing")


def _colors(model, g):
    """Finish colours for views (as-built paint / cladding / trim), cached on the model."""
    if getattr(model, "_view_colors", None) is None:
        from .glb import element_colors

        cols = element_colors(model, g) if g is not None else {}
        # slab edges on the façade are rim bands behind the siding: draw them in the dominant cladding colour
        clad = [c.data["color"] for c in model.elements.values() if c.type == "component" and c.data.get("kind") == "cladding" and c.data.get("color")]
        if clad:
            rim = max(set(clad), key=clad.count)
            for k, e in model.elements.items():
                if e.type == "slab" and e.data.get("kind") in ("floor", "base"):
                    cols[k + "|edge"] = rim
        model._view_colors = cols
    return model._view_colors


def _courses(model, g):
    """Cladding course lines: wall id -> (base z, exposure, exterior normal (x, y))."""
    out = {}
    for ce in model.elements.values():
        if ce.type == "component" and ce.data.get("kind") == "cladding" and ce.data.get("exposure"):
            for h in ce.data.get("hosts", []):
                if h in model.elements:
                    out[h] = (model.elements[h].data["base_z"], ce.data["exposure"])
    return out


def worst_basis(params: dict, keys=None) -> str:
    worst = "measured"
    for k, rec in params.items():
        if keys and k not in keys:
            continue
        b = rec.get("basis") or "assumed"
        if rec.get("defaulted"):
            b = "assumed"
        if BASIS_RANK.get(b, 4) > BASIS_RANK[worst]:
            worst = b
    return worst


class Sheet:
    def __init__(self, pdf, g: Genome, model: CompiledModel, title: str, number: str, scale_label: str = ""):
        self.pdf, self.g, self.model = pdf, g, model
        self.fig = plt.figure(figsize=SHEET)
        self.title, self.number, self.scale_label = title, number, scale_label
        self._frame()

    def _frame(self):
        f = self.fig
        ax = f.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, SHEET[0])
        ax.set_ylim(0, SHEET[1])
        ax.axis("off")
        ax.add_patch(Polygon([(0.25, 0.25), (16.75, 0.25), (16.75, 10.75), (0.25, 10.75)], fill=False, lw=1.2))
        ax.plot([0.25, 16.75], [1.15, 1.15], lw=0.8, color="k")
        g, m = self.g, self.model
        cols = [0.25, 5.2, 9.4, 12.0, 14.6, 16.75]
        for x in cols[1:-1]:
            ax.plot([x, x], [0.25, 1.15], lw=0.6, color="k")
        ax.text(0.4, 0.88, g.project.name + ("  (FICTIONAL TEST PROJECT)" if g.project.fictional else ""), fontsize=11, weight="bold")
        ax.text(0.4, 0.62, f"Property: {g.property.address or g.property.id}", fontsize=7.5)
        ax.text(0.4, 0.40, "Rebuilt — rebuilt.homes", fontsize=7.5, color="#444")
        ax.text(5.35, 0.85, "MODEL REVIEW DRAWING", fontsize=11, weight="bold", color="#b03a2e")
        ax.text(5.35, 0.62, "NOT FOR PERMIT, CONSTRUCTION, OR PRICING.", fontsize=7.5, weight="bold", color="#b03a2e")
        ax.text(5.35, 0.42, "Not reviewed or certified by a licensed design professional.", fontsize=6.5)
        ax.text(5.35, 0.30, "Values carry provenance & uncertainty — see sheet G-001 notes.", fontsize=6.5)
        ax.text(9.55, 0.85, f"Genome rev {m.genome_revision} · profile {m.profile}", fontsize=7.5)
        ax.text(9.55, 0.62, f"Model {m.model_hash[:12]} · MODEL {m.compiler_version}", fontsize=7.5, family="monospace")
        ax.text(9.55, 0.40, f"Generated {_dt.date.today().isoformat()}", fontsize=7.5)
        ax.text(12.15, 0.85, "SCALE", fontsize=6.5, color="#555")
        ax.text(12.15, 0.55, self.scale_label or "as noted / NTS", fontsize=8.5)
        ax.text(14.75, 0.85, self.title, fontsize=9, weight="bold")
        ax.text(14.75, 0.40, self.number, fontsize=18, weight="bold")
        self.frame_ax = ax

    def drawing_axes(self, extent_xy, rect=DRAW, scale=None, pad=0.9):
        """Create true-scale axes for model extents (xmin, ymin, xmax, ymax) in metres."""
        x, y, w, h = rect
        (x0, y0, x1, y1) = extent_xy
        if scale is None:
            for ratio, label in SCALES:
                if (x1 - x0 + 2 * pad) / ratio / 0.0254 <= w and (y1 - y0 + 2 * pad) / ratio / 0.0254 <= h:
                    scale = (ratio, label)
                    break
            else:
                scale = SCALES[-1]
        ratio, label = scale
        ax = self.fig.add_axes([x / SHEET[0], y / SHEET[1], w / SHEET[0], h / SHEET[1]])
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        hw, hh = w * 0.0254 * ratio / 2, h * 0.0254 * ratio / 2
        ax.set_xlim(cx - hw, cx + hw)
        ax.set_ylim(cy - hh, cy + hh)
        ax.set_aspect("equal")
        ax.axis("off")
        return ax, scale

    def save(self):
        self.pdf.savefig(self.fig)
        plt.close(self.fig)


# ------------------------------------------------------------- annotation helpers

def dim(ax, p, q, offset, text_override=None, fs=6.5, color="#222"):
    """Aligned dimension between model points p and q, offset perpendicular (metres)."""
    p, q = np.asarray(p, float), np.asarray(q, float)
    d = q - p
    L = float(np.linalg.norm(d))
    if L < 1e-6:
        return
    t = d / L
    n = np.array([-t[1], t[0]])
    a, b = p + n * offset, q + n * offset
    ax.plot([p[0], a[0] + n[0] * 0.08 * np.sign(offset)], [p[1], a[1] + n[1] * 0.08 * np.sign(offset)], lw=0.35, color=color)
    ax.plot([q[0], b[0] + n[0] * 0.08 * np.sign(offset)], [q[1], b[1] + n[1] * 0.08 * np.sign(offset)], lw=0.35, color=color)
    ax.plot([a[0], b[0]], [a[1], b[1]], lw=0.5, color=color)
    for c in (a, b):
        tk = (t + n) * 0.06
        ax.plot([c[0] - tk[0], c[0] + tk[0]], [c[1] - tk[1], c[1] + tk[1]], lw=0.9, color=color)
    ang = math.degrees(math.atan2(t[1], t[0]))
    if ang > 90.5 or ang < -89.5:
        ang += 180
    mid = (a + b) / 2 + n * 0.09 * np.sign(offset if offset else 1)
    txt = text_override or f"{fmt_ft_in(L)}  [{L:.3f}]"
    ax.text(mid[0], mid[1], txt, fontsize=fs, rotation=ang, ha="center", va="center", color=color,
            bbox=dict(fc="white", ec="none", pad=0.4))


def north_arrow(ax, x, y, size=0.6):
    ax.add_patch(FancyArrow(x, y - size / 2, 0, size, width=size * 0.08, head_width=size * 0.35, head_length=size * 0.35,
                            length_includes_head=True, color="k"))
    ax.text(x, y + size * 0.65, "N (project)", ha="center", fontsize=6.5)


def legend_basis(ax, x, y, fs=6.5):
    ax.text(x, y, "Wall poche colour = least-certain basis of thickness/height:", fontsize=fs, weight="bold")
    for i, (b, c) in enumerate(BASIS_COLOR.items()):
        ax.add_patch(Polygon([(x + i * 1.35, y - 0.28), (x + i * 1.35 + 0.25, y - 0.28), (x + i * 1.35 + 0.25, y - 0.12),
                              (x + i * 1.35, y - 0.12)], color=c))
        ax.text(x + i * 1.35 + 0.32, y - 0.22, b, fontsize=fs, va="center")


def _path(polys):
    verts, codes = [], []
    for p in polys:
        p = np.asarray(p)
        verts += p.tolist() + [p[0].tolist()]
        codes += [Path.MOVETO] + [Path.LINETO] * (len(p) - 1) + [Path.CLOSEPOLY]
    return Path(verts, codes)


def draw_faces(ax, faces, model, lw=0.45, alpha_space=False, colors=None, courses=None):
    """Painter's-order faces. colors: element -> finish hex; courses: wall -> (base z, exposure) for
    siding lines on vertical faces (elevations only: screen y must be world z)."""
    colors = colors or {}
    for fc in faces:
        ce = model.elements[fc.element]
        if fc.etype == "filling" and ce.ifc_class == "IfcWindow":
            base = FACE_COLOR["glass"]
        else:
            base = colors.get(fc.element) or FACE_COLOR.get(fc.etype, "#dddddd")
            if fc.etype == "slab":
                base = colors.get(fc.element + "|edge", base) if abs(fc.normal[2]) < 0.05 else FACE_COLOR["slab"]
        rgb = np.array(matplotlib.colors.to_rgb(base)) * fc.shade + (1 - fc.shade) * 0.25
        patch = PathPatch(_path(fc.loops), facecolor=np.clip(rgb, 0, 1), edgecolor="#222", lw=lw, joinstyle="round")
        ax.add_patch(patch)
        if courses and fc.element in courses and abs(fc.normal[2]) < 0.05:
            z0, exp = courses[fc.element]
            allp = np.vstack(fc.loops)
            x0, x1 = allp[:, 0].min(), allp[:, 0].max()
            ytop = allp[:, 1].max()
            k = 1
            while z0 + k * exp < ytop:
                ln, = ax.plot([x0, x1], [z0 + k * exp] * 2, lw=0.18, color="#3a3a3a", alpha=0.6)
                ln.set_clip_path(patch)
                k += 1


def _drop_slab_tops(faces):
    """Overall views: floor-slab top/bottom faces are almost always hidden and, being large, defeat the
    painter's sort (they get drawn over nearer roofs). Keep only their edges (the visible floor band)."""
    return [f for f in faces if not (f.etype == "slab" and abs(f.normal[2]) > 0.9)]


def _solids_for_views(model):
    return {k: v for k, v in model._solids.items() if model.elements[k].type in VIEW_TYPES}


def _meshes_for_views(model, ids=None):
    return {k: e.mesh for k, e in model.elements.items()
            if e.type in VIEW_TYPES and e.mesh is not None and (ids is None or k in ids)}


# ------------------------------------------------------------- sheets

def sheet_notes(pdf, g, model, export_notes):
    s = Sheet(pdf, g, model, "GENERAL NOTES", "G-001")
    ax = s.frame_ax
    y = 10.4
    ax.text(0.5, y, "GENERAL NOTES — MODEL REVIEW SET", fontsize=13, weight="bold")
    notes = [
        "1. This set is generated automatically from the Rebuilt Genome (authoritative building description) by the MODEL compiler.",
        "   Plans, elevations, sections, the IFC file and the GLB file are produced from the same compiled solids.",
        "2. Purpose: checking the reconstructed building against evidence. It is NOT a permit, construction, or engineering document.",
        "3. Dimensions are shown as feet-inches with metres in brackets. Wall dimensions are to outside faces unless noted.",
        "4. Every value carries a basis: measured · extracted (from a document) · observed · inferred · assumed · unknown.",
        "   Plan poche colour shows the least-certain basis of each wall's thickness/height. Uncertainties are ± bounds.",
        "5. Doors and windows are drawn as proxy panels and generic symbols; frames, trim, hardware and swing direction",
        "   are only as specific as the 'operation' recorded in Genome.",
        "6. NOT MODELLED (declared scope extensions): framing, structure, foundations below slab, MEP, stairs, finishes, site, estimating.",
    ]
    for i, n in enumerate(notes):
        ax.text(0.5, y - 0.45 - i * 0.24, n, fontsize=7.6)
    y2 = y - 0.45 - len(notes) * 0.24 - 0.35
    ax.text(0.5, y2, "VALUES THAT ARE NOT MEASURED, OR NOT VERIFIED AS DISPUTE-FREE", fontsize=9.5, weight="bold")
    rows = []
    for eid, ce in model.elements.items():
        if ce.type in ("filling",):
            continue
        for p, rec in sorted(ce.params.items()):
            b = "assumed" if rec.get("defaulted") else rec.get("basis")
            if b in ("inferred", "assumed", "observed", "unknown") or rec.get("verification") == "disputed":
                unc = rec.get("uncertainty")
                val = rec.get("value")
                vs = "—" if val is None else (fmt_pitch(val) if p == "pitch" else f"{fmt_ft_in(val)} [{val:.3f}]")
                rows.append((eid, p, vs, b, f"±{unc:.3f}" if unc is not None else "—",
                             f"{rec['confidence']:.2f}" if rec.get("confidence") is not None else "—",
                             rec.get("verification", "—"),
                             ("candidates " + " / ".join(f"{c['value']:.3f}" for c in rec["conflicts"]) if rec.get("conflicts")
                              else (rec.get("note") or rec.get("from") or rec.get("input") or ""))[:48]))
    hdr = ("Element", "Param", "Value", "Basis", "Uncert.", "Conf.", "Verification", "Note / input")
    xs = [0.5, 2.0, 3.2, 5.1, 6.0, 6.8, 7.5, 8.6]
    ty = y2 - 0.32
    for x, h in zip(xs, hdr):
        ax.text(x, ty, h, fontsize=7, weight="bold")
    for i, r in enumerate(rows[:22]):
        for x, c in zip(xs, r):
            ax.text(x, ty - 0.2 * (i + 1), str(c), fontsize=6.8, color=BASIS_COLOR.get(r[3], "k") if c == r[3] else "k")
    if len(rows) > 22:
        ax.text(0.5, ty - 0.2 * 23.3, f"... {len(rows) - 22} more — see export_report.json", fontsize=7)
    # right column: unsupported, issues, export notes
    xr = 11.3
    ax.text(xr, y, "COMPILER FINDINGS", fontsize=9.5, weight="bold")
    yy = y - 0.35
    items = [f"[{i.severity}] {i.code}: {i.message}" for i in model.issues.sorted() if i.severity != "info"]
    items += [f"[unsupported] {u['element']}: {u['reason']}" for u in model.unsupported]
    if not items:
        items = ["No errors, warnings or unsupported features."]
    for it in items[:14]:
        ax.text(xr, yy, it[:95], fontsize=6.6)
        yy -= 0.2
    yy -= 0.25
    ax.text(xr, yy, "EXPORT NOTES", fontsize=9.5, weight="bold")
    yy -= 0.35
    for n in export_notes[:16]:
        ax.text(xr, yy, "• " + n[:92], fontsize=6.6)
        yy -= 0.2
    legend_basis(ax, 0.5, 1.75)
    s.save()


def sheet_schedule(pdf, g, model, per_sheet=27):
    ops = model.by_type("opening")
    pages = [ops[i:i + per_sheet] for i in range(0, max(len(ops), 1), per_sheet)] or [[]]
    for pi, chunk in enumerate(pages):
        num = "A-001" if pi == 0 else f"A-00{pi + 1}"
        s = Sheet(pdf, g, model, "OPENING SCHEDULE", num)
        ax = s.frame_ax
        ax.text(0.5, 10.4, "OPENING SCHEDULE" + (f" (continued {pi + 1}/{len(pages)})" if len(pages) > 1 else ""), fontsize=13, weight="bold")
        hdr = ("ID", "Host wall", "Storey", "Kind", "Operation", "Width", "Height", "Sill", "Head (abs. elev.)", "Least-certain basis", "Unc. ±")
        xs = [0.5, 2.0, 3.4, 4.1, 4.9, 6.4, 8.1, 9.8, 11.4, 13.0, 14.8]
        ax.text(0.5, 10.0, "Dimensions are rough-opening sizes recorded in Genome; feet-inches with metres in brackets.", fontsize=7.5)
        for x, h in zip(xs, hdr):
            ax.text(x, 9.6, h, fontsize=7.5, weight="bold")
        ax.plot([0.5, 16.3], [9.5, 9.5], lw=0.6, color="k")
        for i, ce in enumerate(chunk):
            d = ce.data
            fill = model.elements.get(ce.id + "#fill")
            b = worst_basis(ce.params)
            unc = max((r.get("uncertainty") or 0) for r in ce.params.values())
            row = (ce.id, d["host"], ce.storey, d["kind"], ((fill.data["operation"] if fill else "—") or "—")[:22],
                   f"{fmt_ft_in(d['width'])} [{d['width']:.3f}]", f"{fmt_ft_in(d['height'])} [{d['height']:.3f}]",
                   f"{fmt_ft_in(d['sill'])} [{d['sill']:.3f}]", f"{fmt_ft_in(d['head_z'])} [{d['head_z']:.3f}]", b, f"{unc:.3f}")
            for x, c in zip(xs, row):
                ax.text(x, 9.3 - i * 0.28, c, fontsize=7.0, color=BASIS_COLOR[b] if c == b else "k")
        s.save()
    return [("A-001" if i == 0 else f"A-00{i + 1}") for i in range(len(pages))]


def sheet_components(pdf, g, model, per_sheet=30, start=501):
    """Component schedule (G3): every placed component with kind, host, size, finish, condition and evidence."""
    comps = [c for c in model.by_type("component") if c.mesh is not None or c.data.get("kind") == "cladding"]
    if not comps:
        return []
    cols = _colors(model, g)
    pages = [comps[i:i + per_sheet] for i in range(0, len(comps), per_sheet)]
    nums = []
    for pi, chunk in enumerate(pages):
        num = f"A-{start + pi}"
        nums.append(num)
        s = Sheet(pdf, g, model, "COMPONENT SCHEDULE", num)
        ax = s.frame_ax
        ax.text(0.5, 10.4, "COMPONENT SCHEDULE — EXTERIOR DETAIL (G3)" + (f" ({pi + 1}/{len(pages)})" if len(pages) > 1 else ""),
                fontsize=13, weight="bold")
        ax.text(0.5, 10.0, "Sizes w × h × d in inches (along host × vertical × projection). Colours are photo-matched approximations "
                "unless a paint product is named. Info-only items are listed in the review workbook.", fontsize=7.2)
        hdr = ("ID", "Kind", "Category / subtype", "Placement", "Size (in)", "Finish", "Condition", "Photos", "Basis")
        xs = [0.5, 2.3, 3.3, 6.4, 8.9, 10.6, 13.3, 14.7, 15.5]
        for x, h in zip(xs, hdr):
            ax.text(x, 9.6, h, fontsize=7.2, weight="bold")
        ax.plot([0.5, 16.3], [9.5, 9.5], lw=0.6, color="k")
        for i, ce in enumerate(chunk):
            gel = g.elements.get(ce.id)
            inf = gel.info if gel is not None and gel.info else None
            if gel is not None and gel.family and gel.family in g.families and inf is None:
                inf = g.families[gel.family].info
            d = ce.data
            sz = []
            for k in ("w", "h", "d"):
                r = ce.params.get(f"size.{k}")
                sz.append("—" if not r or r.get("value") is None else f"{r['value'] / 0.0254:.1f}")
            host = d.get("host") or d.get("roof") or ("+".join(d.get("walls", [])) if d.get("walls") else "") or \
                (f"{len(d.get('hosts', []))} walls" if d.get("hosts") else "") or (f"({d['at'][0]:.1f}, {d['at'][1]:.1f})" if d.get("at") else "")
            pos = d.get("position") or (",".join(map(str, d["edges"])) if d.get("edges") else "")
            fin = g.finishes.get(inf.finish) if inf and inf.finish else None
            cond = inf.condition.rating if inf and inf.condition else "—"
            photos = len(inf.observed.photos) if inf and inf.observed else 0
            b = worst_basis(ce.params) if ce.params else "observed"
            y = 9.3 - i * 0.28
            cat = " / ".join(x for x in ((inf.category if inf else ""), (inf.subtype if inf else "")) if x)[:44]
            row = (ce.id[:26], d["kind"], cat, f"{d['placement']} {host} {pos}"[:36], " × ".join(sz),
                   (fin.name[:30] if fin else "—"), cond, str(photos), b)
            for x, c in zip(xs, row):
                ax.text(x, y, c, fontsize=6.6, color=BASIS_COLOR.get(b, "k") if c == b else "k")
            if fin and fin.hex:
                ax.add_patch(Rectangle((10.45, y - 0.02), 0.12, 0.12, facecolor=fin.hex, edgecolor="#333", lw=0.3))
        s.save()
    return nums


def sheet_plan(pdf, g, model, storey, number):
    solids = _solids_for_views(model)
    z = storey.elevation.value + 1.2
    def _spans(k):  # elements of this storey, plus walls / fillings of a lower storey that rise through this cut (multi-storey walls)
        e = model.elements[k]
        if e.storey == storey.id:
            return True
        if e.type in ("wall", "filling") and e.mesh is not None:
            lo, hi = e.mesh.bounds()
            return lo[2] < z < hi[2]
        return False
    cuts = V.plan_cut({k: v for k, v in solids.items() if _spans(k)}, z)
    st_els = [e for e in model.elements.values() if e.storey == storey.id]
    pts = np.vstack([np.asarray(p) for e in st_els if e.type in ("wall", "slab") for p in
                     ([e.data["plan_polygon"]] if e.type == "wall" else [e.data["boundary"]])])
    ext = (*pts.min(0), *pts.max(0))
    s = Sheet(pdf, g, model, f"PLAN — {storey.name.upper()}", number)
    ax, scale = s.drawing_axes(ext, pad=1.6)
    s.scale_label = scale[1]
    s.frame_ax.texts[[t.get_text() for t in s.frame_ax.texts].index("as noted / NTS")].set_text(scale[1])
    # slab / footprint outlines (below cut, thin)
    for e in st_els:
        if e.type == "slab" and e.data["kind"] in ("base", "floor"):
            ax.add_patch(Polygon(e.data["boundary"], fill=False, lw=0.4, ls=(0, (4, 2)), color="#888"))
    # roofs bearing on lower storeys that are visible below this cut (outline only)
    for e in model.by_type("roof"):
        if e.data["top_z"] < z and model.elements[e.id].storey != storey.id or (e.storey == storey.id and e.data["plate_z"] > z):
            ax.add_patch(Polygon(e.data["outline"], fill=False, lw=0.5, ls=(0, (6, 3)), color="#666"))
    # spaces
    for e in st_els:
        if e.type == "space":
            b = np.asarray(e.data["boundary"])
            c = b.mean(0)
            ax.text(c[0], c[1] + 0.12, e.name.upper(), ha="center", fontsize=8, weight="bold")
            a = e.data["area"]
            ax.text(c[0], c[1] - 0.18, f"{a * 10.7639:.0f} sf  [{a:.2f} m²]", ha="center", fontsize=6.8)
            hb = e.params.get("height", {}).get("basis", "")
            ax.text(c[0], c[1] - 0.42, f"clg {fmt_ft_in(e.data['height'])} ({hb})", ha="center", fontsize=6, color="#555")
    # components wholly below the cut (stair steps, cabinets, fixtures): plan outline, lightly filled — as drawn on a floor plan
    from shapely.geometry import MultiPoint
    for e in st_els:
        if e.type == "component" and e.mesh is not None and e.id not in cuts and e.data.get("kind") in BELOW_CUT_KINDS:
            lo, hi = e.mesh.bounds()
            if hi[2] >= z or hi[2] <= storey.elevation.value + 0.01:
                continue
            hull = MultiPoint([tuple(v) for v in np.asarray(e.mesh.verts)[:, :2]]).convex_hull
            if hull.geom_type == "Polygon":
                ax.add_patch(Polygon(np.asarray(hull.exterior.coords), facecolor="#f1f1ec", edgecolor="#777", lw=0.3))
    # cut walls coloured by basis
    for eid, polys in cuts.items():
        ce = model.elements[eid]
        if ce.type == "wall":
            col = BASIS_COLOR[worst_basis(ce.params, ("thickness", "height"))]
            ax.add_patch(PathPatch(_path(polys), facecolor=col, edgecolor="k", lw=0.6))
        elif ce.type == "filling" and ce.ifc_class == "IfcWindow":
            ax.add_patch(PathPatch(_path(polys), facecolor="white", edgecolor="k", lw=0.5))
        elif ce.type == "component":
            ax.add_patch(PathPatch(_path(polys), facecolor=_colors(model, g).get(eid, "#ccc"), edgecolor="#333", lw=0.25))
    # opening symbols
    for ce in model.by_type("opening"):
        # show an opening on the plan of the storey whose cut passes through it (doors: whose floor it stands on)
        sz, hz = ce.data.get("sill_z"), ce.data.get("head_z")
        if sz is None:
            if ce.storey != storey.id:
                continue
        elif not (sz < z < hz or (ce.data["kind"] == "door" and storey.elevation.value - 0.05 <= sz < z)):
            continue
        d = ce.data
        host = model.elements[d["host"]].data
        fr = host["frame"]
        st = np.array(host["baseline"][0])
        dd, nn = np.array(fr["d"]), np.array(fr["n"])
        p0 = st + dd * d["offset"]
        p1 = st + dd * (d["offset"] + d["width"])
        cut_here = d["sill_z"] < z < d["head_z"]
        if not cut_here:  # opening above/below cut: dashed outline
            for v in (fr["off_left"], fr["off_right"]):
                ax.plot(*np.c_[p0 + nn * v, p1 + nn * v], lw=0.4, ls="--", color="#555")
        if d["kind"] == "window" and cut_here:
            for v in (fr["off_left"], fr["off_right"]):
                ax.plot(*np.c_[p0 + nn * v, p1 + nn * v], lw=0.4, color="k")
        fill = model.elements.get(ce.id + "#fill")
        if d["kind"] == "door" and fill and "overhead" in (fill.data.get("operation") or ""):
            for v in (fr["off_left"] + 0.15, fr["off_right"] - 0.15):
                ax.plot(*np.c_[p0 + nn * v, p1 + nn * v], lw=0.5, ls=(0, (4, 2)), color="k")
            ax.text(*(p0 + dd * d["width"] / 2 + nn * (fr["off_left"] + 0.25)), "OH door", fontsize=5.5, ha="center")
        elif d["kind"] == "door":
            hinge = p0 + nn * fr["off_left"]
            leaf_end = hinge + nn * d["width"]
            ax.plot(*np.c_[hinge, leaf_end], lw=0.8, color="k")
            ang0 = math.degrees(math.atan2(dd[1], dd[0]))
            ang1 = math.degrees(math.atan2(nn[1], nn[0]))
            a0, a1 = sorted([ang0, ang1]) if abs(ang1 - ang0) <= 180 else sorted([ang1, ang0 + 360])
            ax.add_patch(Arc(hinge, 2 * d["width"], 2 * d["width"], theta1=a0, theta2=a1, lw=0.4, ls=(0, (3, 2))))
        # tag
        tag = p0 + dd * d["width"] / 2 + nn * (fr["off_left"] + 0.38)
        ax.text(*tag, ce.id.split("-")[-1], fontsize=5.8, ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#444", lw=0.4))
    # dimensions: overall outside faces + south-face opening string
    walls = [e for e in st_els if e.type == "wall" and e.data["exterior"]]
    if walls:
        allp = np.vstack([np.asarray(w.data["plan_polygon"]) for w in walls])
        xmin, ymin = allp.min(0)
        xmax, ymax = allp.max(0)
        dim(ax, (xmin, ymax), (xmax, ymax), 0.9)
        dim(ax, (xmin, ymin), (xmin, ymax), 0.9)
        # opening string along each exterior wall's outside face (stations along the baseline)
        cen = allp.mean(0)
        for w in walls:
            fr = w.data["frame"]
            st = np.array(w.data["baseline"][0])
            dd, nn = np.array(fr["d"]), np.array(fr["n"])
            ops = sorted([o for o in model.by_type("opening") if o.data["host"] == w.id], key=lambda o: o.data["offset"])
            if not ops:
                continue
            stations = [0.0] + [x for o in ops for x in (o.data["offset"], o.data["offset"] + o.data["width"])] + [w.data["length"]]
            mid = st + dd * w.data["length"] / 2
            side = 1.0 if np.dot(mid - cen, nn) > 0 else -1.0  # +1: outside is the wall's left
            face_off = fr["off_left"] if side > 0 else fr["off_right"]
            for a, b in zip(stations[:-1], stations[1:]):
                if b - a > 0.02:
                    dim(ax, st + dd * a + nn * face_off, st + dd * b + nn * face_off, 0.45 * side, fs=5.6,
                        text_override=fmt_ft_in(b - a))
    north_arrow(ax, ax.get_xlim()[1] - 0.8, ax.get_ylim()[1] - 1.0)
    legend_basis(s.frame_ax, 0.6, 1.62)
    s.frame_ax.text(9.0, 1.42, f"Plan cut at {fmt_ft_in(1.2)} above storey elevation {fmt_ft_in(storey.elevation.value)}  ·  "
                    "string dims measured along wall baseline (C/L for centre-aligned walls)", fontsize=6.5)
    s.save()


def sheet_roof(pdf, g, model):
    roofs = model.by_type("roof")
    if not roofs:
        return
    pts = np.vstack([np.asarray(r.data["outline"]) for r in roofs])
    s = Sheet(pdf, g, model, "ROOF PLAN", "A-110")
    ax, scale = s.drawing_axes((*pts.min(0), *pts.max(0)), pad=1.4)
    s.frame_ax.texts[[t.get_text() for t in s.frame_ax.texts].index("as noted / NTS")].set_text(scale[1])
    for w in model.by_type("wall"):
        if w.data["exterior"]:
            ax.add_patch(Polygon(w.data["plan_polygon"], fill=False, lw=0.35, ls=(0, (3, 2)), color="#999"))
    # roof surfaces seen from above (hidden-surface by height), so valleys and overlaps read correctly
    meshes = {}
    for r in roofs:
        for k, pm in r.parts.items():
            meshes[f"{r.id}|{k}"] = pm
    roof_top = {}
    for e in model.elements.values():  # chimneys, roof-edge members, roof-mounted items seen from above
        if e.type == "component" and e.mesh is not None and e.data.get("kind") in ("chimney", "gutter", "fascia", "vent", "trim") \
                and (e.data.get("kind") == "chimney" or e.data.get("placement") == "roof_edge"):
            meshes[e.id] = e.mesh
            roof_top[e.id] = True
    faces, _, _ = V.project_faces(meshes, {k: ("component" if k in roof_top else "roof") for k in meshes}, (0, 0, -1), light=(0.3, -0.5, 0.8))
    cols = _colors(model, g)
    for fc in faces:
        if fc.element in roof_top:
            rgb = np.array(matplotlib.colors.to_rgb(cols.get(fc.element, "#bbbbbb"))) * (0.75 + 0.25 * fc.shade)
            ax.add_patch(PathPatch(_path(fc.loops), facecolor=np.clip(rgb, 0, 1), edgecolor="#222", lw=0.35))
            continue
        ax.add_patch(PathPatch(_path(fc.loops), facecolor=np.clip(np.array([0.90, 0.91, 0.92]) * (0.75 + 0.25 * fc.shade), 0, 1),
                               edgecolor="k", lw=0.7))
    for r in roofs:
        bas = worst_basis(r.params, ("pitch",))
        for k, pm in sorted(r.parts.items()):
            edge = int(k.rsplit("edge", 1)[1])
            pn = next(p for p in r.data["panels"] if p["edge"] == edge)
            a, b, _ = pn["plane"]
            v = pm.verts
            top = v[v[:, 2] >= np.percentile(v[:, 2], 40)]
            c = top[:, :2].mean(0)
            grad = np.array([a, b])
            if np.linalg.norm(grad) > 0:
                down = -grad / np.linalg.norm(grad)
                L = 0.8
                ax.add_patch(FancyArrow(c[0] - down[0] * L / 2, c[1] - down[1] * L / 2, down[0] * L, down[1] * L, width=0.02,
                                        head_width=0.16, head_length=0.18, color="k", length_includes_head=True))
                ax.text(c[0] + 0.12, c[1] + 0.12, f"{fmt_pitch(r.data['slope'])}", fontsize=6.5, color=BASIS_COLOR[bas],
                        bbox=dict(fc="white", ec="none", pad=0.3, alpha=0.8))
        o = np.asarray(r.data["outline"])
        ax.text(*o.mean(0), r.name, fontsize=6, ha="center", va="center", style="italic", alpha=0.75)
    mn, mx = pts.min(0), pts.max(0)
    dim(ax, (mn[0], mx[1]), (mx[0], mx[1]), 0.7, fs=6)
    dim(ax, (mn[0], mn[1]), (mn[0], mx[1]), 0.7, fs=6)
    north_arrow(ax, ax.get_xlim()[1] - 0.8, ax.get_ylim()[1] - 1.0)
    s.frame_ax.text(0.6, 1.42, "Roof surfaces seen from above. Arrows point downslope; pitch colour = basis (see G-001). "
                    "Dashed: exterior wall outlines. Overall dims to overhang edges.", fontsize=6.5)
    s.save()


def _levels(ax, g, model, x0, x1):
    for st in g.storeys():
        z = st.elevation.value
        ax.plot([x0 - 0.6, x1 + 0.6], [z, z], lw=0.4, ls=(0, (8, 3, 2, 3)), color="#555")
        ax.text(x1 + 0.7, z, f"{st.name}  {fmt_ft_in(z)} [{z:.3f}]", fontsize=6.3, va="center")
    tops = [r.data["top_z"] for r in model.by_type("roof")]
    if tops:
        z = max(tops)
        ax.plot([x0 - 0.6, x1 + 0.6], [z, z], lw=0.4, ls=(0, (8, 3, 2, 3)), color="#555")
        ax.text(x1 + 0.7, z, f"Roof top {fmt_ft_in(z)} [{z:.3f}]", fontsize=6.3, va="center")


def sheet_elevations(pdf, g, model, pairs, number):
    s = Sheet(pdf, g, model, "EXTERIOR ELEVATIONS", number)
    meshes = _meshes_for_views(model)
    et = {k: model.elements[k].type for k in meshes}
    rects = [(0.45, 5.75, 16.1, 4.8), (0.45, 1.3, 16.1, 4.3)]
    results = []
    for (name, vdir), rect in zip(pairs, rects):
        faces, r, u = V.project_faces(meshes, et, vdir)
        faces = _drop_slab_tops(faces)
        allp = np.vstack([lp for f in faces for lp in f.loops])
        ext = (*allp.min(0), *allp.max(0))
        results.append((name, faces, ext, rect))
    ratio = max(next(rt for rt in SCALES if (e[2] - e[0] + 4) / rt[0] / 0.0254 <= rc[2] and (e[3] - e[1] + 1.5) / rt[0] / 0.0254 <= rc[3])[0]
                for _, _, e, rc in results)
    sc = next(x for x in SCALES if x[0] == ratio)
    for name, faces, ext, rect in results:
        ax, _ = s.drawing_axes(ext, rect=rect, scale=sc)
        draw_faces(ax, faces, model, colors=_colors(model, g), courses=_courses(model, g))
        _levels(ax, g, model, ext[0], ext[2])
        ax.plot([ext[0] - 0.8, ext[2] + 0.8], [ext[1], ext[1]], lw=1.4, color="k")
        ax.text((ext[0] + ext[2]) / 2, ext[1] - 0.55, name, ha="center", fontsize=9, weight="bold")
        dim(ax, (ext[0], ext[1]), (ext[0], ext[3]), -0.9 if False else 0.9, fs=6)
    s.frame_ax.texts[[t.get_text() for t in s.frame_ax.texts].index("as noted / NTS")].set_text(sc[1])
    s.save()


def sheet_section(pdf, g, model, name, point, vdir, number):
    solids = _solids_for_views(model)
    cuts, beyond, r, u, v = V.section(solids, {}, point, vdir)
    et = {k: model.elements[k].type for k in beyond}
    faces, _, _ = V.project_faces(beyond, et, vdir)
    allp = np.vstack([lp for f in faces for lp in f.loops] + [p for ps in cuts.values() for p in ps])
    ext = (*allp.min(0), *allp.max(0))
    s = Sheet(pdf, g, model, f"SECTION {name}", number)
    ax, sc = s.drawing_axes(ext, pad=1.8)
    s.frame_ax.texts[[t.get_text() for t in s.frame_ax.texts].index("as noted / NTS")].set_text(sc[1])
    # spaces cut: label
    draw_faces(ax, faces, model, lw=0.3, colors=_colors(model, g))
    for eid, polys in cuts.items():
        ce = model.elements[eid]
        col = {"wall": BASIS_COLOR[worst_basis(ce.params, ('thickness', 'height'))], "slab": "#555", "roof": "#333",
               "filling": "#ffffff", "component": _colors(model, g).get(eid, "#999")}[ce.type]
        ax.add_patch(PathPatch(_path(polys), facecolor=col, edgecolor="k", lw=0.8))
    for sp in model.by_type("space"):
        b = np.asarray(sp.data["boundary"])
        P = np.c_[b, np.full(len(b), sp.data["base_z"])]
        dist = P @ v - float(np.dot(v, point))
        if dist.min() < 0 < dist.max():
            c = P.mean(0)
            sx = float(c @ r)
            ax.text(sx if b[:, 0].min() <= point[0] <= b[:, 0].max() or True else sx, sp.data["base_z"] + sp.data["height"] / 2,
                    sp.name.upper(), ha="center", fontsize=7, weight="bold", alpha=0.8)
    _levels(ax, g, model, ext[0], ext[2])
    s.frame_ax.text(0.6, 1.42, f"Section plane through ({point[0]:.2f}, {point[1]:.2f}) looking {vdir}. Cut elements solid "
                    "(walls coloured by basis); beyond shown in projection.", fontsize=6.5)
    legend_basis(s.frame_ax, 9.5, 1.62)
    s.save()


def sheet_axo(pdf, g, model, number):
    s = Sheet(pdf, g, model, "3D VIEWS", number, "NTS")
    meshes = _meshes_for_views(model)
    et = {k: model.elements[k].type for k in meshes}
    for (vdir, rect, label) in [((-1, 1, -0.8), (0.45, 1.5, 7.9, 8.9), "Overall — from south-east"),
                                ((1, -1, -0.8), (8.35, 5.6, 8.2, 4.9), "Overall — from north-west")]:
        faces, _, _ = V.project_faces(meshes, et, vdir)
        faces = _drop_slab_tops(faces)
        allp = np.vstack([lp for f in faces for lp in f.loops])
        ax = s.fig.add_axes([rect[0] / 17, rect[1] / 11, rect[2] / 17, rect[3] / 11])
        draw_faces(ax, faces, model, lw=0.3, colors=_colors(model, g))
        ax.set_xlim(allp[:, 0].min() - 0.5, allp[:, 0].max() + 0.5)
        ax.set_ylim(allp[:, 1].min() - 0.5, allp[:, 1].max() + 0.5)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(label, fontsize=8)
    # detail: elements near the mudroom / first junction cluster
    mud = [e for e in model.elements.values() if e.type == "roof"]
    focus = min(mud, key=lambda e: e.data["volume"]) if mud else None
    if focus is not None:
        o = np.asarray(focus.data["outline"])
        lo, hi = o.min(0) - 1.0, o.max(0) + 1.0
        ids = [k for k, e in model.elements.items() if e.type in VIEW_TYPES and e.mesh is not None and
               (e.mesh.bounds()[0][:2] <= hi).all() and (e.mesh.bounds()[1][:2] >= lo).all() and e.mesh.bounds()[0][2] < 3.2]
        sub = _meshes_for_views(model, set(ids))
        faces, _, _ = V.project_faces(sub, {k: model.elements[k].type for k in sub}, (-1, 1.3, -0.6))
        allp = np.vstack([lp for f in faces for lp in f.loops])
        ax = s.fig.add_axes([8.35 / 17, 1.5 / 11, 8.2 / 17, 3.9 / 11])
        draw_faces(ax, faces, model, lw=0.35, colors=_colors(model, g))
        ax.set_xlim(allp[:, 0].min() - 0.3, allp[:, 0].max() + 0.3)
        ax.set_ylim(allp[:, 1].min() - 0.3, allp[:, 1].max() + 0.3)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(f"Detail — {focus.name} and adjoining walls (ground storey only)", fontsize=8)
    s.save()


def export_pdf(model: CompiledModel, g: Genome, path: str, export_notes=()) -> list[str]:
    sheets = []
    with PdfPages(path) as pdf:
        sheet_notes(pdf, g, model, list(export_notes)); sheets.append("G-001")
        sheets += sheet_schedule(pdf, g, model)
        for i, st in enumerate(g.storeys()):
            sheet_plan(pdf, g, model, st, f"A-1{i:02d}"); sheets.append(f"A-1{i:02d}")
        sheet_roof(pdf, g, model); sheets.append("A-110")
        sheet_elevations(pdf, g, model, [("SOUTH ELEVATION", (0, 1, 0)), ("NORTH ELEVATION", (0, -1, 0))], "A-201"); sheets.append("A-201")
        sheet_elevations(pdf, g, model, [("EAST ELEVATION", (-1, 0, 0)), ("WEST ELEVATION", (1, 0, 0))], "A-202"); sheets.append("A-202")
        # cut through the tallest part: centroid of the highest floor slab (fallback: wall extents)
        slabs = [e for e in model.by_type("slab") if e.data["kind"] in ("floor", "base")]
        if slabs:
            top = max(slabs, key=lambda e: (round(e.data["top_z"], 3), e.data["area"]))
            from shapely.geometry import Polygon as _SP
            c = _SP(top.data["boundary"]).centroid
            cx, cy = c.x, c.y
        else:
            allx = np.vstack([np.asarray(w.data["plan_polygon"]) for w in model.by_type("wall")])
            cx, cy = (allx.min(0) + allx.max(0)) / 2
        sheet_section(pdf, g, model, "A-A (looking east)", (float(cx) - 0.4, 0.0, 0.0), (1, 0, 0), "A-301"); sheets.append("A-301")
        sheet_section(pdf, g, model, "B-B (looking north)", (0.0, float(cy) + 0.1, 0.0), (0, 1, 0), "A-302"); sheets.append("A-302")
        sheet_axo(pdf, g, model, "A-401"); sheets.append("A-401")
        sheets += sheet_components(pdf, g, model)
        d = pdf.infodict()
        d["Title"] = f"{g.project.name} — model review set (Genome rev {model.genome_revision})"
        d["Creator"] = f"Rebuilt MODEL {model.compiler_version}"
    return sheets
