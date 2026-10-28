// usage (from the folder holding the editor's index.html):  D=design.json O=prefix OUTDIR=dir node editor_check.js
// prints every check the editor raises for the design and saves plan + 3D screenshots
const {chromium} = require('playwright');
const TH = process.env.THREE_DIR || require('path').join(require('path').dirname(require.resolve('three')), '..'), S = (process.env.OUTDIR || '.') + '/';
(async () => {
  const b = await chromium.launch({args:['--use-gl=swiftshader','--enable-unsafe-swiftshader']});
  const p = await b.newPage({viewport:{width:1600,height:1000}});
  const errs=[]; p.on('pageerror', e=>errs.push(e.message));
  const d = require('fs').readFileSync(process.env.D,'utf8');
  const hook = `window.__L=()=>{const d=${d}; ops=d.ops; cursor=d.cursor; rebuild(); afterChange(false);}; window.__C=(x,y,z,tx,ty,tz)=>{ cam.position.set(x,y,z); orbit.target.set(tx,ty,tz); orbit.update(); }; window.__K=()=>computeChecks().map(x=>x.type+' | '+(x.eng||'')+' | '+x.msg+' | fix:'+fixOpsPreview(x));\n`;
  const html = require('fs').readFileSync('index.html','utf8').replace('/* ---------------- boot', hook + '/* ---------------- boot');
  await p.route(/three@0\.160\.0\/(.*)/, r=>{const m=r.request().url().match(/three@0\.160\.0\/(.*)/)[1]; r.fulfill({path:TH+'/'+m, contentType:'application/javascript'});});
  await p.route(/fonts\.googleapis/, r=>r.fulfill({body:'',contentType:'text/css'}));
  await p.route('http://x/', r=>r.fulfill({body:'<!doctype html><html><head><meta charset=utf-8></head><body>'+html+'</body></html>',contentType:'text/html'}));
  await p.goto('http://x/'); await p.waitForTimeout(3000);
  await p.evaluate(()=>__L());
  console.log('CHECKS', JSON.stringify(await p.evaluate(()=>__K()),null,1));
  await p.screenshot({path:S+process.env.O+'-plan.png'});
  await p.click('[data-v="3d"]'); const on = await p.getAttribute('#tRoof','aria-pressed'); if(on!=='true') await p.click('#tRoof'); await p.waitForTimeout(1000);
  await p.screenshot({path:S+process.env.O+'-3d1.png'}); await p.evaluate(()=>__C(26, 16, -30, 4, 0, -10)); await p.waitForTimeout(500); await p.screenshot({path:S+process.env.O+'-3d2.png'});
  await p.evaluate(()=>__C(-18, 18, 20, 2, 0, -12)); await p.waitForTimeout(500); await p.screenshot({path:S+process.env.O+'-3d3.png'});
  console.log('ERR', errs); await b.close();
})();
