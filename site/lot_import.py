"""County parcel file -> lot lines in the house's plan coordinates, for the editor's lot check.

    python3 lot_import.py PARCELS.zip PARCEL_ID ASBUILT.genome.json site.json
        [--addresses ADDRESSES.zip] [--setbacks front=50,side=15,rear=50,accessory_side=5,accessory_rear=5]
        [--source "Fairfield County parcels 2026-10-26"]

- PARCELS.zip: the county's parcel shapefile (zip with .shp/.shx/.dbf/.prj), in a state-plane grid in feet or metres.
- The house is oriented from its measured compass bearing (project coordinate_system.true_north_deg, or the
  "facing the road" bearing in its description). Grid north is treated as true north (state-plane convergence
  in Central Ohio is well under 1 degree; the editor's rotate buttons take out the rest).
- Position: with --addresses (county address points) the house's centre goes on its address point; otherwise the
  house is centred in the lot. Either way, nudge it in the editor (Lot -> Move lot) against the aerial photo.
- Edge roles: the edge facing the road is front, the opposite one rear, the rest side (click a label in the editor to change).
"""
import argparse, io, json, math, re, sys, zipfile

import shapefile


def read_zip_shp(path):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    shp = next(n for n in names if n.lower().endswith('.shp'))
    stem = shp[:-4]
    get = lambda ext: io.BytesIO(z.read(next(n for n in names if n.lower() == (stem + ext).lower())))
    prj = next((z.read(n).decode('latin-1') for n in names if n.lower() == (stem + '.prj').lower()), '')
    return shapefile.Reader(shp=get('.shp'), shx=get('.shx'), dbf=get('.dbf')), prj


def unit_m(prj):
    p = prj.lower()
    return 0.3048006096 if 'foot_us' in p or 'us survey foot' in p or 'feet' in p else 0.3048 if 'foot' in p else 1.0


def find_record(r, want, field_hint=None):
    key = re.sub(r'\D', '', want)
    fields = [f[0] for f in r.fields[1:]]
    for i, rec in enumerate(r.iterRecords()):
        for f, v in zip(fields, rec):
            if field_hint and f != field_hint:
                continue
            if isinstance(v, str) and v and re.sub(r'\D', '', v) == key:
                return i, f
    return None, None


def rings(shape):
    parts = list(shape.parts) + [len(shape.points)]
    return [shape.points[parts[k]:parts[k + 1]] for k in range(len(parts) - 1)]


def area(P):
    return sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P))) / 2


