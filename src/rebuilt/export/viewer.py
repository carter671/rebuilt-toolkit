"""Single-file browser review viewer (three.js via CDN; GLB + sidecar embedded).

Orbit/zoom/pan, pick, isolate/hide, storey filter, colour by material or by provenance basis,
section clipping plane, view presets, two-point measuring, issue list, and a correction form that
produces a correction JSON + CLI command to copy (applied with `rebuilt apply`) — the viewer never mutates Genome.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

TEMPLATE = r"""<title>__TITLE__</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* layout: full-bleed 3D stage + inspection rail; drafting-table neutrals, one green ink accent */
:root{--bg:#eef1f3;--panel:#fbfcfc;--ink:#1a2126;--muted:#5d6a73;--line:#d5dce1;--accent:#0b6e4f;--hl:#0b6e4f22;
--sans:"IBM Plex Sans",ui-sans-serif,system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#14191c;--panel:#1b2226;--ink:#e6ecef;--muted:#93a1aa;--line:#2c363c;--accent:#4cc79a;--hl:#4cc79a22;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#14191c;--panel:#1b2226;--ink:#e6ecef;--muted:#93a1aa;--line:#2c363c;--accent:#4cc79a;--hl:#4cc79a22;color-scheme:dark}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:13px/1.45 var(--sans)}
#app{display:grid;grid-template-columns:1fr 360px;height:100%}
#view{position:relative;min-height:300px}canvas{display:block}
#side{background:var(--panel);border-left:1px solid var(--line);overflow:auto;padding:14px 16px}
h1{font-size:15px;margin:0 0 2px}h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:16px 0 6px}
.sub{color:var(--muted);font-size:11.5px}.warn{background:var(--hl);border:1px solid var(--accent);color:var(--ink);padding:6px 8px;border-radius:6px;font-size:11.5px;margin:8px 0}
.bar{position:absolute;left:12px;top:12px;display:flex;flex-wrap:wrap;gap:6px;max-width:calc(100% - 24px)}
button:focus-visible,select:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
button,select{font:inherit;font-size:12px;border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:5px 9px;border-radius:6px;cursor:pointer}
button.on{border-color:var(--accent);color:var(--accent)}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:4px 0}
table{width:100%;font-variant-numeric:tabular-nums;border-collapse:collapse;font-size:12px}td,th{text-align:left;padding:3px 4px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:500}.chip{display:inline-block;padding:0 6px;border-radius:9px;font-size:11px;color:#fff}
.mono{font-family:var(--mono);font-size:11.5px;font-variant-numeric:tabular-nums}.issue{cursor:pointer;padding:4px 0;border-bottom:1px solid var(--line)}
.issue:hover{color:var(--accent)}input[type=range]{width:140px}
#hud{position:absolute;left:12px;bottom:12px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px}
input[type=text],textarea{width:100%;font:inherit;font-size:12px;padding:5px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--ink)}
@media (max-width:760px){#app{grid-template-columns:1fr;grid-template-rows:55vh auto}#side{border-left:0;border-top:1px solid var(--line)}}
</style><div id="app"><div id="view"><div class="bar">
<button data-v="iso">3D</button><button data-v="top">Plan</button><button data-v="south">S elev</button><button data-v="north">N elev</button><button data-v="east">E elev</button><button data-v="west">W elev</button>
<select id="colour"><option value="material">Colour: material</option><option value="basis">Colour: provenance</option></select>
<button id="spaces">Spaces</button><button id="details" class="on">Details</button><button id="measure">Measure</button><button id="isolate">Isolate</button><button id="hide">Hide</button><button id="showall">Show all</button>
<span class="row" style="background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:2px 8px;margin:0">Section <select id="secax"><option value="">off</option><option value="x">E–W</option><option value="z">N–S</option><option value="y">Height</option></select><input id="secpos" type="range" min="0" max="1000" value="500"></span>
</div><div id="hud">Click an element to inspect</div></div>
<aside id="side"><h1 id="title"></h1><div class="sub" id="meta"></div>
<div class="warn">Model review only — not for permit, construction or pricing.</div>
<h2>Storeys</h2><div id="storeys" class="row"></div>
<h2>Selection</h2><div id="sel" class="sub">Nothing selected.</div>
<h2>Correction</h2><div id="fix" class="sub">Select an element to prepare a correction. The viewer never edits the model; copy the result and apply it with the rebuilt CLI so it is logged with your name and reason.</div>
<h2>Issues &amp; unsupported</h2><div id="issues"></div>
<h2>Legend</h2><div id="legend" class="row"></div></aside></div>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script>
<script type="module">
import * as THREE from 'three';import {OrbitControls} from 'three/addons/controls/OrbitControls.js';import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
const META=__META__;const GLB_B64="__GLB__";
const BASIS={measured:'#222222',extracted:'#1f4e9c',observed:'#1f7a8c',inferred:'#d9822b',assumed:'#c0392b',unknown:'#8e44ad'};
const RANK={measured:0,extracted:1,observed:2,inferred:3,assumed:4,unknown:5};
const ftin=m=>{const neg=m<0;let t=Math.round(Math.abs(m)/0.0254*16);const ft=Math.floor(t/192);t-=ft*192;const i=Math.floor(t/16);let f=t-i*16;let s=`${ft}'-${i}`;if(f){let n=f,d=16;while(n%2==0){n/=2;d/=2}s+=` ${n}/${d}`}return (neg?'-':'')+s+'"'};
const fmt=v=>typeof v==='number'?`${ftin(v)} <span class="sub">[${v.toFixed(3)}]</span>`:(v===null||v===undefined?'—':String(v));
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
document.getElementById('title').textContent=META.project+(META.fictional?' (fictional)':'');
document.getElementById('meta').innerHTML=`Genome rev ${META.genome_revision} · model <span class="mono">${META.model_hash.slice(0,12)}</span> · MODEL ${META.compiler_version}`;
document.getElementById('legend').innerHTML=Object.entries(BASIS).map(([k,c])=>`<span class="chip" style="background:${c}">${k}</span>`).join(' ');
const view=document.getElementById('view');const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(devicePixelRatio);renderer.localClippingEnabled=true;view.appendChild(renderer.domElement);
const scene=new THREE.Scene();const bg=getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()||'#f4f2ee';scene.background=new THREE.Color(bg);
const cam=new THREE.PerspectiveCamera(40,1,0.05,500);const ctl=new OrbitControls(cam,renderer.domElement);ctl.enableDamping=true;
scene.add(new THREE.HemisphereLight(0xffffff,0x8a8070,1.6));const dl=new THREE.DirectionalLight(0xffffff,1.6);dl.position.set(10,20,-8);scene.add(dl);
const grid=new THREE.GridHelper(40,40,0xbbbbbb,0xdddddd);grid.position.y=-0.11;scene.add(grid);
function resize(){const r=view.getBoundingClientRect();renderer.setSize(r.width,r.height);cam.aspect=r.width/r.height;cam.updateProjectionMatrix()}addEventListener('resize',resize);resize();
const nodes={};let box=new THREE.Box3();const clip=new THREE.Plane(new THREE.Vector3(-1,0,0),0);let clipOn=false;
const bytes=Uint8Array.from(atob(GLB_B64),c=>c.charCodeAt(0));
new GLTFLoader().parse(bytes.buffer,'',g=>{scene.add(g.scene);g.scene.traverse(o=>{if(o.isMesh){const id=o.userData.genome_id||o.name;o.material=o.material.clone();o.userData.baseColor=o.material.color.clone();o.userData.baseOpacity=o.material.opacity;nodes[id]=o;
 const ed=new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry,25),new THREE.LineBasicMaterial({color:0x333333,transparent:true,opacity:.55}));o.add(ed);o.userData.edges=ed;
 if(META.elements[id]?.type==='space'){o.visible=false;ed.visible=false}}});box.setFromObject(g.scene);setView('iso');buildStoreys();buildIssues();colour();});
