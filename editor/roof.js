/* ---------------- roof framing: trusses or rafters, bearing walls, beams ---------------- */
const FRAMING = {
  unknown: {label: 'Not confirmed', sp: 24},
  truss:   {label: 'Trusses, 24" o.c.', sp: 24},
  rafter:  {label: 'Rafters + ceiling joists, 16" o.c.', sp: 16},
};
let showFraming = false;
// a gable roof in its own frame: u along the eaves (ridge direction), v across the span from the first eave
function roofFrame(r){
  const k = r.roles.indexOf('eave'), P = r.fp, a = P[k], b = P[(k + 1) % P.length];
  const u = unit(sub(b, a)), L = dist(a, b);
  let v = perp(u); const c = mul(P.reduce((s, p) => add(s, p), [0, 0]), 1 / P.length); if (dot(sub(c, a), v) < 0) v = mul(v, -1);
  const W = Math.max(...P.map(p => dot(sub(p, a), v)));
  return {o: a, u, v, L, W, z: EL(r.st) + r.plate, rise: W / 2 * r.pitch};
}
const roofOf = id => (S.roofs || []).find(r => r.id === id);
function roofStats(r){
  const F = roofFrame(r), sp = FRAMING[r.framing].sp * IN, n = Math.ceil(F.L / sp - 1e-6) + 1;
  return {F, sp, n, commons: Math.max(0, n - 2)};
}
// walls that carry the roof or ceiling: eave walls always; with rafters (or not confirmed), interior walls near mid-span
function bearingWalls(){
  const out = new Map();
  (S.roofs || []).forEach(r => {
    const F = roofFrame(r);
    PLAN.walls.filter(w => w.st === r.st).forEach(w => {
      const d = wallFrame(w).d; if (Math.abs(dot(d, F.u)) < 0.98) return;
      const vm = dot(sub(mul(add(w.s, w.e), 0.5), F.o), F.v);
      if (w.ext && (vm < 0.3 || vm > F.W - 0.3)) out.set(w.id, {roof: r, why: 'eave'});
      else if (!w.ext && r.framing !== 'truss' && Math.abs(vm - F.W / 2) < 0.9) out.set(w.id, {roof: r, why: r.framing === 'rafter' ? 'joists' : 'maybe'});
    });
  });
  return out;
}
function bearingChecks(out){
  const B = bearingWalls(), beams = S.beams || [];
  B.forEach((info, id) => {
    if (info.why === 'eave') return;
    const base = PLAN.walls.find(w => w.id === id), now = S.walls.find(w => w.id === id);
    const covered = beams.some(b => b.wall === id);
    let problem = null;
    if (!now) problem = 'removed';
    else if (dist(now.s, base.s) > IN || dist(now.e, base.e) > IN) problem = 'moved';
    if (!problem || covered) return;
    const why = info.why === 'joists' ? 'carries the ceiling joists (rafter roof)' : 'may carry the ceiling joists if the roof is rafters, not trusses';
    out.push({type: 'bearing', wall: id, ids: [], walls: [id], msg: `${base.name || id} was ${problem} — it ${why}. Needs a beam${info.why === 'maybe' ? ' unless the attic shows trusses' : ''}.`});
  });
  // openings wider than 6 ft cut into a bearing wall
  S.openings.forEach(o => {
    const info = B.get(o.host); if (!info) return;
    const base = PLAN.openings.find(b => b.id === o.id);
    if (o.w > 6 * FT * 1.0 && (!base || o.w > base.w + IN) && info.why !== 'eave')
      out.push({type: 'header', o: o.id, ids: [], walls: [o.host], msg: `${ftin(o.w)} opening in a ${info.why === 'joists' ? 'bearing' : 'possibly bearing'} wall — needs a sized header (engineer).`});
  });
}

