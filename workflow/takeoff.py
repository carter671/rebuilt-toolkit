"""Design model -> material takeoff (quantities only), for the rehab budget workbook.

    python3 takeoff.py AS_BUILT.genome.json DESIGN.genome.json DESIGN.layout.json OUT/takeoff.json [--name "Design A"] [--address "..."]

DESIGN.genome.json and .layout.json come from `python3 -m rebuilt.design.editor_ops AS_BUILT DESIGN.json OUT.genome.json OUT.layout.json`.
Assumes a full (gut) interior rehab: every room except garages gets finishes, existing windows are replaced,
open doorways get doors. Everything is a quantity; prices live in build_xlsx.py / the pricebook.
"""
import argparse, json, math, sys
import numpy as np
from shapely.geometry import Polygon, Point, LineString
import os, pathlib; sys.path.insert(0, os.environ.get('REBUILT_SRC', str(pathlib.Path(__file__).resolve().parents[1] / 'src')))
from rebuilt.genome.io import parse
from rebuilt.model.compile import compile_genome
from rebuilt.takeoff.quantities import quantities, _up_area

ap = argparse.ArgumentParser()
ap.add_argument('asbuilt'); ap.add_argument('design'); ap.add_argument('layout'); ap.add_argument('out')
ap.add_argument('--name', default='Design'); ap.add_argument('--address', default='')
A = ap.parse_args()

F, SF, IN = 3.28084, 10.7639, 0.0254
E0 = json.load(open(A.asbuilt))['elements']
GG = json.load(open(A.design))
G = GG['elements']
LAY = json.load(open(A.layout))
g, _ = parse(GG)
M = compile_genome(g, 'review')
Q = quantities(M, GG)
C = M.elements
GAR = lambda name: 'garage' in name.lower()


def face_area(ce):
    """one face of a wall in sf (gable triangles included, openings cut out)"""
    v = ce.mesh.verts[ce.mesh.tris]
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    a = np.linalg.norm(n, axis=1) / 2
    nz = np.divide(np.abs(n[:, 2]), 2 * a, out=np.zeros_like(a), where=a > 0)
    return float(a[nz < 0.05].sum() / 2 * SF)


def collinear(p, a, b):
    return abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) / max(math.dist(a, b), 1e-9) < 0.02


room_polys = [(r['name'], r['storey'], Polygon(G[r['id']]['boundary'])) for r in Q['rooms']]


def rooms_beside(w):
    """names of rooms on either side of a wall (sampled at 1/4, 1/2, 3/4)"""
    s, e = w['start'], w['end']
    L = math.dist(s, e) or 1
    d = ((e[0] - s[0]) / L, (e[1] - s[1]) / L)
    n = (-d[1], d[0])
    off = w['thickness']['value'] / 2 + 0.2
    sides = {1: set(), -1: set()}
    for f in (0.1, 0.25, 0.5, 0.75, 0.9):
        p = (s[0] + d[0] * L * f, s[1] + d[1] * L * f)
        for sg in (1, -1):
            q = Point(p[0] + n[0] * off * sg, p[1] + n[1] * off * sg)
            for nm, st, P in room_polys:
                if P.contains(q):          # any storey: a garage beside the house sits on its own level
                    sides[sg].add(nm)
    return sides


# ------------------------------------------------------------------ walls / framing
walls = []
for wid, w in G.items():
    if w['type'] != 'wall':
        continue
    L = math.dist(w['start'], w['end'])
    o = E0.get(wid)
    base = wid[:-4] if wid.endswith('-OUT') else None          # a gable-end wall split at the extended roof
    if base and base in E0:
        o0 = E0[base]
        L0 = math.dist(o0['start'], o0['end'])
        cur = math.dist(G[base]['start'], G[base]['end']) if base in G else 0
        status, new_len = 'extended', max(0.0, L + cur - L0)
    elif o is None:
        status, new_len = 'new', L
    elif o['start'] == w['start'] and o['end'] == w['end']:
        status, new_len = 'existing', 0
    else:
        L0 = math.dist(o['start'], o['end'])
        if collinear(w['start'], o['start'], o['end']) and collinear(w['end'], o['start'], o['end']):
            status, new_len = ('extended', L - L0) if L - L0 > 0.15 else ('trimmed' if L0 - L > 0.15 else 'existing', 0)
        else:
            status, new_len = 'moved', L
    ce = C.get(wid)
    area = face_area(ce) if ce else 0
    sides = rooms_beside(w)
    beside = sides[1] | sides[-1]
    walls.append({'id': wid, 'name': w.get('name', wid), 'storey': w['storey'], 'ext': bool(w.get('exterior')),
                  'len_ft': L * F, 'new_ft': new_len * F, 'status': status, 'face_sf': area, 'avg_h_ft': area / (L * F) if L else 0,
                  'beside': sorted(beside), 'side_a': sorted(sides[1]), 'side_b': sorted(sides[-1]), 'openings': [k for k, e in G.items() if e['type'] == 'opening' and e['host'] == wid]})