def simplify(P, tol):
    """drop near-collinear / duplicate vertices (parcel lines are often digitised with extra points)"""
    P = [p for i, p in enumerate(P) if math.dist(p, P[i - 1]) > 1e-6]
    changed = True
    while changed and len(P) > 3:
        changed = False
        for i in range(len(P)):
            a, b, c = P[i - 1], P[i], P[(i + 1) % len(P)]
            L = math.dist(a, c) or 1e-9
            d = abs((c[0] - a[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (c[1] - a[1])) / L
            if d < tol:
                P.pop(i); changed = True; break
    return P


def house_frame(g):
    """bearing (deg, clockwise from north) of the plan's +y axis, and the 1F footprint box"""
    cs = g['project'].get('coordinate_system', {})
    tn = (cs.get('true_north_deg') or {}).get('value')
    if tn is not None:
        by = (360 - tn) % 360           # true_north_deg = direction of true north measured in plan (ccw from +y) -> +y bearing
    else:
        m = re.search(r'facing the road from the front wall = (\d+)', cs.get('origin_description', ''))
        if not m:
            sys.exit('no compass bearing in the as-built; add coordinate_system.true_north_deg')
        by = (float(m.group(1)) + 180) % 360
    W = [e for e in g['elements'].values() if e['type'] == 'wall' and e.get('exterior')]
    st0 = max({w['storey'] for w in W}, key=lambda s: sum(1 for w in W if w['storey'] == s))
    xs = [p[0] for w in W if w['storey'] == st0 for p in (w['start'], w['end'])]
    ys = [p[1] for w in W if w['storey'] == st0 for p in (w['start'], w['end'])]
    return by, ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2), st0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('parcels'); ap.add_argument('parcel'); ap.add_argument('asbuilt'); ap.add_argument('out')
    ap.add_argument('--addresses'); ap.add_argument('--address-text')
    ap.add_argument('--setbacks', default=''); ap.add_argument('--source', default='county parcel file')
    ap.add_argument('--field')
    ap.add_argument('--house-grid', help='E,N of the house (main storey) centre in the parcel grid, e.g. measured off an aerial — beats the address point')
    ap.add_argument('--plan-bearing', type=float, help='bearing of the plan +y axis (deg); overrides the compass reading')
    ap.add_argument('--no-snap', action='store_true', help="don't square the house to the nearest lot line within 6 deg")
    A = ap.parse_args()
    g = json.load(open(A.asbuilt))
    r, prj = read_zip_shp(A.parcels)
    k, fld = find_record(r, A.parcel, A.field)
    if k is None:
        sys.exit(f'parcel {A.parcel} not found in {A.parcels}')
    um = unit_m(prj)
    R = max(rings(r.shape(k)), key=lambda P: abs(area(P)))
    by, hc, st0 = house_frame(g)
    turn = ''
    if A.plan_bearing is not None:
        by = A.plan_bearing % 360; turn = f'bearing set to {by:.1f} deg'
    elif not A.no_snap:                                  # houses usually sit square to the lot: snap if the compass is close
        best = None
        for i in range(len(R) - 1):
            (x0, y0), (x1, y1) = R[i], R[i + 1]
            if math.dist(R[i], R[i + 1]) < 20: continue
            b = math.degrees(math.atan2(x1 - x0, y1 - y0)) % 90
            d = ((b - by % 90) + 45) % 90 - 45
            if abs(d) < 6 and (best is None or abs(d) < abs(best)): best = d
        if best is not None:
            turn = f'squared to the lot line ({best:+.1f} deg from the compass {by:.1f})'; by = (by + best) % 360
    t = math.radians(by)
    ey = (math.sin(t), math.cos(t))                      # plan +y in grid (E, N)
    ex = (math.sin(t + math.pi / 2), math.cos(t + math.pi / 2))   # plan +x = 90 deg clockwise from +y
    # where the house sits in the grid: its address point, else the lot's centroid
    pt, how = None, 'centred in the lot — move it in the editor'
    if A.house_grid:
        pt = tuple(float(v) for v in A.house_grid.split(',')); how = 'house centre from the aerial'
    elif A.addresses:
        ra, _ = read_zip_shp(A.addresses)
        want = (A.address_text or g['property']['address'].split(',')[0]).upper()
        num, street = want.split(' ', 1)
        fields = [f[0] for f in ra.fields[1:]]
        for i, rec in enumerate(ra.iterRecords()):
            txt = ' '.join(str(v) for v in rec).upper()
            if re.search(r'\b' + re.escape(num) + r'\b', txt) and street.split()[0] in txt:
                s = ra.shape(i); pt = s.points[0]; how = 'house centre on the county address point'; break
    if pt is None:
        a2 = area(R); cx = sum((R[i][0] + R[(i + 1) % len(R)][0]) * (R[i][0] * R[(i + 1) % len(R)][1] - R[(i + 1) % len(R)][0] * R[i][1]) for i in range(len(R))) / (6 * a2)
        cy = sum((R[i][1] + R[(i + 1) % len(R)][1]) * (R[i][0] * R[(i + 1) % len(R)][1] - R[(i + 1) % len(R)][0] * R[i][1]) for i in range(len(R))) / (6 * a2)
        pt = (cx, cy)
    to_plan = lambda p: (hc[0] + ((p[0] - pt[0]) * ex[0] + (p[1] - pt[1]) * ex[1]) * um,
                         hc[1] + ((p[0] - pt[0]) * ey[0] + (p[1] - pt[1]) * ey[1]) * um)
    P = simplify([to_plan(p) for p in (R[:-1] if R[0] == R[-1] else R)], 0.15)
    if area(P) < 0:
        P = P[::-1]
    roles = []
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        L = math.dist(a, b); n_out = ((b[1] - a[1]) / L, -(b[0] - a[0]) / L)       # ccw polygon: outward normal = right of the edge
        roles.append('front' if n_out[1] < -0.7 else 'rear' if n_out[1] > 0.7 else 'side')
    sb = {}
    for kv in filter(None, A.setbacks.split(',')):
        k2, v = kv.split('='); sb[k2.strip()] = float(v)
    acc = []                                             # storeys of detached garages / sheds / barns: accessory setbacks
    for bld in g.get('buildings', []):
        for st in bld.get('storeys', []):
            if st['id'] != st0 and not any(x['id'] == st0 for x in bld.get('storeys', [])) and re.search(r'garage|shed|barn', bld.get('name', '') + st.get('name', '') + st['id'], re.I):
                acc.append(st['id'])
    site = {'lot': {'poly': [[round(x, 3), round(y, 3)] for x, y in P], 'roles': roles, 'pivot': [round(hc[0], 3), round(hc[1], 3)]},
            'setbacks_ft': sb, 'accessory': sorted(set(acc)),
            'source': f"{A.source}, parcel {A.parcel} ({fld}); {how}" + (f'; {turn}' if turn else ''),
            'grid': {'house_centre': pt, 'plan_y_bearing_deg': by, 'unit_m': um}}
    json.dump(site, open(A.out, 'w'), indent=1)
    acres = abs(area(P)) * 10.7639 / 43560
    print(f'lot {len(P)} edges, {acres:.2f} ac, roles {roles}, accessory {site["accessory"]}; {how}')
