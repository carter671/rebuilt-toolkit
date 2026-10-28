/* ---------------- chat: Claude proposes changes, you apply them ---------------- */
let proposal = [];                 // ops previewed on top of the design, not saved until Apply
let chatTurns = [];                // {role, content} kept by the page (Claude keeps nothing between calls)
let sampleFn = null, chatCtl = null;
const COMPASS = [['east', [1, 0]], ['north', [0, 1]], ['west', [-1, 0]], ['south', [0, -1]]];
const inch = m => Math.round(m / IN);

/* rooms described by their sides: which wall, which way it faces, what is on it */
function roomSides(r){
  const P = r.poly, groups = new Map();
  for (let i = 0; i < P.length; i++){
    const p = P[i], q = P[(i + 1) % P.length], d = unit(sub(q, p)), nOut = [d[1], -d[0]];
    const w = S.walls.find(w => w.st === r.st && projOnSeg(p, w.s, w.e).d < w.t / 2 + TOL && projOnSeg(q, w.s, w.e).d < w.t / 2 + TOL);
    if (!w) continue;
    const comp = COMPASS.reduce((b, c) => dot(c[1], nOut) > dot(b[1], nOut) ? c : b)[0];
    const key = w.id + '|' + comp, g = groups.get(key) || {wall: w, side: comp, nOut, pts: []};
    g.pts.push(p, q); groups.set(key, g);
  }
  return [...groups.values()].map(g => {
    // standing in the room facing this wall: the left end is where the polygon edge heads
    const dir = mul(perp(g.nOut), -1);                      // left -> right as seen facing the wall
    const proj = g.pts.map(p => dot(p, dir)), lo = Math.min(...proj), hi = Math.max(...proj);
    const ins = 0.06, inward = mul(g.nOut, -1), faceOff = g.wall.t / 2;
    const ref = g.pts[0], base = sub(ref, mul(dir, dot(ref, dir) - lo - ins));   // left end, on the centreline
    const left = add(base, mul(inward, faceOff));
    return {wall: g.wall, side: g.side, inward, dir, left, len: Math.max(0, hi - lo - 2 * ins)};
  }).filter(s => s.len > 0.2);
}
const posOn = (sd, p) => dot(sub(p, sd.left), sd.dir);
function sideOpenings(sd){
  return S.openings.filter(o => o.host === sd.wall.id).map(o => {
    const {d} = wallFrame(sd.wall), a = add(sd.wall.s, mul(d, o.off)), b = add(sd.wall.s, mul(d, o.off + o.w));
    const x0 = Math.min(posOn(sd, a), posOn(sd, b)), x1 = Math.max(posOn(sd, a), posOn(sd, b));
    return {o, x0, x1};
  }).filter(x => x.x1 > 0.02 && x.x0 < sd.len - 0.02);
}
function describePlan(){
  const L = [];
  L.push('Units: inches. Plan north = up on the screen (the front of the house, on the road, is the south side). Positions along a side are measured from the LEFT end as you stand inside the room facing that wall.');
  L.push('Roofs: ' + (S.roofs || []).map(r => `${r.id} "${r.name}" framing=${r.framing}`).join('; '));
  const B = bearingWalls();
  rooms.filter(r => r.area > 0.3).forEach(r => {
    const xs = r.poly.map(p => p[0]), ys = r.poly.map(p => p[1]);
    L.push(`ROOM ${r.id} "${r.name}" (${r.st === ST ? 'house' : 'garage'}) ${Math.round(r.area * 10.764)} sf, about ${inch(Math.max(...xs) - Math.min(...xs))}" E-W x ${inch(Math.max(...ys) - Math.min(...ys))}" N-S`);
    roomSides(r).forEach(sd => {
      const w = sd.wall, bi = B.get(w.id), ops2 = sideOpenings(sd).map(({o, x0, x1}) =>
        `${o.kind} ${o.id} ${inch(o.w)}" wide at ${Math.max(0, inch(x0))}-${Math.min(inch(sd.len), inch(x1))}"` + (o.kind === 'window' ? ` sill ${inch(o.sill)}"` : '') + (o.kind === 'door' && o.w < 1.25 ? ` (swings ${(w.ext ? -1 : 1) * dot(wallFrame(w).n, sd.inward) > 0 ? 'into this room' : 'away'})` : ''));
      const its = S.items.filter(it => it.st === r.st && inPoly(it.at, r.poly) && Math.abs(dot(sub(it.at, sd.left), sd.inward) - it.d / 2) < 0.05)
        .map(it => `${it.id} ${it.name} ${inch(it.w)}" at ${inch(posOn(sd, it.at) - it.w / 2)}-${inch(posOn(sd, it.at) + it.w / 2)}"`);
      L.push(`  ${sd.side}: wall ${w.id} "${w.name}"${w.ext ? ' exterior' : ''}${bi && bi.why !== 'eave' ? (bi.why === 'joists' ? ' BEARING' : ' maybe-bearing') : ''}, ${inch(sd.len)}" inside` + (ops2.length ? '; ' + ops2.join('; ') : '') + (its.length ? '; against it: ' + its.join('; ') : ''));
    });
    const free = S.items.filter(it => it.st === r.st && inPoly(it.at, r.poly) && !roomSides(r).some(sd => Math.abs(dot(sub(it.at, sd.left), sd.inward) - it.d / 2) < 0.05));
    if (free.length) L.push('  free-standing: ' + free.map(it => `${it.id} ${it.name} ${inch(it.w)}x${inch(it.d)}"`).join('; '));
  });
  const ch = computeChecks();
  L.push('CHECKS: ' + (ch.length ? ch.map(x => x.msg).join(' | ') : 'none'));
  return L.join('\n');
}