framing = []
for w in walls:
    if w['new_ft'] < 0.5:
        continue
    lf = w['new_ft']
    sf = w['face_sf'] * (lf / w['len_ft'])
    framing.append({'wall': w['name'], 'id': w['id'], 'storey': w['storey'], 'type': '2x6 exterior' if w['ext'] else '2x4 partition',
                    'lf': lf, 'sf': sf, 'openings': len(w['openings']), 'status': w['status'],
                    'new_outside_face': w['ext'] and bool(set(w['beside']) - set()) or w['ext']})

# outside walls next to a finished (non-garage) room get insulation; an outside wall that now has rooms on both
# sides (the old back wall behind an addition) does not
insulate = []
for w in walls:
    if not w['ext'] or not w['face_sf']:
        continue
    same = {n for n, st, P in room_polys if st == w['storey']}
    fa = [b for b in w['side_a'] if not GAR(b) and b in same]; fb = [b for b in w['side_b'] if not GAR(b) and b in same]
    fin = fa or fb
    if (fa and not fb) or (fb and not fa):     # finished room on one side only: it faces outside or a garage
        insulate.append({'wall': w['name'], 'id': w['id'], 'storey': w['storey'], 'sf': w['face_sf'], 'rooms': ', '.join(fin)})

firewall = [{'wall': w['name'], 'sf': w['face_sf']} for w in walls if w['face_sf'] and
            ((any(GAR(x) for x in w['side_a']) and any(not GAR(x) for x in w['side_b'])) or (any(GAR(x) for x in w['side_b']) and any(not GAR(x) for x in w['side_a'])))
            and any(GAR(x) for x in (w['side_a'] + w['side_b'])) and w['storey'] == next((st for n, st, P in room_polys if GAR(n)), None)]

# demolition: walls taken out, moved off their old line, or shortened (a gap cut out)
demo_int, demo_ext = [], []
st_by = {w['id']: w for w in walls}
for wid, o in E0.items():
    if o['type'] != 'wall':
        continue
    L0 = math.dist(o['start'], o['end']) * F
    w = st_by.get(wid)
    if w is None:
        lf, why = L0, 'taken out'
    elif w['status'] == 'moved':
        lf, why = L0, 'moved (old wall comes down)'
    elif w['status'] == 'trimmed':
        lf, why = L0 - w['len_ft'] - sum(x['len_ft'] for x in walls if x['id'] not in E0 and x['storey'] == o['storey'] and collinear(G[x['id']]['start'], o['start'], o['end']) and collinear(G[x['id']]['end'], o['start'], o['end'])), 'part cut out'
    else:
        continue
    if lf > 0.5:
        (demo_ext if o.get('exterior') else demo_int).append({'name': f"{o.get('name', wid)} — {why}", 'len_ft': lf})

# ------------------------------------------------------------------ rooms
vault = {sid for sid, s in G.items() if s['type'] == 'space' and 'vaulted' in ((s.get('info') or {}).get('notes') or '')}
roof_list = [(k, r) for k, r in G.items() if r['type'] == 'roof']


def pitch_over(pt, st):
    for k, r in roof_list:
        if r['storey'] == st and Polygon(r['footprint']).contains(Point(pt)):
            return r['pitch']['value']
    return 5 / 12


