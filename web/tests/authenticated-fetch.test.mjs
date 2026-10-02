import test from 'node:test';
import assert from 'node:assert/strict';
import {fetchAuthenticated} from '../lib/authenticated-fetch.ts';

test('expired sessions renew once and retain the exact POST receipt and payload', async () => {
  const sent=[], refresh=[];
  const init={method:'POST',body:JSON.stringify({request_id:'same-receipt',content:'route'}),headers:{Accept:'text/event-stream'}};
  const result=await fetchAuthenticated('/route',init,'old',async (token,force)=>{refresh.push([token,force]);return force?'fresh':token;},async (url,request)=>{
    sent.push(request);
    return new Response(sent.length===1?'unauthorized':'result',{status:sent.length===1?401:200});
  });
  assert.equal(result.status,200);
  assert.deepEqual(refresh,[['old',false],['old',true]]);
  assert.equal(sent[0].body,sent[1].body);
  assert.equal(sent[1].headers.get('Authorization'),'Bearer fresh');
  assert.equal(sent[1].headers.get('Accept'),'text/event-stream');
});

test('quota, failed requests and network errors never replay a mutation', async () => {
  for (const status of [400,403,409,429,500]) {
    let calls=0;
    const result=await fetchAuthenticated('/route',{method:'POST'},'token',async t=>t,async()=>{calls++;return new Response('',{status});});
    assert.equal(calls,1);assert.equal(result.status,status);
  }
  let calls=0;
  await assert.rejects(fetchAuthenticated('/route',{method:'POST'},'token',async t=>t,async()=>{calls++;throw Error('offline');}),/offline/);
  assert.equal(calls,1);
});

test('a rejected refreshed token stops after one retry', async () => {
  let calls=0;
  const result=await fetchAuthenticated('/route',{},'token',async t=>t,async()=>{calls++;return new Response('',{status:401});});
  assert.equal(calls,2);assert.equal(result.status,401);
});