/* resolving names the model uses */
function findRoom(q){
  if (!q) return null; const s = String(q).trim().toLowerCase();
  return rooms.find(r => r.id.toLowerCase() === s) || rooms.find(r => r.name.toLowerCase() === s) || rooms.filter(r => r.name.toLowerCase().includes(s)).sort((a, b) => b.area - a.area)[0] || null;
}
function findSide(r, q){
  const sides = roomSides(r); if (!q) return null; const s = String(q).trim().toLowerCase();
  return sides.find(sd => sd.side === s) || sides.find(sd => sd.wall.id.toLowerCase() === s) || null;
}
const catOf = q => { const s = String(q || '').toLowerCase().replace(/\s+/g, ''); return Object.keys(CAT).find(k => k === s) || Object.keys(CAT).find(k => CAT[k].label.toLowerCase().replace(/\s+/g, '') === s) || Object.keys(CAT).find(k => CAT[k].label.toLowerCase().replace(/\s+/g, '').includes(s)) || null; };

/* placing against a side: back on the wall face, facing into the room */
function onSide(it, sd, x0){ it.st = sd.wall.st; it.rot = rotOf(sd.inward); it.at = add(add(sd.left, mul(sd.dir, x0 + it.w / 2)), mul(sd.inward, it.d / 2 + 0.003)); return it; }
function tallFor(it){ return it.z + it.h > 0.8; }
function placeScore(it, r, sd, x0){
  // higher is better; -Infinity if it does not fit
  onSide(it, sd, x0);
  if (x0 < -0.001 || x0 + it.w > sd.len + 0.001 || !itemClear(it, r.poly)) return -Infinity;
  const ops2 = sideOpenings(sd); let s = 0;
  for (const {o, x0: a, x1: b} of ops2){
    const over = Math.min(b, x0 + it.w) - Math.max(a, x0); if (over <= 0) continue;
    if (o.kind === 'door') return -Infinity;
    if (o.kind === 'window' && o.sill < it.z + it.h) s -= /king|queen|full|twin/.test(it.cat) ? 6 : tallFor(it) ? 20 : 3;
  }
  const doorSides = roomSides(r).filter(x => sideOpenings(x).some(y => y.o.kind === 'door'));
  const isBed = /king|queen|full|twin/.test(it.cat);
  if (isBed || it.cat === 'sofa' || it.cat === 'dresser'){
    if (doorSides.includes(sd)) s -= 8;
    if (doorSides.some(x => dot(x.inward, sd.inward) < -0.9)) s += isBed ? 6 : 2;   // facing the door
    s -= Math.abs(x0 + it.w / 2 - sd.len / 2) * 2;                                 // centred
    if (isBed){ const room = Math.min(x0, sd.len - x0 - it.w); s += Math.min(room, 0.6) * 5; }   // space for nightstands
    // keep 30" clear at the foot
    const front = clone(it); front.at = add(it.at, mul(sd.inward, it.d / 2 + 0.38)); front.d = 0.76; front.z = 0; front.h = 1; if (!itemClear(front, r.poly)) s -= 10;
  } else s -= Math.abs(x0 + it.w / 2 - sd.len / 2) * 0.5;
  return s + sd.len * 0.2;
}
function autoPlace(it, r, sdOnly){
  let best = null;
  (sdOnly ? [sdOnly] : roomSides(r)).forEach(sd => {
    for (let x0 = 0; x0 <= sd.len - it.w + 1e-6; x0 += IN * 2){ const sc = placeScore(it, r, sd, x0); if (sc > -Infinity && (!best || sc > best.sc)) best = {sd, x0, sc}; }
    const x0 = sd.len - it.w; if (x0 >= 0){ const sc = placeScore(it, r, sd, x0); if (sc > -Infinity && (!best || sc > best.sc)) best = {sd, x0, sc}; }
  });
  if (best) onSide(it, best.sd, best.x0);
  return best;
}
function freePlace(it, r){
  // islands, tables: centre of the room, then the nearest clear spot
  const c = interiorPoint(r.poly); it.st = r.st; it.at = c;
  if (itemClear(it, r.poly)) return true;
  const q = findSpot(it); if (q){ it.at = q; return true; } return false;
}