rooms = []
for r in Q['rooms']:
    nm = r['name']; low = nm.lower()
    fl = None if GAR(nm) else 'tile' if any(k in low for k in ('bath', 'laundry', 'utility', 'mud')) else 'carpet / turf' if 'sim' in low else 'LVP'
    c = Polygon(G[r['id']]['boundary']).representative_point()
    v = r['id'] in vault
    p = pitch_over((c.x, c.y), r['storey'])
    rooms.append({'name': nm, 'storey': r['storey'], 'floor_sf': r['floor_sf'], 'perim_lf': r['perimeter_lf'], 'height_ft': r['height_ft'],
                  'wall_sf': r['wall_sf'], 'base_lf': r['base_lf'],
                  'ceiling': 'vaulted' if v else f"flat {int(r['height_ft'])}'-{round((r['height_ft'] % 1) * 12)}\"",
                  'ceiling_sf': r['ceiling_sf'] * (math.sqrt(1 + p * p) * 1.12 if v else 1), 'floor': fl, 'finished': not GAR(nm)})

# ------------------------------------------------------------------ openings (type + default action)
ops = []
for o in Q['openings']:
    go = G[o['id']]
    nm = go.get('name', o['id']); low = nm.lower()
    new = o['id'] not in E0
    rms = [n for n, st, P in room_polys if P.distance(Point(o['centre'][0], o['centre'][1])) < 0.3]
    host = G[go['host']]
    outside = bool(host.get('exterior')) and len([r for r in rms]) <= 1
    k = o['kind']
    if k == 'window':
        ty, act = 'Window', 'New' if new else 'Replace'
    elif k == 'door' and o['w_in'] >= 72 and (('garage' in low) or ('overhead' in low) or ('roll' in low) or any(GAR(r) for r in rms)):
        ty = 'Garage door'
        moved = host.get('phase') == 'new' and go['host'] in E0
        act = 'New' if new else ('Keep' if len(rms) > 1 else ('Reinstall' if moved else 'Keep'))
    elif k == 'door' and outside:
        ty = 'Exterior door'
        act = 'New' if new or (host.get('phase') == 'new' and go['host'] in E0) else 'Keep'
    elif k == 'door':
        ty, act = 'Interior door', 'New' if new else 'Keep'
    else:
        closet = 'closet' in low and 'doorway' not in low
        ty = 'Closet opening' if closet else 'Doorway'
        if closet:
            act = 'Leave open' if o['w_in'] < 24 else 'Bifold'
        else:
            act = 'Cased' if ('cased' in low or o['w_in'] > 40 or any('kitchen' in r.lower() or 'living' in r.lower() for r in rms) and len(rms) > 1 and not any(w in ' '.join(rms).lower() for w in ('bed', 'bath', 'closet'))) else 'Add door'
    cut = new and go['host'] in E0 and G[go['host']].get('phase') != 'new'      # a new opening cut into an existing wall
    ops.append({'id': o['id'], 'name': nm, 'type': ty, 'action': act, 'w_in': o['w_in'], 'h_in': o['h_in'],
                'sill_in': round(go['sill']['value'] / IN) if go.get('sill') and k == 'window' else None,
                'rooms': ' / '.join(rms), 'new': new, 'cut_in_existing_wall': cut})

