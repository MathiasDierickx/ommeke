import test from 'node:test';
import assert from 'node:assert/strict';
import { pendingPrompt, errorMessage, mergeById, chatReply, unansweredPrompt, orphanState } from '../lib/interaction.ts';

test('retry en refresh behouden hetzelfde verzoeknummer, nieuwe inhoud niet', () => {
  const first = pendingPrompt(null, 'chat1', '  50 km  ', () => 'id-1');
  const restored = JSON.parse(JSON.stringify(first));
  assert.equal(pendingPrompt(restored, 'chat1', '50 km', () => 'id-2').id, 'id-1');
  assert.equal(pendingPrompt(restored, 'chat1', '60 km', () => 'id-2').id, 'id-2');
  assert.equal(pendingPrompt(restored, 'chat2', '50 km', () => 'id-3').id, 'id-3');
  assert.throws(() => pendingPrompt(null, 'chat', ' ', () => 'id'));
});
test('quota en revision-fouten bieden begrijpelijk herstel', () => {
  assert.match(errorMessage(429, 'provider', '61'), /2 minuten/);
  assert.equal(errorMessage(409, 'Route gewijzigd; laad opnieuw.'), 'Route gewijzigd; laad opnieuw.');
  assert.doesNotMatch(errorMessage(429, 'secret', null), /secret/);
  assert.match(errorMessage(429, 'provider', '7200'), /2 uur/);
  const quota='Je daglimiet voor chatberichten (40) is bereikt. De teller start opnieuw vannacht om 02:00 (Belgische tijd).';
  assert.equal(errorMessage(429, quota, '10800', 'quota_exceeded'), quota);
  assert.doesNotMatch(errorMessage(429, 'secret', '60', 'other'), /secret/);
});
test('paginering en herhaalde antwoorden dupliceren geen routes of berichten', () => {
  const result = mergeById([{id: 'a', revision: 1}], [{id:'a', revision:2}, {id:'b', revision:1}]);
  assert.deepEqual(result, [{id:'a', revision:2}, {id:'b', revision:1}]);
});

test('onvolledig chatantwoord geeft herstelmelding in plaats van rendercrash', () => {
  for (const payload of [null, {}, {route_ids:[]}, {message:{id:'a'},route_ids:[]}]) assert.throws(() => chatReply(payload), /geen volledig chatantwoord/);
  const payload = {message:{id:'a',conversation_id:'c',role:'assistant',content:'Klaar',created_at:'2026-10-02'},route_ids:['route']};
  assert.equal(chatReply(payload),payload);
});

test('een onbeantwoorde vraag na herladen krijgt een herstelstatus', () => {
  assert.equal(unansweredPrompt([{role:'user',content:'a'},{role:'assistant',content:'b'}]), null);
  assert.equal(unansweredPrompt([{role:'assistant',content:'b'},{role:'user',content:' 35 km '}]), '35 km');
  assert.equal(unansweredPrompt([]), null);
  assert.equal(orphanState('running', true), 'running');
  assert.equal(orphanState('complete', true), 'complete');
  assert.equal(orphanState('interrupted', true), 'interrupted');
  assert.equal(orphanState('unknown', true), 'interrupted');
  assert.equal(orphanState('running', false), 'interrupted');
});