/* one change from the chat, turned into editor ops (applied to the preview right away) */
function doAction(a){
  const act = String(a.action || '').toLowerCase(), out = m => ({ok: true, did: m}), fail = m => ({ok: false, error: m});
  const push = (op) => { proposal.push(op); applyOp(S, op); rooms = computeRooms(); };
  const getIt = id => S.items.find(i => i.id === id);
  if (act === 'place'){
    const cat = catOf(a.item); if (!cat) return fail(`Unknown item "${a.item}". Use one of: ${Object.keys(CAT).filter(k => CAT[k].g).join(', ')}`);
    const r = findRoom(a.room); if (!r) return fail(`No room "${a.room}"`);
    const n = Math.max(1, Math.min(6, Number(a.count) || 1)), did = [];
    for (let k = 0; k < n; k++){
      const it = newItem(cat); if (a.width_in) it.w = Number(a.width_in) * IN; if (a.depth_in) it.d = Number(a.depth_in) * IN; it.st = r.st;
      if (a.beside){
        const B = getIt(a.beside); if (!B) return fail(`No item ${a.beside}`);
        const sd = roomSides(r).find(s => Math.abs(dot(sub(B.at, s.left), s.inward) - B.d / 2) < 0.05); if (!sd) return fail(`${a.beside} is not against a wall`);
        const bx = posOn(sd, B.at), sideLR = String(a.side || 'right').toLowerCase();
        const sides = sideLR === 'both' ? ['left', 'right'] : [sideLR];
        for (const sl of sides){ const it2 = clone(it); it2.id = uid('N-I'); onSide(it2, sd, sl === 'left' ? bx - B.w / 2 - it2.w : bx + B.w / 2);
          push({do: 'add_item', item: it2}); did.push(`${it2.name} on the ${sl} of ${B.name}${itemClear(it2, r.poly) ? '' : ' (it does not fit cleanly — see checks)'}`); }
        return out(did.join('; '));
      }
      if (!CAT[cat].wall && !a.wall){ if (!freePlace(it, r)) return fail(`No clear spot for a ${CAT[cat].label} in ${r.name}`); }
      else if (a.wall){
        const sd = findSide(r, a.wall); if (!sd) return fail(`${r.name} has no side "${a.wall}". Its sides: ${roomSides(r).map(s => s.side + '=' + s.wall.id).join(', ')}`);
        const pos = a.position == null ? 'auto' : String(a.position).toLowerCase();
        if (pos === 'auto'){ if (!autoPlace(it, r, sd)) return fail(`A ${inch(it.w)}" ${CAT[cat].label} does not fit clear on the ${sd.side} side of ${r.name} (${inch(sd.len)}" long)`); }
        else onSide(it, sd, pos === 'center' || pos === 'centre' ? (sd.len - it.w) / 2 : pos === 'left' ? 0 : pos === 'right' ? sd.len - it.w : Number(a.position) * IN);
      } else if (!autoPlace(it, r)) return fail(`Could not find a sensible spot for a ${CAT[cat].label} in ${r.name}; name a wall and position`);
      push({do: 'add_item', item: it});
      const sd2 = roomSides(r).find(s => Math.abs(dot(sub(it.at, s.left), s.inward) - it.d / 2) < 0.05);
      did.push(`${it.id} ${it.name} ` + (sd2 ? `against the ${sd2.side} wall at ${inch(posOn(sd2, it.at) - it.w / 2)}-${inch(posOn(sd2, it.at) + it.w / 2)}" of ${inch(sd2.len)}"` : 'free-standing') + ` in ${r.name}` + (itemClear(it, r.poly) ? '' : ' — overlaps something, see checks'));
    }
    return out(did.join('; '));
  }
  if (act === 'move_item'){
    const it = getIt(a.id); if (!it) return fail(`No item ${a.id}`);
    const t = clone(it), r = findRoom(a.room) || rooms.find(x => inPoly(it.at, x.poly)); if (!r) return fail('Which room?');
    if (a.wall){ const sd = findSide(r, a.wall); if (!sd) return fail(`No side "${a.wall}" in ${r.name}`);
      const pos = a.position == null ? 'auto' : String(a.position).toLowerCase();
      if (pos === 'auto'){ if (!autoPlace(t, r, sd)) return fail('Does not fit there'); }
      else onSide(t, sd, pos === 'center' || pos === 'centre' ? (sd.len - t.w) / 2 : pos === 'left' ? 0 : pos === 'right' ? sd.len - t.w : Number(a.position) * IN);
    } else if (a.shift_in){ const {a: ax, f} = itemFrame(t), dirn = String(a.direction || 'right').toLowerCase();
      const v = dirn === 'left' ? mul(ax, -1) : dirn === 'right' ? ax : dirn === 'forward' ? f : mul(f, -1); t.at = add(t.at, mul(v, Number(a.shift_in) * IN));
    } else if (!(CAT[t.cat].wall ? autoPlace(t, r) : freePlace(t, r))) return fail('No better spot found');
    push({do: 'set_item', item: it.id, at: t.at, rot: t.rot, st: t.st}); return out(`moved ${it.name}`);
  }
  if (act === 'resize_item'){ const it = getIt(a.id); if (!it) return fail(`No item ${a.id}`); const w = Number(a.width_in) * IN; const {a: ax} = itemFrame(it);
    push({do: 'set_item', item: it.id, w, d: a.depth_in ? Number(a.depth_in) * IN : undefined, at: add(it.at, mul(ax, (w - it.w) / 2))}); return out(`${it.name} now ${a.width_in}" wide`); }
  if (act === 'remove_item'){ const it = getIt(a.id); if (!it) return fail(`No item ${a.id}`); push({do: 'remove_item', item: it.id}); return out(`removed ${it.name}`); }
  if (act === 'cabinet_run'){
    const r = findRoom(a.room); if (!r) return fail(`No room "${a.room}"`); const sd = findSide(r, a.wall); if (!sd) return fail(`No side "${a.wall}" in ${r.name}`);
    const op = cabinetRun(sd.wall, add(add(sd.left, mul(sd.dir, sd.len / 2)), mul(sd.inward, 0.1)), true); if (!op) return fail('No room for cabinets there');
    push(op); return out(op.label);
  }
  if (act === 'remove_wall'){ const w = S.walls.find(x => x.id === a.wall); if (!w) return fail(`No wall ${a.wall}`); if (w.ext) return fail('Exterior walls cannot be removed here');
    push({do: 'remove_wall', wall: w.id}); return out(`removed ${w.name}`); }
  if (act === 'move_wall'){
    const w = S.walls.find(x => x.id === a.wall); if (!w) return fail(`No wall ${a.wall}`);
    const r = findRoom(a.toward); if (!r) return fail('Say which room it moves toward');
    const {n} = wallFrame(w), mid = mul(add(w.s, w.e), 0.5), sgn = Math.sign(dot(sub(interiorPoint(r.poly), mid), n)) || 1, mv = mul(n, sgn * Number(a.inches) * IN);
    const walls = {[w.id]: {s: add(w.s, mv), e: add(w.e, mv)}}, offs = {};
    if (a.stretch_attached){ const conns = (() => { const was = stretch; stretch = true; const c = connected(w); stretch = was; return c; })();
      conns.forEach(c => { const o = S.walls.find(x => x.id === c.id); walls[c.id] = c.end === 's' ? {s: add(o.s, mv), e: o.e} : {s: o.s, e: add(o.e, mv)};
        if (c.end === 's'){ const shift = dot(mv, wallFrame(o).d); S.openings.filter(x => x.host === c.id).forEach(x => offs[x.id] = x.off - shift); } }); }
    push({do: 'set_walls', walls, openings: offs}); return out(`moved ${w.name} ${a.inches}" toward ${r.name}`);
  }
  if (act === 'split_room'){
    const r = findRoom(a.room); if (!r) return fail(`No room "${a.room}"`);
    const ns = /north|n-s|ns|vertical/.test(String(a.line).toLowerCase()), xs = r.poly.map(p => p[0]), ys = r.poly.map(p => p[1]);
    const c = ns ? Math.min(...xs) + 0.06 + Number(a.at_in) * IN : Math.min(...ys) + 0.06 + Number(a.at_in) * IN;
    const hits = []; for (let i = 0; i < r.poly.length; i++){ const p = r.poly[i], q = r.poly[(i + 1) % r.poly.length], k = ns ? 0 : 1;
      if ((p[k] - c) * (q[k] - c) <= 0 && p[k] !== q[k]){ const t = (c - p[k]) / (q[k] - p[k]); hits.push(p[1 - k] + t * (q[1 - k] - p[1 - k])); } }
    if (hits.length < 2) return fail('That line does not cross the room');
    const lo = Math.min(...hits), hi = Math.max(...hits), s0 = ns ? [c, lo] : [lo, c], e0 = ns ? [c, hi] : [hi, c];
    const inner = S.walls.filter(w => !w.ext && w.st === r.st), h = inner.length ? inner.map(w => w.h).sort((x, y) => x - y)[inner.length >> 1] : 2.44;
    const w = {id: uid('N-W'), st: r.st, s: s0, e: e0, t: 4.5 * IN, h, b: 0, ext: false, name: a.name || 'New wall'};
    push({do: 'add_wall', wall: w}); return out(`added ${w.id}, a ${inch(hi - lo)}" wall across ${r.name}`);
  }
  if (act === 'add_opening'){
    const kind = String(a.kind || 'door').toLowerCase() === 'window' ? 'window' : 'door', wd = (Number(a.width_in) || (kind === 'door' ? 32 : 36)) * IN;
    let w = S.walls.find(x => x.id === a.wall), off;
    const r = findRoom(a.room);
    if (r){ const sd = findSide(r, a.wall); if (!sd) return fail(`No side "${a.wall}" in ${r.name}`); w = sd.wall;
      const pos = a.position == null || String(a.position).toLowerCase() === 'center' ? (sd.len - wd) / 2 : Number(a.position) * IN;
      const p0 = add(sd.left, mul(sd.dir, pos)), p1 = add(p0, mul(sd.dir, wd)), {d} = wallFrame(w); off = Math.min(dot(sub(p0, w.s), d), dot(sub(p1, w.s), d));
    } else if (w){ off = (wallFrame(w).L - wd) / 2; } else return fail('Give a room and side, or a wall id');
    const o = {id: uid('N-O'), host: w.id, kind, off: snapIn(off), w: wd, h: (Number(a.height_in) || (kind === 'door' ? 80 : 48)) * IN, sill: (a.sill_in != null ? Number(a.sill_in) : kind === 'door' ? 0 : 36) * IN, name: a.name || (kind === 'door' ? 'New door' : 'New window'), op: kind === 'door' ? 'swing' : 'double-hung'};
    if (o.off < 0.05 || o.off + o.w > wallFrame(w).L - 0.05) return fail('That runs past the end of the wall');
    push({do: 'add_opening', opening: o}); return out(`added ${o.id}, a ${inch(wd)}" ${kind} in ${w.name}`);
  }
  if (act === 'remove_opening'){ const o = S.openings.find(x => x.id === a.id); if (!o) return fail(`No opening ${a.id}`); push({do: 'remove_opening', opening: o.id}); return out(`removed ${o.name}`); }
  if (act === 'resize_opening'){ const o = S.openings.find(x => x.id === a.id); if (!o) return fail(`No opening ${a.id}`);
    const wd = a.width_in ? Number(a.width_in) * IN : o.w, c = o.off + o.w / 2;
    push({do: 'set_opening', opening: o.id, w: wd, off: snapIn(c - wd / 2), sill: a.sill_in != null ? Number(a.sill_in) * IN : undefined, h: a.height_in ? Number(a.height_in) * IN : undefined}); return out(`resized ${o.name}`); }
  if (act === 'rename_room'){ const r = findRoom(a.room); if (!r) return fail(`No room "${a.room}"`); push({do: 'name_room', at: r.pt, name: String(a.name)}); return out(`renamed ${r.name} to ${a.name}`); }
  if (act === 'set_roof'){ const r = (S.roofs || []).find(x => x.id === a.roof) || (S.roofs || [])[0]; const fr = ['truss', 'rafter', 'unknown'].includes(a.framing) ? a.framing : null; if (!r || !fr) return fail('roof id and framing truss|rafter|unknown');
    push({do: 'set_roof', roof: r.id, framing: fr}); return out(`${r.name}: ${FRAMING[fr].label}`); }
  if (act === 'add_beam'){ if (!PLAN.walls.some(w => w.id === a.wall)) return fail(`No as-built wall ${a.wall}`); const b = beamFor(a.wall); push({do: 'add_beam', beam: b}); return out(`added ${b.name}`); }
  if (act === 'fix_checks'){ const r = applyFixes(null, true); if (!r.ops.length) return fail(r.fails.join(' ') || 'Nothing to fix'); r.ops.forEach(op => push(op)); return out(r.what); }
  return fail(`Unknown action "${a.action}"`);
}

