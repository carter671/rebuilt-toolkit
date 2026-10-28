/* ---------------- catalogue: cabinets, fixtures, furniture ---------------- */
// sizes in inches; z = bottom above the floor. wall:true = backs up to the nearest wall when placed.
const STD = [9, 12, 15, 18, 21, 24, 27, 30, 33, 36];
const CAT = {
  base:    {g: 'Kitchen', label: 'Base cabinet', w: 30, d: 24, h: 36, z: 0, wall: true, widths: STD, cab: 'base'},
  sink:    {g: 'Kitchen', label: 'Sink base', w: 36, d: 24, h: 36, z: 0, wall: true, widths: [30, 33, 36], cab: 'base'},
  upper:   {g: 'Kitchen', label: 'Upper cabinet', w: 30, d: 12, h: 36, z: 54, wall: true, widths: STD, cab: 'wall'},
  tall:    {g: 'Kitchen', label: 'Pantry cabinet', w: 24, d: 24, h: 84, z: 0, wall: true, widths: [18, 24, 30, 36], cab: 'tall'},
  island:  {g: 'Kitchen', label: 'Island', w: 72, d: 36, h: 36, z: 0, wall: false, widths: [48, 60, 72, 84, 96], cab: 'island'},
  range:   {g: 'Kitchen', label: 'Range', w: 30, d: 26, h: 36, z: 0, wall: true, widths: [30, 36], cab: 'range'},
  fridge:  {g: 'Kitchen', label: 'Refrigerator', w: 36, d: 30, h: 70, z: 0, wall: true, widths: [30, 33, 36], cab: 'fridge'},
  dw:      {g: 'Kitchen', label: 'Dishwasher', w: 24, d: 24, h: 34.5, z: 0, wall: true, widths: [18, 24]},
  vanity:  {g: 'Bath', label: 'Vanity', w: 36, d: 21, h: 34.5, z: 0, wall: true, widths: [24, 30, 36, 48, 60, 72], cab: 'vanity'},
  toilet:  {g: 'Bath', label: 'Toilet', w: 20, d: 28, h: 30, z: 0, wall: true},
  tub:     {g: 'Bath', label: 'Tub', w: 60, d: 30, h: 20, z: 0, wall: true, widths: [60, 66, 72]},
  shower:  {g: 'Bath', label: 'Shower', w: 48, d: 36, h: 4, z: 0, wall: true, widths: [36, 48, 60]},
  washer:  {g: 'Laundry', label: 'Washer', w: 27, d: 30, h: 38, z: 0, wall: true},
  dryer:   {g: 'Laundry', label: 'Dryer', w: 27, d: 30, h: 38, z: 0, wall: true},
  king:    {g: 'Bedroom', label: 'King bed', w: 76, d: 80, h: 24, z: 0, wall: true},
  queen:   {g: 'Bedroom', label: 'Queen bed', w: 60, d: 80, h: 24, z: 0, wall: true},
  full:    {g: 'Bedroom', label: 'Full bed', w: 54, d: 75, h: 24, z: 0, wall: true},
  twin:    {g: 'Bedroom', label: 'Twin bed', w: 39, d: 75, h: 24, z: 0, wall: true},
  night:   {g: 'Bedroom', label: 'Nightstand', w: 22, d: 16, h: 26, z: 0, wall: true},
  dresser: {g: 'Bedroom', label: 'Dresser', w: 60, d: 18, h: 32, z: 0, wall: true},
  sofa:    {g: 'Living', label: 'Sofa', w: 84, d: 36, h: 34, z: 0, wall: true},
  table:   {g: 'Living', label: 'Dining table', w: 72, d: 40, h: 30, z: 0, wall: false},
  filler:  {g: null, label: 'Filler', w: 3, d: 24, h: 36, z: 0, wall: true, cab: 'filler'},
};
const isUpper = it => it.z > 1.0;
function newItem(cat, extra){
  const c = CAT[cat];
  return Object.assign({id: uid('N-I'), cat, st: ST, at: [0, 0], rot: 0, w: c.w * IN, d: c.d * IN, h: c.h * IN, z: c.z * IN, name: c.label}, extra || {});
}
// item frame: w along a, d along f (f = front, away from the wall it backs to)
function itemFrame(it){ const r = it.rot * Math.PI / 180; return {a: [Math.cos(r), Math.sin(r)], f: [-Math.sin(r), Math.cos(r)]}; }
function itemPoly(it, grow){
  const {a, f} = itemFrame(it), g = grow || 0, hw = it.w / 2 + g, hd = it.d / 2 + g;
  return [add(add(it.at, mul(a, -hw)), mul(f, -hd)), add(add(it.at, mul(a, hw)), mul(f, -hd)), add(add(it.at, mul(a, hw)), mul(f, hd)), add(add(it.at, mul(a, -hw)), mul(f, hd))];
}
const rotOf = f => Math.round(Math.atan2(-f[0], f[1]) * 180 / Math.PI * 1000) / 1000;

