import test from 'node:test';
import assert from 'node:assert/strict';
import { optionLabel, questionTopic, reasonAddsInfo, reasonText } from '../lib/question-labels.ts';
import { conversationPreview } from '../lib/route-library.ts';

test('reden: hoofdletter en zonder technisch staartje', () => {
  assert.equal(reasonText('je verkenningsroute heeft 160 hoogtemeters over 12,8 km (12,5 hm/km); heuvelvoorkeur onbekend'), 'Je verkenningsroute heeft 160 hoogtemeters over 12,8 km (12,5 hm/km)');
  assert.equal(reasonText('Er ligt 1,8 km kassei op de verkenning.'), 'Er ligt 1,8 km kassei op de verkenning.');
  assert.equal(reasonText(null), '');
});

test('gesprekspreview zonder concept-id en markdown', () => {
  assert.equal(conversationPreview('Routeconcept 94ef77 heeft nog aanvullende wensen nodig. 12,5 km is verhard.'), '12,5 km is verhard.');
  assert.equal(conversationPreview('**Route**: *Racefietsrit*'), 'Route: Racefietsrit');
  assert.equal(conversationPreview(undefined), '');
});

test('reden alleen als ze iets toevoegt; onderwerp voor het overzicht', () => {
  assert.equal(reasonAddsInfo({ vraag: 'Slechts 25% van je verkenningsroute is fietspad, terwijl je door bebouwde kom rijdt. Wil je…?', reden: 'Slechts 25% van je verkenningsroute is fietspad, terwijl je door 3 bebouwde kernen rijdt', opties: {} }), false);
  assert.equal(reasonAddsInfo({ vraag: 'Het is hier heuvelachtig. Zoek je de heuvels op?', reden: 'je verkenningsroute heeft 90 hoogtemeters over 12,9 km (7,0 hm/km); heuvelvoorkeur onbekend', opties: {} }), true);
  assert.equal(reasonAddsInfo({ vraag: 'Welke?', opties: {} }), false);
  assert.equal(questionTopic({ id: 'heuvels', vraag: 'x', opties: {} }), 'Heuvels');
  assert.equal(questionTopic({ vraag: 'x', opties: {} }), '');
});

test('knoptekst gebruikt het label van de engine voor elke vraag', () => {
  const q = { id: 'plek_afstand', vraag: 'Donkmeer ligt ver.', opties: { ruimer: { label: 'Naar Donkmeer, ~39 km' }, zonder: { label: '14 km zonder Donkmeer' } } };
  assert.equal(optionLabel(q, 'ruimer'), 'Naar Donkmeer, ~39 km');
  assert.equal(optionLabel(q, 'zonder'), '14 km zonder Donkmeer');
  assert.equal(optionLabel({ id: 'knooppunten', vraag: 'x', opties: { graag: {}, ok: {} } }, 'graag'), 'Graag via knooppunten');
  assert.equal(optionLabel({ id: 'knooppunten', vraag: 'x', opties: { graag: {}, ok: {} } }, 'ok'), 'Maakt me niet uit');
});
