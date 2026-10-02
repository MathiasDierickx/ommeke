import asyncio
import json
from starlette.responses import JSONResponse
from lusmaker import progress
from lusmaker.streaming import response


def test_stream_delivers_progress_before_result_with_thread_context():
    async def run():
        release = asyncio.Event()
        async def handler(_):
            await asyncio.to_thread(progress.emit, 'routing', 'Café en route zoeken')
            await release.wait()
            return JSONResponse({'status':'ready','draft':'abc123'})
        stream = await response(None, handler)
        iterator = stream.body_iterator
        assert 'accepted' in await anext(iterator)
        step = await asyncio.wait_for(anext(iterator), 1)
        assert 'Café' in step and 'event: progress' in step
        release.set()
        result = await asyncio.wait_for(anext(iterator), 1)
        assert 'event: result' in result and 'abc123' in result
        await iterator.aclose()
        collected=[]
        with progress.capture(collected.append): progress.emit('other','Los verzoek')
        progress.emit('outside','Niet doorsturen')
        assert len(collected)==1
    asyncio.run(run())


def test_stream_preserves_errors_and_never_reports_them_as_success():
    async def run():
        async def handler(_): return JSONResponse({'error':'Limiet bereikt'}, status_code=429)
        chunks=[chunk async for chunk in (await response(None,handler)).body_iterator]
        assert 'event: error' in chunks[-1] and '"http_status": 429' in chunks[-1]
        assert not any('event: result' in chunk for chunk in chunks)
        async def broken(_): raise RuntimeError('private detail')
        chunks=[chunk async for chunk in (await response(None,broken)).body_iterator]
        assert 'private detail' not in ''.join(chunks)
    asyncio.run(run())


def test_stream_reads_post_body_before_starting_disconnect_listener():
    from starlette.requests import Request
    async def run():
        reads=[]
        async def receive():
            reads.append(True)
            if len(reads)>1: raise AssertionError("De POST-body mag maar één keer uit het kanaal gelezen worden")
            return {'type':'http.request','body':b'{"content":"Wetteren"}','more_body':False}
        request=Request({'type':'http','method':'POST','path':'/test','headers':[]},receive)
        async def handler(req):
            data=await req.json()
            return JSONResponse({'echo':data['content']})
        stream=await response(request,handler)
        assert len(reads)==1  # vóór de ASGI response/disconnect listener start
        chunks=[chunk async for chunk in stream.body_iterator]
        assert len(reads)==1 and '"echo": "Wetteren"' in chunks[-1]
    asyncio.run(run())