// place an item so its back sits on the nearest wall face, then snap its ends to neighbours / corners
function snapItem(it, back){
  const c = CAT[it.cat];
  it.st = storeyAt(back);
  if (!c.wall){ const {f} = itemFrame(it); it.at = add([snapIn(back[0]), snapIn(back[1])], mul(f, it.d / 2)); return null; }
  let best = null;
  S.walls.filter(w => w.st === it.st).forEach(w => { const pr = projOnSeg(back, w.s, w.e); if (pr.t > 0 && pr.t < 1 && pr.d < 0.9 && (!best || pr.d < best.pr.d)) best = {w, pr}; });
  if (!best){ const {f} = itemFrame(it); it.at = add([snapIn(back[0]), snapIn(back[1])], mul(f, it.d / 2)); return null; }
  const w = best.w, {d: wd, n, L} = wallFrame(w);
  let side = Math.sign(dot(sub(back, best.pr.q), n)) || 1;
  const f = mul(n, side); it.rot = rotOf(f);
  let u = snapIn(dot(sub(back, w.s), wd));
  // edge snaps (within 3 in): wall faces at corners, then other items on the same wall face
  const tol = 3 * IN, half = it.w / 2, cands = [];
  S.walls.forEach(o => {
    if (o.id === w.id || o.st !== w.st || Math.abs(dot(wallFrame(o).d, wd)) > 0.3) return;
    for (const end of ['s', 'e']){ const pr = projOnSeg(o[end], w.s, w.e); const other = end === 's' ? o.e : o.s;
      if (pr.d < w.t / 2 + TOL && dot(sub(other, o[end]), n) * side > 0){ const uu = dot(sub(o[end], w.s), wd); cands.push(uu + o.t / 2, uu - o.t / 2); } }
    const pr2 = projOnSeg(w.s, o.s, o.e); if (pr2.d < o.t / 2 + TOL) cands.push(o.t / 2);
    const pr3 = projOnSeg(w.e, o.s, o.e); if (pr3.d < o.t / 2 + TOL) cands.push(L - o.t / 2);
  });
  const backLine = dot(w.s, n) + side * (w.t / 2);
  S.items.forEach(o => {
    if (o.id === it.id || o.st !== it.st || isUpper(o) !== isUpper(it)) return;
    const of = itemFrame(o).f; if (dot(of, f) < 0.99) return;
    if (Math.abs(dot(o.at, n) - side * o.d / 2 - backLine) > 0.03) return;
    const ou = dot(sub(o.at, w.s), wd); cands.push(ou - o.w / 2, ou + o.w / 2);
  });
  let bestDu = null;
  cands.forEach(cu => { for (const du of [cu - (u - half), cu - (u + half)]) if (Math.abs(du) < tol && (bestDu === null || Math.abs(du) < Math.abs(bestDu))) bestDu = du; });
  if (bestDu !== null) u += bestDu;
  u = Math.max(half, Math.min(L - half, u));
  const q = add(w.s, mul(wd, u));
  it.at = add(q, mul(f, w.t / 2 + it.d / 2 + 0.003));
  return {wall: w.id, side};
}

