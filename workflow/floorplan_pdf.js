const {chromium} = require('playwright');
const fs = require('fs');
const TH = process.env.THREE_DIR || require('path').join(require('path').dirname(require.resolve('three')), '..');
// usage (from the folder holding the editor's index.html):
//   DESIGN=design.json TITLE='123 Main St — Design A' CITY='Town, OH 43110' node floorplan_pdf.js OUT.pdf
const OUT = process.argv[2];
(async () => {
  const b = await chromium.launch({args:['--use-gl=swiftshader','--enable-unsafe-swiftshader']});
  const p = await b.newPage({viewport:{width:1650,height:1100}});
  const errs=[]; p.on('pageerror', e=>errs.push(e.message));
  const d = fs.readFileSync(process.env.DESIGN,'utf8');
  const hook = `window.__L=()=>{const d=${d}; ops=d.ops; cursor=d.cursor; rebuild(); afterChange(false);};
window.__X=()=>{ sel=null; hidePop(); vb=null; fit(); drawPlan(); const s=document.querySelector('#svg').cloneNode(true); s.querySelectorAll('.gridl,.op-hit,.handle').forEach(e=>e.remove()); const top = s.querySelector('g') || s; s.querySelectorAll('.room-label,.room-area').forEach(e=>top.appendChild(e));
  return {svg: s.outerHTML, vb: s.getAttribute('viewBox'), rooms: rooms.filter(r=>r.area>0.5).map(r=>({name:r.name, st:r.st, sf:Math.round(r.area*10.764), ceil: r.ceil.given ? (r.ceil.mode==='vault'?'vaulted':ftin(r.ceil.h)) : ''})),
    changes: ops.slice(0,cursor).map(o=>o.label).filter(Boolean), checks: computeChecks().map(x=>x.msg), name: PLAN.name}; };
window.__C=(x,y,z,tx,ty,tz)=>{ cam.position.set(x,y,z); orbit.target.set(tx,ty,tz); orbit.update(); };\n`;
  const html = fs.readFileSync('index.html','utf8').replace('/* ---------------- boot', hook + '/* ---------------- boot');
  await p.route(/three@0\.160\.0\/(.*)/, r=>{const m=r.request().url().match(/three@0\.160\.0\/(.*)/)[1]; r.fulfill({path:TH+'/'+m, contentType:'application/javascript'});});
  await p.route(/fonts\.googleapis/, r=>r.fulfill({body:'',contentType:'text/css'}));
  await p.route('http://x/', r=>r.fulfill({body:'<!doctype html><html data-theme="light"><head><meta charset=utf-8></head><body>'+html+'</body></html>',contentType:'text/html'}));
  await p.goto('http://x/'); await p.waitForTimeout(3000);
  await p.evaluate(()=>__L()); await p.click('[data-v=plan]'); await p.waitForTimeout(400);
  const X = await p.evaluate(()=>__X());
  // 3D with roof, two views
  await p.click('[data-v="3d"]'); await p.waitForTimeout(300);
  if (await p.$eval('#tRoof', e=>e.getAttribute('aria-pressed')) !== 'true') await p.click('#tRoof');
  await p.evaluate(()=>__C(-14, 22, 26, 4, 0, -9)); await p.waitForTimeout(800);
  const shot1 = (await p.locator('#three canvas').screenshot()).toString('base64');
  await p.evaluate(()=>__C(22, 20, -32, 4, 0, -9)); await p.waitForTimeout(800);
  const shot2 = (await p.locator('#three canvas').screenshot()).toString('base64');
  await p.click('#tRoof'); await p.evaluate(()=>__C(-6, 30, 16, 3, 0, -10)); await p.waitForTimeout(800);
  const shot3 = (await p.locator('#three canvas').screenshot()).toString('base64');
  // the editor's plan styles, resolved for print
  const css = `
  .room-fill{fill:#ECE7DC}.room-fill.alt{fill:#E4DED1}.room-label{font-family:Arial,sans-serif;font-weight:700;fill:#22262A;text-anchor:middle;paint-order:stroke;stroke:#fff;stroke-width:3.5px;stroke-linejoin:round;vector-effect:non-scaling-stroke}
  .room-area{font-family:'Courier New',monospace;fill:#22262A;text-anchor:middle;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round;vector-effect:non-scaling-stroke}
  .wall{fill:#2B2F33}.wall.ext{fill:#1A1D20}.wall.sel{fill:#2B2F33}.gap{fill:#F7F5EF}.gap.open{fill:#ECE7DC}
  .op-line{stroke:#22262A;fill:none}.comp{fill:none;stroke:#22262A;opacity:.5}
  .item polygon:first-child{fill:#fff;fill-opacity:.9;stroke:#22262A}.item.up polygon:first-child{fill:none}.item.bad polygon:first-child{stroke:#22262A;fill:#fff}
  .sym{fill:none;stroke:#22262A;opacity:.6}.sym-t{font-family:Arial;fill:#22262A;text-anchor:middle}
  .bearing,.joist,.beam,.boxsel,.draft,.snap,.roomfill,.newwall{display:none}`;
  const rows = X.rooms.sort((a,b)=> (a.st===b.st? b.sf-a.sf : a.st.localeCompare(b.st)*-1));
  const house = rows.filter(r=>r.st==='1F'), gar = rows.filter(r=>r.st!=='1F');
  const tot = l => l.reduce((a,r)=>a+r.sf,0);
  const today = new Date().toLocaleDateString('en-US',{year:'numeric',month:'long',day:'numeric'});
  const tb = (title, sheet) => `<div class="tb"><div><b>${process.env.TITLE || X.name}</b><br>${process.env.CITY || ''}<br>Rebuilt · rebuilt.homes</div>
    <div class="nfc">DESIGN LAYOUT — NOT FOR CONSTRUCTION<br><span>Sizes from the as-built model; field-verify before pricing or permit.</span></div>
    <div>${today}</div><div class="sh"><span>${title}</span><b>${sheet}</b></div></div>`;
  const doc = `<!doctype html><html><head><meta charset="utf-8"><style>
  @page{size:17in 11in;margin:0} body{margin:0;font-family:Arial,Helvetica,sans-serif;color:#22262A}
  .page{width:17in;height:11in;box-sizing:border-box;padding:.4in .45in .3in;position:relative;page-break-after:always;display:flex;flex-direction:column}
  .main{flex:1;display:flex;gap:.3in;min-height:0}
  .plan{flex:1;border:1px solid #bbb;position:relative;display:flex;align-items:center;justify-content:center;min-width:0}
  .plan svg{width:100%;height:100%}
  .side{width:3.4in;font-size:10pt;overflow:hidden}
  h2{font-size:11pt;letter-spacing:.08em;text-transform:uppercase;margin:0 0 6px;border-bottom:2px solid #22262A;padding-bottom:3px}
  table{width:100%;border-collapse:collapse;font-size:9pt;margin-bottom:14px} td{padding:2px 3px;border-bottom:1px solid #e3e0d8} td.n{text-align:right;white-space:nowrap} tr.t td{font-weight:700;border-top:1.5px solid #22262A;border-bottom:0}
  ol{font-size:8pt;margin:0;padding-left:16px;columns:1} li{margin-bottom:1px}
  .tb{display:grid;grid-template-columns:3.3in 1fr 1.6in 3.2in;border:1.5px solid #22262A;margin-top:.15in;font-size:9pt}
  .tb>div{padding:6px 9px;border-right:1px solid #22262A} .tb>div:last-child{border-right:0}
  .nfc{color:#B4432F;font-weight:700} .nfc span{color:#22262A;font-weight:400;font-size:8pt}
  .sh{display:flex;justify-content:space-between;align-items:center} .sh b{font-size:20pt}
  .north{position:absolute;top:10px;right:14px;font-size:9pt;text-align:center} .north div{font-size:18pt;line-height:1}
  .bar{position:absolute;left:14px;bottom:10px;font-size:8pt}
  .views{flex:1;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:minmax(0,1.25fr) minmax(0,1fr);gap:.2in;min-height:0}
  .views img{width:100%;height:100%;object-fit:cover;border:1px solid #bbb}
  .views .big{grid-column:1/3}
  .cap{font-size:8pt;color:#555}
  ${css}</style></head><body>
  <div class="page"><div class="main"><div class="plan">${X.svg}<div class="north"><div>↑</div>N (plan)</div><div class="bar" id="bar"></div></div>
   <div class="side"><h2>Rooms — house</h2><table>${house.map(r=>`<tr><td>${r.name}</td><td class="n">${r.sf} sf</td><td class="n">${r.ceil}</td></tr>`).join('')}<tr class="t"><td>House total</td><td class="n">${tot(house).toLocaleString()} sf</td><td></td></tr></table>
   ${gar.length?`<h2>Garage</h2><table>${gar.map(r=>`<tr><td>${r.name}</td><td class="n">${r.sf} sf</td><td class="n">${r.ceil}</td></tr>`).join('')}<tr class="t"><td>Garage total</td><td class="n">${tot(gar).toLocaleString()} sf</td><td></td></tr></table>`:''}
   <p class="cap">Areas measured to wall centre lines. Ceiling column shows rooms changed from the as-built.</p></div></div>${tb('FLOOR PLAN — HOUSE + GARAGE','L-1')}</div>
  <div class="page"><div class="main"><div class="views"><img class="big" src="data:image/png;base64,${shot3}"><img src="data:image/png;base64,${shot1}"><img src="data:image/png;base64,${shot2}"></div>
   <div class="side"><h2>Design changes</h2><ol>${[...new Set(X.changes.filter(c=>!/^(Moved|Rotated|Slid|Resized|Fixed: slid|Flipped|Copied)/.test(c) && !/→/.test(c) && !/^Chat: .{0,14}$/.test(c)))].slice(-45).map(c=>`<li>${c.replace(/</g,'&lt;')}</li>`).join('')}</ol></div></div>${tb('3D VIEWS + CHANGES','L-2')}</div>
  </body></html>`;
  fs.writeFileSync(require('os').tmpdir()+'/layout.html', doc);
  const q = await b.newPage(); await q.setContent(doc); await q.waitForTimeout(500);
  // scale bar from the plan's viewBox: metres per svg width
  await q.evaluate(() => { const s = document.querySelector('.plan svg'), vb = s.viewBox.baseVal, r = s.getBoundingClientRect();
    const sc = Math.min(r.width / vb.width, r.height / vb.height), ft10 = 10 * 0.3048 * sc;
    document.getElementById('bar').innerHTML = `<div style="width:${ft10}px;height:6px;border:1px solid #22262A;border-top:0"></div>0 · 10 ft`; });
  await q.pdf({path: OUT, width: '17in', height: '11in', printBackground: true, pageRanges: '1'});
  console.log('rooms', X.rooms.length, 'changes', X.changes.length, 'ERR', errs); await b.close();
})();