function setView(v){const c=box.getCenter(new THREE.Vector3()),s=box.getSize(new THREE.Vector3()).length();const d={iso:[1,0.8,1.1],top:[0,1,0.0001],south:[0,0.15,1],north:[0,0.15,-1],east:[1,0.15,0],west:[-1,0.15,0]}[v];
 cam.position.copy(c).add(new THREE.Vector3(...d).normalize().multiplyScalar(s*1.25));ctl.target.copy(c);ctl.update()}
document.querySelectorAll('[data-v]').forEach(b=>b.onclick=()=>setView(b.dataset.v));
// note: glTF axes: x=east, y=up, z=-north
function worst(id){let w='measured';for(const r of Object.values(META.elements[id]?.params||{})){let b=r.defaulted?'assumed':(r.basis||'assumed');if(RANK[b]>RANK[w])w=b}return w}
function colour(){const mode=document.getElementById('colour').value;for(const [id,o] of Object.entries(nodes)){if(mode==='basis'&&META.elements[id]?.type!=='space'){o.material.color.set(BASIS[worst(id)]);}else o.material.color.copy(o.userData.baseColor);if(id===selected)o.material.emissive?.set(0x0b4a36);else o.material.emissive?.set(0)}}
document.getElementById('colour').onchange=colour;
let showSpaces=false;document.getElementById('spaces').onclick=e=>{showSpaces=!showSpaces;e.target.classList.toggle('on',showSpaces);for(const [id,o] of Object.entries(nodes))if(META.elements[id]?.type==='space'){o.visible=showSpaces;o.userData.edges.visible=showSpaces}};
let showDetails=true;document.getElementById('details').onclick=e=>{showDetails=!showDetails;e.target.classList.toggle('on',showDetails);for(const [id,o] of Object.entries(nodes))if(META.elements[id]?.type==='component'){o.visible=showDetails;o.userData.edges.visible=showDetails}};
function renderInfo(m){const I=m.info;if(!I)return'';const F=META.finishes||{};const sw=f=>{const x=F[f];return x?`<span class="chip" style="background:${x.hex||'#999'};color:#111">${esc(x.name)}</span> <span class="mono sub">${x.hex||''}</span>`:esc(f)};let h='<h2>Information</h2><table>';
 const row=(k,v)=>{if(v!==undefined&&v!==null&&v!=='')h+=`<tr><th>${k}</th><td>${v}</td></tr>`};const inf=Object.assign({},I.family_info?.info||{},I.info||{});
 if(I.kind)row('kind',esc(I.kind));if(I.family_info)row('family',esc(I.family_info.name));['category','subtype','material','manufacturer','model','serial'].forEach(k=>row(k,inf[k]&&esc(inf[k])));if(inf.finish)row('finish / colour',sw(inf.finish));
 if(inf.condition)row('condition',`<b>${esc(inf.condition.rating)}</b>${inf.condition.notes?' — '+esc(inf.condition.notes):''}`);if(inf.install_year)row('installed',inf.install_year.value);
 if(inf.observed){const o=inf.observed;row('observed',[o.date,o.by].filter(Boolean).map(esc).join(' · '));if(o.photos?.length)row('photos',o.photos.map(p=>`<span class="mono">${esc(p)}</span>`).join(', '));if(o.confidence!=null)row('confidence',o.confidence)}
 if(inf.notes)row('notes',esc(inf.notes));if(I.phase)row('phase',esc(I.phase));
 for(const [k,v] of Object.entries(I.properties||{}))row(k,`${fmt(v.value)} <span class="chip" style="background:${BASIS[v.basis]||'#777'}">${v.basis}</span>`);
 if(I.unit)row('unit',Object.entries(I.unit).map(([k,v])=>k==='sash_finish'?sw(v):`${k}: ${esc(v)}`).join('<br>'));
 for(const [k,v] of Object.entries(I.surfaces||{}))row(k,[v.material,v.subtype,v.finish?sw(v.finish):'',v.condition?v.condition.rating:'',v.notes].filter(Boolean).map(x=>x.startsWith?.('<span')?x:esc(x)).join(' · '));
 for(const e of (I.history||[]))row('history',`${esc(e.date||'?')} ${esc(e.event)} ${esc(e.note||'')}`);
 return h+'</table>'}