// cabinet run along the clicked side of a wall: base cabinets (sink centred under a window) + uppers
function cabinetRun(w, at){
  const {d: wd, n, L} = wallFrame(w);
  let side = Math.sign(dot(sub(at, w.s), n));
  const inRoom = sd => rooms.some(r => r.st === w.st && inPoly(add(at, mul(n, sd * 0.5)), r.poly));
  if (!side || !inRoom(side)) side = inRoom(1) ? 1 : -1;
  const uc = dot(sub(at, w.s), wd);
  const blocks = (forUpper) => {
    const bl = [];
    S.walls.forEach(o => {
      if (o.id === w.id || o.st !== w.st || Math.abs(dot(wallFrame(o).d, wd)) > 0.3) return;
      for (const end of ['s', 'e']){ const pr = projOnSeg(o[end], w.s, w.e); const other = end === 's' ? o.e : o.s;
        if (pr.d < w.t / 2 + TOL && dot(sub(other, o[end]), n) * side > 0){ const uu = dot(sub(o[end], w.s), wd); bl.push([uu - o.t / 2, uu + o.t / 2]); } }
      if (projOnSeg(w.s, o.s, o.e).d < o.t / 2 + TOL) bl.push([-1, o.t / 2]);
      if (projOnSeg(w.e, o.s, o.e).d < o.t / 2 + TOL) bl.push([L - o.t / 2, L + 1]);
    });
    S.openings.filter(o => o.host === w.id).forEach(o => {
      if (o.kind === 'door') bl.push([o.off - 3 * IN, o.off + o.w + 3 * IN]);
      else if (forUpper) bl.push([o.off - 2 * IN, o.off + o.w + 2 * IN]);
      else if (o.sill < 36 * IN) bl.push([o.off - 2 * IN, o.off + o.w + 2 * IN]);   // low window: no counter under it
    });
    return bl;
  };
  const free = (bl, lo, hi) => {
    let a = lo, b = hi;
    bl.forEach(([x0, x1]) => { if (x1 <= uc) a = Math.max(a, x1); else if (x0 >= uc) b = Math.min(b, x0); else { a = b = uc; } });
    return [a, b];
  };
  const [b0, b1] = free(blocks(false), 0, L);
  if (b1 - b0 < 12 * IN){ toast('No room for cabinets at that spot (doors or walls in the way).'); return; }
  const tall = w.h >= 2.43;
  const fill = (u0, u1) => {          // greedy standard widths, filler for the remainder
    const out = []; let rem = (u1 - u0) / IN, u = u0;
    while (rem >= 9 - 1e-6){ const wd2 = STD.slice().reverse().find(x => x <= rem + 1e-6); out.push([u, u + wd2 * IN, wd2]); u += wd2 * IN; rem -= wd2; }
    if (rem > 0.4) out.push([u, u1, rem]);
    return out;
  };
  const place = (cat, u0, u1, extra) => {
    const it = newItem(cat, Object.assign({st: w.st, w: u1 - u0}, extra || {}));
    const f = mul(n, side); it.rot = rotOf(f);
    it.at = add(add(w.s, mul(wd, (u0 + u1) / 2)), mul(f, w.t / 2 + it.d / 2 + 0.003));
    return it;
  };
  const items = [];
  // sink base centred under a window that sits inside the run
  const win = S.openings.find(o => o.host === w.id && o.kind === 'window' && o.off >= b0 && o.off + o.w <= b1);
  const parts = [];
  if (win && b1 - b0 >= 36 * IN){
    let s0 = win.off + win.w / 2 - 18 * IN; s0 = Math.max(b0, Math.min(b1 - 36 * IN, s0)); s0 = b0 + snapIn(s0 - b0);
    parts.push(['L', b0, s0], ['S', s0, s0 + 36 * IN], ['R', s0 + 36 * IN, b1]);
  } else parts.push(['L', b0, b1]);
  parts.forEach(([k, u0, u1]) => {
    if (k === 'S'){ items.push(place('sink', u0, u1)); return; }
    // keep fillers against walls: fill from the far side of the sink
    const units = fill(u0, u1);
    if (k === 'L' && units.length && units[units.length - 1][2] < 9){ const fl = units.pop(); units.unshift(fl); let u = u0; units.forEach(x => { const wd2 = x[1] - x[0]; x[0] = u; x[1] = u + wd2; u += wd2; }); }
    units.forEach(([x0, x1, inch]) => items.push(inch < 9 ? place('filler', x0, x1) : place('base', x0, x1)));
  });
  // uppers over the same stretch, broken at windows
  const ubl = blocks(true).filter(([x0, x1]) => x1 > b0 && x0 < b1);
  let segs = [[b0, b1]];
  ubl.forEach(([x0, x1]) => { segs = segs.flatMap(([s0, s1]) => x1 <= s0 || x0 >= s1 ? [[s0, s1]] : [[s0, x0], [x1, s1]].filter(([p, q]) => q - p >= 9 * IN)); });
  let nU = 0;
  segs.forEach(([s0, s1]) => fill(s0, s1).forEach(([x0, x1, inch]) => { items.push(inch < 9 ? place('filler', x0, x1, {d: 12 * IN, h: (tall ? 36 : 30) * IN, z: 54 * IN, name: 'Filler (upper)'}) : place('upper', x0, x1, {h: (tall ? 36 : 30) * IN})); nU++; }));
  const nB = items.length - nU;
  commit({do: 'batch', ops: items.map(it => ({do: 'add_item', item: it})), label: `Added cabinet run on ${w.name || 'wall'} (${ftin(b1 - b0)}: ${nB} base, ${nU} upper)`});
  sel = null; hidePop();
}

