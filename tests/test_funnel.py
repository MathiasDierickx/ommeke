import io
import json
import logging

from lusmaker import funnel, telemetry
from lusmaker.metrics import summarize


def _events():
    return [
        {'event': 'route_requested', 'channel': 'quick', 'activity': 'toerfiets', 'actor': 'a', 'date': '2026-10-01'},
        {'event': 'route_ready', 'channel': 'quick', 'activity': 'toerfiets', 'stage': 'plan', 'needs_input': True, 'question_ids': ['kasseien'], 'actor': 'a', 'date': '2026-10-01'},
        {'event': 'route_adjusted', 'channel': 'quick', 'kind': 'answers', 'actor': 'a', 'date': '2026-10-01'},
        {'event': 'route_ready', 'channel': 'quick', 'stage': 'adjust', 'needs_input': False, 'km_bucket': '25-50', 'question_ids': [], 'actor': 'a', 'date': '2026-10-01'},
        {'event': 'route_exported', 'activity': 'toerfiets', 'format': 'gpx', 'actor': 'a', 'date': '2026-10-01'},
        {'event': 'route_requested', 'channel': 'chat', 'activity': 'wandelen', 'actor': 'b', 'date': '2026-10-01'},
        {'event': 'route_ready', 'channel': 'chat', 'activity': 'wandelen', 'stage': 'plan', 'needs_input': False, 'km_bucket': '<10', 'question_ids': [], 'actor': 'b', 'date': '2026-10-01'},
        {'event': 'route_requested', 'channel': 'mcp', 'activity': 'toerfiets'},
        {'event': 'http', 'operation': '/mcp', 'seconds': 1, 'status': 200, 'actor': 'a', 'date': '2026-10-08'},
    ]


def test_funnel_summary_counts_ratios_channels_and_return_visit():
    f = summarize(_events())['funnel']
    assert (f['requested'], f['ready'], f['needs_input'], f['adjusted'], f['exported']) == (3, 2, 1, 1, 1)
    assert f['ready_ratio'] == round(2 / 3, 4)
    assert f['exported_ratio'] == 0.5 and f['adjusted_ratio'] == 0.5
    assert f['by_channel']['quick'] == {'requested': 1, 'ready': 1, 'adjusted': 1, 'needs_input': 1, 'ready_ratio': 1.0}
    assert f['by_channel']['mcp']['ready'] == 0
    assert f['by_activity']['toerfiets']['exported'] == 1
    assert f['question_ids'] == {'kasseien': 1}
    assert f['km_buckets'] == {'25-50': 1, '<10': 1}
    assert f['actors']['returned_after_export'] == 1
    assert f['actors']['returned_after_export_ratio'] == 1.0
    assert summarize([])['funnel']['ready_ratio'] is None
    assert 'users_on_multiple_days' in summarize(_events())


def test_funnel_events_use_injected_sink_and_carry_no_content():
    seen = []
    funnel.sink = lambda event, **v: seen.append((event, v))
    try:
        plan = funnel.tracked_plan(lambda **kw: {'status': 'needs_input', 'vragen': [{'id': 'kasseien', 'vraag': 'Wil je Zottegem?'}, {'id': 'Bad Id!'}]})
        with funnel.channel('chat'):
            plan(start='Gent', activiteit='wandelen')
        ok = funnel.tracked_plan(lambda **kw: {'status': 'ready', 'km': 42.0})
        with funnel.channel('mcp'):
            ok(start='Gent', activiteit='toerfiets')
        adj = funnel.tracked_adjust(lambda *a, **kw: {'status': 'ready', 'km': 120})
        with funnel.channel('quick'):
            adj('d', vermijd_plaatsen=['Zottegem'])
            with funnel.adjust_kind('answers'):
                adj('d', doel='toeren')
        funnel.exported('fit', {'route_request': {'activiteit': 'toerfiets'}})
    finally:
        funnel.sink = None
    assert [e for e, _ in seen] == ['route_requested', 'route_ready', 'route_requested', 'route_ready',
                                    'route_adjusted', 'route_adjusted', 'route_ready', 'route_exported']
    assert seen[1][1]['question_ids'] == ['kasseien'] and seen[1][1]['needs_input'] is True
    assert seen[1][1]['channel'] == 'chat' and seen[3][1]['channel'] == 'mcp'
    assert seen[3][1]['km_bucket'] == '25-50'
    assert [v['kind'] for e, v in seen if e == 'route_adjusted'] == ['avoid', 'answers']
    assert seen[6][1]['km_bucket'] == '100+'
    assert seen[7][1] == {'format': 'fit', 'activity': 'toerfiets'}
    assert 'Zottegem' not in repr(seen) and 'Gent' not in repr(seen)


def test_funnel_events_pass_telemetry_allow_list():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    telemetry.logger.addHandler(handler)
    try:
        funnel.emit('route_ready', channel='mcp', activity='x', km_bucket='<10', needs_input=False,
                    question_ids=[], stage='plan', start='Gent', prompt='geheim')
    finally:
        telemetry.logger.removeHandler(handler)
    row = json.loads(stream.getvalue())
    assert row['channel'] == 'mcp' and row['km_bucket'] == '<10'
    assert 'start' not in row and 'prompt' not in row


def test_funnel_failures_never_break_routing():
    funnel.sink = lambda *a, **k: 1 / 0
    try:
        assert funnel.tracked_plan(lambda **kw: {'status': 'ready', 'km': 5})(activiteit='x')['km'] == 5
    finally:
        funnel.sink = None
