import test from 'node:test';
import assert from 'node:assert/strict';
import {decide, evaluateCheckRuns} from '../scripts/vercel-ignore.mjs';

const SHA = 'a'.repeat(40);
const run = (name, status, conclusion, id = 1) => ({id, name, status, conclusion});
const green = () => ['test', 'terraform', 'web'].map((n) => run(n, 'completed', 'success'));
const reply = (body, ok = true, status = 200) => async () => ({ok, status, json: async () => body});
const prod = {VERCEL_ENV: 'production', VERCEL_GIT_COMMIT_SHA: SHA};
const fast = {sleep: async () => {}, pollIntervalMs: 1};

test('preview-builds worden niet afgeschermd en doen geen netwerkcall', async () => {
  const result = await decide({env: {VERCEL_ENV: 'preview'}, fetch: () => assert.fail('geen call')});
  assert.equal(result.build, true);
});

test('productie bouwt wanneer alle CI-jobs slagen', async () => {
  const result = await decide({env: prod, fetch: reply({check_runs: green()}), ...fast});
  assert.equal(result.build, true);
});

test('een falende CI-job blokkeert productie', async () => {
  const runs = green();
  runs[2] = run('web', 'completed', 'failure');
  const result = await decide({env: prod, fetch: reply({check_runs: runs}), ...fast});
  assert.equal(result.build, false);
  assert.match(result.reason, /web: failure/);
});

test('geannuleerde CI telt als mislukt', () => {
  const runs = green();
  runs[0] = run('test', 'completed', 'cancelled');
  assert.equal(evaluateCheckRuns(runs).state, 'failure');
});

test('jobs van de deploy-aanroep ("checks / test") tellen niet mee', () => {
  const runs = ['checks / test', 'checks / terraform', 'checks / web'].map((n) => run(n, 'completed', 'success'));
  assert.equal(evaluateCheckRuns(runs).state, 'pending');
});

test('de nieuwste run van een job telt na een herstart', () => {
  const runs = [run('test', 'completed', 'failure', 1), run('test', 'completed', 'success', 2),
    run('terraform', 'completed', 'success'), run('web', 'completed', 'success')];
  assert.equal(evaluateCheckRuns(runs).state, 'success');
});

test('wacht tot lopende CI klaar is en bouwt dan', async () => {
  const replies = [{check_runs: []}, {check_runs: [run('test', 'in_progress', null)]}, {check_runs: green()}];
  let calls = 0;
  const fetch = async () => ({ok: true, status: 200, json: async () => replies[calls++]});
  const result = await decide({env: prod, fetch, ...fast});
  assert.equal(result.build, true);
  assert.equal(calls, 3);
});

test('CI die te lang loopt slaat de productiebuild over', async () => {
  let t = 0;
  const result = await decide({
    env: prod, fetch: reply({check_runs: []}), maxWaitMs: 100, pollIntervalMs: 40,
    now: () => t, sleep: async (ms) => { t += ms; },
  });
  assert.equal(result.build, false);
  assert.match(result.reason, /niet klaar/);
});

test('rate limit, netwerkfout en rommelantwoord falen gesloten', async () => {
  for (const fetch of [reply({}, false, 403), async () => { throw new Error('offline'); }, reply({oops: 1})]) {
    const result = await decide({env: prod, fetch, ...fast});
    assert.equal(result.build, false);
  }
});

test('ontbrekende of ongeldige commit-SHA faalt gesloten', async () => {
  for (const sha of [undefined, 'abc', 'g'.repeat(40)]) {
    const result = await decide({env: {VERCEL_ENV: 'production', VERCEL_GIT_COMMIT_SHA: sha}, fetch: () => assert.fail('geen call')});
    assert.equal(result.build, false);
  }
});
