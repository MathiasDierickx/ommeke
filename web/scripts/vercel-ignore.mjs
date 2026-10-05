// Vercel "ignoreCommand": laat een productiebuild alleen door als de CI van
// exact deze commit is geslaagd. Exitcode 1 = bouwen, exitcode 0 = overslaan.
// Alles faalt gesloten: onbekende toestand, rate limit of timeout slaat de build over.
import {pathToFileURL} from 'node:url';

export const REPOSITORY = 'MathiasDierickx/ommeke';
// Namen van de jobs in .github/workflows/ci.yml. Aanroepen via deploy-aws.yml
// heten "checks / test" enz. en tellen dus niet mee.
export const REQUIRED_CHECKS = ['test', 'terraform', 'web'];
export const POLL_INTERVAL_MS = 20_000;
export const MAX_WAIT_MS = 9 * 60_000;

// Beoordeel de check-runs van een commit: 'success' | 'failure' | 'pending'.
export function evaluateCheckRuns(checkRuns, required = REQUIRED_CHECKS) {
  const problems = [];
  let pending = false;
  for (const name of required) {
    // Bij herstarts bestaan er meerdere runs met dezelfde naam; de nieuwste telt.
    const runs = checkRuns
      .filter((run) => run.name === name)
      .sort((a, b) => (b.id ?? 0) - (a.id ?? 0));
    const run = runs[0];
    if (!run) { pending = true; continue; }
    if (run.status !== 'completed') { pending = true; continue; }
    if (run.conclusion !== 'success') problems.push(`${name}: ${run.conclusion}`);
  }
  if (problems.length) return {state: 'failure', detail: problems.join(', ')};
  if (pending) return {state: 'pending', detail: 'CI is nog niet klaar'};
  return {state: 'success', detail: 'CI geslaagd'};
}

async function fetchCheckRuns({sha, fetch, repository}) {
  const url = `https://api.github.com/repos/${repository}/commits/${sha}/check-runs?per_page=100`;
  const response = await fetch(url, {
    headers: {accept: 'application/vnd.github+json', 'user-agent': 'lusmaker-vercel-ignore'},
  });
  if (!response.ok) throw new Error(`GitHub-API gaf status ${response.status}`);
  const body = await response.json();
  if (!Array.isArray(body.check_runs)) throw new Error('Onverwacht GitHub-antwoord');
  return body.check_runs;
}

// Resultaat: {build: boolean, reason: string}. Gooit nooit; fouten worden "niet bouwen".
export async function decide({
  env = process.env,
  fetch = globalThis.fetch,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now = () => Date.now(),
  repository = REPOSITORY,
  pollIntervalMs = POLL_INTERVAL_MS,
  maxWaitMs = MAX_WAIT_MS,
} = {}) {
  if (env.VERCEL_ENV !== 'production') {
    return {build: true, reason: `Geen productiebuild (${env.VERCEL_ENV || 'onbekend'}); niet afgeschermd.`};
  }
  const sha = env.VERCEL_GIT_COMMIT_SHA;
  if (!/^[0-9a-f]{40}$/i.test(sha || '')) {
    return {build: false, reason: 'Geen geldige VERCEL_GIT_COMMIT_SHA; productiebuild overgeslagen.'};
  }
  const deadline = now() + maxWaitMs;
  for (;;) {
    let verdict;
    try {
      verdict = evaluateCheckRuns(await fetchCheckRuns({sha, fetch, repository}));
    } catch (error) {
      return {build: false, reason: `CI-status onbekend (${error.message}); productiebuild overgeslagen.`};
    }
    if (verdict.state === 'success') return {build: true, reason: `CI geslaagd voor ${sha.slice(0, 7)}.`};
    if (verdict.state === 'failure') {
      return {build: false, reason: `CI mislukt voor ${sha.slice(0, 7)} (${verdict.detail}); productiebuild overgeslagen.`};
    }
    if (now() + pollIntervalMs > deadline) {
      return {build: false, reason: `CI niet klaar binnen de wachttijd voor ${sha.slice(0, 7)}; productiebuild overgeslagen. Herdeploy na een groene CI.`};
    }
    await sleep(pollIntervalMs);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = await decide();
  console.log(`[vercel-ignore] ${result.reason}`);
  process.exit(result.build ? 1 : 0);
}
