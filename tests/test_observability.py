"""Quota-idempotentie bij retries, chatfouttelemetrie, routertelemetrie en kosten-samenvatting."""
import asyncio
from copy import deepcopy
import json
import logging
import os
from unittest import mock

from lusmaker import aws_chat, aws_state, gh, pilot, quotas, reroute, telemetry, tenant
from lusmaker.metrics import summarize
from tests.test_aws_state import _FakeS3, _aws_bucket


def _used(kind):
    state, _ = aws_state.get_json(f'usage/{kind}.json')
    return state['used']


def _capture():
    records = []

    class Handler(logging.Handler):
        def emit(self, record):
            records.append(json.loads(record.getMessage()))
    handler = Handler()
    telemetry.logger.addHandler(handler)
    return records, lambda: telemetry.logger.removeHandler(handler)


def test_metered_route_charges_a_retry_with_same_request_id_once():
    @quotas.metered('route')
    def plan(start, request_id=None):
        return start

    with _aws_bucket(), aws_state.use_client(_FakeS3()), tenant.use('retry'):
        plan('Wetteren', request_id='req-12345678')
        plan('Wetteren', request_id='req-12345678')
        assert _used('route') == 1
        plan('Wetteren', request_id='req-other-1')
        plan('Wetteren')  # zonder request-id: gedrag ongewijzigd
        plan('Wetteren')
        assert _used('route') == 4


def test_reroute_and_feedback_retries_are_not_double_charged():
    item = {'id': 'abc', 'revision': 1, 'start': {'lat': 51.0, 'lon': 3.7}, 'profile': 'standaard',
            '_geometry': [[[51.0, 3.7, 10], [51.01, 3.7, 10], [51.02, 3.7, 10]]]}

    def boom(*_args, **_kwargs):
        raise ValueError('router weg')

    with _aws_bucket(), aws_state.use_client(_FakeS3()), tenant.use('retry'):
        for _ in range(2):
            try:
                reroute.reroute_from('abc', 51.005, 3.7, 'kortste', request_id='req-12345678',
                                     load_fn=lambda _id: deepcopy(item), route_fn=boom, climbs_fn=lambda: {})
            except ValueError as exc:
                assert 'router weg' in str(exc)
        assert _used('route') == 1
        saved = []
        for _ in range(2):
            pilot.feedback('abc', 'anders', 'x', request_id='req-12345678', load=lambda _id: item,
                           put=lambda path, value, **kw: saved.append(path))
        assert _used('feedback') == 1
        assert saved[0] == saved[1]  # zelfde document, geen duplicaat


def test_token_reservation_is_idempotent_per_request_id():
    class Client:
        def converse(self, **kwargs):
            return {}

    agent = aws_chat.BedrockRouteAgent(client=Client(), tool_executor=object(), model_id='m')
    messages = [{'role': 'user', 'content': [{'text': 'hoi'}]}]
    with _aws_bucket(), aws_state.use_client(_FakeS3()), tenant.use('retry'):
        agent._converse(messages, 'conv:msg', 1)
        first = _used('tokens')
        agent._converse(messages, 'conv:msg', 1)
        assert _used('tokens') == first
        agent._converse(messages, 'conv:msg', 2)
        assert _used('tokens') == 2 * first


def test_chat_failure_emits_telemetry_with_tokens_and_error_class_only():
    class Store:
        def get(self, _id): return {}
        def add_message(self, *_a, **_k): return {'id': 'm1'}
        def messages(self, _id): return []

    class Agent:
        def reply(self, history, *, request_id):
            exc = aws_chat.ChatError('adres Kerkstraat 1 mislukt')
            exc.chat_usage = {'inputTokens': 11, 'outputTokens': 3}
            exc.chat_iterations = 2
            raise exc

    records, stop = _capture()
    try:
        try:
            aws_chat.send_message('c1', 'Kerkstraat 1', store=Store(), agent=Agent())
        except aws_chat.ChatError:
            pass
        else:
            raise AssertionError('fout verwacht')
    finally:
        stop()
    event = records[0]
    assert event['success'] is False and event['input_tokens'] == 11 and event['iterations'] == 2
    assert event['error_class'] == 'ChatError'
    assert 'Kerkstraat' not in json.dumps(event)