const storeyOn={};function buildStoreys(){const el=document.getElementById('storeys');META.storeys.forEach(s=>{storeyOn[s.id]=true;const b=document.createElement('button');b.textContent=s.name;b.className='on';b.onclick=()=>{storeyOn[s.id]=!storeyOn[s.id];b.classList.toggle('on',storeyOn[s.id]);for(const [id,o] of Object.entries(nodes)){const m=META.elements[id];if(m?.storey===s.id&&(m.type!=='space'||showSpaces)){o.visible=storeyOn[s.id];}}};el.appendChild(b)})}
function buildIssues(){const el=document.getElementById('issues');const items=[...META.issues.map(i=>({t:`[${i.severity}] ${i.code}: ${i.message}`,ids:i.elements})),...META.unsupported.map(u=>({t:`[unsupported] ${u.element}: ${u.reason}`,ids:[u.element]}))];
 el.innerHTML=items.length?'':'<div class="sub">No compiler errors, warnings or unsupported features.</div>';items.forEach(it=>{const d=document.createElement('div');d.className='issue';d.textContent=it.t;d.onclick=()=>it.ids[0]&&select(it.ids[0]);el.appendChild(d)});
 const nm=Object.values(META.elements).flatMap(e=>Object.entries(e.params||{}).filter(([k,r])=>r.basis!=='measured'||r.defaulted||r.verification==='disputed').map(([k,r])=>({id:e.id,k,r})));
 if(nm.length){const h=document.createElement('div');h.className='sub';h.style.marginTop='8px';h.textContent=`${nm.length} parameter values are not measured (switch colour to provenance to see where).`;el.appendChild(h)}}
