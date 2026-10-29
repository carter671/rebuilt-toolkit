"""Permit planner: design takeoff + property facts -> which applications, what to attach, pre-filled forms.

    python3 permits.py takeoff.json property.json OUT_DIR [--asbuilt ASBUILT.genome.json] [--jurisdiction ID]

property.json (fill once per property; anything unknown can stay out — it shows up as a to-do):
  {"address": "...", "parcel": "0370220100", "county": "Fairfield", "zoning": "R-2", "acres": 0.84,
   "old_town": "historic" | "preservation" | "none" | null,          # Canal Winchester only
   "violet_pointe": true | false,                                      # Canal Winchester CEDA overlay
   "owner": {"name", "address", "phone", "email"}, "applicant": {...},
   "well_septic": true, "demolish": ["detached garage"], "proposed_use": "single-family dwelling",
   "variance": {"sections": "...", "request": "..."}}

Jurisdiction comes from the parcel's tax district (Fairfield County: the first 3 digits), else --jurisdiction.
Every rule is in jurisdictions/<id>.json; forms in forms/<id>/. Nothing here replaces a call to the office.
"""
import argparse, json, os, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
JUR = {p.stem: json.load(open(p)) for p in (HERE / 'jurisdictions').glob('*.json')}


def pick_jurisdiction(prop, forced=None):
    if forced:
        return JUR[forced], f'set by --jurisdiction {forced}'
    if prop.get('jurisdiction'):
        return JUR[prop['jurisdiction']], 'set in property.json'
    parcel = re.sub(r'\D', '', prop.get('parcel', ''))
    if (prop.get('county') or '').lower().startswith('franklin') or re.fullmatch(r'\d{3}-?\d{6}(-?\d{2})?', prop.get('parcel', '')):
        d = parcel[:3]
        for j in JUR.values():
            if d in (j.get('applies_when') or {}).get('franklin_districts', []):
                return j, f'Franklin County parcel {prop.get("parcel")}: tax district {d}'
    if (prop.get('county') or '').lower().startswith('fairfield') or len(parcel) == 10:
        d = parcel[:3]
        for j in JUR.values():
            if d in (j.get('applies_when') or {}).get('fairfield_districts', []):
                return j, f'Fairfield County parcel {prop.get("parcel")}: tax district {d}'
    return None, 'could not tell from the parcel number — set "jurisdiction" in property.json'


def scope_from_takeoff(t, asb=None):
    """what the design changes, in permit terms"""
    new_ops = [o for o in t['openings'] if o.get('new')]
    ext_ops = [o for o in t['openings'] if o['type'] in ('Window', 'Exterior door', 'Garage door') and (o.get('new') or o['action'] in ('Replace', 'New'))]
    adds = [s for s in t['slabs']]
    add_sf = sum(s['sf'] for s in adds)
    new_roofs = [r for r in t['roofs'] if r.get('new')]
    beds = sorted({r['name'] for r in t['rooms'] if re.search(r'\bbed', r['name'], re.I) and 'closet' not in r['name'].lower()})
    beds0 = None
    if asb:
        beds0 = sorted({e.get('name', '') for e in asb['elements'].values() if e['type'] == 'space' and re.search(r'\bbed', e.get('name', ''), re.I) and 'closet' not in e.get('name', '').lower()})
    siding = set()
    if asb:
        for e in asb['elements'].values():
            if e['type'] == 'wall' and e.get('exterior'):
                siding.add(((e.get('info') or {}).get('subtype') or '').lower())
    st = t.get('structure') or {}
    return {
        'addition_sf': round(add_sf), 'additions': [s['name'] for s in adds],
        'new_roofs': [r['name'] for r in new_roofs],
        'exterior_openings': len(ext_ops), 'new_openings': len(new_ops),
        'exterior_walls_moved_or_cut': [d['name'] for d in t['demo_ext']],
        'interior_walls_removed': len(t['demo_int']),
        'beams': [b['name'] for b in st.get('beams', [])],
        'bedrooms': len(beds), 'bedrooms_before': len(beds0) if beds0 is not None else None,
        'exterior_change': bool(ext_ops or new_roofs or t['demo_ext'] or adds),
        'structural': bool(st.get('beams') or t['demo_ext'] or adds),
        'vinyl_siding': any('vinyl' in s for s in siding),
        'extras': sorted({x['key'] for x in t.get('extras', [])}),
    }


