import test from 'node:test';
import assert from 'node:assert/strict';
import { messageOptions } from '../lib/message-options.ts';

test('chatopties verwijderen markdown en coördinaatstaarten', () => {
  assert.deepEqual(messageOptions({role:'assistant', content:'Welke plek?\n0. **Kluisbos (Buizingen)** – lat 50.73 lon 4.26\n1. _Kluisbos (Kluisbergen)_ — lat 50.76 lon 3.50\n2. Gent'}), ['Kluisbos (Buizingen)', 'Kluisbos (Kluisbergen)', 'Gent']);
});

test('chatopties blijven beperkt tot vragen van de assistent met twee tot zes opties', () => {
  for (const message of [
    {role:'user', content:'Welke?\n- A\n- B'},
    {role:'assistant', content:'Opties\n- A\n- B'},
    {role:'assistant', content:'Welke?\n- A'},
    {role:'assistant', content:'Welke?'+Array.from({length:7}, (_, i) => `\n- ${i}`).join('')},
  ]) assert.deepEqual(messageOptions(message), []);
});


test('chatopties slaan code, tools en bestanden over vóór markdownopschoning', () => {
  const content = 'Wat wil je?\n- GPX: [/tmp/lusmaker/exports/r1/route.gpx]\n- Preview: [route.html]\n1. Voeg Chemin toe `adjust_route(voeg_klimmen_toe=["x"])`\n2. adjust_route(target_km=55)\n- `Maakt niet uit`\n- /tmp/ander-bestand\n- **Liever vlak**\n- _Graag heuvels_';
  assert.deepEqual(messageOptions({role:'assistant', content}), ['Liever vlak', 'Graag heuvels']);
  assert.deepEqual(messageOptions({role:'assistant', content:'Klaar?\n- route.GPX\n- preview.HTML\n- `code`\n- adjust_route (target_km=55)'}), []);
});
