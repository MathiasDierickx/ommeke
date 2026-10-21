import test from 'node:test';
import assert from 'node:assert/strict';

process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID = 'test-client';
process.env.NEXT_PUBLIC_COGNITO_REGION = 'eu-west-1';
const store = new Map();
globalThis.localStorage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k) };
globalThis.sessionStorage = globalThis.localStorage;
const { currentSession, signOut, storedSession } = await import('../lib/cognito.ts');

const jwt = claims => `e30.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.sig`;
const expired = () => ({ accessToken: jwt({ sub: 'u1' }), idToken: jwt({ sub: 'u1', email: 'a@b.test' }), refreshToken: 'refresh-1', expiresAt: Date.now() - 1000 });
const cognito = (status, body) => async () => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

test('verlopen access token wordt vernieuwd met het refresh-token', async () => {
  store.set('lusmaker.auth', JSON.stringify(expired()));
  globalThis.fetch = cognito(200, { AuthenticationResult: { AccessToken: jwt({ sub: 'u1', fresh: true }), IdToken: jwt({ sub: 'u1' }), ExpiresIn: 3600 } });
  const session = await currentSession();
  assert.ok(session && session.expiresAt > Date.now());
  assert.equal(session.refreshToken, 'refresh-1', 'refresh-token blijft bewaard als Cognito er geen nieuw geeft');
  assert.equal(storedSession().accessToken, session.accessToken);
});

test('netwerkfout of 5xx bij de refresh wist de sessie niet', async () => {
  for (const fetcher of [async () => { throw new Error('offline'); }, cognito(500, { __type: 'InternalErrorException' }), cognito(400, { __type: 'TooManyRequestsException' })]) {
    const session = expired();
    store.set('lusmaker.auth', JSON.stringify(session));
    globalThis.fetch = fetcher;
    const result = await currentSession();
    assert.equal(result?.accessToken, session.accessToken, 'bewaarde sessie blijft bruikbaar');
    assert.ok(storedSession(), 'localStorage blijft gevuld');
  }
});

test('een door Cognito geweigerd refresh-token logt wél uit', async () => {
  store.set('lusmaker.auth', JSON.stringify(expired()));
  globalThis.fetch = cognito(400, { __type: 'NotAuthorizedException', message: 'Invalid Refresh Token' });
  assert.equal(await currentSession(), null);
  assert.equal(storedSession(), null);
  assert.match(store.get('lusmaker.auth.reden'), /NotAuthorizedException/, 'reden van de weigering blijft bewaard');
});

test('afmelden trekt alleen het refresh-token van dit toestel in', async () => {
  const session = expired();
  store.set('lusmaker.auth', JSON.stringify(session));
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ target: init.headers['X-Amz-Target'], body: JSON.parse(init.body) }); return new Response('{}', { status: 200 }); };
  await signOut(session);
  assert.deepEqual(calls, [{ target: 'AWSCognitoIdentityProviderService.RevokeToken', body: { Token: 'refresh-1', ClientId: 'test-client' } }]);
  assert.equal(storedSession(), null);
});