def plan(t, prop, jur, why, sc):
    apps, todo, warn = [], [], []
    J = {a['id']: a for a in jur['applications']}
    add = lambda k, reason, **kw: apps.append({**J[k], 'reason': reason, **kw})
    if jur['id'] == 'canal-winchester-city':
        ot = prop.get('old_town')
        if ot is None:
            todo.append('Old Town Overlay: look the parcel up on the Old Town Guidelines map (P&Z, 614-837-7501) and set old_town to historic / preservation / none.')
        if ot == 'yes':                     # inside Old Town, part not confirmed: plan for the stricter Historic rules
            todo.append('Old Town: confirm Historic vs Preservation District with P&Z (614-837-7501) - planned as Historic (stricter) until then.')
        if ot in ('historic', 'preservation', 'yes') and (sc['exterior_change'] or prop.get('demolish')):
            O = jur['overlays']['old_town']
            add('coa', f"in the Old Town {'(part not confirmed)' if ot == 'yes' else ot.title() + ' District'} and the design changes the outside", lead=O['lead_note'], attach=O['application_contents'])
            if ot == 'yes': ot = 'historic'
            if ot == 'historic' and sc['vinyl_siding']:
                warn.append('Historic District: traditional materials only (wood, brick, stone). The house has vinyl siding — new siding / trim on the addition must be wood (or ask the Commission); budget fiber-cement / vinyl lines need to change.')
            if ot == 'preservation':
                warn.append('Preservation District: the addition (new construction) must use wood, brick or stone; man-made siding on the existing house only at the Commission\'s discretion.')
            if ot == 'historic':
                warn.append('Historic District: a change of paint colour also needs the CoA.')
            warn.append('Old Town: additions are judged on width, height, setbacks and style against the neighbours — bring renders from the street.')
        if prop.get('violet_pointe'):
            R = jur['overlays']['violet_pointe']['residential']
            warn.append(f"Violet Pointe overlay: CEDA Joint Land Use Committee reviews additions. Setbacks front {R['front_setback_ft']} / side {R['side_setback_ft']} / rear {R['rear_setback_ft']} ft; additions must match the house; 3 design elements on the front, 2 on sides and back; AC at the rear.")
        add('zoning_building', 'additions / structure / new openings' if sc['structural'] or sc['new_openings'] else 'any permitted work')
        if prop.get('demolish'):
            add('demolition', 'demolishing: ' + ', '.join(prop['demolish']))
        elif sc['exterior_walls_moved_or_cut']:
            todo.append('Demolition permit: the design takes out parts of outside walls but no whole building — confirm with P&Z that 1135.08 does not apply (it covers "any structure or building").')
        lot = sc.get('lot')
        if lot and lot['over_new'] and not prop.get('variance'):
            req = '; '.join(f"{x['wall']} {x['distance_ft']:g} ft from the {x['line']} line where {x['setback_ft']:g} ft is required" for x in lot['over_new'])
            prop['variance'] = {'sections': prop.get('setback_section', 'yard setbacks (see district standards)'), 'request': req}
        if prop.get('variance'):
            add('variance', prop['variance'].get('request', 'zoning standard not met'))
        elif not lot:
            todo.append('Setbacks / height / coverage: run the lot check; if anything is over the line, a Variance (1147) goes in too.')
        if prop.get('conditional_use'):
            add('conditional_use', prop['conditional_use'])
        if prop.get('rezoning'):
            add('rezoning', prop['rezoning'].get('request', ''))
    else:
        lot = sc.get('lot')
        if lot and lot['over_new']:
            warn.append('Over a setback: ' + '; '.join(f"{x['wall']} {x['distance_ft']:g} ft from the {x['line']} line ({x['setback_ft']:g} ft required)" for x in lot['over_new']) + ' — change the design or apply to the zoning board for a variance.')
        for a in jur['applications']:
            if a['id'] == 'health_dept':
                if prop.get('well_septic') and (sc['addition_sf'] or (sc['bedrooms_before'] is not None and sc['bedrooms'] > sc['bedrooms_before'])):
                    add('health_dept', f"well + septic, {sc['addition_sf']} sf added, bedrooms {sc['bedrooms_before']} -> {sc['bedrooms']}")
            else:
                add(a['id'], a['when'])
        todo += jur.get('todo', [])
    # what the toolkit makes vs what someone else must supply
    have = ['floor plan PDF (floorplan_pdf.js)', '3D renders from every side (model_shots.js)', 'scope of work + materials (budget workbook)',
            'first-pass beam / header / rafter / footing sizes (takeoff structure)']
    need = ['site / plot plan on the survey (lot check — planned)', 'elevations with dimensions (permit sheets — planned)', 'wall section + roof framing sheet (planned)']
    outside = []
    att = ' '.join(' '.join(a.get('attach', [])) for a in apps).lower()
    if 'survey' in att:
        outside.append('boundary survey by an Ohio licensed surveyor, dated within 2 years')
    if 'legal description' in att:
        outside.append('legal description (deed / county recorder)')
    if 'owners' in att or 'adjoining' in att:
        outside.append('adjoining + across-the-street owners from the county auditor tax list')
    if any(a['id'] == 'demolition' for a in apps):
        outside.append('certificate of insurance, $300,000+ liability')
    if sc['beams']:
        outside.append('engineer letter / stamp for the beams and posts (first-pass sizes are in the takeoff)')
    if any(a['id'] == 'site_plan' for a in apps):
        outside.append('site plan stamped by an Ohio PE')
    for k in ('name', 'address', 'phone', 'email'):
        if not (prop.get('owner') or {}).get(k):
            todo.append(f'owner {k}');
    return {'property': prop.get('address') or t.get('address'), 'design': t.get('name'), 'jurisdiction': jur['name'], 'jurisdiction_why': why,
            'office': jur['office'], 'phone': jur['phone'], 'portal': jur.get('portal'), 'scope': sc,
            'applications': [{k: a.get(k) for k in ('id', 'name', 'form', 'form_note', 'code', 'reason', 'lead', 'attach')} for a in apps],
            'warnings': warn, 'toolkit_makes': have, 'toolkit_planned': need, 'from_others': outside, 'todo': todo}