let selected=null;const ray=new THREE.Raycaster();const mouse=new THREE.Vector2();let measuring=false,mpts=[];const mline=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0x0b6e4f,depthTest:false}));mline.renderOrder=9;scene.add(mline);
renderer.domElement.addEventListener('pointerdown',e=>{renderer.domElement._d=[e.clientX,e.clientY]});
renderer.domElement.addEventListener('pointerup',e=>{const d=renderer.domElement._d;if(!d||Math.hypot(e.clientX-d[0],e.clientY-d[1])>4)return;const r=renderer.domElement.getBoundingClientRect();mouse.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);ray.setFromCamera(mouse,cam);
 let hits=ray.intersectObjects(Object.values(nodes).filter(o=>o.visible),false);if(clipOn)hits=hits.filter(h=>clip.distanceToPoint(h.point)>=0);if(!hits.length)return;const h=hits[0];
 if(measuring){mpts.push(h.point.clone());if(mpts.length>2)mpts=[h.point.clone()];mline.geometry.setFromPoints(mpts);if(mpts.length===2){const dd=mpts[0].distanceTo(mpts[1]);const dz=Math.abs(mpts[0].y-mpts[1].y);document.getElementById('hud').innerHTML=`Distance ${ftin(dd)} [${dd.toFixed(3)} m] · vertical ${ftin(dz)} — measured on the model, not on the building`}else document.getElementById('hud').textContent='Pick second point';return}
 select(h.object.userData.genome_id||h.object.name)});
document.getElementById('measure').onclick=e=>{measuring=!measuring;mpts=[];mline.geometry.setFromPoints([]);e.target.classList.toggle('on',measuring);document.getElementById('hud').textContent=measuring?'Pick first point':'Click an element to inspect'};
document.getElementById('isolate').onclick=()=>{if(!selected)return;for(const [id,o] of Object.entries(nodes))o.visible=id===selected||id===selected+'#fill'};
document.getElementById('hide').onclick=()=>{if(selected&&nodes[selected])nodes[selected].visible=false};
document.getElementById('showall').onclick=()=>{for(const [id,o] of Object.entries(nodes))o.visible=META.elements[id]?.type!=='space'||showSpaces};
function secUpdate(){const ax=document.getElementById('secax').value;clipOn=!!ax;const t=document.getElementById('secpos').value/1000;const mn=box.min,mx=box.max;
 const n={x:new THREE.Vector3(-1,0,0),y:new THREE.Vector3(0,-1,0),z:new THREE.Vector3(0,0,-1)}[ax||'x'];const p=mn.clone().lerp(mx,t);clip.normal.copy(n);clip.constant=-n.dot(p);
 for(const o of Object.values(nodes)){o.material.clippingPlanes=clipOn?[clip]:[];o.material.clipShadows=true;o.material.needsUpdate=true;o.userData.edges.material.clippingPlanes=clipOn?[clip]:[]}}
