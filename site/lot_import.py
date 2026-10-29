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


def gdb_path(path):
    """a county map export as a file geodatabase (.gdb folder, or a .zip holding one) -> the .gdb folder"""
    import pathlib, tempfile
    p = pathlib.Path(path)
    if p.suffix.lower() == '.gdb' and p.is_dir():
        return str(p)
    if p.suffix.lower() == '.zip':
        z = zipfile.ZipFile(p)
        gdbs = sorted({n.split('.gdb/')[0] + '.gdb' for n in z.namelist() if '.gdb/' in n})
        if gdbs:
            d = tempfile.mkdtemp(prefix='gdb-'); z.extractall(d)
            return str(pathlib.Path(d) / gdbs[0])
    return None


def read_gdb(gdb, layer):
    """features of one layer as [(attrs, [ring, ...])] in the layer's grid, + metres per grid unit"""
    import pyogrio
    df = pyogrio.read_dataframe(gdb, layer=layer)
    crs = df.crs.to_wkt() if df.crs is not None else ''
    feats = []
    for _, row in df.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        polys = list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
        rs = [[(x, y) for x, y, *_ in p.exterior.coords] for p in polys if hasattr(p, 'exterior')]
        if not rs:
            rs = [[(c[0], c[1]) for c in geom.coords]]
        feats.append(({k: v for k, v in row.items() if k != 'geometry'}, rs))
    return feats, unit_m(crs)


def gdb_layer(gdb, *names):
    import pyogrio
    have = [str(l[0]) for l in pyogrio.list_layers(gdb)]
    for n in names:
        for h in have:
            if h.lower() == n.lower():
                return h
    for n in names:
        for h in have:
            if n.lower() in h.lower():
                return h
    return None


def plan_footprint(g, st0):
    """the main building's outline in plan metres (outside faces of its outside walls)"""
    from shapely.geometry import LineString
    from shapely.ops import unary_union, polygonize
    W = [e for e in g['elements'].values() if e['type'] == 'wall' and e.get('exterior') and e['storey'] == st0]
    lines = unary_union([LineString([w['start'], w['end']]) for w in W])
    polys = list(polygonize(lines))
    if not polys:
        return None
    t = sorted((w.get('thickness') or {}).get('value', 0.15) for w in W)[len(W) // 2]
    return unary_union(polys).buffer(t / 2, join_style=2)


def fit_footprint(fp_plan, hc, fp_grid, um, by0, span=20.0):
    """bearing + grid point of the plan centre that lay the plan outline best over the county building footprint"""
    from shapely import affinity
    from shapely.geometry import Polygon
    best = None
    base = affinity.translate(fp_plan, -hc[0], -hc[1])
    base = affinity.scale(base, 1 / um, 1 / um, origin=(0, 0))          # plan metres -> grid units
    tgt_c = fp_grid.centroid
    def place(by, dx, dy):
        # plan +y bearing `by`: rotate plan so +y points at by (grid north-up)
        P = affinity.rotate(base, -by, origin=(0, 0))
        c = P.centroid
        return affinity.translate(P, tgt_c.x - c.x + dx, tgt_c.y - c.y + dy)
    def score(P):
        u = P.union(fp_grid).area
        return P.intersection(fp_grid).area / u if u else 0
    k = -span
    while k <= span:
        P = place(by0 + k, 0, 0); s = score(P)
        if best is None or s > best[0]: best = (s, by0 + k, 0.0, 0.0)
        k += 0.5
    step = 2.0
    while step > 0.05:                                                   # local polish of shift + turn
        s0, by, dx, dy = best; better = False
        for dby, ddx, ddy in ((step / 4, 0, 0), (-step / 4, 0, 0), (0, step, 0), (0, -step, 0), (0, 0, step), (0, 0, -step)):
            P = place(by + dby, dx + ddx, dy + ddy); s = score(P)
            if s > best[0]: best = (s, by + dby, dx + ddx, dy + ddy); better = True
        if not better: step /= 2
    s, by, dx, dy = best
    P = place(by, dx, dy)
    Pr = affinity.rotate(base, -by, origin=(0, 0)); c = Pr.centroid
    pt = (tgt_c.x - c.x + dx, tgt_c.y - c.y + dy)                       # where plan point hc lands
    return by % 360, pt, s


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
    ap.add_argument('--no-footprint', action='store_true', help="ignore the county building footprints even if the file has them")
    A = ap.parse_args()
    g = json.load(open(A.asbuilt))
    gdb = gdb_path(A.parcels)
    feat_fp, record = None, {}
    if gdb:                                              # a county map export (file geodatabase): parcels + footprints
        feats, um = read_gdb(gdb, gdb_layer(gdb, 'Parcels', 'parcel'))
        key = re.sub(r'\D', '', A.parcel)
        hit = [(a, rs) for a, rs in feats if any(isinstance(v, str) and v and (re.sub(r'\D', '', v) == key or re.sub(r'\D', '', v) == key[:9] or re.sub(r'\D', '', v)[:9] == key[:9] and len(re.sub(r'\D', '', v)) >= 9) for k2, v in a.items() if (A.field is None or k2 == A.field))]
        if not hit:
            sys.exit(f'parcel {A.parcel} not found in {A.parcels}')
        record, rs = hit[0]; fld = 'map export'
        R = max(rs, key=lambda P: abs(area(P)))
        fl = gdb_layer(gdb, 'Building_Footprints', 'footprint', 'building')
        if fl and not A.no_footprint:
            from shapely.geometry import Polygon
            lot = Polygon(R); fps = [Polygon(r_) for a_, rs_ in read_gdb(gdb, fl)[0] for r_ in rs_ if len(r_) > 3]
            fps = [f for f in fps if f.is_valid and f.intersection(lot).area > 0.5 * f.area]
            if fps: feat_fp = max(fps, key=lambda f: f.area)
    else:
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
    fit = None
    if feat_fp is not None and not A.house_grid and A.plan_bearing is None:
        fpp = plan_footprint(g, st0)
        if fpp is not None:
            by_f, pt_f, iou = fit_footprint(fpp, hc, feat_fp, um, by)
            if iou > 0.6:
                fit = iou; by, pt = by_f, pt_f; turn = ''
                how = f'house laid over the county building footprint ({iou:.0%} overlap)'
                t = math.radians(by)
                ey = (math.sin(t), math.cos(t)); ex = (math.sin(t + math.pi / 2), math.cos(t + math.pi / 2))
    if pt is not None:
        pass
    elif A.house_grid:
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
            'grid': {'house_centre': pt, 'plan_y_bearing_deg': by, 'unit_m': um},
            'parcel_record': {k3: (str(v) if v is not None else None) for k3, v in record.items() if k3 in
                              ('PARCELID', 'CVTTXCD', 'CVTTXDSCRP', 'SITEADDRESS', 'OWNERNME1', 'ACRES', 'STATEDAREA', 'CLASSDSCRP', 'RESYRBLT', 'FLOOD', 'SCHLDSCRP')}}
    json.dump(site, open(A.out, 'w'), indent=1)
    acres = abs(area(P)) * 10.7639 / 43560
    print(f'lot {len(P)} edges, {acres:.2f} ac, roles {roles}, accessory {site["accessory"]}; {how}')
