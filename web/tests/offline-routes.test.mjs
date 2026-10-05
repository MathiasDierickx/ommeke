import test from 'node:test';
import assert from 'node:assert/strict';
import { upsertEntry, removeEntry, parseEntries, slimGeometry, MAX_AUTO, MAX_SAVED } from '../lib/offline-routes.ts';

const entry = (id, auto = true, n = 3) => ({
  id, name: id, revision: 1, saved_at: '2026-10-06T10:00:00Z', ...(auto ? { auto: true } : {}),
  geometry: { points: Array.from({ length: n }, (_, i) => [51 + i / 1000, 3 + i / 1000]) },
});
const fill = (list, ids, auto) => ids.reduce((acc, id) => upsertEntry(acc, entry(id, auto)), list);

test('automatische routes zijn begrensd op de laatste vijf, nieuwste eerst', () => {
  const list = fill([], ['a', 'b', 'c', 'd', 'e', 'f', 'g'], true);
  assert.equal(list.length, MAX_AUTO);
  assert.deepEqual(list.map(r => r.id), ['g', 'f', 'e', 'd', 'c']);
});

test('opnieuw openen verplaatst een route naar voren zonder duplicaat', () => {
  const list = upsertEntry(fill([], ['a', 'b', 'c'], true), entry('a'));
  assert.deepEqual(list.map(r => r.id), ['a', 'c', 'b']);
});

test('automatische routes verdringen expliciet bewaarde routes niet', () => {
  let list = fill([], ['s1', 's2'], false);
  list = fill(list, ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7'], true);
  assert.deepEqual(list.filter(r => !r.auto).map(r => r.id).sort(), ['s1', 's2']);
  assert.equal(list.filter(r => r.auto).length, MAX_AUTO);
});

test('expliciet bewaarde routes zijn begrensd op tien', () => {
  const list = fill([], Array.from({ length: 13 }, (_, i) => `s${i}`), false);
  assert.equal(list.length, MAX_SAVED);
  assert.equal(list[0].id, 's12');
});

test('automatisch verversen degradeert een expliciet bewaarde route niet', () => {
  const list = upsertEntry(fill([], ['s'], false), { ...entry('s', true), revision: 2 });
  assert.equal(list[0].revision, 2);
  assert.equal(list[0].auto, undefined);
});

test('expliciet bewaren promoveert een automatische route', () => {
  const list = upsertEntry(fill([], ['a'], true), entry('a', false));
  assert.equal(list[0].auto, undefined);
});

test('bytegrens laat eerst de oudste automatische route vallen en houdt de nieuwe', () => {
  let list = [entry('s', false)];
  const big = id => entry(id, true, 200);
  const limit = JSON.stringify([entry('s', false), big('a'), big('b')]).length + 10;
  for (const id of ['a', 'b', 'c']) list = upsertEntry(list, big(id), limit);
  assert.ok(JSON.stringify(list).length <= limit);
  assert.equal(list[0].id, 'c');
  assert.ok(list.some(r => r.id === 's'), 'expliciete route blijft');
  assert.ok(!list.some(r => r.id === 'a'));
});

test('de nieuwste route blijft zelfs als ze alleen al boven de grens zit', () => {
  const list = upsertEntry([entry('a')], entry('b', true, 500), 100);
  assert.deepEqual(list.map(r => r.id), ['b']);
});

test('verwijderen en kapotte opslag', () => {
  assert.deepEqual(removeEntry([entry('a'), entry('b')], 'a').map(r => r.id), ['b']);
  assert.deepEqual(parseEntries('niet-json'), []);
  assert.deepEqual(parseEntries('{"a":1}'), []);
  assert.deepEqual(parseEntries(null), []);
  assert.deepEqual(parseEntries(JSON.stringify([{ id: 'x' }, entry('ok')])).map(r => r.id), ['ok']);
});

test('slimGeometry laat POI\'s weg', () => {
  const slim = slimGeometry({ points: [[1, 2]], pois: [{ id: 'p' }], elevation: [{ km: 0, ele: 1 }] });
  assert.deepEqual(Object.keys(slim).sort(), ['climbs', 'elevation', 'points', 'start']);
});
