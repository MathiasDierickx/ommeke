import test from 'node:test';
import assert from 'node:assert/strict';
import { reasonText } from '../lib/question-labels.ts';
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