# ------------------------------------------------------------------ roofs + edges
roofs = []
E0roofs = {k: r for k, r in E0.items() if r['type'] == 'roof'}
for rid, ce in C.items():
    if ce.type != 'roof':
        continue
    gr = G[rid]
    fp = gr['footprint']; n = len(fp); p = gr['pitch']['value']
    related = [Polygon(G[o]['footprint']) for o in (gr.get('trim_by') or [])] + \
              [Polygon(x['footprint']) for x in G.values() if x['type'] == 'roof' and rid in (x.get('trim_by') or [])]
    def live_len(a, b):
        if not related:
            return math.dist(a, b) * F
        k = 40
        ok = sum(1 for j in range(k) if not any(P.buffer(-0.05).contains(Point(a[0] + (b[0] - a[0]) * (j + .5) / k, a[1] + (b[1] - a[1]) * (j + .5) / k)) for P in related))
        return math.dist(a, b) * F * ok / k
    lens = [live_len(fp[i], fp[(i + 1) % n]) for i in range(n)]
    roles = gr['edge_roles']
    eave = sum(l for l, r in zip(lens, roles) if r == 'eave')
    rake = sum(l for l, r in zip(lens, roles) if r == 'rake') * math.sqrt(1 + p * p)
    abut = sum(l for l, r in zip(lens, roles) if r == 'abut')
    n_eave = roles.count('eave')
    ridge = max(l for l, r in zip(lens, roles) if r == 'eave') if n_eave >= 2 else 0
    changed = rid not in E0roofs or E0roofs[rid]['footprint'] != gr['footprint'] or E0roofs[rid]['edge_roles'] != gr['edge_roles']
    span_ft = max(abs((q[0] - fp[0][0]) * 0 + 0) for q in fp)  # placeholder, set below
    # run from eave to ridge (or to the high edge for a shed)
    k = roles.index('eave'); a, b = fp[k], fp[(k + 1) % n]
    Le = math.dist(a, b); u = ((b[0] - a[0]) / Le, (b[1] - a[1]) / Le); nv = (-u[1], u[0])
    W = max(abs((q[0] - a[0]) * nv[0] + (q[1] - a[1]) * nv[1]) for q in fp) * F
    run = W / 2 if n_eave >= 2 else W
    roofs.append({'id': rid, 'name': gr.get('name', rid), 'pitch_in12': p * 12, 'sf': _up_area(ce.mesh) * SF, 'eave_lf': eave, 'rake_lf': rake,
                  'abut_lf': abut, 'ridge_lf': ridge, 'run_ft': run, 'length_ft': Le * F, 'form': 'gable' if n_eave >= 2 else 'shed',
                  'tied_in': bool(gr.get('trim_by')), 'new': changed, 'storey': gr['storey'], 'existing_id': rid in E0roofs})
# overlap: where a tied-in roof's run-in covers part of the host roof, keep the area on the tie-in only
for r in roofs:
    gr = G[r['id']]
    for host in gr.get('trim_by') or []:
        hp = Polygon(G[host]['footprint'])
        inter = Polygon(gr['footprint']).intersection(hp).area * SF * math.sqrt(1 + (r['pitch_in12'] / 12) ** 2)
        h = next(x for x in roofs if x['id'] == host)
        if r['form'] == 'gable' and r['new'] and host != r['id']:   # a new tie-in gable runs on over the host: the host is covered there
            h['sf'] = max(0.0, h['sf'] - inter * 0.6)

valleys = sum(2 * r['run_ft'] * 1.25 for r in roofs if r['tied_in'] and r['form'] == 'gable')
edges = {
    'gutter_lf': sum(r['eave_lf'] for r in roofs),
    'drip_lf': sum(r['eave_lf'] + r['rake_lf'] for r in roofs),
    'ridge_lf': sum(r['ridge_lf'] for r in roofs),
    'valley_lf': valleys,
    'step_lf': sum(r['abut_lf'] for r in roofs if r['new']),
    'soffit_lf': sum(r['eave_lf'] + r['rake_lf'] for r in roofs if r['new']),
}
edges['downspout_lf'] = math.ceil(edges['gutter_lf'] / 35) * 10

# ------------------------------------------------------------------ cabinets, fixtures, beams, slabs
items = []
for k, e in G.items():
    if e['type'] == 'component' and k.startswith('N-I-') and e['info']['category'] not in ('bed', 'nightstand', 'dresser', 'sofa', 'dining table'):
        at = e['placement']['at']
        rm = next((n for n, st, P in room_polys if P.buffer(0.05).contains(Point(at))), '')
        items.append({'id': k, 'name': e['name'], 'cat': e['info']['category'], 'w_in': round(e['size']['w']['value'] / IN),
                      'd_in': round(e['size']['d']['value'] / IN), 'h_in': round(e['size']['h']['value'] / IN), 'room': rm})
toilet_existing = []
for k, c in G.items():
    if c['type'] == 'component' and 'toilet' in c.get('name', '').lower() and not k.startswith('N-I-') and (c.get('placement') or {}).get('at'):
        at = c['placement']['at']
        toilet_existing.append(next((n for n, st, P in room_polys if P.buffer(0.05).contains(Point(at))), ''))
beams = [{'name': e['name'], 'len_ft': e['size']['w']['value'] * F, 'depth_in': e['size']['h']['value'] / IN, 'count': 1}
         for k, e in G.items() if e['type'] == 'component' and k.startswith('N-BM')]