/* plan symbols */
function drawItems(g, upper){
  S.items.filter(it => SHOW.has(it.st) && isUpper(it) === upper).forEach(it => {
    const P = itemPoly(it), bad = issueIds.has(it.id), on = sel && sel.kind === 'item' && sel.id === it.id;
    const grp = el('g', {class: 'item' + (upper ? ' up' : '') + (bad ? ' bad' : '') + (on ? ' sel' : ''), 'data-item': it.id}, g);
    el('polygon', {points: pts(P), 'stroke-width': (on ? 2.2 : 1.2) * pxm(), 'stroke-dasharray': upper ? `${5 * pxm()} ${3 * pxm()}` : ''}, grp);
    const {a, f} = itemFrame(it), L = (u, v) => add(add(it.at, mul(a, u * it.w / 2)), mul(f, v * it.d / 2));
    const line = (p, q) => el('line', {x1: toSvg(p)[0], y1: toSvg(p)[1], x2: toSvg(q)[0], y2: toSvg(q)[1], class: 'sym', 'stroke-width': pxm()}, grp);
    const circ = (p, r) => el('circle', {cx: toSvg(p)[0], cy: toSvg(p)[1], r, class: 'sym', 'stroke-width': pxm()}, grp);
    const sw = pxm();
    switch (it.cat){
      case 'base': case 'tall': line(L(-1, 0.8), L(1, 0.8)); if (it.cat === 'tall'){ line(L(-1, -1), L(1, 0.8)); } break;
      case 'sink': el('polygon', {points: pts([L(-0.75, -0.6), L(0.75, -0.6), L(0.75, 0.5), L(-0.75, 0.5)]), class: 'sym', 'stroke-width': sw}, grp); break;
      case 'range': [[-0.5, -0.45], [0.5, -0.45], [-0.5, 0.4], [0.5, 0.4]].forEach(([u, v]) => circ(L(u, v), Math.min(it.w, it.d) * 0.16)); break;
      case 'vanity': circ(L(0, -0.1), Math.min(it.w, it.d) * 0.28); break;
      case 'toilet': line(L(-1, -0.45), L(1, -0.45)); el('ellipse', {cx: toSvg(L(0, 0.3))[0], cy: toSvg(L(0, 0.3))[1], rx: it.w * 0.4, ry: it.d * 0.32, transform: `rotate(${-it.rot} ${toSvg(L(0, 0.3)).join(' ')})`, class: 'sym', 'stroke-width': sw}, grp); break;
      case 'tub': el('polygon', {points: pts([L(-0.88, -0.75), L(0.88, -0.75), L(0.88, 0.8), L(-0.88, 0.8)]), class: 'sym', 'stroke-width': sw}, grp); circ(L(-0.75, 0), 0.03); break;
      case 'shower': line(L(-1, -1), L(1, 1)); line(L(1, -1), L(-1, 1)); break;
      case 'king': case 'queen': case 'full': case 'twin': {
        const k = it.cat === 'twin' ? [[0, 0.8]] : [[-0.5, 0.42], [0.5, 0.42]];
        k.forEach(([u, hw]) => el('polygon', {points: pts([L(u - hw / 2 * 0.9, -0.92), L(u + hw / 2 * 0.9, -0.92), L(u + hw / 2 * 0.9, -0.72), L(u - hw / 2 * 0.9, -0.72)]), class: 'sym', 'stroke-width': sw}, grp));
        line(L(-1, -0.45), L(1, -0.2)); break; }
      case 'sofa': line(L(-1, -0.45), L(1, -0.45)); line(L(-0.85, -0.45), L(-0.85, 1)); line(L(0.85, -0.45), L(0.85, 1)); break;
      case 'fridge': case 'dw': case 'washer': case 'dryer': {
        const t = {fridge: 'REF', dw: 'DW', washer: 'W', dryer: 'D'}[it.cat], [x, y] = toSvg(it.at);
        el('text', {x, y: y + 4 * pxm(), class: 'sym-t', 'font-size': 10 * pxm()}, grp).textContent = t; break; }
    }
    grp.addEventListener('pointerdown', ev => startItemDrag(ev, it.id));
  });
}