def get(prop, path, P):
    if path == 'proposed_use':
        return prop.get('proposed_use', 'Single-family dwelling — renovation and addition')
    if path == 'proposed_use_more':
        return ''
    if path == 'demolition.description':
        return 'Demolish: ' + ', '.join(prop.get('demolish', []))
    if path.startswith('property.'):
        path = path[len('property.'):]
    cur = prop
    for k in path.split('.'):
        cur = (cur or {}).get(k) if isinstance(cur, dict) else None
    return '' if cur is None else str(cur)


def fill_forms(P, prop, jur, out):
    from pypdf import PdfReader, PdfWriter
    done = []
    J = {a['id']: a for a in jur['applications']}
    for a in P['applications']:
        spec = J[a['id']]
        if not spec.get('form'):
            continue
        src = HERE / 'forms' / jur['id'] / spec['form']
        r = PdfReader(str(src)); w = PdfWriter(); w.append(r)
        vals = {f: get(prop, p, P) for f, p in spec.get('fields', {}).items()}
        w.update_page_form_field_values(w.pages[0], vals, auto_regenerate=False)
        w.set_need_appearances_writer(True)
        dst = out / f"{a['id']}-{spec['form']}"
        with open(dst, 'wb') as fh:
            w.write(fh)
        done.append(str(dst.name))
    return done


