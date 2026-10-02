"""SSE rond bestaande geauthenticeerde JSON-handlers, inclusief requestreceipts."""
import asyncio
import json
from starlette.responses import StreamingResponse
from . import progress


def frame(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


def response(request, handler, *, heartbeat_seconds=10):
    async def events():
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        def publish(value):
            loop.call_soon_threadsafe(queue.put_nowait, ('progress', value))
        async def produce():
            try:
                with progress.capture(publish):
                    result = await handler(request)
                payload = json.loads(result.body)
                await queue.put(('result' if result.status_code < 400 else 'error', {**payload, 'http_status': result.status_code}))
            except Exception:
                await queue.put(('error', {'error':'De opdracht kon niet worden afgerond. Herlaad het gesprek en controleer je routes.', 'http_status':500}))
        task = asyncio.create_task(produce())
        yield frame('progress', {'stage':'accepted','message':'Je opdracht is ontvangen.'})
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield ': heartbeat\n\n'
                    continue
                yield frame(kind, payload)
                if kind in ('result','error'):
                    break
        finally:
            # Een verbroken browserverbinding mag geen tweede route-uitvoering
            # veroorzaken. Laat de bestaande operatie haar receipt afronden.
            await asyncio.shield(task)
    return StreamingResponse(events(), media_type='text/event-stream', headers={
        'Cache-Control':'no-store, no-transform', 'X-Accel-Buffering':'no'})
