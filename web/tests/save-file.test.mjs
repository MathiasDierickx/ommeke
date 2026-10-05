import test from 'node:test';
import assert from 'node:assert/strict';
import {safeFilename, saveBlob} from '../lib/save-file.ts';

test('blob downloads stay alive until Chrome has started a delayed download', () => {
  const events=[], scheduled=[];
  const anchor={style:{},click:()=>events.push('click'),remove:()=>events.push('remove')};
  saveBlob(new Blob(['fit']),'route.fit',{
    document:{createElement:()=>anchor,body:{appendChild:()=>events.push('append')}},
    url:{createObjectURL:()=>'blob:x',revokeObjectURL:()=>events.push('revoke')},
    schedule:(callback,ms)=>scheduled.push([callback,ms]),
  });
  assert.deepEqual(events,['append','click']);
  assert.equal(anchor.download,'route.fit');
  assert.ok(scheduled[0][1]>=10_000);
  scheduled[0][0]();
  assert.deepEqual(events,['append','click','remove','revoke']);
});

test('route names become portable filenames', () => {
  assert.equal(safeFilename('Traillus rond je startpunt · 3 km','fit'),'Traillus rond je startpunt · 3 km.fit');
  assert.equal(safeFilename('A/B: lus?','gpx'),'A B lus.gpx');
  assert.equal(safeFilename('  ','gpx'),'ommeke-route.gpx');
});