def markdown(P, filled):
    L = [f"# Permit plan — {P['property']} ({P['design']})", '',
         f"- Jurisdiction: {P['jurisdiction']} — {P['jurisdiction_why']}",
         f"- Office: {P['office']} — {P['phone']}" + (f" — portal {P['portal']}" if P.get('portal') else ''), '']
    s = P['scope']
    L += ['## What the design changes', f"- Additions: {s['addition_sf']} sf ({', '.join(s['additions']) or 'none'})",
          f"- New / changed roofs: {len(s['new_roofs'])}", f"- Outside openings new or replaced: {s['exterior_openings']}",
          f"- Outside walls cut or moved: {len(s['exterior_walls_moved_or_cut'])}; inside walls removed: {s['interior_walls_removed']}",
          f"- Beams: {len(s['beams'])}", f"- Bedrooms: {s['bedrooms_before'] if s['bedrooms_before'] is not None else '?'} -> {s['bedrooms']}", '']
    if s.get('lot'):
        lt = s['lot']; L += ['## Lot check (parcel lines + setbacks)']
        L += [f"- NEW work over a setback: {x['wall']} — {x['distance_ft']:g} ft from the {x['line']} line, {x['setback_ft']:g} ft required ({x['over_ft']:g} ft over)" for x in lt['over_new']] or ['- New work: clear of every setback']
        L += [f"- Existing (legal nonconforming): {x['wall']} — {x['distance_ft']:g} ft from the {x['line']} line, {x['setback_ft']:g} ft required" for x in lt['over_existing']]
        if lt['outside_lot']:
            L.append(f"- Past the lot line: {len(lt['outside_lot'])} walls — check the lot position before trusting this")
        L.append('')
    L += ['## Applications']
    for i, a in enumerate(P['applications'], 1):
        L.append(f"{i}. **{a['name']}**" + (f" (code {a['code']})" if a.get('code') else '') + f" — {a['reason']}")
        if a.get('lead'):
            L.append(f"   - Timing: {a['lead']}")
        if a.get('form_note'):
            L.append(f"   - {a['form_note']}")
        for x in a.get('attach') or []:
            L.append(f"   - attach: {x}")
    if P['warnings']:
        L += ['', '## Watch out'] + [f'- {w}' for w in P['warnings']]
    L += ['', '## Who supplies what', '- Toolkit makes now: ' + '; '.join(P['toolkit_makes']),
          '- Toolkit — planned: ' + '; '.join(P['toolkit_planned'])]
    if P['from_others']:
        L.append('- From others: ' + '; '.join(P['from_others']))
    if filled:
        L += ['', '## Pre-filled forms (sign + date by hand)'] + [f'- {f}' for f in filled]
    if P['todo']:
        L += ['', '## To do before filing'] + [f'- {x}' for x in P['todo']]
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('takeoff'); ap.add_argument('property'); ap.add_argument('out')
    ap.add_argument('--asbuilt'); ap.add_argument('--jurisdiction', choices=sorted(JUR))
    ap.add_argument('--site', help='site.json from site/lot_import.py'); ap.add_argument('--design', help='design genome, for the lot check')
    A = ap.parse_args()
    t = json.load(open(A.takeoff)); prop = json.load(open(A.property))
    asb = json.load(open(A.asbuilt)) if A.asbuilt else None
    jur, why = pick_jurisdiction(prop, A.jurisdiction)
    if not jur:
        sys.exit(why)
    out = pathlib.Path(A.out); out.mkdir(parents=True, exist_ok=True)
    sc = scope_from_takeoff(t, asb)
    if A.site and A.design and asb:           # lot check from the parcel lines (rebuilt/site)
        sys.path.insert(0, str(HERE.parent / 'site')); import lot_check
        adj = prop.get('lot_adj')
        sc['lot'] = lot_check.check(json.load(open(A.site)), asb, json.load(open(A.design)), adj)
    P = plan(t, prop, jur, why, sc)
    filled = fill_forms(P, prop, jur, out)
    P['filled_forms'] = filled
    json.dump(P, open(out / 'permit-plan.json', 'w'), indent=1)
    open(out / 'permit-plan.md', 'w').write(markdown(P, filled))
    print(f"{jur['name']} ({why}): {len(P['applications'])} applications, {len(filled)} forms filled, {len(P['todo'])} to-dos -> {out}")