if vault:                       # one structural ridge beam per roof with vaulted rooms under it (rafter roofs)
    for k, r in roof_list:
        under = [s for s in vault if r['storey'] == G[s]['storey'] and Polygon(r['footprint']).intersects(Polygon(G[s]['boundary']))]
        sub = ((r.get('info') or {}).get('subtype') or '')
        if under and 'truss' not in sub and r['id'] in E0roofs and (r['edge_roles'].count('eave') >= 2):
            Lr = max(math.dist(r['footprint'][i], r['footprint'][(i + 1) % len(r['footprint'])]) for i in range(len(r['footprint']))) * F
            beams.append({'name': f'Structural ridge beam for the vaulted ceilings ({Lr:.0f} ft ridge)', 'len_ft': Lr, 'depth_in': 16,
                          'count': max(1, math.ceil(Lr / 20)), 'ridge': True})


# ------------------------------------------------------------------ structure: first-pass beam / header / rafter / footing sizes
# Same rules as the editor (rebuilt.engineering): rafters bear on the eaves and on a ridge beam when a room under the roof
# is vaulted; ceiling joists bear on the eaves and on every beam running the same way; a beam at an old outside wall that an
# addition moved out also carries half the run to the new outside wall.
from rebuilt import engineering as ENG
FT_ = F
def _frame(r):
    fp, roles = r['footprint'], r['edge_roles']; k = roles.index('eave'); a, b = fp[k], fp[(k + 1) % len(fp)]
    L = math.dist(a, b); u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L); nv = (-u[1], u[0])
    cx = sum(q[0] for q in fp) / len(fp) - a[0]; cy = sum(q[1] for q in fp) / len(fp) - a[1]
    if cx * nv[0] + cy * nv[1] < 0: nv = (-nv[0], -nv[1])
    W = max((q[0] - a[0]) * nv[0] + (q[1] - a[1]) * nv[1] for q in fp)
    return {'a': a, 'u': u, 'v': nv, 'W': W, 'n_eave': roles.count('eave'), 'oh': (r.get('overhang') or {}).get('value', 0.3)}
def _dot(p, a, d): return (p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]
def _has_ridge(k, r):
    return 'truss' not in ((r.get('info') or {}).get('subtype') or '') and any(r['storey'] == G[s]['storey'] and Polygon(r['footprint']).intersects(Polygon(G[s]['boundary']).buffer(-0.1)) for s in vault)
beam_els = {k: e for k, e in G.items() if e['type'] == 'component' and k.startswith('N-BM')}
def _seg(e):
    at, L, t = e['placement']['at'], e['size']['w']['value'], math.radians(e['placement'].get('rotation', 0))
    d = (math.cos(t), math.sin(t)); return [at[0] - d[0] * L / 2, at[1] - d[1] * L / 2], [at[0] + d[0] * L / 2, at[1] + d[1] * L / 2], d
def _half(v, sup):
    xs = sorted(x for x in sup if abs(x - v) > 0.3); p = [x for x in xs if x < v]; n = [x for x in xs if x > v]
    return ((v - p[-1]) if p else 0) + ((n[0] - v) if n else 0)
def tributary(s, e, d, st, ext, skip=None):
    mid = [(s[0] + e[0]) / 2, (s[1] + e[1]) / 2]
    for k, r in roof_list:
        if r['storey'] != st or 'eave' not in r['edge_roles']: continue
        F = _frame(r)
        if abs(d[0] * F['u'][0] + d[1] * F['u'][1]) < 0.95: continue
        v = _dot(mid, F['a'], F['v'])
        if v < -1.0 or v > F['W'] + 1.0: continue
        par = lambda dd: abs(dd[0] * F['u'][0] + dd[1] * F['u'][1]) > 0.95
        bsup = [_dot([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], F['a'], F['v']) for kk, be in beam_els.items() if kk != skip and be['storey'] == st for a, b, dd in [_seg(be)] if par(dd)]
        ceil, roof = _half(v, [0, F['W']] + bsup) / 2, 0.0
        if ext:
            roof = _half(v, [0, F['W'] / 2, F['W']] if (_has_ridge(k, r) and F['n_eave'] >= 2) else [0, F['W']]) / 2
            out = -1 if v < F['W'] / 2 else 1
            us = sorted([_dot(s, F['a'], F['u']), _dot(e, F['a'], F['u'])]); far = []
            for w in G.values():
                if w['type'] != 'wall' or not w.get('exterior') or w['storey'] != st: continue
                wd = (w['end'][0] - w['start'][0], w['end'][1] - w['start'][1]); wl = math.hypot(*wd) or 1
                if not par((wd[0] / wl, wd[1] / wl)): continue
                ws = sorted([_dot(w['start'], F['a'], F['u']), _dot(w['end'], F['a'], F['u'])])
                if min(ws[1], us[1]) - max(ws[0], us[0]) <= 0.5: continue
                x = (_dot([(w['start'][0] + w['end'][0]) / 2, (w['start'][1] + w['end'][1]) / 2], F['a'], F['v']) - v) * out
                if 0.5 < x < 8: far.append(x)
            if far: roof += min(far) / 2; ceil += min(far) / 2
            else: roof += F['oh']
        return roof * FT_, ceil * FT_, k, F
    return 0.0, 4.0, None, None
