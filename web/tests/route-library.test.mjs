import test from 'node:test';
import assert from 'node:assert/strict';
import { filterRoutes } from '../lib/route-library.ts';

const routes = [
  {id:'new',name:'Café aan de Schelde',start:'Wetteren',region:'Vlaanderen',activity:'fietsen'},
  {id:'old',name:'Bospaden',start:'Blaarmeersen',region:'Vlaanderen',activity:'trail'},
];
test('routezoeker negeert accenten, combineert woorden en behoudt recente volgorde', () => {
  assert.deepEqual(filterRoutes(routes, ' CAFE   wetteren ', 'all').map(r => r.id), ['new']);
  assert.deepEqual(filterRoutes(routes, 'vlaanderen', 'all').map(r => r.id), ['new','old']);
  assert.equal(filterRoutes(routes, 'schelde', 'trail').length, 0);
  assert.deepEqual(filterRoutes(routes, '', 'trail').map(r => r.id), ['old']);
  assert.equal(routes.length, 2);
});
test('routezoeker verdraagt ontbrekende optionele velden en lege bibliotheek', () => {
  assert.equal(filterRoutes([{id:'x',name:'Lus',activity:'fietsen'}], 'lus', 'all').length, 1);
  assert.deepEqual(filterRoutes([], '', 'all'), []);
});
