import test from 'node:test';
import assert from 'node:assert/strict';
import {readEventStream} from '../lib/event-stream.ts';
const body = text => {
 const bytes = new TextEncoder().encode(text);
 return new ReadableStream({start(controller){for(const byte of bytes)controller.enqueue(Uint8Array.of(byte));controller.close();}});
};
test('SSE leest gesplitste UTF-8 en frames, negeert heartbeats en levert het echte eindresultaat',async()=>{
 const events=[];
 const result=await readEventStream(body(': heartbeat\n\nevent: progress\ndata: {"stage":"routing","message":"Café zoeken"}\n\nevent: result\ndata: {"status":"ready","draft":"abc"}\n\n'),e=>events.push(e));
 assert.equal(events[0].message,'Café zoeken');assert.equal(result.draft,'abc');
});
test('SSE weigert fouten en een afgebroken stream zonder eindresultaat',async()=>{
 await assert.rejects(readEventStream(body('event: error\ndata: {"error":"Geen route"}\n\n'),()=>{}),/Geen route/);
 await assert.rejects(readEventStream(body(': heartbeat\n\n'),()=>{}),/onderbroken/);
});
test('SSE verdraagt CRLF tussen afzonderlijke netwerkchunks',async()=>{
 const result=await readEventStream(body('event: result\r\ndata: {"ok":true}\r\n\r\n'),()=>{});
 assert.equal(result.ok,true);
});