const RULES = `You are the design assistant inside a floor-plan editor for a home renovation (the "Rebuilt" design editor). The person is a real-estate investor, not a builder: plain words, short answers.

You can change the plan ONLY by calling the apply_changes tool with a list of actions. Changes are a PREVIEW: the person clicks Apply (or Discard) in the panel, so never say they are saved or done; say what you set up and that they can apply it.

Actions (JSON objects in "actions"):
- {"action":"place","item":"queen","room":"Bedroom 2","wall":"north","position":"center"} — item one of: base, sink, upper, tall, island, range, fridge, dw, vanity, toilet, tub, shower, washer, dryer, king, queen, full, twin, night, dresser, sofa, table. wall = a side (north/south/east/west) or wall id; position = center | left | right | inches from the left end | omit for the best spot on that wall. Omit wall to let the editor choose a sensible spot (solid wall, away from doors, clear of windows for tall items). Optional width_in, depth_in, count.
- {"action":"place","item":"night","room":"Bedroom 2","beside":"<item id>","side":"both"} — next to an item on the same wall (left/right/both).
- {"action":"move_item","id":"...","room":"...","wall":"east","position":"center"} or {"action":"move_item","id":"...","shift_in":12,"direction":"left|right|forward|back"} or just {"action":"move_item","id":"..."} to let the editor pick a better spot.
- {"action":"resize_item","id":"...","width_in":36} · {"action":"remove_item","id":"..."}
- {"action":"cabinet_run","room":"Kitchen","wall":"north"} — fills that wall with base + upper cabinets, sink under the window.
- {"action":"remove_wall","wall":"W-..."} · {"action":"move_wall","wall":"W-...","inches":12,"toward":"<room it moves into>","stretch_attached":false}
- {"action":"split_room","room":"...","line":"north-south|east-west","at_in":120} — new wall across the room, at inches from its west (north-south line) or south (east-west line) inside face.
- {"action":"add_opening","room":"...","wall":"east","kind":"door|window","width_in":32,"position":"center|<inches from left>"} · {"action":"remove_opening","id":"..."} · {"action":"resize_opening","id":"...","width_in":36,"sill_in":42}
- {"action":"rename_room","room":"...","name":"..."} · {"action":"set_roof","roof":"R1","framing":"truss|rafter|unknown"} · {"action":"add_beam","wall":"<removed bearing wall id>"} · {"action":"fix_checks"}

Good layout sense: bed headboard on a solid wall (not across a window if avoidable), centred, with 24-36" walking room at the sides and foot and a nightstand each side when there is room; sofa and dresser on solid walls clear of door swings; island needs 42" walkways (36" minimum); toilet needs 15" from its centre to side walls and 21" clear in front; keep door swings and windows clear. Use the room data below: sides, inside lengths, openings with their positions, what is already against each wall. Walls marked BEARING or maybe-bearing need a beam if removed (add_beam).

Call apply_changes once with everything, read the result (it reports what happened and the checks), fix anything that failed or created a problem with a second call if needed, then reply in 1-4 short sentences: what you set up, and any check that is still open. If the request is unclear or big (e.g. which wall to remove), ask one short question instead of guessing.`;

