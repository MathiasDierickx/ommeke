import test from 'node:test';
import assert from 'node:assert/strict';
import { filterRoutes, routeTitle } from '../lib/route-library.ts';

const routes = [
  {id:'new',name:'Café aan de Schelde',start:'Wetteren',region:'Vlaanderen',activity:'fietsen'},
  {id:'old',name:'Bospaden',start:'Blaarmeersen',region:'Vlaanderen',activity:'trail'},
];
test('routezoeker negeert accenten, combineert woorden en behoudt recente volgorde', () => {
  assert.deepEqual(filterRoutes(routes, ' CAFE   wetteren ', 'all').map(r => r.id), ['new']);
  assert.deepEqual(filterRoutes(routes, 'vlaanderen', 'all').map(r => r.id), ['new','old']);
  assert.equal(filterRoutes(routes, 'schelde', 'voet').length, 0);
  assert.deepEqual(filterRoutes(routes, '', 'voet').map(r => r.id), ['old']);
  assert.equal(routes.length, 2);
});
test('routezoeker verdraagt ontbrekende optionele velden en lege bibliotheek', () => {
  assert.equal(filterRoutes([{id:'x',name:'Lus',activity:'fietsen'}], 'lus', 'all').length, 1);
  assert.deepEqual(filterRoutes([{id:'w',name:'A',activity:'wandelen'},{id:'r',name:'B',activity:'koersfiets'}], '', 'fiets').map(r => r.id), ['r']);
  assert.deepEqual(filterRoutes([], '', 'all'), []);
});

test('routetitel laat de gevraagde km uit de naam weg zodra de echte afstand bekend is', () => {
  assert.equal(routeTitle({ name: 'Rondrit rond Oudenaarde · 20 km', ready: true, total_km: 27.5 }), 'Rondrit rond Oudenaarde');
  assert.equal(routeTitle({ name: 'Wandeling langs de Schelde – 4 km', ready: true, total_km: 4.1 }), 'Wandeling langs de Schelde');
  assert.equal(routeTitle({ name: 'Wandellus rond Wetteren · 3.1 km', ready: true, total_km: 3.2 }), 'Wandellus rond Wetteren');
  assert.equal(routeTitle({ name: 'Rondrit rond Oudenaarde · 20 km', ready: false, total_km: null }), 'Rondrit rond Oudenaarde · 20 km');
  assert.equal(routeTitle({ name: 'Berendries-lus', ready: true, total_km: 30 }), 'Berendries-lus');
});
