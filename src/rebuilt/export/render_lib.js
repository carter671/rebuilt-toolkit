// ---- Rebuilt rendered look (display only; geometry unchanged). Injected into a module that already has THREE.
// RB.apply({scene, renderer, sun, hemi, nodes, cfg, site, edges}) -> {set(on)}
const RB = (() => {
const rnd = seed => { let s = seed >>> 0 || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; };
function canvasTex(w, h, draw, sx, sy, opts = {}) {
  const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d'); draw(x, w, h);
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = opts.clamp ? THREE.ClampToEdgeWrapping : THREE.RepeatWrapping;
  t.anisotropy = 8; t.colorSpace = THREE.SRGBColorSpace; t.userData = {sx, sy}; return t;
}
const noise = (x, w, h, n, a, seed, col = 0) => { const r = rnd(seed); for (let i = 0; i < n; i++) { const v = col + Math.round((r() - .5) * a); x.fillStyle = `rgba(${v<0?0:255},${v<0?0:255},${v<0?0:255},${Math.abs(v)/255})`; x.fillRect(r() * w, r() * h, 1 + r() * 2, 1 + r() * 2); } };
const TX = {};
// lap siding, 6.9" exposure (matches the existing house); tile = 4 courses
TX.siding = canvasTex(256, 256, (x, w, h) => { const L = h / 4; for (let i = 0; i < 4; i++) { const y = i * L; const g = x.createLinearGradient(0, y, 0, y + L);
  g.addColorStop(0, '#bdbdbd'); g.addColorStop(.1, '#f2f2f2'); g.addColorStop(.6, '#ffffff'); g.addColorStop(.92, '#e9e9e9'); g.addColorStop(1, '#9e9e9e'); x.fillStyle = g; x.fillRect(0, y, w, L); }
  noise(x, w, h, 900, 18, 3); }, 1.2, 0.701);
// dimensional shingles, 5 5/8" exposure
TX.shingle = canvasTex(512, 256, (x, w, h) => { const r = rnd(7); x.fillStyle = '#fff'; x.fillRect(0, 0, w, h); const C = h / 4;
  for (let i = 0; i < 4; i++) { let px = -r() * 60; while (px < w) { const tw = 30 + r() * 55; const v = Math.round(170 + r() * 85); x.fillStyle = `rgb(${v},${v},${v})`; x.fillRect(px, i * C, tw, C);
    for (let k = 0; k < 30; k++) { const q = Math.round(v - 30 + r() * 60); x.fillStyle = `rgba(${q},${q},${q},.6)`; x.fillRect(px + r() * tw, i * C + r() * C, 2, 2); }
    x.fillStyle = 'rgba(30,30,30,.55)'; x.fillRect(px, i * C, 1.5, C); px += tw; }
    const g = x.createLinearGradient(0, i * C + C * .8, 0, i * C + C); g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,.5)'); x.fillStyle = g; x.fillRect(0, i * C + C * .8, w, C * .2); } }, 1.0, 0.572);
// wood-look planks, 7" wide, random lengths, warm oak
TX.wood = canvasTex(512, 512, (x, w, h) => { const r = rnd(11); const P = h / 8;
  for (let i = 0; i < 8; i++) { let px = -r() * 200; while (px < w) { const L = 140 + r() * 260; const hue = 28 + r() * 8, l = 46 + r() * 14;
    x.fillStyle = `hsl(${hue},45%,${l}%)`; x.fillRect(px, i * P, L, P);
    for (let k = 0; k < 14; k++) { x.strokeStyle = `hsla(${hue},40%,${l - 10 - r() * 8}%,.35)`; x.lineWidth = .6 + r(); x.beginPath(); const yy = i * P + r() * P; x.moveTo(px, yy); x.bezierCurveTo(px + L * .3, yy + (r() - .5) * 6, px + L * .7, yy + (r() - .5) * 6, px + L, yy + (r() - .5) * 3); x.stroke(); }
    x.fillStyle = 'rgba(40,25,10,.55)'; x.fillRect(px, i * P, 1.2, P); px += L; }
    x.fillStyle = 'rgba(40,25,10,.5)'; x.fillRect(0, i * P, w, 1.2); } }, 1.42, 1.42);
// 12x24 porcelain, light warm grey
TX.tile = canvasTex(512, 512, (x, w, h) => { const r = rnd(5); x.fillStyle = '#b9b4ab'; x.fillRect(0, 0, w, h);
  for (let j = 0; j < 4; j++) for (let i = -1; i < 3; i++) { const off = j % 2 ? w / 4 : 0; const v = 214 + r() * 14; x.fillStyle = `rgb(${v},${v - 3},${v - 9})`; x.fillRect(i * w / 2 + off + 2, j * h / 4 + 2, w / 2 - 4, h / 4 - 4); }
  noise(x, w, h, 1400, 22, 9); }, 1.219, 1.219);
TX.stone = canvasTex(512, 512, (x, w, h) => { const r = rnd(21); x.fillStyle = '#5e574f'; x.fillRect(0, 0, w, h); let y = 0;
  while (y < h) { const rh = 22 + r() * 40; let px = -r() * 80; while (px < w) { const rw = 50 + r() * 120; const v = 120 + r() * 70, hue = 25 + r() * 15;
    x.fillStyle = `hsl(${hue},${8 + r() * 10}%,${v / 2.55 * .62}%)`; x.fillRect(px + 2, y + 2, rw - 4, rh - 4); noise(x, rw, rh, 0, 0, 1); px += rw; } y += rh; }
  noise(x, w, h, 4000, 40, 4); }, 1.5, 1.5);
TX.brick = canvasTex(256, 256, (x, w, h) => { const r = rnd(31); x.fillStyle = '#b8b0a4'; x.fillRect(0, 0, w, h); const H = h / 8;
  for (let j = 0; j < 8; j++) { const off = j % 2 ? w / 8 : 0; for (let i = -1; i < 4; i++) { const v = r(); x.fillStyle = `rgb(${130 + v * 40},${70 + v * 22},${58 + v * 15})`; x.fillRect(i * w / 4 + off + 2, j * H + 2, w / 4 - 4, H - 4); } }
  noise(x, w, h, 1500, 40, 6); }, 0.81, 0.54);
TX.block = canvasTex(256, 128, (x, w, h) => { x.fillStyle = '#8f928c'; x.fillRect(0, 0, w, h); const r = rnd(41);
  for (let j = 0; j < 2; j++) for (let i = -1; i < 3; i++) { const off = j % 2 ? w / 4 : 0; const v = 175 + r() * 20; x.fillStyle = `rgb(${v},${v + 2},${v - 4})`; x.fillRect(i * w / 2 + off + 2, j * h / 2 + 2, w / 2 - 4, h / 2 - 4); }
  noise(x, w, h, 1800, 45, 8); }, 0.813, 0.406);
TX.shaker = canvasTex(256, 256, (x, w, h) => { x.fillStyle = '#ffffff'; x.fillRect(0, 0, w, h); const D = (x0, y0, ww, hh) => { x.fillStyle = 'rgba(0,0,0,.22)'; x.fillRect(x0, y0, ww, hh); x.fillStyle = '#f3f3f3'; x.fillRect(x0 + 2, y0 + 2, ww - 4, hh - 4);
  x.fillStyle = 'rgba(0,0,0,.14)'; x.fillRect(x0 + 22, y0 + 22, ww - 44, hh - 44); x.fillStyle = '#fafafa'; x.fillRect(x0 + 25, y0 + 25, ww - 50, hh - 50); x.fillStyle = '#8b8b8b'; x.fillRect(x0 + ww - 14, y0 + hh / 2 - 14, 4, 28); };
  D(4, 4, w / 2 - 8, h - 8); D(w / 2 + 4, 4, w / 2 - 8, h - 8); }, 0.914, 0.762);
TX.quartz = canvasTex(256, 256, (x, w, h) => { x.fillStyle = '#f6f5f1'; x.fillRect(0, 0, w, h); noise(x, w, h, 2500, 26, 12);
  x.strokeStyle = 'rgba(150,150,150,.25)'; x.lineWidth = 1; const r = rnd(3); for (let k = 0; k < 4; k++) { x.beginPath(); x.moveTo(r() * w, 0); x.bezierCurveTo(r() * w, h * .3, r() * w, h * .6, r() * w, h); x.stroke(); } }, 1.2, 1.2);
TX.steel = canvasTex(256, 256, (x, w, h) => { const r = rnd(2); for (let i = 0; i < w; i++) { const v = 175 + r() * 40; x.fillStyle = `rgb(${v},${v + 2},${v + 5})`; x.fillRect(i, 0, 1, h); } }, 0.6, 0.6);
TX.pavers = canvasTex(512, 512, (x, w, h) => { const r = rnd(51); x.fillStyle = '#8e8172'; x.fillRect(0, 0, w, h); const S = w / 4;
  for (let j = 0; j < 4; j++) for (let i = 0; i < 4; i++) { const v = r(); x.fillStyle = `rgb(${190 + v * 30},${168 + v * 26},${138 + v * 22})`; x.fillRect(i * S + 3, j * S + 3, S - 6, S - 6); }
  noise(x, w, h, 3000, 40, 13); }, 1.219, 1.219);
TX.walk = canvasTex(256, 256, (x, w, h) => { x.fillStyle = '#cbc6bc'; x.fillRect(0, 0, w, h); noise(x, w, h, 4000, 28, 14); x.fillStyle = 'rgba(0,0,0,.25)'; x.fillRect(0, 0, w, 2); x.fillRect(0, 0, 2, h); }, 1.52, 1.52);
TX.concrete = canvasTex(256, 256, (x, w, h) => { x.fillStyle = '#b4b0a8'; x.fillRect(0, 0, w, h); noise(x, w, h, 5000, 30, 15); }, 2.0, 2.0);
TX.deck = canvasTex(256, 256, (x, w, h) => { const r = rnd(61); const P = w / 8; for (let i = 0; i < 8; i++) { const v = r(); x.fillStyle = `rgb(${128 + v * 20},${100 + v * 15},${76 + v * 10})`; x.fillRect(i * P, 0, P - 2, h); } noise(x, w, h, 1500, 30, 16); }, 0.9, 0.9);
TX.asphalt = canvasTex(256, 256, (x, w, h) => { x.fillStyle = '#4a4c4f'; x.fillRect(0, 0, w, h); noise(x, w, h, 9000, 60, 17); }, 2.5, 2.5);
TX.grass = canvasTex(512, 512, (x, w, h) => { const r = rnd(71); x.fillStyle = '#6f8f4e'; x.fillRect(0, 0, w, h);
  for (let i = 0; i < 26000; i++) { const g = 100 + r() * 70; x.fillStyle = `rgba(${g * .55},${g},${g * .38},.55)`; x.fillRect(r() * w, r() * h, 1, 2 + r() * 3); } }, 3.0, 3.0);

// openings: one canvas per opening, drawn at its real proportions
const GLASS = 'rgba(160,190,205,0.07)', GL2 = 'rgba(215,230,238,0.12)';
function frameRect(x, X, Y, W, H, t, col = '#fbfbf8') { x.fillStyle = col; x.fillRect(X, Y, W, t); x.fillRect(X, Y + H - t, W, t); x.fillRect(X, Y, t, H); x.fillRect(X + W - t, Y, t, H); }
function glassFill(x, X, Y, W, H) { const g = x.createLinearGradient(X, Y, X + W, Y + H); g.addColorStop(0, GL2); g.addColorStop(.45, GLASS); g.addColorStop(.55, 'rgba(235,242,246,0.16)'); g.addColorStop(1, GLASS); x.fillStyle = g; x.fillRect(X, Y, W, H); }
function panelDoor(x, X, Y, W, H, k = 0.12) { x.fillStyle = '#f6f5f1'; x.fillRect(X, Y, W, H); const p = W * k; const ph = (H - 3 * p) / 2;
  for (const yy of [Y + p, Y + 2 * p + ph]) { x.fillStyle = 'rgba(0,0,0,.18)'; x.fillRect(X + p, yy, W - 2 * p, ph); x.fillStyle = '#fbfbf9'; x.fillRect(X + p + 3, yy + 3, W - 2 * p - 6, ph - 6); } }
function openingTex(o) {
  const ppm = 220, W = Math.max(32, Math.round(o.w * ppm)), H = Math.max(32, Math.round(o.h * ppm)), f = Math.round(0.06 * ppm);
  return canvasTex(W, H, (x) => {
    x.clearRect(0, 0, W, H);
    const t = o.t;
    if (t === 'panel') { panelDoor(x, 0, 0, W, H); frameRect(x, 0, 0, W, H, 4, '#e6e4de'); x.fillStyle = '#9a9a96'; x.fillRect(W - 24, H * .5, 8, 8); return; }
    if (t === 'overhead') { x.fillStyle = '#f4f4f2'; x.fillRect(0, 0, W, H); const rows = 4, cols = Math.max(2, Math.round(W / (0.6 * ppm)));
      for (let r = 0; r < rows; r++) { x.fillStyle = 'rgba(0,0,0,.28)'; x.fillRect(0, r * H / rows, W, 3); for (let k = 0; k < cols; k++) { const cw = W / cols, rh = H / rows; x.fillStyle = 'rgba(0,0,0,.14)'; x.fillRect(k * cw + 10, r * rh + 12, cw - 20, rh - 24); x.fillStyle = '#fbfbfa'; x.fillRect(k * cw + 13, r * rh + 15, cw - 26, rh - 30); } } return; }
    if (t === 'screen') { x.fillStyle = 'rgba(30,32,34,0.45)'; x.fillRect(0, 0, W, H); frameRect(x, 0, 0, W, H, f * .8, '#e9e6de'); return; }
    if (t === 'halflite') { panelDoor(x, 0, 0, W, H); x.fillStyle = '#f6f5f1'; x.fillRect(0, 0, W, H * .48); glassFill(x, f * 1.4, f * 1.4, W - f * 2.8, H * .48 - f * 2);
      frameRect(x, 0, 0, W, H, f * .8); x.fillStyle = '#b7a46a'; x.fillRect(W - 28, H * .52, 10, 14); return; }
    if (t === 'glassdoor' || t === 'french' || t === 'slider') { const n = t === 'glassdoor' ? 1 : 2; const lw = W / n;
      for (let i = 0; i < n; i++) { const X = i * lw; x.fillStyle = '#fbfbf8'; x.fillRect(X, 0, lw, H); glassFill(x, X + f * 1.2, f * 1.2, lw - f * 2.4, H - f * 1.2 - f * 2.6); frameRect(x, X, 0, lw, H, 3, '#d8d6d0'); }
      x.fillStyle = '#7d7d79'; x.fillRect(n === 1 ? W - 26 : W / 2 + (t === 'slider' ? -8 : 6), H * .48, 6, 26); return; }
    // windows
    glassFill(x, 0, 0, W, H); frameRect(x, 0, 0, W, H, f);
    if (t === 'dh') { const m = Math.round(0.035 * ppm); x.fillStyle = '#fbfbf8'; x.fillRect(0, H / 2 - m, W, 2 * m); frameRect(x, f * .6, f * .6, W - f * 1.2, H / 2 - f * .6, 3, 'rgba(0,0,0,.12)'); x.fillStyle = '#9a9a96'; x.fillRect(W / 2 - 10, H / 2 - m - 6, 20, 5); }
    if (t === 'casement') { x.fillStyle = 'rgba(0,0,0,.12)'; x.fillRect(f, f, 3, H - 2 * f); x.fillStyle = '#9a9a96'; x.fillRect(W - f - 6, H / 2 - 12, 4, 24); }
  }, 1, 1, {clamp: true});
}

const skins = [];
function skin(o, tx, keep, opt = {}) {
  o.updateWorldMatrix(true, false); const src = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry; const P = src.attributes.position; const M = o.matrixWorld;
  const A = new THREE.Vector3(), B = new THREE.Vector3(), C = new THREE.Vector3(), n = new THREE.Vector3(), c = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  const pos = [], uv = [], nor = []; const sx = tx.userData.sx, sy = tx.userData.sy; const W = [];
  for (let i = 0; i < P.count; i++) W.push(new THREE.Vector3().fromBufferAttribute(P, i).applyMatrix4(M));
  for (let i = 0; i < P.count; i += 3) { A.copy(W[i]); B.copy(W[i + 1]); C.copy(W[i + 2]); n.subVectors(C, B).cross(new THREE.Vector3().subVectors(A, B)).normalize(); if (!isFinite(n.x)) continue;
    c.copy(A).add(B).add(C).multiplyScalar(1 / 3); if (!keep(n, c)) continue;
    const t = Math.abs(n.y) > .95 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3().crossVectors(up, n).normalize(); const b = new THREE.Vector3().crossVectors(n, t).normalize();
    for (const V of [A, B, C]) { const q = V.clone().addScaledVector(n, opt.lift ?? 0.003); pos.push(q.x, q.y, q.z); nor.push(n.x, n.y, n.z); uv.push(V.dot(t) / sx, V.dot(b) / sy); } }
  if (opt.norm && uv.length) { let u0 = 1e9, u1 = -1e9, v0 = 1e9, v1 = -1e9; for (let i = 0; i < uv.length; i += 2) { u0 = Math.min(u0, uv[i]); u1 = Math.max(u1, uv[i]); v0 = Math.min(v0, uv[i + 1]); v1 = Math.max(v1, uv[i + 1]); }
    for (let i = 0; i < uv.length; i += 2) { uv[i] = (uv[i] - u0) / (u1 - u0 || 1); uv[i + 1] = (uv[i + 1] - v0) / (v1 - v0 || 1); } }
  if (!pos.length) return null;
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  const m = new THREE.MeshStandardMaterial({map: tx, roughness: opt.rough ?? .85, metalness: opt.metal ?? 0, side: THREE.DoubleSide, transparent: !!opt.transparent, depthWrite: !opt.transparent,
    polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -2});
  if (!opt.own) m.color = o.material.color;
  const s = new THREE.Mesh(g, m); s.matrixAutoUpdate = false; s.matrix.copy(new THREE.Matrix4().copy(M).invert()); s.raycast = () => {}; s.castShadow = false; s.receiveShadow = !opt.transparent;
  s.onBeforeRender = () => { const cp = o.material.clippingPlanes || []; if (m.clippingPlanes !== cp) { m.clippingPlanes = cp; m.needsUpdate = true; } };
  o.add(s); skins.push(s); return s;
}
const H = (n) => Math.abs(n.y) < .3, TOP = (n) => n.y > .9, UP = (n) => n.y > .3;

function siteDecor(scene, site, bbox) {
  const grp = new THREE.Group(); const y0 = site.grade;
  const R = 220; const gg = new THREE.PlaneGeometry(2 * R, 2 * R); const uv = gg.attributes.uv; for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * 2 * R / 3, uv.getY(i) * 2 * R / 3);
  const ground = new THREE.Mesh(gg, new THREE.MeshStandardMaterial({map: TX.grass, roughness: 1})); ground.rotation.x = -Math.PI / 2; ground.position.set(bbox.getCenter(new THREE.Vector3()).x, y0 - 0.02, bbox.getCenter(new THREE.Vector3()).z); ground.receiveShadow = true; grp.add(ground);
  const flat = (poly, tex, dy, rep) => { const sh = new THREE.Shape(poly.map(([x, y]) => new THREE.Vector2(x, y))); const geo = new THREE.ShapeGeometry(sh); const u = geo.attributes.uv, p = geo.attributes.position;
    for (let i = 0; i < p.count; i++) u.setXY(i, p.getX(i) / rep, p.getY(i) / rep); const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({map: tex, roughness: .95}));
    m.rotation.x = -Math.PI / 2; m.position.y = y0 + dy; m.receiveShadow = true; grp.add(m); return m; };
  if (site.drive) flat(site.drive, TX.asphalt, 0.012, 2.5);
  if (site.road) { flat(site.road, TX.asphalt, 0.01, 2.5); const ys = site.road.map(p => p[1]); const yc = (Math.min(...ys) + Math.max(...ys)) / 2; const xs = site.road.map(p => p[0]);
    for (let xx = Math.min(...xs); xx < Math.max(...xs); xx += 6) flat([[xx, yc - 0.06], [xx + 3, yc - 0.06], [xx + 3, yc + 0.06], [xx, yc + 0.06]], canvasTex(4, 4, (x) => { x.fillStyle = '#e8c547'; x.fillRect(0, 0, 4, 4); }, 1, 1), 0.016, 1); }
  const r = rnd(97);
  for (const [tx, ty] of (site.trees || [])) { const t = new THREE.Group(); const hgt = 6 + r() * 5;
    const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.24, hgt * .45, 8), new THREE.MeshStandardMaterial({color: '#5b4635', roughness: 1})); trunk.position.y = hgt * .22; t.add(trunk);
    for (let k = 0; k < 4; k++) { const rr = hgt * (.22 + r() * .1); const leaf = new THREE.Mesh(new THREE.IcosahedronGeometry(rr, 1), new THREE.MeshStandardMaterial({color: new THREE.Color().setHSL(.24 + r() * .06, .38, .26 + r() * .08), roughness: 1, flatShading: true}));
      leaf.position.set((r() - .5) * rr, hgt * .55 + r() * hgt * .3, (r() - .5) * rr); t.add(leaf); }
    t.position.set(tx, y0, -ty); t.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } }); grp.add(t); }
  scene.add(grp); return grp;
}