document.getElementById('secax').onchange=secUpdate;document.getElementById('secpos').oninput=secUpdate;
function select(id){selected=id;colour();const m=META.elements[id];if(!m)return;const host=m.data?.host;
 let h=`<div><b>${esc(m.name||id)}</b> <span class="mono">${esc(id)}</span></div><div class="sub">${m.ifc_class} · storey ${m.storey||'—'} · rev ${m.rev} · ${esc(m.material||'no material')}</div>`;
 h+=renderInfo(m);h+='<h2>Geometry</h2><table>';for(const [k,v] of Object.entries(m.data||{})){if(['junctions','butted_by','baseline','centre','clear_span','bbox','color'].includes(k))continue;h+=`<tr><th>${k}</th><td>${typeof v==='number'?(/volume/.test(k)?v.toFixed(4)+' m³':/area/.test(k)?v.toFixed(3)+' m²':k==='slope'?(v*12).toFixed(3)+':12':fmt(v)):esc(JSON.stringify(v))}</td></tr>`}h+='</table>';
 h+='<h2>Provenance</h2><table><tr><th>param</th><th>value</th><th>basis</th><th>±</th><th>verif.</th></tr>';
 for(const [k,r] of Object.entries(m.params||{})){const b=r.defaulted?'assumed':r.basis;h+=`<tr><td>${k}</td><td>${k==='pitch'&&r.value!=null?(r.value*12).toFixed(2)+':12':fmt(r.value)}${r.input?`<div class="sub">input “${esc(r.input)}”</div>`:''}${r.from?`<div class="sub">${esc(r.from)}</div>`:''}${r.note?`<div class="sub">${esc(r.note)}</div>`:''}</td><td><span class="chip" style="background:${BASIS[b]||'#777'}">${b}</span>${r.confidence!=null?`<div class="sub">conf ${r.confidence}</div>`:''}</td><td>${r.uncertainty!=null?r.uncertainty.toFixed(3):'—'}</td><td>${r.verification||'—'}</td></tr>`;
  for(const o of (r.observations||[])){const ob=META.observations[o];if(ob)h+=`<tr><td></td><td colspan="4" class="sub">↳ ${esc(ob.locator)} “${esc(ob.text)}”${ob.status!=='active'?' ('+ob.status+')':''}</td></tr>`}}
 h+='</table>';if(m.issues?.length)h+='<h2>Findings</h2>'+m.issues.map(i=>`<div class="issue">[${i.severity}] ${esc(i.message)}</div>`).join('');if(host)h+=`<div class="row"><button onclick="window.__sel('${host}')">Select host ${host}</button></div>`;
 document.getElementById('sel').innerHTML=h;document.getElementById('hud').textContent=`${id}`;buildFix(id,m)}
window.__sel=select;
function buildFix(id,m){const params=Object.keys(m.params||{}).filter(k=>!m.params[k].derived);const real=id.replace('#fill','');
 document.getElementById('fix').innerHTML=`<div class="row"><select id="fxp">${params.map(p=>`<option>${p}</option>`).join('')}</select><input id="fxv" type="text" placeholder="value e.g. 3' 11 1/4&quot; or 1.2 m" style="flex:1"></div>
 <div class="row"><select id="fxb"><option>measured</option><option>observed</option><option>inferred</option><option>assumed</option></select><input id="fxby" type="text" placeholder="your name" style="flex:1"></div><textarea id="fxr" rows="2" placeholder="reason / evidence"></textarea>
 <div class="row"><button id="fxgo">Prepare correction</button><button id="fxcp">Copy</button></div><textarea id="fxout" rows="6" class="mono" readonly placeholder="Correction JSON and CLI command appear here"></textarea>`;
 document.getElementById('fxgo').onclick=()=>{const p=document.getElementById('fxp').value,v=document.getElementById('fxv').value.trim(),by=document.getElementById('fxby').value.trim()||'reviewer',r=document.getElementById('fxr').value.trim()||'viewer correction',b=document.getElementById('fxb').value;if(!v){document.getElementById('fxout').value='Enter a value first, e.g. 3\' 11 1/4" or 1.2 m';return}
  const cs={proposed_changeset:true,author:by,reason:r,source:'viewer',genome_revision:META.genome_revision,edits:[{element:real,param:p,value_text:v,basis:b}]};
  document.getElementById('fxout').value=`# save as correction.json, then: rebuilt apply PROJECT correction.json\n${JSON.stringify(cs,null,1)}\n\n# or directly:\nrebuilt edit PROJECT ${real} ${p} "${v.replace(/"/g,'\\"')}" --basis ${b} --by "${by}" --reason "${r}"`};
 document.getElementById('fxcp').onclick=()=>{const t=document.getElementById('fxout');navigator.clipboard?.writeText(t.value).catch(()=>{t.focus();t.select()})||(t.focus(),t.select())}}
(function loop(){requestAnimationFrame(loop);ctl.update();renderer.render(scene,cam)})();
</script>
"""


def write_viewer(glb_path, meta_path, out_path):
    glb = base64.b64encode(Path(glb_path).read_bytes()).decode()
    meta = json.loads(Path(meta_path).read_text())
    title = (meta.get("project") or "Rebuilt") + (" Model" if not meta.get("fictional") else " Model Review")
    html = TEMPLATE.replace("__TITLE__", title.replace("<", "")).replace("__GLB__", glb).replace("__META__", json.dumps(meta, default=float).replace("</", "<\\/"))
    Path(out_path).write_text(html)
    return out_path