structure = {'beams': [], 'headers': [], 'rafters': [], 'loads': ENG.LOADS, 'soil_psf': ENG.SOIL_PSF,
             'note': 'First-pass sizes (simple spans, uniform load, IRC defaults). Not an engineered design — engineer to confirm.'}
for k, e in beam_els.items():
    s, en, d = _seg(e); wall = ((e.get('info') or {}).get('notes') or '').replace('replaces wall', '').strip(); ext = bool(E0.get(wall, {}).get('exterior'))
    rt, ct, rk, _ = tributary(s, en, d, e['storey'], ext, skip=k)
    rec = ENG.size_beam(e['name'], e['size']['w']['value'] * F, rt, ct, have_depth_in=e['size']['h']['value'] / IN,
                        have_plies=max(2, round(e['size']['d']['value'] / 0.04445)))
    rec['id'] = k; structure['beams'].append(rec)
for k, r in roof_list:                 # ridge beams for vaulted rooms under a rafter roof
    if r['edge_roles'].count('eave') >= 2 and _has_ridge(k, r) and k in E0roofs:
        Fr = _frame(r); Lr = max(math.dist(r['footprint'][i], r['footprint'][(i + 1) % len(r['footprint'])]) for i in range(len(r['footprint']))) * F
        n = max(1, math.ceil(Lr / 20)); rec = ENG.size_beam(f"Ridge beam, {r.get('name', k)}", Lr / n, Fr['W'] / 2 * F, 0)
        rec.update({'id': 'ridge:' + k, 'count': n, 'ridge': True}); structure['beams'].append(rec)
for o in ops:                          # headers over new or widened openings in walls that hold the roof edge
    if not o['new']: continue
    go = G[o['id']]; w = G.get(go['host']) or {}
    if w.get('type') != 'wall' or not w.get('exterior'): continue
    wd = (w['end'][0] - w['start'][0], w['end'][1] - w['start'][1]); wl = math.hypot(*wd) or 1
    rt, ct, rk, Fr = tributary(w['start'], w['end'], (wd[0] / wl, wd[1] / wl), w['storey'], True)
    if rk is None: continue
    tl = ENG.beam_load(rt, ct); h = ENG.sawn_header(o['w_in'] / 12 + 0.25, *tl)
    structure['headers'].append({'id': o['id'], 'name': o['name'], 'w_in': o['w_in'], 'load_plf': round(tl[0]), 'size': h['label'] if h else 'engineered header'})