/* item dragging + placing from the catalogue */
let placing = null;
function startPlacing(cat){
  setTool('select'); sel = null; hidePop();
  placing = newItem(cat); placing.ghost = true;
  document.querySelectorAll('.cat button').forEach(b => b.setAttribute('aria-pressed', b.dataset.cat === cat));
  toast(CAT[cat].wall ? `Move to a wall and click to place the ${CAT[cat].label.toLowerCase()}. Esc to cancel.` : `Click to place the ${CAT[cat].label.toLowerCase()}. Esc to cancel.`);
}
function stopPlacing(){ placing = null; document.querySelectorAll('.cat button').forEach(b => b.setAttribute('aria-pressed', 'false')); drawPlan(); }
function startItemDrag(ev, id){
  if (placing || tool !== 'select' || ev.button > 0) return;
  ev.stopPropagation(); svg.setPointerCapture(ev.pointerId);
  const it = S.items.find(x => x.id === id), {f} = itemFrame(it);
  drag = {type: 'item', id, p0: screenToPlan(ev), back0: sub(it.at, mul(f, it.d / 2)), orig: clone(it), ev0: ev}; dragMoved = false;
}
function itemDragMove(ev, p){
  if (!dragMoved && Math.hypot(ev.clientX - drag.ev0.clientX, ev.clientY - drag.ev0.clientY) < 4) return;
  dragMoved = true;
  const it = S.items.find(x => x.id === drag.id); Object.assign(it, clone(drag.orig));
  snapItem(it, add(drag.back0, sub(p, drag.p0)));
  issues = computeChecks(); drawPlan(); build3D();
}
function itemDragEnd(d, ev){
  const it = S.items.find(x => x.id === d.id);
  if (!dragMoved){ select({kind: 'item', id: d.id}, ev); return; }
  const v = {at: it.at, rot: it.rot, st: it.st}; rebuild();
  commit({do: 'set_item', item: d.id, ...v, label: `Moved ${it.name}`});
  sel = {kind: 'item', id: d.id}; drawPlan();
}
function itemPop(t){
  const it = S.items.find(x => x.id === sel.id); if (!it){ hidePop(); return false; }
  const c = CAT[it.cat];
  t.textContent = `${it.name} · ${ftin(it.w)} wide` + (isUpper(it) ? ` · ${ftin(it.z)} up` : '');
  (c.widths || []).forEach(inch => { const b = btn(`${inch}"`, () => resizeItem(it, inch * IN)); if (Math.abs(it.w - inch * IN) < 0.005) b.setAttribute('aria-pressed', 'true'); });
  btn('Rotate', () => { commit({do: 'set_item', item: it.id, rot: (it.rot + 90) % 360, label: `Rotated ${it.name}`}); showPop(null); });
  btn('Copy', () => { const {a} = itemFrame(it), cp = clone(it); cp.id = uid('N-I'); cp.at = add(it.at, mul(a, it.w)); commit({do: 'add_item', item: cp, label: `Copied ${it.name}`}); sel = {kind: 'item', id: cp.id}; drawPlan(); showPop(null); });
  btn('Remove', () => { commit({do: 'remove_item', item: it.id, label: `Removed ${it.name}`}); sel = null; hidePop(); }, 'danger');
  return true;
}
function resizeItem(it, wNew){
  const {a} = itemFrame(it), at = add(it.at, mul(a, (wNew - it.w) / 2));   // keep the left end where it is
  commit({do: 'set_item', item: it.id, w: wNew, at, label: `${it.name} → ${ftin(wNew)}`}); showPop(null);
}