async function sendChat(msg){
  if (!sampleFn) return;
  const log = $('#chatLog'), bubble = addBubble('assistant', 'Thinking…'), userMsg = msg;
  chatTurns.push({role: 'user', content: userMsg});
  chatCtl = new AbortController(); setChatBusy(true);
  const tools = [{
    name: 'apply_changes',
    description: 'Apply a list of plan changes to the preview (see the actions list in the instructions). Returns what happened to each action, the updated room list, and the current checks.',
    inputSchema: {type: 'object', properties: {actions: {type: 'array', items: {type: 'object'}}}, required: ['actions']},
    execute: (input) => {
      const acts = Array.isArray(input.actions) ? input.actions : [];
      const res = acts.map(a => { try { return {action: a.action, ...doAction(a)}; } catch (e) { return {action: a.action, ok: false, error: String(e && e.message || e)}; } });
      afterChange(false); showProposal();
      bubble.querySelector('.steps').textContent = `${proposal.length} change${proposal.length === 1 ? '' : 's'} previewed…`;
      return {results: res, checks: computeChecks().map(x => x.msg), rooms_now: rooms.filter(r => r.area > 0.3).map(r => `${r.id} "${r.name}" ${Math.round(r.area * 10.764)} sf`)};
    },
  }, {
    name: 'clear_preview',
    description: 'Throw away every previewed change from this request and start over. Returns the plan as it is without them.',
    execute: () => { proposal = []; rebuild(); afterChange(false); showProposal(); return describePlan(); },
  }];
  const recent = chatTurns.slice(-9, -1).map(t => ({role: t.role, content: t.content}));
  const input = [{role: 'user', content: RULES}, ...recent, {role: 'user', content: 'Current plan:\n' + describePlan() + '\n\nRequest: ' + userMsg}];
  try {
    const {text} = await sampleFn(input, {tools, signal: chatCtl.signal, onText: ({text}) => { bubble.querySelector('.txt').textContent = text.split(/\n\n+/).pop(); }});
    const final = text.split(/\n\n+/).filter(Boolean).pop() || text;
    bubble.querySelector('.txt').textContent = final; chatTurns.push({role: 'assistant', content: final});
  } catch (e) {
    const m = {cancelled: 'Stopped.', not_granted: 'Chat needs your OK to use Claude from this page.', rate_limited: 'Too many requests right now — try again in a minute.',
      tools_unavailable: 'This view can’t run the editor tools, so chat can’t change the plan here.', refused: 'I can’t help with that one.'}[e && e.code] || 'Something went wrong — try again.';
    bubble.querySelector('.txt').textContent = (e && e.text ? e.text.split(/\n\n+/).pop() + '\n\n' : '') + m;
    if (e && (e.code === 'not_granted' || e.code === 'sampling_disabled')) { sampleFn = null; $('#chatForm').hidden = true; }
    chatTurns.pop();
  } finally {
    setChatBusy(false); bubble.querySelector('.steps').textContent = proposal.length ? `${proposal.length} change${proposal.length === 1 ? '' : 's'} ready — Apply or Discard below` : '';
    log.scrollTop = log.scrollHeight;
  }
}
function addBubble(role, text){
  const d = document.createElement('div'); d.className = 'msg ' + role;
  const t = document.createElement('div'); t.className = 'txt'; t.textContent = text; d.appendChild(t);
  const st = document.createElement('div'); st.className = 'steps'; d.appendChild(st);
  $('#chatLog').appendChild(d); $('#chatLog').scrollTop = 1e9; return d;
}
function setChatBusy(b){ $('#chatSend').hidden = b; $('#chatStop').hidden = !b; $('#chatIn').disabled = b; }
function showProposal(){
  const bar = $('#propBar'); bar.hidden = !proposal.length;
  $('#propN').textContent = `Preview: ${proposal.length} change${proposal.length === 1 ? '' : 's'} not applied yet`;
}
function applyProposal(){
  if (!proposal.length) return;
  const p = proposal, last = [...chatTurns].reverse().find(t => t.role === 'user');
  proposal = []; rebuild();
  commit({do: 'batch', ops: p, label: 'Chat: ' + (last ? last.content.slice(0, 70) : `${p.length} changes`)});
  showProposal(); toast('Applied. Undo takes it all back in one step.');
}
function discardProposal(){ proposal = []; rebuild(); afterChange(false); showProposal(); toast('Preview discarded.'); }
async function initChat(){
  try { sampleFn = window.claude ? await window.claude.use('sample') : null; } catch (e) { sampleFn = null; }
  if (sampleFn){ try { const lim = await sampleFn.limits(); if (!lim || !lim.tools) sampleFn = null; } catch (e) { /* keep: the call itself will say */ } }
  $('#chatBtn').hidden = !sampleFn;
}
