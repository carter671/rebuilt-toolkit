"""Setback / lot-line check of a design genome against site.json (same rules as the editor's Lot check).

    python3 lot_check.py site.json ASBUILT.genome.json DESIGN.genome.json [--adj dx,dy,rot]

--adj is the editor's saved lot nudge (db doc site/<base id>: adj {dx, dy, rot}); pass it so both agree.
Returns / prints: new construction over a setback (needs a variance or a design change) and existing walls
already inside one (legal nonconforming).
"""
import argparse, json, math

FT = 0.3048


def lot_poly(site, adj=None):
    a = adj or {}
    c, s = math.cos(math.radians(a.get('rot', 0))), math.sin(math.radians(a.get('rot', 0)))
    pv = site['lot'].get('pivot', [0, 0])
    return [[pv[0] + (p[0] - pv[0]) * c - (p[1] - pv[1]) * s + a.get('dx', 0), pv[1] + (p[0] - pv[0]) * s + (p[1] - pv[1]) * c + a.get('dy', 0)]
            for p in site['lot']['poly']]


def _area(P):
    return sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P))) / 2


def _seg_d(q, a, b):
    ab = (b[0] - a[0], b[1] - a[1]); L2 = ab[0] ** 2 + ab[1] ** 2 or 1e-12
    t = max(0, min(1, ((q[0] - a[0]) * ab[0] + (q[1] - a[1]) * ab[1]) / L2))
    return math.dist(q, (a[0] + ab[0] * t, a[1] + ab[1] * t))


def _inside(p, P):
    c = False
    for i in range(len(P)):
        (xi, yi), (xj, yj) = P[i], P[i - 1]
        if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
            c = not c
    return c


def check(site, asbuilt, design, adj=None):
    P = lot_poly(site, adj); sb = site.get('setbacks_ft') or {}; roles = site['lot'].get('roles') or ['side'] * len(P)
    acc = set(site.get('accessory') or [])
    walls = lambda g: [e for e in g['elements'].values() if e['type'] == 'wall' and e.get('exterior')]
    base = walls(asbuilt)
    on_base = lambda q, st: any(b['storey'] == st and _seg_d(q, b['start'], b['end']) < 0.05 for b in base)
    worst, outside = {}, []
    for w in walls(design):
        s, e, st = w['start'], w['end'], w['storey']
        if not (_inside(s, P) and _inside(e, P)):
            outside.append(w.get('name', w['id'])); continue
        t = (w.get('thickness') or {}).get('value', 0.15); L = math.dist(s, e); n = max(2, math.ceil(L / 0.1))
        for i in range(len(P)):
            role = roles[i]
            need = sb.get('accessory_' + role) if st in acc and sb.get('accessory_' + role) is not None else sb.get(role)
            if not need:
                continue
            need *= FT
            for k in range(n + 1):
                q = (s[0] + (e[0] - s[0]) * k / n, s[1] + (e[1] - s[1]) * k / n)
                d = _seg_d(q, P[i], P[(i + 1) % len(P)]) - t / 2
                if d >= need - 0.02:
                    continue
                new = not on_base(q, st)
                key = ('new' if new else 'old', i)
                if key not in worst or d < worst[key]['d']:
                    worst[key] = {'d': d, 'need': need, 'role': role, 'wall': w.get('name', w['id']), 'new': new}
    res = {'over_new': [], 'over_existing': [], 'outside_lot': outside}
    for (kind, i), x in sorted(worst.items(), key=lambda kv: kv[1]['d']):
        res['over_new' if kind == 'new' else 'over_existing'].append(
            {'wall': x['wall'], 'line': x['role'], 'distance_ft': round(x['d'] / FT, 1), 'setback_ft': round(x['need'] / FT, 1), 'over_ft': round((x['need'] - x['d']) / FT, 1)})
    if sb.get('max_coverage_pct'):
        res['lot_sf'] = round(abs(_area(P)) / FT ** 2)
    return res


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('site'); ap.add_argument('asbuilt'); ap.add_argument('design'); ap.add_argument('--adj')
    A = ap.parse_args()
    adj = dict(zip(('dx', 'dy', 'rot'), map(float, A.adj.split(',')))) if A.adj else None
    r = check(json.load(open(A.site)), json.load(open(A.asbuilt)), json.load(open(A.design)), adj)
    print(json.dumps(r, indent=1))