for r in roofs:                        # rafters for new roofs
    if r['new'] and 'truss' not in ((G[r['id']].get('info') or {}).get('subtype') or ''):
        # clear span = the longest stretch between supports under the slope: eaves / high edge, the ridge (gables),
        # beams and outside walls running the same way (a slope carried out over an old back wall bears on its beam)
        gr = G[r['id']]; Fr = _frame(gr); sup = [0, Fr['W']] + ([Fr['W'] / 2] if Fr['n_eave'] >= 2 else [])
        par = lambda dd: abs(dd[0] * Fr['u'][0] + dd[1] * Fr['u'][1]) > 0.95
        for kk, be in beam_els.items():
            a2, b2, dd = _seg(be)
            if be['storey'] == gr['storey'] and par(dd) and Polygon(gr['footprint']).buffer(-0.05).intersects(LineString([a2, b2])): sup.append(_dot([(a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2], Fr['a'], Fr['v']))
        sup = sorted(x for x in sup if -0.01 <= x <= Fr['W'] + 0.01); span = max(y - x for x, y in zip(sup, sup[1:])) * F
        rf = ENG.rafter(span, 16, r['pitch_in12'] / 12)
        structure['rafters'].append({'roof': r['id'], 'name': r['name'], 'span_ft': round(span, 1), 'pitch_in12': round(r['pitch_in12'], 1), 'size': rf['label'] if rf else 'engineered (trusses or LVL rafters)'})
        r['rafter'] = rf['size'] if rf else None
for b in beams:                        # the beam list in the budget uses the sized members
    m = next((x for x in structure['beams'] if x['name'] == b['name'] or (b.get('ridge') and x.get('ridge'))), None)
    if m and m['need']:
        b['depth_in'] = m['need']['depth_in']; b['plies'] = m['need']['plies']; b['size'] = m['need']['label']
        b['post'] = m['footing']['post']; b['pad'] = m['footing']['label']; b['reaction_lb'] = m['reaction_lb']

slabs = [{'name': e['name'], 'sf': Polygon(e['boundary']).area * SF} for k, e in G.items() if e['type'] == 'slab' and k not in E0]
for k, r in E0roofs.items():     # a building made bigger by moving whole walls (its roof stretched): new floor for the added area
    if k in G and G[k]['footprint'] != r['footprint']:
        grow = (Polygon(G[k]['footprint']).area - Polygon(r['footprint']).area) * SF
        if grow > 20:
            nm = 'Garage' if r['storey'] != '1F' and any(GAR(n) for n, st, P in room_polys if st == r['storey']) else r['storey']
            slabs.append({'name': f'{nm} slab + footings for the enlarged area', 'sf': grow, 'stretched': True})

# design scope items that are not otherwise measured (meter / AC moves, chimney, filled stairwell, closed openings...)
SPECIAL = {'meter_relocate', 'ac_relocate', 'chimney_remove', 'dryer_vent', 'equip_relocate', 'frame_floor', 'opening_close',
           'opening_widen', 'gas_relocate', 'cab_bumpout', 'trash_pullout', 'lazy_susan', 'fridge_panel', 'stair_new', 'fireplace', 'patio', 'front_porch', 'driveway', 'culvert'}
extras = []
for x in LAY:
    for ln in x['options']['do']['lines']:
        if ln['key'] in SPECIAL:
            extras.append({'label': x['label'], 'key': ln['key'], 'qty': ln['qty'], 'note': ln.get('note', '')})
roof_strip = sum(ln['qty'] for x in LAY for ln in x['options']['do']['lines'] if ln['key'] == 'demo_select' and x['id'].startswith('layout:addition'))

out = {'name': A.name, 'address': A.address or Q['address'], 'rooms': rooms, 'openings': ops, 'roofs': roofs, 'edges': edges, 'walls': walls,
       'framing': framing, 'insulate': insulate, 'firewall': firewall, 'demo_ext': demo_ext, 'demo_int': demo_int, 'items': items,
       'existing_toilets': toilet_existing, 'beams': beams, 'slabs': slabs, 'extras': extras, 'roof_strip_sf': roof_strip,
       'vaulted_rooms': len(vault), 'structure': structure, 'totals': Q['totals']}
json.dump(out, open(A.out, 'w'), indent=1, default=float)
print(f"{len(rooms)} rooms, {len(ops)} openings, {len(roofs)} roofs, {len(framing)} framed walls, {len(beams)} beams, {len(slabs)} new floors, {len(extras)} extra scope lines")
for r in roofs:
    print(f"  roof {r['id']:14} {r['sf']:6.0f} sf {r['pitch_in12']:.1f}/12 {'new' if r['new'] else 'existing'} eave {r['eave_lf']:.0f} rake {r['rake_lf']:.0f} ridge {r['ridge_lf']:.0f}")
print('  edges', {k: round(v) for k, v in edges.items()})
print('  insulate', round(sum(w['sf'] for w in insulate)), 'sf on', len(insulate), 'walls')
print('  demo int', round(sum(d['len_ft'] for d in demo_int)), 'ext', round(sum(d['len_ft'] for d in demo_ext)))
print('  slabs', [(s['name'], round(s['sf'])) for s in slabs])
print('  extras', [(e['key'], e['qty']) for e in extras])
from collections import Counter
print('  openings', Counter((o['type'], o['action']) for o in ops))
