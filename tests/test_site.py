"""Lot import (county parcel shapefile -> plan coordinates) and the setback check."""
import importlib.util, json, math, pathlib, sys, zipfile

import pytest
shapefile = pytest.importorskip('shapefile')
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'site'))
import lot_check  # noqa: E402

LI = ROOT / 'site' / 'lot_import.py'


def _genome(by=28):
    w = lambda i, s, e: {'type': 'wall', 'id': i, 'storey': '1F', 'exterior': True, 'start': s, 'end': e, 'thickness': {'value': 0.15}}
    els = {k: w(k, s, e) for k, s, e in [('F', [0, 0], [10, 0]), ('R', [10, 0], [10, 8]), ('B', [10, 8], [0, 8]), ('L', [0, 8], [0, 0])]}
    return {'project': {'coordinate_system': {'true_north_deg': {'value': (360 - by) % 360}}}, 'property': {'address': '1 Main St'},
            'buildings': [{'id': 'B1', 'name': 'House', 'storeys': [{'id': '1F'}]}], 'elements': els}


def test_import_orients_and_places(tmp_path):
    t = math.radians(28); ey = (math.sin(t), math.cos(t)); ex = (math.sin(t + math.pi / 2), math.cos(t + math.pi / 2))
    O = (1.85e6, 7e5); F = 1 / 0.3048
    G = lambda x, y: (O[0] + (x * ex[0] + y * ey[0]) * F, O[1] + (x * ex[1] + y * ey[1]) * F)   # plan metres -> grid feet
    w = shapefile.Writer(str(tmp_path / 'p'), shapeType=shapefile.POLYGON); w.field('PIN', 'C', 20)
    w.poly([[G(-10, -15), G(-10, 40), G(30, 40), G(30, -15), G(-10, -15)]]); w.record('037-0220100'); w.close()
    (tmp_path / 'p.prj').write_text('UNIT["Foot_US",0.3048006096012192]')
    a = shapefile.Writer(str(tmp_path / 'a'), shapeType=shapefile.POINT); a.field('NUM', 'C', 8); a.field('ST', 'C', 20)
    a.point(*G(5, 4)); a.record('1', 'MAIN ST'); a.close()
    for stem, exts in (('p', 'shp shx dbf prj'), ('a', 'shp shx dbf')):
        with zipfile.ZipFile(tmp_path / f'{stem}.zip', 'w') as z:
            for e in exts.split():
                z.write(tmp_path / f'{stem}.{e}', f'{stem}.{e}')
    gp = tmp_path / 'g.json'; gp.write_text(json.dumps(_genome()))
    import subprocess
    subprocess.run([sys.executable, str(LI), str(tmp_path / 'p.zip'), '0370220100', str(gp), str(tmp_path / 's.json'),
                    '--addresses', str(tmp_path / 'a.zip'), '--setbacks', 'front=30,side=10,rear=30'], check=True)
    site = json.loads((tmp_path / 's.json').read_text())
    xs = sorted(round(p[0], 1) for p in site['lot']['poly']); ys = sorted(round(p[1], 1) for p in site['lot']['poly'])
    assert xs[0] == pytest.approx(-10, abs=0.05) and xs[-1] == pytest.approx(30, abs=0.05)
    assert ys[0] == pytest.approx(-15, abs=0.05) and ys[-1] == pytest.approx(40, abs=0.05)
    assert sorted(site['lot']['roles']) == ['front', 'rear', 'side', 'side']
    # front line 15 m = 49 ft from the house front: clear of 30 ft; side line 10 m = 32.8 ft
    r = lot_check.check(site, _genome(), _genome())
    assert r['over_new'] == [] and r['over_existing'] == []
    g2 = _genome(); g2['elements']['N'] = {'type': 'wall', 'id': 'N', 'name': 'Addition', 'storey': '1F', 'exterior': True, 'start': [-8, 0], 'end': [-8, 8], 'thickness': {'value': 0.15}}
    r2 = lot_check.check(site, _genome(), g2)
    assert r2['over_new'][0]['wall'] == 'Addition' and r2['over_new'][0]['line'] == 'side'
    assert r2['over_new'][0]['distance_ft'] == pytest.approx((2 - 0.075) / 0.3048, abs=0.1)