def test_agent_reply_attaches_partial_usage_to_failures():
    class Client:
        def converse(self, **_kw):
            return {'output': {'message': {'content': []}},
                    'usage': {'inputTokens': 7, 'outputTokens': 2, 'totalTokens': 9}}

    agent = aws_chat.BedrockRouteAgent(client=Client(), tool_executor=object(), model_id='m')
    try:
        agent.reply([{'role': 'user', 'content': 'hoi'}], request_id='c:m')
    except aws_chat.ChatError as exc:
        assert exc.chat_usage['inputTokens'] == 7 and exc.chat_iterations == 1
    else:
        raise AssertionError('fout verwacht')


def test_router_calls_and_startup_wait_are_recorded_per_request():
    stats = {'calls': 0, 'ms': 0.0, 'wait_ms': 0.0}
    token = telemetry.router_stats.set(stats)
    old = gh._ready_url
    try:
        gh._ready_url = None
        ticks = iter([0.0, 0.0, 2.0])
        results = iter([False, False, True])  # eerste probe meldt de koude start
        os.environ['LUSMAKER_GH_STARTUP_WAIT_S'] = '30'
        gh.wait_until_ready(health=lambda _u: next(results), sleep=lambda _s: None, clock=lambda: next(ticks))
        assert stats['wait_ms'] == 2000.0 and stats['calls'] == 0
        with mock.patch.object(gh, 'wait_until_ready'), mock.patch.object(gh, '_post_request', return_value={}):
            gh._post('/route', {})
            gh._post('/route', {})
        assert stats['calls'] == 2 and stats['ms'] >= 0
    finally:
        os.environ.pop('LUSMAKER_GH_STARTUP_WAIT_S', None)
        gh._ready_url = old
        telemetry.router_stats.reset(token)
    telemetry.router_record(calls=5)  # buiten een request: geen effect, geen fout


def test_http_event_includes_router_totals():
    async def app(scope, receive, send):
        telemetry.router_record(calls=2, ms=120.4, wait_ms=30.2)
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})

    async def noop(*_a):
        return None

    records, stop = _capture()
    try:
        asyncio.run(telemetry.MetricsMiddleware(app)({'type': 'http', 'path': '/health'}, noop, noop))
    finally:
        stop()
    assert records[0]['router_calls'] == 2 and records[0]['router_ms'] == 120 and records[0]['router_wait_ms'] == 30


def test_summary_reports_success_ratio_cost_per_route_and_router_time():
    events = [
        {'event': 'chat', 'success': True, 'input_tokens': 1_000_000, 'output_tokens': 0, 'routes_ready': 2},
        {'event': 'chat', 'success': False, 'input_tokens': 1_000_000, 'output_tokens': 0, 'error_class': 'ChatError'},
        {'event': 'http', 'operation': '/mcp', 'status': 200, 'success': True, 'seconds': 1,
         'router_calls': 3, 'router_ms': 900, 'router_wait_ms': 400},
        {'event': 'http', 'operation': '/mcp', 'status': 500, 'success': False, 'seconds': 1},
    ]
    result = summarize(events, input_per_million=1)
    assert result['chat_success_ratio'] == 0.5 and result['failed_chats'] == 1
    assert result['estimated_cost_per_successful_chat'] == 2
    assert result['estimated_cost_per_successful_route'] == 1
    assert result['http_success_ratio'] == 0.5
    assert result['router'] == {'requests': 1, 'calls': 3, 'total_ms': 900, 'wait_ms': 400}
    empty = summarize([])
    assert empty['chat_success_ratio'] is None and empty['router'] is None
    assert summarize(events)['estimated_cost_per_successful_route'] is None
