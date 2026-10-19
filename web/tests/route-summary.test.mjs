import test from 'node:test';
import assert from 'node:assert/strict';
import { estimateMinutes, formatDuration, reasonTone } from '../lib/route-summary.ts';

test('duur volgt activiteit en hoogtemeters', () => {
  assert.equal(estimateMinutes(6, 0, 'wandelen'), 80);
  assert.equal(estimateMinutes(6, 100, 'wandelen'), 90);
  assert.equal(estimateMinutes(60, 600, 'koersfiets'), 151);
  assert.equal(estimateMinutes(30, 200, 'onbekend'), 98, 'onbekende activiteit valt terug op fietsen');
  assert.equal(estimateMinutes(null, 10, 'wandelen'), null);
  assert.equal(estimateMinutes(0, 10, 'wandelen'), null);
});

test('duur leesbaar in minuten of uren', () => {
  assert.equal(formatDuration(45), '45 min');
  assert.equal(formatDuration(65), '1 u 05');
  assert.equal(formatDuration(150), '2 u 30');
  assert.equal(formatDuration(null), '—');
});

test('waarom-regel: vinkje, waarschuwing, kruisje of onbekend', () => {
  assert.equal(reasonTone({ ok: true, hard: false }), 'ok');
  assert.equal(reasonTone({ ok: false, hard: false }), 'soft');
  assert.equal(reasonTone({ ok: false, hard: true }), 'hard');
  assert.equal(reasonTone({ ok: null, hard: true }), 'unknown');
});
