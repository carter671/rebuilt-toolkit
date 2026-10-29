"""Permit planner: jurisdiction from the parcel, Old Town triggers, township health review."""
import importlib.util, pathlib

spec = importlib.util.spec_from_file_location('permits', pathlib.Path(__file__).resolve().parents[1] / 'permits' / 'permits.py')
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)

T = {'name': 'D', 'address': 'x', 'rooms': [{'name': 'Bedroom 1'}, {'name': 'Bedroom 2'}],
     'openings': [{'type': 'Window', 'action': 'New', 'new': True}], 'roofs': [], 'demo_ext': [], 'demo_int': [],
     'slabs': [{'name': 'addition', 'sf': 300}], 'structure': {'beams': []}, 'extras': []}
ASB = {'elements': {'s': {'type': 'space', 'name': 'Bedroom 1'}, 'w': {'type': 'wall', 'exterior': True, 'info': {'subtype': 'vinyl lap siding'}}}}


def test_parcel_district_picks_jurisdiction():
    assert P.pick_jurisdiction({'parcel': '0370220100'})[0]['id'] == 'violet-township'
    assert P.pick_jurisdiction({'parcel': '0420001000', 'county': 'Fairfield'})[0]['id'] == 'canal-winchester-city'
    assert P.pick_jurisdiction({'parcel': '010-123456-00'})[0] is None


def test_old_town_historic_needs_coa_and_flags_vinyl():
    j = P.JUR['canal-winchester-city']; sc = P.scope_from_takeoff(T, ASB)
    plan = P.plan(T, {'old_town': 'historic'}, j, 'test', sc)
    ids = [a['id'] for a in plan['applications']]
    assert 'coa' in ids and 'zoning_building' in ids
    assert any('vinyl' in w for w in plan['warnings'])
    none = P.plan(T, {'old_town': 'none'}, j, 'test', sc)
    assert 'coa' not in [a['id'] for a in none['applications']]
    unknown = P.plan(T, {}, j, 'test', sc)
    assert any('Old Town' in x for x in unknown['todo'])


def test_township_septic_review_when_bedrooms_added():
    j = P.JUR['violet-township']; sc = P.scope_from_takeoff(T, ASB)
    assert sc['bedrooms_before'] == 1 and sc['bedrooms'] == 2
    plan = P.plan(T, {'well_septic': True}, j, 'test', sc)
    assert 'health_dept' in [a['id'] for a in plan['applications']]
    assert 'health_dept' not in [a['id'] for a in P.plan(T, {'well_septic': False}, j, 'test', sc)['applications']]


def test_old_town_part_unknown_plans_as_historic():
    j = P.JUR['canal-winchester-city']; sc = P.scope_from_takeoff(T, ASB)
    plan = P.plan(T, {'old_town': 'yes'}, j, 'test', sc)
    assert 'coa' in [a['id'] for a in plan['applications']]
    assert any('Historic vs Preservation' in x for x in plan['todo'])
    assert any('paint' in w for w in plan['warnings'])
