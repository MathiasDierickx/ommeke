'use strict';
const KEY = 'ommeke-offline-routes-v1';
const el = id => document.getElementById(id);
let routes = [], selected, projection, watcher;
try { routes = JSON.parse(localStorage.getItem(KEY) || '[]'); if (!Array.isArray(routes)) routes = []; } catch { routes = []; }
function renderOptions() {
  el('routes').replaceChildren(...routes.map(route => { const option = document.createElement('option'); option.value = route.id; option.textContent = route.name; return option; }));
  el('status').textContent = routes.length ? `${routes.length} route(s) beschikbaar zonder internet.` : 'Nog geen offline routes. Open online een route en kies Bewaar offline.';
  el('gps').disabled = el('remove').disabled = !routes.length;
}
function render() {
  if (watcher !== undefined) navigator.geolocation.clearWatch(watcher);
  selected = routes.find(route => route.id === el('routes').value);
  el('position').setAttribute('visibility', 'hidden');
  if (!selected) { el('line').setAttribute('d',''); el('height').setAttribute('d',''); el('start').setAttribute('visibility','hidden'); el('name').textContent=''; el('saved').textContent=''; return; }
  el('name').textContent = selected.name;
  el('saved').textContent = `Revisie ${selected.revision} · bewaard ${new Date(selected.saved_at).toLocaleString('nl-BE')}`;
  const points = selected.geometry.points;
  const lat = points.reduce((s,p)=>s+p[0],0)/points.length;
  const cos = Math.cos(lat*Math.PI/180);
  const xs = points.map(p=>p[1]*cos), ys = points.map(p=>p[0]);
  const west=Math.min(...xs),east=Math.max(...xs),south=Math.min(...ys),north=Math.max(...ys);
  const scale=Math.min(740/Math.max(east-west,.00001),440/Math.max(north-south,.00001));
  projection=p=>[400+(p[1]*cos-(west+east)/2)*scale,250-(p[0]-(south+north)/2)*scale];
  el('line').setAttribute('d', points.map((p,i)=>`${i?'L':'M'}${projection(p).join(',')}`).join(' '));
  const start=projection(points[0]);el('start').setAttribute('cx',start[0]);el('start').setAttribute('cy',start[1]);el('start').setAttribute('visibility','visible');
  const heights=(selected.geometry.elevation||[]).filter(p=>Number.isFinite(p.km)&&Number.isFinite(p.ele));
  const minimum=Math.min(...heights.map(p=>p.ele)), maximum=Math.max(...heights.map(p=>p.ele));
  const distance=Math.max(...heights.map(p=>p.km),.001);
  el('height').setAttribute('d',heights.map((p,i)=>`${i?'L':'M'}${p.km/distance*800},${120-(p.ele-minimum)/Math.max(1,maximum-minimum)*110}`).join(' '));
}
el('routes').addEventListener('change',render);
el('remove').addEventListener('click',()=>{routes=routes.filter(r=>r.id!==selected?.id);localStorage.setItem(KEY,JSON.stringify(routes));renderOptions();render();});
el('gps').addEventListener('click',()=>{
  if(!navigator.geolocation){el('status').textContent='Locatie is niet beschikbaar op dit toestel.';return;}
  if(watcher!==undefined)navigator.geolocation.clearWatch(watcher);
  watcher=navigator.geolocation.watchPosition(p=>{
    const point=projection([p.coords.latitude,p.coords.longitude]);
    el('position').setAttribute('cx',point[0]);el('position').setAttribute('cy',point[1]);el('position').setAttribute('visibility','visible');
    el('status').textContent=point[0]<0||point[0]>800||point[1]<0||point[1]>500?'Je locatie ligt buiten het getoonde routegebied.':`Locatie bijgewerkt. Nauwkeurigheid circa ${Math.round(p.coords.accuracy)} m.`;
  },()=>{el('status').textContent='Geen locatie beschikbaar. Controleer je locatietoestemming en GPS-ontvangst.';},{enableHighAccuracy:true,timeout:15000,maximumAge:10000});
});
renderOptions();render();