/* 3D members: thin boxes between two plan+height points */
const FM = {
  wood: new THREE.MeshStandardMaterial({color: '#C9A06A', roughness: .8}), beam: new THREE.MeshStandardMaterial({color: '#B4432F', roughness: .6}),
  plate: new THREE.MeshStandardMaterial({color: '#A57E4E', roughness: .8}),
};
function member(grp, p0, z0, p1, z1, w, h, mat){
  const A = P3(p0[0], p0[1], z0), B = P3(p1[0], p1[1], z1), L = A.distanceTo(B); if (L < 0.01) return;
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, L), mat);
  m.position.copy(A.clone().add(B).multiplyScalar(0.5)); m.lookAt(B); m.castShadow = true; grp.add(m);
}
function buildFraming3D(grp){
  if (!showFraming) return;
  (S.roofs || []).forEach(r => {
    const {F, sp, n} = roofStats(r), t = 1.5 * IN, dd = 3.5 * IN, zP = F.z, zR = zP + F.rise, oh = r.oh;
    for (let k = 0; k < n; k++){
      const s = Math.min(k * sp, F.L), at = (v) => add(add(F.o, mul(F.u, s)), mul(F.v, v)), zAt = v => zP + Math.min(v, F.W - v) * r.pitch;
      const end = k === 0 || k === n - 1;
      // top chords / rafters with the overhang tails
      member(grp, at(-oh), zP - oh * r.pitch, at(F.W / 2), zR, t, dd, FM.wood);
      member(grp, at(F.W + oh), zP - oh * r.pitch, at(F.W / 2), zR, t, dd, FM.wood);
      if (r.framing === 'rafter'){ member(grp, at(0), zP, at(F.W), zP, t, 5.5 * IN, FM.wood); continue; }   // ceiling joist
      member(grp, at(0), zP, at(F.W), zP, t, dd, FM.wood);                                                   // bottom chord
      if (end){ for (let v = 16 * IN; v < F.W; v += 16 * IN) member(grp, at(v), zP, at(v), zAt(v), t, dd, FM.wood); continue; }
      [[F.W / 3, F.W / 4], [F.W / 3, F.W / 2], [2 * F.W / 3, F.W / 2], [2 * F.W / 3, 3 * F.W / 4]].forEach(([vb, vt]) => member(grp, at(vb), zP, at(vt), zAt(vt), t, dd, FM.wood));
    }
    if (r.framing === 'rafter'){ const a = add(F.o, mul(F.v, F.W / 2)); member(grp, a, zR, add(a, mul(F.u, F.L)), zR, t, 7.25 * IN, FM.plate); }
  });
  (S.beams || []).forEach(b => member(grp, b.s, EL(b.st) + b.z, b.e, EL(b.st) + b.z, 3.5 * IN, b.depth, FM.beam));
}
function drawFramingPlan(g){
  const B = bearingWalls();
  B.forEach((info, id) => { const w = S.walls.find(x => x.id === id); if (!w || info.why === 'eave') return;
    el('polygon', {points: pts(wallPoly({...w, t: w.t + 0.12})), class: 'bearing' + (info.why === 'maybe' ? ' maybe' : ''), 'stroke-width': 1.5 * pxm(), 'stroke-dasharray': `${4 * pxm()} ${3 * pxm()}`}, g); });
  (S.beams || []).forEach(b => el('line', {x1: toSvg(b.s)[0], y1: toSvg(b.s)[1], x2: toSvg(b.e)[0], y2: toSvg(b.e)[1], class: 'beam', 'stroke-width': 5 * pxm(), 'stroke-dasharray': `${10 * pxm()} ${4 * pxm()}`}, g));
  if (!showFraming) return;
  (S.roofs || []).forEach(r => { const {F, sp, n} = roofStats(r);
    for (let k = 0; k < n; k++){ const s = Math.min(k * sp, F.L), a = add(F.o, mul(F.u, s)), b = add(a, mul(F.v, F.W));
      el('line', {x1: toSvg(a)[0], y1: toSvg(a)[1], x2: toSvg(b)[0], y2: toSvg(b)[1], class: 'joist', 'stroke-width': pxm()}, g); } });
}