/* ---------------- live checks ---------------- */
let issues = [], issueIds = new Set();
function sat(A, B){
  // true if convex polygons A and B overlap by more than 1 cm
  for (const P of [A, B]) for (let i = 0; i < P.length; i++){
    const e = sub(P[(i + 1) % P.length], P[i]), ax = unit(perp(e));
    const pa = A.map(p => dot(p, ax)), pb = B.map(p => dot(p, ax));
    if (Math.max(...pa) < Math.min(...pb) + 0.01 || Math.max(...pb) < Math.min(...pa) + 0.01) return false;
  }
  return true;
}
function computeChecks(){
  const out = [], zr = it => [it.z, it.z + it.h];
  const its = S.items.filter(it => SHOW.has(it.st));
  for (let i = 0; i < its.length; i++) for (let j = i + 1; j < its.length; j++){
    const A = its[i], B = its[j]; if (A.st !== B.st) continue;
    const [a0, a1] = zr(A), [b0, b1] = zr(B); if (a1 <= b0 + 0.01 || b1 <= a0 + 0.01) continue;
    if (sat(itemPoly(A), itemPoly(B))) out.push({ids: [A.id, B.id], msg: `${A.name} overlaps ${B.name}`});
  }
  its.forEach(it => {
    S.walls.filter(w => w.st === it.st).forEach(w => { if (sat(itemPoly(it, -0.002), wallPoly(w))) out.push({ids: [it.id], msg: `${it.name} runs into ${w.name || 'a wall'}`}); });
    if (isUpper(it)) return;
    S.openings.filter(o => o.kind === 'door' && o.w < 1.25).forEach(o => {
      const w = S.walls.find(x => x.id === o.host); if (!w || w.st !== it.st) return;
      const {d, n} = wallFrame(w), side = w.ext ? -1 : 1, a = add(w.s, mul(d, o.off)), b = add(w.s, mul(d, o.off + o.w));
      const swing = [add(a, mul(n, side * w.t / 2)), add(b, mul(n, side * w.t / 2)), add(b, mul(n, side * (w.t / 2 + o.w))), add(a, mul(n, side * (w.t / 2 + o.w)))];
      if (sat(itemPoly(it), swing)) out.push({ids: [it.id], msg: `${it.name} is in the swing of ${o.name || 'a door'}`});
    });
  });
  // walkway between facing counters (island to counters) under 36 in
  its.filter(it => it.cat === 'island').forEach(isl => its.filter(o => o !== isl && !isUpper(o) && CAT[o.cat].cab && o.cat !== 'island' && o.st === isl.st).forEach(o => {
    const P = itemPoly(isl), Q = itemPoly(o); let md = 1e9;
    P.forEach(p => { for (let k = 0; k < 4; k++) md = Math.min(md, projOnSeg(p, Q[k], Q[(k + 1) % 4]).d); });
    Q.forEach(p => { for (let k = 0; k < 4; k++) md = Math.min(md, projOnSeg(p, P[k], P[(k + 1) % 4]).d); });
    if (md > 0.02 && md < 36 * IN) out.push({ids: [isl.id, o.id], msg: `Only ${ftin(md)} between the island and ${o.name.toLowerCase()} (36" minimum, 42" is better)`});
  }));
  issueIds = new Set(out.flatMap(x => x.ids));
  return out;
}

