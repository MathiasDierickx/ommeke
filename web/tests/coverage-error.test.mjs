import test from 'node:test';
import assert from 'node:assert/strict';
import { errorMessage, isOutOfCoverage } from '../lib/interaction.ts';
import { readEventStream, StreamFailure } from '../lib/event-stream.ts';

const message = 'Ommeke dekt momenteel Vlaanderen ongeveer tussen 50.68°N en 51.10°N.';

test('buiten_gebied toont de servertekst met het gedekte gebied', () => {
  assert.equal(errorMessage(422, message, null, 'buiten_gebied'), message);
  assert.equal(isOutOfCoverage({ code: 'buiten_gebied' }), true);
  assert.equal(isOutOfCoverage({ code: 'bad_request' }), false);
  assert.equal(isOutOfCoverage(new Error('x')), false);
  assert.equal(isOutOfCoverage(null), false);
});

test('een foutevent in de stream bewaart de code buiten_gebied', async () => {
  const payload = JSON.stringify({ error: message, code: 'buiten_gebied', http_status: 422 });
  const body = new Response(`event: error\ndata: ${payload}\n\n`).body;
  await assert.rejects(readEventStream(body, () => {}), (error) => {
    assert.ok(error instanceof StreamFailure);
    assert.equal(error.message, message);
    assert.equal(isOutOfCoverage(error), true);
    return true;
  });
});