/* beams: the fix for a removed / moved bearing wall */
function beamFor(wallId){
  const base = PLAN.walls.find(w => w.id === wallId), info = bearingWalls().get(wallId), r = info ? info.roof : null;
  const L = dist(base.s, base.e), depth = (L <= 8 * FT ? 9.25 : L <= 12 * FT ? 11.875 : L <= 16 * FT ? 14 : 16) * IN;
  return {id: uid('N-BM'), wall: wallId, st: base.st, s: base.s.slice(), e: base.e.slice(), depth, z: (r ? r.plate : base.h) - depth, name: `LVL beam (was ${base.name || wallId})`, L};
}

/* side panel */
function drawRoofPanel(){
  const host = $('#roof'); if (!host) return; host.innerHTML = '';
  (S.roofs || []).forEach(r => {
    const {F, n, commons} = roofStats(r), box = document.createElement('div'); box.className = 'roofbox';
    const h = document.createElement('div'); h.className = 'rname'; h.textContent = r.name.replace(/\s*\(.*\)/, ''); box.appendChild(h);
    const sel2 = document.createElement('select'); sel2.setAttribute('aria-label', 'Roof framing for ' + r.name);
    Object.entries(FRAMING).forEach(([k, f]) => { const o = document.createElement('option'); o.value = k; o.textContent = f.label; if (k === r.framing) o.selected = true; sel2.appendChild(o); });
    sel2.onchange = () => commit({do: 'set_roof', roof: r.id, framing: sel2.value, label: `${h.textContent}: ${FRAMING[sel2.value].label}`});
    box.appendChild(sel2);
    const pitch = `${Math.round(r.pitch * 12 * 2) / 2}/12`;
    const lines = [`Span ${ftin(F.W)} · length ${ftin(F.L)} · pitch ${pitch}`,
      r.framing === 'rafter' ? `${n} rafter pairs + ceiling joists, ridge board` : `${commons} common + 2 gable-end trusses` + (r.framing === 'unknown' ? ' (if trusses)' : '')];
    lines.forEach(t => { const d = document.createElement('div'); d.className = 'rline'; d.textContent = t; box.appendChild(d); });
    if (r.framing !== 'rafter'){ const b = document.createElement('button'); b.textContent = 'Copy truss order'; b.onclick = () => copyOrder(r); box.appendChild(b); }
    host.appendChild(box);
  });
  const t = document.createElement('button'); t.id = 'tFrame'; t.setAttribute('aria-pressed', showFraming); t.textContent = showFraming ? 'Hide framing' : 'Show framing';
  t.onclick = () => { showFraming = !showFraming; drawPlan(); build3D(); drawRoofPanel(); }; host.appendChild(t);
}
function copyOrder(r){
  const {F, commons} = roofStats(r), B = bearingWalls(), bw = [...B.entries()].filter(([, i]) => i.roof === r && i.why === 'eave').map(([id]) => (PLAN.walls.find(w => w.id === id) || {}).name || id);
  const txt = [`${r.name} — truss order (for quote)`,
    `- Truss type: common, Fink web (gable ends: 2 gable-end trusses with studs at 16" o.c.)`,
    `- Quantity: ${commons} common + 2 gable-end = ${commons + 2}`,
    `- Span: ${ftin(F.W)} outside of wall to outside of wall`,
    `- Pitch: ${Math.round(r.pitch * 12 * 2) / 2}/12, both sides`,
    `- Overhang: ${ftin(r.oh)} at the eaves; rake overhang ${ftin(r.rake)} (ladder or outlookers)`,
    `- Spacing: 24" o.c. over ${ftin(F.L)}`,
    `- Heel: standard (confirm with supplier)`,
    `- Bearing: ${bw.join(', ') || 'exterior eave walls'}`,
    `- Design loads: per supplier for this address (ground snow + wind); trusses engineered and stamped by the supplier`,
    `- Measurements are from the as-built model and need a field check before ordering`].join('\n');
  try { navigator.clipboard.writeText(txt).then(() => toast('Truss order copied.'), () => showText(txt)); } catch (e) { showText(txt); }
}
function showText(txt){ pop.innerHTML = ''; const ta = document.createElement('textarea'); ta.value = txt; ta.rows = 11; ta.style.width = '320px'; ta.setAttribute('aria-label', 'Truss order'); pop.appendChild(ta); pop.hidden = false; pop.style.left = '280px'; pop.style.top = '80px'; ta.select(); }
