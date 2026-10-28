// usage: node model_shots.js model.glb outprefix [views-json]
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path');
const SP = process.env.THREE_DIR || require('path').join(require('path').dirname(require.resolve('three')), '..');
const glb = process.argv[2], out = process.argv[3];
const views = process.argv[4] ? JSON.parse(fs.readFileSync(process.argv[4], 'utf8')) : [
  {n: 'sw', az: 225, el: 28}, {n: 'se', az: 315, el: 28}, {n: 'ne', az: 45, el: 28}, {n: 'nw', az: 135, el: 28},
  {n: 'top', az: 0, el: 89.5}, {n: 'aer1', az: 250, el: 55}, {n: 'aer2', az: 70, el: 55}];
const html = `<!doctype html><html><body style="margin:0;background:#eef1f4">
<script type="importmap">{"imports":{"three":"/three/build/three.module.js","three/addons/":"/three/examples/jsm/"}}</script>
<script type="module">
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
const W=1600,H=1000, r=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true}); r.setSize(W,H); document.body.appendChild(r.domElement);
r.outputColorSpace=THREE.SRGBColorSpace; r.shadowMap.enabled=true;
const s=new THREE.Scene(); s.background=new THREE.Color('#e9eef3');
s.add(new THREE.HemisphereLight('#ffffff','#8a8f80',1.6)); const d=new THREE.DirectionalLight('#fff',2.2); d.position.set(30,60,20); d.castShadow=true; s.add(d);
const cam=new THREE.PerspectiveCamera(30,W/H,0.1,1000);
new GLTFLoader().load('/model.glb', g=>{
  s.add(g.scene);
  g.scene.traverse(o=>{ if(o.isMesh){o.castShadow=o.receiveShadow=true; const n=(o.name||'')+' '+((o.parent&&o.parent.name)||'');
    if(/^(SITE|GR|TOPO|LOT)/i.test(o.name)) o.visible=false; }});
  const b=new THREE.Box3(); g.scene.traverse(o=>{ if(o.isMesh&&o.visible&&/^(W|N-W|R|RF|SL|WG)/.test(o.name)) b.expandByObject(o);});
  if(b.isEmpty()) b.setFromObject(g.scene);
  const c=b.getCenter(new THREE.Vector3()), rad=b.getSize(new THREE.Vector3()).length()/2;
  window.names=[]; g.scene.traverse(o=>{ if(o.isMesh) window.names.push(o.name);});
  window.shot=(az,el,zoom,tx,ty,tz)=>{ const c0=c.clone(); if(tx!==undefined){c.set(tx,tz||0,-ty);} const R=rad/Math.sin(THREE.MathUtils.degToRad(15))*(zoom||1)*0.9, a=THREE.MathUtils.degToRad(az), e=THREE.MathUtils.degToRad(el);
    cam.position.set(c.x+R*Math.cos(e)*Math.cos(a), c.y+R*Math.sin(e), c.z+R*Math.cos(e)*Math.sin(a)); cam.up.set(0,1,0); if(el>89) cam.up.set(0,0,-1);
    cam.lookAt(c); r.render(s,cam); c.copy(c0); return r.domElement.toDataURL('image/png'); };
  window.ready=true; });
</script></body></html>`;
(async () => {
  const b = await chromium.launch({args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
  const p = await b.newPage({viewport: {width: 1600, height: 1000}});
  await p.route('**/*', rt => { const u = new URL(rt.request().url());
    if (u.pathname === '/') return rt.fulfill({body: html, contentType: 'text/html'});
    if (u.pathname === '/model.glb') return rt.fulfill({body: fs.readFileSync(glb), contentType: 'model/gltf-binary'});
    if (u.pathname.startsWith('/three/')) return rt.fulfill({body: fs.readFileSync(path.join(SP, u.pathname.slice(7))), contentType: 'application/javascript'});
    rt.fulfill({status: 404}); });
  p.on('pageerror', e => console.log('ERR', e.message));
  await p.goto('http://x/'); await p.waitForFunction('window.ready', null, {timeout: 120000});
  if (process.env.NAMES) console.log((await p.evaluate('window.names')).join(' '));
  for (const v of views) { const d = await p.evaluate(([a, e, z, tx, ty, tz]) => window.shot(a, e, z, tx, ty, tz), [v.az, v.el, v.zoom || 1, v.tx, v.ty, v.tz]);
    fs.writeFileSync(`${out}-${v.n}.png`, Buffer.from(d.split(',')[1], 'base64')); console.log('wrote', v.n); }
  await b.close();
})();