/* 3D casework + furniture */
const IM = {
  cab: new THREE.MeshStandardMaterial({color: '#9A9491', roughness: .6}), top: new THREE.MeshStandardMaterial({color: '#EDEAE4', roughness: .3}),
  white: new THREE.MeshStandardMaterial({color: '#F4F4F2', roughness: .35}), steel: new THREE.MeshStandardMaterial({color: '#B8BCC0', roughness: .3, metalness: .6}),
  bed: new THREE.MeshStandardMaterial({color: '#FBFAF6', roughness: .9}), wood: new THREE.MeshStandardMaterial({color: '#8A6A4A', roughness: .7}),
  fabric: new THREE.MeshStandardMaterial({color: '#7E8A90', roughness: 1}), bad: new THREE.MeshStandardMaterial({color: '#B4432F', roughness: .6}),
  pick: new THREE.MeshStandardMaterial({color: '#D9732F', roughness: .6}),
};
function itemBox(it, u0, u1, v0, v1, z0, z1, mat, grp){
  // u along a (−1..1 of w/2), v along f (−1..1 of d/2), z metres above the floor
  const {a, f} = itemFrame(it), cu = (u0 + u1) / 4 * it.w, cv = (v0 + v1) / 4 * it.d;
  const g = new THREE.BoxGeometry((u1 - u0) / 2 * it.w, z1 - z0, (v1 - v0) / 2 * it.d), m = new THREE.Mesh(g, mat);
  const c = add(add(it.at, mul(a, cu)), mul(f, cv)); m.position.copy(P3(c[0], c[1], EL(it.st) + it.z + (z0 + z1) / 2));
  m.rotation.y = it.rot * Math.PI / 180; m.castShadow = true; m.receiveShadow = true; m.userData.item = it.id; grp.add(m); return m;
}
function buildItems3D(grp){
  S.items.filter(it => SHOW.has(it.st)).forEach(it => {
    const H = it.h, bad = issueIds.has(it.id), on = sel && sel.kind === 'item' && sel.id === it.id;
    const body = on ? IM.pick : bad ? IM.bad : IM.cab;
    switch (it.cat){
      case 'base': case 'sink': case 'vanity': case 'island':
        itemBox(it, -1, 1, -1, it.cat === 'island' ? 1 : 0.92, 0, H - 0.032, body, grp); itemBox(it, -1, 1, -1, 1.04, H - 0.032, H, IM.top, grp); break;
      case 'upper': case 'tall': case 'filler': itemBox(it, -1, 1, -1, 1, 0, H, body, grp); break;
      case 'range': itemBox(it, -1, 1, -1, 1, 0, H, on ? IM.pick : IM.steel, grp); break;
      case 'fridge': case 'dw': itemBox(it, -1, 1, -1, 1, 0, H, on ? IM.pick : IM.steel, grp); break;
      case 'toilet': case 'tub': case 'shower': case 'washer': case 'dryer': itemBox(it, -1, 1, -1, 1, 0, H, on ? IM.pick : bad ? IM.bad : IM.white, grp); break;
      case 'king': case 'queen': case 'full': case 'twin':
        itemBox(it, -1, 1, -1, 1, 0, 0.3, on ? IM.pick : bad ? IM.bad : IM.wood, grp); itemBox(it, -0.97, 0.97, -0.97, 0.97, 0.3, 0.6, IM.bed, grp); itemBox(it, -1, 1, -1, -0.94, 0, 1.2, on ? IM.pick : IM.wood, grp); break;
      case 'sofa': itemBox(it, -1, 1, -1, 1, 0, 0.45, on ? IM.pick : bad ? IM.bad : IM.fabric, grp); itemBox(it, -1, 1, -1, -0.45, 0.45, H, IM.fabric, grp); break;
      default: itemBox(it, -1, 1, -1, 1, 0, H, on ? IM.pick : bad ? IM.bad : IM.wood, grp);
    }
  });
}

/* catalogue panel */
function buildCatalogue(){
  const host = $('#cat'); host.innerHTML = '';
  const groups = [...new Set(Object.values(CAT).map(c => c.g).filter(Boolean))];
  groups.forEach(gname => {
    const h = document.createElement('div'); h.className = 'cat-g'; h.textContent = gname; host.appendChild(h);
    const row = document.createElement('div'); row.className = 'cat'; host.appendChild(row);
    Object.entries(CAT).filter(([, c]) => c.g === gname).forEach(([k, c]) => {
      const b = document.createElement('button'); b.textContent = c.label; b.dataset.cat = k; b.setAttribute('aria-pressed', 'false');
      b.onclick = () => placing && placing.cat === k ? stopPlacing() : startPlacing(k); row.appendChild(b);
    });
  });
}
