"""Gestructureerde operationele events zonder prompts, routes of credentials."""
from contextvars import ContextVar
import json
import logging
import re
import time
import uuid

request_id = ContextVar('request_id', default=None)
logger = logging.getLogger('lusmaker.metrics')
logger.setLevel(logging.INFO)
ALLOWED = {'event', 'request_id', 'operation', 'status', 'seconds', 'input_tokens', 'output_tokens', 'iterations', 'success', 'cold_start'}


def emit(event, **values):
    payload = {"event": event, "request_id": request_id.get(), **values}
    logger.info(json.dumps({k: v for k, v in payload.items() if k in ALLOWED}, ensure_ascii=False, separators=(',', ':')))


def operation(path):
    if path.startswith('/api/shared/'):
        return '/api/shared/:token'
    path = re.sub(r'(/api/(?:routes|conversations)/)[^/]+', r'\1:id', path)
    path = re.sub(r'(/requests/)[^/]+', r'\1:id', path)
    return path if path in {'/mcp', '/health', '/api/routes', '/api/conversations', '/api/feedback', '/api/account/export', '/api/account', '/api/me'} or ':id' in path else 'other'


class MetricsMiddleware:
    def __init__(self, app):
        self.app = app
        self.cold = True

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        token = request_id.set(uuid.uuid4().hex)
        started = time.monotonic()
        status = 500
        cold, self.cold = self.cold, False
        async def tracked(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message = {**message, 'headers': [*message.get('headers', []), (b'x-request-id', request_id.get().encode())]}
            await send(message)
        try:
            await self.app(scope, receive, tracked)
        finally:
            emit('http', operation=operation(scope['path']), status=status,
                 seconds=round(time.monotonic()-started, 3), success=status < 400, cold_start=cold)
            request_id.reset(token)