function apply({scene, renderer, sun, hemi, nodes, cfg, site, edges}) {
  const bbox = new THREE.Box3(); Object.values(nodes).forEach(o => { if (o.visible) bbox.expandByObject(o); });
  const fin = cfg.fin || {}, kind = cfg.kind || {};
  for (const [id, o] of Object.entries(nodes)) {
    if (!o.isMesh || !o.material) continue;
    const base = id.replace('#fill', '');
    o.castShadow = true; o.receiveShadow = true;
    if (o.material.isMeshStandardMaterial) { o.material.roughness = .82; o.material.metalness = 0; }
    if (cfg.siding[id]) { const v = new THREE.Vector3(cfg.siding[id][0], 0, cfg.siding[id][1]); skin(o, TX.siding, n => H(n) && n.dot(v) > .9); continue; }
    if (/^R-/.test(id)) { skin(o, TX.shingle, UP, {rough: .95}); continue; }
    if (id.endsWith('#fill') && cfg.win[base]) { const w = cfg.win[base]; const glassy = !['panel', 'overhead'].includes(w.t);
      const N = new THREE.Vector3(w.n[0], 0, w.n[1]), tex = openingTex(w);
      for (const sgn of [1, -1]) { const k = skin(o, tex, n => n.dot(N) * sgn > .9, {norm: true, own: true, transparent: glassy, rough: glassy ? .08 : .7, lift: 0.002});
        if (k && glassy) { k.material.envMapIntensity = .25; k.renderOrder = 2; } }
      o.material.colorWrite = false; o.material.depthWrite = false; o.castShadow = !glassy; o.userData.glassy = glassy; continue; }
    const f = fin[id], k = kind[id] || '';
    if (/^FL-/.test(id)) { skin(o, f === 'fin-floor-tile' ? TX.tile : TX.wood, TOP, {own: true, rough: .6}); continue; }
    if (/^FDN-/.test(id)) { skin(o, TX.block, H, {own: true}); continue; }
    if (k === 'chimney') { skin(o, TX.brick, n => true, {own: true}); continue; }
    if (f === 'fin-stone') { skin(o, TX.stone, n => true, {own: true}); continue; }
    if (f === 'fin-steel') { skin(o, TX.steel, n => true, {own: true, rough: .35, metal: .6}); continue; }
    if (f === 'fin-tile') { skin(o, TX.tile, n => true, {own: true, rough: .4}); continue; }
    if (k === 'casework' || f === 'fin-cab' || f === 'fin-island') { if (!/^P-SHELF|^K-UPPERS|^K-TALL|^M-LOCK/.test(id)) skin(o, TX.quartz, TOP, {own: true, rough: .3}); skin(o, TX.shaker, H); continue; }
    if (id === 'S1-PAT') { skin(o, TX.pavers, TOP, {own: true}); continue; }
    if (id === 'S-WALK' || id === 'S1-FP' || /^FP-STEP/.test(id)) { skin(o, TX.walk, n => !(n.y < -.9), {own: true}); continue; }
    if (id === 'S1-GAR') { skin(o, TX.concrete, TOP, {own: true}); continue; }
    if (id === 'S1-SP') { skin(o, TX.deck, TOP, {own: true}); continue; }
  }
  sun.castShadow = true; sun.shadow.mapSize.set(4096, 4096); sun.shadow.bias = -0.0003; sun.shadow.normalBias = 0.03;
  const c = bbox.getCenter(new THREE.Vector3()), s = bbox.getSize(new THREE.Vector3()), R = Math.max(s.x, s.z) * .75 + 4;
  Object.assign(sun.shadow.camera, {left: -R, right: R, top: R, bottom: -R, near: 1, far: 200}); sun.shadow.camera.updateProjectionMatrix();
  sun.position.set(c.x - 25, c.y + 38, c.z + 30); sun.target.position.copy(c); scene.add(sun.target);
  const decor = siteDecor(scene, site, bbox);
  const sky = canvasTex(4, 256, (x, w, h) => { const g = x.createLinearGradient(0, 0, 0, h); g.addColorStop(0, '#6d9cc7'); g.addColorStop(.55, '#b7d0e2'); g.addColorStop(1, '#e8eef0'); x.fillStyle = g; x.fillRect(0, 0, w, h); }, 1, 1, {clamp: true});
  sky.mapping = THREE.EquirectangularReflectionMapping;
  const prev = {bg: scene.background, env: scene.environment, tm: renderer.toneMapping, exp: renderer.toneMappingExposure, hemi: hemi ? hemi.intensity : 0, sun: sun.intensity};
  let env = null;
  import('three/addons/environments/RoomEnvironment.js').then(({RoomEnvironment}) => { const pm = new THREE.PMREMGenerator(renderer); env = pm.fromScene(new RoomEnvironment(), 0.04).texture; if (on) scene.environment = env; }).catch(() => {});
  let on = true;
  function set(v) {
    on = v; renderer.shadowMap.enabled = v; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = v ? THREE.ACESFilmicToneMapping : prev.tm; renderer.toneMappingExposure = v ? 1.0 : prev.exp;
    scene.background = v ? sky : prev.bg; scene.environment = v ? env : prev.env; if (hemi) hemi.intensity = v ? 0.55 : prev.hemi; sun.intensity = v ? 2.6 : prev.sun;
    decor.visible = v; skins.forEach(k => k.visible = v);
    for (const o of Object.values(nodes)) { if (o.userData.edges) o.userData.edges.visible = !v && o.visible; if (o.userData.glassy !== undefined) { o.material.colorWrite = !v; o.material.depthWrite = !v; } }
    if (edges) edges(v);
    scene.traverse(o => { if (o.material) o.material.needsUpdate = true; });
  }
  set(true);
  return {set, skins, decor};
}
return {apply, TX};
})();
